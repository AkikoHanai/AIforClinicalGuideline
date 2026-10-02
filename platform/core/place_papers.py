"""論文PDFを、2023年版の引用文献(各CQの references)と照合して papers/<PMID>.pdf に配置する

  python3 platform/core/place_papers.py <PDFのフォルダ> <review_workspace> [--dry-run]

照合: 引用文献のタイトルが PDF の1〜2ページ目の本文に含まれるか(記号・大小文字・空白は無視)。
一致したPMIDを持つ全CQ(冷却・圧迫の統合などで複数に載るもの)の papers/ にコピーする。
一致しないPDFは「未照合」として一覧に出す(新規論文なら、PMIDを付けて papers/<PMID>.pdf に置く)。
"""
import argparse
import glob
import json
import os
import re
import shutil
import subprocess
import unicodedata


def norm(s):
    return re.sub(r"[^a-z0-9]", "", unicodedata.normalize("NFKC", s or "").lower())


def title_of(citation):
    """'1）Smith EM, Pang H, et al. Title here. JAMA. 2013；309：1' → 'Title here'"""
    c = re.sub(r"^\s*\d+[）)]\s*", "", citation or "")
    c = unicodedata.normalize("NFKC", c)
    m = re.search(r"et al\.?[;:,]?\s*(?:[^.]{0,80}?\.\s+)?([A-Z][^.]{25,}?)[.?]\s", c) or re.search(r"[A-Z]{1,3}[,.]\s+([A-Z][^.]{25,}?)[.?]\s", c)
    return m.group(1) if m else ""


def pdf_head(path, pages=2):
    r = subprocess.run(["pdftotext", "-l", str(pages), path, "-"], capture_output=True, text=True)
    return r.stdout


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("pdf_dir")
    ap.add_argument("workspace")
    ap.add_argument("--dry-run", action="store_true")
    a = ap.parse_args()
    refs = []     # (cq_dir, pmid, title_norm, citation)
    for pkg in glob.glob(os.path.join(a.workspace, "CQ*", "cq_package.json")):
        d = os.path.dirname(pkg)
        for r in json.load(open(pkg, encoding="utf-8")).get("references", []):
            t = norm(title_of(r.get("citation")))
            if r.get("pmid") and len(t) >= 20:
                refs.append((d, str(r["pmid"]), t, r["citation"]))
    placed, unmatched = [], []
    for pdf in sorted(glob.glob(os.path.join(a.pdf_dir, "**", "*.pdf"), recursive=True)):
        head = norm(pdf_head(pdf))
        hits = {(d, p) for d, p, t, _ in refs if t in head}
        if not hits:
            unmatched.append(pdf); continue
        for d, p in sorted(hits):
            dest = os.path.join(d, "papers", f"{p}.pdf")
            if not a.dry_run:
                os.makedirs(os.path.dirname(dest), exist_ok=True)
                shutil.copyfile(pdf, dest)
            placed.append((os.path.basename(d), p, os.path.basename(pdf)))
    print(f"配置 {len(placed)}件 / 未照合 {len(unmatched)}件" + ("(dry-run)" if a.dry_run else ""))
    for cq, p, f in placed:
        print(f"  {cq:<34} {p}  <- {f[:60]}")
    if unmatched:
        print("\n未照合(2023年版の引用文献に無い。新規論文の可能性):")
        for f in unmatched:
            print("  ", os.path.relpath(f, a.pdf_dir)[:100])


if __name__ == "__main__":
    main()
