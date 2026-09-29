"""
minds_review.xlsx(委員記入済み) → CQパッケージ(JSON) へのマージ
====================================================================
委員会が下記を埋め終えたworkbookから、evidence_schema.pyの粒度
(Study / StudyResult / EvidenceBody / Outcome)に沿ったデータを組み立てて
cq_package.json に書き戻す。この出力を review_bundle.py にかけると、
Minds規則(R1-R8)・引用PMID整合性の機械検証が実質的な意味を持つ。

読むシート:
  CQ・PICO           … P/I/C, comparator_kind の確定値(空なら元の値を維持)
  RoB2_<評価者1名>    … PMID・研究・対応アウトカムID・デザイン・comparator・
                        適格性・RoB2の5ドメイン+総合(直接入力、数式ではない)
  RoB2_<評価者2名>    … 同上(2人目)
  RoB2_照合           … 確定列(G列)。評価者間の不一致を委員が解消した最終値。
                        空欄なら「両者一致した値」を採用し、両者不一致かつ
                        確定も空なら studies[]に "_needs_reconciliation" フラグを立てる
  エビデンス総体評価    … アウトカムごとの確実性・格下げ理由・研究数

シート名は openpyxl で動的に取得する(RoB2_評価者シート2枚を「RoB2_」接頭辞で
検出。prepare_review_workspace.py が作るCQ・PICO/エビデンス総体評価等の
固定名シートは除外)。

使い方:
  python3 merge_rob2_evidence.py <review_workspaceディレクトリ>
  (配下の */minds_review.xlsx と */cq_package.json を突き合わせて上書きする)
"""
import argparse
import glob
import json
import os
import re

from openpyxl import load_workbook

FIXED_SHEETS = {"検索式", "CQ・PICO", "スクリーニングログ", "RoB2_照合",
                 "エビデンス総体評価", "文献リスト", "投票", "SoF"}
ROB2_DOMAIN_LABELS = ["D1 ランダム化の過程", "D2 意図した介入からの逸脱",
                       "D3 アウトカムデータの欠測", "D4 アウトカム測定",
                       "D5 選択的な結果報告", "総合(Overall)"]
DOWNGRADE_KEYS = ["risk_of_bias", "inconsistency", "indirectness",
                   "imprecision", "publication_bias"]


def find_rob2_sheets(wb):
    names = [s for s in wb.sheetnames if s.startswith("RoB2_") and s not in FIXED_SHEETS]
    if len(names) < 2:
        return None, None
    return names[0], names[1]


def read_rob2_rows(ws):
    """PMID列が埋まっている行だけ、位置順(生成時と同じ順序)で読む"""
    rows = []
    for r in ws.iter_rows(min_row=2, values_only=True):
        if not r or not r[0]:
            continue
        pmid, citation, outcome_id, design, comparator, eligible = r[:6]
        domains = r[6:12]  # D1..D5, Overall
        rows.append({
            "pmid": str(pmid), "citation": citation, "outcome_id": outcome_id,
            "design": design, "comparator": comparator, "eligible": eligible,
            "domains": list(domains),
        })
    return rows


def reconcile(rows1, rows2, recon_final):
    """評価者1/2の行を突き合わせ、確定値(recon_final: 位置順のフラットリスト、
    無ければNone)を優先しつつマージ済みのRoB2行リストを返す"""
    n = min(len(rows1), len(rows2))
    if len(rows1) != len(rows2):
        print(f"  [warn] 評価者1({len(rows1)}行)と評価者2({len(rows2)}行)の行数が"
              f"一致しません。先頭{n}行のみ突合します(行の追加・削除がずれていないか確認してください)")
    merged = []
    for i in range(n):
        r1, r2 = rows1[i], rows2[i]
        final_domains, unresolved = [], []
        for j in range(6):
            v1, v2 = r1["domains"][j], r2["domains"][j]
            final = None
            if recon_final is not None:
                idx = i * 6 + j
                if idx < len(recon_final) and recon_final[idx]:
                    final = recon_final[idx]
            if final is None:
                if v1 == v2 and v1:
                    final = v1
                elif v1 or v2:
                    unresolved.append(ROB2_DOMAIN_LABELS[j])
            final_domains.append(final)
        merged.append({
            "pmid": r1["pmid"],
            "citation": r1["citation"] or r2["citation"],
            "outcome_id": r1["outcome_id"] or r2["outcome_id"],
            "design": r1["design"] or r2["design"],
            "comparator": r1["comparator"] or r2["comparator"],
            "eligible": r1["eligible"] or r2["eligible"],
            "domains": final_domains,
            "_unresolved_domains": unresolved,
        })
    return merged


def read_recon_final_column(wb):
    """RoB2_照合シートの確定列(G, 7列目)を位置順のフラットリストで読む。
    シートが無ければ None"""
    if "RoB2_照合" not in wb.sheetnames:
        return None
    ws = wb["RoB2_照合"]
    out = []
    for r in ws.iter_rows(min_row=2, values_only=True):
        if r is None:
            continue
        out.append(r[6] if len(r) > 6 else None)
    return out


def read_evidence_body_rows(wb):
    if "エビデンス総体評価" not in wb.sheetnames:
        return []
    ws = wb["エビデンス総体評価"]
    rows = []
    for r in ws.iter_rows(min_row=2, values_only=True):
        if not r or not r[0]:
            continue
        outcome_id, outcome_name, importance, n_studies, certainty = r[:5]
        downgrades = r[5:10]
        summary = r[10] if len(r) > 10 else None
        dg_keys = [DOWNGRADE_KEYS[i] for i, v in enumerate(downgrades) if v]
        rows.append({
            "outcome_id": outcome_id, "outcome_name": outcome_name,
            "importance": importance, "n_studies": n_studies,
            "certainty": (certainty or "").strip().upper() or None,
            "downgraded_by": dg_keys, "summary": summary or "",
        })
    return rows


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

    r1_name, r2_name = find_rob2_sheets(wb)
    if not r1_name:
        print(f"  [skip] {cq_dir}: RoB2評価者シートが2枚見つかりません")
        return {"cq_id": pkg["cq_id"], "status": "skipped_no_rob2_sheets"}

    rows1 = read_rob2_rows(wb[r1_name])
    rows2 = read_rob2_rows(wb[r2_name])
    recon_final = read_recon_final_column(wb)
    merged_rows = reconcile(rows1, rows2, recon_final)

    eb_rows = read_evidence_body_rows(wb)
    pico = read_pico(wb)

    # --- PICO/comparator_kindの確定値があれば反映(空欄なら既存値を維持) ---
    for key, pico_key in [("P(対象)", "P"), ("I(介入)", "I"), ("C(対照)", "C")]:
        v = pico.get(key)
        if v and not str(v).startswith("(委員会で確定"):
            pkg["pico"][pico_key] = v
    ck = pico.get("comparator_kind")
    if ck:
        pkg["comparator_kind"] = ck

    # --- outcomes[] / evidence_bodies[] ---
    outcomes, evidence_bodies = [], []
    for eb in eb_rows:
        oid = eb["outcome_id"] or f"O:{eb['outcome_name']}"
        outcomes.append({"id": oid, "label": eb["outcome_name"],
                          "importance": eb["importance"]})
        evidence_bodies.append({
            "id": f"EB:{eb['outcome_name']}", "outcome": oid,
            "certainty": eb["certainty"], "downgraded_by": eb["downgraded_by"],
            "summary": eb["summary"], "_n_declared": eb["n_studies"],
        })
    eb_by_outcome_id = {eb["outcome"]: eb["id"] for eb in evidence_bodies}

    # --- studies[] / results[] ---
    studies, results, unresolved_total = [], [], 0
    for row in merged_rows:
        sid = f"S:{row['pmid']}"
        studies.append({
            "id": sid, "pmid": row["pmid"], "design": row["design"],
            "title": row["citation"], "trial_ids": [],
        })
        oid = row["outcome_id"]
        rob2 = dict(zip(
            ["D1", "D2", "D3", "D4", "D5", "overall"], row["domains"]))
        rid = f"R:{row['pmid']}×{oid or '?'}"
        entry = {
            "id": rid, "study": sid, "outcome": oid,
            "comparator": row["comparator"], "eligible": bool(row["eligible"]),
            "rob2": rob2,
            "contributes_to": eb_by_outcome_id.get(oid) if row["eligible"] else None,
        }
        if row["_unresolved_domains"]:
            entry["_needs_reconciliation"] = row["_unresolved_domains"]
            unresolved_total += len(row["_unresolved_domains"])
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
        "n_unresolved_domains": unresolved_total,
        "evaluators": [r1_name, r2_name],
    }


def main():
    ap = argparse.ArgumentParser(description="委員記入済みminds_review.xlsx → cq_package.json マージ")
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
        print(f"\n評価者間の不一致が「RoB2_照合」の確定列で未解決のCQ({len(unresolved)}件):")
        for r in unresolved:
            print(f"  {r['cq_id']}: {r['n_unresolved_domains']}ドメイン")


if __name__ == "__main__":
    main()
