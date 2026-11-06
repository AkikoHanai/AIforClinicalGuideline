"""Google ドライブ JASCC_GL/論文受け取り/<CQフォルダ>/<PMID>.pdf を、ポータルに登録して本文を抽出する(Mac で実行。ドライブ → ポータル)。
  python3 platform/portal/scripts/sync_papers.py <メールアドレス>
  JASCC_GL=<パス> python3 platform/portal/scripts/sync_papers.py <メールアドレス>   場所を変えるとき
  python3 platform/portal/scripts/sync_papers.py --pdf-dir <フォルダ> <メールアドレス>   平らなフォルダのPDFを登録する。ファイル名がPMIDならそのPMIDで、
      そうでなければ1〜2ページ目の本文を2023年版の引用文献(platform/data/gl2023/cq_packages)の題名と照合してPMIDとCQを決める。照合できないPDFは一覧に出す
PDF の名前は PMID.pdf。既に登録済みで本文抽出済みのものは飛ばす。終わりに、CQ ごとの件数と、PDF が 1 件もない CQ を表示する。"""
import glob, json, logging, os, re, sys, urllib.request
logging.getLogger("pypdf").setLevel(logging.ERROR)
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from admin_user import OUT, token  # noqa: E402

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
JASCC_GL = os.environ.get("JASCC_GL", "/Users/ahanai/Library/CloudStorage/GoogleDrive-akiko.hanai@faculty.gs.chiba-u.jp/マイドライブ/JASCC_GL")
INBOX = os.path.join(JASCC_GL, "論文受け取り")


def call(path, tok, method="GET", data=None):
    req = urllib.request.Request(OUT["ApiUrl"] + path, method=method, headers={"Authorization": "Bearer " + tok, "Content-Type": "application/json"},
                                 data=json.dumps(data, ensure_ascii=False).encode() if data is not None else None)
    try:
        return json.loads(urllib.request.urlopen(req).read().decode())
    except urllib.error.HTTPError as e:
        return {"error": f"{e.code} {e.read().decode()[:200]}"}


def main(email):
    plan = json.load(open(os.path.join(ROOT, "governance", "approved_plan.json"), encoding="utf-8"))
    dir2id = {d: it["id"] for it in plan["SR項目"] + plan["FRQ項目"] for d in it["dir"]}
    if not os.path.isdir(INBOX):
        sys.exit(f"フォルダがありません: {INBOX}(Google ドライブが同期済みか確認)")
    tok = token(email)
    total, empty = 0, []
    for d, cqid in sorted(dir2id.items()):
        pdfs = sorted(glob.glob(os.path.join(INBOX, d, "*.pdf")))
        if not pdfs:
            empty.append(f"{cqid} {d}"); continue
        have = {p["pmid"]: p for p in call(f"/papers/{cqid}", tok)} if isinstance(call(f"/papers/{cqid}", tok), list) else {}
        done = 0
        for f in pdfs:
            pmid = re.sub(r"\D", "", os.path.splitext(os.path.basename(f))[0])
            if not pmid:
                print(f"  飛ばす(PMID でない名前): {f}"); continue
            if have.get(pmid, {}).get("status") == "本文抽出済":
                done += 1; continue
            r = call(f"/papers/{cqid}/{pmid}/upload-url", tok, "POST", {"title": ""})
            if "error" in r:
                print(f"  {cqid} {pmid}: 登録できません {r['error']}"); continue
            with open(f, "rb") as fh:
                req = urllib.request.Request(r["url"], method="PUT", data=fh.read(), headers={"Content-Type": "application/pdf"})
                urllib.request.urlopen(req)
            x = call(f"/papers/{cqid}/{pmid}/extract", tok, "POST", {})
            if "error" in x:
                print(f"  {cqid} {pmid}: 本文の抽出に失敗 {x['error']}"); continue
            print(f"  {cqid} {pmid}: 登録 {x['pages']}頁 {x['paragraphs']}段落(Method {x['sections']['methods']} / Result {x['sections']['results']})"); done += 1
        print(f"{cqid} {d}: PDF {len(pdfs)}件 → 本文抽出済 {done}件"); total += done
    print(f"\n合計 {total} 件を登録・抽出済み")
    if empty:
        print("PDF が 1 件もない CQ:\n  " + "\n  ".join(empty))


def norm(s):
    import unicodedata
    return re.sub(r"[^a-z0-9]", "", unicodedata.normalize("NFKC", s or "").lower())


def main_pdf_dir(folder, email):
    """平らなフォルダの PDF を、PMID 名または題名の照合で CQ に振り分けて登録する"""
    from pypdf import PdfReader
    plan = json.load(open(os.path.join(ROOT, "governance", "approved_plan.json"), encoding="utf-8"))
    dir2id = {d: it["id"] for it in plan["SR項目"] + plan["FRQ項目"] for d in it["dir"]}
    refs = {}  # pmid → {"title":, "cqs": set}
    for f in glob.glob(os.path.join(ROOT, "data", "gl2023", "cq_packages", "CQ*.json")):
        stem = os.path.splitext(os.path.basename(f))[0]; cqid = dir2id.get({"CQ1-冷却": "CQ1-冷却・圧迫", "CQ1-圧迫": "CQ1-冷却・圧迫"}.get(stem, stem))
        if not cqid: continue
        for r in json.load(open(f, encoding="utf-8")).get("references", []):
            if r.get("pmid"): refs.setdefault(str(r["pmid"]), {"title": r.get("title", ""), "cqs": set()})["cqs"].add(cqid)
    tok = token(email); done, unmatched = 0, []
    seen = set()
    for f in sorted(f for f in set(glob.glob(os.path.join(folder, "**", "*.pdf"), recursive=True)) if not any(part.startswith("_") for part in os.path.relpath(f, folder).split(os.sep)[:-1])):  # _work などは除く
        name = os.path.splitext(os.path.basename(f))[0]
        m = re.search(r"PMID[_\- ]?(\d{6,9})", name, re.I) or re.fullmatch(r"(\d{6,9})", name)
        pmid = m.group(1) if m else None
        if not pmid:
            try:
                rd = PdfReader(f); head = norm(" ".join((rd.pages[i].extract_text() or "") for i in range(min(2, len(rd.pages)))))
            except Exception as e:
                unmatched.append(f"{os.path.basename(f)} (読めない: {e})"); continue
            hits = [p for p, r in refs.items() if r["title"] and len(norm(r["title"])) > 25 and norm(r["title"])[:80] in head]
            pmid = hits[0] if len(hits) == 1 else None
        cqs = sorted(refs.get(pmid, {}).get("cqs", [])) if pmid else []
        if pmid and pmid in seen: continue  # 同じPMIDのPDFが複数あれば最初の1つだけ
        if pmid: seen.add(pmid)
        if not pmid or not cqs:
            unmatched.append(os.path.basename(f) + (f" (PMID {pmid}: 2023年版の引用文献にない。新規論文は <CQフォルダ>/PMID.pdf に置く)" if pmid else " (題名の照合なし)")); continue
        data = open(f, "rb").read()
        for cqid in cqs:
            r = call(f"/papers/{cqid}/{pmid}/upload-url", tok, "POST", {"title": refs[pmid]["title"]})
            if "error" in r: print(f"  {cqid} {pmid}: {r['error']}"); continue
            urllib.request.urlopen(urllib.request.Request(r["url"], method="PUT", data=data, headers={"Content-Type": "application/pdf"}))
            x = call(f"/papers/{cqid}/{pmid}/extract", tok, "POST", {})
            print(f"  {cqid} {pmid}: {os.path.basename(f)} → " + (f"{x['pages']}頁 {x['paragraphs']}段落(Method {x['sections']['methods']} / Result {x['sections']['results']})" if "error" not in x else x["error"])); done += 1
    print(f"\n登録 {done} 件(CQ×論文)")
    if unmatched:
        print("照合できなかった PDF:\n  " + "\n  ".join(unmatched))


if __name__ == "__main__":
    a = sys.argv[1:]
    if a[:1] == ["--pdf-dir"] and len(a) >= 3:
        main_pdf_dir(a[1], a[2])
    elif a:
        main(a[0])
    else:
        sys.exit(__doc__)
