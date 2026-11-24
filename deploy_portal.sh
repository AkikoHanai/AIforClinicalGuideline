#!/usr/bin/env bash
# 統括委員長用: ポータル(AWS)を、最新のコードで展開する。画面または API を更新したときに行う。
#   cd ~/AIforClinicalGuideline && git pull && ./deploy_portal.sh
set -euo pipefail
cd "$(dirname "$0")/platform/portal/infra"
aws sts get-caller-identity >/dev/null 2>&1 || { echo "AWS にログインします…"; aws sso login; }
cdk deploy --require-approval never --outputs-file ../out/outputs.json
