"""
エビデンス・グラフのテスト
実行: cd src/kb && python -m pytest ../../tests/test_evidence_graph.py -q
"""
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, "..", "core"))

import pytest  # noqa: E402
from evidence_schema import EdgeType, NodeType  # noqa: E402
from evidence_graph import EvidenceGraph, SchemaError  # noqa: E402


def base_graph():
    """CQ1-冷却を模した最小グラフ。CQの対照は『冷却なし』"""
    g = EvidenceGraph()
    g.add_node("CQ1-冷却", NodeType.CQ, comparator_kind="none")
    g.add_node("O:CIPN発症頻度", NodeType.OUTCOME, importance=8)   # 重大
    g.add_node("O:QOL", NodeType.OUTCOME, importance=5)            # 重要
    g.add_node("EB:冷却×発症頻度", NodeType.EVIDENCE_BODY,
               cq="CQ1-冷却", certainty="C")
    g.add_edge("EB:冷却×発症頻度", EdgeType.ASSESSES, "O:CIPN発症頻度")
    g.add_node("REC:CQ1-冷却", NodeType.RECOMMENDATION, strength="2", direction="for")
    g.add_edge("EB:冷却×発症頻度", EdgeType.INFORMS, "REC:CQ1-冷却")
    g.add_edge("REC:CQ1-冷却", EdgeType.ADDRESSES, "CQ1-冷却")
    g.add_node("F:indirectness", NodeType.FACTOR, factor="indirectness")
    g.add_node("F:imprecision", NodeType.FACTOR, factor="imprecision")
    return g


def add_study(g, sid, pmid, design, result_id, comparator="none",
              trial=None, eligible_for="CQ1-冷却", eb="EB:冷却×発症頻度",
              retracted=False):
    g.add_node(sid, NodeType.STUDY, pmid=pmid, design=design, retracted=retracted)
    g.add_node(result_id, NodeType.STUDY_RESULT, comparator=comparator)
    g.add_edge(sid, EdgeType.YIELDS, result_id)
    g.add_edge(result_id, EdgeType.MEASURES, "O:CIPN発症頻度")
    if eligible_for:
        g.add_edge(result_id, EdgeType.ELIGIBLE_FOR, eligible_for)
    if eb:
        g.add_edge(result_id, EdgeType.CONTRIBUTES_TO, eb)
    if trial:
        if trial not in g.nodes:
            g.add_node(trial, NodeType.TRIAL)
        g.add_edge(sid, EdgeType.REPORTS, trial)
    return sid


# ---------- スキーマの強制 ----------
def test_unknown_edge_type_rejected():
    g = base_graph()
    g.add_node("S1", NodeType.STUDY)
    with pytest.raises(SchemaError):
        g.add_edge("S1", "somehow-relates-to", "CQ1-冷却")


def test_edge_to_unregistered_node_rejected():
    """既存ノードと接続しない関係は書けない = 幻覚の抑制"""
    g = base_graph()
    g.add_node("S1", NodeType.STUDY)
    with pytest.raises(SchemaError):
        g.add_edge("S1", EdgeType.YIELDS, "存在しない結果ノード")


# ---------- R1 適格性 ----------
def test_r1_ineligible_result_flagged():
    g = base_graph()
    add_study(g, "S1", "111", "rct", "R1a", eligible_for=None)
    v = g.check_r1_eligibility()
    assert len(v) == 1 and v[0]["rule"] == "R1"


# ---------- R2 同一試験の二重計上 ----------
def test_r2_same_trial_double_count():
    """同一試験の主報告と副次報告が両方総体に入る = 実際によくある誤り"""
    g = base_graph()
    add_study(g, "S:主報告", "111", "rct", "R:主", trial="T:NCT01234567")
    add_study(g, "S:副次報告", "222", "rct", "R:副", trial="T:NCT01234567")
    v = g.check_r2_same_trial()
    assert len(v) == 1
    assert set(v[0]["studies"]) == {"S:主報告", "S:副次報告"}


def test_derive_same_trial_from_registry():
    """試験登録番号から same-trial-as を機械導出できる(人手入力不要)"""
    g = base_graph()
    add_study(g, "S:A", "111", "rct", "R:A", trial="T:NCT01234567")
    add_study(g, "S:B", "222", "rct", "R:B", trial="T:NCT01234567")
    assert g.derive_same_trial() == 1
    assert "S:B" in g.succ("S:A", EdgeType.SAME_TRIAL_AS)


# ---------- R3 メタ解析と構成研究の二重計上 ----------
def test_r3_meta_analysis_overlap():
    g = base_graph()
    add_study(g, "S:RCT1", "111", "rct", "R:RCT1")
    add_study(g, "S:MA", "999", "meta_analysis", "R:MA")
    g.add_edge("S:MA", EdgeType.INCLUDES, "S:RCT1")
    v = g.check_r3_ma_overlap()
    assert len(v) == 1 and v[0]["overlapping"] == ["S:RCT1"]


# ---------- R4 撤回の波及(多段推論) ----------
def test_r4_direct_retraction():
    g = base_graph()
    add_study(g, "S:撤回", "111", "rct", "R:撤回", retracted=True)
    v = g.check_r4_retraction()
    assert len(v) == 1 and v[0]["hops"] == 1


def test_r4_retraction_reaches_meta_analysis_two_hops():
    """撤回論文はMA経由で2ホップ先の総体に効く。文章を読むだけでは気づけない"""
    g = base_graph()
    # 撤回論文自体は総体に寄与していない
    g.add_node("S:撤回", NodeType.STUDY, pmid="666", design="rct", retracted=True)
    add_study(g, "S:MA", "999", "meta_analysis", "R:MA")
    g.add_edge("S:MA", EdgeType.INCLUDES, "S:撤回")
    v = g.check_r4_retraction()
    assert len(v) == 1
    assert v[0]["hops"] == 2 and v[0]["retracted_inside"] == ["S:撤回"]


# ---------- R6 非直接性(冷却の実例) ----------
def test_r6_active_comparator_without_indirectness_downgrade():
    """強い冷却 vs ぬるい冷却のRCT。非直接性の格下げがないと違反"""
    g = base_graph()
    add_study(g, "S:冷却RCT", "111", "rct", "R:冷却", comparator="active_weaker")
    v = g.check_r6_indirectness()
    assert len(v) == 1
    assert v[0]["result_comparator"] == ["active_weaker"]
    assert v[0]["cq_comparator"] == "none"


def test_r6_satisfied_when_indirectness_recorded():
    g = base_graph()
    add_study(g, "S:冷却RCT", "111", "rct", "R:冷却", comparator="active_weaker")
    g.add_edge("EB:冷却×発症頻度", EdgeType.DOWNGRADED_BY, "F:indirectness")
    assert g.check_r6_indirectness() == []


def test_r6_direct_comparator_not_flagged():
    g = base_graph()
    add_study(g, "S:無介入対照RCT", "111", "rct", "R:直接", comparator="none")
    assert g.check_r6_indirectness() == []


# ---------- R7 重大アウトカム ----------
def test_r7_recommendation_without_critical_outcome():
    g = base_graph()
    # 重要度5(重要だが重大でない)のアウトカムのみに紐づく推奨
    g.add_node("EB:QOLのみ", NodeType.EVIDENCE_BODY, cq="CQ1-冷却", certainty="C")
    g.add_edge("EB:QOLのみ", EdgeType.ASSESSES, "O:QOL")
    g.add_node("REC:QOLのみ", NodeType.RECOMMENDATION)
    g.add_edge("EB:QOLのみ", EdgeType.INFORMS, "REC:QOLのみ")
    v = g.check_r7_critical_outcome()
    assert any(x["recommendation"] == "REC:QOLのみ" for x in v)


# ---------- R8 格下げ理由の明示 ----------
def test_r8_missing_downgrade_reason():
    g = base_graph()   # certainty="C" だが DOWNGRADED_BY なし
    v = g.check_r8_downgrade_reason()
    assert len(v) == 1 and v[0]["certainty"] == "C"


# ---------- R5 全体確実性の導出 ----------
def test_r5_overall_certainty_takes_lowest_critical():
    g = base_graph()
    g.add_node("O:疼痛", NodeType.OUTCOME, importance=7)     # 重大
    g.add_node("EB:疼痛", NodeType.EVIDENCE_BODY, cq="CQ1-冷却", certainty="D")
    g.add_edge("EB:疼痛", EdgeType.ASSESSES, "O:疼痛")
    g.add_edge("EB:疼痛", EdgeType.INFORMS, "REC:CQ1-冷却")
    out = g.derive_overall_certainty("REC:CQ1-冷却")
    assert out["overall"] == "D"      # C と D のうち低い D


def test_r5_ignores_non_critical_outcomes():
    g = base_graph()
    g.add_node("EB:QOL", NodeType.EVIDENCE_BODY, cq="CQ1-冷却", certainty="D")
    g.add_edge("EB:QOL", EdgeType.ASSESSES, "O:QOL")   # 重要度5
    g.add_edge("EB:QOL", EdgeType.INFORMS, "REC:CQ1-冷却")
    out = g.derive_overall_certainty("REC:CQ1-冷却")
    assert out["overall"] == "C"      # 重大アウトカムのCのみ採用


# ---------- 多段推論 ----------
def test_new_evidence_impact_three_hops():
    """新規論文 → 結果 → 総体 → 推奨。どの文書にも書かれていない対応"""
    g = base_graph()
    add_study(g, "S:新規", "555", "rct", "R:新規")
    imp = g.new_evidence_impact("S:新規")
    assert imp["recommendations"] == ["REC:CQ1-冷却"]
    assert imp["evidence_bodies"] == ["EB:冷却×発症頻度"]


def test_new_evidence_impact_detects_sibling_already_used():
    g = base_graph()
    add_study(g, "S:既存", "111", "rct", "R:既存", trial="T:NCT9999")
    add_study(g, "S:新規", "222", "rct", "R:新規", trial="T:NCT9999")
    g.derive_same_trial()
    imp = g.new_evidence_impact("S:新規")
    assert imp["same_trial_already_used"] == ["S:既存"]
    assert "二重計上" in imp["note"]


def test_provenance_gives_agree2_item12_trace():
    g = base_graph()
    add_study(g, "S:1", "111", "rct", "R:1")
    add_study(g, "S:2", "222", "meta_analysis", "R:2")
    g.add_edge("EB:冷却×発症頻度", EdgeType.DOWNGRADED_BY, "F:imprecision")
    p = g.recommendation_provenance("REC:CQ1-冷却")
    assert p["n_studies"] == 2
    assert p["chain"][0]["downgraded_by"] == ["imprecision"]
    assert {s["pmid"] for s in p["chain"][0]["studies"]} == {"111", "222"}


# ---------- 一括検証 ----------
def test_validate_aggregates_all_rules():
    g = base_graph()
    add_study(g, "S:冷却RCT", "111", "rct", "R:冷却", comparator="active_weaker")
    rep = g.validate()
    assert rep["passed"] is False
    assert rep["by_rule"]["R6"] == 1   # 非直接性の格下げなし
    assert rep["by_rule"]["R8"] == 1   # 格下げ理由なし


def test_validate_passes_when_clean():
    g = base_graph()
    add_study(g, "S:直接RCT", "111", "rct", "R:直接", comparator="none")
    g.add_edge("EB:冷却×発症頻度", EdgeType.DOWNGRADED_BY, "F:imprecision")
    rep = g.validate()
    assert rep["passed"] is True, rep["violations"]
