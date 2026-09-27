"""
エッジ抽出器 — 人手注釈コストを下げる
=====================================
グラフの実務的な障壁は「エッジは誰が入力するのか」です。
17ユニット × 数十論文に手作業で関係を張るのは現実的ではありません。

そこで機械抽出できるエッジと人手が要るエッジを分離します。

機械抽出できる(このモジュール):
  REPORTS         PubMed の secondary source ID(NCT/UMIN/jRCT/ISRCTN)から
  SAME_TRIAL_AS   同一Trialを REPORTS する Study から導出(グラフ側で自動)
  RETRACTS        publication type と retraction 関連フィールドから
  INCLUDES        メタ解析の参考文献リストから(要 full text または手動補完)

人手が要る(二次スクリーニング時に入力):
  COMPARES_AGAINST  対照の種類。ここを機械化すると冷却の件のような取り違えが起きる
  ELIGIBLE_FOR      適格基準の判定
  MEASURES          報告アウトカム(概念解決で半自動化可)

試験登録番号による同定が決定的に効きます。CIPN領域の国内試験は
UMIN-CTR / jRCT に登録されているため、同一試験の重複報告を
ほぼ自動で検出できます。
"""
import json
import os
import re
import time
import urllib.parse
import urllib.request

EUTILS_BASE = "https://eutils.ncbi.nlm.nih.gov/entrez/eutils"
NCBI_API_KEY = os.environ.get("NCBI_API_KEY", "")

# 試験登録番号のパターン(主要レジストリ)
REGISTRY_PATTERNS = {
    "ClinicalTrials.gov": re.compile(r"\bNCT\d{8}\b"),
    "UMIN-CTR": re.compile(r"\bUMIN\d{9}\b|\bUMIN-?CTR\s*:?\s*C?\d{9}\b", re.I),
    "jRCT": re.compile(r"\bjRCTs?\d{9,10}\b", re.I),
    "ISRCTN": re.compile(r"\bISRCTN\d{8}\b", re.I),
    "JapicCTI": re.compile(r"\bJapicCTI-\w+\b", re.I),
}

RETRACTION_TYPES = {
    "Retracted Publication",          # 撤回された論文そのもの
    "Retraction of Publication",      # 撤回告知
    "Expression of Concern",          # 懸念表明(撤回ではないが要注意)
}


def _get(path: str, params: dict) -> dict:
    if NCBI_API_KEY:
        params["api_key"] = NCBI_API_KEY
    url = f"{EUTILS_BASE}/{path}?" + urllib.parse.urlencode(params)
    req = urllib.request.Request(url, headers={"User-Agent": "JASCC-CIPN-CPG/2028"})
    with urllib.request.urlopen(req, timeout=30) as r:
        return json.loads(r.read())


def fetch_records(pmids: list) -> dict:
    """esummary で書誌 + publication type + 試験登録番号を取得"""
    out = {}
    for i in range(0, len(pmids), 100):
        chunk = [str(p) for p in pmids[i:i + 100]]
        data = _get("esummary.fcgi", {"db": "pubmed", "id": ",".join(chunk),
                                      "retmode": "json"})
        for pmid in chunk:
            rec = data.get("result", {}).get(pmid)
            if not rec or rec.get("error"):
                continue
            out[pmid] = {
                "pmid": pmid,
                "title": rec.get("title", ""),
                "journal": rec.get("source", ""),
                "pubdate": rec.get("pubdate", ""),
                "pubtypes": rec.get("pubtype", []),
                # 試験登録番号は articleids に入ることがある
                "articleids": [a.get("value", "") for a in rec.get("articleids", [])],
                "raw_text_for_registry": " ".join([
                    rec.get("title", ""),
                    " ".join(a.get("value", "") for a in rec.get("articleids", [])),
                ]),
            }
        time.sleep(0.4 if NCBI_API_KEY else 1.1)
    return out


def extract_registry_ids(record: dict, extra_text: str = "") -> dict:
    """
    書誌から試験登録番号を抽出。
    esummary には secondary source ID が入らない場合があるため、
    抄録テキストを extra_text で渡せるようにしている(efetch 併用時)。
    """
    text = record.get("raw_text_for_registry", "") + " " + (extra_text or "")
    found = {}
    for registry, pat in REGISTRY_PATTERNS.items():
        ids = sorted(set(m.group(0).upper().replace(" ", "").replace("UMIN-CTR:", "UMIN")
                         for m in pat.finditer(text)))
        if ids:
            found[registry] = ids
    return found


def is_retracted(record: dict) -> tuple:
    """(撤回されているか, 該当する publication type)"""
    hits = [t for t in record.get("pubtypes", []) if t in RETRACTION_TYPES]
    retracted = "Retracted Publication" in hits
    return retracted, hits


def is_meta_analysis(record: dict) -> bool:
    return any(t in ("Meta-Analysis", "Systematic Review")
               for t in record.get("pubtypes", []))


# ------------------------------------------------------------------
# グラフへの投入
# ------------------------------------------------------------------
def populate_from_pubmed(graph, pmids: list, abstracts: dict = None) -> dict:
    """
    PubMed から取得できる情報だけでグラフの骨格を作る。
    graph: EvidenceGraph
    abstracts: {pmid: 抄録テキスト} 任意。試験登録番号の検出率が上がる

    返り値: 抽出結果のサマリと、人手入力が必要な項目のリスト
    """
    from evidence_schema import EdgeType, NodeType

    abstracts = abstracts or {}
    records = fetch_records(pmids)
    summary = {"studies": 0, "trials": 0, "reports_edges": 0,
               "retracted": [], "meta_analyses": [], "no_registry": []}

    for pmid, rec in records.items():
        sid = f"S:{pmid}"
        retracted, rtypes = is_retracted(rec)
        graph.add_node(sid, NodeType.STUDY, pmid=pmid, title=rec["title"],
                       journal=rec["journal"], pubdate=rec["pubdate"],
                       pubtypes=rec["pubtypes"], retracted=retracted,
                       design="meta_analysis" if is_meta_analysis(rec) else None)
        summary["studies"] += 1
        if retracted:
            summary["retracted"].append(pmid)
        if is_meta_analysis(rec):
            summary["meta_analyses"].append(pmid)

        regs = extract_registry_ids(rec, abstracts.get(pmid, ""))
        if not regs:
            summary["no_registry"].append(pmid)
        for registry, ids in regs.items():
            for tid in ids:
                node = f"T:{tid}"
                if node not in graph.nodes:
                    graph.add_node(node, NodeType.TRIAL, registry=registry,
                                   registry_id=tid)
                    summary["trials"] += 1
                graph.add_edge(sid, EdgeType.REPORTS, node)
                summary["reports_edges"] += 1

    derived = graph.derive_same_trial()

    return {
        "summary": summary,
        "same_trial_pairs_derived": derived,
        "manual_input_required": [
            f"{len(records)}件すべてに COMPARES_AGAINST(対照の種類)の入力が必要",
            f"{len(records)}件すべてに ELIGIBLE_FOR(適格基準の判定)が必要",
            f"メタ解析{len(summary['meta_analyses'])}件に INCLUDES(採用文献)の入力が必要"
            "(参考文献リストから半自動化可)",
            f"試験登録番号が取れなかった{len(summary['no_registry'])}件は"
            "同一試験判定ができない。全文で確認するか重複の可能性ありとして扱う",
        ],
    }
