"""ポータルの記録から、ガイドラインの草案(Word)を作る。標準ライブラリだけを使う。

構成(2023年版の体裁): 作成方法(文献検索、文献選択)、CQ ごとの推奨(推奨文、推奨の強さ、エビデンスの確実性、投票、解説、文献)、FRQ、総論の一覧。
記録のない項目は「未記入」と出す(推測で埋めない)。総論の本文は、執筆者が提出した Word であり、この草案には結合しない。
"""
import io, re, zipfile
from xml.sax.saxutils import escape

FONT = "游明朝"
_RPR = f'<w:rFonts w:ascii="Times New Roman" w:hAnsi="Times New Roman" w:eastAsia="{FONT}"/>'


def _run(text, bold=False, size=21):
    return f'<w:r><w:rPr>{_RPR}{"<w:b/>" if bold else ""}<w:sz w:val="{size}"/></w:rPr><w:t xml:space="preserve">{escape(text)}</w:t></w:r>'


def _p(text, style="", bold=False, size=21):
    ppr = f'<w:pPr><w:pStyle w:val="{style}"/></w:pPr>' if style else ""
    return "".join(f"<w:p>{ppr}{_run(t, bold, size)}</w:p>" for t in (str(text).split("\n") or [""]))


def _tbl(rows):
    b = '<w:tcBorders>' + "".join(f'<w:{s} w:val="single" w:sz="4" w:color="666666"/>' for s in ("top", "left", "bottom", "right")) + '</w:tcBorders>'
    out = ['<w:tbl><w:tblPr><w:tblW w:w="5000" w:type="pct"/></w:tblPr>']; shade = '<w:shd w:val="clear" w:fill="E7E6E6"/>'
    for i, r in enumerate(rows):
        out.append("<w:tr>" + "".join(f"<w:tc><w:tcPr>{b}{shade if i == 0 else ''}</w:tcPr>{_p(c, bold=(i == 0), size=18)}</w:tc>" for c in r) + "</w:tr>")
    return "".join(out) + "</w:tbl><w:p/>"


def docx(blocks):
    """blocks: ("title"|"h1"|"h2"|"p"|"label", 文字列) または ("table", 行の一覧)。Word(docx)のバイト列を返す。"""
    body = []
    for kind, v in blocks:
        if kind == "table": body.append(_tbl(v))
        elif kind == "title": body.append(_p(v, "Title", True, 32))
        elif kind == "h1": body.append(_p(v, "Heading1", True, 28))
        elif kind == "h2": body.append(_p(v, "Heading2", True, 24))
        elif kind == "label": body.append(_p(v, bold=True))
        else: body.append(_p(v))
    ns = 'xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main"'
    doc = f'<?xml version="1.0" encoding="UTF-8" standalone="yes"?><w:document {ns}><w:body>{"".join(body)}<w:sectPr><w:pgSz w:w="11906" w:h="16838"/><w:pgMar w:top="1418" w:right="1418" w:bottom="1418" w:left="1418" w:header="851" w:footer="851" w:gutter="0"/></w:sectPr></w:body></w:document>'
    lv = lambda lvl: "" if lvl is None else '<w:outlineLvl w:val="%d"/>' % lvl
    st = lambda i, name, lvl: f'<w:style w:type="paragraph" w:styleId="{i}"><w:name w:val="{name}"/><w:pPr><w:keepNext/><w:spacing w:before="240" w:after="120"/>{lv(lvl)}</w:pPr></w:style>'
    styles = f'<?xml version="1.0" encoding="UTF-8" standalone="yes"?><w:styles {ns}>{st("Title", "Title", None)}{st("Heading1", "heading 1", 0)}{st("Heading2", "heading 2", 1)}</w:styles>'
    ct = ('<?xml version="1.0" encoding="UTF-8" standalone="yes"?><Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types"><Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>'
          '<Default Extension="xml" ContentType="application/xml"/><Override PartName="/word/document.xml" ContentType="application/vnd.openxmlformats-officedocument.wordprocessingml.document.main+xml"/>'
          '<Override PartName="/word/styles.xml" ContentType="application/vnd.openxmlformats-officedocument.wordprocessingml.styles+xml"/></Types>')
    rels = '<?xml version="1.0" encoding="UTF-8" standalone="yes"?><Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships"><Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" Target="word/document.xml"/></Relationships>'
    drels = '<?xml version="1.0" encoding="UTF-8" standalone="yes"?><Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships"><Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/styles" Target="styles.xml"/></Relationships>'
    b = io.BytesIO()
    with zipfile.ZipFile(b, "w", zipfile.ZIP_DEFLATED) as z:
        for name, data in (("[Content_Types].xml", ct), ("_rels/.rels", rels), ("word/document.xml", doc), ("word/styles.xml", styles), ("word/_rels/document.xml.rels", drels)):
            zi = zipfile.ZipInfo(name, date_time=(2026, 1, 1, 0, 0, 0)); zi.compress_type = zipfile.ZIP_DEFLATED; z.writestr(zi, data)   # 日時を固定する(同じ内容なら、同じファイルになる)
    return b.getvalue()


NONE = "未記入"
cat = lambda it: re.sub(r"\(監修.*?\)$", "", it.get("区分") or "FRQ")


def refs(papers, cands):
    out = []
    for p in papers:
        cd = cands.get(p["pmid"]) or {}
        out.append(". ".join(x for x in (cd.get("authors_all") or cd.get("authors", ""), p.get("title") or cd.get("title", ""), cd.get("journal", ""), cd.get("year", "")) if x) + f". PMID {p['pmid']}")
    return out


def cq_blocks(it, d, with_2023=True):
    """1つの CQ・FRQ の本文。2028年版の記録(推奨文案、解説)があればそれを、なければ 2023年版の記述を、改訂の元の文として置く。"""
    e = d.get("etd") or {}; g = d.get("gl2023") or {}; v = e.get("vote") or {}; frq = it["id"][0] == "F"; B = []
    rec = e.get("rec_draft") or g.get("rec") or NONE; narr = e.get("narrative") or "\n".join(p["text"] for p in g.get("paragraphs") or []) or NONE
    if not e.get("rec_draft") and not e.get("narrative") and g: B.append(("p", "下の推奨文と解説は、2023年版の記述である。改訂して、2028年版の文にする。"))
    B += [("label", "記載" if frq else "推奨文"), ("p", rec)]
    if not frq:
        B.append(("p", f"推奨の強さ: {e.get('strength') or NONE}　エビデンスの確実性: {e.get('certainty') or NONE}"))
        B.append(("p", f"投票: 第{v['round']}回、参加 {v.get('denominator', '')} / {v.get('eligible', '')} 名、最多の選択肢 {v.get('agreement', '')}%" if v.get("round") else "投票: 記録なし"))
    B += [("label", "解説"), ("p", narr), ("label", "文献")]
    B += [("p", f"{i}) {r}") for i, r in enumerate(refs(d.get("papers") or [], d.get("cands") or {}), 1)] or [("p", "採用した論文の登録: なし")]
    if with_2023 and g and (e.get("rec_draft") or e.get("narrative")):
        B += [("label", "参考: 2023年版の推奨文"), ("p", g.get("rec") or ""), ("p", f"推奨の強さ: {g.get('strength', '')}　エビデンスの確実性: {g.get('certainty', '')}")]
    return B


def build_cq(title, it, d):
    """CQ・FRQ の Update 版(Word)。共有ドライブで、委員が編集する。"""
    return docx([("p", title), ("title", f"{cat(it)}: {it['名称']}")] + cq_blocks(it, d))


def from_view(view, body_only=False):
    """画面表示用に読み取った文書(viewer.docx_view の結果)を、この草案の本文の並びにする。body_only: 総論の依頼書の「2023年版の全文」より前(依頼の文)を除く。"""
    blocks = view.get("blocks") or []
    if body_only:
        i = next((k for k, b in enumerate(blocks) if b["t"] in ("h1", "h2", "h3") and "2023年版の全文" in b.get("text", "")), None)
        if i is not None: blocks = [b for b in blocks[i + 1:] if not str(b.get("text", "")).startswith("事務局からの注記")]
    out = []
    for b in blocks:
        if b["t"] == "table": out.append(("table", [[c.get("v", "") for c in r] for r in b["rows"]]))
        elif b["t"] in ("title", "h1", "h2", "h3"): out.append(("label", b["text"]))
        elif b["t"] == "li": out.append(("p", "・" + b["text"]))
        else: out.append(("p", b["text"]))
    return out


def build(title, items, data, soron, units=None):
    """items: 企画書の SR項目・FRQ項目(順序どおり)。data[id]: {"etd", "gl2023", "papers", "cands", "searches", "flow"}。soron: 総論の一覧。
    units: 共有ドライブで編集された Update 版や、提出された原稿の本文({"soron/A": 本文の並び, "cq/P1": …})。あれば、それを本文にする。"""
    units = units or {}
    B = [("title", title), ("p", "草案(ポータルの記録と、Update 版の本文から出力)"), ("h1", "1. 作成方法"), ("h2", "1.1 文献検索")]
    rows = [["CQ・FRQ", "データベース", "検索日", "検索期間", "件数"]]
    for it in items:
        for s_ in data[it["id"]]["searches"]: rows.append([it["名称"], s_.get("database", ""), s_.get("date", ""), s_.get("period", ""), str(s_.get("hits", ""))])
    B += [("table", rows)] if len(rows) > 1 else [("p", "検索の記録: なし")]
    B.append(("h2", "1.2 文献選択"))
    B.append(("table", [["CQ・FRQ", "検索で得た文献", "一次スクリーニングの対象", "二次スクリーニングの対象", "採用"]] + [[it["名称"]] + [str(data[it["id"]]["flow"].get(k, 0)) for k in ("db_hits", "s1_target", "s2_target", "s2_include")] for it in items]))
    B.append(("h1", "2. 総論"))
    for s_ in soron:
        B.append(("h2", f"{s_.get('label', '')}. {s_.get('title', '')}"))
        B += units.get(f"soron/{s_['key']}") or [("p", NONE)]
    for head, frq in (("3. 推奨(CQ)", False), ("4. FRQ(Future Research Question)", True)):
        B.append(("h1", head))
        for it in [x for x in items if (x["id"][0] == "F") == frq]:
            B.append(("h2", f"{cat(it)}: {it['名称']}"))
            B += units.get(f"cq/{it['id']}") or cq_blocks(it, data[it["id"]], with_2023=False)
    return docx(B)
