"""survey/records.json(Methodを読んだ判定)から、介入別の集計表とPMID一覧を作る。
  python3 build_report.py   → out/候補介入_文献調査.xlsx / out/候補介入_文献調査.md
用語は GLOSSARY に定義した語だけを使う。"""
import json, os
from openpyxl import Workbook
from openpyxl.styles import Font, Alignment, Border, Side, PatternFill
from openpyxl.utils import get_column_letter

R = json.load(open("records.json", encoding="utf-8"))
H = json.load(open("rct_hits.json", encoding="utf-8"))
IN2023 = set(H["in_2023_refs"])
G = {k: list(v) for k, v in H["hits"].items()}
G["デュロキセチン"] = "38976095 37774185 36730548 35426033 34738855 42001111 40694173 31925721 31254640 30105459 29680317 28851798 25762165 23549581".split()  # 41630017(セレン)と32493088(電気刺激)は、デュロキセチンが共投薬のため各介入の群へ移した
G["経皮的電気刺激(TENS等)"] += ["32493088"]
G["抗酸化薬(ビタミンE・αリポ酸・グルタチオン・NAC)"] += ["41630017"]

SR = [  # PMID, 年, 第一著者, 種別, 対象
("35461045",2022,"Wang","SR","非侵襲的神経調節(光生体調節・TENS等)"),
("35208610",2022,"Püsküllüoğlu","SR","TENS"),
("41766048",2026,"Aldawahreh","SR","スクランブラー療法(RCTのSR)"),
("35691908",2022,"Karri","SR","スクランブラー療法(慢性疼痛全般。CIPN特異的でない)"),
("32659321",2020,"Cabezón-Gutiérrez","SR","カプサイシン8%パッチ"),
("42085369",2026,"Datta","SR","カンナビノイド(RCTのSR)"),
("36194493",2022,"Chow","SR+MA","デュロキセチン(予防・治療)"),
("42755421",2026,"Caminiti","SR","抗うつ薬"),
("25256375",2014,"Chu","SR","中枢神経作用薬"),
("39952863",2025,"Jesus Palma","SR","薬物治療全般(RCTのSR)"),
("37058254",2023,"D'Souza","SR","疼痛治療"),
("34148036",2021,"Miao","MA","ビタミンE"),
("24491883",2013,"Eum","MA","ビタミンE"),
("34918607",2021,"Retzlaff","SR","ビタミンE(α-トコフェロール)"),
("37231628",2023,"Van de Roovaart","SR","ビタミンB"),
("35819060",2022,"Heilfort","SR","ビタミンB"),
("23647723",2013,"Schloss","SR","栄養補助(ビタミンE・カルニチン・グルタミン・グルタチオン・Ca/Mg・ALA・NAC等)"),
("41482855",2026,"Benna-Doyle","アンブレラレビュー","栄養補助全般(がん支持療法)"),
("37654090",2023,"Frediani","SR","食事・サプリ(慢性神経障害性疼痛全般)"),
("29280005",2017,"Kuriyama","SR+MA","牛車腎気丸(予防)"),
("29270698",2017,"Hoshino","SR+MA","牛車腎気丸(予防)"),
("40703357",2025,"Kim","SR+MA","伝統的漢方薬(予防)"),
("30526124",2018,"Liu","SR+MA","統合漢方(大腸癌のCIPNと手足症候群)"),
("41217297",2025,"Yang","SR","中医学(第3相RCTのSR)"),
("30768427",2019,"Ebrahimi","SR","植物由来薬"),
("26652982",2015,"Brami","SR","天然物・補完療法"),
("41792539",2026,"Chen","SR+MA","徒手的介入(マッサージ等)"),
("39162786",2024,"Khmethong","SR+MA","運動"),
("33710510",2021,"Tanay","SR","行動・運動介入(予防・管理)"),
("38502556",2024,"Ronconi","SR","非薬物療法(乳癌)"),
("38082216",2023,"Zhang","NMA","非薬物療法"),
("42341448",2026,"Kobayashi","SR+NMA","非薬物療法(CIPN関連疼痛)"),
("36593011",2023,"Papadopoulou","SR+MA","非薬物療法(鍼・運動・ヨガ)"),
("29735874",2018,"Oh","SR+MA","非薬物療法(運動・鍼・マッサージ・足浴)"),
("39160496",2024,"Yeh","SR+NMA","鍼関連介入"),
("39900253",2025,"Yeh","アンブレラレビュー","鍼関連介入"),
("37708563",2023,"Zhang","NMA","鍼"),
("35695033",2022,"Pei","SR+MA","鍼・電気鍼"),
("32332632",2020,"Hwang","SR+MA","鍼・電気鍼"),
("37382085",2023,"de Sousa","SR","鍼(化学療法・放射線治療)"),
("30508986",2018,"Hou","SR","CIPN治療全般"),
("36618919",2022,"Wang","SR","CIPN治療(RCTのSR)"),
("35421796",2022,"Wang","SR","CIPN管理"),
]
SR_NOT = [  # 検索にかかったが、介入の評価ではないため集計から除外
("36950556",2023,"Li","書誌計量解析(鍼とがん性疼痛)。介入効果の統合ではない"),
("41815730",2026,"Yan","CIPNの発生率と要因のSR+MA。介入の評価ではない"),
("38837778",2024,"Aruchunan","ヨガと末梢神経障害のナラティブレビュー。CIPN特異的でない"),
("34901069",2021,"Zhang","神経障害性疼痛に対する運動のSRと専門家合意。CIPN特異的でない"),
("28436999",2017,"Greenlee","乳癌の統合医療ガイドライン(SIO)。SRではなくガイドライン"),
("27846661",2016,"Jung","小児に関するSR。成人の該当研究なし"),
]
GROUP_SR = {
 "光生体調節・低出力レーザー":["35461045"],
 "経皮的電気刺激(TENS等)":["35461045","35208610","35695033","32332632","39160496","37708563"],
 "スクランブラー療法":["41766048","35691908","35461045"],
 "外用薬":["32659321","36618919","30508986"],
 "カンナビノイド":["42085369"],
 "抗酸化薬(ビタミンE・αリポ酸・グルタチオン・NAC)":["34148036","24491883","34918607","23647723","41482855","37654090"],
 "カルシウム・マグネシウム":["23647723"],
 "ベンラファキシン":["36194493","42755421","25256375"],
 "メトホルミン・ミノサイクリン":[],
 "マッサージ・ヨガ・認知行動療法・マインドフルネス":["41792539","38082216","42341448","36593011","29735874","38502556"],
 "他の漢方・生薬":["29280005","29270698","40703357","30526124","41217297","30768427","26652982"],
 "デュロキセチン":["36194493","42755421","25256375","39952863"],
}

def purpose(r):
    p=r["purpose"]
    return "予防" if p.startswith("予防") else "治療" if p.startswith("治療") else "対象外" if p.startswith("対象外") else "判定不能"
def dec(r):
    d=r["decision"]
    return "適格" if d.startswith("適格") else "要確認" if d.startswith("要確認") else "不適格"

rows=[]; md=[]; NOJP=set()
GLOSS = """## 用語の定義(この文書で使う語はこれだけ)
- **RCT[pt]**: PubMed の出版タイプ(Publication Type)が Randomized Controlled Trial の論文。計画書、副次解析、単群試験の誤分類を含む。
- **適格RCT**: Method(方法)を読み、次の4条件をすべて満たすと判定した RCT。(1)対象が化学療法を受けた(または受ける)成人のがん患者、(2)比較対照がある、(3)結果が報告されている(計画書でない)、(4)CIPNの発生または症状が主要評価項目、またはCIPNの評価が結果の中心である。国内で実施できない介入(例:国内で処方できない中国の漢方薬)は、(1)〜(4)を満たす場合も「適格(国内未承認)」と付記し、集計表では別に数える。
- **予防**: Method に、化学療法の開始前または開始時に介入を始め、CIPNの発生・重症化を評価する、と書かれている RCT。
- **治療**: Method に、すでにCIPNの症状がある(Grade/NRS等の基準を満たす)患者を対象とする、と書かれている RCT。
- **要確認**: 抄録の Method だけでは4条件の判定ができず、全文が必要な RCT。
- **不適格**: 4条件のいずれかを満たさない RCT。理由を記録する。
- **SR/MA**: 出版タイプが Systematic Review または Meta-Analysis の論文。介入の効果を統合していない論文は集計から除く(理由を記録)。
- **Scope 追加基準**: 同一目的(予防または治療)の適格RCTが3本以上ある介入を、CQ/FRQ追加の検討対象とする(2023年版の「MA+RCTが計3件以上で表を作る」基準に準拠)。
"""
md.append("# 新規介入候補の文献調査(PubMed)\n")
md.append("検索日: %s。出典: PubMed(According to PubMed)。判定は各論文の抄録に書かれた Method を読んで行った。\n"%H["search_date"])
md.append(GLOSS)
md.append("## 検索式\nBASE = (\"chemotherapy-induced peripheral neuropathy\"[tiab] OR CIPN[tiab] OR (neuropath*[tiab] AND (chemotherap*[tiab] OR oxaliplatin[tiab] OR paclitaxel[tiab] OR docetaxel[tiab] OR cisplatin[tiab] OR bortezomib[tiab] OR vincristine[tiab] OR taxane*[tiab])))\n\nRCT: BASE AND (介入語[tiab]) AND \"randomized controlled trial\"[pt]\n\nSR/MA: (\"chemotherapy-induced peripheral neuropathy\"[tiab] OR CIPN[tiab]) AND (介入語[tiab]) AND (meta-analysis[pt] OR systematic review[pt])\n")
md.append("## 介入別の集計\n")
md.append("| 介入 | RCT[pt] 件数 | 適格・予防 | 適格・治療 | 要確認 | 不適格 | 追加基準(3本以上) |\n|---|---|---|---|---|---|---|")
summ=[]
for g,ids in G.items():
    ids=list(dict.fromkeys(ids))
    ep=[i for i in ids if i in R and dec(R[i])=="適格" and purpose(R[i])=="予防"]
    et=[i for i in ids if i in R and dec(R[i])=="適格" and purpose(R[i])=="治療"]
    q=[i for i in ids if i in R and dec(R[i])=="要確認"]
    n=[i for i in ids if i in R and dec(R[i])=="不適格"]
    miss=[i for i in ids if i not in R]
    crit="予防・治療とも該当" if len(ep)>=3 and len(et)>=3 else "予防が該当" if len(ep)>=3 else "治療が該当" if len(et)>=3 else "該当しない"
    summ.append((g,ids,ep,et,q,n,miss,crit))
    # 国内未承認: 根拠欄に「国内で処方不可」と書いた適格RCT
    for i in ep+et:
        if "国内で処方不可" in R[i]["basis"]: NOJP.add(i)
    md.append(f"| {g} | {len(ids)} | {len(ep)} | {len(et)} | {len(q)} | {len(n)} | {crit} |")
md.append("\n国内で処方できない介入(根拠欄に記録)の適格RCT: "+(" ".join(sorted(NOJP)) or "なし")+"。\n\n注: 「デュロキセチン」は、デュロキセチンを含む RCT[pt] 16件のうち、デュロキセチンが共投薬にすぎない2件(41630017 セレン、32493088 電気刺激)を各介入の群へ移した14件の分類。1つの RCT が複数の介入群に重複して数えられる場合がある(例: 33249081 は TENS とスクランブラーの2群)。\n")
md.append("## 介入別のPMID一覧(全件)\n")
for g,ids,ep,et,q,n,miss,crit in summ:
    md.append(f"### {g}\n")
    md.append("- 適格・予防(%d): %s"%(len(ep)," ".join(ep) or "なし"))
    md.append("- 適格・治療(%d): %s"%(len(et)," ".join(et) or "なし"))
    md.append("- 要確認(%d): %s"%(len(q)," ".join(q) or "なし"))
    md.append("- 不適格(%d): %s"%(len(n)," ".join(n) or "なし"))
    if miss: md.append("- Method未判定: "+" ".join(miss))
    s=GROUP_SR.get(g,[])
    md.append("- SR/MA(%d): %s\n"%(len(s)," ".join(s) or "なし"))
md.append("## RCT 判定一覧(PMID・Methodの根拠)\n")
md.append("| PMID | 年 | 第一著者 | デザイン | 目的 | 化学療法 | N | 介入 | 対照 | 判定 | 根拠 |\n|---|---|---|---|---|---|---|---|---|---|---|")
for i,r in sorted(R.items(), key=lambda x:(-int(x[1]['year']) if x[1]['year'].isdigit() else 0)):
    md.append("| "+" | ".join([i,r['year'],r['author'],r['design'],r['purpose'],r['chemo'],r['n'],r['intervention'],r['comparator'],r['decision'],r['basis']]).replace("\n"," ")+" |")
md.append("\n## 2023年版の参考文献に既に含まれる RCT: "+" ".join(sorted(IN2023))+"\n")
md.append("## SR/MA 一覧(%d件)\n"%len(SR))
md.append("| PMID | 年 | 第一著者 | 種別 | 対象 |\n|---|---|---|---|---|")
for p,y,a,t,s in SR: md.append(f"| {p} | {y} | {a} | {t} | {s} |")
md.append("\n### 検索にかかったが集計から除いた文献(%d件)\n"%len(SR_NOT))
md.append("| PMID | 年 | 第一著者 | 除外理由 |\n|---|---|---|---|")
for p,y,a,s in SR_NOT: md.append(f"| {p} | {y} | {a} | {s} |")
os.makedirs("out",exist_ok=True)
open("out/候補介入_文献調査.md","w",encoding="utf-8").write("\n".join(md)+"\n")

# xlsx
wb=Workbook(); thin=Side(style="thin",color="000000"); B=Border(left=thin,right=thin,top=thin,bottom=thin)
def sheet(ws,head,data,widths):
    ws.append(head)
    for r in data: ws.append(r)
    for c in ws[1]: c.font=Font(bold=True); c.fill=PatternFill("solid",fgColor="D9D9D9"); c.border=B; c.alignment=Alignment(wrap_text=True,vertical="top")
    for row in ws.iter_rows(min_row=2):
        for c in row: c.border=B; c.alignment=Alignment(wrap_text=True,vertical="top")
    for i,w in enumerate(widths,1): ws.column_dimensions[get_column_letter(i)].width=w
    ws.freeze_panes="A2"
ws=wb.active; ws.title="介入別集計"
sheet(ws,["介入","RCT[pt]件数","適格・予防","適格・治療","要確認","不適格","追加基準(3本以上)","適格・予防のPMID","適格・治療のPMID","要確認のPMID","不適格のPMID","SR/MAのPMID"],
 [[g,len(ids),len(ep),len(et),len(q),len(n),crit," ".join(ep)," ".join(et)," ".join(q)," ".join(n)," ".join(GROUP_SR.get(g,[]))] for g,ids,ep,et,q,n,miss,crit in summ],[34,10,9,9,8,8,16,40,40,30,40,40])
ws=wb.create_sheet("RCT判定一覧")
keys=["pmid","year","author","design","purpose","chemo","n","intervention","comparator","decision","basis"]
sheet(ws,["PMID","年","第一著者","デザイン","目的(予防/治療)","化学療法","N","介入","対照","判定","Methodの根拠"],[[r[k] for k in keys]+[] for r in R.values()],[11,6,14,22,12,22,8,24,20,30,60])
ws=wb.create_sheet("SR・MA一覧")
sheet(ws,["PMID","年","第一著者","種別","対象"],[list(x) for x in SR],[11,6,18,16,60])
ws=wb.create_sheet("集計から除いた文献")
sheet(ws,["PMID","年","第一著者","除外理由"],[list(x) for x in SR_NOT],[11,6,18,70])
ws=wb.create_sheet("用語の定義")
sheet(ws,["用語","定義"],[[l[4:].split("**: ")[0].strip("*"), l.split("**: ",1)[1]] for l in GLOSS.splitlines() if l.startswith("- **")],[18,110])
wb.save("out/候補介入_文献調査.xlsx")
for g,ids,ep,et,q,n,miss,crit in summ: print(g,len(ids),len(ep),len(et),len(q),len(n),miss,crit)
