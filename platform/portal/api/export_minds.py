"""ポータルの記録から、CQ ごとの Minds 書類(xlsx)を作る。
シート: 研究特性 / 様式4-5(確定。アウトカムごとのブロック) / 様式SR-8 / SoF表 / EtD・推奨 / 作成経過
数値は記録のまま。統合値(メタアナリシス)は計算しない(確定は SR チームの協議による)。"""
import io
import openpyxl
from openpyxl.styles import Alignment, Border, Font, PatternFill, Side

ITEM_JA = ["ランダム化", "コンシールメント", "盲検化(参加者・医療提供者)", "盲検化(アウトカム評価者)", "ITT", "アウトカム不完全報告", "選択的アウトカム報告", "早期試験中止", "その他のバイアス", "バイアスリスク まとめ",
           "非直接性 対象", "非直接性 介入", "非直接性 対照", "非直接性 アウトカム", "非直接性 まとめ"]
ITEM_KEYS = ["randomization", "concealment", "blinding_participants", "blinding_assessors", "itt", "incomplete_outcome", "selective_reporting", "early_stopping", "other_bias", "bias_summary",
             "ind_population", "ind_intervention", "ind_comparator", "ind_outcome", "ind_summary"]
SR8 = [("rob", "バイアスリスク"), ("inconsistency", "非一貫性"), ("imprecision", "不精確性"), ("indirectness", "非直接性"), ("publication_bias", "その他(出版バイアス)"), ("upgrade", "上昇要因"), ("certainty", "エビデンスの確実性")]
THIN = Side(style="thin", color="000000"); BD = Border(left=THIN, right=THIN, top=THIN, bottom=THIN)


def style(ws, header_rows=1, widths=None):
    for row in ws.iter_rows():
        for c in row:
            c.border = BD; c.alignment = Alignment(wrap_text=True, vertical="top")
    for r in range(1, header_rows + 1):
        for c in ws[r]:
            c.font = Font(bold=True); c.fill = PatternFill("solid", fgColor="D9D9D9")
    for i, w in enumerate(widths or []):
        ws.column_dimensions[openpyxl.utils.get_column_letter(i + 1)].width = w


def v(x):
    return "" if x is None else x


def build(cq, papers, finals, sr8_rows, etd, gl2023, audit, soron_users=None):
    """cq: CQ item。papers: PAPER items。finals: 様式4-5の確定レコード。sr8_rows: SR8 items。etd: ETD item。gl2023: GL2023 item。audit: 作成経過"""
    wb = openpyxl.Workbook()
    ws = wb.active; ws.title = "CQ"
    ws.append(["項目", "内容"])
    for k, val in [("ID", cq["id"]), ("名称", cq["title"]), ("区分", cq.get("category", "")), ("担当", "・".join(cq.get("assignees", []))), ("承認", cq.get("approved", "")),
                   ("P", cq["pico"].get("P", "")), ("I", cq["pico"].get("I", "")), ("C", cq["pico"].get("C", "")), ("O", cq["pico"].get("O", "")), ("アウトカム", "\n".join(cq.get("outcomes") or []))]:
        ws.append([k, val])
    style(ws, widths=[14, 90])

    ws = wb.create_sheet("研究特性")
    ws.append(["PMID", "題名", "デザイン", "がん腫", "化学療法の分類", "薬剤名", "全症例数", "介入群症例数", "介入", "対照", "評価時点", "本文"])
    for p in sorted(papers, key=lambda p: p["pmid"]):
        ch = p.get("chars") or {}
        ws.append([p["pmid"], p.get("title", ""), ch.get("design", ""), ch.get("cancer", ""), ch.get("chemo_class", ""), ch.get("chemo_drugs", ""), ch.get("n_total", ""), ch.get("n_int", ""),
                   ch.get("intervention_detail", ""), ch.get("comparator_detail", ""), ch.get("followup", ""), p.get("status", "")])
    style(ws, widths=[11, 40, 10, 12, 14, 20, 8, 8, 24, 20, 14, 10])

    ws = wb.create_sheet("様式4-5")
    ws.append(["アウトカム", "PMID", "研究(題名)", "デザイン"] + ITEM_JA + ["対照 分子", "対照 分母", "介入 分子", "介入 分母", "効果指標", "値", "95%CI下", "95%CI上", "測定尺度", "根拠(段落ID)", "確定者", "照合の元(評価者)", "備考"])
    pmap = {p["pmid"]: p for p in papers}
    for o in cq.get("outcomes") or []:
        for f in sorted((x for x in finals if x["outcome"] == o), key=lambda x: x["pmid"]):
            p = pmap.get(f["pmid"], {}); it = f.get("items", {}); cnt = f.get("counts") or {}; ef = f.get("effect") or {}
            ev = "; ".join(f"{ja}: {', '.join(it.get(k, {}).get('evidence') or [])} {it.get(k, {}).get('quote', '')}".strip() for k, ja in zip(ITEM_KEYS, ITEM_JA) if it.get(k, {}).get("evidence") or it.get(k, {}).get("quote"))
            ws.append([o, f["pmid"], p.get("title", ""), (p.get("chars") or {}).get("design", "")] + [v(it.get(k, {}).get("v")) for k in ITEM_KEYS]
                      + [v(cnt.get("ctrl_num")), v(cnt.get("ctrl_den")), v(cnt.get("int_num")), v(cnt.get("int_den")), v(ef.get("measure")), v(ef.get("value")), v(ef.get("ci_low")), v(ef.get("ci_high")),
                         f.get("instrument", ""), ev, f.get("fixed_by", ""), "・".join(f.get("based_on") or []), f.get("note", "")])
    style(ws, widths=[16, 11, 36, 8] + [7] * 15 + [7, 7, 7, 7, 8, 7, 7, 7, 14, 60, 10, 14, 20])

    ws = wb.create_sheet("様式SR-8")
    ws.append(["アウトカム", "研究数", "化学療法の分類(層別行)"] + [ja for _, ja in SR8] + ["層別の結論", "効果の要約", "記入者", "備考"])
    for o in cq.get("outcomes") or []:
        fs = [x for x in finals if x["outcome"] == o]
        r = next((x for x in sr8_rows if x.get("outcome") == o), {})
        by_class = {}
        for f in fs:
            by_class.setdefault((pmap.get(f["pmid"], {}).get("chars") or {}).get("chemo_class") or "不明", []).append(f["pmid"])
        ws.append([o, len(fs), "\n".join(f"{c}: {', '.join(ps)}" for c, ps in by_class.items())] + [v(r.get(k)) for k, _ in SR8] + [r.get("strata", ""), r.get("effect_summary", ""), r.get("by", ""), r.get("note", "")])
    style(ws, widths=[18, 7, 30] + [10] * 7 + [30, 30, 10, 20])

    ws = wb.create_sheet("SoF表")
    ws.append(["アウトカム", "研究数(参加者数)", "対照群のイベント/人数", "介入群のイベント/人数", "各研究の効果(記録のまま)", "エビデンスの確実性", "層別の結論"])
    for o in cq.get("outcomes") or []:
        fs = [x for x in finals if x["outcome"] == o]; r = next((x for x in sr8_rows if x.get("outcome") == o), {})
        def tot(k):
            s = 0
            for f in fs:
                try: s += int(float((f.get("counts") or {}).get(k) or 0))
                except Exception: pass
            return s
        n_part = tot("ctrl_den") + tot("int_den")
        effects = "; ".join(f"{f['pmid']}: {(f.get('effect') or {}).get('measure') or '—'} {(f.get('effect') or {}).get('value') or ''}" for f in fs)
        ws.append([o, f"{len(fs)}({n_part})" if n_part else str(len(fs)), f"{tot('ctrl_num')}/{tot('ctrl_den')}", f"{tot('int_num')}/{tot('int_den')}", effects, r.get("certainty", ""), r.get("strata", "")])
    ws.append([]); ws.append(["注", "統合値(メタアナリシス)は計算していない。各研究の効果は様式4-5の記録のまま。確実性は様式SR-8の記入"])
    style(ws, widths=[18, 14, 16, 16, 50, 14, 30])

    ws = wb.create_sheet("EtD・推奨")
    e = etd or {}; g = gl2023 or {}
    ws.append(["項目", "2023年版", "2028年版(案)"])
    ws.append(["推奨文", g.get("rec", ""), e.get("rec_draft", "")])
    ws.append(["推奨の強さ", g.get("strength", ""), e.get("strength", "")])
    ws.append(["エビデンスの確実性", g.get("certainty", ""), e.get("certainty", "")])
    ws.append(["適用範囲・変更点", "", e.get("scope_note", "")])
    for k, ja in (("benefit_harm", "益と害のバランス"), ("certainty", "エビデンスの確実性(考慮事項)"), ("values", "患者の価値観・希望"), ("cost", "コスト・資源")):
        c = (e.get("considerations") or {}).get(k) or {}
        ws.append([ja, "", (c.get("text") or "") + ("\n根拠: " + ", ".join(c.get("evidence") or []) if c.get("evidence") else "")])
    gv = g.get("votes") or {}; ev_ = e.get("vote") or {}
    ws.append(["投票", f"分母 {gv.get('denominator', '')} 分布 {gv.get('counts', '')} 投票除外 筆頭著者{gv.get('coi', '')} SR{gv.get('sr', '')}" if gv else "",
               f"第{ev_.get('round', '')}回 {ev_.get('date', '')} 分布 {ev_.get('counts', '')} 分母 {ev_.get('denominator', '')} 合意率 {ev_.get('agreement', '')}% 投票除外 筆頭著者{ev_.get('coi_excluded', '')} SR{ev_.get('sr_excluded', '')}" if ev_ else ""])
    ws.append(["解説", "\n".join(p["text"] for p in g.get("paragraphs", [])), e.get("narrative", "")])
    ws.append(["状態", "", e.get("status", "")])
    style(ws, widths=[22, 60, 60])

    ws = wb.create_sheet("作成経過")
    ws.append(["日時", "操作者", "操作", "対象", "内容"])
    for a in audit:
        ws.append([a.get("at", ""), a.get("actor", ""), a.get("action", ""), a.get("target", ""), a.get("detail", "")])
    style(ws, widths=[20, 12, 22, 30, 60])

    buf = io.BytesIO(); wb.save(buf); return buf.getvalue()
