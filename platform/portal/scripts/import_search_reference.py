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
    plan = json.load(open(os.path.join(ROOT, "data", "search_plan.json"), encoding="utf-8"))["searches"]   # 決定済みの検索(式・期間)。ポータルが、この式で PubMed を検索する
    for cq, r in ref.items():
        r = {**r, "plan": [{k: s[k] for k in ("id", "query", "full_query", "start", "end", "confirmed", "proposal", "formula_kind")} for s in plan if s["cq"] == cq and not s.get("proposal")]}
        out = tok.call("POST", f"/search/{cq}/reference", r)
        print(cq, "決定済みの検索", sum(1 for s in r["plan"] if s["confirmed"]), "件(式が未確認", sum(1 for s in r["plan"] if not s["confirmed"]), "件)/ 2023年版の検索過程", len(r["prior"]), "件", "→", out.get("error", "置きました"))


if __name__ == "__main__":
    from admin_user import email_arg
    sys.exit(__doc__) if {"-h", "--help"} & set(sys.argv[1:]) else main(email_arg(sys.argv[1:]))
