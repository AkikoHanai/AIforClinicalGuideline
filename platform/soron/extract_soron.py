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
            ("I", 40, 49), ("J", 50, 62), ("K", 63, 64), ("L", 65, 66), ("M", 67, 68)]
# 2028年版の担当単位(企画書の総論の記号) ← 2023年版の章と、章の中の節(見出しの正規表現)。
# 2023年版の K(海外ガイドラインの紹介)は、2028年版に対応する項目がない。2028年版の K(漢方・鍼灸治療)と N(小児患者のCIPN対策)は新設で、2023年版に本文がない。
UNITS = [("A", "A", None), ("B", "B", None), ("C", "C", None), ("D", "D", None), ("E", "E", None), ("F", "F", None), ("G", "G", None), ("H", "H", None),
         ("I_1", "I", r"^1．"), ("I_2", "I", r"^2．"), ("J_1", "J", r"^1．"), ("J_2", "J", r"^2．"), ("J_3", "J", r"^3．"), ("J_4", "J", r"^4．"), ("J_5", "J", r"^5．"),
         ("L", "L", None), ("M", "M", None), ("2023K", "K", None)]

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


def chapter_blocks(reader, letter, p0, p1):
    """1章を、原文の順のブロックにする。"""
    blocks = []
    cur = {"t": None, "runs": [], "indent": False, "x0": None, "hang": False}   # 作成中の段落(本文 p、文献 ref、注 note)
    pending = []                                      # 段落の途中に現れた表・図(段落の終わりに置く)
    st = {"last_y": None, "block_left": None}

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
        for n, b in enumerate(bands):
            top = (b["lo"] + 5) if b["lo"] is not None else 52
            bottom = (b["hi"] - (20 if b["hi"] in heads else 11.5)) if b["hi"] is not None else 704
            rows = []; last_y = None
            for c in b["chunks"]:
                for piece in c[5].split("\n"):
                    piece = re.sub(r"[ \t]+", " ", piece).strip()
                    if not piece: continue
                    if last_y is not None and abs(c[0] - last_y) < 1.5 and rows: rows[-1] = rows[-1] + ("" if rows[-1].endswith(("：", "，", "（")) or piece.startswith(("，", "）", "：")) else " ") + piece
                    else: rows.append(piece)
                    last_y = c[0]
            rows = [fix_dash(r) for r in rows]
            caps = [norm(r) for r in rows if re.match(r"^(表|図)\s*\d+", r)]
            img = crop(pn, top, bottom, f"{letter}_p{pn - OFFSET:02d}_{n + 1}.png")
            items.append((min(c[0] for c in b["chunks"]), -1, "band", {"t": "fig", "page": pn - OFFSET, "caption": caps, "rows": rows, "img": img}))
        st["last_y"] = None
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
                      "corrections": [f for f in report[letter].get("corrections", []) if any(b.get("corrected") == f["where"] for b in sub)], "counts": {"paragraphs": sum(1 for b in sub if b["t"] == "p"), "refs": sum(1 for b in sub if b["t"] == "ref"), "figs": sum(1 for b in sub if b["t"] == "fig"),
                                 "chars": len(chars_of(sub))}, "verify": report[letter], "fig_pages": pages})
    json.dump(units, open(os.path.join(HERE, "units.json"), "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    slim = [{k: v for k, v in u.items() if k not in ("blocks", "images")} for u in units]
    json.dump(slim, open(os.path.join(HERE, "..", "data", "gl2023", "units.json"), "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    json.dump(report, open(os.path.join(HERE, "verify.json"), "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    for u in units:
        c = u["counts"]; print(f"{u['key']:6s} 章{u['letter2023']} p.{u['chapter_pages']:6s} 段落 {c['paragraphs']:3d} 文献 {c['refs']:3d} 表図 {c['figs']:2d} 文字 {c['chars']:6d}  著者(2023) {u['author2023']}")
    print("\n照合(章ごと。pdftotext の文字に対して落ちた文字の数):")
    for k, r in report.items(): print(f"  {k}: PDF {r['pdf_chars']} 字 / 切り出し {r['docx_chars']} 字 / 落ち {r['missing']} 字 {r['missing_chars'][:60]!r} / 余り {r['extra']} 字 {r['extra_chars'][:40]!r}")


if __name__ == "__main__":
    main()
