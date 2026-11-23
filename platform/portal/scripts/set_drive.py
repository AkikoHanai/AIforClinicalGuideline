"""ポータルが共有ドライブへ直接転送するための、接続情報(Apps Script の Web アプリの URL と合言葉)を AWS Secrets Manager に保存する(統括委員長が実行)。
  python3 platform/portal/scripts/set_drive.py token                   合言葉を作って表示する(保存はしない。Apps Script のスクリプトのプロパティ TOKEN に貼る)
  python3 platform/portal/scripts/set_drive.py save <メールアドレス>   URL と合言葉を入力して保存し、接続を確かめる(入力は画面に出ない)
  python3 platform/portal/scripts/set_drive.py status <メールアドレス> 接続と直近の転送の状態を表示する
  python3 platform/portal/scripts/set_drive.py sync <メールアドレス> [--force]   今すぐ転送する(--force: 転送済みも全て送り直す)
手順の全体は platform/drive_gas/README.md。合言葉は、チャット・メール・Git に書かない(Secrets Manager と Apps Script の2か所だけ)。
"""
import getpass, json, secrets, sys, time
import boto3

SECRET = "jascc-gl-portal/drive"
REGION = "ap-northeast-1"


def save(url, token):
    sm = boto3.client("secretsmanager", region_name=REGION); val = json.dumps({"url": url, "token": token})
    try:
        sm.create_secret(Name=SECRET, SecretString=val, Description="共有ドライブへ転送する Apps Script の Web アプリの URL と合言葉")
        print("保存しました(新規):", SECRET)
    except sm.exceptions.ResourceExistsException:
        sm.put_secret_value(SecretId=SECRET, SecretString=val); print("保存しました(更新):", SECRET)


if __name__ == "__main__":
    a = sys.argv[1:]
    if not a: sys.exit(__doc__)
    if a[0] == "token":
        print(secrets.token_urlsafe(32)); print("↑ この合言葉を、Apps Script のスクリプトのプロパティ TOKEN に貼ってください。他には書かないでください。")
    elif a[0] == "save" and len(a) > 1:
        url = input("Web アプリの URL(https://script.google.com/macros/s/.../exec): ").strip(); token = getpass.getpass("合言葉(入力は表示されません): ").strip()
        if not url.startswith("https://script.google.com/macros/s/") or not url.endswith("/exec"): sys.exit("URL は https://script.google.com/macros/s/.../exec の形です(「デプロイ」の「ウェブアプリ」の URL)")
        if len(token) < 24: sys.exit("合言葉が短すぎます(24文字以上。token で作ったものを使う)")
        save(url, token); time.sleep(2)
        from admin_user import Session
        r = Session(a[1]).call("POST", "/drive/test", {}); print("接続の確認:", json.dumps(r, ensure_ascii=False))
        if r.get("ok"): print(f"共有ドライブ「{r.get('root')}」に接続できました。次は sync で転送してください")
        else: sys.exit("接続できていません。README の「うまくいかないとき」を確認してください")
    elif a[0] in ("status", "sync") and len(a) > 1:
        from admin_user import Session
        s = Session(a[1])
        if a[0] == "sync":
            r = s.call("POST", "/drive/sync", {"force": "--force" in a}); print(json.dumps(r, ensure_ascii=False)); print("転送は非同期で進みます。数分後に status で確認してください")
        else:
            print(json.dumps(s.call("GET", "/drive/status"), ensure_ascii=False, indent=2))
    else:
        sys.exit(__doc__)
