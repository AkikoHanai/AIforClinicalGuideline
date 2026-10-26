"""2023年版の各CQ(build_etd.py が作る etd_2023.json)から、GRADE EtD(11基準)のワークシート下書きを作る。
  python3 platform/core/etd_draft_from_2023.py <etd_2023.json> -o <出力フォルダ>

platform/etd_draft(利用者から提供されたパッケージ。既存ガイドライン → GRADE EtD 下書き、出典検証つき)を使う。
入力は、刊行版PDFから取り出した2023年版の記載(推奨文、強さ、確実性、解説、投票結果)で、PDFを再解析しない。
LLM は呼ばない(--llm none 相当)。各基準には、2023年版の本文から機械的に拾った候補段落だけを載せ、判断欄と委員記入欄は空欄にする。
出力: etd_draft_state.json、drafts/<CQ>.json、worksheets/EtD_<CQ>.docx と .md(横置きA4の表。末尾に引用段落の原文)
"""
import argparse, json, os, re, sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "etd_draft"))
from etd_draft.draft import draft_worksheet  # noqa: E402
from etd_draft.llm import NoneLLM  # noqa: E402
from etd_draft.render import to_docx, to_markdown  # noqa: E402
from etd_draft.schema import CQRecord, Extracted, GuidelineState, Passage, Provenance  # noqa: E402
from etd_draft.verify import verify_worksheet  # noqa: E402

STRENGTH = {"1": ("1（強い推奨）", "実施することを推奨/提案"), "2": ("2（弱い推奨）", "実施することを推奨/提案"), "3": ("推奨なし", None),
            "4": ("2（弱い推奨）", "実施しないことを推奨/提案"), "5": ("1（強い推奨）", "実施しないことを推奨/提案")}
CERT = {"A": "⊕⊕⊕⊕（高）", "B": "⊕⊕⊕◯（中）", "C": "⊕⊕◯◯（低）", "D": "⊕◯◯◯（非常に低）"}
SRC = "CIPN診療ガイドライン2023年版(刊行版PDF)"


def sentences(text):
    out = []
    for s in re.split(r"(?<=。)\s*", re.sub(r"\s+", " ", text or "")):
        s = s.strip()
        if s: out.append(s)
    return out


def build_state(items):
    cqs = []
    for n, it in enumerate(items, 1):
        code = f"CQ{n:02d}"
        passages = []
        def add(text):
            pid = f"{code}-p{len(passages) + 1:03d}"
            passages.append(Passage(id=pid, cq_code=code, text=text, page=None, source_file=SRC)); return pid
        p_title = add(f"{code} {it['title']}")
        p_rec = add(f"推奨文: {it['rec']}")
        lab, direc = STRENGTH.get(it["strength"], ("情報なし", None))
        v = it.get("votes")
        p_str = add(f"推奨の強さ: {it['strength']}、エビデンスの確実性: {it['certainty']}" + (f"、投票 {v['n']}名(棄権: 利益相反{v['coi']}名・SR{v['sr']}名)。1:{v['counts'][0]} 2:{v['counts'][1]} 3:{v['counts'][2]} 4:{v['counts'][3]} 5:{v['counts'][4]}(分母{v['denominator']})" if v else ""))
        p_cert = add(f"エビデンスの確実性: {CERT.get(it['certainty'], it['certainty'])}")
        for s in sentences(it["narrative"]): add(s)
        pico = {}
        cq = CQRecord(code=code, title=f"{it['title']}(作業フォルダ: {it['dir']})", passages=passages, pico=pico,
                      recommendation_text=Extracted(value=it["rec"], provenance=Provenance(passage_ids=[p_rec])),
                      recommendation_strength=Extracted(value=(lab + f"[2023年版の表記: {it['strength']}]") if lab != "推奨なし" else lab, provenance=Provenance(passage_ids=[p_str])),
                      evidence_certainty=Extracted(value=CERT.get(it["certainty"], "情報なし"), provenance=Provenance(passage_ids=[p_cert])),
                      direction=Extracted(value=direc or "情報なし", provenance=Provenance(passage_ids=[p_rec])))
        cqs.append(cq)
    return GuidelineState(source_files=[SRC], guideline_title="がん薬物療法に伴う末梢神経障害診療ガイドライン2023年版", cqs=cqs)


def main():
    ap = argparse.ArgumentParser(); ap.add_argument("etd"); ap.add_argument("-o", "--out", required=True)
    a = ap.parse_args()
    items = json.load(open(a.etd, encoding="utf-8"))
    state = build_state(items)
    os.makedirs(os.path.join(a.out, "drafts"), exist_ok=True); os.makedirs(os.path.join(a.out, "worksheets"), exist_ok=True)
    open(os.path.join(a.out, "etd_draft_state.json"), "w", encoding="utf-8").write(state.model_dump_json(indent=2, exclude_none=True))
    for cq in state.cqs:
        ws = verify_worksheet(draft_worksheet(cq, NoneLLM()), cq)
        open(os.path.join(a.out, "drafts", f"{cq.code}.json"), "w", encoding="utf-8").write(ws.model_dump_json(indent=2, exclude_none=True))
        open(os.path.join(a.out, "worksheets", f"EtD_{cq.code}.md"), "w", encoding="utf-8").write(to_markdown(ws, cq))
        to_docx(ws, cq, os.path.join(a.out, "worksheets", f"EtD_{cq.code}.docx"))
    print(f"{len(state.cqs)}件のCQのEtD(GRADE 11基準)下書きを作成 → {a.out}/worksheets")


if __name__ == "__main__":
    main()
