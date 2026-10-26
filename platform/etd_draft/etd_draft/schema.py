"""データモデル（Pydantic v2）。

ガイドラインは「編集対象の文書」ではなく「バージョン管理された状態」として扱い、
DOCX/Markdown は状態の描画に過ぎない（CPG 改訂システム設計と同じ方針）。
"""

from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field

from .criteria import NO_INFO


# ────────────────────────── 元ガイドラインの構造化 ──────────────────────────


class Passage(BaseModel):
    """元ガイドラインの最小引用単位（段落）。LLM はこの id でしか引用できない。"""

    id: str  # 例: "CQ3-p012"
    cq_code: str | None = None  # 所属 CQ（前文などは None）
    text: str
    page: int | None = None  # PDF ページ番号（1 始まり）
    source_file: str


class Provenance(BaseModel):
    """決定論的抽出の出典。"""

    passage_ids: list[str] = Field(default_factory=list)
    method: Literal["regex", "llm", "manual"] = "regex"


class Extracted(BaseModel):
    """規則ベースで抽出した値 + その出典。見つからなければ value=情報なし。"""

    value: str = NO_INFO
    provenance: Provenance = Field(default_factory=Provenance)


class CQRecord(BaseModel):
    """1 つの CQ に関する元ガイドラインの構造化状態。"""

    code: str  # "CQ3" など（NFKC 正規化済み）
    title: str  # 見出し行の本文
    passages: list[Passage]
    recommendation_text: Extracted = Field(default_factory=Extracted)
    recommendation_strength: Extracted = Field(default_factory=Extracted)  # 1(強)/2(弱)/推奨なし
    evidence_certainty: Extracted = Field(default_factory=Extracted)  # ⊕表記
    direction: Extracted = Field(default_factory=Extracted)  # 実施する/しない
    outcomes: list[str] = Field(default_factory=list)
    pico: dict[str, str] = Field(default_factory=dict)  # P/I/C/O（見つかった場合のみ）

    def passage_map(self) -> dict[str, Passage]:
        return {p.id: p for p in self.passages}


class GuidelineState(BaseModel):
    source_files: list[str]
    guideline_title: str | None = None
    ingested_at: datetime = Field(default_factory=datetime.now)
    cqs: list[CQRecord]
    orphan_passages: list[Passage] = Field(default_factory=list)  # CQ に属さない前文など


# ────────────────────────── EtD ワークシート（AI 下書き） ──────────────────────────


class EvidenceStatement(BaseModel):
    """「研究のエビデンス」欄の 1 文。必ず passage_ids で元 GL を指す。"""

    statement: str
    passage_ids: list[str]
    # verify が付与するフラグ
    verified: bool | None = None
    overlap_score: float | None = None  # 引用先との語彙重複（0–1）。低いと「要確認」
    flags: list[str] = Field(default_factory=list)


class CriterionDraft(BaseModel):
    criterion_id: str
    judgment: str = NO_INFO  # criteria.allowed_judgments() の中からのみ
    research_evidence: list[EvidenceStatement] = Field(default_factory=list)
    # 元 GL 本文から機械的に拾った候補段落（LLM なしモードでの主出力。LLM モードでは参考）
    candidate_passage_ids: list[str] = Field(default_factory=list)
    additional_considerations: list[str] = Field(default_factory=list)  # 委員への論点提示（事実主張は不可）
    rationale: str = ""  # 判断に至った理由（LLM の説明。出典必須ではないが事実の新規主張は不可）
    confidence: Literal["high", "medium", "low", "none"] = "none"
    flags: list[str] = Field(default_factory=list)
    # 委員（パネル）記入欄 — 常に空で出力される
    panel_judgment: str = ""
    panel_notes: str = ""


class EtDConclusion(BaseModel):
    old_recommendation_text: str = NO_INFO
    old_strength: str = NO_INFO
    old_certainty: str = NO_INFO
    recommendation_type_old: str = NO_INFO  # 旧 GL から読み取れる推奨タイプ
    certainty_to_strength_logic: str = ""  # 旧 GL が推奨の強さをどう導いたか（本文にあれば）
    open_questions_for_panel: list[str] = Field(default_factory=list)


class EtDWorksheet(BaseModel):
    schema_version: str = "etd-draft/0.1"
    cq_code: str
    cq_title: str
    pico: dict[str, str] = Field(default_factory=dict)
    perspective: str = "individual"
    generated_at: datetime = Field(default_factory=datetime.now)
    generator: str  # "none" / "mock" / "bedrock:<model>" / "openai:<model>"
    criteria: list[CriterionDraft]
    conclusion: EtDConclusion = Field(default_factory=EtDConclusion)
    # 検証結果
    verification: dict = Field(default_factory=dict)
    status: Literal["draft", "verified", "rejected"] = "draft"

    def criterion(self, cid: str) -> CriterionDraft:
        for c in self.criteria:
            if c.criterion_id == cid:
                return c
        raise KeyError(cid)
