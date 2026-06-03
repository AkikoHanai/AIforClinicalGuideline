"""
task_runner.py — ECS Fargate エントリポイント

環境変数でジョブパラメータを受け取り、パイプラインを実行して
結果をS3にアップロードする。

環境変数:
    SR_JOB_ID           ジョブID（S3パスのプレフィックスに使用）
    SR_S3_BUCKET        出力先S3バケット名
    SR_QUERY            PubMed検索式
    SR_INCLUSION        包含基準
    SR_EXCLUSION        除外基準
    SR_PICO_Q           レビューの問い
    SR_OUTCOMES         アウトカム（カンマ区切り）
    SR_MODEL            使用LLM（gemini / claude）
    SR_AGE_FILTER       年齢層別フィルタ（1 / 0）
    GEMINI_API_KEY      Gemini APIキー（Secrets Managerから注入）
    ANTHROPIC_API_KEY   Claude APIキー（Secrets Managerから注入）
"""

import asyncio
import json
import os
import sys
import tempfile
import traceback
from datetime import datetime, timezone
from pathlib import Path

import boto3

# ---- ローカルモジュール ----
sys.path.insert(0, os.path.dirname(__file__))
from sr_search import run_search
from sr_screening import run_screening
from sr_data_extraction import run_extraction
from sr_minds_formatter import generate_minds_table


def get_env(key: str, default: str = "") -> str:
    return os.environ.get(key, default)


def s3_upload(s3_client, local_path: str, bucket: str, s3_key: str):
    s3_client.upload_file(local_path, bucket, s3_key)
    print(f"[S3] アップロード完了: s3://{bucket}/{s3_key}")


def write_status(s3_client, bucket: str, job_id: str, status: dict):
    body = json.dumps(status, ensure_ascii=False, indent=2)
    s3_client.put_object(
        Bucket=bucket,
        Key=f"jobs/{job_id}/status.json",
        Body=body.encode("utf-8"),
        ContentType="application/json",
    )


def print_step(n: int, title: str):
    print(f"\n{'='*60}")
    print(f"  Step {n}: {title}")
    print(f"{'='*60}")


async def main():
    job_id = get_env("SR_JOB_ID", f"job-{datetime.now(timezone.utc).strftime('%Y%m%d%H%M%S')}")
    bucket = get_env("SR_S3_BUCKET")
    query = get_env("SR_QUERY")
    inclusion = get_env("SR_INCLUSION")
    exclusion = get_env("SR_EXCLUSION")
    pico_q = get_env("SR_PICO_Q", "介入はアウトカムを改善するか？")
    outcomes = get_env("SR_OUTCOMES", "QOL, 疲労, 身体機能")
    model = get_env("SR_MODEL", "gemini")
    age_filter = get_env("SR_AGE_FILTER", "0") == "1"

    if not bucket or not query:
        print("[エラー] SR_S3_BUCKET と SR_QUERY は必須です。")
        sys.exit(1)

    s3 = boto3.client("s3")
    started_at = datetime.now(timezone.utc).isoformat()

    write_status(s3, bucket, job_id, {
        "job_id": job_id,
        "status": "running",
        "started_at": started_at,
        "query": query,
        "model": model,
    })

    with tempfile.TemporaryDirectory() as tmpdir:
        search_csv = f"{tmpdir}/search_all.csv"
        screened_csv = f"{tmpdir}/screened.csv"
        extracted_csv = f"{tmpdir}/extracted.csv"
        today = datetime.now(timezone.utc).strftime("%Y%m%d")
        minds_xlsx = f"{tmpdir}/minds_evidence_table_{today}.xlsx"

        try:
            # ---- Step 1: 検索 ----
            print_step(1, "PubMed検索")
            result = run_search(query, tmpdir, age_filter=age_filter)
            if not result:
                raise RuntimeError("検索結果が0件でした。")
            s3_upload(s3, search_csv, bucket, f"jobs/{job_id}/search_all.csv")

            # ---- Step 2: スクリーニング ----
            print_step(2, "一次スクリーニング")
            await run_screening(search_csv, screened_csv, inclusion, exclusion, model)
            s3_upload(s3, screened_csv, bucket, f"jobs/{job_id}/screened.csv")

            # ---- Step 3: データ抽出 ----
            print_step(3, "データ抽出（PICO + RoB 2）")
            await run_extraction(screened_csv, extracted_csv, outcomes, model)
            s3_upload(s3, extracted_csv, bucket, f"jobs/{job_id}/extracted.csv")

            # ---- Step 4: Mindsテーブル生成 ----
            print_step(4, "Mindsエビデンステーブル生成")
            generate_minds_table(extracted_csv, minds_xlsx, pico_q, outcomes)
            s3_upload(s3, minds_xlsx, bucket, f"jobs/{job_id}/minds_evidence_table_{today}.xlsx")

            # 完了ステータス書き込み
            finished_at = datetime.now(timezone.utc).isoformat()
            write_status(s3, bucket, job_id, {
                "job_id": job_id,
                "status": "succeeded",
                "started_at": started_at,
                "finished_at": finished_at,
                "outputs": {
                    "search": f"s3://{bucket}/jobs/{job_id}/search_all.csv",
                    "screened": f"s3://{bucket}/jobs/{job_id}/screened.csv",
                    "extracted": f"s3://{bucket}/jobs/{job_id}/extracted.csv",
                    "minds_table": f"s3://{bucket}/jobs/{job_id}/minds_evidence_table_{today}.xlsx",
                },
            })
            print(f"\n[完了] job_id: {job_id}")

        except Exception as e:
            tb = traceback.format_exc()
            print(f"[エラー]\n{tb}")
            write_status(s3, bucket, job_id, {
                "job_id": job_id,
                "status": "failed",
                "started_at": started_at,
                "finished_at": datetime.now(timezone.utc).isoformat(),
                "error": str(e),
                "traceback": tb,
            })
            sys.exit(1)


if __name__ == "__main__":
    asyncio.run(main())
