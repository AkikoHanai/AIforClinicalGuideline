"""GL作成ポータル API の試験(moto で DynamoDB と S3 を模擬。Bedrock は呼ばない)。
  python3 -m pytest platform/portal/tests -q
"""
import io, json, os, shutil, sys
import pytest

HERE = os.path.dirname(os.path.abspath(__file__))
API = os.path.join(HERE, "..", "api")
os.environ.update({"TABLE_NAME": "jascc-gl-portal-test", "PAPERS_BUCKET": "papers-test", "AWS_DEFAULT_REGION": "ap-northeast-1", "AWS_ACCESS_KEY_ID": "testing", "AWS_SECRET_ACCESS_KEY": "testing", "USER_POOL_ID": ""})
os.environ.pop("AWS_LAMBDA_FUNCTION_NAME", None)
shutil.copy(os.path.join(HERE, "..", "..", "governance", "approved_plan.json"), os.path.join(API, "approved_plan.json"))
sys.path.insert(0, API)
import boto3
from moto import mock_aws
import handler as H
import extract_text as X

CHAIR = dict(email="chair@example.org", groups=("統括委員会",))
R1 = dict(email="motoo@example.org", groups=("SR委員",))
R2 = dict(email="kikuchi@example.org", groups=("SR委員",))
LEAD = dict(email="lead@example.org", groups=("SR委員長",))


def ev(method, path, body=None, email="chair@example.org", groups=("統括委員会",)):
    return {"requestContext": {"http": {"method": method}, "authorizer": {"jwt": {"claims": {"email": email, "cognito:groups": "[" + " ".join(groups) + "]"}}}},
            "rawPath": path, "body": json.dumps(body, ensure_ascii=False) if body is not None else None}


def call(method, path, body=None, who=CHAIR):
    r = H.handler(ev(method, path, body, **who)); return r["statusCode"], json.loads(r["body"])


def make_pdf():
    from pypdf import PdfWriter
    from pypdf.generic import DecodedStreamObject, NameObject, DictionaryObject, ArrayObject, FloatObject
    # pypdf だけで文字入りPDFを作る(フォントは標準の Helvetica)
    w = PdfWriter()
    lines = ["Abstract", "Background. We tested cooling for taxane neuropathy in breast cancer patients.", "Methods", "Randomization was performed centrally using a computer generated sequence.",
             "Patients and outcome assessors were not blinded to the allocation.", "Analyses followed the intention to treat principle including all randomized patients.", "Results",
             "Of 120 randomized patients, 6 in the intervention arm and 9 in the control arm were lost to follow up.", "Grade 2 or higher neuropathy occurred in 20 of 60 versus 35 of 60 patients.", "Discussion", "Cooling reduced neuropathy."]
    content = "BT /F1 11 Tf 40 760 Td 14 TL " + " ".join(f"({l}) Tj T*" for l in lines) + " ET"
    page = w.add_blank_page(width=595, height=842)
    font = DictionaryObject({NameObject("/Type"): NameObject("/Font"), NameObject("/Subtype"): NameObject("/Type1"), NameObject("/BaseFont"): NameObject("/Helvetica")})
    page[NameObject("/Resources")] = DictionaryObject({NameObject("/Font"): DictionaryObject({NameObject("/F1"): w._add_object(font)})})
    stream = DecodedStreamObject(); stream.set_data(content.encode("latin-1"))
    page[NameObject("/Contents")] = w._add_object(stream)
    buf = io.BytesIO(); w.write(buf); return buf.getvalue()


@pytest.fixture
def env():
    with mock_aws():
        boto3.resource("dynamodb").create_table(TableName=H.TABLE, KeySchema=[{"AttributeName": "pk", "KeyType": "HASH"}, {"AttributeName": "sk", "KeyType": "RANGE"}],
                                                AttributeDefinitions=[{"AttributeName": "pk", "AttributeType": "S"}, {"AttributeName": "sk", "AttributeType": "S"}], BillingMode="PAY_PER_REQUEST")
        boto3.client("s3").create_bucket(Bucket=H.BUCKET, CreateBucketConfiguration={"LocationConstraint": "ap-northeast-1"})
        H._ddb = None
        assert call("POST", "/admin/seed")[0] == 200
        for who, name in ((R1, "元雄良治"), (R2, "菊池健"), (LEAD, "中川夏樹"), (CHAIR, "華井明子")):
            assert call("POST", "/users", {"email": who["email"], "name": name, "roles": list(who["groups"])})[0] == 200
        assert call("PUT", "/cq/P1", {"outcomes": ["CIPN Grade2以上の発生", "QOL"], "pico": {"P": "白金製剤またはタキサン系薬剤を受ける大腸癌・乳癌患者"}}, LEAD)[0] == 200
        yield


def register_paper(pmid="12345678"):
    c, r = call("POST", f"/papers/P1/{pmid}/upload-url", {"title": "Cooling RCT"}, R1); assert c == 200 and r["key"] == f"papers/P1/{pmid}.pdf"
    boto3.client("s3").put_object(Bucket=H.BUCKET, Key=r["key"], Body=make_pdf(), ContentType="application/pdf")
    c, x = call("POST", f"/papers/P1/{pmid}/extract", {}, R1); assert c == 200
    return x


def test_seed_follows_plan(env):
    c, cqs = call("GET", "/cq"); assert c == 200 and len(cqs) == 15 and sum(1 for x in cqs if x["kind"] == "SR") == 11
    c, soron = call("GET", "/soron"); assert len(soron) == 19 and next(s for s in soron if s["key"] == "K")["title"] == "漢方・鍼灸治療"
    assert call("POST", "/admin/seed")[1]["created"] == 0
    assert call("POST", "/admin/seed", who=R1)[0] == 403


def test_paper_register_extract_and_sections(env):
    x = register_paper()
    assert x["pages"] == 1 and x["sections"]["methods"] >= 1 and x["sections"]["results"] >= 1
    c, t = call("GET", "/papers/P1/12345678/text", who=R2); assert c == 200
    ids = [p["id"] for p in t["paragraphs"]]; assert ids[0] == "12345678-p001" and len(ids) == len(set(ids))
    secs = {p["section"] for p in t["paragraphs"]}; assert {"methods", "results"} <= secs
    assert any("Randomization was performed centrally" in p["text"] and p["section"] == "methods" for p in t["paragraphs"])
    # 外部の人(担当でない SR委員)は登録できないが、本文は読める。PDF の URL は署名付き
    assert call("POST", "/papers/P1/99/upload-url", {}, dict(email="x@example.org", groups=("SR委員",)))[0] == 403
    c, u = call("GET", "/papers/P1/12345678/pdf-url", who=R2); assert c == 200 and "X-Amz-Signature" in u["url"]
    # 研究特性: 化学療法の分類は7区分に限る
    assert call("PUT", "/papers/P1/12345678", {"chars": {"cancer": "乳癌", "chemo_class": "タキサン系", "chemo_drugs": "paclitaxel"}}, R1)[0] == 200
    assert call("PUT", "/papers/P1/12345678", {"chars": {"chemo_class": "不正"}}, R1)[0] == 400
    c, cq = call("GET", "/cq/P1"); assert cq["stages"]["論文登録"] == "1件(本文抽出済 1件)" and cq["stages"]["CQ確定"] == "承認済み(統括委員長)"


def test_f45_two_reviewers_blind_then_reconcile(env):
    register_paper()
    o = "CIPN Grade2以上の発生"; path = f"/f45/P1/12345678/{o}"
    items = {k: {"v": 0, "evidence": ["12345678-p002"], "quote": "Randomization was performed centrally"} for k in H.ITEM_KEYS}
    items["blinding_participants"] = {"v": -2, "evidence": [], "quote": "not blinded"}  # -2 は -1 に直される
    items["blinding_assessors"] = {"v": -1, "evidence": [], "quote": "記載なし"}
    c, r = call("PUT", path, {"items": items, "submitted": True}, R1); assert c == 200 and r["items"]["blinding_participants"]["v"] == -1
    # 相手(R2)は、R1 の評価を見られない
    c, d = call("GET", path, who=R2); assert c == 200 and d["others"] == {} and d["mine"] is None and d["reconcile_open"] is False
    # 提出後、本人は変更できない
    assert call("PUT", path, {"items": items, "submitted": True}, R1)[0] == 409
    items2 = {**items, "concealment": {"v": -1, "evidence": [], "quote": "記載なし"}}
    assert call("PUT", path, {"items": items2, "submitted": True}, R2)[0] == 200
    # 2名が提出すると、互いの評価と照合欄が開く
    c, d = call("GET", path, who=R1); assert d["reconcile_open"] and "菊池健" in d["others"] and d["others"]["菊池健"]["items"]["concealment"]["v"] == -1
    # 第三者は確定できない。提出した評価者は確定できる
    assert call("PUT", path + "/final", {"items": items2}, dict(email="x@example.org", groups=("SR委員",)))[0] == 403
    c, f = call("PUT", path + "/final", {"items": items2, "note": "協議でコンシールメントは記載なしとした"}, R2); assert c == 200 and f["based_on"] == ["元雄良治", "菊池健"]
    c, d = call("GET", path, who=R1); assert d["final"]["fixed_by"] == "菊池健"
    # 下書きは、本文がない論文では作れない(未抽出の論文)
    call("POST", "/papers/P1/22222222/upload-url", {}, R1)
    assert call("POST", f"/f45/P1/22222222/{o}/draft", {}, R1)[0] == 409
    # 空欄の提出も保存できるが、提出時の全項目チェックは画面側。アウトカム外は 400
    assert call("PUT", "/f45/P1/12345678/未登録のアウトカム", {"items": {}}, R1)[0] == 400
    log = call("GET", "/audit")[1]; assert any(a["action"] == "様式4-5の確定(照合)" for a in log)


def test_sr8_stratified_by_chemo_class_and_stage_auto(env):
    register_paper("11111111"); register_paper("22222222")
    call("PUT", "/papers/P1/11111111", {"chars": {"chemo_class": "白金製剤", "cancer": "大腸癌"}}, R1)
    call("PUT", "/papers/P1/22222222", {"chars": {"chemo_class": "タキサン系", "cancer": "乳癌"}}, R1)
    o = "CIPN Grade2以上の発生"
    items = {k: {"v": 0, "evidence": [], "quote": "x"} for k in H.ITEM_KEYS}
    for pm in ("11111111", "22222222"):
        call("PUT", f"/f45/P1/{pm}/{o}/final", {"items": items, "effect": {"measure": "RR", "value": 0.6}}, LEAD)
    c, d = call("GET", "/sr8/P1", who=R2); assert c == 200
    row = next(x for x in d["outcomes"] if x["outcome"] == o)
    assert row["n_studies"] == 2 and set(row["by_chemo_class"]) == {"白金製剤", "タキサン系"}
    assert call("PUT", f"/sr8/P1/{o}", {"rob": "0", "inconsistency": "-1", "imprecision": "-1", "indirectness": "0", "publication_bias": "0", "upgrade": "0", "certainty": "C(弱)", "strata": "白金製剤とタキサン系で方向は同じ"}, R1)[0] == 200
    assert call("PUT", f"/sr8/P1/{o}", {"certainty": "C(弱)"}, dict(email="x@example.org", groups=("SR委員",)))[0] == 403
    c, cq = call("GET", "/cq/P1")
    assert cq["stages"]["様式4-5"] == "確定 2/4(提出 0)"  # 2論文×2アウトカム。QOL が未確定
    assert cq["stages"]["様式SR-8"] == "確実性 記入 1/2"  # QOL が未記入
    assert cq["progress"] == 50


def test_etd_2023_reference_and_vote(env):
    c, r = call("POST", "/gl2023", {"items": [{"plan_id": "P1", "title": "牛車腎気丸", "rec": "2023年版の推奨文。", "strength": "2", "certainty": "C", "narrative": "解説の一文目。解説の二文目。", "votes": {"n": 15, "coi": 1, "sr": 2, "counts": [0, 12, 3, 0, 0], "denominator": 15}}]})
    assert c == 200 and r["imported"] == 1
    c, d = call("GET", "/etd/P1", who=R1); assert d["gl2023"]["paragraphs"][0]["id"] == "GL2023-P1-p001" and len(d["gl2023"]["paragraphs"]) == 2
    assert call("PUT", "/etd/P1", {"rec_draft": "x"}, R1)[0] == 403  # SR委員は EtD を書けない
    body = {"rec_draft": "タキサン系薬剤によるCIPNの予防に冷却療法を提案する", "strength": "2 弱く推奨", "certainty": "C(弱)",
            "considerations": {"benefit_harm": {"text": "Grade2以上の減少", "evidence": ["12345678-p009", "GL2023-P1-p001"]}},
            "vote": {"round": 1, "counts": [0, 13, 2, 0, 0], "denominator": 15, "coi_excluded": 1, "sr_excluded": 2, "date": "2027-09-01"}}
    c, e = call("PUT", "/etd/P1", body, dict(email="g@example.org", groups=("作成グループ",))); assert c == 200 and e["vote"]["agreement"] == 87
    assert call("PUT", "/etd/P1", {"status": "確定"}, dict(email="g@example.org", groups=("作成グループ",)))[0] == 403  # 確定は統括委員会
    assert call("PUT", "/etd/P1", {"status": "確定"})[1]["status"] == "確定"
    assert call("GET", "/cq/P1")[1]["stages"]["EtD"] == "確定"


def test_soron_flow_separated_from_sr(env):
    W = dict(email="naito@example.org", groups=("総説執筆者",))
    assert call("PUT", "/soron/A", {"status": "執筆中"}, W)[0] == 403  # 氏名未登録
    call("POST", "/users", {"email": "naito@example.org", "name": "内藤陽一", "roles": ["総説執筆者"]})
    # 総説執筆者は SR の流れの画面に入れない
    assert call("GET", "/cq", who=W)[0] == 403 and call("GET", "/papers/P1", who=W)[0] == 403
    # 原稿の提出 → 査読中 → 統括委員会の査読コメントで修正中 → 完了は統括委員会だけ
    c, r = call("POST", "/soron/A/upload-url", {"filename": "総論A_内藤.docx", "content_type": "application/vnd.openxmlformats-officedocument.wordprocessingml.document"}, W); assert c == 200 and r["key"].startswith("soron/A/")
    boto3.client("s3").put_object(Bucket=H.BUCKET, Key=r["key"], Body=b"docx")
    assert call("GET", "/soron", who=W)[1][0]["file"] == "総論A_内藤.docx"
    assert call("PUT", "/soron/A", {"status": "査読中"}, W)[1]["status"] == "査読中"
    assert call("PUT", "/soron/A", {"review": "表1の出典を追記"}, W)[0] == 403
    assert call("PUT", "/soron/A", {"review": "表1の出典を追記"})[1]["status"] == "修正中"
    assert call("PUT", "/soron/A", {"status": "完了"}, W)[0] == 403
    assert call("PUT", "/soron/A", {"status": "完了"})[1]["status"] == "完了"
    assert call("PUT", "/soron/B", {"status": "執筆中"}, W)[0] == 403  # 他人の総論
    c, files = call("GET", "/soron/A/files", who=W); assert c == 200 and files[0]["key"] == "総論A_内藤.docx"
    # SR委員は総説の画面に入れない
    assert call("GET", "/soron", who=R1)[0] == 403
    assert call("POST", "/users", {"email": "a@b", "name": "x", "roles": []}, R1)[0] == 403
    c, d = call("GET", "/dashboard", who=dict(email="naito@example.org", groups=("総説執筆者",))); assert [s["key"] for s in d["my_soron"]] == ["A"]


def test_audit_append_only_and_unauthenticated(env):
    n = len(call("GET", "/audit")[1]); assert n > 0
    assert call("DELETE", "/audit")[0] == 200 and len(call("GET", "/audit")[1]) == n
    assert H.handler({"requestContext": {"http": {"method": "GET"}}, "rawPath": "/cq"})["statusCode"] == 401


def test_extract_relevant_prefers_methods_results():
    paras = X.paragraphs("1", [(1, "Abstract\nShort abstract text that is long enough to be a paragraph here.\nMethods\nWe randomized patients using sealed envelopes and a random table.\nResults\nNeuropathy occurred in ten of fifty patients in each of the two arms.\nDiscussion\nThis discussion paragraph should not be sent to the model by default.")])
    sel = X.relevant(paras); assert {p["section"] for p in sel} == {"methods", "results"}
