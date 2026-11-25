"""統括委員長の利用者を Cognito に作り、統括委員会のグループに入れる。必要なら初期データ(企画書)を入れる。
  python3 platform/portal/scripts/admin_user.py <メールアドレス> <氏名>           招待メールを送る
  python3 platform/portal/scripts/admin_user.py --users                          利用者プールの利用者の一覧(メールアドレス・氏名・グループ)
  python3 platform/portal/scripts/admin_user.py --diagnose [<メールアドレス>]    サインインできない原因を調べる(ログイン画面の設定との一致、利用者の状態、大文字・小文字の違い、サインイン試験)
  python3 platform/portal/scripts/admin_user.py --password <メールアドレス>       既存の利用者のパスワードを直接設定し、直後にサインイン試験をする(確認コード不要)
  python3 platform/portal/scripts/admin_user.py --chair <メールアドレス> <氏名>   統括委員長の利用者を作り(なければ)、パスワードを設定し、統括委員会に入れる(招待メールは送らない)
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


def live_config(site):
    """ログイン画面(CloudFront の config.js)が実際に使っている設定。取得できなければ None。"""
    try:
        txt = urllib.request.urlopen(site.rstrip("/") + "/config.js", timeout=6).read().decode("utf-8", "replace")
        return json.loads(txt[txt.index("{"):txt.rindex("}") + 1])
    except Exception:
        return None


def sync_with_site():
    """outputs.json(展開のときに保存した値)が古く、ログイン画面が別の利用者プール・クライアントを使っているとき、画面の設定に合わせる。
    (別のプールの利用者にパスワードを設定しても、画面からは反映されないため。)"""
    if os.environ.get("JASCC_OUTPUTS") or not OUT.get("SiteUrl"): return
    live = live_config(OUT["SiteUrl"])
    if not live: print("(ログイン画面の設定を取得できませんでした。outputs.json の値を使います)"); return
    diff = [(k, OUT.get(o), live.get(l)) for k, o, l in (("利用者プール", "UserPoolId", "userPoolId"), ("クライアント", "ClientId", "clientId")) if live.get(l) and OUT.get(o) != live.get(l)]
    if diff:
        print("【注意】ログイン画面が使っている設定は、outputs.json と違います。画面の設定に合わせます。\n" + "\n".join(f"  {k}: outputs.json={a} / ログイン画面={b}" for k, a, b in diff))
        OUT["UserPoolId"] = live.get("userPoolId", OUT["UserPoolId"]); OUT["ClientId"] = live.get("clientId", OUT["ClientId"])


sync_with_site()


def create(email, name):
    try:
        idp.admin_create_user(UserPoolId=OUT["UserPoolId"], Username=email, UserAttributes=[{"Name": "email", "Value": email}, {"Name": "email_verified", "Value": "true"}, {"Name": "name", "Value": name}],
                              DesiredDeliveryMediums=["EMAIL"])
        print("招待メールを送りました:", email)
    except idp.exceptions.UsernameExistsException:
        print("既に登録されています:", email)
    idp.admin_add_user_to_group(UserPoolId=OUT["UserPoolId"], Username=email, GroupName="統括委員会")
    print("統括委員会のグループに入れました")


def ask_password():
    """パスワードを 2回入力させる(12文字以上、大文字・小文字・数字を含む。ポータルの利用者プールの規則)。"""
    while True:
        a = getpass.getpass("新しいパスワード(12文字以上、大文字・小文字・数字を含む。入力は表示されません): "); b = getpass.getpass("もう一度: ")
        if a != b: print("2回の入力が違います"); continue
        if len(a) < 12 or not re.search("[a-z]", a) or not re.search("[A-Z]", a) or not re.search("[0-9]", a): print("12文字以上で、大文字・小文字・数字を含めてください"); continue
        return a


def chair(email, name):
    """統括委員長の利用者を作り(なければ。招待メールは送らない)、パスワードを設定し、統括委員会のグループに入れる。サインインできないときに使う。"""
    if not EMAIL_RE.fullmatch(email): sys.exit(f"メールアドレスの形ではありません: {email}")
    stored, allm = find_user(email)
    if stored and stored != email: sys.exit(f"大文字・小文字だけが違う利用者が、既にいます: {', '.join(allm)}\n(別の利用者を作らないため、止めました。その表記で --password を実行してください)")
    try:
        idp.admin_create_user(UserPoolId=OUT["UserPoolId"], Username=email, MessageAction="SUPPRESS",
                              UserAttributes=[{"Name": "email", "Value": email}, {"Name": "email_verified", "Value": "true"}, {"Name": "name", "Value": name}])
        print("利用者を作りました(招待メールは送りません):", email)
    except idp.exceptions.UsernameExistsException:
        print("既に登録されています:", email)
    reset_password(email)
    idp.admin_add_user_to_group(UserPoolId=OUT["UserPoolId"], Username=email, GroupName="統括委員会")
    print("統括委員会のグループに入れました。ポータルで、このメールアドレスとパスワードでサインインしてください")


def find_user(email):
    """利用者を探す。この利用者プールは、サインインで大文字・小文字を区別する(Akiko@… と akiko@… は別の利用者)。完全一致がなければ、大文字・小文字を無視して探す。
    戻り値: (保存されているメールアドレス, 一致した全員のリスト)"""
    try:
        idp.admin_get_user(UserPoolId=OUT["UserPoolId"], Username=email); exact = [email]
    except idp.exceptions.UserNotFoundException:
        exact = []
    like = [u["email"] for u in pool_users() if u["email"].lower() == email.lower()]
    allm = list(dict.fromkeys(exact + like))
    return (exact[0] if exact else (like[0] if like else None)), allm


def login_test(email, password):
    """ポータルのログインと同じ認証(メールアドレスとパスワード)を、実際に行う。戻り値: (成功か, 説明)"""
    try:
        r = idp.initiate_auth(ClientId=OUT["ClientId"], AuthFlow="USER_PASSWORD_AUTH", AuthParameters={"USERNAME": email, "PASSWORD": password})
    except idp.exceptions.NotAuthorizedException as e:
        return False, f"認証できません(メールアドレスまたはパスワードが違う): {e}"
    except idp.exceptions.UserNotConfirmedException:
        return False, "アカウントが確認されていません(確認コードの入力が済んでいません)"
    except idp.exceptions.PasswordResetRequiredException:
        return False, "パスワードの再設定が求められています(--password で設定し直してください)"
    except idp.exceptions.UserNotFoundException:
        return False, "この利用者プール・クライアントに、この利用者がいません"
    except Exception as e:
        return False, f"{type(e).__name__}: {str(e)[:200]}"
    ch = r.get("ChallengeName")
    if ch == "NEW_PASSWORD_REQUIRED": return False, "初回のパスワード変更が求められています(--password で設定し直してください)"
    if ch in ("SOFTWARE_TOKEN_MFA", "MFA_SETUP", "SMS_MFA"): return True, f"パスワードは正しい。サインインのとき、多要素認証({ch})のコードも入力が必要です"
    return True, "サインインできました(パスワードは正しい)"


def reset_password(email):
    """既存の利用者のパスワードを、直接(確認コード・メールなしで)設定し、設定した直後に、実際のサインイン試験を行う。
    メールアドレスの大文字・小文字が違うときは、保存されているものを使い、サインインで入力するメールアドレスを示す。"""
    stored, allm = find_user(email)
    if not stored: sys.exit(f"利用者プールに、このメールアドレスの利用者がいません: {email}\n{users_help()}")
    if len(allm) > 1: print("【注意】大文字・小文字だけが違う利用者が複数います(サインインでは別の利用者として扱われます):", *allm, sep="\n  ")
    if stored != email: print(f"【注意】入力は {email} ですが、保存されているメールアドレスは {stored} です。サインインでは、この表記(大文字・小文字を含む)を入力してください")
    u = idp.admin_get_user(UserPoolId=OUT["UserPoolId"], Username=stored)
    if not u.get("Enabled", True): idp.admin_enable_user(UserPoolId=OUT["UserPoolId"], Username=stored); print("無効になっていた利用者を、有効にしました")
    if u.get("UserStatus") == "UNCONFIRMED":
        idp.admin_confirm_sign_up(UserPoolId=OUT["UserPoolId"], Username=stored); print("未確認だった利用者を、確認済みにしました")
    if {a["Name"]: a["Value"] for a in u.get("UserAttributes", [])}.get("email_verified") != "true":
        idp.admin_update_user_attributes(UserPoolId=OUT["UserPoolId"], Username=stored, UserAttributes=[{"Name": "email_verified", "Value": "true"}]); print("メールアドレスを、確認済みにしました(「Forgot your password?」のメールが届くようにするため)")
    while True:
        pw = ask_password()
        try:
            idp.admin_set_user_password(UserPoolId=OUT["UserPoolId"], Username=stored, Password=pw, Permanent=True); break
        except idp.exceptions.InvalidPasswordException as e:
            print("利用者プールの規則に合いません:", str(e).split(":", 1)[-1].strip())
    print("パスワードを設定しました:", stored)
    ok, msg = login_test(stored, pw)
    print(("【確認OK】" if ok else "【確認NG】") + f" 設定した直後のサインイン試験: {msg}")
    print(f"利用者プール {OUT['UserPoolId']} / クライアント {OUT['ClientId']}")
    if ok: print(f"ポータルでは、メールアドレス「{stored}」(大文字・小文字もそのまま)と、いま設定したパスワードでサインインしてください")
    else: print("サインインできない原因は、上の説明のとおりです。--diagnose でも詳しく確認できます")


def diagnose(email=None):
    """サインインできない原因を調べる: ログイン画面の設定との一致、利用者の状態(大文字・小文字の違いを含む)、実際のサインイン試験。"""
    print(f"outputs.json: 利用者プール {OUT['UserPoolId']} / クライアント {OUT['ClientId']}")
    live = live_config(OUT["SiteUrl"]) if OUT.get("SiteUrl") else None
    print(f"ログイン画面({OUT.get('SiteUrl', '')}): " + (f"利用者プール {live.get('userPoolId')} / クライアント {live.get('clientId')} / ドメイン {live.get('domain')}" if live else "設定を取得できませんでした"))
    if live and (live.get("userPoolId") != OUT["UserPoolId"] or live.get("clientId") != OUT["ClientId"]): print("【不一致】outputs.json と、ログイン画面が使っている設定が違います。(このスクリプトは、画面の設定に合わせて動いています)")
    elif live: print("一致しています(画面と、このスクリプトは、同じ利用者プール・クライアントを使っています)")
    if not email: print(users_help()); return
    stored, allm = find_user(email)
    if not stored: print(f"この利用者プールに、{email} の利用者はいません(大文字・小文字を無視しても)。\n{users_help()}"); return
    for m in allm:
        u = idp.admin_get_user(UserPoolId=OUT["UserPoolId"], Username=m); at = {a["Name"]: a["Value"] for a in u.get("UserAttributes", [])}
        print(f"利用者 {m}: 状態 {u['UserStatus']}、{'有効' if u.get('Enabled', True) else '無効'}、メール確認 {at.get('email_verified', '')}、多要素認証 {u.get('UserMFASettingList') or 'なし'}、氏名 {at.get('name', '')}")
    if len(allm) > 1: print("【注意】大文字・小文字だけが違う利用者が複数います。サインインでは別の利用者として扱われます")
    if stored != email: print(f"【注意】入力は {email} ですが、保存されているのは {stored} です。サインインの画面では、保存されている表記を入力してください")
    pw = getpass.getpass(f"サインイン試験をします。{stored} のパスワードを入力(試験をしないときは、そのまま Enter。入力は表示されません): ")
    if pw:
        ok, msg = login_test(stored, pw); print(("【OK】" if ok else "【NG】"), msg)


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
    elif a[:1] == ["--users"]:
        print(users_help())
    elif a[:1] == ["--diagnose"]:
        diagnose(a[1] if len(a) > 1 else None)
    elif a[:1] == ["--password"] and len(a) == 2:
        reset_password(a[1])
    elif a[:1] == ["--chair"] and len(a) == 3:
        chair(a[1], a[2])
    elif a[:1] == ["--gl2023"]:
        gl2023(a[1], a[2])
    elif len(a) == 2:
        create(a[0], a[1])
    else:
        print(__doc__)
