# 🪟 Windows ユーザー向けセットアップガイド

Windows で AIforClinicalGuideline を使うための完全ガイド

---

## 📋 前提条件

- **Windows 10/11**
- **Python 3.10以上** がインストール済み
  - [python.org から最新版をダウンロード](https://www.python.org/downloads/)
  - インストール時に **「Add Python to PATH」にチェック** ✓

---

## 🚀 Step 1: リポジトリをクローン（5分）

### 方法 A: コマンドプロンプト（推奨）

```bash
cd C:\Users\あなたのユーザー名\Documents

git clone https://github.com/AkikoHanai/AIforClinicalGuideline.git

cd AIforClinicalGuideline
```

### 方法 B: GitHub Desktop

1. [GitHub Desktop をダウンロード](https://desktop.github.com/)
2. 「Clone Repository」を選択
3. URL: `https://github.com/AkikoHanai/AIforClinicalGuideline.git`
4. 保存先: `C:\Users\あなたのユーザー名\Documents\`

---

## 🔧 Step 2: Python 仮想環境をセットアップ

### PowerShell（Windows 11推奨）

```powershell
# 仮想環境を作成
python -m venv venv

# 仮想環境を有効化
.\venv\Scripts\Activate.ps1

# パッケージをインストール
pip install -r requirements.txt
```

### コマンドプロンプト（Windows 10）

```cmd
# 仮想環境を作成
python -m venv venv

# 仮想環境を有効化
venv\Scripts\activate.bat

# パッケージをインストール
pip install -r requirements.txt
```

**成功した場合：**
```
(venv) C:\Users\...\AIforClinicalGuideline>
```

左側に `(venv)` が表示されれば OK ✅

---

## 🔑 Step 3: API キーを設定

### 方法 A: .env ファイル（推奨）

1. **メモ帳** を開く
2. 以下をコピペ：

```
GEMINI_API_KEY=sk-your-api-key-here
ANTHROPIC_API_KEY=sk-ant-your-api-key-here
```

3. **ファイル → 名前を付けて保存**
4. ファイル名: `.env`（先頭に `.` をつける）
5. ファイルの種類: **すべてのファイル（\*.\*）**
6. 保存先: `AIforClinicalGuideline` フォルダ直下
7. **実際の API キーに置き換える**

### 方法 B: 環境変数（直接設定）

**コントロール パネル → システムとセキュリティ → システム → 環境変数**

新規環境変数を追加：

| 変数名 | 値 |
|---|---|
| `GEMINI_API_KEY` | `sk-xxx...` |
| `ANTHROPIC_API_KEY` | `sk-ant-xxx...` |

---

## ✨ Step 4: パイプラインを実行

### コマンドプロンプト / PowerShell

```bash
# 仮想環境が有効化されていることを確認
# (venv) が左側に表示されている

python sr_fully_annotated_pipeline.py `
    --extracted ./sample_data/extracted.csv `
    --cq "CQ 1" `
    --outcomes "QoL, 筋力, 倦怠感, うつ" `
    --output-dir ./output/demo
```

**PowerShell での行継続：** バッククォート `` ` `` を使う

**コマンドプロンプト での行継続：** キャレット `^` を使う

```cmd
python sr_fully_annotated_pipeline.py ^
    --extracted ./sample_data/extracted.csv ^
    --cq "CQ 1" ^
    --outcomes "QoL, 筋力, 倦怠感, うつ" ^
    --output-dir ./output/demo
```

---

## 📊 結果を確認

実行が完了したら、`output/demo/` フォルダが作成されます：

```
output/demo/
├── phase1_evidence_table_annotated.json
├── phase1_checklist.md
├── phase2_etd_annotated.json
├── phase2_checklist.md
├── phase3_rc5_output.md
└── phase3_rc1_draft.md
```

**ファイルを開く：**
- `.json`: テキストエディタで開く
- `.md`: ブラウザ で開くか、テキストエディタで確認

---

## 🐛 よくあるエラーと対処法

### エラー 1: `python: command not found`

**原因**: Python がパスに登録されていない

**対処**:
1. Python を再インストール
2. インストール時に **「Add Python to PATH」にチェック** ✓
3. 再度ターミナルを開く

### エラー 2: `ModuleNotFoundError: No module named 'chromadb'`

**原因**: 仮想環境が有効化されていない

**対処**:
```powershell
# PowerShell
.\venv\Scripts\Activate.ps1

# コマンドプロンプト
venv\Scripts\activate.bat

# 再度インストール
pip install -r requirements.txt
```

### エラー 3: `GEMINI_API_KEY が見つかりません`

**原因**: API キーが設定されていない

**対処**:
```powershell
# .env ファイルの確認
type .env

# または環境変数を確認
$env:GEMINI_API_KEY
```

### エラー 4: `.env ファイルが作成できない`

**原因**: Windows が `.env` ファイルの作成を許可していない

**対処**:
1. PowerShell で作成：
```powershell
@"
GEMINI_API_KEY=sk-xxx...
ANTHROPIC_API_KEY=sk-ant-xxx...
"@ | Out-File -Encoding utf8 .env
```

2. または Visual Studio Code で作成
   - `Ctrl+Shift+P` → `Files: New File`
   - ファイル名: `.env`

### エラー 5: `デバイスが見つかりません` (パス関連)

**原因**: パス区切り文字が間違っている

**対処**: 常にスラッシュ `/` または バックスラッシュ `\\` を使用

```bash
# ✅ 正しい
--output-dir ./output/demo
--output-dir .\output\demo
--output-dir C:\Users\...\output\demo

# ❌ 間違い（混在）
--output-dir ./output\demo
```

---

## 💡 便利な Tips

### IDE を使う（推奨）

#### Visual Studio Code（無料）

1. [VS Code をダウンロード](https://code.visualstudio.com/)
2. Python 拡張をインストール
3. フォルダを開く: `File → Open Folder → AIforClinicalGuideline`
4. ターミナルから実行

```bash
# VS Code ターミナルで自動的に venv が有効化される
python sr_fully_annotated_pipeline.py --extracted ...
```

#### PyCharm Community Edition（無料）

1. [PyCharm をダウンロード](https://www.jetbrains.com/pycharm/download/)
2. プロジェクトを開く
3. Interpreter を `venv` に設定
4. 右クリック → `Run` で実行

### ファイル管理

**Windows Explorer で確認：**

```
C:\Users\あなたのユーザー名\Documents\AIforClinicalGuideline\
├── output/
│   └── demo/
│       ├── phase1_checklist.md
│       ├── phase2_checklist.md
│       └── ...
├── sample_data/
├── venv/
└── sr_*.py
```

### 複数の PubMed 検索を実行

```bash
# CQ1 用の検索
python sr_search.py `
    --query '("Cancer"[Mesh] AND "Exercise"[Mesh])' `
    --output-dir ./output/cq1

# CQ2 用の検索
python sr_search.py `
    --query '("Cancer"[Mesh] AND "Rehabilitation"[Mesh])' `
    --output-dir ./output/cq2
```

---

## 🆘 さらにサポートが必要な場合

### ドキュメントを確認

- [README.md](README.md) — メイン説明書
- [GETTING_STARTED.md](GETTING_STARTED.md) — クイックスタート
- [README_ANNOTATION.md](README_ANNOTATION.md) — 確認タグ説明

### Issues を作成

GitHub Issues で質問：
https://github.com/AkikoHanai/AIforClinicalGuideline/issues

**質問テンプレート:**
```
## 環境
- OS: Windows 10/11
- Python version: 3.x.x
- エラーメッセージ: [ここにコピペ]

## 実行したコマンド
```bash
[ここにコマンドをコピペ]
```

## エラーの詳細
[ここに全エラー出力をコピペ]
```

---

## ✅ チェックリスト

Windows セットアップが完了したか確認：

- [ ] Python 3.10以上をインストール（`python --version`で確認）
- [ ] リポジトリをクローン
- [ ] 仮想環境を作成・有効化（`(venv)` が表示される）
- [ ] パッケージをインストール（`pip install -r requirements.txt`）
- [ ] API キーを .env に設定
- [ ] サンプルコマンドを実行
- [ ] `output/demo/` に結果が出力される

すべてチェックできたら **✅ 準備完了！**

---

## 🎉 成功したら

出力ファイルを確認：

```
output/demo/
├── phase1_checklist.md       ← まずこれを開く
├── phase2_checklist.md       ← 手動入力が必要
├── phase3_rc5_output.md      ← 推奨作成の経過
└── phase3_rc1_draft.md       ← 推奨文草案
```

次のステップ：
1. [README_ANNOTATION.md](README_ANNOTATION.md) で確認タグの意味を学ぶ
2. 自分の研究テーマで試す
3. チェックリストに従って確認・入力

---

**Happy Systematic Reviewing on Windows! 🪟✨**

*何か問題があれば Issues で報告してください。*
