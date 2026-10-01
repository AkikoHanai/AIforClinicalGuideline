"""SR統括ファイル(2023年版作成時の担当者別パッケージ)を、改訂作業の CQ 構成に整理する

  python3 platform/core/organize_sr_files.py "<SR統括ファイル>" -o "<整理後の出力先>" [--move]

- zip と展開済みフォルダの二重化は、内容(SHA1)が同じなら1つにまとめる
- 運動・鍼灸は予防(CQ1)と治療(CQ2)の共通ファイルなので両方のCQフォルダに置く
- 出力: <out>/<CQ>/<役割>/<ファイル>  と  <out>/整理インデックス.md / .csv
- 既定はコピー(元は触らない)。--move は元を移動(確認後に使う)
役割: 00_SCOPE / 01_検索 / 02_研究の一覧(エビデンス表) / 03_バイアス・質評価 / 04_データ抽出シート / 05_推奨文 / 06_論文PDF / 09_その他
"""
import argparse
import collections
import csv
import hashlib
import os
import re
import shutil
import sys
import unicodedata
import zipfile

# フォルダ名のキーワード → 改訂ワークスペースの CQ ディレクトリ(複数可)
FOLDER_TO_CQ = [
    ("牛車腎気丸", ["CQ1-牛車腎気丸"]),
    ("カルニチン", ["CQ1-カルニチン-アセチル‒L‒カルニチン"]),
    ("冷却および圧迫", ["CQ1-冷却・圧迫"]),
    ("薬物予防_ガバペン", ["CQ1-プレガバリン"]),
    ("薬物治療_ガバペン", ["CQ2-プレガバリン", "CQ2-ミロガバリン"]),
    ("デュロキセチン", ["CQ2-デュロキセチン"]),
    ("VB12", ["CQ2-ビタミン-B12"]),
    ("NSAIDs", ["CQ2-非ステロイド性消炎鎮痛薬-NSAIDs"]),
    ("併用療法", ["CQ2-薬物の併用療法"]),
    ("運動療法", ["CQ1-運動", "CQ2-運動"]),
    ("_鍼_", ["CQ1-鍼灸", "CQ2-鍼灸"]),
]
ROOT_FILE_TO_CQ = [("運動", "予防", ["CQ1-運動"]), ("運動", "治療", ["CQ2-運動"])]
ROLES = [
    ("00_SCOPE", r"scope"),
    ("05_推奨文", r"推奨文"),
    ("01_検索", r"検索|search|データベース"),
    ("02_研究の一覧(エビデンス表)", r"研究の一覧|研究一覧"),
    ("03_バイアス・質評価", r"バイアス|quality|質評価|評価シート|リスク表"),
    ("04_データ抽出シート", r"データシート|データ抽出"),
    ("06_論文PDF", r"\.pdf$"),
]


def nfc(s):
    """macOSのファイル名はNFD(濁点が分離)なので、キーワード照合の前にNFCへ揃える"""
    return unicodedata.normalize("NFC", s)


def zip_name(info):
    """UTF-8フラグの無いzipの日本語名をcp437誤読から復元"""
    n = info.filename
    if not (info.flag_bits & 0x800):
        try:
            n = n.encode("cp437").decode("utf-8")
        except (UnicodeEncodeError, UnicodeDecodeError):
            pass
    return nfc(n)


def sha1(b):
    return hashlib.sha1(b).hexdigest()


def role_of(name):
    low = name.lower()
    if low.endswith(".pdf") and not re.search(r"quality|質評価", low):
        return "06_論文PDF"
    for role, pat in ROLES:
        if re.search(pat, low):
            return role
    return "09_その他"


def collect(root):
    """(相対パス, bytes, 所属パッケージ名) を、zip の中身も含めて列挙。内容が同じものは重複として記録"""
    items = []
    for dp, dns, fns in os.walk(root):
        dns[:] = [d for d in dns if d != "__MACOSX"]
        for fn in fns:
            if fn == ".DS_Store" or fn.startswith("~$") or fn.startswith("._"):
                continue
            p = os.path.join(dp, fn)
            rel = nfc(os.path.relpath(p, root))
            pkg = rel.split(os.sep)[0]
            if fn.lower().endswith(".zip"):
                try:
                    z = zipfile.ZipFile(p)
                    for info in z.infolist():
                        n = zip_name(info)
                        if n.endswith("/") or "__MACOSX" in n or n.endswith(".DS_Store"):
                            continue
                        items.append((rel + "!" + n, z.read(info), re.sub(r"\.zip$", "", pkg).replace(" (1)", "")))
                except zipfile.BadZipFile:
                    print(f"[warn] 壊れたzip: {rel}", file=sys.stderr)
            else:
                items.append((rel, open(p, "rb").read(), pkg))
    return items


def targets_for(rel, name, pkg):
    key = pkg
    if os.sep not in rel and "!" not in rel:       # ルート直下の単独ファイル
        for kw, tag, cqs in ROOT_FILE_TO_CQ:
            if kw in name and tag in name:
                return cqs
        return ["_未分類"]
    for kw, cqs in FOLDER_TO_CQ:
        if kw in key:
            return cqs
    return ["_未分類"]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("sr_dir")
    ap.add_argument("-o", "--out", required=True)
    ap.add_argument("--move", action="store_true", help="(未実装の安全策) 常にコピーします")
    a = ap.parse_args()
    items = collect(a.sr_dir)
    seen = {}        # sha1 -> 代表の (cq, role, name)
    rows, n_dup = [], 0
    placed = set()
    for rel, data, pkg in sorted(items, key=lambda x: x[0]):
        name = os.path.basename(rel.split("!")[-1])
        name = re.sub(r"\[\d+\]", "", name)   # 「[23][88]」のような修正履歴番号は名前から除く
        name = re.sub(r"\s+\.", ".", name).replace("  ", " ")
        h = sha1(data)
        role = role_of(name)
        cqs = targets_for(rel, name, pkg)
        key = (h, tuple(cqs))      # 同じ内容でも別CQのパッケージにあれば、それぞれのCQに置く
        if key in seen:
            n_dup += 1
            rows.append([",".join(cqs), role, name, "重複(同一内容)", rel]); continue
        seen[key] = True
        for cq in cqs:
            d = os.path.join(a.out, cq, role)
            os.makedirs(d, exist_ok=True)
            dest = os.path.join(d, name)
            if dest in placed and sha1(open(dest, "rb").read()) != h:   # 同名別内容は連番
                base, ext = os.path.splitext(name); i = 2
                while os.path.exists(os.path.join(d, f"{base}_v{i}{ext}")):
                    i += 1
                dest = os.path.join(d, f"{base}_v{i}{ext}")
            if not os.path.exists(dest):
                open(dest, "wb").write(data)
            placed.add(dest)
            rows.append([cq, role, os.path.basename(dest), "配置", rel])
    os.makedirs(a.out, exist_ok=True)
    with open(os.path.join(a.out, "整理インデックス.csv"), "w", newline="", encoding="utf-8-sig") as f:
        w = csv.writer(f); w.writerow(["CQ", "役割", "ファイル", "状態", "元の場所"]); w.writerows(rows)
    by = collections.defaultdict(lambda: collections.defaultdict(list))
    for cq, role, name, st, rel in rows:
        if st == "配置":
            by[cq][role].append(name)
    L = [f"# SR統括ファイル 整理インデックス", "", f"元 {len(items)}件(zip内を含む) → 重複 {n_dup}件を除き {sum(len(v) for r in by.values() for v in r.values())}件を配置", ""]
    for cq in sorted(by):
        L += [f"## {cq}", ""]
        for role in sorted(by[cq]):
            L.append(f"- **{role}**: " + " / ".join(by[cq][role]))
        L.append("")
    open(os.path.join(a.out, "整理インデックス.md"), "w", encoding="utf-8").write("\n".join(L))
    print(f"配置完了: {a.out}  (元{len(items)}件 / 重複{n_dup}件)")


if __name__ == "__main__":
    main()
