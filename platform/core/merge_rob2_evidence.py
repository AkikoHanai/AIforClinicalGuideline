"""
minds_review.xlsx(委員記入済み) → CQパッケージ(JSON) へのマージ
====================================================================
委員会が埋め終えたworkbookから、evidence_schema.pyの粒度
(Study / StudyResult / EvidenceBody / Outcome)に沿ったデータを組み立てて
cq_package.json に書き戻す。この出力を review_bundle.py にかけると、
Minds規則(R1-R8)・引用PMID整合性の機械検証が実質的な意味を持つ。

読むシート(Minds 公式様式に準拠):
  CQ・PICO            … P/I/C, comparator_kind の確定値(空なら元の値を維持)
  4-5_<評価者1名>      … 様式4-5 評価シート 介入研究。アウトカムごとのブロックに、研究ごとの
  4-5_<評価者2名>        バイアスリスク10項目・非直接性5項目(0/-1/-2)、リスク人数、効果指標
  4-5_照合            … 確定列(G列)。評価者間の不一致を委員が解消した最終値。
                        空欄なら「両者一致した値」を採用し、両者不一致かつ確定も空なら
                        results[] に "_needs_reconciliation" を立てる
  4-5_Claude下書き     … 評価者2名が未入力の効果量・評価指標の補完にだけ使う(判定には使わない)
  研究特性            … 化学療法の分類・症例数・対照の内容(非直接性 対象 の判断、層別、フォレストの層別)
  SR-8_エビデンス総体  … アウトカムごとの確実性(A〜D)・5ドメイン(0/-1/-2)・重要性。層別行は参考情報
  RoB2(参考)          … Cochrane RoB 2.0 の参考評価(任意)

使い方:
  python3 merge_rob2_evidence.py <review_workspaceディレクトリ>
  (配下の */minds_review.xlsx と */cq_package.json を突き合わせて上書きする)
"""
import argparse
import glob
import json
import math
import os
import re

from openpyxl import load_workbook

from minds_forms import (C_ITEM0, HEAD_ROWS, ITEM_KEYS, ITEMS, N_ITEMS, read_45, read_sr8, to_score)

FIXED_45 = {"4-5_Claude下書き", "4-5_照合"}
DOWNGRADE_KEYS = {"bias": "risk_of_bias", "inconsistency": "inconsistency", "indirectness": "indirectness",
                  "imprecision": "imprecision", "other": "publication_bias"}
UPGRADE_KEYS = {"upgrade": "large_effect"}
EFFECT_TYPES = {"RR", "OR", "HR", "MD", "SMD", "RD", "IRR"}


def find_45_sheets(wb):
    names = [n for n in wb.sheetnames if n.startswith("4-5_") and n not in FIXED_45]
    if len(names) < 2:
        return None, None
    return names[0], names[1]


def n_rows_of(ws, blocks):
    """ブロックの行数(研究行+予備行)。ブロックが2つ以上なら間隔から、1つなら最終行から求める"""
    from minds_forms import BLOCK_GAP
    if blocks and blocks[0].get("n_rows"):
        return blocks[0]["n_rows"]
    if len(blocks) >= 2:
        return blocks[1]["start"] - blocks[0]["start"] - HEAD_ROWS - BLOCK_GAP
    return max(1, ws.max_row - blocks[0]["start"] - HEAD_ROWS - BLOCK_GAP - 1) if blocks else 0


def read_recon_final(wb):
    """4-5_照合 の確定列(G)を位置順のリストで読む。シートが無ければ None"""
    if "4-5_照合" not in wb.sheetnames:
        return None
    out = []
    for r in wb["4-5_照合"].iter_rows(min_row=2, values_only=True):
        out.append(r[6] if r is not None and len(r) > 6 else None)
    return out


def parse_ci(text):
    """'-0.68 to 4.41' / '0.4–0.9' / '0.4, 0.9' / '0.4~0.9' → (下限, 上限)"""
    t = str(text or "").replace("−", "-").replace("―", "-")
    t = re.sub(r"\s+to\s+|\s*[~〜–;,]\s*", " | ", t)
    nums = re.findall(r"-?\d+(?:\.\d+)?", t)
    if len(nums) >= 2:
        return float(nums[0]), float(nums[1])
    return None, None


def to_float(v):
    try:
        return float(str(v).replace("−", "-"))
    except (TypeError, ValueError):
        return None


def build_effect(row_main, row_alt):
    """効果量: 評価者の入力を優先、無ければ他方/Claude下書き。リスク人数からRRも計算する"""
    for r in (row_main, row_alt):
        if not r:
            continue
        typ = str(r["effect"].get("type") or "").strip().upper()
        val = to_float(r["effect"].get("value"))
        if typ in EFFECT_TYPES and val is not None:
            lo, hi = parse_ci(r["effect"].get("ci"))
            return {"measure": typ, "point": val, "ci_low": lo, "ci_high": hi}
    for r in (row_main, row_alt):
        if not r:
            continue
        c = r["counts"]
        cd, cn, idn, inn = (to_float(c.get(k)) for k in ("ctrl_den", "ctrl_num", "int_den", "int_num"))
        if None not in (cd, cn, idn, inn) and min(cd, idn) > 0 and cn > 0 and inn > 0:
            rr = (inn / idn) / (cn / cd)
            se = math.sqrt(1 / inn - 1 / idn + 1 / cn - 1 / cd)
            return {"measure": "RR", "point": rr, "ci_low": math.exp(math.log(rr) - 1.96 * se),
                    "ci_high": math.exp(math.log(rr) + 1.96 * se), "note": "リスク人数から算出"}
    return None


def instrument_of(*rows):
    for r in rows:
        if not r:
            continue
        if r.get("instrument"):
            return str(r["instrument"]).strip()
        t = str(r["effect"].get("type") or "").strip()
        if t and t.upper() not in EFFECT_TYPES:     # 2023年版担当者は X 列に尺度名を書いていた
            return t
    return None


def comparator_kind(text):
    t = (text or "").lower()
    if not t.strip():
        return None
    if "プラセボ" in t or "placebo" in t or "sham" in t or "偽" in t:
        return "placebo"
    if any(k in t for k in ("非投与", "通常", "標準", "usual", "no treatment", "観察", "なし", "対照群なし", "waitlist", "未介入")):
        return "usual_care"
    return "active_different"


def read_study_chars(wb):
    """研究特性シート → キー(PMID) → 特性"""
    out = {}
    if "研究特性" not in wb.sheetnames:
        return out
    for r in wb["研究特性"].iter_rows(min_row=2, values_only=True):
        if not r or not r[0]:
            continue
        out[str(r[0]).strip()] = {"label": r[1], "design": r[2], "country": r[3], "n_total": r[4], "n_int": r[5],
                                  "chemo_class": r[6], "chemo_drugs": r[7], "cancer": r[8], "intervention_detail": r[9],
                                  "comparator_detail": r[10], "followup": r[11], "fulltext": r[12], "note": r[13] if len(r) > 13 else None}
    return out


def read_rob2_ref(wb):
    out = {}
    if "RoB2(参考)" not in wb.sheetnames:
        return out
    for r in wb["RoB2(参考)"].iter_rows(min_row=2, values_only=True):
        if r and r[0] and any(r[2:8]):
            out[str(r[0]).strip()] = dict(zip(["D1", "D2", "D3", "D4", "D5", "overall"], r[2:8]))
    return out


def reconcile_blocks(wb, r1_name, r2_name):
    """評価者1・2のブロックを(アウトカム,キー)で突き合わせ、確定値を返す"""
    ws1, ws2 = wb[r1_name], wb[r2_name]
    b1, b2 = read_45(ws1), read_45(ws2)
    draft = read_45(wb["4-5_Claude下書き"]) if "4-5_Claude下書き" in wb.sheetnames else []
    final = read_recon_final(wb)
    n_rows = n_rows_of(ws1, b1)
    out = []
    unresolved_total = 0
    for bi, blk in enumerate(b1):
        oid = blk["outcome_id"]
        blk2 = next((x for x in b2 if x["outcome_id"] == oid), None)
        blkd = next((x for x in draft if x["outcome_id"] == oid), None)
        rows2 = {r["key"]: r for r in (blk2["rows"] if blk2 else [])}
        rowsd = {r["key"]: r for r in (blkd["rows"] if blkd else [])}
        for r1 in blk["rows"]:
            key = r1["key"]
            r2 = rows2.get(key)
            rd = rowsd.get(key)
            j = r1["row"] - blk["start"] - HEAD_ROWS
            items, unresolved = {}, []
            for k, name in enumerate(ITEM_KEYS):
                v1 = r1["items"][name]
                v2 = r2["items"][name] if r2 else None
                f = None
                if final is not None:
                    idx = (bi * n_rows + j) * N_ITEMS + k
                    if idx < len(final):
                        f = to_score(final[idx])
                if f is None:
                    if v1 is not None and v1 == v2:
                        f = v1
                    elif v1 is not None or v2 is not None:
                        unresolved.append(ITEMS[k][0])
                items[name] = f
            reviewer_entered = any(v is not None for v in items.values()) or any(
                (x["items"][n] is not None) for x in (r1, r2) if x for n in ITEM_KEYS) \
                or bool(r1["effect"]["value"] or r1["counts"]["int_den"]) or (r2 and bool(r2["effect"]["value"]))
            provisional = False
            if not reviewer_entered and rd and (any(v is not None for v in rd["items"].values()) or rd["effect"]["value"]):
                # 評価者2名が未入力の間は、Claude下書き/2023年版引継ぎの値を「下書き(未確定)」として表示に使う
                items = dict(rd["items"])
                provisional = True
            has_data = reviewer_entered or provisional
            out.append({"outcome_id": oid, "key": key, "label": r1["label"], "design": r1["design"] or (r2 or {}).get("design"),
                        "items": items, "unresolved": unresolved, "has_data": has_data, "provisional": provisional,
                        "effect": build_effect(r1, r2) or build_effect(rd, None),
                        "instrument": instrument_of(r1, r2, rd), "comment": r1.get("comment") or (r2 or {}).get("comment")})
            unresolved_total += len(unresolved)
    return out, unresolved_total


def read_existing_guidelines(wb):
    """既存GL比較シート → [{intervention, guideline, recommendation, grade, source, checked}]"""
    if "既存GL比較" not in wb.sheetnames:
        return []
    rows = []
    for r in wb["既存GL比較"].iter_rows(min_row=2, values_only=True):
        if not r or not r[0] or str(r[0]).startswith("※"):
            continue
        rows.append({"intervention": r[0], "guideline": r[1], "recommendation": r[2],
                     "grade": r[3] if len(r) > 3 else None, "source": r[4] if len(r) > 4 else None,
                     "checked": r[5] if len(r) > 5 else None})
    return rows


def read_candidates(wb, known_pmids):
    """スクリーニングログから、検索/ハンドサーチで新たに挙がった文献(=2023年版採用
    以外の行)を「採用候補」として読む。採否はレビュー画面で委員が判断する"""
    if "スクリーニングログ" not in wb.sheetnames:
        return []
    ws = wb["スクリーニングログ"]
    out = []
    for r in ws.iter_rows(min_row=2, values_only=True):
        if not r or not (r[0] or r[1]):
            continue
        pmid = str(r[0]).strip() if r[0] else ""
        if pmid.startswith("──"):
            continue
        source = r[2] or ""
        if source == "2023年版で採用済み" or (pmid and pmid in known_pmids):
            continue
        out.append({
            "pmid": pmid or None, "title": r[1] or "", "source": source,
            "primary": r[3] or "", "primary_reason": r[4] or "",
            "secondary": r[5] or "", "secondary_reason": r[6] or "",
            "note": r[7] if len(r) > 7 and r[7] else "",
        })
    return out


def read_pico(wb):
    if "CQ・PICO" not in wb.sheetnames:
        return {}
    ws = wb["CQ・PICO"]
    out = {}
    for row in ws.iter_rows(min_row=2, values_only=True):
        if not row or not row[0]:
            continue
        label, val = row[0], row[1]
        out[label] = val
    return out


def merge_one(cq_dir):
    xlsx_path = os.path.join(cq_dir, "minds_review.xlsx")
    pkg_path = os.path.join(cq_dir, "cq_package.json")
    if not (os.path.exists(xlsx_path) and os.path.exists(pkg_path)):
        return None

    wb = load_workbook(xlsx_path, data_only=True)
    pkg = json.load(open(pkg_path, encoding="utf-8"))

    r1_name, r2_name = find_45_sheets(wb)
    if not r1_name:
        print(f"  [skip] {cq_dir}: 4-5 評価者シートが2枚見つかりません(prepare_review_workspace.py --force で作り直してください)")
        return {"cq_id": pkg["cq_id"], "status": "skipped_no_45_sheets"}

    rows, unresolved_total = reconcile_blocks(wb, r1_name, r2_name)
    chars = read_study_chars(wb)
    rob2_ref = read_rob2_ref(wb)
    pico = read_pico(wb)
    known_2023 = {str(ref.get("pmid")) for ref in pkg.get("references", []) if ref.get("pmid")}
    pkg["candidates"] = read_candidates(wb, known_2023)
    egl = read_existing_guidelines(wb)
    if egl:
        pkg["existing_guidelines"] = egl

    for key, pico_key in [("P(対象)", "P"), ("I(介入)", "I"), ("C(対照)", "C")]:
        v = pico.get(key)
        if v and not str(v).startswith("(委員会で確定"):
            pkg["pico"][pico_key] = v
    ck = pico.get("comparator_kind")
    if ck:
        pkg["comparator_kind"] = ck

    # --- SR-8: outcomes[] / evidence_bodies[] / 層別 ---
    bodies, strata = ([], [])
    if "SR-8_エビデンス総体" in wb.sheetnames:
        bodies, strata = read_sr8(wb["SR-8_エビデンス総体"])
    outcomes, evidence_bodies = [], []
    n_by_outcome = {}
    for rw in rows:
        if rw["has_data"]:
            n_by_outcome.setdefault(rw["outcome_id"], set()).add(rw["key"])
    for b in bodies:
        oid = b["outcome_id"]
        outcomes.append({"id": oid, "label": b["outcome_name"], "importance": b["importance"]})
        dg = [DOWNGRADE_KEYS[k] for k in DOWNGRADE_KEYS if b.get(k) is not None and b[k] < 0]
        up = [UPGRADE_KEYS[k] for k in UPGRADE_KEYS if b.get(k) is not None and b[k] > 0]
        evidence_bodies.append({
            "id": f"EB:{b['outcome_name']}", "outcome": oid, "certainty": b["certainty"], "downgraded_by": dg, "upgraded_by": up,
            "summary": b.get("comment") or "", "_n_declared": b.get("design_n"), "_n_studies_in_45": len(n_by_outcome.get(oid, ())),
            "ratings": {k: b[k] for k in ("bias", "inconsistency", "imprecision", "indirectness", "other", "upgrade")}})
    eb_by_outcome = {eb["outcome"]: eb["id"] for eb in evidence_bodies}
    pkg["evidence_strata"] = [{"outcome_id": b["outcome_id"], "stratum": b["stratum"], "certainty": b["certainty"],
                               "ratings": {k: b[k] for k in ("bias", "inconsistency", "imprecision", "indirectness", "other")},
                               "comment": b.get("comment")} for b in strata if b["certainty"] or b.get("bias") is not None]

    # --- studies[] / results[] ---
    studies, results, seen_study = [], [], set()
    ref_in_2023 = {str(r.get("pmid")): r for r in pkg.get("references", []) if r.get("pmid")}
    for rw in rows:
        key = rw["key"]
        sid = f"S:{key}"
        ch = chars.get(key, {})
        if sid not in seen_study:
            seen_study.add(sid)
            studies.append({
                "id": sid, "pmid": key if key.isdigit() else None, "design": ch.get("design") or rw["design"],
                "title": rw["label"], "trial_ids": [],
                "cited_in_2023": key in ref_in_2023 or str(key).startswith("SR2023:"), "newly_added": not (key in ref_in_2023 or str(key).startswith(("SR2023:", "NOPMID:"))),
                "chemo_class": ch.get("chemo_class"), "chemo_drugs": ch.get("chemo_drugs"), "n_total": ch.get("n_total"),
                "n_int": ch.get("n_int"), "country": ch.get("country"), "cancer": ch.get("cancer"),
                "comparator_detail": ch.get("comparator_detail"), "intervention_detail": ch.get("intervention_detail"), "followup": ch.get("followup"), "rob2_ref": rob2_ref.get(key)})
        if not rw["has_data"]:
            continue
        oid = rw["outcome_id"]
        sm = rw["items"].get("bias_summary")
        entry = {
            "id": f"R:{key}×{oid}", "study": sid, "outcome": oid,
            "comparator": comparator_kind(ch.get("comparator_detail")), "eligible": True,
            "rob": rw["items"], "instrument": rw["instrument"], "effect": rw["effect"],
            "comment": rw["comment"], "chemo_class": ch.get("chemo_class"), "provisional": rw["provisional"],
            "contributes_to": eb_by_outcome.get(oid),
        }
        if rw["unresolved"]:
            entry["_needs_reconciliation"] = rw["unresolved"]
        results.append(entry)

    pkg["outcomes"] = outcomes
    pkg["evidence_bodies"] = evidence_bodies
    pkg["studies"] = studies
    pkg["results"] = results

    with open(pkg_path, "w", encoding="utf-8") as f:
        json.dump(pkg, f, ensure_ascii=False, indent=2)

    return {
        "cq_id": pkg["cq_id"], "status": "merged",
        "n_studies": len(studies), "n_outcomes": len(outcomes),
        "n_candidates": len(pkg["candidates"]),
        "n_unresolved_domains": unresolved_total,
        "evaluators": [r1_name, r2_name],
    }


def main():
    ap = argparse.ArgumentParser(description="委員記入済みminds_review.xlsx(4-5/SR-8) → cq_package.json マージ")
    ap.add_argument("workspace_dir")
    args = ap.parse_args()

    dirs = sorted(d for d in glob.glob(os.path.join(args.workspace_dir, "*")) if os.path.isdir(d))
    results = []
    for d in dirs:
        r = merge_one(d)
        if r:
            results.append(r)
            if r["status"] == "merged":
                flag = f" ⚠不一致未解決{r['n_unresolved_domains']}件" if r["n_unresolved_domains"] else ""
                print(f"{r['cq_id']:<28} 研究{r['n_studies']}件 アウトカム{r['n_outcomes']}件"
                      f" (評価者: {'/'.join(r['evaluators'])}){flag}")

    merged = [r for r in results if r["status"] == "merged"]
    print(f"\n{len(merged)}/{len(results)}件のCQをマージしました")
    unresolved = [r for r in merged if r["n_unresolved_domains"]]
    if unresolved:
        print(f"\n評価者間の不一致が「4-5_照合」の確定列で未解決のCQ({len(unresolved)}件):")
        for r in unresolved:
            print(f"  {r['cq_id']}: {r['n_unresolved_domains']}項目")


if __name__ == "__main__":
    main()
