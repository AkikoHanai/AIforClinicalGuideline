"""2023年版(刊行版 PDF)の第2章 総論を、2028年版の担当単位に切り出す。前版の全文を、原文のまま引用するための処理。
  cd platform/soron && python3 extract_soron.py <2023年版PDF> && node build_docx.js     # → out/*.docx、../data/gl2023/units.json
必要: pypdf、poppler(pdftoppm、pdftotext)、ImageMagick(convert)。

方法
 1. 文字は PDF の文字層から、書体と大きさで役割を決める(本文=リュウミン 9.2、文献=リュウミン 7.8、見出し=新ゴ、表と図の文字=ゴシック)。
    柱(ページ上部)、つめ(右端の「第2章 総論」)、透かし(無断転載禁止)は除く。
 2. 段落は、行頭の全角空白(字下げ)で区切る。行をまたぐ語は、原文の語に戻す(行末のハイフンで分かれた英単語をつなぐ)。
 3. 表と図は、ページの画像から該当の範囲を切り出して、原文の位置に置く(体裁をそのまま示す)。表と図の文字は、画像の下に文字でも示す。
 4. 検証: 別の方法(pdftotext)で取り出した文字と照合し、落ちた文字がないことを単位ごとに記録する(verify.json)。

文字の扱い(内容は変えない)
 - 和文と英数字の間の空白(組版上のアキ)は入れない。英単語の間の空白は残す。
 - 英数字の間の「—」は、印刷上のハイフンなので「-」にする(例: 180—90 → 180-90)。
 - 文献番号(例: 1）)は上付きにする。
"""
import collections, json, logging, math, os, re, subprocess, sys

logging.getLogger("pypdf").setLevel(logging.CRITICAL)
from pypdf import PdfReader

PDF = sys.argv[1] if len(sys.argv) > 1 else "../../CIPNGL2023.pdf"
HERE = os.path.dirname(os.path.abspath(__file__))
FIG = os.path.join(HERE, "fig"); os.makedirs(FIG, exist_ok=True)
OFFSET = 12  # 本のページ = PDF のページ - 12

# 章(2023年版の A〜M)。(2023年版の記号, PDF の開始ページ, 終了ページ)
CHAPTERS = [("A", 22, 24), ("B", 25, 25), ("C", 26, 26), ("D", 27, 28), ("E", 29, 30), ("F", 31, 31), ("G", 32, 34), ("H", 35, 39),
            ("I", 40, 49), ("J", 50, 62), ("L", 65, 66), ("M", 67, 68)]
# 2028年版の担当単位(企画書の総論の記号) ← 2023年版の章と、章の中の節(見出しの正規表現)。
# 2023年版の K(海外ガイドラインの紹介、pp.51–52)は、2028年版では扱わない(統括委員長の決定 2026-11-16)。切り出さない。
# 2028年版の K(漢方・鍼灸治療)と N(小児患者のCIPN対策)は新設で、2023年版に本文がない。
UNITS = [("A", "A", None), ("B", "B", None), ("C", "C", None), ("D", "D", None), ("E", "E", None), ("F", "F", None), ("G", "G", None), ("H", "H", None),
         ("I_1", "I", r"^1．"), ("I_2", "I", r"^2．"), ("J_1", "J", r"^1．"), ("J_2", "J", r"^2．"), ("J_3", "J", r"^3．"), ("J_4", "J", r"^4．"), ("J_5", "J", r"^5．"),
         ("L", "L", None), ("M", "M", None)]

JP = r"　-ヿ㐀-鿿＀-￯"
AN = "A-Za-z0-9α-ωΑ-Ω"


def fix_dash(t):
    """英数字・ギリシャ文字に接する「—」は、印刷上のハイフンなので「-」にする(「——」と、和文どうしの間の「—」は残す)。"""
    def f(m):
        left = m.string[m.start() - 1] if m.start() > 0 else ""; right = m.string[m.end()] if m.end() < len(m.string) else ""
        if not (re.match(f"[{AN}）]", left) or re.match(f"[{AN}]", right)): return m.group(0)
        return "-" + (" " if m.group(2) and re.match("[A-Za-z]", right) else "")
    return re.sub(r"(?<!—)( ?)—(?!—)( ?)", f, t)


def norm(s):
    """組版上の空白を除く。内容は変えない。"""
    s = s.replace("\t", " ").replace(" ", " ")
    s = re.sub(r" {2,}", " ", s)
    s = re.sub(rf"(?<=[{JP}]) +| +(?=[{JP}])", "", s)       # 和文・全角記号の隣の空白
    s = fix_dash(s)                                      # 英数字に続く「—」は印刷上のハイフン
    return s.strip(" ")


def glue(prev, nxt):
    """行をまたぐ文字列のつなぎ方: (前の行の末尾を直したもの, 次の行の先頭を直したもの)。"""
    a, b = prev.rstrip(" "), nxt.lstrip(" ")
    if not a or not b: return a, b
    if re.search(r"[A-Za-z]-$", a) and re.match(r"[a-z]", b):   # 行末のハイフンで分かれた英単語
        return a[:-1], b
    if re.search(r"[A-Za-z0-9,.;:)\]]$", a) and re.match(r"[A-Za-z0-9(\[]", b):
        return a + " ", b
    return a, b


def page_chunks(reader, pn):
    """1ページの文字のかたまり: (y, 順番, x, 大きさ, 書体, 文字)。y は上からの位置(pt)。"""
    pg = reader.pages[pn - 1]; H = float(pg.mediabox.height); out = []

    def v(t, cm, tm, fd, fs):
        if not t or not t.strip(): return
        a, b, c, d, e, f = tm; ca, cb, cc, cd, ce, cf = cm
        X = ca * e + cc * f + ce; Y = cb * e + cd * f + cf
        size = round(fs * math.hypot(a, b) * math.hypot(ca, cb), 1)
        font = ((fd or {}).get("/BaseFont") or "?").split("+")[-1].lstrip("/")
        out.append((round(H - Y, 1), len(out), round(X, 1), size, font, t.replace("\x07", " ")))

    pg.extract_text(visitor_text=v)
    return out


def role(y, x, size, font, text):
    t = text.strip()
    if font == "MSPGothic": return None                       # 透かし
    if y < 50: return None                                    # 柱
    if font == "UDShinGoPr6-Light" and size <= 8: return None  # 柱・つめ
    if font == "UDShinGoPr6-Medium" and size <= 7: return None  # つめ(第 2 章)
    if font == "TimesLTStd-BoldItalic": return None            # つめの数字
    if size >= 20 and font.startswith("UDShinGo"): return "chapter"   # 次の章の扉
    if font == "TimesLTStd-SemiboldItalic" and size >= 20: return "letter"
    if font == "UDShinGoPr6-Medium" and size >= 13: return "title"
    if font == "UDShinGoPr6-Medium" and 10.5 <= size < 13: return "h2"
    if font == "UDShinGoPr6-Regular" and 9.5 <= size < 10.5: return "h3"
    if font.startswith("Ryumin") and 9.0 <= size <= 9.4: return "body"
    if font == "UDShinGoPr6-Regular" and 9.0 <= size <= 9.4: return "bodyb"     # 本文中の「表1」「図1」(太字)
    if font.startswith("Ryumin") and 7.5 <= size <= 8.0: return "ref"
    if font.startswith("Ryumin") and 8.2 <= size <= 8.8: return "sign" if re.fullmatch(r"（[^（）]{2,24}）", t) else "note"   # 執筆者名、または小さい字の注
    if font == "UDShinGoPr6-Regular" and 8.2 <= size <= 8.8 and t == "文献": return "refhead"
    return "band"                                             # 表・図の文字、注


# 文字層が壊れている箇所の訂正。紙面の画像から読み取った文字に置き換える(検証の対象外になるので、統括委員長が紙面で確認する)。
# (章, 壊れた文字列の正規表現, 紙面の文字, 場所)
CORRECTIONS = [("I", r"10）篠\u3000美紀，滝口修平，[\U0002F8ED]+，[\U0002F8ED]+．薬剤性嗅覚障害の臨床的[\U0002F8ED]+．日[\U0002F8ED]+と[\U0002F8ED]+会[\U0002F8ED]+．",
                "10）篠\u3000美紀，滝口修平，櫛橋幸民，他．薬剤性嗅覚障害の臨床的検討．日味と匂会誌．", "2023年版 p.37 文献 10")]

BULLET = re.compile(r"^[・●■◆▶＊※]")
ENUM = re.compile(r"^[①-⑳]")


def crop(pn, top, bottom, name):
    """ページの画像から、縦の範囲 top〜bottom(pt)を切り出し、余白を落とす。"""
    r = 200; k = r / 72.0; x0, x1 = 62, 464
    out = os.path.join(FIG, name)
    subprocess.run(["pdftoppm", "-png", "-r", str(r), "-f", str(pn), "-l", str(pn), "-x", str(int(x0 * k)), "-y", str(int(top * k)), "-W", str(int((x1 - x0) * k)), "-H", str(int((bottom - top) * k)),
                    "-singlefile", PDF, out[:-4]], capture_output=True)
    subprocess.run(["convert", out, "-fuzz", "2%", "-trim", "+repage", "-bordercolor", "white", "-border", "8", out], capture_output=True)
    wh = subprocess.run(["identify", "-format", "%w %h", out], capture_output=True, text=True).stdout.split()
    return {"file": os.path.relpath(out, HERE), "w": int(wh[0]), "h": int(wh[1])} if len(wh) == 2 else None


# ---------- 表を、編集できる表として組み立てる(罫線と文字の位置から) ----------
def _mul(m, n):
    a, b, c, d, e, f = m; A, B, C, D, E, F = n
    return (a * A + b * C, a * B + b * D, c * A + d * C, c * B + d * D, e * A + f * C + E, e * B + f * D + F)


_SEGS, _WORDS = {}, {}


def page_segments(reader, pn):
    """ページの罫線と塗り: (種類 S=線/f=塗り, x0, y0, x1, y1)。y は上から。ページの中の部品(Form XObject)も読む。"""
    if pn in _SEGS: return _SEGS[pn]
    from pypdf.generic import ContentStream
    pg = reader.pages[pn - 1]; H = float(pg.mediabox.height); segs = []

    def walk(stream, resources, ctm, depth):
        try: cs = ContentStream(stream, reader)
        except Exception: return
        stack = []; path = []; cur = None
        for operands, op in cs.operations:
            op = op.decode() if isinstance(op, bytes) else op
            tp = lambda x, y: (ctm[0] * x + ctm[2] * y + ctm[4], H - (ctm[1] * x + ctm[3] * y + ctm[5]))
            if op == "q": stack.append(ctm)
            elif op == "Q": ctm = stack.pop() if stack else ctm
            elif op == "cm": ctm = _mul(tuple(float(x) for x in operands), ctm)
            elif op == "re":
                x, y, w, h = [float(v) for v in operands]; p1 = tp(x, y); p2 = tp(x + w, y + h)
                path.append((min(p1[0], p2[0]), min(p1[1], p2[1]), max(p1[0], p2[0]), max(p1[1], p2[1])))
            elif op == "m": cur = tp(float(operands[0]), float(operands[1]))
            elif op == "l":
                q = tp(float(operands[0]), float(operands[1]))
                if cur: path.append((min(cur[0], q[0]), min(cur[1], q[1]), max(cur[0], q[0]), max(cur[1], q[1])))
                cur = q
            elif op in ("S", "s", "f", "F", "f*", "B", "B*", "b", "b*"):
                segs.extend(("S" if op in ("S", "s") else "f",) + t for t in path); path = []
            elif op == "n": path = []
            elif op == "Do" and depth < 4:
                xo = (resources.get("/XObject") or {}).get(operands[0]) if resources else None
                xo = xo.get_object() if xo is not None else None
                if xo is not None and xo.get("/Subtype") == "/Form":
                    walk(xo, xo.get("/Resources") or resources, _mul(tuple(float(v) for v in xo.get("/Matrix", [1, 0, 0, 1, 0, 0])), ctm), depth + 1)

    walk(pg.get_contents(), pg.get("/Resources"), (1, 0, 0, 1, 0, 0), 0)
    _SEGS[pn] = segs
    return segs


def page_words(pn):
    """ページの語と位置: (x0, y0, x1, y1, 文字)。柱、つめ、透かしは除く。"""
    if pn in _WORDS: return _WORDS[pn]
    import html
    x = subprocess.run(["pdftotext", "-bbox-layout", "-f", str(pn), "-l", str(pn), PDF, "-"], capture_output=True, text=True).stdout
    out = []
    for m in re.finditer(r'<word xMin="([\d.]+)" yMin="([\d.]+)" xMax="([\d.]+)" yMax="([\d.]+)">(.*?)</word>', x):
        w = (float(m.group(1)), float(m.group(2)), float(m.group(3)), float(m.group(4)), html.unescape(m.group(5)).replace("\x07", " ").strip())
        if w[4] and w[3] > 52 and w[0] < 462 and "無断転載禁止" not in w[4] and "©JASCC" not in w[4]: out.append(w)
    _WORDS[pn] = out
    return out


def _uniq(vals, tol):
    out = []
    for v in sorted(vals):
        if not out or v - out[-1] > tol: out.append(v)
    return out


def _cell_text(words):
    """セルの中の語を、行ごとに並べてつなぐ。小さい上付き(＊1 など)は、直後の行の該当位置に入れる。"""
    normal = [w for w in words if w[3] - w[1] > 9.5]; tiny = [w for w in words if w[3] - w[1] <= 9.5]
    lines = []
    for w in sorted(normal, key=lambda w: (w[3], w[0])):
        if lines and abs(w[3] - lines[-1][0]) <= 4: lines[-1][1].append(w)
        else: lines.append([w[3], [w]])
    for t in tiny:
        host = next((ln for ln in lines if -1 <= ln[0] - t[3] <= 9), None)
        if host: host[1].append(t)
        else: lines.append([t[3], [t]])
    text = ""
    for _, ws in sorted(lines, key=lambda ln: ln[0]):
        line = ""
        for w in sorted(ws, key=lambda w: w[0]):
            line += (" " if re.search(r"[A-Za-z0-9,.;:%)]$", line) and re.match(r"[A-Za-z0-9(]", w[4]) else "") + w[4]
        a, b = glue(text, line); text = a + b
    return norm(text)


def band_tables(reader, pn, top, bottom, captions, continued):
    """表・図の範囲から、表を組み立てる。captions: [(y, 文字)]。continued: 前のページから続く表か。
    戻り値: (表の一覧, 表が占める縦の範囲の一覧)。表: {caption, widths, rows[[{text, span, shade}]], notes, continued}"""
    segs = [s for s in page_segments(reader, pn) if top - 2 <= s[2] <= bottom + 4 and 60 <= s[1] and s[3] <= 466]
    hs = [(s[2], s[1], s[3]) for s in segs if s[4] - s[2] < 1.6 and s[3] - s[1] > 12]
    if not hs: return [], []
    def grids_in(r0, r1):
        """縦の範囲 r0〜r1 にある横線を、横につながるまとまり(表の本体)に分ける"""
        sel = [h for h in hs if r0 <= h[0] <= r1]; spans = []; out = []
        for _, x0, x1 in sorted(sel, key=lambda h: h[1]):
            if spans and x0 <= spans[-1][1] + 6: spans[-1][1] = max(spans[-1][1], x1)
            else: spans.append([x0, x1])
        for X0, X1 in spans:
            mine = [h for h in sel if h[1] >= X0 - 1 and h[2] <= X1 + 1]
            ys = _uniq([h[0] for h in mine], 1.0)
            if len(ys) >= 2: out.append({"x0": X0, "x1": X1, "ys": ys, "cols": _uniq([v for h in mine for v in (h[1], h[2])], 2.5)})
        return out

    caps = sorted(captions)
    regions = []   # (開始 y, 終了 y, 表の題)
    for n, (cy, ct) in enumerate(caps):
        if ct.startswith("表"): regions.append((cy - 12, caps[n + 1][0] - 12 if n + 1 < len(caps) else bottom + 4, ct))
    if not caps and continued: regions.append((top - 2, bottom + 4, ""))
    words = [w for w in page_words(pn) if top - 2 <= (w[1] + w[3]) / 2 <= bottom + 4]
    tables, used = [], []
    for r0, r1, cap in regions:
        gs = [g for g in grids_in(r0 + (10 if cap else 0), r1) if not cap or g["ys"][0] - (r0 + 12) < 40]
        if not gs: continue
        gs.sort(key=lambda g: g["x0"]); table_rows = []; ncols = None; widths = None; g_bottom = max(g["ys"][-1] for g in gs)
        for g in gs:
            cols = g["cols"]; n = len(cols) - 1
            if ncols is None: ncols, widths = n, [cols[k + 1] - cols[k] for k in range(n)]
            elif n != ncols: continue            # 列の数が違う本体は、別の表として扱わず、この表には入れない
            vs = [s for s in segs if s[3] - s[1] < 1.6 and s[4] - s[2] > 6 and g["x0"] + 3 < s[1] < g["x1"] - 3]
            fills = [s for s in segs if s[0] == "f" and s[4] - s[2] >= 1.6 and s[1] >= g["x0"] - 1.5 and s[3] <= g["x1"] + 1.5]
            gw = [w for w in words if g["x0"] - 2 <= (w[0] + w[2]) / 2 <= g["x1"] + 2]
            col_of = lambda w: max(0, min(n - 1, sum(1 for c in cols[1:-1] if (w[0] + min(w[2], w[0] + 12)) / 2 >= c)))
            for k in range(len(g["ys"]) - 1):
                y0, y1 = g["ys"][k], g["ys"][k + 1]
                bw = [w for w in gw if y0 - 0.5 <= (w[1] + w[3]) / 2 < y1 - 0.5]
                if not bw: continue
                shade = any(abs(f[2] - y0) < 1.5 and abs(f[4] - y1) < 1.5 for f in fills)
                # 結合セル: この行の塗りが、列より少ない数で表の幅を埋めている場合
                cellsx = _uniq([v for f in fills if abs(f[2] - y0) < 1.5 and abs(f[4] - y1) < 1.5 for v in (f[1], f[3])], 2.5)
                merged = None
                if len(cellsx) >= 2 and abs(cellsx[0] - cols[0]) < 3 and abs(cellsx[-1] - cols[-1]) < 3 and len(cellsx) - 1 < n:
                    merged = [(cellsx[j], cellsx[j + 1], sum(1 for c in cols[:-1] if cellsx[j] - 2.5 <= c < cellsx[j + 1] - 2.5)) for j in range(len(cellsx) - 1)]
                single = merged is not None or any(min(v[4], y1) - max(v[2], y0) >= 0.8 * (y1 - y0) for v in vs)
                if single:
                    if merged: row = [{"text": _cell_text([w for w in bw if a - 2 <= (w[0] + w[2]) / 2 < b + 2]), "span": sp, "shade": shade} for a, b, sp in merged if sp > 0]
                    else: row = [{"text": _cell_text([w for w in bw if col_of(w) == c]), "span": 1, "shade": shade} for c in range(n)]
                    table_rows.append(row); continue
                # 罫線のない範囲: 1 列目に文字がある行が、行の始まり。1 列目が空の行は、前の行の続き
                lines = []
                for w in sorted([w for w in bw if w[3] - w[1] > 9.5], key=lambda w: w[3]):
                    if lines and w[3] - lines[-1][0] <= 9: lines[-1][1].append(w); lines[-1][0] = max(lines[-1][0], w[3]) if w[3] - lines[-1][2] <= 9 else lines[-1][0]
                    else: lines.append([w[3], [w], w[3]])
                groups = []
                for _, ws, _ in lines:
                    if groups and not any(col_of(w) == 0 for w in ws): groups[-1].extend(ws)
                    else: groups.append(list(ws))
                for t in [w for w in bw if w[3] - w[1] <= 9.5]:       # 上付きは、直後の行に入れる
                    host = next((gr for gr in groups if any(-1 <= w[3] - t[3] <= 9 for w in gr)), groups[-1] if groups else None)
                    if host is not None: host.append(t)
                for gr in groups:
                    table_rows.append([{"text": _cell_text([w for w in gr if col_of(w) == c]), "span": 1, "shade": shade} for c in range(n)])
        # 表の下の注
        notes = []
        g_top = min(g["ys"][0] for g in gs)
        inside = lambda w: any(g["x0"] - 2 <= (w[0] + w[2]) / 2 <= g["x1"] + 2 and g["ys"][0] - 1 <= (w[1] + w[3]) / 2 <= g["ys"][-1] + 1 for g in gs)
        nw = [w for w in words if g_top < (w[1] + w[3]) / 2 <= r1 and not inside(w)]     # 表の本体の外(下、または短い側の下)にある文字
        nl = []
        for w in sorted([w for w in nw if w[3] - w[1] > 9.5], key=lambda w: (w[3], w[0])):
            if nl and abs(w[3] - nl[-1][0]) <= 4: nl[-1][1].append(w)
            else: nl.append([w[3], [w]])
        for t in [w for w in nw if w[3] - w[1] <= 9.5]:
            host = next((ln for ln in nl if -1 <= ln[0] - t[3] <= 9), None)
            if host: host[1].append(t)
        for _, ws in nl:
            line = ""
            for w in sorted(ws, key=lambda w: w[0]):
                line += (" " if re.search(r"[A-Za-z0-9,.;:%)]$", line) and re.match(r"[A-Za-z0-9(]", w[4]) else "") + w[4]
            notes.append(norm(line))
        if table_rows:
            tables.append({"caption": norm(cap), "widths": widths, "rows": table_rows, "notes": notes, "continued": not cap})
            used.append((r0, max([g_bottom + 3] + [w[3] + 2 for w in nw])))
    return tables, used


def chapter_blocks(reader, letter, p0, p1):
    """1章を、原文の順のブロックにする。"""
    blocks = []
    cur = {"t": None, "runs": [], "indent": False, "x0": None, "hang": False}   # 作成中の段落(本文 p、文献 ref、注 note)
    pending = []                                      # 段落の途中に現れた表・図(段落の終わりに置く)
    st = {"last_y": None, "block_left": None, "tail_table": False}

    def text_so_far():
        return "".join(r[0] for r in cur["runs"])

    def flush():
        if cur["t"] and text_so_far().strip():
            blocks.append({"t": cur["t"], "runs": [list(r) for r in cur["runs"]], "indent": cur["indent"]})
        cur["t"] = None; cur["runs"] = []; cur["indent"] = False; cur["x0"] = None; cur["hang"] = False
        blocks.extend(pending); pending.clear()

    def add(kind, text, bold, new_line, indent, x):
        if cur["t"] != kind:
            flush(); cur["t"] = kind
        if not cur["runs"]:
            cur["indent"] = indent; cur["x0"] = x; cur["hang"] = bool(kind == "p" and (BULLET.match(text.lstrip(" ")) or ENUM.match(text.lstrip(" "))))
            cur["runs"].append([text.lstrip(" "), bold]); return
        if new_line:
            a, text = glue(cur["runs"][-1][0], text); cur["runs"][-1][0] = a
        if cur["runs"][-1][1] == bold: cur["runs"][-1][0] += text
        else: cur["runs"].append([text, bold])

    letter_seen = None
    for pn in range(p0, p1 + 1):
        ch = [(y, i, x, size, font, t, role(y, x, size, font, t)) for (y, i, x, size, font, t) in page_chunks(reader, pn)]
        if any(c[6] == "chapter" for c in ch): break
        ch = [c for c in ch if c[6]]
        # 本文の大きさのゴシック体が、その行に単独である場合は小見出し(例: 予防、治療、投与量)。本文の行の中にある場合は「表1」などの強調
        ch = [c[:6] + ("h4",) if c[6] == "bodyb" and not any(o is not c and o[6] in ("body", "bodyb") and abs(o[0] - c[0]) < 1.5 for o in ch) else c for c in ch]
        anchors = sorted({c[0] for c in ch if c[6] not in ("band", "letter")})
        heads = {c[0] for c in ch if c[6] in ("h2", "h3", "title")}
        # 表・図の範囲: 本文・見出し・文献の行に挟まれた、表と図の文字のまとまり
        band_ch = sorted([c for c in ch if c[6] == "band"], key=lambda c: (c[0], c[1])); bands = []
        for c in band_ch:
            lo = max([a for a in anchors if a < c[0]], default=None); hi = min([a for a in anchors if a > c[0]], default=None)
            if bands and bands[-1]["lo"] == lo and bands[-1]["hi"] == hi: bands[-1]["chunks"].append(c)
            else: bands.append({"lo": lo, "hi": hi, "chunks": [c]})
        items = [(c[0], c[1], "chunk", c) for c in ch if c[6] != "band"]
        tail_next = False
        for n, b in enumerate(bands):
            top = (b["lo"] + 5) if b["lo"] is not None else 52
            bottom = (b["hi"] - (20 if b["hi"] in heads else 11.5)) if b["hi"] is not None else 704
            rows = []; rows_y = []; last_y = None
            for c in b["chunks"]:
                for piece in c[5].split("\n"):
                    piece = re.sub(r"[ \t]+", " ", piece).strip()
                    if not piece: continue
                    if last_y is not None and abs(c[0] - last_y) < 1.5 and rows: rows[-1] = rows[-1] + ("" if rows[-1].endswith(("：", "，", "（")) or piece.startswith(("，", "）", "：")) else " ") + piece
                    else: rows.append(piece); rows_y.append(c[0])
                    last_y = c[0]
            rows = [fix_dash(r) for r in rows]
            caps = [norm(r) for r in rows if re.match(r"^(表|図)\s*\d+", r)]
            cap_pos = [(y_, norm(r)) for y_, r in zip(rows_y, rows) if re.match(r"^(表|図)\s*\d+", r)]
            img = crop(pn, top, bottom, f"{letter}_p{pn - OFFSET:02d}_{n + 1}.png")
            # 題の直前にある上付き(題に付く文献番号)は、題に含める
            for y_, r_ in zip(rows_y, rows):
                for ci, (cy_, ct_) in enumerate(cap_pos):
                    if 0 < cy_ - y_ <= 9 and len(r_) <= 6 and not re.match(r"^(表|図)", r_): cap_pos[ci] = (cy_, ct_ + norm(r_))
            caps = [ct_ for _, ct_ in cap_pos]
            tables, used = band_tables(reader, pn, top, bottom, cap_pos, continued=(not cap_pos and b["lo"] is None and st["tail_table"]))
            if n == len(bands) - 1: tail_next = bool(tables) and b["hi"] is None    # ページの下端まで続く表
            fig_rows = [r for y_, r in zip(rows_y, rows) if not any(a_ - 9 <= y_ <= b_ for a_, b_ in used)]   # 表に入らなかった文字(図の中の文字)
            key_ = lambda t: collections.Counter(re.sub(r"[\s\-—‒–]", "", t))
            got = key_("".join(c_["text"] for t_ in tables for row in t_["rows"] for c_ in row) + "".join(n_ for t_ in tables for n_ in t_["notes"]) + "".join(t_["caption"] for t_ in tables) + "".join(fig_rows))
            want_ = key_("".join(norm(r) for r in rows))
            diff = sum((want_ - got).values()) + sum((got - want_).values())
            items.append((min(c[0] for c in b["chunks"]), -1, "band", {"t": "fig", "page": pn - OFFSET, "caption": caps, "rows": rows, "img": img, "tables": tables, "fig_rows": fig_rows, "table_diff": diff if tables else 0}))
        st["last_y"] = None; st["tail_table"] = tail_next
        for y, _, kind, c in sorted(items, key=lambda it: (it[0], it[1])):
            if kind == "band":
                if cur["t"] == "p" and not re.search(r"[。）：]$", text_so_far().rstrip()): pending.append(c)   # 段落の途中: 段落の終わりに置く
                else: flush(); blocks.append(c)
                continue
            _, _, x, size, font, t, r = c
            if r == "letter": letter_seen = t.strip(); continue
            if r in ("title", "h2", "h3", "h4"):
                tx = norm(t.replace("\n", " "))
                if not tx: continue
                last = blocks[-1] if blocks else None
                if r != "h4" and last and cur["t"] is None and not pending and last["t"] == ("h1" if r == "title" else r) and last.get("pn") == pn and abs(last.get("y", -99) - y) < 24:
                    a, b2 = glue(last["text"], tx); last["text"] = a + b2; last["y"] = y           # 2行にわたる見出し
                else:
                    flush(); blocks.append({"t": "h1" if r == "title" else r, "text": tx, "y": y, "pn": pn})
                st["last_y"] = None; continue
            if r == "refhead":
                flush(); blocks.append({"t": "refhead", "text": "文献"}); st["last_y"] = None; continue
            if r == "sign":
                flush(); blocks.append({"t": "sign", "text": norm(t.replace("\n", " "))}); st["last_y"] = None; continue
            kindp = {"ref": "ref", "note": "note"}.get(r, "p")
            first = True
            for piece in re.split(r"(\n)", t):
                if piece == "\n":
                    st["last_y"] = None; continue
                if not piece.strip(): continue
                new_line = st["last_y"] is None or abs(y - st["last_y"]) > 3 or not first
                s2 = piece.lstrip(" \t") if new_line else piece
                indent = kindp == "p" and x >= 84
                if new_line:
                    brk = cur["t"] != kindp
                    if kindp == "p":
                        if s2.startswith("　"): brk = True; s2 = s2[1:].lstrip(" ")       # 字下げ = 段落の始まり
                        elif BULLET.match(s2) or (ENUM.match(s2) and (cur["hang"] or re.search(r"[。：]$|^$", text_so_far().rstrip()))): brk = True   # 箇条書きの項目
                        elif cur["t"] == "p" and cur["hang"] and cur["x0"] is not None and x > cur["x0"] + 3: brk = False   # 箇条書きの項目の 2 行目以降(ぶら下げ)
                        elif cur["t"] == "p" and indent != cur["indent"]: brk = True            # 囲みの始まりと終わり
                        elif indent and st["block_left"] is not None and x <= st["block_left"] + 1.5: brk = True   # 囲みの中の次の項目
                        if indent and (st["block_left"] is None or x < st["block_left"]): st["block_left"] = x
                        if not indent: st["block_left"] = None
                    elif kindp == "ref" and re.match(r"^\d+）", s2): brk = True
                    elif kindp == "note" and re.match(r"^[＊*※　]", s2): brk = True; s2 = s2.lstrip("　")
                    if brk: flush()
                add(kindp, s2, r == "bodyb", new_line, indent, x)
                st["last_y"] = y; first = False
    flush()
    for b in blocks:
        b.pop("y", None); b.pop("pn", None)
        if "runs" in b:
            # 段落全体で空白を整える(書体の切れ目をまたぐ空白も正しく扱うため、全体を整えてから書体ごとに分け直す)
            full = "".join(r[0] for r in b["runs"]); flags = []
            for tx, bold in b["runs"]: flags += [bold] * len(tx)
            keep = [ch for ch in full]; nf = norm(full)
            # norm は文字を削るか「—」を「-」に置き換えるだけなので、元の文字列と順に突き合わせて書体を引き継ぐ
            out = []; k = 0
            for chx in nf:
                while k < len(keep) and not (keep[k] == chx or (keep[k] == "—" and chx == "-") or (keep[k] in "\t " and chx == " ")): k += 1
                bold = flags[k] if k < len(flags) else False; k += 1
                if out and out[-1][1] == bold: out[-1][0] += chx
                else: out.append([chx, bold])
            b["runs"] = out; b["text"] = nf
    fixed = []
    for b in blocks:
        for ch_, pat, rep, where in CORRECTIONS:
            if ch_ == letter and "text" in b and re.search(pat, b["text"]):
                b["text"] = re.sub(pat, rep, b["text"]); b["runs"] = [[b["text"], False]]; b["corrected"] = where; fixed.append({"where": where, "text": rep})
    return blocks, letter_seen, fixed


CITE = re.compile(r"(?<![0-9（(〜～，,])((?:\d{1,3}）)(?:[〜～，,・]?\d{1,3}）)*)")


def mark_cites(blocks):
    """本文の文献番号を上付きにする(文献一覧にある番号に限る)。"""
    nref = sum(1 for b in blocks if b["t"] == "ref")
    for b in blocks:
        if b["t"] != "p": continue
        runs = []; started = False
        enumerated = bool(re.search(r"[，、]2）", "".join(r[0] for r in b["runs"])))   # 「1）…，2）…」の形の列挙がある段落
        for tx, bold in b["runs"]:
            pos = 0
            for m in CITE.finditer(tx):
                nums = [int(n) for n in re.findall(r"\d+", m.group(1))]
                if m.start() == 0 and not started: continue          # 段落の先頭の「1）」は番号付きの項目
                if not nums or max(nums) > max(nref, 1): continue
                if enumerated and m.group(1) == "1）" and not re.match(r"[。，、．）」]|$", tx[m.end():m.end() + 1]): continue   # 列挙の 1 番目
                if tx.rfind("（", 0, m.start()) > tx.rfind("）", 0, m.start()): continue   # 開いた括弧の中(例: （Grade 2）)は文献番号ではない
                if m.start() > pos: runs.append([tx[pos:m.start()], bold, False])
                runs.append([m.group(1), bold, True]); pos = m.end()
            if pos < len(tx): runs.append([tx[pos:], bold, False])
            started = True
        b["runs"] = runs
    for b in blocks:
        if "runs" in b: b["runs"] = [r if len(r) == 3 else [r[0], r[1], False] for r in b["runs"]]


def as_paras(blocks):
    """ポータルと Google ドキュメントに渡す段落(文字列)。#見出し、##文献、^上付き^。"""
    out = []
    for b in blocks:
        if b["t"] in ("h1", "h2", "h3", "h4"): out.append("#" + b["text"])
        elif b["t"] == "refhead": out.append("##文献")
        elif b["t"] == "fig": out.append("［" + ("、".join(b["caption"]) or "図表") + f"(2023年版 p.{b['page']})］" + " ／ ".join(r for r in b["rows"] if norm(r) not in b["caption"]))
        elif b["t"] == "sign": out.append(b["text"])
        elif b["t"] == "note": out.append(b["text"])
        else: out.append("".join(f"^{t.replace('）', ')')}^" if sup else t for t, _, sup in b["runs"]))
    return out


def chars_of(blocks):
    s = ""
    for b in blocks:
        if b["t"] == "fig": s += "".join(b["rows"])
        else: s += b.get("text", "")
    return s


def verify(reader, letter, p0, p1, blocks):
    """別の方法(pdftotext)で取り出した文字と照合する。落ちた文字の数を返す。"""
    raw = subprocess.run(["pdftotext", "-raw", "-x", "0", "-y", "50", "-W", "462", "-H", "670", "-f", str(p0), "-l", str(p1), PDF, "-"], capture_output=True, text=True).stdout   # 柱(上)とつめ(右)を除く範囲
    lines = [ln.strip() for ln in raw.replace("\x0c", "\n").split("\n") if ln.strip() and "無断転載禁止" not in ln]
    key = lambda s: collections.Counter(re.sub(r"[\s\-—‒–\x07\U0002F8ED]", "", s))   # 空白、ハイフン類、文字層が壊れた字(訂正の対象)は数えない
    # 訂正した箇所(文字層が壊れている文献)は、紙面から読んだ字なので、照合の両側から外す
    mine = chars_of([b for b in blocks if not b.get("corrected")]) + (letter or "")
    for ch_, pat, rep, where in CORRECTIONS:
        if ch_ == letter: lines = [ln for ln in lines if not re.sub(r"\s", "", ln).startswith(re.sub(r"\s", "", rep)[:5])]
    want = key("".join(lines)); have = key(mine)
    miss = want - have; extra = have - want
    return {"pdf_chars": sum(want.values()), "docx_chars": sum(have.values()), "missing": sum(miss.values()), "missing_chars": "".join(sorted(miss.elements()))[:120],
            "extra": sum(extra.values()), "extra_chars": "".join(sorted(extra.elements()))[:60]}


def main():
    reader = PdfReader(PDF)
    plan = json.load(open(os.path.join(HERE, "..", "governance", "approved_plan.json"), encoding="utf-8"))["総論"]
    chap = {}; report = {}
    for letter, p0, p1 in CHAPTERS:
        blocks, seen, fixed = chapter_blocks(reader, letter, p0, p1)
        chap[letter] = (blocks, p0, p1)
        report[letter] = verify(reader, letter, p0, p1, blocks); report[letter]["corrections"] = fixed
    units = []
    for key, letter, start in UNITS:
        blocks, p0, p1 = chap[letter]
        h1 = [b for b in blocks if b["t"] == "h1"]; ctitle = (letter + "．" + h1[0]["text"]) if h1 else letter
        if start:
            idx = [i for i, b in enumerate(blocks) if b["t"] == "h2"]
            s = next(i for i in idx if re.match(start, blocks[i]["text"])); later = [i for i in idx if i > s]
            sub = [dict(b) for b in blocks[s:(later[0] if later else len(blocks))]]
        else:
            sub = [dict(b) for b in blocks if b["t"] != "h1"]
        for b in sub:
            if "runs" in b: b["runs"] = [list(r) for r in b["runs"]]
        mark_cites(sub)
        pages = sorted({b["page"] for b in sub if b["t"] == "fig"})
        signs = [b["text"].strip("（）()") for b in sub if b["t"] == "sign"]
        title28, _, who28 = (plan.get(key) or "").rpartition(":")
        units.append({"key": key, "letter2023": letter, "chapter_title": ctitle, "section_title": (sub[0]["text"] if start else ""),
                      "title": (f"{key.replace('_', '-')}. {title28}" if title28 else f"2023年版 {ctitle}(2028年版に対応する項目なし)"),
                      "who": who28, "author2023": "、".join(signs), "pages": f"{p0 - OFFSET}–{p1 - OFFSET}" if not start else "", "chapter_pages": f"{p0 - OFFSET}–{p1 - OFFSET}",
                      "blocks": sub, "paras": as_paras(sub), "images": [b["img"] for b in sub if b["t"] == "fig" and b["img"]],
                      "corrections": [f for f in report[letter].get("corrections", []) if any(b.get("corrected") == f["where"] for b in sub)], "counts": {"paragraphs": sum(1 for b in sub if b["t"] == "p"), "refs": sum(1 for b in sub if b["t"] == "ref"), "figs": sum(1 for b in sub if b["t"] == "fig"), "tables": sum(len(b.get("tables", [])) for b in sub if b["t"] == "fig"), "table_diff": sum(b.get("table_diff", 0) for b in sub if b["t"] == "fig"),
                                 "chars": len(chars_of(sub))}, "verify": report[letter], "fig_pages": pages})
    json.dump(units, open(os.path.join(HERE, "units.json"), "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    slim = [{k: v for k, v in u.items() if k not in ("blocks", "images")} for u in units]
    json.dump(slim, open(os.path.join(HERE, "..", "data", "gl2023", "units.json"), "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    json.dump(report, open(os.path.join(HERE, "verify.json"), "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    for u in units:
        c = u["counts"]; print(f"{u['key']:6s} 章{u['letter2023']} p.{u['chapter_pages']:6s} 段落 {c['paragraphs']:3d} 文献 {c['refs']:3d} 表図 {c['figs']:2d} 表(編集用) {c['tables']:2d} 表の文字の差 {c['table_diff']:3d} 文字 {c['chars']:6d}  著者(2023) {u['author2023']}")
    print("\n照合(章ごと。pdftotext の文字に対して落ちた文字の数):")
    for k, r in report.items(): print(f"  {k}: PDF {r['pdf_chars']} 字 / 切り出し {r['docx_chars']} 字 / 落ち {r['missing']} 字 {r['missing_chars'][:60]!r} / 余り {r['extra']} 字 {r['extra_chars'][:40]!r}")


if __name__ == "__main__":
    main()
