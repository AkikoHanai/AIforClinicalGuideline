"""論文PDF → 段落(ID付き)。様式4-5の判定の根拠として、Method と Result の該当箇所を引用するために使う。
段落ID: <PMID>-p001 … 。各段落に節(abstract/methods/results/discussion/other)とページを付ける。
pypdf(純Python)で本文を取り出す。図表の文字は段落に混ざることがあるため、節の見出しは行頭の語で判定する。"""
import io, re

NUM = r"(\d+(\.\d+)*\.?\s*[|:.\-–]?\s*)?"  # 見出しの番号。例: "2 "、"2. "、"4.1. "、"2 | "
HEAD_M = r"(patients,? (materials )?and methods|materials and methods|methods and materials|subjects and methods|patients and methods|statistical (methods?|analys[ie]s)|methods?|study design|trial design|participants|study population|experimental( procedures?)?)"
HEAD_R = r"((investigations? and )?results?|findings)"
SEC_PAT = [("abstract", r"^(abstract|summary)\b"), ("other", "^" + NUM + r"(introduction|background)\b"), ("methods", "^" + NUM + HEAD_M + r"\b"),
           ("results", "^" + NUM + HEAD_R + r"\b"), ("discussion", "^" + NUM + r"(discussion|conclusions?|comment)\b"), ("references", r"^(references|acknowledg|funding|conflicts? of interest|disclosure)")]
# 見出しと本文が同じ行にある場合。採用する形: 見出しが大文字("METHODS Patients were …")、直後にコロン("Results: Of 120 …")、
# 直後にピリオドで次が大文字("Methods. Pain-free …")。"Results were reported …" のような文は見出しにしない
INLINE = re.compile(r"^(?P<h>" + NUM + "(" + HEAD_M + "|" + HEAD_R + r"|discussion))(?P<sep>\s*[:.]?)\s+(?P<rest>\S.{20,})$", re.I)


def _inline(line):
    """同じ行の見出し → (節, 残りの本文)。見出しでなければ None"""
    m = INLINE.match(line)
    if not m: return None
    h, sep, rest = m.group("h"), m.group("sep").strip(), m.group("rest")
    if not (h.isupper() or sep == ":" or (sep == "." and rest[:1].isupper())): return None
    low = h.lower()
    return ("results" if re.search(r"result|finding", low) else "discussion" if "discussion" in low else "methods"), rest


CHUNK = 1500  # 1段落の上限文字数。超えるときは文末で分ける(切り捨てない)


def _chunks(t):
    if len(t) <= CHUNK: return [t]
    out, cur = [], ""
    for sent in re.split(r"(?<=[.!?。])\s+", t):
        if cur and len(cur) + len(sent) + 1 > CHUNK: out.append(cur); cur = sent
        else: cur = (cur + " " + sent).strip()
    if cur: out.append(cur)
    return out


def pdf_pages(data: bytes):
    from pypdf import PdfReader
    r = PdfReader(io.BytesIO(data))
    return [(i + 1, (p.extract_text() or "")) for i, p in enumerate(r.pages)]


def paragraphs(doc_id: str, pages):
    """pages: [(page_no, text)]。戻り値: [{id, page, section, text}]"""
    out, sec, buf, buf_page = [], "other", [], None

    def flush():
        nonlocal buf, buf_page
        t = re.sub(r"\s+", " ", " ".join(buf)).strip()
        if len(t) >= 40:
            for c in _chunks(t):
                out.append({"id": f"{doc_id}-p{len(out) + 1:03d}", "page": buf_page, "section": sec, "text": c})
        buf, buf_page = [], None

    for pno, text in pages:
        for raw in text.split("\n"):
            line = raw.strip()
            if not line:
                flush(); continue
            low = line.lower()
            hit = next((s for s, pat in SEC_PAT if re.match(pat, low) and len(line) < 60), None)
            if hit:
                flush(); sec = hit
                if sec == "references":
                    return out
                continue
            il = _inline(line)
            if il:
                flush(); sec, line = il
            if buf and re.search(r"[.。]$", buf[-1]) and (line[:1].isupper() or re.match(r"^[A-Z]", line)) and len(" ".join(buf)) > 300:
                flush()  # 文末で終わり、次が大文字で始まり、既に長い → 段落の切れ目
            if not buf:
                buf_page = pno
            buf.append(line)
    flush()
    return out


def quality(pages, paras):
    """抽出の状態。画像だけの PDF(文字が無い)と、節の見出しを判定できない PDF を区別する"""
    low = sum(1 for _, t in pages if len(t.strip()) < 300)  # 文字がほとんど無いページ(通常の論文は 1 ページ 3000 字前後)
    if not paras or (len(pages) >= 3 and low * 2 > len(pages)):  # 半数を超えるページに文字層が無い → 画像 PDF
        return "画像PDF(本文を抽出できない。OCR が必要)"
    if not any(p["section"] in ("methods", "results") for p in paras):
        return "本文抽出済(節の見出しを判定できない。全段落を参照)"
    return "本文抽出済"


def relevant(paras, sections=("methods", "results"), limit_chars=60000):
    """Method と Result の段落(なければ全段落)。LLMへの入力。"""
    sel = [p for p in paras if p["section"] in sections] or paras
    out, n = [], 0
    for p in sel:
        if n + len(p["text"]) > limit_chars:
            break
        out.append(p); n += len(p["text"])
    return out
