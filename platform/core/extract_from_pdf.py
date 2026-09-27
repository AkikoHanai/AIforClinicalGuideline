"""
刊行ガイドラインPDF → CQパッケージ 抽出器
==========================================
対象: Minds様式で付録に「エビデンス総体」「エビデンスの評価シート」を載せている和文GL。
（検証に使ったのは『がんサバイバーシップガイドライン 身体活動・運動編』第1版）

3か所から別々に取って、突き合わせるのが要点。

  本文の推奨セクション   → 推奨文・推奨の強さ・確実性・アウトカムごとの記述・投票結果
  付録 エビデンス総体表   → アウトカムごとの 研究数/格下げドメイン/統合値/確実性/重要度
  付録 評価シート        → 論文 × アウトカム の個別研究行（StudyResultの素になる）

同じ数値が3か所に書かれているので、一致しなければ抽出ミスか原本の不整合。
どちらであれ委員に出す前に気づく必要がある。→ extraction_report に出す。

依存: pdftotext (poppler)。テキスト層のないPDFには使えない。
"""
import argparse
import json
import os
import re
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))

CERT_MAP = {"強": "A", "中": "B", "弱": "C", "非常に弱": "D", "とても弱い": "D"}
DOMAINS = ["risk_of_bias", "inconsistency", "imprecision", "indirectness", "publication_bias"]


def pdftotext(pdf, first, last):
    r = subprocess.run(["pdftotext", "-f", str(first), "-l", str(last), "-layout", pdf, "-"],
                       capture_output=True, text=True, check=True)
    return r.stdout


def norm(s):
    """全角スペース・記号を素朴に正規化"""
    return (s.replace("　", " ").replace("～", "~").replace("，", ",")
             .replace("（", "(").replace("）", ")").strip())


# ------------------------------------------------------------------
# 1. 本文の推奨セクション
# ------------------------------------------------------------------
def parse_recommendation(text, cq_label="CQ1"):
    out = {"cq_id": cq_label, "outcomes_text": {}, "panel_vote": None}
    t = norm(text)

    m = re.search(r"1\s*\)\s*CQ\s*(.+?)\s*2\s*\)\s*推奨文\s*(.+?)\s*推奨の強さ\s*[:：]\s*(\S+)"
                  r"\s*エビデンスの強さ\s*[:：]\s*([ABCD])", t, re.S)
    if m:
        out["cq_text"] = re.sub(r"\s+", "", m.group(1))
        out["recommendation_text"] = re.sub(r"\s+", "", m.group(2))
        out["strength_label"] = m.group(3)
        out["certainty"] = m.group(4)

    # アウトカムごとの段落
    for blk in re.finditer(r"アウトカム\s*(\d+)\s*[:：]\s*(\S[^\n]*)\n(.*?)(?=アウトカム\s*\d+\s*[:：]|"
                           r"〈推奨とエビデンスの強さ〉|$)", t, re.S):
        no, name, body = blk.group(1), re.sub(r"\s+", "", blk.group(2)), blk.group(3)
        b = re.sub(r"\s+", "", body)
        rec = {"no": int(no), "name": name}
        m = re.search(r"ランダム化比較試験\s*(\d+)\s*件", b)
        if m:
            rec["n_studies"] = int(m.group(1))
        # 「-0.74~-0.26」の区切りを、負号を食わずに取る
        m = re.search(r"(SMD|HR|RR|MD)\s*(-?[\d.]+)[,、]?\s*95%信頼区間\s*"
                      r"(-?[\d.]+)\s*[~–—]\s*(-?[\d.]+)", b)
        if m:
            rec["effect"] = {"measure": m.group(1), "point": float(m.group(2)),
                             "ci_low": float(m.group(3)), "ci_high": float(m.group(4))}
        m = re.search(r"I.?[²2]は(\d+)%", b)
        if m:
            rec["i2"] = int(m.group(1))
        m = re.search(r"エビデンスの強さは[\"“”']?(強|中|弱|非常に弱|とても弱い)", b)
        if m:
            rec["certainty"] = CERT_MAP[m.group(1)]
        out["outcomes_text"][name] = rec

    m = re.search(r"投票の結果[,、].*?(\d+)\s*名中\s*(\d+)\s*名が「(.+?)」[,、]?\s*(\d+)\s*名が「(.+?)」に投票"
                  r"[,、]\s*(\d+)\s*%の合意", re.sub(r"\s+", "", t))
    if m:
        out["panel_vote"] = {
            "n_panel": int(m.group(1)),
            "distribution": {"1": int(m.group(2)), "2": int(m.group(4))},
            "agreement_rate": int(m.group(6)) / 100,
        }
    return out


# ------------------------------------------------------------------
# 2. 付録「エビデンス総体」
# ------------------------------------------------------------------
def parse_evidence_total(text, cq_label="CQ 1"):
    """アウトカム行: 名称 デザイン/研究数 [5ドメイン] ... 効果指標 統合値 信頼区間 確実性 重要性"""
    rows, cur = [], None
    for line in text.splitlines():
        s = norm(line)
        m = re.match(r"^(?:\d+\s+)?(CQ ?\d)\s*$", s)
        if m:
            cur = m.group(1).replace(" ", "")
            continue
        if cur != cq_label.replace(" ", ""):
            continue
        m = re.match(r"^(?:\d+\s+)?(\S+?)\s+(RCT|観察研究|コホート)/(\d+)\s+(.*)$", s)
        if not m:
            continue
        name, design, n, rest = m.group(1), m.group(2), int(m.group(3)), m.group(4)
        toks = rest.split()
        doms = []
        i = 0
        while i < len(toks) and re.fullmatch(r"-?[012]", toks[i]) and len(doms) < 5:
            doms.append(int(toks[i]))
            i += 1
        me = re.search(r"\b(SMD|HR|RR|MD|OR)\b\s+(-?[\d.]+)\s+(-?[\d.]+)\s*to\s*(-?[\d.]+)", rest)
        cert = re.search(r"(非常に弱|強|中|弱)\((A|B|C|D)\)", rest)
        imp = re.search(r"\((?:A|B|C|D)\)\s+(\d)\b", rest)
        rows.append({
            "outcome": name, "design": design, "n_studies": n,
            "domains": dict(zip(DOMAINS, doms + [0] * (5 - len(doms)))),
            "effect": ({"measure": me.group(1), "point": float(me.group(2)),
                        "ci_low": float(me.group(3)), "ci_high": float(me.group(4))}
                       if me else None),
            "certainty": cert.group(2) if cert else None,
            "importance": int(imp.group(1)) if imp else None,
            "_raw": s,
        })
    return rows


# ------------------------------------------------------------------
# 3. 付録「エビデンスの評価シート」
# ------------------------------------------------------------------
STUDY_ROW = re.compile(r"^(?:\d+\s+)?(?P<code>[A-Z][^\s].*?[a-z]+.*?,\s*\d{4}[^\s]*(?:\s*\([^)]*\))?)"
                       r"\s+(?P<design>RCT|観察研究|コホート|準RCT)\s+(?P<rest>.*)$")


def parse_assessment_sheets(text, cq_label="CQ 1"):
    """アウトカム見出しで区切り、個別研究行を拾う"""
    sections, cur_cq, cur_oc = {}, None, None
    for line in text.splitlines():
        s = norm(line)
        m = re.match(r"^(?:\d+\s+)?(CQ ?\d)\s*$", s)
        if m:
            cur_cq = m.group(1).replace(" ", "")
            continue
        m = re.match(r"^アウトカム\s{2,}(\S.*)$", s)
        if m:
            cur_oc = re.sub(r"\s+", "", m.group(1))
            if cur_cq == cq_label.replace(" ", ""):
                sections.setdefault(cur_oc, [])
            continue
        if cur_cq != cq_label.replace(" ", "") or cur_oc is None:
            continue
        m = STUDY_ROW.match(s)
        if m:
            code = re.sub(r"\s+", " ", m.group("code")).strip()
            sections[cur_oc].append({"code": code, "design": m.group("design").lower(),
                                     "_raw": s[:400]})
    return sections


# ------------------------------------------------------------------
# 突き合わせ + パッケージ組み立て
# ------------------------------------------------------------------
def match_outcome(name, candidates):
    """『QoL（FACT，QLQ-C30，SF-36）』と『QOL』のような表記揺れを吸収"""
    base = re.sub(r"\(.*?\)", "", name)
    bl = base.lower()
    for c in candidates:
        cb = re.sub(r"\(.*?\)", "", c)
        cl = cb.lower()
        if bl == cl or bl in cl or cl in bl:      # QoL / QOL / 健康関連QoL を同一視
            return c
    alias = {"全生存時間": "全生存期間", "全生存期間": "全生存時間",
             "筋力": "筋力", "有害事象": "有害事象"}
    a = alias.get(base)
    if a:
        for c in candidates:
            if a in c:
                return c
    return None


def build_package(pdf, cq="CQ1", rec_pages=(21, 30), total_pages=(146, 147),
                  sheet_pages=(130, 146)):
    rec = parse_recommendation(pdftotext(pdf, *rec_pages), cq)
    totals = parse_evidence_total(pdftotext(pdf, *total_pages), f"CQ {cq[-1]}")
    sheets = parse_assessment_sheets(pdftotext(pdf, *sheet_pages), f"CQ {cq[-1]}")

    report = {"cq": cq, "checks": [], "counts": {}}
    outcomes, bodies, studies, results = [], [], {}, []

    for row in totals:
        oid = f"O:{row['outcome']}"
        outcomes.append({"id": oid, "label": row["outcome"],
                         "importance": row["importance"]})
        dg = [d for d, v in row["domains"].items() if v < 0]
        eb = {"id": f"EB:{row['outcome']}", "outcome": oid,
              "certainty": row["certainty"], "downgraded_by": dg,
              "summary": (f"{row['design']} {row['n_studies']}件。"
                          + (f"{row['effect']['measure']} {row['effect']['point']}"
                             f"（95%CI {row['effect']['ci_low']}–{row['effect']['ci_high']}）"
                             if row["effect"] else "統合値なし")),
              "_pooled": row["effect"], "_n_declared": row["n_studies"]}
        bodies.append(eb)

        # 評価シートの個別研究と件数照合
        sheet_key = match_outcome(row["outcome"], list(sheets.keys()))
        rows = sheets.get(sheet_key, []) if sheet_key else []
        report["counts"][row["outcome"]] = {
            "総体表の研究数": row["n_studies"],
            "評価シートの行数": len(rows),
            "評価シート見出し": sheet_key,
        }
        if sheet_key is None:
            report["checks"].append({
                "level": "warn", "outcome": row["outcome"],
                "detail": "エビデンス総体表のアウトカムに対応する評価シートが見つからない"})
        elif len(rows) != row["n_studies"]:
            codes = [r["code"] for r in rows]
            dup = sorted({c for c in codes if codes.count(c) > 1})
            report["checks"].append({
                "level": "warn", "outcome": row["outcome"],
                "detail": f"研究数が一致しない: 総体表 {row['n_studies']}件 / "
                          f"評価シート {len(rows)}行。"
                          + (f"同一論文が複数行に出ている（多腕・複数尺度）: {'、'.join(dup)}"
                             if dup else
                             "評価シートには載るがメタ解析に寄与しない研究がある可能性"
                             "（例: イベント0件で推定不能）"),
                "duplicated_codes": dup})

        for r in rows:
            sid = f"S:{r['code']}"
            studies.setdefault(sid, {"id": sid, "pmid": None, "design": r["design"],
                                     "title": r["code"], "trial_ids": [],
                                     "_source": "評価シート"})
            rid = f"R:{r['code']}×{row['outcome']}"
            if any(x["id"] == rid for x in results):
                rid += f"#{sum(1 for x in results if x['id'].startswith(rid))+1}"
            results.append({"id": rid, "study": sid, "outcome": oid,
                            "comparator": None, "eligible": True,
                            "contributes_to": eb["id"],
                            "_needs_human": ["comparator"]})

    # 本文 ↔ 総体表 の数値照合
    for name, tx in rec["outcomes_text"].items():
        tkey = match_outcome(name, [r["outcome"] for r in totals])
        row = next((r for r in totals if r["outcome"] == tkey), None)
        if not row:
            report["checks"].append({"level": "warn", "outcome": name,
                                     "detail": "本文のアウトカムが総体表に見つからない"})
            continue
        if tx.get("n_studies") and tx["n_studies"] != row["n_studies"]:
            report["checks"].append({
                "level": "block", "outcome": name,
                "detail": f"研究数が本文と総体表で不一致: 本文 {tx['n_studies']}件 / "
                          f"総体表 {row['n_studies']}件"})
        if tx.get("effect") and row["effect"]:
            a, b = tx["effect"], row["effect"]
            if abs(a["point"] - b["point"]) > 0.005 or abs(a["ci_low"] - b["ci_low"]) > 0.005:
                report["checks"].append({
                    "level": "block", "outcome": name,
                    "detail": f"統合値が本文と総体表で不一致: 本文 {a['measure']} {a['point']}"
                              f"（{a['ci_low']}–{a['ci_high']}）/ 総体表 {b['measure']} "
                              f"{b['point']}（{b['ci_low']}–{b['ci_high']}）"})
        if tx.get("certainty") and row["certainty"] and tx["certainty"] != row["certainty"]:
            report["checks"].append({
                "level": "block", "outcome": name,
                "detail": f"確実性が本文と総体表で不一致: 本文 {tx['certainty']} / "
                          f"総体表 {row['certainty']}"})

    strength = {"弱": "2", "強": "1"}.get(rec.get("strength_label"), rec.get("strength_label"))
    pkg = {
        "_source": {
            "pdf": os.path.basename(pdf),
            "extracted_by": "extract_from_pdf.py",
            "pages": {"推奨": list(rec_pages), "エビデンス総体": list(total_pages),
                      "評価シート": list(sheet_pages)},
            "注意": "刊行PDFからの自動抽出。対照の種類・適格性・PMIDは未入力（人手で補う）",
        },
        "cq_id": cq,
        "title": rec.get("cq_text", ""),
        "comparator_kind": "none",
        "pico": {"P": "", "I": "", "C": "", "O": [o["label"] for o in outcomes]},
        "outcomes": outcomes,
        "evidence_bodies": bodies,
        "studies": sorted(studies.values(), key=lambda x: x["id"]),
        "includes": [],
        "results": results,
        "draft": {
            "_note": "刊行版の推奨をそのまま入れたもの（AI生成ではない）。改訂時はここをPhase1出力で置き換える",
            "generated_by": "published_guideline",
            "recommendation_text": rec.get("recommendation_text", ""),
            "direction": "for",
            "strength": strength,
            "certainty": rec.get("certainty"),
            "cited_pmids": [],
            "mentioned_outcomes": [],
            "panel_vote": rec.get("panel_vote"),
        },
        "narrative": "",
    }
    report["extracted"] = {"outcomes": len(outcomes), "studies": len(studies),
                           "results": len(results)}
    return pkg, report


def main():
    ap = argparse.ArgumentParser(description="刊行GL PDF → CQパッケージ")
    ap.add_argument("pdf")
    ap.add_argument("--cq", default="CQ1")
    ap.add_argument("--rec-pages", nargs=2, type=int, default=[21, 30])
    ap.add_argument("--total-pages", nargs=2, type=int, default=[146, 147])
    ap.add_argument("--sheet-pages", nargs=2, type=int, default=[130, 146])
    ap.add_argument("-o", "--outdir", default=os.path.join(HERE, "..", "data", "cq"))
    args = ap.parse_args()

    pkg, rep = build_package(args.pdf, args.cq, tuple(args.rec_pages),
                             tuple(args.total_pages), tuple(args.sheet_pages))
    os.makedirs(args.outdir, exist_ok=True)
    p = os.path.join(args.outdir, f"{args.cq}.json")
    with open(p, "w", encoding="utf-8") as f:
        json.dump(pkg, f, ensure_ascii=False, indent=2)
    r = os.path.join(args.outdir, f"{args.cq}.extraction_report.json")
    with open(r, "w", encoding="utf-8") as f:
        json.dump(rep, f, ensure_ascii=False, indent=2)

    print(f"抽出: アウトカム{rep['extracted']['outcomes']}件 / "
          f"論文{rep['extracted']['studies']}件 / 結果{rep['extracted']['results']}件 → {p}")
    for name, c in rep["counts"].items():
        print(f"  {name}: 総体表{c['総体表の研究数']}件 / 評価シート{c['評価シートの行数']}行")
    if rep["checks"]:
        print("\n照合で見つかった不一致:")
        for c in rep["checks"]:
            print(f"  [{c['level']}] {c['outcome']}: {c['detail']}")
    else:
        print("照合: 不一致なし")


if __name__ == "__main__":
    main()
