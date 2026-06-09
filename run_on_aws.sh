#!/bin/bash
set -e

# AWS設定
ACCOUNT_ID="439112340401"
REGION="ap-northeast-1"
REPO_NAME="sr-pipeline"
CLUSTER_NAME="sr-cluster"
SERVICE_NAME="sr-service"

echo "=========================================="
echo "AWS上でSRパイプラインを実行"
echo "=========================================="

# ステップ 1: CloudWatch Logs グループを作成
echo "📝 Creating CloudWatch Logs group..."
aws logs create-log-group \
  --log-group-name /ecs/sr-pipeline \
  --region $REGION 2>/dev/null || true

aws logs put-retention-policy \
  --log-group-name /ecs/sr-pipeline \
  --retention-in-days 7 \
  --region $REGION 2>/dev/null || true

# ステップ 2: ECSクラスタを作成
echo "🔧 Creating ECS cluster..."
aws ecs create-cluster \
  --cluster-name $CLUSTER_NAME \
  --region $REGION 2>/dev/null || true

# ステップ 3: ECSタスク定義を登録（JSONファイルから）
echo "📋 Registering ECS task definition..."

cat > /tmp/task-definition.json << 'EOF'
{
  "family": "sr-pipeline",
  "networkMode": "awsvpc",
  "requiresCompatibilities": ["FARGATE"],
  "cpu": "1024",
  "memory": "2048",
  "executionRoleArn": "arn:aws:iam::439112340401:role/ecsTaskExecutionRole",
  "taskRoleArn": "arn:aws:iam::439112340401:role/ecsTaskRole",
  "containerDefinitions": [
    {
      "name": "sr-pipeline",
      "image": "439112340401.dkr.ecr.ap-northeast-1.amazonaws.com/sr-pipeline:latest",
      "essential": true,
      "environment": [
        {
          "name": "QUERY",
          "value": "(\"Cancer Survivors\"[MeSH]) AND (\"Exercise\"[MeSH] OR \"Physical Activity\"[MeSH])"
        },
        {
          "name": "INCLUSION",
          "value": "Adult cancer survivors, exercise-based interventions, RCT or cohort studies"
        },
        {
          "name": "EXCLUSION",
          "value": "Animal studies, pediatric, non-English"
        },
        {
          "name": "OUTCOMES",
          "value": "Quality of Life, Fatigue, Physical Function"
        },
        {
          "name": "OUTPUT_DIR",
          "value": "/output/cancer_exercise"
        }
      ],
      "logConfiguration": {
        "logDriver": "awslogs",
        "options": {
          "awslogs-group": "/ecs/sr-pipeline",
          "awslogs-region": "ap-northeast-1",
          "awslogs-stream-prefix": "ecs"
        }
      }
    }
  ]
}
EOF

aws ecs register-task-definition \
  --cli-input-json file:///tmp/task-definition.json \
  --region $REGION

# ステップ 4: VPC/Subnet情報を取得
echo "🌐 Getting VPC information..."
VPC_ID=$(aws ec2 describe-vpcs \
  --filters "Name=is-default,Values=true" \
  --query "Vpcs[0].VpcId" \
  --output text \
  --region $REGION)

SUBNET=$(aws ec2 describe-subnets \
  --filters "Name=vpc-id,Values=$VPC_ID" \
  --query "Subnets[0].SubnetId" \
  --output text \
  --region $REGION)

SG=$(aws ec2 describe-security-groups \
  --filters "Name=vpc-id,Values=$VPC_ID" "Name=group-name,Values=default" \
  --query "SecurityGroups[0].GroupId" \
  --output text \
  --region $REGION)

echo "VPC: $VPC_ID"
echo "Subnet: $SUBNET"
echo "SecurityGroup: $SG"

# ステップ 5: ECSタスクを実行
echo "🚀 Running ECS task..."
TASK_ARN=$(aws ecs run-task \
  --cluster $CLUSTER_NAME \
  --task-definition sr-pipeline \
  --launch-type FARGATE \
  --network-configuration "awsvpcConfiguration={subnets=[$SUBNET],securityGroups=[$SG],assignPublicIp=ENABLED}" \
  --query "tasks[0].taskArn" \
  --output text \
  --region $REGION)

echo "✅ Task started!"
echo "Task ARN: $TASK_ARN"

# ステップ 6: ログを表示
echo ""
echo "📊 Waiting for task to complete..."
echo "Real-time logs: aws logs tail /ecs/sr-pipeline --follow --region $REGION"
echo ""

# タスク完了を待機
aws ecs wait tasks-stopped \
  --cluster $CLUSTER_NAME \
  --tasks $TASK_ARN \
  --region $REGION

# 最終ステータスを確認
TASK_STATUS=$(aws ecs describe-tasks \
  --cluster $CLUSTER_NAME \
  --tasks $TASK_ARN \
  --query "tasks[0].lastStatus" \
  --output text \
  --region $REGION)

EXIT_CODE=$(aws ecs describe-tasks \
  --cluster $CLUSTER_NAME \
  --tasks $TASK_ARN \
  --query "tasks[0].containers[0].exitCode" \
  --output text \
  --region $REGION)

echo ""
echo "=========================================="
echo "✅ Task完了"
echo "=========================================="
echo "Status: $TASK_STATUS"
echo "Exit Code: $EXIT_CODE"
echo ""
echo "📊 ログを確認:"
echo "  aws logs tail /ecs/sr-pipeline --region $REGION"
