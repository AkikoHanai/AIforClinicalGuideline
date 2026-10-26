"""EtDWorksheet（状態）→ DOCX / Markdown（描画）。

描画は状態を一切変更しない。委員記入欄は常に空欄。
DOCX は白黒・装飾なし・Meiryo、横置き A4。
"""

from __future__ import annotations

from pathlib import Path

from . import criteria as C
from .schema import CQRecord, EtDWorksheet

FONT = "Meiryo"
DISCLAIMER = (
    "本ワークシートは既存ガイドライン本文のみを入力として AI が生成した下書きです。"
    "「研究のエビデンス」欄の各文は末尾の段落 ID（付録に原文）で検証できます。"
    "判断欄は委員（パネル）が EtD 審議で決定し、AI 下書きは参考情報として扱ってください。"
)


# ────────────────────────── 共通ヘルパ ──────────────────────────


def _evidence_lines(cd, pmap) -> list[str]:
    lines = []
    for es in cd.research_evidence:
        pages = sorted({pmap[p].page for p in es.passage_ids if p in pmap and pmap[p].page})
        pg = f" p.{'/'.join(map(str, pages))}" if pages else ""
        flag = f" ※{'・'.join(es.flags)}" if es.flags else ""
        lines.append(f"{es.statement} [{', '.join(es.passage_ids)}{pg}]{flag}")
    if not lines and cd.candidate_passage_ids and cd.judgment in (C.TO_BE_JUDGED, C.NO_INFO):
        lines.append("（LLM 補完なし）候補段落: " + ", ".join(cd.candidate_passage_ids))
    if not lines:
        lines.append("旧ガイドラインに該当記載なし")
    return lines


def _cited_ids(ws: EtDWorksheet) -> list[str]:
    ids: list[str] = []
    for cd in ws.criteria:
        for es in cd.research_evidence:
            ids.extend(es.passage_ids)
        ids.extend(cd.candidate_passage_ids)
    return list(dict.fromkeys(ids))


# ────────────────────────── Markdown ──────────────────────────


def to_markdown(ws: EtDWorksheet, cq: CQRecord) -> str:
    pmap = cq.passage_map()
    out = [f"# EtD ワークシート（AI 下書き） {ws.cq_code}", "", f"**CQ**: {ws.cq_title}", ""]
    if ws.pico:
        out += ["**PICO**", ""] + [f"- {k}: {v}" for k, v in ws.pico.items()] + [""]
    c = ws.conclusion
    out += [
        "**旧ガイドラインの推奨（規則抽出）**",
        "",
        f"- 推奨文: {c.old_recommendation_text}",
        f"- 推奨の強さ: {c.old_strength}",
        f"- エビデンスの確実性: {c.old_certainty}",
        f"- 推奨タイプ（読み取り）: {c.recommendation_type_old}",
        "",
        f"生成: {ws.generator} / 状態: {ws.status} / 検証: 除去 {ws.verification.get('n_rejected', 0)} 件, "
        f"エラー {ws.verification.get('n_errors', 0)} 件, 警告 {ws.verification.get('n_warnings', 0)} 件",
        "",
        "| # | 判断基準 | 判断（AI下書き） | 研究のエビデンス（出典） | 追加の考慮事項（委員への論点） | 委員判断 |",
        "|---|---|---|---|---|---|",
    ]
    for crit in C.CRITERIA:
        cd = ws.criterion(crit.id)
        ev = "<br>".join(_evidence_lines(cd, pmap)).replace("|", "｜")
        ac = "<br>".join(cd.additional_considerations).replace("|", "｜") or ""
        flags = f"<br>⚑ {'；'.join(cd.flags)}" if cd.flags else ""
        out.append(f"| {crit.order} | {crit.label_ja}<br><small>{crit.question_ja}</small> | {cd.judgment}{flags} | {ev} | {ac} |  |")
    out += ["", "## 結論（委員記入）", "", "- 推奨タイプ: ＿＿＿＿", "- 推奨文: ＿＿＿＿", "- 正当性の根拠: ＿＿＿＿", ""]
    if c.certainty_to_strength_logic:
        out += [f"旧GLにおける強さの導出（読み取り）: {c.certainty_to_strength_logic}", ""]
    if c.open_questions_for_panel:
        out += ["## 改訂時に委員が確認すべき点", ""] + [f"- {q}" for q in c.open_questions_for_panel] + [""]
    out += ["## 付録: 引用段落の原文", ""]
    for pid in _cited_ids(ws):
        p = pmap.get(pid)
        if p:
            pg = f"（{p.source_file} p.{p.page}）" if p.page else f"（{p.source_file}）"
            out.append(f"**[{pid}]**{pg} {p.text}")
            out.append("")
    out += ["---", DISCLAIMER]
    return "\n".join(out)


# ────────────────────────── DOCX ──────────────────────────


def _set_font(run, size_pt: float, bold: bool = False):
    from docx.oxml.ns import qn
    from docx.shared import Pt

    run.font.name = FONT
    run.font.size = Pt(size_pt)
    run.font.bold = bold
    rpr = run._element.get_or_add_rPr()
    rfonts = rpr.find(qn("w:rFonts"))
    if rfonts is None:
        rfonts = rpr.makeelement(qn("w:rFonts"), {})
        rpr.append(rfonts)
    rfonts.set(qn("w:eastAsia"), FONT)


def _para(doc, text: str, size: float = 9, bold: bool = False):
    p = doc.add_paragraph()
    _set_font(p.add_run(text), size, bold)
    p.paragraph_format.space_after = 0
    return p


def _cell_write(cell, lines: list[str], size: float = 8, bold: bool = False):
    cell.text = ""
    first = True
    for line in lines:
        p = cell.paragraphs[0] if first else cell.add_paragraph()
        first = False
        _set_font(p.add_run(line), size, bold)
        p.paragraph_format.space_after = 0


def to_docx(ws: EtDWorksheet, cq: CQRecord, out_path: str | Path) -> Path:
    from docx import Document
    from docx.enum.section import WD_ORIENT
    from docx.shared import Cm

    pmap = cq.passage_map()
    doc = Document()
    sec = doc.sections[0]
    sec.orientation = WD_ORIENT.LANDSCAPE
    sec.page_width, sec.page_height = Cm(29.7), Cm(21.0)
    for side in ("left_margin", "right_margin", "top_margin", "bottom_margin"):
        setattr(sec, side, Cm(1.5))

    _para(doc, f"EtD ワークシート（AI 下書き）　{ws.cq_code}", 12, True)
    _para(doc, f"CQ: {ws.cq_title}", 9)
    if ws.pico:
        _para(doc, "PICO: " + " / ".join(f"{k}: {v}" for k, v in ws.pico.items()), 8)
    c = ws.conclusion
    _para(doc, f"旧推奨文: {c.old_recommendation_text}", 8)
    _para(doc, f"旧推奨の強さ: {c.old_strength}　旧エビデンス確実性: {c.old_certainty}　推奨タイプ（読み取り）: {c.recommendation_type_old}", 8)
    _para(
        doc,
        f"生成: {ws.generator}　状態: {ws.status}　検証: 除去 {ws.verification.get('n_rejected', 0)} / "
        f"エラー {ws.verification.get('n_errors', 0)} / 警告 {ws.verification.get('n_warnings', 0)}",
        8,
    )
    doc.add_paragraph()

    headers = ["#", "判断基準", "判断（AI下書き）", "研究のエビデンス（出典段落 ID）", "追加の考慮事項（委員への論点）", "委員判断", "委員メモ"]
    widths = [Cm(0.8), Cm(3.6), Cm(3.0), Cm(9.0), Cm(5.6), Cm(2.4), Cm(2.3)]
    table = doc.add_table(rows=1, cols=len(headers))
    table.style = "Table Grid"
    for i, h in enumerate(headers):
        _cell_write(table.rows[0].cells[i], [h], 8, True)
        table.rows[0].cells[i].width = widths[i]
    for crit in C.CRITERIA:
        cd = ws.criterion(crit.id)
        row = table.add_row().cells
        _cell_write(row[0], [str(crit.order)])
        _cell_write(row[1], [crit.label_ja, crit.question_ja])
        jl = [cd.judgment] + ([f"⚑ {f}" for f in cd.flags])
        _cell_write(row[2], jl)
        _cell_write(row[3], _evidence_lines(cd, pmap))
        _cell_write(row[4], cd.additional_considerations or [""])
        _cell_write(row[5], [cd.panel_judgment])
        _cell_write(row[6], [cd.panel_notes])
        for i, w in enumerate(widths):
            row[i].width = w

    doc.add_paragraph()
    _para(doc, "結論（委員記入）", 10, True)
    for lab in ("推奨タイプ", "推奨文", "正当性の根拠", "実施上の考慮事項", "モニタリングと評価", "研究上の優先事項"):
        _para(doc, f"{lab}: ", 9)
    if c.certainty_to_strength_logic:
        _para(doc, f"旧GLにおける推奨の強さの導出（読み取り）: {c.certainty_to_strength_logic}", 8)
    if c.open_questions_for_panel:
        doc.add_paragraph()
        _para(doc, "改訂時に委員が確認すべき点", 10, True)
        for q in c.open_questions_for_panel:
            _para(doc, f"・{q}", 8)

    doc.add_page_break()
    _para(doc, "付録: 引用段落の原文", 10, True)
    for pid in _cited_ids(ws):
        p = pmap.get(pid)
        if p:
            pg = f"（{p.source_file} p.{p.page}）" if p.page else f"（{p.source_file}）"
            _para(doc, f"[{pid}]{pg} {p.text}", 8)
    doc.add_paragraph()
    _para(doc, DISCLAIMER, 7)

    out_path = Path(out_path)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    doc.save(str(out_path))
    return out_path
