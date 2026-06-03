"""
sr_evidence_table.py — 定性的SRエビデンス総体テーブル生成

extracted.csv → 複数アウトカムの統計的サマリー生成
（SMD/RRは元論文から推定）
"""

import argparse
import json
from pathlib import Path
from typing import Any, Dict, List, Optional

import pandas as pd


GRADE_CERTAINTY = {
    "High": "⊕⊕⊕⊕",
    "Moderate": "⊕⊕⊕◯",
    "Low": "⊕⊕◯◯",
    "Very Low": "⊕◯◯◯",
}


def infer_grade_certainty(rob_values: List[str]) -> str:
    """RoB結果からGRADE確実性を簡易推定"""
    if not rob_values:
        return "Very Low"

    rob_counts = {
        "low": sum(1 for v in rob_values if v and "low" in str(v).lower()),
        "some": sum(1 for v in rob_values if v and "some" in str(v).lower() or "concern" in str(v).lower()),
        "high": sum(1 for v in rob_values if v and "high" in str(v).lower()),
    }
    n = len(rob_values)

    high_ratio = rob_counts["high"] / n if n > 0 else 0
    if high_ratio > 0.5:
        return "Very Low"
    if high_ratio > 0.2 or rob_counts["some"] / n > 0.5:
        return "Low"
    if rob_counts["some"] / n > 0.2:
        return "Moderate"
    return "High"


def extract_effect_sizes(df: pd.DataFrame, outcome: str) -> Dict[str, Any]:
    """
    アウトカムから効果量情報を抽出
    （自然言語から数値を推定）
    """
    effects = {
        "count": 0,
        "direction": [],  # 改善/悪化/不変
        "effect_size_estimates": [],  # 推定量
        "events": [],  # イベント数
    }

    for idx, row in df.iterrows():
        outcomes_text = str(row.get("outcomes", ""))

        # キーワードから方向性を判定
        if any(word in outcomes_text for word in ["改善", "上昇", "増加", "向上", "有意に"]):
            effects["direction"].append("改善")
        elif any(word in outcomes_text for word in ["悪化", "低下", "減少", "有害"]):
            effects["direction"].append("悪化")
        else:
            effects["direction"].append("不変")

        effects["count"] += 1

    effects["summary_direction"] = effects["direction"][0] if effects["direction"] else "不明"
    return effects


def generate_evidence_table(
    extracted_csv: str,
    outcomes: Optional[str] = None,
    output_dir: str = "./sr_output"
) -> Dict[str, Any]:
    """
    エビデンス総体テーブルを生成
    outputs:
    - evidence_table.json (構造化)
    - evidence_table.md (Markdown表)
    """
    df = pd.read_csv(extracted_csv).fillna("")
    include_df = df[df.get("decision", "") == "Include"].reset_index(drop=True)

    if include_df.empty:
        print("[警告] Include件数が0件のため、テーブル生成をスキップ")
        return {}

    print(f"[テーブル生成] Include論文数: {len(include_df)}件")

    # アウトカムのリストを設定
    if outcomes:
        outcome_list = [o.strip() for o in outcomes.split(",") if o.strip()]
    else:
        # extracted.csvから自動抽出
        outcome_list = [
            "持久性体力",
            "筋力",
            "健康関連QoL",
            "倦怠感",
            "うつ",
            "運動関連有害事象",
        ]

    table_data = {}

    for outcome in outcome_list:
        effect_info = extract_effect_sizes(include_df, outcome)

        # バイアスリスク情報を集計
        rob_overall = include_df.get("rob_overall", []).tolist()
        grade = infer_grade_certainty(rob_overall)

        table_data[outcome] = {
            "outcome": outcome,
            "n_studies": len(include_df),
            "n_participants": "不明",  # 抄録からは取得困難
            "effect_direction": effect_info.get("summary_direction", "不明"),
            "effect_size_estimate": "(推定量)",
            "certainty_of_evidence": grade,
            "certainty_symbol": GRADE_CERTAINTY.get(grade, "?"),
            "rob_high_count": sum(1 for v in rob_overall if v and "high" in str(v).lower()),
            "rob_some_count": sum(1 for v in rob_overall if v and "some" in str(v).lower()),
        }

    # JSON出力
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    json_path = output_dir / "evidence_table.json"
    with open(json_path, "w", encoding="utf-8") as f:
        json.dump(table_data, f, ensure_ascii=False, indent=2)
    print(f"✅ {json_path}")

    # Markdown表出力
    md_path = output_dir / "evidence_table.md"
    with open(md_path, "w", encoding="utf-8") as f:
        f.write("# エビデンス総体テーブル（定性的システマティックレビュー）\n\n")
        f.write(f"Include論文数: **{len(include_df)}件**\n\n")

        f.write("| アウトカム | 研究数 | 効果の方向 | 効果量（推定） | エビデンスの確実性 | RoB（High/Some） |\n")
        f.write("|---|---|---|---|---|---|\n")

        for outcome, info in table_data.items():
            f.write(
                f"| {outcome} "
                f"| {info['n_studies']} "
                f"| {info['effect_direction']} "
                f"| {info['effect_size_estimate']} "
                f"| {info['certainty_symbol']} {info['certainty_of_evidence']} "
                f"| {info['rob_high_count']}/{info['rob_some_count']} |\n"
            )

        f.write("\n## 凡例\n")
        f.write("- 効果量：抄録から推定した定性的評価（メタアナリシスではなく定性的集約）\n")
        f.write("- エビデンスの確実性：GRADE方法に基づく推定\n")
        f.write(f"  - ⊕⊕⊕⊕ High（非常に強い証拠）\n")
        f.write(f"  - ⊕⊕⊕◯ Moderate（中程度の証拠）\n")
        f.write(f"  - ⊕⊕◯◯ Low（弱い証拠）\n")
        f.write(f"  - ⊕◯◯◯ Very Low（非常に弱い証拠）\n")
        f.write("- RoB：バイアスリスク判定（High件数/Some concerns件数）\n")

    print(f"✅ {md_path}")

    return table_data


def generate_etd_chunks(
    table_data: Dict[str, Any],
    extracted_csv: str,
    output_file: str = "./sr_output/etd_chunks.json"
) -> None:
    """
    エビデンステーブルをチャンク形式に変換
    （build_and_search_chromadbで使用）
    """
    df = pd.read_csv(extracted_csv).fillna("")
    include_df = df[df.get("decision", "") == "Include"].reset_index(drop=True)

    chunks = []
    chunk_id = 0

    # CQ（仮：手動で設定が必要）
    cq_name = "CQ (定性的SR)"

    # 1. 背景・対象
    for idx, row in include_df.iterrows():
        chunk_id += 1
        chunks.append({
            "id": f"chunk_{chunk_id:04d}",
            "content": f"【研究特性】\n"
                      f"著者: {row.get('Authors', '')}\n"
                      f"年: {row.get('Year', '')}\n"
                      f"対象: {row.get('population', '')}\n"
                      f"介入: {row.get('intervention', '')}\n"
                      f"比較: {row.get('comparison', '')}\n",
            "metadata": {
                "Chapter_or_CQ": cq_name,
                "Section": "研究特性",
                "PMID": str(row.get("PMID", "")),
                "source": "extracted.csv",
            }
        })

    # 2. 各アウトカムのサマリー
    for outcome, info in table_data.items():
        chunk_id += 1
        chunks.append({
            "id": f"chunk_{chunk_id:04d}",
            "content": f"【アウトカム: {outcome}】\n"
                      f"研究数: {info['n_studies']}件\n"
                      f"効果の方向: {info['effect_direction']}\n"
                      f"エビデンスの確実性: {info['certainty_of_evidence']}\n"
                      f"バイアスリスク: High {info['rob_high_count']}件、Some concerns {info['rob_some_count']}件\n",
            "metadata": {
                "Chapter_or_CQ": cq_name,
                "Section": f"アウトカム: {outcome}",
                "outcome": outcome,
                "source": "evidence_table.json",
            }
        })

    output_path = Path(output_file)
    output_path.parent.mkdir(parents=True, exist_ok=True)

    with open(output_path, "w", encoding="utf-8") as f:
        for chunk in chunks:
            f.write(json.dumps(chunk, ensure_ascii=False) + "\n")

    print(f"✅ チャンク形式に変換: {output_path}")


def main():
    parser = argparse.ArgumentParser(description="定性的SRエビデンス総体テーブル生成")
    parser.add_argument("--input", required=True, help="extracted.csv")
    parser.add_argument("--outcomes", default=None, help="アウトカム（カンマ区切り）")
    parser.add_argument("--output-dir", default="./sr_output")
    args = parser.parse_args()

    table_data = generate_evidence_table(args.input, args.outcomes, args.output_dir)
    generate_etd_chunks(table_data, args.input, f"{args.output_dir}/etd_chunks.json")

    print("\n[完了] エビデンス総体テーブルとチャンクを生成しました")


if __name__ == "__main__":
    main()
