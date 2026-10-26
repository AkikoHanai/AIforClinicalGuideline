"""段落ブロックを CQ 単位に分割し、推奨文・推奨の強さ・エビデンス確実性などを
規則ベース（決定論的）で抽出する。LLM は一切使わない。

抽出できなかった値は NO_INFO のまま残す。推測で埋めない。
"""

from __future__ import annotations

import re

from .criteria import NO_INFO
from .ingest import RawBlock
from .schema import CQRecord, Extracted, GuidelineState, Passage, Provenance

# "CQ3", "CQ 3", "CQ3-1", "BQ2", "FQ1" など（NFKC 済み前提）。見出し行として扱うため行頭限定。
CQ_HEADING_RE = re.compile(
    r"^(?P<type>CQ|BQ|FQ)\s*[-‐－]?\s*(?P<num>\d{1,2}(?:[-‐－.]\d{1,2})?)\s*[:：.．)）\s]?\s*(?P<title>.*)$",
    re.I,
)

# 本文中の CQ 参照（「CQ3 参照」など）は見出しではない → 見出し判定は行長で絞る
MAX_HEADING_LEN = 160

REC_SENTENCE_RE = re.compile(
    r"[^。]*(?:することを(?:強く|弱く)?(?:推奨|提案)(?:する|しない)|"
    r"(?:推奨|提案)(?:する|しない)|行わないことを(?:推奨|提案)する)[^。]*。?"
)
STRENGTH_PATTERNS: list[tuple[re.Pattern, str]] = [
    (re.compile(r"強い推奨|強く推奨|推奨の強さ\s*[:：]?\s*(?:1|強)|\(1\)|（1）|グレード\s*1"), "1（強い推奨）"),
    (re.compile(r"弱い推奨|弱く推奨|条件付き推奨|推奨の強さ\s*[:：]?\s*(?:2|弱)|\(2\)|（2）|グレード\s*2|提案する"), "2（弱い推奨）"),
    (re.compile(r"推奨なし|推奨を提示しない|推奨できない|明確な推奨"), "推奨なし"),
]
DIRECTION_PATTERNS: list[tuple[re.Pattern, str]] = [
    (re.compile(r"(?:しないこと|行わないこと|用いないこと|使用しないこと)を(?:推奨|提案)"), "実施しないことを推奨/提案"),
    (re.compile(r"(?:すること|行うこと|用いること|使用すること)を(?:推奨|提案)"), "実施することを推奨/提案"),
]
CERTAINTY_PATTERNS: list[tuple[re.Pattern, str]] = [
    (re.compile(r"⊕⊕⊕⊕|確実性\s*[:：]?\s*(?:A|高い?|high)\b|\(A\)|（A）", re.I), "⊕⊕⊕⊕（高）"),
    (re.compile(r"⊕⊕⊕[◯○〇]|確実性\s*[:：]?\s*(?:B|中(?:等度)?|moderate)\b|\(B\)|（B）", re.I), "⊕⊕⊕◯（中）"),
    (re.compile(r"⊕⊕[◯○〇][◯○〇]|確実性\s*[:：]?\s*(?:C|低い?|low)\b|\(C\)|（C）", re.I), "⊕⊕◯◯（低）"),
    (re.compile(r"⊕[◯○〇][◯○〇][◯○〇]|確実性\s*[:：]?\s*(?:D|非常に低い?|とても低い?|very\s*low)\b|\(D\)|（D）", re.I), "⊕◯◯◯（非常に低）"),
]
OUTCOME_RE = re.compile(r"(?:アウトカム|outcome)\s*[:：]\s*(.+)", re.I)
PICO_RE = re.compile(r"^\s*(?P<k>P|I|C|O|患者|介入|比較|アウトカム)\s*[（(]?[^)）:：]*[)）]?\s*[:：]\s*(?P<v>.+)$")
PICO_KEY = {"P": "P", "患者": "P", "I": "I", "介入": "I", "C": "C", "比較": "C", "O": "O", "アウトカム": "O"}


def _match_heading(text: str) -> re.Match | None:
    if len(text) > MAX_HEADING_LEN:
        return None
    m = CQ_HEADING_RE.match(text)
    if not m:
        return None
    # 「CQ3 を参照」「CQ3 と同様」のような本文中参照を除外
    title = m.group("title")
    if re.match(r"^\s*(を|と|に|の|で|参照|同様)", title):
        return None
    return m


def split_into_cqs(blocks: list[RawBlock]) -> GuidelineState:
    cqs: list[CQRecord] = []
    orphans: list[Passage] = []
    current: CQRecord | None = None
    seq = 0

    for b in blocks:
        m = _match_heading(b.text)
        if m:
            code = f"{m.group('type').upper()}{m.group('num').replace('‐', '-').replace('－', '-')}"
            # 同じ CQ の見出しが再出現（目次→本文）した場合は本文側で上書きせず継続
            existing = next((c for c in cqs if c.code == code), None)
            if existing is not None:
                current = existing
                if not existing.title and m.group("title"):
                    existing.title = m.group("title").strip()
            else:
                current = CQRecord(code=code, title=m.group("title").strip(), passages=[])
                cqs.append(current)
            seq = len(current.passages)
            # 見出し自体も passage として保持（推奨文が見出し直下に無い GL への備え）
            seq += 1
            current.passages.append(
                Passage(id=f"{code}-p{seq:03d}", cq_code=code, text=b.text, page=b.page, source_file=b.source_file)
            )
            continue
        if current is None:
            orphans.append(
                Passage(id=f"PRE-p{len(orphans) + 1:03d}", cq_code=None, text=b.text, page=b.page, source_file=b.source_file)
            )
        else:
            seq = len(current.passages) + 1
            current.passages.append(
                Passage(id=f"{current.code}-p{seq:03d}", cq_code=current.code, text=b.text, page=b.page, source_file=b.source_file)
            )

    # 目次だけで本文の無い CQ（段落 1〜2 個）を除去
    cqs = [c for c in cqs if len(c.passages) >= 2]

    for cq in cqs:
        extract_fields(cq)

    files = sorted({b.source_file for b in blocks})
    title = orphans[0].text if orphans else None
    return GuidelineState(source_files=files, guideline_title=title, cqs=cqs, orphan_passages=orphans)


def _first_match(cq: CQRecord, patterns: list[tuple[re.Pattern, str]], window: list[Passage]) -> Extracted:
    for p in window:
        for rx, label in patterns:
            if rx.search(p.text):
                return Extracted(value=label, provenance=Provenance(passage_ids=[p.id], method="regex"))
    return Extracted()


def extract_fields(cq: CQRecord) -> None:
    """推奨文・強さ・確実性・方向・アウトカム・PICO を規則で抽出し、出典 passage を記録。"""
    # 推奨文: 「推奨」を含む passage のうち最初のもの（推奨文は通常 CQ 冒頭）
    rec_passages = [p for p in cq.passages if REC_SENTENCE_RE.search(p.text) and "文献" not in p.text[:4]]
    if rec_passages:
        p = rec_passages[0]
        sent = REC_SENTENCE_RE.search(p.text).group(0).strip()
        sent = re.sub(r"^(?:推奨文|推奨|Recommendation)\s*[:：]\s*", "", sent, flags=re.I)
        cq.recommendation_text = Extracted(value=sent, provenance=Provenance(passage_ids=[p.id]))
        # 強さ・確実性・方向は推奨文周辺（推奨文 passage とその前後 2 段落）を優先
        idx = cq.passages.index(p)
        window = cq.passages[max(0, idx - 2): idx + 3]
    else:
        window = cq.passages[:6]

    cq.recommendation_strength = _first_match(cq, STRENGTH_PATTERNS, window)
    if cq.recommendation_strength.value == NO_INFO:
        cq.recommendation_strength = _first_match(cq, STRENGTH_PATTERNS, cq.passages)
    cq.evidence_certainty = _first_match(cq, CERTAINTY_PATTERNS, window)
    if cq.evidence_certainty.value == NO_INFO:
        cq.evidence_certainty = _first_match(cq, CERTAINTY_PATTERNS, cq.passages)
    cq.direction = _first_match(cq, DIRECTION_PATTERNS, window)

    outcomes: list[str] = []
    pico: dict[str, str] = {}
    for p in cq.passages:
        for line in p.text.split("\n"):
            pm = PICO_RE.match(line)
            if pm:
                k = PICO_KEY.get(pm.group("k").upper() if pm.group("k").isascii() else pm.group("k"))
                if k and k not in pico:
                    pico[k] = pm.group("v").strip()
        om = OUTCOME_RE.search(p.text)
        if om:
            outcomes.extend([o.strip() for o in re.split(r"[、,，/／]", om.group(1)) if o.strip()])
    if not outcomes and pico.get("O"):
        outcomes = _split_outside_parens(pico["O"])
    cq.outcomes = list(dict.fromkeys(outcomes))
    cq.pico = pico


def _split_outside_parens(s: str) -> list[str]:
    """括弧の外にある区切り文字（、,，/／）でのみ分割する。"""
    out, buf, depth = [], "", 0
    for ch in s:
        if ch in "（(":
            depth += 1
        elif ch in "）)":
            depth = max(0, depth - 1)
        if depth == 0 and ch in "、,，/／":
            if buf.strip():
                out.append(buf.strip())
            buf = ""
        else:
            buf += ch
    if buf.strip():
        out.append(buf.strip())
    return out
