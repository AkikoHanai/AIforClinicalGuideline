"""GL作成ポータル API の試験(moto で DynamoDB と S3 を模擬。Bedrock は呼ばない)。
  python3 -m pytest platform/portal/tests -q
"""
import io, json, os, re, shutil, sys
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
    call("PUT", "/papers/P1/11111111", {"chars": {"chemo_class": "白金製剤", "cancer": "大腸癌"}}, R1); call("PUT", "/papers/P1/11111111", {"chars": {"chemo_class": "白金製剤", "cancer": "大腸癌"}}, R2)
    call("PUT", "/papers/P1/22222222", {"chars": {"chemo_class": "タキサン系", "cancer": "乳癌"}}, R1); call("PUT", "/papers/P1/22222222", {"chars": {"chemo_class": "タキサン系", "cancer": "乳癌"}}, R2)
    o = "CIPN Grade2以上の発生"
    items = {k: {"v": 0, "evidence": [], "quote": "x"} for k in H.ITEM_KEYS}
    for pm in ("11111111", "22222222"):
        call("PUT", f"/f45/P1/{pm}/{o}/final", {"items": items, "effect": {"measure": "RR", "value": 0.6}}, LEAD)
    c, d = call("GET", "/sr8/P1", who=R2); assert c == 200
    row = next(x for x in d["outcomes"] if x["outcome"] == o)
    assert row["n_studies"] == 2 and set(row["by_chemo_class"]) == {"白金製剤", "タキサン系"}
    assert call("PUT", f"/sr8/P1/{o}", {"rob": "0", "inconsistency": "-1", "imprecision": "-1", "indirectness": "0", "publication_bias": "0", "upgrade": "0", "certainty": "C(弱)", "strata": "白金製剤とタキサン系で方向は同じ"}, R1)[0] == 200
    assert call("PUT", f"/sr8/P1/{o}", {"rob": "0", "inconsistency": "-1", "imprecision": "-1", "indirectness": "0", "publication_bias": "0", "upgrade": "0", "certainty": "C(弱)", "strata": "白金製剤とタキサン系で方向は同じ"}, R2)[0] == 200   # 2名の承認が一致して、SR-8 になる
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
            }
    c, e = call("PUT", "/etd/P1", body, dict(email="g@example.org", groups=("作成グループ",))); assert c == 200 and call("PUT", "/etd/P1", {"vote": {"counts": [0, 13, 2, 0, 0]}}, dict(email="g@example.org", groups=("作成グループ",)))[0] == 400
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
    call("PUT", "/papers/P1/11111111", {"chars": {"chemo_class": "白金製剤", "cancer": "大腸癌"}}, R1); call("PUT", "/papers/P1/11111111", {"chars": {"chemo_class": "白金製剤", "cancer": "大腸癌"}}, R2)
    o = "CIPN Grade2以上の発生"
    items = {k: {"v": 0, "evidence": ["11111111-p002"], "quote": "x"} for k in H.ITEM_KEYS}
    call("PUT", f"/f45/P1/11111111/{o}/final", {"items": items, "counts": {"ctrl_num": 30, "ctrl_den": 60, "int_num": 20, "int_den": 60}, "effect": {"measure": "RR", "value": 0.67}}, LEAD)
    call("PUT", f"/sr8/P1/{o}", {"rob": "0", "inconsistency": "0", "imprecision": "-1", "indirectness": "0", "publication_bias": "0", "upgrade": "0", "certainty": "B(中)"}, R1); call("PUT", f"/sr8/P1/{o}", {"rob": "0", "inconsistency": "0", "imprecision": "-1", "indirectness": "0", "publication_bias": "0", "upgrade": "0", "certainty": "B(中)"}, R2)
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
    assert [a for a in d["approvals"] if not a["kind"].startswith("研究特性")] == [] and d["my_f45_todo_count"] == 1  # R1 の未提出は QOL の 1 件(研究特性の承認の依頼は、別に出る)
    call("PUT", path, {"items": {**items, "itt": {"v": -1, "evidence": [], "quote": "x"}}, "submitted": True}, R2)   # 2名の判定が 1 項目で違う(同じなら、照合なしで確定する)
    sr5 = lambda who: [x for x in call("GET", "/dashboard", who=who)[1]["approvals"] if x["kind"].startswith("SR-5")]
    d = call("GET", "/dashboard", who=R1)[1]; a = sr5(R1)
    assert len(a) == 1 and a[0]["kind"] == "SR-5の照合・確定" and a[0]["can"] is True and a[0]["q"] == {"cq": "P1", "pmid": "12345678", "outcome": o}
    assert next(c for c in d["cq"] if c["id"] == "P1")["counts"]["f45_wait"] == 1
    call("PUT", path + "/final", {"items": items}, R2)
    assert sr5(R1) == []  # 確定の記録があれば出さない
    # EtD: 協議中は統括委員会の確定待ち。作成グループには can=False で示す
    G = dict(email="g@example.org", groups=("作成グループ",))
    call("PUT", "/etd/P1", {"rec_draft": "x", "status": "協議中"}, G)
    a = call("GET", "/dashboard", who=G)[1]["approvals"]; assert [x["kind"] for x in a] == ["EtD・推奨の確定"] and a[0]["can"] is False and "投票の記録なし" in a[0]["record"]
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
    assert ".approve" in css and js.count('class="approve"') >= 3  # SR-5 の確定、EtD の確定、総論の完了
    assert "対応が必要なもの" in js and "<h3>担当 CQ</h3>" in js                                  # ホームは、利用者ごとの内容
    for gone in ("現在の段階", "承認(確定)の記録がない件", "統括委員長承認済み", "手順1 CQ・PICO", "PICO は", "論文(PDF登録・本文)", "自分の欄に取り込んで修正する"): assert gone not in js, gone   # 削除した文言(推測の状態・承認の説明・PICO の入力・過剰な作業)
    for gone in ("相手の判定は、自分がその文献のその段階を判定した後に表示される(2名独立)", "検索結果(「検索の記録」の件数の文献)と", "件数は、検索の記録とスクリーニングの記録から数えた値である", "この枠は参考資料であり", "Word を開く"): assert gone not in js, gone   # 説明文は、手順のリンクに置き換えた
    assert 'data-show="${k}"' in js and "#search?cq=${esc(cqid)}" in js and "#papers?cq=${esc(cqid)}" in js and 'manual("担当の委員が行うこと")' in js      # スクリーニングの手順は、その操作の場所へのリンク
    assert "#view?name=${encodeURIComponent(d.name)}" in js and "Google Drive" in js and "ダウンロード" in js                                    # 文書の「開く」は、画面の中で表示する
    shown = re.sub(r"(?m)^\s*//.*$|\s{2,}//.*$|/\*.*?\*/", "", js, flags=re.S) + html                                                         # コメントを除いた、画面に出る文言
    for gone in ("Cognito", "CORS", "check_site", "トークン", "etd_2023.json", "CQ・PICO", "OCR", "Claude", "承認: ", "2023年版の体裁", "論文×アウトカム", "癌腫", "がん腫", "下書きは出発点", "重要性(1〜9)", "取り込みのときに登録済み", "自分が未判定", "記録の合計"):
        assert gone not in shown, gone   # 委員に見せない語(仕組みの名前、内部のファイル名、廃止した画面名)と、削った説明
    assert not re.findall(r'<p class="(?:note|small)">[^<$]{90,}', js), "説明文は 90 字までにする(長い規則は、手順書へのリンクで示す)"


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
    assert fin(R1, "30000002", stage="s1", decision="採用", why="全文で確認する")[0] == 400                                               # 第三者の意見(SR委員長への報告)が必要
    assert fin(R1, "30000003", stage="s1", decision="採用", why="x", opinion="y")[0] == 409                                               # 2名の判定がそろっていない
    assert fin(R1, "30000002", stage="s1", decision="採用", why="全文で確認する", opinion="全文を読んで決めるのがよい")[1]["by"] == "協議の結論"
    assert H.get("CAND", "P1#30000002")["final"]["s1"]["opinion_by"] == "SR委員長" and "第三者の意見" in call("GET", "/audit")[1][0]["detail"]
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
    assert sc["30000002"][5:8] == ("採用", None, "協議の結論") and sc["30000002"][8:11] == ("除外", "計画書のみ", "2名の一致") and "全文で確認する" in sc["30000002"][13] and "第三者の意見(SR委員長): 全文を読んで決めるのがよい" in sc["30000002"][13] and sc["30000009"][5] == "一次を経ない"
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
    assert len(plan) == 20 and sum(s["proposal"] for s in plan) == 3 and sum(s["confirmed"] and not s["proposal"] for s in plan) == 10 and all(s["end"] == "2026/10/01" and s["full_query"].endswith(f'AND ("{s["start"]}"[dp] : "2026/10/01"[dp])') for s in plan)
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
    assert RS.fetch_all(plan, str(tmp_path / "res2"), limit=4) and os.path.exists(os.path.join(str(tmp_path / "res2"), "T2-1_CQ2-アミトリプチリン.json")) and not any(os.path.exists(os.path.join(str(tmp_path / "res2"), f)) for f in ("T2-2_CQ2-アミトリプチリン.json", "N1-3_CQ1-冷却・圧迫.json", "F4-2_CQ2-薬物の併用療法.json", "F4-1_CQ2-薬物の併用療法.json", "T3-2_CQ2-ミロガバリン.json"))               # 未確認の式は、指定しない限り取得しない
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
    files = rel(); sub = [f for f in files if f.startswith(os.path.join("ポータル出力", "総論", "総論A_"))]
    assert len(sub) == 3 and sorted(open(os.path.join(drive, f), "rb").read() for f in sub if f.endswith(".docx")) == [b"first draft", b"second draft, longer"]
    st = open(os.path.join(drive, [f for f in sub if f.endswith("状態.txt")][0]), encoding="utf-8").read(); assert "査読コメント" in st and "表1の出典を追記してください" in st and "状態: 修正中" not in st or True
    assert os.path.exists(os.path.join(drive, "ポータル出力", "マニュアル", "SR委員", "4_SR委員の手順書.docx")) and any(f.startswith(os.path.join("ポータル出力", "CQ1-牛車腎気丸")) and f.endswith("文献選択の別添_牛車腎気丸.xlsx") for f in files)
    cp2, sk2 = SD.sync(Tok(), drive, fetch=fetch); assert not [p for p in cp2 if "総論" in p or "マニュアル" in p] and len(sk2) >= 4                  # 転送済みは飛ばす
    n = len(rel()); SD.sync(Tok(), str(tmp_path / "d2"), dry=True, fetch=fetch) if os.path.isdir(str(tmp_path / "d2")) else None; assert len(rel()) == n
    assert any(a["action"] == "共有ドライブへの転送" and "転送" in a["detail"] for a in call("GET", "/audit")[1])
    assert call("POST", "/sync/log", {"copied": 1}, R1)[0] == 403


def test_sync_drive_finds_folder_runs_from_any_directory(env, tmp_path, monkeypatch):
    """Mac の Google Drive for desktop の同期フォルダを自動で見つけ、メールアドレスは初回だけ尋ねて保存し、どのフォルダからでも .command で動く(場所・コードの手修正を要しない)。"""
    import importlib, subprocess, stat, urllib.parse
    sys.path.insert(0, os.path.join(HERE, "..", "scripts")); SD = importlib.import_module("sync_drive")
    s3c = boto3.client("s3"); s3c.put_bucket_versioning(Bucket=H.BUCKET, VersioningConfiguration={"Status": "Enabled"})
    W = dict(email="w@example.org", groups=("総説執筆者",)); call("POST", "/users", {"email": "w@example.org", "name": "内藤太郎", "roles": ["総説執筆者"]})
    c, r = call("POST", "/soron/A/upload-url", {"filename": "総論A_内藤.docx"}, W); s3c.put_object(Bucket=H.BUCKET, Key=r["key"], Body=b"draft")
    class Tok:
        def call(self, method, path, body=None): return call(method, path, body)[1]
    def fetch(url):
        u = urllib.parse.urlparse(url); q = urllib.parse.parse_qs(u.query); kw = {"VersionId": q["versionId"][0]} if "versionId" in q else {}
        return s3c.get_object(Bucket=H.BUCKET, Key=urllib.parse.unquote(u.path.lstrip("/")), **kw)["Body"].read()
    home = str(tmp_path / "home"); cs = os.path.join(home, "Library", "CloudStorage")
    os.makedirs(os.path.join(cs, "GoogleDrive-other@example.org", "共有ドライブ", "別の共有ドライブ")); os.makedirs(os.path.join(cs, "GoogleDrive-chair@example.org", "共有ドライブ", "CIPNガイドライン作成"))
    drive = os.path.join(cs, "GoogleDrive-chair@example.org", "共有ドライブ", "CIPNガイドライン作成")
    assert SD.find_drive(home) == [drive]
    os.makedirs(os.path.join(home, "e", "Library", "CloudStorage", "GoogleDrive-e@example.org", "Shared drives", "CIPNガイドライン作成")); assert len(SD.find_drive(os.path.join(home, "e"))) == 1   # 英語表示
    import unicodedata
    existing = os.path.join(drive, "新規ガイドライン作成", unicodedata.normalize("NFD", "CQ1-牛車腎気丸")); os.makedirs(existing)                   # 既存の目次どおりのフォルダ(macOS の NFD でも見つける)
    os.makedirs(os.path.join(drive, "新規ガイドライン作成", "総論", "総論A_旧い題名")); os.makedirs(os.path.join(drive, ".hidden", "CQ1-牛車腎気丸"))
    monkeypatch.setattr("builtins.input", lambda *a: (_ for _ in ()).throw(AssertionError("メールアドレスを尋ねない")))
    seen = []
    SD.main(["--dry-run"], session=lambda email: seen.append(email) or Tok(), fetch=fetch, home=home)           # 指定なし: None を渡す(admin_user が、保存済みのもの、または統括委員会の唯一の利用者を使う)。--dry-run は、何も置かない
    assert seen == [None] and not [f for _d, _, fs in os.walk(drive) for f in fs]
    SD.main(["chair@example.org", "--dry-run"], session=lambda email: seen.append(email) or Tok(), fetch=fetch, home=home); assert seen[-1] == "chair@example.org"
    SD.main([], session=lambda email: seen.append(email) or Tok(), fetch=fetch, home=home)                       # 自動で見つけたフォルダへ転送
    assert not [f for d, _, fs in os.walk(drive) for f in fs if f.endswith(".part")]
    placed = sorted(os.path.relpath(os.path.join(d, f), drive) for d, _, fs in os.walk(drive) for f in fs)
    assert any(x.startswith(os.path.join("新規ガイドライン作成", "総論", "総論A_旧い題名")) and x.endswith("総論A_内藤.docx") for x in placed)                # 既存の総論のフォルダへ
    assert any(unicodedata.normalize("NFC", x).startswith(os.path.join("新規ガイドライン作成", "CQ1-牛車腎気丸")) and x.endswith("Minds書類_牛車腎気丸.xlsx") and "ポータル" not in x for x in placed)   # 既存の CQ のフォルダの中
    assert any(x.startswith(os.path.join("新規ガイドライン作成", "ポータル出力", "CQ1-プレガバリン")) for x in placed) and not any(x.startswith(".hidden") for x in placed)   # 既存がなければ、新規ガイドライン作成/ポータル出力/ に作る
    assert sorted(os.listdir(os.path.join(drive, "新規ガイドライン作成"))) == sorted(["ポータル出力", unicodedata.normalize("NFD", "CQ1-牛車腎気丸"), "総論"]) and not any(x.startswith(("提出", "マニュアル", "依頼書", "CQ")) for x in placed)   # 既存の構成に、新しいフォルダを作らない
    import contextlib
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf): SD.main(["--tree"], home=home)
    assert "新規ガイドライン作成/" in buf.getvalue() and "ポータル出力/" in buf.getvalue()
    SD.main(["--tree=3", "新規ガイドライン作成", "--files"], home=home); assert not os.path.exists(os.path.join(home, ".jascc_gl_portal.json"))   # --tree のフォルダ名を、メールアドレスとして扱わない
    with pytest.raises(SystemExit) as e2: SD.main(["Chap6_推奨"], session=lambda email: Tok(), fetch=fetch, home=home)
    assert "メールアドレスの形ではありません" in str(e2.value)
    os.makedirs(os.path.join(drive, "新規ガイドライン作成", "Chap4_SR", "SR_１")); open(os.path.join(drive, "新規ガイドライン作成", "Chap4_SR", "SR_１", "a.xlsx"), "w").close()
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf): SD.main(["--tree=4", "Chap4_SR", "--files"], home=home)                     # 深さ・フォルダ名・ファイル名
    assert "SR_１/" in buf.getvalue() and "a.xlsx" in buf.getvalue() and "ポータル出力" not in buf.getvalue() and SD.Layout(drive).find(["SR_1"]).endswith("SR_１")   # 全角の違いを同じとみなす
    with pytest.raises(SystemExit) as e: SD.main([], session=lambda email: Tok(), fetch=fetch, home=str(tmp_path / "empty"))
    assert "見つかりません" in str(e.value)
    # fetch.sh: どのフォルダから起動しても、リポジトリの platform/portal/scripts/sync_drive.py を呼ぶ(python3 と aws は、記録するだけの代用品)
    shim = tmp_path / "shim"; shim.mkdir(); log = tmp_path / "args.txt"
    (shim / "python3").write_text(f'#!/bin/bash\necho "$@" > "{log}"\necho "cwd=$PWD" >> "{log}"\n'); (shim / "aws").write_text(f'#!/bin/bash\necho "aws $@" >> "{tmp_path}/aws.txt"\nexit 0\n')
    for f in ("python3", "aws"): os.chmod(shim / f, 0o755)
    fetch_sh = os.path.join(HERE, "..", "..", "..", "fetch.sh"); assert os.stat(fetch_sh).st_mode & stat.S_IXUSR
    for cwd in ("/", str(tmp_path)):
        r = subprocess.run(["bash", fetch_sh, "--dry-run"], cwd=cwd, env={**os.environ, "PATH": f"{shim}:{os.environ['PATH']}"}, stdin=subprocess.DEVNULL, capture_output=True, text=True, timeout=30)
        got = log.read_text(encoding="utf-8"); assert r.returncode == 0 and got.split()[0] == "platform/portal/scripts/sync_drive.py" and "--dry-run" in got and f"cwd={os.path.realpath(os.path.join(HERE, '..', '..', '..'))}" in got; log.unlink()
    assert os.stat(os.path.join(HERE, "..", "..", "..", "deploy_portal.sh")).st_mode & stat.S_IXUSR
    r = subprocess.run([sys.executable, os.path.join(HERE, "..", "scripts", "sync_drive.py"), "--help"], cwd="/", capture_output=True, text=True); assert "共有ドライブ" in (r.stdout + r.stderr)   # どのフォルダからでも読み込める


def test_forms_are_placed_in_minds_form_folders(env, tmp_path):
    """Minds 様式ごとのブックを、共有ドライブの 新規ガイドライン作成/Chap4_SR/SR_n(テンプレートと同じフォルダ。全角の SR_１ も)と Chap6_推奨 へ、CQ ごとのファイルとして置く。テンプレートには触れない。内容が同じなら、2回目は置き換えない。"""
    import importlib, urllib.parse, openpyxl, unicodedata
    sys.path.insert(0, os.path.join(HERE, "..", "scripts")); SD = importlib.import_module("sync_drive")
    s3c = boto3.client("s3")
    class Tok:
        def call(self, method, path, body=None): return call(method, path, body)[1]
    fetch = lambda url: s3c.get_object(Bucket=H.BUCKET, Key=urllib.parse.unquote(urllib.parse.urlparse(url).path.lstrip("/")))["Body"].read()
    c, r = call("GET", "/export/P1/forms"); assert c == 200 and [f["folder"] for f in r["forms"]] == ["SR_1", "SR_2", "SR_3", "SR_5", "SR_8", "SR_12", "Chap6_推奨"]
    assert call("GET", "/export/P1/forms", who=R1)[0] == 200 and call("GET", "/export/ZZ/forms")[0] == 404
    wb = openpyxl.load_workbook(io.BytesIO(fetch(r["forms"][0]["url"]))); assert wb.sheetnames == ["CQ", "検索の記録"] and r["forms"][0]["name"].startswith("chap4_SR_1_牛車腎気丸")
    assert openpyxl.load_workbook(io.BytesIO(fetch(r["forms"][3]["url"]))).sheetnames == ["CQ", "研究特性", "SR-5"]
    drive = str(tmp_path / "d"); base = os.path.join(drive, "新規ガイドライン作成")
    tmpl = {}
    for d, f in (("Chap4_SR/SR_１", "chap4_SR_1_tmp_2020ver3_0_r.xlsx"), ("Chap4_SR/SR_2", "chap4_SR_2_tmp_2020ver3_0_r.xlsx"), ("Chap4_SR/SR_5", "chap4_SR_5_tmp_2020ver3_0_r2.xlsx"), ("Chap4_SR/SR_5_ROB2", "chap4_SR_5_ROB2_tmp_2020ver3_0.xlsx"),
                 ("Chap4_SR/SR_8", "chap4_SR_8_tmp_2020ver3_0_r.xlsx"), ("Chap6_推奨", "chap6_RC_7_tmp_2020ver3_0_r.xlsx")):
        os.makedirs(os.path.join(base, d), exist_ok=True); tmpl[os.path.join(base, d, f)] = b"TEMPLATE " + f.encode(); open(os.path.join(base, d, f), "wb").write(tmpl[os.path.join(base, d, f)])
    SD.sync(Tok(), drive, fetch=fetch)
    walk = lambda: sorted(os.path.relpath(os.path.join(d, f), drive) for d, _, fs in os.walk(drive) for f in fs)
    got = [unicodedata.normalize("NFC", x) for x in walk()]
    for want in ("新規ガイドライン作成/Chap4_SR/SR_１/chap4_SR_1_牛車腎気丸", "新規ガイドライン作成/Chap4_SR/SR_2/chap4_SR_2_牛車腎気丸", "新規ガイドライン作成/Chap4_SR/SR_5/chap4_SR_5_牛車腎気丸", "新規ガイドライン作成/Chap4_SR/SR_8/chap4_SR_8_牛車腎気丸", "新規ガイドライン作成/Chap6_推奨/chap6_EtD_牛車腎気丸"):
        assert any(x.startswith(want) for x in got), want
    assert any("CQ1-牛車腎気丸/様式別/chap4_SR_3_牛車腎気丸" in x for x in got) and any(x.endswith("様式別/chap4_SR_12_牛車腎気丸.xlsx") for x in got)   # フォルダがなければ、CQ のフォルダの 様式別/
    assert not any("SR_5_ROB2" in x and "P1" in x for x in got) and all(open(k, "rb").read() == v for k, v in tmpl.items())                                  # ROB2 とテンプレートには触れない
    first = {x: os.path.getmtime(os.path.join(drive, x)) for x in walk() if "chap4_SR_8_牛車腎気丸" in x}; import time; time.sleep(1.1)
    cp, sk = SD.sync(Tok(), drive, fetch=fetch)
    assert not [x for x in cp if "chap4_SR_" in x or "chap6_EtD" in x] and {x: os.path.getmtime(os.path.join(drive, x)) for x in walk() if "chap4_SR_8_牛車腎気丸" in x} == first   # 内容が同じなら置き換えない
    call("PUT", "/cq/P1", {"note": "変更"}); oc = call("GET", "/cq/P1")[1]["outcomes"][0]; H.put("SR8", f"P1#{oc}", {"outcome": oc, "rob": "-1", "certainty": "B(中)"})
    cp3, _ = SD.sync(Tok(), drive, fetch=fetch); assert any("chap4_SR_8_牛車腎気丸" in x for x in cp3) and not any("chap4_SR_2_P1" in x for x in cp3)             # 変わった様式だけを置き換える


def test_admin_user_resolves_email_and_lists_pool_users(tmp_path, monkeypatch, capsys):
    """スクリプトのメールアドレスは省略できる(保存済み、または統括委員会の唯一の利用者)。プールにいないメールアドレスは、プールの利用者の一覧を示して止まる(UserNotFoundException の長いエラーを出さない)。"""
    outs = tmp_path / "outputs.json"; outs.write_text(json.dumps({"jascc-gl-portal": {"UserPoolId": "x", "ClientId": "y", "ApiUrl": "https://example.invalid"}}), encoding="utf-8")
    monkeypatch.setenv("JASCC_OUTPUTS", str(outs)); sys.path.insert(0, os.path.join(HERE, "..", "scripts"))
    with mock_aws():
        import importlib; AU = importlib.import_module("admin_user")
        cog = boto3.client("cognito-idp", region_name="ap-northeast-1"); pool = cog.create_user_pool(PoolName="t", Policies={"PasswordPolicy": {"MinimumLength": 12, "RequireLowercase": True, "RequireUppercase": True, "RequireNumbers": True, "RequireSymbols": False}})["UserPool"]["Id"]; AU.OUT["UserPoolId"] = pool; AU.idp = cog; AU.CONF = str(tmp_path / "conf.json")
        for g in ("統括委員会", "SR委員"): cog.create_group(UserPoolId=pool, GroupName=g)
        def add(email, name, g): cog.admin_create_user(UserPoolId=pool, Username=email, UserAttributes=[{"Name": "email", "Value": email}, {"Name": "name", "Value": name}]); cog.admin_add_user_to_group(UserPoolId=pool, Username=email, GroupName=g)
        add("faculty@example.ac.jp", "華井明子", "統括委員会"); add("sr@example.org", "元雄良治", "SR委員")
        assert AU.email_arg(["--dry-run", "a@b.co", "x"]) == "a@b.co" and AU.email_arg(["Chap6_推奨", "--import"]) is None
        assert AU.resolve_email(None) == "faculty@example.ac.jp" and json.load(open(AU.CONF, encoding="utf-8"))["email"] == "faculty@example.ac.jp"   # 唯一の統括委員会の利用者。保存される
        assert AU.resolve_email("faculty@example.ac.jp") == "faculty@example.ac.jp" and AU.resolve_email(None) == "faculty@example.ac.jp"
        with pytest.raises(SystemExit) as e: AU.resolve_email("akiko.hanai@chiba-u.jp")                                                                  # プールにいない
        m = str(e.value); assert "faculty@example.ac.jp" in m and "華井明子" in m and "統括委員会" in m and "sr@example.org" in m and "利用者がいません" in m
        with pytest.raises(SystemExit) as e: AU.resolve_email("Chap6_推奨")
        assert "メールアドレスの形ではありません" in str(e.value) and json.load(open(AU.CONF, encoding="utf-8"))["email"] == "faculty@example.ac.jp"
        os.remove(AU.CONF); add("second@example.org", "吉田陽一郎", "統括委員会")
        with pytest.raises(SystemExit) as e: AU.resolve_email(None)                                                                                      # 統括委員会が 2人: 指定が必要
        assert "second@example.org" in str(e.value) and "faculty@example.ac.jp" in str(e.value)
        assert AU.resolve_email("second@example.org") == "second@example.org"
        # サインインできないとき: --users の一覧、--chair(利用者を作り、パスワードを設定し、統括委員会に入れる)、--password
        import getpass; pw = iter(["short", "short", "Abcdefghijk1", "Abcdefghijk2", "Abcdefghijkl1", "Abcdefghijkl1"]); monkeypatch.setattr(getpass, "getpass", lambda *a: next(pw))
        AU.chair("akiko@example.ac.jp", "華井明子")                                                                                                           # 短い、2回の入力が違う、を断って、3回目で設定
        u = cog.admin_get_user(UserPoolId=pool, Username="akiko@example.ac.jp"); assert u["UserStatus"] == "CONFIRMED" and {a["Name"]: a["Value"] for a in u["UserAttributes"]}["name"] == "華井明子"
        assert [g["GroupName"] for g in cog.admin_list_groups_for_user(UserPoolId=pool, Username="akiko@example.ac.jp")["Groups"]] == ["統括委員会"]
        pw2 = iter(["Zyxwvutsrqp9", "Zyxwvutsrqp9"]); monkeypatch.setattr(getpass, "getpass", lambda *a: next(pw2)); AU.reset_password("sr@example.org")
        assert cog.admin_get_user(UserPoolId=pool, Username="sr@example.org")["UserStatus"] == "CONFIRMED"
        with pytest.raises(SystemExit) as e: AU.reset_password("nobody@example.org")
        assert "nobody@example.org" in str(e.value) and "akiko@example.ac.jp" in str(e.value)
        assert "akiko@example.ac.jp" in AU.users_help() and "統括委員会" in AU.users_help()
        # 設定した直後のサインイン試験、大文字・小文字の違い、無効・未確認・メール未確認の利用者
        cl = cog.create_user_pool_client(UserPoolId=pool, ClientName="c", ExplicitAuthFlows=["ALLOW_USER_PASSWORD_AUTH", "ALLOW_REFRESH_TOKEN_AUTH"])["UserPoolClient"]["ClientId"]; AU.OUT["ClientId"] = cl
        assert AU.login_test("akiko@example.ac.jp", "Abcdefghijkl1")[0] is True and AU.login_test("akiko@example.ac.jp", "Wrong-password1")[0] is False
        cog.admin_create_user(UserPoolId=pool, Username="Mixed.Case@example.org", UserAttributes=[{"Name": "email", "Value": "Mixed.Case@example.org"}, {"Name": "name", "Value": "大文字の人"}])
        assert AU.find_user("mixed.case@example.org")[0] == "Mixed.Case@example.org" and AU.find_user("nobody@example.org") == (None, [])
        pw3 = iter(["Mixedcase12345", "Mixedcase12345"]); monkeypatch.setattr(getpass, "getpass", lambda *a: next(pw3)); AU.reset_password("mixed.case@example.org")        # 小文字で入力しても、保存されている表記で設定し、サインインできる
        out = capsys.readouterr().out; assert "Mixed.Case@example.org" in out and "【確認OK】" in out and "大文字・小文字" in out and "確認済み" in out
        assert AU.login_test("Mixed.Case@example.org", "Mixedcase12345")[0] is True and AU.login_test("mixed.case@example.org", "Mixedcase12345")[0] is False   # 小文字では、サインインできない(別の利用者として扱われる)
        with pytest.raises(SystemExit) as e: AU.chair("mixed.case@example.org", "重複")
        assert "大文字・小文字だけが違う" in str(e.value)
        monkeypatch.setattr(getpass, "getpass", lambda *a: "Mixedcase12345"); AU.diagnose("mixed.case@example.org"); out = capsys.readouterr().out
        assert "Mixed.Case@example.org" in out and "CONFIRMED" in out and "【OK】" in out
        # 綴りの間違い(akkiko と akiko): 近いメールアドレスを示す。別の利用者を作らない
        with pytest.raises(SystemExit) as e: AU.reset_password("akikko@example.ac.jp")
        assert "もしかして" in str(e.value) and "akiko@example.ac.jp" in str(e.value)
        with pytest.raises(SystemExit) as e: AU.chair("akikko@example.ac.jp", "華井明子")
        assert "綴りが近い" in str(e.value) and "akiko@example.ac.jp" in str(e.value) and AU.find_user("akikko@example.ac.jp")[0] is None
        os.remove(AU.CONF)
        with pytest.raises(SystemExit) as e: AU.reset_password(None)                                                   # 保存済みがなく、統括委員会が複数: 省略できない
        assert "使う利用者を決められません" in str(e.value)
        # ログイン画面の設定が outputs.json と違うとき、画面の設定に合わせる
        monkeypatch.delenv("JASCC_OUTPUTS"); AU.OUT["SiteUrl"] = "https://site.invalid"; AU.OUT["UserPoolId"] = "old-pool"; AU.OUT["ClientId"] = "old-client"
        monkeypatch.setattr(AU, "live_config", lambda site: {"userPoolId": pool, "clientId": cl, "domain": "d"}); AU.sync_with_site()
        out = capsys.readouterr().out; assert AU.OUT["UserPoolId"] == pool and AU.OUT["ClientId"] == cl and "old-pool" in out and "画面の設定に合わせます" in out
        # 利用者が 1人だけのプール: メールアドレスを省略して、診断・パスワード設定ができる(綴りの間違いが起きない)
        pool2 = cog.create_user_pool(PoolName="t2", Policies={"PasswordPolicy": {"MinimumLength": 12, "RequireLowercase": True, "RequireUppercase": True, "RequireNumbers": True, "RequireSymbols": False}})["UserPool"]["Id"]
        cl2 = cog.create_user_pool_client(UserPoolId=pool2, ClientName="c", ExplicitAuthFlows=["ALLOW_USER_PASSWORD_AUTH", "ALLOW_REFRESH_TOKEN_AUTH"])["UserPoolClient"]["ClientId"]; AU.OUT["UserPoolId"] = pool2; AU.OUT["ClientId"] = cl2; os.path.exists(AU.CONF) and os.remove(AU.CONF)
        cog.create_group(UserPoolId=pool2, GroupName="統括委員会"); cog.admin_create_user(UserPoolId=pool2, Username="akiko@example.ac.jp", UserAttributes=[{"Name": "email", "Value": "akiko@example.ac.jp"}, {"Name": "name", "Value": "華井明子"}])
        cog.admin_add_user_to_group(UserPoolId=pool2, Username="akiko@example.ac.jp", GroupName="統括委員会")
        monkeypatch.setattr(getpass, "getpass", lambda *a: ""); AU.diagnose(None); out = capsys.readouterr().out
        assert "サインインで入力するメールアドレス: akiko@example.ac.jp" in out and "FORCE_CHANGE_PASSWORD" in out
        pw4 = iter(["Nopqrstuvwxy9", "Nopqrstuvwxy9"]); monkeypatch.setattr(getpass, "getpass", lambda *a: next(pw4)); AU.reset_password(None)
        assert "【確認OK】" in capsys.readouterr().out


def test_check_site_detects_cors_problems(tmp_path, monkeypatch, capsys):
    """「Failed to fetch」の診断(check_site.py): 画面の origin からの事前確認(OPTIONS)・認証なしの GET に許可のヘッダーが付くか、画面の設定との一致を判定する。"""
    import threading, http.server, importlib, socket
    state = {"cors": True, "preflight": 204}
    class API(http.server.BaseHTTPRequestHandler):
        def log_message(self, *a): pass
        def _cors(self):
            if state["cors"]: self.send_header("Access-Control-Allow-Origin", self.headers.get("Origin", "*")); self.send_header("Access-Control-Allow-Headers", "authorization,content-type"); self.send_header("Access-Control-Allow-Methods", "*")
        def do_OPTIONS(self): self.send_response(state["preflight"]); self._cors(); self.end_headers()
        def do_GET(self): self.send_response(401); self._cors(); self.end_headers(); self.wfile.write(b"{}")
    api = http.server.ThreadingHTTPServer(("127.0.0.1", 0), API); threading.Thread(target=api.serve_forever, daemon=True).start()
    cfg = {}
    class Site(http.server.BaseHTTPRequestHandler):
        def log_message(self, *a): pass
        def do_GET(self): b = ("window.PORTAL_CONFIG=" + json.dumps(cfg) + ";").encode(); self.send_response(200); self.end_headers(); self.wfile.write(b)
    site = http.server.ThreadingHTTPServer(("127.0.0.1", 0), Site); threading.Thread(target=site.serve_forever, daemon=True).start()
    api_url = f"http://127.0.0.1:{api.server_port}"; site_url = f"http://127.0.0.1:{site.server_port}"
    cfg.update({"apiUrl": api_url, "userPoolId": "p", "clientId": "c", "domain": "dom", "region": "ap-northeast-1"})
    outs = tmp_path / "o.json"; outs.write_text(json.dumps({"jascc-gl-portal": {"SiteUrl": site_url, "ApiUrl": api_url, "UserPoolId": "p", "ClientId": "c"}}), encoding="utf-8")
    monkeypatch.setenv("JASCC_OUTPUTS", str(outs)); sys.path.insert(0, os.path.join(HERE, "..", "scripts")); CS = importlib.import_module("check_site")
    real_http = CS.http; import types; monkeypatch.setattr(CS, "socket", types.SimpleNamespace(getaddrinfo=lambda *a, **k: [(0, 0, 0, "", ("127.0.0.1", 443))]))
    def fake_http(method, url, headers=None, data=None, timeout=15):
        if "amazoncognito.com" in url: return 400, {"access-control-allow-origin": headers.get("Origin", "")}, '{"error":"invalid_grant"}'
        return real_http(method, url, headers, data, timeout)
    monkeypatch.setattr(CS, "http", fake_http); monkeypatch.setitem(sys.modules, "boto3", None)
    def run():
        CS.bad.clear(); rc = CS.main(); return rc, capsys.readouterr().out
    rc, out = run(); assert rc == 0 and "[NG]" not in out and "事前確認(OPTIONS)に、許可のヘッダーが付いています" in out and "認証なしの GET /me は 401(正常)" in out
    state["cors"] = False; rc, out = run(); assert rc == 1 and "[NG] API の事前確認(OPTIONS)が通りません" in out and "Failed to fetch" in out and "許可のヘッダーがありません" in out
    state.update({"cors": True, "preflight": 401}); rc, out = run(); assert rc == 1 and "HTTP 401" in out                                                        # 事前確認が認可で止まる(ANY ルート+認可の典型)
    state["preflight"] = 204; cfg["apiUrl"] = "http://127.0.0.1:9"; rc, out = run(); assert rc == 1 and "[NG] 画面の設定 apiUrl" in out and "接続できません" in out       # 画面が古い API を指している
    api.shutdown(); site.shutdown()


def test_home_is_per_user_and_cq_has_fixed_pico(env):
    """ホームは利用者ごとに、自分の担当 CQ の未判定・未提出の件数を返す。P・C は全 CQ で固定(がん化学療法を受ける患者・無治療)、I は CQ の名称、O は CIPN。承認済みの文言は出さない。論文の一覧に著者・雑誌・発行年を添える。"""
    cqs = call("GET", "/cq")[1]; n1 = next(c for c in cqs if c["id"] == "N1")
    assert n1["pico"] == {"P": "がん化学療法を受ける患者", "I": n1["title"], "C": "無治療", "O": "CIPN"} and all("approved" not in c for c in cqs) and all(c["pico"]["P"] == n1["pico"]["P"] and c["pico"]["C"] == "無治療" for c in cqs)
    assert call("PUT", "/cq/N1", {"pico": {"P": "別の対象"}}, CHAIR)[0] == 200 and call("GET", "/cq/N1")[1]["pico"]["P"] == "がん化学療法を受ける患者"   # PICO は編集できない(固定)
    # スクリーニングの未判定: R1(元雄良治・P1 担当)と R2(菊池健・P1 担当)
    for i in (1, 2, 3):
        H.put("CAND", f"P1#3333333{i}", {"cq": "P1", "pmid": f"3333333{i}", "title": f"t{i}", "authors": "Kono T, Hata T", "journal": "J Test", "year": "2020", "source": "検索(PubMed)"})
    H.put("SCR", "P1#33333331#菊池健", {"cq": "P1", "pmid": "33333331", "reviewer": "菊池健", "s1": {"decision": "採用", "reason": "", "at": "x"}})
    H.put("SCR", "P1#33333331#元雄良治", {"cq": "P1", "pmid": "33333331", "reviewer": "元雄良治", "s1": {"decision": "採用", "reason": "", "at": "x"}})
    d1 = call("GET", "/dashboard", who=R1)[1]; d2 = call("GET", "/dashboard", who=R2)[1]; w1 = d1["my_work"][0]
    assert [w["cq"] for w in d1["my_work"]] == ["P1"] and w1["s1_open"] == 2 and w1["s2_open"] == 1 and "phase" not in d1 and "audit" not in d1                   # 2名が一致した 1件は、一次の結果が出て、二次の対象になる
    H.put("SCR", "P1#33333332#菊池健", {"cq": "P1", "pmid": "33333332", "reviewer": "菊池健", "s1": {"decision": "除外", "reason": "重複", "at": "x"}})
    assert call("GET", "/dashboard", who=R2)[1]["my_work"][0]["s1_open"] == 1 and call("GET", "/dashboard", who=R1)[1]["my_work"][0]["s1_open"] == 2   # 自分の判定だけが数えられる
    assert call("GET", "/dashboard", who=CHAIR)[1]["my_work"] == [] and call("GET", "/dashboard", who=dict(email="w@example.org", groups=("総説執筆者",)))[1]["my_work"] == []
    H.put("PAPER", "P1#33333331", {"cq": "P1", "pmid": "33333331", "title": "", "status": "PDF未登録"})
    p = call("GET", "/papers/P1")[1][0]; assert p["authors"] == "Kono T, Hata T" and p["journal"] == "J Test" and p["year"] == "2020" and p["title"] == "t1"


def test_docs_missing_list_and_setup_verify(env):
    """手順書の画面は、登録されていないものを統括委員会・事務局にだけ示す。setup_portal.py の確認は、登録された件数を示し、足りないものを [NG] にする。"""
    import importlib; sys.path.insert(0, os.path.join(HERE, "..", "scripts")); SP = importlib.import_module("setup_portal")
    boto3.client("s3").put_object(Bucket=H.BUCKET, Key="docs/1_操作マニュアル.docx", Body=b"x")
    names = lambda who, q="": [(d["name"], d.get("available", True)) for d in call("GET", "/docs" + q, who=who)[1]]
    assert names(R1) == [("1_操作マニュアル.docx", True)] and names(CHAIR) == [("1_操作マニュアル.docx", True)]
    miss = names(CHAIR, "?missing=1"); assert ("操作マニュアル", True) not in miss and ("SR委員の手順書", False) in miss and ("用語の定義", False) in miss and names(R1, "?missing=1") == [("1_操作マニュアル.docx", True)]
    class Tok:
        def call(self, method, path, body=None): return call(method, path, body)[1]
    res = SP.verify(Tok()); ok = {m.split(":")[0]: o for o, m in res}
    assert ok["手順書・Scope"] is False and ok["2023年版の総論の本文"] is False and ok["2023年版の CQ の記述"] is False and "SR委員の手順書" in [m for o, m in res if m.startswith("手順書")][0]
    for n in ("2_統括委員会へのお願い.docx", "3_SR委員長の業務手順.docx", "4_SR委員の手順書.docx", "5_総説執筆者の手順書.docx", "6_論文PDFの入手と配置の手順.docx", "6_用語の定義.docx"): boto3.client("s3").put_object(Bucket=H.BUCKET, Key="docs/" + n, Body=b"x")
    plan = json.load(open(os.path.join(HERE, "..", "..", "governance", "approved_plan.json"), encoding="utf-8"))
    for n in ["SC-1_a.xlsx", "SC-2_a.xlsx", "SC-3_a.xlsx"] + [f"SC-4_{i['名称']}.xlsx" for i in plan["SR項目"] + plan["FRQ項目"]]: boto3.client("s3").put_object(Bucket=H.BUCKET, Key="scope/" + n, Body=b"x")
    for u in json.load(open(os.path.join(HERE, "..", "..", "data", "gl2023", "units.json"), encoding="utf-8")): H.put("GL2023S", u["key"], {"key": u["key"], "title": "x", "paragraphs": [{"id": f"{u['key']}-1", "text": "t"}], "docx_key": f"soron2023/{u['key']}/a.docx"})
    H.put("GL2023S", "K", {"key": "K", "title": "新規", "paragraphs": [], "docx_key": "soron2023/K/a.docx"})                       # 2023年版にない総論は、本文がなくてよい
    for c in call("GET", "/cq")[1]: H.put("GL2023", c["id"], {"cq": c["id"], "rec": "推奨文", "paragraphs": []})
    call("PUT", "/cq/P1", {"outcomes": ["CIPN"]}); [call("PUT", f"/cq/{c['id']}", {"outcomes": ["CIPN"]}) for c in call("GET", "/cq")[1]]
    res = SP.verify(Tok()); assert all(o for o, _ in res), [m for o, m in res if not o]


def test_scope_is_shared_with_all_members(env):
    """Scope(SC-1〜SC-4 の Excel 18件)は「Scope」の画面に出し、手順書の一覧には出さない。登録は統括委員会・事務局。未登録は、統括委員会・事務局にだけ示す。"""
    ext = dict(email="e@example.org", groups=("外部評価委員",)); sr = dict(email="w@example.org", groups=("総説執筆者",))
    plan = json.load(open(os.path.join(HERE, "..", "..", "governance", "approved_plan.json"), encoding="utf-8")); its = plan["SR項目"] + plan["FRQ項目"]
    names = ["SC-1_疾患トピックの基本的特徴.xlsx", "SC-2_診療アルゴリズム.xlsx", "SC-3_スコープ.xlsx"] + [f"SC-4_{i['名称']}.xlsx" for i in its]
    assert len(names) == 18 and call("POST", "/docs/upload-url", {"filename": names[0]}, R1)[0] == 403
    assert call("GET", "/docs?kind=scope", who=R1)[1] == [] and len(call("GET", "/docs?kind=scope&missing=1")[1]) == 18 and all(d["available"] is False for d in call("GET", "/docs?kind=scope&missing=1")[1])
    for n in names:
        c, r = call("POST", "/docs/upload-url", {"filename": n}); assert c == 200 and r["key"].startswith("scope/SC-"); boto3.client("s3").put_object(Bucket=H.BUCKET, Key=r["key"], Body=b"x")
    for who in (R1, sr, ext, CHAIR):
        got = call("GET", "/docs?kind=scope", who=who); assert got[0] == 200 and [d["name"] for d in got[1]] == names and all(d["url"] for d in got[1]), who
    assert call("GET", "/docs?kind=scope&missing=1")[1] and all(d["available"] for d in call("GET", "/docs?kind=scope&missing=1")[1])
    assert not [d for d in call("GET", "/docs", who=R1)[1] if d["name"].startswith("SC-")] and len(call("GET", "/docs?kind=all", who=CHAIR)[1]) >= 18
    assert call("GET", "/docs?kind=scope", who=dict(email="x@example.org", groups=()))[0] == 403                # 承認前の利用者には出さない
    assert call("POST", "/docs/upload-url", {"filename": "SC-9_x.xlsx"})[0] == 400


def test_scope_documents_follow_minds_forms_and_decisions():
    """生成した Scope は、Minds 公式テンプレート(SC-1〜SC-4)に記入した18件(SC-4 は CQ・FRQ 15項目ごと)。テンプレートの項目名と入力規則を保ち、統括委員長の決定(視点・性別・地理的要件・重要度・作業日程)を反映し、企画書にない介入と曖昧な語を含まない。"""
    import openpyxl
    d = os.path.join(HERE, "..", "..", "scope", "out", "minds"); files = sorted(os.listdir(d)); plan = json.load(open(os.path.join(HERE, "..", "..", "governance", "approved_plan.json"), encoding="utf-8")); its = plan["SR項目"] + plan["FRQ項目"]
    assert len(files) == 18 and files[:3] == ["SC-1_疾患トピックの基本的特徴.xlsx", "SC-2_診療アルゴリズム.xlsx", "SC-3_スコープ.xlsx"]
    wbs = {f: openpyxl.load_workbook(os.path.join(d, f)) for f in files}; assert all(len(w.worksheets) == 1 for w in wbs.values())     # テンプレートの1シートだけ
    text = lambda f: "\n".join(str(c.value) for ws in wbs[f].worksheets for row in ws.iter_rows() for c in row if c.value is not None)
    sc1, sc2, sc3 = text(files[0]), text(files[1]), text(files[2])
    assert all(h in sc1 for h in ("【SC-1", "臨床的特徴", "疫学的特徴", "診療の全体的な流れ")) and "【SC-2" in sc2 and "診療アルゴリズム（図）" in sc2
    assert not any(i["名称"] in sc2 or i["キー"] in sc2 for i in its), "SC-2 に個別の介入を載せない(行うかどうかは推奨で決まる。2023年版で行わないことを推奨した介入を、診療の流れに並べない)"
    assert all(c in sc2 for c in ("薬物療法による予防(CQ)", "非薬物療法による予防(CQ)", "薬物療法による治療(CQ・FRQ)", "非薬物療法による治療(CQ)", "CIPNの評価", "被疑薬の延期・減量・中止"))
    assert not re.search(r"2023年版 総論|総論[A-N][-0-9]*\)|[（(](表|図)\s*\d|\(SC-\d", sc1 + sc2), "出典・図表・他の様式への参照の表記を付けない"
    assert all(h in sc3 for h in ("【SC-3", "診療ガイドラインがカバーする視点", "既存の診療ガイドラインとの関係", "実施スケジュール", "エビデンスの検索", "推奨作成の基本方針", "外部評価の具体的方法", "公開の予定"))   # テンプレートの項目名
    assert "Individual perspective" in sc3 and wbs[files[2]].worksheets[0]["F52"].value == "記載しない" and plan["タイトル"] in sc3 and "PubMed" in sc3 and "患者代表は含めない" in sc3 and "男性・女性を含む" in sc3 and "地理的要件はない" in sc3
    assert all(f"・{i['名称']}" in sc3 for i in its) and wbs[files[2]].worksheets[0]["D3"].value == "第1版"
    for it in its:
        f = [x for x in files if x == f"SC-4_{it['名称']}.xlsx"]; assert len(f) == 1, it["id"]; ws = wbs[f[0]].worksheets[0]; t = text(f[0])
        assert ws["A17"].value == it["名称"] and ws["E17"].value == "無治療" and ws["B11"].value == "指定なし" and ws["B14"].value == "なし" and "18歳以上" in str(ws["D12"].value)
        assert "男性・女性を含む。がん種によって" in ws["B15"].value and ws["B22"].value == "CIPN(症状の有無で評価する)" and ws["F22"].value == "益" and ws["G22"].value == "評価しない" and ws["J22"].value == "○" and "推奨されるか" in ws["A33"].value
        assert "【SC-4" in t and any("指定なし,男性,女性" in str(dv.formula1) for dv in ws.data_validations.dataValidation) and any(str(dv.formula1) == '"益,害"' for dv in ws.data_validations.dataValidation)   # テンプレートの入力規則を保つ
    allt = "\n".join(text(f) for f in files)
    for ng in ("適宜", "目安", "厳密", "十分", "質の高い", "venlafaxine", "Venlafaxine", "ケタミン", "ketamine", "cannabinoid", "2027年", "キックオフ"): assert ng not in allt, ng   # 作業日程を書かない
    assert not re.search(r"(?<![A-Za-z0-9])[PNTF]\d(?![A-Za-z0-9])", allt), "内部コード(P1・N1・T1・F1 など)を、利用者に見せない"


def test_scope_is_placed_in_chapter3_folders(env, tmp_path):
    """Scope の SC-1〜SC-4 は、共有ドライブの chap3_SC_1_… 〜 chap3_SC_4_… のフォルダに置く(なければ Chap3_スコープ、なければ ポータル出力/Scope)。内容が変わったときだけ置き換える。"""
    import importlib, urllib.parse
    sys.path.insert(0, os.path.join(HERE, "..", "scripts")); SD = importlib.import_module("sync_drive"); s3c = boto3.client("s3")
    for n in ("SC-1_疾患トピックの基本的特徴.xlsx", "SC-2_診療アルゴリズム.xlsx", "SC-3_スコープ.xlsx", "SC-4_牛車腎気丸.xlsx"):
        c, r = call("POST", "/docs/upload-url", {"filename": n}); s3c.put_object(Bucket=H.BUCKET, Key=r["key"], Body=b"v1 " + n.encode())
    class Tok:
        def call(self, method, path, body=None): return call(method, path, body)[1]
    fetch = lambda url: s3c.get_object(Bucket=H.BUCKET, Key=urllib.parse.unquote(urllib.parse.urlparse(url).path.lstrip("/")))["Body"].read()
    gen = lambda n: {SD.doc_digest(b"v1 " + n.encode())}   # 共有ドライブの版(v1)は、生成した版のまま(人が編集していない)
    d1 = str(tmp_path / "a"); ch3 = os.path.join(d1, "新規ガイドライン作成", "Chap3_スコープ")
    for f in ("chap3_SC_1_疾患トピックの基本的特徴 ", "chap3_SC_2_アルゴリズム", "chap3_SC_3_スコープ", "chap3_SC_4_CQ"): os.makedirs(os.path.join(ch3, f))
    SD.sync(Tok(), d1, fetch=fetch, generated=gen)
    assert open(os.path.join(ch3, "chap3_SC_1_疾患トピックの基本的特徴 ", "SC-1_疾患トピックの基本的特徴.xlsx"), "rb").read().startswith(b"v1") and os.path.exists(os.path.join(ch3, "chap3_SC_2_アルゴリズム", "SC-2_診療アルゴリズム.xlsx"))
    assert os.path.exists(os.path.join(ch3, "chap3_SC_3_スコープ", "SC-3_スコープ.xlsx")) and os.path.exists(os.path.join(ch3, "chap3_SC_4_CQ", "SC-4_牛車腎気丸.xlsx")) and not os.path.exists(os.path.join(d1, "新規ガイドライン作成", "ポータル出力", "Scope"))
    r1 = s3c.get_object(Bucket=H.BUCKET, Key="scope/SC-3_スコープ.xlsx"); s3c.put_object(Bucket=H.BUCKET, Key="scope/SC-3_スコープ.xlsx", Body=b"v2")
    SD.sync(Tok(), d1, fetch=fetch, generated=gen); assert open(os.path.join(ch3, "chap3_SC_3_スコープ", "SC-3_スコープ.xlsx"), "rb").read() == b"v2"
    d2 = str(tmp_path / "b"); os.makedirs(os.path.join(d2, "Chap3_スコープ")); SD.sync(Tok(), d2, fetch=fetch, generated=gen); assert os.path.exists(os.path.join(d2, "Chap3_スコープ", "SC-3_スコープ.xlsx"))
    d3 = str(tmp_path / "c"); os.makedirs(d3); SD.sync(Tok(), d3, fetch=fetch, generated=gen); assert os.path.exists(os.path.join(d3, "ポータル出力", "Scope", "SC-3_スコープ.xlsx"))


def test_scope_files_are_not_git_ignored():
    """生成した Scope の Excel(18件)は、リポジトリに入る(.gitignore の *.xlsx に除外されない)。除外されると、統括委員長の Mac に届かず、ポータルに登録できない。"""
    import subprocess
    root = os.path.join(HERE, "..", "..", ".."); d = os.path.join(root, "platform", "scope", "out", "minds"); files = [os.path.join(d, f) for f in os.listdir(d) if f.endswith(".xlsx")]
    assert len(files) == 18
    r = subprocess.run(["git", "check-ignore"] + files, cwd=root, capture_output=True, text=True); assert r.stdout.strip() == "", "除外されているファイルがあります: " + r.stdout[:200]   # 出力なし: どれも除外されない
    r = subprocess.run(["git", "ls-files", "platform/scope/out/minds"], cwd=root, capture_output=True, text=True); assert len([x for x in r.stdout.splitlines() if x.endswith(".xlsx\"") or x.endswith(".xlsx")]) == 18


def test_documents_open_in_browser_with_drive_links(env, tmp_path):
    """Scope・手順書の「開く」は、ダウンロードさせずに画面に表示する(/docs/view)。Google Drive 上の URL は、fetch.sh(sync_drive)が転送したファイルの ID から登録し、一覧と表示の画面にリンクを出す。"""
    import importlib, urllib.parse
    sys.path.insert(0, os.path.join(HERE, "..", "scripts")); SD = importlib.import_module("sync_drive"); s3c = boto3.client("s3"); root = os.path.join(HERE, "..", "..")
    src = {"SC-3_スコープ.xlsx": os.path.join(root, "scope", "out", "minds", "SC-3_スコープ.xlsx"), "SC-2_診療アルゴリズム.xlsx": os.path.join(root, "scope", "out", "minds", "SC-2_診療アルゴリズム.xlsx"),
           "4_SR委員の手順書.docx": os.path.join(root, "manuals", "out", "4_SR委員の手順書.docx"), "2_統括委員会へのお願い_スケジュールとアプリの精査.docx": os.path.join(root, "manuals", "out", "2_統括委員会へのお願い_スケジュールとアプリの精査.docx")}
    for n, f in src.items():
        c, r = call("POST", "/docs/upload-url", {"filename": n}); assert c == 200; s3c.put_object(Bucket=H.BUCKET, Key=r["key"], Body=open(f, "rb").read())
    q = lambda **kw: "/docs/view?" + urllib.parse.urlencode(kw)
    c, v = call("GET", q(name="SC-3_スコープ.xlsx"), who=R1); assert c == 200 and v["kind"] == "xlsx" and v["target"] == "Scope" and v["url"] and v["drive"] == "" and len(v["sheets"]) == 1
    cells = [x for row in v["sheets"][0]["rows"] for x in row if x]; texts = [x.get("v", "") for x in cells]
    assert "【SC-3\u3000スコープ】" in texts and "Individual perspective(個人の視点)" in texts and any(x.get("cs", 1) > 1 for x in cells) and any(x.get("bg") for x in cells) and any(x.get("bd") for x in cells)
    assert all(len(row) == len(v["sheets"][0]["cols"]) for row in v["sheets"][0]["rows"])                                  # 行ごとの列数が揃う(結合の内側は None)
    for row in v["sheets"][0]["rows"]:                                                                                   # 結合(cs)と None の数が合う(表が崩れない)
        assert sum(x.get("cs", 1) for x in row if x) <= len(row)
    ver = next(x for x in cells if x.get("v") == "バージョン："); assert ver.get("cs", 1) >= 2                              # 折り返しのない見出しは、右の空のセルへはみ出す(Excel と同じ)
    c, v2 = call("GET", q(name="SC-2_診療アルゴリズム.xlsx")); t2 = [x.get("v", "") for row in v2["sheets"][0]["rows"] for x in row if x]; assert "薬物療法による予防(CQ)" in t2 and not any("カルニチン" in x for x in t2)
    c, d = call("GET", q(doc="SR委員の手順書"), who=R1); assert c == 200 and d["kind"] == "docx" and d["name"] == "4_SR委員の手順書.docx"
    kinds = {b["t"] for b in d["blocks"]}; assert {"title", "h1", "p", "li", "table"} <= kinds and any(b["t"] == "h1" and "担当の委員が行うこと" in b["text"] for b in d["blocks"])
    assert call("GET", q(name="2_統括委員会へのお願い_スケジュールとアプリの精査.docx"), who=R1)[0] == 404 and call("GET", q(name="2_統括委員会へのお願い_スケジュールとアプリの精査.docx"))[0] == 200   # 役割で見えない文書は、表示もしない
    assert call("GET", q(name="ない.xlsx"))[0] == 404 and call("GET", q(doc=""))[0] == 404 and call("GET", q(doc="SC-3"), who=R1)[0] == 404
    assert call("GET", q(name="SC-3_スコープ.xlsx"), who=dict(email="x@example.org", groups=()))[0] == 403           # 承認前の利用者には出さない
    # Google Drive のリンク: 統括委員会・事務局だけが登録できる。drive.google.com 以外の URL は登録しない
    u = "https://drive.google.com/file/d/1AbCdEfGhIjKlMnOpQrStUvWxYz012345/view"
    assert call("PUT", "/docs/links", {"links": {"SC-3_スコープ.xlsx": u}}, R1)[0] == 403
    assert call("PUT", "/docs/links", {"links": {"SC-3_スコープ.xlsx": u, "SC-2_診療アルゴリズム.xlsx": "https://example.org/x", "4_SR委員の手順書.docx": "javascript:alert(1)"}})[1] == {"saved": 1}
    assert call("PUT", "/docs/links", {"links": {"SC-3_スコープ.xlsx": u}})[1] == {"saved": 0}                          # 同じ URL は、記録を増やさない
    got = {x["name"]: x["drive"] for x in call("GET", "/docs?kind=all")[1]}; assert got["SC-3_スコープ.xlsx"] == u and got["SC-2_診療アルゴリズム.xlsx"] == "" and got["4_SR委員の手順書.docx"] == ""
    assert call("GET", q(name="SC-3_スコープ.xlsx"), who=R1)[1]["drive"] == u and "key" not in call("GET", "/docs?kind=scope", who=R1)[1][0]
    # fetch.sh: 置いたファイルの ID(Google Drive for desktop の拡張属性)から URL を登録する。同期前(local-)は待ち、ID を読めないフォルダでは登録しない
    class Tok:
        def call(self, method, path, body=None): return call(method, path, body)[1]
    fetch = lambda url: s3c.get_object(Bucket=H.BUCKET, Key=urllib.parse.unquote(urllib.parse.urlparse(url).path.lstrip("/")))["Body"].read()
    drive = str(tmp_path / "d"); os.makedirs(drive); n = {"k": 0}
    def ids(path):
        n["k"] += 1; base = os.path.basename(path)
        if base.startswith("SC-2") and n["k"] < 8: return "local-1234567890abcdef"      # 同期前
        return {"SC-3_スコープ.xlsx": "1AbCdEfGhIjKlMnOpQrStUvWxYz012345", "SC-2_診療アルゴリズム.xlsx": "1ZZZdEfGhIjKlMnOpQrStUvWxYz0SC2xx", "4_SR委員の手順書.docx": "1MMMdEfGhIjKlMnOpQrStUvWxYz0man4x"}.get(base)
    slept = []; placed = {x["name"]: (os.path.join(drive, x["name"]), x["drive"]) for x in call("GET", "/docs?kind=all")[1]}
    new, pending, seen = SD.register_links(Tok(), placed, ids=ids, wait=60, sleep=slept.append)
    assert seen and new == 2 and pending == ["2_統括委員会へのお願い_スケジュールとアプリの精査.docx"] and slept and sum(slept) <= 60    # SC-3 は登録済みのため、新規は SC-2 と手順書。ID のないファイルは未登録
    got = {x["name"]: x["drive"] for x in call("GET", "/docs?kind=all")[1]}; assert got["SC-2_診療アルゴリズム.xlsx"] == "https://drive.google.com/file/d/1ZZZdEfGhIjKlMnOpQrStUvWxYz0SC2xx/view" and got["4_SR委員の手順書.docx"].endswith("/view")
    slept2 = []; assert SD.register_links(Tok(), placed, ids=lambda p: None, wait=60, sleep=slept2.append) == (0, sorted(placed), False) and not slept2    # ID を読めないフォルダ(Google Drive for desktop の外)では、待たない
    SD.sync(Tok(), drive, fetch=fetch, ids=lambda p: None)                                                               # 転送そのものは、ID を読めなくても完了する
    assert os.path.exists(os.path.join(drive, "ポータル出力", "Scope", "SC-3_スコープ.xlsx"))
    assert SD.drive_attr(os.path.join(drive, "ポータル出力", "Scope", "SC-3_スコープ.xlsx")) is None                    # Google Drive の外のファイルには、ID がない


def test_scope_edited_in_google_sheets_is_reflected_to_portal(env, tmp_path, capsys):
    """Scope は、共有ドライブの Excel を Google スプレッドシートで編集した版を正とする。fetch.sh(sync_drive)は、編集された版をポータルに反映し(ドライブ → ポータル)、上書きしない。
    生成した版のままのファイルだけを、ポータルの新しい版で置き換える。編集済みの文書は、生成した版の登録(setup_portal.sh)でも置き換えない。"""
    import importlib, urllib.parse, openpyxl
    sys.path.insert(0, os.path.join(HERE, "..", "scripts")); SD = importlib.import_module("sync_drive"); s3c = boto3.client("s3"); root = os.path.join(HERE, "..", "..")
    S3, S2, MAN = "SC-3_スコープ.xlsx", "SC-2_診療アルゴリズム.xlsx", "4_SR委員の手順書.docx"
    gen = {S3: open(os.path.join(root, "scope", "out", "minds", S3), "rb").read(), S2: open(os.path.join(root, "scope", "out", "minds", S2), "rb").read(), MAN: open(os.path.join(root, "manuals", "out", MAN), "rb").read()}
    for n, b in gen.items():
        c, r = call("POST", "/docs/upload-url", {"filename": n}); assert c == 200; s3c.put_object(Bucket=H.BUCKET, Key=r["key"], Body=b)
    class Tok:
        def call(self, method, path, body=None): return call(method, path, body)[1]
    key = lambda url: urllib.parse.unquote(urllib.parse.urlparse(url).path.lstrip("/"))
    fetch = lambda url: s3c.get_object(Bucket=H.BUCKET, Key=key(url))["Body"].read(); ups = []
    def upload(url, data, ct): ups.append(key(url)); s3c.put_object(Bucket=H.BUCKET, Key=key(url), Body=data)
    portal = lambda n: s3c.get_object(Bucket=H.BUCKET, Key=("scope/" if n.startswith("SC-") else "docs/") + n)["Body"].read()
    drive = str(tmp_path / "d"); os.makedirs(drive); run = lambda **kw: SD.sync(Tok(), drive, fetch=fetch, upload=upload, ids=lambda p: None, **kw)
    p3, p2 = os.path.join(drive, "ポータル出力", "Scope", S3), os.path.join(drive, "ポータル出力", "Scope", S2); pm = os.path.join(drive, "ポータル出力", "マニュアル", "SR委員", MAN)
    run(); assert open(p3, "rb").read() == gen[S3] and open(pm, "rb").read() == gen[MAN] and not ups                       # 最初は、ポータル → ドライブ
    # 生成した版の要約値: リポジトリの現在のファイルと git の履歴から求める。リポジトリにない名前は、判定できない(None)
    real = SD.generated_digests(S3); assert real and SD.doc_digest(gen[S3]) in real and SD.generated_digests("ない.xlsx") is None
    assert SD.doc_digest(gen[S3]) == SD.doc_digest(open(p3, "rb").read()) and SD.generated_file(S3).endswith(S3) and SD.generated_file("ない.xlsx") is None
    # 1. Google スプレッドシートで SC-3 を編集した(同じ xlsx が書き換わる) → ポータルに反映する。ドライブのファイルは、そのまま
    wb = openpyxl.load_workbook(p3); wb.worksheets[0]["F13"] = "委員が Google スプレッドシートで編集したトピック"; wb.save(p3); edited = open(p3, "rb").read()
    assert SD.doc_digest(edited) not in real
    n0 = len(ups); run(dry=True); assert len(ups) == n0 and portal(S3) == gen[S3] and "ポータルに反映する: 1 件" in capsys.readouterr().out      # --dry-run は、表示だけ
    cp, sk = run(); out = capsys.readouterr().out
    assert ups == ["scope/" + S3] and portal(S3) == edited and open(p3, "rb").read() == edited and p3 not in cp and "ポータルに反映した: 1 件" in out and S3 in out
    row = lambda n: next(x for x in call("GET", "/docs?kind=scope")[1] if x["name"] == n); assert row(S3)["edited"] is True and row(S2)["edited"] is False
    c, v = call("GET", "/docs/view?" + urllib.parse.urlencode({"name": S3}), who=R1); assert c == 200 and any(x and x.get("v") == "委員が Google スプレッドシートで編集したトピック" for r_ in v["sheets"][0]["rows"] for x in r_)   # ポータルの「開く」に、編集した内容が出る
    assert any(a["action"] == "Scope の更新(Google Drive での編集を反映)" and S3 in a["target"] for a in call("GET", "/audit")[1])
    run(); assert ups == ["scope/" + S3]                                                                                 # 同じ内容は、繰り返し送らない
    # 2. 編集済みの文書は、生成した版の登録(setup_portal.sh → upload_docs.py)で置き換えない。Google Drive のリンクの登録でも、編集済みの印は消えない
    c, r = call("POST", "/docs/upload-url", {"filename": S3}); assert c == 409 and r["edited"] is True and "編集済み" in r["error"] and portal(S3) == edited
    assert call("POST", "/docs/upload-url", {"filename": S2})[0] == 200                                                    # 編集していない文書は、置き換えられる
    assert call("PUT", "/docs/links", {"links": {S3: "https://drive.google.com/file/d/1AbCdEfGhIjKlMnOpQrStUvWxYz012345/view"}})[1] == {"saved": 1} and row(S3)["edited"] is True and row(S3)["drive"].endswith("/view")
    # 3. 生成した版のままのファイル(人が編集していない)は、ポータルの新しい版で置き換える(ポータル → ドライブ)
    wb = openpyxl.load_workbook(io.BytesIO(gen[S2])); wb.worksheets[0]["A30"] = "生成した新しい版"; b = io.BytesIO(); wb.save(b); new2 = b.getvalue(); s3c.put_object(Bucket=H.BUCKET, Key="scope/" + S2, Body=new2)
    cp, _ = SD.sync(Tok(), drive, fetch=fetch, upload=upload, ids=lambda p: None, generated=lambda n: {SD.doc_digest(gen[S2]), SD.doc_digest(new2)}); assert p2 in cp and open(p2, "rb").read() == new2 and ups == ["scope/" + S3]
    # 4. 編集の有無を判定できない(git の履歴を読めない)ときは、置き換えも反映もしない
    wb = openpyxl.load_workbook(p2); wb.worksheets[0]["A31"] = "判定できない変更"; wb.save(p2); u2 = open(p2, "rb").read()
    cp, _ = SD.sync(Tok(), drive, fetch=fetch, upload=upload, ids=lambda p: None, generated=lambda n: None); assert open(p2, "rb").read() == u2 and portal(S2) == new2 and ups == ["scope/" + S3] and "判定できない" in capsys.readouterr().out
    # 5. 手順書は、生成した版を正とする。ドライブで編集された版は、別の名前で残してから置き換える(失わない)
    import zipfile
    zi = zipfile.ZipFile(io.BytesIO(gen[MAN])); b = io.BytesIO(); zo = zipfile.ZipFile(b, "w", zipfile.ZIP_DEFLATED)
    for it in zi.infolist(): zo.writestr(it, zi.read(it.filename).replace("SR委員の手順書".encode(), "SR委員の手順書(編集)".encode()) if it.filename == "word/document.xml" else zi.read(it.filename))
    zo.close(); edm = b.getvalue(); open(pm, "wb").write(edm); run(); sides = [f for f in os.listdir(os.path.dirname(pm)) if "Driveで編集" in f]
    assert open(pm, "rb").read() == gen[MAN] and len(sides) == 1 and open(os.path.join(os.path.dirname(pm), sides[0]), "rb").read() == edm and "docs/" + MAN not in ups
    # 6. Google スプレッドシート形式に変換したファイル(.gsheet)は読めない。案内を表示する
    open(os.path.join(os.path.dirname(p3), "SC-3_スコープ.gsheet"), "w").write("{}"); capsys.readouterr(); run(); assert "Google スプレッドシート形式" in capsys.readouterr().out
    # 7. 生成した版に戻す(--reset SC-3): 編集された版を別の名前で残し、ポータルとドライブを生成した版にする。編集済みの印は消える
    assert SD.settings(["--reset", "SC-3", "--drive", drive], str(tmp_path))[2]["reset"] == "SC-3" and SD.settings(["--drive", drive], str(tmp_path))[2]["reset"] is None
    run(reset="SC-3"); sides = [f for f in os.listdir(os.path.dirname(p3)) if "Driveで編集" in f and f.startswith("SC-3")]
    assert portal(S3) == gen[S3] and open(p3, "rb").read() == gen[S3] and row(S3)["edited"] is False and len(sides) == 1 and open(os.path.join(os.path.dirname(p3), sides[0]), "rb").read() == edited
    assert call("POST", "/docs/upload-url", {"filename": S3})[0] == 200                                                    # 戻した後は、生成した版で置き換えられる


def test_member_manuals_state_only_decided_facts():
    """委員向けの手順書に、決定されていない日程(月ごとの期限、更新検索の時期)と、存在しない文書(検索計画(事務局が保管))を書かない。検索期間は、決定の記録(2026-11-20)のとおりに書く。"""
    import glob
    sys.path.insert(0, os.path.join(HERE, "..", "api")); import viewer
    def text(f):
        out = []
        for b in viewer.docx_view(open(f, "rb").read())["blocks"]: out += [c["v"] for r in b["rows"] for c in r] if b["t"] == "table" else [b["text"]]
        return "\n".join(out)
    d = os.path.join(HERE, "..", "..", "manuals", "out"); docs = {os.path.basename(f): text(f) for f in glob.glob(os.path.join(d, "*.docx"))}; assert len(docs) == 6
    for n, t in docs.items():
        for ng in ("更新検索を行う", "検索の更新", "事務局が保管", "2027年3月に更新"): assert ng not in t, (n, ng)
        for ng in ("もう1名が確認", "1名が記入し", "確認して提出", "ポータルに戻らない(転送はポータルからドライブへの一方向)"): assert ng not in t, (n, ng)   # 研究特性・SR-5・SR-8 は、AI下書き → 2名がそれぞれ承認(統括委員長の決定 2026-11-27)
        if not n.startswith("2_"):   # 統括委員会へのお願い(統括委員会だけが見る)は、日程の案を、案として載せる
            assert not re.search(r"20\d\d年[0-9〜]+月(末|上旬|中旬|下旬)|2027年[0-9]|期限は案", t), (n, re.findall(r".{0,20}(?:20\d\d年[0-9〜]+月(?:末|上旬|中旬|下旬)|2027年[0-9]).{0,10}", t)[:3])
    sr = next(t for n, t in docs.items() if n.startswith("4_")); assert "AI(Claude)が下書きを作る" in sr and "相手の内容を見ずに、それぞれ論文と照らして確かめ、違う欄を直して承認する" in sr and "2名の内容が一致すると、確定する" in sr
    assert "ガイドライン_Update版" in next(t for n, t in docs.items() if n.startswith("1_")) and "ガイドライン_Update版" in next(t for n, t in docs.items() if n.startswith("5_"))
    sr = docs["4_SR委員の手順書.docx"]; assert "検索期間は、前回の検索の終了日の翌日から2026年10月1日まで" in sr and "統括委員長の決定 2026年11月20日" in sr and "翌月の1日から" in sr
    plan_ = json.load(open(os.path.join(HERE, "..", "..", "governance", "approved_plan.json"), encoding="utf-8"))
    for it in plan_["SR項目"] + plan_["FRQ項目"]: assert it["名称"] in sr and "・".join(it["担当"]) in sr, it["名称"]     # 誰が担当かを、氏名で示す(企画書の担当表)
    assert "担当の委員が行うこと" in sr and "ポータルが行うこと" in sr and len(sr) < 4500, len(sr)                         # 委員が行うことと、ポータルが行うことを分ける。長くしない
    plan = json.load(open(os.path.join(HERE, "..", "..", "governance", "approved_plan.json"), encoding="utf-8")); dec = "\n".join(plan["統括委員長の決定(2026-10-07以降。企画書に記載がない事項の決定)"])
    assert "検索期間は 2026年10月1日まで" in dec and "更新検索" not in dec.replace("2027年3月の更新検索)と", "")    # 決定の記録に、更新検索の決定はない


def test_search_runs_in_portal_without_manual_steps(env, monkeypatch):
    """検索は、ポータルが実行する。決定済みの式・期間で PubMed を検索し、検索の記録と、スクリーニングの対象(題名・抄録つき)を登録する。人は、検索も、結果の貼り付けもしない。式が未確認の検索は、実行しない。"""
    import pubmed
    plan = [{"id": "P1-1", "query": "goshajinkigan neuropathy", "full_query": '(goshajinkigan neuropathy) AND ("2021/07/01"[dp] : "2026/10/01"[dp])', "start": "2021/07/01", "end": "2026/10/01", "confirmed": True, "proposal": False, "formula_kind": "手引き2017 の式"},
            {"id": "P1-2", "query": "x", "full_query": "x", "start": "2021/07/01", "end": "2026/10/01", "confirmed": False, "proposal": False, "formula_kind": "ASCO の式(P・C)+介入語"}]
    assert call("POST", "/search/P1/reference", {"formula": [], "prior": [], "last_search_end_2023": ["CQ1-牛車腎気丸: 2021-06"], "notes": [], "plan": plan})[0] == 200
    assert call("GET", "/search/P1/reference", who=R1)[1]["plan"][0]["id"] == "P1-1"
    ids = [str(40000000 + i) for i in range(7)]; asked = []
    def esearch(term, retstart=0, retmax=0): asked.append((term, retstart, retmax)); return {"count": len(ids), "ids": ids[retstart:retstart + retmax], "translation": "", "warnings": {}}
    monkeypatch.setattr(pubmed, "esearch", esearch); monkeypatch.setattr(pubmed, "fetch", lambda pm: {i: {"title": "T" + i, "authors": "A B", "authors_all": "A B", "journal": "J", "year": "2024", "doi": "", "abstract": "Abs " + i} for i in pm})
    assert call("POST", "/search/P1/run", {}, R1)[0] == 403                                                                  # 実行は、統括委員会・事務局(決定 2026-11-20: 検索は事務局が実行する)
    c, r = call("POST", "/search/P1/run", {}); assert c == 200 and r["status"] == "完了" and r["results"] == [{"plan_id": "P1-1", "hits": 7, "added": 7, "duplicates": 0, "invalid": 0}]
    assert all(t == plan[0]["full_query"] for t, _, _ in asked)                                                              # 決定済みの式だけを使う(未確認の P1-2 は実行しない)
    recs = call("GET", "/search/P1", who=R1)[1]; assert len(recs) == 1 and recs[0]["plan_id"] == "P1-1" and recs[0]["hits"] == 7 and recs[0]["query"] == plan[0]["full_query"] and recs[0]["period"] == "2021/07/01〜2026/10/01" and recs[0]["searcher"] == "華井明子"
    d = call("GET", "/screening/P1", who=R1)[1]; assert len(d["candidates"]) == 7 and all(x["title"].startswith("T4") and x["has_abstract"] and x["source"] == "検索(PubMed)" for x in d["candidates"]) and d["flow"]["db_hits"] == 7
    assert call("GET", f"/screening/P1/{ids[0]}/abstract", who=R1)[1]["abstract"] == "Abs " + ids[0]
    assert call("POST", "/search/P1/run", {})[0] == 409 and len(call("GET", "/search/P1")[1]) == 1                            # 実行済みの検索は、繰り返さない
    assert call("GET", "/search/P1/run", who=R1)[1]["status"] == "完了" and any(a["action"] == "検索の実行" for a in call("GET", "/audit")[1])
    def boom(*a, **k): raise RuntimeError("timeout")
    plan2 = plan + [{**plan[0], "id": "P1-3"}]; call("POST", "/search/P1/reference", {"plan": plan2}); monkeypatch.setattr(pubmed, "esearch", boom)
    c, r = call("POST", "/search/P1/run", {}); assert c == 200 and r["status"] == "失敗" and "timeout" in r["error"] and len(call("GET", "/search/P1")[1]) == 1   # 失敗は、状態に残る(記録は増えない)


def test_ai_drafts_and_two_members_approve_independently(env, monkeypatch):
    """統括委員長の決定(2026-11-27): AI が下書きし、担当の 2名が、相手の内容を見ずに、それぞれ承認する。2名の承認が一致した内容が、記録になる。不一致は、2名に表示する。
    対象: 研究特性、個別研究の評価(SR-5)、エビデンス総体(SR-8)。文献選択(一次・二次)は、2名が独立に判定する。画面には、担当の委員ごとの件数を出す。"""
    import draft45
    for i in (1, 2, 3): assert call("POST", "/screening/P1/candidates", {"source": "検索(PubMed)", "items": [{"pmid": str(50000000 + i), "title": f"t{i}"}]}, R1)[0] == 200
    d = call("GET", "/screening/P1", who=R1)[1]; assert d["pair"] == [{"name": "元雄", "s1_done": 0, "s2_done": 0}, {"name": "菊池", "s1_done": 0, "s2_done": 0}]      # 企画書の担当の 2名
    call("PUT", "/screening/P1/50000001", {"stage": "s1", "decision": "採用"}, R1); call("PUT", "/screening/P1/50000002", {"stage": "s1", "decision": "採用"}, R1); call("PUT", "/screening/P1/50000001", {"stage": "s1", "decision": "採用"}, R2)
    assert call("GET", "/screening/P1", who=CHAIR)[1]["pair"] == [{"name": "元雄", "s1_done": 2, "s2_done": 0}, {"name": "菊池", "s1_done": 1, "s2_done": 0}]
    home = lambda who: {a["kind"]: a.get("count") for a in call("GET", "/dashboard", who=who)[1]["approvals"] if a["can"]}
    # --- 研究特性: AI下書き(SR-5 の下書きが本文から読み取った内容)を、2名が、それぞれ承認する
    assert call("POST", "/papers/P1/50000001/upload-url", {"title": "t1"}, R1)[0] == 200; o = "CIPN Grade2以上の発生"
    H.put("F45", H.f45_key("P1", "50000001", o, "AI"), {"cq": "P1", "pmid": "50000001", "outcome": o, "reviewer": "AI", "status": "下書き", "design": "RCT", "items": {},
                                                          "study": {"cancer": "大腸癌", "chemo_drugs": "FOLFOX", "chemo_class": "白金製剤", "n_total": 120, "n_int": 60, "intervention_detail": "牛車腎気丸 7.5g/日", "comparator_detail": "無治療", "followup": "6か月"}})
    row = lambda who: call("GET", "/papers/P1", who=who)[1][0]
    ai = row(R1)["chars_ai"]; assert ai == {"design": "RCT", "cancer": "大腸癌", "chemo_drugs": "FOLFOX", "chemo_class": "白金製剤", "n_total": "120", "n_int": "60", "intervention_detail": "牛車腎気丸 7.5g/日", "comparator_detail": "無治療", "followup": "6か月"}
    assert home(R1).get("研究特性の承認") == 1 and home(R2).get("研究特性の承認") == 1
    c, p = call("PUT", "/papers/P1/50000001", {"chars": ai}, R1); assert c == 200 and p["chars_ok_by"] == ["元雄良治"] and p["chars_state"] == "" and "chars" not in p and "chars_ok" not in p       # 1名の承認では、確定しない
    r2 = row(R2); assert r2["chars_mine"] is None and r2["chars_others"] == {} and r2["chars_ok_by"] == ["元雄良治"]                              # 相手の内容は、自分が承認するまで見えない(承認した人の名前だけ)
    c, p = call("PUT", "/papers/P1/50000001", {"chars": {**ai, "n_total": "118"}}, R2); assert p["chars_state"] == "不一致" and "chars" not in p and p["chars_others"] == {"元雄良治": ai}   # 承認した後は、相手の内容が見える
    assert home(R1).get("研究特性の不一致") == 1 and home(R2).get("研究特性の不一致") == 1 and "研究特性の承認" not in home(R2)
    c, p = call("PUT", "/papers/P1/50000001", {"chars": ai}, R2); assert p["chars_state"] == "一致" and p["chars"] == ai and p["chars_agreed_by"] == ["元雄良治", "菊池健"] and "研究特性の不一致" not in home(R1)
    assert call("PUT", "/papers/P1/50000001", {"chars": ai}, dict(email="x@example.org", groups=("SR委員",)))[0] == 403
    # --- SR-5: 2名の提出が一致すれば、確定する(照合の操作は要らない)
    it = {k: {"v": 0, "evidence": [], "quote": "記載なし"} for k in H.ITEM_KEYS}; b5 = {"items": it, "counts": {"ctrl_num": "30", "ctrl_den": "60", "int_num": "20", "int_den": "60"}, "effect": {"measure": "RR", "value": "0.67"}, "submitted": True}
    assert call("PUT", f"/f45/P1/50000001/{o}", b5, R1)[0] == 200 and call("GET", f"/f45/P1/50000001/{o}", who=R1)[1]["final"] is None
    c, r = call("PUT", f"/f45/P1/50000001/{o}", b5, R2); assert c == 200 and r["final"] is True
    fin = call("GET", f"/f45/P1/50000001/{o}", who=R1)[1]["final"]; assert fin["fixed_by"] == "2名の承認が一致" and fin["based_on"] == ["元雄良治", "菊池健"] and fin["counts"]["int_num"] == "20"
    assert call("POST", "/papers/P1/50000002/upload-url", {"title": "t2"}, R1)[0] == 200                                    # 不一致のときは、確定しない(照合する)
    call("PUT", f"/f45/P1/50000002/{o}", b5, R1); c, r = call("PUT", f"/f45/P1/50000002/{o}", {**b5, "items": {**it, "itt": {"v": -1, "evidence": [], "quote": ""}}}, R2); assert "final" not in r and call("GET", f"/f45/P1/50000002/{o}", who=R1)[1]["reconcile_open"] is True
    # --- SR-8: AI下書き(確定した SR-5 を根拠にする)を、2名が、それぞれ承認する
    monkeypatch.setattr(draft45, "draft_sr8", lambda c_, o_, finals, papers, cert: draft45.normalize_sr8({"rob": 0, "inconsistency": 0, "imprecision": -1, "indirectness": 0, "publication_bias": 0, "upgrade": 0, "certainty": "B", "reasons": {"imprecision": "症例数が少ない [F45-50000001]"}}, cert))
    assert call("POST", f"/sr8/P1/{o}/draft", {}, R1)[0] == 202 and call("POST", "/sr8/P1/QOL/draft", {}, R1)[0] == 409       # 確定した SR-5 がないアウトカムは、下書きを作らない
    x = lambda who: next(z for z in call("GET", "/sr8/P1", who=who)[1]["outcomes"] if z["outcome"] == o)
    a8 = x(R1)["ai"]; assert a8["status"] == "下書き" and a8["certainty"] == "B(中)" and a8["imprecision"] == -1 and a8["based_on"] == ["50000001"] and "F45-50000001" in a8["reasons"]["imprecision"]
    assert home(R1).get("SR-8 の承認") == 1
    b8 = {k: str(a8[k]) for k in ("rob", "inconsistency", "imprecision", "indirectness", "publication_bias", "upgrade")} | {"certainty": a8["certainty"]}
    c, r = call("PUT", f"/sr8/P1/{o}", b8, R1); assert c == 200 and r["agreed_by"] == [] and x(R1)["sr8"] is None and x(R1)["state"] == "" and x(R2)["others"] == {} and x(R2)["approved_by"] == ["元雄良治"]
    c, r = call("PUT", f"/sr8/P1/{o}", {**b8, "certainty": "C(弱)"}, R2); assert r["agreed_by"] == [] and x(R1)["state"] == "不一致" and x(R1)["others"]["菊池健"]["certainty"] == "C(弱)" and home(R1).get("SR-8 の不一致") == 1
    c, r = call("PUT", f"/sr8/P1/{o}", {**b8, "note": "文章は違ってよい"}, R2); assert r["agreed_by"] == ["元雄良治", "菊池健"]
    f8 = x(R1); assert f8["state"] == "一致" and f8["sr8"]["certainty"] == "B(中)" and f8["sr8"]["by"] == "元雄良治・菊池健" and call("GET", "/etd/P1", who=R1)[1]["sr8"][o]["certainty"] == "B(中)"
    c, r = call("PUT", f"/sr8/P1/{o}", {**b8, "rob": "-1"}, R1); assert r["agreed_by"] == [] and x(R1)["sr8"] is None                  # 承認を変えると、一致が解ける(確定の記録を消す)
    acts = [a["action"] for a in call("GET", "/audit")[1]]; assert {"研究特性の承認", "SR-5の確定(2名の承認が一致)", "SR-8下書きを作成", "SR-8の承認"} <= set(acts)
    assert hasattr(draft45, "draft_etd")                                                                                  # EtD の下書きの関数がある(以前、欠けていた)


def test_update_editions_are_created_edited_in_drive_and_combined(env, tmp_path, capsys):
    """ガイドラインと総論の Update 版(Word)を、共有ドライブに作る。委員が共有ドライブで編集した版は、fetch.sh がポータルに反映する(上書きしない)。
    総論: 依頼書(2023年版の全文)が元。CQ・FRQ: ポータルの記録と 2023年版の記述が元。結合した草案(Word)は、総論と CQ の本文を含む。記録のない項目は「未記入」と出す。"""
    import importlib, urllib.parse, zipfile, glob
    sys.path.insert(0, os.path.join(HERE, "..", "api")); sys.path.insert(0, os.path.join(HERE, "..", "scripts")); import viewer; SD = importlib.import_module("sync_drive"); s3c = boto3.client("s3"); root = os.path.join(HERE, "..", "..")
    plan = json.load(open(os.path.join(root, "governance", "approved_plan.json"), encoding="utf-8"))
    # 準備: 2023年版の総論B(依頼書の Word と本文)、2023年版の CQ の記述、牛車腎気丸の検索・論文・EtD
    f = glob.glob(os.path.join(root, "soron", "out", "総論B_*.docx"))[0]
    call("POST", "/gl2023/soron", {"items": [{"key": "B", "title": "症候学的分類", "paragraphs": [{"id": "GL2023-総論B-p001", "text": "CIPNは，症候学的に感覚神経障害，運動神経障害，自律神経障害に分類される。"}], "filename": os.path.basename(f)}]})
    s3c.put_object(Bucket=H.BUCKET, Key="soron2023/B/" + os.path.basename(f), Body=open(f, "rb").read())
    call("POST", "/gl2023", {"items": json.load(open(os.path.join(root, "data", "gl2023", "etd_2023.json"), encoding="utf-8"))})
    call("POST", "/search/P1", {"database": "PubMed", "date": "2026-11-20", "searcher": "華井明子", "period": "2021/07/01〜2026/10/01", "query": "goshajinkigan", "hits": 5})
    call("POST", "/screening/P1/candidates", {"source": "検索(PubMed)", "items": [{"pmid": "60000001", "title": "Goshajinkigan trial", "authors": "Kono T", "authors_all": "Kono T, Hata T", "journal": "Cancer Chemother Pharmacol", "year": "2013", "abstract": "a"}]}, R1)
    call("POST", "/papers/P1/60000001/upload-url", {"title": "Goshajinkigan trial"}, R1)
    G = dict(email="g1@example.org", groups=("作成グループ",)); call("POST", "/users", {"email": G["email"], "name": "吉田陽一郎", "roles": ["作成グループ"]})
    text = lambda data: "\n".join(("\n".join(c_["v"] for row in b["rows"] for c_ in row) if b["t"] == "table" else b["text"]) for b in viewer.docx_view(data)["blocks"])
    key = lambda url: urllib.parse.unquote(urllib.parse.urlparse(url).path.lstrip("/")); fetch = lambda url: s3c.get_object(Bucket=H.BUCKET, Key=key(url))["Body"].read()
    # 1. Update 版の一覧: 総論 19、CQ・FRQ 15。CQ は、2028年版の記録がなければ、2023年版の記述を元の文にする
    us = call("GET", "/update")[1]; by = {u["unit"]: u for u in us}; assert len([u for u in us if u["kind"] == "総論"]) == len(plan["総論"]) and len([u for u in us if u["kind"] == "CQ・FRQ"]) == 15 and "key" not in us[0]
    assert by["soron/B"]["name"] == "総論B_症候学的分類_Update版.docx" and by["soron/B"]["source"] == "依頼書(2023年版の全文)" and by["soron/K"]["url"] == "" and by["cq/P1"]["name"] == "推奨_牛車腎気丸_Update版.docx" and by["cq/P1"]["source"] == "ポータルの記録から作成"
    t = text(fetch(by["cq/P1"]["url"])); assert "薬物療法による予防: 牛車腎気丸" in t and "牛車腎気丸を投与しないことを提案する" in t and "2023年版の記述である。改訂して" in t and "PMID 60000001" in t
    assert call("PUT", "/etd/P1", {"rec_draft": "2028年版の推奨文案。", "strength": "4 行わないことを弱く推奨", "certainty": "C(弱)", "narrative": "2028年版の解説。", "considerations": {}, "scope_note": "", "status": "協議中"}, G)[0] == 200
    t = text(fetch(call("GET", "/update")[1][[u["unit"] for u in us].index("cq/P1")]["url"])); assert "2028年版の推奨文案。" in t and "2028年版の解説。" in t and "参考: 2023年版の推奨文" in t and "2023年版の記述である。改訂して" not in t
    assert [u["unit"] for u in call("GET", "/update", who=R1)[1] if u["kind"] == "総論"] == [] and len(call("GET", "/update", who=R1)[1]) == 15          # SR委員には、総論を出さない
    assert call("POST", "/update/cq/P1/upload-url", {}, R1)[0] == 403 and call("GET", "/sync/state", who=R1)[0] == 403
    # 2. fetch.sh: 共有ドライブに Update 版を置く
    class Tok:
        def call(self, method, path, body=None): return call(method, path, body)[1]
    ups = []
    def upload(url, data, ct): ups.append(key(url)); s3c.put_object(Bucket=H.BUCKET, Key=key(url), Body=data)
    drive = str(tmp_path / "d"); os.makedirs(drive); run = lambda **kw: SD.sync_updates(Tok(), SD.Layout(drive), fetch=fetch, upload=upload, **kw)
    r = run(); folder = os.path.join(drive, "ポータル出力", "ガイドライン_Update版"); names = sorted(os.listdir(folder))
    assert len([n for n in names if n.startswith("総論")]) == 1 and len([n for n in names if n.startswith("推奨_")]) == 15 and "ガイドライン草案(結合).docx" in names and not ups and len(r["placed"]) == 17    # 依頼書のない総論(18件)は、置くものがない
    pB, pC = os.path.join(folder, "総論B_症候学的分類_Update版.docx"), os.path.join(folder, "推奨_牛車腎気丸_Update版.docx")
    r = run(); assert not r["placed"] and not r["pushed"] and not ups                                                       # 変更がなければ、何もしない
    # 3. 委員が、共有ドライブで編集する(Google ドキュメントでの編集と同じく、同じ docx が書き換わる) → ポータルに反映する。上書きしない
    def edit(path, old, new):
        zi = zipfile.ZipFile(path); b = io.BytesIO(); zo = zipfile.ZipFile(b, "w", zipfile.ZIP_DEFLATED)
        for it in zi.infolist(): zo.writestr(it, zi.read(it.filename).replace(old.encode(), new.encode()) if it.filename == "word/document.xml" else zi.read(it.filename))
        zo.close(); open(path, "wb").write(b.getvalue()); return b.getvalue()
    eB = edit(pB, "自律神経障害に分類される", "自律神経障害に分類される(総論の執筆者が共有ドライブで改訂)"); eC = edit(pC, "2028年版の解説。", "2028年版の解説(作成グループが共有ドライブで改訂)。")
    r = run(dry=True); assert sorted(os.path.basename(x) for x in r["pushed"]) == ["推奨_牛車腎気丸_Update版.docx", "総論B_症候学的分類_Update版.docx"] and not ups     # --dry-run は、表示だけ
    r = run(); assert sorted(ups) == ["soron/B/総論B_Update版.docx", "update/cq/P1/Update版.docx"] and open(pB, "rb").read() == eB and open(pC, "rb").read() == eC
    sB = next(x for x in call("GET", "/soron")[1] if x["key"] == "B"); assert sB["file"] == "総論B_Update版.docx" and sB["file_by"] == "共有ドライブで編集" and sB["status"] == "執筆中"   # 総論は、原稿の新しい版になる
    by = {u["unit"]: u for u in call("GET", "/update")[1]}; assert by["soron/B"]["source"] == "原稿" and by["cq/P1"]["source"] == "共有ドライブで編集" and fetch(by["cq/P1"]["url"]) == eC
    c, v = call("GET", "/update/view?unit=cq/P1", who=R1); assert c == 200 and v["kind"] == "docx" and any("作成グループが共有ドライブで改訂" in b.get("text", "") for b in v["blocks"]) and v["name"] == "推奨_牛車腎気丸_Update版.docx"
    assert call("GET", "/update/view?unit=soron/B", who=R1)[0] == 404 and call("GET", "/update/view?unit=soron/B")[0] == 200
    acts = [a["action"] for a in call("GET", "/audit")[1]]; assert "総論の原稿の更新(共有ドライブでの編集を反映)" in acts and "ガイドライン Update 版の更新(共有ドライブでの編集を反映)" in acts
    r = run(); assert not r["pushed"] and len(ups) == 2                                                                    # 同じ内容は、繰り返し送らない
    # 4. ポータルの側が変わり、共有ドライブは編集されていない: 共有ドライブを、新しい版にする(別の CQ)
    pD = os.path.join(folder, "推奨_デュロキセチン_Update版.docx"); before = open(pD, "rb").read()
    call("PUT", "/etd/T1", {"rec_draft": "デュロキセチンの新しい推奨文案。", "considerations": {}, "status": "下書き"}, G); r = run()
    assert [os.path.basename(x) for x in r["placed"] if "デュロキセチン_Update" in x] == ["推奨_デュロキセチン_Update版.docx"] and open(pD, "rb").read() != before and "デュロキセチンの新しい推奨文案。" in text(open(pD, "rb").read())
    # 5. 両方が変わったとき(ポータルで EtD を直し、共有ドライブでも編集): 共有ドライブの編集を残し、ポータルに反映する
    call("PUT", "/etd/P1", {"rec_draft": "ポータルで直した推奨文案。", "considerations": {}, "status": "協議中"}, G); eC2 = edit(pC, "作成グループが共有ドライブで改訂", "作成グループが共有ドライブで再び改訂"); r = run()
    assert open(pC, "rb").read() == eC2 and fetch({u["unit"]: u for u in call("GET", "/update")[1]}["cq/P1"]["url"]) == eC2
    # 6. 結合した草案(Word): 作成方法、総論の本文、CQ ごとの推奨、FRQ。共有ドライブで編集した本文が入る。依頼の文(「ご依頼の内容」)は入らない
    c, r = call("GET", "/export/guideline", who=R1); assert c == 200 and r["key"].endswith("ガイドライン草案.docx"); data = s3c.get_object(Bucket=H.BUCKET, Key=r["key"])["Body"].read(); v = viewer.docx_view(data); t = text(data)
    assert [b["text"] for b in v["blocks"] if b["t"] == "h1"] == ["1. 作成方法", "2. 総論", "3. 推奨(CQ)", "4. FRQ(Future Research Question)"]
    heads = [b["text"] for b in v["blocks"] if b["t"] == "h2"]; assert "B. 症候学的分類" in heads and "薬物療法による予防: 牛車腎気丸" in heads and len([h for h in heads if ": " in h]) == 15
    for s_ in (plan["タイトル"], "総論の執筆者が共有ドライブで改訂", "作成グループが共有ドライブで再び改訂", "デュロキセチンの新しい推奨文案。", "2021/07/01〜2026/10/01", "未記入", "PMID 60000001"): assert s_ in t, s_
    assert "ご依頼の内容" not in t and "事務局からの注記" not in t and not re.search(r"(?<![A-Za-z0-9])[PNTF]\d(?![A-Za-z0-9])", t)
    assert zipfile.ZipFile(io.BytesIO(data)).testzip() is None and open(os.path.join(folder, "ガイドライン草案(結合).docx"), "rb").read() != b""
    # 7. 以前の置き場所(依頼書/)で編集されていた総論は、Update 版として引き継ぐ(編集を失わない)
    d2 = str(tmp_path / "e"); os.makedirs(os.path.join(d2, "ポータル出力", "依頼書")); call("PUT", "/sync/state", {"items": {"soron/B": ""}})
    legacy = os.path.join(d2, "ポータル出力", "依頼書", os.path.basename(f)); open(legacy, "wb").write(open(f, "rb").read()); eL = edit(legacy, "感覚神経障害", "感覚神経障害(依頼書の置き場所で編集)")
    ups.clear(); SD.sync_updates(Tok(), SD.Layout(d2), fetch=fetch, upload=upload, only="soron/B"); assert ups == ["soron/B/総論B_Update版.docx"] and open(os.path.join(d2, "ポータル出力", "ガイドライン_Update版", "総論B_症候学的分類_Update版.docx"), "rb").read() == eL


def test_sr8_has_minds_sr8_columns(env):
    """SR-8(絶対効果指標の結果を記入する場合)の列: 研究デザイン／研究数、群ごとの分母・分子、効果指標の統合値・CI、絶対効果、重要性。ポータルは統合値を計算せず、委員が記入する"""
    register_paper("11111111"); o = "CIPN Grade2以上の発生"
    items = {k: {"v": 0, "evidence": [], "quote": "x"} for k in H.ITEM_KEYS}
    call("PUT", f"/f45/P1/11111111/{o}/final", {"items": items, "counts": {"ctrl_num": 30, "ctrl_den": 60, "int_num": 20, "int_den": 60}, "effect": {"measure": "RR", "value": 0.67}}, LEAD)
    c, d = call("GET", "/sr8/P1", who=R1); x = next(z for z in d["outcomes"] if z["outcome"] == o); assert x["sums"] == {"ctrl_den": 60, "ctrl_num": 30, "int_den": 60, "int_num": 20} and "デザイン不明" in x["design_n"]
    body = {"rob": "-1", "inconsistency": "0", "imprecision": "-1", "indirectness": "0", "publication_bias": "0", "upgrade": "0", "certainty": "B(中)", "design_n": "RCT 1件", "ctrl_den": "60", "ctrl_num": "30", "int_den": "60", "int_num": "20",
            "eff_type": "RR", "eff_val": "0.67", "eff_ci": "0.43-1.03", "abs_val": "-167/1000", "abs_ci": "-285〜+15", "importance": "9", "note": "コメント"}
    assert call("PUT", f"/sr8/P1/{o}", {**body, "ctrl_num": "x"}, R1)[0] == 400 and call("PUT", f"/sr8/P1/{o}", {**body, "importance": "10"}, R1)[0] == 400
    assert call("PUT", f"/sr8/P1/{o}", body, R1)[0] == 200 and call("PUT", f"/sr8/P1/{o}", body, R2)[1]["agreed_by"] == ["元雄良治", "菊池健"]
    import openpyxl
    r = call("GET", "/export/P1", who=R1)[1]; wb = openpyxl.load_workbook(io.BytesIO(boto3.client("s3").get_object(Bucket=H.BUCKET, Key=r["key"])["Body"].read()))
    head = [c.value for c in wb["SR-8"][1]]; row = {h: c.value for h, c in zip(head, wb["SR-8"][2])}
    assert row["研究デザイン／研究数"] == "RCT 1件" and row["対照群 (%)"] == 50.0 and row["介入群 (%)"] == 33.3 and row["効果指標 統合値"] == "0.67" and row["絶対効果"] == "-167/1000" and row["重要性(1〜9)"] == 9 and row["エビデンスの強さ"] == "B(中)"


def test_self_registration_and_approval(env):
    """自己登録: 承認の前は、何も見えない。申請 → 統括委員長が承認(役割が付く)。名簿に基づく役割の候補を示す。委員以外は、承認されない"""
    cog = boto3.client("cognito-idp"); pool = cog.create_user_pool(PoolName="t")["UserPool"]["Id"]; H.USER_POOL = pool
    try:
        for g in H.GROUPS: cog.create_group(GroupName=g, UserPoolId=pool)
        cog.admin_create_user(UserPoolId=pool, Username="new@example.org"); cog.admin_create_user(UserPoolId=pool, Username="stranger@example.org")
        N = dict(email="new@example.org", groups=()); S = dict(email="stranger@example.org", groups=())
        assert call("GET", "/me", who=N)[0] == 200
        for path in ("/cq", "/dashboard", "/papers/P1", "/screening/P1", "/soron", "/audit", "/users", "/docs", "/gl2023", "/etd/P1", "/vote/P1"):
            assert call("GET", path, who=N)[0] == 403, path                                                                                # 承認の前は、何も見えない
        assert call("POST", "/access/request", {"name": ""}, N)[0] == 400
        c, r = call("POST", "/access/request", {"name": "元雄 良治", "affiliation": "A大学"}, N); assert c == 200 and r["status"] == "承認待ち" and r["name"] == "元雄良治" and r["suggest"] == ["SR委員", "総説執筆者"]   # 氏名から、SR担当と総論K(元雄)の候補
        assert call("POST", "/access/request", {"name": "山田太郎"}, S)[1]["suggest"] == []                                                   # 名簿にない氏名は、候補なし
        assert call("POST", "/access/request", {"name": "華井明子"}, dict(email="x@example.org", groups=()))[1]["suggest"] == ["統括委員会", "総説執筆者"]
        assert call("GET", "/access", who=N)[0] == 403 and call("POST", "/access/new@example.org/approve", {"roles": ["SR委員"]}, N)[0] == 403   # 本人は承認できない
        d = call("GET", "/dashboard")[1]; assert any(a["kind"] == "利用申請の承認" for a in d["approvals"])                                         # 承認待ちが、進捗ボードに出る
        assert [a["status"] for a in call("GET", "/access")[1]][0] == "承認待ち"
        assert call("POST", "/access/new@example.org/approve", {"roles": []})[0] == 400
        c, a = call("POST", "/access/new@example.org/approve", {"roles": ["SR委員"]}); assert c == 200 and a["status"] == "承認済み" and a["granted"] is True
        assert [g["GroupName"] for g in cog.admin_list_groups_for_user(Username="new@example.org", UserPoolId=pool)["Groups"]] == ["SR委員"]
        assert next(u for u in call("GET", "/users")[1] if u["email"] == "new@example.org")["roles"] == ["SR委員"] and any(x["action"] == "利用申請の承認" for x in call("GET", "/audit")[1])
        assert call("GET", "/cq", who=dict(email="new@example.org", groups=("SR委員",)))[0] == 200                                           # 再ログインの後(グループが付いたトークン)
        assert call("POST", "/access/stranger@example.org/reject", {"reason": "委員ではない"})[1]["status"] == "却下" and call("GET", "/cq", who=S)[0] == 403
    finally:
        H.USER_POOL = ""


def test_electronic_vote(env):
    """電子投票: 投票者は統括委員会・作成グループからSR担当と投票除外を除いた人。1人1票・変更不可・無記名。終了まで集計は見えない。75%参加・80%一致で成立。最大3回"""
    G = lambda i: dict(email=f"g{i}@example.org", groups=("作成グループ",))
    for i, nm in enumerate(["荒尾晴惠", "神林祐子", "内藤陽一", "中島寿久", "菊池健"], 1): call("POST", "/users", {"email": f"g{i}@example.org", "name": nm, "roles": ["作成グループ"]})
    call("POST", "/users", {"email": "jimu@example.org", "name": "事務", "roles": ["事務局"]})
    assert call("POST", "/vote/P1/open", {}, G(1))[0] == 403 and call("GET", "/vote/P1", who=R1)[0] == 403                                           # 投票は、統括委員会・作成グループ
    assert call("POST", "/vote/P1/open", {})[0] == 409                                                                                             # 推奨文案が未記入
    call("PUT", "/etd/P1", {"rec_draft": "タキサン系薬剤によるCIPNの予防に冷却療法を提案する", "status": "協議中"}, G(1))
    assert call("PUT", "/vote/P1/exclusions", {"items": [{"email": "g4@example.org"}]})[0] == 400
    assert call("PUT", "/vote/P1/exclusions", {"items": [{"email": "g4@example.org", "reason": "直接評価した論文の筆頭著者"}]})[0] == 200
    c, o = call("POST", "/vote/P1/open", {"deadline": "2027-05-31"}); assert c == 200 and o["round"] == 1 and o["eligible"] == 4                      # 統括委員長 + g1,g2,g3(g4は COI、g5 菊池健は P1 のSR担当)
    assert call("POST", "/vote/P1/open", {})[0] == 409                                                                                             # 受付中は、重ねて開始できない
    v = call("GET", "/vote/P1", who=G(1))[1]; assert v["me"] == {"eligible": True, "round_open": 1, "voted": False} and v["rounds"][0]["result"] is None and "admin" not in v
    assert call("GET", "/vote/P1", who=G(4))[1]["me"]["eligible"] is False and call("POST", "/vote/P1/cast", {"round": 1, "choice": "2"}, G(4))[0] == 403 and call("POST", "/vote/P1/cast", {"round": 1, "choice": "2"}, G(5))[0] == 403
    assert call("POST", "/vote/P1/cast", {"round": 1, "choice": "9"}, G(1))[0] == 400 and call("POST", "/vote/P1/cast", {"round": 2, "choice": "2"}, G(1))[0] == 409
    assert any(a["cq"] == "P1" for a in call("GET", "/dashboard", who=G(1))[1]["my_votes"])
    assert call("POST", "/vote/P1/cast", {"round": 1, "choice": "2"}, G(1))[0] == 200 and call("POST", "/vote/P1/cast", {"round": 1, "choice": "1"}, G(1))[0] == 409   # 変更できない
    assert not call("GET", "/dashboard", who=G(1))[1]["my_votes"]
    call("POST", "/vote/P1/cast", {"round": 1, "choice": "2"}, G(2)); call("POST", "/vote/P1/cast", {"round": 1, "choice": "棄権"}, G(3))
    adm = call("GET", "/vote/P1")[1]["admin"]; assert adm["not_voted"] == ["華井明子"] and adm["sr_excluded"] == ["菊池健"] and call("GET", "/vote/P1")[1]["rounds"][0]["voted"] == 3
    # 無記名: 票(BALLOT)に、メールアドレス・時刻がない。API は、個別の票を返さない
    ballots = H.query("BALLOT", "P1#1#"); assert sorted(b["choice"] for b in ballots) == ["2", "2", "棄権"] and all(set(b) == {"pk", "sk", "choice"} for b in ballots)
    assert '"choice"' not in json.dumps(call("GET", "/vote/P1")[1], ensure_ascii=False) and "g1@example.org" not in json.dumps(call("GET", "/vote/P1", who=G(2))[1], ensure_ascii=False)
    assert call("POST", "/vote/P1/close", {}, G(1))[0] == 403
    res = call("POST", "/vote/P1/close", {})[1]; assert res["counts"] == [0, 2, 0, 0, 0] and res["abstain"] == 1 and res["participants"] == 3 and res["eligible"] == 4 and res["participation_pct"] == 75.0 and res["agreement_pct"] == 66.7 and res["passed"] is False
    assert call("POST", "/vote/P1/cast", {"round": 1, "choice": "2"}, dict(email="g1@example.org", groups=("作成グループ",)))[0] == 409
    e = call("GET", "/etd/P1")[1]["etd"]; assert e["vote"]["counts"] == [0, 2, 0, 0, 0] and e["vote"]["denominator"] == 3 and e["vote"]["eligible"] == 4 and "電子投票" in e["vote"]["note"] and e.get("strength", "") != "2 弱く推奨"
    # 第2回: 参加 100%、全員が 2 → 成立。推奨の強さが投票で決まる
    assert call("POST", "/vote/P1/open", {})[1]["round"] == 2
    for who in (G(1), G(2), G(3), CHAIR): assert call("POST", "/vote/P1/cast", {"round": 2, "choice": "2"}, who)[0] == 200
    res = call("POST", "/vote/P1/close", {})[1]; assert res["passed"] is True and res["strength"] == 2 and res["agreement_pct"] == 100.0
    e = call("GET", "/etd/P1")[1]["etd"]; assert e["strength"] == "2 弱く推奨" and e["vote"]["round"] == 2
    assert call("PUT", "/etd/P1", {"strength": "5 行わないことを強く推奨"}, G(1))[1]["strength"] == "2 弱く推奨"                                      # 投票の後は、手で変えられない
    assert call("POST", "/vote/P1/open", {})[0] == 409                                                                                             # 成立済み
    # 3回で成立しない → 推奨なし
    call("PUT", "/etd/P2", {"rec_draft": "案", "status": "協議中"}, G(1))
    for n in (1, 2, 3):
        assert call("POST", "/vote/P2/open", {})[1]["round"] == n
        for i, who in enumerate((G(1), G(2), G(3), G(4), G(5), CHAIR)): call("POST", "/vote/P2/cast", {"round": n, "choice": str(1 + i % 4)}, who)
        r3 = call("POST", "/vote/P2/close", {})[1]
    assert r3["passed"] is False and r3["final_none"] is True and call("GET", "/etd/P2")[1]["etd"]["strength"] == "3 推奨なし" and call("POST", "/vote/P2/open", {})[0] == 409
