"""
CQパッケージ → 委員会レビュー作業一式(Minds様式ファイル + 文献フォルダ)
====================================================================
extract_cipn_guideline.py が作る CQ パッケージ(JSON)から、CQ(介入)ごとに
以下をまとめて用意する。

  <outdir>/<cq_id>/
    minds_review.xlsx   Minds様式のレビュー用ワークブック
                         (CQ・PICO / エビデンス総体評価 / 個別研究RoB2評価 / 文献リスト / 投票)
    MANIFEST.md          引用文献の書誌情報一覧(PMID・著者・誌名・年)。
                          論文PDF本体は著作権上ここでは収集できないため、
                          「papers/」フォルダに手作業で集めてもらうためのチェックリスト
    papers/               論文PDFを手作業で入れてもらうための空フォルダ

Minds様式の対応(『Minds診療ガイドライン作成の手引き』準拠):
  シート「CQ・PICO」            = Minds 3.3-3.5 (CQ設定・PICO・アウトカム重要度)
  シート「エビデンス総体評価」    = Minds 4.4 (エビデンス総体の確実性評価)
  シート「個別研究RoB2評価」     = Minds 4.3 (個別研究のバイアスリスク評価。RoB2)
  シート「文献リスト」           = Minds 3.5/4.2 (適格文献リスト)
  シート「投票」                = Minds 6.2-6.3 (推奨作成の投票)

エビデンス総体評価・個別研究RoB2評価シートは空欄で出力する。ここを
ROB2に基づき学生/SR委員が埋めたものを merge_rob2_evidence.py で
CQパッケージ(JSON)に戻し、platform/core/review_bundle.py の
Minds規則検証(R1-R8)にかける設計。
"""
import argparse
import glob
import json
import os

from openpyxl import Workbook
from openpyxl.styles import Alignment, Font, PatternFill
from openpyxl.utils import get_column_letter

HERE = os.path.dirname(os.path.abspath(__file__))

HEADER_FILL = PatternFill("solid", fgColor="1F4E5F")
HEADER_FONT = Font(color="FFFFFF", bold=True)
NOTE_FILL = PatternFill("solid", fgColor="FFF3CD")
WRAP = Alignment(wrap_text=True, vertical="top")

STRENGTH_TEXT = {
    "1": "1(強い推奨・実施)", "2": "2(弱い推奨・実施を提案)",
    "3": "3(推奨なし)", "4": "4(弱い推奨・非実施を提案)", "5": "5(強い推奨・非実施)",
}
CERT_TEXT = {"A": "A(強)", "B": "B(中)", "C": "C(弱)", "D": "D(非常に弱い)"}
DOWNGRADE_DOMAINS = ["risk_of_bias(バイアスリスク)", "inconsistency(非一貫性)",
                     "indirectness(非直接性)", "imprecision(不精確)",
                     "publication_bias(出版バイアス)"]
ROB2_DOMAINS = ["D1 ランダム化の過程", "D2 意図した介入からの逸脱",
                "D3 アウトカムデータの欠測", "D4 アウトカム測定",
                "D5 選択的な結果報告", "総合(Overall)"]


def header_row(ws, row, headers, widths=None):
    for i, h in enumerate(headers, start=1):
        c = ws.cell(row=row, column=i, value=h)
        c.fill = HEADER_FILL
        c.font = HEADER_FONT
        c.alignment = WRAP
        if widths:
            ws.column_dimensions[get_column_letter(i)].width = widths[i - 1]
    # ws.cell()でセルに触れるとappend()の開始行がずれる(空行混入の原因になる)ため
    # 文字列座標を組み立てるだけにする
    ws.freeze_panes = f"A{row + 1}"


def sheet_pico(wb, item):
    ws = wb.active
    ws.title = "CQ・PICO"
    d = item["draft"]
    rows = [
        ("cq_id", item["cq_id"]),
        ("CQ(分類)", item["_source"]["category"]),
        ("介入/薬剤", item["_source"]["intervention"]),
        ("P(対象)", item["pico"]["P"] or "(委員会で確定)"),
        ("I(介入)", item["pico"]["I"]),
        ("C(対照)", item["pico"]["C"] or "(委員会で確定 comparator_kind参照)"),
        ("comparator_kind", item["comparator_kind"]),
        ("O(アウトカム)", "; ".join(item["pico"]["O"]) or "(下の「エビデンス総体評価」シートで設定)"),
        ("", ""),
        ("── 2023年版(現行)の推奨 ──", ""),
        ("推奨文(原文)", d["recommendation_text"]),
        ("推奨の強さ", STRENGTH_TEXT.get(d["strength"], d.get("strength_label"))),
        ("エビデンスの確実性", CERT_TEXT.get(d["certainty"], d.get("certainty_label"))),
        ("委員会合意率", (f"{round((d['panel_vote'].get('agreement_rate') or 0)*100)}% "
                       f"({d['panel_vote'].get('agreement_n')}/{d['panel_vote'].get('agreement_total')}名)")
                       if d.get("panel_vote", {}).get("agreement_rate") is not None else ""),
        ("引用PMID数(2023年版)", len(d["cited_pmids"])),
    ]
    ws.append(["項目", "内容"])
    for i in range(1, 3):
        ws.cell(row=1, column=i).fill = HEADER_FILL
        ws.cell(row=1, column=i).font = HEADER_FONT
    ws.column_dimensions["A"].width = 26
    ws.column_dimensions["B"].width = 90
    for label, val in rows:
        ws.append([label, val])
    for r in ws.iter_rows(min_row=2):
        r[1].alignment = WRAP
        if r[0].value and str(r[0].value).startswith("──"):
            r[0].fill = NOTE_FILL
            r[1].fill = NOTE_FILL


def sheet_evidence_body(wb, item):
    ws = wb.create_sheet("エビデンス総体評価")
    headers = ["アウトカムID", "アウトカム名", "重要度(1-9)", "研究数",
               "確実性(A/B/C/D)"] + DOWNGRADE_DOMAINS + ["総合評価の要約", "備考(委員記入)"]
    header_row(ws, 1, headers, widths=[10, 20, 10, 8, 14, 16, 14, 14, 12, 16, 40, 30])
    ws.append(["", "(SR担当が Minds 4.4 に沿って記入。'✓'または理由を格下げ列に記入)"])
    ws.cell(row=2, column=1).fill = NOTE_FILL


def sheet_rob2(wb, item):
    ws = wb.create_sheet("個別研究RoB2評価")
    headers = (["PMID", "研究(著者,年)", "対応するアウトカムID", "デザイン",
               "comparator(none/usual_care/placebo/active_weaker/active_different)",
               "適格性(eligible)"] + ROB2_DOMAINS
               + ["2023年版で引用", "新規追加", "備考(委員記入)"])
    header_row(ws, 1, headers, widths=[12, 30, 16, 10, 34, 10, 14, 14, 14, 14, 12, 10, 14, 12, 30])
    r = 2
    for ref in item["references"]:
        ws.cell(row=r, column=1, value=ref["pmid"] or "")
        ws.cell(row=r, column=2, value=ref["citation"][:120])
        ws.cell(row=r, column=2).alignment = WRAP
        ws.cell(row=r, column=13, value="○")   # 2023年版で引用
        r += 1
    ws.append([""] * 13 + ["", "(新規追加論文はここに1行ずつ追記。○を「新規追加」列に)"])


def sheet_references(wb, item):
    ws = wb.create_sheet("文献リスト")
    header_row(ws, 1, ["No", "PMID", "citation(著者・誌名・年)", "papers/収集状況"],
               widths=[6, 12, 100, 16])
    for ref in item["references"]:
        ws.append([ref["no"], ref["pmid"] or "(PMIDなし・和文誌等)", ref["citation"], "未収集"])
    for row in ws.iter_rows(min_row=2):
        row[2].alignment = WRAP


def sheet_vote(wb, item):
    ws = wb.create_sheet("投票")
    d = item["draft"]
    v = d.get("panel_vote", {})
    header_row(ws, 1, ["項目", "2023年版(参考)", "改訂版(今回)"], widths=[24, 30, 30])
    rows = [
        ("推奨の強さ", STRENGTH_TEXT.get(d["strength"], ""), ""),
        ("エビデンスの確実性", CERT_TEXT.get(d["certainty"], ""), ""),
        ("委員会人数", v.get("n_panel", ""), ""),
        ("合意人数/母数", f"{v.get('agreement_n','')}/{v.get('agreement_total','')}", ""),
        ("合意率", f"{round((v.get('agreement_rate') or 0)*100)}%" if v.get("agreement_rate") is not None else "", ""),
        ("棄権(利益相反)", "", ""),
        ("棄権(SR従事)", "", ""),
    ]
    for row in rows:
        ws.append(list(row))
    ws.column_dimensions["C"].fill = NOTE_FILL


def build_workbook(item):
    wb = Workbook()
    sheet_pico(wb, item)
    sheet_evidence_body(wb, item)
    sheet_rob2(wb, item)
    sheet_references(wb, item)
    sheet_vote(wb, item)
    return wb


def write_manifest(item, path):
    d = item["draft"]
    lines = [
        f"# 文献マニフェスト: {item['cq_id']}",
        "",
        f"介入/薬剤: **{item['_source']['intervention']}**"
        f"（{item['_source']['category']}, {item['_source']['cq']}）",
        "",
        "> 論文PDF本体は著作権のため自動収集していません。"
        "下記チェックリストを見ながら、入手できたPDFを `papers/` フォルダに置いてください。"
        "ファイル名は `PMID.pdf`（例: `23549581.pdf`）を推奨します。",
        "",
        "## 2023年版で引用されている文献",
        "",
        "| # | PMID | 収集 | 文献 |",
        "|---|---|---|---|",
    ]
    for ref in item["references"]:
        pmid = ref["pmid"] or "-"
        link = f"[{pmid}](https://pubmed.ncbi.nlm.nih.gov/{pmid}/)" if ref["pmid"] else pmid
        lines.append(f"| {ref['no']} | {link} | ☐ | {ref['citation']} |")
    lines += [
        "",
        "## 新規追加文献(改訂で追加するもの)",
        "",
        "| # | PMID | 収集 | 文献 |",
        "|---|---|---|---|",
        "|  |  | ☐ |  |",
        "",
    ]
    with open(path, "w", encoding="utf-8") as f:
        f.write("\n".join(lines))


def main():
    ap = argparse.ArgumentParser(description="CQパッケージ群 → 委員会レビュー作業一式")
    ap.add_argument("cq_dir", help="extract_cipn_guideline.py の出力先(CQ*.jsonがあるディレクトリ)")
    ap.add_argument("-o", "--outdir", required=True)
    args = ap.parse_args()

    files = sorted(glob.glob(os.path.join(args.cq_dir, "CQ*.json")))
    files = [f for f in files if not os.path.basename(f).startswith("_")]
    os.makedirs(args.outdir, exist_ok=True)

    for fp in files:
        item = json.load(open(fp, encoding="utf-8"))
        cq_dir = os.path.join(args.outdir, item["cq_id"])
        os.makedirs(os.path.join(cq_dir, "papers"), exist_ok=True)

        wb = build_workbook(item)
        wb.save(os.path.join(cq_dir, "minds_review.xlsx"))
        write_manifest(item, os.path.join(cq_dir, "MANIFEST.md"))
        with open(os.path.join(cq_dir, "papers", ".gitkeep"), "w") as f:
            pass
        # 元のCQパッケージ自体もコピーしておく(後でmerge_rob2_evidence.pyが使う)
        with open(os.path.join(cq_dir, "cq_package.json"), "w", encoding="utf-8") as f:
            json.dump(item, f, ensure_ascii=False, indent=2)

        print(f"{item['cq_id']:<28} → {cq_dir}/")

    print(f"\n{len(files)}件のCQ作業一式を {args.outdir}/ に作成しました")


if __name__ == "__main__":
    main()
