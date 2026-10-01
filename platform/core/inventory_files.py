"""Mac上の作業フォルダを走査して、CIPN改訂に関係するファイルを分類・一覧化する(読み取り専用)

  python3 platform/core/inventory_files.py "/Users/ahanai/CIPN/CIPN Guideline" "/Users/ahanai/CIPN/SR統括ファイル" -o inventory

出力(-o の先に作る):
  inventory.csv   … 全ファイル: 分類, CQ推定, 種別, サイズ, 更新日, 重複(同一内容), パス
  inventory.md    … 分類ごとの件数と要約、重複・疑わしいファイルの一覧
ファイルの移動・削除は一切しない。整理(コピー先の提案)は organize_files.py で別に行う。
"""
import argparse
import csv
import datetime
import hashlib
import os
import re
import sys
import zipfile

CQ_WORDS = [("牛車腎気丸", "CQ1-牛車腎気丸"), ("goshajinkigan", "CQ1-牛車腎気丸"), ("カルニチン", "CQ1-カルニチン"), ("carnitine", "CQ1-カルニチン"),
            ("冷却", "CQ1-冷却・圧迫"), ("圧迫", "CQ1-冷却・圧迫"), ("cryo", "CQ1-冷却・圧迫"), ("compression", "CQ1-冷却・圧迫"),
            ("デュロキセチン", "CQ2-デュロキセチン"), ("duloxetine", "CQ2-デュロキセチン"), ("アミトリプチリン", "CQ2-アミトリプチリン"),
            ("ミロガバリン", "CQ2-ミロガバリン"), ("mirogabalin", "CQ2-ミロガバリン"), ("プレガバリン", "プレガバリン(CQ1/CQ2)"), ("pregabalin", "プレガバリン(CQ1/CQ2)"),
            ("B12", "CQ2-ビタミンB12"), ("NSAID", "CQ2-NSAIDs"), ("オピオイド", "CQ2-オピオイド"), ("opioid", "CQ2-オピオイド"),
            ("併用", "CQ2-併用療法"), ("運動", "運動(CQ1/CQ2)"), ("exercise", "運動(CQ1/CQ2)"), ("鍼", "鍼灸(CQ1/CQ2)"), ("acupuncture", "鍼灸(CQ1/CQ2)")]
KIND = [("検索", r"検索|search|pubmed|query"), ("スクリーニング", r"screen|スクリーニング|抽出|採否|除外"),
        ("RoB/質評価", r"rob|bias|バイアス|quality|質評価|評価シート"), ("エビデンス表", r"エビデンス|evidence|sof|summary of findings|文献の内容|forest|メタ"),
        ("推奨文/解説", r"推奨|recommend|解説|原稿|draft|草案"), ("議事/連絡", r"議事|minutes|メール|連絡|依頼|schedule|日程"),
        ("文献PDF", r"^\d{6,9}$|et al|\d{4}[_ -]|paper|文献"), ("総論原稿", r"総論|第2章|chapter")]
SKIP_DIRS = {".git", "node_modules", "__pycache__", ".venv", ".Trash"}


def sha1(path, limit=50_000_000):
    h = hashlib.sha1()
    try:
        with open(path, "rb") as f:
            n = 0
            while n < limit:
                b = f.read(1 << 20)
                if not b:
                    break
                h.update(b); n += len(b)
    except OSError:
        return ""
    return h.hexdigest()


def peek_text(path, ext):
    """分類の手がかりにするため、先頭の文字だけ取り出す(失敗したら空)"""
    try:
        if ext in (".docx", ".pptx", ".xlsx"):
            z = zipfile.ZipFile(path)
            name = {"docx": "word/document.xml", "pptx": "ppt/slides/slide1.xml", "xlsx": "xl/sharedStrings.xml"}[ext[1:]]
            if name in z.namelist():
                return re.sub(r"<[^>]+>", " ", z.read(name).decode("utf8", "ignore"))[:3000]
        elif ext in (".txt", ".md", ".csv"):
            return open(path, encoding="utf-8", errors="ignore").read(3000)
    except Exception:
        pass
    return ""


def classify(path, text):
    s = (os.path.basename(path) + " " + os.path.dirname(path) + " " + text).lower()
    cq = next((c for w, c in CQ_WORDS if w.lower() in s), "")
    base = os.path.splitext(os.path.basename(path))[0].lower()
    kind = next((k for k, pat in KIND if re.search(pat, base + " " + text[:400].lower())), "その他")
    return kind, cq


def scan(roots):
    rows = []
    for root in roots:
        for dp, dns, fns in os.walk(root):
            dns[:] = [d for d in dns if d not in SKIP_DIRS and not d.startswith(".")]
            for fn in fns:
                if fn.startswith(".") or fn.startswith("~$"):
                    continue
                p = os.path.join(dp, fn)
                ext = os.path.splitext(fn)[1].lower()
                try:
                    st = os.stat(p)
                except OSError:
                    continue
                kind, cq = classify(p, peek_text(p, ext))
                rows.append({"kind": kind, "cq": cq, "ext": ext, "size": st.st_size,
                             "mtime": datetime.datetime.fromtimestamp(st.st_mtime).strftime("%Y-%m-%d"),
                             "root": root, "path": p, "sha1": sha1(p) if st.st_size else ""})
    by = {}
    for r in rows:
        if r["sha1"]:
            by.setdefault(r["sha1"], []).append(r["path"])
    for r in rows:
        dup = by.get(r["sha1"], [])
        r["dup_of"] = "" if len(dup) < 2 or dup[0] == r["path"] else dup[0]
    return rows


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("roots", nargs="+")
    ap.add_argument("-o", "--out", default="inventory")
    a = ap.parse_args()
    roots = [r for r in a.roots if os.path.isdir(r)]
    for r in a.roots:
        if r not in roots:
            print(f"[warn] フォルダが見つかりません: {r}", file=sys.stderr)
    rows = scan(roots)
    with open(a.out + ".csv", "w", newline="", encoding="utf-8-sig") as f:
        w = csv.writer(f)
        w.writerow(["分類", "CQ推定", "拡張子", "サイズ(KB)", "更新日", "重複(同一内容の先頭)", "パス"])
        for r in sorted(rows, key=lambda r: (r["kind"], r["cq"], r["path"])):
            w.writerow([r["kind"], r["cq"], r["ext"], r["size"] // 1024, r["mtime"], r["dup_of"], r["path"]])
    kinds = {}
    for r in rows:
        kinds.setdefault(r["kind"], []).append(r)
    L = [f"# ファイル棚卸し ({len(rows)}件)", ""]
    for root in roots:
        L.append(f"- {root}: {sum(1 for r in rows if r['root'] == root)}件")
    L += ["", "| 分類 | 件数 | CQ推定の内訳 |", "|---|---|---|"]
    for k, rs in sorted(kinds.items(), key=lambda kv: -len(kv[1])):
        cqs = {}
        for r in rs:
            cqs[r["cq"] or "(不明)"] = cqs.get(r["cq"] or "(不明)", 0) + 1
        L.append(f"| {k} | {len(rs)} | " + "、".join(f"{c} {n}" for c, n in sorted(cqs.items(), key=lambda x: -x[1])[:8]) + " |")
    dups = [r for r in rows if r["dup_of"]]
    L += ["", f"## 内容が同一の重複 ({len(dups)}件)", ""] + [f"- {r['path']}  = {r['dup_of']}" for r in dups[:60]]
    old = sorted(rows, key=lambda r: r["mtime"])[:15]
    L += ["", "## 更新が最も古い15件", ""] + [f"- {r['mtime']}  {r['path']}" for r in old]
    open(a.out + ".md", "w", encoding="utf-8").write("\n".join(L) + "\n")
    print(f"{len(rows)}件 → {a.out}.csv / {a.out}.md")


if __name__ == "__main__":
    main()
