"""
sr_data_extraction.py — データ抽出（PICO + RoB 2）

スクリーニング済みCSVのInclude論文から、研究特性・アウトカム・バイアスリスクを抽出。

Usage:
    python sr_data_extraction.py \
        --input ./sr_output/screened.csv \
        --output ./sr_output/extracted.csv \
        --outcome "QOL, 疲労, 身体機能" \
        --model gemini
"""

import argparse
import asyncio
import json
import os

import pandas as pd
from dotenv import load_dotenv
from tqdm.asyncio import tqdm_asyncio

load_dotenv()

CONCURRENCY_LIMIT = 20

EXTRACTION_SCHEMA = {
    "population": "対象（疾患、ステージ、年齢、N数）",
    "intervention": "介入内容（種類、強度、頻度、期間）",
    "comparison": "対照群（通常ケア、別介入など）",
    "outcomes": "報告されたアウトカムと主な結果（数値あれば含める）",
    "follow_up": "追跡期間",
    "study_design": "研究デザイン（RCT/準RCT等）",
    "rob_randomization": "無作為化の適切さ [Low/Some concerns/High]",
    "rob_allocation": "割付け隠蔽 [Low/Some concerns/High]",
    "rob_blinding": "盲検化 [Low/Some concerns/High]",
    "rob_attrition": "不完全なアウトカムデータ [Low/Some concerns/High]",
    "rob_reporting": "選択的アウトカム報告 [Low/Some concerns/High]",
    "rob_overall": "バイアスリスク総合判定 [Low/Some concerns/High]",
    "notes": "特記事項",
}

SYSTEM_PROMPT_TEMPLATE = """あなたは臨床研究の専門的なデータ抽出者です。
論文のタイトルと抄録から、システマティックレビュー用のデータを抽出してください。

対象アウトカム: {outcome}

以下のJSONスキーマに従って抽出してください。情報が抄録から読み取れない場合は "不明" としてください:
{schema_json}

JSONのみを出力してください。"""


def build_prompt(row: dict) -> str:
    return f"Title: {row['Title']}\nAbstract: {row.get('Abstract', '')}"


# ---- Gemini ----

async def _gemini_extract(client, pmid: str, prompt: str, system_prompt: str, semaphore):
    from google.genai import types

    async with semaphore:
        try:
            response = await client.aio.models.generate_content(
                model="gemini-2.5-flash",
                contents=prompt,
                config=types.GenerateContentConfig(
                    system_instruction=system_prompt,
                    response_mime_type="application/json",
                    temperature=0.0,
                ),
            )
            return pmid, json.loads(response.text)
        except Exception as e:
            return pmid, {k: "Error" for k in EXTRACTION_SCHEMA} | {"notes": str(e)}


async def extract_with_gemini(df: pd.DataFrame, system_prompt: str) -> list[dict]:
    from google import genai

    client = genai.Client(api_key=os.environ["GEMINI_API_KEY"])
    semaphore = asyncio.Semaphore(CONCURRENCY_LIMIT)

    rows = df.to_dict("records")
    tasks = [
        _gemini_extract(client, str(r["PMID"]), build_prompt(r), system_prompt, semaphore)
        for r in rows
    ]
    print(f"[Gemini] {len(tasks)}件のデータ抽出を開始...")
    return await tqdm_asyncio.gather(*tasks)


# ---- Claude ----

async def _claude_extract(client, pmid: str, prompt: str, system_prompt: str, semaphore):
    async with semaphore:
        try:
            response = await asyncio.to_thread(
                client.messages.create,
                model="claude-haiku-4-5-20251001",
                max_tokens=1024,
                system=system_prompt,
                messages=[{"role": "user", "content": prompt}],
                temperature=0.0,
            )
            text = response.content[0].text.strip()
            if "```" in text:
                text = text.split("```")[1].strip()
                if text.startswith("json"):
                    text = text[4:].strip()
            return pmid, json.loads(text)
        except Exception as e:
            return pmid, {k: "Error" for k in EXTRACTION_SCHEMA} | {"notes": str(e)}


async def extract_with_claude(df: pd.DataFrame, system_prompt: str) -> list[dict]:
    import anthropic

    client = anthropic.Anthropic(api_key=os.environ["ANTHROPIC_API_KEY"])
    semaphore = asyncio.Semaphore(10)

    rows = df.to_dict("records")
    tasks = [
        _claude_extract(client, str(r["PMID"]), build_prompt(r), system_prompt, semaphore)
        for r in rows
    ]
    print(f"[Claude] {len(tasks)}件のデータ抽出を開始...")
    return await tqdm_asyncio.gather(*tasks)


# ---- メイン ----

async def run_extraction(input_csv: str, output_csv: str, outcome: str, model: str):
    df = pd.read_csv(input_csv).fillna("")
    include_df = df[df["decision"] == "Include"].reset_index(drop=True)
    print(f"[データ抽出] Include件数: {len(include_df)}件")

    if include_df.empty:
        print("Includeが0件のため終了。")
        return

    system_prompt = SYSTEM_PROMPT_TEMPLATE.format(
        outcome=outcome,
        schema_json=json.dumps(EXTRACTION_SCHEMA, ensure_ascii=False, indent=2),
    )

    if model == "gemini":
        results = await extract_with_gemini(include_df, system_prompt)
    elif model == "claude":
        results = await extract_with_claude(include_df, system_prompt)
    else:
        raise ValueError(f"未対応のモデル: {model}")

    extracted_rows = []
    for pmid, extracted in results:
        base = include_df[include_df["PMID"].astype(str) == pmid].to_dict("records")
        if base:
            merged = base[0] | extracted
            extracted_rows.append(merged)

    final_df = pd.DataFrame(extracted_rows)
    final_df.to_csv(output_csv, index=False, encoding="utf-8-sig")
    print(f"[完了] {len(final_df)}件 -> {output_csv}")


def main():
    parser = argparse.ArgumentParser(description="データ抽出（PICO + RoB 2）")
    parser.add_argument("--input", required=True)
    parser.add_argument("--output", required=True)
    parser.add_argument("--outcome", default="QOL, 疲労, 身体機能, 運動耐容能", help="対象アウトカム")
    parser.add_argument("--model", default="gemini", choices=["gemini", "claude"])
    args = parser.parse_args()

    asyncio.run(run_extraction(args.input, args.output, args.outcome, args.model))


if __name__ == "__main__":
    main()
