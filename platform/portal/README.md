# GL作成ポータル(AWS)

がん薬物療法に伴う末梢神経障害診療ガイドライン2028年版の作成を、委員がブラウザで進めるためのポータル。
千葉大学の AWS アカウント(東京リージョン)に置く。Google ドライブ JASCC_GL は、原稿と論文の保管に使い続ける。

## 画面
| 画面 | 内容 | 編集できる人 |
|---|---|---|
| ダッシュボード | 現在の段階、自分のタスク、担当CQ・総論、承認リクエスト、CQごとの進捗、承認ログ | 段階の変更は統括委員会・事務局 |
| メンバー管理 | 企画書の名簿。役割(グループ)、メールアドレス、Cognito への招待 | 統括委員会・事務局 |
| CQ・PICO一覧 | SR項目11・FRQ項目4。8段階(検索〜解説文)の状態、PICO、備考 | 担当委員、SR委員長、統括委員会、事務局 |
| 総論(A〜N) | 企画書の総論18項目。状態(未着手・執筆中・査読中・完了)、期限、原稿URL | 執筆者本人、SR委員長、統括委員会、事務局。担当の変更は統括委員会 |
| SR作業(スクリーニング) | スクリーニング管理シートの JSON の取り込みと、担当者別の進捗。照合用に JSON を返す | 本人の JSON は本人、他人の JSON は SR委員長以上 |
| 推奨決定・原稿執筆 | 様式4-5、様式SR-8・SoF、EtD、解説文の状態 | CQ・PICO一覧と同じ |
| 依頼事項 | 依頼事項の作成、担当、期限、状態 | 作成はSR委員長以上。状態は担当本人 |
| 承認リクエスト | 申請、承認・差戻し | 決定は統括委員会のみ |
| 承認ログ | 全ての変更の追記。更新・削除の操作はない | — |

COI の申告は学会が管理するため、ポータルには置かない。論文 PDF も置かない(PMID と入手状況だけ)。
判断(採否、バイアスリスク、推奨)は委員が行う。ポータルは記録と集計だけを行う。

## 構成(`infra/portal_stack.py`)
Cognito(招待制、メールでログイン、MFA任意、役割のグループ7つ) / DynamoDB 1テーブル(`jascc-gl-portal`、PITR) /
Lambda(Python 3.12、`api/handler.py`)+ API Gateway HTTP API(Cognito JWT 認可) / S3 + CloudFront(`web/`)。
テーブルと利用者プールはスタックを消しても残る。費用は月額およそ数米ドル(利用者30名、1日数百リクエストの想定)。

## 展開
```bash
npm install -g aws-cdk
python3 -m pip install -r platform/portal/infra/requirements.txt
cd platform/portal/infra && cdk deploy --require-approval never --outputs-file ../out/outputs.json
```
出力の `SiteUrl` がポータルの URL。初回は次の2つを行う。
1. 統括委員長の利用者を作り、統括委員会のグループに入れる(招待メールが届く):
   `python3 platform/portal/scripts/admin_user.py <メールアドレス> <氏名>`
2. ポータルにログインし、メンバー管理の下にある「初期データの作成」(`POST /admin/seed`)を実行する。
   または `python3 platform/portal/scripts/admin_user.py --seed <メールアドレス>`。企画書の名簿・CQ・総論が入る。
以後の委員の招待は、メンバー管理の画面から行う(メールアドレスを入れて「招待」)。

## 試験
```bash
python3 -m pip install moto pytest
python3 -m pytest platform/portal/tests -q      # API(moto で DynamoDB を模擬)
```

## 既存ツールとの関係
- スクリーニング管理シート(`core/render_screening.py`)の JSON を、SR作業の画面で取り込む。照合(`core/merge_screening.py`)は、画面から JSON を取り出して Mac で実行する。
- 決定記録(`core/render_meeting.py`)と Minds 書類(`core/export_minds_documents.py`)は、これまでどおり生成し、段階の状態だけをポータルに反映する。
