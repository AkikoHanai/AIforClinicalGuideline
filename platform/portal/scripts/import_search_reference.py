"""保存済みの検索の資料(platform/data/search_reference.json)を、ポータルの「検索の記録」の画面の参考の枠に置く(Mac で実行)。
  python3 platform/portal/scripts/import_search_reference.py <メールアドレス>
内容: CQ ごとの検索式の案(前回Scopeの式 + 本CQの介入語)と、2023年版の検索過程(検索期間、検索式、件数の記載)。検索の記録には数えない。"""
import json, os, sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from admin_user import token  # noqa: E402

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def main(email):
    tok = token(email)
    ref = json.load(open(os.path.join(ROOT, "data", "search_reference.json"), encoding="utf-8"))["cq"]
    for cq, r in ref.items():
        out = tok.call("POST", f"/search/{cq}/reference", r)
        print(cq, "検索式の案", len(r["formula"]), "件 / 2023年版の検索過程", len(r["prior"]), "件", "→", out.get("error", "置きました"))


if __name__ == "__main__":
    from admin_user import email_arg
    sys.exit(__doc__) if {"-h", "--help"} & set(sys.argv[1:]) else main(email_arg(sys.argv[1:]))
