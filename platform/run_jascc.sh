#!/usr/bin/env bash
# JASCC_GL(Googleドライブ)のフォルダで、作業一式・論文・決定記録を管理する。
#   bash platform/run_jascc.sh init              フォルダを作る(初回)
#   bash platform/run_jascc.sh first <2023年版PDF>   初回の作成(2023年版PDFから。EtDも作る)
#   bash platform/run_jascc.sh papers            論文受け取りフォルダのPDFを配置・登録(AWS認証なしで動く)
#   bash platform/run_jascc.sh full              配置・登録のあと、Claudeが本文から下書きを作る(AWS認証が必要)
#   bash platform/run_jascc.sh minds             Minds書類の一式を出力(決定記録の最新のJSONを使う)
# 場所を変えるときは、JASCC_GL=<パス> を付けて実行する。
# platform(GitHubのコピー)は、Googleドライブの外に置く。.git と .venv は同期の負荷が大きいため。
set -euo pipefail
HERE="$(cd "$(dirname "$0")" && pwd)"
JASCC_GL="${JASCC_GL:-/Users/ahanai/Library/CloudStorage/GoogleDrive-akiko.hanai@faculty.gs.chiba-u.jp/マイドライブ/JASCC_GL}"
WS="$JASCC_GL/review_workspace"; INBOX="$JASCC_GL/論文受け取り"; REC="$JASCC_GL/決定記録"
PY="python3"; [ -x "$HERE/.venv/bin/python" ] && PY="$HERE/.venv/bin/python"
cmd="${1:-}"
[ -d "$JASCC_GL" ] || { echo "JASCC_GL が見つかりません: $JASCC_GL (Googleドライブが同期済みか確認)"; exit 1; }
case "$cmd" in
  init)
    mkdir -p "$WS" "$INBOX" "$REC" "$JASCC_GL/承認済み企画書" "$JASCC_GL/配布資料" "$WS/_drafts"
    $PY - "$HERE" "$INBOX" <<'PY'
import json, os, sys
plan = json.load(open(os.path.join(sys.argv[1], "governance", "approved_plan.json"), encoding="utf-8"))
for it in plan["SR項目"] + plan["FRQ項目"]:
    for d in it["dir"]:
        os.makedirs(os.path.join(sys.argv[2], d), exist_ok=True)
PY
    cp -n "$HERE"/governance/*.docx "$JASCC_GL/承認済み企画書/" 2>/dev/null || true
    echo "作成しました: $JASCC_GL"; ls "$JASCC_GL" ;;
  first)
    [ -n "${2:-}" ] || { echo "使い方: bash platform/run_jascc.sh first <2023年版PDF>"; exit 1; }
    PAPER_DIR="$INBOX" bash "$HERE/run_revision.sh" "$2" "$WS" ;;
  papers)
    PAPER_DIR="$INBOX" SYNC_ONLY=1 bash "$HERE/run_revision.sh" "" "$WS" ;;
  full)
    PAPER_DIR="$INBOX" bash "$HERE/run_revision.sh" "" "$WS" ;;
  minds)
    LATEST="$(ls -t "$REC"/決定記録_*.json 2>/dev/null | head -1 || true)"
    M=""; [ -n "$LATEST" ] && M="--meeting $LATEST" && echo "決定記録: $LATEST"
    $PY "$HERE/core/export_minds_documents.py" "$WS" $M -o "$WS/_minds_documents" ;;
  *) sed -n 2,9p "$0"; exit 1 ;;
esac
