"""2023年版の総論(platform/soron/out/総論*.docx の「3. 2023年版 原文」)を、段落ID付きでポータルに取り込む(Mac で実行)。
  python3 platform/portal/scripts/import_soron2023.py <メールアドレス>
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


def main(email):
    tok = token(email)
    items = []
    for f in sorted(glob.glob(os.path.join(SRC, "総論*.docx"))):
        name = os.path.basename(f)
        m = re.match(r"総論([A-M](?:_\d)?)_(.+)\.docx$", name)
        if not m:
            continue
        key, title = m.group(1), m.group(2)
        paras = paragraphs(f)
        items.append({"key": key, "title": title, "paragraphs": [{"id": f"GL2023-総論{key.replace('_', '-')}-p{i + 1:03d}", "text": p} for i, p in enumerate(paras)], "filename": name})
        print(f"総論{key}: {len(paras)}段落")
    req = urllib.request.Request(OUT["ApiUrl"] + "/gl2023/soron", method="POST", headers={"Authorization": "Bearer " + tok, "Content-Type": "application/json"}, data=json.dumps({"items": items}, ensure_ascii=False).encode())
    r = json.loads(urllib.request.urlopen(req).read().decode()); print(r)
    for it, url in zip(items, r.get("upload_urls", [])):
        if url:
            with open(os.path.join(SRC, it["filename"]), "rb") as fh:
                urllib.request.urlopen(urllib.request.Request(url, method="PUT", data=fh.read(), headers={"Content-Type": "application/vnd.openxmlformats-officedocument.wordprocessingml.document"}))
    print("docx を置きました")


if __name__ == "__main__":
    main(sys.argv[1])
