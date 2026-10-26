"""出典検証（provenance validation）。LLM の挙動に頼らず、ハーネス側で捏造を落とす。

ルール:
  R1 research_evidence の各文は passage_ids を 1 つ以上持ち、すべて当該 CQ の段落に解決すること。
     解決しない文は research_evidence から除去し、verification.rejected_statements に監査ログとして残す。
  R2 judgment は criteria.allowed_judgments() の中の文字列であること。違反は TO_BE_JUDGED に差し替え。
  R3 judgment が 情報なし / 要判断 以外なのに research_evidence が空 → 根拠なしの判断として TO_BE_JUDGED に差し替え。
  R4 各文と引用先段落の文字 bigram 重複率が閾値未満 → 「要確認」フラグ（除去はしない。意訳の可能性があるため）。
  R5 additional_considerations に数値（効果量・研究数など）が含まれる → 事実主張の疑いとしてフラグ。
"""

from __future__ import annotations

import re

from . import criteria as C
from .schema import CQRecord, EtDWorksheet

OVERLAP_THRESHOLD = 0.30
_NUM_RE = re.compile(r"\d+(?:\.\d+)?\s*(?:%|％|件|例|人|報|研究|試験|倍|mg|g|℃)")


def _bigrams(s: str) -> set[str]:
    s = re.sub(r"[\s、。，．,.：:；;（）()「」『』\[\]【】]", "", s)
    return {s[i : i + 2] for i in range(len(s) - 1)}


def overlap(statement: str, sources: list[str]) -> float:
    sb = _bigrams(statement)
    if not sb:
        return 0.0
    tb: set[str] = set()
    for t in sources:
        tb |= _bigrams(t)
    return len(sb & tb) / len(sb)


def verify_worksheet(ws: EtDWorksheet, cq: CQRecord) -> EtDWorksheet:
    pmap = cq.passage_map()
    report: dict = {"rejected_statements": [], "warnings": [], "errors": []}

    for cd in ws.criteria:
        allowed = C.allowed_judgments(cd.criterion_id)
        # R2
        if cd.judgment not in allowed:
            report["errors"].append(f"{cd.criterion_id}: 選択肢外の判断 '{cd.judgment}' → 要判断に差し替え")
            cd.flags.append(f"選択肢外の判断を差し替え（元: {cd.judgment}）")
            cd.judgment = C.TO_BE_JUDGED

        kept = []
        for es in cd.research_evidence:
            unresolved = [pid for pid in es.passage_ids if pid not in pmap]
            if not es.passage_ids or unresolved:
                es.verified = False
                es.flags.append("出典未解決" if unresolved else "出典なし")
                report["rejected_statements"].append(
                    {"criterion": cd.criterion_id, "statement": es.statement, "passage_ids": es.passage_ids, "unresolved": unresolved}
                )
                continue
            es.overlap_score = round(overlap(es.statement, [pmap[p].text for p in es.passage_ids]), 3)
            es.verified = True
            if es.overlap_score < OVERLAP_THRESHOLD:  # R4
                es.flags.append("要確認（引用先との語彙重複が低い）")
                report["warnings"].append(f"{cd.criterion_id}: 重複率 {es.overlap_score} — '{es.statement[:40]}…'")
            kept.append(es)
        if len(kept) != len(cd.research_evidence):
            cd.flags.append(f"出典未解決の文を {len(cd.research_evidence) - len(kept)} 件除去")
        cd.research_evidence = kept

        # R3
        if cd.judgment not in (C.NO_INFO, C.TO_BE_JUDGED) and not cd.research_evidence:
            report["errors"].append(f"{cd.criterion_id}: 根拠文なしの判断 '{cd.judgment}' → 要判断に差し替え")
            cd.flags.append(f"根拠なしの判断を差し替え（元: {cd.judgment}）")
            cd.judgment = C.TO_BE_JUDGED

        # R5
        for ac in cd.additional_considerations:
            if _NUM_RE.search(ac):
                cd.flags.append("追加考慮事項に数値を含む文（事実主張の疑い）")
                report["warnings"].append(f"{cd.criterion_id}: 追加考慮事項に数値 — '{ac[:40]}…'")
                break

    report["n_rejected"] = len(report["rejected_statements"])
    report["n_errors"] = len(report["errors"])
    report["n_warnings"] = len(report["warnings"])
    ws.verification = report
    # 捏造引用が 1 件でもあれば、下書き全体を rejected（監査上そのまま委員に渡さない）
    ws.status = "rejected" if report["n_rejected"] else "verified"
    return ws
