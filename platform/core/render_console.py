"""
レビューコンソール生成器 — バンドル → 自己完結HTML
====================================================
委員が「推奨案を読みながら、その根拠を同じ画面で辿れる」ことだけを目的にする。

設計上の決めごと:
  - サーバ不要。1ファイルのHTMLをメール添付/共有ドライブで配れる
  - 判定とコメントはブラウザのlocalStorageに保存し、JSONで書き出す
    (書き出したJSONを事務局が集約する。Minds 7.2の作成経過の素材になる)
  - 機械検証で不合格のCQは、推奨案を畳んで先に不整合を見せる
    委員に「もっともらしい文章」を先に読ませない
"""
import html
import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))

BAND_JA = {"critical": "重大", "important": "重要", "limited": "重要でない"}
FACTOR_JA = {
    "risk_of_bias": "バイアスリスク", "inconsistency": "非一貫性",
    "indirectness": "非直接性", "imprecision": "不精確", "publication_bias": "出版バイアス",
    "large_effect": "効果が大きい", "dose_response": "用量反応", "opposing_confounding": "交絡が逆方向",
}
COMPARATOR_JA = {
    "none": "無介入", "usual_care": "通常ケア", "placebo": "プラセボ",
    "active_weaker": "実対照（弱い介入）", "active_different": "実対照（別介入）",
}
# Minds 5段階(CIPN診療GL 2023年版の表記)。旧来の "なし" もデモ互換で残す
STRENGTH_JA = {
    "1": "1（強い推奨・実施）", "2": "2（弱い推奨・実施を提案）", "3": "3（推奨なし）",
    "4": "4（弱い推奨・非実施を提案）", "5": "5（強い推奨・非実施）", "なし": "推奨なし",
}
DIRECTION_JA = {
    "for_strong": "行うことを強く推奨", "for": "行うことを提案", "none": "推奨なし",
    "against": "行わないことを提案", "against_strong": "行わないことを強く推奨",
}
CERT_JA = {"A": "A（強）", "B": "B（中）", "C": "C（弱）", "D": "D（非常に弱い）"}

CSS = """
/* 印刷を前提にした白地・黒文字。濃い塗りつぶし・白抜き文字は使わない */
*{box-sizing:border-box}
body{margin:0;font-family:-apple-system,BlinkMacSystemFont,"Hiragino Sans","Noto Sans JP",sans-serif;
 background:#fff;color:#000;line-height:1.7;font-size:15px}
header{background:#fff;color:#000;padding:16px 28px 12px;border-bottom:2px solid #000}
header .cqid{font-size:12px;letter-spacing:.12em;color:#444}
header h1{margin:4px 0 8px;font-size:20px;font-weight:700}
.wrap{max-width:1180px;margin:0 auto;padding:18px 28px 90px}
.badge{display:inline-block;padding:2px 10px;border-radius:999px;font-size:12px;font-weight:700;
 border:1.5px solid #000;background:#fff;color:#000}
.badge.ng{border-style:double;border-width:3px}
.badge.mute{border-color:#888;color:#444}
section{background:#fff;border:1px solid #bbb;border-radius:6px;padding:16px 20px;margin:14px 0;
 break-inside:avoid}
section>h2{margin:0 0 12px;font-size:15px;font-weight:700;color:#000;
 border-left:4px solid #000;padding-left:9px}
table{width:100%;border-collapse:collapse;font-size:14px}
th,td{border-bottom:1px solid #ccc;padding:7px 9px;text-align:left;vertical-align:top}
th{background:#fff;font-weight:700;font-size:13px;color:#000;border-bottom:2px solid #000}
.scroll{overflow-x:auto}
.issue{border-left:4px solid #000;border-top:1px solid #ddd;border-bottom:1px solid #ddd;
 padding:9px 13px;margin:8px 0;background:#fff}
.issue.w{border-left-style:dashed}
.issue.i{border-left-style:dotted}
.issue .rule{font-weight:700;font-size:13px}
.issue .d{font-size:13.5px;color:#222;margin-top:3px}
.rec{background:#fff;border:2px solid #000;border-radius:6px;padding:14px 16px;font-size:16px;font-weight:600}
.kv{display:flex;flex-wrap:wrap;gap:8px;margin-top:10px}
.kv div{border:1px solid #bbb;border-radius:4px;padding:4px 10px;font-size:13px;background:#fff}
.kv b{color:#000}
details.study{border:1px solid #bbb;border-radius:6px;margin:8px 0;background:#fff}
details.study>summary{cursor:pointer;padding:9px 13px;font-size:14px;list-style:none}
details.study>summary::-webkit-details-marker{display:none}
details.study>summary:before{content:"▸ ";color:#000}
details.study[open]>summary:before{content:"▾ "}
.sbody{padding:0 14px 12px;font-size:13.5px}
.tag{display:inline-block;border:1px solid #666;border-radius:3px;padding:0 6px;font-size:11.5px;margin-left:6px;
 background:#fff;color:#000}
.tag.r{border:2px solid #000;font-weight:700}.tag.ma{border-style:dashed}
.tag.dup{border-style:dotted}.tag.new{border:2px solid #000;font-weight:700}
a{color:#000;text-decoration:underline}
.chain{border-left:3px solid #000;padding-left:13px;margin:10px 0;font-size:13.5px}
.chk{border-top:1px solid #ddd;padding:9px 0;display:flex;gap:10px;align-items:flex-start}
.chk input[type=checkbox]{margin-top:5px;width:17px;height:17px;flex:none}
.chk .q{flex:1}.chk .q small{color:#444;display:block;font-size:12.5px}
textarea,input[type=text],select{width:100%;border:1px solid #888;border-radius:4px;padding:8px;
 font-family:inherit;font-size:14px;background:#fff;color:#000}
textarea{min-height:78px;resize:vertical}
textarea.narr{min-height:260px;line-height:1.8}
.verdicts{display:flex;gap:9px;flex-wrap:wrap;margin:12px 0}
.verdicts label{border:1.5px solid #000;border-radius:5px;padding:8px 14px;cursor:pointer;font-size:14px;background:#fff}
.verdicts input{margin-right:6px}
.bar{position:fixed;left:0;right:0;bottom:0;background:#fff;color:#000;padding:10px 28px;
 display:flex;gap:12px;align-items:center;font-size:13.5px;border-top:2px solid #000}
button{background:#fff;color:#000;border:1.5px solid #000;border-radius:5px;padding:8px 16px;font-size:14px;
 font-weight:700;cursor:pointer}
button.ghost{border-color:#888;color:#333;font-weight:400}
button.small{padding:4px 10px;font-size:12.5px;font-weight:400}
.note{font-size:12.5px;color:#444}
.demo{border:1.5px dashed #000;border-radius:6px;padding:10px 14px;font-size:13.5px;margin:14px 0}
.change{display:none;margin-top:10px;padding:12px 14px;border:1px dashed #000;border-radius:6px}
.change.on{display:block}
.change label{display:inline-block;margin:4px 14px 4px 0}
.change select{width:auto}
.cand td{vertical-align:middle}
.cand .dec label{display:inline-block;margin-right:10px;white-space:nowrap}
.cand input[type=text]{font-size:13px;padding:5px}
@media print{
 .bar,button{display:none}
 .wrap{padding-bottom:0}
 details.study{break-inside:avoid}
 details:not([open])>*:not(summary){display:block}
 textarea{border:1px solid #000}
}
"""

# 委員が必ず答えるチェック項目。AGREE II の該当項目を併記する
CHECKLIST = [
    ("2023年版以降の新規文献（「新規」タグの論文）を読んだうえで、推奨の方向・強さを"
     "変える根拠の有無を判断した",
     "改訂の要点：踏襲するなら「変える根拠がない」ことの確認、変えるなら新規文献との対応"),
    ("推奨文が、この画面に並ぶ根拠だけで説明できる（書かれていない根拠を前提にしていない）",
     "AGREE II 項目12：推奨とエビデンスの対応関係"),
    ("採用文献に、除外すべき研究（同一試験の重複・撤回論文・適格基準外）が混じっていない",
     "Minds 4.2 / 4.4"),
    ("エビデンスの確実性の格下げ理由に納得できる",
     "AGREE II 項目9 / Minds 4.4"),
    ("益と害のバランスの記述が、示された効果量と矛盾しない",
     "AGREE II 項目11 / Minds 6.3"),
    ("推奨の強さ（1/2/なし）と方向が、確実性と益害バランスから妥当である",
     "Minds 6.3"),
    ("患者の価値観・希望のばらつきへの言及が、この領域の実態に合っている",
     "AGREE II 項目5"),
    ("実施上の障壁（費用・器材・体制）の記述に、現場から見た抜けがない",
     "AGREE II 項目18 / Minds 6.4"),
]


def esc(s):
    return html.escape(str(s if s is not None else ""))


def _effect(e):
    if not e:
        return "—"
    if e.get("point") is None:
        return "—"
    s = f"{e.get('measure','')} {e['point']}"
    if e.get("ci_low") is not None:
        s += f"（95%CI {e['ci_low']}–{e['ci_high']}）"
    if e.get("i2") is not None:
        s += f" I²={e['i2']}%"
    return s


def _issues_html(b, baseline=False):
    out = []
    for v in b["validation"]["violations"]:
        out.append(f'<div class="issue"><div class="rule">{esc(v["rule"])} 違反</div>'
                   f'<div class="d">{esc(v["detail"])}</div></div>')
    # 改訂レビューでは draft は刊行版(2023年版)なので「AI生成」とは呼ばない
    block_label = "2023年版の記載と今回の根拠の不一致" if baseline else "AI生成の申告と根拠の不一致"
    checks = [c for c in b["cross_check"] if c.get("level") != "info"]
    # 引用PMIDの未接続は文献数ぶん同じ文面で並ぶ(未入力段階では全件)。
    # 推奨文を押し下げないよう、3件以上なら1つにまとめて畳む
    cites = [c for c in checks if c.get("check") == "citation"]
    others = [c for c in checks if c.get("check") != "citation"]
    if len(cites) >= 3:
        pm = "、".join(esc(c.get("pmid", "")) for c in cites)
        out.append(f'<div class="issue"><div class="rule">{block_label}（citation）'
                   f'　{len(cites)}件</div>'
                   f'<div class="d">推奨が引用する {len(cites)} 件のPMIDが、今回の根拠グラフ'
                   f'（RoB2評価→エビデンス総体）にまだ接続されていません。'
                   f'<details><summary style="cursor:pointer">PMID一覧</summary>{pm}</details></div></div>')
        cites = []
    for c in others + cites:
        lv = c.get("level")
        cls = "issue" if lv == "block" else "issue w"
        label = block_label if lv == "block" else "要確認"
        out.append(f'<div class="{cls}"><div class="rule">{label}（{esc(c["check"])}）</div>'
                   f'<div class="d">{esc(c["detail"])}</div></div>')
    return "\n".join(out) or '<p class="note">機械検証で検出された不整合はありません。</p>'


def _bodies_html(b):
    rows = []
    for eb in b["evidence_bodies"]:
        band = BAND_JA.get(eb["band"], "—")
        dg = "、".join(FACTOR_JA.get(f, f) for f in eb["downgraded_by"]) or "—"
        studies = "<br>".join(esc(s) for s in eb["studies"]) or "—"
        rows.append(
            f"<tr><td><b>{esc(eb['outcome_label'])}</b><br>"
            f'<span class="tag">{band}・重要度{esc(eb["importance"])}</span></td>'
            f"<td><b>{esc(eb['certainty'])}</b></td><td>{esc(dg)}</td>"
            f"<td>{esc(eb['summary'])}</td><td style='font-size:12.5px'>{studies}</td></tr>")
    return ("<div class='scroll'><table><tr><th>アウトカム</th><th>確実性</th>"
            "<th>格下げ理由</th><th>要約</th><th>寄与した論文</th></tr>"
            + "".join(rows) + "</table></div>")


def _ref_no(s):
    """2023年版採用 → 新規 の順、その中は 年 → 第一著者 で並べる
    (title は "Loprinzi 2020" 形式。旧形式 "7）..." なら番号順)"""
    import re
    t = str(s.get("title") or "")
    m = re.match(r"\s*(\d+)[）)]", t)
    if m:
        return (0, int(m.group(1)), "")
    y = re.search(r"(19|20)\d{2}", t)
    return (1 if s.get("newly_added") else 0, int(y.group(0)) if y else 9999, t)


def _studies_html(b):
    out = []
    for s in sorted(b["studies"], key=_ref_no):
        tags = ""
        if s.get("newly_added"):
            tags += '<span class="tag new">新規（2023年版以降）</span>'
        elif s.get("cited_in_2023"):
            tags += '<span class="tag">2023年版採用</span>'
        if s["retracted"]:
            tags += '<span class="tag r">撤回論文</span>'
        if s["design"] == "meta_analysis":
            tags += '<span class="tag ma">メタ解析</span>'
        if s["same_trial_as"]:
            tags += '<span class="tag dup">同一試験の別報告あり</span>'
        pmid = s.get("pmid")
        link = (f'<a href="https://pubmed.ncbi.nlm.nih.gov/{esc(pmid)}/" '
                f'target="_blank" rel="noopener">PMID {esc(pmid)}</a>' if pmid else "PMID未登録")
        res = []
        for r in s["results"]:
            comp = COMPARATOR_JA.get(r["comparator"], r["comparator"] or "—")
            rob = r.get("rob2") or {}
            rob_txt = ("／".join(f"{k}:{v}" for k, v in rob.items() if v) if any(rob.values()) else "—") if rob else "—"
            res.append(f"<tr><td>{esc(r['outcome_label'] or '（未割当）')}</td>"
                       f"<td>{esc(r.get('instrument') or '—')}</td><td>{esc(comp)}</td>"
                       f"<td>{esc(_effect(r['effect']))}</td><td>{esc(rob_txt)}</td>"
                       f"<td>{'適格' if r['eligible'] else '未判定'}</td></tr>")
        inc = ""
        if s["includes"]:
            inc = ("<p class='note'>このメタ解析が含む研究：" +
                   "、".join(esc(x) for x in s["includes"]) + "</p>")
        same = ""
        if s["same_trial_as"]:
            same = ("<p class='note'>同一試験を報告：" +
                    "、".join(esc(x) for x in s["same_trial_as"]) +
                    "（試験登録番号から自動判定）</p>")
        out.append(
            f'<details class="study"><summary>{esc(s["title"] or s["id"])}{tags}</summary>'
            f'<div class="sbody">{link}｜{esc(s.get("journal") or "")} '
            f'{esc(s.get("year") or "")}｜デザイン: {esc(s.get("design") or "—")}'
            f'<div class="scroll"><table><tr><th>アウトカム</th><th>評価指標</th><th>対照</th>'
            f'<th>効果</th><th>RoB2</th><th>適格性</th></tr>{"".join(res)}</table></div>{inc}{same}</div></details>')
    return "\n".join(out)


def _incomplete_html(b):
    """RoB2は入力したがアウトカム未割当など、入力途中の結果を「未完了」として見せる"""
    items = b.get("incomplete_results") or []
    if not items:
        return ""
    # 同じ理由が文献数ぶん並ぶので、理由ごとにまとめて対象IDは畳む
    by_reason = {}
    for x in items:
        by_reason.setdefault(x["reason"], []).append(x["result"])
    rows = "".join(
        f'<div class="issue i"><div class="rule">入力未完了　{len(ids)}件</div>'
        f'<div class="d">{esc(reason)}'
        f'<details><summary style="cursor:pointer">対象</summary>{"、".join(esc(i) for i in ids)}</details></div></div>'
        for reason, ids in by_reason.items())
    more = ""
    return (f'<section><h2>入力が未完了の項目（{len(items)}件）</h2>{rows}{more}'
            '<p class="note">minds_review.xlsx の RoB2 評価シートで「対応するアウトカムID」'
            '「適格性」を埋め、merge_rob2_evidence.py を再実行すると解消します。</p></section>')


def _candidates_html(b):
    """検索/ハンドサーチで挙がった候補文献の採否を委員が判断する欄。
    候補はスクリーニングログの新規行から merge_rob2_evidence.py が拾う"""
    cands = b.get("candidates") or []
    if not cands:
        return ('<section><h2>採用文献候補（検索結果から）</h2>'
                '<p class="note">候補はまだありません。minds_review.xlsx の「スクリーニングログ」に'
                '検索・ハンドサーチで挙がった文献を追記し、merge_rob2_evidence.py → review_bundle.py → '
                'render_console.py を再実行するとここに並びます。</p></section>')
    rows = []
    for i, c in enumerate(cands):
        pmid = c.get("pmid")
        link = (f'<a href="https://pubmed.ncbi.nlm.nih.gov/{esc(pmid)}/" target="_blank" '
                f'rel="noopener">{esc(pmid)}</a>' if pmid else "—")
        scr = " / ".join(x for x in [
            f"一次: {c['primary']}" if c.get("primary") else "",
            f"二次: {c['secondary']}" if c.get("secondary") else ""] if x) or "未記入"
        rows.append(
            f'<tr class="cand" data-cand="{i}"><td>{link}</td>'
            f'<td>{esc(c.get("title"))}<br><span class="note">{esc(c.get("source"))}｜ログ: {esc(scr)}'
            f'{("｜" + esc(c.get("primary_reason") or c.get("secondary_reason"))) if (c.get("primary_reason") or c.get("secondary_reason")) else ""}</span></td>'
            f'<td class="dec"><label><input type="radio" name="cand{i}" value="adopt">採用</label>'
            f'<label><input type="radio" name="cand{i}" value="exclude">除外</label>'
            f'<label><input type="radio" name="cand{i}" value="hold">保留</label></td>'
            f'<td><input type="text" data-candreason="{i}" placeholder="理由（除外時は必須）"></td></tr>')
    return ('<section><h2>採用文献候補（検索結果から）　' + f'{len(cands)}件</h2>'
            '<p class="note">2023年版の採用文献は下の「採用文献」欄にあります。ここは今回の検索で新たに挙がった'
            '文献です。採用したものは RoB2 評価シートに「新規追加」として1行ずつ追記してください。</p>'
            '<div class="scroll"><table><tr><th style="width:8em">PMID</th><th>文献</th>'
            '<th style="width:16em">採否</th><th style="width:18em">理由</th></tr>'
            + "".join(rows) + '</table></div></section>')


def _provenance_html(b):
    out = []
    for c in b["provenance"]["chain"]:
        dg = "、".join(FACTOR_JA.get(f, f) for f in c["downgraded_by"]) or "なし"
        studies = "、".join(
            f"{s['study']}（PMID {s['pmid']}）" if s["pmid"] else str(s["study"])
            for s in c["studies"]) or "—"
        out.append(f'<div class="chain"><b>{esc(c["evidence_body"])}</b>'
                   f'（確実性 {esc(c["certainty"])}、格下げ: {esc(dg)}）<br>'
                   f'<span class="note">根拠: {esc(studies)}</span></div>')
    return "".join(out) or '<p class="note">根拠鎖がありません。</p>'


def _draft_block_2023(dd, label=None):
    pv = dd.get("panel_vote") or {}
    head = f"<p class='note' style='margin:0 0 6px'><b>{esc(label)}</b></p>" if label else ""
    return f"""{head}
  <div class="rec">{esc(dd.get('recommendation_text') or '')}</div>
  <div class="kv">
    <div><b>推奨の強さ</b> {esc(STRENGTH_JA.get(dd.get('strength'), dd.get('strength') or '—'))}</div>
    <div><b>エビデンスの確実性</b> {esc(CERT_JA.get(dd.get('certainty'), dd.get('certainty') or '—'))}</div>
    <div><b>合意率</b> {esc(f"{pv.get('agreement_rate'):.0%}" if pv.get('agreement_rate') is not None else '—')}
      {esc(f"（{pv.get('n_panel')}名）" if pv.get('n_panel') else '')}</div>
    <div><b>引用文献</b> {len(dd.get('cited_pmids') or [])}件</div>
  </div>"""


INSTRUMENT_GROUPS = [
    ("医療者評価", "CTCAE（G2: IADL障害／G3: ADL障害）、ECOG、DEB-NTC"),
    ("患者報告（PRO）", "EORTC QLQ-CIPN20、FACT-Ntx（FACT/GOG-Ntx）、PNQ、PRO-CTCAE、CAS-CIPN"),
    ("疼痛尺度", "VAS、NRS、Brief Pain Inventory（短縮版）"),
    ("複合指標", "Total Neuropathy Score（TNS／mTNS／TNSc）"),
    ("定量評価", "モノフィラメント、二点識別覚、音叉振動覚、TUG／6分間歩行、Pegboard／STEF、神経伝導検査／CPT"),
]


def _outcomes_html(b):
    ocs = b["cq"].get("outcomes") or []
    used = sorted({(r.get("instrument") or "").strip() for s in b["studies"] for r in s["results"]
                   if r.get("instrument")})
    inst = ("<p style='margin:12px 0 4px'><b>評価指標（アウトカムの測定尺度）</b>"
            "<span class='note'>　2023年版 第2章H「CIPNの評価」より</span></p>"
            "<div class='scroll'><table><tr><th style='width:9em'>分類</th><th>尺度</th></tr>"
            + "".join(f"<tr><td>{esc(g)}</td><td>{esc(n)}</td></tr>" for g, n in INSTRUMENT_GROUPS)
            + "</table></div>"
            + (f"<p class='note'>採用研究で使われた指標：{esc('、'.join(used))}</p>" if used else
               "<p class='note'>各研究がどの指標で測ったかは、RoB2シートの「評価指標(使用尺度)」列"
               "（papers/のPDFから自動記入）から採用文献欄に表示されます。</p>"))
    if not ocs:
        return "<p class='note'>アウトカム未設定</p>" + inst
    rows = "".join(
        f"<tr><td><b>{esc(o.get('label'))}</b></td>"
        f"<td>{esc(o.get('importance') if o.get('importance') is not None else '—')}"
        f"{'（暫定）' if o.get('_note') else ''}</td>"
        f"<td class='note'>{esc(o.get('_note') or '')}</td></tr>" for o in ocs)
    return ("<div class='scroll'><table><tr><th>アウトカム</th><th style='width:9em'>重要度(1-9)</th>"
            "<th>備考</th></tr>" + rows + "</table></div>"
            "<p class='note'>2023年版（第1章4）で設定されたアウトカム概念です。重要度の点数化は2023年版では"
            "行われていないため暫定値です。改訂での確定は委員会で行います。</p>" + inst)


def _consideration_fields():
    items = [
        ("cons_certainty", "アウトカム全体にわたる総括的なエビデンスの確実性"),
        ("cons_balance", "望ましい効果と望ましくない効果のバランス"),
        ("cons_values", "患者・市民の価値観と希望"),
        ("cons_cost", "資源の利用（コスト）※特に高額が予想される場合のみ"),
    ]
    return "".join(
        f'<p style="margin:10px 0 4px"><b>{esc(lbl)}</b></p>'
        f'<textarea id="{i}" data-draft="{i}" style="min-height:64px"></textarea>' for i, lbl in items)


def render(bundle: dict, audience: str = "committee") -> str:
    cq, d = bundle["cq"], bundle["draft"]
    gate = bundle["gate"]
    pico = cq.get("pico", {})
    derived = bundle["derived_certainty"]
    secretariat = audience == "secretariat"
    is_frq = bundle.get("question_type") == "FRQ"
    drafts_2023 = bundle.get("drafts_2023") or []
    n_new = sum(1 for s in bundle["studies"] if s.get("newly_added"))
    n_old = sum(1 for s in bundle["studies"] if s.get("cited_in_2023"))

    demo = ""
    if "DEMO" in cq["id"].upper():
        demo = ('<div class="demo"><b>デモ用の画面です。</b>'
                'PMID・効果量・推奨文はすべて架空で、実在の研究ではありません。</div>')

    # ---- 2023年版の推奨(統合CQは介入ごとに) ----
    if drafts_2023:
        blocks = "".join(_draft_block_2023(dd, dd.get("_intervention")) for dd in drafts_2023)
        note_merge = ("<p class='note'>この改訂では2つの介入を1つのCQとして扱います。"
                      "2023年版ではそれぞれ別の推奨でした。</p>")
    else:
        blocks = _draft_block_2023(d)
        note_merge = ""
    rec_block = f"""
<section>
  <h2>2023年版の推奨</h2>
  {note_merge}{blocks}
  <p class="note">文献：2023年版採用 {n_old}件 ／ 今回新規 {n_new}件。
  今回のエビデンスから機械的に導いた確実性：{esc(derived.get('overall') or '—（エビデンス総体が未入力）')}</p>
</section>"""

    # ---- 解説(編集可) ----
    narrative = ""
    if bundle.get("narrative"):
        narrative = (
            f'<section><h2>解説（草案）　初期値は2023年版の原文</h2>'
            f'<p class="note">2023年版の解説を全文載せています。このまま改訂の草案として直してください。'
            f'<button class="small" type="button" onclick="resetNarrative()">2023年版の原文に戻す</button></p>'
            f'<textarea id="narrative" class="narr" data-draft="narrative">{esc(bundle["narrative"])}</textarea>'
            f'<p class="note" id="narrStatus"></p></section>')

    # ---- 草案フォーム(CQ / FRQ) ----
    if is_frq:
        form = f"""
<section>
  <h2>FRQ（今後の研究課題）記載草案</h2>
  <p class="note">このCQは委員会の割り振りでFRQ（Future Research Question）とされています。
  Minds 2020ではエビデンス不足で推奨を出せない問いをFRQとし、推奨文・推奨の強さは付けず、
  現時点のエビデンスの状況と今後必要な研究を記述します（手引きの該当項で最終確認してください）。</p>
  <p style="margin:10px 0 4px"><b>背景・臨床上の重要性</b></p>
  <textarea id="frq_background" data-draft="frq_background"></textarea>
  <p style="margin:10px 0 4px"><b>現時点のエビデンスの状況（SRの結果）</b></p>
  <textarea id="frq_evidence" data-draft="frq_evidence"></textarea>
  <p style="margin:10px 0 4px"><b>推奨を出せない理由</b></p>
  <textarea id="frq_reason" data-draft="frq_reason"></textarea>
  <p style="margin:10px 0 4px"><b>今後必要な研究（デザイン・対象・アウトカム）</b></p>
  <textarea id="frq_future" data-draft="frq_future"></textarea>
</section>"""
    else:
        base_text = d.get("recommendation_text") or ""
        if drafts_2023:
            base_text = "\n".join(f"【{dd.get('_intervention')}】{dd.get('recommendation_text','')}"
                                  for dd in drafts_2023)
        opt = lambda v, cur, lbl: f'<option value="{v}"{" selected" if str(cur)==v else ""}>{lbl}</option>'
        form = f"""
<section>
  <h2>Minds推奨文草案</h2>
  <p class="note">初期値は2023年版です。SRの結果（エビデンス総体・採用文献）を踏まえて、改訂版の草案として直してください。
  投票は委員会会議で行います（資格者の75%以上が参加し80%以上の賛成で決定）。</p>
  <p style="margin:10px 0 4px"><b>推奨文（草案）</b></p>
  <textarea id="rec_text" data-draft="rec_text">{esc(base_text)}</textarea>
  <div class="kv" style="margin-top:10px">
    <div><b>推奨の強さ</b>
      <select id="rec_strength" data-draft="rec_strength" style="width:auto">
        <option value="">—</option>
        {opt("1", d.get("strength"), "1 投与・実施することを強く推奨する")}
        {opt("2", d.get("strength"), "2 投与・実施することを提案する")}
        {opt("3", d.get("strength"), "3 投与・実施について「推奨なし」とする")}
        {opt("4", d.get("strength"), "4 投与・実施しないことを提案する")}
        {opt("5", d.get("strength"), "5 投与・実施しないことを強く推奨する")}
      </select></div>
    <div><b>エビデンスの確実性</b>
      <select id="rec_certainty" data-draft="rec_certainty" style="width:auto">
        <option value="">—</option>
        {opt("A", d.get("certainty"), "A（強）")}{opt("B", d.get("certainty"), "B（中）")}
        {opt("C", d.get("certainty"), "C（弱）")}{opt("D", d.get("certainty"), "D（非常に弱い）")}
      </select></div>
  </div>
  {_consideration_fields()}
  <p style="margin:10px 0 4px"><b>2023年版からの変更点と理由（新規文献のPMID等）</b></p>
  <textarea id="rec_changes" data-draft="rec_changes"></textarea>
</section>"""

    # ---- 事務局向けの内部情報(委員には出さない) ----
    internal = ""
    if secretariat:
        internal = f"""
<section>
  <h2>［事務局用］機械検証の結果（規則で判定）</h2>
  {_issues_html(bundle, True)}
</section>
<section><h2>［事務局用］推奨の由来</h2>{_provenance_html(bundle)}</section>
{_incomplete_html(bundle)}"""

    header_badge = ('<span class="badge">FRQ（今後の研究課題）</span>' if is_frq
                    else '<span class="badge">CQ（推奨を作成）</span>')
    if secretariat:
        ok = gate["ready_for_review"]
        vtxt = "検証 通過" if ok else "検証 未通過（%d件）" % gate["n_blocking"]
        header_badge += ' <span class="badge %s">%s</span>' % ("" if ok else "ng", vtxt)

    return f"""<!doctype html><html lang="ja"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>{esc(cq['id'])} 草案作成｜CIPN診療ガイドライン改訂</title><style>{CSS}</style></head><body>
<header>
  <div class="cqid">CIPN診療ガイドライン改訂 ・ {'FRQ記載' if is_frq else '推奨文草案'}作成シート</div>
  <h1>{esc(cq['id'])}　{esc(cq['title'])}</h1>
  {header_badge}
  <span class="badge mute">生成 {esc(bundle['generated_at'][:10])}</span>
</header>
<div class="wrap">
{demo}
<section>
  <h2>臨床疑問（PICO）</h2>
  <div class="scroll"><table>
    <tr><th style="width:4em">P</th><td>{esc(pico.get('P') or '（委員会で確定）')}</td></tr>
    <tr><th>I</th><td>{esc(pico.get('I'))}</td></tr>
    <tr><th>C</th><td>{esc(pico.get('C') or '（委員会で確定）')}</td></tr>
    <tr><th>O</th><td>{esc('、'.join(pico.get('O', [])) or '—')}</td></tr>
  </table></div>
</section>

<section><h2>アウトカム</h2>{_outcomes_html(bundle)}</section>

{rec_block}

<section><h2>エビデンス総体（アウトカムごと）</h2>{_bodies_html(bundle)}
<p class="note">RoB2評価と統合の結果を minds_review.xlsx の「エビデンス総体評価」に記入すると反映されます。</p></section>

<section><h2>採用文献（2023年版採用＋新規追加。クリックで結果を展開）</h2>{_studies_html(bundle)}</section>

{_candidates_html(bundle)}

{narrative}

{form}

{internal}

<section>
  <p>お名前：<input id="reviewer" type="text" style="width:16em" placeholder="委員名">
  　備考（事務局への連絡）：<input id="comment" type="text" style="width:40em"></p>
</section>
</div>

<div class="bar">
  <span id="status">入力は自動保存されます（この端末のブラウザ内のみ）</span>
  <span style="flex:1"></span>
  <button class="ghost" onclick="clearAll()">入力を消去</button>
  <button onclick="exportJSON()">草案をJSONで書き出す</button>
</div>

<script>
const CQ = {json.dumps(bundle['cq']['id'], ensure_ascii=False)};
const IS_FRQ = {json.dumps(is_frq)};
const KEY = "cipn-draft-" + CQ;
const NARRATIVE_ORIG = {json.dumps(bundle.get("narrative") or "", ensure_ascii=False)};
function collect() {{
  const drafts = {{}};
  document.querySelectorAll('[data-draft]').forEach(e => drafts[e.dataset.draft] = e.value);
  const cands = [];
  document.querySelectorAll('tr.cand').forEach(tr => {{
    const i = tr.dataset.cand;
    const d = tr.querySelector('input[name="cand' + i + '"]:checked');
    cands.push({{index: +i, pmid: (tr.querySelector('td a') || {{}}).textContent || null,
                decision: d ? d.value : null,
                reason: (tr.querySelector('[data-candreason]') || {{}}).value || ""}});
  }});
  return {{cq: CQ, question_type: IS_FRQ ? "FRQ" : "CQ",
          reviewer: document.getElementById('reviewer').value,
          draft: drafts,
          narrative_changed: (drafts.narrative !== undefined) && drafts.narrative !== NARRATIVE_ORIG,
          candidates: cands,
          comment: document.getElementById('comment').value,
          saved_at: new Date().toISOString()}};
}}
function resetNarrative() {{
  const n = document.getElementById('narrative'); if (!n) return;
  if (n.value !== NARRATIVE_ORIG && !confirm("編集内容を破棄して2023年版の原文に戻します。よろしいですか。")) return;
  n.value = NARRATIVE_ORIG; syncNarrStatus(); save();
}}
function syncNarrStatus() {{
  const n = document.getElementById('narrative'), st = document.getElementById('narrStatus');
  if (!n || !st) return;
  st.textContent = n.value === NARRATIVE_ORIG ? "2023年版の原文のまま（変更なし）" : "※ 2023年版から変更あり";
}}
function save() {{
  localStorage.setItem(KEY, JSON.stringify(collect()));
  document.getElementById('status').textContent = "保存しました " + new Date().toLocaleTimeString('ja-JP');
}}
function restore() {{
  const raw = localStorage.getItem(KEY); if (!raw) {{ syncNarrStatus(); return; }}
  const d = JSON.parse(raw);
  document.getElementById('reviewer').value = d.reviewer || "";
  document.getElementById('comment').value = d.comment || "";
  Object.entries(d.draft || {{}}).forEach(([k, v]) => {{
    const e = document.querySelector('[data-draft="' + k + '"]'); if (e && v != null) e.value = v;
  }});
  (d.candidates || []).forEach(c => {{
    if (c.decision) {{
      const e = document.querySelector('input[name="cand' + c.index + '"][value="' + c.decision + '"]');
      if (e) e.checked = true;
    }}
    const r = document.querySelector('[data-candreason="' + c.index + '"]');
    if (r && c.reason) r.value = c.reason;
  }});
  syncNarrStatus();
}}
function exportJSON() {{
  const d = collect();
  if (!d.reviewer) {{ alert("お名前を入力してください"); return; }}
  if (!IS_FRQ && !(d.draft.rec_text || "").trim()) {{ alert("推奨文（草案）を入力してください"); return; }}
  const bad = d.candidates.filter(c => c.decision === "exclude" && !c.reason.trim());
  if (bad.length) {{ alert("除外にした候補文献には理由を入力してください（" + bad.length + "件）"); return; }}
  const blob = new Blob([JSON.stringify(d, null, 2)], {{type: "application/json"}});
  const a = document.createElement("a");
  a.href = URL.createObjectURL(blob);
  a.download = CQ + "_" + (d.reviewer || "reviewer") + ".draft.json";
  a.click();
}}
function clearAll() {{
  if (!confirm("この画面の入力を消去します。よろしいですか。")) return;
  localStorage.removeItem(KEY); location.reload();
}}
document.addEventListener("input", () => {{ syncNarrStatus(); save(); }});
document.addEventListener("change", save);
restore();
</script>
</body></html>"""


def main():
    import argparse
    ap = argparse.ArgumentParser(description="レビューバンドル → 委員用HTML")
    ap.add_argument("bundles", nargs="+")
    ap.add_argument("-o", "--outdir", default=os.path.join(HERE, "..", "review"))
    ap.add_argument("--audience", choices=["committee", "secretariat"], default="committee",
                    help="committee: 委員用(内部の検証結果を出さない) / secretariat: 事務局用(全部出す)")
    args = ap.parse_args()
    os.makedirs(args.outdir, exist_ok=True)
    for path in args.bundles:
        with open(path, encoding="utf-8") as f:
            b = json.load(f)
        suffix = ".review.html" if args.audience == "committee" else ".secretariat.html"
        out = os.path.join(args.outdir, f"{b['cq']['id']}{suffix}")
        with open(out, "w", encoding="utf-8") as f:
            f.write(render(b, args.audience))
        print(f"{b['cq']['id']}: {out}")


if __name__ == "__main__":
    main()
