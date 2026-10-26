import json,sys,os
# 使い方: python3 add.py  (標準入力: 1行=パイプ区切り PMID|年|第一著者|デザイン|目的(予防/治療/対象外)|化学療法|N|介入|対照|対象CQ|判定|根拠(Method))
f="records.json"; d=json.load(open(f,encoding="utf-8")) if os.path.exists(f) else {}
k=["pmid","year","author","design","purpose","chemo","n","intervention","comparator","cq","decision","basis"]
for line in sys.stdin:
    line=line.strip()
    if not line or line.startswith("#"): continue
    p=[x.strip() for x in line.split("|")]; assert len(p)==12,(len(p),line[:50])
    d[p[0]]=dict(zip(k,p))
json.dump(d,open(f,"w",encoding="utf-8"),ensure_ascii=False,indent=1); print(len(d),"records")
