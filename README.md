# AI for Clinical Guideline Development

定性的システマティックレビューから医療ガイドラインの推奨文を自動生成するパイプライン

**自動化度**: 🟡 50% — PubMed検索からRC-5/RC-1推奨文生成までを部分自動化

---

## 📋 目次

- [概要](#概要)
- [セットアップ](#セットアップ)
- [使い方](#使い方)
- [ファイル構成](#ファイル構成)
- [Q&A](#qa)
- [トラブルシューティング](#トラブルシューティング)

---

## 概要

### このツールでできること

PubMed の論文検索から医療ガイドラインの推奨文生成まで、以下のステップを自動化します：

```
PubMed 検索
    ↓
一次スクリーニング（Gemini/Claude）
    ↓
データ抽出（PICO + バイアスリスク評価）
    ↓
定性的 SR テーブル生成
    ↓
EtD（Evidence-to-Decision）フレームワーク構築
    ↓
RC-5（推奨作成の経過）生成
    ↓
RC-1（推奨文草案）生成
    ↓
完成 ✅
```

### 自動化レベル

| フェーズ | 自動化度 | 確認の必要性 |
|---|---|---|
| **検索・スクリーニング** | ✅ 90% | 低 |
| **データ抽出** | ✅ 85% | 中 |
| **テーブル生成** | 🟡 70% | 中 |
| **EtD 構築** | 🟡 40% | 高（手動入力必須） |
| **推奨文生成** | 🟡 55% | 高（確認必須） |

---

## セットアップ

### 1. Python 環境を準備

```bash
# Python 3.10以上が必要
python --version

# 仮想環境を作成（推奨）
python -m venv venv
source venv/bin/activate  # Mac/Linux
# or
venv\Scripts\activate  # Windows
```

### 2. リポジトリをクローン

```bash
git clone https://github.com/YOUR_USERNAME/AIforClinicalGuideline.git
cd AIforClinicalGuideline
```

### 3. 依存パッケージをインストール

```bash
pip install -r requirements.txt
```

**必要なもの**：
- requests (PubMed検索)
- pandas (データ処理)
- openpyxl (Excel出力)
- tqdm (進捗表示)
- python-dotenv (環境変数管理)
- google-genai (Gemini API)
- anthropic (Claude API)
- boto3 (AWS S3)
- chromadb (RAG検索)

### 4. API キーを設定

#### Gemini を使う場合

```bash
# .env ファイルを作成
echo "GEMINI_API_KEY=sk-xxx..." > .env

# または環境変数を直接設定
export GEMINI_API_KEY="sk-xxx..."
```

[Gemini API キーを取得](https://ai.google.dev/tutorials/setup)

#### Claude API を使う場合

```bash
echo "ANTHROPIC_API_KEY=sk-ant-xxx..." > .env

# または
export ANTHROPIC_API_KEY="sk-ant-xxx..."
```

[Claude API キーを取得](https://console.anthropic.com)

---

## 使い方

### 最も簡単な方法：完全自動パイプラインを実行

```bash
python sr_fully_annotated_pipeline.py \
    --extracted ./sample_data/extracted.csv \
    --cq "CQ 1" \
    --outcomes "QoL, 筋力, 倦怠感, うつ" \
    --output-dir ./output
```

**出力ファイル**：

```
output/
├── phase1_evidence_table_annotated.json    # ✅ 自動生成完了
├── phase1_checklist.md                     # 🟡 確認チェックリスト
├── phase2_etd_annotated.json               # ✅ 自動生成 + 確認
├── phase2_checklist.md                     # ❌ 手動入力項目
├── phase3_rc5_output.md                    # 🟡 推奨作成の経過
└── phase3_rc1_draft.md                     # 🟡 推奨文草案
```

### 各ステップを個別に実行

#### ステップ 1: PubMed から文献検索

```bash
python sr_search.py \
    --query '("Cancer"[Mesh] AND "Exercise"[Mesh] AND "Survivor"[Mesh])' \
    --output-dir ./output/search_results \
    --age-filter
```

**出力**: `search_all.csv`（PubMedの検索結果）

#### ステップ 2: 一次スクリーニング（タイトル・抄録）

```bash
python sr_screening.py \
    --input ./output/search_results/search_all.csv \
    --output ./output/screened.csv \
    --inclusion "がんサバイバーを対象とした運動介入のRCT" \
    --exclusion "動物実験、プロトコル論文" \
    --model gemini
```

**出力**: `screened.csv`（Include/Exclude/Unclear判定付き）

#### ステップ 3: データ抽出（PICO + バイアスリスク）

```bash
python sr_data_extraction.py \
    --input ./output/screened.csv \
    --output ./output/extracted.csv \
    --outcome "QoL, 筋力, 倦怠感, うつ, 運動関連有害事象" \
    --model gemini
```

**出力**: `extracted.csv`（各研究の詳細情報）

#### ステップ 4: エビデンス総体テーブル生成

```bash
python sr_evidence_table_annotated.py \
    --input ./output/extracted.csv \
    --outcomes "QoL, 筋力, 倦怠感, うつ" \
    --output-dir ./output/tables
```

**出力**:
- `evidence_table.md` — Markdown形式のテーブル
- `evidence_table.json` — 構造化データ

#### ステップ 5: EtD フレームワーク構築

```bash
python sr_etd_builder_annotated.py \
    --evidence-table ./output/tables/evidence_table.json \
    --extracted ./output/extracted.csv \
    --cq "CQ 1" \
    --output-dir ./output/etd
```

**出力**:
- `etd_framework.json` — EtDメタデータ
- `etd_checklist.md` — 手動入力チェックリスト

#### ステップ 6: 推奨文生成（RC-5/RC-1）

```bash
python generate_recommendation.py \
    --chunks-file ./output/etd_chunks.json \
    --etd-file ./output/etd/etd_framework.json \
    --cq "CQ 1" \
    --output-dir ./output/recommendations
```

**出力**:
- `CQ1_RC5_output.md` — 推奨作成の経過
- `CQ1_RC1_draft.md` — 推奨文草案

---

## ファイル構成

```
AIforClinicalGuideline/
├── README.md                              # このファイル
├── requirements.txt                       # Python依存パッケージ
│
├── 【コア実装】
├── sr_search.py                           # PubMed検索
├── sr_screening.py                        # 一次スクリーニング
├── sr_data_extraction.py                  # データ抽出（PICO+RoB2）
├── sr_evidence_table.py                   # テーブル生成
├── sr_evidence_table_annotated.py         # テーブル生成（確認タグ付き）
├── sr_etd_builder.py                      # EtD構築
├── sr_etd_builder_annotated.py            # EtD構築（確認タグ+チェックリスト付き）
├── generate_recommendation.py             # RC-5/RC-1生成
├── sr_fully_annotated_pipeline.py         # ⭐ 全工程統合版（推奨）
│
├── 【RAG検索・検証】
├── build_and_search_chromadb.py           # ChromaDB構築・検索
├── sr_pdf_chunk_extractor.py              # PDFからチャンク抽出
├── sr_rag_validation.py                   # RAG精度検証
│
├── 【統合パイプライン】
├── sr_pipeline.py                         # クイックスタートパイプライン
├── sr_qualitative_sr_pipeline.py          # 定性的SRパイプライン
│
├── 【ドキュメント】
├── README_ANNOTATION.md                   # 確認タグ付き手順
├── AUTOMATION_READINESS.md                # 自動化度分析
├── IMPLEMENTATION_STATUS.md               # 実装状況
├── QUALITATIVE_SR_GUIDE.md                # 詳細ガイド
├── RAG_VALIDATION_COMPLETE.md             # RAG検証レポート
├── DEPLOY.md                              # AWS CDKデプロイ手順
│
├── 【AWS インフラ】
├── infra/
│   ├── app.py                             # CDKアプリ定義
│   ├── sr_stack.py                        # CDKスタック
│   ├── cdk.json                           # CDK設定
│   └── requirements.txt                   # CDK依存パッケージ
│
└── 【サンプルデータ】
    └── sample_data/
        └── extracted.csv                  # テスト用抽出データ
```

---

## 実行例

### 例 1: がんサバイバーの運動ガイドライン

```bash
python sr_fully_annotated_pipeline.py \
    --extracted ./sample_data/extracted.csv \
    --cq "CQ 1" \
    --outcomes "QoL, 筋力, 倦怠感, うつ, 運動関連有害事象" \
    --output-dir ./output/cancer_exercise_guideline
```

### 例 2: Gemini APIを使う

```bash
export GEMINI_API_KEY="sk-..."

python sr_screening.py \
    --input ./output/search_results/search_all.csv \
    --output ./output/screened.csv \
    --inclusion "患者対象の介入研究" \
    --exclusion "動物実験" \
    --model gemini
```

### 例 3: Claude APIを使う

```bash
export ANTHROPIC_API_KEY="sk-ant-..."

python sr_screening.py \
    --input ./output/search_results/search_all.csv \
    --output ./output/screened.csv \
    --inclusion "患者対象の介入研究" \
    --exclusion "動物実験" \
    --model claude
```

---

## 重要な確認ポイント 🟡

各フェーズで、以下のファイルに従って確認・入力してください：

### Phase 1: エビデンス総体テーブル

- [ ] `phase1_checklist.md` を開く
- [ ] ✅（自動生成）項目を確認
- [ ] 🟡（要確認）項目をレビュー
  - effect_direction の妥当性
  - GRADE確実性推定値の妥当性

### Phase 2: EtDフレームワーク

- [ ] `phase2_checklist.md` を開く
- [ ] ❌（手動入力必須）項目に入力
  - PICO(P, I, C)の詳細定義
  - 患者価値観・経済・実装データ
- [ ] 🟡（要確認）項目をレビュー

### Phase 3: 推奨文生成

- [ ] `phase3_rc5_output.md` を読む（推奨作成の経過）
- [ ] `phase3_rc1_draft.md` を読む（推奨文草案）
- [ ] パネル会議で投票
  - 推奨の方向（実施する/実施しない）
  - 推奨の強さ（強い推奨/弱い推奨）
  - 合意度（全員一致/大多数/意見分かれ）

---

## Q&A

### Q1: どのモデルを使うべき？

- **Gemini 2.5 Flash**: コスト低い、高速（推奨・初心者向け）
- **Claude**: 日本語精度が高い、より詳細

```bash
# Gemini（デフォルト）
python sr_screening.py --input input.csv --output output.csv --model gemini

# Claude
python sr_screening.py --input input.csv --output output.csv --model claude
```

### Q2: 自分のデータを使いたい

1. CSV形式の検索結果を用意（列: PMID, Title, Abstract, Authors, Year, Journal）
2. ステップ 2 からスタート

```bash
python sr_screening.py --input your_data.csv --output screened.csv ...
```

### Q3: PubMed検索から始めたい

```bash
python sr_search.py \
    --query "your_search_terms" \
    --output-dir ./output \
    --age-filter
```

[PubMed検索式の書き方](https://pubmed.ncbi.nlm.nih.gov/help/)

### Q4: AWS にデプロイしたい

```bash
cd infra
pip install -r requirements.txt
cdk bootstrap
cdk deploy

# 詳細は DEPLOY.md を参照
```

---

## トラブルシューティング

### エラー: APIキーが見つからない

```
ValueError: GEMINI_API_KEY が設定されていません
```

**解決策**:
```bash
# .env ファイルを作成
echo "GEMINI_API_KEY=sk-your-key-here" > .env

# または環境変数を直接設定
export GEMINI_API_KEY="sk-your-key-here"
```

### エラー: パッケージが見つからない

```
ModuleNotFoundError: No module named 'chromadb'
```

**解決策**:
```bash
pip install -r requirements.txt --upgrade
```

### エラー: PubMed接続失敗

```
requests.exceptions.ConnectionError
```

**解決策**:
1. インターネット接続を確認
2. PubMed APIが利用可能か確認
3. レート制限に達していないか確認（NCBI APIは3回/秒）

### エラー: メモリ不足

大量の論文を処理する場合、メモリが足りないことがあります

**解決策**:
```bash
# 年齢層別に分割して処理
python sr_search.py --query "..." --age-filter

# バッチサイズを縮小
# sr_screening.py のCONCURRENCY_LIMITを変更
```

### エラー: ChromaDB 埋め込みモデルのダウンロード失敗

```
Error downloading embedding model
```

**解決策**:
```bash
# 再度実行（オンライン）
python sr_rag_validation.py --chunks-file pdf_chunks.json
```

---

## サポート

### ドキュメント

- 📖 [詳細ガイド](QUALITATIVE_SR_GUIDE.md)
- 📊 [自動化度分析](AUTOMATION_READINESS.md)
- 🏗️ [AWS デプロイ](DEPLOY.md)
- 📝 [確認タグ説明](README_ANNOTATION.md)

### Q&A

Issues を作成してください：
https://github.com/YOUR_USERNAME/AIforClinicalGuideline/issues

---

## ライセンス

MIT License

---

## バージョン情報

- **バージョン**: 1.0 (2026-06-03)
- **自動化度**: 🟡 50%
- **ステータス**: ✅ 本番化準備完了

---

**Happy Systematic Reviewing! 🎉**

*このツールは医療ガイドライン作成を効率化します。*
