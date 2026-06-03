"""
sr_etd_builder.py — EtD（Evidence-to-Decision）フレームワーク生成

evidence_table.json + extracted.csv → EtD構造化メタデータ
"""

import argparse
import json
from pathlib import Path
from typing import Any, Dict, List, Optional

import pandas as pd


def build_etd_framework(
    evidence_table_json: str,
    extracted_csv: str,
    cq_name: str = "CQ",
    output_file: str = "./sr_output/etd_framework.json"
) -> Dict[str, Any]:
    """
    EtDフレームワークを構築
    """
    with open(evidence_table_json, "r", encoding="utf-8") as f:
        table_data = json.load(f)

    df = pd.read_csv(extracted_csv).fillna("")
    include_df = df[df.get("decision", "") == "Include"].reset_index(drop=True)

    # EtDフレームワークの基本構造
    etd = {
        "cq": cq_name,
        "pico": {
            "P": "（対象の説明）",  # 手動入力が必要
            "I": "（介入の説明）",
            "C": "（比較対照の説明）",
            "O": list(table_data.keys()),
        },
        "evidence_summary": {},
        "etd_judgments": {},
        "conclusions": {},
    }

    # 1. エビデンスサマリー
    for outcome, info in table_data.items():
        etd["evidence_summary"][outcome] = {
            "n_studies": info["n_studies"],
            "certainty_of_evidence": info["certainty_of_evidence"],
            "effect_direction": info["effect_direction"],
            "effect_size": info["effect_size_estimate"],
            "rob_summary": f"High {info['rob_high_count']}, Some concerns {info['rob_some_count']}",
        }

    # 2. EtD判定（各評価項目）
    rob_overall = include_df.get("rob_overall", []).tolist()
    rob_high_ratio = sum(1 for v in rob_overall if v and "high" in str(v).lower()) / len(rob_overall) if len(rob_overall) > 0 else 0

    # 益・害のバランス判定
    benefits_outcomes = [o for o, info in table_data.items() if "改善" in info.get("effect_direction", "")]
    harms_outcomes = [o for o, info in table_data.items() if "悪化" in info.get("effect_direction", "")]

    etd["etd_judgments"] = {
        "benefit_harm_balance": {
            "description": f"望ましい効果（{len(benefits_outcomes)}アウトカム）が望ましくない効果（{len(harms_outcomes)}アウトカム）を上回る",
            "benefits": benefits_outcomes,
            "harms": harms_outcomes,
            "judgement": "benefits exceed harms" if len(benefits_outcomes) > len(harms_outcomes) else "similar",
        },
        "values_preferences": {
            "description": "患者の価値観・嗜好性に関するデータは限定的",
            "certainty": "moderate uncertainty",
        },
        "resource_use": {
            "description": "データ不十分",
            "certainty": "insufficient data",
        },
        "equity": {
            "description": "公平性に関するデータは限定的",
            "certainty": "moderate uncertainty",
        },
        "acceptability": {
            "description": "受容性に関するデータは限定的",
            "certainty": "moderate uncertainty",
        },
        "feasibility": {
            "description": "実行可能性に関するデータは限定的",
            "certainty": "moderate uncertainty",
        },
    }

    # 3. 推奨決定（条件付き推奨の判定ロジック）
    certainties = [info["certainty_of_evidence"] for info in table_data.values()]
    certainty_order = {"Very Low": 0, "Low": 1, "Moderate": 2, "High": 3}
    min_certainty = min((certainty_order.get(c, 0) for c in certainties), default=0)

    if min_certainty >= certainty_order.get("Moderate", 0) and len(benefits_outcomes) > len(harms_outcomes):
        recommendation_strength = "Strong"
    else:
        recommendation_strength = "Weak"

    etd["conclusions"] = {
        "recommendation_direction": "For" if len(benefits_outcomes) > len(harms_outcomes) else "Against",
        "recommendation_strength": recommendation_strength,
        "rationale": f"最低確実性: {list(table_data.values())[0]['certainty_of_evidence']}, "
                     f"バイアスリスク: High {sum(1 for v in rob_overall if v and 'high' in str(v).lower())}/{len(rob_overall)}",
        "note": "手動確認が必要（LLMによる自動推定）",
    }

    # ファイルに保存
    output_path = Path(output_file)
    output_path.parent.mkdir(parents=True, exist_ok=True)

    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(etd, f, ensure_ascii=False, indent=2)

    print(f"✅ EtDフレームワーク生成: {output_path}")
    return etd


def generate_sof_table(
    etd: Dict[str, Any],
    output_file: str = "./sr_output/summary_of_findings.md"
) -> None:
    """
    Summary of Findings (SoF) テーブルを生成
    GRADE形式
    """
    output_path = Path(output_file)
    output_path.parent.mkdir(parents=True, exist_ok=True)

    with open(output_path, "w", encoding="utf-8") as f:
        f.write("# Summary of Findings - GRADE\n\n")
        f.write(f"**CQ:** {etd.get('cq', 'CQ')}\n\n")

        f.write("| アウトカム | 研究数 | 確実性 | 効果の方向 | バイアスリスク |\n")
        f.write("|---|---|---|---|---|\n")

        for outcome, summary in etd.get("evidence_summary", {}).items():
            f.write(
                f"| {outcome} "
                f"| {summary['n_studies']} "
                f"| {summary['certainty_of_evidence']} "
                f"| {summary['effect_direction']} "
                f"| {summary['rob_summary']} |\n"
            )

        f.write("\n## EtD判定のまとめ\n\n")
        judgments = etd.get("etd_judgments", {})
        f.write(f"- **益・害バランス**: {judgments.get('benefit_harm_balance', {}).get('description', '')}\n")
        f.write(f"- **患者の価値観**: {judgments.get('values_preferences', {}).get('description', '')}\n")
        f.write(f"- **資源利用**: {judgments.get('resource_use', {}).get('description', '')}\n")
        f.write(f"- **公平性**: {judgments.get('equity', {}).get('description', '')}\n")

        f.write("\n## 推奨\n\n")
        conclusions = etd.get("conclusions", {})
        f.write(f"- **推奨の方向**: {conclusions.get('recommendation_direction', '')}\n")
        f.write(f"- **推奨の強さ**: {conclusions.get('recommendation_strength', '')}\n")
        f.write(f"- **根拠**: {conclusions.get('rationale', '')}\n")

    print(f"✅ SoFテーブル生成: {output_path}")


def main():
    parser = argparse.ArgumentParser(description="EtDフレームワーク生成")
    parser.add_argument("--evidence-table", required=True, help="evidence_table.json")
    parser.add_argument("--extracted", required=True, help="extracted.csv")
    parser.add_argument("--cq", default="CQ", help="CQ名")
    parser.add_argument("--output-dir", default="./sr_output")
    args = parser.parse_args()

    etd = build_etd_framework(
        args.evidence_table,
        args.extracted,
        args.cq,
        f"{args.output_dir}/etd_framework.json"
    )

    generate_sof_table(etd, f"{args.output_dir}/summary_of_findings.md")

    print("\n[完了] EtDフレームワークとSoFテーブルを生成しました")


if __name__ == "__main__":
    main()
