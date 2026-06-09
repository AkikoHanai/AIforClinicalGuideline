#!/bin/bash
set -e

ACCOUNT_ID="439112340401"
REGION="ap-northeast-1"

echo "=========================================="
echo "Setting up IAM Roles for ECS"
echo "=========================================="

# ステップ 1: ECS Task Execution Role を作成
echo "📋 Creating ecsTaskExecutionRole..."

cat > /tmp/assume-role-policy.json << 'EOF'
{
  "Version": "2012-10-17",
  "Statement": [
    {
      "Effect": "Allow",
      "Principal": {
        "Service": "ecs-tasks.amazonaws.com"
      },
      "Action": "sts:AssumeRole"
    }
  ]
}
EOF

aws iam create-role \
  --role-name ecsTaskExecutionRole \
  --assume-role-policy-document file:///tmp/assume-role-policy.json \
  --region $REGION || echo "Role already exists"

# ECSタスク実行ポリシーをアタッチ
aws iam attach-role-policy \
  --role-name ecsTaskExecutionRole \
  --policy-arn arn:aws:iam::aws:policy/service-role/AmazonECSTaskExecutionRolePolicy \
  --region $REGION

# CloudWatch Logsへのアクセス権限を追加
aws iam put-role-policy \
  --role-name ecsTaskExecutionRole \
  --policy-name ECSTaskExecutionRolePolicy \
  --policy-document '{
    "Version": "2012-10-17",
    "Statement": [
      {
        "Effect": "Allow",
        "Action": [
          "logs:CreateLogGroup",
          "logs:CreateLogStream",
          "logs:PutLogEvents"
        ],
        "Resource": "*"
      }
    ]
  }' \
  --region $REGION

# ステップ 2: ECS Task Role を作成（Bedrockアクセス用）
echo "📋 Creating ecsTaskRole..."

aws iam create-role \
  --role-name ecsTaskRole \
  --assume-role-policy-document file:///tmp/assume-role-policy.json \
  --region $REGION || echo "Role already exists"

# Bedrock アクセス権限をアタッチ
aws iam put-role-policy \
  --role-name ecsTaskRole \
  --policy-name BedrockAccessPolicy \
  --policy-document '{
    "Version": "2012-10-17",
    "Statement": [
      {
        "Effect": "Allow",
        "Action": [
          "bedrock:InvokeModel",
          "bedrock:InvokeModelWithResponseStream"
        ],
        "Resource": "arn:aws:bedrock:*::foundation-model/*"
      }
    ]
  }' \
  --region $REGION

# S3 アクセス権限を追加（出力保存用）
aws iam put-role-policy \
  --role-name ecsTaskRole \
  --policy-name S3AccessPolicy \
  --policy-document '{
    "Version": "2012-10-17",
    "Statement": [
      {
        "Effect": "Allow",
        "Action": [
          "s3:PutObject",
          "s3:GetObject"
        ],
        "Resource": "arn:aws:s3:::sr-pipeline-output/*"
      }
    ]
  }' \
  --region $REGION

# ECR アクセス権限を追加
aws iam put-role-policy \
  --role-name ecsTaskRole \
  --policy-name ECRAccessPolicy \
  --policy-document '{
    "Version": "2012-10-17",
    "Statement": [
      {
        "Effect": "Allow",
        "Action": [
          "ecr:GetAuthorizationToken",
          "ecr:BatchGetImage",
          "ecr:GetDownloadUrlForLayer"
        ],
        "Resource": "*"
      }
    ]
  }' \
  --region $REGION

echo "✅ IAM roles created successfully!"
echo ""
echo "ecsTaskExecutionRole ARN: arn:aws:iam::$ACCOUNT_ID:role/ecsTaskExecutionRole"
echo "ecsTaskRole ARN: arn:aws:iam::$ACCOUNT_ID:role/ecsTaskRole"
