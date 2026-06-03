FROM python:3.12-slim

WORKDIR /app

# 依存パッケージのインストール
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# アプリケーションコードのコピー
COPY sr_search.py \
     sr_screening.py \
     sr_data_extraction.py \
     sr_minds_formatter.py \
     sr_pipeline.py \
     task_runner.py \
     ./

ENTRYPOINT ["python", "task_runner.py"]
