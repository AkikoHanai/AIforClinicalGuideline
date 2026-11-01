"""Google ドライブ JASCC_GL/論文受け取り/<CQフォルダ>/<PMID>.pdf を、ポータルに登録して本文を抽出する(Mac で実行。ドライブ → ポータル)。
  python3 platform/portal/scripts/sync_papers.py <メールアドレス>
  JASCC_GL=<パス> python3 platform/portal/scripts/sync_papers.py <メールアドレス>   場所を変えるとき
PDF の名前は PMID.pdf。既に登録済みで本文抽出済みのものは飛ばす。終わりに、CQ ごとの件数と、PDF が 1 件もない CQ を表示する。"""
import glob, json, os, re, sys, urllib.request
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


if __name__ == "__main__":
    if len(sys.argv) < 2:
        sys.exit(__doc__)
    main(sys.argv[1])
