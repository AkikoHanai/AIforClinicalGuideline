"""論文PDFのフォルダと、2023年版の引用文献(platform/data/gl2023/cq_packages)の過不足を確認する(Mac で実行。AWS 不要)。
  python3 platform/portal/scripts/check_papers.py <PDFのフォルダ>
照合: ファイル名が PMID ならその PMID。そうでなければ 1〜2 ページ目の本文を引用文献の題名と照合する(pypdf)。
出力: CQ ごとの「必要 / あり / 不足(PMID・題名)」、照合できなかった PDF(新規論文または題名の照合失敗)、照合結果の CSV。"""
import csv, glob, json, logging, os, re, sys, unicodedata
logging.getLogger("pypdf").setLevel(logging.ERROR)  # フォントの警告を出さない

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
    pdfs = sorted(f for f in set(glob.glob(os.path.join(folder, "**", "*.pdf"), recursive=True)) if not any(part.startswith("_") for part in os.path.relpath(f, folder).split(os.sep)[:-1]))  # _work などの作業フォルダは除く
    found, unmatched, rows = {}, [], []
    for f in pdfs:
        name = os.path.splitext(os.path.basename(f))[0]
        m = re.search(r"PMID[_\- ]?(\d{6,9})", name, re.I) or re.fullmatch(r"(\d{6,9})", name)  # 例: 01_PMID23733756_2013_Hershman.pdf、23733756.pdf
        pmid = m.group(1) if m else None; how = "ファイル名のPMID"
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
    print(f"\n不足の合計(CQ×論文): {total_missing} / 複数のCQフォルダに入っている論文(CQが複数の文献の複製): {len(dup)}")
    for p, fs in dup.items(): print(f"    PMID {p}: {', '.join(fs)}")
    if unmatched:
        print(f"\n照合できなかった PDF({len(unmatched)} 件。新規論文は <CQフォルダ>/PMID.pdf にする):")
        for n, why in unmatched: print(f"    {n}: {why}")
    out = os.path.join(folder, "_照合結果.csv")
    with open(out, "w", newline="", encoding="utf-8-sig") as fh:
        w = csv.writer(fh); w.writerow(["ファイル", "PMID", "CQ", "照合方法"]); w.writerows(rows)
    print(f"\n照合結果を保存: {out}")
    # フォルダ(CQ-介入)ごとの過不足。フォルダ名は cq_packages の名前と同じ(CQ1-冷却・圧迫 は 冷却+圧迫、CQ1-鍼灸-3-章 は 鍼灸)
    pk = {}
    for f in glob.glob(os.path.join(ROOT, "data", "gl2023", "cq_packages", "CQ*.json")):
        stem = os.path.splitext(os.path.basename(f))[0]
        pk[stem] = {str(r["pmid"]) for r in json.load(open(f, encoding="utf-8")).get("references", []) if r.get("pmid")}
    subs = [d for d in sorted(os.listdir(folder)) if os.path.isdir(os.path.join(folder, d)) and d.startswith("CQ")]
    if subs:
        print("\nフォルダ(CQ-介入)ごとの過不足:  フォルダ | 2023年版の引用 | あり | 不足 | 2023年版にないPDF")
        for d in subs:
            keys = ["CQ1-冷却", "CQ1-圧迫"] if d == "CQ1-冷却・圧迫" else [re.sub(r"-3-章$", "", d)]
            need = set().union(*(pk.get(k, set()) for k in keys))
            inpdf = set()
            for f in glob.glob(os.path.join(folder, d, "**", "*.pdf"), recursive=True):
                m = re.search(r"PMID[_\- ]?(\d{6,9})", os.path.basename(f), re.I); inpdf.add(m.group(1) if m else os.path.basename(f))
            miss = sorted(need - inpdf); extra = sorted(inpdf - need)
            print(f"{d} | {len(need)} | {len(need & inpdf)} | {len(miss)} | {len(extra)}")
            for q in miss: print(f"    不足 PMID {q}: {refs.get(q, {}).get('title', '')[:90]}")
            for q in extra: print(f"    2023年版にない: {q}" + (f"(2023年版では {'・'.join(sorted(refs[q]['cqs']))} の引用)" if q in refs else ""))
    for n in ("未取得文献.md", "取得結果.md"):
        fp = os.path.join(folder, n)
        if os.path.exists(fp): print(f"\n==== {n} ====\n" + open(fp, encoding="utf-8", errors="ignore").read()[:4000])


if __name__ == "__main__":
    if len(sys.argv) < 2: sys.exit(__doc__)
    main(sys.argv[1])
