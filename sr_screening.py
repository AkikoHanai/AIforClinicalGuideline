"""
sr_screening.py — 一次スクリーニング（タイトル・抄録）

Usage:
    python sr_screening.py \
        --input ./sr_output/search_all.csv \
        --output ./sr_output/screened.csv \
        --inclusion "がんサバイバーを対象とした運動介入のRCT" \
        --exclusion "動物実験、プロトコル論文、運動介入なし"
"""

import argparse
import asyncio
import json
import os

import pandas as pd
from dotenv import load_dotenv
from tqdm.asyncio import tqdm_asyncio

load_dotenv()

CONCURRENCY_LIMIT = 50


def build_system_prompt(inclusion: str, exclusion: str) -> str:
    return f"""あなたはシステマティックレビューの一次スクリーニング担当者です。
論文のタイトルと抄録を読み、以下の基準に従って包含/除外を判定してください。

【包含基準】
{inclusion}

【除外基準】
{exclusion}

【出力形式】以下のJSONのみ出力してください（説明不要）:
{{"decision": "Include" | "Exclude" | "Unclear", "reason": "判定理由（日本語・2文以内）"}}

判断に迷う場合は Unclear を選択してください。"""


# ---- Claude ----

async def _claude_decision(client, pmid: str, prompt: str, system_prompt: str, semaphore):
    async with semaphore:
        try:
            response = await asyncio.to_thread(
                client.messages.create,
                model="claude-haiku-4-5-20251001",
                max_tokens=256,
                system=system_prompt,
                messages=[{"role": "user", "content": prompt}],
                temperature=0.0,
            )
            text = response.content[0].text.strip()
            # JSONブロック抽出
            if "```" in text:
                text = text.split("```")[1].strip()
                if text.startswith("json"):
                    text = text[4:].strip()
            return pmid, json.loads(text)
        except Exception as e:
            return pmid, {"decision": "Error", "reason": str(e)}


async def screen_with_claude(df: pd.DataFrame, system_prompt: str) -> dict:
    import anthropic

    client = anthropic.Anthropic(api_key=os.environ["ANTHROPIC_API_KEY"])
    semaphore = asyncio.Semaphore(20)  # Claude APIのレート制限を考慮
    records_dict = {str(r["PMID"]): r for r in df.to_dict("records")}
    tasks = []

    for _, row in df.iterrows():
        pmid = str(row["PMID"])
        abstract = str(row.get("Abstract", ""))
        if len(abstract) < 50:
            records_dict[pmid].update({"decision": "Unclear", "reason": "Abstract missing or too short"})
            continue
        prompt = f"Title: {row['Title']}\nAbstract: {abstract}"
        tasks.append(_claude_decision(client, pmid, prompt, system_prompt, semaphore))

    print(f"[Claude] {len(tasks)}件のスクリーニングを開始...")
    results = await tqdm_asyncio.gather(*tasks)
    for pmid, result in results:
        records_dict[pmid].update(result)
    return records_dict


# ---- メイン ----

async def run_screening(input_csv: str, output_csv: str, inclusion: str, exclusion: str):
    df = pd.read_csv(input_csv).fillna("")
    system_prompt = build_system_prompt(inclusion, exclusion)
    records_dict = await screen_with_claude(df, system_prompt)

    final_df = pd.DataFrame(list(records_dict.values()))
    final_df = final_df.sort_values(by="decision")
    final_df.to_csv(output_csv, index=False, encoding="utf-8-sig")

    counts = final_df["decision"].value_counts().to_dict()
    print(f"\n[スクリーニング完了]")
    for k, v in counts.items():
        print(f"  {k}: {v}件")
    print(f"  -> {output_csv}")


def main():
    parser = argparse.ArgumentParser(description="一次スクリーニング")
    parser.add_argument("--input", required=True)
    parser.add_argument("--output", required=True)
    parser.add_argument("--inclusion", required=True, help="包含基準")
    parser.add_argument("--exclusion", required=True, help="除外基準")
    args = parser.parse_args()

    asyncio.run(run_screening(args.input, args.output, args.inclusion, args.exclusion))


if __name__ == "__main__":
    main()
