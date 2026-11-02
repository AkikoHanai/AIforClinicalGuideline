"""様式4-5(評価シート 介入研究)の下書き。Bedrock(Claude)に、Method と Result の段落(ID付き)だけを渡し、15項目の 0/-1/-2 と、根拠の段落IDを返させる。
下書きは委員2名の独立した判定の出発点であり、確定値ではない(Minds 2020、統括委員長の決定)。
抄録のみの論文には使わない(呼び出し側で本文の有無を確認する)。"""
import json, os, re
import boto3

MODEL_ID = os.environ.get("BEDROCK_MODEL_ID", "anthropic.claude-sonnet-4-5")
ITEM_KEYS = ["randomization", "concealment", "blinding_participants", "blinding_assessors", "itt", "incomplete_outcome", "selective_reporting", "early_stopping", "other_bias", "bias_summary",
             "ind_population", "ind_intervention", "ind_comparator", "ind_outcome", "ind_summary"]
ITEM_JA = dict(zip(ITEM_KEYS, ["ランダム化", "コンシールメント", "盲検化(参加者・医療提供者)", "盲検化(アウトカム評価者)", "ITT", "アウトカム不完全報告", "選択的アウトカム報告", "早期試験中止", "その他のバイアス", "バイアスリスク まとめ",
                               "非直接性 対象", "非直接性 介入", "非直接性 対照", "非直接性 アウトカム", "非直接性 まとめ"]))
CHEMO_CLASSES = ["白金製剤", "タキサン系", "ビンカアルカロイド", "ボルテゾミブ等", "混在", "不明"]

SYSTEM = ("あなたは診療ガイドライン(Minds診療ガイドライン作成マニュアル2020)の系統的レビュー担当の補助です。"
          "渡された論文本文の段落(主にMethodとResult。各段落にIDがある)だけを根拠に、Minds様式『4-5 評価シート 介入研究』の各項目を 0(低リスク)/-1(中・疑い)/-2(高リスク)で評価し、指定のJSONのみを返してください。"
          "本文に書かれていないことは推測しません。評価の最終判断は人間の評価者2名が行います。")

PROMPT = """CQ: {cq_title}
対象(P): {population}
介入(I): {intervention}
アウトカム: {outcome}

評価の基準(Minds 4-5):
- 各項目は 0=低リスク(適切に行われている) / -1=中・疑い(不明・不十分) / -2=高リスク(行われていない)。
- 盲検化の2項目(参加者・医療提供者、アウトカム評価者)は、二重盲検=0、単盲検=-1、非盲検(オープンラベル)=-1、記載がない=-1 とし、-2 は使わない(統括委員長の決定)。
- 非直接性 対象/介入/対照/アウトカム = 本CQのPICOとのずれ(0=一致、-1=やや異なる、-2=大きく異なる)。対象では、化学療法の種類(白金製剤/タキサン系 等)とがん腫が本CQの対象と一致するかを評価する。
- 非RCTの場合、ランダム化・コンシールメントは null とし、デザインを書く。

判定の手順(各項目で同じ):
1. 段落から、その項目に該当する記載を探し、段落IDを evidence に入れ、原文を quote に短く写す。引用できない記載を根拠にしない。
2. 記載があり適切なら 0。記載があり不適切なら -2(盲検化の2項目は -1)。記載がなければ -1 とし、quote に「記載なし」と書く。推測で 0 にしない。
3. 項目ごとに確認する記載: ランダム化=乱数の生成方法。コンシールメント=中央割付・封筒・ウェブ等の割付の隠蔽方法。盲検化=誰が盲検化されたか。ITT=解析集団の定義。
   アウトカム不完全報告=群ごとの脱落・欠測の数と割合、その扱い。選択的アウトカム報告=試験登録番号・プロトコールと報告アウトカムの対応。早期試験中止=予定症例数と中止の有無・理由。その他=資金源・COI・単施設・ベースラインの不均衡。
4. 非直接性は、本CQのP(がん腫・化学療法の種類)・I・C・Oと、本文の記載を1つずつ比べる。

JSONを1つだけ返す:
{{
  "design": "RCT | non_RCT | other",
  "study": {{"cancer": "がん腫", "chemo_drugs": "化学療法の薬剤名(本文のまま)", "chemo_class": "{chemo_classes} のいずれか", "n_total": 数値またはnull, "n_int": 数値またはnull,
             "intervention_detail": "介入の内容", "comparator_detail": "対照の内容", "followup": "評価時点", "instrument": "このアウトカムの測定尺度"}},
  "items": {{ {item_fields} }},
  "counts": {{"ctrl_den": null, "ctrl_num": null, "int_den": null, "int_num": null}},
  "effect": {{"measure": "RR|OR|HR|MD|SMD|null", "value": null, "ci_low": null, "ci_high": null}}
}}
items の各値は {{"v": 0|-1|-2|null, "evidence": ["段落ID"], "quote": "原文の短い引用または「記載なし」"}}

--- 論文本文の段落 ---
{paras}
"""


def draft(cq_title, population, intervention, outcome, paras, model_id=None):
    item_fields = ", ".join(f'"{k}": {{"v": null, "evidence": [], "quote": ""}}' for k in ITEM_KEYS)
    body = "\n".join(f"[{p['id']}] ({p['section']}, p.{p['page']}) {p['text']}" for p in paras)
    prompt = PROMPT.format(cq_title=cq_title, population=population or "がん薬物療法に伴う末梢神経障害のあるがん患者、またはそのリスクのあるがん患者", intervention=intervention, outcome=outcome,
                           chemo_classes="/".join(CHEMO_CLASSES), item_fields=item_fields, paras=body)
    client = boto3.client("bedrock-runtime")
    resp = client.converse(modelId=model_id or MODEL_ID, system=[{"text": SYSTEM}], messages=[{"role": "user", "content": [{"text": prompt}]}],
                           inferenceConfig={"maxTokens": 4000, "temperature": 0})
    text = resp["output"]["message"]["content"][0]["text"]
    m = re.search(r"\{.*\}", text, re.S)
    out = json.loads(m.group(0) if m else text)
    valid = {p["id"] for p in paras}
    items = {}
    for k in ITEM_KEYS:
        it = (out.get("items") or {}).get(k) or {}
        v = it.get("v")
        if v not in (0, -1, -2, None):
            v = None
        if k in ("blinding_participants", "blinding_assessors") and v == -2:
            v = -1
        ev = [e for e in (it.get("evidence") or []) if e in valid]  # 存在しない段落IDは捨てる
        items[k] = {"v": v, "evidence": ev, "quote": str(it.get("quote") or "")[:400]}
    out["items"] = items
    return out


# ---------- EtD(推奨文・考慮事項・解説文)の下書き ----------
ETD_SYSTEM = ("あなたは診療ガイドライン(Minds診療ガイドライン作成マニュアル2020)の推奨作成の補助です。"
              "渡された資料(様式SR-8、確定した様式4-5の要約、2023年版の記述。各段落・記録にIDがある)だけを根拠に、2023年版の体裁の EtD(推奨文案、4つの考慮事項、解説文案)の下書きを作り、指定のJSONのみを返してください。"
              "根拠のない記述は書きません。推奨の強さと確実性は決めません(推奨作成会議の投票と様式SR-8の判定による)。")
ETD_PROMPT = """CQ: {cq_title}
P: {P}
I: {I}
C: {C}
O: {O}

規則:
- 推奨文案には、適用するがん腫と化学療法の分類(白金製剤/タキサン系など)を明記する。予防か治療かを明記する。
- 4つの考慮事項(益と害のバランス、エビデンスの確実性、患者の価値観・希望、コスト・資源)は、各文の末尾に根拠のIDを [ID] で付ける。根拠は、様式SR-8(ID: SR8-<アウトカム>)、様式4-5の確定記録(ID: F45-<PMID>-<アウトカム>)、2023年版の段落(ID: GL2023-...)に限る。
- 解説文案は、2023年版の解説の構成に合わせ、変更点(新しい研究、確実性の変化)を本文で示す。各文の末尾に根拠のIDを付ける。根拠のない一般論は書かない。
- 推奨の強さ、確実性(A〜D)は書かない。

JSONを1つだけ返す:
{{"rec_draft": "推奨文案", "considerations": {{"benefit_harm": {{"text": "", "evidence": []}}, "certainty": {{"text": "", "evidence": []}}, "values": {{"text": "", "evidence": []}}, "cost": {{"text": "", "evidence": []}}}}, "narrative": "解説文案", "changes_from_2023": "2023年版からの変更点"}}

--- 様式SR-8 ---
{sr8}
--- 様式4-5(確定)の要約 ---
{f45}
--- 2023年版の記述 ---
{gl}
"""


def draft_etd(cq, sr8_rows, finals, papers, gl2023, model_id=None):
    pm = {p["pmid"]: p for p in papers}
    sr8 = "\n".join(f"[SR8-{r['outcome']}] 研究数 {sum(1 for f in finals if f['outcome'] == r['outcome'])}、バイアスリスク {r.get('rob')}、非一貫性 {r.get('inconsistency')}、不精確性 {r.get('imprecision')}、非直接性 {r.get('indirectness')}、その他 {r.get('publication_bias')}、上昇要因 {r.get('upgrade')}、確実性 {r.get('certainty')}。層別: {r.get('strata', '')}。効果の要約: {r.get('effect_summary', '')}" for r in sr8_rows) or "(記入なし)"
    f45 = "\n".join(f"[F45-{f['pmid']}-{f['outcome']}] {pm.get(f['pmid'], {}).get('title', '')} / がん腫 {(pm.get(f['pmid'], {}).get('chars') or {}).get('cancer', '')} / 分類 {(pm.get(f['pmid'], {}).get('chars') or {}).get('chemo_class', '')} / バイアスリスクまとめ {f['items']['bias_summary']['v']} 非直接性まとめ {f['items']['ind_summary']['v']} / 対照 {(f.get('counts') or {}).get('ctrl_num')}/{(f.get('counts') or {}).get('ctrl_den')} 介入 {(f.get('counts') or {}).get('int_num')}/{(f.get('counts') or {}).get('int_den')} / 効果 {(f.get('effect') or {}).get('measure')} {(f.get('effect') or {}).get('value')} [{(f.get('effect') or {}).get('ci_low')}, {(f.get('effect') or {}).get('ci_high')}]" for f in finals) or "(確定なし)"
    g = gl2023 or {}
    gl = (f"推奨文: {g.get('rec', '')} / 推奨の強さ {g.get('strength', '')} / 確実性 {g.get('certainty', '')}\n" + "\n".join(f"[{p['id']}] {p['text']}" for p in g.get("paragraphs", []))) if g else "(未取り込み)"
    prompt = ETD_PROMPT.format(cq_title=cq["title"], P=cq["pico"].get("P", ""), I=cq["pico"].get("I", ""), C=cq["pico"].get("C", ""), O=cq["pico"].get("O", ""), sr8=sr8, f45=f45, gl=gl)
    client = boto3.client("bedrock-runtime")
    resp = client.converse(modelId=model_id or MODEL_ID, system=[{"text": ETD_SYSTEM}], messages=[{"role": "user", "content": [{"text": prompt}]}], inferenceConfig={"maxTokens": 6000, "temperature": 0})
    text = resp["output"]["message"]["content"][0]["text"]
    m = re.search(r"\{.*\}", text, re.S)
    out = json.loads(m.group(0) if m else text)
    valid = {f"SR8-{r['outcome']}" for r in sr8_rows} | {f"F45-{f['pmid']}-{f['outcome']}" for f in finals} | {p["id"] for p in g.get("paragraphs", [])}
    cons = {}
    for k in ("benefit_harm", "certainty", "values", "cost"):
        c = (out.get("considerations") or {}).get(k) or {}
        cons[k] = {"text": str(c.get("text") or "")[:3000], "evidence": [e for e in (c.get("evidence") or []) if e in valid]}
    return {"rec_draft": str(out.get("rec_draft") or "")[:1000], "considerations": cons, "narrative": str(out.get("narrative") or "")[:12000], "changes_from_2023": str(out.get("changes_from_2023") or "")[:3000]}
