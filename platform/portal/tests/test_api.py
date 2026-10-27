"""GL作成ポータル API の試験(moto で DynamoDB を模擬)。
  python3 -m pytest platform/portal/tests -q
"""
import json, os, shutil, sys
import pytest

HERE = os.path.dirname(os.path.abspath(__file__))
API = os.path.join(HERE, "..", "api")
os.environ.update({"TABLE_NAME": "jascc-gl-portal-test", "AWS_DEFAULT_REGION": "ap-northeast-1", "AWS_ACCESS_KEY_ID": "testing", "AWS_SECRET_ACCESS_KEY": "testing", "USER_POOL_ID": ""})
shutil.copy(os.path.join(HERE, "..", "..", "governance", "approved_plan.json"), os.path.join(API, "approved_plan.json"))
sys.path.insert(0, API)
import boto3
from moto import mock_aws
import handler as H


def ev(method, path, body=None, email="chair@example.org", groups=("統括委員会",)):
    return {"requestContext": {"http": {"method": method}, "authorizer": {"jwt": {"claims": {"email": email, "cognito:groups": "[" + " ".join(groups) + "]"}}}},
            "rawPath": path, "body": json.dumps(body, ensure_ascii=False) if body is not None else None}


def call(*a, **k):
    r = H.handler(ev(*a, **k)); return r["statusCode"], json.loads(r["body"])


@pytest.fixture
def env():
    with mock_aws():
        boto3.resource("dynamodb").create_table(TableName=H.TABLE, KeySchema=[{"AttributeName": "pk", "KeyType": "HASH"}, {"AttributeName": "sk", "KeyType": "RANGE"}],
                                                AttributeDefinitions=[{"AttributeName": "pk", "AttributeType": "S"}, {"AttributeName": "sk", "AttributeType": "S"}], BillingMode="PAY_PER_REQUEST")
        H._ddb = None
        assert call("POST", "/admin/seed")[0] == 200
        yield


def test_seed_follows_plan(env):
    c, cqs = call("GET", "/cq"); assert c == 200 and len(cqs) == 15
    assert sum(1 for x in cqs if x["kind"] == "SR") == 11 and sum(1 for x in cqs if x["kind"] == "FRQ") == 4
    assert {x["id"] for x in cqs} == {"P1", "P2", "P3", "N1", "N2", "N3", "N4", "N5", "T1", "T2", "T3", "F1", "F2", "F3", "F4"}
    c, soron = call("GET", "/soron"); assert len(soron) == 19 and soron[0]["key"] == "A" and soron[0]["author"] == "内藤"
    assert next(s for s in soron if s["key"] == "K")["title"] == "漢方・鍼灸治療"
    c, members = call("GET", "/members"); names = {m["name"] for m in members}
    assert {"華井明子", "吉田陽一郎", "古川孝広", "中川夏樹", "内藤陽一"} <= names
    plan = json.load(open(os.path.join(API, "approved_plan.json"), encoding="utf-8"))
    assert not (names & set(plan["禁止する旧体制の氏名(2023年版の体制。企画書にない)"]))  # 2023年版の体制の氏名は入らない
    assert "SR委員長" in next(m for m in members if m["name"] == "中川夏樹")["roles"]
    assert "総説執筆者" in next(m for m in members if m["name"] == "内藤陽一")["roles"]
    assert all("coi" not in json.dumps(m, ensure_ascii=False).lower() for m in members)
    # 2回目は何も増えない
    assert call("POST", "/admin/seed")[1]["created"] == 0


def test_seed_requires_admin(env):
    assert call("POST", "/admin/seed", groups=("SR委員",))[0] == 403


def test_member_email_links_tasks(env):
    assert call("PUT", "/members", {"name": "元雄良治", "roles": ["SR委員", "総説執筆者"], "email": "motoo@example.org"})[0] == 200
    c, t = call("POST", "/tasks", {"title": "P1 一次スクリーニング", "assignee": "元雄良治", "ref": "P1", "due": "2026-12-01"}); assert c == 200
    c, d = call("GET", "/dashboard", email="motoo@example.org", groups=("SR委員",))
    assert d["user"]["name"] == "元雄良治" and [x["title"] for x in d["my_tasks"]] == ["P1 一次スクリーニング"]
    assert [x["id"] for x in d["my_cq"]] == ["P1"] and [x["key"] for x in d["my_soron"]] == ["K"]
    # 本人は自分の依頼事項の状態を変えられる。他人の依頼事項は変えられない
    assert call("PUT", f"/tasks/{t['id']}", {"status": "進行中"}, email="motoo@example.org", groups=("SR委員",))[0] == 200
    assert call("PUT", f"/tasks/{t['id']}", {"status": "完了"}, email="other@example.org", groups=("SR委員",))[0] == 403


def test_cq_stage_update_by_assignee_only(env):
    call("PUT", "/members", {"name": "元雄良治", "roles": ["SR委員"], "email": "motoo@example.org"})
    call("PUT", "/members", {"name": "伊藤哲也", "roles": ["SR委員"], "email": "ito@example.org"})
    c, r = call("PUT", "/cq/P1", {"stages": {"検索": "完了", "一次スクリーニング": "進行中"}}, email="motoo@example.org", groups=("SR委員",))
    assert c == 200 and r["stages"]["検索"] == "完了" and r["progress"] == 12
    assert call("PUT", "/cq/P1", {"stages": {"検索": "未着手"}}, email="ito@example.org", groups=("SR委員",))[0] == 403
    assert call("PUT", "/cq/P1", {"stages": {"検索": "未着手"}}, email="lead@example.org", groups=("SR委員長",))[0] == 200
    assert call("PUT", "/cq/P1", {"stages": {"検索": "不正な値"}})[1]["stages"]["検索"] == "未着手"


def test_soron_update(env):
    call("PUT", "/members", {"name": "内藤陽一", "roles": ["総説執筆者"], "email": "naito@example.org"})
    c, r = call("PUT", "/soron/A", {"status": "執筆中", "due": "2027-03-31", "draft_url": "https://drive.google.com/x"}, email="naito@example.org", groups=("総説執筆者",))
    assert c == 200 and r["status"] == "執筆中"
    assert call("PUT", "/soron/A", {"author": "別の人"}, email="naito@example.org", groups=("総説執筆者",))[0] == 403  # 担当の変更は統括委員会のみ
    assert call("PUT", "/soron/B", {"status": "完了"}, email="naito@example.org", groups=("総説執筆者",))[0] == 403


def test_approval_flow_and_audit_append_only(env):
    c, a = call("POST", "/approvals", {"subject": "N1 検索式の確定", "ref": "N1", "detail": "前回Scopeを踏襲"}, email="sr@example.org", groups=("SR委員",))
    assert c == 200 and a["status"] == "申請中"
    assert call("PUT", f"/approvals/{a['id']}", {"status": "承認"}, email="lead@example.org", groups=("SR委員長",))[0] == 403
    c, r = call("PUT", f"/approvals/{a['id']}", {"status": "承認", "comment": "了承"}); assert c == 200 and r["status"] == "承認"
    assert call("PUT", f"/approvals/{a['id']}", {"status": "差戻し"})[0] == 409
    c, log = call("GET", "/audit")
    actions = [x["action"] for x in log]
    assert actions[0] == "承認" and "承認リクエスト" in actions and "初期データの作成" in actions
    assert call("DELETE", "/audit")[0] == 200  # 削除の方法はなく、一覧が返るだけ
    assert len(call("GET", "/audit")[1]) == len(log)


def test_screening_import_and_progress(env):
    call("PUT", "/members", {"name": "元雄良治", "roles": ["SR委員"], "email": "motoo@example.org"})
    data = {"reviewer": "元雄良治", "saved_at": "2026-11-01T10:00:00", "papers": [
        {"key": "1", "title": "a", "s1": {"decision": "採用"}, "ft": "未入手"},
        {"key": "2", "title": "b", "s1": {"decision": "除外", "reason": ""}},
        {"key": "3", "title": "c", "s1": {"decision": "採用"}, "s2": {"decision": "採用"}, "ft": "読了"},
        {"key": "4", "title": "d"}], "history": []}
    c, r = call("POST", "/screening/CQ1-牛車腎気丸", data, email="motoo@example.org", groups=("SR委員",))
    assert c == 200 and (r["papers"], r["s1_done"], r["s1_todo"], r["s2_done"], r["s2_todo"], r["ft_missing"], r["ft_read"], r["no_reason"]) == (4, 3, 1, 1, 1, 1, 1, 1)
    # 他人のJSONは SR委員長以上
    assert call("POST", "/screening/CQ1-牛車腎気丸", {**data, "reviewer": "菊池健"}, email="motoo@example.org", groups=("SR委員",))[0] == 403
    assert call("POST", "/screening/CQ1-牛車腎気丸", {**data, "reviewer": "菊池健"}, groups=("SR委員長",))[0] == 200
    # 古い保存は取り込まない
    assert call("POST", "/screening/CQ1-牛車腎気丸", {**data, "saved_at": "2026-10-01T00:00:00"}, email="motoo@example.org", groups=("SR委員",))[0] == 409
    c, prog = call("GET", "/screening"); assert len(prog["CQ1-牛車腎気丸"]) == 2
    c, raw = call("GET", "/screening/raw/CQ1-牛車腎気丸%23元雄良治".replace("%23", "#")); assert raw["reviewer"] == "元雄良治" and len(raw["papers"]) == 4


def test_unauthenticated(env):
    r = H.handler({"requestContext": {"http": {"method": "GET"}}, "rawPath": "/cq"}); assert r["statusCode"] == 401
