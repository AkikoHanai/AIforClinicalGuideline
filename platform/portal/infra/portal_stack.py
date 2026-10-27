"""GL作成ポータルの AWS 構成(CDK)。
  Cognito(招待制のログイン、役割のグループ) / DynamoDB(1テーブル) / Lambda + API Gateway HTTP API(JWT認可)
  S3 + CloudFront(画面) / 画面の設定(config.js)は展開時に自動で書く
テーブルと利用者プールは、スタックを消しても残す(RemovalPolicy.RETAIN)。
"""
import os
import aws_cdk as cdk
from aws_cdk import (Duration, RemovalPolicy, Stack, aws_apigatewayv2 as apigw, aws_apigatewayv2_authorizers as authz, aws_apigatewayv2_integrations as integ,
                     aws_cloudfront as cf, aws_cloudfront_origins as origins, aws_cognito as cognito, aws_dynamodb as ddb, aws_iam as iam, aws_lambda as lam,
                     aws_logs as logs, aws_s3 as s3, aws_s3_deployment as s3deploy)
from constructs import Construct

HERE = os.path.dirname(os.path.abspath(__file__))
API_DIR = os.path.join(HERE, "..", "api")
WEB_DIR = os.path.join(HERE, "..", "web")
GROUPS = ["統括委員会", "事務局", "SR委員長", "作成グループ", "SR委員", "総説執筆者", "外部評価委員"]


class PortalStack(Stack):
    def __init__(self, scope: Construct, cid: str, **kw):
        super().__init__(scope, cid, **kw)
        name = "jascc-gl-portal"

        table = ddb.Table(self, "Table", table_name=name, partition_key=ddb.Attribute(name="pk", type=ddb.AttributeType.STRING),
                          sort_key=ddb.Attribute(name="sk", type=ddb.AttributeType.STRING), billing_mode=ddb.BillingMode.PAY_PER_REQUEST,
                          point_in_time_recovery_specification=ddb.PointInTimeRecoverySpecification(point_in_time_recovery_enabled=True),
                          removal_policy=RemovalPolicy.RETAIN)

        pool = cognito.UserPool(self, "Users", user_pool_name=name, self_sign_up_enabled=False, sign_in_aliases=cognito.SignInAliases(email=True),
                                auto_verify=cognito.AutoVerifiedAttrs(email=True), standard_attributes=cognito.StandardAttributes(email=cognito.StandardAttribute(required=True, mutable=True)),
                                mfa=cognito.Mfa.OPTIONAL, mfa_second_factor=cognito.MfaSecondFactor(sms=False, otp=True),
                                password_policy=cognito.PasswordPolicy(min_length=12, require_lowercase=True, require_uppercase=True, require_digits=True, require_symbols=False),
                                account_recovery=cognito.AccountRecovery.EMAIL_ONLY, removal_policy=RemovalPolicy.RETAIN,
                                user_invitation=cognito.UserInvitationConfig(
                                    email_subject="がん薬物療法に伴う末梢神経障害診療ガイドライン2028年版 作成ポータルへの招待",
                                    email_body="GL作成ポータルの利用者として登録されました。ユーザー名(メールアドレス): {username}  仮パスワード: {####}  初回ログイン後にパスワードを変更してください。"))
        for g in GROUPS:
            cognito.CfnUserPoolGroup(self, f"Group{GROUPS.index(g)}", user_pool_id=pool.user_pool_id, group_name=g)
        domain = pool.add_domain("Domain", cognito_domain=cognito.CognitoDomainOptions(domain_prefix=f"{name}-{cdk.Fn.select(0, cdk.Fn.split('-', cdk.Fn.select(2, cdk.Fn.split('/', self.stack_id))))}"))

        bucket = s3.Bucket(self, "Web", block_public_access=s3.BlockPublicAccess.BLOCK_ALL, encryption=s3.BucketEncryption.S3_MANAGED,
                           removal_policy=RemovalPolicy.DESTROY, auto_delete_objects=True)
        dist = cf.Distribution(self, "Cdn", default_behavior=cf.BehaviorOptions(origin=origins.S3BucketOrigin.with_origin_access_control(bucket),
                                                                                 viewer_protocol_policy=cf.ViewerProtocolPolicy.REDIRECT_TO_HTTPS),
                               default_root_object="index.html", price_class=cf.PriceClass.PRICE_CLASS_200,
                               error_responses=[cf.ErrorResponse(http_status=403, response_http_status=200, response_page_path="/index.html", ttl=Duration.seconds(0)),
                                                cf.ErrorResponse(http_status=404, response_http_status=200, response_page_path="/index.html", ttl=Duration.seconds(0))])
        site = f"https://{dist.distribution_domain_name}"
        local = "http://localhost:8000"

        client = pool.add_client("WebClient", generate_secret=False, auth_flows=cognito.AuthFlow(user_password=True, user_srp=True),
                                 o_auth=cognito.OAuthSettings(flows=cognito.OAuthFlows(authorization_code_grant=True),
                                                              scopes=[cognito.OAuthScope.OPENID, cognito.OAuthScope.EMAIL, cognito.OAuthScope.PROFILE],
                                                              callback_urls=[site + "/", local + "/"], logout_urls=[site + "/", local + "/"]),
                                 prevent_user_existence_errors=True, id_token_validity=Duration.hours(8), access_token_validity=Duration.hours(8), refresh_token_validity=Duration.days(7))

        fn = lam.Function(self, "Api", runtime=lam.Runtime.PYTHON_3_12, handler="handler.handler", code=lam.Code.from_asset(API_DIR), timeout=Duration.seconds(20), memory_size=512,
                          environment={"TABLE_NAME": table.table_name, "USER_POOL_ID": pool.user_pool_id}, log_retention=logs.RetentionDays.ONE_YEAR)
        table.grant_read_write_data(fn)
        fn.add_to_role_policy(iam.PolicyStatement(actions=["cognito-idp:AdminCreateUser", "cognito-idp:AdminAddUserToGroup", "cognito-idp:AdminRemoveUserFromGroup", "cognito-idp:AdminListGroupsForUser"],
                                                  resources=[pool.user_pool_arn]))

        api = apigw.HttpApi(self, "HttpApi", api_name=name,
                            cors_preflight=apigw.CorsPreflightOptions(allow_origins=[site, local], allow_methods=[apigw.CorsHttpMethod.ANY], allow_headers=["Authorization", "Content-Type"], max_age=Duration.hours(1)))
        auth = authz.HttpJwtAuthorizer("Jwt", f"https://cognito-idp.{self.region}.amazonaws.com/{pool.user_pool_id}", jwt_audience=[client.user_pool_client_id])
        api.add_routes(path="/{proxy+}", methods=[apigw.HttpMethod.ANY], integration=integ.HttpLambdaIntegration("Lambda", fn), authorizer=auth)

        config = cdk.Fn.join("", ["window.PORTAL_CONFIG=", cdk.Fn.join("", ['{"region":"', self.region, '","userPoolId":"', pool.user_pool_id, '","clientId":"', client.user_pool_client_id,
                                                                           '","domain":"', domain.domain_name, '","apiUrl":"', api.api_endpoint, '"}']), ";"])
        s3deploy.BucketDeployment(self, "Deploy", destination_bucket=bucket, distribution=dist, distribution_paths=["/*"],
                                  sources=[s3deploy.Source.asset(WEB_DIR, exclude=["config.js"]), s3deploy.Source.data("config.js", config)])

        for k, v in {"SiteUrl": site, "ApiUrl": api.api_endpoint, "UserPoolId": pool.user_pool_id, "ClientId": client.user_pool_client_id,
                     "CognitoDomain": f"{domain.domain_name}.auth.{self.region}.amazoncognito.com", "TableName": table.table_name}.items():
            cdk.CfnOutput(self, k, value=v)
