# どの .command からも読み込む共通の設定。ダブルクリック、ターミナルのどのフォルダからでも、リポジトリの場所を、このファイルの位置から決める。
MAC_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PORTAL="$(cd "$MAC_DIR/.." && pwd)"
REPO="$(cd "$PORTAL/../.." && pwd)"
BRANCH="claude/sleepy-turing-a740xe"

# AWS にログインしていなければ、ログインする(SSO のとき、ブラウザが開く)
aws_login() {
  if ! aws sts get-caller-identity >/dev/null 2>&1; then
    echo "AWS にログインします…"
    aws sso login || { echo "AWS にログインできませんでした"; return 1; }
  fi
}
finish() { echo; read -r -p "終わりました。Enter キーでこのウィンドウを閉じます" _; }
