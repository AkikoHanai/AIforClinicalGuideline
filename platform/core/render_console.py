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
STRENGTH_JA = {"1": "1（強い推奨）", "2": "2（弱い推奨）", "なし": "推奨なし"}

CSS = """
*{box-sizing:border-box}
body{margin:0;font-family:-apple-system,BlinkMacSystemFont,"Hiragino Sans","Noto Sans JP",sans-serif;
 background:#f6f7f9;color:#16202b;line-height:1.7;font-size:15px}
header{background:#0f3d3e;color:#fff;padding:18px 28px}
header .cqid{font-size:12px;letter-spacing:.12em;color:#6ecfc4}
header h1{margin:4px 0 10px;font-size:20px;font-weight:700}
.wrap{max-width:1180px;margin:0 auto;padding:22px 28px 90px}
.badge{display:inline-block;padding:3px 10px;border-radius:999px;font-size:12px;font-weight:700}
.ok{background:#1c7c4a;color:#fff}.ng{background:#b3261e;color:#fff}
.warn{background:#a86200;color:#fff}.mute{background:#e3e6ea;color:#41505f}
section{background:#fff;border:1px solid #e0e4e9;border-radius:10px;padding:18px 20px;margin:16px 0}
section>h2{margin:0 0 12px;font-size:15px;font-weight:700;color:#0f3d3e;
 border-left:4px solid #17a398;padding-left:9px}
table{width:100%;border-collapse:collapse;font-size:14px}
th,td{border-bottom:1px solid #eceff2;padding:8px 9px;text-align:left;vertical-align:top}
th{background:#f2f5f6;font-weight:600;font-size:13px;color:#41505f}
.scroll{overflow-x:auto}
.issue{border-left:4px solid #b3261e;background:#fdf3f2;padding:10px 13px;margin:8px 0;border-radius:5px}
.issue.w{border-color:#a86200;background:#fdf8ee}
.issue .rule{font-weight:700;font-size:13px}
.issue .d{font-size:13.5px;color:#3b4854;margin-top:3px}
.rec{background:#f0f8f7;border:1px solid #bfe0dc;border-radius:8px;padding:14px 16px;font-size:16px;font-weight:600}
.kv{display:flex;flex-wrap:wrap;gap:8px;margin-top:10px}
.kv div{background:#f2f5f6;border-radius:6px;padding:5px 11px;font-size:13px}
.kv b{color:#0f3d3e}
details.study{border:1px solid #e0e4e9;border-radius:8px;margin:8px 0;background:#fcfdfd}
details.study>summary{cursor:pointer;padding:10px 13px;font-size:14px;list-style:none}
details.study>summary::-webkit-details-marker{display:none}
details.study>summary:before{content:"▸ ";color:#17a398}
details.study[open]>summary:before{content:"▾ "}
.sbody{padding:0 14px 13px;font-size:13.5px}
.tag{display:inline-block;background:#e7edf1;border-radius:4px;padding:1px 7px;font-size:11.5px;margin-left:6px}
.tag.r{background:#b3261e;color:#fff}.tag.ma{background:#3d5a80;color:#fff}
.tag.dup{background:#a86200;color:#fff}
a{color:#0b6ea8}
.chain{border-left:3px solid #17a398;padding-left:13px;margin:10px 0;font-size:13.5px}
.chk{border-top:1px solid #eceff2;padding:9px 0;display:flex;gap:10px;align-items:flex-start}
.chk input[type=checkbox]{margin-top:5px;width:17px;height:17px;flex:none}
.chk .q{flex:1}.chk .q small{color:#5b6a78;display:block;font-size:12.5px}
textarea{width:100%;min-height:78px;border:1px solid #ccd3da;border-radius:6px;padding:9px;
 font-family:inherit;font-size:14px;resize:vertical}
.verdicts{display:flex;gap:9px;flex-wrap:wrap;margin:12px 0}
.verdicts label{border:1.5px solid #ccd3da;border-radius:7px;padding:8px 14px;cursor:pointer;font-size:14px;background:#fff}
.verdicts input{margin-right:6px}
.bar{position:fixed;left:0;right:0;bottom:0;background:#0f3d3e;color:#fff;padding:11px 28px;
 display:flex;gap:12px;align-items:center;font-size:13.5px}
button{background:#17a398;color:#fff;border:0;border-radius:7px;padding:9px 17px;font-size:14px;
 font-weight:700;cursor:pointer}
button.ghost{background:transparent;border:1.5px solid #6ecfc4;color:#6ecfc4}
.note{font-size:12.5px;color:#5b6a78}
.demo{background:#fdf8ee;border:1px solid #e3c98a;border-radius:8px;padding:11px 14px;
 font-size:13.5px;color:#6b4d00;margin:14px 0}
@media(prefers-color-scheme:dark){
 body{background:#11171d;color:#e6eaee}
 section{background:#1a222b;border-color:#2b3742}
 th{background:#222c36;color:#a9b7c4}td,th{border-color:#2b3742}
 .rec{background:#14302e;border-color:#2a5c56}.kv div{background:#222c36}
 .kv b{color:#6ecfc4}details.study{background:#1a222b;border-color:#2b3742}
 .issue{background:#2c1a19}.issue.w{background:#2b2415}.issue .d{color:#c3cdd6}
 textarea{background:#141b22;color:#e6eaee;border-color:#38454f}
 .verdicts label{background:#1a222b;border-color:#38454f;color:#e6eaee}
 .mute{background:#2b3742;color:#c3cdd6}.tag{background:#2b3742;color:#dbe3ea}
 a{color:#6ab7e8}.note,.chk .q small{color:#9dabb8}
 .demo{background:#2b2415;border-color:#5a4a1e;color:#e8d5a3}
 section>h2{color:#6ecfc4}
}
"""

# 委員が必ず答えるチェック項目。AGREE II の該当項目を併記する
CHECKLIST = [
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


def _issues_html(b):
    out = []
    for v in b["validation"]["violations"]:
        out.append(f'<div class="issue"><div class="rule">{esc(v["rule"])} 違反</div>'
                   f'<div class="d">{esc(v["detail"])}</div></div>')
    for c in b["cross_check"]:
        lv = c.get("level")
        if lv == "info":
            continue
        cls = "issue" if lv == "block" else "issue w"
        label = "AI生成の申告と根拠の不一致" if lv == "block" else "要確認"
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


def _studies_html(b):
    out = []
    for s in b["studies"]:
        tags = ""
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

    rec_block = f"""
<section>
  <h2>推奨案（AI生成・未承認）</h2>
  <div class="rec">{esc(d.get('recommendation_text') or '（推奨案が未生成です）')}</div>
  <div class="kv">
    <div><b>推奨の強さ</b> {esc(STRENGTH_JA.get(d.get('strength'), d.get('strength') or '—'))}</div>
    <div><b>方向</b> {esc({'for': '行うことを推奨', 'against': '行わないことを推奨'}.get(d.get('direction'), d.get('direction') or '—'))}</div>
    <div><b>AI申告の確実性</b> {esc(d.get('certainty') or '—')}</div>
    <div><b>グラフから導いた確実性</b> {esc(derived.get('overall') or '—')}</div>
    <div><b>合意率</b> {esc(f"{vote.get('agreement_rate'):.0%}" if vote.get('agreement_rate') is not None else '—')}
      {esc(f"（{vote.get('n_panel')}名）" if vote.get('n_panel') else '')}</div>
  </div>
  <p class="note">確実性は「重大アウトカムの総体のうち最も低いもの」として機械的に導出しています：{esc(derived.get('reason') or '')}</p>
</section>"""

    if not ready:
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
        narrative = (f'<section><h2>解説文（Phase2生成）</h2>'
                     f'<div style="white-space:pre-wrap">{esc(bundle["narrative"])}</div></section>')

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
  {_issues_html(bundle)}
  <p class="note">Minds規則 R1–R8（適格性・二重計上・撤回・非直接性・重大アウトカム・格下げ理由）と、
  AI生成の申告値の照合を、決定論的に実行した結果です。</p>
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

<section><h2>採用文献（クリックで結果を展開）</h2>{_studies_html(bundle)}</section>

<section><h2>推奨の由来（AGREE II 項目12の証跡）</h2>{_provenance_html(bundle)}
<p class="note">推奨 → エビデンス総体 → 格下げ要因 → 論文PMID の連鎖です。この鎖に載っていない根拠は、推奨の裏づけになりません。</p></section>

{"<section><h2>EtD（判断の枠組み）</h2><div class='scroll'><table>" + etd_rows + "</table></div></section>" if etd_rows else ""}

{narrative}

<section>
  <h2>あなたの確認</h2>
  {checklist}
  <div class="verdicts">
    <label><input type="radio" name="verdict" value="approve">承認する</label>
    <label><input type="radio" name="verdict" value="conditional">条件付き承認（コメント必須）</label>
    <label><input type="radio" name="verdict" value="revise">差し戻す（コメント必須）</label>
  </div>
  <textarea id="comment" placeholder="コメント（差し戻し・条件付き承認の場合は必須。どの記述を、何を根拠に、どう直すかを書いてください）"></textarea>
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
function collect() {{
  const chk = {{}};
  document.querySelectorAll('[data-chk]').forEach(e => chk[e.dataset.chk] = e.checked);
  const v = document.querySelector('input[name=verdict]:checked');
  return {{cq: CQ, reviewer: document.getElementById('reviewer').value,
          verdict: v ? v.value : null, checklist: chk,
          comment: document.getElementById('comment').value,
          saved_at: new Date().toISOString()}};
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
}}
function exportJSON() {{
  const d = collect();
  if (!d.reviewer) {{ alert("お名前を入力してください"); return; }}
  if (!d.verdict) {{ alert("承認・条件付き承認・差し戻しのいずれかを選んでください"); return; }}
  if (d.verdict !== "approve" && !d.comment.trim()) {{ alert("コメントを入力してください"); return; }}
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
document.addEventListener("change", save);
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
