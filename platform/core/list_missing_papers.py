"""全CQの MANIFEST.md を走査し、全文が未入手の論文(△抄録 / ☐)を一覧にする

  python3 platform/core/list_missing_papers.py review_workspace [-o 未入手論文.md]

出力: Markdown表(CQ / PMID / 状態 / 文献 / 置き場所)。同じPMIDが複数CQにあれば1行にまとめる。
"""
import argparse
import glob
import os
import re

ROW = re.compile(r"^\| \d+ \| \[(\d+)\]\([^)]*\) \| ([☐☑△][^|]*) \| (.*) \|\s*$")


def scan(ws):
    found = {}
    for path in sorted(glob.glob(os.path.join(ws, "CQ*", "MANIFEST.md"))):
        cq = os.path.basename(os.path.dirname(path))
        for line in open(path, encoding="utf-8"):
            m = ROW.match(line)
            if not m:
                continue
            pmid, mark, cite = m.group(1), m.group(2).strip(), m.group(3).strip()
            if mark.startswith("☑"):
                continue
            cite = re.sub(r"^\d+[）)]\s*", "", cite)
            e = found.setdefault(pmid, {"mark": mark, "cite": cite, "cqs": []})
            e["cqs"].append(cq)
    return found


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("workspace_dir")
    ap.add_argument("-o", "--out")
    a = ap.parse_args()
    found = scan(a.workspace_dir)
    lines = ["# 全文が未入手の論文(全CQ)", "",
             f"{len(found)}件。PDFを入手したら `<CQフォルダ>/papers/<PMID>.pdf` に置いて run_revision.sh を再実行。",
             "同じPMIDが複数CQにある場合は、どれか1つのCQに置けば残りはキャッシュを共有します。", "",
             "| # | PMID | 状態 | 文献 | 置き場所(CQ) |", "|---|---|---|---|---|"]
    for i, (pmid, e) in enumerate(sorted(found.items(), key=lambda kv: (kv[1]["cqs"][0], kv[0])), 1):
        lines.append(f"| {i} | [{pmid}](https://pubmed.ncbi.nlm.nih.gov/{pmid}/) | {e['mark']} | {e['cite'][:160]} | {'、'.join(e['cqs'])} |")
    txt = "\n".join(lines) + "\n"
    if a.out:
        open(a.out, "w", encoding="utf-8").write(txt)
        print(f"{len(found)}件 → {a.out}")
    else:
        print(txt)


if __name__ == "__main__":
    main()
