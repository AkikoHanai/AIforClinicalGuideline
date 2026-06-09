#!/usr/bin/env python3
"""
Create AWS Bedrock provisioned throughput for Claude Sonnet
Run this to enable your account for Bedrock API calls
"""
import boto3
import sys

client = boto3.client("bedrock", region_name="ap-northeast-1")

print("=" * 70)
print("Creating AWS Bedrock Provisioned Throughput")
print("=" * 70)

try:
    response = client.create_provisioned_model_throughput(
        modelId="anthropic.claude-3-5-sonnet-20241022-v2:0",
        modelUnits=1,
        provisionedModelName="sr-pipeline-sonnet",
        commitmentDuration="OneMonth"
    )

    arn = response['provisionedModelArn']
    print(f"\n✅ SUCCESS!")
    print(f"\n📦 Provisioned Model ARN:")
    print(f"   {arn}")
    print(f"\n📋 Details:")
    print(f"   Model: {response['modelId']}")
    print(f"   Name: {response.get('provisionedModelName')}")
    print(f"   Units: {response.get('modelUnits')}")
    print(f"   Status: {response.get('status', 'Creating...')}")
    print(f"\n⏳ Status: It may take a few minutes to be ready")
    print(f"\n💾 Save this ARN - you'll need it in your code")

    # Save to file
    with open(".bedrock_arn", "w") as f:
        f.write(arn)
    print(f"\n✅ ARN saved to .bedrock_arn")

except Exception as e:
    print(f"\n❌ Error: {type(e).__name__}")
    print(f"Message: {str(e)}")

    if "AccessDenied" in str(e) or "not authorized" in str(e):
        print("\n⚠️  Your credentials don't have permission!")
        print("\nYou need:")
        print("  • bedrock:CreateProvisionedModelThroughput permission")
        print("  • Or ask your AWS admin to create it")

    sys.exit(1)
