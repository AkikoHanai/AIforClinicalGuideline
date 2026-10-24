"""CIPN診療ガイドライン2023年版の「推奨作成の記録(EtD)」を、2023年版の体裁で作る。
  python3 platform/core/build_etd.py <_cq_packages> --pdf <2023年版PDF> -o <出力フォルダ> [--add-to-workbooks <作業ディレクトリ>]

2023年版の各CQは、推奨文 / 推奨の強さ・エビデンスの確実性・合意率 / 解説 / 投票結果(投票者数、棄権: 利益相反・SR、5択の票数) / 文献 の順に書かれている。
このスクリプトは、刊行版PDFから上の項目を取り出し(AIによる要約・言い換えは行わない)、CQごとの記録表にする。
推奨を決めるときに考慮する項目(2023年版 第1章 作成手順):
  アウトカム全体にわたる総括的なエビデンスの確実性 / 望ましい効果と望ましくない効果のバランス /
  患者・市民の価値観と希望 / 資源の利用(コスト。特に高額が予想される場合のみ)
2028年版の欄は空欄で、委員が記入する。
出力: etd_2023.json、CIPN_EtD_2023年版準拠.xlsx(一覧 + CQごとのシート)
"""
import argparse, glob, json, os, re, subprocess, unicodedata
import openpyxl
from openpyxl.styles import Font, Alignment, Border, Side, PatternFill

STR_LABEL = {"1": "1 投与(実施)することを強く推奨する", "2": "2 投与(実施)することを提案する", "3": "3 「推奨なし」とする",
             "4": "4 投与(実施)しないことを提案する", "5": "5 投与(実施)しないことを強く推奨する"}
MERGE = {"CQ1-冷却": "CQ1-冷却・圧迫", "CQ1-圧迫": "CQ1-冷却・圧迫"}


def nz(s):
    return re.sub(r"\s+", "", unicodedata.normalize("NFKC", s or ""))


def pdf_lines(pdf):
    r = subprocess.run(["pdftotext", "-layout", pdf, "-"], capture_output=True, text=True)
    return r.stdout.splitlines()


def parse_votes(lines):
    """「投票結果」ブロックを取り出す: 行番号、投票者数、棄権(利益相反・SR)、5択の票数"""
    out = []
    for i, l in enumerate(lines):
        if l.strip() != "投票結果":
            continue
        blk = "\n".join(lines[i + 1:i + 22])
        nb = unicodedata.normalize("NFKC", blk)
        m = re.search(r"(\d+)\s*名\s*\(棄権:\s*利益相反\s*(\d+)\s*名・SR\s*(\d+)\s*名\)", nb)
        counts = re.findall(r"\(\s*(\d+)\s*/\s*(\d+)\s*\)", nb)
        if not m or len(counts) < 5:
            continue
        out.append({"line": i, "n": int(m.group(1)), "coi": int(m.group(2)), "sr": int(m.group(3)),
                    "counts": [int(a) for a, b in counts[:5]], "denominator": int(counts[0][1])})
    return out


def locate(lines, rec, start):
    """推奨文が本文の何行目に出るか(空白・改行を無視して照合)"""
    target = nz(rec)
    acc, idx = "", []
    for i in range(start, len(lines)):
        t = nz(lines[i]); idx += [i] * len(t); acc += t
    p = acc.find(target[:60])
    return idx[p] if p >= 0 else None


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("packages"); ap.add_argument("--pdf", required=True); ap.add_argument("-o", "--out", required=True)
    ap.add_argument("--add-to-workbooks")
    a = ap.parse_args()
    lines = pdf_lines(a.pdf); votes = parse_votes(lines)
    start = next((i for i, l in enumerate(lines) if re.match(r"\s*1．薬物療法による予防", l) and i > 2000), 2000)
    items = []
    for f in sorted(glob.glob(os.path.join(a.packages, "*.json"))):
        pkg = json.load(open(f, encoding="utf-8")); stem = os.path.splitext(os.path.basename(f))[0]
        d = pkg.get("draft") or {}
        rec = d.get("recommendation_text") or ""
        if not rec:
            continue
        pos = locate(lines, rec, start)
        items.append({"stem": stem, "dir": MERGE.get(stem, stem), "title": pkg.get("title") or stem, "rec": rec, "strength": str(d.get("strength") or ""),
                      "certainty": d.get("certainty") or "", "narrative": pkg.get("narrative") or "", "pos": pos, "pmids": d.get("cited_pmids") or [],
                      "panel": d.get("panel_vote") or {}})
    items.sort(key=lambda x: (x["pos"] is None, x["pos"] or 0))
    used = set()
    for it in items:
        v = next((v for v in votes if v["line"] > (it["pos"] or 10**9) and v["line"] not in used), None) if it["pos"] is not None else None
        if v:
            used.add(v["line"]); it["votes"] = v
            ok = (it["panel"].get("agreement_total") in (None, v["n"] - v["coi"] - v["sr"], v["denominator"]))
            it["vote_check"] = "一致" if ok else f"要確認(合意率の分母 {it['panel'].get('agreement_total')} と票数の分母 {v['denominator']})"
        else:
            it["votes"] = None; it["vote_check"] = "投票結果を取り出せません(PDFを確認)"
        it.pop("pos", None)
    os.makedirs(a.out, exist_ok=True)
    json.dump(items, open(os.path.join(a.out, "etd_2023.json"), "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    bd = Border(*(Side(style="thin", color="000000"),) * 4)

    def style(ws, header_rows=(1,)):
        for row in ws.iter_rows():
            for c in row:
                c.border = bd; c.alignment = Alignment(wrap_text=True, vertical="top")
        for r in header_rows:
            for c in ws[r]:
                c.font = Font(bold=True); c.fill = PatternFill("solid", fgColor="D9D9D9")

    wb = openpyxl.Workbook(); ws = wb.active; ws.title = "一覧(2023年版)"
    ws.append(["CQ(作業フォルダ)", "推奨文(2023年版)", "推奨の強さ", "エビデンスの確実性", "投票者数", "棄権(利益相反)", "棄権(SR)", "1 強く推奨", "2 提案する", "3 推奨なし", "4 しないことを提案", "5 しないことを強く推奨", "合意率", "投票結果の照合"])
    for it in items:
        v = it["votes"]; mx = max(v["counts"]) if v else None
        ws.append([it["stem"], it["rec"], STR_LABEL.get(it["strength"], it["strength"]), it["certainty"], v["n"] if v else "", v["coi"] if v else "", v["sr"] if v else ""] +
                  ([f"{c}/{v['denominator']}" for c in v["counts"]] if v else [""] * 5) + [f"{round(100*mx/v['denominator'])}%({mx}/{v['denominator']})" if v else "", it["vote_check"]])
    for col, w in zip("ABCDEFGHIJKLMN", [34, 60, 26, 10, 8, 8, 8, 9, 9, 9, 9, 9, 14, 24]): ws.column_dimensions[col].width = w
    style(ws)
    per_dir = {}
    for it in items: per_dir.setdefault(it["dir"], []).append(it)
    for d, its in per_dir.items():
        w = wb.create_sheet(d[:31].replace("・", "").replace("/", "") or "EtD")
        w.append([f"推奨作成の記録(EtD)　{d}　【2023年版の記載。2028年版は右の列に委員が記入する】"]); w.append([])
        for it in its:
            v = it["votes"]
            w.append(["CQ", it["title"]]); w.append(["推奨文", it["rec"], "", "2028年版 推奨文案(委員が記入)", ""])
            w.append(["推奨の強さ", STR_LABEL.get(it["strength"], it["strength"]), "", "2028年版 推奨の強さ(投票で決定)", ""])
            w.append(["エビデンスの確実性", it["certainty"], "", "2028年版 確実性(様式SR-8の結果)", ""])
            if v:
                w.append(["投票結果(2023年版)", f"ガイドライン統括委員会+作成委員会 {v['n']}名(棄権: 利益相反 {v['coi']}名・SR {v['sr']}名)"])
                w.append(["", " / ".join(f"{k} {c}/{v['denominator']}" for k, c in zip(["1強く推奨", "2提案する", "3推奨なし", "4しないことを提案", "5しないことを強く推奨"], v["counts"]))])
            w.append(["推奨決定で考慮する項目", "2023年版の記載(解説に含まれる)", "", "2028年版(委員が記入)", ""])
            w.append(["アウトカム全体にわたる総括的なエビデンスの確実性", f"2023年版: 確実性 {it['certainty']}", "", "", ""])
            w.append(["望ましい効果と望ましくない効果のバランス", "解説を参照", "", "", ""])
            w.append(["患者・市民の価値観と希望", "解説を参照", "", "", ""])
            w.append(["資源の利用(コスト)。高額が予想される場合のみ検討", "解説を参照", "", "", ""])
            w.append(["解説(2023年版の原文)", it["narrative"]]); w.append(["引用文献のPMID(2023年版)", " ".join(it["pmids"])]); w.append([])
        for col, wd in zip("ABCDE", [34, 70, 2, 34, 50]): w.column_dimensions[col].width = wd
        style(w, header_rows=())
        w["A1"].font = Font(bold=True)
    wb.save(os.path.join(a.out, "CIPN_EtD_2023年版準拠.xlsx"))
    miss = [it["stem"] for it in items if not it["votes"]]
    print(f"{len(items)}件のCQのEtDを作成 / 投票結果を取り出せた {len(items) - len(miss)}件 → {a.out}" + (f"  取り出せない: {miss}" if miss else ""))
    bad = [(it["stem"], it["vote_check"]) for it in items if it["votes"] and it["vote_check"] != "一致"]
    if bad: print("要確認:", bad)
    if a.add_to_workbooks:
        n = 0
        for d, its in per_dir.items():
            p = os.path.join(a.add_to_workbooks, d, "minds_review.xlsx")
            if not os.path.exists(p): continue
            b = openpyxl.load_workbook(p)
            if "EtD(2023年版)" in b.sheetnames: del b["EtD(2023年版)"]
            w = b.create_sheet("EtD(2023年版)")
            src = wb[d[:31].replace("・", "").replace("/", "")]
            for row in src.iter_rows(values_only=True): w.append(list(row))
            for col, wd in zip("ABCDE", [34, 70, 2, 34, 50]): w.column_dimensions[col].width = wd
            style(w, header_rows=()); b.save(p); n += 1
        print(f"{n}件の作業ブックに「EtD(2023年版)」シートを追加")


if __name__ == "__main__":
    main()
