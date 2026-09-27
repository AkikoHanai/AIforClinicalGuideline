"""
エビデンス・グラフ — 個別論文結果をノードに、Minds縛りのエッジでつなぐ
=====================================================================
実装方針:
  1. エッジ型は evidence_schema.EdgeType に限定。未知の型は追加時に拒否する
  2. Mindsルール R1-R8 は決定論的に検証する(LLMに判定させない)
  3. 多段推論は「文章に書かれていない事実」を出すために使う
     — 二重計上、撤回の波及、同一試験の重複、非直接性の連鎖

参照記事の教訓との整合:
  グラフは第一にLLMへ渡すコンテキストではなく、**検証層の照合元**として使う。
  KBに入れて読ませても幻覚は減らないが、後段で機械照合すると効く。
  LLMへ渡すのは、検証を通ったサブグラフに限る。
"""
from collections import defaultdict, deque

from evidence_schema import (
    EdgeType, NodeType, DIRECT_COMPARATORS, CERTAINTY_ORDER,
    DOWNGRADE_FACTORS, UPGRADE_FACTORS, importance_band, MINDS_RULES,
)


class SchemaError(ValueError):
    pass


class EvidenceGraph:
    def __init__(self):
        self.nodes = {}                              # id -> {type, **attrs}
        self.out = defaultdict(lambda: defaultdict(set))  # src -> etype -> {dst}
        self.inn = defaultdict(lambda: defaultdict(set))  # dst -> etype -> {src}

    # ------------------------------------------------------------------
    # 構築
    # ------------------------------------------------------------------
    def add_node(self, node_id: str, ntype: NodeType, **attrs):
        if node_id in self.nodes and self.nodes[node_id]["type"] != ntype:
            raise SchemaError(f"{node_id} の型が衝突: "
                              f"{self.nodes[node_id]['type']} vs {ntype}")
        self.nodes.setdefault(node_id, {"type": ntype})
        self.nodes[node_id].update(attrs)
        return node_id

    def add_edge(self, src: str, etype, dst: str):
        """型は EdgeType に限る。閉じた語彙を強制する"""
        if not isinstance(etype, EdgeType):
            try:
                etype = EdgeType(etype)
            except ValueError:
                raise SchemaError(
                    f"未定義のエッジ型 '{etype}'。使用可能: "
                    f"{[e.value for e in EdgeType]}")
        for n in (src, dst):
            if n not in self.nodes:
                raise SchemaError(f"未登録のノード '{n}'。既存ノードと接続しない関係は書けない")
        self.out[src][etype].add(dst)
        self.inn[dst][etype].add(src)

    # ------------------------------------------------------------------
    # 走査
    # ------------------------------------------------------------------
    def succ(self, node: str, etype: EdgeType) -> set:
        return set(self.out[node].get(etype, set()))

    def pred(self, node: str, etype: EdgeType) -> set:
        return set(self.inn[node].get(etype, set()))

    def of_type(self, ntype: NodeType) -> list:
        return sorted(n for n, a in self.nodes.items() if a["type"] == ntype)

    def reach(self, start: str, etypes: list, max_hops: int = 5) -> set:
        """指定エッジ型のみを辿って到達可能なノード集合(多段推論の土台)"""
        seen, q = set(), deque([(start, 0)])
        while q:
            n, d = q.popleft()
            if d >= max_hops:
                continue
            for et in etypes:
                for nxt in self.succ(n, et):
                    if nxt not in seen:
                        seen.add(nxt)
                        q.append((nxt, d + 1))
        return seen

    # ------------------------------------------------------------------
    # 導出エッジ: same-trial-as(人手入力しない)
    # ------------------------------------------------------------------
    def derive_same_trial(self) -> int:
        """同一 Trial を REPORTS する Study 同士を結ぶ。試験登録番号から自動で引ける"""
        added = 0
        for trial in self.of_type(NodeType.TRIAL):
            studies = sorted(self.pred(trial, EdgeType.REPORTS))
            for i, a in enumerate(studies):
                for b in studies[i + 1:]:
                    if b not in self.succ(a, EdgeType.SAME_TRIAL_AS):
                        self.add_edge(a, EdgeType.SAME_TRIAL_AS, b)
                        self.add_edge(b, EdgeType.SAME_TRIAL_AS, a)
                        added += 1
        return added

    # ==================================================================
    # Mindsルールの検証 — 決定論。LLMに判定させない
    # ==================================================================
    def _study_of(self, result_id: str) -> str:
        s = self.pred(result_id, EdgeType.YIELDS)
        return next(iter(s)) if s else None

    def check_r1_eligibility(self) -> list:
        """適格性を持たない StudyResult が総体に寄与していないか"""
        v = []
        for eb in self.of_type(NodeType.EVIDENCE_BODY):
            cq = self.nodes[eb].get("cq")
            for res in self.pred(eb, EdgeType.CONTRIBUTES_TO):
                if cq and cq not in self.succ(res, EdgeType.ELIGIBLE_FOR):
                    v.append({"rule": "R1", "evidence_body": eb, "result": res,
                              "detail": f"{res} は {cq} の適格基準を満たす記録がないまま"
                                        f"エビデンス総体に寄与している"})
        return v

    def check_r2_same_trial(self) -> list:
        """同一試験の複数論文が同じ総体に入っていないか(二重計上)"""
        v = []
        for eb in self.of_type(NodeType.EVIDENCE_BODY):
            results = sorted(self.pred(eb, EdgeType.CONTRIBUTES_TO))
            trial_of = {}
            for res in results:
                st = self._study_of(res)
                if not st:
                    continue
                for tr in self.succ(st, EdgeType.REPORTS):
                    trial_of.setdefault(tr, []).append((res, st))
            for tr, group in trial_of.items():
                if len(group) > 1:
                    v.append({
                        "rule": "R2", "evidence_body": eb, "trial": tr,
                        "results": [r for r, _ in group],
                        "studies": [s for _, s in group],
                        "detail": f"試験 {tr} の複数論文が同一総体に寄与している"
                                  f"(二重計上)。1つを主報告として残し他を除外する",
                    })
        return v

    def check_r3_ma_overlap(self) -> list:
        """メタ解析とその構成研究が同じ総体に入っていないか(二重計上)"""
        v = []
        for eb in self.of_type(NodeType.EVIDENCE_BODY):
            results = sorted(self.pred(eb, EdgeType.CONTRIBUTES_TO))
            studies = {self._study_of(r): r for r in results if self._study_of(r)}
            for st, res in studies.items():
                included = self.succ(st, EdgeType.INCLUDES)
                overlap = sorted(included & set(studies.keys()))
                if overlap:
                    v.append({
                        "rule": "R3", "evidence_body": eb, "meta_analysis": st,
                        "overlapping": overlap,
                        "detail": f"メタ解析 {st} が含む {'・'.join(overlap)} が"
                                  f"同一総体に個別にも寄与している(二重計上)。"
                                  f"MAを採るか個別研究を採るかを決める",
                    })
        return v

    def check_r4_retraction(self) -> list:
        """撤回論文の直接寄与と、2ホップ先(MA経由)への波及"""
        v = []
        retracted = set()
        for st in self.of_type(NodeType.STUDY):
            if self.pred(st, EdgeType.RETRACTS):
                retracted.add(st)
            if self.nodes[st].get("retracted"):
                retracted.add(st)

        for eb in self.of_type(NodeType.EVIDENCE_BODY):
            for res in sorted(self.pred(eb, EdgeType.CONTRIBUTES_TO)):
                st = self._study_of(res)
                if st in retracted:
                    v.append({"rule": "R4", "evidence_body": eb, "study": st,
                              "hops": 1,
                              "detail": f"撤回論文 {st} が直接寄与している。除外が必須"})
                    continue
                # 2ホップ: この総体に寄与するMAが撤回論文を含んでいないか
                bad = sorted(self.succ(st, EdgeType.INCLUDES) & retracted) if st else []
                if bad:
                    v.append({"rule": "R4", "evidence_body": eb, "study": st,
                              "hops": 2, "retracted_inside": bad,
                              "detail": f"メタ解析 {st} が撤回論文 {'・'.join(bad)} を"
                                        f"含んでいる。MAの再計算または除外が必要"
                                        f"(文章を読むだけでは気づけない)"})
        return v

    def check_r6_indirectness(self) -> list:
        """CQのCと異なる対照の結果が、非直接性の格下げなしに使われていないか"""
        v = []
        for eb in self.of_type(NodeType.EVIDENCE_BODY):
            cq = self.nodes[eb].get("cq")
            if not cq:
                continue
            cq_comp = self.nodes[cq].get("comparator_kind", "none")
            downgraded = any(self.nodes[f].get("factor") == "indirectness"
                             for f in self.succ(eb, EdgeType.DOWNGRADED_BY))
            for res in sorted(self.pred(eb, EdgeType.CONTRIBUTES_TO)):
                kinds = {self.nodes[c].get("comparator_kind")
                         for c in self.succ(res, EdgeType.COMPARES_AGAINST)}
                kinds |= {self.nodes[res].get("comparator")}
                kinds = {k for k in kinds if k}
                mismatched = {k for k in kinds if k != cq_comp
                              and k not in DIRECT_COMPARATORS}
                if mismatched and not downgraded:
                    v.append({
                        "rule": "R6", "evidence_body": eb, "result": res,
                        "cq_comparator": cq_comp, "result_comparator": sorted(mismatched),
                        "detail": f"{res} の対照({'・'.join(sorted(mismatched))})は"
                                  f"CQの対照({cq_comp})と異なるが、非直接性の格下げが"
                                  f"記録されていない。方向の判定には使えない",
                    })
        return v

    def check_r7_critical_outcome(self) -> list:
        """重大アウトカムの総体を持たない推奨がないか"""
        v = []
        for rec in self.of_type(NodeType.RECOMMENDATION):
            bodies = self.pred(rec, EdgeType.INFORMS)
            has_critical = False
            for eb in bodies:
                for oc in self.succ(eb, EdgeType.ASSESSES):
                    imp = self.nodes[oc].get("importance")
                    if imp is not None and importance_band(imp) == "critical":
                        has_critical = True
            if not has_critical:
                v.append({"rule": "R7", "recommendation": rec,
                          "detail": f"{rec} は重大アウトカム(重要度7-9)の"
                                    f"エビデンス総体を持たない。推奨を作成できない"})
        return v

    def check_r8_downgrade_reason(self) -> list:
        """確実性A未満なのに格下げ理由が記録されていない総体"""
        v = []
        for eb in self.of_type(NodeType.EVIDENCE_BODY):
            cert = self.nodes[eb].get("certainty")
            if cert and cert != "A" and not self.succ(eb, EdgeType.DOWNGRADED_BY):
                v.append({"rule": "R8", "evidence_body": eb, "certainty": cert,
                          "detail": f"{eb} は確実性{cert}だが格下げ要因が記録されていない。"
                                    f"AGREE II 項目9で減点される"})
        return v

    def validate(self) -> dict:
        """R1-R8 を一括検証"""
        checks = {
            "R1": self.check_r1_eligibility, "R2": self.check_r2_same_trial,
            "R3": self.check_r3_ma_overlap, "R4": self.check_r4_retraction,
            "R6": self.check_r6_indirectness, "R7": self.check_r7_critical_outcome,
            "R8": self.check_r8_downgrade_reason,
        }
        violations = []
        for fn in checks.values():
            violations.extend(fn())
        return {
            "passed": not violations,
            "violations": violations,
            "by_rule": {r: sum(1 for v in violations if v["rule"] == r)
                        for r in checks},
        }

    # ==================================================================
    # R5: 全体確実性の導出(制約ではなく計算)
    # ==================================================================
    def derive_overall_certainty(self, rec: str) -> dict:
        """推奨の確実性 = 重大アウトカムの総体のうち最低の確実性"""
        per_outcome = {}
        for eb in sorted(self.pred(rec, EdgeType.INFORMS)):
            cert = self.nodes[eb].get("certainty")
            for oc in self.succ(eb, EdgeType.ASSESSES):
                imp = self.nodes[oc].get("importance")
                per_outcome[oc] = {"certainty": cert, "importance": imp,
                                   "band": importance_band(imp) if imp is not None else None,
                                   "evidence_body": eb}
        critical = {o: d for o, d in per_outcome.items()
                    if d["band"] == "critical" and d["certainty"]}
        if not critical:
            return {"overall": None, "reason": "重大アウトカムの総体がない(R7違反)",
                    "per_outcome": per_outcome}
        lowest = min(critical.values(),
                     key=lambda d: CERTAINTY_ORDER.index(d["certainty"]))
        return {
            "overall": lowest["certainty"],
            "reason": f"重大アウトカム{len(critical)}件のうち最低の確実性を採用"
                      f"(決定元: {lowest['evidence_body']})",
            "per_outcome": per_outcome,
        }

    # ==================================================================
    # 多段推論 — 文章に書かれていない事実を出す
    # ==================================================================
    def new_evidence_impact(self, new_study: str) -> dict:
        """
        新規論文1本が、既存のどの推奨まで影響するかを辿る。
        Study → StudyResult → EvidenceBody → Recommendation の3ホップ。
        「この論文はどの推奨に効くか」は、どの文書にも書かれていない。
        """
        results = self.succ(new_study, EdgeType.YIELDS)
        bodies, recs = set(), set()
        for r in results:
            bodies |= self.succ(r, EdgeType.CONTRIBUTES_TO)
        for b in bodies:
            recs |= self.succ(b, EdgeType.INFORMS)

        # 同一試験の別報告が既に使われていないか(二重計上の予防)
        dup = set()
        for sib in self.succ(new_study, EdgeType.SAME_TRIAL_AS):
            for r in self.succ(sib, EdgeType.YIELDS):
                if self.succ(r, EdgeType.CONTRIBUTES_TO) & bodies:
                    dup.add(sib)

        return {
            "study": new_study,
            "results": sorted(results),
            "evidence_bodies": sorted(bodies),
            "recommendations": sorted(recs),
            "same_trial_already_used": sorted(dup),
            "note": ("同一試験の別報告が既存総体に入っている。二重計上を避けるため"
                     "主報告を1つ選ぶ" if dup else ""),
        }

    def recommendation_provenance(self, rec: str) -> dict:
        """
        推奨から根拠論文までを逆に辿る。AGREE II 項目12(推奨とエビデンスの
        対応関係)の証跡そのものになる。
        """
        chain = []
        for eb in sorted(self.pred(rec, EdgeType.INFORMS)):
            entry = {"evidence_body": eb,
                     "certainty": self.nodes[eb].get("certainty"),
                     "outcomes": sorted(self.succ(eb, EdgeType.ASSESSES)),
                     "downgraded_by": sorted(
                         self.nodes[f].get("factor", f)
                         for f in self.succ(eb, EdgeType.DOWNGRADED_BY)),
                     "studies": []}
            for res in sorted(self.pred(eb, EdgeType.CONTRIBUTES_TO)):
                st = self._study_of(res)
                entry["studies"].append({
                    "result": res, "study": st,
                    "pmid": self.nodes.get(st, {}).get("pmid") if st else None,
                    "design": self.nodes.get(st, {}).get("design") if st else None,
                })
            chain.append(entry)
        return {"recommendation": rec, "chain": chain,
                "n_studies": sum(len(c["studies"]) for c in chain)}


def rule_reference() -> str:
    """Mindsルールの一覧(委員向け説明用)"""
    lines = ["# グラフ上で走るMinds導出規則", ""]
    for rid, r in MINDS_RULES.items():
        lines.append(f"**{rid} {r['name']}**({r['source']})")
        lines.append(f"  {r['statement']}")
        lines.append("")
    return "\n".join(lines)
