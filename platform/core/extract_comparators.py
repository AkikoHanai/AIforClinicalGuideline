"""
対照(C)の候補抽出 — 二次スクリーニング後の一覧表から
=====================================================
対照の種類は、機械で決め切らせない。ここが崩れると
「実対照との差なし」を「効果なし」と読み違える。

そこで:
  この器は **候補を出すだけ**。適用は merge_comparators.py で、
  人が確認した列を読むか、暫定(--provisional)と明示した場合に限る。

一覧表はテキスト層の行が折り返すため、単純な行読みでは列がずれる。
pdfplumberで語の座標を取り、ヘッダのx位置から列境界を決めて復元する。
"""
import argparse
import csv
import json
import os
import re

HERE = os.path.dirname(os.path.abspath(__file__))

HEADERS = ["文献", "研究デザイン", "P", "I", "C", "O", "除外", "コメント"]

# 対照の種類の判定。上から順に当てる（先に来るものほど具体的）
RULES = [
    ("usual_care", "high", [r"usual\s*care", r"standard\s*care", r"通常ケア", r"標準治療"]),
    ("placebo", "high", [r"placebo", r"sham", r"プラセボ"]),
    ("none", "high", [r"wait[\s-]*list", r"waiting\s*list", r"no\s+intervention",
                      r"non[\s-]*intervention", r"no\s+exercise", r"非介入", r"介入なし",
                      r"運動なし", r"untreated"]),
    ("active_weaker", "high", [r"stretch", r"flexibilit", r"low[\s-]*intensity",
                               r"low[\s-]*to[\s-]*moderate", r"light\s+exercise",
                               r"ストレッチ", r"低強度"]),
    ("active_different", "high", [r"attention\s*control", r"education", r"counsel",
                                  r"relaxation", r"diet\s*only", r"health\s*promotion",
                                  r"教育", r"栄養指導"]),
    ("none", "low", [r"^control$", r"\bcontrol\b", r"対照群"]),
]


def column_bounds(words):
    """
    列境界を決める。見出し語は列の中央寄せで、データは左寄せのため、
    見出しのx位置をそのまま境界に使うと『Kampshoff C S et』の "et" が
    隣の列に落ちる。そこで **データ側の列開始位置** を頻度で学習し、
    「次の列の開始位置」を境界にする。
    """
    hs = {}
    for w in words:
        if w["text"] in HEADERS and w["top"] < 120 and w["text"] not in hs:
            hs[w["text"]] = w["x0"]
    if len(hs) < len(HEADERS):
        return None

    freq = {}
    for w in words:
        if w["top"] < 80:
            continue
        freq[round(w["x0"])] = freq.get(round(w["x0"]), 0) + 1
    peaks = sorted(x for x, c in freq.items() if c >= 3)

    anchors, prev = [], -100
    for h in (hs[x] for x in HEADERS):
        # 範囲内で最も多くの語が始まるx = 列の開始位置。
        # 著者名の途中の語も peak になるので、最左ではなく最頻を採る
        cand = [x for x in peaks if prev + 15 < x <= h + 10]
        anchors.append(max(cand, key=lambda x: (freq[x], -x)) if cand else h)
        prev = anchors[-1]

    bounds = []
    for i, h in enumerate(HEADERS):
        lo = 0 if i == 0 else anchors[i]
        hi = 10 ** 6 if i == len(HEADERS) - 1 else anchors[i + 1]
        bounds.append((h, lo, hi))
    return bounds


def page_records(page, bounds=None):
    """
    表は複数ページに続くが、ヘッダは最初のページにしかない。
    列境界は先頭ページで決めて、以降のページに使い回す（列位置は同じ）。
    """
    words = page.extract_words(use_text_flow=False, keep_blank_chars=False)
    own = column_bounds(words)
    has_header = own is not None
    bounds = own or bounds
    if not bounds:
        return [], None

    lines = {}
    for w in words:
        if has_header and w["top"] < 80:   # 見出し行とタイトルだけ捨てる
            continue
        key = round(w["top"] / 4)
        lines.setdefault(key, []).append(w)

    records, cur = [], None
    for key in sorted(lines):
        cells = {h: [] for h, _, _ in bounds}
        for w in sorted(lines[key], key=lambda x: x["x0"]):
            for h, lo, hi in bounds:
                if lo <= w["x0"] < hi:
                    cells[h].append(w["text"])
                    break
        cells = {h: " ".join(v).strip() for h, v in cells.items()}
        if not any(cells.values()):
            continue
        # 研究デザインが入っている行が、新しい文献の1行目
        if cells["研究デザイン"]:
            if cur:
                records.append(cur)
            cur = {h: cells[h] for h, _, _ in bounds}
        elif cur:
            for h in cur:
                if cells[h]:
                    cur[h] = (cur[h] + " " + cells[h]).strip()
    if cur:
        records.append(cur)
    return records, bounds


def normalize_code(s: str) -> str:
    """『Brown J C et al., 2018』『Brown JC et al.,2018(High vs Ctrl)』を同一視する鍵"""
    s = re.sub(r"\(.*?\)", "", s or "")
    s = re.sub(r"[^0-9A-Za-z]", "", s).lower()
    return s


def classify(c_text: str):
    t = (c_text or "").lower()
    for kind, conf, pats in RULES:
        for p in pats:
            if re.search(p, t):
                return kind, conf, p
    return None, None, None


def main():
    import pdfplumber
    ap = argparse.ArgumentParser(description="一覧表 → 対照(C)の候補")
    ap.add_argument("pdf")
    ap.add_argument("--pages", nargs=2, type=int, default=[57, 80],
                    help="二次スクリーニング後の一覧表のPDFページ範囲")
    ap.add_argument("--package", help="照合するCQパッケージ(data/cq/CQ1.json)")
    ap.add_argument("-o", "--outdir", default=os.path.join(HERE, "..", "data", "cq"))
    args = ap.parse_args()

    recs, bounds = [], None
    with pdfplumber.open(args.pdf) as pdf:
        for i in range(args.pages[0] - 1, args.pages[1]):
            r, bounds = page_records(pdf.pages[i], bounds)
            recs.extend(r)

    rows = []
    for r in recs:
        code = re.sub(r"\s+", " ", r["文献"]).strip()
        if not code:
            continue
        kind, conf, pat = classify(r["C"])
        rows.append({
            "code": code, "key": normalize_code(code),
            "design": r["研究デザイン"], "P": r["P"], "I": r["I"],
            "C_raw": r["C"], "O": r["O"],
            "excluded": bool(r["除外"]), "comment": r["コメント"],
            "suggested_comparator": kind, "confidence": conf, "matched_rule": pat,
        })

    matched = unmatched = 0
    pkg_codes = {}
    if args.package:
        with open(args.package, encoding="utf-8") as f:
            pkg = json.load(f)
        for s in pkg["studies"]:
            pkg_codes.setdefault(normalize_code(s["title"] or s["id"]), []).append(s["id"])
        by_key = {r["key"]: r for r in rows}
        for k, sids in pkg_codes.items():
            if k in by_key:
                matched += len(sids)
            else:
                unmatched += len(sids)

    os.makedirs(args.outdir, exist_ok=True)
    j = os.path.join(args.outdir, "comparator_candidates.json")
    with open(j, "w", encoding="utf-8") as f:
        json.dump(rows, f, ensure_ascii=False, indent=2)

    c = os.path.join(args.outdir, "comparator_worksheet.csv")
    with open(c, "w", encoding="utf-8", newline="") as f:
        w = csv.writer(f)
        w.writerow(["研究コード", "一覧表のC（原文）", "機械の候補", "確からしさ",
                    "確定値（none/usual_care/placebo/active_weaker/active_different）", "確認者"])
        for r in sorted(rows, key=lambda x: (x["confidence"] or "z", x["code"])):
            if r["excluded"]:
                continue
            w.writerow([r["code"], r["C_raw"], r["suggested_comparator"] or "",
                        r["confidence"] or "判定不能", "", ""])

    n_hi = sum(1 for r in rows if r["confidence"] == "high" and not r["excluded"])
    n_lo = sum(1 for r in rows if r["confidence"] == "low" and not r["excluded"])
    n_no = sum(1 for r in rows if r["confidence"] is None and not r["excluded"])
    n_ex = sum(1 for r in rows if r["excluded"])
    print(f"一覧表から {len(rows)} 件（うち除外 {n_ex} 件）")
    print(f"  候補あり(確からしさ高) {n_hi} 件 / (低) {n_lo} 件 / 判定不能 {n_no} 件")
    if args.package:
        print(f"  パッケージの論文との照合: 一致 {matched} 件 / 一覧表に見つからない {unmatched} 件")
    from collections import Counter
    print("  内訳:", dict(Counter(r["suggested_comparator"] for r in rows if not r["excluded"])))
    print(f"→ {j}\n→ {c}（確定値の列を埋めて merge_comparators.py に渡す）")


if __name__ == "__main__":
    main()
