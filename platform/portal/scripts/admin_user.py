"""統括委員長の利用者を Cognito に作り、統括委員会のグループに入れる。必要なら初期データ(企画書)を入れる。
  python3 platform/portal/scripts/admin_user.py <メールアドレス> <氏名>           招待メールを送る
  python3 platform/portal/scripts/admin_user.py --seed <メールアドレス>            その利用者として POST /admin/seed を実行(仮パスワードの入力を求める)
  python3 platform/portal/scripts/admin_user.py --gl2023 <etd_2023.json> <メールアドレス>   2023年版の記述(run_jascc.sh first が作る)を取り込む
展開の出力(platform/portal/out/outputs.json)から、利用者プールと API の URL を読む。
"""
import getpass, json, os, sys, urllib.error, urllib.request
import boto3

HERE = os.path.dirname(os.path.abspath(__file__))
OUT = json.load(open(os.path.join(HERE, "..", "out", "outputs.json"), encoding="utf-8"))["jascc-gl-portal"]
idp = boto3.client("cognito-idp", region_name="ap-northeast-1")


def create(email, name):
    try:
        idp.admin_create_user(UserPoolId=OUT["UserPoolId"], Username=email, UserAttributes=[{"Name": "email", "Value": email}, {"Name": "email_verified", "Value": "true"}, {"Name": "name", "Value": name}],
                              DesiredDeliveryMediums=["EMAIL"])
        print("招待メールを送りました:", email)
    except idp.exceptions.UsernameExistsException:
        print("既に登録されています:", email)
    idp.admin_add_user_to_group(UserPoolId=OUT["UserPoolId"], Username=email, GroupName="統括委員会")
    print("統括委員会のグループに入れました")


class Session:
    """ポータルの API を、統括委員長の AWS 認証情報で直接呼ぶ(Lambda を invoke。パスワード不要)。
    利用者のメールアドレスとグループは Cognito から読み、監査記録(AUDIT)にはその利用者が記録される。
    AWS 認証情報が無いときは、Cognito のパスワードで ID トークンを取り、API Gateway 経由で呼ぶ。"""

    def __init__(self, email):
        self.email = email; self.tok = None; self.fn = None
        try:
            sts = boto3.client("sts", region_name="ap-northeast-1"); sts.get_caller_identity()
            fns = boto3.client("lambda", region_name="ap-northeast-1").list_functions()["Functions"]
            cands = [f["FunctionName"] for f in fns if f["FunctionName"].startswith("jascc-gl-portal-Api")]
            if len(cands) != 1: raise RuntimeError(f"API の Lambda が特定できません: {cands}")
            self.fn = cands[0]
            groups = [g["GroupName"] for g in idp.admin_list_groups_for_user(UserPoolId=OUT["UserPoolId"], Username=email)["Groups"]]
            if not groups: raise RuntimeError(f"{email} はどのグループにも入っていません")
            self.claims = {"email": email, "cognito:groups": groups}
            print(f"AWS 認証情報で実行(利用者 {email}、グループ {'・'.join(groups)})")
        except Exception as e:
            if self.fn is not None or "特定できません" in str(e) or "グループ" in str(e): raise
            print("AWS 認証情報が無いため、パスワードで認証します")
            self.tok = _id_token(email)

    def call(self, method, path, data=None):
        body = json.dumps(data, ensure_ascii=False) if data is not None else None
        if self.fn:
            ev = {"rawPath": path, "requestContext": {"http": {"method": method}, "authorizer": {"jwt": {"claims": self.claims}}}, "body": body}
            r = boto3.client("lambda", region_name="ap-northeast-1").invoke(FunctionName=self.fn, Payload=json.dumps(ev).encode())
            out = json.loads(r["Payload"].read().decode() or "{}")
            if "FunctionError" in r: raise RuntimeError(f"API の実行に失敗: {out}")
            res = json.loads(out.get("body") or "{}")
            if out.get("statusCode", 200) >= 400: return {"error": f"{out.get('statusCode')} {json.dumps(res, ensure_ascii=False)[:200]}"}
            return res
        req = urllib.request.Request(OUT["ApiUrl"] + path, method=method, headers={"Authorization": "Bearer " + self.tok, "Content-Type": "application/json"}, data=body.encode() if body else None)
        try:
            return json.loads(urllib.request.urlopen(req).read().decode())
        except urllib.error.HTTPError as e:
            return {"error": f"{e.code} {e.read().decode()[:200]}"}


def _id_token(email):
    pw = getpass.getpass("パスワード(仮パスワードの場合は初回ログインで変更後のもの): ")
    r = idp.initiate_auth(ClientId=OUT["ClientId"], AuthFlow="USER_PASSWORD_AUTH", AuthParameters={"USERNAME": email, "PASSWORD": pw})
    if r.get("ChallengeName") == "NEW_PASSWORD_REQUIRED":
        new = getpass.getpass("新しいパスワード(12文字以上、大文字・小文字・数字): ")
        r = idp.respond_to_auth_challenge(ClientId=OUT["ClientId"], ChallengeName="NEW_PASSWORD_REQUIRED", Session=r["Session"], ChallengeResponses={"USERNAME": email, "NEW_PASSWORD": new})
    return r["AuthenticationResult"]["IdToken"]


def token(email):
    return Session(email)


def post(path, tok, data):
    print(json.dumps(tok.call("POST", path, data), ensure_ascii=False))


def seed(email):
    post("/admin/seed", token(email), {})


def gl2023(path, email):
    items = json.load(open(path, encoding="utf-8"))
    post("/gl2023", token(email), {"items": items})


if __name__ == "__main__":
    a = sys.argv[1:]
    if a[:1] == ["--seed"]:
        seed(a[1])
    elif a[:1] == ["--gl2023"]:
        gl2023(a[1], a[2])
    elif len(a) == 2:
        create(a[0], a[1])
    else:
        print(__doc__)
