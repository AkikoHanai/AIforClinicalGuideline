"""統括委員長の利用者を Cognito に作り、統括委員会のグループに入れる。必要なら初期データ(企画書)を入れる。
  python3 platform/portal/scripts/admin_user.py <メールアドレス> <氏名>           招待メールを送る
  python3 platform/portal/scripts/admin_user.py --seed <メールアドレス>            その利用者として POST /admin/seed を実行(仮パスワードの入力を求める)
展開の出力(platform/portal/out/outputs.json)から、利用者プールと API の URL を読む。
"""
import getpass, json, os, sys, urllib.request
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


def seed(email):
    pw = getpass.getpass("パスワード(仮パスワードの場合は初回ログインで変更後のもの): ")
    r = idp.initiate_auth(ClientId=OUT["ClientId"], AuthFlow="USER_PASSWORD_AUTH", AuthParameters={"USERNAME": email, "PASSWORD": pw})
    if r.get("ChallengeName") == "NEW_PASSWORD_REQUIRED":
        new = getpass.getpass("新しいパスワード(12文字以上、大文字・小文字・数字): ")
        r = idp.respond_to_auth_challenge(ClientId=OUT["ClientId"], ChallengeName="NEW_PASSWORD_REQUIRED", Session=r["Session"], ChallengeResponses={"USERNAME": email, "NEW_PASSWORD": new})
    tok = r["AuthenticationResult"]["IdToken"]
    req = urllib.request.Request(OUT["ApiUrl"] + "/admin/seed", method="POST", headers={"Authorization": "Bearer " + tok, "Content-Type": "application/json"}, data=b"{}")
    print(urllib.request.urlopen(req).read().decode())


if __name__ == "__main__":
    a = sys.argv[1:]
    if a[:1] == ["--seed"]:
        seed(a[1])
    elif len(a) == 2:
        create(a[0], a[1])
    else:
        print(__doc__)
