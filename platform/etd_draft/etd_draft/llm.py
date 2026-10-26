"""LLM クライアント抽象化。

provider:
  none     — LLM を呼ばない（決定論的抽出のみでワークシートを作る）
  mock     — 候補段落からそれらしい JSON を機械生成（テスト・配線確認用。内容に意味はない）
  bedrock  — Amazon Bedrock Converse API（既定リージョン ap-northeast-1、APAC クロスリージョン推論プロファイル）
  openai   — OpenAI 互換 API（vLLM の Qwen など。ETD_OPENAI_BASE_URL / ETD_OPENAI_API_KEY）
"""

from __future__ import annotations

import json
import os
import re
from dataclasses import dataclass
from typing import Protocol


class LLM(Protocol):
    name: str

    def complete(self, system: str, user: str) -> str: ...


@dataclass
class NoneLLM:
    name: str = "none"

    def complete(self, system: str, user: str) -> str:  # pragma: no cover - never called
        raise RuntimeError("provider=none では LLM は呼ばれません")


@dataclass
class MockLLM:
    """プロンプト中の候補段落 ID を拾い、各基準に 1 文ずつ割り当てた JSON を返す。

    verify の配線と描画確認のためだけに存在する。判断はすべて「情報なし」。
    """

    name: str = "mock"

    def complete(self, system: str, user: str) -> str:
        # プロンプト内の "## <criterion_id> 候補段落: id1, id2" を拾う
        out: dict = {"criteria": {}, "conclusion": {"open_questions_for_panel": ["（mock）委員で確認してください"]}}
        for m in re.finditer(r"### 基準 (\w+)（[^）]*）\n候補段落: ([^\n]*)", user):
            cid, ids = m.group(1), [s.strip() for s in m.group(2).split(",") if s.strip() and s.strip() != "なし"]
            ev = []
            if ids:
                ev.append({"statement": f"（mock）元GL段落 {ids[0]} に関連記載あり。", "passage_ids": ids[:1]})
            out["criteria"][cid] = {
                "judgment": "情報なし",
                "research_evidence": ev,
                "additional_considerations": [],
                "rationale": "（mock）",
                "confidence": "none",
            }
        return json.dumps(out, ensure_ascii=False)


@dataclass
class BedrockLLM:
    model_id: str = os.environ.get("ETD_BEDROCK_MODEL", "apac.anthropic.claude-sonnet-4-5-20250929-v1:0")
    region: str = os.environ.get("AWS_REGION", "ap-northeast-1")
    max_tokens: int = 8000
    temperature: float = 0.0

    @property
    def name(self) -> str:
        return f"bedrock:{self.model_id}"

    def complete(self, system: str, user: str) -> str:
        import boto3  # 遅延 import（ローカルテストで boto3 不要にするため）

        client = boto3.client("bedrock-runtime", region_name=self.region)
        resp = client.converse(
            modelId=self.model_id,
            system=[{"text": system}],
            messages=[{"role": "user", "content": [{"text": user}]}],
            inferenceConfig={"maxTokens": self.max_tokens, "temperature": self.temperature},
        )
        return "".join(part.get("text", "") for part in resp["output"]["message"]["content"])


@dataclass
class OpenAICompatLLM:
    """vLLM / OpenAI 互換エンドポイント。依存を増やさないため urllib を使う。"""

    model: str = os.environ.get("ETD_OPENAI_MODEL", "Qwen/Qwen3-32B")
    base_url: str = os.environ.get("ETD_OPENAI_BASE_URL", "http://localhost:8000/v1")
    api_key: str = os.environ.get("ETD_OPENAI_API_KEY", "EMPTY")
    max_tokens: int = 8000
    temperature: float = 0.0

    @property
    def name(self) -> str:
        return f"openai:{self.model}"

    def complete(self, system: str, user: str) -> str:
        import urllib.request

        body = json.dumps(
            {
                "model": self.model,
                "messages": [{"role": "system", "content": system}, {"role": "user", "content": user}],
                "max_tokens": self.max_tokens,
                "temperature": self.temperature,
            }
        ).encode("utf-8")
        req = urllib.request.Request(
            f"{self.base_url.rstrip('/')}/chat/completions",
            data=body,
            headers={"Content-Type": "application/json", "Authorization": f"Bearer {self.api_key}"},
        )
        with urllib.request.urlopen(req, timeout=600) as r:
            data = json.loads(r.read().decode("utf-8"))
        return data["choices"][0]["message"]["content"]


def make_llm(provider: str, model: str | None = None) -> LLM:
    provider = provider.lower()
    if provider == "none":
        return NoneLLM()
    if provider == "mock":
        return MockLLM()
    if provider == "bedrock":
        return BedrockLLM(model_id=model) if model else BedrockLLM()
    if provider == "openai":
        return OpenAICompatLLM(model=model) if model else OpenAICompatLLM()
    raise ValueError(f"未知の provider: {provider}")


def extract_json(text: str) -> dict:
    """LLM 出力から最初の JSON オブジェクトを取り出す（```json フェンス対応）。"""
    text = text.strip()
    fence = re.search(r"```(?:json)?\s*(\{.*\})\s*```", text, re.S)
    if fence:
        text = fence.group(1)
    start = text.find("{")
    end = text.rfind("}")
    if start == -1 or end == -1:
        raise ValueError("LLM 出力に JSON が含まれていません")
    return json.loads(text[start : end + 1])
