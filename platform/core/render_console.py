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
    """タイトル先頭の "7）" (2023年版の文献番号)で並べる。無ければ末尾"""
    import re
    m = re.match(r"\s*(\d+)[）)]", str(s.get("title") or ""))
    return (0, int(m.group(1))) if m else (1, str(s.get("pmid") or ""))


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
            res.append(f"<tr><td>{esc(r['outcome_label'])}</td><td>{esc(comp)}</td>"
                       f"<td>{esc(_effect(r['effect']))}</td>"
                       f"<td>{'適格' if r['eligible'] else '<b>適格性の記録なし</b>'}</td></tr>")
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
            f'<div class="scroll"><table><tr><th>アウトカム</th><th>対照</th>'
            f'<th>効果</th><th>適格性</th></tr>{"".join(res)}</table></div>{inc}{same}</div></details>')
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


def render(bundle: dict) -> str:
    cq, d = bundle["cq"], bundle["draft"]
    gate = bundle["gate"]
    ready = gate["ready_for_review"]
    pico = cq.get("pico", {})
    vote = d.get("panel_vote") or {}
    derived = bundle["derived_certainty"]

    demo = ""
    if "DEMO" in cq["id"].upper():
        demo = ('<div class="demo"><b>デモ用の画面です。</b>'
                'PMID・効果量・推奨文はすべて架空で、実在の研究ではありません。'
                'この画面の動きを確認するためのものです。</div>')

    # 改訂レビュー: draft が刊行版(2023年版)の推奨なら「踏襲の出発点」として扱う。
    # AI生成の推奨案(Phase1)なら従来どおり「未承認」として扱う
    baseline = str(d.get("generated_by", "")).startswith("published_guideline")
    n_new = sum(1 for s in bundle["studies"] if s.get("newly_added"))
    n_old = sum(1 for s in bundle["studies"] if s.get("cited_in_2023"))

    if baseline:
        rec_title = "2023年版の推奨（改訂の出発点・原文）"
        cert_label = "2023年版の確実性"
        rec_note = ("これは刊行済み2023年版の推奨文です。改訂では原則としてこれを踏襲し、"
                    "新規文献（下の採用文献で「新規」タグ）が方向・強さを変える根拠になる場合だけ変更します。")
    else:
        rec_title = "推奨案（AI生成・未承認）"
        cert_label = "AI申告の確実性"
        rec_note = ""

    rec_block = f"""
<section>
  <h2>{rec_title}</h2>
  <div class="rec">{esc(d.get('recommendation_text') or '（推奨案が未生成です）')}</div>
  <div class="kv">
    <div><b>推奨の強さ</b> {esc(STRENGTH_JA.get(d.get('strength'), d.get('strength') or '—'))}</div>
    <div><b>方向</b> {esc(DIRECTION_JA.get(d.get('direction'), d.get('direction') or '—'))}</div>
    <div><b>{cert_label}</b> {esc(CERT_JA.get(d.get('certainty'), d.get('certainty') or '—'))}</div>
    <div><b>今回のエビデンスから導いた確実性</b> {esc(derived.get('overall') or '—（総体評価が未入力）')}</div>
    <div><b>2023年版の合意率</b> {esc(f"{vote.get('agreement_rate'):.0%}" if vote.get('agreement_rate') is not None else '—')}
      {esc(f"（{vote.get('n_panel')}名）" if vote.get('n_panel') else '')}</div>
    <div><b>文献</b> 2023年版採用 {n_old}件 ／ <b>新規 {n_new}件</b></div>
  </div>
  {f'<p class="note">{esc(rec_note)}</p>' if rec_note else ''}
  <p class="note">確実性は「重大アウトカムの総体のうち最も低いもの」として機械的に導出しています：{esc(derived.get('reason') or '')}</p>
</section>"""

    # AI生成案は機械検証不合格なら畳む(もっともらしい文章を先に読ませない)。
    # 刊行版の推奨は承認済みの出発点なので畳まない
    if not ready and not baseline:
        rec_block = ('<section><h2>推奨案（AI生成・未承認）</h2>'
                     '<p class="note">機械検証で不整合が残っているため、推奨文は畳んでいます。'
                     '先に上の「機械検証の結果」を確認してください。</p>'
                     '<details><summary style="cursor:pointer">それでも推奨案を読む</summary>'
                     + rec_block + '</details></section>')

    etd = d.get("etd_judgments") or {}
    etd_rows = "".join(f"<tr><td>{esc(k)}</td><td>{esc(v)}</td></tr>" for k, v in etd.items())

    checklist = "".join(
        f'<div class="chk"><input type="checkbox" id="c{i}" data-chk="{i}">'
        f'<label class="q" for="c{i}">{esc(q)}<small>{esc(ref)}</small></label></div>'
        for i, (q, ref) in enumerate(CHECKLIST))

    narrative = ""
    if bundle.get("narrative"):
        nar_title = "2023年版の解説（原文）" if baseline else "解説文（Phase2生成）"
        narrative = (
            f'<section><h2>{nar_title}　— 加筆修正はこの欄に直接</h2>'
            f'<p class="note">2023年版の解説を全文載せています。踏襲するならそのまま、変更するなら'
            f'この欄で直してください（書き出すJSONに編集後の全文と「変更あり/なし」が入ります）。'
            f'<button class="small" type="button" onclick="resetNarrative()">原文に戻す</button></p>'
            f'<textarea id="narrative" class="narr">{esc(bundle["narrative"])}</textarea>'
            f'<p class="note" id="narrStatus"></p></section>')

    # 判定の選択肢。改訂レビューでは「踏襲／変更／削除・FRQ化」、AI案では従来の承認系
    if baseline:
        verdict_html = """
  <div class="verdicts">
    <label><input type="radio" name="verdict" value="keep">2023年版を踏襲する</label>
    <label><input type="radio" name="verdict" value="change">推奨を変更する（下に変更案・コメント必須）</label>
    <label><input type="radio" name="verdict" value="withdraw">推奨を削除・FRQ化する（コメント必須）</label>
  </div>
  <div class="change" id="changeBox">
    <label>変更後の推奨の強さ
      <select id="newStrength"><option value="">—</option>
        <option value="1">1 強い推奨・実施</option><option value="2">2 弱い推奨・実施</option>
        <option value="3">3 推奨なし</option><option value="4">4 弱い推奨・非実施</option>
        <option value="5">5 強い推奨・非実施</option></select></label>
    <label>変更後の確実性
      <select id="newCertainty"><option value="">—</option>
        <option>A</option><option>B</option><option>C</option><option>D</option></select></label>
    <div style="margin-top:8px"><label style="display:block">変更後の推奨文（案）</label>
      <textarea id="newText" placeholder="変更後の推奨文を書いてください"></textarea></div>
  </div>"""
        verdict_status = ('{"keep":"踏襲","change":"変更","withdraw":"削除・FRQ化"}')
    else:
        verdict_html = """
  <div class="verdicts">
    <label><input type="radio" name="verdict" value="approve">承認する</label>
    <label><input type="radio" name="verdict" value="conditional">条件付き承認（コメント必須）</label>
    <label><input type="radio" name="verdict" value="revise">差し戻す（コメント必須）</label>
  </div>"""
        verdict_status = "{}"

    return f"""<!doctype html><html lang="ja"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>{esc(cq['id'])} レビュー｜CIPN診療ガイドライン改訂</title><style>{CSS}</style></head><body>
<header>
  <div class="cqid">CIPN GUIDELINE REVISION · REVIEW CONSOLE</div>
  <h1>{esc(cq['id'])}　{esc(cq['title'])}</h1>
  <span class="badge {'ok' if ready else 'ng'}">{'機械検証 通過' if ready else f'機械検証 不合格（{gate["n_blocking"]}件）'}</span>
  <span class="badge mute">生成 {esc(bundle['generated_at'][:10])}</span>
</header>
<div class="wrap">
{demo}
<section>
  <h2>機械検証の結果（LLMではなく規則で判定）</h2>
  {_issues_html(bundle, baseline)}
  <p class="note">Minds規則 R1–R8（適格性・二重計上・撤回・非直接性・重大アウトカム・格下げ理由）と、
  {'2023年版の記載（確実性・引用PMID）と今回整備した根拠' if baseline else 'AI生成の申告値'}の照合を、決定論的に実行した結果です。
  {'RoB2評価・エビデンス総体が未入力の段階では、引用文献が根拠グラフに未接続のため不一致として並びます。入力が進むと消えていきます。' if baseline else ''}</p>
</section>

<section>
  <h2>臨床疑問（PICO）</h2>
  <div class="scroll"><table>
    <tr><th style="width:4em">P</th><td>{esc(pico.get('P'))}</td></tr>
    <tr><th>I</th><td>{esc(pico.get('I'))}</td></tr>
    <tr><th>C</th><td>{esc(pico.get('C'))}</td></tr>
    <tr><th>O</th><td>{esc('、'.join(pico.get('O', [])))}</td></tr>
  </table></div>
</section>

{rec_block}

<section><h2>エビデンス総体（アウトカムごと）</h2>{_bodies_html(bundle)}</section>

<section><h2>採用文献（2023年版採用＋新規追加。クリックで結果を展開）</h2>{_studies_html(bundle)}</section>

{_candidates_html(bundle)}

<section><h2>推奨の由来（AGREE II 項目12の証跡）</h2>{_provenance_html(bundle)}
<p class="note">推奨 → エビデンス総体 → 格下げ要因 → 論文PMID の連鎖です。この鎖に載っていない根拠は、推奨の裏づけになりません。</p></section>

{_incomplete_html(bundle)}

{"<section><h2>EtD（判断の枠組み）</h2><div class='scroll'><table>" + etd_rows + "</table></div></section>" if etd_rows else ""}

{narrative}

<section>
  <h2>あなたの確認</h2>
  {checklist}
  {verdict_html}
  <textarea id="comment" placeholder="コメント（変更・削除・差し戻し・条件付き承認の場合は必須。どの記述を、何を根拠に（新規文献のPMID等）、どう直すかを書いてください）"></textarea>
  <p style="margin-top:10px">
    お名前：<input id="reviewer" style="padding:7px;border:1px solid #ccd3da;border-radius:6px;font-size:14px" placeholder="委員名">
  </p>
</section>
</div>

<div class="bar">
  <span id="status">入力は自動保存されます（この端末のブラウザ内のみ）</span>
  <span style="flex:1"></span>
  <button class="ghost" onclick="clearAll()">入力を消去</button>
  <button onclick="exportJSON()">回答をJSONで書き出す</button>
</div>

<script>
const CQ = {json.dumps(bundle['cq']['id'], ensure_ascii=False)};
const KEY = "cipn-review-" + CQ;
const VERDICT_JA = {verdict_status};
const NARRATIVE_ORIG = {json.dumps(bundle.get("narrative") or "", ensure_ascii=False)};
const val = id => {{ const e = document.getElementById(id); return e ? e.value : null; }};
function collect() {{
  const chk = {{}};
  document.querySelectorAll('[data-chk]').forEach(e => chk[e.dataset.chk] = e.checked);
  const v = document.querySelector('input[name=verdict]:checked');
  const cands = [];
  document.querySelectorAll('tr.cand').forEach(tr => {{
    const i = tr.dataset.cand;
    const d = tr.querySelector('input[name="cand' + i + '"]:checked');
    cands.push({{index: +i, pmid: (tr.querySelector('td a') || {{}}).textContent || null,
                decision: d ? d.value : null,
                reason: (tr.querySelector('[data-candreason]') || {{}}).value || ""}});
  }});
  const narr = document.getElementById('narrative');
  return {{cq: CQ, reviewer: document.getElementById('reviewer').value,
          verdict: v ? v.value : null, verdict_ja: v ? (VERDICT_JA[v.value] || v.value) : null,
          checklist: chk,
          proposed: {{strength: val('newStrength'), certainty: val('newCertainty'), text: val('newText')}},
          narrative_edited: narr ? narr.value : null,
          narrative_changed: narr ? narr.value !== NARRATIVE_ORIG : false,
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
  st.textContent = n.value === NARRATIVE_ORIG ? "原文のまま（変更なし）" : "※ 原文から変更あり";
}}
function syncChangeBox() {{
  const box = document.getElementById('changeBox'); if (!box) return;
  const v = document.querySelector('input[name=verdict]:checked');
  box.classList.toggle('on', !!v && v.value === 'change');
}}
function save() {{
  localStorage.setItem(KEY, JSON.stringify(collect()));
  document.getElementById('status').textContent = "保存しました " + new Date().toLocaleTimeString('ja-JP');
}}
function restore() {{
  const raw = localStorage.getItem(KEY); if (!raw) return;
  const d = JSON.parse(raw);
  document.getElementById('reviewer').value = d.reviewer || "";
  document.getElementById('comment').value = d.comment || "";
  Object.entries(d.checklist || {{}}).forEach(([k, v]) => {{
    const e = document.querySelector('[data-chk="' + k + '"]'); if (e) e.checked = v;
  }});
  if (d.verdict) {{
    const e = document.querySelector('input[name=verdict][value="' + d.verdict + '"]');
    if (e) e.checked = true;
  }}
  const p = d.proposed || {{}};
  [['newStrength', p.strength], ['newCertainty', p.certainty], ['newText', p.text]].forEach(([id, v]) => {{
    const e = document.getElementById(id); if (e && v != null) e.value = v;
  }});
  const n = document.getElementById('narrative');
  if (n && typeof d.narrative_edited === "string") n.value = d.narrative_edited;
  (d.candidates || []).forEach(c => {{
    if (c.decision) {{
      const e = document.querySelector('input[name="cand' + c.index + '"][value="' + c.decision + '"]');
      if (e) e.checked = true;
    }}
    const r = document.querySelector('[data-candreason="' + c.index + '"]');
    if (r && c.reason) r.value = c.reason;
  }});
  syncChangeBox(); syncNarrStatus();
}}
function exportJSON() {{
  const d = collect();
  if (!d.reviewer) {{ alert("お名前を入力してください"); return; }}
  if (!d.verdict) {{ alert("判定を選んでください"); return; }}
  const needComment = !["approve", "keep"].includes(d.verdict);
  if (needComment && !d.comment.trim()) {{ alert("コメントを入力してください"); return; }}
  if (d.verdict === "change" && !(d.proposed.strength || d.proposed.text.trim())) {{
    alert("変更後の推奨の強さ、または推奨文（案）を入力してください"); return; }}
  const bad = d.candidates.filter(c => c.decision === "exclude" && !c.reason.trim());
  if (bad.length) {{ alert("除外にした候補文献には理由を入力してください（" + bad.length + "件）"); return; }}
  const blob = new Blob([JSON.stringify(d, null, 2)], {{type: "application/json"}});
  const a = document.createElement("a");
  a.href = URL.createObjectURL(blob);
  a.download = CQ + "_" + (d.reviewer || "reviewer") + ".review.json";
  a.click();
}}
function clearAll() {{
  if (!confirm("この画面の入力を消去します。よろしいですか。")) return;
  localStorage.removeItem(KEY); location.reload();
}}
document.addEventListener("input", save);
document.addEventListener("input", syncNarrStatus);
document.addEventListener("change", () => {{ syncChangeBox(); save(); }});
restore();
</script>
</body></html>"""


def main():
    import argparse
    ap = argparse.ArgumentParser(description="レビューバンドル → 委員用HTML")
    ap.add_argument("bundles", nargs="+")
    ap.add_argument("-o", "--outdir", default=os.path.join(HERE, "..", "review"))
    args = ap.parse_args()
    os.makedirs(args.outdir, exist_ok=True)
    for path in args.bundles:
        with open(path, encoding="utf-8") as f:
            b = json.load(f)
        out = os.path.join(args.outdir, f"{b['cq']['id']}.review.html")
        with open(out, "w", encoding="utf-8") as f:
            f.write(render(b))
        print(f"{b['cq']['id']}: {out}")


if __name__ == "__main__":
    main()
