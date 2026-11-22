"""検索式の用語を、PubMed のシソーラス(MeSH)で確認する(Mac で実行。AWS は不要)。
  python3 platform/portal/scripts/check_mesh.py
内容: 検索計画(platform/data/search_plan.json)の 17 検索について、PubMed が解釈した式(querytranslation)と件数を表示する。
      式に含まれる [Mesh] の見出し語は、1 語ずつ [MeSH Terms] で検索し、件数が 0 の語(見出し語でない語)を表示する。
      PubMed の警告(認識できなかった語句)も表示する。結果は search_results/mesh_check.csv にも保存する。"""
import csv, json, os, re, sys
HERE = os.path.dirname(os.path.abspath(__file__)); ROOT = os.path.dirname(os.path.dirname(HERE))
sys.path.insert(0, os.path.join(HERE, "..", "api"))
import pubmed  # noqa: E402

plan = json.load(open(os.path.join(ROOT, "data", "search_plan.json"), encoding="utf-8"))["searches"]
rows, seen = [], {}
for s in plan:
    r = pubmed.esearch(s["full_query"])
    print(f"{s['id']} {s['cq_name']}: {r['count']} 件({'確認済み' if s['confirmed'] else '未確認'})")
    if r["warnings"]: print("   PubMed の警告:", json.dumps(r["warnings"], ensure_ascii=False))
    # 見出し語: [Mesh] を付けた語と、「見出し語/副標目」の形の語。式を OR・AND・NOT・括弧で区切って 1 語ずつ取り出す
    toks = [t.strip() for t in re.split(r"\s+(?:OR|AND|NOT)\s+|[()]", s["query"]) if t.strip()]
    heads = {re.sub(r'^"|"$', "", re.sub(r"\[Mesh\]$", "", t, flags=re.I).strip()) for t in toks if re.search(r"\[Mesh\]$", t, re.I)} | {t.strip('"') for t in toks if "/" in t and "[" not in t and not t.startswith("20")}
    for h in sorted(heads):
        if h not in seen:
            if "/" in h:   # 「見出し語/副標目」の形は、PubMed が見出し語に読み替えるかを、解釈した式で確認する(読み替えられれば [MeSH Terms] が付く)
                tr = pubmed.esearch(h)["translation"]; seen[h] = 1 if "[MeSH Terms]" in tr else 0
            else: seen[h] = pubmed.esearch(f'"{h}"[MeSH Terms]')["count"]
        if seen[h] == 0: print(f"   見出し語として検索できない語: {h}")
    rows.append([s["id"], s["cq"], s["cq_name"], r["count"], "確認済み" if s["confirmed"] else "未確認", json.dumps(r["warnings"], ensure_ascii=False), r["translation"]])
os.makedirs(os.path.join(os.path.dirname(ROOT), "search_results"), exist_ok=True)
out = os.path.join(os.path.dirname(ROOT), "search_results", "mesh_check.csv")
with open(out, "w", encoding="utf-8-sig", newline="") as fh:
    w = csv.writer(fh); w.writerow(["ID", "CQ", "名称", "件数", "式の確認", "PubMed の警告", "PubMed が解釈した式"]); w.writerows(rows)
print("保存:", out)
