"""GL作成ポータルの API(AWS Lambda)。API Gateway(HTTP API)の JWT 認可(Cognito)を通った要求だけが届く。

データは DynamoDB の1テーブル(pk, sk)に置く。
  MEMBER/<氏名>        名簿(企画書の体制)。email と Cognito のグループを持つ
  CQ/<id>              SR項目11・FRQ項目4(企画書)。段階ごとの状態
  SORON/<key>          総論A〜N(企画書)。執筆の状態
  TASK/<id>            依頼事項(担当、期限、状態)
  APPROVAL/<id>        承認リクエスト(申請、承認・差戻し)
  AUDIT/<時刻>#<id>    承認ログ。追記だけで、更新・削除の API はない
  SCREEN/<CQ>#<担当>   スクリーニング管理シートが出力する JSON(担当者ごとの最新)
  PHASE/current        現在の段階
判断(採否、バイアスリスク、推奨)は委員が行う。この API は記録と集計だけを行う。
"""
import json, os, re, time, uuid, datetime
import boto3
from boto3.dynamodb.conditions import Key

TABLE = os.environ.get("TABLE_NAME", "jascc-gl-portal")
USER_POOL = os.environ.get("USER_POOL_ID", "")
HERE = os.path.dirname(os.path.abspath(__file__))
_ddb = None

ROLE_ADMIN = {"統括委員会", "事務局"}            # 全ての編集、メンバー管理、承認の決定
ROLE_LEAD = ROLE_ADMIN | {"SR委員長"}            # CQの段階・依頼事項の編集
GROUPS = ["統括委員会", "事務局", "SR委員長", "作成グループ", "SR委員", "総説執筆者", "外部評価委員"]
CQ_STAGES = ["検索", "一次スクリーニング", "二次スクリーニング", "全文入手", "様式4-5", "様式SR-8・SoF", "EtD", "解説文"]
STAGE_STATES = ["未着手", "進行中", "完了"]
SORON_STATES = ["未着手", "執筆中", "査読中", "完了"]
TASK_STATES = ["未着手", "進行中", "完了"]
PHASES = ["STEP 1 Scope・体制", "STEP 2 検索・スクリーニング", "STEP 3 システマティックレビュー実施中", "STEP 4 推奨作成", "STEP 5 解説・総論執筆", "STEP 6 外部評価・パブリックコメント", "STEP 7 公開"]


def table():
    global _ddb
    if _ddb is None:
        _ddb = boto3.resource("dynamodb").Table(TABLE)
    return _ddb


def now():
    return datetime.datetime.now(datetime.timezone.utc).astimezone(datetime.timezone(datetime.timedelta(hours=9))).isoformat(timespec="seconds")


def new_id():
    return f"{int(time.time() * 1000):013d}-{uuid.uuid4().hex[:6]}"


def resp(code, body):
    return {"statusCode": code, "headers": {"Content-Type": "application/json; charset=utf-8"}, "body": json.dumps(body, ensure_ascii=False, default=str)}


class Forbidden(Exception):
    pass


# ---------- 利用者 ----------
def caller(event):
    claims = (((event.get("requestContext") or {}).get("authorizer") or {}).get("jwt") or {}).get("claims") or {}
    groups = claims.get("cognito:groups") or []
    if isinstance(groups, str):  # HTTP API は "[a b]" の文字列で渡すことがある
        groups = [g for g in re.split(r"[\s,\[\]]+", groups) if g]
    email = (claims.get("email") or "").lower()
    member = None
    if email:
        for m in query("MEMBER"):
            if (m.get("email") or "").lower() == email:
                member = m; break
    return {"email": email, "groups": groups, "name": (member or {}).get("name", ""), "member": member}


def require(user, roles):
    if not (set(user["groups"]) & roles):
        raise Forbidden("この操作は、" + "・".join(sorted(roles)) + " に限ります")


# ---------- DynamoDB ----------
def query(pk):
    items, kw = [], {}
    while True:
        r = table().query(KeyConditionExpression=Key("pk").eq(pk), **kw)
        items += r.get("Items", [])
        if "LastEvaluatedKey" not in r:
            return items
        kw = {"ExclusiveStartKey": r["LastEvaluatedKey"]}


def get(pk, sk):
    return table().get_item(Key={"pk": pk, "sk": sk}).get("Item")


def put(pk, sk, item):
    item = dict(item); item.update({"pk": pk, "sk": sk, "updated_at": now()})
    table().put_item(Item=item); return item


def audit(user, action, target, detail=""):
    """承認ログ。追記のみ。"""
    sk = f"{datetime.datetime.now(datetime.timezone.utc).isoformat(timespec='microseconds')}#{uuid.uuid4().hex[:6]}"  # 並び順のため精度を上げる
    table().put_item(Item={"pk": "AUDIT", "sk": sk, "at": now(), "actor": user.get("name") or user.get("email", ""), "email": user.get("email", ""),
                           "action": action, "target": target, "detail": detail}, ConditionExpression="attribute_not_exists(pk)")


# ---------- 初期データ(企画書) ----------
def seed(user):
    plan = json.load(open(os.path.join(HERE, "approved_plan.json"), encoding="utf-8"))
    n = 0
    body = plan["体制"]
    roles = {}
    for m in body["統括委員会"]: roles.setdefault(strip(m), []).append("統括委員会")
    for m in body["診療ガイドライン作成グループ委員"]: roles.setdefault(strip(m), []).append("作成グループ")
    for m in body["SRチーム委員(仮案)"]: roles.setdefault(strip(m), []).append("SR委員長" if "委員長" in m else "SR委員")
    for m in body["外部評価委員(仮)"]: roles.setdefault(strip(m), []).append("外部評価委員")
    for k, v in plan["総論"].items():
        for a in re.split("[・]", v.split(":")[-1]):
            if a and a not in ("GL委員会に依頼",):
                roles.setdefault(full_name(a, roles), []).append("総説執筆者")
    for name, rs in roles.items():
        if not get("MEMBER", name):
            put("MEMBER", name, {"name": name, "roles": sorted(set(rs)), "email": "", "note": ""}); n += 1
    for it in plan["SR項目"] + plan["FRQ項目"]:
        if not get("CQ", it["id"]):
            put("CQ", it["id"], {"id": it["id"], "kind": "SR" if it["id"][0] != "F" else "FRQ", "category": it.get("区分", "FRQ(将来の研究課題)"), "title": it["名称"],
                                 "assignees": it["担当"], "dirs": it["dir"], "stages": {s: "未着手" for s in CQ_STAGES}, "pico": {"P": "", "I": it["名称"], "C": "", "O": ""}, "note": ""}); n += 1
    for k, v in plan["総論"].items():
        if not get("SORON", k):
            title, _, author = v.rpartition(":")
            put("SORON", k, {"key": k, "label": k.replace("_", "-"), "title": title, "author": author, "status": "未着手", "due": "", "draft_url": "", "note": ""}); n += 1
    if not get("PHASE", "current"):
        put("PHASE", "current", {"phase": PHASES[1]}); n += 1
    audit(user, "初期データの作成", "企画書 Ver1", f"{n}件")
    return {"created": n}


def strip(s):
    return re.sub(r"\(.*?\)", "", s).strip()


def full_name(short, roles):
    """総論の担当(姓)を、名簿の氏名に合わせる。"""
    for n in roles:
        if n.startswith(short) or n == short:
            return n
    return short


# ---------- 集計 ----------
def cq_progress(cq):
    done = sum(1 for s in CQ_STAGES if cq.get("stages", {}).get(s) == "完了")
    return round(100 * done / len(CQ_STAGES))


def screening_progress(d):
    P = d.get("papers", [])
    s1 = lambda p: (p.get("s1") or {}).get("decision", "")
    s2 = lambda p: (p.get("s2") or {}).get("decision", "")
    need2 = lambda p: (s1(p) in ("採用", "保留") or p.get("direct")) and not s2(p)
    targ = lambda p: s2(p) == "採用" or need2(p)
    return {"reviewer": d.get("reviewer", ""), "saved_at": d.get("saved_at", ""), "papers": len(P),
            "s1_done": sum(1 for p in P if s1(p)), "s1_todo": sum(1 for p in P if not s1(p) and not p.get("direct")),
            "s2_done": sum(1 for p in P if s2(p)), "s2_todo": sum(1 for p in P if need2(p)),
            "ft_missing": sum(1 for p in P if targ(p) and (p.get("ft") or "未入手") == "未入手"),
            "ft_read": sum(1 for p in P if targ(p) and p.get("ft") == "読了"),
            "no_reason": sum(1 for p in P if (s1(p) == "除外" and not (p.get("s1") or {}).get("reason", "").strip()) or (s2(p) == "除外" and not (p.get("s2") or {}).get("reason", "").strip()))}


def dashboard(user):
    cqs = sorted(query("CQ"), key=lambda c: c["id"])
    soron = sorted(query("SORON"), key=lambda s: s["key"])
    tasks = query("TASK")
    mine = [t for t in tasks if user["name"] and t.get("assignee") == user["name"] and t.get("status") != "完了"]
    my_cq = [c for c in cqs if user["name"] and any(user["name"].startswith(a) for a in c.get("assignees", []))]
    my_soron = [s for s in soron if user["name"] and any(user["name"].startswith(a) for a in re.split("[・]", s.get("author", "")))]
    approvals = [a for a in query("APPROVAL") if a.get("status") == "申請中"]
    audits = sorted(query("AUDIT"), key=lambda a: a["sk"], reverse=True)[:20]
    return {"user": {"name": user["name"], "email": user["email"], "groups": user["groups"]}, "phase": (get("PHASE", "current") or {}).get("phase", ""),
            "my_tasks": mine, "my_cq": [{"id": c["id"], "title": c["title"], "progress": cq_progress(c)} for c in my_cq],
            "my_soron": [{"key": s["key"], "label": s["label"], "title": s["title"], "status": s["status"]} for s in my_soron],
            "pending_approvals": approvals, "cq": [{**c, "progress": cq_progress(c)} for c in cqs],
            "soron_summary": {st: sum(1 for s in soron if s.get("status") == st) for st in SORON_STATES}, "audit": audits}


# ---------- ルーティング ----------
def handler(event, context=None):
    method = (event.get("requestContext") or {}).get("http", {}).get("method") or event.get("httpMethod", "GET")
    path = re.sub(r"^/(prod|v1)", "", event.get("rawPath") or event.get("path") or "/")
    body = {}
    if event.get("body"):
        try:
            body = json.loads(event["body"])
        except Exception:
            return resp(400, {"error": "JSONではありません"})
    try:
        user = caller(event)
        if not user["email"]:
            return resp(401, {"error": "ログインが必要です"})
        return route(method, path, body, user)
    except Forbidden as e:
        return resp(403, {"error": str(e)})
    except KeyError as e:
        return resp(400, {"error": f"項目がありません: {e}"})


def route(method, path, body, user):
    parts = [p for p in path.split("/") if p]
    head = parts[0] if parts else ""
    if head == "me":
        return resp(200, {"name": user["name"], "email": user["email"], "groups": user["groups"], "member": user["member"]})
    if head == "dashboard":
        return resp(200, dashboard(user))
    if head == "meta":
        return resp(200, {"stages": CQ_STAGES, "stage_states": STAGE_STATES, "soron_states": SORON_STATES, "task_states": TASK_STATES, "phases": PHASES, "groups": GROUPS})
    if head == "admin" and len(parts) > 1 and parts[1] == "seed" and method == "POST":
        require(user, ROLE_ADMIN); return resp(200, seed(user))
    if head == "phase":
        if method == "PUT":
            require(user, ROLE_ADMIN)
            if body["phase"] not in PHASES: return resp(400, {"error": "段階の値が不正です"})
            put("PHASE", "current", {"phase": body["phase"]}); audit(user, "段階の変更", "全体", body["phase"]); return resp(200, {"ok": True})
        return resp(200, get("PHASE", "current") or {})
    if head == "members":
        return members(method, parts, body, user)
    if head == "cq":
        return cq(method, parts, body, user)
    if head == "soron":
        return soron(method, parts, body, user)
    if head == "tasks":
        return tasks(method, parts, body, user)
    if head == "approvals":
        return approvals(method, parts, body, user)
    if head == "audit":
        return resp(200, sorted(query("AUDIT"), key=lambda a: a["sk"], reverse=True))
    if head == "screening":
        return screening(method, parts, body, user)
    return resp(404, {"error": "ありません"})


def members(method, parts, body, user):
    if method == "GET":
        return resp(200, sorted(query("MEMBER"), key=lambda m: m["name"]))
    require(user, ROLE_ADMIN)
    name = body["name"].strip()
    if method in ("POST", "PUT"):
        old = get("MEMBER", name) or {"name": name}
        item = {**old, "roles": body.get("roles", old.get("roles", [])), "email": body.get("email", old.get("email", "")).strip().lower(), "note": body.get("note", old.get("note", ""))}
        put("MEMBER", name, item)
        invited = False
        if body.get("invite") and item["email"] and USER_POOL:
            invited = invite(item["email"], name, item["roles"])
        audit(user, "名簿の更新" + ("と招待" if invited else ""), name, f"役割: {'・'.join(item['roles'])}")
        return resp(200, {**item, "invited": invited})
    if method == "DELETE":
        table().delete_item(Key={"pk": "MEMBER", "sk": name}); audit(user, "名簿から削除", name); return resp(200, {"ok": True})
    return resp(405, {"error": "方法が不正です"})


def invite(email, name, roles):
    """Cognito に利用者を作り、招待メールを送る。既にある場合はグループだけ合わせる。"""
    idp = boto3.client("cognito-idp")
    try:
        idp.admin_create_user(UserPoolId=USER_POOL, Username=email, UserAttributes=[{"Name": "email", "Value": email}, {"Name": "email_verified", "Value": "true"}, {"Name": "name", "Value": name}],
                              DesiredDeliveryMediums=["EMAIL"])
    except idp.exceptions.UsernameExistsException:
        pass
    current = {g["GroupName"] for g in idp.admin_list_groups_for_user(Username=email, UserPoolId=USER_POOL).get("Groups", [])}
    for g in set(roles) - current:
        idp.admin_add_user_to_group(UserPoolId=USER_POOL, Username=email, GroupName=g)
    for g in current - set(roles):
        idp.admin_remove_user_from_group(UserPoolId=USER_POOL, Username=email, GroupName=g)
    return True


def cq(method, parts, body, user):
    if method == "GET":
        if len(parts) > 1:
            c = get("CQ", parts[1]); return resp(200, {**c, "progress": cq_progress(c)}) if c else resp(404, {"error": "ありません"})
        return resp(200, [{**c, "progress": cq_progress(c)} for c in sorted(query("CQ"), key=lambda c: c["id"])])
    if method == "PUT" and len(parts) > 1:
        c = get("CQ", parts[1])
        if not c: return resp(404, {"error": "ありません"})
        own = user["name"] and any(user["name"].startswith(a) for a in c.get("assignees", []))
        if not own: require(user, ROLE_LEAD)
        changes = []
        if "stages" in body:
            for s, v in body["stages"].items():
                if s in CQ_STAGES and v in STAGE_STATES and c["stages"].get(s) != v:
                    changes.append(f"{s}: {c['stages'].get(s)}→{v}"); c["stages"][s] = v
        if "pico" in body:
            c["pico"] = {k: str(body["pico"].get(k, c["pico"].get(k, ""))) for k in "PICO"}; changes.append("PICO")
        if "note" in body:
            c["note"] = str(body["note"]); changes.append("備考")
        put("CQ", c["id"], c); audit(user, "CQの更新", c["id"], "、".join(changes)); return resp(200, {**c, "progress": cq_progress(c)})
    return resp(405, {"error": "方法が不正です"})


def soron(method, parts, body, user):
    if method == "GET":
        return resp(200, sorted(query("SORON"), key=lambda s: s["key"]))
    if method == "PUT" and len(parts) > 1:
        s = get("SORON", parts[1])
        if not s: return resp(404, {"error": "ありません"})
        own = user["name"] and any(user["name"].startswith(a) for a in re.split("[・]", s.get("author", "")) if a)
        if not own: require(user, ROLE_LEAD)
        changes = []
        if "status" in body and body["status"] in SORON_STATES and body["status"] != s["status"]:
            changes.append(f"状態: {s['status']}→{body['status']}"); s["status"] = body["status"]
        for k in ("due", "draft_url", "note"):
            if k in body: s[k] = str(body[k]); changes.append({"due": "期限", "draft_url": "原稿", "note": "備考"}[k])
        if "author" in body:
            require(user, ROLE_ADMIN); s["author"] = str(body["author"]); changes.append("担当(企画書の変更は統括委員会の承認が必要)")
        put("SORON", s["key"], s); audit(user, "総論の更新", f"総論{s['label']}", "、".join(changes)); return resp(200, s)
    return resp(405, {"error": "方法が不正です"})


def tasks(method, parts, body, user):
    if method == "GET":
        return resp(200, sorted(query("TASK"), key=lambda t: (t.get("status") == "完了", t.get("due") or "9999", t["sk"])))
    if method == "POST":
        require(user, ROLE_LEAD)
        t = {"id": new_id(), "title": body["title"], "assignee": body.get("assignee", ""), "ref": body.get("ref", ""), "due": body.get("due", ""), "status": "未着手", "created_by": user["name"] or user["email"], "note": body.get("note", "")}
        put("TASK", t["id"], t); audit(user, "依頼事項の作成", t["assignee"] or "(未割当)", t["title"]); return resp(200, t)
    if method == "PUT" and len(parts) > 1:
        t = get("TASK", parts[1])
        if not t: return resp(404, {"error": "ありません"})
        if t.get("assignee") != user["name"]: require(user, ROLE_LEAD)
        changes = []
        if "status" in body and body["status"] in TASK_STATES and body["status"] != t["status"]:
            changes.append(f"状態: {t['status']}→{body['status']}"); t["status"] = body["status"]
        for k in ("title", "assignee", "due", "note", "ref"):
            if k in body and set(user["groups"]) & ROLE_LEAD: t[k] = str(body[k]); changes.append(k)
        put("TASK", t["id"], t); audit(user, "依頼事項の更新", t["title"], "、".join(changes)); return resp(200, t)
    return resp(405, {"error": "方法が不正です"})


def approvals(method, parts, body, user):
    if method == "GET":
        return resp(200, sorted(query("APPROVAL"), key=lambda a: a["sk"], reverse=True))
    if method == "POST":
        a = {"id": new_id(), "subject": body["subject"], "detail": body.get("detail", ""), "ref": body.get("ref", ""), "requester": user["name"] or user["email"], "status": "申請中", "requested_at": now(), "decided_by": "", "decided_at": "", "comment": ""}
        put("APPROVAL", a["id"], a); audit(user, "承認リクエスト", a["subject"], a["detail"]); return resp(200, a)
    if method == "PUT" and len(parts) > 1:
        require(user, {"統括委員会"})
        a = get("APPROVAL", parts[1])
        if not a: return resp(404, {"error": "ありません"})
        if a["status"] != "申請中": return resp(409, {"error": "既に決定済みです"})
        if body["status"] not in ("承認", "差戻し"): return resp(400, {"error": "承認 または 差戻し"})
        a.update({"status": body["status"], "decided_by": user["name"] or user["email"], "decided_at": now(), "comment": body.get("comment", "")})
        put("APPROVAL", a["id"], a); audit(user, body["status"], a["subject"], a["comment"]); return resp(200, a)
    return resp(405, {"error": "方法が不正です"})


def screening(method, parts, body, user):
    """スクリーニング管理シート(render_screening.py)が出力する JSON を受け取り、担当者別の進捗を返す。判定の内容は変えない。"""
    if method == "GET":
        items = query("SCREEN")
        if len(parts) > 1 and parts[1] == "raw" and len(parts) > 2:
            it = get("SCREEN", parts[2]); return resp(200, it["data"] if it else {})
        out = {}
        for it in items:
            out.setdefault(it["cq"], []).append({**screening_progress(it["data"]), "sk": it["sk"], "uploaded_by": it.get("uploaded_by", "")})
        return resp(200, out)
    if method == "POST" and len(parts) > 1:
        cq_dir = parts[1]
        d = body
        if not isinstance(d.get("papers"), list) or not d.get("reviewer"):
            return resp(400, {"error": "スクリーニング管理シートの JSON(reviewer, papers)が必要です"})
        reviewer = d["reviewer"]
        if reviewer != user["name"]: require(user, ROLE_LEAD)
        sk = f"{cq_dir}#{reviewer}"
        old = get("SCREEN", sk)
        if old and (old["data"].get("saved_at") or "") > (d.get("saved_at") or ""):
            return resp(409, {"error": "保存済みの方が新しいため、取り込みません"})
        put("SCREEN", sk, {"cq": cq_dir, "reviewer": reviewer, "uploaded_by": user["name"] or user["email"], "data": d})
        pr = screening_progress(d)
        audit(user, "スクリーニングJSONの取り込み", f"{cq_dir} / {reviewer}", f"文献{pr['papers']}件、一次判定済{pr['s1_done']}、二次判定済{pr['s2_done']}")
        return resp(200, pr)
    return resp(405, {"error": "方法が不正です"})
