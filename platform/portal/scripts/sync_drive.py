"""ポータルの提出物・出力・手順書を、Google 共有ドライブ「CIPNガイドライン作成」へ転送する(統括委員長の Mac で実行。ポータル → ドライブ)。
  python3 platform/portal/scripts/sync_drive.py <メールアドレス>
  DRIVE_DIR=<パス> python3 platform/portal/scripts/sync_drive.py <メールアドレス>     ドライブの場所を変えるとき
  python3 platform/portal/scripts/sync_drive.py <メールアドレス> --dry-run             転送する内容だけを表示する
ドライブの中の構成(なければ作る):
  提出/総論/総論<項目>_<題名>/   原稿の全ての版(<日時>_<版ID末尾>_<ファイル名>)、状態.txt(状態・期限・提出者・査読コメント)
  提出/SR/<CQ>_<名称>/           Minds書類(xlsx)、文献選択の別添(xlsx)。出力のたびに、同じ名前で置き換える(ドライブの版の履歴に残る)
  依頼書/                        総論の依頼書(Word。2023年版の全文入り)
  マニュアル/                    手順書(Word)
転送済みの版(同じ名前・同じ大きさ)は、飛ばす。転送した内容は、ポータルの「作成経過の記録」に残る。
注意: 共有ドライブのメンバーは、委員に限る(学生を含めない。委員以外に資料を見せない)。"""
import datetime, os, re, sys, urllib.request
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

DRIVE = os.environ.get("DRIVE_DIR", "/Users/ahanai/Library/CloudStorage/GoogleDrive-akiko.hanai@faculty.gs.chiba-u.jp/共有ドライブ/CIPNガイドライン作成")
safe = lambda s: re.sub(r'[\\/:*?"<>|\n\r]', "_", str(s)).strip()[:80]


def get_bytes(url):
    return urllib.request.urlopen(url, timeout=120).read()


def place(dest, data, copied, skipped, dry, overwrite=False):
    """ファイルを置く。同じ名前・同じ大きさのファイルがあれば飛ばす(overwrite=True のときは、内容が違えば置き換える)。"""
    if os.path.exists(dest) and (len(data) == os.path.getsize(dest)) and (not overwrite or open(dest, "rb").read() == data):
        skipped.append(dest); return
    if not dry:
        os.makedirs(os.path.dirname(dest), exist_ok=True)
        with open(dest + ".part", "wb") as fh: fh.write(data)
        os.replace(dest + ".part", dest)
    copied.append(dest)


def sync(tok, drive=DRIVE, dry=False, fetch=get_bytes):
    if not os.path.isdir(drive): sys.exit(f"共有ドライブのフォルダがありません: {drive}(Google Drive for desktop が同期済みか確認)")
    copied, skipped, rel = [], [], lambda p: os.path.relpath(p, drive)
    # 1. 総論の原稿(全ての版)と状態
    for s in tok.call("GET", "/soron"):
        if isinstance(s, str): break
        folder = os.path.join(drive, "提出", "総論", f"総論{s['label']}_{safe(s['title'])}")
        txt = "\n".join([f"総論{s['label']} {s['title']}", f"担当: {s.get('author', '')}", f"状態: {s.get('status', '')}", f"期限: {s.get('due', '')}", f"最新の原稿: {s.get('file', '')}({s.get('file_by', '')}、{s.get('file_at', '')})",
                         f"査読コメント({s.get('review_by', '')}、{s.get('review_at', '')}):", s.get("review", ""), f"備考: {s.get('note', '')}"]) + "\n"
        place(os.path.join(folder, "状態.txt"), txt.encode("utf-8"), copied, skipped, dry, overwrite=True)
        files = tok.call("GET", f"/soron/{s['key']}/files")
        for v in (files if isinstance(files, list) else []):
            stamp = v["at"][:19].replace("-", "").replace(":", "").replace("T", "-")                 # 秒まで + 版IDの末尾(同じ時刻の 2 つの版を、上書きしないため)
            dest = os.path.join(folder, f"{stamp}_{str(v['version'])[-6:]}_{safe(v['key'])}")
            if os.path.exists(dest) and os.path.getsize(dest) == v["size"]: skipped.append(dest); continue
            r = tok.call("GET", f"/soron/{s['key']}/download-url?v={v['version']}&name={urllib.request.quote(v['key'])}")
            if "url" in r: place(dest, fetch(r["url"]), copied, skipped, dry)
    # 2. SR の出力(CQ ごとの Minds 書類と、文献選択の別添)
    for c in tok.call("GET", "/cq"):
        folder = os.path.join(drive, "提出", "SR", f"{c['id']}_{safe(c['title'])}")
        for kind, path in (("Minds書類", f"/export/{c['id']}"), ("文献選択の別添", f"/export/{c['id']}/screening")):
            r = tok.call("GET", path)
            if "url" in r and r["url"]: place(os.path.join(folder, f"{kind}_{c['id']}.xlsx"), fetch(r["url"]), copied, skipped, dry, overwrite=True)
            elif "error" in r: print("  出力できませんでした:", c["id"], kind, r["error"])
    # 3. 依頼書(総論)と手順書
    for g in tok.call("GET", "/gl2023/soron"):
        if g.get("docx_key"):
            r = tok.call("GET", f"/soron/{g['key']}/gl2023")
            if r.get("docx_url"): place(os.path.join(drive, "依頼書", os.path.basename(g["docx_key"])), fetch(r["docx_url"]), copied, skipped, dry)
    for d in tok.call("GET", "/docs"):
        place(os.path.join(drive, "マニュアル", d["name"]), fetch(d["url"]), copied, skipped, dry)
    print(("【転送の内容の表示だけ。ファイルは置いていません】\n" if dry else "") + f"転送 {len(copied)} 件、変更なしで飛ばした {len(skipped)} 件")
    for p in copied: print("  置いた:" if not dry else "  置く:", rel(p))
    if not dry and (copied or skipped):
        tok.call("POST", "/sync/log", {"copied": len(copied), "skipped": len(skipped), "detail": "; ".join(rel(p) for p in copied)[:800]})
    return copied, skipped


if __name__ == "__main__":
    a = [x for x in sys.argv[1:] if not x.startswith("--")]
    if not a: sys.exit(__doc__)
    from admin_user import token
    sync(token(a[0]), dry="--dry-run" in sys.argv)
