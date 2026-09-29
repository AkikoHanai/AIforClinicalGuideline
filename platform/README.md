# CIPN改訂レビュー・プラットフォーム

委員がAIの生成物を「エビデンスを見ながら」チェックするための最小構成。
ゼミ（武藤さん 2026/07/13）のPhase1→専門家確認→Phase2の流れを、
エビデンス・グラフ（Minds規則 R1–R8）の決定論的検証で挟む形にしたもの。

## 位置づけ

```
SRパイプライン(AIforClinicalGuideline)      ゼミのBedrock Agent
  検索→スクリーニング→データ抽出               Phase1: 推奨案JSON生成
            ↓                                        ↓
      CQパッケージ (data/cq/*.json)  ←──────────────┘
            ↓
    review_bundle.py   ← ここはLLMを呼ばない。規則で検証する
       ・R1–R8 の検証（適格性/二重計上/撤回/非直接性/重大アウトカム/格下げ理由）
       ・AI申告 vs グラフの事実 の照合（確実性・引用PMID・アウトカム・語彙）
       ・推奨の由来鎖（AGREE II 項目12の証跡）
            ↓
    render_console.py → review/<CQ>.review.html （委員に配る1ファイル）
            ↓
    委員の判定JSON → 事務局が集約 → Phase2(解説文生成) へ
```

**AIは推奨を決めない。** 決めるのは委員で、AIは承認済みデータを文章にする。
検証はLLMではなく規則で行い、不合格のCQは委員に出す前に差し戻す。

## 使い方（CIPN診療ガイドライン改訂・Mac）

```bash
cd ~/AIforClinicalGuideline
git pull
brew install poppler              # pdftotext(初回のみ)

# 初回: 2023年版PDFから作業一式を作る
bash platform/run_revision.sh ~/path/to/CIPN診療ガイドライン2023年版.pdf

# 委員が review_workspace/CQ*/papers/ に論文PDF(PMID.pdf)を入れたら
bash platform/run_revision.sh "" review_workspace          # Bedrock(AWS認証が必要)
SYNC_ONLY=1 bash platform/run_revision.sh "" review_workspace   # 認証なし: 新規PDFの登録だけ
```

出力は `review_workspace/` に集まる:

| パス | 中身 |
|---|---|
| `CQ*/minds_review.xlsx` | 検索式 / CQ・PICO / 評価指標 / スクリーニングログ / RoB2_Claude下書き / RoB2_担当者×2 / RoB2_照合 / エビデンス総体評価 / 文献リスト / 推奨文草案(FRQは FRQ記載草案) / SoF |
| `CQ*/MANIFEST.md` | 2023年版採用文献と、papers/ から自動登録した新規文献 |
| `CQ*/papers/` | 論文PDFを置く(PMID.pdf) |
| `_draft_sheets/*.review.html` | 委員用: Minds推奨文草案の作成シート(内部の検証結果は出さない) |
| `_secretariat/*.secretariat.html` | 事務局用: 機械検証(R1–R8)・根拠鎖つき |

既にある `minds_review.xlsx` は2回目以降も上書きしない(委員の記入を守る)。作り直すときは
`python3 platform/core/prepare_review_workspace.py review_workspace/_cq_packages -o review_workspace --force`。

macOSで「検証できませんでした」と出て開けないときは、ダウンロードしたフォルダに対して
`xattr -dr com.apple.quarantine <フォルダ>` を1回実行する。

### 個別のスクリプト

| スクリプト | 役割 |
|---|---|
| `core/extract_cipn_guideline.py` | 2023年版PDF → CQパッケージ(推奨・強さ・確実性・解説・文献PMID) |
| `core/prepare_review_workspace.py` | CQパッケージ → Minds様式workbook等。冷却/圧迫の統合、FRQ、アウトカム、担当委員を反映 |
| `core/fill_rob2_from_papers.py` | papers/*.pdf → Bedrockでデザイン/対照/評価指標/RoB2を抽出し下書きシートへ。新規論文をログ・マニフェストに登録 |
| `core/merge_rob2_evidence.py` | 評価者2名のシートを照合しCQパッケージへ書き戻す |
| `core/build_sof.py` | エビデンス総体評価 → SoF |
| `core/review_bundle.py` | Minds規則R1–R8と引用整合性の機械検証 |
| `core/render_console.py` | 草案作成シート(委員用) / 検証画面(事務局用 `--audience secretariat`) |

## CQパッケージの書き方（data/cq/*.json）

| キー | 中身 | 誰が入れるか |
|---|---|---|
| `pico` / `outcomes` | PICOとアウトカム（重要度1–9） | スコープ確定時に委員会 |
| `studies` | 論文（pmid, design, retracted, trial_ids） | PubMedから機械抽出（`edge_extract.py`） |
| `results` | 論文×アウトカム×比較 の結果 | データ抽出時にSR担当 |
| `includes` | メタ解析が含む研究 | 参考文献リストから半自動 |
| `evidence_bodies` | アウトカムごとの総体（確実性・格下げ理由） | SR担当（Minds SR-5相当） |
| `draft` | Phase1が出した推奨案JSON | AI生成 |
| `narrative` | Phase2の解説文 | 承認後にAI生成 |

`comparator`（対照の種類）と`eligible`（適格性）は**人手で入れる**。
ここを機械任せにすると、実対照との差なしを「効果なし」と誤判定する。

## 検証で弾いているもの

デモCQで実際に検出される例：

- **R2** 同一試験の主報告と副次報告が両方エビデンス総体に入っている（二重計上）
- **R3** メタ解析とその構成RCTが同一総体に同時に入っている（二重計上）
- **R6** CQの対照は「冷却なし」なのに、実対照（弱い冷却）の結果を非直接性の格下げなしで使っている
- **確実性の不一致** AIが「確実性B」と申告したが、重大アウトカムの総体から導くとD
- **引用の捏造** 推奨案が引用するPMIDが根拠グラフに存在しない
- **スコープ逸脱** 設定していないアウトカム（全生存期間）への言及

## ファイル

```
core/evidence_schema.py    ノード型・エッジ型の閉じた語彙、Minds規則 R1–R8
core/evidence_graph.py     グラフ本体・規則検証・多段推論
core/edge_extract.py       PubMedから機械抽出できるエッジ（試験登録番号・撤回）
core/review_bundle.py      CQパッケージ → 検証済みレビューバンドル
core/render_console.py     バンドル → 委員用HTML
data/cq/*.json             CQパッケージ（★DEMOは架空データ。実データは別ファイルで）
review/*.bundle.json       検証結果つきバンドル
review/*.review.html       委員に配る画面
tests/test_evidence_graph.py  20件（通過）
```

## テスト

```bash
cd core && python -m pytest ../tests/test_evidence_graph.py -q
```

## 次にやること

1. 実CQ 1件で `data/cq/` を実データ化し、委員2–3名にHTMLを配ってレビューを試す
2. Phase1（推奨案生成）の出力を `draft` に直接書き込む配線（Bedrock/Claude API）
3. 委員の回答JSONを集約して差し戻し理由を分類 → Minds 7.2「作成経過に関する報告事項」へ
4. `edge_extract.py` を実文献リストに当てて `studies`/`trial_ids` の自動投入
