"""承認済み企画書からの逸脱を検査する。逸脱が1件でもあれば終了コード1。
  python3 platform/governance/plan_guard.py
検査:
 1. 承認済み企画書(docx)のSHA-256が approved_plan.json の値と一致する(企画書が書き換えられていない)
 2. 作業フォルダ(CQ名)がすべて企画書のSR項目・FRQ項目に対応する(企画書にない項目が無い)
 3. 生成物(scope / procedures / review / core / README)に、企画書にない介入名・旧体制の氏名が現れない
 4. Scope改訂案に、企画書のSR項目・FRQ項目の名称がすべて載っている
隔離フォルダ(_企画書外_保留)、governance、総論の元原稿(soron)は検査しない。"""
import hashlib, json, os, re, sys, zipfile, glob

HERE = os.path.dirname(os.path.abspath(__file__)); ROOT = os.path.dirname(HERE)
P = json.load(open(os.path.join(HERE, "approved_plan.json"), encoding="utf-8"))
errs = []

# 1
f = glob.glob(os.path.join(HERE, "承認済み企画書_*.docx"))
if not f: errs.append("承認済み企画書のdocxがありません")
else:
    h = hashlib.sha256(open(f[0], "rb").read()).hexdigest()
    if h != P["sha256"]: errs.append(f"承認済み企画書のSHA-256が一致しません: {h}")

v2 = glob.glob(os.path.join(HERE, "提案書v2_*.docx"))
if not v2 or hashlib.sha256(open(v2[0], "rb").read()).hexdigest() != P["提案書v2(正。企画書と異なる点はこちらが優先)"]["sha256"]: errs.append("提案書v2が無い、またはSHA-256が一致しません")
# 2
known = {d for it in P["SR項目"] + P["FRQ項目"] for d in it["dir"]}
cq = os.path.join(ROOT, "scope", "cq_rows.json")
if os.path.exists(cq):
    for r in json.load(open(cq, encoding="utf-8")):
        if r["dir"] not in known: errs.append(f"企画書にない作業フォルダ: {r['dir']}")
    have = {r["dir"] for r in json.load(open(cq, encoding="utf-8"))}
    for d in sorted(known - have): errs.append(f"企画書の項目に対応する作業フォルダがありません: {d}")

# 3
def text_of(path):
    if path.endswith(".docx"):
        x = zipfile.ZipFile(path).read("word/document.xml").decode("utf-8")
        return re.sub(r"<[^>]+>", "", x)
    if path.endswith(".xlsx"):
        z = zipfile.ZipFile(path); out = []
        for n in z.namelist():
            if n.startswith("xl/sharedStrings") or n.startswith("xl/worksheets/"): out.append(re.sub(r"<[^>]+>", " ", z.read(n).decode("utf-8", "ignore")))
        return " ".join(out)
    return open(path, encoding="utf-8", errors="ignore").read()
bad = P["禁止する語(企画書にない介入。生成物に現れたらガードが失敗する)"] + P["禁止する旧体制の氏名(2023年版の体制。企画書にない)"]
scan_dirs = ["scope", "procedures", "manuals", "review", "core", "data", "tests"]
skip = ("_企画書外_保留", "governance", "soron", "__pycache__", "node_modules", "prior_worksheets")
for sd in scan_dirs:
    for dp, dn, fn in os.walk(os.path.join(ROOT, sd)):
        dn[:] = [d for d in dn if d not in skip]
        for n in fn:
            if not n.endswith((".docx", ".xlsx", ".py", ".js", ".md", ".sh", ".json", ".html")): continue
            p = os.path.join(dp, n)
            try: t = text_of(p)
            except Exception: continue
            for w in bad:
                if w in t: errs.append(f"企画書にない語「{w}」: {os.path.relpath(p, ROOT)}")
rd = os.path.join(ROOT, "README.md")
if os.path.exists(rd):
    t = open(rd, encoding="utf-8").read()
    for w in bad:
        if w in t: errs.append(f"企画書にない語「{w}」: README.md")

# 4
sc = os.path.join(ROOT, "scope", "out", "1_Scope改訂案.docx")
if os.path.exists(sc):
    t = text_of(sc)
    for it in P["SR項目"] + P["FRQ項目"]:
        key = it["キー"]
        if key not in t: errs.append(f"Scope改訂案に企画書の項目がありません: {it['名称']}")
    if P["タイトル"] not in t: errs.append("Scope改訂案のタイトルが「" + P["タイトル"] + "」になっていません")

if errs:
    print("【企画書からの逸脱を検出】"); [print(" -", e) for e in errs]; sys.exit(1)
print("OK: 承認済み企画書(Ver1 2026-06-17)からの逸脱はありません")
