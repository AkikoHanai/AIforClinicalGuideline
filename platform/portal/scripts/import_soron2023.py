"""2023年版の総論(platform/data/gl2023/units.json。刊行版 PDF から原文のまま全文を切り出したもの)を、段落ID付きでポータルに取り込む(Mac で実行)。
  python3 platform/portal/scripts/import_soron2023.py <メールアドレス>                      platform/data/gl2023/units.json(2023年版PDFの抽出結果)から取り込む
  python3 platform/portal/scripts/import_soron2023.py --docx <メールアドレス>               platform/soron/out の docx から取り込む
総論の画面で、執筆者が 2023年版の本文を参照できるようになる。docx 自体も S3 に置き、画面から取得できる。"""
import glob, json, os, re, sys, urllib.request, zipfile
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from admin_user import OUT, token  # noqa: E402

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
SRC = os.path.join(ROOT, "soron", "out")


def paragraphs(path):
    xml = zipfile.ZipFile(path).read("word/document.xml").decode("utf-8")
    ps = [re.sub(r"<[^>]+>", "", p) for p in re.findall(r"<w:p[ >].*?</w:p>", xml, re.S)]
    ps = [re.sub(r"\s+", " ", p).strip() for p in ps]
    ps = [p for p in ps if p]
    start = next((i for i, p in enumerate(ps) if re.match(r"^3\.\s*2023年版\s*原文", p)), None)
    body = ps[start + 1:] if start is not None else ps
    end = next((i for i, p in enumerate(body) if re.match(r"^(4\.|文献$)", p)), len(body))
    return [p for p in body[:end] if len(p) >= 2]


def main(email, use_docx=False):
    tok = token(email)
    items = []
    if not use_docx:
        units = json.load(open(os.path.join(ROOT, "data", "gl2023", "units.json"), encoding="utf-8"))
        plan = json.load(open(os.path.join(ROOT, "governance", "approved_plan.json"), encoding="utf-8"))["総論"]
        for u in units:
            key = u["key"]
            if key not in plan:
                print(f"{key}: 2028年版の企画書に対応する項目がないため、取り込まない"); continue
            paras = [p for p in u["paras"] if not p.startswith("#")]  # 見出し行(#)と文献(##文献)の印を除く。本文・表図・文献の段落
            docx = glob.glob(os.path.join(SRC, f"総論{key}_*.docx"))
            items.append({"key": key, "title": u["title"], "paragraphs": [{"id": f"GL2023-総論{key.replace('_', '-')}-p{i + 1:03d}", "text": p} for i, p in enumerate(paras)], "filename": os.path.basename(docx[0]) if docx else ""})
            print(f"総論{key}: {len(paras)}段落 (2023年版 章{u['letter2023']} pp.{u['chapter_pages']}。照合: 落ちた文字 {u['verify']['missing']} 字)")
        for key, v in plan.items():      # 新設の項目(2023年版に本文がない)。依頼書だけを置く
            if any(it["key"] == key for it in items): continue
            docx = glob.glob(os.path.join(SRC, f"総論{key}_*.docx"))
            items.append({"key": key, "title": v.rpartition(":")[0], "paragraphs": [], "filename": os.path.basename(docx[0]) if docx else ""})
            print(f"総論{key}: 新設(2023年版の本文なし。依頼書 {'あり' if docx else 'なし'})")
    for f in (sorted(glob.glob(os.path.join(SRC, "総論*.docx"))) if use_docx else []):
        name = os.path.basename(f)
        m = re.match(r"総論([A-N](?:_\d)?)_(.+)\.docx$", name)
        if not m or name.endswith("_新設.docx"):
            continue
        key, title = m.group(1), m.group(2)
        paras = paragraphs(f)
        items.append({"key": key, "title": title, "paragraphs": [{"id": f"GL2023-総論{key.replace('_', '-')}-p{i + 1:03d}", "text": p} for i, p in enumerate(paras)], "filename": name})
        print(f"総論{key}: {len(paras)}段落")
    r = tok.call("POST", "/gl2023/soron", {"items": items}); print({k: v for k, v in r.items() if k != "upload_urls"})   # 署名付き URL(一時的な認証情報を含む)は表示しない
    for it, url in zip(items, r.get("upload_urls", [])):
        if url and it.get("filename"):
            with open(os.path.join(SRC, it["filename"]), "rb") as fh:
                urllib.request.urlopen(urllib.request.Request(url, method="PUT", data=fh.read(), headers={"Content-Type": "application/vnd.openxmlformats-officedocument.wordprocessingml.document"}))
    print("docx を置きました")


if __name__ == "__main__":
    a = sys.argv[1:]
    from admin_user import email_arg
    if {"-h", "--help"} & set(a): sys.exit(__doc__)
    main(email_arg(a), use_docx="--docx" in a)
