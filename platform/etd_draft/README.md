# etd_draft — 既存ガイドライン → GRADE EtD ワークシート下書き

既存の診療ガイドライン（PDF / DOCX / TXT）を CQ 単位に構造化し、GRADE EtD（Evidence to Decision）
フレームワーク（Minds 2020 RC-7 相当、11 基準）のワークシート下書きを CQ ごとに生成する。
出力は委員（パネル）が EtD 審議で使う「たたき台」であり、判断欄は空欄のまま残る。

## 設計方針（CPG 改訂システムの過去設計を踏襲）

| 方針 | 実装箇所 |
|---|---|
| 決定論的処理と LLM 生成の厳密分離 | `segment.py`（規則抽出）/ `verify.py` / `render.py` は LLM を呼ばない。LLM は `draft.py` の (b) 層のみ |
| 引用 ID が解決しない AI 文はハーネス側で reject | `verify.py` R1 — 未解決引用の文を除去し `verification.rejected_statements` に監査ログ、下書き全体を `rejected` に |
| 記載が無ければ「情報なし」。推測で埋めない | `criteria.NO_INFO`、スケルトン生成時のフラグ、system prompt 原則 2 |
| 状態（JSON）が真のソース、DOCX は描画 | `work/state.json`（元GL構造）＋ `work/drafts/<CQ>.json`（EtD 状態）→ `render` |
| 人間の承認ゲート | 委員判断・委員メモ列は常に空。`status` は `draft → verified / rejected` のみで、`approved` は人間側のワークフローに委ねる |

## 使い方

```bash
pip install -e ".[dev]"            # Bedrock を使う場合は ".[dev,bedrock]"

# 一括実行（LLM なし。規則抽出＋候補段落のみで下書きを作る）
python -m etd_draft run path/to/CIPN_GL.pdf --llm none -o work

# 段階実行
python -m etd_draft ingest path/to/CIPN_GL.pdf -o work/state.json
python -m etd_draft draft  work/state.json --llm bedrock -o work/drafts          # 全 CQ
python -m etd_draft draft  work/state.json --llm bedrock --cq CQ3 CQ5 -o work/drafts
python -m etd_draft verify work/state.json work/drafts                           # 検証だけやり直す
python -m etd_draft render work/state.json work/drafts -o work/worksheets --format docx,md
```

### LLM プロバイダ

| `--llm` | 用途 | 設定 |
|---|---|---|
| `none` | 規則抽出＋候補段落のみ（既定） | なし |
| `mock` | 配線・描画確認（内容に意味なし） | なし |
| `bedrock` | Amazon Bedrock Converse API | `AWS_REGION`（既定 ap-northeast-1）、`ETD_BEDROCK_MODEL`（既定 `apac.anthropic.claude-sonnet-4-5-20250929-v1:0`）。認証は通常の AWS 資格情報 |
| `openai` | vLLM 等の OpenAI 互換 API | `ETD_OPENAI_BASE_URL`（既定 `http://localhost:8000/v1`）、`ETD_OPENAI_MODEL`、`ETD_OPENAI_API_KEY` |

`--model` で上書き可。temperature は 0 固定。

## 出力

- `work/state.json` — CQ ごとの段落（`CQ3-p012` 形式の ID、PDF ページ番号付き）、規則抽出した推奨文・強さ・確実性・方向・PICO・アウトカムとその出典段落
- `work/drafts/<CQ>.json` — EtD 11 基準ごとの `judgment` / `research_evidence`（各文に `passage_ids`、検証後は `overlap_score`・`flags`）/ `additional_considerations` / 委員記入欄、結論部、検証レポート
- `work/worksheets/EtD_<CQ>.docx` / `.md` — 横置き A4 の表。末尾に「付録: 引用段落の原文」を付け、委員が引用元を即座に確認できるようにしている

## 検証ルール（verify.py）

- **R1** 研究のエビデンスの各文は 1 つ以上の `passage_ids` を持ち、全て当該 CQ の段落に解決する。違反文は除去して監査ログに残し、下書きは `rejected`
- **R2** `judgment` は `criteria.py` の選択肢文字列のみ。違反は「要判断（委員）」に差し替え
- **R3** 「情報なし／要判断」以外の判断なのに根拠文が空 → 「要判断（委員）」に差し替え
- **R4** 文と引用先段落の文字 bigram 重複率 < 0.30 → 「要確認」フラグ（意訳の可能性があるため除去はしない）
- **R5** 追加考慮事項に数値（%・件・mg など）を含む → 事実主張の疑いとしてフラグ

## 実 GL に適用するときの調整点

- CQ 見出し検出は `segment.CQ_HEADING_RE`（`CQ3` / `CQ 3` / `CQ3-1` / `BQ` / `FQ`、全角は NFKC で吸収）。目次と本文で同じ CQ が 2 回現れる場合は本文側に段落を継続する
- 推奨の強さ・確実性の表記は GL によって異なる（`1/2`、`強い/弱い`、`A–D`、`⊕` 記号、`High/Low`）。`segment.STRENGTH_PATTERNS` / `CERTAINTY_PATTERNS` に追加する
- PDF の 2 段組や表組みは `pdfplumber` の `extract_text()` では順序が崩れることがある。その場合は `ingest.read_pdf` を `page.extract_text(layout=True)` やカラム分割に差し替える
- 基準ごとの候補段落のキーワード（`criteria.Criterion.keywords`）は CIPN 向けに調整済み。他領域では害・実行可能性の語彙を差し替える

## テスト

```bash
pytest -q tests
```

`sample/sample_cipn_gl.txt` は動作確認用に書き下ろした**架空**のガイドライン文であり、実在 GL の文章ではない。
テストは CQ 分割、規則抽出、捏造引用の reject（R1）、選択肢外判断の差し替え（R2）、根拠なし判断の差し替え（R3）、
重複率メトリクス、mock LLM 往復、DOCX/Markdown 描画を網羅する。

## 既知の限界

- 規則抽出は見出し直下に推奨文がある Minds 型 GL を前提にしている。推奨一覧表のみに推奨がある GL では `ingest.read_docx` の表セル取り込みが効くが、PDF の表は追加実装が要る
- R4 の重複率は意訳を「要確認」にするだけで、意味的な改変（方向の反転など）を検出しない。方向の整合（推奨/非推奨、効果あり/なし）は委員の確認事項として残る
- 旧 GL に記載が無い基準（価値観・費用・公平性・受容性・実行可能性）は原理的に「情報なし」になる。これらを埋めるには、新規 SR 結果・経済評価・患者調査を別入力として渡す層（旧設計の Phase 3 相当）を `draft.py` の上に重ねる
