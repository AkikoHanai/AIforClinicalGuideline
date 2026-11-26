"""文書(xlsx・docx)を、ブラウザで表示するための構造(JSON)に変換する。

「Scope」「手順書」の画面の「開く」は、ファイルをダウンロードさせずに、この構造を画面に描く。
- xlsx: シートごとの行と列。結合セルは rs(行)・cs(列)で表す。結合の内側のセルは None。
- docx: 見出し・段落・箇条書き・表の並び。
"""
import io, re, zipfile
import xml.etree.ElementTree as ET
import openpyxl
from openpyxl.utils import get_column_letter

W = "{http://schemas.openxmlformats.org/wordprocessingml/2006/main}"
THEME_FILL = "#dbe5f1"   # テーマ色の塗り(Minds のテンプレートの見出しセル)。テーマの定義は読まず、この色で表す


def _text(v):
    if v is None: return ""
    if isinstance(v, float) and v.is_integer(): return str(int(v))
    s = str(v)
    return "" if s.startswith("=") else s   # 数式は、計算結果が保存されていないため表示しない


def _fill(cell):
    f = cell.fill
    if not f or f.fill_type != "solid": return ""
    c = f.fgColor
    if c.type == "rgb" and isinstance(c.rgb, str) and len(c.rgb) == 8 and c.rgb[2:].upper() != "FFFFFF": return "#" + c.rgb[2:].lower()
    return THEME_FILL if c.type == "theme" else ""


def _bordered(cell):
    b = cell.border
    return bool(b and any(getattr(s, "style", None) for s in (b.left, b.right, b.top, b.bottom)))


def xlsx_view(data):
    wb = openpyxl.load_workbook(io.BytesIO(data)); sheets = []
    for ws in wb.worksheets:
        if ws.sheet_state != "visible": continue
        span, inner = {}, set()
        for rng in ws.merged_cells.ranges:
            span[(rng.min_row, rng.min_col)] = (rng.max_row - rng.min_row + 1, rng.max_col - rng.min_col + 1)
            inner |= {(r, c) for r in range(rng.min_row, rng.max_row + 1) for c in range(rng.min_col, rng.max_col + 1)} - {(rng.min_row, rng.min_col)}
        last_r = last_c = 0   # 表示する範囲: 値・罫線・塗りのあるセルまで
        for row in ws.iter_rows():
            for c in row:
                if c.value is not None or _bordered(c) or _fill(c):
                    rs, cs = span.get((c.row, c.column), (1, 1)); last_r = max(last_r, c.row + rs - 1); last_c = max(last_c, c.column + cs - 1)
        widths = {}
        for d in ws.column_dimensions.values():
            for i in range(d.min or 0, (d.max or 0) + 1):
                if d.width: widths[i] = d.width
        rows = []
        for r in range(1, last_r + 1):
            if ws.row_dimensions[r].hidden: continue
            line = []
            for c in range(1, last_c + 1):
                if (r, c) in inner: line.append(None); continue
                cell = ws.cell(row=r, column=c); o = {}
                v = _text(cell.value)
                if v: o["v"] = v
                rs, cs = span.get((r, c), (1, 1))
                if rs > 1: o["rs"] = rs
                if cs > 1: o["cs"] = cs
                if cell.font and cell.font.b: o["b"] = 1
                bg = _fill(cell)
                if bg: o["bg"] = bg
                if _bordered(cell): o["bd"] = 1
                if cell.alignment and cell.alignment.horizontal == "center": o["al"] = "center"
                if v and (rs, cs) == (1, 1) and not (cell.alignment and cell.alignment.wrap_text): o["_need"] = 1.3 * sum(2 if ord(ch) > 0x2E80 else 1 for ch in max(v.split("\n"), key=len))   # 画面の字幅の余裕を見込む
                line.append(o)
            # 折り返しのないセルの文字は、Excel と同じく、右の空のセルにはみ出して表示する(狭い列の見出しが、縦に折り返されないように)
            for i, o in enumerate(line):
                need = (o or {}).pop("_need", 0); have = float(widths.get(i + 1, 8.43)); k = i + 1
                while k < len(line) and line[k] is not None and not ({"v", "rs", "cs"} & set(line[k])) and (need > have or (need and o.get("bg") and line[k].get("bg") == o["bg"])):   # 見出しの帯(同じ塗り)は、帯の端まで
                    have += float(widths.get(k + 1, 8.43)); o["bd"] = o.get("bd") or line[k].get("bd"); line[k] = None; o["cs"] = o.get("cs", 1) + 1; k += 1
                if o is not None and not o.get("bd"): o.pop("bd", None)
            rows.append(line)
        sheets.append({"name": ws.title, "cols": [round(float(widths.get(i, 8.43)), 1) for i in range(1, last_c + 1)], "rows": rows})
    return {"kind": "xlsx", "sheets": sheets}


def _para_text(p):
    out = []
    for el in p.iter():
        if el.tag == W + "t": out.append(el.text or "")
        elif el.tag in (W + "br", W + "cr"): out.append("\n")
        elif el.tag == W + "tab": out.append(" ")
    return "".join(out)


def _para(p):
    ppr = p.find(W + "pPr"); style = ""; listed = False
    if ppr is not None:
        st = ppr.find(W + "pStyle"); style = st.get(W + "val", "") if st is not None else ""
        listed = ppr.find(W + "numPr") is not None
    text = _para_text(p)
    m = re.match(r"(?:Heading|見出し)\s*(\d)", style)
    kind = "title" if style == "Title" else f"h{min(int(m.group(1)), 3)}" if m else "li" if listed else "p"
    runs = [r for r in p.iter(W + "r") if _para_text(r).strip()]
    bold = bool(runs) and all(r.find(W + "rPr") is not None and r.find(W + "rPr").find(W + "b") is not None for r in runs)
    o = {"t": kind, "text": text}
    if bold and kind == "p": o["b"] = 1
    return o


def _table(tbl):
    rows = []
    for tr in tbl.findall(W + "tr"):
        line = []
        for tc in tr.findall(W + "tc"):
            pr = tc.find(W + "tcPr"); o = {"v": "\n".join(_para_text(p) for p in tc.findall(W + "p")).strip()}
            if pr is not None:
                gs = pr.find(W + "gridSpan"); shd = pr.find(W + "shd")
                if gs is not None and int(gs.get(W + "val", "1")) > 1: o["cs"] = int(gs.get(W + "val"))
                fill = shd.get(W + "fill", "") if shd is not None else ""
                if re.fullmatch(r"[0-9A-Fa-f]{6}", fill) and fill.upper() != "FFFFFF": o["bg"] = "#" + fill.lower()
            line.append(o)
        rows.append(line)
    return {"t": "table", "rows": rows}


def docx_view(data):
    body = ET.fromstring(zipfile.ZipFile(io.BytesIO(data)).read("word/document.xml")).find(W + "body"); blocks = []
    for el in list(body) if body is not None else []:
        if el.tag == W + "p":
            b = _para(el)
            if b["text"].strip(): blocks.append(b)
        elif el.tag == W + "tbl": blocks.append(_table(el))
    return {"kind": "docx", "blocks": blocks}


def view(name, data):
    return xlsx_view(data) if name.lower().endswith(".xlsx") else docx_view(data)
