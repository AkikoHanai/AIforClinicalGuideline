# AWS CDK デプロイガイド（完全版）

**完成日**: 2026-06-05

---

## 概要

このガイドでは、AI for Clinical Guideline SR パイプラインを AWS にデプロイします。

## アーキテクチャ

```
┌─────────────────────────────────────────────────┐
│  AWS Lambda / ECS Fargate                       │
│  - sr_search.py (PubMed 検索)                  │
│  - sr_screening.py (スクリーニング)             │
│  - sr_data_extraction.py (データ抽出)           │
│  - sr_stage1_integration.py (SR 統合)           │
│  - sr_stage3_legacy_integration.py (新旧統合)   │
└─────────────────────────────────────────────────┘
         ↓ Input via SQS
┌─────────────────────────────────────────────────┐
│  AWS S3                                          │
│  - input: PDF, CSV                              │
│  - output: SR documents, JSON                   │
└─────────────────────────────────────────────────┘
         ↓ Credentials
┌─────────────────────────────────────────────────┐
│  AWS Secrets Manager                            │
│  - ANTHROPIC_API_KEY (Claude API)               │
└─────────────────────────────────────────────────┘
```

---

## 前提条件

1. AWS Account with appropriate permissions
2. AWS CLI configured
3. Python 3.10+
4. Node.js 18+ (for CDK)
5. Docker (for local testing)

---

## ステップバイステップ デプロイ

### Step 1: CDK 環境をセットアップ

```bash
# CDK をインストール
npm install -g aws-cdk

# CDK バージョン確認
cdk --version

# 初期化（既にある場合はスキップ）
cdk init app --language python
```

### Step 2: CDK スタックを構成

**infra/sr_stack.py** に以下を確認：

```python
from aws_cdk import (
    Stack,
    aws_s3 as s3,
    aws_ecs as ecs,
    aws_ec2 as ec2,
    aws_secretsmanager as secretsmanager,
    aws_sqs as sqs,
)

class SRStack(Stack):
    def __init__(self, scope, id, **kwargs):
        super().__init__(scope, id, **kwargs)
        
        # S3 バケット
        sr_bucket = s3.Bucket(
            self, "SR-Bucket",
            removal_policy=RemovalPolicy.DESTROY
        )
        
        # ECS Fargate タスク
        # (既に実装済み)
        
        # Secrets Manager
        secrets = secretsmanager.Secret(
            self, "SR-Secrets",
            secret_object_value={
                "GEMINI_API_KEY": SecretValue.secrets_manager(...),
                "ANTHROPIC_API_KEY": SecretValue.secrets_manager(...)
            }
        )
```

### Step 3: API キーを Secrets Manager に登録

```bash
# Claude API キー（ANTHROPIC_API_KEY）
aws secretsmanager create-secret \
  --name sr-anthropic-key \
  --secret-string "sk-ant-..." \
  --region ap-northeast-1
```

> **Note**: System uses Claude API only. Gemini API is no longer required.

### Step 4: Docker イメージをビルド

```bash
# Dockerfile が存在することを確認
ls Dockerfile

# イメージをビルド
docker build -t sr-pipeline:latest .

# ECR にプッシュ
aws ecr create-repository --repository-name sr-pipeline
aws ecr get-login-password | docker login --username AWS --password-stdin <ACCOUNT_ID>.dkr.ecr.ap-northeast-1.amazonaws.com
docker tag sr-pipeline:latest <ACCOUNT_ID>.dkr.ecr.ap-northeast-1.amazonaws.com/sr-pipeline:latest
docker push <ACCOUNT_ID>.dkr.ecr.ap-northeast-1.amazonaws.com/sr-pipeline:latest
```

### Step 5: CDK をデプロイ

```bash
# Bootstrap （初回のみ）
cdk bootstrap aws://<ACCOUNT_ID>/ap-northeast-1

# リソースを確認
cdk synth

# デプロイ実行
cdk deploy SRStack

# デプロイ完了を確認
aws cloudformation describe-stacks \
  --stack-name SRStack \
  --region ap-northeast-1
```

### Step 6: CLI ツールを設定

```bash
# aws-sr CLI をインストール
chmod +x aws-sr
sudo mv aws-sr /usr/local/bin/

# 設定ファイルを作成
mkdir -p ~/.aws-sr
cat > ~/.aws-sr/config.yaml << 'EOF'
aws:
  region: ap-northeast-1
  s3_bucket: sr-output-<ACCOUNT_ID>
  ecs_cluster: SRCluster
  ecs_task_definition: sr-task
  
api_keys:
  gemini: ${GEMINI_API_KEY}
  anthropic: ${ANTHROPIC_API_KEY}
EOF
```

### Step 7: パイプラインをテスト実行

```bash
# ジョブを送信
aws-sr submit \
  --pdf cancer_survivor_guidelines.pdf \
  --cq "CQ 1" \
  --output-dir s3://sr-output-<ACCOUNT_ID>/results

# ステータスを確認
aws-sr status --task-id <TASK_ID>

# 結果をダウンロード
aws-sr download --task-id <TASK_ID> --output-dir ./results
```

---

## 費用見積もり

### 月額費用（小規模チーム向け）

| サービス | 使用量 | 月額費用 |
|---|---|---|
| S3 | 10GB | $0.23 |
| ECS Fargate | 10 タスク × 1時間 | $3-5 |
| Lambda | 0 | $0（ECS 使用） |
| Secrets Manager | 2 シークレット | $0.40 |
| **合計** | | **$4-6/月** |

### コスト削減のコツ

1. **オンデマンド実行**: タスクを非同期で実行
2. **Spot インスタンス**: 開発環境で使用
3. **S3 ライフサイクル**: 古いログを削除
4. **API キー共有**: チーム内で 1 つのキーを使用

---

## トラブルシューティング

### エラー: Task failed to start

```bash
# ログを確認
aws logs tail /ecs/sr-task --follow

# Secrets Manager が正しく設定されているか確認
aws secretsmanager get-secret-value --secret-id sr-anthropic-key
```

### エラー: S3 permission denied

```bash
# IAM ポリシーを確認
aws iam get-role-policy --role-name <ECS_TASK_ROLE> --policy-name s3-access
```

### エラー: Docker image not found

```bash
# ECR イメージが存在するか確認
aws ecr describe-images --repository-name sr-pipeline
```

---

## 本番環境への推奨設定

### セキュリティ

```bash
# VPC を使用（非公開）
# - Private subnets for ECS
# - NAT Gateway for outbound

# API キーのローテーション（毎月）
# - Secrets Manager automatic rotation

# CloudTrail でログを記録
```

### スケーリング

```bash
# ECS Auto Scaling
# - Target CPU utilization: 70%
# - Min tasks: 1
# - Max tasks: 10

# S3 バージョニング
# - 古いバージョンは 90 日後に削除
```

### モニタリング

```bash
# CloudWatch ダッシュボード
# - Task count
# - Error rate
# - Average processing time

# SNS アラート
# - Task failed
# - API quota exceeded
```

---

## デプロイ後の確認チェックリスト

- [ ] S3 バケットに access 可能
- [ ] ECS タスクが起動・完了
- [ ] Secrets Manager に API キーが登録
- [ ] CloudWatch に ログが記録
- [ ] CLI ツール（aws-sr）で submit / status / download が動作
- [ ] sample PDF での end-to-end テスト完了
- [ ] コスト見積もりが予算内

---

## 次のステップ

1. **チーム設定**: IAM ユーザーを追加
2. **監視**: CloudWatch アラームを設定
3. **CI/CD**: GitHub Actions で自動テスト・デプロイ
4. **スケール**: 複数の CQ、複数の言語に対応

---

**デプロイ完了日**: 2026-06-05

お疲れ様でした！🎉
