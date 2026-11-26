"""手順書(Word)をポータルに置く(Mac で実行)。委員は、ポータルの「手順書」の画面から、自分の役割の手順書を開く。
  python3 platform/portal/scripts/upload_docs.py <メールアドレス>
置くもの: platform/manuals/out/*.docx、platform/procedures/out の「用語の定義」、platform/scope/out の Scope(「Scope」の画面)。"""
import glob, os, sys, urllib.request
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from admin_user import token  # noqa: E402

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def main(email):
    tok = token(email)
    files = sorted(glob.glob(os.path.join(ROOT, "manuals", "out", "*.docx"))) + [f for f in sorted(glob.glob(os.path.join(ROOT, "procedures", "out", "*.docx"))) if "用語の定義" in f] + sorted(glob.glob(os.path.join(ROOT, "scope", "out", "minds", "SC-*.xlsx")))   # 推奨作成会議手順書は、会議を開かない決定(2026-11-22)のため置かない
    if not glob.glob(os.path.join(ROOT, "scope", "out", "minds", "SC-*.xlsx")): print("【注意】Scope(platform/scope/out/minds の SC-*.xlsx)がありません。git pull で取得してください")
    for f in files:
        r = tok.call("POST", "/docs/upload-url", {"filename": os.path.basename(f)})
        if "error" in r: print(os.path.basename(f), "→", r["error"]); continue
        with open(f, "rb") as fh:
            urllib.request.urlopen(urllib.request.Request(r["url"], method="PUT", data=fh.read(), headers={"Content-Type": "application/vnd.openxmlformats-officedocument." + ("spreadsheetml.sheet" if f.endswith(".xlsx") else "wordprocessingml.document")}))
        print("置きました:", os.path.basename(f))
    print("\n委員に見える一覧(この利用者の役割):"); [print(" ", d["name"], "/", d["target"]) for d in tok.call("GET", "/docs")]


if __name__ == "__main__":
    from admin_user import email_arg
    sys.exit(__doc__) if {"-h", "--help"} & set(sys.argv[1:]) else main(email_arg(sys.argv[1:]))
