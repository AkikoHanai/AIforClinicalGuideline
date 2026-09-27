"""
CIPN診療ガイドライン(JASCC 2023年版) → CQパッケージ 抽出器
================================================================
対象: 『がん薬物療法に伴う末梢神経障害診療ガイドライン 2023年版』
      （日本がんサポーティブケア学会編）第3章「クリニカルクエスチョンと推奨」。

extract_from_pdf.py との違い:
  extract_from_pdf.py は「本文の推奨」「付録エビデンス総体表」「付録評価シート」の
  3か所が独立した刊行ガイドライン(がんサバイバーシップ運動ガイドライン等)を想定していた。
  本ガイドラインには独立した総体表・評価シートが無く、推奨文・強さ/確実性・解説・
  投票結果・文献が「介入(薬剤/手技)ごとに1ブロック」としてまとまっている。

構造:
  CQ1(予防) / CQ2(治療)
    └ 1．薬物療法による予防／治療  (category)
        └ 1）牛車腎気丸           (intervention)
            推奨文 → 強さ/確実性/合意率 → 解説 → 投票結果 → 文献(PMID)
        └ 2）プレガバリン
    └ 2．非薬物療法による予防／治療
        └ 1）冷却
        ...

出力方針:
  介入(薬剤/手技)ごとに1つのCQパッケージを作る(CQ-DEMOと同じ粒度)。
  evidence_bodies / studies / results は空のまま出力する。
  これらはROB2に基づき学生が別途構築中の評価シートを
  merge_rob2_evidence.py でマージして埋める設計（本抽出器の責務ではない）。

依存: pdftotext (poppler)。テキスト層のないPDFには使えない。
"""
import argparse
import json
import os
import re
import subprocess
import unicodedata

HERE = os.path.dirname(os.path.abspath(__file__))

CERT_MAP = {"強": "A", "中": "B", "弱": "C", "非常に弱い": "D", "非常に弱": "D"}
JP_CHAR = r"[぀-ヿ一-鿿＀-￯]"

# 注意: norm()はNFKC正規化までかけるため、比較対象の正規表現は
# 全角(．（）／：，)ではなく正規化後のASCII(.()/:,)で書く
CATEGORY_RE = re.compile(r"^\s*(\d)\.(薬物療法|非薬物療法)による(予防|治療)\s*$")
INTERVENTION_RE = re.compile(r"^\s*(\d+)\)\s*(\S.*\S|\S)\s*$")
CQ_SECTION_RE = re.compile(r"^CQ([12])\.\s")

SECTION_KEYWORDS = {"推奨文", "解説", "投票結果", "文献"}


# ------------------------------------------------------------------
def pdftotext(pdf, first=None, last=None):
    cmd = ["pdftotext"]
    if first is not None:
        cmd += ["-f", str(first)]
    if last is not None:
        cmd += ["-l", str(last)]
    cmd += ["-layout", pdf, "-"]
    r = subprocess.run(cmd, capture_output=True, text=True, check=True)
    return r.stdout


def find_page(pdf, needle, start_page=1, max_pages=140):
    """指定文字列(空白無視)が現れる最初の物理ページ番号を返す。

    空白を全部無視して部分一致を見るため、短い/ありふれた文字列だと
    無関係な前付け(委員一覧など)に偶然一致することがある。
    それを避けるため探索開始ページ(start_page)を必ず絞って呼ぶこと。
    """
    target = needle.replace(" ", "").replace("　", "")
    for pg in range(start_page, max_pages + 1):
        try:
            t = pdftotext(pdf, pg, pg)
        except subprocess.CalledProcessError:
            break
        if target in t.replace(" ", "").replace("　", ""):
            return pg
    return None


def norm(s: str) -> str:
    """全角記号・空白の正規化"""
    s = (s.replace("　", " ").replace("～", "~").replace("，", ",")
           .replace("（", "(").replace("）", ")")
           .replace("：", ":").replace("／", "/").replace("、", ","))
    return unicodedata.normalize("NFKC", s).strip()


def is_japanese(ch: str) -> bool:
    return bool(re.match(JP_CHAR, ch))


def join_text(lines):
    """行を1文にまとめる。日本語同士の境界の空白は消し、英数字は空白を残す"""
    s = " ".join(l.strip() for l in lines if l.strip())
    prev = None
    for _ in range(6):
        s2 = re.sub(rf"({JP_CHAR}) ({JP_CHAR})", r"\1\2", s)
        if s2 == prev:
            break
        prev, s = s, s2
    return re.sub(r"\s+", " ", s).strip()


# ------------------------------------------------------------------
# 介入ブロックへの分割
# ------------------------------------------------------------------
CQ_OF_CATEGORY = {"予防": "CQ1", "治療": "CQ2"}


def split_blocks(text):
    """章テキスト全体(CQ1+CQ2)を介入ごとの生データブロックに分割する。

    CQ1/CQ2をページ範囲で別々に抽出して2回呼ぶと、両者の境界ページで
    文章が割れてブロックが壊れる(観測済みの実際の不具合)。そのため
    本文全体を1回のpdftotext呼び出しで取得し、ここで1回だけ処理する。
    cqはカテゴリ見出し("...による予防/治療")の末尾から判定する。
    """
    lines = text.splitlines()
    blocks = []
    cur = None          # 現在組み立て中のブロック
    cur_cq = None
    cur_category = None
    pending_name = None  # 直近に見た"N)text"行。次の推奨文の介入名として使う
    state = None

    def flush():
        if cur and cur.get("推奨文"):
            blocks.append(cur)

    for raw in lines:
        line = raw
        s = norm(line)

        m = CQ_SECTION_RE.match(s)
        if m:
            cur_cq = f"CQ{m.group(1)}"
            continue

        m = CATEGORY_RE.match(s)
        if m:
            # 各CQの詳細セクションの直前に、複数介入分の推奨文＋強さ箱だけを
            # 「解説」抜きで並べた概要ページがある(実データで確認済み)。
            # そこでは1個の"推奨文"の後にヘッダ行が来るまで解説に辿り着かない
            # ままなので、state="推奨文"のまま新しい見出しに突入したら
            # 直前のcurは概要ページの残骸として破棄する。
            if state == "推奨文":
                cur = None
            cur_category = f"{m.group(2)}による{m.group(3)}"
            cur_cq = CQ_OF_CATEGORY[m.group(3)]
            pending_name = None
            continue

        # ページフッタ・縦組みの柱(欄外に"第\n3\n章\nクリニカルクエスチョンと推奨"が
        # 独立した行として挟まる)等のノイズは無視。捨てずに読み込むと
        # ページ境界をまたぐ推奨文の途中に"第"などが混入し正規表現照合が壊れる
        if (re.match(r"^CQ\d/\d\.", s) or re.match(r"^\d+\s+第\d章", s)
                or s in ("第3章", "第", "クリニカルクエスチョンと推奨")
                or re.match(r"^\d\s*章$", s)):
            continue

        m = INTERVENTION_RE.match(s)
        if m and s not in SECTION_KEYWORDS:
            if state == "推奨文":  # 同上: 概要ページの残骸を破棄
                cur = None
            # 文献行("1）Nishioka M, ...")も同じ"N)text"の形をしているが、
            # 直後に"推奨文"が来た時点のpending_nameだけが介入名として採用される
            # (=文献リストの最後の行のNo.が次の介入番号1)と偶然一致しても、
            #  その次の実際の見出し行で必ず上書きされるので実害はない)
            pending_name = re.sub(r"[.．…\s]{2,}\d*$", "", m.group(2)).strip()
            continue

        if s == "推奨文":
            flush()
            cur = {"cq": cur_cq, "category": cur_category,
                   "intervention": pending_name, "推奨文": [], "解説": [],
                   "投票結果": [], "文献": []}
            pending_name = None
            state = "推奨文"
            continue

        if cur is None:
            continue

        if s == "解説":
            state = "解説"
            continue
        if s == "投票結果":
            state = "投票結果"
            continue
        if s == "文献":
            state = "文献"
            continue

        if state in cur:
            cur[state].append(line)

    flush()
    return blocks


# ------------------------------------------------------------------
# ブロック内の詳細抽出
# ------------------------------------------------------------------
STRENGTH_RE = re.compile(
    r"(?P<num>[1-5])(?P<cert>[ABCD])\s*推奨の強さ\s*:\s*[1-5]\s*\((?P<slabel>[^)]+)\)\s*,?\s*"
    r"エビデンスの確実性\s*:\s*[ABCD]\s*\((?P<clabel>[^)]+)\)\s*,?\s*"
    r"合意率\s*(?P<pct>\d+)\s*%\s*\((?P<n>\d+)\s*/\s*(?P<total>\d+)\)")

PANEL_SIZE_RE = re.compile(r"(\d+)\s*名\s*\(棄権")

PMID_RE = re.compile(r"PMID\s*:\s*(\d+)")


def parse_block(b):
    # 表示用は全角のまま保持し、正規表現照合にだけ正規化版を使う。
    # norm()の変換はすべて1文字→1文字(全角記号→半角/NFKC)なので、
    # 正規化後の一致位置(インデックス)を生テキストの切れ目にそのまま使ってよい。
    rec_raw = join_text(b["推奨文"])
    rec_norm = norm(rec_raw)
    m = STRENGTH_RE.search(rec_norm)
    rec_text = rec_raw[: m.start()].strip() if m else rec_raw

    rationale = join_text(b["解説"])
    vote_joined = norm(join_text(b["投票結果"]))
    pm = PANEL_SIZE_RE.search(vote_joined)

    refs_text = "\n".join(b["文献"])
    pmids = PMID_RE.findall(norm(refs_text))

    out = {
        "cq": b["cq"], "category": b["category"], "intervention": b["intervention"],
        "recommendation_text": rec_text,
        "rationale_text": rationale,
        "cited_pmids": sorted(set(pmids), key=pmids.index),
        "n_references": len(re.findall(r"^\s*\d+）", "\n".join(b["文献"]), re.M)),
        "_raw_references": [l.strip() for l in b["文献"] if l.strip()],
        "_parse_warnings": [],
    }
    if m:
        out["strength_number"] = m.group("num")
        out["strength_label"] = m.group("slabel")
        out["certainty"] = m.group("cert")
        out["certainty_label"] = m.group("clabel")
        out["agreement_rate"] = int(m.group("pct")) / 100
        out["agreement_n"] = int(m.group("n"))
        out["agreement_total"] = int(m.group("total"))
    else:
        out["_parse_warnings"].append("推奨の強さ/エビデンスの確実性/合意率の行を検出できなかった")
    if pm:
        out["panel_size"] = int(pm.group(1))
    if not out["intervention"]:
        out["_parse_warnings"].append("介入名(見出し)を検出できなかった")
    if not pmids:
        out["_parse_warnings"].append("引用PMIDが1件も見つからなかった")

    return out


def slugify(cq, name):
    name = re.sub(r"[（）()/／\s]+", "-", name).strip("-")
    return f"{cq}-{name}"


def to_package(rec, source_pdf):
    strength_map = {"1": "1", "2": "2", "3": "3", "4": "4", "5": "5"}
    direction_map = {"1": "for_strong", "2": "for", "3": "none",
                      "4": "against", "5": "against_strong"}
    cq_id = slugify(rec["cq"], rec["intervention"] or "unknown")
    return {
        "_source": {
            "pdf": os.path.basename(source_pdf),
            "extracted_by": "extract_cipn_guideline.py",
            "cq": rec["cq"], "category": rec["category"],
            "intervention": rec["intervention"],
            "注意": ("刊行GL本文からの自動抽出。エビデンス総体・個別研究(studies/results/"
                    "evidence_bodies)は未入力。学生が構築中のROB2評価シートを"
                    "merge_rob2_evidence.py でマージして埋める。"),
            "parse_warnings": rec["_parse_warnings"],
        },
        "cq_id": cq_id,
        "title": f"{rec['cq']} {rec['category']}: {rec['intervention']}",
        "comparator_kind": "none",
        "pico": {"P": "", "I": rec["intervention"] or "", "C": "", "O": []},
        "outcomes": [],
        "evidence_bodies": [],
        "studies": [],
        "includes": [],
        "results": [],
        "draft": {
            "_note": "刊行版(2023年版)の推奨をそのまま入れたもの（AI生成ではない）。"
                     "改訂時はここをPhase1出力(Bedrock)で置き換える",
            "generated_by": "published_guideline_2023",
            "recommendation_text": rec["recommendation_text"],
            "direction": direction_map.get(rec.get("strength_number"), None),
            "strength": strength_map.get(rec.get("strength_number")),
            "strength_label": rec.get("strength_label"),
            "certainty": rec.get("certainty"),
            "certainty_label": rec.get("certainty_label"),
            "cited_pmids": rec["cited_pmids"],
            "mentioned_outcomes": [],
            "panel_vote": {
                "n_panel": rec.get("panel_size"),
                "agreement_rate": rec.get("agreement_rate"),
                "agreement_n": rec.get("agreement_n"),
                "agreement_total": rec.get("agreement_total"),
                "_note": "5択の内訳(誰が何%)は本抽出器では未パース。合意率のみ",
            },
        },
        "narrative": rec["rationale_text"],
    }


# ------------------------------------------------------------------
def build_all(pdf, rec_pages):
    text = pdftotext(pdf, *rec_pages)
    blocks = split_blocks(text)
    recs = [parse_block(b) for b in blocks]
    pkgs = [to_package(r, pdf) for r in recs]

    report = {"pdf": os.path.basename(pdf), "rec_pages": list(rec_pages),
               "n_interventions": len(pkgs), "items": []}
    all_pmids = {}
    for r, p in zip(recs, pkgs):
        report["items"].append({
            "cq_id": p["cq_id"], "intervention": r["intervention"],
            "strength": r.get("strength_number"), "certainty": r.get("certainty"),
            "n_cited_pmids": len(r["cited_pmids"]),
            "warnings": r["_parse_warnings"],
        })
        for pmid in r["cited_pmids"]:
            all_pmids.setdefault(pmid, []).append(p["cq_id"])
    report["pmids_cited_in_multiple_cqs"] = {
        k: v for k, v in all_pmids.items() if len(v) > 1}
    return pkgs, report


def main():
    ap = argparse.ArgumentParser(description="CIPN診療ガイドライン(2023) → CQパッケージ群")
    ap.add_argument("pdf")
    ap.add_argument("--rec-pages", nargs=2, type=int, default=None,
                     help="第3章(推奨)の物理ページ範囲。省略時は自動検出")
    ap.add_argument("-o", "--outdir", default=os.path.join(HERE, "..", "data", "cq"))
    args = ap.parse_args()

    if args.rec_pages:
        rec_pages = tuple(args.rec_pages)
    else:
        cq1_start = find_page(args.pdf, "1．薬物療法による予防", start_page=1)
        cq2_end = find_page(args.pdf, "平山泰生先生を偲んで", start_page=cq1_start) \
            or (cq1_start + 40)
        rec_pages = (cq1_start, cq2_end - 1)

    pkgs, report = build_all(args.pdf, rec_pages)

    os.makedirs(args.outdir, exist_ok=True)
    for p in pkgs:
        fp = os.path.join(args.outdir, f"{p['cq_id']}.json")
        with open(fp, "w", encoding="utf-8") as f:
            json.dump(p, f, ensure_ascii=False, indent=2)
    rp = os.path.join(args.outdir, "_extraction_report.cipn.json")
    with open(rp, "w", encoding="utf-8") as f:
        json.dump(report, f, ensure_ascii=False, indent=2)

    print(f"介入 {report['n_interventions']} 件を抽出 → {args.outdir}/")
    for it in report["items"]:
        w = f"  [!] {'; '.join(it['warnings'])}" if it["warnings"] else ""
        print(f"  {it['cq_id']:<28} 強さ{it['strength']} 確実性{it['certainty']} "
              f"PMID{it['n_cited_pmids']}件{w}")
    if report["pmids_cited_in_multiple_cqs"]:
        print("\n複数CQで引用されているPMID(二重計上チェックの参考):")
        for pmid, cqs in report["pmids_cited_in_multiple_cqs"].items():
            print(f"  PMID {pmid}: {', '.join(cqs)}")


if __name__ == "__main__":
    main()
