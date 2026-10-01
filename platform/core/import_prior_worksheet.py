"""2023年版作成時の委員ワークシート(検索ログ・RoB表・エビデンス表)を minds_review.xlsx に取り込む

  python3 platform/core/import_prior_worksheet.py review_workspace platform/prior_worksheets/*.json

書き込み先:
  検索式            … 「2023年版の検索記録」行(DB・期間・検索式・件数)
  スクリーニングログ … 2023年版の除外/採用内訳を1行のメモとして
  研究特性          … デザイン・化学療法の薬剤と分類(薬剤名から推定)・症例数・対照の内容
  4-5_Claude下書き   … 2023年版のバイアス評価(✔/?/－)を 4-5 様式の 0/-1/-2 に変換して記入
                        (2023年版は Minds 4-5 様式を使っていたので項目がそのまま対応する)。
                        結果要約と、リスク人数から計算できる RR・95%CI も記入(フォレストプロットに出る)
既に委員が書いた欄は上書きしない。評価者シート(4-5_<名前>)には書かない(独立二重評価のため)。
"""
import argparse
import glob
import json
import math
import os

from openpyxl import load_workbook

from minds_forms import (C_CODE, C_COMMENT, C_CTRL_DEN, C_CTRL_NUM, C_EFF_CI, C_EFF_TYPE, C_EFF_VAL, C_INT_DEN, C_INT_NUM, C_ITEM0,
                         ITEM_KEYS, add_study_all_blocks, classify_chemo, read_45)

DRAFT = "4-5_Claude下書き"
FIXED_45 = {DRAFT, "4-5_照合"}
CHAR = {"key": 1, "label": 2, "design": 3, "n_total": 5, "n_int": 6, "chemo_class": 7, "chemo_drugs": 8, "comparator_detail": 11, "note": 14}
# 2023年版の旧RoB表の項目 → 4-5 の項目キー
ROB1_TO_45 = {"ランダム化": "randomization", "隠蔽": "concealment", "盲検化": "blinding_participants",
              "測定者盲検": "blinding_assessors", "ITT": "itt"}


def rr_ci(a, n1, c, n2):
    if min(a, c) == 0 or a > n1 or c > n2:
        return None
    rr = (a / n1) / (c / n2)
    se = math.sqrt(1 / a - 1 / n1 + 1 / c - 1 / n2)
    return rr, math.exp(math.log(rr) - 1.96 * se), math.exp(math.log(rr) + 1.96 * se)


def _mark_to_score(m):
    """2023年版の表記 ✔(行われている)=0 / ?(可能性)=-1 / －(行われていない)=-2 を 4-5 の値に"""
    m = str(m or "").strip()
    if m[:1] in ("✔", "✓", "レ", "○", "◯", "√"):
        return 0
    if m[:1] in ("?", "？"):
        return -1
    if m[:1] in ("－", "ー", "−", "-", "―", "×", "x", "X"):
        return -2
    return None


def _find_chars_row(ws, pmid=None, label=None, year=None):
    """研究特性シートで、PMID → ラベルの姓(どの語でも可)+年(±2年: 電子版と紙版のずれ)の順に探す"""
    import re as _re
    for r in range(2, ws.max_row + 1):
        if pmid and str(ws.cell(row=r, column=1).value or "").strip() == str(pmid):
            return r
    if not label:
        return None
    words = [w.lower() for w in _re.findall(r"[A-Za-z\u00C0-\u024F][A-Za-z\u00C0-\u024F'\-]{2,}", label) if w.lower() not in ("et", "al")]
    if year is None:
        m = _re.search(r"(19|20)\d\d", label)
        year = int(m.group(0)) if m else None
    for r in range(2, ws.max_row + 1):
        v = str(ws.cell(row=r, column=CHAR["label"]).value or "").lower()
        if not v or not any(w in v for w in words):
            continue
        ym = _re.search(r"(19|20)\d\d", v)
        if year is None or (ym and abs(int(ym.group(0)) - int(year)) <= 2):
            return r
    return None


def _first_free(ws):
    last = 1
    for r in range(2, ws.max_row + 1):
        if ws.cell(row=r, column=1).value:
            last = r
    return last + 1


def _add_study(wb, st):
    """2023年版のSR表にあるが文献リスト(PMID付き)に無い研究を、4-5の全シート(同じ位置)と研究特性に追加"""
    import re as _re
    key = "SR2023:" + _re.sub(r"[^A-Za-z0-9]+", "", st.get("surname") or st.get("label", ""))[:20] + str(st.get("year") or "")
    names = [n for n in wb.sheetnames if n.startswith("4-5_") and n != "4-5_照合"]
    for n in names:
        add_study_all_blocks(wb[n], key, st.get("label"), st.get("design"))
    ws = wb["研究特性"]
    r = _find_chars_row(ws, key)
    if r is None:
        r = _first_free(ws)
        c = ws.cell(row=r, column=CHAR["note"])
        if c.value and str(c.value).startswith("(新規論文は"):
            c.value = None
        ws.cell(row=r, column=CHAR["key"], value=key)
        ws.cell(row=r, column=CHAR["label"], value=st.get("label"))
        ws.cell(row=r, column=CHAR["note"], value="2023年版のSR表にあり、文献リストにPMIDなし(PMIDを確認して記入)")
    return key, r


def _append_comment(ws, row, text):
    c = ws.cell(row=row, column=C_COMMENT)
    if c.value and text in str(c.value):
        return
    c.value = (str(c.value) + " / " if c.value else "") + text


def _write_study(wb, key, st):
    """研究特性と4-5下書き(全アウトカムブロックの当該研究行)に書き込む"""
    chars = wb["研究特性"]
    r = _find_chars_row(chars, key)
    def put(name, val):
        if val not in (None, "") and chars.cell(row=r, column=CHAR[name]).value in (None, ""):
            chars.cell(row=r, column=CHAR[name], value=val)
    put("design", st.get("design"))
    put("chemo_drugs", st.get("drug"))
    if st.get("drug"):
        put("chemo_class", classify_chemo(st["drug"]))
    put("n_total", st.get("n_total"))
    put("n_int", st.get("n_int"))
    put("comparator_detail", st.get("comparator"))
    draft = wb[DRAFT]
    rob = st.get("rob_2023") or {}
    e = st.get("effect_from_2023")
    ci = rr_ci(e["events_int"], st["n_int"], e["events_ctrl"], st["n_ctrl"]) if (e and st.get("n_int") and st.get("n_ctrl")) else None
    for blk in read_45(draft):
        row = next((x["row"] for x in blk["rows"] if x["key"] == str(wb["研究特性"].cell(row=r, column=1).value)), None)
        if not row:
            continue
        for k, v in rob.items():
            name = ROB1_TO_45.get(k)
            sc = _mark_to_score(v)
            if name and sc is not None and draft.cell(row=row, column=C_ITEM0 + ITEM_KEYS.index(name)).value in (None, ""):
                draft.cell(row=row, column=C_ITEM0 + ITEM_KEYS.index(name), value=sc)
        if rob:
            _append_comment(draft, row, "2023年版のバイアス評価(旧表記✔/?/－)を引継ぎ。アウトカム別に要見直し"
                            + (f"。その他: {rob['その他']}" if rob.get("その他") else ""))
        if st.get("result_2023"):
            _append_comment(draft, row, "2023年版の結果要約: " + str(st["result_2023"]))
        if st.get("external_quality"):
            _append_comment(draft, row, st["external_quality"])
        if st.get("n_text") or st.get("drug") or st.get("comparator"):
            _append_comment(draft, row, "2023年版の研究表: " + " / ".join(x for x in [
                f"症例数 {st['n_text']}" if st.get("n_text") else "", f"誘発薬 {st['drug']}" if st.get("drug") else "",
                f"対照 {st['comparator']}" if st.get("comparator") else ""] if x))
        # 効果量: 発症頻度のアウトカムのブロックだけに(2×2が分かる研究)
        if ci and ("発症" in str(blk["outcome_label"]) or len(read_45(draft)) == 1) \
                and draft.cell(row=row, column=C_EFF_VAL).value in (None, ""):
            rr, lo, hi = ci
            draft.cell(row=row, column=C_INT_DEN, value=st["n_int"])
            draft.cell(row=row, column=C_INT_NUM, value=e["events_int"])
            draft.cell(row=row, column=C_CTRL_DEN, value=st["n_ctrl"])
            draft.cell(row=row, column=C_CTRL_NUM, value=e["events_ctrl"])
            draft.cell(row=row, column=C_EFF_TYPE, value="RR")
            draft.cell(row=row, column=C_EFF_VAL, value=round(rr, 3))
            draft.cell(row=row, column=C_EFF_CI, value=f"{lo:.2f} to {hi:.2f}")
            _append_comment(draft, row, f"効果量はリスク人数から計算({e.get('note', '')}) 要原著確認")


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
    ss = spec.get("searches_2023")
    if ss and "検索式" in wb.sheetnames:
        ws = wb["検索式"]
        if not any("2023年版の検索記録" in str(ws.cell(row=r, column=1).value or "") for r in range(1, ws.max_row + 1)):
            ws.append([])
            for i, x in enumerate(ss, 1):
                tag = f"2023年版の検索記録{i}" if len(ss) > 1 else "2023年版の検索記録"
                ws.append([tag, f"{x.get('database') or 'PubMed'} / 期間: {x.get('period_text', '')}"])
                if x.get("query"):
                    ws.append([f"  検索式", x["query"]])
                if x.get("flow_lines"):
                    ws.append(["  件数・除外の流れ", " / ".join(x["flow_lines"])])
            if spec.get("last_search_end_2023"):
                ws.append(["→ 今回(改訂)の検索の起点", f"{spec['last_search_end_2023']} 以降〜現在 ※前回の検索終了日。検索期間の起点は委員会で確認"])
            if spec.get("note"):
                ws.append(["注意", spec["note"]])
    if s and "スクリーニングログ" in wb.sheetnames:
        ws = wb["スクリーニングログ"]
        memo = ("2023年版: " + "、".join(f"{k} {v}件" for k, v in (s.get("excluded") or {}).items()) + " を除外; 採用 "
                + "、".join(f"{k} {v}件" for k, v in (s.get("included") or {}).items()))
        if not any("2023年版:" in str(ws.cell(row=r, column=2).value or "") for r in range(1, ws.max_row + 1)):
            ws.append(["", memo, "2023年版の記録(委員ワークシートより)"])
    n = 0
    if DRAFT in wb.sheetnames and "研究特性" in wb.sheetnames:
        for st in spec.get("studies", []):
            r = _find_chars_row(wb["研究特性"], st.get("pmid"), st.get("label"), st.get("year"))
            key = str(wb["研究特性"].cell(row=r, column=1).value) if r else None
            if not r:
                if spec.get("add_missing") and (st.get("result_2023") or st.get("rob_2023")):
                    key, r = _add_study(wb, st)
                if not r:
                    continue
            _write_study(wb, key, st)
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
            spec = json.load(open(f, encoding="utf-8"))
            if spec.get("cq_dir") == "*":   # 全CQに対して、ラベルが一致する研究だけ取り込む
                for d in sorted(glob.glob(os.path.join(a.workspace_dir, "CQ*"))):
                    import_one(a.workspace_dir, dict(spec, cq_dir=os.path.basename(d), quiet=True))
            else:
                import_one(a.workspace_dir, spec)


if __name__ == "__main__":
    main()
