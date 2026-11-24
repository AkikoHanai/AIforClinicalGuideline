#!/bin/bash
# 30分ごとに、共有ドライブへ転送する。ウィンドウを開いたままにする(閉じると止まる)。AWS のログインが切れたら、再ログインを求める。
source "$(cd "$(dirname "$0")" && pwd)/_共通.sh"
while true; do
  aws_login && python3 "$PORTAL/scripts/sync_drive.py" "$@" --watch=30
  echo "転送が止まりました。60秒後に、もう一度始めます(止めるときは Ctrl+C)"; sleep 60
done
