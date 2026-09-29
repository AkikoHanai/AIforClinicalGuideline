"""2023年版作成時の委員ワークシート(検索ログ・RoB表・エビデンス表)を minds_review.xlsx に取り込む

  python3 platform/core/import_prior_worksheet.py review_workspace platform/prior_worksheets/*.json

書き込み先:
  検索式            … 「2023年版の検索記録」行(DB・期間・検索式・件数)
  スクリーニングログ … 2023年版の除外/採用内訳を1行のメモとして
  RoB2_Claude下書き  … 各PMID行: デザイン/対照/備考に「2023年版RoB(RoB1)」と結果要約、
                        2×2 が分かる研究は RR と95%CI を「効果:」として追記(フォレストプロットに出る)
既に委員が書いた欄は上書きしない。
"""
import argparse
import glob
import json
import math
import os

from openpyxl import load_workbook

ROB2_COL = {"pmid": 1, "cite": 2, "outcome_id": 3, "design": 4, "comparator": 5, "note": 15}
ROB1_TO_ROB2 = {"ランダム化": "D1", "隠蔽": "D1", "盲検化": "D2", "測定者盲検": "D4", "ITT": "D3", "その他": "D5/その他"}


def rr_ci(a, n1, c, n2):
    if min(a, c) == 0 or a > n1 or c > n2:
        return None
    rr = (a / n1) / (c / n2)
    se = math.sqrt(1 / a - 1 / n1 + 1 / c - 1 / n2)
    return rr, math.exp(math.log(rr) - 1.96 * se), math.exp(math.log(rr) + 1.96 * se)


def _find_row(ws, pmid):
    for r in range(2, ws.max_row + 1):
        if str(ws.cell(row=r, column=1).value or "").strip() == str(pmid):
            return r
    return None


def _append_note(ws, r, text):
    c = ws.cell(row=r, column=ROB2_COL["note"])
    if c.value and text in str(c.value):
        return
    c.value = (str(c.value) + " / " if c.value else "") + text


def import_one(ws_dir, spec):
    cq_dir = os.path.join(ws_dir, spec["cq_dir"])
    xlsx = os.path.join(cq_dir, "minds_review.xlsx")
    if not os.path.exists(xlsx):
        print(f"  [skip] {xlsx} がありません"); return
    wb = load_workbook(xlsx)
    s = spec.get("search_2023")
    if s and "検索式" in wb.sheetnames:
        ws = wb["検索式"]
        if not any("2023年版の検索記録" in str(ws.cell(row=r, column=1).value or "") for r in range(1, ws.max_row + 1)):
            ws.append([]); ws.append(["2023年版の検索記録", f"{s.get('database')} / 期間 {s.get('period')} / {s.get('hits')}件"])
            ws.append(["2023年版の検索式", s.get("query")])
            ws.append(["→ 今回の検索期間", f"{s.get('period', '').split('–')[-1]} 以降〜現在(前回検索の終了時点から)"])
    if s and "スクリーニングログ" in wb.sheetnames:
        ws = wb["スクリーニングログ"]
        memo = ("2023年版: " + "、".join(f"{k} {v}件" for k, v in (s.get("excluded") or {}).items()) + " を除外; 採用 "
                + "、".join(f"{k} {v}件" for k, v in (s.get("included") or {}).items()))
        if not any("2023年版:" in str(ws.cell(row=r, column=2).value or "") for r in range(1, ws.max_row + 1)):
            ws.append(["", memo, "2023年版の記録(委員ワークシートより)"])
    draft = wb["RoB2_Claude下書き"] if "RoB2_Claude下書き" in wb.sheetnames else None
    n = 0
    if draft is not None:
        for st in spec.get("studies", []):
            r = _find_row(draft, st["pmid"])
            if not r:
                print(f"  [warn] {st['pmid']} {st.get('label')} は下書きシートにありません"); continue
            for key, col in (("design", "design"), ("comparator", "comparator")):
                if st.get(key) and not draft.cell(row=r, column=ROB2_COL[col]).value:
                    draft.cell(row=r, column=ROB2_COL[col]).value = st[key]
            rob = st.get("rob_2023")
            if rob:
                _append_note(draft, r, "2023年版RoB(RoB1): " + "、".join(f"{k}{v}(→{ROB1_TO_ROB2.get(k, '')})" for k, v in rob.items()))
            if st.get("result_2023"):
                _append_note(draft, r, "2023年版の結果要約: " + st["result_2023"])
            e = st.get("effect_from_2023")
            if e and st.get("n_int") and st.get("n_ctrl"):
                ci = rr_ci(e["events_int"], st["n_int"], e["events_ctrl"], st["n_ctrl"])
                if ci:
                    rr, lo, hi = ci
                    _append_note(draft, r, f"効果: RR {rr:.2f} ({lo:.2f}–{hi:.2f}) [{e['outcome']}; {e['events_int']}/{st['n_int']} vs {e['events_ctrl']}/{st['n_ctrl']}; {e.get('note', '')}]")
            n += 1
    wb.save(xlsx)
    print(f"{spec['cq_dir']}: {n}研究を取り込み")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("workspace_dir")
    ap.add_argument("specs", nargs="+")
    a = ap.parse_args()
    for pat in a.specs:
        for f in glob.glob(pat):
            import_one(a.workspace_dir, json.load(open(f, encoding="utf-8")))


if __name__ == "__main__":
    main()
