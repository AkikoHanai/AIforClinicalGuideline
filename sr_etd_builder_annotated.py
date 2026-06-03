"""
sr_etd_builder_annotated.py — EtDフレームワーク生成（確認タグ付き）

各判定項目に自動化度合いと確認タグを付与
"""

import json
from pathlib import Path
from typing import Any, Dict

import pandas as pd


def build_etd_framework_annotated(
    evidence_table_json: str,
    extracted_csv: str,
    cq_name: str = "CQ",
    output_file: str = "./sr_output/etd_framework_annotated.json"
) -> Dict[str, Any]:
    """
    EtDフレームワーク構築（確認タグ付き）
    """
    with open(evidence_table_json, "r", encoding="utf-8") as f:
        table_data = json.load(f)

    df = pd.read_csv(extracted_csv).fillna("")
    include_df = df[df.get("decision", "") == "Include"].reset_index(drop=True)

    etd = {
        "metadata": {
            "automation_level": 0.40,
            "confidence_score": 0.55,
            "description": "EtDフレームワーク（40%自動化、要手動入力）",
            "manual_input_required": [
                "❌ pico.P （対象の詳細定義）",
                "❌ pico.I （介入の詳細定義）",
                "❌ pico.C （比較対照の定義）",
                "🟡（要確認） etd_judgments.benefit_harm_balance （臨床的重要性の判定）",
                "❌ etd_judgments.values_preferences （患者データの補足）",
                "❌ etd_judgments.resource_use （医療経済データの補足）",
            ]
        },
        "cq": cq_name,
        "pico": {
            "P": {
                "value": "（対象の説明）",
                "automation_tag": "❌ 手動入力必須",
                "example": "18～64歳のがんが治癒・安定しているがんサバイバー（N=1,000人以上）",
                "why_manual": "詳細な定義は全文論文から必要。年齢、ステージ、治療歴等が重要"
            },
            "I": {
                "value": "（介入の説明）",
                "automation_tag": "❌ 手動入力必須",
                "example": "中強度以上の有酸素運動および/または筋力トレーニング（週3-5日、30-60分）",
                "why_manual": "介入の定義（有酸素/筋力/強度/頻度）はガイドラインの根幹"
            },
            "C": {
                "value": "（比較対照の説明）",
                "automation_tag": "❌ 手動入力必須",
                "example": "運動なし、または標準的ケアのみ",
                "why_manual": "対照群の定義により益害バランスが変わる"
            },
            "O": {
                "value": ["QoL", "筋力", "倦怠感", "うつ"],
                "automation_tag": "✅ 自動抽出",
                "why_auto": "evidence_table.json から自動取得"
            }
        },
        "evidence_summary": {},
        "etd_judgments": {},
        "conclusions": {}
    }

    # エビデンスサマリー
    outcomes_data = table_data.get("outcomes", {})
    for outcome, info in outcomes_data.items():
        etd["evidence_summary"][outcome] = {
            "n_studies": {
                "value": info.get("n_studies", {}).get("value", 0),
                "automation_tag": "✅"
            },
            "certainty_of_evidence": {
                "value": info.get("certainty_of_evidence", {}).get("value", "Unknown"),
                "automation_tag": "🟡（要確認）",
                "note": "LLM推定。形式的GRADE評価で確認が必須"
            },
            "effect_direction": {
                "value": info.get("effect_direction", {}).get("value", "Unknown"),
                "automation_tag": "🟡（要確認）",
                "note": "複数研究間の矛盾確認が必須"
            }
        }

    # EtD判定
    rob_overall = include_df.get("rob_overall", []).tolist()
    benefits = len([o for o in outcomes_data.keys() if "改善" in str(outcomes_data[o])])
    harms = len([o for o in outcomes_data.keys() if "悪化" in str(outcomes_data[o])])

    etd["etd_judgments"] = {
        "benefit_harm_balance": {
            "value": "benefits exceed harms" if benefits > harms else "similar",
            "automation_tag": "🟡（要確認）",
            "note": "数的判定のみ。『筋肉痛』と『死亡』の重みは異なる。臨床的重要性の判定が必須",
            "manual_required": True
        },
        "values_preferences": {
            "value": "患者の価値観・嗜好性に関するデータは限定的",
            "automation_tag": "❌ 手動補足必須",
            "note": "患者インタビュー、FGD等の一次データがあれば記載。なければ『不明』と記載"
        },
        "resource_use": {
            "value": "データ不十分",
            "automation_tag": "❌ 手動補足必須",
            "note": "医療経済評価の有無を確認。日本での実装コストを調査"
        },
        "equity": {
            "value": "公平性に関するデータは限定的",
            "automation_tag": "❌ 手動補足必須",
            "note": "社会経済的地位、性別、人種等による格差の有無を確認"
        },
        "acceptability": {
            "value": "受容性に関するデータは限定的",
            "automation_tag": "❌ 手動補足必須",
            "note": "患者・医療者の受容性に関するデータを補足"
        },
        "feasibility": {
            "value": "実行可能性に関するデータは限定的",
            "automation_tag": "❌ 手動補足必須",
            "note": "日本国内での施設、人員、機器の整備状況を確認"
        }
    }

    # 推奨結論
    etd["conclusions"] = {
        "recommendation_direction": {
            "value": "For" if benefits > harms else "Against",
            "automation_tag": "🟡（要確認）",
            "note": "LLM推定。最終決定はパネル会議で"
        },
        "recommendation_strength": {
            "value": "Weak" if len(include_df) < 10 or min([info.get("certainty_of_evidence", {}).get("value", "Low") for info in etd["evidence_summary"].values()]) == "Low" else "Strong",
            "automation_tag": "🟡（要確認）",
            "note": "LLM簡易推定。正式決定はパネル会議で投票"
        },
        "consensus": {
            "value": "（投票結果を記載してください）",
            "automation_tag": "❌ パネル会議で決定",
            "note": "例: 10名中9名が弱い推奨に投票（90%合意）"
        }
    }

    # 保存
    output_path = Path(output_file)
    output_path.parent.mkdir(parents=True, exist_ok=True)

    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(etd, f, ensure_ascii=False, indent=2)

    print(f"✅ {output_path}")

    # Markdown チェックリスト出力
    checklist_path = output_path.parent / "etd_checklist.md"
    with open(checklist_path, "w", encoding="utf-8") as f:
        f.write("# EtD確認チェックリスト\n\n")
        f.write(f"**自動化度合い**: 🟡 40% — 60%は手動入力が必須\n\n")

        f.write("## 【必須: 手動入力項目】\n\n")
        for item in etd["metadata"]["manual_input_required"]:
            status = "❌" if "❌" in item else "🟡"
            f.write(f"- [ ] {item}\n")

        f.write("\n## 【詳細確認項目】\n\n")

        f.write("### PICO定義（手動入力）\n")
        f.write("- [ ] **P（対象）**: \n")
        f.write(f"  疾患: {etd['pico']['P']['example']}\n")
        f.write("  → 記載内容を確認・修正してください\n")
        f.write("- [ ] **I（介入）**: \n")
        f.write(f"  具体的介入: {etd['pico']['I']['example']}\n")
        f.write("  → 記載内容を確認・修正してください\n")
        f.write("- [ ] **C（比較対照）**: \n")
        f.write(f"  {etd['pico']['C']['example']}\n")
        f.write("  → 記載内容を確認・修正してください\n")

        f.write("\n### 益・害評価（要確認）\n")
        f.write("- [ ] 益と害のバランス：臨床的に妥当か？\n")
        f.write("  - 「軽微」vs「重篤」の有害事象を区別したか？\n")
        f.write("  - 患者にとっての重要性は？\n")

        f.write("\n### 患者・社会的要因（手動補足）\n")
        f.write("- [ ] 患者の価値観データを補足\n")
        f.write("- [ ] 医療経済情報（コスト、保険適用等）\n")
        f.write("- [ ] 実装可能性（施設、人員、地域差）\n")

        f.write("\n### 推奨決定（パネル会議）\n")
        f.write("- [ ] 推奨の方向（For / Against）を決定\n")
        f.write("- [ ] 推奨の強さ（強い / 弱い）を投票\n")
        f.write("- [ ] 合意度（◎ / ○ / △ / ×）を記録\n")

    print(f"✅ {checklist_path}")

    return etd


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="EtDフレームワーク生成（確認タグ付き）")
    parser.add_argument("--evidence-table", required=True)
    parser.add_argument("--extracted", required=True)
    parser.add_argument("--cq", default="CQ 1")
    parser.add_argument("--output-dir", default="./sr_output")
    args = parser.parse_args()

    build_etd_framework_annotated(
        args.evidence_table,
        args.extracted,
        args.cq,
        f"{args.output_dir}/etd_framework_annotated.json"
    )
