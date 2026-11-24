"""ポータルの提出物・出力・手順書を、Google 共有ドライブ「CIPNガイドライン作成」へ転送する(統括委員長の Mac。ポータル → ドライブ)。
Google Drive for desktop の同期フォルダへ書き込むと、Google Drive for desktop が共有ドライブへ同期する(Apps Script など、Google 側の設定は不要。学術アカウントでよい)。
使い方(統括委員長の Mac):
  cd ~/AIforClinicalGuideline && git pull && ./fetch.sh            ポータルから共有ドライブへ転送する(場所の指定・コードの修正は要らない)
  ./fetch.sh --dry-run   置く場所と内容の表示だけ    ./fetch.sh --tree   共有ドライブのフォルダの構成を表示    ./fetch.sh --watch   30分ごとに繰り返す
直接実行するとき:
  python3 <このファイル> [メールアドレス] [--dry-run] [--tree] [--watch[=分]] [--drive <フォルダ>]
メールアドレスは、初回だけ尋ね、~/.jascc_gl_portal.json に保存する。
共有ドライブのフォルダは、自動で見つける(~/Library/CloudStorage/GoogleDrive-*/共有ドライブ/CIPNガイドライン作成。英語表示の Shared drives も)。環境変数 DRIVE_DIR か --drive で指定もできる。
ドライブの中の置き場所(共有ドライブの既存のフォルダを、深さ4まで調べる。同じ名前のフォルダがあればそこへ置き、なければ 新規ガイドライン作成/ポータル出力/ に作る。既存のフォルダの構成には作らない):
  CQ・FRQ     企画書の dir の名前(例: CQ1-牛車腎気丸、CQ2-デュロキセチン)のフォルダがあれば、その中に。なければ ポータル出力/<dir の名前>/ に、Minds書類(xlsx)、文献選択の別添(xlsx)。出力のたびに、同じ名前で置き換える(ドライブの版の履歴に残る)
  総論        「総論A」「総論I-1」などで始まるフォルダに、原稿の全ての版(<日時>_<版ID末尾>_<ファイル名>)、状態.txt(状態・期限・提出者・査読コメント)。なければ ポータル出力/総論/総論<項目>_<題名>/
  依頼書/     総論の依頼書(Word。2023年版の全文入り)
  マニュアル/<対象>/  手順書(Word)。対象(全委員、SR委員、SR委員長、作成グループ、総論の執筆者、統括委員会)ごとのフォルダに分ける
  共有ドライブの構成を確かめるには --tree[=深さ] [フォルダ名] [--files](フォルダの構成を表示する。例: --tree=4 Chap4_SR --files)。置き場所は --dry-run で、置く前に確かめられる。
転送済みの版(同じ名前・同じ大きさ)は、飛ばす。転送した内容は、ポータルの「作成経過の記録」に残る。
注意: 共有ドライブのメンバーは、委員に限る(学生を含めない。委員以外に資料を見せない)。
ポータルでは役割ごとに見える範囲を分けているが、ドライブのフォルダは、ドライブの共有設定で分ける(例: マニュアル/統括委員会 は統括委員会だけ)。
文献選択の別添と Minds書類は、各委員の判定を、その段階を 2名が判定した後だけ載せる(2名独立)。"""
import datetime, json, os, re, sys, urllib.request
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

DRIVE_NAME = "CIPNガイドライン作成"


def find_drive(home=None, name=DRIVE_NAME):
    """Google Drive for desktop の同期フォルダの中から、共有ドライブ「CIPNガイドライン作成」を見つける。見つけた場所の一覧を返す(先頭を使う)。"""
    import glob
    home = home or os.path.expanduser("~"); found = []
    for base in (os.path.join(home, "Library", "CloudStorage", "GoogleDrive-*"), "/Volumes/GoogleDrive*", os.path.join(home, "Google Drive*")):
        for shared in ("共有ドライブ", "Shared drives"):
            found += [p for p in sorted(glob.glob(os.path.join(base, shared, name))) if os.path.isdir(p)]
    return found


def drive_help(home=None):
    """見つからないときの案内(見つかった Google ドライブと、その中の共有ドライブの名前)"""
    import glob
    home = home or os.path.expanduser("~"); lines = []
    for base in sorted(glob.glob(os.path.join(home, "Library", "CloudStorage", "GoogleDrive-*"))):
        names = [x for sh in ("共有ドライブ", "Shared drives") for x in sorted(os.listdir(os.path.join(base, sh)))] if any(os.path.isdir(os.path.join(base, sh)) for sh in ("共有ドライブ", "Shared drives")) else []
        lines.append(f"  {base}  → 共有ドライブ: {', '.join(names) if names else '(なし。Google Drive for desktop の「共有ドライブ」が表示されているか確認)'}")
    return "\n".join(lines) or "  Google Drive for desktop の同期フォルダ(~/Library/CloudStorage/GoogleDrive-...)が見つかりません。アプリが起動し、ログイン済みか確認してください"


safe = lambda s: re.sub(r'[\\/:*?"<>|\n\r]', "_", str(s)).strip()[:80]


def get_bytes(url):
    return urllib.request.urlopen(url, timeout=120).read()


def place(dest, data, copied, skipped, dry, overwrite=False):
    """ファイルを置く。同じ名前・同じ大きさのファイルがあれば飛ばす(overwrite=True のときは、内容が違えば置き換える)。"""
    if os.path.exists(dest) and (len(data) == os.path.getsize(dest)) and (not overwrite or open(dest, "rb").read() == data):
        skipped.append(dest); return
    if not dry:
        os.makedirs(os.path.dirname(dest), exist_ok=True)
        with open(dest, "wb") as fh: fh.write(data)   # 一時ファイルを作らない(Google Drive for desktop が一時ファイルを同期しないように)
    copied.append(dest)


def nfc(x):
    """フォルダ名の比較用。NFD(macOS)と全角・半角の違い(SR_１ と SR_1 など)を同じとみなす。"""
    import unicodedata
    return unicodedata.normalize("NFKC", x)


class Layout:
    """共有ドライブの既存のフォルダ(ガイドラインの目次に沿った構成)を、深さ4まで調べ、置き場所を決める。既存の同名のフォルダがあれば、そこへ置く。なければ、新規ガイドライン作成/ポータル出力/ に作る(既存の構成には作らない)。"""

    def __init__(self, root, depth=4):
        self.root = root; self.dirs = []   # (比較用の名前, パス)
        def walk(path, d):
            try: names = sorted(os.listdir(path))
            except OSError: return
            for n in names:
                q = os.path.join(path, n)
                if n.startswith(".") or not os.path.isdir(q): continue
                self.dirs.append((nfc(n), q))
                if d < depth: walk(q, d + 1)
        walk(root, 1)
        # 既存の目次に沿ったフォルダ(Chap2_準備 〜 Chap8_公開後調整)を汚さないため、置き場所が決まっていないものは、ここへまとめる
        self.out = os.path.join(self.find(["新規ガイドライン作成"]) or root, "ポータル出力")

    def find(self, names, prefix=False):
        """名前が完全に一致するフォルダ(なければ、prefix=True のとき、名前で始まり、次の文字が英数字・- でないフォルダ)。浅いものを優先する。"""
        for nm in names:
            nm = nfc(nm); hit = [q for n, q in self.dirs if n == nm]
            if not hit and prefix: hit = [q for n, q in self.dirs if n.startswith(nm) and not re.match(r"[A-Za-z0-9-]", n[len(nm):len(nm) + 1] or " ")]
            if hit: return sorted(hit, key=lambda q: (q.count(os.sep), q))[0]
        return None

    def soron(self, s):
        found = self.find([f"総論{s['label']}", f"総論{s['key']}"], prefix=True)
        return found or os.path.join(self.out, "総論", f"総論{s['label']}_{safe(s['title'])}")

    def cq(self, c):
        names = c.get("dirs") or []; found = self.find(names)
        return found or os.path.join(self.out, safe((names or [f"{c['id']}_{c['title']}"])[0]))

    def top(self, name):
        return self.find([name]) or os.path.join(self.out, name)


def tree(root, depth=3, sub=None, files=False):
    """共有ドライブのフォルダの構成を表示する。sub: そのフォルダの名前(例: Chap4_SR)から表示する。files: ファイル名(各フォルダ 8件まで)も表示する。"""
    if sub:
        hit = Layout(root, depth=5).find([sub], prefix=True)
        if not hit: sys.exit(f"フォルダが見つかりません: {sub}")
        root = hit
    def walk(path, d, pre):
        try: names = sorted(x for x in os.listdir(path) if not x.startswith("."))
        except OSError: return
        dirs = [x for x in names if os.path.isdir(os.path.join(path, x))]; fl = [x for x in names if x not in dirs]
        if files:
            for x in fl[:8]: print(f"{pre}{x}")
            if len(fl) > 8: print(f"{pre}…(ほか {len(fl) - 8} ファイル)")
        for n in dirs:
            print(f"{pre}{n}/")
            if d < depth: walk(os.path.join(path, n), d + 1, pre + "  ")
    print(root); walk(root, 1, "  ")


def sync(tok, drive, dry=False, fetch=get_bytes):
    if not os.path.isdir(drive): sys.exit(f"共有ドライブのフォルダがありません: {drive}")
    copied, skipped, rel = [], [], lambda p: os.path.relpath(p, drive); L = Layout(drive)
    # 1. 総論の原稿(全ての版)と状態
    for s in tok.call("GET", "/soron"):
        if isinstance(s, str): break
        folder = L.soron(s)
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
        folder = L.cq(c)
        for kind, path in (("Minds書類", f"/export/{c['id']}"), ("文献選択の別添", f"/export/{c['id']}/screening")):
            r = tok.call("GET", path)
            if "url" in r and r["url"]: place(os.path.join(folder, f"{kind}_{c['id']}.xlsx"), fetch(r["url"]), copied, skipped, dry, overwrite=True)
            elif "error" in r: print("  出力できませんでした:", c["id"], kind, r["error"])
    # 3. 依頼書(総論)と手順書
    for g in tok.call("GET", "/gl2023/soron"):
        if g.get("docx_key"):
            r = tok.call("GET", f"/soron/{g['key']}/gl2023")
            if r.get("docx_url"): place(os.path.join(L.top("依頼書"), os.path.basename(g["docx_key"])), fetch(r["docx_url"]), copied, skipped, dry)
    for d in tok.call("GET", "/docs"):
        place(os.path.join(L.top("マニュアル"), safe(d["target"]), d["name"]), fetch(d["url"]), copied, skipped, dry)   # 対象(全委員・SR委員・総論の執筆者・統括委員会など)ごとのフォルダ
    print(("【転送の内容の表示だけ。ファイルは置いていません】\n" if dry else "") + f"転送 {len(copied)} 件、変更なしで飛ばした {len(skipped)} 件")
    for p in copied: print("  置いた:" if not dry else "  置く:", rel(p))
    if not dry and (copied or skipped):
        tok.call("POST", "/sync/log", {"copied": len(copied), "skipped": len(skipped), "detail": "; ".join(rel(p) for p in copied)[:800]})
    return copied, skipped


def settings(argv, home=None, need_email=True):
    """引数から (メールアドレス, 共有ドライブのフォルダ, オプション) を決める。"""
    home = home or os.path.expanduser("~"); conf = os.path.join(home, ".jascc_gl_portal.json")
    opts = {"dry": "--dry-run" in argv, "watch": None}
    for x in argv:
        if x == "--watch": opts["watch"] = 30
        elif x.startswith("--watch="): opts["watch"] = max(1, int(x.split("=", 1)[1]))
    pos, skip = [], False
    for k, x in enumerate(argv):
        if skip: skip = False; continue
        if x == "--drive": skip = True; continue
        if not x.startswith("--"): pos.append(x)
    drive = (argv[argv.index("--drive") + 1] if "--drive" in argv else "") or os.environ.get("DRIVE_DIR", "")
    if not drive:
        found = find_drive(home)
        if not found: sys.exit(f"共有ドライブ「{DRIVE_NAME}」の同期フォルダが見つかりません。見つかった Google ドライブ:\n{drive_help(home)}")
        drive = found[0]
        if len({os.path.realpath(x) for x in found}) > 1: print("共有ドライブが複数見つかりました。最初のものを使います:", *found, sep="\n  ")
    cfg = json.load(open(conf, encoding="utf-8")) if os.path.exists(conf) else {}
    email = (pos[0] if pos else "") or os.environ.get("JASCC_EMAIL", "") or cfg.get("email", "")
    if not email and not need_email: return "", drive, opts
    if not email:
        email = input("ポータルのメールアドレス(統括委員会のもの。初回だけ尋ねます): ").strip()
    if email and cfg.get("email") != email:
        cfg["email"] = email; json.dump(cfg, open(conf, "w", encoding="utf-8"), ensure_ascii=False)
    return email, drive, opts


def main(argv, session=None, fetch=get_bytes, home=None):
    tr = [x for x in argv if x == "--tree" or x.startswith("--tree=")]
    if tr:
        rest = [x for x in argv if x not in tr]; depth = int(tr[0].split("=", 1)[1]) if "=" in tr[0] else 3
        _, drive, _ = settings([x for x in rest if x != "--files"], home, need_email=False)
        pos = [x for x in rest if not x.startswith("--") and x != drive and "@" not in x]; return tree(drive, depth, pos[0] if pos else None, "--files" in rest)
    email, drive, opts = settings(argv, home); print(f"共有ドライブ: {drive}\nポータルの利用者: {email}")
    if session is None:
        sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
        from admin_user import Session
        session = Session
    import time
    while True:
        try: sync(session(email), drive, dry=opts["dry"], fetch=fetch)
        except SystemExit: raise
        except Exception as e:
            if not opts["watch"]: raise
            print("転送に失敗しました(次の回に再び試します):", e)
        if not opts["watch"]: return
        print(f"{opts['watch']}分後に、もう一度転送します(止めるときは Ctrl+C)"); time.sleep(opts["watch"] * 60)


if __name__ == "__main__":
    if "-h" in sys.argv or "--help" in sys.argv: sys.exit(__doc__)
    main(sys.argv[1:])
