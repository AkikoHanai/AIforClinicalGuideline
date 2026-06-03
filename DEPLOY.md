# SR Automation — AWSデプロイ手順

## 前提条件

```bash
# AWS CLIが設定済みであること
aws sts get-caller-identity

# Node.js（CDK要件）
node --version  # v18以上推奨

# CDKのインストール
npm install -g aws-cdk

# Pythonパッケージ
pip install -r infra/requirements.txt
```

---

## Step 1: CDK Bootstrap（初回のみ）

```bash
# AWSアカウントとリージョンを指定してBootstrap
cdk bootstrap aws://$(aws sts get-caller-identity --query Account --output text)/ap-northeast-1 \
  --cloudformation-execution-policies arn:aws:iam::aws:policy/AdministratorAccess
```

---

## Step 2: インフラをデプロイ

```bash
cd infra

# 差分確認（ドライラン）
cdk diff -c account=$(aws sts get-caller-identity --query Account --output text) -c region=ap-northeast-1

# デプロイ実行
cdk deploy -c account=$(aws sts get-caller-identity --query Account --output text) -c region=ap-northeast-1
```

デプロイ完了後、Outputsに以下が表示される:
```
SrAutomationStack.ClusterArn        = arn:aws:ecs:ap-northeast-1:XXXX:cluster/sr-automation
SrAutomationStack.EcrRepoUri        = XXXX.dkr.ecr.ap-northeast-1.amazonaws.com/sr-automation
SrAutomationStack.OutputBucketName  = sr-automation-output-XXXXXXXXXXXX
SrAutomationStack.TaskDefinitionArn = arn:aws:ecs:ap-northeast-1:XXXX:task-definition/sr-automation:1
SrAutomationStack.ContainerName     = sr-pipeline
```

---

## Step 3: APIキーをSecrets Managerに登録

```bash
# Gemini APIキー
aws secretsmanager put-secret-value \
  --secret-id sr-automation/gemini-api-key \
  --secret-string '{"api_key":"YOUR_GEMINI_API_KEY"}'

# Claude APIキー（Claudeを使う場合）
aws secretsmanager put-secret-value \
  --secret-id sr-automation/claude-api-key \
  --secret-string '{"api_key":"YOUR_ANTHROPIC_API_KEY"}'
```

---

## Step 4: DockerイメージをビルドしてECRにプッシュ

```bash
# SRディレクトリに戻る
cd ..

ACCOUNT=$(aws sts get-caller-identity --query Account --output text)
REGION=ap-northeast-1
ECR_URI="${ACCOUNT}.dkr.ecr.${REGION}.amazonaws.com/sr-automation"

# ECRにログイン
aws ecr get-login-password --region $REGION | \
  docker login --username AWS --password-stdin "${ACCOUNT}.dkr.ecr.${REGION}.amazonaws.com"

# ビルド & プッシュ
docker build -t sr-automation .
docker tag sr-automation:latest ${ECR_URI}:latest
docker push ${ECR_URI}:latest
```

---

## Step 5: CLIの設定

```bash
# aws-sr を PATH に追加
chmod +x aws-sr
sudo cp aws-sr /usr/local/bin/aws-sr  # またはPATHの通った場所へ

# CDK Outputsから設定を自動生成
aws-sr config init
```

`~/.aws-sr/config.json` が生成される。

---

## Step 6: ジョブを投入して実行

```bash
# ジョブ投入（例：がんサバイバー × 運動）
aws-sr submit \
  --query '("Neoplasms"[Mesh] OR "Cancer"[TIAB]) AND ("Exercise"[Mesh]) AND ("Survivor"[Mesh]) AND (randomized controlled trial[pt]) AND (English[LA] OR Japanese[LA])' \
  --inclusion "がんサバイバーを対象とした運動介入のRCT" \
  --exclusion "動物実験、プロトコル論文、運動介入なし" \
  --pico-q "がんサバイバーへの運動介入はQOLを改善するか？" \
  --outcomes "QOL, 疲労, 身体機能, 運動耐容能" \
  --model gemini

# → job_id が表示される（例: sr-20260602123456-ab1234）

# ステータス確認
aws-sr status sr-20260602123456-ab1234

# ログをリアルタイム確認
aws-sr logs sr-20260602123456-ab1234 --follow

# 完了後にダウンロード
aws-sr download sr-20260602123456-ab1234 --output-dir ./results

# ジョブ一覧
aws-sr list
```

---

## コスト目安（東京リージョン）

| リソース | 単価 | 月10回実行（〜30分/回）の概算 |
|---|---|---|
| Fargate (0.5vCPU, 1GB) | $0.01234/vCPU時間 + $0.00135/GB時間 | ~$0.15 |
| S3 | $0.025/GB | ~$0.01 |
| CloudWatch Logs | $0.76/GB | ~$0.05 |
| Secrets Manager | $0.40/シークレット/月 | $0.80（2シークレット） |
| ECR | 500MB無料枠内 | $0 |
| **合計** | | **~$1/月** |

---

## イメージ更新時

パイプラインのコードを変更したら：

```bash
docker build -t sr-automation .
docker tag sr-automation:latest ${ECR_URI}:latest
docker push ${ECR_URI}:latest
# ← 次回のジョブ投入から自動的に新イメージが使われる（:latest）
```

---

## トラブルシューティング

**タスクが STOPPED になる場合**
```bash
# ECSタスクの終了理由を確認
aws ecs describe-tasks \
  --cluster sr-automation \
  --tasks <TASK_ARN> \
  --query 'tasks[0].stoppedReason'
```

**ログが見つからない場合**
```bash
# CloudWatch Logsで直接確認
aws logs tail /sr-automation/pipeline --follow
```

**VPCエラー（ネットワーク設定）が出る場合**
```bash
# デフォルトVPCのサブネットIDを確認
aws ec2 describe-subnets \
  --filters "Name=default-for-az,Values=true" \
  --query 'Subnets[].SubnetId'

# ~/.aws-sr/config.json の subnet_ids を更新
```
