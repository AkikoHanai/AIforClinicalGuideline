# GL作成ポータル(AWS)

がん薬物療法に伴う末梢神経障害診療ガイドライン2028年版の作成を、CIPN診療ガイドライン2023年版の手順(Minds 2020)のとおりに、委員がブラウザで進めるためのポータル。
千葉大学の AWS アカウント(東京リージョン)に置く。名簿・COI は Google フォーム・ドライブで管理し、ポータルには置かない。
Google ドライブとの受け渡しは統括委員長の Mac を経由する。

**担当のペアの相互確認**(統括委員長の決定 2026-11-27): 文献選択(一次・二次)は、担当の委員が独立に判定し、ポータルが照合する。研究特性・SR-5・SR-8 は、AI が下書きし、担当の委員 2名が、相手の内容を見ずに、それぞれ承認する(`PUT /papers/<cq>/<pmid>` の `chars`、`PUT /f45/...`、`PUT /sr8/<cq>/<outcome>`)。2名の内容が一致すると確定する。違うときは、違う欄を表示する(SR-5 は確定欄で照合する)。SR-8 の AI下書きは、SR-5 の確定のときに作る(`POST /sr8/<cq>/<outcome>/draft` で作り直す)。バイアスリスクは Minds の 0 / -1 / -2。

**ガイドラインと総論の Update 版**: `./fetch.sh` が、共有ドライブの `ポータル出力/ガイドライン_Update版/` に、総論ごと(`総論X_題名_Update版.docx`)・CQ ごと(`推奨_名称_Update版.docx`)の Word と、`ガイドライン草案(結合).docx` を置く。共有ドライブで編集した Update 版は、次の `./fetch.sh` でポータルに反映する(総論は原稿の新しい版、CQ は推奨文と解説の版。`GET /update`、`POST /update/<soron|cq>/<ID>/upload-url`)。どちらが変わったかは、最後に転送した内容の要約値(`/sync/state`)で判定し、編集された版を上書きしない。結合した草案は、転送のたびに全ての Update 版から作り直す(`GET /export/guideline`。`api/guideline.py`)。画面では、「総論の執筆・査読」と「EtD・推奨」の「Update 版」で開く。

**基準の企画書**(統括委員長の決定 2026-11-27): 企画書 Ver1.2(2026-10-26。`platform/governance/企画書_Ver1.2_2026-10-26.docx`、機械可読版 `approved_plan.json`)。SR項目10・FRQ項目5(鍼灸による予防は FRQ)。CQ か FRQ かは、企画書のどちらの表にあるかで決める(内部コードの先頭の文字では決めない)。`./setup_portal.sh` が、登録済みの項目の名称・担当・CQ か FRQ か、総論の題名を、企画書に合わせる(`POST /admin/seed`。記録は変えない)。名称が変わった項目のファイル(Scope の SC-4、Update 版、Minds 書類、総論の依頼書)は、`./fetch.sh` が共有ドライブで新しい名前に変える(編集と Google Drive のリンクを引き継ぐ。`approved_plan.json` の「旧名称」)。氏名は、企画書の名簿の表記で照合する(空白・字体の違いは同じ人として扱う)。

## 2つの流れ(独立)
| 流れ | 使う人 | 手順 |
|---|---|---|
| SRの流れ(CQ) | SR委員、SR委員長、作成グループ、統括委員会、事務局 | 検索の記録 → スクリーニング(2名が独立に可否を入力、協議の結論)・文献選択の流れ図 → 論文 → SR-5(2名が独立に判定、照合) → SR-8 → EtD・推奨(投票) |
| 総説の流れ(総論A〜N) | 総説執筆者、統括委員会、事務局 | 原稿(Word)をポータルで提出 → 査読中 → 統括委員会の査読コメント → 修正中 → 修正版の提出 → 完了(統括委員会) |
総説執筆者だけの利用者は SR の画面に入れず、SR委員だけの利用者は総説の画面に入れない(API で制限)。委員の操作は全てブラウザで行い、ターミナルは使わない。ターミナルを使うのは、統括委員長の展開とドライブとの受け渡しだけである。

## 画面と、委員が行う判断
| 画面 | 内容 | 判断する人(Minds) |
|---|---|---|
| Scope | Minds 第3章の様式 SC-1〜SC-4(Excel 18件)。ログイン後の最初の画面。「開く」は画面に表示する(`GET /docs/view`。ダウンロードしない)。「Google Drive」は共有ドライブの同じファイル(`./fetch.sh` が URL を登録した後に出る)。生成: `python3 platform/scope/build_scope_minds.py`(公式テンプレートに記入)。登録: `./setup_portal.sh` | 全員 |
| ホーム | 利用者ごとに変わる。対応が必要なもの(投票、自分が確定できる記録)、担当 CQ の未判定・未提出の件数(一次・二次スクリーニング、SR-5、SR-8)、担当の総論、全 CQ・FRQ の記録(件数だけ。統括委員会・事務局・SR委員長・作成グループ) | 全員 |
| CQ一覧 | SR項目10・FRQ項目5(企画書 Ver1.2)。企画書の順(予防 → 治療 → FRQ)。担当の決まっていない枠は「公募」。読むだけ。P(がん化学療法を受ける患者)・C(無治療)・O(CIPN)は全 CQ で共通、I は CQ の名称。各画面へのリンク | 全員 |
| 論文 | 二次スクリーニング採用論文を PMID で登録し、PDF を置く。本文を取り込み(Method・Result の段落に ID)、SR-5 の下書きを自動で作る。一覧: PMID、筆頭著者・雑誌・発行年、題名、研究デザイン、対象者数、介入、対照、評価時点 | 担当委員 |
| SR-5 | 左に本文の段落(Method・Result、検索、根拠の段落を強調)と PDF、右に 15 項目の判定(0/-1/-2)・根拠の段落ID・引用。2名が独立に判定し提出(相手の評価は2名が提出するまで見えない)。提出後、照合欄で協議の結果を確定。Claude 下書き(本文の段落だけを根拠に作る。本文がない論文では作らない)は出発点として取り込み、修正して提出する | 担当委員2名(照合)、SR委員長 |
| SR-8 | アウトカムごとに、確定したSR-5を化学療法の分類で層別して表示。5要因(0/-1/-2)、上昇要因、確実性(A〜D)、層別の結論 | SRチーム |
| EtD・推奨 | 2023年版の体裁。左に 2023年版の記述(推奨文・強さ・確実性・解説の段落ID・投票)、右に 2028年版の案(推奨文はがん種・レジメンを明記、強さ、確実性、4つの考慮事項と根拠の段落ID、投票の記録、解説) | 作成グループ(投票)、統括委員会(確定) |
| 総論(A〜N) | 企画書の 18 項目。原稿の提出(版ごとに保存)、状態、期限、査読コメント | 執筆者(提出)、統括委員会(査読・完了) |
| 検索の記録 | CQ ごとに、検索を実行するたびに 1 行(データベース、検索日、検索者、検索期間、検索式、件数)。修正は作成経過の記録に残る | 担当委員、事務局 |
| 検索の記録 | 検索は、ポータルが実行する。統括委員会・事務局が「検索を実行し、スクリーニングの対象に登録する」を押すと、決定済みの式と期間(`platform/data/search_plan.json`。`setup_portal.sh` が登録する)で PubMed を検索し、検索の記録と文献(題名・抄録)を登録する(`POST /search/<cq>/run`。Lambda が非同期で実行)。式が未確認の検索は、実行しない | 実行: 統括委員会・事務局 |
| スクリーニング・流れ図 | 文献の取り込み(PubMed の CSV、PMID の行。登録済みは重複として数える)、題名・抄録の取得(PubMed)、一次・二次の可否と除外理由の入力(相手の判定は自分の判定の後に表示。2名がそろった後は変更できない)、不一致の文献の協議の結論、文献選択の流れ図(記録から数えた件数) | 担当委員2名(可否)、担当委員・SR委員長(協議の結論) |
| 利用申請 | 委員が自己登録(Sign up)し、氏名・所属を申請。統括委員長が承認して役割を付ける(名簿に基づく役割の候補を表示)。承認の前は、何も見えない | 統括委員会 |
| 推奨の投票 | 電子投票。統括委員会がラウンドを開始・終了し、投票者(統括委員会・作成グループ。SR担当と投票除外を除く)が各自で投票。1人1票、変更不可、無記名。終了まで集計を非表示。成立: 参加75%以上かつ最多80%以上。最大3回、3回で成立しなければ推奨なし | 統括委員会(ラウンド)、統括委員会・作成グループ(投票) |
| 利用者 | 承認済みの利用者の一覧。例外の直接登録と招待 | 事務局 |
| Minds書類の出力 | CQ ごとに、記録から xlsx(CQ、検索の記録、文献選択の流れ図、スクリーニング、研究特性、SR-5、SR-8、SoF表、EtD・推奨、作成経過)を出力。EtD・推奨とSR-8 の画面のボタン | — |
| EtD の Claude 下書き | SR-8・確定したSR-5・2023年版の記述だけを根拠に、推奨文案・4つの考慮事項・解説文案を作る(根拠 ID 付き。強さと確実性は含めない)。作成グループが取り込み、修正・保存 | 作成グループ |
| 総論の 2023年版参照 | 総論の画面で、2023年版の本文(段落 ID 付き)と Word 原文を参照 | — |
| 作成経過の記録 | 全操作の追記。更新・削除の操作はない | — |

規則: 盲検化の2項目は -2 を使わない(統括委員長の決定)。抄録のみの論文では下書きを作らない。判断は委員が行い、AI は本文の段落を根拠とする下書きに限る。

## 構成(`infra/portal_stack.py`)
Cognito(自己登録 + 統括委員長の承認、メール、MFA任意、役割グループ7つ。承認の前の利用者は、/me と利用申請だけを使える)/ DynamoDB 1テーブル(PITR)/ S3(論文PDFと本文、非公開・暗号化・版管理)/
Lambda(Python 3.12、`api/`。pypdf 同梱。Bedrock で下書き)+ API Gateway HTTP API(Cognito JWT 認可)/ S3 + CloudFront(`web/`)。
テーブル・利用者プール・論文バケットはスタックを消しても残る。

## 展開(Mac)
```bash
cd ~/AIforClinicalGuideline && git checkout claude/sleepy-turing-a740xe && git pull
python3 -m venv .venv && source .venv/bin/activate
pip install -r platform/portal/infra/requirements.txt boto3
npm install -g aws-cdk
export AWS_DEFAULT_REGION=ap-northeast-1
cd platform/portal/infra && cdk deploy --require-approval never --outputs-file ../out/outputs.json && cd ~/AIforClinicalGuideline
python3 platform/portal/scripts/admin_user.py <メールアドレス> 華井明子      # 統括委員長の利用者と招待メール
python3 platform/portal/scripts/admin_user.py --seed <メールアドレス>       # 企画書の CQ・総論を入れる
```
Bedrock のモデルは環境変数 `BEDROCK_MODEL_ID`(省略時 `anthropic.claude-sonnet-4-5`)で指定し、`cdk deploy` の前に設定する。
2023年版の記述(CQ)は、`run_jascc.sh first` が作る `etd_2023.json` を `scripts/admin_user.py --gl2023 <json> <メールアドレス>` で取り込む。2023年版の総論は `scripts/import_soron2023.py <メールアドレス>` で取り込む(`platform/data/gl2023/units.json` の段落と、`platform/soron/out` の依頼書(Word)。新設の K・N は依頼書だけを置く)。

## 試験
```bash
pip install moto pytest pypdf
python3 -m pytest platform/portal/tests -q
```

## 本文を取り出せない PDF(画像だけの PDF)
`sync_papers.py` は、文字を取り出せない PDF を「画像PDF(本文を抽出できない。OCR が必要)」として登録し、終わりに一覧を出す。Mac の文字認識(Apple Vision)で本文を入れる:
```bash
pip install pypdfium2 ocrmac
python3 platform/portal/scripts/sync_papers.py --pdf-dir <フォルダ> <メールアドレス>   # もう一度実行すると、該当 PDF だけ OCR して本文を入れる
```
OCR の本文は状態「本文抽出済(OCR(Apple Vision))」で区別する。SR-5 の画面では PDF を並べて表示するので、引用箇所は PDF で確認する。
Method・Result の見出しを判定できない PDF は「本文抽出済(節の見出しを判定できない。全段落を参照)」とし、画面では全段落を表示する。

## 画面の体裁の規則
1. 文字の大きさは 1 種類(`style.css` の `body` の指定だけ)。見出しは太字と罫線で区別する。
2. 白抜き文字(濃い地に白い字)を使わない。
3. 承認(確定)が必要な箇所は、橙色の枠(`.approve`)で示す。
`tests/test_api.py` の `test_web_style_rules` が、1〜3 を検査する。

## アウトカム(統括委員長の決定 2026-11-16)
今回の改訂では、全CQ・FRQのアウトカムを「CIPN」とする。初期データの作成は、この値で CQ を作る。既にある CQ には次で登録する(未登録の CQ だけ):
```bash
python3 platform/portal/scripts/admin_user.py --outcomes <メールアドレス>
```

## 共有ドライブへの転送(ポータル → ドライブ。統括委員長の決定 2026-11-20、方式の決定 2026-11-24)

統括委員長の Mac の Google Drive for desktop の同期フォルダへ書き込み、Google Drive for desktop が共有ドライブ「CIPNガイドライン作成」へ同期する(学術アカウントでは Apps Script などの共有が使えないため、Google 側の設定は使わない)。AWS のサーバーは Mac のフォルダに書けないため、転送は Mac で行う。

```
cd ~/AIforClinicalGuideline && git pull && ./fetch.sh
./fetch.sh --dry-run    # 置く場所と内容の表示だけ(何も置かない)
./fetch.sh --tree       # 共有ドライブのフォルダの構成を表示する(--tree=4 Chap4_SR --files: 深さ・フォルダ名・ファイル名)
./fetch.sh --watch      # 30分ごとに繰り返す(ウィンドウを開いたままにする)
./deploy_portal.sh      # ポータル(AWS)の展開(画面・API を更新したとき)
```

- Scope は、共有ドライブの Excel を Google スプレッドシートで編集した版を正とする。`./fetch.sh` は、人が編集した版をポータルに反映し(ドライブ → ポータル。上書きしない)、生成した版のままのファイルだけを、ポータルの新しい版で置き換える。人が編集したかは、ファイルの内容の要約値が、リポジトリの生成した版(現在のファイルと git の履歴)にあるかで判定する。編集済みの Scope は、`./setup_portal.sh` でも置き換えない。生成した版に戻すときは `./fetch.sh --reset SC-3`(編集された版は、別の名前で残す)。Google スプレッドシート形式(.gsheet)に変換したファイルは読めない。手順書は、生成した版を正とする(ドライブで編集された版は、別の名前で残してから置き換える)。ポータルの記録から出力する Minds書類・別添は、ポータル → ドライブの一方向
- `./fetch.sh` は、転送した Scope・手順書の Google Drive 上の URL を、ポータルに登録する(Google Drive for desktop がファイルに付ける ID `com.google.drivefs.item-id#S` を `xattr` で読む。同期前のファイルは、同期が終わるまで最長 5 分待つ。それでも残ったものは、次の実行で登録する)。ポータルの「Scope」「手順書」に「Google Drive」のリンクが出る
- 場所の指定・コードの修正は要らない。共有ドライブのフォルダは、`~/Library/CloudStorage/GoogleDrive-*/共有ドライブ/CIPNガイドライン作成`(英語表示は `Shared drives`)から自動で見つける。`DRIVE_DIR` または `--drive <フォルダ>` で指定もできる。
- スクリプト(`fetch.sh`、`upload_docs.py`、`import_soron2023.py`、`run_search.py --import` など)のメールアドレスの指定は、省略できる。保存済みのもの(`~/.jascc_gl_portal.json`)、なければ統括委員会の唯一の利用者を使う。プールにいないメールアドレスを指定したときは、プールの利用者の一覧(メールアドレス・氏名・グループ)を表示して止まる。AWS にログインしていなければ、ログインを求める。
- 置き場所は、共有ドライブの既存のフォルダ(ガイドラインの目次に沿った構成: `新規ガイドライン作成/Chap2_準備` 〜 `Chap8_公開後調整`)を、深さ4まで調べて決める。同じ名前のフォルダ(全角・半角の違いは同じとみなす)があればそこへ置き、なければ `新規ガイドライン作成/ポータル出力/` に作る。既存の構成には、新しいフォルダを作らない。
  - CQ・FRQ の一式: 企画書の `dir` の名前(例: `CQ1-牛車腎気丸`)のフォルダがあれば、その中。なければ `ポータル出力/<dir の名前>/`。
  - 総論: 「総論A」「総論I-1」などで始まるフォルダ。なければ `ポータル出力/総論/総論<項目>_<題名>/`。原稿の全ての版(`<日時>_<版ID末尾>_<ファイル名>`)と `状態.txt`。
  - `依頼書/`、`マニュアル/<対象>/`: 同名のフォルダがあればそこ。なければ `ポータル出力/` の下。
  - Minds 様式ごと: 共有ドライブの `Chap4_SR/SR_n`(Minds のテンプレート `chap4_SR_n_tmp_2020ver3_0.xlsx`、記入例、解説が入っているフォルダ)と `Chap6_推奨` に、CQ ごとのファイルを、テンプレートと同じフォルダに置く。テンプレートには触れない。フォルダがなければ、その CQ のフォルダの `様式別/` に置く。

    | ポータルの出力 | 置き場所 | ファイル名 |
    |---|---|---|
    | SR-1 DB検索結果(検索の記録) | `Chap4_SR/SR_1` | `chap4_SR_1_<CQのID>_<名称>.xlsx` |
    | SR-2 文献検索フローチャート | `Chap4_SR/SR_2` | `chap4_SR_2_…` |
    | SR-3 二次スクリーニング後の一覧 | `Chap4_SR/SR_3` | `chap4_SR_3_…` |
    | SR-5 介入研究評価(0/-1/-2。研究特性を含む) | `Chap4_SR/SR_5`(`SR_5_ROB2` には置かない) | `chap4_SR_5_…` |
    | SR-8 エビデンス総体 | `Chap4_SR/SR_8` | `chap4_SR_8_…` |
    | SR-12 SoF | `Chap4_SR/SR_12` | `chap4_SR_12_…` |
    | EtD・推奨 | `Chap6_推奨` | `chap6_EtD_…` |

    各ファイルは、CQ のシートと、その様式のシートだけからなる。ポータルの様式は Minds のテンプレートの書式そのものではなく(SR-8 の列だけが Minds の列)、テンプレートへの転記は委員が行う。
  - 一式(全シート。作成経過を含む)と文献選択の別添は、`ポータル出力/<dir の名前>/` に置く。
  - 内容が変わったものだけを置き換える(xlsx は、作成日時を除いて比べる。共有ドライブの版の履歴を増やさない)。
- 転送済みの版(同じ名前・同じ大きさ)は飛ばす。Minds書類と文献選択の別添は、同じ名前で最新の内容に置き換える(ドライブの版の履歴に残る)。転送した内容は、作成経過の記録(「共有ドライブへの転送」)に残る。ドライブからポータルへは戻さない。
- 共有ドライブのメンバーは、委員に限る。

## サインインできないとき(統括委員長)

ポータルの「Incorrect username or password」は、利用者がいない場合もパスワードが違う場合も、同じ表示になる(利用者の存在を隠す設定)。「Forgot your password?」も、利用者がいない場合は、メールが届かないまま「送った」と表示される。AWS の権限で、直接確認する。

```
python3 platform/portal/scripts/admin_user.py --diagnose [<メールアドレス>]      # 原因を調べる
python3 platform/portal/scripts/admin_user.py --password <メールアドレス>        # パスワードを直接設定し、直後にサインイン試験をする
python3 platform/portal/scripts/admin_user.py --users                            # 利用者の一覧(メールアドレス・氏名・グループ)
python3 platform/portal/scripts/admin_user.py --chair <メールアドレス> <氏名>    # 一覧にないとき: 統括委員長の利用者を作り、パスワードを設定し、統括委員会に入れる(招待メールは送らない)
```

確認すること(`--diagnose` が表示する):
- ログイン画面が使っている利用者プール・クライアント(CloudFront の `config.js`)が、`outputs.json` と一致するか。違うときは、画面の設定に合わせて動く(別のプールの利用者にパスワードを設定しても、画面から反映されないため)。
- この利用者プールは、サインインでメールアドレスの大文字・小文字を区別する(`Akiko@…` と `akiko@…` は別の利用者)。保存されている表記と、ログイン画面で入力した表記が同じか。
- 利用者の状態(確認済みか、有効か、メールが確認済みか、多要素認証)。
- `--password` は、設定した直後に、ポータルと同じ認証(メールアドレスとパスワード)を実際に行い、結果(【確認OK】または【確認NG】)と、サインインで入力するメールアドレスを表示する。

パスワードは 12文字以上で、大文字・小文字・数字を含む。

## 「Failed to fetch」が出るとき(統括委員長)

ブラウザから API・Cognito に届いていない(通信の失敗)。API の許可設定(CORS)、API の URL、学内ネットワーク・ブラウザの拡張機能が原因になる。

```
python3 platform/portal/scripts/check_site.py
```

ブラウザと同じ要求(画面の origin からの事前確認 OPTIONS、認証なしの GET、Cognito のトークン取得)を送り、`[NG]` の行で原因を示す。AWS の権限があれば、API Gateway の CORS・ルートの認可・Lambda の状態も表示する。`[NG]` がなければ、Cmd+Shift+R で再読み込み、別のブラウザまたはシークレットウィンドウで試す。
API のルートは、メソッドを明示する(GET・POST・PUT・DELETE・PATCH)。`ANY` にすると、OPTIONS にも認可が掛かり、ブラウザの事前確認が 401 で止まる。展開(`./deploy_portal.sh`)で反映される。

## 検索式の用語の確認

`python3 platform/portal/scripts/check_mesh.py` が、検索計画の 17 検索(案を除く)の PubMed の解釈と、MeSH の見出し語を確認する。2026-11-20 の確認結果は `platform/data/search_plan.json` の `mesh_check`。

## 手順書と依頼書の受け渡し(個別に送付しない)

委員は、ポータルで手順書と依頼書を受け取る。統括委員長が行う操作は、委員の招待(「利用者」の画面。手動)と、次の 2 つのコマンドである。

```
python3 platform/portal/scripts/upload_docs.py <メールアドレス>        # 手順書(platform/manuals/out、procedures/out の 2 件)を「手順書」の画面に置く
python3 platform/portal/scripts/import_soron2023.py <メールアドレス>   # 総論の依頼書 19 件を「総論の執筆・査読」の各行に置く
```

- 「手順書」の画面は、ログインした委員の役割に応じた手順書だけを表示する(SR委員: 操作マニュアル、SR委員の手順書、論文PDFの入手、用語の定義。総説執筆者: 操作マニュアル、総説執筆者の手順書、用語の定義)。
- 総論の依頼書は、その総論の執筆者、統括委員会、事務局だけが開ける。
- 手順書を置けるのは、統括委員会と事務局に限る。

## 保存済みの検索の資料(参考)

リポジトリに保存してある検索の資料を、「検索の記録」の画面の参考の枠に置く。検索の記録・流れ図の件数には数えない。

```
python3 platform/portal/scripts/import_search_reference.py <メールアドレス>
python3 platform/portal/scripts/check_pubmed.py        # PubMed からの題名・抄録の取得を、Mac から実際の PubMed で確認する(AWS は不要)
```

- `platform/data/search_reference.json`: CQ ごとの検索式の案(前回Scopeの式。`core/prepare_review_workspace.py` の P節・C節・I節)と、2023年版の検索過程(`platform/prior_worksheets/search_*.json`。12 件)。
- 2023年版の検索過程の記録がない CQ: P2(プレガバリン・予防)、T2(アミトリプチリン)、F3(オピオイド)、F4(併用療法)。
- 今回(2028年版)の検索結果の一覧(検索式ごとの全件)は、リポジトリに保存されていない。`platform/literature_update/records.json` は、2026-10-26 に題名と RCT に限定して確認した 64 件であり、前回Scopeの式による検索ではない。

## 検索の実行と、文献選択の別添(統括委員長の決定 2026-11-20)

検索期間は 2026年10月1日まで、検索式は前回(2023年版)の式。検索ごとの式・期間・根拠は `platform/data/search_plan.json`(`scripts/build_search_plan.py` が作る)。
17 検索(案 3 件を除く)のうち、前回の式が確認できた 10 検索が「確認済み」、確認できない 7 検索が「未確認」(件数だけを調べ、文献は取得しない)。

```
python3 platform/portal/scripts/run_search.py                    # 全検索の件数(AWS は不要)
python3 platform/portal/scripts/run_search.py --fetch            # 確認済みの検索の文献を取得し、search_results/<実行日>/ に保存(json と csv)
python3 platform/portal/scripts/run_search.py --import <メールアドレス> --searcher <氏名> --dir search_results/<実行日>
```

- 保存する csv は、検索ごとの文献の全件(No、PMID、題名、著者、誌名、年、DOI)。`検索の記録.csv` は、検索ごとの式、件数、取得した文献の数、PubMed が解釈した式。
- 件数(PubMed の検索結果の件数)と取得した文献の数が一致しない検索は、ポータルに登録しない。1 万件を超える検索は、期間を分けて全件を取る。1つの CQ の対象が 8000 件を超える検索は、登録しない(式を確認する)。
- ポータルの「スクリーニング・流れ図」の「別添を出力」(`GET /export/<cq>/screening`)は、検索の記録(件数 = 新たに登録した文献 + 重複 + 差)、流れ図の件数、枠ごとの文献の一覧(PMID・題名・著者)を xlsx にする。件数と一覧は同じ分け方(`classify`)から作る。
- `search_results/` と `literature_pdfs_*/` は `.gitignore` に入れてあり、リポジトリに入らない。

## 自己登録と電子投票(統括委員長の決定 2026-11-22)

- **自己登録**: 委員が Sign up でアカウントを作る(メールの確認コード)→ ログインして氏名・所属を申請 → 統括委員長が「利用申請」で承認(Cognito のグループが付く)→ 委員が再ログイン。承認の前は、API が /me と /access だけを返す(試験: `test_self_registration_and_approval`)。
- **電子投票**: `api/handler.py` の `vote()`。投票の記録(VOTED: 誰が投票したか)と票(BALLOT: 選択だけ。メールアドレス・時刻を持たない)を分けて保存する。API は個別の票を返さない(試験: `test_electronic_vote`)。成立した強さは EtD・推奨に入り、手で変えられない。
- `cdk deploy` で、Cognito の自己登録が有効になる(`self_sign_up_enabled=True`)。
