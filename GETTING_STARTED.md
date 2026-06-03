# 🚀 クイックスタート（学生向け）

最も簡単な方法で今すぐ試す！

> **🪟 Windows ユーザーですか？** → [WINDOWS_SETUP.md](WINDOWS_SETUP.md) を参照（詳細な Windows 専用ガイド）

---

## 📦 Step 1: セットアップ（5分）

### Mac/Linux

```bash
# リポジトリをクローン
git clone https://github.com/AkikoHanai/AIforClinicalGuideline.git
cd AIforClinicalGuideline

# Python 環境構築
python -m venv venv
source venv/bin/activate

# パッケージをインストール
pip install -r requirements.txt
```

### Windows（PowerShell 推奨）

```powershell
# リポジトリをクローン
git clone https://github.com/AkikoHanai/AIforClinicalGuideline.git
cd AIforClinicalGuideline

# Python 環境構築
python -m venv venv
.\venv\Scripts\Activate.ps1

# パッケージをインストール
pip install -r requirements.txt
```

> 詳しい Windows セットアップは [WINDOWS_SETUP.md](WINDOWS_SETUP.md) を参照

---

## 🔑 Step 2: API キー設定（1分）

### 方法 A: .env ファイル（推奨）

```bash
cat > .env << 'EOF_KEY'
GEMINI_API_KEY=sk-your-api-key-here
ANTHROPIC_API_KEY=sk-ant-your-api-key-here
EOF_KEY
```

### 方法 B: 環境変数

```bash
export GEMINI_API_KEY="sk-..."
export ANTHROPIC_API_KEY="sk-ant-..."
```

**API キーはどこから？**
- Gemini: https://ai.google.dev/tutorials/setup
- Claude: https://console.anthropic.com

---

## ✨ Step 3: パイプラインを実行（10分）

### 最も簡単な方法：サンプルデータで試す

```bash
python sr_fully_annotated_pipeline.py \
    --extracted ./sample_data/extracted.csv \
    --cq "CQ 1" \
    --outcomes "QoL, 筋力, 倦怠感, うつ" \
    --output-dir ./output/demo
```

### 結果を確認

```bash
# 出力ファイルを見る
ls -lh output/demo/

# テーブルを確認
cat output/demo/phase1_evidence_table_annotated.json

# チェックリストを確認
cat output/demo/phase1_checklist.md
```

---

## 📋 出力ファイルの意味

| ファイル | 何が入っているか |
|---|---|
| `phase1_checklist.md` | ✅ や 🟡 のタグ付きで確認項目を表示 |
| `phase2_checklist.md` | ❌ 手動入力が必須な項目を表示 |
| `phase3_rc5_output.md` | 🟡 推奨作成の経過（LLM生成） |
| `phase3_rc1_draft.md` | 🟡 推奨文草案（LLM生成） |

---

## 🎯 やってみたいこと別ガイド

### Q: 自分の検索結果から始めたい

```bash
# ステップ 1: PubMed から検索
python sr_search.py \
    --query '("Cancer"[Mesh] AND "Exercise"[Mesh])' \
    --output-dir ./output

# ステップ 2: スクリーニング
python sr_screening.py \
    --input ./output/search_results/search_all.csv \
    --output ./output/screened.csv \
    --inclusion "RCT形式の患者対象研究" \
    --exclusion "動物実験、プロトコル論文" \
    --model gemini
```

### Q: 元々あるデータを処理したい

1. CSV ファイルを用意（列: PMID, Title, Abstract, Authors, Year, Journal）
2. ステップ 2 からスタート

```bash
python sr_screening.py \
    --input your_data.csv \
    --output screened.csv \
    --inclusion "患者対象の介入研究" \
    --exclusion "動物実験" \
    --model gemini
```

### Q: Claude を使いたい

```bash
export ANTHROPIC_API_KEY="sk-ant-..."

python sr_screening.py \
    --input input.csv \
    --output output.csv \
    --model claude  # ← これを追加
```

---

## 🐛 エラーが出たときは？

### エラー: `GEMINI_API_KEY が見つかりません`

```bash
# .env ファイルができているか確認
cat .env

# なければ作成
echo "GEMINI_API_KEY=sk-..." > .env
```

### エラー: `ModuleNotFoundError: No module named 'chromadb'`

```bash
# パッケージを再インストール
pip install -r requirements.txt --upgrade
```

### エラー: `requests.exceptions.ConnectionError`

PubMed に接続できていません。以下を確認：

```bash
# インターネット接続確認
ping pubmed.ncbi.nlm.nih.gov

# レート制限に達していないか（3回/秒まで）
# 一度待ってから再実行
```

---

## 📚 次のステップ

1. **詳細なドキュメントを読む**
   ```bash
   cat README.md         # メインの説明書
   cat README_ANNOTATION.md  # 確認タグの説明
   cat AUTOMATION_READINESS.md  # 自動化度の詳細
   ```

2. **自分の研究テーマで試す**
   - PubMed 検索式を作成
   - 組み入れ・除外基準を定義
   - パイプラインを実行

3. **結果を解釈する**
   - Phase 1: テーブルの 🟡（要確認）を確認
   - Phase 2: チェックリストの ❌（手動入力必須）に入力
   - Phase 3: 推奨文を読んで確認

---

## 💡 Tips

### 小さく始める
```bash
# サンプルデータで動作確認してから
python sr_fully_annotated_pipeline.py \
    --extracted ./sample_data/extracted.csv \
    --cq "CQ 1" \
    --outcomes "QoL" \
    --output-dir ./output/test
```

### 詳しくログを見る
```bash
# Python スクリプトを直接実行して、詳細ログを確認
python -u sr_screening.py \
    --input input.csv \
    --output output.csv \
    --inclusion "..." \
    --exclusion "..." \
    --model gemini
```

### 複数の CQ を処理
```bash
# CQ1
python sr_fully_annotated_pipeline.py \
    --extracted extracted_cq1.csv \
    --cq "CQ 1" \
    --outcomes "QoL, 筋力" \
    --output-dir ./output/cq1

# CQ2
python sr_fully_annotated_pipeline.py \
    --extracted extracted_cq2.csv \
    --cq "CQ 2" \
    --outcomes "安全性" \
    --output-dir ./output/cq2
```

---

## 📞 わからないことがあったら

1. **README.md** の Q&A を見る
2. **QUALITATIVE_SR_GUIDE.md** で詳細を確認
3. Issues を作成して質問
   https://github.com/YOUR_USERNAME/AIforClinicalGuideline/issues

---

## 🎉 成功したら？

出力ファイルが `output/` にできた！

- `phase1_checklist.md` — 確認チェックリスト
- `phase2_checklist.md` — 手動入力ガイド
- `phase3_rc5_output.md` — 推奨作成の経過
- `phase3_rc1_draft.md` — 推奨文草案

これらは医療ガイドラインの作成に使えます 🏥

---

**Happy Research! 🔬✨**
