#!/bin/bash
# ポータルの提出物・出力・手順書を、共有ドライブ「CIPNガイドライン作成」へ転送する。ダブルクリックで動く(場所の指定は要らない)。
source "$(cd "$(dirname "$0")" && pwd)/_共通.sh"
aws_login && python3 "$PORTAL/scripts/sync_drive.py" "$@"
finish
