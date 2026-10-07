#!/usr/bin/env bash
# CIPN診療ガイドライン改訂パイプライン(Mac用・1コマンド)
#
#   cd ~/AIforClinicalGuideline
#   bash platform/run_revision.sh <2023年版PDF> [作業ディレクトリ]
#
# 初回: 2023年版PDFからCQパッケージと作業一式(review_workspace/)を作る
# 2回目以降: 既にある minds_review.xlsx は上書きしない(委員の記入を守る)。
#            papers/ の論文(PDFまたはOA全文)を読んで 4-5下書き→マージ→SoF→検証→草案作成シート を更新する
#
# 環境変数:
#   AWS_PROFILE / AWS_ACCESS_KEY_ID など … Bedrock を呼ぶのに必要
#   BEDROCK_MODEL_ID                    … 省略時 anthropic.claude-sonnet-4-5
#   SYNC_ONLY=1                          … Bedrockを呼ばず、新規PDFの登録だけ行う
#   PAPER_DIR=<PDFのフォルダ>            … 論文PDFを2023年版の引用文献と照合して各CQの papers/<PMID>.pdf に配置する
set -euo pipefail

PDF="${1:-}"
WS="${2:-review_workspace}"
HERE="$(cd "$(dirname "$0")" && pwd)"
CORE="$HERE/core"
PY="${PYTHON:-python3}"

if [ -z "$PDF" ] && [ ! -d "$WS" ]; then
  echo "使い方: bash platform/run_revision.sh <2023年版PDF> [作業ディレクトリ]"; exit 1
fi

step() { printf '\n== %s ==\n' "$1"; }

step "0a. 承認済み企画書からの逸脱の検査(失敗したら中止)"
python3 "$(dirname "$0")/governance/plan_guard.py"

step "0. 依存"
# Homebrew の Python(PEP 668)は直接 pip install できないので platform/.venv に閉じて入れる
VENV="$HERE/.venv"
if [ ! -x "$VENV/bin/python" ]; then
  echo "仮想環境を作成: $VENV"
  $PY -m venv "$VENV"
fi
PY="$VENV/bin/python"
$PY -c "import openpyxl, boto3" 2>/dev/null || $PY -m pip install -q --upgrade pip openpyxl boto3
command -v pdftotext >/dev/null || { echo "pdftotext がありません: brew install poppler"; exit 1; }

if [ -n "$PDF" ]; then
  step "1. 2023年版PDF → CQパッケージ"
  $PY "$CORE/extract_cipn_guideline.py" "$PDF" -o "$WS/_cq_packages"
fi

step "2. 作業一式(既存の minds_review.xlsx は保持)"
$PY "$CORE/prepare_review_workspace.py" "$WS/_cq_packages" -o "$WS"

if ls "$HERE"/prior_worksheets/*.json >/dev/null 2>&1; then
  step "2b. 2023年版の委員ワークシート・海外GLの品質評価を取り込み(platform/prior_worksheets/*.json)"
  $PY "$CORE/import_prior_worksheet.py" "$WS" "$HERE"/prior_worksheets/*.json | grep -v " 0研究" || true
fi

if [ -n "${PAPER_DIR:-}" ]; then
  step "2c. 論文PDFを各CQの papers/ に配置($PAPER_DIR)"
  $PY "$CORE/place_papers.py" "$PAPER_DIR" "$WS"
fi

step "3. 論文本文 → 4-5下書き(Minds様式)・研究特性・新規論文の登録"
if [ "${SYNC_ONLY:-0}" = "1" ]; then
  $PY "$CORE/fill_rob2_from_papers.py" "$WS" --sync-only
else
  $PY "$CORE/fill_rob2_from_papers.py" "$WS" || echo "(Bedrock呼び出しに失敗。AWS認証を確認。SYNC_ONLY=1 で登録だけ行えます)"
fi

step "4. xlsx → cq_package.json(評価者2名の照合)"
$PY "$CORE/merge_rob2_evidence.py" "$WS"

step "5. SoF"
$PY "$CORE/build_sof.py" "$WS"

step "6. Minds規則の機械検証"
mkdir -p "$WS/_bundles"
for d in "$WS"/CQ*/; do
  $PY "$CORE/review_bundle.py" "$d/cq_package.json" -o "$WS/_bundles"
done

step "7. 草案作成シート(委員用) / 検証画面(事務局用)"
$PY "$CORE/render_console.py" "$WS"/_bundles/*.bundle.json -o "$WS/_draft_sheets"
$PY "$CORE/render_console.py" "$WS"/_bundles/*.bundle.json -o "$WS/_secretariat" --audience secretariat

$PY "$CORE/list_missing_papers.py" "$WS" -o "$WS/_未入手論文一覧.md"
printf '\n完了: %s/\n  委員用: %s/_draft_sheets/*.review.html\n  事務局用: %s/_secretariat/*.secretariat.html\n' "$WS" "$WS" "$WS"
