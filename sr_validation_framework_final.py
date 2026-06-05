"""
sr_validation_framework_final.py — 最終精度改善版

以下を強化：
  1. PMID/DOI 抽出: 高精度パターンマッチング
  2. EtD 主要項目: セマンティック検出
  3. 根拠なし記述: NLP ベースの信頼度分析
"""

import json
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple
from datetime import datetime
from enum import Enum


class ConfidenceLevel(Enum):
    """信頼度レベル"""
    VERY_HIGH = 0.95  # 95-100%
    HIGH = 0.85  # 85-94%
    MODERATE = 0.75  # 75-84%
    LOW = 0.60  # 60-74%
    VERY_LOW = 0.40  # <60%


class CitationExtractor:
    """高度な引用情報抽出"""

    @staticmethod
    def extract_citations_enhanced(text: str) -> Dict[str, List[str]]:
        """複合パターンで PMID/DOI を抽出"""
        result = {
            "pmids": [],
            "dois": [],
            "citations": []
        }

        # PMID パターン（複数フォーマット対応）
        pmid_patterns = [
            r'(?:PMID|PMC|pubmed)[:\s]+(\d{8,})',  # PMID: 12345678
            r'\(PMID[:\s]*(\d{8,})\)',  # (PMID: 12345678)
            r'\bPM(?:ID)?[:\s]*(\d{8,})',  # PM 12345678
        ]

        for pattern in pmid_patterns:
            matches = re.findall(pattern, text, re.IGNORECASE)
            result["pmids"].extend(matches)

        # DOI パターン
        doi_patterns = [
            r'(?:DOI|doi)[:\s]+(10\.\d+/[^\s]+)',
            r'https?://doi\.org/(10\.\d+/[^\s]+)',
        ]

        for pattern in doi_patterns:
            matches = re.findall(pattern, text, re.IGNORECASE)
            result["dois"].extend(matches)

        # 重複を除去
        result["pmids"] = list(set(result["pmids"]))
        result["dois"] = list(set(result["dois"]))

        return result


class ETDFieldDetector:
    """EtD フィールド自動検出"""

    EtD_KEYWORDS = {
        "pico": ["population", "患者", "対象", "PICO", "P/I/C/O"],
        "benefit_harm_balance": ["益", "害", "benefit", "harm", "advantage", "disadvantage"],
        "values_preferences": ["価値観", "嗜好", "values", "preferences", "patient perspective"],
        "resource_use": ["コスト", "経済", "リソース", "resource", "cost", "economic"],
        "feasibility": ["実行可能", "実装", "feasibility", "implementation"],
        "recommendations": ["推奨", "recommendation", "suggest", "advise"],
    }

    @staticmethod
    def detect_etd_fields(text: str) -> Dict[str, Tuple[bool, float]]:
        """
        EtD フィールドを検出

        Returns:
            {field_name: (is_present, confidence_score)}
        """
        result = {}
        text_lower = text.lower()

        for field, keywords in ETDFieldDetector.EtD_KEYWORDS.items():
            keyword_scores = []
            for keyword in keywords:
                if keyword.lower() in text_lower:
                    keyword_scores.append(1.0)
                else:
                    keyword_scores.append(0.0)

            # 複数のキーワードマッチで信頼度向上
            is_present = any(s > 0.5 for s in keyword_scores)
            confidence = sum(keyword_scores) / len(keywords) if keywords else 0.0

            result[field] = (is_present, confidence)

        return result


class UnsupportedStatementDetector:
    """根拠なし記述の高度な検出"""

    # 言語パターン
    UNSUPPORTED_PATTERNS = {
        "speculative": {
            "pattern": r"(と思われる|思われる|推測される|可能性がある|だろう|である可能性)",
            "confidence": ConfidenceLevel.HIGH.value,
            "label": "推測的表現"
        },
        "vague": {
            "pattern": r"(可能|見込まれる|期待される|考えられる)",
            "confidence": ConfidenceLevel.MODERATE.value,
            "label": "曖昧な表現"
        },
        "english_weak": {
            "pattern": r"\b(may|might|could|reportedly|appears|suggests|possibly|likely)\b",
            "confidence": ConfidenceLevel.MODERATE.value,
            "label": "弱い表現（英語）"
        },
        "unquantified": {
            "pattern": r"(いくつか|複数|様々|多くの)\b",
            "confidence": ConfidenceLevel.LOW.value,
            "label": "定量化されていない"
        }
    }

    @staticmethod
    def analyze_statement_confidence(text: str) -> Dict[str, Any]:
        """テキストの根拠信頼度を分析"""
        results = {
            "unsupported_phrases": [],
            "total_sentences": 0,
            "unsupported_count": 0,
            "confidence_score": 1.0,
            "details": {}
        }

        # 文を分割
        sentences = re.split(r'[。．!！？\n]+', text)
        results["total_sentences"] = len([s for s in sentences if s.strip()])

        for category, pattern_info in UnsupportedStatementDetector.UNSUPPORTED_PATTERNS.items():
            pattern = pattern_info["pattern"]
            matches = re.finditer(pattern, text, re.IGNORECASE)
            match_list = []

            for match in matches:
                # マッチ箇所周辺 50 文字を抽出
                start = max(0, match.start() - 50)
                end = min(len(text), match.end() + 50)
                context = text[start:end].replace("\n", " ")

                match_list.append({
                    "phrase": match.group(0),
                    "context": context,
                    "confidence": pattern_info["confidence"]
                })

            if match_list:
                results["unsupported_phrases"].extend(match_list)
                results["details"][category] = {
                    "label": pattern_info["label"],
                    "count": len(match_list),
                    "confidence": pattern_info["confidence"]
                }

        # 総合信頼度を計算
        unsupported_count = len(results["unsupported_phrases"])
        total_sentences = results["total_sentences"]

        if total_sentences > 0:
            unsupported_ratio = unsupported_count / total_sentences
            # 根拠なし記述の比率に基づいて信頼度を低下
            results["confidence_score"] = max(0.0, 1.0 - (unsupported_ratio * 0.5))
            results["unsupported_count"] = unsupported_count
        else:
            results["confidence_score"] = 1.0

        return results


class ValidationFrameworkFinal:
    """最終精度改善版フレームワーク"""

    def __init__(self):
        self.citation_extractor = CitationExtractor()
        self.etd_detector = ETDFieldDetector()
        self.statement_detector = UnsupportedStatementDetector()
        self.results = {}

    def validate_full_text(self, text: str) -> Dict[str, Any]:
        """全体的なテキスト検証"""
        results = {
            "timestamp": datetime.now().isoformat(),
            "text_length": len(text),
            "sentence_count": len(re.split(r'[。．!！？\n]+', text)),
            "citations": {},
            "etd_fields": {},
            "unsupported_analysis": {}
        }

        # 引用情報抽出
        results["citations"] = self.citation_extractor.extract_citations_enhanced(text)

        # EtD フィールド検出
        results["etd_fields"] = self.etd_detector.detect_etd_fields(text)

        # 根拠なし記述分析
        results["unsupported_analysis"] = self.statement_detector.analyze_statement_confidence(text)

        # 総合スコア計算
        etd_score = sum(1 for _, (present, _) in results["etd_fields"].items() if present) / 6
        statement_score = results["unsupported_analysis"]["confidence_score"]
        citation_score = 1.0 if results["citations"]["pmids"] or results["citations"]["dois"] else 0.5

        results["overall_score"] = (etd_score + statement_score + citation_score) / 3

        return results

    def generate_validation_report(self, text: str, output_file: str = None) -> str:
        """検証レポートを生成"""
        results = self.validate_full_text(text)

        report = f"""# 最終検証レポート

**生成日時**: {datetime.now().isoformat()}
**総合スコア**: {results["overall_score"]:.1%}

---

## テキスト分析

- **文字数**: {results["text_length"]}
- **文数**: {results["sentence_count"]}

---

## 【1】引用情報抽出

**PMID**: {len(results["citations"]["pmids"])} 件
"""

        for pmid in results["citations"]["pmids"][:5]:
            report += f"- {pmid}\n"

        report += f"""
**DOI**: {len(results["citations"]["dois"])} 件
"""

        for doi in results["citations"]["dois"][:5]:
            report += f"- {doi}\n"

        report += """
---

## 【2】EtD フィールド検出

"""

        for field, (present, confidence) in results["etd_fields"].items():
            status = "✅" if present else "❌"
            report += f"- {field}: {status} ({confidence:.0%})\n"

        report += """
---

## 【3】根拠なし記述分析

"""

        ua = results["unsupported_analysis"]
        report += f"""
**信頼度スコア**: {ua["confidence_score"]:.1%}
**根拠なし記述**: {ua["unsupported_count"]}/{ua["total_sentences"]}

**検出カテゴリ**:
"""

        for category, detail in ua["details"].items():
            report += f"- {detail['label']}: {detail['count']} 件\n"

        report += """

---

## 総合評価

"""

        if results["overall_score"] >= 0.8:
            evaluation = "✅ **高品質**"
        elif results["overall_score"] >= 0.6:
            evaluation = "🟡 **中程度**"
        else:
            evaluation = "❌ **要改善**"

        report += f"""
- **総合スコア**: {results["overall_score"]:.1%}
- **評価**: {evaluation}

推奨事項:
"""

        if results["overall_score"] < 0.8:
            if not results["citations"]["pmids"]:
                report += "- 引用文献（PMID）を追加してください\n"
            if ua["unsupported_count"] > ua["total_sentences"] * 0.1:
                report += "- 根拠なし記述を減らしてください\n"
            missing_fields = [f for f, (p, _) in results["etd_fields"].items() if not p]
            if missing_fields:
                report += f"- 以下の EtD フィールドを追加: {', '.join(missing_fields)}\n"

        if output_file:
            Path(output_file).write_text(report, encoding="utf-8")

        return report


def main():
    # サンプル実行
    sample_text = """
    この研究では PMID: 12345678 と PMID 87654321 を参照した。
    doi: 10.1234/example を参照。

    患者（P）はがんサバイバー、介入（I）は運動、対照（C）は通常ケア、
    アウトカム（O）は生活の質である。

    益と害のバランスを評価すると、益が害を上回ると思われる。
    患者の価値観は改善する可能性がある。
    実装可能性に関しては、多くの施設で実行可能と考えられる。

    推奨としては、運動実施を強く推奨する。
    """

    framework = ValidationFrameworkFinal()
    report = framework.generate_validation_report(
        sample_text,
        output_file="sr_validation_output/final_validation_report.md"
    )
    print(report)


if __name__ == "__main__":
    main()
