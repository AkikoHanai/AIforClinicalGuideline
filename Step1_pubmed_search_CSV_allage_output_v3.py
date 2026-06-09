import requests
import pandas as pd
import xml.etree.ElementTree as ET
import time

# age filterなし
BASE_QUERY = '("Neoplasms"[Mesh] OR cancer[TIAB] OR tumor[TIAB] OR neoplasm*[TIAB]) AND ("Exercise"[Mesh] OR "Exercise Therapy"[Mesh] OR exercise[TIAB] OR "physical activity"[TIAB] OR prehabilitation[TIAB]) AND (("Patient"[Mesh] OR patient*[TIAB]) OR ("Survivor"[Mesh] OR surviv*[TIAB])) AND (randomized controlled trial[pt] OR controlled clinical trial[pt] OR randomized[TIAB] OR randomised[TIAB] OR randomly[TIAB] OR trial[TIAB]) NOT (animals[mh] NOT humans[mh]) AND (1966:2026/05/31[EDAT]) AND (English[LA] OR Japanese[LA])'

def get_mesh_terms(article):
    """MeSH termsをリストで取得"""
    mesh_terms = []
    for mesh in article.findall('.//MeshHeading/DescriptorName'):
        if mesh.text:
            mesh_terms.append(mesh.text)
    return mesh_terms


def extract_sex(mesh_terms, abstract):
    """性別をMeSH優先で抽出"""
    mesh_lower = [m.lower() for m in mesh_terms]
    text = str(abstract).lower()

    has_male = "male" in mesh_lower
    has_female = "female" in mesh_lower

    if has_male and has_female:
        return "Mixed"
    if has_male:
        return "Male"
    if has_female:
        return "Female"

    if "prostate cancer" in text:
        return "Male"
    if "breast cancer" in text or "women" in text or "female" in text:
        return "Female"
    if "men" in text or "male" in text:
        return "Male"

    return "Unknown"


def extract_age_group(mesh_terms):
    """年齢層をMeSHから抽出"""
    age_terms = [
        "Infant",
        "Child",
        "Adolescent",
        "Adult",
        "Young Adult",
        "Middle Aged",
        "Aged",
        "Aged, 80 and over"
    ]

    found = [term for term in age_terms if term in mesh_terms]

    if found:
        return "; ".join(found)

    return "Unknown"


def extract_cancer_type(mesh_terms, title, abstract):
    """がん種をMeSH＋Title＋Abstractから推定"""
    text = (str(title) + " " + str(abstract)).lower()
    mesh_text = " ".join(mesh_terms).lower()

    target_text = mesh_text + " " + text

    cancer_map = {
        "Breast cancer": ["breast neoplasms", "breast cancer"],
        "Prostate cancer": ["prostatic neoplasms", "prostate cancer"],
        "Colorectal cancer": [
            "colorectal neoplasms",
            "colonic neoplasms",
            "rectal neoplasms",
            "colorectal cancer",
            "colon cancer",
            "rectal cancer"
        ],
        "Lung cancer": ["lung neoplasms", "lung cancer"],
        "Hematologic cancer": [
            "leukemia",
            "lymphoma",
            "multiple myeloma",
            "hematologic neoplasms",
            "hematological malignancy"
        ],
        "Gynecologic cancer": [
            "ovarian neoplasms",
            "endometrial neoplasms",
            "uterine cervical neoplasms",
            "ovarian cancer",
            "endometrial cancer",
            "cervical cancer"
        ],
        "Head and neck cancer": [
            "head and neck neoplasms",
            "head and neck cancer"
        ],
        "Gastrointestinal cancer": [
            "stomach neoplasms",
            "gastric cancer",
            "pancreatic neoplasms",
            "pancreatic cancer",
            "esophageal neoplasms",
            "esophageal cancer"
        ]
    }

    found = []
    for cancer_type, keywords in cancer_map.items():
        if any(keyword in target_text for keyword in keywords):
            found.append(cancer_type)

    if found:
        return "; ".join(sorted(set(found)))

    if "neoplasms" in mesh_text or "cancer" in text or "tumor" in text:
        return "Mixed/Other cancer"

    return "Unknown"


def extract_phase(title, abstract):
    """治療フェーズをTitle＋Abstractから推定"""
    text = (str(title) + " " + str(abstract)).lower()

    pre_keywords = [
        "prehabilitation",
        "preoperative",
        "before surgery",
        "before treatment",
        "prior to surgery",
        "prior to treatment"
    ]

    during_keywords = [
        "during chemotherapy",
        "during radiotherapy",
        "during radiation therapy",
        "undergoing chemotherapy",
        "undergoing radiotherapy",
        "receiving chemotherapy",
        "receiving radiotherapy",
        "during treatment",
        "undergoing treatment",
        "active treatment",
        "adjuvant chemotherapy",
        "adjuvant therapy"
    ]

    post_keywords = [
        "after treatment",
        "post-treatment",
        "posttreatment",
        "completed treatment",
        "following treatment",
        "after chemotherapy",
        "after radiotherapy",
        "survivor",
        "survivors",
        "survivorship"
    ]

    if any(k in text for k in pre_keywords):
        return "Pre-treatment"

    if any(k in text for k in during_keywords):
        return "During-treatment"

    if any(k in text for k in post_keywords):
        return "Post-treatment"

    return "Unknown"


def fetch_literature_to_csv(base_query):
    base_url_search = "https://eutils.ncbi.nlm.nih.gov/entrez/eutils/esearch.fcgi"
    base_url_fetch = "https://eutils.ncbi.nlm.nih.gov/entrez/eutils/efetch.fcgi"

    search_params = {
        "db": "pubmed",
        "term": base_query,
        "retmode": "json",
        "usehistory": "y"
    }

    search_res = requests.get(base_url_search, params=search_params).json()
    count = int(search_res["esearchresult"]["count"])

    if count == 0:
        print("ヒット数0件のため終了")
        return

    webenv = search_res["esearchresult"]["webenv"]
    query_key = search_res["esearchresult"]["querykey"]

    records = []

    retmax = 500
    for retstart in range(0, count, retmax):
        fetch_params = {
            "db": "pubmed",
            "query_key": query_key,
            "WebEnv": webenv,
            "retmode": "xml",
            "retstart": retstart,
            "retmax": retmax
        }

        fetch_res = requests.get(base_url_fetch, params=fetch_params)
        root = ET.fromstring(fetch_res.content)

        for article in root.findall('.//PubmedArticle'):
            pmid = article.findtext('.//PMID')
            title = article.findtext('.//ArticleTitle')
            abstract = " ".join([
                text.text for text in article.findall('.//AbstractText')
                if text.text
            ])
            journal = article.findtext('.//Journal/Title')
            year = article.findtext('.//PubDate/Year')
            doi = article.findtext(
                './/ArticleIdList/ArticleId[@IdType="doi"]',
                default=""
            )

            mesh_terms = get_mesh_terms(article)

            authors = []
            for author in article.findall('.//Author'):
                last_name = author.findtext('LastName')
                initials = author.findtext('Initials')
                if last_name and initials:
                    authors.append(f"{last_name} {initials}")
                elif last_name:
                    authors.append(last_name)

            records.append({
                "PMID": pmid,
                "DOI": doi,
                "Authors": ", ".join(authors),
                "Title": title,
                "Year": year,
                "Journal": journal,
                "Sex": extract_sex(mesh_terms, abstract),
                "AgeGroup": extract_age_group(mesh_terms),
                "CancerType": extract_cancer_type(mesh_terms, title, abstract),
                "Phase": extract_phase(title, abstract),
                "MeSH_Terms": "; ".join(mesh_terms),
                "URL": f"https://pubmed.ncbi.nlm.nih.gov/{pmid}/" if pmid else "",
                "Abstract": abstract
            })

        print(f"{min(retstart + retmax, count)} / {count} 件取得完了")
        time.sleep(1)

    df = pd.DataFrame(records)

    df = df.sort_values(
        by=["CancerType", "Phase", "Sex", "AgeGroup", "Year"],
        ascending=True
    )

    filename = "screening_all_ages_with_classificationv2.csv"
    df.to_csv(filename, index=False, encoding="utf-8-sig")

    print(f"出力完了: {len(df)}件 -> {filename}")


if __name__ == "__main__":
    fetch_literature_to_csv(BASE_QUERY)