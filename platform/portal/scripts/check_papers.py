"""論文PDFのフォルダと、2023年版の引用文献(platform/data/gl2023/cq_packages)の過不足を確認する(Mac で実行。AWS 不要)。
  python3 platform/portal/scripts/check_papers.py <PDFのフォルダ>
照合: ファイル名が PMID ならその PMID。そうでなければ 1〜2 ページ目の本文を引用文献の題名と照合する(pypdf)。
出力: CQ ごとの「必要 / あり / 不足(PMID・題名)」、照合できなかった PDF(新規論文または題名の照合失敗)、照合結果の CSV。"""
import csv, glob, json, os, re, sys, unicodedata

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def norm(s):
    return re.sub(r"[^a-z0-9]", "", unicodedata.normalize("NFKC", s or "").lower())


def main(folder):
    from pypdf import PdfReader
    plan = json.load(open(os.path.join(ROOT, "governance", "approved_plan.json"), encoding="utf-8"))
    dir2id = {d: it["id"] for it in plan["SR項目"] + plan["FRQ項目"] for d in it["dir"]}
    merge = {"CQ1-冷却": "CQ1-冷却・圧迫", "CQ1-圧迫": "CQ1-冷却・圧迫"}
    refs, by_cq = {}, {}
    for f in sorted(glob.glob(os.path.join(ROOT, "data", "gl2023", "cq_packages", "CQ*.json"))):
        stem = os.path.splitext(os.path.basename(f))[0]; cqid = dir2id.get(merge.get(stem, stem))
        if not cqid: continue
        for r in json.load(open(f, encoding="utf-8")).get("references", []):
            if r.get("pmid"):
                refs.setdefault(str(r["pmid"]), {"title": r.get("title", ""), "cqs": set()})["cqs"].add(cqid); by_cq.setdefault(cqid, set()).add(str(r["pmid"]))
    pdfs = sorted(glob.glob(os.path.join(folder, "**", "*.pdf"), recursive=True))
    found, unmatched, rows = {}, [], []
    for f in pdfs:
        name = os.path.splitext(os.path.basename(f))[0]; pmid = name if name.isdigit() else None; how = "ファイル名"
        if not pmid:
            try:
                rd = PdfReader(f); head = norm(" ".join((rd.pages[i].extract_text() or "") for i in range(min(2, len(rd.pages)))))
            except Exception as e:
                unmatched.append((os.path.basename(f), f"読めない: {e}")); rows.append([os.path.basename(f), "", "", "読めない"]); continue
            hits = [p for p, r in refs.items() if r["title"] and len(norm(r["title"])) > 25 and norm(r["title"])[:80] in head]
            pmid = hits[0] if len(hits) == 1 else None; how = "題名の照合" if pmid else ("題名が複数に一致" if hits else "一致なし")
        if pmid and pmid in refs:
            found.setdefault(pmid, []).append(os.path.basename(f)); rows.append([os.path.basename(f), pmid, "・".join(sorted(refs[pmid]["cqs"])), how])
        else:
            unmatched.append((os.path.basename(f), f"PMID {pmid}: 2023年版の引用文献にない(新規論文)" if pmid else how)); rows.append([os.path.basename(f), pmid or "", "", how])
    print(f"PDF {len(pdfs)} 件 / 2023年版の引用文献 {len(refs)} 件(PMID あり)\n")
    print("CQ | 必要 | あり | 不足")
    total_missing = 0
    for cqid in sorted(by_cq, key=lambda c: (c[0] != "P", c[0] != "N", c)):
        need = by_cq[cqid]; have = {p for p in need if p in found}; miss = need - have; total_missing += len(miss)
        print(f"{cqid} | {len(need)} | {len(have)} | {len(miss)}")
        for p in sorted(miss): print(f"    不足 PMID {p}: {refs[p]['title'][:90]}")
    dup = {p: fs for p, fs in found.items() if len(fs) > 1}
    print(f"\n不足の合計(CQ×論文): {total_missing} / 重複して入っている論文: {len(dup)}")
    for p, fs in dup.items(): print(f"    PMID {p}: {', '.join(fs)}")
    if unmatched:
        print(f"\n照合できなかった PDF({len(unmatched)} 件。新規論文は <CQフォルダ>/PMID.pdf にする):")
        for n, why in unmatched: print(f"    {n}: {why}")
    out = os.path.join(folder, "_照合結果.csv")
    with open(out, "w", newline="", encoding="utf-8-sig") as fh:
        w = csv.writer(fh); w.writerow(["ファイル", "PMID", "CQ", "照合方法"]); w.writerows(rows)
    print(f"\n照合結果を保存: {out}")


if __name__ == "__main__":
    if len(sys.argv) < 2: sys.exit(__doc__)
    main(sys.argv[1])
