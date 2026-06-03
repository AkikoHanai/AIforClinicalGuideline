#!/usr/bin/env python3
import aws_cdk as cdk
from sr_stack import SrStack

app = cdk.App()

SrStack(
    app,
    "SrAutomationStack",
    # AWSアカウント・リージョンを明示（cdk bootstrapで使用するものと合わせる）
    env=cdk.Environment(
        account=app.node.try_get_context("account"),
        region=app.node.try_get_context("region") or "ap-northeast-1",
    ),
    description="SR Automation Pipeline — PubMed → Minds Evidence Table",
)

app.synth()
