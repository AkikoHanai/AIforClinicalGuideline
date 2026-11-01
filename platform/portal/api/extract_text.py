"""論文PDF → 段落(ID付き)。様式4-5の判定の根拠として、Method と Result の該当箇所を引用するために使う。
段落ID: <PMID>-p001 … 。各段落に節(abstract/methods/results/discussion/other)とページを付ける。
pypdf(純Python)で本文を取り出す。図表の文字は段落に混ざることがあるため、節の見出しは行頭の語で判定する。"""
import io, re

SEC_PAT = [("abstract", r"^(abstract|summary)\b"), ("methods", r"^(\d+\.?\s*)?(patients and methods|materials and methods|methods?|subjects and methods|study design|participants|trial design)\b"),
           ("results", r"^(\d+\.?\s*)?results?\b"), ("discussion", r"^(\d+\.?\s*)?(discussion|conclusions?|comment)\b"), ("references", r"^(references|acknowledg|funding|conflicts? of interest|disclosure)")]


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
            out.append({"id": f"{doc_id}-p{len(out) + 1:03d}", "page": buf_page, "section": sec, "text": t[:3000]})
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
            if buf and re.search(r"[.。]$", buf[-1]) and (line[:1].isupper() or re.match(r"^[A-Z]", line)) and len(" ".join(buf)) > 300:
                flush()  # 文末で終わり、次が大文字で始まり、既に長い → 段落の切れ目
            if not buf:
                buf_page = pno
            buf.append(line)
    flush()
    return out


def relevant(paras, sections=("methods", "results"), limit_chars=60000):
    """Method と Result の段落(なければ全段落)。LLMへの入力。"""
    sel = [p for p in paras if p["section"] in sections] or paras
    out, n = [], 0
    for p in sel:
        if n + len(p["text"]) > limit_chars:
            break
        out.append(p); n += len(p["text"])
    return out
