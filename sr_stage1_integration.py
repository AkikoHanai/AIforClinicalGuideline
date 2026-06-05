"""
sr_stage1_integration.py — 段階 1: SoF + RoB2 統合出力

以下を統合：
  1. SoF テーブル（GRADE format）
  2. RoB2 評価シート（7 ドメイン）
  3. エビデンス総体サマリー
  4. 定性的 SR テーブル
"""

import json
import csv
from pathlib import Path
from typing import Any, Dict, List, Optional
from datetime import datetime
from dataclasses import dataclass, asdict


@dataclass
class StudyCharacteristics:
    """研究特性"""
    pmid: str
    doi: str
    author: str
    year: int
    title: str
    study_design: str  # RCT, Cohort, etc.
    n_participants: int
    intervention: str
    comparator: str
    country: str
    funding_source: str


@dataclass
class OutcomeData:
    """アウトカムデータ"""
    outcome_name: str
    n_studies: int
    effect_estimate: str  # SMD, RR, etc.
    confidence_interval: str
    certainty_of_evidence: str  # GRADE
    effect_direction: str  # Favors intervention, Favors control, No clear difference


class Stage1SRBuilder:
    """段階 1 SR 統合ビルダー"""

    def __init__(self, output_dir: str = "./sr_output/stage1"):
        self.output_dir = Path(output_dir)
        self.output_dir.mkdir(parents=True, exist_ok=True)

        self.studies: List[StudyCharacteristics] = []
        self.outcomes: List[OutcomeData] = []
        self.rob2_evaluations: Dict[str, Any] = {}

    def add_study(self, study: StudyCharacteristics) -> None:
        """研究を追加"""
        self.studies.append(study)

    def add_outcome(self, outcome: OutcomeData) -> None:
        """アウトカムを追加"""
        self.outcomes.append(outcome)

    def add_rob2_evaluation(self, pmid: str, evaluation: Dict[str, Any]) -> None:
        """RoB2 評価を追加"""
        self.rob2_evaluations[pmid] = evaluation

    def generate_study_characteristics_table(self) -> str:
        """研究特性テーブルを生成"""
        if not self.studies:
            return "研究がまだ追加されていません"

        table = """# 【付録 1】研究の特性

| # | PMID | 著者 | 年 | 対象者 | 介入 | 対照 | 研究設計 | 国 |
|---|---|---|---|---|---|---|---|---|
"""

        for i, study in enumerate(self.studies, 1):
            table += f"| {i} | {study.pmid} | {study.author} | {study.year} | " + \
                    f"{study.n_participants} | {study.intervention} | " + \
                    f"{study.comparator} | {study.study_design} | {study.country} |\n"

        return table

    def generate_rob2_summary_table(self) -> str:
        """RoB2 サマリーテーブルを生成"""
        if not self.rob2_evaluations:
            return "RoB2 評価がまだ追加されていません"

        table = """# 【付録 2】バイアスリスク評価（RoB 2）サマリー

| PMID | D1 | D2 | D3 | D4 | D5 | D6 | D7 | Overall |
|---|---|---|---|---|---|---|---|---|
"""

        for pmid, eval_data in self.rob2_evaluations.items():
            domains = eval_data.get("domains", [])
            domain_risks = [d.get("risk_level", "?") for d in domains]

            overall = eval_data.get("overall_risk", "?")

            # リスク短縮表記
            risk_short = {"Low": "L", "Some concerns": "S", "High": "H"}
            domain_short = [risk_short.get(r, "?") for r in domain_risks[:7]]

            table += f"| {pmid} | " + " | ".join(domain_short) + f" | {risk_short.get(overall, '?')} |\n"

        return table

    def generate_sof_table(self, cq: str = "CQ 1") -> str:
        """Summary of Findings テーブルを生成"""
        if not self.outcomes:
            return "アウトカムがまだ追加されていません"

        table = f"""# 【付録 3】Findings テーブル（{cq}）

## GRADE シンプル テーブル

| アウトカム | 研究数 | 効果推定値 | 確実性 | 効果の方向 |
|---|---|---|---|---|
"""

        for outcome in self.outcomes:
            # GRADE の確実性を視覚化
            grade_symbol = {
                "High": "⊕⊕⊕⊕",
                "Moderate": "⊕⊕⊕○",
                "Low": "⊕⊕○○",
                "Very low": "⊕○○○"
            }
            grade = grade_symbol.get(outcome.certainty_of_evidence, "?")

            direction = "↑" if "intervention" in outcome.effect_direction.lower() else \
                       "↓" if "control" in outcome.effect_direction.lower() else "→"

            table += f"| {outcome.outcome_name} | {outcome.n_studies} | " + \
                    f"{outcome.effect_estimate} {outcome.confidence_interval} | " + \
                    f"{grade} | {direction} |\n"

        return table

    def generate_evidence_profile(self, cq: str = "CQ 1") -> str:
        """詳細なエビデンス プロファイルを生成"""
        profile = f"""# {cq} エビデンス総体プロファイル

**生成日時**: {datetime.now().isoformat()}

---

## サマリー

- **総研究数**: {len(self.studies)}
- **対象者数**: {sum(s.n_participants for s in self.studies)}
- **アウトカム数**: {len(self.outcomes)}

---

## 研究の特性

{self.generate_study_characteristics_table()}

---

## バイアスリスク評価

{self.generate_rob2_summary_table()}

---

## 効果推定値

{self.generate_sof_table(cq)}

---

## メタ分析

メタアナリシスは実施されていません（定性的レビュー）

---

## 確実性の評価（GRADE）

| アウトカム | バイアス | 非一貫性 | 非直接性 | 不精密性 | その他 | 確実性 |
|---|---|---|---|---|---|---|
"""

        for outcome in self.outcomes:
            # 簡易的なGRADE評価
            issues = []
            if outcome.n_studies < 3:
                issues.append("研究数が少ない")
            if outcome.certainty_of_evidence in ["Low", "Very low"]:
                issues.append("確実性が低い")

            issue_str = ", ".join(issues) if issues else "なし"

            profile += f"| {outcome.outcome_name} | ? | ? | ? | ? | {issue_str} | " + \
                      f"{outcome.certainty_of_evidence} |\n"

        profile += """

---

## 定性的 SR

各アウトカムについて、含まれた研究のフィンディングスを定性的に要約しました。

"""

        return profile

    def generate_complete_sr_document(self, cq: str = "CQ 1") -> str:
        """完全な SR ドキュメントを生成"""
        doc = f"""# システマティックレビュー：完全版

**検索日**: {datetime.now().isoformat()}
**臨床疑問**: {cq}

---

## 目次

1. [背景](#背景)
2. [方法](#方法)
3. [結果](#結果)
4. [付録](#付録)

---

## 背景

本レビューは、{cq}に関するエビデンスを体系的に検索・評価したものです。

---

## 方法

### 検索戦略

複数のデータベース（PubMed, CENTRAL）を検索しました。

### 組み入れ基準

- 研究設計: RCT, cohort study
- 対象: 成人患者
- 介入: 指定された介入
- 比較: 通常のケアまたはプラセボ

### 除外基準

- 完全な報告書が入手不可
- 言語制限（英語または日本語）

---

## 結果

{self.generate_evidence_profile(cq)}

---

## 付録

{self.generate_study_characteristics_table()}

{self.generate_rob2_summary_table()}

{self.generate_sof_table(cq)}

---

**ドキュメント完成**: {datetime.now().isoformat()}
"""

        return doc

    def save_all_to_files(self, cq: str = "CQ 1") -> None:
        """全てのドキュメントをファイルに保存"""
        # マークダウン形式の完全な SR ドキュメント
        sr_doc = self.generate_complete_sr_document(cq)
        sr_file = self.output_dir / f"SR_Complete_{cq.replace(' ', '_')}.md"
        sr_file.write_text(sr_doc, encoding="utf-8")
        print(f"✅ SR ドキュメント: {sr_file}")

        # JSON 形式のメタデータ
        metadata = {
            "cq": cq,
            "generated_at": datetime.now().isoformat(),
            "study_count": len(self.studies),
            "outcome_count": len(self.outcomes),
            "studies": [asdict(s) for s in self.studies],
            "outcomes": [asdict(o) for o in self.outcomes],
            "rob2_evaluations": self.rob2_evaluations
        }
        meta_file = self.output_dir / f"SR_Metadata_{cq.replace(' ', '_')}.json"
        with open(meta_file, "w", encoding="utf-8") as f:
            json.dump(metadata, f, ensure_ascii=False, indent=2)
        print(f"✅ メタデータ: {meta_file}")

        # CSV 形式の研究特性テーブル
        if self.studies:
            csv_file = self.output_dir / f"Studies_{cq.replace(' ', '_')}.csv"
            with open(csv_file, "w", newline="", encoding="utf-8") as f:
                writer = csv.DictWriter(f, fieldnames=asdict(self.studies[0]).keys())
                writer.writeheader()
                for study in self.studies:
                    writer.writerow(asdict(study))
            print(f"✅ 研究特性 CSV: {csv_file}")


def main():
    """サンプル実行"""
    builder = Stage1SRBuilder()

    # サンプル研究を追加
    study1 = StudyCharacteristics(
        pmid="12345678",
        doi="10.1234/example1",
        author="Smith J",
        year=2020,
        title="Exercise intervention in cancer survivors",
        study_design="RCT",
        n_participants=120,
        intervention="12-week aerobic exercise",
        comparator="Usual care",
        country="USA",
        funding_source="NIH"
    )
    builder.add_study(study1)

    # サンプルアウトカムを追加
    outcome1 = OutcomeData(
        outcome_name="Quality of Life",
        n_studies=1,
        effect_estimate="SMD 0.45",
        confidence_interval="(0.10 to 0.80)",
        certainty_of_evidence="Moderate",
        effect_direction="Favors intervention"
    )
    builder.add_outcome(outcome1)

    # RoB2 評価を追加
    builder.add_rob2_evaluation("12345678", {
        "overall_risk": "Some concerns",
        "domains": [
            {"risk_level": "Low"},
            {"risk_level": "Low"},
            {"risk_level": "Some concerns"},
            {"risk_level": "Low"},
            {"risk_level": "Low"},
            {"risk_level": "Low"},
            {"risk_level": "Low"}
        ]
    })

    # ファイルに保存
    builder.save_all_to_files("CQ 1")

    # 完全なドキュメントを出力
    doc = builder.generate_complete_sr_document("CQ 1")
    print(doc)


if __name__ == "__main__":
    main()
