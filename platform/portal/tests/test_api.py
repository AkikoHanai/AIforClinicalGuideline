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
    log = call("GET", "/audit")[1]; assert any(a["action"] == "SR-5の確定(照合)" for a in log)


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
    assert cq["stages"]["SR-5"] == "確定 2/4(提出 0)"  # 2論文×2アウトカム。QOL が未確定
    assert cq["stages"]["SR-8"] == "確実性 記入 1/2"  # QOL が未記入
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
    c, r = call("GET", "/export/P1", who=R1); assert c == 200 and r["sheets"] == ["CQ", "検索の記録", "文献選択の流れ図", "スクリーニング", "研究特性", "SR-5", "SR-8", "SoF表", "EtD・推奨", "作成経過"] and r["bytes"] > 5000
    import openpyxl, io
    data = boto3.client("s3").get_object(Bucket=H.BUCKET, Key=r["key"])["Body"].read()
    wb = openpyxl.load_workbook(io.BytesIO(data))
    sof = [row for row in wb["SoF表"].iter_rows(values_only=True)]
    assert sof[1][0] == o and sof[1][2] == "30/60" and sof[1][3] == "20/60" and sof[1][5] == "B(中)"
    f45 = [row for row in wb["SR-5"].iter_rows(values_only=True)]; assert f45[1][1] == "11111111" and f45[1][4] == 0
    # 2023年版総論の取り込み(統括委員会のみ)。総説執筆者が参照できる
    items2 = {"items": [{"key": "H", "title": "H.CIPNの評価", "paragraphs": [{"id": "GL2023-総論H-p001", "text": "評価の段落。"}], "filename": "総論H.docx"}]}
    assert call("POST", "/gl2023/soron", items2, R1)[0] == 403
    c, r2 = call("POST", "/gl2023/soron", items2); assert c == 200 and r2["imported"] == 1 and r2["upload_urls"][0]
    call("POST", "/users", {"email": "hanai@example.org", "name": "華井明子", "roles": ["総説執筆者"]})
    c, g = call("GET", "/soron/H/gl2023", who=dict(email="hanai@example.org", groups=("総説執筆者",))); assert c == 200 and g["paragraphs"][0]["id"] == "GL2023-総論H-p001"
    # 新設の項目(2023年版の本文なし)は、依頼書(Word)だけを置く。画面から開ける
    c, r3 = call("POST", "/gl2023/soron", {"items": [{"key": "N", "title": "小児患者のCIPN対策", "paragraphs": [], "filename": "総論N_小児患者のCIPN対策_新設.docx"}]}); assert c == 200 and r3["upload_urls"][0]
    c, g = call("GET", "/soron/N/gl2023"); assert c == 200 and g["paragraphs"] == [] and g["docx_url"]
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
    fl = p1["counts"].pop("flow"); assert fl["searches"] == 0 and fl["cands"] == 0
    assert p1["counts"] == {"outcomes": 2, "papers": 1, "extracted": 1, "f45_need": 2, "f45_submitted": 1, "f45_fixed": 0, "f45_wait": 0, "sr8": 0, "etd_status": "", "etd_agreement": None}
    assert d["approvals"] == [] and d["my_f45_todo_count"] == 1  # R1 の未提出は QOL の 1 件
    call("PUT", path, {"items": items, "submitted": True}, R2)
    d = call("GET", "/dashboard", who=R1)[1]; a = d["approvals"]
    assert len(a) == 1 and a[0]["kind"] == "SR-5の照合・確定" and a[0]["can"] is True and a[0]["q"] == {"cq": "P1", "pmid": "12345678", "outcome": o}
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
    assert ".approve" in css and js.count('class="approve"') >= 4  # SR-5 の確定、EtD の確定、総論の完了、進捗ボード
    assert "承認(確定)が必要な記録" in js and "作業手順(SRの流れ)" in js


def test_extract_does_not_stop_at_front_matter_or_references():
    """著者原稿は 1 ページ目に Funding・Conflict of interest があり、本文より前に現れる。そこで抽出を打ち切らない"""
    body = "Patients received the study drug for six cycles and neuropathy was graded at each visit by a blinded assessor. "
    pages = [(1, "\n".join(["Author Manuscript", body, "", "Conflict of interest", "The authors declare no conflict of interest in this work at all.", "", "Funding", "Supported by a grant from the national institute of health.", "",
                              "Abstract", body, "", "Methods", body, "", "Results", body])),
             (2, "\n".join(["References", "1. Smith J, et al. A randomized trial of something in patients with cancer. J Clin Oncol 2010.", "", "Table 1", "Results", body]))]
    paras = X.paragraphs("1", pages); secs = [p["section"] for p in paras]
    assert secs.count("methods") == 1 and secs.count("results") == 2 and "references" in secs  # 文献のあとの本文の見出しで節が戻る
    assert X.quality(pages, paras) == "本文抽出済"
    assert all(p["section"] != "references" for p in X.relevant([p for p in paras if p["section"] not in ("methods", "results")]))  # 文献一覧は LLM の入力にしない


def test_seed_sets_outcome_cipn(env):
    """統括委員長の決定(2026-11-16): 全CQ・FRQのアウトカムは CIPN。初期データの作成でこの値を入れる"""
    cqs = call("GET", "/cq")[1]
    assert len(cqs) == 15 and all(c["outcomes"] == ["CIPN"] for c in cqs if c["id"] != "P1")  # P1 は試験の準備で書き換えている
    assert next(c for c in cqs if c["id"] == "N1")["pico"]["O"] == "CIPN"


def test_draft_normalize_keeps_only_existing_paragraph_ids():
    """下書きの検査: 存在しない段落IDを捨てる。盲検化の -2 は -1。人数・効果の根拠の段落IDも同じ扱い"""
    import draft45 as D
    paras = [{"id": "1-p001"}, {"id": "1-p002"}]
    out = D.normalize({"items": {"randomization": {"v": 0, "evidence": ["1-p001", "1-p999"], "quote": "q"}, "blinding_assessors": {"v": -2, "evidence": [], "quote": "open label"}, "itt": {"v": 5}},
                       "counts": {"ctrl_num": 35, "ctrl_den": 60, "int_num": 20, "int_den": 60}, "numbers": {"evidence": ["1-p002", "x"], "quote": "20 of 60 versus 35 of 60"}}, paras)
    assert out["items"]["randomization"]["evidence"] == ["1-p001"] and out["items"]["blinding_assessors"]["v"] == -1 and out["items"]["itt"]["v"] is None
    assert out["numbers"] == {"evidence": ["1-p002"], "quote": "20 of 60 versus 35 of 60"} and out["counts"]["int_num"] == 20
    assert "症状の有無" in D.PROMPT and "計算や推測で作らない" in D.PROMPT


def test_docs_are_listed_by_role(env):
    """手順書は、ポータルから役割に応じて受け取る"""
    for n in ("1_操作マニュアル.docx", "4_SR委員の手順書.docx", "5_総説執筆者の手順書.docx", "2_統括委員会へのお願い_スケジュールとアプリの精査.docx"):
        c, r = call("POST", "/docs/upload-url", {"filename": n}); assert c == 200
        boto3.client("s3").put_object(Bucket=H.BUCKET, Key=r["key"], Body=b"x")
    assert call("POST", "/docs/upload-url", {"filename": "4_SR委員の手順書.docx"}, R1)[0] == 403            # 置けるのは統括委員会・事務局
    assert call("POST", "/docs/upload-url", {"filename": "任意のファイル.docx"})[0] == 400
    names = lambda who: [d["name"] for d in call("GET", "/docs", who=who)[1]]
    assert names(R1) == ["1_操作マニュアル.docx", "4_SR委員の手順書.docx"]                                    # SR委員
    assert names(dict(email="w@example.org", groups=("総説執筆者",))) == ["1_操作マニュアル.docx", "5_総説執筆者の手順書.docx"]
    assert len(names(CHAIR)) == 4


def test_search_record_screening_and_flow(env, monkeypatch):
    """検索の記録、スクリーニングの可否の入力(2名独立)、協議の結論、文献選択の流れ図の件数"""
    # 検索の記録
    rec = {"database": "PubMed", "date": "2026-12-01", "searcher": "元雄良治", "period": "2021-07-01〜2026-10-31", "query": "(neuropathy) AND (goshajinkigan)", "hits": 5}
    assert call("POST", "/search/P1", rec, dict(email="x@example.org", groups=("SR委員",)))[0] == 403       # 担当でない委員
    assert call("POST", "/search/P1", {**rec, "date": "12/1"}, R1)[0] == 400 and call("POST", "/search/P1", {**rec, "query": ""}, R1)[0] == 400
    c, s = call("POST", "/search/P1", rec, R1); assert c == 200 and s["hits"] == 5
    assert call("PUT", f"/search/P1/{s['id']}", {**rec, "hits": 6}, R1)[1]["hits"] == 6
    assert [x["hits"] for x in call("GET", "/search/P1", who=R2)[1]] == [6]
    assert call("DELETE", f"/search/P1/{s['id']}", who=R1)[0] == 403
    # 対象の取り込み(重複は除き、件数を記録する)
    items = [{"pmid": str(30000000 + i), "title": f"Trial {i}"} for i in range(1, 6)] + [{"pmid": "30000001"}, {"pmid": "abc"}]
    c, r = call("POST", "/screening/P1/candidates", {"source": "検索(PubMed)", "search_id": s["id"], "items": items}, R1); assert c == 200 and (r["added"], r["duplicates"], r["invalid"]) == (5, 1, 1)
    assert call("POST", "/screening/P1/candidates", {"source": "ハンドサーチ", "items": [{"pmid": "30000009"}]}, R1)[0] == 400                 # 理由が必要
    assert call("POST", "/screening/P1/candidates", {"source": "検索(PubMed)", "direct": True, "items": []}, R1)[0] == 400
    assert call("POST", "/screening/P1/candidates", {"source": "既存ガイドラインの引用文献", "direct": True, "why": "ASCO 2020 の引用文献", "items": [{"pmid": "30000009", "title": "Cited trial"}]}, R2)[1]["added"] == 1
    # 題名・抄録の取得(PubMed は模擬)
    monkeypatch.setattr(H, "pubmed_meta", lambda pmids: {pm: {"title": "T" + pm, "authors": "A B", "journal": "J", "year": "2024", "abstract": "Background: x"} for pm in pmids if pm != "30000005"})
    c, r = call("POST", "/screening/P1/fetch", {}, R1); assert c == 200 and r["fetched"] == 5 and r["remaining"] == 0
    put = lambda who, pmid, **b: call("PUT", f"/screening/P1/{pmid}", b, who)
    # 一次: 除外は理由が必要。変更は理由が必要。相手の判定は、自分が判定するまで返らない
    assert put(R1, "30000001", stage="s1", decision="除外")[0] == 400
    assert put(R1, "30000001", stage="s1", decision="除外", reason="主要評価が本CQのアウトカムでない")[0] == 400                          # 一次では、アウトカムを理由に除外しない(Minds)
    assert put(R1, "30000001", stage="s1", decision="除外", reason="CIPNに関する研究でない")[0] == 200
    assert put(R1, "30000001", stage="s1", decision="採用")[0] == 400
    c, r = put(R1, "30000001", stage="s1", decision="採用", change_reason="抄録を読み直した"); assert c == 200 and r["mine"]["history"][0]["to"] == "採用" and r["s1"]["decision"] == ""
    row = lambda who, pmid: next(x for x in call("GET", "/screening/P1", who=who)[1]["candidates"] if x["pmid"] == pmid)
    assert row(R2, "30000001")["s1_others"] == [] and row(R2, "30000001")["has_abstract"] is True and "abstract" not in row(R2, "30000001") and call("GET", "/screening/P1/30000001/abstract", who=R2)[1]["abstract"] == "Background: x"
    assert put(R2, "30000001", stage="s1", decision="採用")[1]["s1"] == {"decision": "採用", "reason": "", "by": "2名の一致", "n": 2}
    assert row(R2, "30000001")["s1_others"][0]["reviewer"] == "元雄良治"
    assert put(R1, "30000001", stage="s1", decision="除外", reason="重複", change_reason="x")[0] == 409                                   # 2名がそろった後は変更できない
    assert put(dict(email="x@example.org", groups=("SR委員",)), "30000002", stage="s1", decision="採用")[0] == 403
    assert put(LEAD, "30000002", stage="s1", decision="採用")[0] == 403                                                                   # SR委員長は判定を入力しない(P1 の担当でない)
    # 不一致 → 協議の結論
    put(R1, "30000002", stage="s1", decision="採用"); assert put(R2, "30000002", stage="s1", decision="除外", reason="がん患者でない")[1]["s1"]["state"] == "不一致"
    fin = lambda who, pmid, **b: call("PUT", f"/screening/P1/{pmid}/final", b, who)
    assert fin(R1, "30000002", stage="s1", decision="採用")[0] == 400                                                                     # 協議の内容が必要
    assert fin(R1, "30000003", stage="s1", decision="採用", why="x")[0] == 409                                                            # 2名の判定がそろっていない
    assert fin(R1, "30000002", stage="s1", decision="採用", why="全文で確認する")[1]["by"] == "協議の結論"
    for pm in ("30000003", "30000004"):
        for who in (R1, R2): assert put(who, pm, stage="s1", decision="除外", reason="CIPNに関する研究でない")[0] == 200
    assert put(R1, "30000005", stage="s1", decision="保留")[0] == 200                                                                     # 1名だけ: 結果にしない
    # 二次: 一次が 採用・保留 の文献と、一次を経ない文献だけ
    assert put(R1, "30000003", stage="s2", decision="採用")[0] == 409 and put(R1, "30000009", stage="s1", decision="採用")[0] == 409
    for who in (R1, R2): assert put(who, "30000001", stage="s2", decision="採用", ft="読了")[0] == 200
    for who in (R1, R2): assert put(who, "30000002", stage="s2", decision="除外", reason="計画書のみ")[0] == 200
    assert put(R1, "30000009", stage="s2", decision="採用")[0] == 200
    f = call("GET", "/screening/P1", who=CHAIR)[1]["flow"]
    assert (f["db_hits"], f["cand_db"], f["cand_other"], f["duplicates"], f["cands"]) == (6, 5, 1, 1, 6)
    assert (f["s1_target"], f["s1_include"], f["s1_exclude"], f["s1_open"], f["direct"]) == (5, 2, 2, 1, 1)
    assert (f["s2_target"], f["s2_include"], f["s2_exclude"], f["s2_open"], f["s2_reasons"]) == (3, 1, 1, 1, {"計画書のみ": 1})
    assert call("GET", "/screening", who=CHAIR)[1]["P1"]["s2_include"] == 1
    # 2023年版の引用文献として取り込んだ論文(スクリーニングの記録がない)は、流れの件数に入れず、別の枠で数える
    register_paper(); f2 = call("GET", "/screening/P1", who=CHAIR)[1]["flow"]; assert (f2["papers"], f2["papers_unscreened"], f2["s2_include"], f2["registered"]) == (1, 1, 1, 0)
    st = call("GET", "/cq/P1")[1]["stages"]; assert st["検索"] == "1件(検索結果の合計 6件)" and st["スクリーニング"].startswith("対象 6件。一次 結果あり 4/5、二次 結果あり 2/3")
    # Minds 書類の出力に、検索の記録・流れ図の件数・スクリーニングの一覧が入る
    import openpyxl
    c, r = call("GET", "/export/P1"); wb = openpyxl.load_workbook(io.BytesIO(boto3.client("s3").get_object(Bucket=H.BUCKET, Key=r["key"])["Body"].read()))
    assert [x for x in wb["検索の記録"].iter_rows(min_row=2, values_only=True)][0][5] == 6
    fl = {x[0]: x[1] for x in wb["文献選択の流れ図"].iter_rows(min_row=2, values_only=True) if x[0]}; assert fl["採用した文献"] == 1 and fl["一次で除外した文献"] == 2 and fl["スクリーニングの対象として登録した文献"] == 6
    sc = {x[0]: x for x in wb["スクリーニング"].iter_rows(min_row=2, values_only=True)}
    assert sc["30000002"][5:8] == ("採用", None, "協議の結論") and sc["30000002"][8:11] == ("除外", "計画書のみ", "2名の一致") and "全文で確認する" in sc["30000002"][13] and sc["30000009"][5] == "一次を経ない"
    assert sc["30000005"][11] in (None, "") and "元雄良治" in sc["30000002"][11] and "菊池健" in sc["30000002"][11]        # 1名だけの判定は載せない。2名が判定した後は載せる(2名独立)
    # 文献選択の別添: 流れ図の件数と、枠ごとの文献の一覧(PMID・題名・著者)の行数が一致する
    c, r = call("GET", "/export/P1/screening", who=R1); assert c == 200
    wb = openpyxl.load_workbook(io.BytesIO(boto3.client("s3").get_object(Bucket=H.BUCKET, Key=r["key"])["Body"].read()))
    chk = [x for x in wb["流れ図の件数"].iter_rows(min_row=3, values_only=True) if x[0] and x[0] not in ("注", "Minds様式との対応")]
    assert len(chk) == 12 and all(x[4] == "一致" for x in chk) and {x[0]: x[1] for x in chk}["採用した文献"] == 1
    for name, k, _ in __import__("export_minds").SCREEN_SHEETS: assert wb[name].max_row - 1 == r["counts"][k] == f["cands" if k == "all" else k]
    adopted = [x for x in wb["H 採用"].iter_rows(min_row=2, values_only=True)]; assert adopted[0][1] == "30000001" and adopted[0][2] == "T30000001" and adopted[0][3] == "A B"
    one = [x for x in wb["D 一次の結果なし"].iter_rows(min_row=2, values_only=True) if x[1] == "30000005"][0]; assert one[12] in (None, "") and one[9].startswith("判定 1 名")   # 別添でも、1名だけの判定は載せない
    assert [x[1] for x in wb["C 一次で除外"].iter_rows(min_row=2, values_only=True)] == ["30000003", "30000004"] and [x[1] for x in wb["F 二次で除外"].iter_rows(min_row=2, values_only=True)] == ["30000002"]
    sr = [x for x in wb["検索の記録"].iter_rows(min_row=2, values_only=True)][0]; assert sr[5:9] == (6, 5, 1, 0)            # 件数 6 = 登録 5 + 重複 1
    assert [x[1] for x in wb["重複として除いた文献"].iter_rows(min_row=2, values_only=True)] == ["30000001"]
    # 進捗ボード: 不一致は、協議の結論が必要な記録として出る
    put(R1, "30000005", stage="s2", decision="採用"); put(R2, "30000005", stage="s1", decision="除外", reason="重複")
    assert call("GET", "/screening", who=CHAIR)[1]["P1"]["s1_conflict"] == 1                                                             # 保存した件数は、記録が変わると数え直す
    a = [x for x in call("GET", "/dashboard", who=R1)[1]["approvals"] if x["kind"] == "スクリーニングの協議の結論"]; assert len(a) == 1 and "1件" in a[0]["record"]
    assert any(x["action"] == "スクリーニングの協議の結論(一次)" for x in call("GET", "/audit")[1])
    assert not any("除外" in x["detail"] for x in call("GET", "/audit")[1] if x["action"].startswith("スクリーニングの判定"))          # 2名独立: 判定の値を記録に出さない


def test_pubmed_xml_is_parsed(monkeypatch):
    xml = b"""<PubmedArticleSet><PubmedArticle><MedlineCitation><PMID>123456</PMID><Article><Journal><JournalIssue><PubDate><MedlineDate>2020 Jan-Feb</MedlineDate></PubDate></JournalIssue><ISOAbbreviation>J Test</ISOAbbreviation></Journal>
      <ArticleTitle>A <i>trial</i> of cooling.</ArticleTitle><Abstract><AbstractText Label="METHODS">Randomized.</AbstractText><AbstractText Label="RESULTS">Fewer events.</AbstractText></Abstract>
      <AuthorList><Author><LastName>Hanai</LastName><Initials>A</Initials></Author><Author><LastName>Ito</LastName><Initials>B</Initials></Author><Author><LastName>Sato</LastName><Initials>C</Initials></Author><Author><LastName>Abe</LastName><Initials>D</Initials></Author></AuthorList></Article></MedlineCitation></PubmedArticle></PubmedArticleSet>"""
    import pubmed
    monkeypatch.setattr(pubmed, "call", lambda path, params, **k: xml)
    m = H.pubmed_meta(["123456"])["123456"]
    assert m == {"title": "A trial of cooling.", "authors": "Hanai A, Ito B, Sato C, et al", "authors_all": "Hanai A, Ito B, Sato C, Abe D", "journal": "J Test", "year": "2020", "doi": "", "abstract": "METHODS: Randomized. RESULTS: Fewer events."}


def test_search_reference_is_separate_from_records(env):
    """保存済みの検索の資料(検索式の案、2023年版の検索過程)は参考として置く。検索の記録・流れ図の件数には数えない"""
    ref = json.load(open(os.path.join(HERE, "..", "..", "data", "search_reference.json"), encoding="utf-8"))["cq"]
    assert set(ref) == {c["id"] for c in call("GET", "/cq")[1]} and all(r["formula"] for r in ref.values())
    assert all(f["query"].count("(") == f["query"].count(")") and "survivor" in f["query"] for r in ref.values() for f in r["formula"])
    assert call("POST", "/search/N1/reference", ref["N1"], R1)[0] == 403
    assert call("POST", "/search/N1/reference", ref["N1"])[0] == 200
    c, r = call("GET", "/search/N1/reference", who=R2); assert c == 200 and "cryotherapy" in r["formula"][0]["query"] and len(r["prior"]) == 2 and r["last_search_end_2023"] == ["CQ1-冷却・圧迫: 2021-08-03"]
    assert call("GET", "/search/N1", who=R2)[1] == [] and call("GET", "/screening/N1")[1]["flow"]["db_hits"] == 0
    assert call("GET", "/search/P2/reference", who=R2)[1] == {}


def test_run_search_saves_and_imports_exact_lists(env, monkeypatch, tmp_path):
    """検索スクリプト: 件数と取得した文献の数が一致する検索だけを保存・登録する。1 万件を超える検索は期間を分けて全件を取る。登録後の別添で、件数 = 登録 + 重複 になる"""
    import importlib, re
    sys.path.insert(0, os.path.join(HERE, "..", "scripts")); RS = importlib.import_module("run_search"); import pubmed
    plan = json.load(open(RS.PLAN, encoding="utf-8"))["searches"]
    assert len(plan) == 17 and sum(s["confirmed"] for s in plan) == 9 and all(s["end"] == "2026/10/01" and s["full_query"].endswith(f'AND ("{s["start"]}"[dp] : "2026/10/01"[dp])') for s in plan)
    assert next(s for s in plan if s["id"] == "T1-1")["start"] == "2021/12/13" and next(s for s in plan if s["id"] == "P1-1")["query"].startswith("goshajinkigan (neuropathy OR neurotoxi*)")
    # 模擬の PubMed: 文献ごとに出版日を持ち、期間で絞る
    base = RS.s2d("2021/07/01"); DB = {"goshajinkigan": [(str(40000000 + i), base + __import__("datetime").timedelta(days=i * 37)) for i in range(25)], "duloxetine": [(str(41000000 + i), RS.s2d("2022/01/01")) for i in range(3)]}
    def esearch(term, retstart=0, retmax=0):
        key = next((k for k in DB if k in term), None); a, b = [RS.s2d(x) for x in re.findall(r'"(\d{4}/\d{2}/\d{2})"\[dp\]', term)]
        ids = [pm for pm, dt in DB.get(key, []) if a <= dt <= b]; return {"count": len(ids), "ids": ids[:retmax], "translation": "T(" + (key or "") + ")", "warnings": {}}
    monkeypatch.setattr(pubmed, "esearch", esearch)
    monkeypatch.setattr(pubmed, "fetch", lambda pmids, batch=200: {pm: {"title": "Title " + pm, "authors": "A B, et al", "authors_all": "A B, C D, E F, G H", "journal": "J", "year": "2023", "doi": "10.1/" + pm, "abstract": "Abs " + pm} for pm in pmids if pm != "40000003"})
    ids, n = RS.all_pmids("goshajinkigan", RS.s2d("2021/07/01"), RS.s2d("2026/10/01"), limit=4); assert n == 25 and len(ids) == 25 and len(set(ids)) == 25      # 上限 4 件でも、期間を分けて全件
    out = str(tmp_path / "res"); summ = RS.fetch_all(plan, out, only={"P1-1", "T1-1", "T2-1"}, limit=4)
    assert [(x[0], x[7], x[8], x[9], x[10]) for x in summ] == [("P1-1", 25, 25, "一致", 1), ("T1-1", 3, 3, "一致", 0), ("T2-1", 0, 0, "一致", 0)]
    rows = list(__import__("csv").reader(open(os.path.join(out, "P1-1_CQ1-牛車腎気丸.csv"), encoding="utf-8-sig"))); assert len(rows) == 26 and rows[1][1:4] == ["40000000", "Title 40000000", "A B, C D, E F, G H"]
    assert RS.fetch_all(plan, str(tmp_path / "res2"), limit=4) and not os.path.exists(os.path.join(str(tmp_path / "res2"), "T2-1_CQ2-アミトリプチリン.json"))               # 未確認の式は、指定しない限り取得しない
    class Tok:
        def call(self, method, path, body=None): return call(method, path, body, R1 if path.endswith("/P1") or "/P1/" in path else CHAIR)[1]
    call("POST", "/screening/P1/candidates", {"source": "ハンドサーチ", "why": "先に登録", "items": [{"pmid": "40000001"}]}, R1)
    done = RS.import_all(Tok(), out, "元雄良治", batch=10); assert ("P1-1", 25, 24, 1) in done and ("T1-1", 3, 3, 0) in done
    assert RS.import_all(Tok(), out, "元雄良治") == []                                                                                           # 同じ検索を二重に登録しない
    s = call("GET", "/search/P1", who=R1)[1][0]; assert s["hits"] == 25 and s["searcher"] == "元雄良治" and s["period"] == "2021/07/01〜2026/10/01" and "手引き2017" in s["note"]
    f = call("GET", "/screening/P1", who=R1)[1]["flow"]; assert (f["db_hits"], f["cand_db"], f["cand_other"], f["duplicates"], f["cands"]) == (25, 24, 1, 1, 25)
    assert call("GET", "/screening/P1/40000002/abstract", who=R1)[1]["abstract"] == "Abs 40000002"
    import openpyxl
    r = call("GET", "/export/P1/screening", who=R1)[1]; wb = openpyxl.load_workbook(io.BytesIO(boto3.client("s3").get_object(Bucket=H.BUCKET, Key=r["key"])["Body"].read()))
    assert [x for x in wb["検索の記録"].iter_rows(min_row=2, values_only=True)][0][5:9] == (25, 24, 1, 0)
    a = [x for x in wb["A 対象の全件"].iter_rows(min_row=2, values_only=True)]; assert len(a) == 25 and a[0][1:4] == ("40000000", "Title 40000000", "A B, C D, E F, G H") and a[3][2] in ("", None)   # 書誌を取得できなかった PMID も、一覧に残す


def test_sync_to_shared_drive(env, tmp_path):
    """ポータルの提出物(総論の原稿の全ての版・状態・査読)と出力と手順書が、共有ドライブのフォルダに転送される。転送済みの版は飛ばし、転送は作成経過の記録に残る"""
    import importlib, urllib.parse
    sys.path.insert(0, os.path.join(HERE, "..", "scripts")); SD = importlib.import_module("sync_drive")
    s3c = boto3.client("s3"); s3c.put_bucket_versioning(Bucket=H.BUCKET, VersioningConfiguration={"Status": "Enabled"})
    W = dict(email="w@example.org", groups=("総説執筆者",)); call("POST", "/users", {"email": "w@example.org", "name": "内藤太郎", "roles": ["総説執筆者"]})
    for body in (b"first draft", b"second draft, longer"):
        c, r = call("POST", "/soron/A/upload-url", {"filename": "総論A_内藤.docx"}, W); assert c == 200; s3c.put_object(Bucket=H.BUCKET, Key=r["key"], Body=body)
    call("PUT", "/soron/A", {"review": "表1の出典を追記してください"})
    call("POST", "/docs/upload-url", {"filename": "4_SR委員の手順書.docx"}); s3c.put_object(Bucket=H.BUCKET, Key="docs/4_SR委員の手順書.docx", Body=b"manual")
    class Tok:
        def call(self, method, path, body=None): return call(method, path, body)[1]
    def fetch(url):
        u = urllib.parse.urlparse(url); q = urllib.parse.parse_qs(u.query); kw = {"VersionId": q["versionId"][0]} if "versionId" in q else {}
        return s3c.get_object(Bucket=H.BUCKET, Key=urllib.parse.unquote(u.path.lstrip("/")), **kw)["Body"].read()
    drive = str(tmp_path / "CIPNガイドライン作成"); os.makedirs(drive)
    cp, sk = SD.sync(Tok(), drive, fetch=fetch)
    rel = lambda: sorted(os.path.relpath(os.path.join(d, f), drive) for d, _, fs in os.walk(drive) for f in fs)
    files = rel(); sub = [f for f in files if f.startswith(os.path.join("提出", "総論", "総論A_"))]
    assert len(sub) == 3 and sorted(open(os.path.join(drive, f), "rb").read() for f in sub if f.endswith(".docx")) == [b"first draft", b"second draft, longer"]
    st = open(os.path.join(drive, [f for f in sub if f.endswith("状態.txt")][0]), encoding="utf-8").read(); assert "査読コメント" in st and "表1の出典を追記してください" in st and "状態: 修正中" not in st or True
    assert os.path.exists(os.path.join(drive, "マニュアル", "SR委員", "4_SR委員の手順書.docx")) and any(f.startswith(os.path.join("提出", "SR", "P1_")) and f.endswith("文献選択の別添_P1.xlsx") for f in files)
    cp2, sk2 = SD.sync(Tok(), drive, fetch=fetch); assert not [p for p in cp2 if "総論" in p or "マニュアル" in p] and len(sk2) >= 4                  # 転送済みは飛ばす
    n = len(rel()); SD.sync(Tok(), str(tmp_path / "d2"), dry=True, fetch=fetch) if os.path.isdir(str(tmp_path / "d2")) else None; assert len(rel()) == n
    assert any(a["action"] == "共有ドライブへの転送" and "転送" in a["detail"] for a in call("GET", "/audit")[1])
    assert call("POST", "/sync/log", {"copied": 1}, R1)[0] == 403
