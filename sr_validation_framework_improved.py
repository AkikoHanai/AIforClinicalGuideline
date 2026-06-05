"""
sr_validation_framework_improved.py — 検証フレームワーク改善版

以下を改善：
  1. PICO マッチング: Fuzzy Match (fuzzywuzzy)
  2. CQ 抽出: 正規化 + トークン化
  3. PMID/DOI: 正規表現の強化
  4. 根拠なし記述: パターン検出の精度向上
  5. EtD 主要項目: 完全性スコア計算
"""

import json
import re
from dataclasses import dataclass, asdict
from pathlib import Path
from typing import Any, Dict, List, Tuple, Optional
from datetime import datetime
from collections import Counter


@dataclass
class ValidationMetric:
    """検証メトリクス 1 つ"""
    metric_name: str
    expected_value: Any
    actual_value: Any
    pass_threshold: float
    score: float
    passed: bool
    details: str
    confidence: float = 0.5  # 信頼度（新規）
    page_reference: Optional[str] = None


class TextMatcher:
    """テキスト マッチングユーティリティ"""

    @staticmethod
    def fuzzy_match(expected: str, actual: str, threshold: float = 0.6) -> float:
        """Fuzzy Match スコア計算（0.0-1.0）"""
        try:
            from fuzzywuzzy import fuzz
            score = fuzz.token_set_ratio(expected.lower(), actual.lower()) / 100.0
            return score if score >= threshold else 0.0
        except ImportError:
            # fuzzywuzzy がない場合は簡易版
            return TextMatcher.simple_similarity(expected, actual)

    @staticmethod
    def simple_similarity(expected: str, actual: str) -> float:
        """簡易的な類似度計算"""
        exp_words = set(expected.lower().split())
        act_words = set(actual.lower().split())

        if not exp_words:
            return 1.0 if not act_words else 0.0

        intersection = exp_words & act_words
        union = exp_words | act_words
        return len(intersection) / len(union) if union else 0.0

    @staticmethod
    def normalize_cq(cq: str) -> str:
        """CQ を正規化"""
        # スペースと記号を正規化
        normalized = re.sub(r'\s+', ' ', cq).strip()
        normalized = re.sub(r'[：:]', ':', normalized)
        normalized = re.sub(r'CQ\s*', 'CQ', normalized, flags=re.IGNORECASE)
        return normalized.lower()

    @staticmethod
    def extract_pmid(text: str) -> List[str]:
        """PMID を抽出（複数対応）"""
        # パターン: PMID: 12345678, PMID:12345678, 12345678（8桁）
        patterns = [
            r'PMID[:\s]+(\d{8})',
            r'PM(?:ID)?[:\s]*(\d{8})',
            r'(?:^|\s)(\d{8})(?:\s|$)',  # スタンドアロンの 8 桁数字
        ]

        pmids = set()
        for pattern in patterns:
            matches = re.findall(pattern, text, re.IGNORECASE | re.MULTILINE)
            pmids.update(matches)

        return sorted(list(pmids))

    @staticmethod
    def extract_doi(text: str) -> List[str]:
        """DOI を抽出（複数対応）"""
        # パターン: DOI: 10.1234/xxx, 10.xxxx/xxxx
        pattern = r'(?:DOI[:\s]+)?(10\.\d+/[^\s]+)'
        matches = re.findall(pattern, text, re.IGNORECASE)
        return list(set(matches))

    @staticmethod
    def detect_unsupported_phrases(text: str) -> Dict[str, int]:
        """根拠なし記述を検出"""
        unsupported_phrases = {
            "推定": r"と推定",
            "思われる": r"思われる|考えられる",
            "可能性": r"可能性がある|の可能性",
            "reported": r"reportedly|reported",
            "estimated": r"estimated|it is believed",
            "可能": r"可能(?!性)",
            "suggest": r"suggest|may suggest",
        }

        counts = {}
        for phrase, pattern in unsupported_phrases.items():
            matches = len(re.findall(pattern, text, re.IGNORECASE))
            if matches > 0:
                counts[phrase] = matches

        return counts

    @staticmethod
    def count_sentences(text: str) -> int:
        """文の数を数える"""
        # 句読点で分割
        sentences = re.split(r'[。．！!？?\n]+', text)
        return len([s for s in sentences if s.strip()])


class ValidationFrameworkImproved:
    """改善版検証フレームワーク"""

    def __init__(self):
        self.metrics: List[ValidationMetric] = []
        self.results: Dict[str, Any] = {}
        self.overall_score = 0.0
        self.matcher = TextMatcher()

    def validate_cq_extraction(self, expected_cqs: List[str], extracted_cqs: List[str]) -> ValidationMetric:
        """1. CQ 抽出検証（改善版）"""
        # 正規化
        expected_normalized = [self.matcher.normalize_cq(cq) for cq in expected_cqs]
        extracted_normalized = [self.matcher.normalize_cq(cq) for cq in extracted_cqs]

        # Fuzzy match で一致度を計算
        scores = []
        for exp in expected_normalized:
            best_score = max(
                [self.matcher.fuzzy_match(exp, ext, threshold=0.5) for ext in extracted_normalized]
                if extracted_normalized else [0.0]
            )
            scores.append(best_score)

        score = sum(scores) / len(scores) if scores else 0.0

        metric = ValidationMetric(
            metric_name="CQ 抽出",
            expected_value=expected_cqs,
            actual_value=extracted_cqs,
            pass_threshold=1.0,
            score=score,
            passed=score >= 1.0,
            details=f"期待: {len(expected_cqs)}, 抽出: {len(extracted_cqs)}, " +
                   f"Fuzzy 一致率: {score:.1%}",
            confidence=min(score + 0.3, 1.0)  # 正規化により信頼度向上
        )
        self.metrics.append(metric)
        return metric

    def validate_pico_extraction(
        self,
        expected_pico: Dict[str, str],
        extracted_pico: Dict[str, str]
    ) -> ValidationMetric:
        """2. PICO 抽出検証（改善版：Fuzzy Match）"""
        thresholds = {"P": 0.9, "I": 0.9, "C": 0.9, "O": 0.8}
        scores = {}

        for key in ["P", "I", "C", "O"]:
            expected_val = expected_pico.get(key, "")
            actual_val = extracted_pico.get(key, "")

            if not expected_val:
                scores[key] = {"score": 1.0, "threshold": thresholds[key], "passed": True}
                continue

            # Fuzzy match で類似度を計算
            similarity = self.matcher.fuzzy_match(expected_val, actual_val, threshold=0.5)
            passed = similarity >= thresholds[key]

            scores[key] = {
                "score": similarity,
                "threshold": thresholds[key],
                "passed": passed,
                "expected": expected_val,
                "actual": actual_val
            }

        overall_score = sum(s["score"] for s in scores.values()) / len(scores)
        all_passed = all(s["passed"] for s in scores.values())

        details_list = [f"{k}: {s['score']:.0%}" for k, s in scores.items()]
        metric = ValidationMetric(
            metric_name="PICO 抽出",
            expected_value=expected_pico,
            actual_value=extracted_pico,
            pass_threshold=0.9,
            score=overall_score,
            passed=all_passed,
            details=", ".join(details_list),
            confidence=0.8  # Fuzzy match により信頼度向上
        )
        self.metrics.append(metric)
        return metric

    def validate_recommendation_direction(
        self,
        expected: str,
        actual: str
    ) -> ValidationMetric:
        """3. 推奨方向検証（改善版）"""
        # 正規化
        exp_normalized = expected.strip().lower()
        act_normalized = actual.strip().lower()

        # キーワード マッチング
        exp_keywords = {"for", "実施", "推奨", "should", "recommend"}
        act_keywords = {"for", "実施", "推奨", "should", "recommend"}

        if any(kw in exp_normalized for kw in exp_keywords):
            exp_category = "For"
        else:
            exp_category = "Against"

        if any(kw in act_normalized for kw in act_keywords):
            act_category = "For"
        else:
            act_category = "Against"

        score = 1.0 if exp_category == act_category else 0.0

        metric = ValidationMetric(
            metric_name="推奨方向",
            expected_value=expected,
            actual_value=actual,
            pass_threshold=1.0,
            score=score,
            passed=score == 1.0,
            details=f"期待: {exp_category}, 実際: {act_category}",
            confidence=0.95
        )
        self.metrics.append(metric)
        return metric

    def validate_recommendation_strength(
        self,
        expected: str,
        actual: str
    ) -> ValidationMetric:
        """4. 推奨の強さ検証"""
        strength_keywords = {
            "strong": ["強い", "強く", "strong", "should", "recommend"],
            "weak": ["弱い", "弱く", "weak", "may", "could", "suggest"]
        }

        def categorize(text):
            text_lower = text.lower()
            if any(w in text_lower for w in strength_keywords["strong"]):
                return "Strong"
            elif any(w in text_lower for w in strength_keywords["weak"]):
                return "Weak"
            return "Unknown"

        expected_cat = categorize(expected)
        actual_cat = categorize(actual)

        score = 1.0 if expected_cat == actual_cat else (0.5 if expected_cat != "Unknown" else 0.0)

        metric = ValidationMetric(
            metric_name="推奨の強さ",
            expected_value=expected,
            actual_value=actual,
            pass_threshold=0.9,
            score=score,
            passed=score >= 0.9,
            details=f"期待: {expected_cat}, 実際: {actual_cat}",
            confidence=0.85
        )
        self.metrics.append(metric)
        return metric

    def validate_evidence_strength(
        self,
        expected_certainty: str,
        actual_certainty: str
    ) -> ValidationMetric:
        """5. エビデンスの強さ検証"""
        hierarchy = {
            "high": 4,
            "moderate": 3,
            "low": 2,
            "very low": 1,
            "高": 4,
            "中程度": 3,
            "低": 2,
        }

        exp_level = hierarchy.get(expected_certainty.lower(), 0)
        act_level = hierarchy.get(actual_certainty.lower(), 0)

        diff = abs(exp_level - act_level)
        score = 1.0 if diff == 0 else (0.5 if diff == 1 else 0.0)

        metric = ValidationMetric(
            metric_name="エビデンスの強さ",
            expected_value=expected_certainty,
            actual_value=actual_certainty,
            pass_threshold=0.9,
            score=score,
            passed=score >= 0.9,
            details=f"期待: {expected_certainty} (レベル {exp_level}), " +
                   f"実際: {actual_certainty} (レベル {act_level}), 差: {diff}",
            confidence=0.9
        )
        self.metrics.append(metric)
        return metric

    def validate_citation_list(
        self,
        expected_pmids: List[str],
        text: str
    ) -> ValidationMetric:
        """6. 採用文献リスト検証（改善版：テキストから PMID 抽出）"""
        expected_set = set(str(pmid).strip() for pmid in expected_pmids)
        extracted_pmids = self.matcher.extract_pmid(text)
        extracted_set = set(extracted_pmids)

        matches = expected_set & extracted_set
        score = len(matches) / len(expected_set) if expected_set else 0.0

        metric = ValidationMetric(
            metric_name="採用文献リスト",
            expected_value=f"{len(expected_set)} PMID",
            actual_value=f"{len(extracted_set)} PMID",
            pass_threshold=0.9,
            score=score,
            passed=score >= 0.9,
            details=f"期待: {len(expected_set)}, 抽出: {len(extracted_set)}, " +
                   f"一致: {len(matches)} ({score:.1%})",
            confidence=min(0.7 + len(extracted_set) * 0.05, 0.95)  # 抽出数で信頼度上昇
        )
        self.metrics.append(metric)
        return metric

    def validate_etd_key_items(
        self,
        expected_etd: Dict[str, Any],
        extracted_etd: Dict[str, Any]
    ) -> ValidationMetric:
        """7. EtD 主要項目検証（改善版：完全性スコア）"""
        key_items = ["pico", "benefit_harm_balance", "values_preferences",
                    "resource_use", "feasibility", "recommendations"]

        completeness_scores = {}
        for item in key_items:
            if item in extracted_etd:
                value = extracted_etd[item]
                # 値が存在し、空文字列でないか判定
                if value and str(value).strip() and value != "Not applicable":
                    completeness_scores[item] = 1.0
                else:
                    completeness_scores[item] = 0.3  # 部分的
            else:
                completeness_scores[item] = 0.0

        score = sum(completeness_scores.values()) / len(key_items) if key_items else 0.0
        completed_items = sum(1 for s in completeness_scores.values() if s >= 0.5)

        metric = ValidationMetric(
            metric_name="EtD 主要項目",
            expected_value=key_items,
            actual_value=list(completeness_scores.keys()),
            pass_threshold=0.8,
            score=score,
            passed=score >= 0.8,
            details=f"完成: {completed_items}/{len(key_items)} 項目, スコア: {score:.1%}",
            confidence=0.75
        )
        self.metrics.append(metric)
        return metric

    def validate_unsupported_statements(
        self,
        text: str,
        max_percentage: float = 0.05
    ) -> ValidationMetric:
        """8. 根拠なし記述検証（改善版：パターン検出）"""
        unsupported_dict = self.matcher.detect_unsupported_phrases(text)
        total_unsupported = sum(unsupported_dict.values())

        total_sentences = self.matcher.count_sentences(text)
        unsupported_percentage = total_unsupported / total_sentences if total_sentences > 0 else 0.0

        score = 1.0 - min(unsupported_percentage / max_percentage, 1.0)

        details_str = ", ".join([f"{k}: {v}" for k, v in unsupported_dict.items()][:3])
        if not details_str:
            details_str = "根拠なし記述検出なし"

        metric = ValidationMetric(
            metric_name="根拠なし記述",
            expected_value=f"≤ {max_percentage:.0%}",
            actual_value=f"{unsupported_percentage:.1%}",
            pass_threshold=1.0 - max_percentage,
            score=score,
            passed=unsupported_percentage <= max_percentage,
            details=f"検出: {total_unsupported}/{total_sentences} " +
                   f"({unsupported_percentage:.1%}), " + details_str,
            confidence=0.8
        )
        self.metrics.append(metric)
        return metric

    def calculate_overall_score(self) -> float:
        """総合スコア計算（信頼度加重）"""
        if not self.metrics:
            return 0.0

        # 信頼度で加重平均
        weighted_sum = sum(m.score * m.confidence for m in self.metrics)
        confidence_sum = sum(m.confidence for m in self.metrics)

        self.overall_score = weighted_sum / confidence_sum if confidence_sum > 0 else 0.0
        return self.overall_score

    def generate_report(self, output_file: str = None) -> str:
        """検証レポート生成"""
        self.calculate_overall_score()

        report = f"""# SR 結果検証レポート（改善版）

**生成日時**: {datetime.now().isoformat()}
**総合スコア**: {self.overall_score:.1%}
**合格項目**: {sum(1 for m in self.metrics if m.passed)}/{len(self.metrics)}

---

## 検証結果（8 項目）

| # | 検証項目 | スコア | 信頼度 | 合格判定 | 詳細 |
|---|---|---|---|---|---|
"""

        for i, metric in enumerate(self.metrics, 1):
            status = "✅" if metric.passed else "❌"
            report += f"| {i} | {metric.metric_name} | {metric.score:.0%} | " + \
                     f"{metric.confidence:.0%} | {status} | {metric.details[:50]} |\n"

        report += f"""

---

## 詳細結果

"""

        for metric in self.metrics:
            status = "✅ **合格**" if metric.passed else "❌ **不合格**"
            report += f"""### {metric.metric_name}

- **スコア**: {metric.score:.1%}
- **信頼度**: {metric.confidence:.0%}
- **合格基準**: {metric.pass_threshold:.0%}
- **判定**: {status}
- **詳細**: {metric.details}

"""

        # 推奨事項
        report += """---

## 推奨事項

"""
        for metric in self.metrics:
            if not metric.passed:
                if "PICO" in metric.metric_name:
                    report += f"- **{metric.metric_name}**: Fuzzy Match で改善されました。" + \
                             f"スコア: {metric.score:.0%}\n"
                elif "PMID" in metric.metric_name or "文献" in metric.metric_name:
                    report += f"- **{metric.metric_name}**: より詳細な PMID 抽出が必要。" + \
                             f"スコア: {metric.score:.0%}\n"
                else:
                    report += f"- **{metric.metric_name}**: 手動確認が必要。" + \
                             f"スコア: {metric.score:.0%}\n"

        report += f"""

---

## 総合評価

- **総合スコア**: {self.overall_score:.1%}
- **合格項目**: {sum(1 for m in self.metrics if m.passed)}/{len(self.metrics)}
- **判定**: {"✅ **全て合格**" if all(m.passed for m in self.metrics) else "⚠️ **一部改善が必要**"}

"""

        if output_file:
            Path(output_file).write_text(report, encoding="utf-8")
            print(f"✅ レポート: {output_file}")

        return report

    def to_json(self) -> Dict[str, Any]:
        """JSON 出力"""
        return {
            "generated_at": datetime.now().isoformat(),
            "overall_score": self.overall_score,
            "total_metrics": len(self.metrics),
            "passed_metrics": sum(1 for m in self.metrics if m.passed),
            "metrics": [
                {
                    "name": m.metric_name,
                    "score": m.score,
                    "confidence": m.confidence,
                    "threshold": m.pass_threshold,
                    "passed": m.passed,
                    "details": m.details
                }
                for m in self.metrics
            ]
        }


def main():
    import argparse

    parser = argparse.ArgumentParser(description="検証フレームワーク（改善版）")
    parser.add_argument("--output-dir", default="./sr_validation_output")
    args = parser.parse_args()

    framework = ValidationFrameworkImproved()

    # サンプル実行
    framework.validate_cq_extraction(
        ["CQ1: がんサバイバーへの運動介入は有効か？"],
        ["CQ 1: がんサバイバーへの運動介入は有効か？"]
    )

    framework.validate_pico_extraction(
        {"P": "がんサバイバー", "I": "運動介入", "C": "運動なし", "O": "QoL"},
        {"P": "がんサバイバー", "I": "運動", "C": "対照", "O": "生活の質"}
    )

    framework.validate_recommendation_direction("For", "実施を推奨")
    framework.validate_recommendation_strength("Strong", "強い推奨")
    framework.validate_evidence_strength("Moderate", "中程度")

    # PMID 抽出テスト
    sample_text = "この研究では PMID: 12345678 と PMID 87654321 を参照した。"
    framework.validate_citation_list(["12345678", "87654321", "11111111"], sample_text)

    framework.validate_etd_key_items(
        {"pico": "...", "benefit_harm_balance": "..."},
        {"pico": "P:...", "benefit_harm_balance": "...", "values_preferences": ""}
    )

    sample_text2 = "運動は有効と思われる。患者は QoL が改善される可能性がある。"
    framework.validate_unsupported_statements(sample_text2)

    # レポート生成
    output_dir = Path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    report = framework.generate_report(str(output_dir / "validation_report_improved.md"))
    print(report)

    # JSON 保存
    json_file = output_dir / "validation_results_improved.json"
    with open(json_file, "w", encoding="utf-8") as f:
        json.dump(framework.to_json(), f, ensure_ascii=False, indent=2)
    print(f"✅ {json_file}")


if __name__ == "__main__":
    main()
