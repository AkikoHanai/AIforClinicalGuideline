#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Evaluation script for Minds guideline RAG -> RC-1/RC-5 generation.

Gold JSON and prediction JSON are compared on:
- CQ extraction
- PICO extraction
- recommendation direction / strength / evidence certainty
- recommendation semantic agreement
- EtD item agreement
- PMID/DOI-based reference agreement
- unsupported-claim rate and optional LLM fact consistency
- optional expert usability ratings
"""
from __future__ import annotations

import argparse
import csv
import json
import math
import os
import re
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Sequence, Tuple

import boto3
from botocore.config import Config

DEFAULT_MODEL_ID = os.getenv("BEDROCK_MODEL_ID", "anthropic.claude-3-5-sonnet-20241022-v2:0")
DEFAULT_REGION = os.getenv("AWS_REGION", os.getenv("AWS_DEFAULT_REGION", "us-east-1"))


def load_json(path: str | Path) -> Dict[str, Any]:
    return json.loads(Path(path).read_text(encoding="utf-8"))


def normalize_text(s: Any) -> str:
    s = "" if s is None else str(s)
    s = s.replace("　", " ").strip().lower()
    s = re.sub(r"\s+", " ", s)
    return s


def normalize_cq(s: Any) -> str:
    m = re.search(r"(?i)cq\s*([0-9]+)", str(s or ""))
    return f"CQ{int(m.group(1))}" if m else normalize_text(s).upper()


def normalize_direction(s: Any) -> str:
    t = normalize_text(s)
    if t in {"for", "recommend_for", "推奨する", "提案する", "賛成"} or "勧める" in t or "提案" in t:
        return "for"
    if t in {"against", "recommend_against", "推奨しない", "反対"} or "勧めない" in t:
        return "against"
    if t in {"none", "no_recommendation", "推奨なし"}:
        return "none"
    return "unclear"


def normalize_strength(s: Any) -> str:
    t = normalize_text(s)
    if t in {"strong", "強", "強い"} or "strong" in t or "強い" in t:
        return "strong"
    if t in {"weak", "弱", "弱い", "conditional"} or "weak" in t or "弱" in t or "条件" in t or "提案" in t:
        return "weak"
    if t in {"none", "なし"}:
        return "none"
    return "unclear"


def normalize_grade(s: Any) -> str:
    t = str(s or "").upper()
    for g in ["A", "B", "C", "D"]:
        if re.search(rf"\b{g}\b", t) or f"（{g}）" in t or f"({g})" in t:
            return g
    if "強" in str(s):
        return "A"
    if "中" in str(s):
        return "B"
    if "弱" in str(s):
        return "C"
    if "非常" in str(s) or "とても" in str(s):
        return "D"
    return "unclear"


def exact(a: Any, b: Any) -> float:
    return 1.0 if normalize_text(a) == normalize_text(b) else 0.0


def f1_set(gold: Iterable[str], pred: Iterable[str]) -> Dict[str, float]:
    g = {normalize_text(x) for x in gold if normalize_text(x)}
    p = {normalize_text(x) for x in pred if normalize_text(x)}
    if not g and not p:
        return {"precision": 1.0, "recall": 1.0, "f1": 1.0}
    if not p:
        return {"precision": 0.0, "recall": 0.0, "f1": 0.0}
    tp = len(g & p)
    precision = tp / len(p) if p else 0.0
    recall = tp / len(g) if g else 0.0
    f1 = 2 * precision * recall / (precision + recall) if precision + recall else 0.0
    return {"precision": precision, "recall": recall, "f1": f1}


def bleu_like(reference: str, hypothesis: str, max_n: int = 4) -> float:
    ref = list(normalize_text(reference))
    hyp = list(normalize_text(hypothesis))
    if not ref or not hyp:
        return 0.0
    precisions = []
    for n in range(1, max_n + 1):
        ref_ngrams = {}
        hyp_ngrams = {}
        for i in range(len(ref) - n + 1):
            ref_ngrams[tuple(ref[i:i+n])] = ref_ngrams.get(tuple(ref[i:i+n]), 0) + 1
        for i in range(len(hyp) - n + 1):
            hyp_ngrams[tuple(hyp[i:i+n])] = hyp_ngrams.get(tuple(hyp[i:i+n]), 0) + 1
        overlap = sum(min(c, ref_ngrams.get(k, 0)) for k, c in hyp_ngrams.items())
        total = max(sum(hyp_ngrams.values()), 1)
        precisions.append((overlap + 1) / (total + 1))
    bp = 1.0 if len(hyp) > len(ref) else math.exp(1 - len(ref) / max(len(hyp), 1))
    return bp * math.exp(sum(math.log(p) for p in precisions) / max_n)


def semantic_similarity(reference: str, hypothesis: str, model_name: str = "intfloat/multilingual-e5-base") -> Optional[float]:
    try:
        from sentence_transformers import SentenceTransformer
        import numpy as np
        model = SentenceTransformer(model_name)
        emb = model.encode([reference, hypothesis], normalize_embeddings=True)
        return float(np.dot(emb[0], emb[1]))
    except Exception:
        return None


def normalize_identifier(s: Any) -> str:
    t = str(s or "").strip().lower()
    t = re.sub(r"^(doi:|pmid:)", "", t)
    t = t.replace("https://doi.org/", "")
    return t


def collect_refs(obj: Dict[str, Any]) -> List[str]:
    refs = []
    for r in obj.get("references", []) or []:
        if isinstance(r, dict):
            for k in ("pmid", "doi"):
                val = normalize_identifier(r.get(k))
                if val:
                    refs.append(val)
        else:
            ids = re.findall(r"10\.\d{4,9}/[-._;()/:A-Za-z0-9]+|PMID[:\s]*\d+", str(r))
            refs.extend(normalize_identifier(x) for x in ids)
    return refs


def flatten_etd(d: Any, prefix: str = "") -> Dict[str, str]:
    out: Dict[str, str] = {}
    if isinstance(d, dict):
        for k, v in d.items():
            key = f"{prefix}.{k}" if prefix else str(k)
            out.update(flatten_etd(v, key))
    elif isinstance(d, list):
        out[prefix] = " | ".join(normalize_text(x) for x in d)
    else:
        out[prefix] = normalize_text(d)
    return out


def etd_item_agreement(gold: Dict[str, Any], pred: Dict[str, Any]) -> Dict[str, Any]:
    g = flatten_etd(gold.get("etd_judgments", {}) or {})
    p = flatten_etd(pred.get("etd_judgments", {}) or {})
    if not g:
        return {"agreement": None, "matched": 0, "total": 0, "details": []}
    details = []
    matched = 0
    for k, gv in g.items():
        pv = p.get(k, "")
        ok = 1 if gv and gv == pv else 0
        matched += ok
        details.append({"item": k, "gold": gv, "pred": pv, "match": ok})
    return {"agreement": matched / len(g), "matched": matched, "total": len(g), "details": details}


def bedrock_call(model_id: str, region: str, system: str, user: str, max_tokens: int = 2048) -> str:
    client = boto3.client("bedrock-runtime", region_name=region, config=Config(read_timeout=300, retries={"max_attempts": 3}))
    body = json.dumps(
        {"anthropic_version": "bedrock-2023-05-31", "max_tokens": max_tokens, "temperature": 0, "system": system, "messages": [{"role": "user", "content": user}]},
        ensure_ascii=False,
    )
    response = client.invoke_model(modelId=model_id, body=body, accept="application/json", contentType="application/json")
    payload = json.loads(response["body"].read())
    return "".join(b.get("text", "") for b in payload.get("content", []) if b.get("type") == "text")


def fact_consistency_llm(prediction_text: str, retrieved_context: str, model_id: str, region: str) -> Dict[str, Any]:
    system = """
You are a strict medical guideline fact checker. Use only the retrieved context.
Return JSON only: {"supported_claims": int, "unsupported_claims": int, "unsupported_rate": float, "unsupported_examples": [string], "verdict": "pass|fail"}.
A claim is unsupported if it adds facts, numbers, citations, judgments, or mechanisms not present in the context.
""".strip()
    user = f"""
<retrieved_context>
{retrieved_context[:120000]}
</retrieved_context>
<prediction>
{prediction_text[:40000]}
</prediction>
""".strip()
    raw = bedrock_call(model_id, region, system, user)
    m = re.search(r"\{.*\}", raw, flags=re.S)
    return json.loads(m.group(0) if m else raw)


def expert_usability_rate(csv_path: Optional[str]) -> Optional[Dict[str, Any]]:
    if not csv_path:
        return None
    rows = list(csv.DictReader(open(csv_path, encoding="utf-8")))
    if not rows:
        return {"usable_rate": None, "n": 0}
    usable = 0
    for r in rows:
        val = normalize_text(r.get("usable") or r.get("使用可能") or r.get("判定") or "")
        if val in {"1", "true", "yes", "使用可能", "usable", "可"}:
            usable += 1
    return {"usable_rate": usable / len(rows), "usable": usable, "n": len(rows)}


def evaluate(gold: Dict[str, Any], pred: Dict[str, Any], args: argparse.Namespace) -> Dict[str, Any]:
    result: Dict[str, Any] = {}
    result["cq_match"] = 1.0 if normalize_cq(gold.get("cq")) == normalize_cq(pred.get("cq")) else 0.0

    gp = gold.get("pico", {}) or {}
    pp = pred.get("pico", {}) or {}
    pico_scores = {
        "P": exact(gp.get("P"), pp.get("P")),
        "I": exact(gp.get("I"), pp.get("I")),
        "C": exact(gp.get("C"), pp.get("C")),
        "O": f1_set(gp.get("O", []) or [], pp.get("O", []) or []),
    }
    result["pico"] = pico_scores

    result["recommendation_direction_match"] = 1.0 if normalize_direction(gold.get("recommendation_direction")) == normalize_direction(pred.get("recommendation_direction")) else 0.0
    result["recommendation_strength_match"] = 1.0 if normalize_strength(gold.get("recommendation_strength")) == normalize_strength(pred.get("recommendation_strength")) else 0.0
    result["evidence_certainty_match"] = 1.0 if normalize_grade(gold.get("evidence_certainty")) == normalize_grade(pred.get("evidence_certainty")) else 0.0

    ref_text = gold.get("recommendation_text", "") or ""
    hyp_text = pred.get("recommendation_text", "") or ""
    result["recommendation_text"] = {
        "bleu_like": bleu_like(ref_text, hyp_text),
        "semantic_similarity": semantic_similarity(ref_text, hyp_text, args.embedding_model) if args.semantic else None,
    }

    result["etd"] = etd_item_agreement(gold, pred)
    result["references"] = f1_set(collect_refs(gold), collect_refs(pred))

    unsupported = pred.get("unsupported_or_uncited_claims", []) or []
    supported_claim_n = pred.get("supported_claim_count") or None
    if supported_claim_n is not None:
        denom = int(supported_claim_n) + len(unsupported)
        result["unsupported_claim_rate"] = len(unsupported) / denom if denom else 0.0
    else:
        result["unsupported_claim_rate"] = None

    if args.fact_check and args.prediction_text and args.retrieval_trace:
        pred_text = Path(args.prediction_text).read_text(encoding="utf-8")
        trace = load_json(args.retrieval_trace)
        result["fact_consistency_llm"] = fact_consistency_llm(pred_text, trace.get("context", ""), args.bedrock_model_id, args.bedrock_region)

    result["expert_usability"] = expert_usability_rate(args.expert_csv)
    result["pass_fail"] = pass_fail(result)
    return result


def pass_fail(r: Dict[str, Any]) -> Dict[str, bool]:
    pico = r.get("pico", {})
    p_i_c_ok = (pico.get("P", 0) >= 0.90 and pico.get("I", 0) >= 0.90 and pico.get("C", 0) >= 0.90)
    o_ok = (pico.get("O", {}).get("recall", 0) >= 0.80)
    unsupported_rate = r.get("unsupported_claim_rate")
    fact_llm = r.get("fact_consistency_llm") or {}
    if unsupported_rate is None and "unsupported_rate" in fact_llm:
        unsupported_rate = fact_llm.get("unsupported_rate")
    expert = r.get("expert_usability") or {}
    return {
        "CQ抽出_100%": r.get("cq_match") == 1.0,
        "PICO_PIC_90%以上": p_i_c_ok,
        "PICO_O_80%以上": o_ok,
        "推奨方向_100%": r.get("recommendation_direction_match") == 1.0,
        "推奨の強さ_90%以上": r.get("recommendation_strength_match", 0) >= 0.90,
        "エビデンスの強さ_90%以上": r.get("evidence_certainty_match", 0) >= 0.90,
        "採用文献リスト_90%以上": r.get("references", {}).get("f1", 0) >= 0.90,
        "EtD主要項目_80%以上": (r.get("etd", {}).get("agreement") or 0) >= 0.80,
        "根拠なし記述_5%未満": (unsupported_rate is not None and unsupported_rate < 0.05),
        "専門家使用可能_80%以上": (expert.get("usable_rate") is not None and expert.get("usable_rate") >= 0.80),
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="Evaluate Minds RAG RC-1/RC-5 generation outputs.")
    parser.add_argument("--gold", required=True, help="Gold JSON")
    parser.add_argument("--pred", required=True, help="Prediction structured JSON")
    parser.add_argument("--output", default="evaluation_report.json")
    parser.add_argument("--semantic", action="store_true", help="Compute sentence-transformer semantic similarity")
    parser.add_argument("--embedding_model", default="intfloat/multilingual-e5-base")
    parser.add_argument("--fact_check", action="store_true", help="Use Bedrock LLM-as-judge for fact consistency")
    parser.add_argument("--prediction_text", default=None, help="Generated RC markdown text for fact checking")
    parser.add_argument("--retrieval_trace", default=None, help="Retrieval trace JSON containing context")
    parser.add_argument("--bedrock_model_id", default=DEFAULT_MODEL_ID)
    parser.add_argument("--bedrock_region", default=DEFAULT_REGION)
    parser.add_argument("--expert_csv", default=None, help="CSV with expert usability judgments; column usable or 使用可能")
    args = parser.parse_args()

    report = evaluate(load_json(args.gold), load_json(args.pred), args)
    Path(args.output).write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
