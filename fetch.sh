#!/usr/bin/env bash
# 統括委員長用: ポータルの提出物・出力・手順書を、Google 共有ドライブ「CIPNガイドライン作成」へ転送する。
#   cd ~/AIforClinicalGuideline && git pull && ./fetch.sh
#   ./fetch.sh --dry-run    置く場所と内容の表示だけ(何も置かない)
#   ./fetch.sh --tree       共有ドライブのフォルダの構成を表示する
#   ./fetch.sh --watch      30分ごとに繰り返す(ウィンドウを開いたままにする。--watch=5 は 5分ごと)
#   ./fetch.sh --reset SC-3 名前に SC-3 を含む Scope を、生成した版に戻す(共有ドライブで編集された版は、別の名前で残す)
# Scope(SC-1〜SC-4)は、共有ドライブの Excel を Google スプレッドシートで編集した版を正とし、ポータルに反映する(ドライブ → ポータル)。
# 共有ドライブの同期フォルダは、自動で見つける(~/Library/CloudStorage/GoogleDrive-*/共有ドライブ/CIPNガイドライン作成)。環境変数 DRIVE_DIR で指定もできる。
# ポータルのメールアドレスの指定は不要(統括委員会の利用者を自動で使う。プールにいないメールアドレスを指定したときは、利用者の一覧を表示する)。AWS にログインしていなければ、ログインを求める。
set -euo pipefail
cd "$(dirname "$0")"
if [ "${1:-}" != "--tree" ] && ! aws sts get-caller-identity >/dev/null 2>&1; then
  echo "AWS にログインします…"; aws sso login
fi
exec python3 platform/portal/scripts/sync_drive.py "$@"
