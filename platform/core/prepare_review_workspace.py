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
  シート「検索式」               = Minds 3.5 (文献検索式・DB・検索期間の記録)
  シート「CQ・PICO」            = Minds 3.3-3.5 (CQ設定・PICO・アウトカム重要度)
  シート「スクリーニングログ」    = Minds 3.5/4.2 (一次・二次スクリーニング、除外理由、PRISMAフロー用)
  シート「RoB2_評価者1/2」      = Minds 4.3 (個別研究のバイアスリスク評価。2名が独立に記入)
  シート「RoB2_照合」            = Minds 4.3 (2名の評価を自動照合し不一致を検出→委員が確定)
  シート「エビデンス総体評価」    = Minds 4.4 (エビデンス総体の確実性評価)
  シート「文献リスト」           = Minds 3.5/4.2 (適格文献リスト)
  シート「投票」                = Minds 6.2-6.3 (推奨作成の投票)

エビデンス総体評価・RoB2評価シートは空欄で出力する。ここを
ROB2に基づき学生/SR委員が埋めたものを merge_rob2_evidence.py で
CQパッケージ(JSON)に戻し、platform/core/review_bundle.py の
Minds規則検証(R1-R8)にかける設計。
"""
import argparse
import glob
import json
import os
import re

from openpyxl import Workbook
from openpyxl.formatting.rule import CellIsRule
from openpyxl.styles import Alignment, Font, PatternFill
from openpyxl.utils import get_column_letter

HERE = os.path.dirname(os.path.abspath(__file__))

HEADER_FILL = PatternFill("solid", fgColor="1F4E5F")
HEADER_FONT = Font(color="FFFFFF", bold=True)
NOTE_FILL = PatternFill("solid", fgColor="FFF3CD")
WARN_FILL = PatternFill("solid", fgColor="F8D7DA")
MISMATCH_FILL = PatternFill("solid", fgColor="F8D7DA")
WRAP = Alignment(wrap_text=True, vertical="top")

# ------------------------------------------------------------------
# 検索式(委員会から提示されたもの。介入語句部分のみCQごとに変わる)
# DBはPubMedのみ、期間は「前回検索から現在まで」。
# ------------------------------------------------------------------
SEARCH_P = '(((survivor OR (survivor AND cancer) OR "cancer survivor" OR cancer))'
SEARCH_C = ('(neuropathy OR "neuropathy" OR "neuropathies" OR chemotherapy-induced '
            'OR "chemotherapy-induced neuropathy" OR "chemotherapy-induced peripheral neuropathy" '
            'OR CIPN OR peripheral nervous system/drug effects OR peripheral nerve diseases/chemically induced '
            'OR antineoplastic agents/adverse effects OR neoplasms/drug therapy OR neoplasms/complications)')
SEARCH_I_FULL = ('(Goshajinkigan OR (Calcium and Magnesium) OR Acetyl-L-carnitine OR Alpha-lipoic acid '
                  'OR Pregabalin OR gabapentin OR Venlafaxine OR duloxetine OR Vitamin E '
                  'OR Ganglioside-monosialic acid OR amitriptyline/ketamine OR cannabinoid OR nabiximols '
                  'OR LC07 OR cryotherapy OR scrambler therapy)')
SEARCH_DB = "PubMed"
SEARCH_PERIOD = "前回検索日(要確認) 〜 今回検索実施日"

# CQごとに検索式の第3節(介入語)のうち対応する語句。無いCQは
# 「本検索式に個別対応語なし」として要確認フラグを立てる(機械マッチではなく
# 人手で確認した対応表。誤りに気づいたら書き換えてよい)
SEARCH_TERM_MAP = {
    "CQ1-牛車腎気丸": (["Goshajinkigan"], None),
    "CQ1-プレガバリン": (["Pregabalin"], None),
    "CQ1-カルニチン-アセチル‒L‒カルニチン": (["Acetyl-L-carnitine"], None),
    "CQ1-冷却": (["cryotherapy"], None),
    "CQ1-圧迫": ([], "本検索式に圧迫療法(compression)に対応する語がありません。ハンドサーチ等の追加検討が必要です"),
    "CQ1-運動": ([], "本検索式に運動(exercise)に対応する語がありません。ハンドサーチ等の追加検討が必要です"),
    "CQ1-鍼灸": ([], "本検索式に鍼灸(acupuncture)に対応する語がありません。ハンドサーチ等の追加検討が必要です"),
    "CQ2-デュロキセチン": (["duloxetine"], None),
    "CQ2-アミトリプチリン": (["amitriptyline/ketamine"], None),
    "CQ2-プレガバリン": (["Pregabalin", "gabapentin"], None),
    "CQ2-ミロガバリン": (["gabapentin"], "gabapentinoidとしてgabapentin語でヒットする可能性があるが、"
                       "ミロガバリン(mirogabalin)自体の語は含まれていません。担当者で要確認"),
    "CQ2-ビタミン-B12": ([], "検索式には Vitamin E は含まれますが Vitamin B12 は含まれていません。"
                        "担当者は検索式の追加・別途検索を検討してください"),
    "CQ2-非ステロイド性消炎鎮痛薬-NSAIDs": ([], "本検索式にNSAIDsに対応する語がありません。ハンドサーチ等の追加検討が必要です"),
    "CQ2-オピオイド": ([], "本検索式にオピオイドに対応する語がありません(FRQ)。ハンドサーチ等の追加検討が必要です"),
    "CQ2-薬物の併用療法": ([], "本検索式に併用療法に対応する語がありません(FRQ)。ハンドサーチ等の追加検討が必要です"),
    "CQ2-運動": ([], "本検索式に運動(exercise)に対応する語がありません。ハンドサーチ等の追加検討が必要です"),
    "CQ2-鍼灸": ([], "本検索式に鍼灸(acupuncture)に対応する語がありません。ハンドサーチ等の追加検討が必要です"),
}

# CQごとの担当委員2名(2026/09収集の割り振り表より)。RoB2の独立二重評価シートの
# 見出しに使う。ここに無いcq_idは "評価者1"/"評価者2" の汎用名で出力する
REVIEWERS_BY_CQ = {
    "CQ1-牛車腎気丸": ["元雄", "菊池"],
    "CQ1-プレガバリン": ["中島", "伊藤"],
    "CQ1-カルニチン-アセチル‒L‒カルニチン": ["内藤"],
    "CQ1-冷却": ["川口", "上野"],
    "CQ1-圧迫": ["川口", "上野"],
    "CQ1-運動": ["山本", "中川夏樹"],
    "CQ1-鍼灸": ["在原", "田辺"],
    "CQ2-デュロキセチン": ["神林", "武井"],
    "CQ2-アミトリプチリン": ["縄田", "平川"],
    "CQ2-プレガバリン": ["渡辺", "釆野"],
    "CQ2-ミロガバリン": ["渡辺", "釆野"],
    "CQ2-ビタミン-B12": ["坂下", "中川貴之"],
    "CQ2-非ステロイド性消炎鎮痛薬-NSAIDs": ["松岡宏", "松坂"],
    "CQ2-オピオイド": ["高木", "山田"],
    "CQ2-薬物の併用療法": ["宇和川", "佐藤"],
    "CQ2-運動": ["荒尾", "大岩"],
    "CQ2-鍼灸": ["神田", "京田", "草場", "久保"],
}

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


def sheet_search(wb, item):
    ws = wb.active
    ws.title = "検索式"
    terms, warn = SEARCH_TERM_MAP.get(item["cq_id"], ([], "対応表未登録。要確認"))
    ws.append(["項目", "内容"])
    for i in range(1, 3):
        ws.cell(row=1, column=i).fill = HEADER_FILL
        ws.cell(row=1, column=i).font = HEADER_FONT
    ws.column_dimensions["A"].width = 22
    ws.column_dimensions["B"].width = 100
    rows = [
        ("DB", SEARCH_DB),
        ("検索期間", SEARCH_PERIOD),
        ("検索実施日(委員記入)", ""),
        ("検索実施者(委員記入)", ""),
        ("P節(対象)", SEARCH_P),
        ("C節(病態)", SEARCH_C),
        ("I節(介入・全CQ共通の検索式全文)", SEARCH_I_FULL),
        ("本CQに対応する語句", ", ".join(terms) if terms else "(なし)"),
        ("ヒット件数(委員記入)", ""),
        ("重複除去後件数(委員記入)", ""),
    ]
    for label, val in rows:
        ws.append([label, val])
    for r in ws.iter_rows(min_row=2):
        r[1].alignment = WRAP
    if warn:
        ws.append(["⚠要確認", warn])
        ws.cell(row=ws.max_row, column=1).fill = WARN_FILL
        ws.cell(row=ws.max_row, column=2).fill = WARN_FILL
        ws.cell(row=ws.max_row, column=2).alignment = WRAP


def sheet_screening(wb, item):
    ws = wb.create_sheet("スクリーニングログ")
    headers = ["PMID", "タイトル", "出典(検索/ハンドサーチ)",
               "一次スクリーニング(採用/除外/保留)", "一次除外理由",
               "二次スクリーニング(採用/除外)", "二次除外理由", "備考"]
    header_row(ws, 1, headers, widths=[12, 40, 16, 22, 26, 22, 26, 26])
    r = 2
    for ref in item["references"]:
        ws.cell(row=r, column=1, value=ref["pmid"] or "")
        ws.cell(row=r, column=2, value=ref["citation"][:120])
        ws.cell(row=r, column=2).alignment = WRAP
        ws.cell(row=r, column=3, value="2023年版で採用済み")
        ws.cell(row=r, column=4, value="採用")
        ws.cell(row=r, column=6, value="採用")
        r += 1
    ws.append(["", "", "", "", "", "", "",
               "(新規文献はここに1行ずつ追記。除外した文献も理由とともに必ず残す = PRISMAフロー用)"])
    note_row = ws.max_row
    ws.cell(row=note_row, column=8).fill = NOTE_FILL
    ws.cell(row=note_row, column=8).alignment = WRAP
    ws.append(["", "", "", "", "", "", "", ""])
    ws.append(["── 除外理由コードの例 ──", "PICO不一致 / 対象外デザイン(RCT以外等) / "
               "重複掲載 / 全文入手不可 / 会議抄録のみ / その他(備考に記載)", "", "", "", "", "", ""])
    ws.cell(row=ws.max_row, column=1).fill = NOTE_FILL
    ws.cell(row=ws.max_row, column=2).fill = NOTE_FILL
    ws.cell(row=ws.max_row, column=2).alignment = WRAP


def sheet_pico(wb, item):
    ws = wb.create_sheet("CQ・PICO")
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


ROB2_HEADERS = (["PMID", "研究(著者,年)", "対応するアウトカムID", "デザイン",
                 "comparator(none/usual_care/placebo/active_weaker/active_different)",
                 "適格性(eligible)"] + ROB2_DOMAINS
                + ["2023年版で引用", "新規追加", "備考(委員記入)"])
ROB2_WIDTHS = [12, 30, 16, 10, 34, 10, 14, 14, 14, 14, 12, 10, 14, 12, 30]
# D1〜総合(Overall)の列(A=1起点)。照合シートで評価者1/2を突き合わせる対象
ROB2_DOMAIN_COLS = list(range(7, 13))  # G〜L


def _rob2_sheet(wb, title, item):
    ws = wb.create_sheet(title)
    header_row(ws, 1, ROB2_HEADERS, widths=ROB2_WIDTHS)
    r = 2
    for ref in item["references"]:
        ws.cell(row=r, column=1, value=ref["pmid"] or "")
        ws.cell(row=r, column=2, value=ref["citation"][:120])
        ws.cell(row=r, column=2).alignment = WRAP
        ws.cell(row=r, column=13, value="○")   # 2023年版で引用
        r += 1
    ws.append([""] * 13 + ["", "(新規追加論文はここに1行ずつ追記。○を「新規追加」列に)"])
    return ws


def sheet_rob2_pair(wb, item):
    """独立二重レビュー: 評価者1・評価者2が別シートに互いを見ずに記入する"""
    reviewers = REVIEWERS_BY_CQ.get(item["cq_id"], ["評価者1", "評価者2"])
    r1_name = reviewers[0] if len(reviewers) > 0 else "評価者1"
    r2_name = reviewers[1] if len(reviewers) > 1 else "評価者2(未割当)"
    ws1 = _rob2_sheet(wb, f"RoB2_{r1_name}", item)
    ws2 = _rob2_sheet(wb, f"RoB2_{r2_name}", item)
    n_refs = len(item["references"])
    return ws1, ws2, r1_name, r2_name, n_refs


def sheet_rob2_reconcile(wb, item, r1_name, r2_name, n_refs):
    """2名の評価を自動照合し、ドメインごとの不一致を検出する(Minds/コクラン標準の
    独立二重レビュー→照合の手順)。値はすべて評価者シートを参照する数式で、
    このシート自体には手入力しない(確定列だけ委員が記入する)"""
    ws = wb.create_sheet("RoB2_照合")
    headers = ["PMID", "研究", "ドメイン", f"評価者1({r1_name})", f"評価者2({r2_name})",
               "判定", "確定(委員記入・不一致時は協議のうえ決定)"]
    header_row(ws, 1, headers, widths=[12, 34, 20, 16, 16, 10, 34])

    s1, s2 = f"'RoB2_{r1_name}'", f"'RoB2_{r2_name}'"
    row = 2
    for i in range(n_refs):
        src_row = i + 2  # 評価者シート側の行(ヘッダ分+1)
        for col in ROB2_DOMAIN_COLS:
            col_letter = get_column_letter(col)
            domain_label = ROB2_HEADERS[col - 1]
            ws.cell(row=row, column=1, value=f"={s1}!A{src_row}")
            ws.cell(row=row, column=2, value=f"={s1}!B{src_row}")
            ws.cell(row=row, column=3, value=domain_label)
            ws.cell(row=row, column=4, value=f"={s1}!{col_letter}{src_row}")
            ws.cell(row=row, column=5, value=f"={s2}!{col_letter}{src_row}")
            ws.cell(row=row, column=6, value=(
                f'=IF({s1}!{col_letter}{src_row}={s2}!{col_letter}{src_row},'
                f'IF({s1}!{col_letter}{src_row}="","未入力","一致"),"不一致")'
            ))
            row += 1
    last_row = row - 1
    if last_row >= 2:
        ws.conditional_formatting.add(
            f"F2:F{last_row}",
            CellIsRule(operator="equal", formula=['"不一致"'], fill=MISMATCH_FILL),
        )
    for r in ws.iter_rows(min_row=2, max_row=max(last_row, 2)):
        r[1].alignment = WRAP
        r[6].alignment = WRAP
    ws.freeze_panes = "A2"


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
    sheet_search(wb, item)          # active/1枚目
    sheet_pico(wb, item)
    sheet_screening(wb, item)
    _, _, r1, r2, n_refs = sheet_rob2_pair(wb, item)
    sheet_rob2_reconcile(wb, item, r1, r2, n_refs)
    sheet_evidence_body(wb, item)
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
