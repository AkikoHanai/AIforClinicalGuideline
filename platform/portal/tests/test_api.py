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


def test_export_and_gl2023_soron(env):
    register_paper("11111111")
    call("PUT", "/papers/P1/11111111", {"chars": {"chemo_class": "白金製剤", "cancer": "大腸癌"}}, R1)
    o = "CIPN Grade2以上の発生"
    items = {k: {"v": 0, "evidence": ["11111111-p002"], "quote": "x"} for k in H.ITEM_KEYS}
    call("PUT", f"/f45/P1/11111111/{o}/final", {"items": items, "counts": {"ctrl_num": 30, "ctrl_den": 60, "int_num": 20, "int_den": 60}, "effect": {"measure": "RR", "value": 0.67}}, LEAD)
    call("PUT", f"/sr8/P1/{o}", {"rob": "0", "inconsistency": "0", "imprecision": "-1", "indirectness": "0", "publication_bias": "0", "upgrade": "0", "certainty": "B(中)"}, R1)
    c, r = call("GET", "/export/P1", who=R1); assert c == 200 and r["sheets"] == ["CQ", "研究特性", "様式4-5", "様式SR-8", "SoF表", "EtD・推奨", "作成経過"] and r["bytes"] > 5000
    import openpyxl, io
    data = boto3.client("s3").get_object(Bucket=H.BUCKET, Key=r["key"])["Body"].read()
    wb = openpyxl.load_workbook(io.BytesIO(data))
    sof = [row for row in wb["SoF表"].iter_rows(values_only=True)]
    assert sof[1][0] == o and sof[1][2] == "30/60" and sof[1][3] == "20/60" and sof[1][5] == "B(中)"
    f45 = [row for row in wb["様式4-5"].iter_rows(values_only=True)]; assert f45[1][1] == "11111111" and f45[1][4] == 0
    # 2023年版総論の取り込み(統括委員会のみ)。総説執筆者が参照できる
    items2 = {"items": [{"key": "H", "title": "H.CIPNの評価", "paragraphs": [{"id": "GL2023-総論H-p001", "text": "評価の段落。"}], "filename": "総論H.docx"}]}
    assert call("POST", "/gl2023/soron", items2, R1)[0] == 403
    c, r2 = call("POST", "/gl2023/soron", items2); assert c == 200 and r2["imported"] == 1 and r2["upload_urls"][0]
    call("POST", "/users", {"email": "hanai@example.org", "name": "華井明子", "roles": ["総説執筆者"]})
    c, g = call("GET", "/soron/H/gl2023", who=dict(email="hanai@example.org", groups=("総説執筆者",))); assert c == 200 and g["paragraphs"][0]["id"] == "GL2023-総論H-p001"
    # EtD下書きは SR-8 がなければ作らない(P2)。P1 では作成中になる(Bedrock は呼ばれない環境では失敗として記録される)
    assert call("POST", "/etd/P2/draft", {}, dict(email="g@example.org", groups=("作成グループ",)))[0] == 409
    assert call("POST", "/etd/P1/draft", {}, dict(email="g@example.org", groups=("作成グループ",)))[0] == 202
    assert call("GET", "/etd/P1")[1]["etd"]["ai_draft"]["status"] in ("下書き", "失敗")


def test_audit_append_only_and_unauthenticated(env):
    n = len(call("GET", "/audit")[1]); assert n > 0
    assert call("DELETE", "/audit")[0] == 200 and len(call("GET", "/audit")[1]) == n
    assert H.handler({"requestContext": {"http": {"method": "GET"}}, "rawPath": "/cq"})["statusCode"] == 401


def test_extract_relevant_prefers_methods_results():
    paras = X.paragraphs("1", [(1, "Abstract\nShort abstract text that is long enough to be a paragraph here.\nMethods\nWe randomized patients using sealed envelopes and a random table.\nResults\nNeuropathy occurred in ten of fifty patients in each of the two arms.\nDiscussion\nThis discussion paragraph should not be sent to the model by default.")])
    sel = X.relevant(paras); assert {p["section"] for p in sel} == {"methods", "results"}


def test_extract_inline_headings_chunks_and_quality():
    pages = [(1, "METHODS Patients with breast cancer receiving paclitaxel were randomized to cooling or control. " + "The primary outcome was CTCAE grade 2 or higher sensory neuropathy. " * 40),
             (2, "Results: Of 120 patients, 60 received cooling. Grade 2 or higher neuropathy occurred in 20% versus 50% of controls at 12 weeks.")]
    paras = X.paragraphs("1", pages)
    assert any(p["section"] == "methods" for p in paras) and any(p["section"] == "results" for p in paras)
    assert all(len(p["text"]) <= X.CHUNK for p in paras) and sum(len(p["text"]) for p in paras) > 2500  # 切り捨てない
    assert X.quality(pages, paras) == "本文抽出済"
    assert X.quality([(1, ""), (2, "")], []).startswith("画像PDF")
    assert X.quality([(1, "x" * 3000), (2, ""), (3, ""), (4, "")], [{"section": "methods", "text": "x"}]).startswith("画像PDF")  # 大半のページに文字層が無い
    assert X.quality([(1, "Some text. " * 100)], [{"section": "other", "text": "x"}]).startswith("本文抽出済(節の見出し")


def test_put_ocr_text(env):
    H.handler(ev("POST", "/admin/seed", {}, **CHAIR))
    H.handler(ev("POST", "/papers/N1/99999999/upload-url", {"title": "t"}, **CHAIR))
    r = H.handler(ev("PUT", "/papers/N1/99999999/text", {"pages": [{"page": 1, "text": "Methods\nPatients were randomized to cooling. " * 5 + "\n\nResults\nNeuropathy was less frequent in the cooling group than in controls."}], "source": "OCR(Apple Vision)"}, **CHAIR))
    j = json.loads(r["body"]); assert r["statusCode"] == 200 and j["sections"]["methods"] == 1 and j["sections"]["results"] == 1 and j["status"] == "本文抽出済(OCR(Apple Vision))"
    t = json.loads(H.handler(ev("GET", "/papers/N1/99999999/text", **CHAIR))["body"]); assert t["source"] == "OCR(Apple Vision)"


def test_extract_heading_forms_seen_in_registered_papers():
    """登録済み論文で見出しを判定できなかった 3 形式(Clinical Trial Results 形式、番号 + 縦線、多段の番号)"""
    body = "Patients received the study drug for six cycles and neuropathy was graded at each visit by a blinded assessor. "
    sec = lambda lines: [p["section"] for p in X.paragraphs("1", [(1, "\n".join(lines))])]
    assert sec(["Methods. Pain-free, chemotherapy-naive CRC patients receiv-", body, "", "Results. One hundred ninety-nine patients were randomized.", body]) == ["methods", "results"]
    assert sec(["1 | INTRODUCTION", body, "", "2 | PATIENTS AND METHODS", body, "", "3 | RESULTS", body, "", "4 | DISCUSSION", body]) == ["other", "methods", "results", "discussion"]
    assert sec(["2. Investigations and results", body, "", "3. Discussion", body, "", "4.1. Patients and methods", body]) == ["results", "discussion", "methods"]
    assert sec(["Statistical Methods: Descriptive data analysis presented categorical variables as observed counts.", body]) == ["methods"]
    assert sec(["Introduction", body, "Results were reported as predicted means for numeric outcomes in each group."]) == ["other"]  # 文は見出しにしない


def test_dashboard_counts_and_approvals(env):
    """進捗ボード: 記録された件数、承認(確定)の記録がない件、役割による分離"""
    register_paper(); o = "CIPN Grade2以上の発生"; path = f"/f45/P1/12345678/{o}"
    items = {k: {"v": 0, "evidence": [], "quote": "x"} for k in H.ITEM_KEYS}
    call("PUT", path, {"items": items, "submitted": True}, R1)
    d = call("GET", "/dashboard", who=R1)[1]; p1 = next(c for c in d["cq"] if c["id"] == "P1")
    assert p1["counts"] == {"outcomes": 2, "papers": 1, "extracted": 1, "f45_need": 2, "f45_submitted": 1, "f45_fixed": 0, "f45_wait": 0, "sr8": 0, "etd_status": "", "etd_agreement": None}
    assert d["approvals"] == [] and d["my_f45_todo_count"] == 1  # R1 の未提出は QOL の 1 件
    call("PUT", path, {"items": items, "submitted": True}, R2)
    d = call("GET", "/dashboard", who=R1)[1]; a = d["approvals"]
    assert len(a) == 1 and a[0]["kind"] == "様式4-5の照合・確定" and a[0]["can"] is True and a[0]["q"] == {"cq": "P1", "pmid": "12345678", "outcome": o}
    assert next(c for c in d["cq"] if c["id"] == "P1")["counts"]["f45_wait"] == 1
    call("PUT", path + "/final", {"items": items}, R2)
    assert call("GET", "/dashboard", who=R1)[1]["approvals"] == []  # 確定の記録があれば出さない
    # EtD: 協議中は統括委員会の確定待ち。作成グループには can=False で示す
    G = dict(email="g@example.org", groups=("作成グループ",))
    call("PUT", "/etd/P1", {"rec_draft": "x", "status": "協議中", "vote": {"round": 1, "counts": [0, 13, 2, 0, 0], "denominator": 15}}, G)
    a = call("GET", "/dashboard", who=G)[1]["approvals"]; assert [x["kind"] for x in a] == ["EtD・推奨の確定"] and a[0]["can"] is False and "合意率 87%" in a[0]["record"]
    assert call("GET", "/dashboard")[1]["approvals"][0]["can"] is True  # 統括委員会
    # 総説執筆者だけの利用者には、SR の記録を返さない
    d = call("GET", "/dashboard", who=dict(email="w@example.org", groups=("総説執筆者",)))[1]; assert d["cq"] == [] and d["approvals"] == []


def test_web_style_rules():
    """画面の体裁の規則(統括委員長の指示): 文字の大きさは 1 種類、白抜き文字を使わない、承認箇所の印(.approve)がある"""
    import re
    web = os.path.join(HERE, "..", "web")
    css = re.sub(r"/\*.*?\*/", "", open(os.path.join(web, "style.css"), encoding="utf-8").read(), flags=re.S)
    js = open(os.path.join(web, "app.js"), encoding="utf-8").read(); html = open(os.path.join(web, "index.html"), encoding="utf-8").read()
    assert len(re.findall(r"font-size\s*:", css)) == 1 and "font-size" not in js and "font-size" not in html  # body の指定だけ
    assert not re.search(r"(?<![-\w])color\s*:\s*(#fff\b|#ffffff\b|white\b)", css + js + html, re.I)   # 字の色に白を使わない
    assert ".approve" in css and js.count('class="approve"') >= 4  # 様式4-5 の確定、EtD の確定、総論の完了、進捗ボード
    assert "承認(確定)が必要な記録" in js and "作業手順(SRの流れ)" in js
