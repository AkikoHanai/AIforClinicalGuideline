# MacBook移行手順

この手順は、AIforClinicalGuidelineを別のMacへ再現可能かつ安全に移すためのものです。コード、共有資料、秘密情報を分けて扱います。

## 移行対象

| 対象 | 移行方法 | Gitへ保存 |
|---|---|---|
| プログラム、テスト、設定例 | GitHub | 可 |
| Minds帳票、検索結果、委員資料 | Google Drive共有ドライブ | 不可 |
| ローカルのレビュー基盤 | AirDropまたは暗号化外部ドライブ | 不可 |
| APIキー、AWS認証情報 | MacBook側で再設定 | 不可 |
| `.venv`、キャッシュ、生成ログ | 移行せず再生成 | 不可 |

## 1. 旧Macで行うこと

未送信のコード変更がある場合だけ、内容を確認してGitHubへcommit/pushします。`.env`、論文PDF、検索結果、委員資料はcommitしません。

ローカルのレビュー基盤を運ぶ必要がある場合は、転送用アーカイブを作ります。

```bash
./scripts/package_local_workspace.sh \
  --source "/path/to/local/platform" \
  --output "$HOME/Desktop/cipn-platform.migration.tar.gz"
```

`data/` と `review/` も含める場合だけ `--include-data` を加えます。作成物は暗号化されていないため、一般のクラウドストレージへ置かず、AirDropまたは暗号化外部ドライブを使います。

表示されたSHA-256値を控えます。MacBookでは次のように検証して展開します。

```bash
./scripts/import_local_workspace.sh \
  --archive "$HOME/Downloads/cipn-platform.migration.tar.gz" \
  --destination "$HOME/Documents" \
  --sha256 "<旧Macで表示されたSHA-256>"
```

## 2. MacBookで準備すること

1. macOSを更新する。
2. Google Drive for desktopを導入し、共有ドライブが同期されたことを確認する。
3. TerminalでCommand Line Toolsを導入する。

```bash
xcode-select --install
```

4. Python 3.11をHomebrewまたはpython.orgから導入する。既にPython 3.10以上があればそのまま利用できます。
5. AWS機能を使う場合だけAWS CLIを導入する。

## 3. コードを取得してセットアップする

```bash
git clone https://github.com/AkikoHanai/AIforClinicalGuideline.git
cd AIforClinicalGuideline
./scripts/setup_mac.sh --dev
```

セットアップは次を行います。

- `.venv`を新規作成
- Python依存関係をインストール
- `.env.example`から`.env`を新規作成（既存ファイルは上書きしない）
- `config/paths.example.env`から`config/paths.local.env`を新規作成（既存ファイルは上書きしない）

## 4. MacBook固有の設定を入力する

`.env`には利用するサービスの値だけを入力します。値を画面共有、メール、GitHub issueへ貼り付けないでください。

`config/paths.local.env`にはMacBook上で確認した実在パスを入力します。

```bash
GL_GOOGLE_DRIVE_ROOT="/Users/<name>/Library/CloudStorage/<GoogleDrive>/共有ドライブ/CIPNガイドライン作成/新規ガイドライン作成"
GL_LOCAL_WORKSPACE="/Users/<name>/Documents/CIPN-workspace"
GL_OUTPUT_ROOT="./sr_output"
```

ユーザー名やGoogle Driveのフォルダ名を推測せず、Finderから確認してください。

## 5. 認証を再設定する

AWSを使う場合は、組織で定めたSSOまたはプロファイル方式で設定します。長期アクセスキーをリポジトリへ保存しません。

```bash
aws configure sso
aws sso login --profile <profile-name>
```

`.env`の`AWS_PROFILE`を同じプロファイル名にします。Claude Direct APIを使う場合だけ`ANTHROPIC_API_KEY`をMacBookの`.env`へ設定します。

## 6. 診断とテスト

オフライン診断:

```bash
./scripts/doctor_mac.sh
```

AWS認証も確認:

```bash
./scripts/doctor_mac.sh --online
```

テストも実行:

```bash
./scripts/doctor_mac.sh --tests
```

`FAIL`が0件になるまで設定を修正します。APIキーを利用しない構成やAWSを使わない構成の警告は、その機能を使わなければ許容できます。

## 7. 動作確認の順序

本番データを使う前に、次の順で確認します。

1. サンプルまたは匿名化データで検索処理
2. スクリーニング処理
3. データ抽出とMindsテーブル生成
4. RAG検索
5. 推奨文の生成（利用する場合）
6. 委員レビュー画面

旧MacとMacBookで同一入力を使い、採用件数、除外件数、効果量、確実性、引用文献IDが一致することを確認します。

## 移行完了チェックリスト

- [ ] GitHubからコードを取得できた
- [ ] Google Drive共有ドライブを開ける
- [ ] Python 3.10以上と`.venv`を確認した
- [ ] `pip install`が完了した
- [ ] `.env`がGit管理外である
- [ ] ローカルパス設定が実在する
- [ ] 必要なAPI／AWS認証を再設定した
- [ ] `doctor_mac.sh`のFAILが0件
- [ ] テストが通る
- [ ] 匿名化データによる一連の動作確認が完了した
- [ ] 旧Macと主要結果が一致した

## トラブル時

- Pythonが古い: Python 3.11を導入し、`./scripts/setup_mac.sh --python /path/to/python3.11 --dev`を実行する。
- Google Driveが見つからない: Drive for desktopの同期完了後、Finderでパスを確認して`paths.local.env`を直す。
- AWS認証エラー: `aws sso login --profile ...`を再実行し、`AWS_PROFILE`を確認する。
- Apple Siliconで依存関係に失敗: TerminalがRosettaで起動していないか確認し、arm64版Pythonで`.venv`を作り直す。
- APIキー未設定: 推奨文生成だけが必要か確認し、必要な場合のみ`.env`へ設定する。
