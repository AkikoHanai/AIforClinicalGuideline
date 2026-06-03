"""
sr_qualitative_sr_pipeline.py — 定性的SR完全パイプライン

extracted.csv → エビデンステーブル → EtD → RC-5/RC-1

Usage:
    python sr_qualitative_sr_pipeline.py \
        --extracted ./sr_output/extracted.csv \
        --cq "CQ 1" \
        --outcomes "持久性体力, 筋力, QoL, 倦怠感, うつ" \
        --output-dir ./sr_output/qualitative_sr
"""

import argparse
import asyncio
import os
import subprocess
import sys
from datetime import datetime
from pathlib import Path

# Phase 1: エビデンステーブル生成
from sr_evidence_table import generate_evidence_table, generate_etd_chunks

# Phase 2: EtD生成
from sr_etd_builder import build_etd_framework, generate_sof_table

# Phase 3: RC-5/RC-1生成
from generate_recommendation import generate_recommendations


def run_phase(phase_num: int, phase_name: str, func, *args, **kwargs):
    """フェーズを実行"""
    print(f"\n{'='*60}")
    print(f"  Phase {phase_num}: {phase_name}")
    print(f"{'='*60}")
    try:
        if asyncio.iscoroutinefunction(func):
            asyncio.run(func(*args, **kwargs))
        else:
            func(*args, **kwargs)
        print(f"✅ Phase {phase_num} 完了")
    except Exception as e:
        print(f"❌ Phase {phase_num} エラー: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)


async def main():
    parser = argparse.ArgumentParser(
        description="定性的SR完全パイプライン: extracted.csv → RC-5/RC-1"
    )
    parser.add_argument("--extracted", required=True, help="extracted.csv")
    parser.add_argument("--cq", default="CQ 1", help="CQ名")
    parser.add_argument("--outcomes", default=None, help="アウトカム（カンマ区切り）")
    parser.add_argument("--output-dir", default="./sr_output/qualitative_sr")
    args = parser.parse_args()

    output_dir = Path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    log_file = output_dir / f"pipeline_{timestamp}.log"

    print(f"""
╔══════════════════════════════════════════════════════════╗
║  定性的SR完全パイプライン                              ║
║  extracted.csv → エビデンステーブル → EtD → RC-5/RC-1  ║
╚══════════════════════════════════════════════════════════╝

【入力】
  - extracted.csv: {args.extracted}
  - CQ: {args.cq}
  - outcomes: {args.outcomes or '自動検出'}

【出力ディレクトリ】
  - {output_dir}
    """)

    # Phase 1: エビデンステーブル生成
    run_phase(
        1, "エビデンス総体テーブル生成",
        generate_evidence_table,
        args.extracted,
        args.outcomes,
        str(output_dir)
    )

    # Phase 2: チャンク化
    print("\n  Generating chunks for RAG...")
    table_json = output_dir / "evidence_table.json"
    run_phase(
        2, "チャンク化（RAG用）",
        generate_etd_chunks,
        None,  # table_data（次のステップで生成）
        args.extracted,
        str(output_dir / "etd_chunks.json")
    )

    # ※手動: table_dataを読み込む
    import json
    with open(table_json) as f:
        table_data = json.load(f)

    generate_etd_chunks(table_data, args.extracted, str(output_dir / "etd_chunks.json"))

    # Phase 3: EtD生成
    run_phase(
        3, "EtDフレームワーク生成",
        build_etd_framework,
        str(table_json),
        args.extracted,
        args.cq,
        str(output_dir / "etd_framework.json")
    )

    # SoF生成
    etd_json = output_dir / "etd_framework.json"
    with open(etd_json) as f:
        etd = json.load(f)
    generate_sof_table(etd, str(output_dir / "summary_of_findings.md"))

    # Phase 4: RC-5/RC-1生成
    if not os.environ.get("ANTHROPIC_API_KEY"):
        print("\n[警告] ANTHROPIC_API_KEY が設定されていません")
        print("  RC-5/RC-1生成をスキップします（手動実行可）")
        print(f"  実行コマンド:")
        print(f"    python generate_recommendation.py \\")
        print(f"      --chunks-file {output_dir}/etd_chunks.json \\")
        print(f"      --etd-file {output_dir}/etd_framework.json \\")
        print(f"      --cq '{args.cq}' \\")
        print(f"      --output-dir {output_dir}")
    else:
        await run_phase(
            4, "推奨文生成（RC-5/RC-1）",
            generate_recommendations,
            str(output_dir / "etd_chunks.json"),
            str(etd_json),
            args.cq,
            str(output_dir)
        )

    # 完了ログ
    print(f"""
╔══════════════════════════════════════════════════════════╗
║  パイプライン完了                                      ║
╚══════════════════════════════════════════════════════════╝

【出力ファイル】
  - evidence_table.md      : エビデンス総体テーブル
  - evidence_table.json    : 構造化データ
  - etd_chunks.json        : RAG用チャンク
  - etd_framework.json     : EtDフレームワーク
  - summary_of_findings.md : GRADE Summary of Findings
  - CQ1_RC5_output.md      : 推奨作成の経過（RC-5）
  - CQ1_RC1_draft.md       : 推奨文草案（RC-1）

【次のステップ】
  1. evidence_table.md と summary_of_findings.md を確認
  2. etd_framework.json を修正（手動調整）
  3. RC-5 / RC-1 を確認・編集
  4. ガイドラインに統合
    """)


if __name__ == "__main__":
    asyncio.run(main())
