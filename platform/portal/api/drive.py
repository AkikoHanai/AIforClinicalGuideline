"""共有ドライブ「CIPNガイドライン作成」への転送(ポータル → ドライブ。統括委員長の Mac を介さない)。
転送先は、統括委員長の Google アカウントで動かす Apps Script の Web アプリ(platform/drive_gas)。
Web アプリへの接続情報(url と token)は、AWS Secrets Manager の jascc-gl-portal/drive に置く(コードと画面に出さない)。
標準ライブラリだけで書く(Lambda に追加の部品を入れない)。
"""
import base64, json, os, time, urllib.request

SECRET_ID = os.environ.get("DRIVE_SECRET", "")
_cache = {"at": 0.0, "cfg": None}


def config():
    """{url, token}。未設定なら None。5分間は同じ値を使う。"""
    if time.time() - _cache["at"] < 300: return _cache["cfg"]
    cfg = None
    if SECRET_ID:
        import boto3
        try:
            cfg = json.loads(boto3.client("secretsmanager").get_secret_value(SecretId=SECRET_ID)["SecretString"])
        except Exception:
            cfg = None
    elif os.environ.get("DRIVE_URL") and os.environ.get("DRIVE_TOKEN"):
        cfg = {"url": os.environ["DRIVE_URL"], "token": os.environ["DRIVE_TOKEN"]}
    if cfg and not (cfg.get("url", "").startswith("https://script.google.com/") and cfg.get("token")): cfg = None
    _cache.update({"at": time.time(), "cfg": cfg}); return cfg


def reset_cache():
    _cache.update({"at": 0.0, "cfg": None})


def call(cfg, payload, timeout=60):
    """Apps Script に POST する。Google は 302 で結果の場所へ移すため、urllib の既定の追従(POST → GET)をそのまま使う。"""
    body = json.dumps(dict(payload, token=cfg["token"]), ensure_ascii=False).encode("utf-8")
    req = urllib.request.Request(cfg["url"], data=body, headers={"Content-Type": "text/plain; charset=utf-8"}, method="POST")
    raw = urllib.request.urlopen(req, timeout=timeout).read().decode("utf-8", "replace")
    try:
        return json.loads(raw)
    except ValueError:
        raise RuntimeError("共有ドライブの受け口が、JSON でない応答を返しました(Web アプリの公開設定を確認)")


def put(cfg, path, data, overwrite=False, mime="application/octet-stream"):
    """path = [フォルダ名..., ファイル名]。同じ名前のファイルがあるとき、overwrite=False なら何もしない(action=same)、True なら内容を置き換える(ドライブの版の履歴に残る)。"""
    r = call(cfg, {"action": "put", "path": path, "mime": mime, "mode": "overwrite" if overwrite else "skip", "data": base64.b64encode(data).decode("ascii")}, timeout=120)
    if not r.get("ok"): raise RuntimeError(str(r.get("error", "転送できませんでした"))[:300])
    return r


def ping(cfg):
    r = call(cfg, {"action": "ping"}, timeout=30)
    if not r.get("ok"): raise RuntimeError(str(r.get("error", "接続できませんでした"))[:300])
    return r
