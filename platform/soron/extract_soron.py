"""2023年版PDFの第2章 総論を担当単位(A〜M, I-1/I-2, J-1〜J-5)に切り出す
  cd platform/soron && python3 extract_soron.py <2023年版PDF> && node build_docx.js   # → out/*.docx
(node の docx パッケージが必要: npm install docx)
"""
import json, re, os, subprocess, sys
P = sys.argv[1] if len(sys.argv) > 1 else "../../CIPNGL2023.pdf"
for i in range(22, 70):
    subprocess.run(["pdftotext", "-raw", "-f", str(i), "-l", str(i), P, f"p{i}.txt"], capture_output=True)
UNITS = [
 ("A","A. CIPNの頻度","内藤",22,24,None,None),
 ("B","B. CIPNの症候学的分類","松岡宏",25,25,None,None),
 ("C","C. 病理組織学的分類と症状","武井（前回 平山）",26,26,None,None),
 ("D","D. CIPNと神経障害性疼痛の関係","中川貴之（前回 森）",27,28,None,None),
 ("E","E. CIPNのリスク因子","宇和川",29,30,None,None),
 ("F","F. 鑑別診断に用いられる検査項目","田辺（前回 大熊）",31,31,None,None),
 ("G","G. 各薬剤によるCIPNの症状","神林・縄田・坂下",32,34,None,None),
 ("H","H. CIPNの評価","華井",35,39,None,None),
 ("I_1","I-1. がん薬物療法に伴う中枢神経障害","平川（前回 平山）",40,45,None,r"^2．感覚器障害"),
 ("I_2","I-2. 感覚器障害（聴覚，視覚，嗅覚など）","古川",45,49,r"^2．感覚器障害",None),
 ("J_1","J-1. CIPNにおける被疑薬の減量あるいは中止について","吉田",50,53,None,r"^2．デュロキセチン"),
 ("J_2","J-2. デュロキセチン","中島",53,55,r"^2．デュロキセチン",r"^3．化学療法誘発性急性神経障害"),
 ("J_3","J-3. 化学療法誘発性急性神経障害について","菊池（前回 平山）",55,57,r"^3．化学療法誘発性急性神経障害",r"^4．CIPN における看護"),
 ("J_4","J-4. CIPNにおける看護","荒尾（前回 神田）",57,60,r"^4．CIPN における看護",r"^5．CIPN における理学的手法"),
 ("J_5","J-5. CIPNにおける理学的手法","中川夏樹（前回 華井）",60,62,r"^5．CIPN における理学的手法",None),
 ("K","K. ASCO および ESMO‒EONS‒EANO CIPNガイドラインの紹介","（未定：2023年版執筆者）",63,64,None,None),
 ("L","L. 「手引き2017年版」公表の効果の検証","（未定：2023年版執筆者）",65,66,None,None),
 ("M","M. ガイドライン普及と活用促進のための工夫","（未定：2023年版執筆者）",67,69,None,None),
]
HEAD = re.compile(r"^([A-M]．.+|[A-M] \S.+|[1-9]．[^0-9\s].*|[1-9]）[^\d\s，,].*|文献)$")
REFMARK = re.compile(r"^(\d+）(?:[,，]\s*\d+）)*|\d+）[〜～]\d+）)$")
NOISE = re.compile(r"^(\d+ 第 2 章 総論|総論 .* \d+|\d{1,3}|第|2 章|第\s*2\s*章|総\s*論|CIPN)$")

def page_lines(p):
    ls=[l.rstrip("\x0c").rstrip() for l in open(f"p{p}.txt",encoding="utf-8")]
    ls=[re.sub(r"\x07"," ",l).strip() for l in ls]
    # 先頭の柱(ページ番号/章/節見出しの繰り返し)を落とす
    i=0
    while i<len(ls) and (ls[i]=="" or NOISE.match(ls[i]) or re.match(r"^[A-M]．",ls[i]) and i<3):
        i+=1
    return [l for l in ls[i:] if not NOISE.match(l)]

def build(unit):
    key,title,who,a,b,start,end=unit
    lines=[]; figpages=set()
    for p in range(a,b+1):
        ls=page_lines(p)
        if p==a and start:
            idx=next((i for i,l in enumerate(ls) if re.match(start,l)),0); ls=ls[idx:]
        if p==b and end:
            idx=next((i for i,l in enumerate(ls) if re.match(end,l)),len(ls)); ls=ls[:idx]
        if any(re.match(r"^(表|図)\s*\d+．",l) for l in ls): figpages.add(p)
        lines+=ls
    # 段落化
    paras=[]; cur=""; in_ref=False
    for l in lines:
        if l=="":
            continue
        if l=="文献":
            if cur: paras.append(cur)
            cur=""; in_ref=True; paras.append("##文献"); continue
        if REFMARK.match(l):
            cur+= "^"+l.replace("）",")")+"^"; continue
        if in_ref and re.match(r"^\d+）",l):
            if cur: paras.append(cur)
            cur=l; continue
        if not in_ref and HEAD.match(l):
            if cur: paras.append(cur)
            paras.append("#"+l); cur=""; continue
        if cur and cur.endswith("。"):
            paras.append(cur); cur=l
        else:
            cur += (" " if (cur and re.search(r"[A-Za-z0-9]$",cur) and re.match(r"^[A-Za-z0-9]",l)) else "") + l
    if cur: paras.append(cur)
    imgs=[]
    for p in sorted(figpages):
        out=f"fig_{key}_p{p}"
        subprocess.run(["pdftoppm","-png","-r","110","-f",str(p),"-l",str(p),P,out],capture_output=True)
        f=[x for x in os.listdir(".") if x.startswith(out) and x.endswith(".png")]
        if f: imgs.append({"page":p-12,"file":f[0]})
    return {"key":key,"title":title,"who":who,"pages":f"{a-12}–{b-12}","paras":paras,"images":imgs}

data=[build(u) for u in UNITS]
json.dump(data,open("units.json","w",encoding="utf-8"),ensure_ascii=False,indent=1)
for d in data: print(d["key"],d["pages"],len(d["paras"]),"paras",[i["page"] for i in d["images"]])
