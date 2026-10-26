"""決定論的部分（抽出・検証・描画）のテスト。LLM は mock のみ使用。"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from etd_draft import criteria as C
from etd_draft.draft import build_skeleton, build_user_prompt, draft_worksheet, merge_llm_output
from etd_draft.ingest import read_any
from etd_draft.llm import MockLLM, extract_json
from etd_draft.render import to_docx, to_markdown
from etd_draft.segment import split_into_cqs
from etd_draft.verify import overlap, verify_worksheet

SAMPLE = Path(__file__).resolve().parent.parent / "sample" / "sample_cipn_gl.txt"


@pytest.fixture(scope="module")
def state():
    return split_into_cqs(read_any(SAMPLE))


def test_segmentation_detects_cqs(state):
    codes = [c.code for c in state.cqs]
    assert codes == ["CQ1", "CQ2", "CQ3", "BQ1"]


def test_regex_extraction_cq1(state):
    cq = state.cqs[0]
    assert cq.recommendation_strength.value == "2（弱い推奨）"
    assert cq.evidence_certainty.value == "⊕⊕◯◯（低）"
    assert cq.direction.value == "実施することを推奨/提案"
    assert cq.pico["I"].startswith("投与中の手足の冷却")
    assert "QOL" in cq.outcomes
    # 出典 passage が実在する
    pmap = cq.passage_map()
    for pid in cq.recommendation_text.provenance.passage_ids:
        assert pid in pmap


def test_regex_extraction_against(state):
    cq3 = state.cqs[2]
    assert cq3.direction.value == "実施しないことを推奨/提案"
    bq = state.cqs[3]
    assert bq.recommendation_text.value == C.NO_INFO


def test_skeleton_marks_absent_criteria(state):
    ws = build_skeleton(state.cqs[2], "none")  # CQ3: 費用の記載はあるが費用対効果・受容性は無い
    assert ws.criterion("cost_effectiveness").judgment == C.NO_INFO
    assert ws.criterion("certainty").judgment == "⊕⊕◯◯（低）"
    assert ws.conclusion.recommendation_type_old == "介入に反対する条件付き推奨"


def test_verify_rejects_fabricated_citation(state):
    cq = state.cqs[0]
    ws = build_skeleton(cq, "test")
    data = {
        "criteria": {
            "desirable_effects": {
                "judgment": "中程度",
                "research_evidence": [
                    {"statement": "冷却群でグレード 2 以上の CIPN の発生が少ない傾向が一貫して示された。", "passage_ids": ["CQ1-p008"]},
                    {"statement": "大規模試験で 44% のリスク低下が示された。", "passage_ids": ["CQ1-p999"]},  # 捏造
                ],
                "additional_considerations": ["評価尺度の差異をどう扱うか？"],
                "rationale": "",
                "confidence": "medium",
            },
            "values": {"judgment": "ばらつき大", "research_evidence": [], "additional_considerations": [], "rationale": "", "confidence": "low"},  # 選択肢外
            "equity": {"judgment": "おそらく低下する", "research_evidence": [], "additional_considerations": [], "rationale": "", "confidence": "low"},  # 根拠なし
        },
        "conclusion": {"open_questions_for_panel": []},
    }
    merge_llm_output(ws, data)
    ws = verify_worksheet(ws, cq)
    assert ws.status == "rejected"
    assert ws.verification["n_rejected"] == 1
    de = ws.criterion("desirable_effects")
    assert len(de.research_evidence) == 1 and de.research_evidence[0].verified
    assert de.judgment == "中程度"  # 根拠が残っているので判断は維持
    assert ws.criterion("values").judgment == C.TO_BE_JUDGED  # 選択肢外 → 差し替え
    assert ws.criterion("equity").judgment == C.TO_BE_JUDGED  # 根拠なし → 差し替え


def test_overlap_metric():
    src = "有害事象としては冷却に伴う不快感、疼痛が報告され、一部の試験で忍容できず中止した例があった。"
    assert overlap("冷却に伴う不快感・疼痛が報告され、忍容できず中止した例があった。", [src]) > 0.6
    assert overlap("薬価は 1 万円で費用対効果は良好であった。", [src]) < 0.3


def test_mock_llm_roundtrip_and_render(state, tmp_path):
    cq = state.cqs[0]
    ws = draft_worksheet(cq, MockLLM())
    ws = verify_worksheet(ws, cq)
    assert ws.status == "verified"
    md = to_markdown(ws, cq)
    assert "付録: 引用段落の原文" in md
    out = to_docx(ws, cq, tmp_path / "x.docx")
    assert out.exists() and out.stat().st_size > 10_000
    # JSON 往復
    from etd_draft.schema import EtDWorksheet

    ws2 = EtDWorksheet.model_validate_json(ws.model_dump_json(exclude_none=True))
    assert ws2.cq_code == "CQ1"


def test_prompt_contains_all_passage_ids(state):
    cq = state.cqs[1]
    ws = build_skeleton(cq, "none")
    prompt = build_user_prompt(cq, ws)
    for p in cq.passages:
        assert f"[{p.id}]" in prompt
    for c in C.CRITERIA:
        assert f"### 基準 {c.id}" in prompt


def test_extract_json_with_fence():
    assert extract_json('前置き\n```json\n{"a": 1}\n```') == {"a": 1}
