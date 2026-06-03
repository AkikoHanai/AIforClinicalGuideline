"""
generate_recommendation.py — RC-5生成 + RC-1草案生成

改修: Bedrock → Direct Claude API
入力: etd_chunks.json + etd_framework.json
出力: RC-5推奨作成の経過 + RC-1推奨文草案
"""

import argparse
import asyncio
import json
import os
import re
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional

import chromadb
from chromadb.utils import embedding_functions

sys.path.insert(0, str(Path(__file__).parent))
from build_and_search_chromadb import parse_chunks_file, build_chromadb, search_chromadb


async def generate_with_claude(
    etd_metadata: Dict[str, Any],
    rag_context: str,
    output_type: str = "RC-5"
) -> str:
    """
    Direct Claude API で生成
    output_type: "RC-5" or "RC-1"
    """
    import anthropic

    client = anthropic.Anthropic(api_key=os.environ.get("ANTHROPIC_API_KEY"))

    if output_type == "RC-5":
        system_prompt = """あなたは医療ガイドラインの推奨作成を支援する専門AIです。
提示された「EtDメタデータ」と「RAG検索コンテキスト」を用いて、
CQに対する推奨決定の解説（RC-5）を執筆してください。

【出力形式】Mindsに準拠した4つの見出しで構成：
## 1. 臨床疑問の定式化（PICO）とアウトカムの選定
## 2. エビデンスの確実性と益害バランスの評価
## 3. 価値観、嗜好性、および医療経済・実装に関する検討
## 4. 推奨の強さと方向性の決定（合意形成プロセス）
"""
        user_message = f"""以下のデータに基づいて、RC-5（推奨作成の経過）を作成してください。

【EtDメタデータ】
{json.dumps(etd_metadata, ensure_ascii=False, indent=2)}

【RAGコンテキスト】
{rag_context}

各見出し下で、メタデータの情報と生テキストの根拠を組み合わせて、
論理的に推奨決定に至った過程を説明してください。"""

    elif output_type == "RC-1":
        system_prompt = """あなたは医療ガイドラインの推奨文作成を支援するAIです。
EtDメタデータを基に、患者個別視点（Individual Perspective）での
推奨文草案（RC-1）を簡潔に生成してください。

【推奨文の形式】
「[介入名]を[対象]に[実施/実施しない]ことを[強く推奨する/提案する]。」

【出力】推奨文1-2文で構成してください。"""

        user_message = f"""以下のEtDメタデータから、RC-1推奨文草案（Individual Perspective）を生成してください。

【EtDメタデータ】
{json.dumps(etd_metadata, ensure_ascii=False, indent=2)}

【補足情報】
{rag_context[:500]}
"""

    message = await asyncio.to_thread(
        client.messages.create,
        model="claude-opus-4-8",
        max_tokens=2048 if output_type == "RC-5" else 256,
        system=system_prompt,
        messages=[{"role": "user", "content": user_message}],
        temperature=0.0,
    )

    return message.content[0].text


async def retrieve_context(
    chunks_file: str,
    etd_file: str,
    cq_name: str,
    top_k: int = 10
) -> tuple[Dict[str, Any], str, str]:
    """
    ChromaDB から RAG コンテキストを取得
    """
    print(f"[RAG] ChromaDB構築中...")
    chunks = parse_chunks_file(chunks_file)
    client, collection = build_chromadb(chunks)

    # EtDメタデータを読み込み
    with open(etd_file, "r", encoding="utf-8") as f:
        etd_metadata = json.load(f)

    # ハイブリッド検索
    pico = etd_metadata.get("pico", {})
    search_query = f"{cq_name} {pico.get('P', '')} {pico.get('I', '')} {pico.get('O', '')}"

    print(f"[検索] クエリ: {search_query[:100]}...")
    results = search_chromadb(collection, search_query, cq_filter=cq_name, top_k=top_k)

    # 検索結果をテキストに変換
    rag_context_parts = []
    debug_info = []

    for i, result in enumerate(results, 1):
        rag_context_parts.append(result["content"])
        debug_info.append(
            f"[{i}] {result['metadata'].get('Section', 'unknown')}\n"
            f"    {result['content'][:100]}..."
        )

    rag_context = "\n\n".join(rag_context_parts)
    debug_output = "\n".join(debug_info)

    print(f"[完了] {len(results)}件のコンテキストを取得")
    return etd_metadata, rag_context, debug_output


async def generate_recommendations(
    chunks_file: str,
    etd_file: str,
    cq_name: str,
    output_dir: str = "./sr_output"
) -> None:
    """
    RC-5 + RC-1 を生成
    """
    output_path = Path(output_dir)
    output_path.mkdir(parents=True, exist_ok=True)

    print(f"[生成開始] CQ: {cq_name}")

    # RAG コンテキスト取得
    etd_metadata, rag_context, debug_info = await retrieve_context(
        chunks_file, etd_file, cq_name
    )

    # RC-5生成
    print("\n[RC-5] 推奨作成の経過を生成中...")
    rc5_text = await generate_with_claude(etd_metadata, rag_context, output_type="RC-5")

    rc5_path = output_path / f"{cq_name.replace(' ', '')}_RC5_output.md"
    with open(rc5_path, "w", encoding="utf-8") as f:
        f.write(rc5_text)
    print(f"✅ {rc5_path}")

    # RC-1生成
    print("\n[RC-1] 推奨文草案を生成中...")
    rc1_text = await generate_with_claude(etd_metadata, rag_context, output_type="RC-1")

    rc1_path = output_path / f"{cq_name.replace(' ', '')}_RC1_draft.md"
    with open(rc1_path, "w", encoding="utf-8") as f:
        f.write("# 推奨文草案（RC-1: Individual Perspective）\n\n")
        f.write(rc1_text)
    print(f"✅ {rc1_path}")

    # デバッグ情報を保存
    debug_path = output_path / f"{cq_name.replace(' ', '')}_retrieval_debug.txt"
    with open(debug_path, "w", encoding="utf-8") as f:
        f.write(f"=== CQ: {cq_name} ===\n\n")
        f.write("【EtDメタデータ】\n")
        f.write(json.dumps(etd_metadata, ensure_ascii=False, indent=2))
        f.write("\n\n【RAG検索結果】\n")
        f.write(debug_info)
    print(f"✅ {debug_path}")


async def main():
    parser = argparse.ArgumentParser(description="RC-5/RC-1推奨文生成（Direct Claude API）")
    parser.add_argument("--chunks-file", required=True, help="etd_chunks.json")
    parser.add_argument("--etd-file", required=True, help="etd_framework.json")
    parser.add_argument("--cq", default="CQ 1", help="CQ名")
    parser.add_argument("--output-dir", default="./sr_output")
    args = parser.parse_args()

    await generate_recommendations(
        args.chunks_file,
        args.etd_file,
        args.cq,
        args.output_dir
    )

    print("\n[完了] RC-5 / RC-1 を生成しました")


if __name__ == "__main__":
    if not os.environ.get("ANTHROPIC_API_KEY"):
        print("[エラー] ANTHROPIC_API_KEY が設定されていません")
        sys.exit(1)
    asyncio.run(main())
