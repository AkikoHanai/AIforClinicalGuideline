"""
エビデンス・グラフのスキーマ — Minds由来の閉じたエッジ語彙
==========================================================
設計思想:
  ノード = 個別論文結果(論文 × アウトカム × 比較)
  エッジ = 論文・結果・総体・推奨をつなぐ証拠関係。**型はMinds由来の閉じた語彙に限る**
  Mindsルール = グラフ上を走る導出規則・制約(エッジではない)

なぜエッジ型を閉じるか:
  自由記述の関係は、もっともらしい嘘をいくらでも作れる。型を有限にすると
  作れる主張が有限になる。さらに既存ノードと接続しない関係はそもそも書けない。

なぜ粒度を「論文」でなく「論文×アウトカム×比較」にするか:
  MindsのSR-5評価シートがアウトカムの型ごと(二値/連続/ハザード比)に分かれており、
  バイアスリスクもアウトカム単位で判定する。1論文1ノードにすると
  「疼痛では低リスクだがQOLでは高リスク」を表現できない。
"""
from enum import Enum


# ==================================================================
# ノード型
# ==================================================================
class NodeType(str, Enum):
    TRIAL = "Trial"                    # 試験(登録番号で同定)
    STUDY = "Study"                    # 論文1本
    STUDY_RESULT = "StudyResult"       # 論文 × アウトカム × 比較 ← 最小単位
    OUTCOME = "Outcome"
    EVIDENCE_BODY = "EvidenceBody"     # CQ × アウトカム(Minds 4.4)
    RECOMMENDATION = "Recommendation"
    CQ = "ClinicalQuestion"
    FACTOR = "Factor"                  # 格下げ/格上げ要因


# ==================================================================
# エッジ型 — Minds由来の閉じた語彙。ここにない関係は書けない
# ==================================================================
class EdgeType(str, Enum):
    # --- 論文・試験レベル(二重計上の検出に使う) ---
    REPORTS = "reports"                        # Study → Trial
    SAME_TRIAL_AS = "same-trial-as"            # Study ↔ Study(導出)
    INCLUDES = "includes"                      # Study[MA] → Study[個別研究]
    RETRACTS = "retracts"                      # Study → Study
    SECONDARY_ANALYSIS_OF = "secondary-analysis-of"  # Study → Study

    # --- 結果レベル ---
    YIELDS = "yields"                          # Study → StudyResult
    MEASURES = "measures"                      # StudyResult → Outcome
    COMPARES_AGAINST = "compares-against"      # StudyResult → 対照の種類

    # --- 評価レベル(Minds 4.3) ---
    ELIGIBLE_FOR = "eligible-for"              # StudyResult → CQ(適格基準を満たす)

    # --- 総体レベル(Minds 4.4) ---
    CONTRIBUTES_TO = "contributes-to"          # StudyResult → EvidenceBody
    DOWNGRADED_BY = "downgraded-by"            # EvidenceBody → Factor
    UPGRADED_BY = "upgraded-by"                # EvidenceBody → Factor
    ASSESSES = "assesses"                      # EvidenceBody → Outcome

    # --- 推奨レベル(Minds 6.2-6.3) ---
    INFORMS = "informs"                        # EvidenceBody → Recommendation
    ADDRESSES = "addresses"                    # Recommendation → CQ

    # --- CQレベル ---
    HAS_POPULATION = "has-population"
    HAS_INTERVENTION = "has-intervention"
    HAS_COMPARATOR = "has-comparator"
    HAS_OUTCOME = "has-outcome"

    # --- 版間(改訂で使う) ---
    SUPERSEDES = "supersedes"                  # Recommendation → Recommendation


# 導出されるエッジ(人手で入力しない。機械が引く)
DERIVED_EDGES = {EdgeType.SAME_TRIAL_AS}

# 機械抽出できるエッジ(人手入力を減らせる)
MACHINE_EXTRACTABLE = {
    EdgeType.REPORTS: "PubMed の secondary source ID(NCT/UMIN/jRCT)から抽出",
    EdgeType.SAME_TRIAL_AS: "同一Trialを REPORTS する Study 同士から導出",
    EdgeType.RETRACTS: "PubMed の publication type / retraction notice から抽出",
    EdgeType.INCLUDES: "メタ解析の採用文献リスト(参考文献)から抽出",
}

# 人手入力が必要なエッジ(二次スクリーニング時に入力する)
MANUAL_REQUIRED = {
    EdgeType.COMPARES_AGAINST: "対照の種類。実対照との差なしを反証と誤判定しないために必須",
    EdgeType.ELIGIBLE_FOR: "適格基準の判定",
    EdgeType.MEASURES: "報告アウトカムの同定(概念解決で半自動化可)",
}


# ==================================================================
# 対照の種類(既存の surveillance.py と整合させる)
# ==================================================================
DIRECT_COMPARATORS = {"none", "usual_care", "placebo"}
ACTIVE_COMPARATORS = {"active_weaker", "active_different"}


# ==================================================================
# GRADE 格下げ/格上げ要因(Minds 4.4)
# ==================================================================
DOWNGRADE_FACTORS = ["risk_of_bias", "inconsistency", "indirectness",
                     "imprecision", "publication_bias"]
UPGRADE_FACTORS = ["large_effect", "dose_response", "opposing_confounding"]

CERTAINTY_ORDER = ["D", "C", "B", "A"]     # 低 → 高


# ==================================================================
# アウトカム重要度(GRADE。Minds 3.3 でSR前に確定)
# ==================================================================
def importance_band(score: int) -> str:
    if score >= 7:
        return "critical"      # 重大
    if score >= 4:
        return "important"     # 重要
    return "limited"           # 重要でない


# ==================================================================
# Minds導出規則 — グラフ上を走る制約。エッジではない
# ==================================================================
MINDS_RULES = {
    "R1": {
        "name": "適格性フィルタ",
        "source": "Minds 3.5 / 4.2",
        "statement": "ELIGIBLE_FOR を持たない StudyResult は CONTRIBUTES_TO できない",
    },
    "R2": {
        "name": "同一試験の二重計上禁止",
        "source": "Minds 4.4(エビデンス総体の評価)",
        "statement": "同一 Trial を REPORTS する Study 群からは、1つの StudyResult のみが "
                     "同一 EvidenceBody に CONTRIBUTES_TO できる",
    },
    "R3": {
        "name": "メタ解析と構成研究の二重計上禁止",
        "source": "Minds 4.4",
        "statement": "Study[MA] が INCLUDES する Study と、その MA 自身の StudyResult が "
                     "同一 EvidenceBody に同時に CONTRIBUTES_TO できない",
    },
    "R4": {
        "name": "撤回の波及",
        "source": "Minds 4.1 / 8.4",
        "statement": "RETRACTS されている Study の StudyResult は CONTRIBUTES_TO できない。"
                     "さらにその Study を INCLUDES する MA は再評価が必要",
    },
    "R5": {
        "name": "全体確実性の決定",
        "source": "Minds 4.4 / GRADE",
        "statement": "推奨の確実性 = 重大アウトカム(重要度7-9)の EvidenceBody のうち最も低い確実性",
    },
    "R6": {
        "name": "非直接性の判定",
        "source": "Minds 4.4(非直接性)",
        "statement": "StudyResult の COMPARES_AGAINST が CQ の HAS_COMPARATOR と異なる場合、"
                     "非直接性による格下げ候補。方向の判定には使えない",
    },
    "R7": {
        "name": "重大アウトカムの必要性",
        "source": "Minds 6.2 / GRADE",
        "statement": "重大アウトカムの EvidenceBody を1つも持たない Recommendation は作成できない",
    },
    "R8": {
        "name": "格下げ要因の明示",
        "source": "Minds 4.4 / AGREE II 項目9",
        "statement": "確実性が A 未満の EvidenceBody は、DOWNGRADED_BY を少なくとも1つ持つ。"
                     "理由なき格下げは記載不備",
    },
}
