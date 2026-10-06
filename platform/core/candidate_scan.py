"""新規介入の「候補」を、文献の件数で裏づける(PubMed E-utilities。要ネットワーク)

  python3 platform/core/candidate_scan.py -o candidate_scan [--since 2021/07/01] [--terms 追加の語.txt]

介入ごとに、CIPN を対象とした論文を数える:
  RCT(無作為化比較試験) / 系統的レビュー・メタ解析 / そのうち --since 以降の新しい RCT
出力: candidate_scan.csv(件数表)、candidate_scan.md(RCT一覧: PMID・年・題名)
注意: 件数は「質の高いRCT」の数ではない。質は、SR委員が 4-5 様式で評価して初めて決まる。
      「RCT(全件)」は、研究計画書、共投薬としてのみ言及する試験、CIPNが副次評価項目の試験も含む上限値。
      「厳密」は、介入語とneuropathy等が題名にあり、protocolを除いたもの。予防と治療は区別されない。
      最終的な件数は、一覧の題名と抄録を読むスクリーニングで確定する。
      Scope 7.2 の基準(メタ解析+RCTが計3件以上で表を作る)を、CQ化の目安として「3件以上」に使う。
"""
import argparse
import csv
import json
import os
import time
import urllib.parse
import urllib.request

BASE = ('("chemotherapy-induced peripheral neuropathy"[tiab] OR CIPN[tiab] OR (neuropath*[tiab] AND '
        '(chemotherap*[tiab] OR oxaliplatin[tiab] OR paclitaxel[tiab] OR docetaxel[tiab] OR cisplatin[tiab] OR bortezomib[tiab] OR vincristine[tiab] OR taxane*[tiab])))')
RCT = '"randomized controlled trial"[pt]'
# 「CIPNが主題」の近似: 題名に neuropathy/CIPN/neurotoxicity を含み、研究計画書(protocol)を除く。
# [pt]=RCT の全件数は、CIPNが副次評価項目や背景にすぎない試験も含むため、上限値でしかない
TITLE_N = '(neuropath*[ti] OR CIPN[ti] OR neurotoxic*[ti])'
RCT_TITLE = f'{RCT} AND {TITLE_N} NOT protocol[ti]'
SR = '("meta-analysis"[pt] OR "systematic review"[pt])'
# (区分, 名称, PubMed検索語)  区分: 既存CQ(基準として) / 調査対象
TERMS = [
    ("既存CQ(基準)", "デュロキセチン", '(duloxetine[tiab])'),
    ("既存CQ(基準)", "冷却療法", '(cryotherapy[tiab] OR "cold therapy"[tiab] OR "frozen glove*"[tiab] OR hypothermia[tiab])'),
    ("既存CQ(基準)", "運動", '(exercise[tiab] OR "exercise therapy"[mesh])'),
    ("既存CQ(基準)", "鍼", '(acupuncture[tiab] OR electroacupuncture[tiab] OR "acupuncture therapy"[mesh])'),
    ("調査対象", "光生体調節・低出力レーザー", '(photobiomodulation[tiab] OR "low level laser*"[tiab] OR "low-level laser*"[tiab] OR "laser therapy, low-level"[mesh])'),
    ("調査対象", "経皮的電気刺激(TENS等)", '("transcutaneous electrical nerve stimulation"[tiab] OR TENS[tiab] OR "electrical stimulation"[tiab] OR "neuromuscular electrical stimulation"[tiab])'),
    ("調査対象", "スクランブラー療法", '("scrambler therapy"[tiab] OR "calmare"[tiab])'),
    ("調査対象", "外用薬(バクロフェン・アミトリプチリン・ケタミン等)", '(topical[tiab] OR gel[tiab] OR cream[tiab] OR patch[tiab] OR capsaicin[tiab] OR lidocaine[tiab] OR menthol[tiab])'),
    ("調査対象", "カンナビノイド", '(cannabi*[tiab] OR nabiximols[tiab])'),
    ("調査対象", "ビタミンE・αリポ酸・グルタチオン等の抗酸化", '("vitamin E"[tiab] OR "alpha-lipoic acid"[tiab] OR glutathione[tiab] OR "N-acetylcysteine"[tiab])'),
    ("調査対象", "カルシウム・マグネシウム", '(calcium[tiab] AND magnesium[tiab])'),
    ("調査対象", "ベンラファキシン", '(venlafaxine[tiab])'),
    ("調査対象", "メトホルミン・ミノサイクリン", '(metformin[tiab] OR minocycline[tiab])'),
    ("調査対象", "マッサージ・ヨガ・認知行動療法", '(massage[tiab] OR yoga[tiab] OR "cognitive behavio*"[tiab] OR "mindfulness"[tiab])'),
    ("調査対象", "他の漢方(芍薬甘草湯・桂枝加朮附湯など)", '(kampo[tiab] OR "shakuyaku-kanzo-to"[tiab] OR "keishikajutsubuto"[tiab] OR "traditional chinese medicine"[tiab] OR "herbal"[tiab])'),
]
API = "https://eutils.ncbi.nlm.nih.gov/entrez/eutils/"
KEY = os.environ.get("NCBI_API_KEY")


def call(endpoint, **params):
    params.update({"retmode": "json", "tool": "cipn-guideline-revision", "email": os.environ.get("NCBI_EMAIL", "")})
    if KEY:
        params["api_key"] = KEY
    url = API + endpoint + "?" + urllib.parse.urlencode(params)
    for attempt in range(4):
        try:
            with urllib.request.urlopen(url, timeout=40) as r:
                data = json.loads(r.read().decode())
            time.sleep(0.12 if KEY else 0.4)
            return data
        except Exception:
            time.sleep(2 ** attempt)
    raise RuntimeError("PubMedに接続できません: " + url[:100])


def search(term, retmax=0, since=None):
    q = term + (f' AND ("{since}"[dp] : "3000"[dp])' if since else "")
    d = call("esearch.fcgi", db="pubmed", term=q, retmax=retmax)["esearchresult"]
    return int(d["count"]), d.get("idlist", [])


def summaries(ids):
    out = []
    for i in range(0, len(ids), 100):
        d = call("esummary.fcgi", db="pubmed", id=",".join(ids[i:i + 100]))["result"]
        for u in d.get("uids", []):
            r = d[u]
            out.append((u, (r.get("pubdate") or "")[:4], r.get("title", ""), r.get("source", "")))
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("-o", "--out", default="candidate_scan")
    ap.add_argument("--since", default="2021/07/01", help="新しいRCTを数える起点(前回の検索終了日)")
    ap.add_argument("--terms", help="追加の調査対象(1行=『名称<TAB>PubMed検索語』)")
    a = ap.parse_args()
    terms = list(TERMS)
    if a.terms:
        for line in open(a.terms, encoding="utf-8"):
            if "\t" in line:
                n, q = line.rstrip("\n").split("\t", 1)
                terms.append(("調査対象", n, q))
    rows, md = [], ["# 新規介入の件数調査(PubMed)", "", f"対象: CIPN。新しいRCTの起点: {a.since}。", ""]
    for kind, name, q in terms:
        t = f"{BASE} AND {q}"
        n_all, _ = search(t)
        n_rct, _ = search(f"{t} AND {RCT}")
        n_sr, _ = search(f"{t} AND {SR}")
        n_new, _ = search(f"{t} AND {RCT}", since=a.since)
        # 厳密: 介入語も題名に含む(共投薬・背景に出てくるだけの論文を除く)
        ts = f"{BASE} AND {q.replace('[tiab]', '[ti]')} AND {RCT_TITLE}"
        n_rt, _ = search(ts)
        n_nt, ids = search(ts, retmax=200, since=a.since)
        rows.append([kind, name, n_all, n_rct, n_sr, n_new, n_rt, n_nt])
        print(f"{name:<36} 全{n_all:4d} RCT{n_rct:3d}(厳密:{n_rt:3d}) SR/MA{n_sr:3d} 新RCT{n_new:3d}(厳密:{n_nt:3d})")
        md += [f"## {name}（{kind}）", f"全{n_all}件 / RCT {n_rct}件(題名に介入語とneuropathy等 {n_rt}件) / SR・メタ解析 {n_sr}件 / {a.since}以降のRCT {n_new}件(題名に介入語とneuropathy等 {n_nt}件)", "",
               f"{a.since}以降・題名に介入語とneuropathy等を含むRCT(厳密。予防と治療が混在。内容は未確認):", ""]
        for u, y, title, src in sorted(summaries(ids), key=lambda x: x[1], reverse=True):
            md.append(f"- {y} [{u}](https://pubmed.ncbi.nlm.nih.gov/{u}/) {title} ({src})")
        md.append("")
    os.makedirs(os.path.dirname(os.path.abspath(a.out)), exist_ok=True)   # 出力先のフォルダが無くても作る
    with open(a.out + ".csv", "w", newline="", encoding="utf-8-sig") as f:
        w = csv.writer(f)
        w.writerow(["区分", "介入", "CIPN関連の全論文", "RCT(全件・上限値)", "SR・メタ解析", f"{a.since}以降のRCT(全件)", "RCT(厳密: 題名に介入語とneuropathy等)", f"{a.since}以降(厳密)"])
        w.writerows(rows)
    open(a.out + ".md", "w", encoding="utf-8").write("\n".join(md) + "\n")
    print(f"\n→ {a.out}.csv / {a.out}.md")


if __name__ == "__main__":
    main()
