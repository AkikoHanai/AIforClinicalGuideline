#!/usr/bin/env bash
# 統括委員長用: 手順書・2023年版の資料・検索の参考資料をポータルに登録し、登録された件数を確認する(何度実行してもよい)。
#   cd ~/AIforClinicalGuideline && git pull origin claude/sleepy-turing-a740xe && ./setup_portal.sh
set -euo pipefail
cd "$(dirname "$0")"
aws sts get-caller-identity >/dev/null 2>&1 || { echo "AWS にログインします…"; aws sso login; }
exec python3 platform/portal/scripts/setup_portal.py "$@"
