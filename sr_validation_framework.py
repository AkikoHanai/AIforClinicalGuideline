"""
sr_validation_framework.py — SR 結果検証フレームワーク

8 つの検証指標でパイプラインの精度を評価：
  1. CQ 抽出: 100%
  2. PICO 抽出: P/I/C は 90%, O は 80%
  3. 推奨方向: 100%
  4. 推奨の強さ: 90%
  5. エビデンスの強さ: 90%
  6. 採用文献リスト: 90%
  7. EtD 主要項目: 80%
  8. 根拠なし記述: 5%未満
"""

import json
import re
from dataclasses import dataclass, asdict
from pathlib import Path
from typing import Any, Dict, List, Tuple, Optional
from datetime import datetime


@dataclass
class ValidationMetric:
    """検証メトリクス 1 つ"""
    metric_name: str  # e.g., "CQ 抽出"
    expected_value: Any  # 期待値
    actual_value: Any  # 実際の値
    pass_threshold: float  # 合格閾値（0.0-1.0）
    score: float  # スコア（0.0-1.0）
    passed: bool  # 合格判定
    details: str  # 詳細説明
    page_reference: Optional[str] = None  # 参照ページ


class ValidationFramework:
    """SR 結果検証フレームワーク"""

    def __init__(self):
        self.metrics: List[ValidationMetric] = []
        self.results: Dict[str, Any] = {}
        self.overall_score = 0.0

    def validate_cq_extraction(self, expected_cqs: List[str], extracted_cqs: List[str]) -> ValidationMetric:
        """1. CQ 抽出の検証（100% 合格）"""
        expected_set = set(cq.lower().strip() for cq in expected_cqs)
        extracted_set = set(cq.lower().strip() for cq in extracted_cqs)

        matches = expected_set & extracted_set
        score = len(matches) / len(expected_set) if expected_set else 0.0

        metric = ValidationMetric(
            metric_name="CQ 抽出",
            expected_value=expected_cqs,
            actual_value=extracted_cqs,
            pass_threshold=1.0,
            score=score,
            passed=score >= 1.0,
            details=f"期待: {len(expected_set)}個, 抽出: {len(extracted_set)}個, 一致: {len(matches)}個"
        )
        self.metrics.append(metric)
        return metric

    def validate_pico_extraction(
        self,
        expected_pico: Dict[str, str],
        extracted_pico: Dict[str, str]
    ) -> ValidationMetric:
        """2. PICO 抽出の検証（P/I/C: 90%, O: 80%）"""
        scores = {}
        thresholds = {"P": 0.9, "I": 0.9, "C": 0.9, "O": 0.8}

        for key in ["P", "I", "C", "O"]:
            expected = expected_pico.get(key, "").lower()
            actual = extracted_pico.get(key, "").lower()

            # 類似度を計算（簡易版：キーワード一致数）
            expected_words = set(expected.split())
            actual_words = set(actual.split())
            matches = expected_words & actual_words
            similarity = len(matches) / len(expected_words) if expected_words else 0.0

            scores[key] = {
                "similarity": similarity,
                "threshold": thresholds[key],
                "passed": similarity >= thresholds[key]
            }

        overall_score = sum(s["similarity"] for s in scores.values()) / len(scores)
        all_passed = all(s["passed"] for s in scores.values())

        metric = ValidationMetric(
            metric_name="PICO 抽出",
            expected_value=expected_pico,
            actual_value=extracted_pico,
            pass_threshold=0.9,
            score=overall_score,
            passed=all_passed,
            details=f"P: {scores['P']['similarity']:.1%}, I: {scores['I']['similarity']:.1%}, " +
                   f"C: {scores['C']['similarity']:.1%}, O: {scores['O']['similarity']:.1%}"
        )
        self.metrics.append(metric)
        return metric

    def validate_recommendation_direction(
        self,
        expected: str,  # "For" or "Against"
        actual: str
    ) -> ValidationMetric:
        """3. 推奨方向の検証（100% 合格）"""
        expected_normalized = expected.strip().lower()
        actual_normalized = actual.strip().lower()
        score = 1.0 if expected_normalized == actual_normalized else 0.0

        metric = ValidationMetric(
            metric_name="推奨方向",
            expected_value=expected,
            actual_value=actual,
            pass_threshold=1.0,
            score=score,
            passed=score == 1.0,
            details=f"期待: {expected}, 実際: {actual}"
        )
        self.metrics.append(metric)
        return metric

    def validate_recommendation_strength(
        self,
        expected: str,  # "Strong" or "Weak"
        actual: str
    ) -> ValidationMetric:
        """4. 推奨の強さの検証（90% 合格）"""
        strength_keywords = {
            "strong": ["強い", "strong", "should"],
            "weak": ["弱い", "weak", "may", "could"]
        }

        expected_category = self._categorize_strength(expected)
        actual_category = self._categorize_strength(actual)

        score = 1.0 if expected_category == actual_category else 0.5

        metric = ValidationMetric(
            metric_name="推奨の強さ",
            expected_value=expected,
            actual_value=actual,
            pass_threshold=0.9,
            score=score,
            passed=score >= 0.9,
            details=f"期待: {expected_category}, 実際: {actual_category}"
        )
        self.metrics.append(metric)
        return metric

    def validate_evidence_strength(
        self,
        expected_certainty: str,  # "High", "Moderate", "Low", "Very low"
        actual_certainty: str
    ) -> ValidationMetric:
        """5. エビデンスの強さの検証（90% 合格）"""
        certainty_hierarchy = {
            "high": 4,
            "moderate": 3,
            "low": 2,
            "very low": 1
        }

        expected_level = certainty_hierarchy.get(expected_certainty.lower(), 0)
        actual_level = certainty_hierarchy.get(actual_certainty.lower(), 0)

        # 差が 1 以内なら許容
        diff = abs(expected_level - actual_level)
        score = 1.0 if diff == 0 else (0.5 if diff == 1 else 0.0)

        metric = ValidationMetric(
            metric_name="エビデンスの強さ",
            expected_value=expected_certainty,
            actual_value=actual_certainty,
            pass_threshold=0.9,
            score=score,
            passed=score >= 0.9,
            details=f"期待: {expected_certainty}, 実際: {actual_certainty}, 差: {diff}"
        )
        self.metrics.append(metric)
        return metric

    def validate_citation_list(
        self,
        expected_pmids: List[str],
        extracted_pmids: List[str]
    ) -> ValidationMetric:
        """6. 採用文献リスト検証（PMID ベースで 90%）"""
        expected_set = set(str(pmid).strip() for pmid in expected_pmids)
        extracted_set = set(str(pmid).strip() for pmid in extracted_pmids)

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
                   f"一致: {len(matches)}, 一致率: {score:.1%}"
        )
        self.metrics.append(metric)
        return metric

    def validate_etd_key_items(
        self,
        expected_etd: Dict[str, Any],
        extracted_etd: Dict[str, Any]
    ) -> ValidationMetric:
        """7. EtD 主要項目検証（80% 合格）"""
        key_items = ["pico", "benefit_harm_balance", "values_preferences", "feasibility"]
        matched_items = 0

        for item in key_items:
            if item in extracted_etd and extracted_etd[item]:
                matched_items += 1

        score = matched_items / len(key_items) if key_items else 0.0

        metric = ValidationMetric(
            metric_name="EtD 主要項目",
            expected_value=key_items,
            actual_value=[k for k in key_items if k in extracted_etd and extracted_etd[k]],
            pass_threshold=0.8,
            score=score,
            passed=score >= 0.8,
            details=f"主要項目: {matched_items}/{len(key_items)} が入力済み"
        )
        self.metrics.append(metric)
        return metric

    def validate_unsupported_statements(
        self,
        text: str,
        max_percentage: float = 0.05
    ) -> ValidationMetric:
        """8. 根拠なし記述検証（5% 未満）"""
        # 根拠なし記述を検出（簡易版）
        unsupported_patterns = [
            r"と考えられる",
            r"思われる",
            r"可能性がある",
            r"estimated",
            r"reportedly",
        ]

        total_sentences = len(re.split(r"[。．!\n]", text))
        unsupported_sentences = 0

        for pattern in unsupported_patterns:
            unsupported_sentences += len(re.findall(pattern, text, re.IGNORECASE))

        score = 1.0 - (unsupported_sentences / total_sentences) if total_sentences > 0 else 1.0
        unsupported_percentage = unsupported_sentences / total_sentences if total_sentences > 0 else 0.0

        metric = ValidationMetric(
            metric_name="根拠なし記述",
            expected_value="5% 未満",
            actual_value=f"{unsupported_percentage:.1%}",
            pass_threshold=1.0 - max_percentage,
            score=score,
            passed=unsupported_percentage <= max_percentage,
            details=f"根拠なし文: {unsupported_sentences}/{total_sentences} " +
                   f"({unsupported_percentage:.1%})"
        )
        self.metrics.append(metric)
        return metric

    def _categorize_strength(self, text: str) -> str:
        """推奨の強さを分類"""
        text_lower = text.lower()
        if any(w in text_lower for w in ["強い", "strong", "should"]):
            return "Strong"
        elif any(w in text_lower for w in ["弱い", "weak", "may", "could"]):
            return "Weak"
        return "Unknown"

    def calculate_overall_score(self) -> float:
        """総合スコアを計算"""
        if not self.metrics:
            return 0.0

        # 加重平均（各検証指標に同じ重み）
        self.overall_score = sum(m.score for m in self.metrics) / len(self.metrics)
        return self.overall_score

    def generate_report(self, output_file: str = None) -> str:
        """検証レポートを生成"""
        self.calculate_overall_score()

        report = f"""# SR 結果検証レポート

**生成日時**: {datetime.now().isoformat()}
**総合スコア**: {self.overall_score:.1%}

---

## 検証結果（8 項目）

| # | 検証項目 | 期待値 | 実際の値 | 合格基準 | スコア | 合格判定 |
|---|---|---|---|---|---|---|
"""

        for i, metric in enumerate(self.metrics, 1):
            status = "✅ 合格" if metric.passed else "❌ 不合格"
            report += f"| {i} | {metric.metric_name} | {str(metric.expected_value)[:30]} | "
            report += f"{str(metric.actual_value)[:30]} | {metric.pass_threshold:.0%} | "
            report += f"{metric.score:.1%} | {status} |\n"

        report += f"""

---

## 詳細結果

"""

        for metric in self.metrics:
            status = "✅ **合格**" if metric.passed else "❌ **不合格**"
            report += f"""### {metric.metric_name}

- **期待値**: {metric.expected_value}
- **実際の値**: {metric.actual_value}
- **スコア**: {metric.score:.1%}
- **合格基準**: {metric.pass_threshold:.0%}
- **判定**: {status}
- **詳細**: {metric.details}

"""

        # 全体評価
        all_passed = all(m.passed for m in self.metrics)
        overall_status = "✅ **全て合格**" if all_passed else "⚠️ **一部不合格**"

        report += f"""---

## 総合評価

- **総合スコア**: {self.overall_score:.1%}
- **判定**: {overall_status}
- **合格项目**: {sum(1 for m in self.metrics if m.passed)}/{len(self.metrics)}

"""

        if output_file:
            Path(output_file).write_text(report, encoding="utf-8")
            print(f"✅ レポート: {output_file}")

        return report

    def to_json(self) -> Dict[str, Any]:
        """JSON フォーマットで出力"""
        return {
            "generated_at": datetime.now().isoformat(),
            "overall_score": self.overall_score,
            "total_metrics": len(self.metrics),
            "passed_metrics": sum(1 for m in self.metrics if m.passed),
            "metrics": [
                {
                    "name": m.metric_name,
                    "expected": str(m.expected_value),
                    "actual": str(m.actual_value),
                    "threshold": m.pass_threshold,
                    "score": m.score,
                    "passed": m.passed,
                    "details": m.details
                }
                for m in self.metrics
            ]
        }


def main():
    import argparse

    parser = argparse.ArgumentParser(description="SR 結果検証フレームワーク")
    parser.add_argument("--expected-json", help="期待値の JSON ファイル")
    parser.add_argument("--extracted-json", help="抽出結果の JSON ファイル")
    parser.add_argument("--output-dir", default="./sr_validation_output")
    args = parser.parse_args()

    # サンプル実行
    framework = ValidationFramework()

    # 1. CQ 抽出
    framework.validate_cq_extraction(
        ["CQ1: がんサバイバーへの運動介入は有効か？"],
        ["CQ 1: がんサバイバーへの運動介入は有効か？"]
    )

    # 2. PICO 抽出
    framework.validate_pico_extraction(
        {"P": "がんサバイバー", "I": "運動介入", "C": "運動なし", "O": "QoL"},
        {"P": "がんサバイバー", "I": "運動", "C": "対照", "O": "生活の質"}
    )

    # 3. 推奨方向
    framework.validate_recommendation_direction("For", "For")

    # 4. 推奨の強さ
    framework.validate_recommendation_strength("Strong", "強い推奨")

    # 5. エビデンスの強さ
    framework.validate_evidence_strength("Moderate", "Moderate")

    # 6. 採用文献
    framework.validate_citation_list(
        ["12345678", "87654321", "11111111"],
        ["12345678", "87654321"]
    )

    # 7. EtD 主要項目
    framework.validate_etd_key_items(
        {"pico": "P:...", "benefit_harm_balance": "..."},
        {"pico": "P:...", "benefit_harm_balance": "...", "values_preferences": ""}
    )

    # 8. 根拠なし記述
    framework.validate_unsupported_statements(
        "運動は有効と思われる。患者は QoL が改善された。"
    )

    # レポート生成
    output_dir = Path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    report = framework.generate_report(str(output_dir / "validation_report.md"))
    print(report)

    # JSON に保存
    json_file = output_dir / "validation_results.json"
    with open(json_file, "w", encoding="utf-8") as f:
        json.dump(framework.to_json(), f, ensure_ascii=False, indent=2)
    print(f"✅ {json_file}")


if __name__ == "__main__":
    main()
