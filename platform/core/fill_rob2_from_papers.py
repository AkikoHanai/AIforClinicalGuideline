"""
論文本文 → RoB2_Claude下書き シートを自動記入
====================================================================
RoB2シートに並ぶ論文(2023年版採用 + papers/ の新規PDF)について、本文
(Method/Result)から
  デザイン / 対照の種類 / 対応するアウトカム / 評価指標 / 適格性 / RoB2の5ドメイン+総合
を Claude (AWS Bedrock) に構造化させ、「RoB2_Claude下書き」に書き込む。
評価者2名のシート(RoB2_<名前>)の空欄にも同じ下書きをコピーする。

本文の入手順(PDFは必須ではない):
  1. papers/<PMID>.pdf があればそれ(pdftotext)
  2. 無ければ Europe PMC のオープンアクセス全文(PMC)を取得 … 多くの論文はこれで足りる
  3. それも無ければ PubMed の抄録のみ(RoB2は「抄録のみ」と注記し、要PDF)
取得した本文は papers/<PMID>.txt にキャッシュする(2回目以降は通信しない)。
有料誌で全文が取れなかったものだけ、委員が papers/<PMID>.pdf を置けばよい。

実行環境: AWS認証情報のあるMac(ネットワーク必要)。
  python3 fill_rob2_from_papers.py <review_workspace> [--only CQ1-冷却・圧迫] [--dry-run] [--no-fetch] [--sync-only]
  --dry-run   : Bedrockを呼ばず、本文取得と書き込み経路だけ確認(各ドメインに"要確認")
  --no-fetch  : ネットワーク取得をしない(PDFとキャッシュのみ)
  --sync-only : papers/ の新規PDFをシート・マニフェストに登録するだけ(=dry-run + no-fetch)
"""
import argparse
import glob
import json
import os
import re
import subprocess
import sys
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET

from openpyxl import load_workbook

DEFAULT_MODEL = os.environ.get("BEDROCK_MODEL_ID", "anthropic.claude-sonnet-4-5")
DOMAIN_KEYS = ["D1", "D2", "D3", "D4", "D5", "overall"]
ROB2_COL = {"cite": 2, "outcome_id": 3, "design": 4, "comparator": 5, "eligible": 6,
            "D1": 7, "D2": 8, "D3": 9, "D4": 10, "D5": 11, "overall": 12,
            "cited_2023": 13, "newly_added": 14, "note": 15, "instrument": 16}
KIND_JA = {"pdf": "PDF", "oa_fulltext": "全文(オープンアクセス)", "abstract": "抄録のみ(要PDF)",
           "none": "本文なし(要PDF)"}
UA = {"User-Agent": "AIforClinicalGuideline/1.0 (CIPN guideline revision; contact via repo)"}

SYSTEM = (
    "あなたは系統的レビューのデータ抽出担当です。渡された論文本文(主にMethodとResult)だけを"
    "根拠に、Cochrane RoB 2 に従って評価し、指定のJSONのみを返してください。"
    "本文に書かれていないことは推測せず null にしてください。"
)

PROMPT = """CQ: {cq_title}
介入: {intervention}
アウトカム候補: {outcomes}
本文の種類: {kind}  (抄録のみの場合、RoB2は判定できるドメインだけ埋め、他は null)

以下の論文本文からJSONを1つだけ返してください(説明文は不要)。
{{
  "pmid": "本文中にあれば",
  "design": "RCT | meta_analysis | cohort | case_control | cross_sectional | case_series | other",
  "comparator": "none | usual_care | placebo | active_weaker | active_different",
  "outcome_id": "上のアウトカム候補のIDのうち、この論文の主要アウトカムに該当するもの。無ければ null",
  "instrument": "アウトカムの測定に使った評価指標(例: CTCAE v4.0 grade>=2, EORTC QLQ-CIPN20, FACT-Ntx, NRS, TNS)。複数ならカンマ区切り",
  "eligible": true/false  (適格基準: 18歳以上・がん患者・英語・国内で実施可能・メタ解析/RCT/分析疫学研究),
  "rob2": {{
    "D1": "低 | 懸念あり | 高",
    "D2": "低 | 懸念あり | 高",
    "D3": "低 | 懸念あり | 高",
    "D4": "低 | 懸念あり | 高",
    "D5": "低 | 懸念あり | 高",
    "overall": "低 | 懸念あり | 高"
  }},
  "rob2_rationale": {{"D1": "根拠(本文の該当箇所を短く)", "D2": "...", "D3": "...", "D4": "...", "D5": "..."}},
  "effect": {{"measure": "RR|OR|HR|MD|SMD|null", "point": 数値またはnull, "ci_low": null, "ci_high": null,
             "outcome_text": "本文の記載"}},
  "citation": {{"first_author": "第一著者の姓", "year": 西暦, "title": "論文タイトル", "journal": "誌名"}},
  "n_total": 数値またはnull
}}
RCTでない場合、rob2 は null にし、design と理由を rob2_rationale.note に書いてください。

--- 論文本文 ---
{text}
"""


# ------------------------------------------------------------------
# 本文の入手
# ------------------------------------------------------------------
def _get(url, timeout=30):
    req = urllib.request.Request(url, headers=UA)
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return r.read().decode("utf-8", "replace")


def pdf_text(path, max_chars=60000):
    r = subprocess.run(["pdftotext", "-layout", path, "-"], capture_output=True, text=True)
    t = r.stdout
    m = re.search(r"(?is)\b(methods?|patients and methods|materials and methods)\b", t)
    if m and len(t) > max_chars:
        t = t[m.start():]
    return t[:max_chars]


def europepmc_fulltext_xml_to_text(xml_text, max_chars=60000):
    """JATS XML → Methods/Results 優先のプレーンテキスト"""
    root = ET.fromstring(xml_text)
    def txt(el):
        return " ".join(t.strip() for t in el.itertext() if t and t.strip())
    body = root.find(".//body")
    if body is None:
        return txt(root)[:max_chars]
    secs = body.findall("sec")  # 直下のセクションのみ(入れ子の二重取り防止)
    picked = []
    for sec in secs:
        title = (sec.findtext("title") or "").lower()
        if re.search(r"method|material|patients|design|result|outcome|analysis", title):
            picked.append(txt(sec))
    abstract = root.find(".//abstract")
    out = (txt(abstract) + "\n\n" if abstract is not None else "") + ("\n\n".join(picked) if picked else txt(body))
    return out[:max_chars]


def fetch_fulltext(pmid):
    """Europe PMC: OA全文 → 無ければ PubMed抄録。(text, kind) を返す"""
    q = urllib.parse.quote(f"EXT_ID:{pmid} AND SRC:MED")
    try:
        meta = json.loads(_get(f"https://www.ebi.ac.uk/europepmc/webservices/rest/search?query={q}&format=json&resultType=core"))
        hits = meta.get("resultList", {}).get("result", [])
    except Exception as e:  # noqa: BLE001
        hits = []
    if hits:
        h = hits[0]
        pmcid = h.get("pmcid")
        if pmcid and str(h.get("isOpenAccess", "N")).upper() == "Y":
            try:
                xml_text = _get(f"https://www.ebi.ac.uk/europepmc/webservices/rest/{pmcid}/fullTextXML")
                t = europepmc_fulltext_xml_to_text(xml_text)
                if len(t) > 500:
                    return t, "oa_fulltext"
            except Exception:  # noqa: BLE001
                pass
        abst = h.get("abstractText")
        if abst:
            title = h.get("title", "")
            return f"{title}\n\n{abst}", "abstract"
    # 最後の手段: PubMed efetch の抄録
    try:
        xml_text = _get(f"https://eutils.ncbi.nlm.nih.gov/entrez/eutils/efetch.fcgi?db=pubmed&id={pmid}&retmode=xml")
        root = ET.fromstring(xml_text)
        title = root.findtext(".//ArticleTitle") or ""
        abst = " ".join(t.text or "" for t in root.findall(".//AbstractText"))
        if abst:
            return f"{title}\n\n{abst}", "abstract"
    except Exception:  # noqa: BLE001
        pass
    return "", "none"


def get_text_for(pmid, papers_dir, no_fetch):
    """PDF → キャッシュ → ネット取得 の順。(text, kind)"""
    pdf = os.path.join(papers_dir, f"{pmid}.pdf")
    if os.path.exists(pdf):
        return pdf_text(pdf), "pdf"
    cache = os.path.join(papers_dir, f"{pmid}.txt")
    if os.path.exists(cache):
        raw = open(cache, encoding="utf-8").read()
        kind = raw.split("\n", 1)[0].replace("#kind:", "").strip() if raw.startswith("#kind:") else "oa_fulltext"
        return raw.split("\n", 1)[1] if "\n" in raw else "", kind
    if no_fetch:
        return "", "none"
    text, kind = fetch_fulltext(pmid)
    if text:
        os.makedirs(papers_dir, exist_ok=True)
        with open(cache, "w", encoding="utf-8") as f:
            f.write(f"#kind:{kind}\n{text}")
    return text, kind


# ------------------------------------------------------------------
# Bedrock
# ------------------------------------------------------------------
def call_bedrock(system, prompt, model_id):
    import boto3  # 実行はMac側
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


def extract_one(text, kind, cq_title, intervention, outcomes, model_id, dry_run):
    if dry_run or not text:
        lines = [ln.strip() for ln in text.splitlines() if ln.strip()]
        title = (next((ln for ln in lines if len(ln) > 25), None) or (max(lines, key=len) if lines else ""))[:120]
        return {"pmid": None, "design": "要確認" if text else None, "comparator": None, "outcome_id": None,
                "instrument": None, "eligible": None,
                "rob2": {k: "要確認" for k in DOMAIN_KEYS} if text else None,
                "rob2_rationale": {"note": (f"dry-run: {KIND_JA.get(kind, kind)} {len(text)}文字。Bedrock未呼び出し"
                                            if text else "本文が取得できません。papers/<PMID>.pdf を置いてください")},
                "effect": None,
                "citation": {"first_author": None, "year": None, "title": title, "journal": None},
                "n_total": None}
    prompt = PROMPT.format(cq_title=cq_title, intervention=intervention,
                           outcomes=json.dumps(outcomes, ensure_ascii=False),
                           kind=KIND_JA.get(kind, kind), text=text)
    return call_bedrock(SYSTEM, prompt, model_id)


# ------------------------------------------------------------------
# シートへの書き込み
# ------------------------------------------------------------------
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


def write_row(ws, r, res, kind, overwrite):
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
    put(ROB2_COL["instrument"], res.get("instrument"))
    if res.get("eligible") is not None:
        put(ROB2_COL["eligible"], "Y" if res["eligible"] else "N")
    rob = res.get("rob2") or {}
    for k in DOMAIN_KEYS:
        put(ROB2_COL[k], rob.get(k))
    if overwrite:
        rat = res.get("rob2_rationale") or {}
        eff = res.get("effect") or {}
        parts = [f"本文: {KIND_JA.get(kind, kind)}"]
        if eff and eff.get("measure"):
            parts.append(f"効果: {eff.get('measure')} {eff.get('point')} ({eff.get('ci_low')}–{eff.get('ci_high')})")
        if rat:
            parts.append("RoB2根拠: " + "; ".join(f"{k}:{v}" for k, v in rat.items() if v))
        ws.cell(row=r, column=ROB2_COL["note"]).value = " / ".join(parts)[:1000]


def _first_free_row(ws):
    last = 1
    for r in range(2, ws.max_row + 1):
        if ws.cell(row=r, column=1).value:
            last = r
    return last + 1


def _append_new_row(ws, pmid, label):
    r = _first_free_row(ws)
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
            return
    r = 2
    while r <= ws.max_row and (ws.cell(row=r, column=1).value or ws.cell(row=r, column=2).value):
        if str(ws.cell(row=r, column=1).value or "").startswith("──"):
            break
        r += 1
    ws.insert_rows(r)
    ws.cell(row=r, column=1).value = pmid
    ws.cell(row=r, column=2).value = f"{label}: {cit.get('title') or ''}"[:200]
    ws.cell(row=r, column=3).value = "papers/ に追加(検索/ハンドサーチ)"


def _update_reference_status(wb, status_by_pmid):
    """文献リストの「papers/収集状況」を本文の入手状況で更新"""
    if "文献リスト" not in wb.sheetnames:
        return
    ws = wb["文献リスト"]
    for r in range(2, ws.max_row + 1):
        pmid = str(ws.cell(row=r, column=2).value or "").strip()
        if pmid in status_by_pmid:
            ws.cell(row=r, column=4).value = KIND_JA.get(status_by_pmid[pmid], status_by_pmid[pmid])


def _all_new_items(wb, draft, status_by_pmid):
    """下書きシートの「新規追加=○」行すべて(過去の実行分も含む)を MANIFEST 用に集める"""
    titles = {}
    if "スクリーニングログ" in wb.sheetnames:
        ws = wb["スクリーニングログ"]
        for r in range(2, ws.max_row + 1):
            k = str(ws.cell(row=r, column=1).value or "").strip()
            if k:
                titles[k] = str(ws.cell(row=r, column=2).value or "")
    items = []
    for r in range(2, draft.max_row + 1):
        key = str(draft.cell(row=r, column=1).value or "").strip()
        if not key or draft.cell(row=r, column=ROB2_COL["newly_added"]).value != "○":
            continue
        label = str(draft.cell(row=r, column=ROB2_COL["cite"]).value or "")
        title = titles.get(key, "")
        title = title.split(": ", 1)[1] if title.startswith(label + ": ") else title
        items.append({"pmid": key if key.isdigit() else None, "stem": key, "label": label,
                      "cit": {"title": title}, "kind": status_by_pmid.get(key, "pdf")})
    return items


def _update_manifest(path, new_items, status_by_pmid):
    if not os.path.exists(path):
        return
    txt = open(path, encoding="utf-8").read()
    # 2023年版の行: "| n | [pmid](...) | ☐ | ..." の ☐ を入手状況に
    def repl(m):
        pmid = m.group(2)
        st = status_by_pmid.get(pmid)
        mark = {"pdf": "☑PDF", "oa_fulltext": "☑全文", "abstract": "△抄録", "none": "☐"}.get(st, "☐")
        return f"| {m.group(1)} | [{pmid}]({m.group(3)}) | {mark} |"
    txt = re.sub(r"\| (\d+) \| \[(\d+)\]\(([^)]+)\) \| [☐☑△][^|]* \|", repl, txt)
    head, _, _ = txt.partition("## 新規追加文献(改訂で追加するもの)")
    rows = ["| # | PMID | 収集 | 文献 |", "|---|---|---|---|"]
    for i, it in enumerate(new_items, start=1):
        pmid = it["pmid"]
        link = f"[{pmid}](https://pubmed.ncbi.nlm.nih.gov/{pmid}/)" if pmid else it["stem"]
        cit = it["cit"] or {}
        desc = " ".join(x for x in [it["label"], cit.get("title") or "", cit.get("journal") or ""] if x)[:200]
        mark = {"pdf": "☑PDF", "oa_fulltext": "☑全文", "abstract": "△抄録"}.get(it.get("kind", "pdf"), "☑PDF")
        rows.append(f"| {i} | {link} | {mark} | {desc} |")
    if not new_items:
        rows.append("|  |  | ☐ |  |")
    new = (head + "## 新規追加文献(改訂で追加するもの)\n\n"
           "papers/ に置かれたPDFのうち2023年版に無いもの(fill_rob2_from_papers.py が自動更新)\n\n"
           + "\n".join(rows) + "\n\n凡例: ☑全文=オープンアクセス全文を取得 / ☑PDF=papers/にPDFあり / △抄録=抄録のみ(有料誌。PDFを置いてください) / ☐=未取得\n")
    open(path, "w", encoding="utf-8").write(new)


# ------------------------------------------------------------------
def process_cq(cq_dir, model_id, dry_run, no_fetch):
    xlsx = os.path.join(cq_dir, "minds_review.xlsx")
    pkg_path = os.path.join(cq_dir, "cq_package.json")
    papers = os.path.join(cq_dir, "papers")
    if not os.path.exists(xlsx):
        return None
    pkg = json.load(open(pkg_path, encoding="utf-8")) if os.path.exists(pkg_path) else {}
    outcomes = [{"id": o["id"], "label": o["label"]} for o in pkg.get("outcomes", [])]
    cq_title, interv = pkg.get("title", ""), pkg.get("_source", {}).get("intervention", "")
    wb = load_workbook(xlsx)
    draft, reviewers = rob2_sheets(wb)
    if draft is None:
        print(f"  [skip] {cq_dir}: RoB2_Claude下書き シートがありません(prepare_review_workspace.py を再実行)")
        return None
    idx = row_index_by_pmid(draft)
    status, new_items = {}, []

    # 1) 新規PDF(2023年版に無いPMID/名前) を登録
    for pdf in sorted(glob.glob(os.path.join(papers, "*.pdf"))):
        stem = os.path.splitext(os.path.basename(pdf))[0]
        if stem in idx:
            continue
        text = pdf_text(pdf)
        res = extract_one(text, "pdf", cq_title, interv, outcomes, model_id, dry_run)
        pmid = stem if stem.isdigit() else (str(res.get("pmid")) if res.get("pmid") else None)
        cit = res.get("citation") or {}
        label = (f"{cit.get('first_author')} et al. {cit.get('year')}".strip()
                 if cit.get("first_author") else f"(新規) {stem}")
        key = pmid or stem
        r = _append_new_row(draft, key, label)
        for ws in reviewers:
            _append_new_row(ws, key, label)
        _append_screening(wb, key, label, cit)
        write_row(draft, r, res, "pdf", overwrite=True)
        if not dry_run:
            for ws in reviewers:
                rr = row_index_by_pmid(ws).get(key)
                if rr:
                    write_row(ws, rr, res, "pdf", overwrite=False)
        idx[key] = r
        status[key] = "pdf"
        new_items.append({"pmid": pmid, "stem": stem, "label": label, "cit": cit})
        print(f"    [新規] {os.path.basename(pdf)} → {label}")

    # 2) 既存行(2023年版採用)を本文から埋める
    n_done = 0
    for pmid, r in list(idx.items()):
        if pmid in status:
            continue
        if not pmid.isdigit():
            continue
        text, kind = get_text_for(pmid, papers, no_fetch)
        if kind == "none":
            # 本文が無い: 前回の下書き/入手状況は触らない(備考が空なら案内だけ書く)
            note = draft.cell(row=r, column=ROB2_COL["note"])
            if not note.value:
                note.value = "本文が取得できません。papers/<PMID>.pdf を置いてください"
                status[pmid] = kind
            continue
        status[pmid] = kind
        if dry_run and draft.cell(row=r, column=ROB2_COL["design"]).value:
            continue  # sync-only/dry-run では、前回(Bedrock)の下書きを仮値で上書きしない
        res = extract_one(text, kind, cq_title, interv, outcomes, model_id, dry_run)
        write_row(draft, r, res, kind, overwrite=True)
        if not dry_run:  # 評価者シートには本物の抽出結果だけを流す
            for ws in reviewers:
                rr = row_index_by_pmid(ws).get(pmid)
                if rr:
                    write_row(ws, rr, res, kind, overwrite=False)
        n_done += 1
        rob = res.get("rob2") or {}
        print(f"    {pmid} [{KIND_JA.get(kind, kind)}] → {res.get('design')} / overall={rob.get('overall')}")

    _update_reference_status(wb, status)
    wb.save(xlsx)
    _update_manifest(os.path.join(cq_dir, "MANIFEST.md"), _all_new_items(wb, draft, status), status)
    return {"cq": os.path.basename(cq_dir), "rows": n_done, "new": len(new_items),
            "kinds": {k: sum(1 for v in status.values() if v == k) for k in KIND_JA}}


def main():
    ap = argparse.ArgumentParser(description="論文本文(PDF/OA全文/抄録) → RoB2_Claude下書き")
    ap.add_argument("workspace_dir")
    ap.add_argument("--only", help="特定のCQディレクトリ名だけ処理")
    ap.add_argument("--model", default=DEFAULT_MODEL)
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--no-fetch", action="store_true")
    ap.add_argument("--sync-only", action="store_true",
                    help="Bedrockもネット取得もせず、papers/ の新規PDFを登録するだけ")
    args = ap.parse_args()
    dry, nofetch = args.dry_run or args.sync_only, args.no_fetch or args.sync_only

    dirs = sorted(d for d in glob.glob(os.path.join(args.workspace_dir, "*"))
                  if os.path.isdir(d) and not os.path.basename(d).startswith("_"))
    if args.only:
        dirs = [d for d in dirs if os.path.basename(d) == args.only]
    summary = []
    for d in dirs:
        print(f"{os.path.basename(d)}:")
        r = process_cq(d, args.model, dry, nofetch)
        if r:
            summary.append(r)
    if summary:
        tot = {k: sum(r["kinds"].get(k, 0) for r in summary) for k in KIND_JA}
        print(f"\n{len(summary)}CQ / 本文の入手: " + ", ".join(f"{KIND_JA[k]} {v}" for k, v in tot.items() if v))
        need = tot.get("abstract", 0) + tot.get("none", 0)
        if need:
            print(f"→ {need}件は全文が取れていません。文献リスト/MANIFESTで「△抄録」「☐」の論文に papers/<PMID>.pdf を置いてください")
        print("次: merge_rob2_evidence.py → review_bundle.py → render_console.py (run_revision.sh が続けて実行します)")


if __name__ == "__main__":
    main()
