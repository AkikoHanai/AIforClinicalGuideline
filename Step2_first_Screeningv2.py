import pandas as pd
import json
import os
import asyncio
from dotenv import load_dotenv
from google import genai
from google.genai import types
from tqdm.asyncio import tqdm_asyncio

load_dotenv()

# 並列リクエスト数の上限（課金枠の制限に合わせて調整。ここでは50並列）
CONCURRENCY_LIMIT = 50 

async def fetch_llm_decision(client, pmid, prompt, base_prompt, semaphore):
    async with semaphore:
        try:
            # 新SDKの非同期クライアント (client.aio) を使用
            response = await client.aio.models.generate_content(
                model='gemini-2.5-flash',
                contents=prompt,
                config=types.GenerateContentConfig(
                    system_instruction=base_prompt,
                    response_mime_type="application/json",
                    temperature=0.0
                )
            )
            return pmid, json.loads(response.text)
        except Exception as e:
            return pmid, {"decision": "Error", "reason": str(e)}

async def execute_async_screening(input_csv, output_csv):
    api_key = os.environ.get("GEMINI_API_KEY")
    if not api_key:
        raise ValueError("APIキー未設定。")
        
    client = genai.Client(api_key=api_key)
    df = pd.read_csv(input_csv).fillna("")
    
    base_prompt = """
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
        task = fetch_llm_decision(client, pmid, prompt, base_prompt, semaphore)
        tasks.append(task)

    # 非同期タスクの一斉実行とプログレスバー表示
    print(f"[{len(tasks)}件の非同期スクリーニングを開始...]")
    results = await tqdm_asyncio.gather(*tasks)

    # 結果のマージ
    for pmid, llm_result in results:
        records_dict[pmid].update(llm_result)

    final_df = pd.DataFrame(list(records_dict.values()))
    final_df = final_df.sort_values(by='decision', ascending=False)
    final_df.to_csv(output_csv, index=False, encoding="utf-8-sig")
    print(f"[完了] {output_csv} を出力しました。")

if __name__ == "__main__":
    # Jupyter等で実行している場合は await execute_async_screening(...) を使用
    asyncio.run(execute_async_screening("screening_all_ages_with_classificationv2.csv", "screening_all_ages_async_v3.csv"))