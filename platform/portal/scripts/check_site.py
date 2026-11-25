"""ポータルの画面から API・Cognito に届くかを、ブラウザと同じ要求で確認する(「Failed to fetch」が出るとき)。統括委員長の Mac で実行する。
  python3 platform/portal/scripts/check_site.py
確認すること:
  1. ログイン画面の設定(config.js)と outputs.json の API の URL・利用者プール・クライアントが一致するか
  2. API・Cognito のホスト名が引けるか(DNS)
  3. API の CORS: 画面の origin からの事前確認(OPTIONS)と、認証なしの GET に、許可のヘッダーが付くか(付かないと、ブラウザは「Failed to fetch」にする)
  4. Cognito のトークン取得の CORS
  5. AWS の権限があれば、API Gateway の CORS 設定・ルートの認可・Lambda の状態
判定は、各行の先頭の [OK] / [NG] / [注意]。[NG] の行が、原因。結果を貼ってください(メールアドレスは含まれません)。
"""
import json, os, socket, sys, urllib.error, urllib.parse, urllib.request

HERE = os.path.dirname(os.path.abspath(__file__))
OUT = json.load(open(os.environ.get("JASCC_OUTPUTS") or os.path.join(HERE, "..", "out", "outputs.json"), encoding="utf-8"))["jascc-gl-portal"]
bad = []


def say(tag, msg):
    print(f"[{tag}] {msg}")
    if tag == "NG": bad.append(msg)


def http(method, url, headers=None, data=None, timeout=15):
    """戻り値: (HTTP の状態, ヘッダー(小文字のキー), 本文)。接続できないときは (None, {}, エラーの説明)"""
    req = urllib.request.Request(url, method=method, headers=headers or {}, data=data)
    try:
        r = urllib.request.urlopen(req, timeout=timeout); return r.status, {k.lower(): v for k, v in r.headers.items()}, r.read(2000).decode("utf-8", "replace")
    except urllib.error.HTTPError as e:
        return e.code, {k.lower(): v for k, v in e.headers.items()}, e.read(2000).decode("utf-8", "replace")
    except Exception as e:
        return None, {}, f"{type(e).__name__}: {e}"


def cors_ok(h, origin):
    a = h.get("access-control-allow-origin", "")
    return a in ("*", origin)


def main():
    site = OUT["SiteUrl"].rstrip("/"); api = OUT["ApiUrl"].rstrip("/")
    print(f"画面: {site}\nAPI: {api}")
    st, h, body = http("GET", site + "/config.js")
    live = None
    if st == 200:
        try: live = json.loads(body[body.index("{"):body.rindex("}") + 1])
        except Exception: pass
    if not live: say("NG", f"ログイン画面の設定(config.js)を取得できません: HTTP {st} {body[:120]}")
    else:
        for k, o in (("apiUrl", "ApiUrl"), ("userPoolId", "UserPoolId"), ("clientId", "ClientId")):
            if (live.get(k) or "").rstrip("/") == OUT.get(o, "").rstrip("/"): say("OK", f"画面の設定 {k} は outputs.json と一致")
            else: say("NG" if k == "apiUrl" else "注意", f"画面の設定 {k}={live.get(k)} は、outputs.json({OUT.get(o)})と違います。画面が使うのは、画面の設定です")
        api = (live.get("apiUrl") or api).rstrip("/"); dom = live.get("domain"); reg = live.get("region")
    for host in {urllib.parse.urlparse(api).hostname} | ({f"{live['domain']}.auth.{live['region']}.amazoncognito.com"} if live else set()):
        try: socket.getaddrinfo(host, 443); say("OK", f"ホスト名を引けます: {host}")
        except Exception as e: say("NG", f"ホスト名を引けません: {host}({e})。ネットワーク(学内 VPN・DNS・フィルタ)、または API・Cognito のドメインが存在しません")
    # API: ブラウザと同じ事前確認(OPTIONS)
    pre = {"Origin": site, "Access-Control-Request-Method": "GET", "Access-Control-Request-Headers": "authorization,content-type"}
    st, h, body = http("OPTIONS", api + "/me", pre)
    if st is None: say("NG", f"API に接続できません: {body}")
    else:
        miss = [k for k in ("access-control-allow-origin", "access-control-allow-headers", "access-control-allow-methods") if k not in h]
        if st in (200, 204) and cors_ok(h, site) and not miss: say("OK", f"API の事前確認(OPTIONS)に、許可のヘッダーが付いています(HTTP {st}、Allow-Origin {h['access-control-allow-origin']})")
        else: say("NG", f"API の事前確認(OPTIONS)が通りません: HTTP {st}、Allow-Origin={h.get('access-control-allow-origin')}、不足={miss}。ブラウザは「Failed to fetch」にします(CORS)。{body[:100]}")
        st2, h2, body2 = http("GET", api + "/me", {"Origin": site})
        if st2 == 401 and cors_ok(h2, site): say("OK", "認証なしの GET /me は 401(正常)で、許可のヘッダーが付いています")
        elif st2 == 401: say("NG", "認証なしの GET /me は 401 ですが、許可のヘッダーがありません(ブラウザは 401 の内容を読めず「Failed to fetch」にします)")
        else: say("注意", f"認証なしの GET /me が HTTP {st2}(401 が正常): {body2[:100]}")
    # Cognito のトークン取得
    if live:
        tok = f"https://{live['domain']}.auth.{live['region']}.amazoncognito.com/oauth2/token"
        st, h, body = http("POST", tok, {"Origin": site, "Content-Type": "application/x-www-form-urlencoded"}, urllib.parse.urlencode({"grant_type": "authorization_code", "client_id": live["clientId"], "code": "x", "redirect_uri": site + "/", "code_verifier": "x"}).encode())
        if st is None: say("NG", f"Cognito のトークン取得に接続できません: {body}")
        elif st == 400 and cors_ok(h, site): say("OK", f"Cognito のトークン取得は応答し(HTTP 400 は、ダミーのコードのため正常)、許可のヘッダーが付いています")
        elif st == 400: say("NG", "Cognito のトークン取得に、許可のヘッダー(Access-Control-Allow-Origin)がありません。ブラウザが読めず「Failed to fetch」になります")
        else: say("注意", f"Cognito のトークン取得が HTTP {st}: {body[:120]}")
    # AWS の設定(権限があるとき)
    try:
        import boto3
        ag = boto3.client("apigatewayv2", region_name="ap-northeast-1")
        host = urllib.parse.urlparse(api).hostname; apis = [x for x in ag.get_apis()["Items"] if x.get("ApiEndpoint", "").endswith(host)]
        if not apis: say("NG", f"API Gateway に、{host} の API がありません(削除された、または別のアカウント・リージョン)")
        else:
            a = apis[0]; cfg = a.get("CorsConfiguration") or {}
            print(f"  API Gateway の CORS 設定: 許可する origin={cfg.get('AllowOrigins')} / methods={cfg.get('AllowMethods')} / headers={cfg.get('AllowHeaders')}")
            if site not in (cfg.get("AllowOrigins") or []): say("NG", f"API Gateway の CORS が許可する origin に、画面 {site} がありません")
            for rt in ag.get_routes(ApiId=a["ApiId"])["Items"]: print(f"  ルート {rt['RouteKey']}: 認可 {rt.get('AuthorizationType')}")
            for au in ag.get_authorizers(ApiId=a["ApiId"])["Items"]: print(f"  認可: {au.get('AuthorizerType')} audience={au.get('JwtConfiguration', {}).get('Audience')} issuer={au.get('JwtConfiguration', {}).get('Issuer')}")
            if live and live.get("clientId") not in [x for au in ag.get_authorizers(ApiId=a["ApiId"])["Items"] for x in au.get("JwtConfiguration", {}).get("Audience", [])]:
                say("NG", "API の認可(audience)に、ログイン画面のクライアントがありません。サインインしても API が 401 を返します")
        lam = boto3.client("lambda", region_name="ap-northeast-1")
        for f in lam.list_functions()["Functions"]:
            if f["FunctionName"].startswith("jascc-gl-portal-Api"): print(f"  Lambda {f['FunctionName']}: 状態 {f.get('State')}/{f.get('LastUpdateStatus')}、実行時間の上限 {f['Timeout']}秒、更新 {f['LastModified']}")
    except Exception as e:
        print(f"  (AWS の設定は確認できませんでした: {type(e).__name__}。AWS にログインしているか確認)")
    print("\n" + ("【原因】[NG] の行を確認してください。この出力を貼ってください。" if bad else "NG の行はありません。画面側(ブラウザの拡張機能・キャッシュ)を確認します: Cmd+Shift+R で再読み込み、または別のブラウザ・シークレットウィンドウで試してください。"))
    return 1 if bad else 0


if __name__ == "__main__":
    if {"-h", "--help"} & set(sys.argv[1:]): sys.exit(__doc__)
    sys.exit(main())
