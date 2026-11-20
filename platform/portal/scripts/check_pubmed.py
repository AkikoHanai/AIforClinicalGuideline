"""ポータルが使う PubMed からの題名・抄録の取得を、Mac から実際の PubMed に対して確認する(AWS は不要)。
  python3 platform/portal/scripts/check_pubmed.py [PMID ...]
PMID を省くと、2023年版の引用文献 1 件と、2026-10-26 の確認で保存した文献 2 件で確認する。"""
import os, sys
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "api"))
os.environ.setdefault("AWS_DEFAULT_REGION", "ap-northeast-1")
import handler as H  # noqa: E402

pmids = sys.argv[1:] or ["21258836", "39256982", "42750137"]
meta = H.pubmed_meta(pmids)
for pm in pmids:
    m = meta.get(pm)
    if not m: print(pm, "→ 取得できませんでした"); continue
    print(f"PMID {pm}\n  題名: {m['title']}\n  著者: {m['authors']}\n  誌名・年: {m['journal']} {m['year']}\n  抄録: {len(m['abstract'])} 字 {m['abstract'][:80]}…")
print("\n取得", len(meta), "/", len(pmids), "件")
