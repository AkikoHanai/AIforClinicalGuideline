import pandas as pd
import requests
import re
import time
from datetime import datetime

def build_pubmed_query(queries, index):
    raw_query = str(queries[index])
    if pd.isna(raw_query) or raw_query.strip() == "nan":
        return ""
    
    # 構文エラーの原因となる全角スペース・不要な空白を除去
    raw_query = raw_query.replace('　', ' ').strip()
    
    # 「18歳以下」の行を #15 に対する小児フィルタとして動的定義
    if "18歳以下" in raw_query:
        raw_query = '#15 AND ("infant"[MeSH Terms] OR "child"[MeSH Terms] OR "adolescent"[MeSH Terms])'
    
    # 年齢フィルタの置換
    if "Filters: Adult: 19-44 years; Middle Aged: 45-64 years" in raw_query:
        raw_query = raw_query.replace("Filters: Adult: 19-44 years; Middle Aged: 45-64 years", '("adult"[MeSH Terms] OR "middle aged"[MeSH Terms])')
    if "Filters: Aged: 65+ years" in raw_query:
        raw_query = raw_query.replace("Filters: Aged: 65+ years", '"aged"[MeSH Terms]')

    # 検索期間の現在日付への更新
    current_date = datetime.now().strftime("%Y/%m/%d")
    raw_query = re.sub(r'\d{4}:\d{4}/\d{1,2}/\d{1,2}\[EDAT\]', f'1966:{current_date}[EDAT]', raw_query)

    # 参照タグ (#番号) の再帰的展開
    def replacer(match):
        ref_id = int(match.group(1))
        resolved = build_pubmed_query(queries, ref_id)
        return f"({resolved})"

    return re.sub(r'#(\d+)', replacer, raw_query)

def execute_pubmed_update(filepath="CSGL身体活動検索結果.xlsx"):
    df = pd.read_excel(filepath, sheet_name='Sheet2')
    queries = df['Unnamed: 1'].tolist()
    
    current_date = datetime.now().strftime("%Y/%m/%d")
    new_queries = []
    updated_counts = []
    
    base_url = "https://eutils.ncbi.nlm.nih.gov/entrez/eutils/esearch.fcgi"
    
    for i, row in df.iterrows():
        query_str = row['Unnamed: 1']
        
        # 処理スキップ条件から「18歳以下」を除外し、検索可能とする
        if pd.isna(query_str) or query_str == "検索式":
            new_queries.append(None)
            updated_counts.append(None)
            continue
            
        full_query = build_pubmed_query(queries, i)
        
        # セルへの出力用文字列の整形
        if "18歳以下" in str(query_str):
            display_query = '#15 AND Filters: Child: birth-18 years'
        else:
            display_query = re.sub(r'\d{4}:\d{4}/\d{1,2}/\d{1,2}\[EDAT\]', f'1966:{current_date}[EDAT]', str(query_str))
            
        new_queries.append(display_query)
        
        try:
            params = {
                "db": "pubmed",
                "term": full_query,
                "retmode": "json",
                "rettype": "count"
            }
            res = requests.get(base_url, params=params, timeout=10)
            res.raise_for_status()
            updated_counts.append(int(res.json()["esearchresult"]["count"]))
            time.sleep(0.34) # 3 requests/sec のレート制限を遵守
        except Exception as e:
            updated_counts.append(None)
    
    df['Unnamed: 6'] = new_queries
    df['Unnamed: 7'] = updated_counts
    
    # 増加数の比較対象を「Unnamed: 4（E列）」から「Unnamed: 2（C列・オリジナル文献数）」へ変更
    df['Unnamed: 8'] = df['Unnamed: 7'] - pd.to_numeric(df['Unnamed: 2'], errors='coerce')
    
    output_name = f"CSGL身体活動検索結果_{datetime.now().strftime('%Y%m%d')}_Updated.xlsx"
    df.to_excel(output_name, index=False)

if __name__ == "__main__":
    execute_pubmed_update()