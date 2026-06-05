"""
sr_rob2_extractor.py — RoB2 評価シート抽出（7 ドメイン完全版）

Risk of Bias 2 (RoB2) の 7 ドメインを PDF から抽出：
  1. Selection Bias (Sequence generation)
  2. Selection Bias (Allocation concealment)
  3. Performance Bias (Blinding of participants/personnel)
  4. Detection Bias (Blinding of outcome assessors)
  5. Attrition Bias (Incomplete outcome data)
  6. Reporting Bias (Selective outcome reporting)
  7. Other Bias
"""

import json
import re
from dataclasses import dataclass, asdict
from pathlib import Path
from typing import Any, Dict, List, Optional
from datetime import datetime


@dataclass
class ROB2DomainDetail:
    """RoB2 の 1 ドメイン詳細"""
    domain_number: int  # 1-7
    domain_name: str
    signaling_questions: List[str]  # Yes/No の質問
    risk_level: str  # "Low", "Some concerns", "High", "Not applicable"
    justification: str
    page_number: int


@dataclass
class ROB2EvaluationFull:
    """RoB2 完全評価（1 論文）"""
    pmid: str
    doi: str
    author: str
    year: int
    title: str
    domains: List[ROB2DomainDetail]
    overall_risk: str
    notes: Optional[str] = None


class ROB2Extractor:
    """RoB2 7 ドメイン抽出器"""

    # RoB2 ドメイン定義
    DOMAINS = {
        1: {
            "name": "Selection Bias - Bias due to randomization process",
            "keywords": ["randomisation", "random", "randomization", "sequence"],
        },
        2: {
            "name": "Selection Bias - Bias due to deviations from intended interventions",
            "keywords": ["allocation concealment", "hidden allocation"],
        },
        3: {
            "name": "Performance Bias - Bias due to deviations from intended interventions",
            "keywords": ["blinding", "blind", "double-blind", "masked"],
        },
        4: {
            "name": "Detection Bias - Bias due to measurement of the outcome",
            "keywords": ["outcome assessment", "assessor blind", "measurement bias"],
        },
        5: {
            "name": "Attrition Bias - Bias due to missing outcome data",
            "keywords": ["dropout", "missing data", "attrition", "incomplete", "lost to follow-up"],
        },
        6: {
            "name": "Reporting Bias - Bias due to selective outcome reporting",
            "keywords": ["selective reporting", "outcome switching", "primary outcome"],
        },
        7: {
            "name": "Other Bias",
            "keywords": ["other bias", "funding", "conflict of interest", "sponsorship"],
        },
    }

    def __init__(self):
        self.evaluations: List[ROB2EvaluationFull] = []

    def extract_from_text(
        self,
        text: str,
        page_number: int,
        pmid: str = "",
        doi: str = "",
        author: str = "",
        year: int = 0,
        title: str = ""
    ) -> Optional[ROB2EvaluationFull]:
        """
        テキストから RoB2 評価を抽出

        Args:
            text: 評価シートのテキスト
            page_number: ページ番号
            pmid: PMID
            doi: DOI
            author: 著者
            year: 発行年
            title: タイトル

        Returns:
            RoB2EvaluationFull または None
        """
        domains = []

        # 7 ドメインを順番に抽出
        for domain_num, domain_info in self.DOMAINS.items():
            domain_name = domain_info["name"]

            # ドメイン名を検索
            pattern = rf"{domain_name}.*?(?=Domain|Overall|$)"
            match = re.search(pattern, text, re.IGNORECASE | re.DOTALL)

            if match:
                domain_text = match.group(0)
            else:
                domain_text = text

            # リスク判定を抽出
            risk_level, justification = self._extract_risk_judgment(domain_text)

            # Signaling questions を抽出
            signaling_questions = self._extract_signaling_questions(domain_text)

            domain = ROB2DomainDetail(
                domain_number=domain_num,
                domain_name=domain_name,
                signaling_questions=signaling_questions,
                risk_level=risk_level,
                justification=justification,
                page_number=page_number,
            )
            domains.append(domain)

        # Overall risk を計算
        overall_risk = self._calculate_overall_risk(domains)

        evaluation = ROB2EvaluationFull(
            pmid=pmid,
            doi=doi,
            author=author,
            year=year,
            title=title,
            domains=domains,
            overall_risk=overall_risk,
        )

        self.evaluations.append(evaluation)
        return evaluation

    def _extract_risk_judgment(self, text: str) -> tuple:
        """リスク判定を抽出"""
        risk_pattern = r"(Low risk|Some concerns|High risk|Not applicable)"
        match = re.search(risk_pattern, text, re.IGNORECASE)

        if match:
            risk = match.group(1)
        else:
            # デフォルト
            risk = "Not applicable"

        # 根拠（最大 200 文字）
        justification = text[match.end() if match else 0:200].strip() if match else ""
        if not justification:
            justification = "詳細情報なし"

        return risk, justification

    def _extract_signaling_questions(self, text: str) -> List[str]:
        """Signaling questions を抽出"""
        # Yes/No の質問パターン
        questions = []

        # パターン: "Question X: ..."
        question_pattern = r"(?:Question|Q\d+)[:\s]+([^\n]+\?)"
        matches = re.findall(question_pattern, text, re.IGNORECASE)

        if matches:
            questions = matches[:5]  # 最大 5 つ
        else:
            # デフォルト質問を追加
            questions = ["詳細な質問情報は抽出できませんでした"]

        return questions

    def _calculate_overall_risk(self, domains: List[ROB2DomainDetail]) -> str:
        """Overall risk を計算"""
        high_count = sum(1 for d in domains if d.risk_level == "High risk")
        some_count = sum(1 for d in domains if d.risk_level == "Some concerns")

        if high_count > 0:
            return "High"
        elif some_count > 0:
            return "Some concerns"
        else:
            return "Low"

    def to_dict_list(self) -> List[Dict[str, Any]]:
        """JSON 形式に変換"""
        return [
            {
                "pmid": e.pmid,
                "doi": e.doi,
                "author": e.author,
                "year": e.year,
                "title": e.title,
                "domains": [asdict(d) for d in e.domains],
                "overall_risk": e.overall_risk,
            }
            for e in self.evaluations
        ]

    def save_to_json(self, output_file: str) -> None:
        """JSON ファイルに保存"""
        output_path = Path(output_file)
        output_path.parent.mkdir(parents=True, exist_ok=True)

        with open(output_path, "w", encoding="utf-8") as f:
            json.dump(self.to_dict_list(), f, ensure_ascii=False, indent=2)

        print(f"✅ RoB2 評価: {output_path}")

    def generate_report(self, output_file: str = None) -> str:
        """RoB2 評価レポートを生成"""
        report = f"""# RoB2 評価シート抽出レポート

**生成日時**: {datetime.now().isoformat()}
**抽出論文数**: {len(self.evaluations)}

---

## 抽出サマリー

| PMID | 著者 | 年 | Overall Risk |
|---|---|---|---|
"""

        for evaluation in self.evaluations:
            report += f"| {evaluation.pmid} | {evaluation.author} | {evaluation.year} | " + \
                     f"{evaluation.overall_risk} |\n"

        report += "\n---\n\n## 詳細結果\n\n"

        for evaluation in self.evaluations:
            report += f"""### PMID: {evaluation.pmid}

- **著者**: {evaluation.author}
- **年**: {evaluation.year}
- **タイトル**: {evaluation.title}
- **Overall Risk**: {evaluation.overall_risk}

#### ドメイン別リスク評価

"""
            for domain in evaluation.domains:
                report += f"""**Domain {domain.domain_number}: {domain.domain_name}**
- **リスク**: {domain.risk_level}
- **Signaling Questions**:
"""
                for i, q in enumerate(domain.signaling_questions, 1):
                    report += f"  {i}. {q}\n"
                report += f"- **根拠**: {domain.justification}\n\n"

        if output_file:
            Path(output_file).write_text(report, encoding="utf-8")
            print(f"✅ RoB2 レポート: {output_file}")

        return report


def main():
    import argparse

    parser = argparse.ArgumentParser(description="RoB2 評価シート抽出")
    parser.add_argument("--text", help="評価テキスト")
    parser.add_argument("--output-dir", default="./sr_output")
    args = parser.parse_args()

    extractor = ROB2Extractor()

    # サンプル実行
    sample_text = """
    Domain 1: Bias due to randomization process
    Risk of bias judgement: Low risk
    The trial used appropriate randomisation methods (computer-generated sequence).

    Domain 2: Bias due to allocation concealment
    Risk of bias judgement: Low risk
    Central allocation was used appropriately.

    Domain 3: Performance Bias
    Risk of bias judgement: Some concerns
    Double-blinding was attempted but details are unclear.

    Domain 4: Detection Bias
    Risk of bias judgement: Low risk
    Outcome assessors were blinded to treatment allocation.

    Domain 5: Attrition Bias
    Risk of bias judgement: High risk
    Dropout rate was 25% and reasons were not reported.

    Domain 6: Reporting Bias
    Risk of bias judgement: Some concerns
    Protocol registration not found.

    Domain 7: Other Bias
    Risk of bias judgement: Low risk
    No other potential sources of bias identified.
    """

    evaluation = extractor.extract_from_text(
        sample_text,
        page_number=50,
        pmid="12345678",
        author="Smith J",
        year=2020,
        title="Sample Study on Exercise"
    )

    # 保存
    output_dir = Path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    extractor.save_to_json(str(output_dir / "rob2_evaluations_full.json"))
    report = extractor.generate_report(str(output_dir / "rob2_report.md"))
    print(report)


if __name__ == "__main__":
    main()
