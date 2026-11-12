"""GL作成ポータルの API(AWS Lambda)。API Gateway(HTTP API)の JWT 認可(Cognito)を通った要求だけが届く。
CIPN診療ガイドライン2023年版の作成手順(Minds)を踏襲する。判断は委員が行い、この API は記録・集計・下書きの生成だけを行う。

DynamoDB 1テーブル(pk, sk):
  USER/<email>                利用者(氏名、役割)。名簿・COIはGoogleフォーム・ドライブで管理し、ここには置かない
  CQ/<id>                     SR項目11・FRQ項目4(企画書)。PICO、アウトカム一覧、段階
  PAPER/<cq>#<pmid>           登録した論文。PDFは S3(papers/<cq>/<pmid>.pdf)、本文の段落は S3(text/<cq>/<pmid>.json)。研究特性
  F45/<cq>#<pmid>#<outcome>#<評価者>   様式4-5。評価者= 委員の氏名 / "AI"(下書き) / "確定"(照合の結果)
  SR8/<cq>#<outcome>          様式SR-8(エビデンス総体)
  ETD/<cq>                    EtD(2023年版の体裁: 推奨文、強さ、確実性、4つの考慮事項、投票)
  GL2023/<cq>                 2023年版の記述(推奨文・解説・投票。build_etd.py の etd_2023.json を取り込む)
  SORON/<key>                 総論A〜N(企画書)
  SCREEN/<cq>#<担当>          スクリーニング管理シートの JSON
  AUDIT/<時刻>#<id>           作成経過の記録。追記のみ
  PHASE/current               現在の段階
"""
import base64, datetime, json, os, re, time, uuid
import boto3
from boto3.dynamodb.conditions import Key

TABLE = os.environ.get("TABLE_NAME", "jascc-gl-portal")
BUCKET = os.environ.get("PAPERS_BUCKET", "")
USER_POOL = os.environ.get("USER_POOL_ID", "")
FUNCTION = os.environ.get("AWS_LAMBDA_FUNCTION_NAME", "")
HERE = os.path.dirname(os.path.abspath(__file__))
_ddb = None

ROLE_ADMIN = {"統括委員会", "事務局"}
ROLE_LEAD = ROLE_ADMIN | {"SR委員長"}
ROLE_GROUP = {"統括委員会", "作成グループ"}  # 推奨作成(EtD・投票)
GROUPS = ["統括委員会", "事務局", "SR委員長", "作成グループ", "SR委員", "総説執筆者", "外部評価委員"]
CQ_STAGES = ["CQ確定", "論文登録", "様式4-5", "様式SR-8", "EtD"]  # 表示は記録された件数だけ。推測の状態は出さない
SORON_STATES = ["原稿未提出", "執筆中", "査読中", "修正中", "完了"]  # 記録に基づく状態だけ
PHASES = ["STEP 1 Scope・体制", "STEP 2 検索・スクリーニング", "STEP 3 システマティックレビュー実施中", "STEP 4 推奨作成", "STEP 5 解説・総論執筆", "STEP 6 外部評価・パブリックコメント", "STEP 7 公開"]
ITEM_KEYS = ["randomization", "concealment", "blinding_participants", "blinding_assessors", "itt", "incomplete_outcome", "selective_reporting", "early_stopping", "other_bias", "bias_summary",
             "ind_population", "ind_intervention", "ind_comparator", "ind_outcome", "ind_summary"]
ITEM_JA = ["ランダム化", "コンシールメント", "盲検化(参加者・医療提供者)", "盲検化(アウトカム評価者)", "ITT", "アウトカム不完全報告", "選択的アウトカム報告", "早期試験中止", "その他のバイアス", "バイアスリスク まとめ",
           "非直接性 対象", "非直接性 介入", "非直接性 対照", "非直接性 アウトカム", "非直接性 まとめ"]
CHEMO_CLASSES = ["白金製剤", "タキサン系", "ビンカアルカロイド", "ボルテゾミブ等", "混在", "不明"]  # 用語の定義(6区分)
SR8_KEYS = ["rob", "inconsistency", "imprecision", "indirectness", "publication_bias", "upgrade", "certainty"]
SR8_JA = ["バイアスリスク", "非一貫性", "不精確性", "非直接性", "その他(出版バイアス)", "上昇要因", "エビデンスの確実性(A〜D)"]
ETD_CONSIDERATIONS = [("benefit_harm", "益と害のバランス"), ("certainty", "エビデンスの確実性"), ("values", "患者の価値観・希望"), ("cost", "コスト・資源")]
STRENGTH = ["1 強く推奨", "2 弱く推奨", "3 推奨なし", "4 行わないことを弱く推奨", "5 行わないことを強く推奨"]  # 用語の定義
CERT = ["A(強)", "B(中)", "C(弱)", "D(非常に弱い)"]  # 用語の定義


def table():
    global _ddb
    if _ddb is None:
        _ddb = boto3.resource("dynamodb").Table(TABLE)
    return _ddb


def s3():
    from botocore.config import Config
    return boto3.client("s3", config=Config(signature_version="s3v4"))


def now():
    return datetime.datetime.now(datetime.timezone(datetime.timedelta(hours=9))).isoformat(timespec="seconds")


def new_id():
    return f"{int(time.time() * 1000):013d}-{uuid.uuid4().hex[:6]}"


def resp(code, body):
    return {"statusCode": code, "headers": {"Content-Type": "application/json; charset=utf-8"}, "body": json.dumps(body, ensure_ascii=False, default=_dec)}


def _dec(o):
    import decimal
    if isinstance(o, decimal.Decimal):
        return int(o) if o == int(o) else float(o)
    return str(o)


def _py(o):
    """DynamoDB が受け付けない float を Decimal に変える"""
    import decimal
    if isinstance(o, float): return decimal.Decimal(str(o))
    if isinstance(o, dict): return {k: _py(v) for k, v in o.items()}
    if isinstance(o, list): return [_py(v) for v in o]
    return o


class Forbidden(Exception):
    pass


# ---------- 利用者 ----------
def caller(event):
    claims = (((event.get("requestContext") or {}).get("authorizer") or {}).get("jwt") or {}).get("claims") or {}
    groups = claims.get("cognito:groups") or []
    if isinstance(groups, str):
        groups = [g for g in re.split(r"[\s,\[\]]+", groups) if g]
    email = (claims.get("email") or "").lower()
    u = get("USER", email) if email else None
    name = (u or {}).get("name") or claims.get("name") or ""
    return {"email": email, "groups": groups, "name": name}


def require(user, roles):
    if not (set(user["groups"]) & roles):
        raise Forbidden("この操作は、" + "・".join(sorted(roles)) + " に限ります")


# ---------- DynamoDB ----------
def query(pk, prefix=None):
    items, kw = [], {}
    cond = Key("pk").eq(pk) & Key("sk").begins_with(prefix) if prefix else Key("pk").eq(pk)
    while True:
        r = table().query(KeyConditionExpression=cond, **kw)
        items += r.get("Items", [])
        if "LastEvaluatedKey" not in r:
            return items
        kw = {"ExclusiveStartKey": r["LastEvaluatedKey"]}


def get(pk, sk):
    return table().get_item(Key={"pk": pk, "sk": sk}).get("Item")


def put(pk, sk, item):
    item = dict(item); item.update({"pk": pk, "sk": sk, "updated_at": now()})
    table().put_item(Item=_py(item)); return item


def audit(user, action, target, detail=""):
    """作成経過の記録。追記のみ。"""
    sk = f"{datetime.datetime.now(datetime.timezone.utc).isoformat(timespec='microseconds')}#{uuid.uuid4().hex[:6]}"
    table().put_item(Item={"pk": "AUDIT", "sk": sk, "at": now(), "actor": user.get("name") or user.get("email", ""), "email": user.get("email", ""), "action": action, "target": target, "detail": detail[:1000]},
                     ConditionExpression="attribute_not_exists(pk)")


# ---------- 初期データ(企画書) ----------
def strip(s):
    return re.sub(r"\(.*?\)", "", s).strip()


def seed(user):
    plan = json.load(open(os.path.join(HERE, "approved_plan.json"), encoding="utf-8"))
    n = 0
    for it in plan["SR項目"] + plan["FRQ項目"]:
        if not get("CQ", it["id"]):
            put("CQ", it["id"], {"id": it["id"], "kind": "SR" if it["id"][0] != "F" else "FRQ", "category": it.get("区分", "FRQ"), "title": it["名称"], "assignees": it["担当"], "dirs": it["dir"],
                                 "approved": "統括委員長承認済み(企画書 Ver1 2026-06-17)", "pico": {"P": "", "I": it["名称"], "C": "", "O": ""}, "outcomes": [], "note": ""}); n += 1
    for k, v in plan["総論"].items():
        if not get("SORON", k):
            title, _, author = v.rpartition(":")
            put("SORON", k, {"key": k, "label": k.replace("_", "-"), "title": title, "author": author, "status": "原稿未提出", "due": "", "note": ""}); n += 1
    if not get("PHASE", "current"):
        put("PHASE", "current", {"phase": PHASES[2]}); n += 1  # CQ・FRQは承認済み。SRの実施中
    audit(user, "初期データの作成", "企画書 Ver1", f"{n}件")
    return {"created": n}


# ---------- 集計 ----------
def cq_records(cq):
    """1つの CQ について記録を読み、件数にする。推測はしない。
    戻り値: (counts, units)。units: (PMID, アウトカム) → {"submitted": [提出した評価者], "final": 確定の記録の有無}"""
    cqid = cq["id"]; outs = cq.get("outcomes") or []
    papers = query("PAPER", f"{cqid}#")
    units = {}
    for r in query("F45", f"{cqid}#"):
        base, reviewer = r["sk"].rsplit("#", 1); _, pmid, outcome = base.split("#", 2)
        u = units.setdefault((pmid, outcome), {"submitted": [], "final": False})
        if reviewer == "確定": u["final"] = True
        elif reviewer != "AI" and r.get("submitted"): u["submitted"].append(reviewer)
    wait = sorted(({"pmid": pm, "outcome": o, "submitted": sorted(u["submitted"])} for (pm, o), u in units.items() if len(u["submitted"]) >= 2 and not u["final"]), key=lambda w: (w["pmid"], w["outcome"]))
    etd = get("ETD", cqid)
    counts = {"outcomes": len(outs), "papers": len(papers), "extracted": sum(1 for p in papers if str(p.get("status", "")).startswith("本文抽出済")),
              "f45_need": len(papers) * len(outs), "f45_submitted": sum(len(u["submitted"]) for u in units.values()), "f45_fixed": sum(1 for u in units.values() if u["final"]),
              "f45_wait": wait, "sr8": sum(1 for r in query("SR8", f"{cqid}#") if r.get("certainty")),
              "etd_status": (etd.get("status", "下書き") if etd else ""), "etd_agreement": ((etd.get("vote") or {}).get("agreement") if etd else None)}
    return counts, units, papers


def stage_text(n):
    """件数(cq_records)を、段階ごとの文字にする。"""
    return {"CQ確定": "承認済み(統括委員長)",
            "論文登録": f"{n['papers']}件(本文抽出済 {n['extracted']}件)" if n["papers"] else "記録なし",
            "様式4-5": (f"確定 {n['f45_fixed']}/{n['f45_need']}(提出 {n['f45_submitted']})" if n["f45_need"] else ("アウトカム未登録" if n["papers"] else "記録なし")),
            "様式SR-8": (f"確実性 記入 {n['sr8']}/{n['outcomes']}" if n["outcomes"] else "記録なし"),
            "EtD": n["etd_status"] or "記録なし"}


def stage_auto(cq):
    """記録された件数から、各段階の状態を文字で返す。推測はしない。"""
    return stage_text(cq_records(cq)[0])


def progress(st):
    """確定した様式4-5の割合(記録がなければ None)。"""
    m = re.match(r"確定 (\d+)/(\d+)", st.get("様式4-5", ""))
    return round(100 * int(m.group(1)) / int(m.group(2))) if m and int(m.group(2)) else None


def dashboard(user):
    """進捗ボード。記録された件数、自分の作業、承認(確定)の記録がない件を返す。SR の流れと総説の流れは、役割で分ける。"""
    g = set(user["groups"]); name = user["name"]; lead = bool(g & ROLE_LEAD)
    sr_view = bool(g & (ROLE_LEAD | {"SR委員", "作成グループ"})); soron_view = bool(g & (ROLE_ADMIN | {"総説執筆者"}))
    out_cq, todo, approvals = [], [], []
    for c in (sorted(query("CQ"), key=lambda c: c["id"]) if sr_view else []):
        n, units, papers = cq_records(c); st = stage_text(n); mine = is_assignee(user, c)
        wait = n.pop("f45_wait"); n["f45_wait"] = len(wait)
        out_cq.append({**c, "stages": st, "progress": progress(st), "counts": n, "mine": mine})
        if mine:
            for p in papers:
                for o in c.get("outcomes") or []:
                    if name not in units.get((p["pmid"], o), {}).get("submitted", []):
                        todo.append({"cq": c["id"], "pmid": p["pmid"], "title": p.get("title", ""), "outcome": o})
        if lead or mine:
            for w in wait:
                approvals.append({"kind": "様式4-5の照合・確定", "target": f"{c['id']} PMID {w['pmid']} / {w['outcome']}", "record": "2名が提出済(" + "・".join(w["submitted"]) + ")。確定の記録なし",
                                  "approver": "評価した2名、またはSR委員長", "can": lead or name in w["submitted"], "page": "f45", "q": {"cq": c["id"], "pmid": w["pmid"], "outcome": w["outcome"]}})
        if n["etd_status"] == "協議中":
            approvals.append({"kind": "EtD・推奨の確定", "target": f"{c['id']} {c['title']}", "record": "状態 協議中。" + (f"投票 合意率 {n['etd_agreement']}%" if n["etd_agreement"] is not None else "投票の記録なし"),
                              "approver": "統括委員会", "can": "統括委員会" in g, "page": "etd", "q": {"cq": c["id"]}})
    soron = sorted(query("SORON"), key=lambda s: s["key"]) if soron_view else []
    is_author = lambda s: bool(name) and any(name.startswith(a) for a in re.split("[・]", s.get("author", "")) if a)
    my_soron = [s for s in soron if is_author(s)]
    for s in soron:
        if s.get("status") == "査読中" and (g & ROLE_ADMIN or is_author(s)):
            approvals.append({"kind": "総論の査読・完了", "target": f"総論{s['label']} {s['title']}", "record": "状態 査読中。" + (f"原稿 {s['file']}" if s.get("file") else "原稿の記録なし"),
                              "approver": "統括委員会(査読コメントは統括委員会・事務局)", "can": bool(g & ROLE_ADMIN), "page": "soron", "q": {}})
    return {"user": user, "phase": (get("PHASE", "current") or {}).get("phase", ""), "cq": out_cq, "my_cq": [{"id": c["id"], "title": c["title"], "progress": c["progress"]} for c in out_cq if c["mine"]],
            "my_f45_todo": todo[:50], "my_f45_todo_count": len(todo), "approvals": approvals[:200], "approvals_count": len(approvals),
            "my_soron": [{"key": s["key"], "label": s["label"], "title": s["title"], "status": s["status"]} for s in my_soron],
            "soron_summary": {st: sum(1 for s in soron if s.get("status") == st) for st in SORON_STATES},
            "audit": sorted(query("AUDIT"), key=lambda a: a["sk"], reverse=True)[:20]}


# ---------- ルーティング ----------
def handler(event, context=None):
    if event.get("task") == "draft45":  # 非同期の下書き(自分自身を invoke)
        return run_draft45(event)
    if event.get("task") == "draft_etd":
        return run_draft_etd(event)
    method = (event.get("requestContext") or {}).get("http", {}).get("method") or event.get("httpMethod", "GET")
    path = event.get("rawPath") or event.get("path") or "/"
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
        return route(method, [p for p in path.split("/") if p], body, user)
    except Forbidden as e:
        return resp(403, {"error": str(e)})
    except KeyError as e:
        return resp(400, {"error": f"項目がありません: {e}"})


SORON_ONLY = {"me", "meta", "dashboard", "soron", "audit"}  # 総説執筆者だけの利用者が使える範囲(SRの流れとは分離)
SR_ONLY = {"me", "meta", "dashboard", "cq", "papers", "f45", "sr8", "etd", "gl2023", "screening", "audit", "export"}


def route(method, parts, body, user):
    head = parts[0] if parts else ""
    g = set(user["groups"])
    if g and g <= {"総説執筆者", "外部評価委員"} and head not in SORON_ONLY:
        raise Forbidden("総説の流れの画面だけを利用できます")
    if g and g <= {"SR委員"} and head not in SR_ONLY:
        raise Forbidden("SRの流れの画面だけを利用できます")
    if head == "me":
        return resp(200, user)
    if head == "meta":
        return resp(200, {"stages": CQ_STAGES, "soron_states": SORON_STATES, "phases": PHASES, "groups": GROUPS, "item_keys": ITEM_KEYS, "item_ja": ITEM_JA,
                          "chemo_classes": CHEMO_CLASSES, "sr8_keys": SR8_KEYS, "sr8_ja": SR8_JA, "etd_considerations": ETD_CONSIDERATIONS, "strength": STRENGTH, "cert": CERT})
    if head == "dashboard":
        return resp(200, dashboard(user))
    if head == "admin" and parts[1:2] == ["seed"] and method == "POST":
        require(user, ROLE_ADMIN); return resp(200, seed(user))
    if head == "phase":
        if method == "PUT":
            require(user, ROLE_ADMIN)
            if body["phase"] not in PHASES: return resp(400, {"error": "段階の値が不正です"})
            put("PHASE", "current", {"phase": body["phase"]}); audit(user, "段階の変更", "全体", body["phase"]); return resp(200, {"ok": True})
        return resp(200, get("PHASE", "current") or {})
    if head == "users":
        return users(method, parts, body, user)
    if head == "cq":
        return cq(method, parts, body, user)
    if head == "papers":
        return papers(method, parts, body, user)
    if head == "f45":
        return f45(method, parts, body, user)
    if head == "sr8":
        return sr8(method, parts, body, user)
    if head == "etd":
        return etd(method, parts, body, user)
    if head == "gl2023" and parts[1:2] == ["soron"]:
        return gl2023_soron(method, parts, body, user)
    if head == "gl2023":
        return gl2023(method, parts, body, user)
    if head == "export":
        return export(method, parts, body, user)
    if head == "soron":
        return soron(method, parts, body, user)
    if head == "screening":
        return screening(method, parts, body, user)
    if head == "audit":
        return resp(200, sorted(query("AUDIT"), key=lambda a: a["sk"], reverse=True))
    return resp(404, {"error": "ありません"})


# ---------- 利用者(ログイン用。名簿ではない) ----------
def users(method, parts, body, user):
    if method == "GET":
        return resp(200, sorted(query("USER"), key=lambda u: u.get("name", "")))
    require(user, ROLE_ADMIN)
    if method in ("POST", "PUT"):
        email = body["email"].strip().lower(); name = body["name"].strip(); roles = [g for g in body.get("roles", []) if g in GROUPS]
        put("USER", email, {"email": email, "name": name, "roles": roles})
        invited = invite(email, name, roles) if body.get("invite") and USER_POOL else False
        audit(user, "利用者の登録" + ("と招待" if invited else ""), name, "役割: " + "・".join(roles)); return resp(200, {"email": email, "name": name, "roles": roles, "invited": invited})
    if method == "DELETE" and len(parts) > 1:
        table().delete_item(Key={"pk": "USER", "sk": parts[1].lower()}); audit(user, "利用者の削除", parts[1]); return resp(200, {"ok": True})
    return resp(405, {"error": "方法が不正です"})


def invite(email, name, roles):
    idp = boto3.client("cognito-idp")
    try:
        idp.admin_create_user(UserPoolId=USER_POOL, Username=email, UserAttributes=[{"Name": "email", "Value": email}, {"Name": "email_verified", "Value": "true"}, {"Name": "name", "Value": name}],
                              DesiredDeliveryMediums=["EMAIL"])
    except idp.exceptions.UsernameExistsException:
        idp.admin_update_user_attributes(UserPoolId=USER_POOL, Username=email, UserAttributes=[{"Name": "name", "Value": name}])
    current = {g["GroupName"] for g in idp.admin_list_groups_for_user(Username=email, UserPoolId=USER_POOL).get("Groups", [])}
    for g in set(roles) - current: idp.admin_add_user_to_group(UserPoolId=USER_POOL, Username=email, GroupName=g)
    for g in current - set(roles): idp.admin_remove_user_from_group(UserPoolId=USER_POOL, Username=email, GroupName=g)
    return True


# ---------- CQ ----------
def is_assignee(user, c):
    return bool(user["name"]) and any(user["name"].startswith(a) for a in c.get("assignees", []))


def cq(method, parts, body, user):
    if method == "GET":
        if len(parts) > 1:
            c = get("CQ", parts[1])
            if not c: return resp(404, {"error": "ありません"})
            st = stage_auto(c); return resp(200, {**c, "stages": st, "progress": progress(st)})
        out = []
        for c in sorted(query("CQ"), key=lambda c: c["id"]):
            c.setdefault("approved", "統括委員長承認済み(企画書 Ver1 2026-06-17)"); c.pop("stages", None); st = stage_auto(c)
            out.append({**c, "stages": st, "progress": progress(st)})
        return resp(200, out)
    if method == "PUT" and len(parts) > 1:
        c = get("CQ", parts[1])
        if not c: return resp(404, {"error": "ありません"})
        if not is_assignee(user, c): require(user, ROLE_LEAD)
        ch = []
        if "pico" in body: c["pico"] = {k: str(body["pico"].get(k, c["pico"].get(k, ""))) for k in "PICO"}; ch.append("PICO")
        if "outcomes" in body: c["outcomes"] = [str(o).strip() for o in body["outcomes"] if str(o).strip()]; ch.append("アウトカム: " + "、".join(c["outcomes"]))
        if "note" in body: c["note"] = str(body["note"]); ch.append("備考")
        put("CQ", c["id"], c); audit(user, "CQの更新", c["id"], "、".join(ch)); st = stage_auto(c); return resp(200, {**c, "stages": st, "progress": progress(st)})
    return resp(405, {"error": "方法が不正です"})


# ---------- 論文(PDF登録・本文) ----------
def paper_key(cqid, pmid):
    return f"{cqid}#{pmid}"


def save_text(user, cqid, pmid, p, pages, source):
    from extract_text import paragraphs, quality
    paras = paragraphs(pmid, pages); status = quality(pages, paras)
    if source != "pypdf": status = status.replace("本文抽出済", f"本文抽出済({source})")
    text_key = f"text/{cqid}/{pmid}.json"
    s3().put_object(Bucket=BUCKET, Key=text_key, Body=json.dumps({"pmid": pmid, "pages": len(pages), "source": source, "paragraphs": paras}, ensure_ascii=False).encode(), ContentType="application/json")
    secs = {s: sum(1 for x in paras if x["section"] == s) for s in ("abstract", "methods", "results", "discussion", "other")}
    p.update({"text_key": text_key, "status": status, "pages": len(pages), "n_paragraphs": len(paras), "sections": secs, "text_source": source}); put("PAPER", p["sk"], p)
    audit(user, "本文の抽出", f"{cqid} / PMID {pmid}", f"{source}: {len(pages)}ページ、{len(paras)}段落(Method {secs['methods']}、Result {secs['results']})。{status}")
    return resp(200, {"pages": len(pages), "paragraphs": len(paras), "sections": secs, "status": status})


def papers(method, parts, body, user):
    # GET /papers/<cq>                      一覧
    # POST /papers/<cq>/<pmid>/upload-url   PDF置き場(署名付きURL)。登録も行う
    # POST /papers/<cq>/<pmid>/extract      PDFから段落を抽出して保存
    # GET /papers/<cq>/<pmid>/text          段落(ID付き)
    # GET /papers/<cq>/<pmid>/pdf-url       PDF閲覧(署名付きURL)
    # PUT /papers/<cq>/<pmid>               研究特性・題名
    if method == "GET" and len(parts) == 2:
        return resp(200, sorted(query("PAPER", f"{parts[1]}#"), key=lambda p: p["pmid"]))
    if len(parts) < 3: return resp(400, {"error": "CQ と PMID が必要です"})
    cqid, pmid = parts[1], re.sub(r"\D", "", parts[2])
    c = get("CQ", cqid)
    if not c or not pmid: return resp(404, {"error": "CQ または PMID が不正です"})
    sub = parts[3] if len(parts) > 3 else ""
    p = get("PAPER", paper_key(cqid, pmid))
    if method == "GET" and sub == "text":
        if not p or not p.get("text_key"): return resp(404, {"error": "本文が未抽出です"})
        return resp(200, json.loads(s3().get_object(Bucket=BUCKET, Key=p["text_key"])["Body"].read()))
    if method == "GET" and sub == "pdf-url":
        if not p or not p.get("s3_key"): return resp(404, {"error": "PDFが未登録です"})
        url = s3().generate_presigned_url("get_object", Params={"Bucket": BUCKET, "Key": p["s3_key"], "ResponseContentType": "application/pdf", "ResponseContentDisposition": "inline"}, ExpiresIn=900)
        audit(user, "PDFの閲覧", f"{cqid} / PMID {pmid}"); return resp(200, {"url": url})
    if not (is_assignee(user, c) or set(user["groups"]) & ROLE_LEAD): raise Forbidden("この CQ の担当委員、SR委員長、統括委員会、事務局に限ります")
    if method == "POST" and sub == "upload-url":
        key = f"papers/{cqid}/{pmid}.pdf"
        if not p:
            p = put("PAPER", paper_key(cqid, pmid), {"cq": cqid, "pmid": pmid, "title": body.get("title", ""), "s3_key": key, "status": "登録", "registered_by": user["name"] or user["email"], "chars": {}})
            audit(user, "論文の登録", f"{cqid} / PMID {pmid}", body.get("title", ""))
        url = s3().generate_presigned_url("put_object", Params={"Bucket": BUCKET, "Key": key, "ContentType": "application/pdf"}, ExpiresIn=900)
        return resp(200, {"url": url, "key": key})
    if method == "POST" and sub == "extract":
        if not p: return resp(404, {"error": "未登録です"})
        from extract_text import pdf_pages
        data = s3().get_object(Bucket=BUCKET, Key=p["s3_key"])["Body"].read()
        return save_text(user, cqid, pmid, p, pdf_pages(data), "pypdf")
    if method == "PUT" and sub == "text":
        # PUT /papers/<cq>/<pmid>/text  画像PDFを Mac で OCR した本文(pages: [{page, text}])を保存する
        if not p: return resp(404, {"error": "未登録です"})
        pages = [(int(x.get("page", i + 1)), str(x.get("text", ""))) for i, x in enumerate(body.get("pages") or []) if isinstance(x, dict)]
        if not pages: return resp(400, {"error": "pages が必要です"})
        return save_text(user, cqid, pmid, p, pages, str(body.get("source") or "OCR"))
    if method == "PUT" and not sub:
        if not p: return resp(404, {"error": "未登録です"})
        if "title" in body: p["title"] = str(body["title"])
        if "chars" in body:
            ch = {k: str(body["chars"].get(k, "")) for k in ("design", "cancer", "chemo_drugs", "chemo_class", "n_total", "n_int", "intervention_detail", "comparator_detail", "followup")}
            if ch["chemo_class"] and ch["chemo_class"] not in CHEMO_CLASSES: return resp(400, {"error": "化学療法の分類は " + "/".join(CHEMO_CLASSES)})
            p["chars"] = ch
        put("PAPER", p["sk"], p); audit(user, "研究特性の更新", f"{cqid} / PMID {pmid}", f"がん腫: {p['chars'].get('cancer', '')}、分類: {p['chars'].get('chemo_class', '')}"); return resp(200, p)
    if method == "DELETE" and not sub:
        require(user, ROLE_LEAD)
        if p: table().delete_item(Key={"pk": "PAPER", "sk": p["sk"]}); audit(user, "論文の登録解除", f"{cqid} / PMID {pmid}")
        return resp(200, {"ok": True})
    return resp(405, {"error": "方法が不正です"})


# ---------- 様式4-5 ----------
def f45_key(cqid, pmid, outcome, reviewer):
    return f"{cqid}#{pmid}#{outcome}#{reviewer}"


def f45(method, parts, body, user):
    # GET  /f45/<cq>/<pmid>/<outcome>            自分の評価、AI下書き、照合(2名が提出済みのときだけ相手の評価と確定欄)
    # PUT  /f45/<cq>/<pmid>/<outcome>            自分の評価の保存(submitted=true で提出)
    # PUT  /f45/<cq>/<pmid>/<outcome>/final      照合の確定(提出済みの2名、またはSR委員長以上)
    # POST /f45/<cq>/<pmid>/<outcome>/draft      AI下書きの作成(本文抽出済みの論文に限る。非同期)
    if len(parts) < 4: return resp(400, {"error": "CQ、PMID、アウトカムが必要です"})
    cqid, pmid, outcome = parts[1], parts[2], parts[3]
    sub = parts[4] if len(parts) > 4 else ""
    c = get("CQ", cqid); p = get("PAPER", paper_key(cqid, pmid))
    if not c or not p: return resp(404, {"error": "CQ または論文がありません"})
    if outcome not in (c.get("outcomes") or []): return resp(400, {"error": "この CQ のアウトカムにありません(CQ・PICO一覧で登録)"})
    recs = {r["sk"].rsplit("#", 1)[1]: r for r in query("F45", f"{cqid}#{pmid}#{outcome}#")}
    reviewers = sorted(k for k in recs if k not in ("AI", "確定"))
    submitted = [k for k in reviewers if recs[k].get("submitted")]
    lead = bool(set(user["groups"]) & ROLE_LEAD)
    if method == "GET":
        mine = recs.get(user["name"])
        both = len(submitted) >= 2
        others = {k: v for k, v in recs.items() if k not in ("AI", "確定", user["name"])} if (both or lead) else {}
        return resp(200, {"mine": mine, "ai": recs.get("AI"), "final": recs.get("確定"), "others": others, "reviewers": reviewers, "submitted": submitted, "reconcile_open": both,
                          "paper": p, "item_keys": ITEM_KEYS, "item_ja": ITEM_JA})
    if method == "PUT" and not sub:
        if not user["name"]: return resp(400, {"error": "利用者の氏名が未登録です(事務局に依頼)"})
        if not (is_assignee(user, c) or lead): raise Forbidden("この CQ の担当委員に限ります")
        mine = recs.get(user["name"]) or {}
        if mine.get("submitted") and not lead and body.get("submitted") is not False:
            return resp(409, {"error": "提出済みです。変更は照合で行います"})
        items = norm_items(body.get("items") or {})
        rec = {"cq": cqid, "pmid": pmid, "outcome": outcome, "reviewer": user["name"], "items": items, "counts": body.get("counts") or {}, "effect": body.get("effect") or {},
               "instrument": str(body.get("instrument", "")), "note": str(body.get("note", "")), "submitted": bool(body.get("submitted")), "submitted_at": now() if body.get("submitted") else ""}
        put("F45", f45_key(cqid, pmid, outcome, user["name"]), rec)
        audit(user, "様式4-5の" + ("提出" if rec["submitted"] else "保存"), f"{cqid} / PMID {pmid} / {outcome}", summarize_items(items)); return resp(200, rec)
    if method == "PUT" and sub == "final":
        if not (lead or (user["name"] in submitted and len(submitted) >= 2)): raise Forbidden("照合の確定は、2名独立の評価を提出した評価者、またはSR委員長以上に限ります")
        if len(submitted) < 2 and not lead: return resp(409, {"error": "2名独立の評価の提出が必要です"})
        items = norm_items(body.get("items") or {})
        rec = {"cq": cqid, "pmid": pmid, "outcome": outcome, "reviewer": "確定", "items": items, "counts": body.get("counts") or {}, "effect": body.get("effect") or {}, "instrument": str(body.get("instrument", "")),
               "note": str(body.get("note", "")), "fixed_by": user["name"], "based_on": submitted}
        put("F45", f45_key(cqid, pmid, outcome, "確定"), rec); audit(user, "様式4-5の確定(照合)", f"{cqid} / PMID {pmid} / {outcome}", summarize_items(items)); return resp(200, rec)
    if method == "POST" and sub == "draft":
        if not (is_assignee(user, c) or lead): raise Forbidden("この CQ の担当委員に限ります")
        if not str(p.get("status", "")).startswith("本文抽出済"): return resp(409, {"error": "本文が未抽出です。PDFを登録し、本文を抽出してください(抄録だけでは作りません。画像PDFは OCR で本文を入れます)"})
        put("F45", f45_key(cqid, pmid, outcome, "AI"), {"cq": cqid, "pmid": pmid, "outcome": outcome, "reviewer": "AI", "status": "作成中", "requested_by": user["name"]})
        ev = {"task": "draft45", "cq": cqid, "pmid": pmid, "outcome": outcome, "user": user}
        if FUNCTION:
            boto3.client("lambda").invoke(FunctionName=FUNCTION, InvocationType="Event", Payload=json.dumps(ev, ensure_ascii=False).encode())
        else:
            run_draft45(ev)
        audit(user, "様式4-5の下書きを依頼", f"{cqid} / PMID {pmid} / {outcome}"); return resp(202, {"status": "作成中"})
    return resp(405, {"error": "方法が不正です"})


def norm_items(items):
    out = {}
    for k in ITEM_KEYS:
        it = items.get(k) or {}
        v = it.get("v") if isinstance(it, dict) else it
        if isinstance(v, str) and v.strip() in ("0", "-1", "-2"): v = int(v)
        if v not in (0, -1, -2): v = None
        if k in ("blinding_participants", "blinding_assessors") and v == -2: v = -1  # 統括委員長の決定
        out[k] = {"v": v, "evidence": [str(e) for e in (it.get("evidence") or [])][:10] if isinstance(it, dict) else [], "quote": str(it.get("quote", ""))[:400] if isinstance(it, dict) else ""}
    return out


def summarize_items(items):
    return " ".join(f"{ja}={items[k]['v'] if items[k]['v'] is not None else '—'}" for k, ja in zip(ITEM_KEYS, ITEM_JA))


def run_draft45(ev):
    cqid, pmid, outcome, user = ev["cq"], ev["pmid"], ev["outcome"], ev.get("user") or {"name": "system", "email": ""}
    key = f45_key(cqid, pmid, outcome, "AI")
    try:
        c = get("CQ", cqid); p = get("PAPER", paper_key(cqid, pmid))
        from extract_text import relevant
        import draft45
        text = json.loads(s3().get_object(Bucket=BUCKET, Key=p["text_key"])["Body"].read())
        paras = relevant(text["paragraphs"])
        if not paras: return resp(400, {"error": "本文の段落がありません(画像PDF)。OCR で本文を入れてから下書きを作ります"})
        out = draft45.draft(c["title"], c["pico"].get("P"), c["pico"].get("I") or c["title"], outcome, paras)
        rec = {"cq": cqid, "pmid": pmid, "outcome": outcome, "reviewer": "AI", "status": "下書き", "items": out["items"], "study": out.get("study") or {}, "design": out.get("design"),
               "counts": out.get("counts") or {}, "effect": out.get("effect") or {}, "model": draft45.MODEL_ID, "paragraphs_used": [x["id"] for x in paras], "at": now()}
        put("F45", key, rec); audit(user, "様式4-5の下書きを作成", f"{cqid} / PMID {pmid} / {outcome}", f"段落 {len(paras)}件を根拠に。" + summarize_items(out["items"]))
        return {"ok": True}
    except Exception as e:
        put("F45", key, {"cq": cqid, "pmid": pmid, "outcome": outcome, "reviewer": "AI", "status": "失敗", "error": str(e)[:500]})
        audit(user, "様式4-5の下書きに失敗", f"{cqid} / PMID {pmid} / {outcome}", str(e)[:300]); return {"ok": False}


# ---------- 様式SR-8 ----------
def sr8(method, parts, body, user):
    # GET /sr8/<cq>              アウトカムごとの SR-8 と、確定済み様式4-5の集計(研究数、分類別)
    # PUT /sr8/<cq>/<outcome>    SRチーム(担当委員・SR委員長)が記入
    if len(parts) < 2: return resp(400, {"error": "CQ が必要です"})
    cqid = parts[1]; c = get("CQ", cqid)
    if not c: return resp(404, {"error": "ありません"})
    if method == "GET":
        papers = {p["pmid"]: p for p in query("PAPER", f"{cqid}#")}
        finals = [r for r in query("F45", f"{cqid}#") if r["sk"].endswith("#確定")]
        rows = {r["sk"].rsplit("#", 1)[0]: r for r in query("SR8", f"{cqid}#")}
        out = []
        for o in c.get("outcomes") or []:
            fs = [f for f in finals if f["outcome"] == o]
            by_class = {}
            for f in fs:
                cls = (papers.get(f["pmid"], {}).get("chars") or {}).get("chemo_class") or "不明"
                by_class.setdefault(cls, []).append({"pmid": f["pmid"], "bias_summary": f["items"]["bias_summary"]["v"], "ind_summary": f["items"]["ind_summary"]["v"], "effect": f.get("effect"), "counts": f.get("counts")})
            out.append({"outcome": o, "n_studies": len(fs), "by_chemo_class": by_class, "sr8": rows.get(f"{cqid}#{o}")})
        return resp(200, {"cq": cqid, "outcomes": out, "sr8_keys": SR8_KEYS, "sr8_ja": SR8_JA})
    if method == "PUT" and len(parts) > 2:
        o = parts[2]
        if o not in (c.get("outcomes") or []): return resp(400, {"error": "アウトカムがありません"})
        if not (is_assignee(user, c) or set(user["groups"]) & ROLE_LEAD): raise Forbidden("SRチーム(担当委員・SR委員長)に限ります")
        rec = {"cq": cqid, "outcome": o, "by": user["name"]}
        for k in ("rob", "inconsistency", "imprecision", "indirectness", "publication_bias"):
            v = body.get(k); rec[k] = int(v) if str(v) in ("0", "-1", "-2") else None
        rec["upgrade"] = int(body["upgrade"]) if str(body.get("upgrade")) in ("0", "1", "2") else None
        rec["certainty"] = body.get("certainty") if body.get("certainty") in CERT else ""
        rec["strata"] = str(body.get("strata", "")); rec["effect_summary"] = str(body.get("effect_summary", "")); rec["note"] = str(body.get("note", ""))
        put("SR8", f"{cqid}#{o}", rec); audit(user, "様式SR-8の記入", f"{cqid} / {o}", f"確実性 {rec['certainty'] or '—'}"); return resp(200, rec)
    return resp(405, {"error": "方法が不正です"})


# ---------- EtD(2023年版の体裁) ----------
def etd(method, parts, body, user):
    if len(parts) < 2: return resp(400, {"error": "CQ が必要です"})
    cqid = parts[1]; c = get("CQ", cqid)
    if not c: return resp(404, {"error": "ありません"})
    if method == "GET":
        e = get("ETD", cqid) or {"cq": cqid, "rec_draft": "", "strength": "", "certainty": "", "scope_note": "", "considerations": {k: {"text": "", "evidence": []} for k, _ in ETD_CONSIDERATIONS}, "vote": {}, "status": "下書き"}
        sr = {r["outcome"]: r for r in query("SR8", f"{cqid}#")}
        return resp(200, {"etd": e, "gl2023": get("GL2023", cqid), "sr8": sr, "considerations": ETD_CONSIDERATIONS, "strength": STRENGTH, "cert": CERT})
    if method == "POST" and parts[2:3] == ["draft"]:
        require(user, ROLE_GROUP | ROLE_LEAD)
        if not query("SR8", f"{cqid}#"): return resp(409, {"error": "様式SR-8 が未記入です。SR-8 の記入後に下書きを作ります"})
        e = get("ETD", cqid) or {"cq": cqid, "considerations": {}, "vote": {}, "status": "下書き"}
        e["ai_draft"] = {"status": "作成中", "requested_by": user["name"], "at": now()}; put("ETD", cqid, e)
        ev = {"task": "draft_etd", "cq": cqid, "user": user}
        if FUNCTION: boto3.client("lambda").invoke(FunctionName=FUNCTION, InvocationType="Event", Payload=json.dumps(ev, ensure_ascii=False).encode())
        else: run_draft_etd(ev)
        audit(user, "EtD下書きを依頼", cqid); return resp(202, {"status": "作成中"})
    if method == "PUT":
        require(user, ROLE_GROUP | ROLE_LEAD)
        e = get("ETD", cqid) or {"cq": cqid, "considerations": {}, "vote": {}}
        if e.get("status") == "確定" and body.get("status") != "下書き": require(user, {"統括委員会"})
        for k in ("rec_draft", "scope_note", "narrative"):
            if k in body: e[k] = str(body[k])
        if "strength" in body: e["strength"] = body["strength"] if body["strength"] in STRENGTH else ""
        if "certainty" in body: e["certainty"] = body["certainty"] if body["certainty"] in CERT else ""
        if "considerations" in body:
            e["considerations"] = {k: {"text": str((body["considerations"].get(k) or {}).get("text", "")), "evidence": [str(x) for x in (body["considerations"].get(k) or {}).get("evidence", [])][:30]} for k, _ in ETD_CONSIDERATIONS}
        if "vote" in body:
            v = body["vote"]; counts = [int(x or 0) for x in (v.get("counts") or [0, 0, 0, 0, 0])][:5]
            denom = int(v.get("denominator") or sum(counts)); top = max(counts) if counts else 0
            e["vote"] = {"round": int(v.get("round") or 1), "counts": counts, "denominator": denom, "coi_excluded": int(v.get("coi_excluded") or 0), "sr_excluded": int(v.get("sr_excluded") or 0),
                         "agreement": round(100 * top / denom) if denom else None, "date": str(v.get("date", "")), "note": str(v.get("note", ""))}
        if "status" in body and body["status"] in ("下書き", "協議中", "確定"):
            if body["status"] == "確定": require(user, {"統括委員会"})
            e["status"] = body["status"]
        put("ETD", cqid, e); audit(user, "EtDの更新", cqid, f"状態 {e.get('status', '下書き')}" + (f"、投票 第{e['vote']['round']}回 合意率 {e['vote']['agreement']}%" if e.get("vote") else "")); return resp(200, e)
    return resp(405, {"error": "方法が不正です"})


def gl2023(method, parts, body, user):
    """2023年版の記述(build_etd.py の etd_2023.json)。統括委員会・事務局が取り込む。CQ ごとに、推奨文・強さ・確実性・解説・投票を置く"""
    if method == "GET":
        return resp(200, sorted(query("GL2023"), key=lambda g: g["sk"])) if len(parts) < 2 else resp(200, get("GL2023", parts[1]) or {})
    if method == "POST":
        require(user, ROLE_ADMIN)
        items = body if isinstance(body, list) else body.get("items")
        if not isinstance(items, list): return resp(400, {"error": "etd_2023.json の配列が必要です"})
        plan = json.load(open(os.path.join(HERE, "approved_plan.json"), encoding="utf-8"))
        dir2id = {d: it["id"] for it in plan["SR項目"] + plan["FRQ項目"] for d in it["dir"]}  # 2023年版の作業フォルダ名 → 企画書の項目ID
        merged = {}
        for n_, it in enumerate(items, 1):
            cqid = it.get("plan_id") or it.get("cq") or dir2id.get(it.get("dir", "")) or f"CQ{n_:02d}"
            m = merged.setdefault(cqid, {"cq": cqid, "title": it.get("title", ""), "dir": it.get("dir", ""), "rec": "", "strength": "", "certainty": "", "votes": None, "recs": [], "paragraphs": []})
            m["recs"].append({"rec": it.get("rec", ""), "strength": it.get("strength", ""), "certainty": it.get("certainty", ""), "votes": it.get("votes"), "stem": it.get("stem", "")})
            m["rec"] = "\n".join(r["rec"] for r in m["recs"]); m["strength"] = "・".join(r["strength"] for r in m["recs"]); m["certainty"] = "・".join(r["certainty"] for r in m["recs"]); m["votes"] = m["recs"][0]["votes"]
            base = len(m["paragraphs"])
            m["paragraphs"] += [{"id": f"GL2023-{cqid}-p{base + i + 1:03d}", "text": s} for i, s in enumerate(x for x in re.split(r"(?<=。)\s*", it.get("narrative") or "") if x.strip())]
        n = 0
        for cqid, m in merged.items():
            put("GL2023", cqid, m); n += 1
        stale = [g["sk"] for g in query("GL2023") if g["sk"] not in merged and g["sk"] not in set(dir2id.values())]  # 企画書の項目IDでない古い記録(以前の取り込み)を消す
        for sk in stale: table().delete_item(Key={"pk": "GL2023", "sk": sk})
        audit(user, "2023年版の記述の取り込み", "全CQ", f"{n}件" + (f"、古い記録 {len(stale)} 件を削除" if stale else "")); return resp(200, {"imported": n, "removed": stale})
    return resp(405, {"error": "方法が不正です"})


def gl2023_soron(method, parts, body, user):
    """2023年版の総論の本文(段落ID付き)。統括委員会・事務局が取り込む(scripts/import_soron2023.py)。docx の置き場(署名付きURL)も返す"""
    if method == "GET":
        return resp(200, sorted(query("GL2023S"), key=lambda g: g["sk"]))
    if method == "POST":
        require(user, ROLE_ADMIN)
        items = body.get("items") or []
        urls = []
        for it in items:
            key = str(it.get("key", "")).strip()
            if not key or not isinstance(it.get("paragraphs"), list): urls.append(None); continue
            paras = [{"id": str(p.get("id")), "text": str(p.get("text", ""))[:4000]} for p in it["paragraphs"] if p.get("id")]
            rec = {"key": key, "title": str(it.get("title", "")), "paragraphs": paras}
            if it.get("filename") and BUCKET:
                safe = re.sub(r"[^\w.\-一-龥ぁ-んァ-ン（）()．.]", "_", it["filename"])[:80]
                rec["docx_key"] = f"soron2023/{key}/{safe}"
                urls.append(s3().generate_presigned_url("put_object", Params={"Bucket": BUCKET, "Key": rec["docx_key"]}, ExpiresIn=900))
            else:
                urls.append(None)
            put("GL2023S", key, rec)
        audit(user, "2023年版総論の取り込み", "総論", f"{sum(1 for u in urls if u is not None or True)}件"); return resp(200, {"imported": len(items), "upload_urls": urls})
    return resp(405, {"error": "方法が不正です"})


def run_draft_etd(ev):
    cqid, user = ev["cq"], ev.get("user") or {"name": "system", "email": ""}
    e = get("ETD", cqid) or {"cq": cqid, "considerations": {}, "vote": {}, "status": "下書き"}
    try:
        import draft45
        c = get("CQ", cqid); papers = query("PAPER", f"{cqid}#")
        finals = [r for r in query("F45", f"{cqid}#") if r["sk"].endswith("#確定")]
        out = draft45.draft_etd(c, query("SR8", f"{cqid}#"), finals, papers, get("GL2023", cqid))
        e["ai_draft"] = {**out, "status": "下書き", "model": draft45.MODEL_ID, "at": now(), "based_on": {"sr8": len(query("SR8", f"{cqid}#")), "f45_final": len(finals)}}
        put("ETD", cqid, e); audit(user, "EtD下書きを作成", cqid, f"SR-8 {e['ai_draft']['based_on']['sr8']}件、様式4-5確定 {len(finals)}件を根拠に"); return {"ok": True}
    except Exception as ex:
        e["ai_draft"] = {"status": "失敗", "error": str(ex)[:500], "at": now()}; put("ETD", cqid, e)
        audit(user, "EtD下書きに失敗", cqid, str(ex)[:300]); return {"ok": False}


def export(method, parts, body, user):
    """GET /export/<cq> : ポータルの記録から Minds 書類(xlsx)を作り、S3 に置いて署名付きURLを返す"""
    if method != "GET" or len(parts) < 2: return resp(405, {"error": "方法が不正です"})
    cqid = parts[1]; c = get("CQ", cqid)
    if not c: return resp(404, {"error": "ありません"})
    import export_minds
    papers = query("PAPER", f"{cqid}#"); finals = [r for r in query("F45", f"{cqid}#") if r["sk"].endswith("#確定")]
    aud = [a for a in sorted(query("AUDIT"), key=lambda a: a["sk"]) if cqid in str(a.get("target", ""))]
    data = export_minds.build(c, papers, finals, query("SR8", f"{cqid}#"), get("ETD", cqid), get("GL2023", cqid), aud)
    key = f"exports/{cqid}/Minds書類_{cqid}_{now()[:19].replace(':', '')}.xlsx"
    if BUCKET:
        s3().put_object(Bucket=BUCKET, Key=key, Body=data, ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")
        url = s3().generate_presigned_url("get_object", Params={"Bucket": BUCKET, "Key": key, "ResponseContentDisposition": f"attachment; filename*=UTF-8''Minds_{cqid}.xlsx"}, ExpiresIn=900)
    else:
        url = ""
    audit(user, "Minds書類の出力", cqid, key); return resp(200, {"url": url, "key": key, "sheets": ["CQ", "研究特性", "様式4-5", "様式SR-8", "SoF表", "EtD・推奨", "作成経過"], "bytes": len(data)})


# ---------- 総説(総論A〜N)。SRの流れとは独立した流れ ----------
SORON_FLOW = SORON_STATES


def soron(method, parts, body, user):
    # GET  /soron                           一覧(状態、期限、最新原稿、査読)
    # PUT  /soron/<key>                     執筆者: 状態・期限・備考。統括委員会: 査読コメント、確定
    # POST /soron/<key>/upload-url          原稿(docx/pdf)の置き場。版を重ねる(S3 の版管理)
    # GET  /soron/<key>/files               原稿の版一覧
    # GET  /soron/<key>/download-url?v=     原稿の取得
    if method == "GET" and len(parts) == 1:
        return resp(200, sorted(query("SORON"), key=lambda s: s["key"]))
    if len(parts) < 2: return resp(400, {"error": "項目が必要です"})
    s = get("SORON", parts[1])
    if not s: return resp(404, {"error": "ありません"})
    sub = parts[2] if len(parts) > 2 else ""
    own = bool(user["name"]) and any(user["name"].startswith(a) for a in re.split("[・]", s.get("author", "")) if a)
    admin = bool(set(user["groups"]) & ROLE_ADMIN)
    if not (own or admin): raise Forbidden("この総論の執筆者、統括委員会、事務局に限ります")
    if method == "GET" and sub == "gl2023":
        g = get("GL2023S", s["key"])
        if not g: return resp(200, {})
        if g.get("docx_key") and BUCKET:
            g["docx_url"] = s3().generate_presigned_url("get_object", Params={"Bucket": BUCKET, "Key": g["docx_key"]}, ExpiresIn=900)
        return resp(200, g)
    if method == "GET" and sub == "files":
        if not BUCKET: return resp(200, [])
        vs = s3().list_object_versions(Bucket=BUCKET, Prefix=f"soron/{s['key']}/").get("Versions", [])
        return resp(200, sorted([{"key": v["Key"].split("/")[-1], "version": v["VersionId"], "at": v["LastModified"].isoformat(), "size": v["Size"], "latest": v["IsLatest"]} for v in vs], key=lambda x: x["at"], reverse=True))
    if method == "GET" and sub == "download-url":
        name = s.get("file") or ""
        if not name: return resp(404, {"error": "原稿がありません"})
        url = s3().generate_presigned_url("get_object", Params={"Bucket": BUCKET, "Key": f"soron/{s['key']}/{name}"}, ExpiresIn=900)
        audit(user, "総論の原稿の取得", f"総論{s['label']}", name); return resp(200, {"url": url})
    if method == "POST" and sub == "upload-url":
        name = re.sub(r"[^\w.\-一-龥ぁ-んァ-ン]", "_", body.get("filename") or "原稿.docx")[:80]
        key = f"soron/{s['key']}/{name}"
        url = s3().generate_presigned_url("put_object", Params={"Bucket": BUCKET, "Key": key, "ContentType": body.get("content_type") or "application/octet-stream"}, ExpiresIn=900)
        s["file"] = name; s["file_at"] = now(); s["file_by"] = user["name"] or user["email"]
        if s.get("status") in ("原稿未提出", "修正中"): s["status"] = "執筆中"
        put("SORON", s["key"], s); audit(user, "総論の原稿の提出", f"総論{s['label']}", name); return resp(200, {"url": url, "key": key})
    if method == "PUT" and not sub:
        ch = []
        if "status" in body and body["status"] in SORON_FLOW and body["status"] != s.get("status"):
            if body["status"] == "完了": require(user, {"統括委員会"})
            ch.append(f"状態: {s.get('status')}→{body['status']}"); s["status"] = body["status"]
        for k, ja in (("due", "期限"), ("note", "備考")):
            if k in body: s[k] = str(body[k]); ch.append(ja)
        if "review" in body:
            require(user, ROLE_ADMIN); s["review"] = str(body["review"]); s["review_by"] = user["name"]; s["review_at"] = now(); ch.append("査読コメント")
            if s.get("status") == "査読中": s["status"] = "修正中"
        put("SORON", s["key"], s); audit(user, "総論の更新", f"総論{s['label']}", "、".join(ch)); return resp(200, s)
    return resp(405, {"error": "方法が不正です"})

# ---------- スクリーニング ----------
def screening_progress(d):
    P = d.get("papers", [])
    s1 = lambda p: (p.get("s1") or {}).get("decision", ""); s2 = lambda p: (p.get("s2") or {}).get("decision", "")
    need2 = lambda p: (s1(p) in ("採用", "保留") or p.get("direct")) and not s2(p)
    targ = lambda p: s2(p) == "採用" or need2(p)
    return {"reviewer": d.get("reviewer", ""), "saved_at": d.get("saved_at", ""), "papers": len(P), "s1_done": sum(1 for p in P if s1(p)), "s1_todo": sum(1 for p in P if not s1(p) and not p.get("direct")),
            "s2_done": sum(1 for p in P if s2(p)), "s2_todo": sum(1 for p in P if need2(p)), "ft_missing": sum(1 for p in P if targ(p) and (p.get("ft") or "未入手") == "未入手"),
            "ft_read": sum(1 for p in P if targ(p) and p.get("ft") == "読了"),
            "no_reason": sum(1 for p in P if (s1(p) == "除外" and not (p.get("s1") or {}).get("reason", "").strip()) or (s2(p) == "除外" and not (p.get("s2") or {}).get("reason", "").strip()))}


def screening(method, parts, body, user):
    if method == "GET":
        if len(parts) > 2 and parts[1] == "raw":
            it = get("SCREEN", parts[2]); return resp(200, it["data"] if it else {})
        out = {}
        for it in query("SCREEN"):
            out.setdefault(it["cq"], []).append({**screening_progress(it["data"]), "sk": it["sk"], "uploaded_by": it.get("uploaded_by", "")})
        return resp(200, out)
    if method == "POST" and len(parts) > 1:
        d = body
        if not isinstance(d.get("papers"), list) or not d.get("reviewer"): return resp(400, {"error": "スクリーニング管理シートの JSON(reviewer, papers)が必要です"})
        if d["reviewer"] != user["name"]: require(user, ROLE_LEAD)
        sk = f"{parts[1]}#{d['reviewer']}"; old = get("SCREEN", sk)
        if old and (old["data"].get("saved_at") or "") > (d.get("saved_at") or ""): return resp(409, {"error": "保存済みの方が新しいため、取り込みません"})
        put("SCREEN", sk, {"cq": parts[1], "reviewer": d["reviewer"], "uploaded_by": user["name"] or user["email"], "data": d})
        pr = screening_progress(d); audit(user, "スクリーニングJSONの取り込み", f"{parts[1]} / {d['reviewer']}", f"文献{pr['papers']}件、一次判定済{pr['s1_done']}、二次判定済{pr['s2_done']}"); return resp(200, pr)
    return resp(405, {"error": "方法が不正です"})
