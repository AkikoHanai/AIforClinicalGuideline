"""統括委員長の利用者を Cognito に作り、統括委員会のグループに入れる。必要なら初期データ(企画書)を入れる。
  python3 platform/portal/scripts/admin_user.py <メールアドレス> <氏名>           招待メールを送る
  python3 platform/portal/scripts/admin_user.py --seed <メールアドレス>            その利用者として POST /admin/seed を実行(仮パスワードの入力を求める)
  python3 platform/portal/scripts/admin_user.py --gl2023 <etd_2023.json> <メールアドレス>   2023年版の記述(run_jascc.sh first が作る)を取り込む
  python3 platform/portal/scripts/admin_user.py --outcomes <メールアドレス> [アウトカム名]   全CQ・FRQにアウトカムを登録する(既定は CIPN。統括委員長の決定 2026-11-16)。
      アウトカムが未登録の CQ だけに登録する。別のアウトカムが登録済みの CQ は変えずに一覧に出す
展開の出力(platform/portal/out/outputs.json)から、利用者プールと API の URL を読む。
"""
import getpass, json, os, re, sys, urllib.error, urllib.request
import boto3

HERE = os.path.dirname(os.path.abspath(__file__))
OUT = json.load(open(os.environ.get("JASCC_OUTPUTS") or os.path.join(HERE, "..", "out", "outputs.json"), encoding="utf-8"))["jascc-gl-portal"]
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


CONF = os.path.expanduser("~/.jascc_gl_portal.json")
EMAIL_RE = re.compile(r"[^@\s/]+@[^@\s/]+\.[^@\s/]+")


def email_arg(argv):
    """引数の中の、メールアドレスの形のもの(なければ None。保存済みのもの、または統括委員会の唯一の利用者が使われる)。"""
    return next((x for x in argv if EMAIL_RE.fullmatch(x)), None)


def pool_users():
    """利用者プールの全利用者: [{email, name, groups}]"""
    out, kw = [], {}
    while True:
        r = idp.list_users(UserPoolId=OUT["UserPoolId"], **kw)
        for u in r["Users"]:
            at = {a["Name"]: a["Value"] for a in u.get("Attributes", [])}
            gs = [g["GroupName"] for g in idp.admin_list_groups_for_user(UserPoolId=OUT["UserPoolId"], Username=u["Username"])["Groups"]]
            out.append({"email": at.get("email", u["Username"]), "name": at.get("name", ""), "groups": gs})
        if "PaginationToken" not in r: return out
        kw = {"PaginationToken": r["PaginationToken"]}


def users_help():
    us = pool_users()
    return f"利用者プール {OUT['UserPoolId']} の利用者({len(us)}人):\n" + "\n".join(f"  {u['email']}  {u['name']}  {'・'.join(u['groups']) or '(グループなし)'}" for u in us) if us else \
        f"利用者プール {OUT['UserPoolId']} に、利用者がいません。次で統括委員長の利用者を作ってください:\n  python3 platform/portal/scripts/admin_user.py <メールアドレス> 華井明子"


def resolve_email(email=None):
    """使う利用者のメールアドレスを決める。指定がなければ、保存済みのもの、なければ統括委員会の唯一の利用者。プールにいなければ、プールの利用者の一覧を示して止まる。"""
    if email is not None and not EMAIL_RE.fullmatch(email): sys.exit(f"メールアドレスの形ではありません: {email}")
    if email is None:
        try: saved = json.load(open(CONF, encoding="utf-8")).get("email", "") if os.path.exists(CONF) else ""
        except ValueError: saved = ""
        email = saved if EMAIL_RE.fullmatch(saved or "") else None
    if email is None:
        admins = [u for u in pool_users() if "統括委員会" in u["groups"]]
        if len(admins) != 1: sys.exit("使う利用者を決められません。メールアドレスを指定してください。\n" + users_help())
        email = admins[0]["email"]; print("統括委員会の利用者:", email)
    try:
        idp.admin_get_user(UserPoolId=OUT["UserPoolId"], Username=email)
    except idp.exceptions.UserNotFoundException:
        sys.exit(f"利用者プールに、このメールアドレスの利用者がいません: {email}\n{users_help()}\n(上の一覧の統括委員会のメールアドレスで、もう一度実行してください。メールアドレスの指定は、省略もできます)")
    try:
        cfg = json.load(open(CONF, encoding="utf-8")) if os.path.exists(CONF) else {}
        if cfg.get("email") != email: cfg["email"] = email; json.dump(cfg, open(CONF, "w", encoding="utf-8"), ensure_ascii=False)
    except (OSError, ValueError): pass
    return email


class Session:
    """ポータルの API を、統括委員長の AWS 認証情報で直接呼ぶ(Lambda を invoke。パスワード不要)。
    利用者のメールアドレスとグループは Cognito から読み、監査記録(AUDIT)にはその利用者が記録される。
    AWS 認証情報が無いときは、Cognito のパスワードで ID トークンを取り、API Gateway 経由で呼ぶ。"""

    def __init__(self, email=None):
        self.tok = None; self.fn = None
        try:
            boto3.client("sts", region_name="ap-northeast-1").get_caller_identity(); has_aws = True
        except Exception:
            has_aws = False
        if has_aws: email = resolve_email(email)
        self.email = email
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


def token(email=None):
    return Session(email)


def post(path, tok, data):
    print(json.dumps(tok.call("POST", path, data), ensure_ascii=False))


def seed(email):
    post("/admin/seed", token(email), {})


def gl2023(path, email):
    items = json.load(open(path, encoding="utf-8"))
    post("/gl2023", token(email), {"items": items})


def outcomes(email, name="CIPN"):
    tok = token(email); done, same, other = [], [], []
    for c in tok.call("GET", "/cq"):
        cur = c.get("outcomes") or []
        if cur == [name]: same.append(c["id"]); continue
        if cur: other.append(f"{c['id']}({'、'.join(cur)})"); continue
        r = tok.call("PUT", "/cq/" + c["id"], {"outcomes": [name], "pico": {**c.get("pico", {}), "O": c.get("pico", {}).get("O") or name}})
        (done if "error" not in r else other).append(c["id"] if "error" not in r else f"{c['id']}: {r['error']}")
    print(f"アウトカム「{name}」を登録: {len(done)} 件 {' '.join(done)}")
    print(f"登録済み(変更なし): {len(same)} 件 {' '.join(same)}")
    if other: print("別のアウトカムが登録済み、または失敗(変更していない):\n  " + "\n  ".join(other))


if __name__ == "__main__":
    a = sys.argv[1:]
    if a[:1] == ["--seed"]:
        seed(a[1])
    elif a[:1] == ["--outcomes"] and len(a) >= 2:
        outcomes(a[1], *(a[2:3]))
    elif a[:1] == ["--gl2023"]:
        gl2023(a[1], a[2])
    elif len(a) == 2:
        create(a[0], a[1])
    else:
        print(__doc__)
