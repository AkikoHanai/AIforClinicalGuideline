"""
Bedrock-based screening for SR Pipeline
Converts Antigravity scripts to use AWS Bedrock/Claude instead of Gemini
"""

import pandas as pd
import json
import os
import asyncio
import boto3
from dotenv import load_dotenv
from tqdm.asyncio import tqdm_asyncio

load_dotenv()

CONCURRENCY_LIMIT = 20

async def fetch_bedrock_decision(client, pmid, prompt, system_prompt, semaphore):
    """Call Bedrock Claude API for screening decision"""
    async with semaphore:
        try:
            response = await asyncio.to_thread(
                client.converse,
                modelId="anthropic.claude-3-sonnet-20240229-v1:0",
                messages=[{"role": "user", "content": [{"text": prompt}]}],
                system=[{"text": system_prompt}],
                inferenceConfig={"maxTokens": 256, "temperature": 0.0},
            )

            text = response["output"]["message"]["content"][0]["text"].strip()

            # Handle markdown code blocks
            if "```" in text:
                text = text.split("```")[1].strip()
                if text.startswith("json"):
                    text = text[4:].strip()

            return pmid, json.loads(text)
        except Exception as e:
            print(f"[ERROR PMID {pmid}] {type(e).__name__}: {str(e)}")
            return pmid, {"decision": "Error", "reason": str(e)}


async def execute_bedrock_screening(input_csv, output_csv):
    """Screen papers using AWS Bedrock"""

    client = boto3.client("bedrock-runtime", region_name="ap-northeast-1")
    df = pd.read_csv(input_csv).fillna("")

    system_prompt = """
    以下の論文抄録を評価し、システマティックレビューの一次スクリーニング判定をJSON形式で出力せよ。
    【包含基準(Include)】がんサバイバーを対象とした運動介入（HIIT等）のRCTであること。
    【除外基準(Exclude)】動物実験、プロトコル論文のみ、運動介入なし、がん患者以外。
    【出力スキーマ】 {"decision": "Include" | "Exclude" | "Unclear", "reason": "簡潔な判定理由(日本語)"}
    """

    tasks = []
    semaphore = asyncio.Semaphore(CONCURRENCY_LIMIT)
    records_dict = {}

    for index, row in df.iterrows():
        pmid = str(row['PMID'])
        records_dict[pmid] = row.to_dict()

        if not row['Abstract'] or len(str(row['Abstract'])) < 50:
            records_dict[pmid].update({"decision": "Unclear", "reason": "Abstract missing or too short"})
            continue

        prompt = f"Title: {row['Title']}\nAbstract: {row['Abstract']}"
        task = fetch_bedrock_decision(client, pmid, prompt, system_prompt, semaphore)
        tasks.append(task)

    print(f"[Bedrock/Claude] {len(tasks)}件のスクリーニングを開始...")
    results = await tqdm_asyncio.gather(*tasks)

    for pmid, llm_result in results:
        records_dict[pmid].update(llm_result)

    final_df = pd.DataFrame(list(records_dict.values()))
    final_df = final_df.sort_values(by='decision', ascending=False)
    final_df.to_csv(output_csv, index=False, encoding="utf-8-sig")

    # Print summary
    counts = final_df['decision'].value_counts().to_dict()
    print(f"\n[スクリーニング完了]")
    for k, v in counts.items():
        print(f"  {k}: {v}件")
    print(f"  -> {output_csv}")


if __name__ == "__main__":
    asyncio.run(execute_bedrock_screening(
        "screening_all_ages_with_classificationv2.csv",
        "screening_bedrock_result.csv"
    ))
