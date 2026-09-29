"""
papers/*.pdf → RoB2_Claude下書き シートを自動記入
====================================================================
委員がPDFを papers/ に入れたら、論文本文(Method/Result)から
  デザイン / 対照の種類 / 対応するアウトカム / 適格性 / RoB2の5ドメイン+総合
を Claude (AWS Bedrock) に構造化させ、minds_review.xlsx の「RoB2_Claude下書き」に
書き込む。あわせて評価者2名のシート(RoB2_<名前>)の空欄にも同じ下書きを
コピーするので、委員は「白紙から書く」のではなく「下書きを直す」だけになる。

実行環境: AWS認証情報のあるMac。このリポジトリの bedrock_screening.py と同じ
boto3 converse API を使う。
  export AWS_PROFILE=...  (または AWS_ACCESS_KEY_ID/SECRET)
  export BEDROCK_MODEL_ID=anthropic.claude-...   # 省略時は下の既定値
  python3 fill_rob2_from_papers.py <review_workspaceディレクトリ> [--only CQ1-冷却・圧迫] [--dry-run]

--dry-run: Bedrockを呼ばず、PDFテキスト抽出と書き込み経路だけ確認する
           (各ドメインに "要確認" を入れる)。認証情報のない環境での動作確認用。

PDFのファイル名は PMID.pdf を推奨(RoB2シートの行と突き合わせるため)。
PMIDでない名前のPDFは、本文から DOI/PMID を拾えなければ「新規追加」候補行として
末尾に追加する。
"""
import argparse
import glob
import json
import os
import re
import subprocess
import sys

from openpyxl import load_workbook

DEFAULT_MODEL = os.environ.get("BEDROCK_MODEL_ID", "anthropic.claude-sonnet-4-5")
DOMAIN_KEYS = ["D1", "D2", "D3", "D4", "D5", "overall"]
ROB2_COL = {"cite": 2, "outcome_id": 3, "design": 4, "comparator": 5, "eligible": 6,
            "D1": 7, "D2": 8, "D3": 9, "D4": 10, "D5": 11, "overall": 12,
            "cited_2023": 13, "newly_added": 14, "note": 15, "instrument": 16}

SYSTEM = (
    "あなたは系統的レビューのデータ抽出担当です。渡された論文本文(主にMethodとResult)だけを"
    "根拠に、Cochrane RoB 2 に従って評価し、指定のJSONのみを返してください。"
    "本文に書かれていないことは推測せず null にしてください。"
)

PROMPT = """CQ: {cq_title}
介入: {intervention}
アウトカム候補: {outcomes}

以下の論文本文からJSONを1つだけ返してください(説明文は不要)。
{{
  "pmid": "本文中にあれば",
  "design": "RCT | meta_analysis | cohort | case_control | cross_sectional | case_series | other",
  "comparator": "none | usual_care | placebo | active_weaker | active_different",
  "outcome_id": "上のアウトカム候補のIDのうち、この論文の主要アウトカムに該当するもの。無ければ null",
  "eligible": true/false  (適格基準: 18歳以上・がん患者・英語・国内で実施可能・メタ解析/RCT/分析疫学研究),
  "rob2": {{
    "D1": "低 | 懸念あり | 高",  // ランダム化の過程
    "D2": "低 | 懸念あり | 高",  // 意図した介入からの逸脱
    "D3": "低 | 懸念あり | 高",  // アウトカムデータの欠測
    "D4": "低 | 懸念あり | 高",  // アウトカム測定
    "D5": "低 | 懸念あり | 高",  // 選択的な結果報告
    "overall": "低 | 懸念あり | 高"
  }},
  "rob2_rationale": {{"D1": "根拠(本文の該当箇所を短く)", "D2": "...", "D3": "...", "D4": "...", "D5": "..."}},
  "effect": {{"measure": "RR|OR|HR|MD|SMD|null", "point": 数値またはnull, "ci_low": null, "ci_high": null,
             "outcome_text": "本文の記載"}},
  "instrument": "アウトカムの測定に使った評価指標(例: CTCAE v4.0 grade≥2, EORTC QLQ-CIPN20, FACT-Ntx, NRS, TNS)。複数ならカンマ区切り",
  "citation": {{"first_author": "第一著者の姓", "year": 西暦, "title": "論文タイトル", "journal": "誌名"}},
  "n_total": 数値またはnull
}}
RCTでない場合、rob2 は null にし、design と理由を rob2_rationale.note に書いてください。

--- 論文本文 ---
{text}
"""


def pdf_text(path, max_chars=60000):
    r = subprocess.run(["pdftotext", "-layout", path, "-"], capture_output=True, text=True)
    t = r.stdout
    # Method〜Result を優先(長い論文はそこだけ)
    m = re.search(r"(?is)\b(methods?|patients and methods|materials and methods)\b", t)
    if m and len(t) > max_chars:
        t = t[m.start():]
    return t[:max_chars]


def call_bedrock(system, prompt, model_id):
    import boto3  # 実行はMac側。ここではimportを遅延させる
    client = boto3.client("bedrock-runtime", region_name=os.environ.get("AWS_REGION", "ap-northeast-1"))
    resp = client.converse(
        modelId=model_id,
        system=[{"text": system}],
        messages=[{"role": "user", "content": [{"text": prompt}]}],
        inferenceConfig={"maxTokens": 2000, "temperature": 0},
    )
    text = resp["output"]["message"]["content"][0]["text"]
    m = re.search(r"\{.*\}", text, re.S)
    return json.loads(m.group(0) if m else text)


def extract_one(pdf, cq_title, intervention, outcomes, model_id, dry_run):
    text = pdf_text(pdf)
    if dry_run:
        head = subprocess.run(["pdftotext", "-l", "1", pdf, "-"], capture_output=True, text=True).stdout
        lines = [ln.strip() for ln in head.splitlines() if ln.strip()]
        # 1ページ目で最初の「長めの行」をタイトル候補に。無ければ最長行
        title = (next((ln for ln in lines if len(ln) > 25), None)
                 or (max(lines, key=len) if lines else ""))[:120]
        return {"pmid": None, "design": "要確認", "comparator": None, "outcome_id": None,
                "eligible": None, "rob2": {k: "要確認" for k in DOMAIN_KEYS},
                "rob2_rationale": {"note": f"dry-run: 本文{len(text)}文字を抽出。Bedrock未呼び出し"},
                "effect": None, "instrument": None,
                "citation": {"first_author": None, "year": None, "title": title, "journal": None},
                "n_total": None}
    prompt = PROMPT.format(cq_title=cq_title, intervention=intervention,
                           outcomes=json.dumps(outcomes, ensure_ascii=False), text=text)
    return call_bedrock(SYSTEM, prompt, model_id)


def rob2_sheets(wb):
    draft = wb["RoB2_Claude下書き"] if "RoB2_Claude下書き" in wb.sheetnames else None
    reviewers = [wb[n] for n in wb.sheetnames
                 if n.startswith("RoB2_") and n not in ("RoB2_Claude下書き", "RoB2_照合")]
    return draft, reviewers


def row_index_by_pmid(ws):
    idx = {}
    for r in range(2, ws.max_row + 1):
        v = ws.cell(row=r, column=1).value
        if v:
            idx[str(v).strip()] = r
    return idx


def write_row(ws, r, res, overwrite):
    """下書きは常に上書き。評価者シートは空欄だけ埋める(委員の記入を消さない)"""
    def put(col, val):
        if val is None:
            return
        cell = ws.cell(row=r, column=col)
        if overwrite or cell.value in (None, ""):
            cell.value = val
    put(ROB2_COL["design"], res.get("design"))
    put(ROB2_COL["comparator"], res.get("comparator"))
    put(ROB2_COL["outcome_id"], res.get("outcome_id"))
    if res.get("eligible") is not None:
        put(ROB2_COL["eligible"], "Y" if res["eligible"] else "N")
    rob = res.get("rob2") or {}
    for k in DOMAIN_KEYS:
        put(ROB2_COL[k], rob.get(k))
    put(ROB2_COL["instrument"], res.get("instrument"))
    rat = res.get("rob2_rationale") or {}
    eff = res.get("effect") or {}
    note_parts = []
    if eff and eff.get("measure"):
        note_parts.append(f"効果: {eff.get('measure')} {eff.get('point')} "
                          f"({eff.get('ci_low')}–{eff.get('ci_high')})")
    if rat:
        note_parts.append("RoB2根拠: " + "; ".join(f"{k}:{v}" for k, v in rat.items() if v))
    if note_parts and overwrite:
        ws.cell(row=r, column=ROB2_COL["note"]).value = " / ".join(note_parts)[:1000]


def process_cq(cq_dir, model_id, dry_run):
    xlsx = os.path.join(cq_dir, "minds_review.xlsx")
    pkg_path = os.path.join(cq_dir, "cq_package.json")
    pdfs = sorted(glob.glob(os.path.join(cq_dir, "papers", "*.pdf")))
    if not (os.path.exists(xlsx) and pdfs):
        return None
    pkg = json.load(open(pkg_path, encoding="utf-8")) if os.path.exists(pkg_path) else {}
    outcomes = [{"id": o["id"], "label": o["label"]} for o in pkg.get("outcomes", [])]
    wb = load_workbook(xlsx)
    draft, reviewers = rob2_sheets(wb)
    if draft is None:
        print(f"  [skip] {cq_dir}: RoB2_Claude下書き シートがありません(prepare_review_workspace.py を再実行)")
        return None
    idx = row_index_by_pmid(draft)
    done, added = 0, 0
    new_items = []
    for pdf in pdfs:
        stem = os.path.splitext(os.path.basename(pdf))[0]
        res = extract_one(pdf, pkg.get("title", ""), pkg.get("_source", {}).get("intervention", ""),
                          outcomes, model_id, dry_run)
        pmid = stem if stem.isdigit() else (str(res.get("pmid")) if res.get("pmid") else None)
        r = idx.get(pmid) if pmid else None
        cit = res.get("citation") or {}
        label = (f"{cit.get('first_author')} {cit.get('year')}".strip()
                 if cit.get("first_author") else f"(新規) {stem}")
        if r is None:
            # 2023年版に無い論文 → 新規追加行(下書き・評価者シート・スクリーニングログ)
            r = _append_new_row(draft, pmid or stem, label)
            for ws in reviewers:
                _append_new_row(ws, pmid or stem, label)
            _append_screening(wb, pmid or stem, label, cit)
            new_items.append({"pmid": pmid, "stem": stem, "label": label, "cit": cit})
            idx[pmid or stem] = r
            added += 1
        write_row(draft, r, res, overwrite=True)
        for ws in reviewers:
            ridx = row_index_by_pmid(ws)
            rr = ridx.get(pmid) if pmid else None
            if rr:
                write_row(ws, rr, res, overwrite=False)
        done += 1
        print(f"    {os.path.basename(pdf)} → {res.get('design')} / overall={((res.get('rob2') or {}).get('overall'))}")
    wb.save(xlsx)
    if new_items:
        _update_manifest(os.path.join(cq_dir, "MANIFEST.md"), new_items)
    return {"cq": os.path.basename(cq_dir), "pdfs": done, "new": added}


def _first_free_row(ws):
    """末尾の案内行(PMID空・備考に説明)を避けて、PMID列が埋まった最後の行の次"""
    last = 1
    for r in range(2, ws.max_row + 1):
        if ws.cell(row=r, column=1).value:
            last = r
    return last + 1


def _append_new_row(ws, pmid, label):
    r = _first_free_row(ws)
    # 案内行が挟まっている場合はその行を使う(上書き)
    ws.cell(row=r, column=1).value = pmid
    ws.cell(row=r, column=ROB2_COL["cite"]).value = label
    ws.cell(row=r, column=ROB2_COL["newly_added"]).value = "○"
    ws.cell(row=r, column=ROB2_COL["cited_2023"]).value = None
    return r


def _append_screening(wb, pmid, label, cit):
    if "スクリーニングログ" not in wb.sheetnames:
        return
    ws = wb["スクリーニングログ"]
    for r in range(2, ws.max_row + 1):
        if str(ws.cell(row=r, column=1).value or "") == str(pmid):
            return  # 既にある
    r = 2
    while r <= ws.max_row and (ws.cell(row=r, column=1).value or ws.cell(row=r, column=2).value):
        if str(ws.cell(row=r, column=1).value or "").startswith("──"):
            break
        r += 1
    ws.insert_rows(r)
    ws.cell(row=r, column=1).value = pmid
    ws.cell(row=r, column=2).value = f"{label}: {cit.get('title') or ''}"[:200]
    ws.cell(row=r, column=3).value = "papers/ に追加(検索/ハンドサーチ)"
    ws.cell(row=r, column=4).value = ""   # 一次スクリーニングは委員が判定


def _update_manifest(path, new_items):
    """MANIFEST.md の「新規追加文献」表を papers/ の実態で作り直す"""
    if not os.path.exists(path):
        return
    txt = open(path, encoding="utf-8").read()
    head, sep, _ = txt.partition("## 新規追加文献(改訂で追加するもの)")
    rows = ["| # | PMID | 収集 | 文献 |", "|---|---|---|---|"]
    for i, it in enumerate(new_items, start=1):
        pmid = it["pmid"]
        link = f"[{pmid}](https://pubmed.ncbi.nlm.nih.gov/{pmid}/)" if pmid else it["stem"]
        cit = it["cit"] or {}
        desc = " ".join(x for x in [it["label"], cit.get("title") or "", cit.get("journal") or ""] if x)
        rows.append(f"| {i} | {link} | ☑ | {desc} |")
    new = (head + "## 新規追加文献(改訂で追加するもの)\n\n"
           "papers/ に置かれたPDFのうち2023年版に無いもの(fill_rob2_from_papers.py が自動更新)\n\n"
           + "\n".join(rows) + "\n")
    open(path, "w", encoding="utf-8").write(new)


def main():
    ap = argparse.ArgumentParser(description="papers/*.pdf → RoB2_Claude下書き")
    ap.add_argument("workspace_dir")
    ap.add_argument("--only", help="特定のCQディレクトリ名だけ処理")
    ap.add_argument("--model", default=DEFAULT_MODEL)
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--sync-only", action="store_true",
                    help="Bedrockを呼ばず、papers/ の新規PDFをシート・マニフェストに登録するだけ")
    args = ap.parse_args()

    dirs = sorted(d for d in glob.glob(os.path.join(args.workspace_dir, "*")) if os.path.isdir(d))
    if args.only:
        dirs = [d for d in dirs if os.path.basename(d) == args.only]
    total = 0
    for d in dirs:
        n_pdf = len(glob.glob(os.path.join(d, "papers", "*.pdf")))
        if not n_pdf:
            continue
        print(f"{os.path.basename(d)}: PDF {n_pdf}件")
        r = process_cq(d, args.model, args.dry_run or args.sync_only)
        if r:
            total += r["pdfs"]
    if total == 0:
        print("papers/ にPDFが見つかりませんでした。PMID.pdf の名前で各CQの papers/ に置いてください。")
    else:
        print(f"\n{total}件のPDFを処理しました。次: merge_rob2_evidence.py → review_bundle.py → render_console.py")


if __name__ == "__main__":
    main()
