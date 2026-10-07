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
| `CQ*/minds_review.xlsx` | 検索式 / CQ・PICO(層別の方針つき) / 評価指標 / 既存GL比較 / スクリーニングログ / 研究特性(化学療法の分類) / **4-5_Claude下書き / 4-5_担当者×2 / 4-5_照合**(Minds様式4-5) / **SR-8_エビデンス総体**(Minds様式SR-8) / RoB2(参考) / 文献リスト / 推奨文草案(FRQは FRQ記載草案) / SoF |
| `CQ*/MANIFEST.md` | 2023年版採用文献と、papers/ から自動登録した新規文献 |
| `CQ*/papers/` | 論文PDF(PMID.pdf)。**必須ではない**: オープンアクセス全文(Europe PMC)は自動取得し `PMID.txt` にキャッシュする。取れなかった有料誌の分だけPDFを置く |
| `_draft_sheets/*.review.html` | 委員用: Minds推奨文草案の作成シート(内部の検証結果は出さない) |
| `_secretariat/*.secretariat.html` | 事務局用: 機械検証(R1–R8)・根拠鎖つき |
| `_meeting/決定記録シート.html` | 推奨作成会議用: 投票(最大3回)・投票除外・成立の判定・確定、JSON/CSVで共有(投票者は統括委員と作成グループ委員。患者代表は含めない) |
| `_minds_documents/` | Minds書類の一式: CQ別の作業ブック、書類の作成状況(PRISMA件数つき)、推奨作成の記録、管理台帳(COI・外部評価・作成経過) |

既にある `minds_review.xlsx` は2回目以降も上書きしない(委員の記入を守る)。作り直すときは
`python3 platform/core/prepare_review_workspace.py review_workspace/_cq_packages -o review_workspace --force`。

macOSで「検証できませんでした」と出て開けないときは、ダウンロードしたフォルダに対して
`xattr -dr com.apple.quarantine <フォルダ>` を1回実行する。

### 個別のスクリプト

| スクリプト | 役割 |
|---|---|
| `core/extract_cipn_guideline.py` | 2023年版PDF → CQパッケージ(推奨・強さ・確実性・解説・文献PMID) |
| `core/prepare_review_workspace.py` | CQパッケージ → Minds様式workbook等。冷却/圧迫の統合、FRQ、アウトカム、担当委員を反映 |
| `core/fill_rob2_from_papers.py` | 各論文の本文(PDF → OA全文 → 抄録の順に入手) → Bedrockで化学療法の分類・症例数・対照・評価指標・4-5の各項目(0/-1/-2)・リスク人数・効果量を抽出し、4-5_Claude下書き/研究特性/RoB2(参考)へ。評価者シートには書かない(独立二重評価)。新規PDFをログ・マニフェストに登録 |
| `core/minds_forms.py` | Minds様式4-5・SR-8の列構成と読み書き(公式様式の列A〜Zは変更しない) |
| `core/merge_rob2_evidence.py` | 4-5の評価者2名を項目ごとに照合(確定列>一致>要協議)し、SR-8とあわせてCQパッケージへ書き戻す。評価者の入力が無い間は下書きを「未確定」で表示に使う |
| `core/build_sof.py` | SR-8エビデンス総体 → SoF(化学療法別の層別行を含む) |
| `core/review_bundle.py` | Minds規則R1–R8と引用整合性の機械検証 |
| `core/render_console.py` | 草案作成シート(委員用。採用文献の概要表に、がん腫・化学療法・介入・対照を表示し、化学療法の分類で絞り込める) / 検証画面(事務局用 `--audience secretariat`) |
| `core/render_meeting.py` | 推奨作成会議の決定記録シート(HTML 1ファイル) |
| `core/export_minds_documents.py` | Minds書類の一式を集め、CQごと・書類ごとの作成状況を点検する |
| `tests/ui_check.py` | 画面のブラウザ操作テスト(playwright) |
| `governance/plan_guard.py` | 承認済み企画書からの逸脱の検査 |

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

## Minds 様式との対応と、化学療法の種類の扱い

- **個別研究の評価は Minds 様式 4-5(評価シート 介入研究)**。2023年版の SR 担当者が使った様式と同じ列構成で、
  バイアスリスク10項目(ランダム化・コンシールメント・盲検化×2・ITT・不完全報告・選択的報告・早期中止・その他・まとめ)と
  非直接性5項目(対象・介入・対照・アウトカム・まとめ)を **0 / -1 / -2** で評価する。アウトカムごとのブロックに研究を並べ、
  リスク人数と効果指標を記入する。評価者2名が互いを見ずに記入し、`4-5_照合` の不一致を協議して確定列に書く。
- **エビデンス総体は SR-8**(バイアスリスク・非一貫性・不精確性・非直接性・その他を 0/-1/-2、上昇要因 0/+1/+2、強さ A〜D、重要性 1〜9)。
- **RoB 2 は参考欄**(`RoB2(参考)` シート)。公式様式ではなく、独立二重評価・照合の対象にもしない。
- **2023年版の評価の引継ぎ**: 2023年版の表記(✔/?/－)は 0/-1/-2 に変換して 4-5_Claude下書きに入る(アウトカム別に要見直し)。
- **化学療法の種類**: CIPN は薬剤クラスで病態・経過・介入効果が異なるため、`研究特性` シートに化学療法の分類
  (白金製剤/タキサン系/ビンカアルカロイド系/プロテアソーム阻害薬/複数・混合/その他)を記録する。
  ①4-5の「非直接性 対象」で本CQの対象との一致を評価、②SR-8に層別行(白金製剤/タキサン系)を置き効果が異なる場合は別々に総体を作る、
  ③草案作成シートでは分類別の研究数とフォレストプロット(全体+層別)を表示、④推奨の対象を限定するか検討する。

## フォレストプロットと海外ガイドライン(2020)との比較

- 4-5シートの効果指標(RR/OR/MD…と値・信頼区間)またはリスク人数(RRを計算)から、草案作成シートの「エビデンス総体」に
  アウトカムごとのフォレストプロット(白黒SVG、化学療法の分類別も)を描く(`core/forest_plot.py`)。
  統合値は逆分散法(固定効果)の参考値。Minds では統合方法(変量効果・異質性の評価)を SR 委員が判断する。
- minds_review.xlsx の「既存GL比較」シートに ASCO 2020 (Loprinzi et al.) / ESMO-EONS-EANO 2020 (Jordan et al.)
  の当該介入に関する記載要約を入れてある。原文照合の上「事務局確認」を☑にする。
  シートの修正はそのまま草案作成シートの「海外ガイドライン(2020年)の推奨」に反映される。
