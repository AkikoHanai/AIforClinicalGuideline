"""GL作成ポータルの API(AWS Lambda)。API Gateway(HTTP API)の JWT 認可(Cognito)を通った要求だけが届く。
CIPN診療ガイドライン2023年版の作成手順(Minds)を踏襲する。判断は委員が行い、この API は記録・集計・下書きの生成だけを行う。

DynamoDB 1テーブル(pk, sk):
  USER/<email>                利用者(氏名、役割)。名簿・COIはGoogleフォーム・ドライブで管理し、ここには置かない
  CQ/<id>                     SR項目11・FRQ項目4(企画書)。PICO、アウトカム一覧、段階
  PAPER/<cq>#<pmid>           登録した論文。PDFは S3(papers/<cq>/<pmid>.pdf)、本文の段落は S3(text/<cq>/<pmid>.json)。研究特性
  F45/<cq>#<pmid>#<outcome>#<評価者>   SR-5。評価者= 委員の氏名 / "AI"(下書き) / "確定"(照合の結果)
  SR8/<cq>#<outcome>          SR-8(エビデンス総体)
  ETD/<cq>                    EtD(2023年版の体裁: 推奨文、強さ、確実性、4つの考慮事項、投票)
  GL2023/<cq>                 2023年版の記述(推奨文・解説・投票。build_etd.py の etd_2023.json を取り込む)
  SORON/<key>                 総論A〜N(企画書)
  SEARCH/<cq>#<id>            検索の記録(データベース、検索日、検索者、検索期間、検索式、件数)
  SEARCHREF/<cq>              検索の参考資料(2023年版の検索過程、検索式の案)。検索の記録には数えない
  CAND/<cq>#<pmid>            スクリーニングの対象の文献(出典、題名、抄録)。協議の結論(final)
  SCR/<cq>#<pmid>#<担当>      担当委員ごとの判定(一次・二次の可否、除外理由、全文の状態、変更の履歴)
  ABS/<cq>#<pmid>             抄録(一覧を軽くするため、文献の記録と分ける)
  SCRIMP/<cq>#<id>            対象の取り込みの記録(追加した PMID、登録済みのため重複として除いた PMID)
  SCRMETA/<cq>                流れ図の件数の保存(rev: 記録の変更の回数。flow_rev が rev と同じなら、保存した件数は最新)
  ACCESS/<email>              利用申請(氏名・所属・状態。承認で USER と Cognito のグループが付く)
  VOTE/<cq>#<回>              電子投票のラウンド(投票者の固定、状態、集計)  VOTEEXCL/<cq>  投票除外(COI)
  VOTED/<cq>#<回>#<email>     投票済みの記録(選択は持たない)  BALLOT/<cq>#<回>#<乱数>  投票(メールアドレス・時刻を持たない。無記名)
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
FIXED_P = "がん化学療法を受ける患者"; FIXED_C = "無治療"   # 統括委員長の決定: P と C は全 CQ で同じ。I は CQ の介入。O は CIPN


def pico_of(c):
    """PICO。P・C は固定、I は CQ の介入、O は CIPN(登録されたアウトカム)。"""
    return {"P": FIXED_P, "I": c.get("title", ""), "C": FIXED_C, "O": "、".join(c.get("outcomes") or [DEFAULT_OUTCOME])}


DEFAULT_OUTCOME = "CIPN"  # 統括委員長の決定(2026-11-16): 今回の改訂では、全CQ・FRQのアウトカムを CIPN とする
CQ_STAGES = ["CQ確定", "検索", "スクリーニング", "論文登録", "SR-5", "SR-8", "EtD"]  # 表示は記録された件数だけ。推測の状態は出さない
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


def cq_name(cqid):
    c = table().get_item(Key={"pk": "CQ", "sk": cqid}).get("Item")
    return (c or {}).get("title", cqid)


def audit(user, action, target, detail=""):
    """作成経過の記録。追記のみ。CQ の内部コード(P1 など)は、利用者に意味がないため、CQ・FRQ の名称で記録する。"""
    m = re.match(r"^([A-Z]\d+)(?= / |$)", str(target))
    if m: target = cq_name(m.group(1)) + str(target)[m.end():]
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
                                 "approved": "統括委員長承認済み(企画書 Ver1 2026-06-17)", "pico": {"P": "", "I": it["名称"], "C": "", "O": DEFAULT_OUTCOME}, "outcomes": [DEFAULT_OUTCOME], "note": ""}); n += 1
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
              "etd_status": (etd.get("status", "下書き") if etd else ""), "etd_agreement": ((etd.get("vote") or {}).get("agreement") if etd else None), "flow": flow_cached(cqid)}
    return counts, units, papers


def stage_text(n):
    """件数(cq_records)を、段階ごとの文字にする。"""
    f = n["flow"]
    return {"CQ確定": "承認済み(統括委員長)",
            "検索": f"{f['searches']}件(検索結果の合計 {f['db_hits']}件)" if f["searches"] else "記録なし",
            "スクリーニング": (f"対象 {f['cands']}件。一次 結果あり {f['s1_target'] - f['s1_open']}/{f['s1_target']}、二次 結果あり {f['s2_target'] - f['s2_open']}/{f['s2_target']}(採用 {f['s2_include']}件)" if f["cands"] else "記録なし"),
            "論文登録": f"{n['papers']}件(本文抽出済 {n['extracted']}件)" if n["papers"] else "記録なし",
            "SR-5": (f"確定 {n['f45_fixed']}/{n['f45_need']}(提出 {n['f45_submitted']})" if n["f45_need"] else ("アウトカム未登録" if n["papers"] else "記録なし")),
            "SR-8": (f"確実性 記入 {n['sr8']}/{n['outcomes']}" if n["outcomes"] else "記録なし"),
            "EtD": n["etd_status"] or "記録なし"}


def stage_auto(cq):
    """記録された件数から、各段階の状態を文字で返す。推測はしない。"""
    return stage_text(cq_records(cq)[0])


def progress(st):
    """確定したSR-5の割合(記録がなければ None)。"""
    m = re.match(r"確定 (\d+)/(\d+)", st.get("SR-5", ""))
    return round(100 * int(m.group(1)) / int(m.group(2))) if m and int(m.group(2)) else None


def dashboard(user):
    """進捗ボード。記録された件数、自分の作業、承認(確定)の記録がない件を返す。SR の流れと総説の流れは、役割で分ける。"""
    g = set(user["groups"]); name = user["name"]; lead = bool(g & ROLE_LEAD)
    sr_view = bool(g & (ROLE_LEAD | {"SR委員", "作成グループ"})); soron_view = bool(g & (ROLE_ADMIN | {"総説執筆者"}))
    out_cq, todo, approvals, my_work = [], [], [], []
    for c in (sorted(query("CQ"), key=lambda c: c["id"]) if sr_view else []):
        n, units, papers = cq_records(c); st = stage_text(n); mine = is_assignee(user, c)
        wait = n.pop("f45_wait"); n["f45_wait"] = len(wait)
        out_cq.append({**c, "stages": st, "progress": progress(st), "counts": n, "mine": mine})
        if mine:
            cands, recs = screen_data(c["id"]); o1 = o2 = 0
            for cd in cands:
                rs = recs.get(cd["pmid"], []); mine_done = lambda st: any(r["reviewer"] == name and (r.get(st) or {}).get("decision") for r in rs)
                r1 = stage_result(cd, rs, "s1")
                if not cd.get("direct") and not r1["decision"] and not mine_done("s1"): o1 += 1
                if to_s2(cd, r1) and not stage_result(cd, rs, "s2")["decision"] and not mine_done("s2"): o2 += 1
            my_work.append({"cq": c["id"], "title": c["title"], "s1_open": o1, "s2_open": o2, "papers": len(papers), "f45_need": n["f45_need"], "f45_submitted_mine": 0,
                            "sr8_open": (n["outcomes"] - n["sr8"]) if n["f45_fixed"] else 0, "sr8": n["sr8"], "outcomes": n["outcomes"], "searches": n["flow"]["searches"], "etd_status": n["etd_status"]})
            for p in papers:
                for o in c.get("outcomes") or []:
                    if name not in units.get((p["pmid"], o), {}).get("submitted", []):
                        todo.append({"cq": c["id"], "pmid": p["pmid"], "title": p.get("title", ""), "outcome": o})
                    else: my_work[-1]["f45_submitted_mine"] += 1
        if lead or mine:
            for w in wait:
                approvals.append({"kind": "SR-5の照合・確定", "target": f"{c['title']} PMID {w['pmid']} / {w['outcome']}", "record": "2名が提出済(" + "・".join(w["submitted"]) + ")。確定の記録なし",
                                  "approver": "評価した2名、またはSR委員長", "can": lead or name in w["submitted"], "page": "f45", "q": {"cq": c["id"], "pmid": w["pmid"], "outcome": w["outcome"]}})
        nc = n["flow"]["s1_conflict"] + n["flow"]["s2_conflict"]
        if nc and (lead or mine):
            approvals.append({"kind": "スクリーニングの協議の結論", "target": f"{c['title']}", "record": f"2名の判定が不一致の文献 {nc}件(一次 {n['flow']['s1_conflict']}件、二次 {n['flow']['s2_conflict']}件)。協議の結論の記録なし",
                              "approver": "担当委員2名の協議と、第三者の意見(SR委員長への報告)", "can": True, "page": "screening", "q": {"cq": c["id"], "show": "conflict"}})
        if n["etd_status"] == "協議中":
            approvals.append({"kind": "EtD・推奨の確定", "target": f"{c['title']}", "record": "状態 協議中。" + (f"投票 合意率 {n['etd_agreement']}%" if n["etd_agreement"] is not None else "投票の記録なし"),
                              "approver": "統括委員会", "can": "統括委員会" in g, "page": "etd", "q": {"cq": c["id"]}})
    if g & ROLE_ADMIN:
        pend = [a for a in query("ACCESS") if a.get("status") == "承認待ち"]
        if pend: approvals.append({"kind": "利用申請の承認", "target": f"{len(pend)}件", "record": "承認待ち: " + "、".join(f"{a['name']}({a.get('affiliation', '')})" for a in pend[:8]) + ("…" if len(pend) > 8 else ""), "approver": "統括委員会(委員長)", "can": True, "page": "access", "q": {}})
    my_votes = []
    if g & (ROLE_GROUP | ROLE_ADMIN):
        for c in query("CQ"):
            r = (vote_rounds(c["id"]) or [None])[-1]
            if r and r["status"] == "受付中" and user["email"] in r["eligible"] and not get("VOTED", f"{c['id']}#{r['round']}#{user['email']}"):
                my_votes.append({"cq": c["id"], "title": c["title"], "round": int(r["round"]), "deadline": r.get("deadline", "")})
    soron = sorted(query("SORON"), key=lambda s: s["key"]) if soron_view else []
    is_author = lambda s: bool(name) and any(name.startswith(a) for a in re.split("[・]", s.get("author", "")) if a)
    my_soron = [s for s in soron if is_author(s)]
    for s in soron:
        if s.get("status") == "査読中" and (g & ROLE_ADMIN or is_author(s)):
            approvals.append({"kind": "総論の査読・完了", "target": f"総論{s['label']} {s['title']}", "record": "状態 査読中。" + (f"原稿 {s['file']}" if s.get("file") else "原稿の記録なし"),
                              "approver": "統括委員会(査読コメントは統括委員会・事務局)", "can": bool(g & ROLE_ADMIN), "page": "soron", "q": {}})
    return {"user": user, "my_work": my_work, "cq": out_cq, "my_cq": [{"id": c["id"], "title": c["title"], "progress": c["progress"]} for c in out_cq if c["mine"]],
            "my_votes": my_votes, "my_f45_todo": todo[:50], "my_f45_todo_count": len(todo), "approvals": approvals[:200], "approvals_count": len(approvals),
            "my_soron": [{"key": s["key"], "label": s["label"], "title": s["title"], "status": s["status"]} for s in my_soron],
            "soron_summary": {st: sum(1 for s in soron if s.get("status") == st) for st in SORON_STATES}}


# ---------- ルーティング ----------
def handler(event, context=None):
    if event.get("task") == "draft45":  # 非同期の下書き(自分自身を invoke)
        return run_draft45(event)
    if event.get("task") == "draft_etd":
        return run_draft_etd(event)
    method = (event.get("requestContext") or {}).get("http", {}).get("method") or event.get("httpMethod", "GET")
    path = event.get("rawPath") or event.get("path") or "/"
    path, _, q = path.partition("?")
    qs = dict(event.get("queryStringParameters") or {}) or {k: v for k, v in __import__("urllib.parse", fromlist=["x"]).parse_qsl(q)}
    body = {}
    if event.get("body"):
        try:
            body = json.loads(event["body"])
        except Exception:
            return resp(400, {"error": "JSONではありません"})
    if qs and isinstance(body, dict): body["_query"] = qs
    try:
        user = caller(event)
        if not user["email"]:
            return resp(401, {"error": "ログインが必要です"})
        return route(method, [p for p in path.split("/") if p], body, user)
    except Forbidden as e:
        return resp(403, {"error": str(e)})
    except KeyError as e:
        return resp(400, {"error": f"項目がありません: {e}"})


SORON_ONLY = {"me", "meta", "dashboard", "soron", "audit", "docs", "access"}  # 総説執筆者だけの利用者が使える範囲(SRの流れとは分離)
SR_ONLY = {"me", "meta", "dashboard", "cq", "papers", "f45", "sr8", "etd", "gl2023", "screening", "search", "audit", "export", "docs", "access"}


def route(method, parts, body, user):
    head = parts[0] if parts else ""
    g = set(user["groups"])
    if not g and head not in ("me", "access"):
        raise Forbidden("利用の承認を待っています。統括委員長の承認の後、もう一度ログインしてください")
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
    if head == "docs":
        return docs(method, parts, body, user)
    if head == "access":
        return access(method, parts, body, user)
    if head == "vote":
        if not (g & (ROLE_GROUP | ROLE_ADMIN)): raise Forbidden("推奨の投票は、統括委員会・作成グループ(事務局は、運営)に限ります")
        return vote(method, parts, body, user)
    if head == "sync":
        # POST /sync/log : 統括委員長の Mac が、ポータル → 共有ドライブへ転送した内容を、作成経過の記録に残す(転送の内容を後で確認できるようにする)
        require(user, ROLE_ADMIN)
        if method != "POST": return resp(405, {"error": "方法が不正です"})
        audit(user, "共有ドライブへの転送", "ポータル → 共有ドライブ", f"転送 {int(body.get('copied', 0))}件、変更なしで飛ばした {int(body.get('skipped', 0))}件。" + str(body.get("detail", ""))[:800]); return resp(200, {"ok": True})
    if head == "screening":
        return screening(method, parts, body, user)
    if head == "search":
        return search(method, parts, body, user)
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


# ---------- 利用申請(自己登録 → 統括委員長の承認) ----------
# 委員は、ポータルの「Sign up」で自分のアカウントを作り(メールの確認コード)、氏名を申請する。統括委員長が承認するまで、ポータルの内容は何も見えない。
# 承認すると、役割(Cognito のグループ)が付く。氏名から、企画書の名簿に基づく役割の候補を示す(候補であり、承認する人が決める)。
def roster_roles(name):
    plan = json.load(open(os.path.join(HERE, "approved_plan.json"), encoding="utf-8"))
    norm = lambda x: re.sub(r"[\s　]", "", re.sub(r"[((].*?[))]", "", str(x)))
    n = norm(name)
    if not n: return []
    roles = []
    add = lambda r: roles.append(r) if r not in roles else None
    for key, role in (("統括委員会", "統括委員会"), ("診療ガイドライン作成グループ委員", "作成グループ"), ("SRチーム委員(仮案)", "SR委員"), ("外部評価委員(仮)", "外部評価委員")):
        for m in plan.get("体制", {}).get(key, []):
            if norm(m) == n:
                add(role)
                if role == "SR委員" and "委員長" in m: add("SR委員長")
    # 総論の執筆者(企画書は姓だけの表記が多い): 名簿の氏名(フルネーム)に一致し、その姓が執筆者の表記で始まる場合だけ、候補にする(同姓の別人を候補にしない)
    authors = {x for v in plan["総論"].values() for x in re.split("[・]", v.rpartition(":")[2]) if x}
    if any(norm(m) == n and any(n.startswith(x) for x in authors) for lst in plan.get("体制", {}).values() for m in lst): add("総説執筆者")
    return roles


def grant(email, roles):
    """Cognito のグループを、役割に合わせる(利用者のアカウントは、本人が作成済み)"""
    if not USER_POOL: return False
    idp = boto3.client("cognito-idp")
    current = {g["GroupName"] for g in idp.admin_list_groups_for_user(Username=email, UserPoolId=USER_POOL).get("Groups", [])}
    for g in set(roles) - current: idp.admin_add_user_to_group(UserPoolId=USER_POOL, Username=email, GroupName=g)
    for g in current - set(roles): idp.admin_remove_user_from_group(UserPoolId=USER_POOL, Username=email, GroupName=g)
    return True


def access(method, parts, body, user):
    # GET  /access/me                 自分の申請の状態
    # POST /access/request            申請(氏名・所属)。承認の前は、これだけが使える
    # GET  /access                    申請の一覧(統括委員会・事務局)
    # POST /access/<email>/approve    承認(役割を付ける)  / POST /access/<email>/reject  却下
    me = user["email"]; sub = parts[1] if len(parts) > 1 else ""
    if method == "GET" and sub == "me": return resp(200, {"email": me, "groups": user["groups"], "request": get("ACCESS", me)})
    if method == "POST" and sub == "request":
        if user["groups"]: return resp(409, {"error": "すでに承認されています"})
        name = re.sub(r"[\s　]+", "", str(body.get("name", ""))); aff = str(body.get("affiliation", "")).strip()[:100]
        if not name or len(name) > 40: return resp(400, {"error": "氏名(企画書の表記。例: 華井明子)を入力してください"})
        old = get("ACCESS", me)
        if old and old.get("status") == "承認済み": return resp(200, old)
        rec = put("ACCESS", me, {"email": me, "name": name, "affiliation": aff, "status": "承認待ち", "requested_at": now(), "suggest": roster_roles(name)})
        audit(user, "利用申請", name, f"所属: {aff}。名簿に基づく役割の候補: {'・'.join(rec['suggest']) or 'なし(名簿に氏名がない)'}"); return resp(200, rec)
    require(user, ROLE_ADMIN)
    if method == "GET" and not sub: return resp(200, sorted(query("ACCESS"), key=lambda a: (a.get("status") != "承認待ち", a.get("requested_at", ""))))
    a = get("ACCESS", sub.lower()) if sub else None
    if not a: return resp(404, {"error": "申請がありません"})
    act = parts[2] if len(parts) > 2 else ""
    if method == "POST" and act == "approve":
        roles = [g for g in body.get("roles", []) if g in GROUPS]; name = re.sub(r"[\s　]+", "", str(body.get("name") or a["name"]))
        if not roles: return resp(400, {"error": "役割を 1つ以上、選んでください"})
        put("USER", a["email"], {"email": a["email"], "name": name, "roles": roles}); granted = grant(a["email"], roles)
        a.update({"status": "承認済み", "approved_by": user["name"] or user["email"], "approved_at": now(), "roles": roles, "name": name}); put("ACCESS", a["email"], a)
        audit(user, "利用申請の承認", name, "役割: " + "・".join(roles)); return resp(200, {**a, "granted": granted})
    if method == "POST" and act == "reject":
        a.update({"status": "却下", "rejected_by": user["name"] or user["email"], "rejected_at": now(), "reason": str(body.get("reason", ""))[:200]}); put("ACCESS", a["email"], a)
        audit(user, "利用申請の却下", a["name"], a.get("reason", "")); return resp(200, a)
    return resp(405, {"error": "方法が不正です"})


# ---------- 電子投票(推奨の強さ)。ポータルが意思決定の場になる ----------
# 投票者: 統括委員会・作成グループの利用者。そのCQのSR担当と、統括委員会が登録した投票除外(COI)は、除く(ラウンドの開始時に固定する)。患者代表は含めない。
# 1人 1票(ラウンドごと)。無記名: 「誰が投票したか」(VOTED)と「何に投票したか」(BALLOT)を、結び付かない形で別に記録する。ラウンドが終了するまで、集計を誰にも見せない。
# 成立: 参加者が投票者の 75% 以上、かつ、最多の選択肢が参加者(棄権を含む)の 80% 以上(前回Scope)。最大 3回。3回で成立しなければ「推奨なし」。
VOTE_CHOICES = ["1", "2", "3", "4", "5", "棄権"]
VOTE_MAX_ROUNDS = 3


def vote_pool(c, excl):
    """投票者のメールアドレスと、除外した人数(SR担当、COI)"""
    voters, sr_ex, coi_ex = [], [], []
    for u in query("USER"):
        if not (set(u.get("roles", [])) & {"統括委員会", "作成グループ"}): continue
        if is_assignee({"name": u.get("name", "")}, c): sr_ex.append(u["email"]); continue
        if u["email"] in {e["email"] for e in excl}: coi_ex.append(u["email"]); continue
        voters.append(u["email"])
    return sorted(voters), sr_ex, coi_ex


def vote_rounds(cqid):
    return sorted(query("VOTE", f"{cqid}#"), key=lambda r: int(r["round"]))


def vote_tally(r):
    ballots = query("BALLOT", f"{r['cq']}#{r['round']}#"); n = len(r["eligible"])
    counts = [sum(1 for b in ballots if b["choice"] == str(i)) for i in range(1, 6)]; abst = sum(1 for b in ballots if b["choice"] == "棄権"); part = len(ballots)
    top = max(counts) if counts else 0; leaders = [i + 1 for i, v in enumerate(counts) if v == top and top]
    part_pct = round(100 * part / n, 1) if n else 0; agree = round(100 * top / part, 1) if part else 0
    passed = bool(n and part * 100 >= 75 * n and part and top * 100 >= 80 * part and len(leaders) == 1)
    res = {"counts": counts, "abstain": abst, "participants": part, "eligible": n, "participation_pct": part_pct, "agreement_pct": agree, "passed": passed, "strength": leaders[0] if passed else None}
    res["final_none"] = (not passed) and int(r["round"]) >= VOTE_MAX_ROUNDS
    return res


def vote(method, parts, body, user):
    # GET  /vote/<cq>                 状態(推奨文案、ラウンド、自分の投票の可否と済み)。ラウンドの終了後の集計
    # PUT  /vote/<cq>/exclusions      投票除外(COI)の登録(統括委員会・事務局)
    # POST /vote/<cq>/open            ラウンドの開始(統括委員会・事務局)
    # POST /vote/<cq>/cast            投票(投票者本人。1回だけ。変更できない)
    # POST /vote/<cq>/close           ラウンドの終了と集計(統括委員会・事務局)
    if len(parts) < 2: return resp(400, {"error": "CQ が必要です"})
    cqid = parts[1]; c = get("CQ", cqid)
    if not c: return resp(404, {"error": "ありません"})
    admin = bool(set(user["groups"]) & ROLE_ADMIN); me = user["email"]; act = parts[2] if len(parts) > 2 else ""
    etd_ = get("ETD", cqid) or {}; rounds = vote_rounds(cqid); cur = rounds[-1] if rounds else None
    excl = (get("VOTEEXCL", cqid) or {}).get("items", [])
    if method == "GET":
        out = []
        for r in rounds:
            voted = len(query("VOTED", f"{cqid}#{r['round']}#"))
            out.append({"round": int(r["round"]), "status": r["status"], "opened_at": r["opened_at"], "deadline": r.get("deadline", ""), "closed_at": r.get("closed_at", ""), "eligible": len(r["eligible"]), "voted": voted,
                        "sr_excluded": len(r.get("sr_excluded", [])), "coi_excluded": len(r.get("coi_excluded", [])), "rec": r.get("rec", ""), "result": r.get("result") if r["status"] == "終了" else None})
        mine = {"eligible": bool(cur and me in cur["eligible"]), "round_open": int(cur["round"]) if cur and cur["status"] == "受付中" else None, "voted": bool(cur and get("VOTED", f"{cqid}#{cur['round']}#{me}"))}
        d = {"cq": cqid, "title": c["title"], "rec": etd_.get("rec_draft", ""), "scope_note": etd_.get("scope_note", ""), "etd_status": etd_.get("status", "下書き"), "strength_labels": STRENGTH, "choices": VOTE_CHOICES,
             "sr8": [{"outcome": r.get("outcome"), "certainty": r.get("certainty", "")} for r in query("SR8", f"{cqid}#")], "rounds": out, "me": mine, "max_rounds": VOTE_MAX_ROUNDS}
        if admin:
            pool, sr_ex, coi_ex = vote_pool(c, excl); name_of = {u["email"]: u.get("name", "") for u in query("USER")}
            pend = [name_of.get(e, e) for e in (cur["eligible"] if cur and cur["status"] == "受付中" else []) if not get("VOTED", f"{cqid}#{cur['round']}#{e}")]
            d["admin"] = {"exclusions": excl, "pool": [name_of.get(e, e) for e in pool], "sr_excluded": [name_of.get(e, e) for e in sr_ex], "not_voted": pend}
        return resp(200, d)
    if method == "PUT" and act == "exclusions":
        require(user, ROLE_ADMIN)
        if cur and cur["status"] == "受付中": return resp(409, {"error": "ラウンドの受付中は、投票除外を変更できません"})
        items = []
        for it in body.get("items") or []:
            e = str(it.get("email", "")).strip().lower(); rs = str(it.get("reason", "")).strip()
            if not e or not rs: return resp(400, {"error": "投票除外には、メールアドレスと理由が必要です"})
            items.append({"email": e, "reason": rs[:200]})
        put("VOTEEXCL", cqid, {"items": items}); audit(user, "投票除外の登録", cqid, f"{len(items)}名: " + "、".join(f"{i['email']}({i['reason']})" for i in items)); return resp(200, {"items": items})
    if method == "POST" and act == "open":
        require(user, ROLE_ADMIN)
        if cur and cur["status"] == "受付中": return resp(409, {"error": "受付中のラウンドがあります"})
        if cur and cur.get("result", {}).get("passed"): return resp(409, {"error": "すでに成立しています"})
        n = (int(cur["round"]) + 1) if cur else 1
        if n > VOTE_MAX_ROUNDS: return resp(409, {"error": f"投票は最大 {VOTE_MAX_ROUNDS} 回です。成立しなかったため、推奨なしとして確定します"})
        if not str(etd_.get("rec_draft", "")).strip(): return resp(409, {"error": "推奨文案が未記入です。「EtD・推奨」に、推奨文案を書いてから開始します"})
        if etd_.get("status") == "確定": return resp(409, {"error": "EtD・推奨は確定済みです"})
        pool, sr_ex, coi_ex = vote_pool(c, excl)
        if len(pool) < 3: return resp(409, {"error": f"投票者が {len(pool)} 名です。投票者(統括委員会・作成グループ)の利用申請の承認を確認してください"})
        dl = str(body.get("deadline", "")).strip()
        if dl and not re.match(r"^\d{4}-\d{2}-\d{2}$", dl): return resp(400, {"error": "締切は 年-月-日 で入力してください"})
        put("VOTE", f"{cqid}#{n}", {"cq": cqid, "round": n, "status": "受付中", "opened_at": now(), "opened_by": user["name"] or me, "deadline": dl, "eligible": pool, "sr_excluded": sr_ex,
                                    "coi_excluded": [e for e in excl if e["email"] in coi_ex], "rec": etd_.get("rec_draft", "")})
        audit(user, "投票ラウンドの開始", cqid, f"第{n}回。投票者 {len(pool)}名(SR担当の除外 {len(sr_ex)}名、COIの除外 {len(coi_ex)}名)。締切 {dl or 'なし'}"); return resp(200, {"round": n, "eligible": len(pool)})
    if method == "POST" and act == "cast":
        if not cur or cur["status"] != "受付中": return resp(409, {"error": "受付中の投票がありません"})
        if int(body.get("round", 0)) != int(cur["round"]): return resp(409, {"error": "ラウンドが変わりました。画面を読み込み直してください"})
        if me not in cur["eligible"]: raise Forbidden("この CQ の投票者ではありません(SR担当、投票除外、または投票権のない役割)")
        ch = str(body.get("choice", ""))
        if ch not in VOTE_CHOICES: return resp(400, {"error": "選択肢が不正です"})
        from botocore.exceptions import ClientError
        try: table().put_item(Item={"pk": "VOTED", "sk": f"{cqid}#{cur['round']}#{me}", "email": me, "at": now()}, ConditionExpression="attribute_not_exists(pk)")
        except ClientError as e:
            if e.response["Error"]["Code"] == "ConditionalCheckFailedException": return resp(409, {"error": "すでに投票済みです(投票は 1回だけで、変更できません)"})
            raise
        try: table().put_item(Item={"pk": "BALLOT", "sk": f"{cqid}#{cur['round']}#{uuid.uuid4().hex}", "choice": ch})   # 無記名: メールアドレス・時刻を持たせない
        except Exception:
            table().delete_item(Key={"pk": "VOTED", "sk": f"{cqid}#{cur['round']}#{me}"}); raise
        audit(user, "投票", cqid, f"第{cur['round']}回に投票した(選択は記録に残さない)"); return resp(200, {"ok": True})
    if method == "POST" and act == "close":
        require(user, ROLE_ADMIN)
        if not cur or cur["status"] != "受付中": return resp(409, {"error": "受付中のラウンドがありません"})
        res = vote_tally(cur); cur.update({"status": "終了", "closed_at": now(), "closed_by": user["name"] or me, "result": res}); put("VOTE", cur["sk"], cur)
        e = get("ETD", cqid) or {"cq": cqid, "considerations": {}, "status": "下書き"}
        top = max(res["counts"]) if res["participants"] else 0
        e["vote"] = {"round": int(cur["round"]), "counts": res["counts"], "denominator": res["participants"], "eligible": res["eligible"], "abstain": res["abstain"], "coi_excluded": len(cur.get("coi_excluded", [])), "sr_excluded": len(cur.get("sr_excluded", [])),
                     "agreement": round(100 * top / res["participants"]) if res["participants"] else None, "date": now()[:10], "note": "電子投票(ポータル)。分母は参加者数(棄権を含む)"}
        if res["passed"]: e["strength"] = STRENGTH[res["strength"] - 1]
        elif res["final_none"]: e["strength"] = STRENGTH[2]
        if e.get("status") in (None, "下書き"): e["status"] = "協議中"
        put("ETD", cqid, e)
        audit(user, "投票ラウンドの終了", cqid, f"第{cur['round']}回。参加 {res['participants']}/{res['eligible']}名、最多 {top}票(参加者の {res['agreement_pct']}%)。" + ("成立" if res["passed"] else "推奨なし(3回で成立せず)" if res["final_none"] else "不成立"))
        return resp(200, res)
    return resp(405, {"error": "方法が不正です"})


# ---------- CQ ----------
def is_assignee(user, c):
    return bool(user["name"]) and any(user["name"].startswith(a) for a in c.get("assignees", []))


def cq(method, parts, body, user):
    if method == "GET":
        if len(parts) > 1:
            c = get("CQ", parts[1])
            if not c: return resp(404, {"error": "ありません"})
            st = stage_auto(c); return resp(200, {**c, "pico": pico_of(c), "stages": st, "progress": progress(st)})
        out = []
        for c in sorted(query("CQ"), key=lambda c: c["id"]):
            c.pop("stages", None); c.pop("approved", None); st = stage_auto(c)
            out.append({**c, "pico": pico_of(c), "stages": st, "progress": progress(st)})
        return resp(200, out)
    if method == "PUT" and len(parts) > 1:
        c = get("CQ", parts[1])
        if not c: return resp(404, {"error": "ありません"})
        if not is_assignee(user, c): require(user, ROLE_LEAD)
        ch = []
        if "outcomes" in body: c["outcomes"] = [str(o).strip() for o in body["outcomes"] if str(o).strip()]; ch.append("アウトカム: " + "、".join(c["outcomes"]))
        if "note" in body: c["note"] = str(body["note"]); ch.append("備考")
        put("CQ", c["id"], c); audit(user, "CQの更新", c["id"], "、".join(ch)); st = stage_auto(c); return resp(200, {**c, "stages": st, "progress": progress(st)})
    return resp(405, {"error": "方法が不正です"})


# ---------- 論文(PDF登録・本文) ----------
def paper_key(cqid, pmid):
    return f"{cqid}#{pmid}"


def request_draft(user, cqid, pmid, outcome):
    """SR-5 の下書き(Claude)を、非同期で依頼する。"""
    put("F45", f45_key(cqid, pmid, outcome, "AI"), {"cq": cqid, "pmid": pmid, "outcome": outcome, "reviewer": "AI", "status": "作成中", "requested_by": user["name"]})
    ev = {"task": "draft45", "cq": cqid, "pmid": pmid, "outcome": outcome, "user": user}
    if FUNCTION: boto3.client("lambda").invoke(FunctionName=FUNCTION, InvocationType="Event", Payload=json.dumps(ev, ensure_ascii=False).encode())
    else: run_draft45(ev)


def auto_drafts(cqid, pmid):
    """本文を抽出したとき、まだ下書きがないアウトカムの SR-5 の下書きを、自動で依頼する(委員が下書きを待たずに、確認から始められるようにする)。Lambda 上だけで行う。"""
    if not FUNCTION: return
    c = get("CQ", cqid) or {}
    for o in c.get("outcomes") or []:
        if not get("F45", f45_key(cqid, pmid, o, "AI")): request_draft({"name": "自動(本文の抽出後)", "email": ""}, cqid, pmid, o)


def save_text(user, cqid, pmid, p, pages, source):
    from extract_text import paragraphs, quality
    paras = paragraphs(pmid, pages); status = quality(pages, paras)
    if source != "pypdf": status = status.replace("本文抽出済", f"本文抽出済({source})")
    text_key = f"text/{cqid}/{pmid}.json"
    s3().put_object(Bucket=BUCKET, Key=text_key, Body=json.dumps({"pmid": pmid, "pages": len(pages), "source": source, "paragraphs": paras}, ensure_ascii=False).encode(), ContentType="application/json")
    secs = {s: sum(1 for x in paras if x["section"] == s) for s in ("abstract", "methods", "results", "discussion", "other")}
    p.update({"text_key": text_key, "status": status, "pages": len(pages), "n_paragraphs": len(paras), "sections": secs, "text_source": source}); put("PAPER", p["sk"], p)
    audit(user, "本文の抽出", f"{cqid} / PMID {pmid}", f"{source}: {len(pages)}ページ、{len(paras)}段落(Method {secs['methods']}、Result {secs['results']})。{status}")
    if status.startswith("本文抽出済"): auto_drafts(cqid, pmid)
    return resp(200, {"pages": len(pages), "paragraphs": len(paras), "sections": secs, "status": status})


def papers(method, parts, body, user):
    # GET /papers/<cq>                      一覧
    # POST /papers/<cq>/<pmid>/upload-url   PDF置き場(署名付きURL)。登録も行う
    # POST /papers/<cq>/<pmid>/extract      PDFから段落を抽出して保存
    # GET /papers/<cq>/<pmid>/text          段落(ID付き)
    # GET /papers/<cq>/<pmid>/pdf-url       PDF閲覧(署名付きURL)
    # PUT /papers/<cq>/<pmid>               研究特性・題名
    if method == "GET" and len(parts) == 2:
        cands = {x["pmid"]: x for x in query("CAND", f"{parts[1]}#")}   # スクリーニングの記録から、著者・雑誌・発行年を添える(SR-4 の引用文献の列)
        out = []
        for p in sorted(query("PAPER", f"{parts[1]}#"), key=lambda p: p["pmid"]):
            cd = cands.get(p["pmid"]) or {}
            out.append({**p, "title": p.get("title") or cd.get("title", ""), "authors": cd.get("authors", ""), "journal": cd.get("journal", ""), "year": cd.get("year", "")})
        return resp(200, out)
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
            bump(cqid); audit(user, "論文の登録", f"{cqid} / PMID {pmid}", body.get("title", ""))
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
        if p: table().delete_item(Key={"pk": "PAPER", "sk": p["sk"]}); bump(cqid); audit(user, "論文の登録解除", f"{cqid} / PMID {pmid}")
        return resp(200, {"ok": True})
    return resp(405, {"error": "方法が不正です"})


# ---------- SR-5 ----------
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
        audit(user, "SR-5の" + ("提出" if rec["submitted"] else "保存"), f"{cqid} / PMID {pmid} / {outcome}", summarize_items(items)); return resp(200, rec)
    if method == "PUT" and sub == "final":
        if not (lead or (user["name"] in submitted and len(submitted) >= 2)): raise Forbidden("照合の確定は、2名独立の評価を提出した評価者、またはSR委員長以上に限ります")
        if len(submitted) < 2 and not lead: return resp(409, {"error": "2名独立の評価の提出が必要です"})
        items = norm_items(body.get("items") or {})
        rec = {"cq": cqid, "pmid": pmid, "outcome": outcome, "reviewer": "確定", "items": items, "counts": body.get("counts") or {}, "effect": body.get("effect") or {}, "instrument": str(body.get("instrument", "")),
               "note": str(body.get("note", "")), "fixed_by": user["name"], "based_on": submitted}
        put("F45", f45_key(cqid, pmid, outcome, "確定"), rec); audit(user, "SR-5の確定(照合)", f"{cqid} / PMID {pmid} / {outcome}", summarize_items(items)); return resp(200, rec)
    if method == "POST" and sub == "draft":
        if not (is_assignee(user, c) or lead): raise Forbidden("この CQ の担当委員に限ります")
        if not str(p.get("status", "")).startswith("本文抽出済"): return resp(409, {"error": "本文が未抽出です。PDFを登録し、本文を抽出してください(抄録だけでは作りません。画像PDFは OCR で本文を入れます)"})
        request_draft(user, cqid, pmid, outcome)
        audit(user, "SR-5の下書きを依頼", f"{cqid} / PMID {pmid} / {outcome}"); return resp(202, {"status": "作成中"})
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
        out = draft45.draft(c["title"], pico_of(c)["P"], pico_of(c)["I"], outcome, paras)
        rec = {"cq": cqid, "pmid": pmid, "outcome": outcome, "reviewer": "AI", "status": "下書き", "items": out["items"], "study": out.get("study") or {}, "design": out.get("design"),
               "counts": out.get("counts") or {}, "effect": out.get("effect") or {}, "numbers": out.get("numbers") or {}, "model": draft45.MODEL_ID, "paragraphs_used": [x["id"] for x in paras], "at": now()}
        put("F45", key, rec); audit(user, "SR-5の下書きを作成", f"{cqid} / PMID {pmid} / {outcome}", f"段落 {len(paras)}件を根拠に。" + summarize_items(out["items"]))
        return {"ok": True}
    except Exception as e:
        put("F45", key, {"cq": cqid, "pmid": pmid, "outcome": outcome, "reviewer": "AI", "status": "失敗", "error": str(e)[:500]})
        audit(user, "SR-5の下書きに失敗", f"{cqid} / PMID {pmid} / {outcome}", str(e)[:300]); return {"ok": False}


# ---------- SR-8 ----------
def sr8(method, parts, body, user):
    # GET /sr8/<cq>              アウトカムごとの SR-8 と、確定済みSR-5の集計(研究数、分類別)
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
            def tot(k):
                t = 0
                for f in fs:
                    try: t += int(float((f.get("counts") or {}).get(k) or 0))
                    except (TypeError, ValueError): pass
                return t
            dc = {}
            for f in fs: d_ = ((papers.get(f["pmid"], {}).get("chars") or {}).get("design") or "デザイン不明"); dc[d_] = dc.get(d_, 0) + 1
            out.append({"outcome": o, "n_studies": len(fs), "by_chemo_class": by_class, "sr8": rows.get(f"{cqid}#{o}"),
                        "sums": {k: tot(k) for k in ("ctrl_den", "ctrl_num", "int_den", "int_num")}, "design_n": "、".join(f"{k} {v}件" for k, v in dc.items())})   # 記録の合計(統計的な統合ではない)
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
        # SR-8(絶対効果指標の結果を記入する場合)の列。統合値・信頼区間・絶対効果は、委員が記入する(ポータルは統計的な統合を計算しない)
        for k in ("design_n", "eff_type", "eff_val", "eff_ci", "abs_val", "abs_ci"): rec[k] = str(body.get(k, ""))[:200]
        for k in ("ctrl_den", "ctrl_num", "int_den", "int_num"):
            v = str(body.get(k, "")).strip()
            if v and not v.isdigit(): return resp(400, {"error": "分母・分子は、0 以上の整数で入力してください"})
            rec[k] = int(v) if v else None
        imp = str(body.get("importance", "")).strip()
        if imp and imp not in [str(i) for i in range(1, 10)]: return resp(400, {"error": "重要性は 1〜9 です"})
        rec["importance"] = int(imp) if imp else None
        put("SR8", f"{cqid}#{o}", rec); audit(user, "SR-8の記入", f"{cqid} / {o}", f"確実性 {rec['certainty'] or '—'}"); return resp(200, rec)
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
        if not query("SR8", f"{cqid}#"): return resp(409, {"error": "SR-8 が未記入です。SR-8 の記入後に下書きを作ります"})
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
        if "strength" in body and not e.get("vote"): e["strength"] = body["strength"] if body["strength"] in STRENGTH else ""   # 投票の後は、推奨の強さは投票の結果で決まる
        if "certainty" in body: e["certainty"] = body["certainty"] if body["certainty"] in CERT else ""
        if "considerations" in body:
            e["considerations"] = {k: {"text": str((body["considerations"].get(k) or {}).get("text", "")), "evidence": [str(x) for x in (body["considerations"].get(k) or {}).get("evidence", [])][:30]} for k, _ in ETD_CONSIDERATIONS}
        if body.get("vote"): return resp(400, {"error": "投票は、「推奨の投票」の画面で行います(票数の入力はできません)"})
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
        keys = {str(it.get("key", "")).strip() for it in items}
        stale = [g["sk"] for g in query("GL2023S") if g["sk"] not in keys] if len(keys) >= 10 else []   # 全体の取り込みのときだけ、一覧にない古い記録を消す
        for sk in stale: table().delete_item(Key={"pk": "GL2023S", "sk": sk})
        audit(user, "2023年版総論の取り込み", "総論", f"{len(items)}件" + (f"、古い記録 {len(stale)} 件を削除({'・'.join(stale)})" if stale else "")); return resp(200, {"imported": len(items), "removed": stale, "upload_urls": urls})
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
        put("ETD", cqid, e); audit(user, "EtD下書きを作成", cqid, f"SR-8 {e['ai_draft']['based_on']['sr8']}件、SR-5確定 {len(finals)}件を根拠に"); return {"ok": True}
    except Exception as ex:
        e["ai_draft"] = {"status": "失敗", "error": str(ex)[:500], "at": now()}; put("ETD", cqid, e)
        audit(user, "EtD下書きに失敗", cqid, str(ex)[:300]); return {"ok": False}


def screening_book(cqid, c):
    """文献選択の別添(xlsx のバイト列)と、枠ごとの件数"""
    import export_minds
    d = screening_lists(cqid); return export_minds.build_screening(c, d, now()), {k: len(v) for k, v in d["lists"].items()}


def minds_book(cqid, c):
    """Minds書類(xlsx のバイト列)"""
    import export_minds
    c = {**c, "pico": pico_of(c)}
    papers = query("PAPER", f"{cqid}#"); finals = [r for r in query("F45", f"{cqid}#") if r["sk"].endswith("#確定")]
    aud = [a for a in sorted(query("AUDIT"), key=lambda a: a["sk"]) if str(a.get("target", "")).startswith(c["title"])]
    cands, recs = screen_data(cqid); rows = []
    for cd in cands:
        rs = recs.get(cd["pmid"], []); fin = cd.get("final") or {}
        who = lambda st: who_decisions(rs, st, fin)
        rows.append({"pmid": cd["pmid"], "title": cd.get("title", ""), "citation": ". ".join(x for x in (cd.get("authors"), cd.get("journal"), cd.get("year")) if x), "source": cd.get("source", ""), "added_why": cd.get("added_why", ""),
                     "s1": {"decision": "一次を経ない"} if cd.get("direct") else stage_result(cd, rs, "s1"), "s2": stage_result(cd, rs, "s2"), "s1_reviewers": who("s1"), "s2_reviewers": who("s2"),
                     "why": " / ".join(f"{STAGE_JA[st]}: {fin[st].get('why', '')}({fin[st].get('by', '')})。第三者の意見({fin[st].get('opinion_by', '')}): {fin[st].get('opinion', '')}" for st in ("s1", "s2") if fin.get(st))})
    scr = {"searches": sorted(query("SEARCH", f"{cqid}#"), key=lambda r: r.get("date", "")), "flow": flow(cqid, cands, recs), "rows": rows}
    return export_minds.build(c, papers, finals, query("SR8", f"{cqid}#"), get("ETD", cqid), get("GL2023", cqid), aud, screening=scr)


# Minds 様式ごとの出力(共有ドライブの 新規ガイドライン作成/Chap4_SR/SR_n、Chap6_推奨 に、CQ ごとのファイルとして置く)
# (様式, 置き場のフォルダ名, ファイル名の接頭語, ブックに含めるシート)
FORM_MAP = [("SR-1 DB検索結果", "SR_1", "chap4_SR_1", ["CQ", "検索の記録"]), ("SR-2 文献検索フローチャート", "SR_2", "chap4_SR_2", ["CQ", "文献選択の流れ図"]),
            ("SR-3 二次スクリーニング後の一覧", "SR_3", "chap4_SR_3", ["CQ", "スクリーニング"]), ("SR-5 介入研究評価(0/-1/-2)", "SR_5", "chap4_SR_5", ["CQ", "研究特性", "SR-5"]),
            ("SR-8 エビデンス総体", "SR_8", "chap4_SR_8", ["CQ", "SR-8"]), ("SR-12 SoF", "SR_12", "chap4_SR_12", ["CQ", "SoF表"]), ("EtD・推奨", "Chap6_推奨", "chap6_EtD", ["CQ", "EtD・推奨"])]


def form_books(cqid, c):
    """様式ごとのブック: [{form, folder, name, data}]"""
    import export_minds
    book = minds_book(cqid, c); nm = re.sub(r'[\\/:*?"<>|\n\r]', "_", c["title"])[:60]
    return [{"form": f, "folder": folder, "name": f"{pre}_{nm}.xlsx", "sheets": sh, "data": export_minds.split_book(book, sh)} for f, folder, pre, sh in FORM_MAP]


def export(method, parts, body, user):
    """GET /export/<cq> : ポータルの記録から Minds 書類(xlsx)を作り、S3 に置いて署名付きURLを返す"""
    if method != "GET" or len(parts) < 2: return resp(405, {"error": "方法が不正です"})
    cqid = parts[1]; c = get("CQ", cqid)
    if not c: return resp(404, {"error": "ありません"})
    log = (lambda *a, **k: None) if (body.get("_query") or {}).get("sync") == "1" else audit   # 共有ドライブへの転送(sync_drive.py)の出力は、作成経過に記録しない(Minds書類の作成経過のシートが、出力のたびに変わらないように。転送は /sync/log に記録する)
    if parts[2:3] == ["screening"]:
        # GET /export/<cq>/screening : 文献選択の別添(検索の記録、流れ図の件数、枠ごとの文献の一覧: PMID・題名・著者)
        data, counts = screening_book(cqid, c)
        key = f"exports/{cqid}/文献選択の別添_{cqid}_{now()[:19].replace(':', '')}.xlsx"; url = ""
        if BUCKET:
            s3().put_object(Bucket=BUCKET, Key=key, Body=data, ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")
            url = s3().generate_presigned_url("get_object", Params={"Bucket": BUCKET, "Key": key, "ResponseContentDisposition": f"attachment; filename*=UTF-8''Screening_{cqid}.xlsx"}, ExpiresIn=900)
        log(user, "文献選択の別添の出力", cqid, key); return resp(200, {"url": url, "key": key, "bytes": len(data), "counts": counts})
    if parts[2:3] == ["forms"]:
        # GET /export/<cq>/forms : Minds 様式ごと(SR-1・2・3・5・8・12、EtD)のブック。共有ドライブの様式番号のフォルダへ置くため
        out = []
        for fb in form_books(cqid, c):
            key = f"exports/{cqid}/forms/{fb['name']}"; url = ""
            if BUCKET:
                s3().put_object(Bucket=BUCKET, Key=key, Body=fb["data"], ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")
                url = s3().generate_presigned_url("get_object", Params={"Bucket": BUCKET, "Key": key}, ExpiresIn=900)
            out.append({"form": fb["form"], "folder": fb["folder"], "name": fb["name"], "sheets": fb["sheets"], "bytes": len(fb["data"]), "url": url})
        log(user, "Minds様式ごとの出力", cqid, ", ".join(x["form"] for x in out)); return resp(200, {"forms": out})
    data = minds_book(cqid, c)
    key = f"exports/{cqid}/Minds書類_{cqid}_{now()[:19].replace(':', '')}.xlsx"
    if BUCKET:
        s3().put_object(Bucket=BUCKET, Key=key, Body=data, ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")
        url = s3().generate_presigned_url("get_object", Params={"Bucket": BUCKET, "Key": key, "ResponseContentDisposition": f"attachment; filename*=UTF-8''Minds_{cqid}.xlsx"}, ExpiresIn=900)
    else:
        url = ""
    log(user, "Minds書類の出力", cqid, key); return resp(200, {"url": url, "key": key, "sheets": ["CQ", "検索の記録", "文献選択の流れ図", "スクリーニング", "研究特性", "SR-5", "SR-8", "SoF表", "EtD・推奨", "作成経過"], "bytes": len(data)})


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
        # ?v=<版ID> で、過去の版を取得する(省略すると最新)。ファイル名は ?name= で指定できる(版の一覧 /files の key)
        qs = body.get("_query") or {}; name = qs.get("name") or s.get("file") or ""
        if not name: return resp(404, {"error": "原稿がありません"})
        prm = {"Bucket": BUCKET, "Key": f"soron/{s['key']}/{re.sub(r'[/]', '_', name)}"}
        if qs.get("v"): prm["VersionId"] = qs["v"]
        url = s3().generate_presigned_url("get_object", Params=prm, ExpiresIn=900)
        audit(user, "総論の原稿の取得", f"総論{s['label']}", name + (f"(版 {qs['v'][:8]})" if qs.get("v") else "")); return resp(200, {"url": url})
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

# ---------- 手順書(委員がポータルから受け取る。個別に送らない) ----------
# (ファイル名に含む語, 対象, 閲覧できる役割。None は全員)
DOCS = [("操作マニュアル", "全委員", None), ("SR委員の手順書", "SR委員", {"統括委員会", "事務局", "SR委員長", "SR委員", "作成グループ"}), ("SR委員長の業務手順", "SR委員長", ROLE_LEAD),
        ("論文PDFの入手", "SR委員", {"統括委員会", "事務局", "SR委員長", "SR委員"}), 
        ("総説執筆者の手順書", "総論の執筆者", {"統括委員会", "事務局", "総説執筆者"}), ("用語の定義", "全委員", None), ("統括委員会へのお願い", "統括委員会", ROLE_ADMIN)]


def doc_list(g, kind, show_missing):
    """文書の一覧。kind=scope: Scope だけ / all: 全て / 省略: 手順書だけ。g は利用者の役割。"""
    if not BUCKET: return []
    link = {x["sk"]: x.get("url", "") for x in query("DOCLINK")}; out = []
    def row(o, target):
        name = o["Key"].split("/", 1)[1]
        return {"name": name, "target": target, "updated": o["LastModified"].isoformat()[:10], "key": o["Key"], "drive": link.get(name, ""), "available": True,
                "url": s3().generate_presigned_url("get_object", Params={"Bucket": BUCKET, "Key": o["Key"]}, ExpiresIn=900)}
    miss = lambda name, target: {"name": name, "target": target, "updated": "", "url": "", "drive": "", "available": False}
    if kind in ("scope", "all"):
        sc = s3().list_objects_v2(Bucket=BUCKET, Prefix="scope/").get("Contents", [])
        plan = json.load(open(os.path.join(HERE, "approved_plan.json"), encoding="utf-8"))
        for pre in ["SC-1", "SC-2", "SC-3"] + [f"SC-4_{it['名称']}" for it in plan["SR項目"] + plan["FRQ項目"]]:
            o = next((x for x in sc if x["Key"].split("/", 1)[1].startswith(pre)), None)
            if o: out.append(row(o, "Scope"))
            elif show_missing: out.append(miss(pre, "Scope"))
        if kind == "scope": return out
    objs = s3().list_objects_v2(Bucket=BUCKET, Prefix="docs/").get("Contents", [])
    for k, target, roles in DOCS:
        if roles is not None and not (g & roles): continue
        o = next((x for x in objs if k in x["Key"]), None)
        if o: out.append(row(o, target))
        elif show_missing: out.append(miss(k, target))
    return out


def docs(method, parts, body, user):
    # GET  /docs               自分の役割で閲覧できる手順書の一覧(取得用の署名付きURL)
    # GET  /docs/view?name=    文書を、画面に表示する構造で返す
    # PUT  /docs/links         Google Drive 上の URL を登録する(scripts/sync_drive.py)
    # POST /docs/upload-url    統括委員会・事務局が手順書を置く(scripts/upload_docs.py)
    g = set(user["groups"])
    if method == "POST" and parts[1:2] == ["upload-url"]:
        require(user, ROLE_ADMIN)
        name = re.sub(r"[^\w.\-一-龥ぁ-んァ-ン（）()・、]", "_", str(body.get("filename", "")))[:100]
        if re.match(r"SC-[1-4]", name) and name.endswith(".xlsx"):   # Scope(Minds 第3章の様式 SC-1〜SC-4)。「Scope」の画面に出す
            url = s3().generate_presigned_url("put_object", Params={"Bucket": BUCKET, "Key": f"scope/{name}", "ContentType": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"}, ExpiresIn=900)
            audit(user, "Scope の登録", name); return resp(200, {"url": url, "key": f"scope/{name}"})
        if not name.endswith(".docx") or not any(k in name for k, _, _ in DOCS): return resp(400, {"error": "手順書のファイル名ではありません"})
        url = s3().generate_presigned_url("put_object", Params={"Bucket": BUCKET, "Key": f"docs/{name}", "ContentType": "application/vnd.openxmlformats-officedocument.wordprocessingml.document"}, ExpiresIn=900)
        audit(user, "手順書の登録", name); return resp(200, {"url": url, "key": f"docs/{name}"})
    if method == "PUT" and parts[1:2] == ["links"]:
        # Google Drive 上の同じファイルの URL(scripts/sync_drive.py が、転送したファイルの ID から登録する)
        require(user, ROLE_ADMIN); n = 0
        for name, url in (body.get("links") or {}).items():
            if not re.fullmatch(r"https://drive\.google\.com/[\w\-./?=&%]+", str(url)) or "/" in str(name): continue
            if (get("DOCLINK", str(name)) or {}).get("url") != url: put("DOCLINK", str(name), {"url": url}); n += 1
        if n: audit(user, "Google Drive のリンクの登録", f"{n}件")
        return resp(200, {"saved": n})
    if method == "GET":
        q_ = body.get("_query") or {}
        if parts[1:2] == ["view"]:   # ブラウザで表示する(ダウンロードしない)
            L = doc_list(g, "all", False)   # name: ファイル名 / doc: 手順書の名称の一部(画面の「手順書」のリンク)
            d = next((x for x in L if x["name"] == q_.get("name")), None) or next((x for x in L if q_.get("doc") and x["target"] != "Scope" and q_["doc"] in x["name"]), None)
            if not d: return resp(404, {"error": "文書がありません"})
            import viewer
            data = s3().get_object(Bucket=BUCKET, Key=d["key"])["Body"].read()
            try: v = viewer.view(d["name"], data)
            except Exception: return resp(422, {"error": "この文書は、画面に表示できません。ダウンロードして開いてください", "url": d["url"]})
            return resp(200, {**{k: d[k] for k in ("name", "target", "updated", "url", "drive")}, **v})
        return resp(200, [{k: v for k, v in d.items() if k != "key"} for d in doc_list(g, q_.get("kind", ""), q_.get("missing") == "1" and bool(g & ROLE_ADMIN))])
    return resp(405, {"error": "方法が不正です"})


# ---------- 検索の記録、スクリーニング(2名独立の可否)、文献選択の流れ図 ----------
SCREEN_REASONS = ["18歳未満が対象", "がん患者でない", "英語でない", "国内で施行できない方法・薬物", "研究デザインが対象外(総説・症例報告など)", "CIPNに関する研究でない", "本CQの介入を評価していない",
                  "予防・治療の目的が本CQと異なる", "対象の化学療法が本CQと異なる", "重複", "計画書のみ", "副次解析", "主要評価が本CQのアウトカムでない", "全文が入手できない", "その他(備考に記載)"]  # 前回Scopeの選択基準に対応
S2_ONLY_REASONS = ["主要評価が本CQのアウトカムでない", "副次解析", "全文が入手できない"]   # 全文を読んで決める理由。一次(題名・抄録)では使わない(Minds 第4章: 一次ではアウトカムを考慮せず、抄録で判断できないものは残す)
SCREEN_SOURCES = ["検索(PubMed)", "更新検索", "既存ガイドラインの引用文献", "ハンドサーチ", "作成委員のサーベイランス", "その他"]
DB_SOURCES = {"検索(PubMed)", "更新検索"}  # データベース検索。他は「その他の情報源」
S1_DEC = ["採用", "除外", "保留"]; S2_DEC = ["採用", "除外"]
STAGE_JA = {"s1": "一次", "s2": "二次"}


def can_edit_cq(user, c):
    return is_assignee(user, c) or bool(set(user["groups"]) & ROLE_LEAD)


def search(method, parts, body, user):
    # GET /search/<cq>            検索の記録の一覧
    # POST /search/<cq>           追加(担当委員、SR委員長、統括委員会、事務局)
    # PUT /search/<cq>/<id>       修正(変更は作成経過の記録に残る)
    # DELETE /search/<cq>/<id>    削除(SR委員長、統括委員会、事務局)
    if len(parts) < 2: return resp(400, {"error": "CQ が必要です"})
    cqid = parts[1]; c = get("CQ", cqid)
    if not c: return resp(404, {"error": "ありません"})
    if parts[2:3] == ["reference"]:
        # 参考: 2023年版の検索過程と、検索式の案(platform/data/search_reference.json。scripts/import_search_reference.py が置く)
        if method == "GET": return resp(200, get("SEARCHREF", cqid) or {})
        if method == "POST":
            require(user, ROLE_ADMIN)
            ref = {k: body.get(k) or [] for k in ("formula", "prior", "last_search_end_2023", "notes")}
            put("SEARCHREF", cqid, {"cq": cqid, **ref}); audit(user, "検索の参考資料の登録", cqid, f"検索式の案 {len(ref['formula'])}件、2023年版の検索過程 {len(ref['prior'])}件"); return resp(200, {"ok": True})
    if method == "GET":
        return resp(200, sorted(query("SEARCH", f"{cqid}#"), key=lambda r: (r.get("date", ""), r["sk"])))
    if not can_edit_cq(user, c): raise Forbidden("この CQ の担当委員、SR委員長、統括委員会、事務局に限ります")
    if method == "DELETE" and len(parts) > 2:
        require(user, ROLE_LEAD)
        r = get("SEARCH", f"{cqid}#{parts[2]}")
        if r: table().delete_item(Key={"pk": "SEARCH", "sk": r["sk"]}); bump(cqid); audit(user, "検索の記録の削除", cqid, f"{r.get('database', '')} {r.get('date', '')} {r.get('hits', '')}件")
        return resp(200, {"ok": True})
    if method in ("POST", "PUT"):
        old = get("SEARCH", f"{cqid}#{parts[2]}") if method == "PUT" and len(parts) > 2 else None
        if method == "PUT" and not old: return resp(404, {"error": "ありません"})
        r = {k: str(body.get(k, "")).strip() for k in ("database", "date", "searcher", "period", "query", "note")}
        if not re.match(r"^\d{4}-\d{2}-\d{2}$", r["date"]): return resp(400, {"error": "検索日は 年-月-日(例: 2026-12-01)で入力してください"})
        miss = [ja for k, ja in (("database", "データベース"), ("searcher", "検索者"), ("query", "検索式")) if not r[k]]
        if miss: return resp(400, {"error": "・".join(miss) + " が必要です"})
        try: r["hits"] = int(body.get("hits"))
        except (TypeError, ValueError): return resp(400, {"error": "件数は数で入力してください"})
        if r["hits"] < 0: return resp(400, {"error": "件数は 0 以上です"})
        sid = old["id"] if old else new_id()
        r.update({"cq": cqid, "id": sid, "created_by": (old or {}).get("created_by") or user["name"] or user["email"]})
        put("SEARCH", f"{cqid}#{sid}", r); bump(cqid)
        audit(user, "検索の記録の修正" if old else "検索の記録", cqid, f"{r['database']} {r['date']} 検索者 {r['searcher']} {r['hits']}件 期間 {r['period']} 式: {r['query']}"[:1000])
        return resp(200, r)
    return resp(405, {"error": "方法が不正です"})


def pubmed_meta(pmids):
    """PubMed(E-utilities の efetch)から、題名・著者・誌名・年・抄録を取る。取れなかった PMID は結果に含めない。"""
    import pubmed
    return pubmed.fetch(pmids)


def stage_result(c, recs, stage):
    """1つの文献・1つの段階の結果。協議の結論があればそれ。なければ、2名の判定が一致したときだけ結果になる。記録にない結果は作らない。"""
    fin = (c.get("final") or {}).get(stage)
    ds = [(r["reviewer"], r[stage]) for r in recs if (r.get(stage) or {}).get("decision")]
    if fin: return {"decision": fin["decision"], "reason": fin.get("reason", ""), "by": "協議の結論", "n": len(ds)}
    vals = {d["decision"] for _, d in ds}
    if len(ds) >= 2 and len(vals) == 1:
        return {"decision": vals.pop(), "reason": next((d.get("reason") for _, d in ds if d.get("reason")), ""), "by": "2名の一致", "n": len(ds)}
    return {"decision": "", "state": "不一致" if len(vals) > 1 else "", "n": len(ds)}


def screen_data(cqid):
    cands = sorted(query("CAND", f"{cqid}#"), key=lambda c: int(c["pmid"]))
    recs = {}
    for r in query("SCR", f"{cqid}#"): recs.setdefault(r["pmid"], []).append(r)
    return cands, recs


def to_s2(c, r1):
    """二次(全文)の対象。一次を経ずに追加した文献、または一次の結果が 採用・保留 の文献。"""
    return bool(c.get("direct")) or r1["decision"] in ("採用", "保留")


def classify(cands, recs):
    """文献を、流れ図の枠ごとの一覧に分ける。流れ図の件数と、別添の一覧は、この一覧から作る(件数と一覧が必ず一致する)。
    戻り値: 枠の名 → [(文献, 一次の結果, 二次の結果)]"""
    L = {k: [] for k in ("all", "db", "other", "s1_target", "s1_include", "s1_hold", "s1_exclude", "s1_open", "s1_conflict", "direct", "s2_target", "s2_include", "s2_exclude", "s2_open", "s2_conflict")}
    for c in cands:
        rs = recs.get(c["pmid"], []); r1 = stage_result(c, rs, "s1"); r2 = stage_result(c, rs, "s2"); row = (c, r1, r2)
        L["all"].append(row); L["db" if c.get("source") in DB_SOURCES else "other"].append(row)
        if c.get("direct"): L["direct"].append(row)
        else:
            L["s1_target"].append(row); L[{"採用": "s1_include", "保留": "s1_hold", "除外": "s1_exclude"}.get(r1["decision"], "s1_open")].append(row)
            if r1.get("state") == "不一致": L["s1_conflict"].append(row)
        if to_s2(c, r1):
            L["s2_target"].append(row); L[{"採用": "s2_include", "除外": "s2_exclude"}.get(r2["decision"], "s2_open")].append(row)
            if r2.get("state") == "不一致": L["s2_conflict"].append(row)
    return L


def flow(cqid, cands=None, recs=None):
    """文献選択の流れ図の件数。検索の記録と、スクリーニングの記録(2名の一致、または協議の結論)だけを数える。"""
    if cands is None: cands, recs = screen_data(cqid)
    searches = query("SEARCH", f"{cqid}#"); L = classify(cands, recs)
    by_db = {}
    for s_ in searches: by_db[s_.get("database", "")] = by_db.get(s_.get("database", ""), 0) + int(s_.get("hits") or 0)
    f = {"searches": len(searches), "db_hits": sum(by_db.values()), "by_db": by_db, "duplicates": sum(len(b.get("duplicates") or []) for b in query("SCRIMP", f"{cqid}#")),
         "cand_db": len(L["db"]), "cand_other": len(L["other"]), "cands": len(L["all"]), "s2_reasons": {}}
    for k in ("s1_target", "s1_include", "s1_hold", "s1_exclude", "s1_open", "s1_conflict", "direct", "s2_target", "s2_include", "s2_exclude", "s2_open", "s2_conflict"): f[k] = len(L[k])
    for _, _, r2 in L["s2_exclude"]: f["s2_reasons"][r2.get("reason") or "理由の記録なし"] = f["s2_reasons"].get(r2.get("reason") or "理由の記録なし", 0) + 1
    papers = {p["pmid"] for p in query("PAPER", f"{cqid}#")}
    f["registered"] = sum(1 for c, _, _ in L["s2_include"] if c["pmid"] in papers)
    f["papers"] = len(papers); f["papers_unscreened"] = len(papers - {c["pmid"] for c in cands})   # スクリーニングの記録がなく登録済みの論文(2023年版の引用文献として取り込んだ論文など)
    return f


def bump(cqid):
    """この CQ の検索・スクリーニング・論文の記録が変わったことを記す(保存してある流れ図の件数を、次に読むときに数え直す)。"""
    table().update_item(Key={"pk": "SCRMETA", "sk": cqid}, UpdateExpression="ADD rev :one", ExpressionAttributeValues={":one": 1})


def flow_cached(cqid, fresh=None):
    """流れ図の件数。記録が変わっていなければ、保存してある件数を返す(進捗ボードで、全CQの文献を毎回読まないため)。"""
    meta = get("SCRMETA", cqid) or {}; rev = int(meta.get("rev", 0))
    if fresh is None and meta.get("flow") is not None and int(meta.get("flow_rev", -1)) == rev: return meta["flow"]
    f = fresh if fresh is not None else flow(cqid)
    table().update_item(Key={"pk": "SCRMETA", "sk": cqid}, UpdateExpression="SET flow = :f, flow_rev = :r", ExpressionAttributeValues={":f": _py(f), ":r": rev})
    return f


def who_decisions(rs, st, fin=None):
    """出力(別添・Minds書類)に載せる、各委員の判定。2名独立のため、その段階を 2名以上が判定した後(または協議の結論がある場合)だけ載せる。
    1名だけが判定した段階は、空にする(共有ドライブに置いた出力から、もう一人の担当委員に見えないようにする)。"""
    ds = [r for r in rs if (r.get(st) or {}).get("decision")]
    if len(ds) < 2 and not (fin or {}).get(st): return ""
    return "、".join(f"{r['reviewer']}: {r[st]['decision']}" + (f"({r[st]['reason']})" if r[st].get("reason") else "") for r in ds)


def cand_row(cd, rs, name, mine, lead):
    """画面に返す 1 文献の行。抄録は含めない(別に取得する)。2名独立: 担当委員には、自分がその段階を判定するまで、他の委員の判定を返さない。"""
    my = next((r for r in rs if r["reviewer"] == name), None) or {}
    row = {k: cd.get(k, "") for k in ("pmid", "title", "authors", "journal", "year", "source", "added_by", "added_why")}
    row.update({"has_abstract": bool(cd.get("has_abstract")), "direct": bool(cd.get("direct")), "final": cd.get("final") or {}, "mine": {k: my.get(k) for k in ("s1", "s2", "ft", "note", "history")}})
    for st in ("s1", "s2"):
        row[st] = stage_result(cd, rs, st)
        show = (lead and not mine) or bool((my.get(st) or {}).get("decision"))
        row[st + "_others"] = [{"reviewer": r["reviewer"], **(r.get(st) or {})} for r in rs if r["reviewer"] != name and (r.get(st) or {}).get("decision")] if show else []
    return row


MAX_CANDS = 8000  # 1つの CQ の対象の上限(画面が一度に読む量の上限)


def screening(method, parts, body, user):
    # GET /screening                          全CQの流れ図の件数
    # GET /screening/<cq>                     対象の文献、自分の判定、照合、流れ図の件数
    # POST /screening/<cq>/candidates         対象の文献の取り込み(検索結果、その他の情報源)。登録済みの文献は重複として記録する
    # POST /screening/<cq>/fetch              題名・抄録を PubMed から取得する(未取得の文献。1回に100件まで)
    # GET /screening/<cq>/<pmid>/abstract     抄録
    # PUT /screening/<cq>/<pmid>              自分の判定(一次・二次の可否、除外理由、全文の状態、備考)
    # PUT /screening/<cq>/<pmid>/final        協議の結論(不一致の解消、または結果の修正)
    if len(parts) < 2:
        return resp(200, {c["id"]: flow_cached(c["id"]) for c in query("CQ")})
    cqid = parts[1]; c = get("CQ", cqid)
    if not c: return resp(404, {"error": "ありません"})
    name = user["name"]; mine = is_assignee(user, c); lead = bool(set(user["groups"]) & ROLE_LEAD)
    sub = parts[2] if len(parts) > 2 else ""
    if method == "GET" and not sub:
        cands, recs = screen_data(cqid); f = flow_cached(cqid, flow(cqid, cands, recs))
        return resp(200, {"cq": cqid, "can_edit": mine or lead, "reviewer": mine, "candidates": [cand_row(cd, recs.get(cd["pmid"], []), name, mine, lead) for cd in cands], "flow": f, "reasons": SCREEN_REASONS, "reasons_s2_only": S2_ONLY_REASONS, "sources": SCREEN_SOURCES})
    if method == "GET" and parts[3:4] == ["abstract"]:
        a = get("ABS", f"{cqid}#{re.sub(r'[^0-9]', '', sub)}"); return resp(200, {"abstract": (a or {}).get("abstract", "")})
    if not (mine or lead): raise Forbidden("この CQ の担当委員、SR委員長、統括委員会、事務局に限ります")
    if method == "POST" and sub == "candidates":
        src = str(body.get("source", "")); direct = bool(body.get("direct")); why = str(body.get("why", "")).strip()
        if src not in SCREEN_SOURCES: return resp(400, {"error": "出典は " + " / ".join(SCREEN_SOURCES)})
        if src not in DB_SOURCES and not why: return resp(400, {"error": "データベース検索以外の文献は、追加の理由が必要です"})
        if direct and src in DB_SOURCES: return resp(400, {"error": "データベース検索の文献は、一次スクリーニングを経ます"})
        have = {x["pmid"] for x in query("CAND", f"{cqid}#")}; items = body.get("items") or []
        if len(items) > 1000: return resp(400, {"error": "1回に取り込めるのは 1000 件までです"})
        added, dup, bad, new = [], [], 0, {}
        for it in items:
            pmid = re.sub(r"\D", "", str(it.get("pmid", "")))
            if not 5 <= len(pmid) <= 9: bad += 1
            elif pmid in have or pmid in new: dup.append(pmid)
            else: new[pmid] = it
        if len(have) + len(new) > MAX_CANDS: return resp(409, {"error": f"1つの CQ の対象は {MAX_CANDS} 件までです。検索式を統括委員会で確認してください"})
        with table().batch_writer() as bw:
            for pmid, it in new.items():
                ab = str(it.get("abstract", ""))[:6000]; added.append(pmid)
                bw.put_item(Item=_py({"pk": "CAND", "sk": f"{cqid}#{pmid}", "updated_at": now(), "cq": cqid, "pmid": pmid, "title": str(it.get("title", ""))[:500], "authors": str(it.get("authors", ""))[:300],
                                      "authors_all": str(it.get("authors_all", ""))[:3000], "journal": str(it.get("journal", ""))[:200], "year": str(it.get("year", ""))[:10], "doi": str(it.get("doi", ""))[:100],
                                      "has_abstract": bool(ab), "meta_fetched": now() if it.get("title") and "abstract" in it else "", "source": src, "search_id": str(body.get("search_id", "")), "direct": direct,
                                      "added_by": name or user["email"], "added_why": why}))
                if ab: bw.put_item(Item={"pk": "ABS", "sk": f"{cqid}#{pmid}", "abstract": ab})
        dup = sorted(set(dup))
        put("SCRIMP", f"{cqid}#{new_id()}", {"cq": cqid, "at": now(), "by": name or user["email"], "source": src, "search_id": str(body.get("search_id", "")), "direct": direct, "why": why, "added": added, "duplicates": dup, "invalid": bad})
        bump(cqid)
        audit(user, "スクリーニング対象の取り込み", cqid, f"出典 {src}。追加 {len(added)}件、登録済みのため除いた重複 {len(dup)}件、PMIDでない行 {bad}件" + ("。一次を経ない(二次の対象)" if direct else "") + (f"。理由: {why}" if why else ""))
        return resp(200, {"added": len(added), "duplicates": len(dup), "invalid": bad})
    if method == "POST" and sub == "fetch":
        todo = [cd for cd in query("CAND", f"{cqid}#") if not cd.get("has_abstract") and not cd.get("meta_fetched")][:100]
        if not todo: return resp(200, {"fetched": 0, "asked": 0, "remaining": 0})
        try: meta = pubmed_meta([cd["pmid"] for cd in todo])
        except Exception as e: return resp(502, {"error": f"PubMed から取得できませんでした({type(e).__name__})。時間をおいて、もう一度実行してください"})
        for cd in todo:
            m_ = dict(meta.get(cd["pmid"]) or {}); ab = m_.pop("abstract", "")
            cd.update({k: v for k, v in m_.items() if v}); cd["meta_fetched"] = now(); cd["has_abstract"] = bool(ab); put("CAND", cd["sk"], cd)
            if ab: put("ABS", cd["sk"], {"abstract": ab})
        rest = sum(1 for cd in query("CAND", f"{cqid}#") if not cd.get("has_abstract") and not cd.get("meta_fetched"))
        audit(user, "題名・抄録の取得(PubMed)", cqid, f"{len(todo)}件のうち {len(meta)}件を取得"); return resp(200, {"fetched": len(meta), "asked": len(todo), "remaining": rest})
    pmid = re.sub(r"\D", "", sub); cd = get("CAND", f"{cqid}#{pmid}") if pmid else None
    if not cd: return resp(404, {"error": "この文献は、スクリーニングの対象に登録されていません"})
    rs = query("SCR", f"{cqid}#{pmid}#")
    if method == "PUT" and parts[3:4] == ["final"]:
        st = body.get("stage"); dec = str(body.get("decision", "")); reason = str(body.get("reason", "")); why = str(body.get("why", "")).strip()
        if st not in ("s1", "s2") or dec not in (S1_DEC if st == "s1" else S2_DEC): return resp(400, {"error": "段階または判定の値が不正です"})
        if dec == "除外" and reason not in SCREEN_REASONS: return resp(400, {"error": "除外には、除外理由が必要です"})
        if st == "s1" and reason in S2_ONLY_REASONS: return resp(400, {"error": f"「{reason}」は、全文を読んで決める理由です。一次では使えません(判断できないときは、残します)"})
        if not why: return resp(400, {"error": "協議の内容(結論の理由)が必要です"})
        opinion = str(body.get("opinion", "")).strip()
        if not opinion: return resp(400, {"error": "第三者の意見(SR委員長への報告と、その意見)が必要です(Minds: 不一致は、第三者の意見を取り入れて決める)"})
        opinion_by = (name or user["email"]) if "SR委員長" in set(user["groups"]) else (str(body.get("opinion_by", "")).strip() or "SR委員長")
        if sum(1 for r in rs if (r.get(st) or {}).get("decision")) < 2 and not lead: return resp(409, {"error": "2名の判定がそろってから、協議の結論を記録します"})
        if st == "s2" and not to_s2(cd, stage_result(cd, rs, "s1")): return resp(409, {"error": "一次の結果が 採用・保留 の文献だけが、二次の対象です"})
        before = stage_result(cd, rs, st)
        cd.setdefault("final", {})[st] = {"decision": dec, "reason": reason if dec == "除外" else "", "why": why, "opinion": opinion[:1000], "opinion_by": opinion_by[:40], "by": name or user["email"], "at": now()}
        put("CAND", cd["sk"], cd); bump(cqid)
        audit(user, f"スクリーニングの協議の結論({STAGE_JA[st]})", f"{cqid} / PMID {pmid}", f"{before['decision'] or before.get('state') or '結果なし'} → {dec}" + (f"(除外理由: {reason})" if dec == "除外" else "") + f"。協議: {why}。第三者の意見({opinion_by}): {opinion[:300]}")
        return resp(200, {"ok": True, **stage_result(cd, rs, st), "row": cand_row(cd, rs, name, mine, lead)})
    if method == "PUT":
        if not mine or not name: raise Forbidden("判定を入力できるのは、この CQ の担当委員です(SR委員長は協議の結論を記録できます)")
        r = next((x for x in rs if x["reviewer"] == name), None) or {"cq": cqid, "pmid": pmid, "reviewer": name, "s1": {}, "s2": {}, "ft": "未入手", "note": "", "history": []}
        log = lambda field, old, new_, why_: r["history"].append({"at": now(), "field": field, "from": old, "to": new_, "reason": why_})
        if "ft" in body:
            if body["ft"] not in ("未入手", "入手済", "読了"): return resp(400, {"error": "全文の状態は 未入手 / 入手済 / 読了"})
            if body["ft"] != r.get("ft"): log("全文", r.get("ft", ""), body["ft"], ""); r["ft"] = body["ft"]
        if "note" in body: r["note"] = str(body["note"])[:1000]
        st = body.get("stage")
        if st:
            dec = str(body.get("decision", "")); reason = str(body.get("reason", ""))
            if st not in ("s1", "s2") or dec not in (S1_DEC if st == "s1" else S2_DEC): return resp(400, {"error": "段階または判定の値が不正です"})
            if st == "s1" and cd.get("direct"): return resp(409, {"error": "一次を経ずに追加した文献です。二次の判定を入力してください"})
            if st == "s2" and not (cd.get("direct") or (r.get("s1") or {}).get("decision") in ("採用", "保留") or to_s2(cd, stage_result(cd, rs, "s1"))):
                return resp(409, {"error": "二次の対象は、一次が 採用・保留 の文献です"})
            if dec == "除外" and reason not in SCREEN_REASONS: return resp(400, {"error": "除外には、除外理由が必要です"})
            if st == "s1" and reason in S2_ONLY_REASONS: return resp(400, {"error": f"「{reason}」は、全文を読んで決める理由です。一次では使えません(判断できないときは、残します)"})
            cur = r.get(st) or {}
            if cur.get("decision") and (cur["decision"] != dec or cur.get("reason", "") != (reason if dec == "除外" else "")):
                # 他の委員の判定が見える状態になった後(2名がそろった後)は、自分の判定を変えない。協議の結論で記録する
                if any((x.get(st) or {}).get("decision") for x in rs if x["reviewer"] != name) or (cd.get("final") or {}).get(st):
                    return resp(409, {"error": "2名の判定がそろった後は、判定を変更できません。「協議の結論」で記録してください"})
                why = str(body.get("change_reason", "")).strip()
                if not why: return resp(400, {"error": "判定の変更には、変更の理由が必要です"})
                log(STAGE_JA[st] + "の判定", cur["decision"] + (f"({cur['reason']})" if cur.get("reason") else ""), dec + (f"({reason})" if dec == "除外" else ""), why)
            r[st] = {"decision": dec, "reason": reason if dec == "除外" else "", "at": now()}
        put("SCR", f"{cqid}#{pmid}#{name}", r)
        if st: bump(cqid); audit(user, f"スクリーニングの判定({STAGE_JA[st]})", f"{cqid} / PMID {pmid}", "判定を記録")   # 2名独立のため、作成経過の記録に判定の値を出さない
        rs = [x for x in rs if x["reviewer"] != name] + [r]
        return resp(200, {"mine": {k: r.get(k) for k in ("s1", "s2", "ft", "note", "history")}, "s1": stage_result(cd, rs, "s1"), "s2": stage_result(cd, rs, "s2"), "row": cand_row(cd, rs, name, mine, lead)})
    return resp(405, {"error": "方法が不正です"})


def screening_lists(cqid):
    """別添(文献の一覧)の材料。流れ図の件数と同じ分け方(classify)で、枠ごとの文献の一覧を返す。"""
    cands, recs = screen_data(cqid); L = classify(cands, recs); searches = {s_["id"]: s_ for s_ in query("SEARCH", f"{cqid}#")}
    batches = sorted(query("SCRIMP", f"{cqid}#"), key=lambda b: b["sk"]); title = {c["pmid"]: c for c in cands}
    def line(c, r1, r2):
        rs = recs.get(c["pmid"], []); fin = c.get("final") or {}; sr = searches.get(c.get("search_id") or "", {})
        who = lambda st: who_decisions(rs, st, fin)
        return {"pmid": c["pmid"], "title": c.get("title", ""), "authors": c.get("authors_all") or c.get("authors", ""), "journal": c.get("journal", ""), "year": c.get("year", ""), "doi": c.get("doi", ""),
                "source": c.get("source", ""), "search": f"{sr.get('date', '')} {sr.get('database', '')}".strip(), "added_why": c.get("added_why", ""),
                "s1": "一次を経ない" if c.get("direct") else (r1["decision"] or r1.get("state") or f"判定 {r1['n']} 名"), "s1_reason": r1.get("reason", ""), "s1_by": r1.get("by", ""), "s1_who": who("s1"),
                "s2": (r2["decision"] or r2.get("state") or f"判定 {r2['n']} 名") if to_s2(c, r1) else "", "s2_reason": r2.get("reason", ""), "s2_by": r2.get("by", ""), "s2_who": who("s2"),
                "why": " / ".join(f"{STAGE_JA[st]}: {fin[st].get('why', '')}({fin[st].get('by', '')})。第三者の意見({fin[st].get('opinion_by', '')}): {fin[st].get('opinion', '')}" for st in ("s1", "s2") if fin.get(st))}
    dups = [{"pmid": pm, "title": (title.get(pm) or {}).get("title", ""), "authors": (title.get(pm) or {}).get("authors_all") or (title.get(pm) or {}).get("authors", ""), "at": b.get("at", ""), "source": b.get("source", ""),
             "search": f"{searches.get(b.get('search_id') or '', {}).get('date', '')}".strip()} for b in batches for pm in (b.get("duplicates") or [])]
    per_search = []
    for s_ in sorted(searches.values(), key=lambda x: (x.get("date", ""), x["id"])):
        bs = [b for b in batches if b.get("search_id") == s_["id"]]; a = sum(len(b.get("added") or []) for b in bs); d = sum(len(b.get("duplicates") or []) for b in bs)
        per_search.append({**s_, "added": a, "dups": d, "diff": int(s_.get("hits") or 0) - a - d})
    return {"flow": flow(cqid, cands, recs), "lists": {k: [line(*row) for row in v] for k, v in L.items()}, "duplicates": dups, "searches": per_search}
