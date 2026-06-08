"""
sr_pipeline.py — システマティックレビュー自動化パイプライン

検索式を入力 → PubMed検索 → スクリーニング → データ抽出 → Mindsエビデンステーブル

Usage:
    python sr_pipeline.py \
        --query '("Cancer"[Mesh] AND "Exercise"[Mesh] AND "Survivor"[Mesh])' \
        --inclusion "がんサバイバーを対象とした運動介入のRCT" \
        --exclusion "動物実験、プロトコル論文、運動介入なし" \
        --pico-q "がんサバイバーへの運動介入はQOLを改善するか？" \
        --outcomes "QOL, 疲労, 身体機能, 運動耐容能" \
        --output-dir ./output/cancer_exercise_sr_2026 \
        [--age-filter] \
        [--skip-search]      # 既存のsearch_all.csvを再利用
        [--skip-screening]   # 既存のscreened.csvを再利用
        [--skip-extraction]  # 既存のextracted.csvを再利用
"""

import argparse
import asyncio
import os
import sys
from datetime import date

# ---- ローカルモジュールのimport ----
sys.path.insert(0, os.path.dirname(__file__))

from sr_search import run_search
from sr_screening import run_screening
from sr_data_extraction import run_extraction
from sr_minds_formatter import generate_minds_table


def resolve_path(output_dir: str, filename: str) -> str:
    return os.path.join(output_dir, filename)


def print_step(n: int, title: str):
    print(f"\n{'='*60}")
    print(f"  Step {n}: {title}")
    print(f"{'='*60}")


async def run_pipeline(args):
    output_dir = args.output_dir
    os.makedirs(output_dir, exist_ok=True)

    search_csv = resolve_path(output_dir, "search_all.csv")
    screened_csv = resolve_path(output_dir, "screened.csv")
    extracted_csv = resolve_path(output_dir, "extracted.csv")
    today = date.today().strftime("%Y%m%d")
    minds_xlsx = resolve_path(output_dir, f"minds_evidence_table_{today}.xlsx")

    # ---- Step 1: 検索 ----
    if not args.skip_search:
        print_step(1, "PubMed検索")
        result = run_search(args.query, output_dir, age_filter=args.age_filter)
        if not result:
            print("[エラー] 検索結果が0件でした。検索式を確認してください。")
            return
    else:
        print_step(1, "PubMed検索（スキップ）")
        if not os.path.exists(search_csv):
            print(f"[エラー] {search_csv} が見つかりません。--skip-searchを外して再実行してください。")
            return

    # ---- Step 2: 一次スクリーニング ----
    if not args.skip_screening:
        print_step(2, "一次スクリーニング（タイトル・抄録）")
        await run_screening(
            input_csv=search_csv,
            output_csv=screened_csv,
            inclusion=args.inclusion,
            exclusion=args.exclusion,
        )
    else:
        print_step(2, "一次スクリーニング（スキップ）")

    # ---- Step 3: データ抽出 ----
    if not args.skip_extraction:
        print_step(3, "データ抽出（PICO + RoB 2）")
        await run_extraction(
            input_csv=screened_csv,
            output_csv=extracted_csv,
            outcome=args.outcomes,
        )
    else:
        print_step(3, "データ抽出（スキップ）")

    # ---- Step 4: Mindsテーブル生成 ----
    print_step(4, "Mindsエビデンステーブル生成")
    if not os.path.exists(extracted_csv):
        print(f"[エラー] {extracted_csv} が見つかりません。")
        return
    generate_minds_table(
        input_csv=extracted_csv,
        output_xlsx=minds_xlsx,
        pico_q=args.pico_q,
        outcomes=args.outcomes,
    )

    print(f"\n{'='*60}")
    print("  パイプライン完了")
    print(f"{'='*60}")
    print(f"  検索結果:         {search_csv}")
    print(f"  スクリーニング:   {screened_csv}")
    print(f"  データ抽出:       {extracted_csv}")
    print(f"  Mindsテーブル:    {minds_xlsx}")
    print(f"{'='*60}\n")


def main():
    parser = argparse.ArgumentParser(
        description="SRパイプライン: 検索式 → Mindsエビデンステーブル",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument("--query", required=True, help="PubMed検索式")
    parser.add_argument("--inclusion", required=True, help="包含基準（テキスト）")
    parser.add_argument("--exclusion", required=True, help="除外基準（テキスト）")
    parser.add_argument("--pico-q", default="介入はアウトカムを改善するか？", help="レビューの問い")
    parser.add_argument("--outcomes", default="QOL, 疲労, 身体機能", help="アウトカム（カンマ区切り）")
    parser.add_argument("--output-dir", default="./sr_output", help="出力ディレクトリ")
    parser.add_argument("--age-filter", action="store_true", help="年齢層別フィルタを有効化")
    parser.add_argument("--skip-search", action="store_true", help="検索済みCSVを再利用")
    parser.add_argument("--skip-screening", action="store_true", help="スクリーニング済みCSVを再利用")
    parser.add_argument("--skip-extraction", action="store_true", help="抽出済みCSVを再利用")

    args = parser.parse_args()
    asyncio.run(run_pipeline(args))


if __name__ == "__main__":
    main()
