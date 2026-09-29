"""
レビューバンドル生成器 — CQ1件分の「委員が見る材料」を1つにまとめる
=====================================================================
入力: data/cq/<CQ>.json (CQパッケージ)
出力: review/<CQ>.bundle.json

役割は3つ。

1. CQパッケージから EvidenceGraph を組み、Minds規則 R1-R8 を決定論的に検証する
2. AI生成の推奨案(Phase1のJSON)と、グラフから導出される事実を機械照合する
   — 確実性 / 根拠論文 / アウトカム / 対照 の4点。AIの申告を信用しない
3. 推奨 → 総体 → 格下げ理由 → 論文PMID の由来鎖を出す(AGREE II 項目12の証跡)

生成(LLM)と検証(決定論)を分離する。ここはLLMを一切呼ばない。
"""
import json
import os
import sys
from datetime import datetime, timezone

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

from evidence_schema import (  # noqa: E402
    CERTAINTY_ORDER, DOWNGRADE_FACTORS, EdgeType, NodeType, importance_band,
)
from evidence_graph import EvidenceGraph  # noqa: E402


# ------------------------------------------------------------------
# CQパッケージ → グラフ
# ------------------------------------------------------------------
def build_graph(pkg: dict) -> EvidenceGraph:
    g = EvidenceGraph()
    cq = pkg["cq_id"]
    g.add_node(cq, NodeType.CQ, comparator_kind=pkg.get("comparator_kind", "none"),
               title=pkg.get("title", ""))

    for oc in pkg.get("outcomes", []):
        g.add_node(oc["id"], NodeType.OUTCOME, label=oc.get("label", oc["id"]),
                   importance=oc.get("importance"))

    for f in sorted({f for eb in pkg.get("evidence_bodies", [])
                     for f in eb.get("downgraded_by", [])}):
        g.add_node(f"F:{f}", NodeType.FACTOR, factor=f)

    for eb in pkg.get("evidence_bodies", []):
        g.add_node(eb["id"], NodeType.EVIDENCE_BODY, cq=cq,
                   certainty=eb.get("certainty"), summary=eb.get("summary", ""))
        g.add_edge(eb["id"], EdgeType.ASSESSES, eb["outcome"])
        for f in eb.get("downgraded_by", []):
            g.add_edge(eb["id"], EdgeType.DOWNGRADED_BY, f"F:{f}")

    for st in pkg.get("studies", []):
        g.add_node(st["id"], NodeType.STUDY, pmid=st.get("pmid"),
                   design=st.get("design"), retracted=st.get("retracted", False),
                   title=st.get("title", ""), journal=st.get("journal", ""),
                   year=st.get("year"),
                   cited_in_2023=st.get("cited_in_2023", False),
                   newly_added=st.get("newly_added", False))
        for tid in st.get("trial_ids", []):
            node = f"T:{tid}"
            if node not in g.nodes:
                g.add_node(node, NodeType.TRIAL, registry_id=tid)
            g.add_edge(st["id"], EdgeType.REPORTS, node)

    for ma, member in pkg.get("includes", []):
        g.add_edge(ma, EdgeType.INCLUDES, member)

    outcome_ids = {oc["id"] for oc in pkg.get("outcomes", [])}
    eb_ids = {eb["id"] for eb in pkg.get("evidence_bodies", [])}
    incomplete_results = []
    for r in pkg.get("results", []):
        g.add_node(r["id"], NodeType.STUDY_RESULT, comparator=r.get("comparator"),
                   effect=r.get("effect"), instrument=r.get("instrument"),
                   rob2=r.get("rob2"))
        g.add_edge(r["study"], EdgeType.YIELDS, r["id"])
        # アウトカム未割当の行(委員のRoB2入力途中でよくある状態)は
        # MEASURESエッジを張れない(未登録ノードへのエッジはSchemaErrorで落ちる)。
        # クラッシュさせず「入力未完了」として記録し、検証をスキップする
        if r.get("outcome") and r["outcome"] in outcome_ids:
            g.add_edge(r["id"], EdgeType.MEASURES, r["outcome"])
        else:
            incomplete_results.append({
                "result": r["id"],
                "reason": "対応するアウトカムIDが未設定、または存在しないIDです"
                          "(RoB2評価シートの「対応するアウトカムID」列を確認してください)",
            })
            continue
        if r.get("eligible", True):
            g.add_edge(r["id"], EdgeType.ELIGIBLE_FOR, cq)
        if r.get("contributes_to") and r["contributes_to"] in eb_ids:
            g.add_edge(r["id"], EdgeType.CONTRIBUTES_TO, r["contributes_to"])
        elif r.get("contributes_to"):
            incomplete_results.append({
                "result": r["id"],
                "reason": f"contributes_to='{r['contributes_to']}' が"
                          "エビデンス総体評価シートに存在しません",
            })
    g.incomplete_results = incomplete_results  # build_bundle側でbundleに載せる

    draft = pkg.get("draft") or {}
    rec = f"REC:{cq}"
    g.add_node(rec, NodeType.RECOMMENDATION,
               strength=draft.get("strength"), direction=draft.get("direction"))
    g.add_edge(rec, EdgeType.ADDRESSES, cq)
    for eb in pkg.get("evidence_bodies", []):
        if eb.get("informs", True):
            g.add_edge(eb["id"], EdgeType.INFORMS, rec)

    g.derive_same_trial()
    return g


# ------------------------------------------------------------------
# AI生成の申告 vs グラフの事実 — 機械照合
# ------------------------------------------------------------------
def check_unit_of_analysis(g: EvidenceGraph) -> list:
    """
    R2の同種だが、試験登録番号がなくても効く検査。
    同一論文（Study）から複数のStudyResultが同じエビデンス総体に寄与している場合、
    多腕試験で対照群を使い回している可能性が高い（単位解析エラー）。
    刊行GLの評価シートには多腕試験が別行で載るため、実データで頻出する。
    """
    v = []
    for eb in g.of_type(NodeType.EVIDENCE_BODY):
        by_study = {}
        for res in sorted(g.pred(eb, EdgeType.CONTRIBUTES_TO)):
            st = g._study_of(res)
            if st:
                by_study.setdefault(st, []).append(res)
        for st, rs in by_study.items():
            if len(rs) > 1:
                v.append({
                    "rule": "R2b", "evidence_body": eb, "study": st, "results": rs,
                    "detail": f"{st} の結果が{len(rs)}件、同一のエビデンス総体に寄与している。"
                              f"多腕試験で対照群を重複計上していないか確認が必要"
                              f"（単位解析エラー）",
                })
    return v


def cross_check_draft(pkg: dict, g: EvidenceGraph) -> list:
    """
    Phase1が出した推奨案JSONの各フィールドを、グラフから導ける事実と突き合わせる。
    LLMが「確実性B」と書いても、重大アウトカムの総体が全部Cなら不一致として弾く。
    """
    issues = []
    cq = pkg["cq_id"]
    rec = f"REC:{cq}"
    draft = pkg.get("draft") or {}
    if not draft:
        return [{"check": "draft", "level": "info",
                 "detail": "推奨案(Phase1出力)が未投入。生成前の状態"}]

    # 1. 確実性
    derived = g.derive_overall_certainty(rec)
    declared = draft.get("certainty")
    if declared and derived["overall"] and declared != derived["overall"]:
        issues.append({
            "check": "certainty", "level": "block",
            "declared": declared, "derived": derived["overall"],
            "detail": f"推奨案の確実性 {declared} は、重大アウトカムの総体から導かれる "
                      f"{derived['overall']} と一致しない({derived['reason']})",
        })

    # 2. 引用PMIDが根拠グラフに存在するか(引用の捏造検出)
    prov = g.recommendation_provenance(rec)
    graph_pmids = {s["pmid"] for c in prov["chain"] for s in c["studies"] if s["pmid"]}
    for pmid in draft.get("cited_pmids", []):
        if str(pmid) not in graph_pmids:
            issues.append({
                "check": "citation", "level": "block", "pmid": str(pmid),
                "detail": f"推奨案が引用する PMID {pmid} は、この推奨の根拠グラフに"
                          f"存在しない。採用文献でないものを引いている",
            })

    # 3. 言及アウトカムがスコープのアウトカムに含まれるか
    known = {o["id"] for o in pkg.get("outcomes", [])} | \
            {o.get("label") for o in pkg.get("outcomes", [])}
    for oc in draft.get("mentioned_outcomes", []):
        if oc not in known:
            issues.append({
                "check": "outcome_scope", "level": "warn", "outcome": oc,
                "detail": f"推奨案が言及するアウトカム「{oc}」はスコープで設定した"
                          f"アウトカム一覧にない。スコープ逸脱の候補",
            })

    # 4. 推奨の強さの語彙
    # CIPN診療GL(2023)はMindsの5段階(1:強く実施 2:弱く実施 3:推奨なし
    # 4:弱く非実施 5:強く非実施)を使う。旧来の "なし" もデモ互換で許容する
    if draft.get("strength") not in (None, "1", "2", "3", "4", "5", "なし"):
        issues.append({
            "check": "vocabulary", "level": "block", "value": draft.get("strength"),
            "detail": "推奨の強さは 1〜5(Minds 5段階) のいずれかで記述する",
        })

    # 5. 合意率の記録
    vote = draft.get("panel_vote") or {}
    if vote and vote.get("agreement_rate") is not None and vote["agreement_rate"] < 0.7:
        issues.append({
            "check": "consensus", "level": "warn",
            "agreement_rate": vote["agreement_rate"],
            "detail": "合意率70%未満。Minds 6.3の合意基準を満たすか委員会で確認が必要",
        })
    return issues


# ------------------------------------------------------------------
# 委員に見せる形へ整形
# ------------------------------------------------------------------
def _study_card(g: EvidenceGraph, sid: str, pkg: dict) -> dict:
    a = g.nodes[sid]
    results = []
    for r in sorted(g.succ(sid, EdgeType.YIELDS)):
        ra = g.nodes[r]
        oc = next(iter(g.succ(r, EdgeType.MEASURES)), None)
        results.append({
            "id": r, "outcome": oc,
            "outcome_label": g.nodes.get(oc, {}).get("label", oc) if oc else None,
            "comparator": ra.get("comparator"),
            "effect": ra.get("effect"),
            "instrument": ra.get("instrument"),
            "rob2": ra.get("rob2"),
            "eligible": bool(g.succ(r, EdgeType.ELIGIBLE_FOR)),
            "contributes_to": sorted(g.succ(r, EdgeType.CONTRIBUTES_TO)),
        })
    return {
        "id": sid, "pmid": a.get("pmid"), "title": a.get("title"),
        "journal": a.get("journal"), "year": a.get("year"),
        "design": a.get("design"), "retracted": bool(a.get("retracted")),
        "cited_in_2023": bool(a.get("cited_in_2023")),
        "newly_added": bool(a.get("newly_added")),
        "trials": sorted(g.succ(sid, EdgeType.REPORTS)),
        "same_trial_as": sorted(g.succ(sid, EdgeType.SAME_TRIAL_AS)),
        "includes": sorted(g.succ(sid, EdgeType.INCLUDES)),
        "results": results,
    }


def build_bundle(pkg: dict) -> dict:
    g = build_graph(pkg)
    cq = pkg["cq_id"]
    rec = f"REC:{cq}"

    validation = g.validate()
    ua = check_unit_of_analysis(g)
    if ua:
        validation["violations"].extend(ua)
        validation["by_rule"]["R2b"] = len(ua)
        validation["passed"] = False
    cross = cross_check_draft(pkg, g)
    prov = g.recommendation_provenance(rec)
    certainty = g.derive_overall_certainty(rec)

    bodies = []
    for eb in pkg.get("evidence_bodies", []):
        oc = eb["outcome"]
        imp = g.nodes[oc].get("importance")
        contributing = sorted(g.pred(eb["id"], EdgeType.CONTRIBUTES_TO))
        bodies.append({
            "id": eb["id"], "outcome": oc,
            "outcome_label": g.nodes[oc].get("label", oc),
            "importance": imp,
            "band": importance_band(imp) if imp is not None else None,
            "certainty": eb.get("certainty"),
            "downgraded_by": eb.get("downgraded_by", []),
            "summary": eb.get("summary", ""),
            "results": contributing,
            "studies": sorted({g._study_of(r) for r in contributing if g._study_of(r)}),
        })

    blocking = [v for v in validation["violations"]] + \
               [c for c in cross if c.get("level") == "block"]

    return {
        "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "cq": {
            "id": cq, "title": pkg.get("title", ""),
            "pico": pkg.get("pico", {}),
            "comparator_kind": pkg.get("comparator_kind", "none"),
            "outcomes": pkg.get("outcomes", []),
        },
        "draft": pkg.get("draft") or {},
        "narrative": pkg.get("narrative", ""),
        "evidence_bodies": bodies,
        "studies": [_study_card(g, s, pkg) for s in g.of_type(NodeType.STUDY)],
        "validation": validation,
        "cross_check": cross,
        "incomplete_results": getattr(g, "incomplete_results", []),
        # 検索/ハンドサーチで挙がった採用候補(スクリーニングログ由来)。採否は委員が画面で判断
        "candidates": pkg.get("candidates", []),
        "references_2023": pkg.get("references", []),
        "question_type": pkg.get("question_type", "CQ"),
        "drafts_2023": pkg.get("drafts_2023") or [],
        "merged_from": (pkg.get("_source") or {}).get("merged_from"),
        "derived_certainty": certainty,
        "provenance": prov,
        "gate": {
            "ready_for_review": not blocking,
            "n_blocking": len(blocking),
            "reason": ("機械検証を通過。委員レビューに進める" if not blocking else
                       "機械検証で不整合。委員に出す前に差し戻す"),
        },
        "source_package": pkg.get("source_file"),
    }


def main():
    import argparse
    ap = argparse.ArgumentParser(description="CQパッケージ → レビューバンドル")
    ap.add_argument("packages", nargs="+", help="data/cq/*.json")
    ap.add_argument("-o", "--outdir", default=os.path.join(HERE, "..", "review"))
    args = ap.parse_args()

    os.makedirs(args.outdir, exist_ok=True)
    for path in args.packages:
        with open(path, encoding="utf-8") as f:
            pkg = json.load(f)
        pkg["source_file"] = os.path.basename(path)
        b = build_bundle(pkg)
        out = os.path.join(args.outdir, f"{pkg['cq_id']}.bundle.json")
        with open(out, "w", encoding="utf-8") as f:
            json.dump(b, f, ensure_ascii=False, indent=2)
        g = b["gate"]
        print(f"{pkg['cq_id']}: {'OK ' if g['ready_for_review'] else 'NG '}"
              f"違反{g['n_blocking']}件 / 論文{len(b['studies'])}件 "
              f"/ 確実性{b['derived_certainty']['overall']} → {out}")


if __name__ == "__main__":
    main()
