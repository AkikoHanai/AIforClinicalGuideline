// 総論の改訂の依頼書(Word)を作る。2023年版の該当箇所を、原文のまま全文引用する。  cd platform/soron && node build_docx.js
// 入力: units.json(extract_soron.py が作る)、fig/(紙面から切り出した表・図)。出力: out/総論<記号>_<題名>.docx
const fs = require("fs");
const path = require("path");
const { Document, Packer, Paragraph, TextRun, HeadingLevel, Table, TableRow, TableCell, WidthType, ImageRun, AlignmentType, BorderStyle, ShadingType, Footer, PageNumber } = require("docx");
const units = JSON.parse(fs.readFileSync(path.join(__dirname, "units.json"), "utf8"));
const plan = JSON.parse(fs.readFileSync(path.join(__dirname, "..", "governance", "approved_plan.json"), "utf8"));
const MIN = "Yu Mincho", GO = "Yu Gothic";
const run = (t, o = {}) => new TextRun({ text: t, font: MIN, size: 21, ...o });
const para = (t, o = {}) => new Paragraph({ children: Array.isArray(t) ? t : [run(t)], spacing: { after: 120 }, ...o });
const head = (t, lvl, size) => new Paragraph({ heading: lvl, children: [new TextRun({ text: t, font: GO, bold: true, size })], spacing: { before: 240, after: 120 }, keepNext: true });
const bord = { style: BorderStyle.SINGLE, size: 4, color: "000000" };
const borders = { top: bord, bottom: bord, left: bord, right: bord };
const cell = (children, w, shade) => new TableCell({ width: { size: w, type: WidthType.DXA }, borders, margins: { top: 60, bottom: 60, left: 100, right: 100 },
  shading: shade ? { type: ShadingType.CLEAR, fill: "EDEDED", color: "auto" } : undefined, children });
const W = 9638; // A4、余白 20mm の本文幅

function memoTable() {
  const w = [3200, W - 3200];
  const rows = [["項目", "ご記入欄"], ["改訂の要点(2023年版から変える点)", ""], ["追加・変更する表と図", ""], ["追加する文献(PMID)", ""], ["2023年版から削除する記述", ""]];
  return new Table({ columnWidths: w, width: { size: W, type: WidthType.DXA },
    rows: rows.map((r, i) => new TableRow({ children: r.map((c, j) => cell([new Paragraph({ children: [run(c, { bold: i === 0 || j === 0, font: i === 0 || j === 0 ? GO : MIN })] })], w[j], i === 0 || j === 0)) })) });
}

// 本文の段落: 文献番号は上付き、「表1」「図1」は太字
const runsOf = (b, size = 21) => b.runs.map(([t, bold, sup]) => run(t, { bold: !!bold, font: bold ? GO : MIN, superScript: !!sup, size }));

// 表(編集できる表)。列の幅は紙面の比率。結合セルと、見出し行の網かけを再現する
function editableTable(t) {
  const total = t.widths.reduce((a, b) => a + b, 0), tw = Math.min(W, Math.max(5200, Math.round(total * 20 * 1.15)));
  const widths = t.widths.map((w) => Math.round(w / total * tw));
  const out = [new Paragraph({ children: [run((t.caption || "(前のページから続く表)") + "　［編集用の表］", { size: 18, bold: true, font: GO })], spacing: { before: 60, after: 40 }, keepNext: true })];
  out.push(new Table({ columnWidths: widths, width: { size: widths.reduce((a, b) => a + b, 0), type: WidthType.DXA }, alignment: AlignmentType.CENTER,
    rows: t.rows.map((r) => { let c = 0; return new TableRow({ cantSplit: true, children: r.map((cellv) => { const w = widths.slice(c, c + cellv.span).reduce((a, b) => a + b, 0); c += cellv.span;
      return new TableCell({ width: { size: w, type: WidthType.DXA }, columnSpan: cellv.span > 1 ? cellv.span : undefined, borders, margins: { top: 30, bottom: 30, left: 80, right: 80 },
        shading: cellv.shade ? { type: ShadingType.CLEAR, fill: "E8EEF7", color: "auto" } : undefined, children: [new Paragraph({ children: [run(cellv.text, { size: 17, font: GO })] })] }); }) }); }) }));
  t.notes.forEach((n) => out.push(new Paragraph({ children: [run(n, { size: 16, font: GO })], spacing: { after: 20 } })));
  return out;
}

function figure(b, key) {
  const out = [];
  if (b.img) {
    const natural = b.img.w * 96 / 200, scale = Math.min(1, 630 / natural);
    out.push(new Paragraph({ alignment: AlignmentType.CENTER, spacing: { before: 120, after: 60 }, keepNext: true,
      children: [new ImageRun({ type: "png", data: fs.readFileSync(path.join(__dirname, b.img.file)), transformation: { width: Math.round(natural * scale), height: Math.round(b.img.h * 96 / 200 * scale) } })] }));
    out.push(new Paragraph({ alignment: AlignmentType.CENTER, children: [run(`上: 2023年版 p.${b.page} の紙面(原文の体裁)`, { size: 15, font: GO })], spacing: { after: 60 } }));
  }
  (b.tables || []).forEach((t) => out.push(...editableTable(t)));
  // 図の中の文字、注(表に入らない文字)
  if ((b.fig_rows || []).length) {
    const lines = [new Paragraph({ children: [run(`図の中の文字・注(2023年版 p.${b.page}。紙面と同じ内容)`, { size: 16, bold: true, font: GO })] }),
      ...b.fig_rows.map((r) => new Paragraph({ children: [run(r, { size: 16, font: GO })] }))];
    out.push(new Table({ columnWidths: [W], width: { size: W, type: WidthType.DXA }, rows: [new TableRow({ children: [cell(lines, W, false)] })] }));
  }
  out.push(para("", { spacing: { after: 60 } }));
  return out;
}

function body(u) {
  const out = [];
  for (const b of u.blocks) {
    if (b.t === "h2") out.push(head(b.text, HeadingLevel.HEADING_2, 24));
    else if (b.t === "h3") out.push(head(b.text, HeadingLevel.HEADING_3, 22));
    else if (b.t === "h4") out.push(new Paragraph({ children: [run(b.text, { bold: true, font: GO })], spacing: { before: 160, after: 60 }, keepNext: true }));
    else if (b.t === "p") {
      const first = b.runs.length ? b.runs[0][0] : "";
      const list = /^[・●■◆▶＊※①-⑳]/.test(first);
      out.push(new Paragraph({ children: runsOf(b), spacing: { after: 100 }, alignment: AlignmentType.BOTH,
        indent: list ? { left: (b.indent ? 420 : 0) + 210, hanging: 210 } : b.indent ? { left: 420 } : { firstLine: 210 } }));
    } else if (b.t === "fig") out.push(...figure(b, u.key));
    else if (b.t === "sign") out.push(para([run(b.text)], { alignment: AlignmentType.RIGHT }));
    else if (b.t === "note") out.push(new Paragraph({ children: runsOf(b, 18), spacing: { after: 60 }, indent: { left: 210 } }));
    else if (b.t === "refhead") out.push(head("文献", HeadingLevel.HEADING_3, 22));
    else if (b.t === "ref") out.push(new Paragraph({ children: [run(b.text, { size: 18 })], spacing: { after: 40 }, indent: { left: 420, hanging: 420 } }));
  }
  return out;
}

const footer = (t) => new Footer({ children: [new Paragraph({ alignment: AlignmentType.CENTER, children: [run(t + "　", { size: 16 }), new TextRun({ children: [PageNumber.CURRENT], font: MIN, size: 16 })] })] });
// 敬称: 企画書の担当(姓)に「先生」を付ける。委員会への依頼は、そのまま書く
const honor = (who) => /委員会/.test(who) ? who.replace(/に依頼$/, "") + "(ご依頼先)" : who.split("・").map((n) => n + " 先生").join("、");
const polite = (items) => items.map((t, i) => new Paragraph({ children: [run(`${i + 1}. ${t}`)], indent: { left: 420, hanging: 420 }, spacing: { after: 60 } }));
const safe = (s) => s.replace(/[\\/:*?"<>|]/g, "_").replace(/\s+/g, "");

async function main() {
  const outDir = path.join(__dirname, "out"); fs.mkdirSync(outDir, { recursive: true });
  for (const f of fs.readdirSync(outDir)) if (f.endsWith(".docx")) fs.unlinkSync(path.join(outDir, f));
  const made = [];
  for (const u of units) {
    const is2028 = !!plan["総論"][u.key];
    const label = u.key.replace("_", "-");
    const src = `2023年版 ${u.chapter_title}` + (u.section_title ? ` の「${u.section_title}」` : "") + `(第2章 総論、章のページ pp.${u.chapter_pages}、執筆 ${u.author2023 || "記載なし"})`;
    const v = u.verify, c = u.counts;
    const children = [
      new Paragraph({ children: [run(plan["タイトル"] + "　第2章 総論　改訂原稿のご執筆のお願い", { size: 18 })] }),
      new Paragraph({ heading: HeadingLevel.TITLE, children: [new TextRun({ text: is2028 ? `総論 ${u.title}` : u.title, font: GO, bold: true, size: 32 })], spacing: { before: 100, after: 100 } }),
      para(`ご担当: ${honor(u.who)}`),
      para(`引用元: ${src}`),
      head("1. ご依頼の内容", HeadingLevel.HEADING_1, 26),
      para(`総論「${u.title.replace(/^[A-N](?:-\d)?\. /, "")}」の改訂原稿のご執筆を、お願い申し上げます。`, { indent: { firstLine: 210 } }),
      para("「2. 2023年版の全文」に、2023年版(刊行版)の該当箇所を、原文のまま全文掲載しております。改訂は、この全文を直接ご修正いただく形でお願いいたします。", { indent: { firstLine: 210 } }),
      ...polite(["Word の「変更履歴の記録」をオンにしてご修正ください。追加、削除、変更の箇所が記録されます。",
        "追加される文献には、PMID をお書き添えください。",
        "表は、紙面の画像の下に、編集できる表をお付けしております。表を変更される場合は、編集用の表をご修正ください。図を変更される場合は、新しい図を挿入してください。",
        "下の表に、改訂の要点をご記入ください。",
        "原稿は、GL作成ポータルの「総論の執筆・査読」の画面からご提出ください。提出の時期と書き方は、同じポータルの「手順書」にある「総説執筆者の手順書」に記載しております。"]),
      para("ご不明の点は、統括委員長(華井)までお問い合わせください。ご多用のところ恐れ入りますが、よろしくお願い申し上げます。", { indent: { firstLine: 210 }, spacing: { before: 80, after: 160 } }),
      memoTable(),
      head("2. 2023年版の全文(原文のまま)", HeadingLevel.HEADING_1, 26),
      new Paragraph({ children: [run(`事務局からの注記: 段落 ${c.paragraphs}、文献 ${c.refs}、表・図 ${c.figs}。文字は刊行版 PDF から取り出し、別の方法で取り出した文字と照合しております(2023年版の章 ${u.letter2023}: ${v.pdf_chars} 字のうち、欠落 ${v.missing} 字)。` +
        "和文と英数字の間の空白(組版上のアキ)は入れておりません。英数字に接する「—」は「-」としております。文献番号は上付きにしております。" +
        (c.tables ? `表 ${c.tables} 件は、紙面の画像に加えて、編集できる表をお付けしております(紙面の文字との差 ${c.table_diff} 字)。` : "") +
        (u.corrections.length ? u.corrections.map((x) => `${x.where} は、PDF の文字情報に欠損があるため、紙面の画像から読み取った文字を入れております。お手数ですが、刊行版でご確認ください。`).join("") : ""), { size: 16, font: GO })],
        spacing: { after: 160 }, border: { left: { style: BorderStyle.SINGLE, size: 12, color: "888888", space: 6 } } }),
      ...body(u),
    ];
    if (!is2028) continue;   // 企画書にない項目は作らない
    const name = `総論${u.key}_${safe(plan["総論"][u.key].split(":")[0])}.docx`;
    const doc = new Document({ styles: { default: { document: { run: { font: MIN, size: 21 } } } },
      sections: [{ properties: { page: { size: { width: 11906, height: 16838 }, margin: { top: 1134, bottom: 1134, left: 1134, right: 1134 } } }, footers: { default: footer(is2028 ? `総論 ${label}　2023年版の全文と改訂のお願い` : `2023年版 ${u.letter2023}(参考)`) }, children }] });
    fs.writeFileSync(path.join(outDir, name), await Packer.toBuffer(doc)); made.push(name);
  }
  // 2028年版で新設の項目(2023年版に本文がない)
  for (const [key, v] of Object.entries(plan["総論"])) {
    if (units.some((u) => u.key === key)) continue;
    const [title, who] = [v.slice(0, v.lastIndexOf(":")), v.slice(v.lastIndexOf(":") + 1)];
    const children = [
      new Paragraph({ children: [run(plan["タイトル"] + "　第2章 総論　原稿のご執筆のお願い", { size: 18 })] }),
      new Paragraph({ heading: HeadingLevel.TITLE, children: [new TextRun({ text: `総論 ${key}. ${title}`, font: GO, bold: true, size: 32 })], spacing: { before: 100, after: 100 } }),
      para(`ご担当: ${honor(who)}`),
      head("1. ご依頼の内容", HeadingLevel.HEADING_1, 26),
      para(`総論「${title}」の原稿のご執筆を、お願い申し上げます。`, { indent: { firstLine: 210 } }),
      para("この項目は、2028年版で新設いたします。2023年版の第2章 総論には該当する節がないため、前版の本文の掲載はございません。", { indent: { firstLine: 210 } }),
      ...polite(["引用される文献には、PMID をお書き添えください。",
        "下の表に、執筆の要点をご記入ください。",
        "原稿は、GL作成ポータルの「総論の執筆・査読」の画面からご提出ください。提出の時期と書き方は、同じポータルの「手順書」にある「総説執筆者の手順書」に記載しております。"]),
      para("ご不明の点は、統括委員長(華井)までお問い合わせください。ご多用のところ恐れ入りますが、よろしくお願い申し上げます。", { indent: { firstLine: 210 }, spacing: { before: 80, after: 160 } }),
      memoTable(),
    ];
    const name = `総論${key}_${safe(title)}_新設.docx`;
    const doc = new Document({ styles: { default: { document: { run: { font: MIN, size: 21 } } } },
      sections: [{ properties: { page: { size: { width: 11906, height: 16838 }, margin: { top: 1134, bottom: 1134, left: 1134, right: 1134 } } }, footers: { default: footer(`総論 ${key}　ご執筆のお願い(新設)`) }, children }] });
    fs.writeFileSync(path.join(outDir, name), await Packer.toBuffer(doc)); made.push(name);
  }
  made.sort().forEach((n) => console.log(n));
}
main();
