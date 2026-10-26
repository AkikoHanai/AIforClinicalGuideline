"""EtD ワークシート下書きの生成。

2 層構成:
  (a) 決定論的スケルトン — 旧推奨文・強さ・確実性、基準ごとの候補段落（キーワード一致）
  (b) LLM 補完（任意） — 候補段落を含む CQ 全文を渡し、基準ごとの判断・研究のエビデンス
      （passage_ids 必須）・委員への追加考慮事項を JSON で受け取る

(b) の出力は verify.py を通るまで status="draft" のまま。
"""

from __future__ import annotations

import json
import re

from . import criteria as C
from .llm import LLM, NoneLLM, extract_json
from .schema import CQRecord, CriterionDraft, EtDConclusion, EtDWorksheet, EvidenceStatement, Passage

# ────────────────────────── (a) 決定論的スケルトン ──────────────────────────


def _score(passage: Passage, keywords: list[str]) -> int:
    t = passage.text
    return sum(len(re.findall(re.escape(k), t)) for k in keywords)


def candidate_passages(cq: CQRecord, crit: C.Criterion, top_n: int = 5) -> list[str]:
    scored = [(p, _score(p, crit.keywords)) for p in cq.passages]
    scored = [(p, s) for p, s in scored if s > 0]
    scored.sort(key=lambda x: (-x[1], x[0].id))
    return [p.id for p, _ in scored[:top_n]]


def _old_recommendation_type(cq: CQRecord) -> str:
    s, d = cq.recommendation_strength.value, cq.direction.value
    if s == C.NO_INFO and d == C.NO_INFO:
        return C.NO_INFO
    if s == "推奨なし":
        return "推奨なし"
    strong = s.startswith("1")
    against = "しない" in d
    if against:
        return "介入に反対する強い推奨" if strong else "介入に反対する条件付き推奨"
    if d == C.NO_INFO:
        return C.NO_INFO
    return "介入を支持する強い推奨" if strong else "介入を支持する条件付き推奨"


def build_skeleton(cq: CQRecord, generator: str) -> EtDWorksheet:
    crits: list[CriterionDraft] = []
    for crit in C.CRITERIA:
        cand = candidate_passages(cq, crit)
        cd = CriterionDraft(criterion_id=crit.id, candidate_passage_ids=cand)
        if crit.id == "certainty" and cq.evidence_certainty.value != C.NO_INFO:
            # 旧 GL が明示しているエビデンス確実性はそのまま判断欄に写す（出典付き）
            cd.judgment = cq.evidence_certainty.value
            cd.research_evidence.append(
                EvidenceStatement(
                    statement=f"旧ガイドラインの記載するエビデンスの確実性: {cq.evidence_certainty.value}",
                    passage_ids=list(cq.evidence_certainty.provenance.passage_ids),
                )
            )
            cd.confidence = "high"
        elif not cand:
            cd.judgment = C.NO_INFO
            if crit.usually_absent_in_gl:
                cd.flags.append("旧GLに該当記載なし（委員の追加考慮が必要）")
            else:
                cd.flags.append("旧GLから候補段落を検出できず")
        else:
            cd.judgment = C.TO_BE_JUDGED
        crits.append(cd)

    concl = EtDConclusion(
        old_recommendation_text=cq.recommendation_text.value,
        old_strength=cq.recommendation_strength.value,
        old_certainty=cq.evidence_certainty.value,
        recommendation_type_old=_old_recommendation_type(cq),
    )
    missing = [k for k in ("recommendation_text", "recommendation_strength", "evidence_certainty") if getattr(cq, k).value == C.NO_INFO]
    if missing:
        concl.open_questions_for_panel.append(f"旧GLから規則抽出できなかった項目: {', '.join(missing)}。原文を確認してください。")

    return EtDWorksheet(cq_code=cq.code, cq_title=cq.title, pico=cq.pico, generator=generator, criteria=crits, conclusion=concl)


# ────────────────────────── (b) LLM 補完 ──────────────────────────

SYSTEM_PROMPT = """あなたは Minds 診療ガイドライン作成マニュアル 2020 ver.3.0 と GRADE アプローチに精通した
ガイドライン作成支援者です。与えられた既存ガイドラインの CQ 本文から、GRADE EtD（Evidence to Decision）
ワークシートの「下書き」を作ります。最終判断は委員（パネル）が行います。

## 絶対に守る原則
1. 「研究のエビデンス」欄に書く文は、必ず与えられた段落 ID（例: CQ3-p004）を passage_ids に挙げる。
   段落に書かれていないこと（効果量、研究数、追加文献、新しい事実）を書いてはならない。
2. 旧ガイドライン本文にその基準に関する記載が無い場合、judgment は「情報なし」とし、
   research_evidence は空配列にする。推測や一般知識で埋めない。
3. judgment は各基準で提示される選択肢の文字列からのみ選ぶ（表記を変えない）。
4. additional_considerations は「委員が検討すべき論点」であり、事実の新規主張ではない。
   疑問形または「〜の確認が必要」の形で書く。
5. 旧ガイドラインの記載内容を要約する際は、原文の方向（推奨/非推奨、効果あり/なし）を変えない。
6. 出力は JSON のみ。前後に説明文を付けない。"""


def _passages_block(cq: CQRecord) -> str:
    lines = []
    for p in cq.passages:
        pg = f" p.{p.page}" if p.page else ""
        lines.append(f"[{p.id}]{pg} {p.text}")
    return "\n".join(lines)


def build_user_prompt(cq: CQRecord, ws: EtDWorksheet) -> str:
    crit_blocks = []
    for crit in C.CRITERIA:
        cd = ws.criterion(crit.id)
        cand = ", ".join(cd.candidate_passage_ids) if cd.candidate_passage_ids else "なし"
        crit_blocks.append(
            f"### 基準 {crit.id}（{crit.label_ja}）\n"
            f"候補段落: {cand}\n"
            f"問い: {crit.question_ja}\n"
            f"選択肢: {' / '.join(crit.options)} / {C.NO_INFO}"
        )
    pico = "\n".join(f"- {k}: {v}" for k, v in ws.pico.items()) or "（本文から PICO を規則抽出できず）"
    schema = {
        "criteria": {
            "<criterion_id>": {
                "judgment": "選択肢の文字列",
                "research_evidence": [{"statement": "旧GL本文に基づく1文", "passage_ids": ["CQx-pNNN"]}],
                "additional_considerations": ["委員への論点（疑問形）"],
                "rationale": "判断理由（200字以内）",
                "confidence": "high / medium / low / none",
            }
        },
        "conclusion": {
            "certainty_to_strength_logic": "旧GLが推奨の強さをどう導いたか（本文にあれば。無ければ空文字）",
            "open_questions_for_panel": ["改訂時に委員が確認すべき点"],
        },
    }
    return (
        f"## 対象 CQ\n{cq.code}: {cq.title}\n\n"
        f"## PICO（規則抽出）\n{pico}\n\n"
        f"## 旧ガイドラインの推奨（規則抽出）\n"
        f"- 推奨文: {cq.recommendation_text.value}\n"
        f"- 推奨の強さ: {cq.recommendation_strength.value}\n"
        f"- エビデンスの確実性: {cq.evidence_certainty.value}\n\n"
        f"## 旧ガイドライン CQ 本文（段落 ID 付き。引用はこの ID のみ）\n{_passages_block(cq)}\n\n"
        f"## EtD 判断基準（11 項目）\n" + "\n\n".join(crit_blocks) + "\n\n"
        f"## 出力 JSON スキーマ\n{json.dumps(schema, ensure_ascii=False, indent=2)}\n\n"
        f"criteria の key は 11 基準すべて（{', '.join(c.id for c in C.CRITERIA)}）を含めてください。"
    )


def merge_llm_output(ws: EtDWorksheet, data: dict) -> None:
    crit_data = data.get("criteria", {}) or {}
    for cd in ws.criteria:
        d = crit_data.get(cd.criterion_id)
        if not isinstance(d, dict):
            cd.flags.append("LLM 出力にこの基準が含まれていない")
            continue
        j = str(d.get("judgment", C.NO_INFO)).strip()
        # certainty は旧GLの明示値を優先（LLM に上書きさせない）
        if not (cd.criterion_id == "certainty" and cd.confidence == "high"):
            cd.judgment = j or C.NO_INFO
        cd.research_evidence = [
            EvidenceStatement(
                statement=str(e.get("statement", "")).strip(),
                passage_ids=[str(x).strip() for x in (e.get("passage_ids") or [])],
            )
            for e in (d.get("research_evidence") or [])
            if isinstance(e, dict) and str(e.get("statement", "")).strip()
        ] or ([] if cd.criterion_id != "certainty" else cd.research_evidence)
        cd.additional_considerations = [str(x).strip() for x in (d.get("additional_considerations") or []) if str(x).strip()]
        cd.rationale = str(d.get("rationale", "")).strip()
        conf = str(d.get("confidence", "none")).strip().lower()
        cd.confidence = conf if conf in ("high", "medium", "low", "none") else "none"  # type: ignore[assignment]
    concl = data.get("conclusion", {}) or {}
    ws.conclusion.certainty_to_strength_logic = str(concl.get("certainty_to_strength_logic", "")).strip()
    ws.conclusion.open_questions_for_panel.extend(
        str(x).strip() for x in (concl.get("open_questions_for_panel") or []) if str(x).strip()
    )


def draft_worksheet(cq: CQRecord, llm: LLM) -> EtDWorksheet:
    ws = build_skeleton(cq, generator=llm.name)
    if isinstance(llm, NoneLLM):
        return ws
    raw = llm.complete(SYSTEM_PROMPT, build_user_prompt(cq, ws))
    try:
        data = extract_json(raw)
    except Exception as e:  # noqa: BLE001
        ws.verification = {"error": f"LLM 出力の JSON 解析に失敗: {e}", "raw_head": raw[:500]}
        ws.status = "rejected"
        return ws
    merge_llm_output(ws, data)
    return ws
