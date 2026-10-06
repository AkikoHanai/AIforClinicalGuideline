import json,sys,os
# 使い方: python3 add.py  (標準入力: 1行=パイプ区切り PMID|年|第一著者|デザイン|目的|化学療法|N|介入|対照|判定|理由・根拠(Method))
f="records.json"; d=json.load(open(f,encoding="utf-8")) if os.path.exists(f) else {}
for line in sys.stdin:
    line=line.strip()
    if not line or line.startswith("#"): continue
    p=[x.strip() for x in line.split("|")]
    assert len(p)==11,(len(p),line[:60])
    k=["pmid","year","author","design","purpose","chemo","n","intervention","comparator","decision","basis"]
    d[p[0]]=dict(zip(k,p))
json.dump(d,open(f,"w",encoding="utf-8"),ensure_ascii=False,indent=1); print(len(d),"records")
