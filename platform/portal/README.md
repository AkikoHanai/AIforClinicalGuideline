# GL作成ポータル(AWS)

がん薬物療法に伴う末梢神経障害診療ガイドライン2028年版の作成を、CIPN診療ガイドライン2023年版の手順(Minds 2020)のとおりに、委員がブラウザで進めるためのポータル。
千葉大学の AWS アカウント(東京リージョン)に置く。名簿・COI は Google フォーム・ドライブで管理し、ポータルには置かない。
Google ドライブとの受け渡しは統括委員長の Mac を経由する。

## 2つの流れ(独立)
| 流れ | 使う人 | 手順 |
|---|---|---|
| SRの流れ(CQ) | SR委員、SR委員長、作成グループ、統括委員会、事務局 | 論文(PDF登録・本文) → 様式4-5(2名が独立に判定、照合) → 様式SR-8 → EtD・推奨(投票) |
| 総説の流れ(総論A〜N) | 総説執筆者、統括委員会、事務局 | 原稿(Word)をポータルで提出 → 査読中 → 統括委員会の査読コメント → 修正中 → 修正版の提出 → 完了(統括委員会) |
総説執筆者だけの利用者は SR の画面に入れず、SR委員だけの利用者は総説の画面に入れない(API で制限)。委員の操作は全てブラウザで行い、ターミナルは使わない。ターミナルを使うのは、統括委員長の展開とドライブとの受け渡しだけである。

## 画面と、委員が行う判断
| 画面 | 内容 | 判断する人(Minds) |
|---|---|---|
| ダッシュボード | 現在の段階、自分の未提出の様式4-5、担当CQ・総論、CQごとの進捗(入力の完了から自動判定)、作成経過の記録 | — |
| CQ・PICO・アウトカム | SR項目11・FRQ項目4(企画書)。PICO(Pにがん腫・化学療法の種類)、アウトカム(様式4-5・SR-8の単位) | 担当委員、SR委員長 |
| 論文(PDF登録・本文) | 二次スクリーニング採用論文を PMID で登録し、PDF を置く。本文を抽出し、Method・Result の段落に ID を付ける。研究特性(がん腫、化学療法の分類7区分・薬剤名、デザイン、N、介入、対照、評価時点) | 担当委員 |
| 様式4-5 | 左に本文の段落(Method・Result、検索、根拠の段落を強調)と PDF、右に 15 項目の判定(0/-1/-2)・根拠の段落ID・引用。2名が独立に判定し提出(相手の評価は2名が提出するまで見えない)。提出後、照合欄で協議の結果を確定。Claude 下書き(本文の段落だけを根拠に作る。本文がない論文では作らない)は出発点として取り込み、修正して提出する | 担当委員2名(照合)、SR委員長 |
| 様式SR-8 | アウトカムごとに、確定した様式4-5を化学療法の分類で層別して表示。5要因(0/-1/-2)、上昇要因、確実性(A〜D)、層別の結論 | SRチーム |
| EtD・推奨 | 2023年版の体裁。左に 2023年版の記述(推奨文・強さ・確実性・解説の段落ID・投票)、右に 2028年版の案(推奨文は癌腫・レジメンを明記、強さ、確実性、4つの考慮事項と根拠の段落ID、投票の記録、解説) | 作成グループ(投票)、統括委員会(確定) |
| 総論(A〜N) | 企画書の 18 項目。原稿の提出(版ごとに保存)、状態、期限、査読コメント | 執筆者(提出)、統括委員会(査読・完了) |
| スクリーニングの進捗 | スクリーニング管理シートの JSON の取り込みと担当者別の進捗 | — |
| 利用者 | ログイン用の登録と招待(氏名は企画書の表記) | 事務局 |
| Minds書類の出力 | CQ ごとに、記録から xlsx(CQ、研究特性、様式4-5、様式SR-8、SoF表、EtD・推奨、作成経過)を出力。EtD・推奨と様式SR-8 の画面のボタン | — |
| EtD の Claude 下書き | 様式SR-8・確定した様式4-5・2023年版の記述だけを根拠に、推奨文案・4つの考慮事項・解説文案を作る(根拠 ID 付き。強さと確実性は含めない)。作成グループが取り込み、修正・保存 | 作成グループ |
| 総論の 2023年版参照 | 総論の画面で、2023年版の本文(段落 ID 付き)と Word 原文を参照 | — |
| 作成経過の記録 | 全操作の追記。更新・削除の操作はない | — |

規則: 盲検化の2項目は -2 を使わない(統括委員長の決定)。抄録のみの論文では下書きを作らない。判断は委員が行い、AI は本文の段落を根拠とする下書きに限る。

## 構成(`infra/portal_stack.py`)
Cognito(招待制、メール、MFA任意、役割グループ7つ)/ DynamoDB 1テーブル(PITR)/ S3(論文PDFと本文、非公開・暗号化・版管理)/
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
2023年版の記述(CQ)は、`run_jascc.sh first` が作る `etd_2023.json` を `scripts/admin_user.py --gl2023 <json> <メールアドレス>` で取り込む。2023年版の総論は `scripts/import_soron2023.py <メールアドレス>` で取り込む(platform/soron/out の docx から)。

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
OCR の本文は状態「本文抽出済(OCR(Apple Vision))」で区別する。様式4-5 の画面では PDF を並べて表示するので、引用箇所は PDF で確認する。
Method・Result の見出しを判定できない PDF は「本文抽出済(節の見出しを判定できない。全段落を参照)」とし、画面では全段落を表示する。
