#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Minds guideline RAG generator for RC-1 draft and RC-5 process explanation.

Input: chunk file with page/chapter/CQ metadata and optional EtD metadata.
Output: Markdown generation + retrieval trace + structured JSON for evaluation.

The script is deliberately conservative: it does not ask the LLM to reveal
chain-of-thought; it asks for source-grounded final text only.
"""
from __future__ import annotations

import argparse
import ast
import hashlib
import json
import os
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Sequence, Tuple

os.environ.setdefault("TOKENIZERS_PARALLELISM", "false")

import boto3
from botocore.config import Config
import chromadb
from chromadb.utils import embedding_functions

try:
    from build_and_search_chromadb import parse_chunks_file  # type: ignore
except Exception:
    parse_chunks_file = None


DEFAULT_MODEL_ID = os.getenv(
    "BEDROCK_MODEL_ID",
    "anthropic.claude-3-5-sonnet-20241022-v2:0",
)
DEFAULT_REGION = os.getenv("AWS_REGION", os.getenv("AWS_DEFAULT_REGION", "us-east-1"))


@dataclass(frozen=True)
class Chunk:
    id: str
    content: str
    metadata: Dict[str, Any]


def normalize_cq_name(cq_input: str) -> str:
    s = str(cq_input or "").strip()
    m = re.search(r"(?i)\bCQ\s*([0-9]+)\b", s)
    if m:
        return f"CQ {int(m.group(1))}"
    return s


def cq_number(cq_name: str) -> str:
    m = re.search(r"(?i)CQ\s*([0-9]+)", normalize_cq_name(cq_name))
    if not m:
        raise ValueError(f"CQ番号を解釈できません: {cq_name}")
    return m.group(1)


def safe_json_loads(value: Any) -> Any:
    if value is None:
        return None
    if isinstance(value, (dict, list)):
        return value
    if not isinstance(value, str):
        return value
    text = value.strip()
    if not text:
        return None
    try:
        return json.loads(text)
    except Exception:
        try:
            return ast.literal_eval(text)
        except Exception:
            return value


def chroma_metadata(meta: Dict[str, Any]) -> Dict[str, Any]:
    """Chroma metadata must be scalar. Serialize nested values."""
    out: Dict[str, Any] = {}
    for k, v in (meta or {}).items():
        if v is None:
            out[k] = ""
        elif isinstance(v, (str, int, float, bool)):
            out[k] = v
        else:
            out[k] = json.dumps(v, ensure_ascii=False)
    return out


def fallback_parse_chunks_file(path: Path) -> List[Chunk]:
    """
    Fallback parser.
    Supported formats:
    1) JSONL: {"id":..., "content":..., "metadata":{...}}
    2) JSON list with the same structure
    3) Plain text split by blank lines, with minimal metadata.
    """
    text = path.read_text(encoding="utf-8")
    stripped = text.strip()
    records: List[Dict[str, Any]] = []

    if stripped.startswith("["):
        obj = json.loads(stripped)
        if isinstance(obj, list):
            records = obj
    else:
        for line in text.splitlines():
            line = line.strip()
            if not line:
                continue
            if line.startswith("{") and line.endswith("}"):
                try:
                    records.append(json.loads(line))
                except Exception:
                    records = []
                    break

    if records:
        chunks: List[Chunk] = []
        for i, r in enumerate(records):
            meta = r.get("metadata") or {}
            content = r.get("content") or r.get("document") or r.get("text") or ""
            cid = str(r.get("id") or meta.get("id") or f"chunk_{i:05d}")
            chunks.append(Chunk(cid, str(content), dict(meta)))
        return chunks

    parts = [p.strip() for p in re.split(r"\n\s*\n", text) if p.strip()]
    return [Chunk(f"chunk_{i:05d}", p, {"source": str(path.name)}) for i, p in enumerate(parts)]


def load_chunks(path: Path) -> List[Chunk]:
    if not path.exists():
        raise FileNotFoundError(f"Input file not found: {path}")
    raw: Any
    if parse_chunks_file is not None:
        raw = parse_chunks_file(str(path))
        chunks: List[Chunk] = []
        for i, r in enumerate(raw):
            meta = r.get("metadata") or {}
            content = r.get("content") or r.get("document") or r.get("text") or ""
            cid = str(r.get("id") or meta.get("id") or f"chunk_{i:05d}")
            chunks.append(Chunk(cid, str(content), dict(meta)))
        return chunks
    return fallback_parse_chunks_file(path)


def build_collection(
    chunks: Sequence[Chunk],
    collection_name: str,
    embedding_model: str,
    persist_dir: Optional[Path] = None,
):
    client = chromadb.PersistentClient(path=str(persist_dir)) if persist_dir else chromadb.Client()
    try:
        client.delete_collection(collection_name)
    except Exception:
        pass
    ef = embedding_functions.SentenceTransformerEmbeddingFunction(model_name=embedding_model)
    collection = client.create_collection(collection_name, embedding_function=ef)

    documents = [c.content for c in chunks]
    ids = [c.id for c in chunks]
    metadatas = [chroma_metadata(c.metadata) for c in chunks]
    for start in range(0, len(chunks), 64):
        end = min(start + 64, len(chunks))
        collection.add(documents=documents[start:end], ids=ids[start:end], metadatas=metadatas[start:end])
    return collection


def chunk_mentions_target_cq(content: str, meta: Dict[str, Any], cq: str) -> bool:
    n = cq_number(cq)
    target = re.compile(rf"(?i)\bCQ\s*{re.escape(n)}\b")
    fields = [str(meta.get(k, "")) for k in ("Chapter_or_CQ", "chapter", "cq", "section", "Section")]
    joined = "\n".join(fields + [content[:600]])
    return bool(target.search(joined))


def chunk_mentions_other_cq(content: str, meta: Dict[str, Any], cq: str) -> bool:
    target_n = cq_number(cq)
    fields = [str(meta.get(k, "")) for k in ("Chapter_or_CQ", "chapter", "cq", "section", "Section")]
    joined = "\n".join(fields + [content[:400]])
    nums = re.findall(r"(?i)\bCQ\s*([0-9]+)\b", joined)
    return any(n != target_n for n in nums)


def extract_etd_metadata(chunks: Sequence[Chunk], cq: str) -> Optional[Dict[str, Any]]:
    for c in chunks:
        if not chunk_mentions_target_cq(c.content, c.metadata, cq):
            continue
        for key in ("etd_metadata", "EtD", "etd", "evidence_to_decision"):
            if key in c.metadata and c.metadata.get(key):
                obj = safe_json_loads(c.metadata.get(key))
                if isinstance(obj, dict):
                    return obj
    return None


def retrieve_context(collection, chunks: Sequence[Chunk], cq: str, top_k_per_aspect: int = 6) -> Tuple[Optional[Dict[str, Any]], str, List[Dict[str, Any]]]:
    cq_norm = normalize_cq_name(cq)
    etd = extract_etd_metadata(chunks, cq_norm)

    base_chunks: List[Chunk] = [c for c in chunks if chunk_mentions_target_cq(c.content, c.metadata, cq_norm)]
    selected: Dict[str, Chunk] = {c.id: c for c in base_chunks}
    trace: List[Dict[str, Any]] = []

    aspects = {
        "pico_outcomes": "PICO 対象 介入 比較 アウトカム 臨床疑問 選定 重要度",
        "evidence_body": "エビデンス総体 確実性 バイアスリスク 非一貫性 不精確 SMD RR HR 95%信頼区間",
        "qualitative_sr": "定性的システマティックレビュー 採用文献 RCT 評価シート 研究数",
        "benefit_harm": "益 害 有害事象 重篤 心血管イベント QoL 倦怠感 うつ 生存期間",
        "values_resources": "患者の価値観 嗜好性 負担 経済的負担 費用対効果 受容性 実行可能性",
        "consensus_process": "推奨決定 投票 合意 修正デルファイ パネル会議 推奨の強さ 推奨方向",
    }

    for aspect, keywords in aspects.items():
        query = f"{cq_norm} {keywords}"
        res = collection.query(query_texts=[query], n_results=max(10, top_k_per_aspect * 3))
        docs = res.get("documents", [[]])[0]
        metas = res.get("metadatas", [[]])[0]
        ids = res.get("ids", [[]])[0]
        dists = res.get("distances", [[]])[0] if "distances" in res else [None] * len(ids)
        kept = 0
        for doc, meta, cid, dist in zip(docs, metas, ids, dists):
            meta = dict(meta or {})
            if chunk_mentions_other_cq(doc, meta, cq_norm) and not chunk_mentions_target_cq(doc, meta, cq_norm):
                continue
            if cid not in selected:
                selected[cid] = Chunk(cid, doc, meta)
            trace.append({"aspect": aspect, "chunk_id": cid, "distance": dist, "metadata": meta})
            kept += 1
            if kept >= top_k_per_aspect:
                break

    context_parts: List[str] = []
    for i, c in enumerate(selected.values(), 1):
        page = c.metadata.get("page") or c.metadata.get("Page") or c.metadata.get("source_page") or ""
        section = c.metadata.get("Section") or c.metadata.get("section") or c.metadata.get("Chapter_or_CQ") or ""
        context_parts.append(
            f"<chunk id=\"{c.id}\" page=\"{page}\" section=\"{section}\">\n{c.content}\n</chunk>"
        )
    return etd, "\n\n".join(context_parts), trace


def bedrock_call(model_id: str, region: str, system: str, user: str, max_tokens: int = 8192) -> str:
    client = boto3.client("bedrock-runtime", region_name=region, config=Config(read_timeout=300, retries={"max_attempts": 3}))
    body = json.dumps(
        {
            "anthropic_version": "bedrock-2023-05-31",
            "max_tokens": max_tokens,
            "temperature": 0,
            "system": system,
            "messages": [{"role": "user", "content": user}],
        },
        ensure_ascii=False,
    )
    response = client.invoke_model(modelId=model_id, body=body, accept="application/json", contentType="application/json")
    payload = json.loads(response["body"].read())
    return "".join(block.get("text", "") for block in payload.get("content", []) if block.get("type") == "text")


def make_system_prompt(output_type: str) -> str:
    if output_type == "rc1":
        template = """
# RC-1 草案
## CQ
## 推奨文案
## 推奨の強さ
## エビデンスの確実性
## PICO
## アウトカム
## 採用文献・根拠
## EtD判断要約
## 根拠の限界
""".strip()
    elif output_type == "rc5":
        template = """
# RC-5 推奨作成過程
## 1. 臨床疑問の定式化（PICO）とアウトカムの選定
## 2. エビデンスの確実性と益害バランスの評価
## 3. 価値観、嗜好性、医療経済・実装に関する検討
## 4. 推奨の強さと方向性の決定（合意形成プロセス）
""".strip()
    else:
        raise ValueError(output_type)

    return f"""
あなたは診療ガイドライン作成方法論に詳しい医療文書作成支援者です。
入力されたEtDメタデータとRAGチャンクのみを根拠に、{output_type.upper()}を日本語で作成してください。

厳守事項:
1. 入力にない事実、数値、PMID、DOI、判断理由を補完しない。
2. 主要な主張の末尾に、根拠となるチャンクIDを [chunk:ID] 形式で付す。
3. EtDメタデータとRAGチャンクが矛盾する場合は、矛盾を明示し、断定しない。
4. "記載なし"、空欄、根拠不明の項目は、推測せず「記載なし」または「根拠チャンク上は確認不能」と書く。
5. 思考過程やchain-of-thoughtは出力しない。結論、根拠、限界のみを書く。
6. 出力構成は次のテンプレートに従う。

{template}
""".strip()


def make_user_prompt(cq: str, etd: Optional[Dict[str, Any]], context: str) -> str:
    return f"""
対象CQ: {normalize_cq_name(cq)}

<etd_metadata>
{json.dumps(etd or {}, ensure_ascii=False, indent=2)}
</etd_metadata>

<rag_chunks>
{context}
</rag_chunks>
""".strip()


def extract_structured_from_outputs(cq: str, rc1_text: str, rc5_text: str, model_id: str, region: str) -> Dict[str, Any]:
    system = """
あなたは評価用データ抽出器です。入力されたRC-1/RC-5から、評価に必要なフィールドだけをJSONで返してください。
推測は禁止。存在しない値はnullまたは空配列にしてください。JSON以外は出力しない。
""".strip()
    user = f"""
抽出対象CQ: {normalize_cq_name(cq)}

出力JSONスキーマ:
{{
  "cq": "",
  "pico": {{"P": "", "I": "", "C": "", "O": []}},
  "recommendation_direction": "for|against|none|unclear",
  "recommendation_strength": "strong|weak|none|unclear",
  "evidence_certainty": "A|B|C|D|unclear",
  "recommendation_text": "",
  "etd_judgments": {{}},
  "references": [{{"pmid": "", "doi": "", "citation": ""}}],
  "unsupported_or_uncited_claims": []
}}

<rc1>
{rc1_text}
</rc1>
<rc5>
{rc5_text}
</rc5>
""".strip()
    raw = bedrock_call(model_id, region, system, user, max_tokens=4096)
    m = re.search(r"\{.*\}", raw, flags=re.S)
    return json.loads(m.group(0) if m else raw)


def main() -> None:
    parser = argparse.ArgumentParser(description="Generate Minds RC-1 and RC-5 from EtD + RAG chunks.")
    parser.add_argument("--cq", required=True, help="CQ1, CQ 2, etc.")
    parser.add_argument("--input_file", required=True, help="Chunk file path")
    parser.add_argument("--output_dir", default="results/generations")
    parser.add_argument("--collection", default="minds_guideline_chunks")
    parser.add_argument("--embedding_model", default="intfloat/multilingual-e5-base")
    parser.add_argument("--persist_dir", default=None)
    parser.add_argument("--bedrock_model_id", default=DEFAULT_MODEL_ID)
    parser.add_argument("--bedrock_region", default=DEFAULT_REGION)
    parser.add_argument("--skip_llm", action="store_true", help="Only build retrieval trace, no Bedrock call.")
    args = parser.parse_args()

    input_path = Path(args.input_file)
    output_dir = Path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    retrieval_dir = output_dir.parent / "retrievals"
    retrieval_dir.mkdir(parents=True, exist_ok=True)

    chunks = load_chunks(input_path)
    if not chunks:
        raise RuntimeError("No chunks loaded.")

    collection = build_collection(
        chunks,
        args.collection,
        args.embedding_model,
        Path(args.persist_dir) if args.persist_dir else None,
    )
    etd, context, trace = retrieve_context(collection, chunks, args.cq)

    cq_label = normalize_cq_name(args.cq).replace(" ", "")
    context_hash = hashlib.sha256(context.encode("utf-8")).hexdigest()[:12]
    trace_payload = {"cq": normalize_cq_name(args.cq), "context_sha256_12": context_hash, "etd_metadata": etd, "retrieval_trace": trace, "context": context}
    (retrieval_dir / f"{cq_label}_retrieval_trace.json").write_text(json.dumps(trace_payload, ensure_ascii=False, indent=2), encoding="utf-8")

    if args.skip_llm:
        return

    user_prompt = make_user_prompt(args.cq, etd, context)
    rc1 = bedrock_call(args.bedrock_model_id, args.bedrock_region, make_system_prompt("rc1"), user_prompt)
    rc5 = bedrock_call(args.bedrock_model_id, args.bedrock_region, make_system_prompt("rc5"), user_prompt)

    rc1_path = output_dir / f"{cq_label}_RC1_draft.md"
    rc5_path = output_dir / f"{cq_label}_RC5_process.md"
    rc1_path.write_text(rc1, encoding="utf-8")
    rc5_path.write_text(rc5, encoding="utf-8")

    try:
        structured = extract_structured_from_outputs(args.cq, rc1, rc5, args.bedrock_model_id, args.bedrock_region)
    except Exception as e:
        structured = {"error": f"structured extraction failed: {e}"}
    (output_dir / f"{cq_label}_prediction_structured.json").write_text(json.dumps(structured, ensure_ascii=False, indent=2), encoding="utf-8")

    print(json.dumps({"rc1": str(rc1_path), "rc5": str(rc5_path), "structured": str(output_dir / f"{cq_label}_prediction_structured.json"), "retrieval": str(retrieval_dir / f"{cq_label}_retrieval_trace.json")}, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
