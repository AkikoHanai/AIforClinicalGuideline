#!/bin/bash
# RAG検証一括実行スクリプト

set -e

PDF_PATH="${1:-./$Users/ahanai/Downloads/cancer_survivor_guidelines.pdf}"
OUTPUT_DIR="./rag_validation_output"

echo "╔══════════════════════════════════════════════════════════╗"
echo "║  RAG検証パイプライン                                    ║"
echo "║  cancer_survivor_guidelines.pdf → コンタミ検査 → 精度検証"
echo "╚══════════════════════════════════════════════════════════╝"
echo ""

if [ ! -f "$PDF_PATH" ]; then
    echo "❌ エラー: PDFが見つかりません: $PDF_PATH"
    exit 1
fi

mkdir -p "$OUTPUT_DIR"

# Step 1: PDF チャンク抽出
echo "【Step 1】PDFからチャンク抽出..."
python sr_pdf_chunk_extractor.py \
    --pdf "$PDF_PATH" \
    --output "$OUTPUT_DIR/pdf_chunks.json"

echo ""

# Step 2: RAG精度検証
echo "【Step 2】RAG精度検証..."
python sr_rag_validation.py \
    --chunks-file "$OUTPUT_DIR/pdf_chunks.json"

echo ""

# Step 3: 結果確認
echo "╔══════════════════════════════════════════════════════════╗"
echo "║  検証完了                                              ║"
echo "╚══════════════════════════════════════════════════════════╝"
echo ""
echo "【出力ファイル】"
echo "  - $OUTPUT_DIR/pdf_chunks.json"
echo "  - rag_validation_results.json"
echo ""

if [ -f "rag_validation_results.json" ]; then
    echo "【検証結果のハイライト】"
    python -c "
import json
with open('rag_validation_results.json') as f:
    r = json.load(f)
    print(f'  CQ一致率: {r[\"cq_match_count\"]}/{r[\"total_cases\"]}')
    print(f'  コンタミなし率: {r[\"no_contamination_count\"]}/{r[\"total_cases\"]}')
    print(f'  キーワードカバレッジ: {r[\"keyword_coverage_avg\"]:.1%}')
"
fi

echo ""
echo "✅ 完了"
