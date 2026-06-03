# 定性的SR完全ガイド

定性的システマティックレビューから RC-5（推奨作成の経過）＆ RC-1（推奨文草案）を自動生成するパイプライン。

---

## アーキテクチャ

```
【入力】
extracted.csv (スクリーニング済み論文の PICO + RoB 2)
    ↓
【Phase 1】エビデンス総体テーブル生成
  sr_evidence_table.py
  ├─ アウトカムごとに複数研究を集計
  ├─ GRADE確実性を自動推定
  └─ outputs: evidence_table.md / evidence_table.json
    ↓
【Phase 2】チャンク化 + RAG準備
  build_and_search_chromadb.py (ChromaDB投入)
  └─ output: etd_chunks.json
    ↓
【Phase 3】EtDフレームワーク生成
  sr_etd_builder.py
  ├─ evidence_table.json + extracted.csv → EtD構造体
  └─ outputs: etd_framework.json / summary_of_findings.md
    ↓
【Phase 4】推奨文生成（Direct Claude API）
  generate_recommendation.py
  ├─ ChromaDB RAG検索
  ├─ Claude 3.5 Sonnet (Opus 4.8 推奨)
  └─ outputs: RC-5_output.md / RC-1_draft.md
    ↓
【出力】
├─ RC-5 (推奨作成の経過) - Minds推奨フォーマット
├─ RC-1 (推奨文草案) - Individual Perspective
└─ デバッグ情報 (検索トレース等)
```

---

## クイックスタート

### 1. 依存パッケージのインストール

```bash
cd /Users/ahanai/SR
pip install -r requirements.txt

# 補足: 初回だけChromaDBが埋め込みモデルをダウンロード
# 時間がかかる場合があります（~5分）
```

### 2. スクリーニング済みCSVを準備

前のSRパイプラインから `extracted.csv` を用意：

```bash
python sr_pipeline.py \
  --query "your_pubmed_query" \
  --inclusion "..." \
  --exclusion "..." \
  --output-dir ./sr_output \
  --model gemini  # or claude
```

### 3. 定性的SRパイプラインを実行

```bash
# 環境変数でClaude APIキーを設定
export ANTHROPIC_API_KEY="sk-ant-xxx..."

# パイプライン実行
python sr_qualitative_sr_pipeline.py \
  --extracted ./sr_output/extracted.csv \
  --cq "CQ 1" \
  --outcomes "持久性体力, 筋力, QoL, 倦怠感, うつ" \
  --output-dir ./sr_output/qualitative_sr_output
```

**実行時間目安**: 2-5分

---

## 出力ファイル詳細

### エビデンス総体テーブル

**`evidence_table.md`**
```markdown
| アウトカム | 研究数 | 効果の方向 | 効果量 | 確実性 |
|---|---|---|---|---|
| QoL | 18 | 改善 | (推定量) | ⊕⊕⊕◯ Moderate |
| 倦怠感 | 17 | 改善 | (推定量) | ⊕⊕⊕◯ Moderate |
```

**`evidence_table.json`**
```json
{
  "QoL": {
    "n_studies": 18,
    "certainty_of_evidence": "Moderate",
    "effect_direction": "改善",
    "rob_summary": "High 2, Some concerns 5"
  }
}
```

### EtDフレームワーク

**`etd_framework.json`**
```json
{
  "cq": "CQ 1",
  "pico": {
    "P": "運動習慣のない18～64歳のがんサバイバー",
    "I": "運動・身体活動を勧めること",
    "C": "非介入",
    "O": ["QoL", "倦怠感", "筋力", ...]
  },
  "evidence_summary": { ... },
  "etd_judgments": {
    "benefit_harm_balance": "benefits exceed harms",
    "values_preferences": "moderate uncertainty",
    "resource_use": "insufficient data",
    ...
  },
  "conclusions": {
    "recommendation_direction": "For",
    "recommendation_strength": "Weak"
  }
}
```

### 推奨文

**`CQ1_RC5_output.md`** - 推奨作成の経過
```markdown
## 1. 臨床疑問の定式化（PICO）とアウトカムの選定

運動習慣のない18～64歳のがんサバイバー（P）に対して、
運動・身体活動を勧めること（I）が、非介入（C）と比較して、
QoL、筋力、倦怠感などのアウトカム（O）を改善するかを検討した。

... （詳細な解説）

## 2. エビデンスの確実性と益害バランスの評価

18件のRCTが対象となった。メタアナリシスの結果から、
QoL改善（SMD 0.70）...

... （詳細な解説）
```

**`CQ1_RC1_draft.md`** - 推奨文草案
```markdown
# 推奨文草案（RC-1: Individual Perspective）

運動習慣のない18～64歳のがんサバイバーにおいて、
運動を勧めることを提案する。
（推奨の強さ: 弱い、エビデンスの確実性: C（弱））
```

---

## トラブルシューティング

### Q: ChromaDBの埋め込みモデルがダウンロードできない

**A**: プロキシ設定を確認
```bash
pip install --proxy [user:passwd@]proxy.server:port
```

### Q: "ANTHROPIC_API_KEY が設定されていません"

**A**: Claude APIキーを設定
```bash
export ANTHROPIC_API_KEY="sk-ant-..."
```

または `.env` ファイルに記載：
```bash
ANTHROPIC_API_KEY=sk-ant-...
```

### Q: ChromaDBの検索結果が少ない

**A**: チャンクファイルを確認
```bash
# etd_chunks.json の行数を確認
wc -l sr_output/etd_chunks.json

# JSONの形式を確認
head -1 sr_output/etd_chunks.json | python -m json.tool
```

### Q: RC-5/RC-1の生成がタイムアウトする

**A**: Claudeのモデル設定を確認
```python
# generate_recommendation.py で使用モデルを確認
model="claude-opus-4-8"  # 推奨
# 代替: "claude-sonnet-4-6" (軽量だが精度は下がる)
```

---

## 手動調整ポイント

### 1. etd_framework.json の PICO 補足

自動生成版は簡潔です。詳細に修正：

```json
{
  "pico": {
    "P": "18～64歳の、がんが治癒・安定しているがんサバイバー（N=1,234人）",
    "I": "中強度以上の有酸素運動および/または筋力トレーニング（週3-5日、30-60分）",
    "C": "運動なし、または標準的ケアのみ",
    "O": [...]
  }
}
```

### 2. etd_judgments の手動確認

"データ不十分" となっている項目（resource_use等）は、
ガイドラインの背景文脈から補足：

```json
{
  "resource_use": {
    "description": "日本国内で実施可能な運動プログラムのコスト情報は限定的だが、..."
  }
}
```

### 3. RC-5 / RC-1 の最終編集

自動生成は要旨です。ガイドライン全体の文脈と整合性を確認してから
確定版を作成してください。

---

## Advanced: 各モジュール単独実行

### テーブルだけ生成

```bash
python sr_evidence_table.py \
  --input ./sr_output/extracted.csv \
  --outcomes "QoL, 筋力, 倦怠感" \
  --output-dir ./sr_output
```

### EtDだけ更新

```bash
python sr_etd_builder.py \
  --evidence-table ./sr_output/evidence_table.json \
  --extracted ./sr_output/extracted.csv \
  --cq "CQ 1" \
  --output-dir ./sr_output
```

### RC-5/RC-1だけ再生成

```bash
export ANTHROPIC_API_KEY="sk-ant-..."
python generate_recommendation.py \
  --chunks-file ./sr_output/etd_chunks.json \
  --etd-file ./sr_output/etd_framework.json \
  --cq "CQ 1" \
  --output-dir ./sr_output
```

---

## 次のステップ

1. ✅ `extracted.csv` を準備
2. ✅ `sr_qualitative_sr_pipeline.py` で自動生成
3. 📝 `etd_framework.json` を手動調整
4. 📝 `RC-5_output.md`, `RC-1_draft.md` を編集
5. ✅ ガイドラインに統合

---

## その他

- **cancer_survivor_guidelines.pdf 検証**: 
  本パイプラインが、既存ガイドラインの RC-5/RC-1 を再現できるか確認するテストに利用可

- **メタアナリシス非対応**: 
  定性的SRのため、複数研究のナラティブ集約のみ
  
- **効果量（推定量）**: 
  元論文の詳細データがあれば、二次スクリーニング時に S3 経由で算出可能

---
