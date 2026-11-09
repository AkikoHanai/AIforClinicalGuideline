"""論文PDF → 段落(ID付き)。様式4-5の判定の根拠として、Method と Result の該当箇所を引用するために使う。
段落ID: <PMID>-p001 … 。各段落に節(abstract/methods/results/discussion/other)とページを付ける。
pypdf(純Python)で本文を取り出す。図表の文字は段落に混ざることがあるため、節の見出しは行頭の語で判定する。"""
import io, re

HEAD_M = r"(patients,? (materials )?and methods|materials and methods|methods and materials|subjects and methods|patients and methods|methods?|study design|trial design|participants|study population|experimental procedures?)"
HEAD_R = r"(results?|findings)"
SEC_PAT = [("abstract", r"^(abstract|summary)\b"), ("other", r"^(\d+\.?\s*)?(introduction|background)\b"), ("methods", r"^(\d+\.?\s*)?" + HEAD_M + r"\b"),
           ("results", r"^(\d+\.?\s*)?" + HEAD_R + r"\b"), ("discussion", r"^(\d+\.?\s*)?(discussion|conclusions?|comment)\b"), ("references", r"^(references|acknowledg|funding|conflicts? of interest|disclosure)")]
# 見出しと本文が同じ行にある場合(例: "METHODS Patients were …"、"Results: Of 120 …")。見出しが大文字、または直後にコロン
INLINE = re.compile(r"^(?P<h>(\d+\.?\s*)?(" + HEAD_M + "|" + HEAD_R + r"|discussion))\s*[:.]?\s+(?P<rest>\S.{20,})$", re.I)
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
            m = INLINE.match(line)
            if m and (m.group("h").isupper() or re.match(r"^[^:]*:", line[:len(m.group("h")) + 2])):
                flush(); h = m.group("h").lower()
                sec = "results" if re.search(HEAD_R, h) else ("discussion" if "discussion" in h else "methods"); line = m.group("rest")
            if buf and re.search(r"[.。]$", buf[-1]) and (line[:1].isupper() or re.match(r"^[A-Z]", line)) and len(" ".join(buf)) > 300:
                flush()  # 文末で終わり、次が大文字で始まり、既に長い → 段落の切れ目
            if not buf:
                buf_page = pno
            buf.append(line)
    flush()
    return out


def quality(pages, paras):
    """抽出の状態。画像だけの PDF(文字が無い)と、節の見出しを判定できない PDF を区別する"""
    chars = sum(len(t) for _, t in pages)
    if not paras or chars < 200 * max(1, len(pages)) // 4:
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
