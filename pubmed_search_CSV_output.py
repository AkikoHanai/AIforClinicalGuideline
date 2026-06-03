import requests
import pandas as pd
import xml.etree.ElementTree as ET
import time

# #15相当のベース検索式（最新日付対応）
BASE_QUERY = '("Neoplasms"[Mesh] OR "Cancer"[TIAB] OR "Tumor"[TIAB]) AND ("Exercise"[Mesh] OR "Exercise therapy"[Mesh]) AND ("Survivor"[Mesh] OR "surviv*"[TIAB]) AND (randomized controlled trial[pt] OR controlled clinical trial[pt] OR randomized[tiab] OR placebo[tiab] OR drug therapy[sh] OR randomly[tiab] OR trial[tiab] OR groups[tiab] NOT (animals [mh] NOT humans [mh])) AND (1966:2026/05/31[EDAT]) AND (English[LA] OR Japanese[LA])'

# MeSHタームによる年齢層定義
AGE_FILTERS = {
    "under_18": '"infant"[MeSH Terms] OR "child"[MeSH Terms] OR "adolescent"[MeSH Terms]',
    "18_64": '"adult"[MeSH Terms] OR "middle aged"[MeSH Terms]',
    "over_65": '"aged"[MeSH Terms]'
}

def fetch_literature_to_csv(base_query, age_filters):
    base_url_search = "https://eutils.ncbi.nlm.nih.gov/entrez/eutils/esearch.fcgi"
    base_url_fetch = "https://eutils.ncbi.nlm.nih.gov/entrez/eutils/efetch.fcgi"
    
    for age_group, age_query in age_filters.items():
        full_query = f"({base_query}) AND ({age_query})"
        
        # 1. usehistory=y でPubMedサーバー上に検索結果をキャッシュ
        search_params = {
            "db": "pubmed",
            "term": full_query,
            "retmode": "json",
            "usehistory": "y"
        }
        search_res = requests.get(base_url_search, params=search_params).json()
        count = int(search_res["esearchresult"]["count"])
        
        if count == 0:
            print(f"[{age_group}] ヒット数0件のためスキップ")
            continue
            
        webenv = search_res["esearchresult"]["webenv"]
        query_key = search_res["esearchresult"]["querykey"]
        
        # 2. efetchで文献詳細（抄録含む）をXML取得（Rayyan/Covidenceインポート用）
        # ※件数が多い場合は retstart/retmax によるページネーションが必要
        fetch_params = {
            "db": "pubmed",
            "query_key": query_key,
            "WebEnv": webenv,
            "retmode": "xml",
            "retmax": 5000 
        }
        fetch_res = requests.get(base_url_fetch, params=fetch_params)
        root = ET.fromstring(fetch_res.content)
        
        records = []
        for article in root.findall('.//PubmedArticle'):
            pmid = article.findtext('.//PMID')
            title = article.findtext('.//ArticleTitle')
            # 抄録は複数タグに分割されている場合があるため結合
            abstract = " ".join([text.text for text in article.findall('.//AbstractText') if text.text])
            journal = article.findtext('.//Title')
            year = article.findtext('.//PubDate/Year')
            doi = article.findtext('.//ArticleIdList/ArticleId[@IdType="doi"]', default="")
            
            authors = []
            for author in article.findall('.//Author'):
                last_name = author.findtext('LastName')
                initials = author.findtext('Initials')
                if last_name and initials:
                    authors.append(f"{last_name} {initials}")
                elif last_name:
                    authors.append(last_name)
            author_str = ", ".join(authors)
            
            records.append({
                "PMID": pmid,
                "DOI": doi,
                "Authors": author_str,
                "Title": title,
                "Year": year,
                "Journal": journal,
                "URL": f"https://pubmed.ncbi.nlm.nih.gov/{pmid}/" if pmid else "",
                "Abstract": abstract
            })
        
        # 3. 文字化け防止（utf-8-sig）でCSV出力
        df = pd.DataFrame(records)
        filename = f"screening_{age_group}.csv"
        df.to_csv(filename, index=False, encoding="utf-8-sig")
        print(f"[{age_group}] 出力完了: {count}件 -> {filename}")
        
        time.sleep(1) # レート制限回避

if __name__ == "__main__":
    fetch_literature_to_csv(BASE_QUERY, AGE_FILTERS)