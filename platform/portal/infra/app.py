#!/usr/bin/env python3
"""cdk deploy の入口。展開の前に、企画書(approved_plan.json)を Lambda の資産にコピーする(初期データの出典)。"""
import os, shutil
import aws_cdk as cdk
from portal_stack import PortalStack

HERE = os.path.dirname(os.path.abspath(__file__))
shutil.copy(os.path.join(HERE, "..", "..", "governance", "approved_plan.json"), os.path.join(HERE, "..", "api", "approved_plan.json"))

app = cdk.App()
PortalStack(app, "jascc-gl-portal", env=cdk.Environment(account=os.environ.get("CDK_DEFAULT_ACCOUNT"), region=os.environ.get("CDK_DEFAULT_REGION", "ap-northeast-1")),
            description="がん薬物療法に伴う末梢神経障害診療ガイドライン2028年版 作成ポータル")
app.synth()
