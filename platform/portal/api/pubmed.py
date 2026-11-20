"""PubMed(E-utilities)の呼び出し。標準ライブラリだけを使う。ポータルの API(題名・抄録の取得)と、scripts/run_search.py(検索の実行)が使う。"""
import json, re, time, urllib.parse, urllib.request
import xml.etree.ElementTree as ET

BASE = "https://eutils.ncbi.nlm.nih.gov/entrez/eutils/"
ESEARCH_MAX = 9999   # PubMed の esearch は、1つの検索につき先頭の約1万件までしか PMID を返さない


def call(path, params, timeout=60, tries=4, pause=0.4):
    """E-utilities を POST で呼ぶ。失敗したときは、間をあけて繰り返す。"""
    data = urllib.parse.urlencode(params).encode()
    for i in range(tries):
        try:
            time.sleep(pause)
            return urllib.request.urlopen(urllib.request.Request(BASE + path, data=data), timeout=timeout).read()
        except Exception:
            if i == tries - 1: raise
            time.sleep(2 * (i + 1))


def esearch(term, retstart=0, retmax=0):
    """検索を実行する。戻り値: {"count": 件数, "ids": [PMID], "translation": PubMed が解釈した式}"""
    r = json.loads(call("esearch.fcgi", {"db": "pubmed", "term": term, "retmode": "json", "retstart": retstart, "retmax": retmax}))["esearchresult"]
    if r.get("ERROR"): raise RuntimeError(f"PubMed の検索でエラー: {r['ERROR']}")
    return {"count": int(r["count"]), "ids": list(r.get("idlist") or []), "translation": r.get("querytranslation", ""), "warnings": r.get("warninglist") or r.get("errorlist") or {}}


def parse(data):
    """efetch の XML から、PMID ごとの題名・著者・誌名・年・DOI・抄録を取り出す。"""
    root = ET.fromstring(data)
    text = lambda e: re.sub(r"\s+", " ", "".join(e.itertext())).strip() if e is not None else ""
    out = {}
    for a in root.findall(".//PubmedArticle"):
        pmid = text(a.find("./MedlineCitation/PMID")); art = a.find("./MedlineCitation/Article")
        if not pmid or art is None: continue
        au = [(text(x.find("LastName")) + " " + text(x.find("Initials"))).strip() if x.find("LastName") is not None else text(x.find("CollectiveName")) for x in art.findall("./AuthorList/Author")]
        au = [x for x in au if x]
        year = text(art.find("./Journal/JournalIssue/PubDate/Year")) or (re.findall(r"\d{4}", text(art.find("./Journal/JournalIssue/PubDate/MedlineDate"))) or [""])[0]
        ab = " ".join(((x.get("Label") + ": ") if x.get("Label") else "") + text(x) for x in art.findall("./Abstract/AbstractText"))
        doi = next((text(x) for x in a.findall("./PubmedData/ArticleIdList/ArticleId") if x.get("IdType") == "doi"), "")
        out[pmid] = {"title": text(art.find("ArticleTitle")), "authors": ", ".join(au[:3]) + (", et al" if len(au) > 3 else ""), "authors_all": ", ".join(au),
                     "journal": text(art.find("./Journal/ISOAbbreviation")) or text(art.find("./Journal/Title")), "year": year, "doi": doi, "abstract": ab[:6000]}
    for a in root.findall(".//PubmedBookArticle"):   # 書籍の章。題名だけを取る
        pmid = text(a.find("./BookDocument/PMID"))
        if pmid: out[pmid] = {"title": text(a.find("./BookDocument/ArticleTitle")) or text(a.find("./BookDocument/Book/BookTitle")), "authors": "", "authors_all": "", "journal": "(書籍)", "year": text(a.find("./BookDocument/Book/PubDate/Year")), "doi": "", "abstract": ""}
    return out


def fetch(pmids, batch=200):
    """PMID の書誌と抄録を取る。取れなかった PMID は結果に含めない。"""
    out = {}
    for i in range(0, len(pmids), batch):
        out.update(parse(call("efetch.fcgi", {"db": "pubmed", "retmode": "xml", "id": ",".join(pmids[i:i + batch])})))
    return out
