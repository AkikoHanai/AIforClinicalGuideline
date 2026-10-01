"""整理済みSRフォルダ(organize_sr_files.py の出力)の「01_検索」から、2023年版の検索記録を読み取る

  python3 platform/core/extract_prior_search.py <整理後フォルダ> -o platform/prior_worksheets

CQごとに search_<CQ>.json を作る(import_prior_worksheet.py がそのまま取り込める)。
各文書から: 検索DB / 検索期間の原文 / 期間の終了日(今回の検索の起点になる) / 検索式 / 流れ図の行(件数・除外内訳)
"""
import argparse
import glob
import json
import os
import re
import unicodedata
import zipfile


def paras(path):
    x = zipfile.ZipFile(path).read("word/document.xml").decode("utf8", "ignore")
    out = []
    for p in re.findall(r"<w:p[ >].*?</w:p>", x, re.S):
        t = re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", p)).strip()
        if t and not t.startswith("INCLUDEPICTURE"):
            out.append(unicodedata.normalize("NFKC", t))
    return out


def squeeze_digits(t):
    return re.sub(r"(?<=\d)\s+(?=\d)", "", t)


MONTHS = {m: i for i, m in enumerate(["jan", "feb", "mar", "apr", "may", "jun", "jul", "aug", "sep", "oct", "nov", "dec"], 1)}


def last_date(text):
    """期間の原文から最も新しい年月(日)を (YYYY, MM, DD|None) で返す。年だけなら月=None"""
    t = squeeze_digits(text)
    cands = []
    # 2021年6月30日 / 2021.6.30 / 2021/6 / 2021.8 .12
    for m in re.finditer(r"(20\d\d)\s*(?:年|[./])\s*(\d{1,2})(?!\d)(?:\s*(?:月|[./])\s*(\d{1,2})(?!\d))?", t):
        y, mo = int(m.group(1)), int(m.group(2))
        d = int(m.group(3)) if m.group(3) and int(m.group(3)) <= 31 else None
        if 1 <= mo <= 12:
            cands.append((y, mo, d))
    # 2021-06 / 2021-06-30
    for m in re.finditer(r"(20\d\d)-(\d{2})(?:-(\d{2}))?(?!\d)", t):
        cands.append((int(m.group(1)), int(m.group(2)), int(m.group(3)) if m.group(3) else None))
    # August 3, 2021
    for m in re.finditer(r"(Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)[a-z]*\.?\s*(\d{1,2})?,?\s*(20\d\d)", t, re.I):
        cands.append((int(m.group(3)), MONTHS[m.group(1).lower()], int(m.group(2)) if m.group(2) else None))
    if not cands:
        ys = [int(y) for y in re.findall(r"(20\d\d)", t)]
        return (max(ys), None, None) if ys else None
    return max(cands, key=lambda c: (c[0], c[1], c[2] or 0))


def fmt(ld):
    if not ld:
        return None
    return f"{ld[0]}" + (f"-{ld[1]:02d}" if ld[1] else "") + (f"-{ld[2]:02d}" if ld[2] else "")


def parse(path):
    ps = paras(path)
    period = next((p for p in ps if re.search(r"検索期間|search(ed)? (date|period)|^検索\b|Pubmed で 検索", p, re.I)), "")
    # 期間の行が無い文書: 日付を含む最初の行
    if not period:
        period = next((p for p in ps if last_date(p)), "")
    db = next((re.sub(r".*検索データベース\s*[:：\]]\s*", "", p) for p in ps if "検索データベース" in p), "")
    if not db:
        db = "PubMed" if any("pubmed" in p.lower() for p in ps) else ""
    query = max((p for p in ps if re.search(r"neuropath|goshajinkigan|carnit|cryo|exercise", p, re.I) and len(p) > 60), key=len, default="")
    flow = [p for p in ps if re.search(r"件|RCT|除外|メタ|観察|ASCO|ESMO|ハンドサーチ", p) and p != query and len(p) < 160]
    ld = last_date(period)
    return {"file": os.path.basename(path), "database": db.strip(" ]"), "period_text": period[:200],
            "last_search_end": fmt(ld),
            "query": query, "flow_lines": flow[:14]}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("organized_dir")
    ap.add_argument("-o", "--out", required=True)
    a = ap.parse_args()
    os.makedirs(a.out, exist_ok=True)
    summary = []
    for d in sorted(glob.glob(os.path.join(a.organized_dir, "CQ*"))):
        cq = os.path.basename(d)
        searches = [parse(f) for f in sorted(glob.glob(os.path.join(d, "01_検索", "*.docx")))]
        if not searches:
            summary.append((cq, "(検索記録なし)", "")); continue
        ends = [s["last_search_end"] for s in searches if s["last_search_end"]]
        note = None
        if cq == "CQ1-牛車腎気丸":
            # このフォルダの検索過程は2017年手引き時点(〜2016.5)。2023年版の検索(2020〜2021.6, 53件)は別資料
            ends = ["2021-06"]
            note = "この検索過程docxは2017年手引き時点(~2016.5, 40件)の記録。2023年版の検索(PubMed 2020~2021.6, 53件)は prior_worksheets/CQ1-牛車腎気丸.json"
        spec = {"cq_dir": cq, "source": "2023年版作成時のSR担当者の検索過程(SR統括ファイル)",
                "searches_2023": searches, "last_search_end_2023": max(ends) if ends else None}
        if note:
            spec["note"] = note
        json.dump(spec, open(os.path.join(a.out, f"search_{cq}.json"), "w", encoding="utf-8"), ensure_ascii=False, indent=1)
        summary.append((cq, "; ".join(s["period_text"][:60] for s in searches), spec["last_search_end_2023"] or "?"))
    print(f"{'CQ':<34} {'前回検索の終了':<10} 期間(原文)")
    for cq, per, end in summary:
        print(f"{cq:<34} {end or '':<10} {per}")


if __name__ == "__main__":
    main()
