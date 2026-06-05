# AWS CDK デプロイ - ステップバイステップガイド

**完成日**: 2026-06-05

---

## 【前提条件】

以下がインストール済みであることを確認してください：

```bash
# AWS CLI
aws --version
# → AWS CLI 2.x.x

# Node.js + npm
node --version
npm --version

# CDK
cdk --version
# → 2.x.x

# Docker
docker --version
# → Docker version x.x.x

# Python
python --version
# → Python 3.10+
```

インストールが必要な場合：

```bash
# Mac
brew install awscli node docker

# Linux (Ubuntu)
sudo apt-get install awscli nodejs npm docker.io

# CDK（全プラットフォーム）
npm install -g aws-cdk
```

---

## 【ステップ 1】AWS アカウント設定

### 1-1. AWS Account を作成（初回のみ）

[AWS Management Console](https://console.aws.amazon.com) にアクセス

### 1-2. IAM ユーザーを作成

```bash
# AWS Management Console > IAM > Users > Create User
# ユーザー名: sr-deployment
# アクセスキータイプ: Access Key
```

### 1-3. AWS CLI を設定

```bash
aws configure

# 対話形式で以下を入力：
# AWS Access Key ID: <作成したアクセスキー>
# AWS Secret Access Key: <シークレットキー>
# Default region name: ap-northeast-1
# Default output format: json

# 確認
aws sts get-caller-identity
# → "Account": "123456789012" が表示されたら OK
```

---

## 【ステップ 2】リポジトリを準備

```bash
# リポジトリをクローン
git clone https://github.com/AkikoHanai/AIforClinicalGuideline.git
cd AIforClinicalGuideline

# 依存パッケージをインストール
pip install -r requirements.txt

# CDK 依存パッケージをインストール
cd infra
pip install -r requirements.txt
cd ..
```

---

## 【ステップ 3】ECR（Docker Registry）を準備

### 3-1. ECR リポジトリを作成

```bash
# リポジトリ名
REPO_NAME="sr-pipeline"
ACCOUNT_ID=$(aws sts get-caller-identity --query Account --output text)
REGION="ap-northeast-1"

# リポジトリを作成
aws ecr create-repository \
  --repository-name $REPO_NAME \
  --region $REGION

# 出力例:
# "repositoryUri": "123456789012.dkr.ecr.ap-northeast-1.amazonaws.com/sr-pipeline"
```

### 3-2. Docker イメージをビルド

```bash
# Dockerfile の確認
ls -la Dockerfile

# イメージをビルド（時間がかかります：5-10分）
docker build -t sr-pipeline:latest .

# 確認
docker images | grep sr-pipeline
```

### 3-3. Docker イメージを ECR にプッシュ

```bash
# ECR にログイン
aws ecr get-login-password --region $REGION | \
  docker login --username AWS --password-stdin \
  $ACCOUNT_ID.dkr.ecr.$REGION.amazonaws.com

# イメージにタグを付与
docker tag sr-pipeline:latest \
  $ACCOUNT_ID.dkr.ecr.$REGION.amazonaws.com/sr-pipeline:latest

# ECR にプッシュ（時間がかかります：2-5分）
docker push $ACCOUNT_ID.dkr.ecr.$REGION.amazonaws.com/sr-pipeline:latest

# 確認
aws ecr describe-images \
  --repository-name sr-pipeline \
  --region $REGION
```

---

## 【ステップ 4】API キーを AWS Secrets Manager に登録

### 4-1. Gemini API キーを登録

```bash
# キーを取得: https://ai.google.dev/tutorials/setup

aws secretsmanager create-secret \
  --name sr/gemini-api-key \
  --secret-string "sk-..." \
  --region ap-northeast-1

# 確認
aws secretsmanager get-secret-value \
  --secret-id sr/gemini-api-key \
  --region ap-northeast-1
```

### 4-2. Claude API キーを登録

```bash
# キーを取得: https://console.anthropic.com

aws secretsmanager create-secret \
  --name sr/anthropic-api-key \
  --secret-string "sk-ant-..." \
  --region ap-northeast-1

# 確認
aws secretsmanager get-secret-value \
  --secret-id sr/anthropic-api-key \
  --region ap-northeast-1
```

---

## 【ステップ 5】CDK スタックをデプロイ

### 5-1. Bootstrap（初回のみ）

```bash
# CDK bootstrap（CloudFormation スタック用テンプレートを作成）
cdk bootstrap aws://$ACCOUNT_ID/ap-northeast-1

# 出力例:
# ✓ Success! Resources have been deployed.
```

### 5-2. CloudFormation テンプレートを生成

```bash
# CDK から CloudFormation JSON を生成
cdk synth

# 出力例:
# Successfully synthesized to /path/to/cdk.out
```

### 5-3. スタックをデプロイ

```bash
# リソースの変更を確認（オプション）
cdk diff

# デプロイを実行（確認が出たら "y" を入力）
cdk deploy SRStack

# 出力例:
# SRStack: deploying...
# SRStack: creating CloudFormation changeset...
# ✓ SRStack
# Outputs:
# SRStack.SRBucketName = sr-output-xxxxx
```

**デプロイに時間がかかります（5-15分）** ⏳

---

## 【ステップ 6】出力を確認

```bash
# CloudFormation スタックの詳細を確認
aws cloudformation describe-stacks \
  --stack-name SRStack \
  --region ap-northeast-1

# S3 バケット名を確認
S3_BUCKET=$(aws cloudformation describe-stacks \
  --stack-name SRStack \
  --query 'Stacks[0].Outputs[?OutputKey==`SRBucketName`].OutputValue' \
  --output text \
  --region ap-northeast-1)

echo "S3 Bucket: $S3_BUCKET"

# ECS クラスターを確認
aws ecs list-clusters --region ap-northeast-1
```

---

## 【ステップ 7】テストジョブを投入

### 7-1. テスト用 PDF をアップロード

```bash
# S3 にテスト PDF をアップロード
aws s3 cp cancer_survivor_guidelines.pdf \
  s3://$S3_BUCKET/input/ \
  --region ap-northeast-1

# 確認
aws s3 ls s3://$S3_BUCKET/input/ --region ap-northeast-1
```

### 7-2. ECS タスクを実行

```bash
# ECS クラスター名を取得
CLUSTER_NAME=$(aws cloudformation describe-stacks \
  --stack-name SRStack \
  --query 'Stacks[0].Outputs[?OutputKey==`ECSClusterName`].OutputValue' \
  --output text \
  --region ap-northeast-1)

# タスク定義を取得
TASK_DEFINITION=$(aws ecs list-task-definitions \
  --family-prefix sr-task \
  --region ap-northeast-1 \
  --query 'taskDefinitionArns[0]' \
  --output text)

# タスクを実行
aws ecs run-task \
  --cluster $CLUSTER_NAME \
  --task-definition $TASK_DEFINITION \
  --launch-type FARGATE \
  --network-configuration "awsvpcConfiguration={subnets=[subnet-xxxxx],assignPublicIp=ENABLED}" \
  --region ap-northeast-1 \
  --overrides "{\"containerOverrides\": [{\"name\": \"sr-container\", \"environment\": [{\"name\": \"INPUT_PDF\", \"value\": \"cancer_survivor_guidelines.pdf\"}, {\"name\": \"CQ\", \"value\": \"CQ 1\"}]}]}"

# 出力例:
# "taskArn": "arn:aws:ecs:ap-northeast-1:123456789012:task/SRCluster/xxxxx"
```

### 7-3. タスクのログを確認

```bash
# タスク ID を取得
TASK_ID="xxxxx"  # 上記の taskArn から最後の部分

# CloudWatch Logs でログを確認
aws logs tail /ecs/sr-task --follow --region ap-northeast-1

# または Management Console で確認
# CloudWatch > Logs > /ecs/sr-task
```

### 7-4. 結果を確認

```bash
# S3 の出力ディレクトリを確認
aws s3 ls s3://$S3_BUCKET/output/ --region ap-northeast-1 --recursive

# 結果をダウンロード
aws s3 cp s3://$S3_BUCKET/output/ ./results --recursive --region ap-northeast-1

# ファイルを確認
ls -la results/
```

---

## 【ステップ 8】本番運用設定

### 8-1. Auto Scaling を設定

```bash
# Application Auto Scaling を設定（オプション）
# ECS Service の desired count を自動調整
```

### 8-2. CloudWatch アラームを設定

```bash
# タスク失敗時にアラーム
aws cloudwatch put-metric-alarm \
  --alarm-name sr-task-failed \
  --alarm-description "SR task execution failed" \
  --metric-name TasksFailed \
  --namespace AWS/ECS \
  --statistic Sum \
  --period 300 \
  --threshold 1 \
  --comparison-operator GreaterThanOrEqualToThreshold \
  --region ap-northeast-1
```

### 8-3. IAM ユーザーを追加（チーム用）

```bash
# 新しい IAM ユーザーを作成
aws iam create-user --user-name sr-team-member

# S3 への権限を付与
aws iam put-user-policy \
  --user-name sr-team-member \
  --policy-name sr-s3-access \
  --policy-document file://s3-policy.json
```

---

## 【トラブルシューティング】

### エラー: AccessDenied

```bash
# IAM ポリシーを確認
aws iam get-user-policy --user-name sr-deployment --policy-name ...

# または Management Console で IAM > Users > permissions を確認
```

### エラー: ECR イメージが見つからない

```bash
# ECR にイメージがあるか確認
aws ecr describe-images \
  --repository-name sr-pipeline \
  --region ap-northeast-1
```

### エラー: ECS タスクが起動しない

```bash
# CloudWatch ログを確認
aws logs describe-log-streams \
  --log-group-name /ecs/sr-task \
  --region ap-northeast-1
```

---

## 【費用確認】

```bash
# AWS Billing Dashboard で確認
# https://console.aws.amazon.com/billing

# または CLI で確認
aws ce get-cost-and-usage \
  --time-period Start=2026-06-01,End=2026-06-30 \
  --granularity MONTHLY \
  --metrics "UnblendedCost" \
  --region ap-northeast-1
```

---

## 【クリーンアップ（不要になった場合）】

```bash
# スタックを削除
cdk destroy SRStack

# S3 バケットを削除（内容も消去）
aws s3 rb s3://$S3_BUCKET --force

# ECR リポジトリを削除
aws ecr delete-repository \
  --repository-name sr-pipeline \
  --force \
  --region ap-northeast-1

# IAM ユーザーを削除
aws iam delete-user --user-name sr-deployment
```

---

## 【完了チェックリスト】

- [ ] AWS CLI がインストール・設定完了
- [ ] CDK がインストール完了
- [ ] Docker がインストール完了
- [ ] IAM ユーザーを作成
- [ ] API キーを Secrets Manager に登録
- [ ] ECR イメージをプッシュ完了
- [ ] CDK bootstrap 実行完了
- [ ] CDK deploy 実行完了
- [ ] テストジョブで ECS タスク実行成功
- [ ] S3 出力フォルダに結果が表示される

---

## 【次のステップ】

1. AWS Management Console で CloudWatch ダッシュボードを作成
2. チーム用 IAM ユーザーを追加
3. GitHub Actions で自動デプロイを設定
4. 本番運用マニュアルを作成

---

**デプロイ成功時の出力イメージ**

```
Outputs:
SRStack.SRBucketName = sr-output-123456789012
SRStack.ECSClusterName = SRCluster
SRStack.ECRRepositoryUri = 123456789012.dkr.ecr.ap-northeast-1.amazonaws.com/sr-pipeline

✅ デプロイ完了！
AWS Management Console で確認してください：
https://ap-northeast-1.console.aws.amazon.com/cloudformation
```
