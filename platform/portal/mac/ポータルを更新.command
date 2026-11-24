#!/bin/bash
# 最新のコードを取得し、ポータル(AWS)へ展開する。画面または API を更新したときに行う。
source "$(cd "$(dirname "$0")" && pwd)/_共通.sh"
cd "$REPO" && git pull origin "$BRANCH" && aws_login && cd "$PORTAL/infra" && cdk deploy --require-approval never --outputs-file ../out/outputs.json
finish
