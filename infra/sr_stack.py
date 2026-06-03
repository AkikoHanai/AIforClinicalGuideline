"""
sr_stack.py — SR Automation AWS CDK Stack

リソース:
  - S3 バケット（ジョブ出力）
  - ECR リポジトリ（Dockerイメージ）
  - ECS Fargate クラスター + タスク定義
  - Secrets Manager シークレット（API キー）
  - CloudWatch ロググループ
  - IAM ロール（タスク実行 / タスク）
"""

import aws_cdk as cdk
from aws_cdk import (
    Duration,
    RemovalPolicy,
    Stack,
)
from aws_cdk import aws_ecr as ecr
from aws_cdk import aws_ecs as ecs
from aws_cdk import aws_iam as iam
from aws_cdk import aws_logs as logs
from aws_cdk import aws_s3 as s3
from aws_cdk import aws_secretsmanager as secretsmanager
from constructs import Construct


class SrStack(Stack):
    def __init__(self, scope: Construct, construct_id: str, **kwargs):
        super().__init__(scope, construct_id, **kwargs)

        # ------------------------------------------------------------------ #
        # S3 バケット（ジョブ出力）
        # ------------------------------------------------------------------ #
        self.output_bucket = s3.Bucket(
            self,
            "SrOutputBucket",
            bucket_name=f"sr-automation-output-{self.account}",
            versioned=False,
            removal_policy=RemovalPolicy.RETAIN,  # 誤削除防止
            lifecycle_rules=[
                # 古いジョブの出力を90日後に自動削除
                s3.LifecycleRule(
                    id="ExpireOldJobs",
                    expiration=Duration.days(90),
                    prefix="jobs/",
                )
            ],
            block_public_access=s3.BlockPublicAccess.BLOCK_ALL,
            encryption=s3.BucketEncryption.S3_MANAGED,
        )
        cdk.CfnOutput(self, "OutputBucketName", value=self.output_bucket.bucket_name)

        # ------------------------------------------------------------------ #
        # ECR リポジトリ
        # ------------------------------------------------------------------ #
        self.ecr_repo = ecr.Repository(
            self,
            "SrEcrRepo",
            repository_name="sr-automation",
            removal_policy=RemovalPolicy.RETAIN,
            lifecycle_rules=[
                # 最新5イメージのみ保持
                ecr.LifecycleRule(
                    max_image_count=5,
                    rule_priority=1,
                    description="Keep latest 5 images",
                )
            ],
        )
        cdk.CfnOutput(self, "EcrRepoUri", value=self.ecr_repo.repository_uri)

        # ------------------------------------------------------------------ #
        # Secrets Manager（API キー）
        # ------------------------------------------------------------------ #
        # 初期値は空文字列。デプロイ後に手動で値をセットする。
        # aws secretsmanager put-secret-value --secret-id SrGeminiApiKey --secret-string '{"api_key":"YOUR_KEY"}'
        self.gemini_secret = secretsmanager.Secret(
            self,
            "SrGeminiApiKey",
            secret_name="sr-automation/gemini-api-key",
            description="Gemini API Key for SR automation pipeline",
            secret_object_value={
                "api_key": cdk.SecretValue.unsafe_plain_text("REPLACE_ME"),
            },
        )
        self.claude_secret = secretsmanager.Secret(
            self,
            "SrClaudeApiKey",
            secret_name="sr-automation/claude-api-key",
            description="Anthropic Claude API Key for SR automation pipeline",
            secret_object_value={
                "api_key": cdk.SecretValue.unsafe_plain_text("REPLACE_ME"),
            },
        )

        # ------------------------------------------------------------------ #
        # CloudWatch ロググループ
        # ------------------------------------------------------------------ #
        self.log_group = logs.LogGroup(
            self,
            "SrLogGroup",
            log_group_name="/sr-automation/pipeline",
            retention=logs.RetentionDays.THREE_MONTHS,
            removal_policy=RemovalPolicy.DESTROY,
        )

        # ------------------------------------------------------------------ #
        # ECS クラスター（Fargate）
        # ------------------------------------------------------------------ #
        self.cluster = ecs.Cluster(
            self,
            "SrCluster",
            cluster_name="sr-automation",
            enable_fargate_capacity_providers=True,
        )

        # タスク実行ロール（ECSがイメージ pull・ログ送信するための権限）
        task_execution_role = iam.Role(
            self,
            "SrTaskExecutionRole",
            assumed_by=iam.ServicePrincipal("ecs-tasks.amazonaws.com"),
            managed_policies=[
                iam.ManagedPolicy.from_aws_managed_policy_name(
                    "service-role/AmazonECSTaskExecutionRolePolicy"
                )
            ],
        )
        # シークレットの読み取り権限を追加（タスク定義でsecretとして注入するため）
        self.gemini_secret.grant_read(task_execution_role)
        self.claude_secret.grant_read(task_execution_role)

        # タスクロール（コンテナが実行中にS3へ書き込む権限）
        task_role = iam.Role(
            self,
            "SrTaskRole",
            assumed_by=iam.ServicePrincipal("ecs-tasks.amazonaws.com"),
        )
        self.output_bucket.grant_read_write(task_role)

        # ------------------------------------------------------------------ #
        # Fargate タスク定義
        # ------------------------------------------------------------------ #
        self.task_definition = ecs.FargateTaskDefinition(
            self,
            "SrTaskDef",
            family="sr-automation",
            cpu=512,        # 0.5 vCPU（大量スクリーニング時は1024に増やす）
            memory_limit_mib=1024,
            execution_role=task_execution_role,
            task_role=task_role,
        )

        container = self.task_definition.add_container(
            "SrContainer",
            container_name="sr-pipeline",
            image=ecs.ContainerImage.from_ecr_repository(
                self.ecr_repo, tag="latest"
            ),
            logging=ecs.LogDrivers.aws_logs(
                stream_prefix="sr-pipeline",
                log_group=self.log_group,
            ),
            environment={
                "SR_S3_BUCKET": self.output_bucket.bucket_name,
            },
            secrets={
                # Secrets Manager から環境変数へ注入
                "GEMINI_API_KEY": ecs.Secret.from_secrets_manager(
                    self.gemini_secret, field="api_key"
                ),
                "ANTHROPIC_API_KEY": ecs.Secret.from_secrets_manager(
                    self.claude_secret, field="api_key"
                ),
            },
        )

        # ------------------------------------------------------------------ #
        # Outputs（CLIツールが参照する値）
        # ------------------------------------------------------------------ #
        cdk.CfnOutput(
            self, "ClusterArn", value=self.cluster.cluster_arn
        )
        cdk.CfnOutput(
            self, "TaskDefinitionArn", value=self.task_definition.task_definition_arn
        )
        cdk.CfnOutput(
            self, "ContainerName", value=container.container_name
        )
