"""
sr_search.py — PubMed検索 → CSV出力（汎用版）

Usage:
    python sr_search.py --query '("Cancer"[Mesh] AND "Exercise"[Mesh])' \
        --output-dir ./output/my_sr \
        [--age-filter]  # 年齢層別フィルタを有効化
"""

import argparse
import os
import time
import xml.etree.ElementTree as ET

import pandas as pd
import requests

BASE_URL_SEARCH = "https://eutils.ncbi.nlm.nih.gov/entrez/eutils/esearch.fcgi"
BASE_URL_FETCH = "https://eutils.ncbi.nlm.nih.gov/entrez/eutils/efetch.fcgi"
RETMAX_PER_PAGE = 10000

AGE_FILTERS = {
    "under_18": '"infant"[MeSH Terms] OR "child"[MeSH Terms] OR "adolescent"[MeSH Terms]',
    "18_64": '"adult"[MeSH Terms] OR "middle aged"[MeSH Terms]',
    "over_65": '"aged"[MeSH Terms]',
}


def search_pubmed(query: str) -> tuple[str, str, int]:
    """サーバー側にキャッシュしてWebEnv/QueryKeyを返す。"""
    params = {
        "db": "pubmed",
        "term": query,
        "retmode": "json",
        "usehistory": "y",
    }
    res = requests.get(BASE_URL_SEARCH, params=params, timeout=30)
    res.raise_for_status()
    result = res.json()["esearchresult"]
    return result["webenv"], result["querykey"], int(result["count"])


def fetch_records(webenv: str, query_key: str, count: int) -> list[dict]:
    """ページネーションで全件取得。"""
    records = []
    for start in range(0, count, RETMAX_PER_PAGE):
        params = {
            "db": "pubmed",
            "query_key": query_key,
            "WebEnv": webenv,
            "retmode": "xml",
            "retstart": start,
            "retmax": RETMAX_PER_PAGE,
        }
        res = requests.get(BASE_URL_FETCH, params=params, timeout=60)
        res.raise_for_status()
        root = ET.fromstring(res.content)

        for article in root.findall(".//PubmedArticle"):
            pmid = article.findtext(".//PMID")
            title = article.findtext(".//ArticleTitle") or ""
            abstract = " ".join(
                t.text for t in article.findall(".//AbstractText") if t.text
            )
            journal = article.findtext(".//Title") or ""
            year = article.findtext(".//PubDate/Year") or ""
            doi = article.findtext('.//ArticleIdList/ArticleId[@IdType="doi"]') or ""
            authors = []
            for author in article.findall(".//Author"):
                last = author.findtext("LastName")
                initials = author.findtext("Initials")
                if last:
                    authors.append(f"{last} {initials}" if initials else last)
            records.append(
                {
                    "PMID": pmid,
                    "DOI": doi,
                    "Authors": ", ".join(authors),
                    "Title": title,
                    "Year": year,
                    "Journal": journal,
                    "URL": f"https://pubmed.ncbi.nlm.nih.gov/{pmid}/" if pmid else "",
                    "Abstract": abstract,
                }
            )
        time.sleep(0.5)
    return records


def run_search(base_query: str, output_dir: str, age_filter: bool = False):
    os.makedirs(output_dir, exist_ok=True)

    if age_filter:
        groups = AGE_FILTERS
    else:
        groups = {"all": ""}

    all_dfs = []
    for group_name, age_query in groups.items():
        query = f"({base_query}) AND ({age_query})" if age_query else base_query
        print(f"[検索中] グループ: {group_name}")
        webenv, query_key, count = search_pubmed(query)
        print(f"  ヒット数: {count}件")

        if count == 0:
            continue

        records = fetch_records(webenv, query_key, count)
        df = pd.DataFrame(records)
        df["age_group"] = group_name

        out_path = os.path.join(output_dir, f"search_{group_name}.csv")
        df.to_csv(out_path, index=False, encoding="utf-8-sig")
        print(f"  出力: {out_path}")
        all_dfs.append(df)

    if all_dfs:
        combined = pd.concat(all_dfs).drop_duplicates(subset="PMID")
        combined_path = os.path.join(output_dir, "search_all.csv")
        combined.to_csv(combined_path, index=False, encoding="utf-8-sig")
        print(f"\n[統合] 重複除去後 {len(combined)}件 -> {combined_path}")
        return combined_path
    return None


def main():
    parser = argparse.ArgumentParser(description="PubMed検索 → CSV出力")
    parser.add_argument("--query", required=True, help="PubMed検索式")
    parser.add_argument("--output-dir", default="./sr_output", help="出力ディレクトリ")
    parser.add_argument("--age-filter", action="store_true", help="年齢層別フィルタを有効化")
    args = parser.parse_args()

    run_search(args.query, args.output_dir, args.age_filter)


if __name__ == "__main__":
    main()
