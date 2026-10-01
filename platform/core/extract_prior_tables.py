"""2023年版作成時の「研究の一覧」「バイアス」pptx(表形式)を読み、CQごとの研究データ JSON にする

  python3 platform/core/extract_prior_tables.py <フォルダ> -o platform/prior_worksheets

対象: 表(a:tbl)を含む pptx。ヘッダーに「報告者」「結果」があれば研究表、「バイアス」があればRoB表として読む。
出力: table_<CQ>.json (import_prior_worksheet.py がそのまま取り込める studies[])
表でなく自由配置のテキストボックスで作られた pptx は対象外(件数を最後に表示)。
"""
import argparse
import collections
import glob
import json
import os
import re
import unicodedata
import zipfile

CQ_BY_KEYWORD = [("VB12", ["CQ2-ビタミン-B12"]), ("アミトリプチリン", ["CQ2-アミトリプチリン"]), ("オピオイド", ["CQ2-オピオイド"]),
                 ("デュロキセチン", ["CQ2-デュロキセチン"]), ("運動", ["CQ1-運動", "CQ2-運動"]), ("鍼", ["CQ1-鍼灸", "CQ2-鍼灸"]),
                 ("カルニチン", ["CQ1-カルニチン-アセチル‒L‒カルニチン"]), ("cryo", ["CQ1-冷却・圧迫"]), ("Compression", ["CQ1-冷却・圧迫"]),
                 ("NSAID", ["CQ2-非ステロイド性消炎鎮痛薬-NSAIDs"]), ("併用", ["CQ2-薬物の併用療法"])]
ROB_COLS = ["ランダム化", "隠蔽", "盲検化", "測定者盲検", "ITT", "その他"]


def cell_text(c):
    return unicodedata.normalize("NFKC", re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", c)).strip())


def tables_of(path):
    z = zipfile.ZipFile(path)
    out = []
    for n in sorted((n for n in z.namelist() if re.match(r"ppt/slides/slide\d+\.xml", n)), key=lambda n: int(re.findall(r"\d+", n)[0])):
        x = z.read(n).decode("utf8", "ignore")
        for tbl in re.findall(r"<a:tbl>.*?</a:tbl>", x, re.S):
            rows = [[cell_text(c) for c in re.findall(r"<a:tc[ >].*?</a:tc>", r, re.S)] for r in re.findall(r"<a:tr[ >].*?</a:tr>", tbl, re.S)]
            out.append(rows)
    return out


def canon(label):
    """'Smith, 2013' / 'Schloss et al 2017' / '13 Kim (2018)' → ('smith', 2013)"""
    t = re.sub(r"^\s*\d+\s+", "", label)
    m = re.search(r"([A-Za-zÀ-ɏ][A-Za-zÀ-ɏ'\-]+).*?(20\d\d|19\d\d)", t)
    return (m.group(1).lower(), int(m.group(2))) if m else (None, None)


def mark(v):
    v = v.strip()
    if v in ("✔", "レ", "○", "◯", "✓", "√"):
        return "✔"
    if v in ("?", "？"):
        return "?"
    if v in ("―", "ー", "−", "-", "－", "‒", "—", "×", "x", "X"):
        return "－"
    return v or None


def study_table(rows):
    hdr = next((i for i, r in enumerate(rows) if any("報告者" in c for c in r) and any("結果" in c for c in r)), None)
    if hdr is None:
        return []
    cols = {}
    for j, c in enumerate(rows[hdr]):
        if "報告者" in c: cols["label"] = j
        elif "デザイン" in c: cols["design"] = j
        elif "症例数" in c: cols["n"] = j
        elif "誘発薬" in c: cols["drug"] = j
        elif "対照" in c or "対象薬" in c: cols["comparator"] = j
        elif "結果" in c: cols["result"] = j
    out = []
    for r in rows[hdr + 1:]:
        if len(r) <= cols.get("label", 0) or not r[cols["label"]]:
            continue
        s, y = canon(r[cols["label"]])
        if not s:
            continue
        g = lambda k: r[cols[k]] if k in cols and cols[k] < len(r) else None
        n = g("n") or ""
        mm = re.search(r"(\d+)\s*[\(（]\s*(\d+)", n.replace(" ", ""))
        st = {"label": r[cols["label"]], "surname": s, "year": y, "design": g("design"), "drug": g("drug"),
              "comparator": g("comparator"), "n_text": n, "result_2023": g("result")}
        if mm:
            st["n_total"], st["n_int"] = int(mm.group(1)), int(mm.group(2))
        out.append(st)
    return out


def rob_table(rows):
    if not any("バイアス" in c for r in rows[:2] for c in r):
        return []
    out = []
    for r in rows:
        if not r or not r[0] or "バイアス" in r[0]:
            continue
        s, y = canon(r[0])
        if not s or len(r) < 3:
            continue
        marks = [mark(c) for c in r[1:]]
        d = {"label": r[0], "surname": s, "year": y}
        # 標準の並び: ランダム化, 隠蔽, 盲検化, 測定者盲検, ITT, その他(自由記載)
        vals = marks[:5]
        if len(marks) >= 4:
            d["rob_2023"] = {ROB_COLS[i]: vals[i] for i in range(min(5, len(vals))) if vals[i]}
            if len(marks) > 5 and marks[5]:
                d["rob_2023"]["その他"] = r[6] if len(r) > 6 else marks[5]
        out.append(d)
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("folder")
    ap.add_argument("-o", "--out", required=True)
    a = ap.parse_args()
    per_cq = collections.defaultdict(dict)    # cq -> (surname, year) -> study
    skipped = []
    for p in sorted(glob.glob(os.path.join(a.folder, "**", "*.pptx"), recursive=True)):
        name = unicodedata.normalize("NFC", os.path.basename(p))
        if name.startswith("~$"):
            continue
        cqs = next((c for k, c in CQ_BY_KEYWORD if k.lower() in name.lower()), None)
        tabs = tables_of(p)
        if not tabs:
            skipped.append(name); continue
        if not cqs:
            skipped.append(name + " (CQ不明)"); continue
        for rows in tabs:
            for st in study_table(rows):
                for cq in cqs:
                    per_cq[cq].setdefault((st["surname"], st["year"]), {}).update({k: v for k, v in st.items() if v})
            for rb in rob_table(rows):
                for cq in cqs:
                    per_cq[cq].setdefault((rb["surname"], rb["year"]), {}).update({k: v for k, v in rb.items() if v})
    os.makedirs(a.out, exist_ok=True)
    for cq, studies in per_cq.items():
        json.dump({"cq_dir": cq, "add_missing": True, "source": "2023年版作成時の研究一覧・バイアス表(pptx)", "studies": list(studies.values())},
                  open(os.path.join(a.out, f"table_{cq}.json"), "w", encoding="utf-8"), ensure_ascii=False, indent=1)
        print(f"{cq}: {len(studies)}研究 (結果あり {sum(1 for s in studies.values() if s.get('result_2023'))} / RoBあり {sum(1 for s in studies.values() if s.get('rob_2023'))})")
    if skipped:
        print("\n表形式でないため未取込(自由配置のテキストボックス):", " / ".join(skipped))


if __name__ == "__main__":
    main()
