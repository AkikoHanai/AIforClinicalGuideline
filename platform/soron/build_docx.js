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
  const rows = [["項目", "記入欄(担当委員)"], ["改訂の要点(2023年版から変える点)", ""], ["追加・変更する表と図", ""], ["追加する文献(PMID)", ""], ["2023年版から削除する記述", ""]];
  return new Table({ columnWidths: w, width: { size: W, type: WidthType.DXA },
    rows: rows.map((r, i) => new TableRow({ children: r.map((c, j) => cell([new Paragraph({ children: [run(c, { bold: i === 0 || j === 0, font: i === 0 || j === 0 ? GO : MIN })] })], w[j], i === 0 || j === 0)) })) });
}

// 本文の段落: 文献番号は上付き、「表1」「図1」は太字
const runsOf = (b, size = 21) => b.runs.map(([t, bold, sup]) => run(t, { bold: !!bold, font: bold ? GO : MIN, superScript: !!sup, size }));

function figure(b, key) {
  const out = [];
  if (b.img) {
    const natural = b.img.w * 96 / 200, scale = Math.min(1, 630 / natural);
    out.push(new Paragraph({ alignment: AlignmentType.CENTER, spacing: { before: 120, after: 60 }, keepNext: true,
      children: [new ImageRun({ type: "png", data: fs.readFileSync(path.join(__dirname, b.img.file)), transformation: { width: Math.round(natural * scale), height: Math.round(b.img.h * 96 / 200 * scale) } })] }));
  }
  // 表と図の文字(紙面の画像と同じ内容。変更するときに書き換える)
  const lines = [new Paragraph({ children: [run(`表・図の文字(2023年版 p.${b.page}。上の画像と同じ内容)`, { size: 16, bold: true, font: GO })] }),
    ...b.rows.map((r) => new Paragraph({ children: [run(r, { size: 16, font: GO })] }))];
  out.push(new Table({ columnWidths: [W], width: { size: W, type: WidthType.DXA }, rows: [new TableRow({ children: [cell(lines, W, false)] })] }));
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
      new Paragraph({ children: [run(plan["タイトル"] + "　第2章 総論　改訂の依頼", { size: 18 })] }),
      new Paragraph({ heading: HeadingLevel.TITLE, children: [new TextRun({ text: is2028 ? `総論 ${u.title}` : u.title, font: GO, bold: true, size: 32 })], spacing: { before: 100, after: 100 } }),
      para(is2028 ? `2028年版の担当: ${u.who}` : "2028年版の企画書に、対応する項目はない。参考として 2023年版の全文を示す。"),
      para(`引用元: ${src}`),
      head("1. 依頼事項", HeadingLevel.HEADING_1, 26),
      para("「2. 2023年版の全文」は、2023年版(刊行版)の該当箇所を、原文のまま全文引用したものである。改訂は、この全文を直接書き換えて行う。", { indent: { firstLine: 210 } }),
      new Paragraph({ children: [run("1. Word の「変更履歴の記録」をオンにして書き換える(追加、削除、変更の箇所を残す)。")], indent: { left: 420, hanging: 420 }, spacing: { after: 60 } }),
      new Paragraph({ children: [run("2. 追加する文献には PMID を付ける。")], indent: { left: 420, hanging: 420 }, spacing: { after: 60 } }),
      new Paragraph({ children: [run("3. 表と図は、2023年版の紙面を画像で示している。変更する場合は、画像の下の「表・図の文字」を書き換えるか、新しい表・図を挿入する。")], indent: { left: 420, hanging: 420 }, spacing: { after: 60 } }),
      new Paragraph({ children: [run("4. 下の表に、改訂の要点を記入する。")], indent: { left: 420, hanging: 420 }, spacing: { after: 120 } }),
      memoTable(),
      head("2. 2023年版の全文(原文のまま)", HeadingLevel.HEADING_1, 26),
      new Paragraph({ children: [run(`段落 ${c.paragraphs}、文献 ${c.refs}、表・図 ${c.figs}。文字は刊行版 PDF の文字層から取り出し、別の方法で取り出した文字と照合した(2023年版の章 ${u.letter2023}: ${v.pdf_chars} 字のうち、落ちた文字 ${v.missing} 字)。` +
        "和文と英数字の間の空白(組版上のアキ)は入れていない。英数字に接する「—」は「-」とした。文献番号は上付きにした。表と図は紙面から切り出した画像である。" +
        (u.corrections.length ? u.corrections.map((x) => `${x.where} は、PDF の文字層が壊れているため、紙面の画像から読み取った文字を入れた。紙面で確認すること。`).join("") : ""), { size: 16, font: GO })],
        spacing: { after: 160 }, border: { left: { style: BorderStyle.SINGLE, size: 12, color: "888888", space: 6 } } }),
      ...body(u),
    ];
    const name = is2028 ? `総論${u.key}_${safe(plan["総論"][u.key].split(":")[0])}.docx` : `参考_2023年版${u.letter2023}_2028年版に対応する項目なし.docx`;
    const doc = new Document({ styles: { default: { document: { run: { font: MIN, size: 21 } } } },
      sections: [{ properties: { page: { size: { width: 11906, height: 16838 }, margin: { top: 1134, bottom: 1134, left: 1134, right: 1134 } } }, footers: { default: footer(is2028 ? `総論 ${label}　2023年版の全文と改訂の依頼` : `2023年版 ${u.letter2023}(参考)`) }, children }] });
    fs.writeFileSync(path.join(outDir, name), await Packer.toBuffer(doc)); made.push(name);
  }
  // 2028年版で新設の項目(2023年版に本文がない)
  for (const [key, v] of Object.entries(plan["総論"])) {
    if (units.some((u) => u.key === key)) continue;
    const [title, who] = [v.slice(0, v.lastIndexOf(":")), v.slice(v.lastIndexOf(":") + 1)];
    const children = [
      new Paragraph({ children: [run(plan["タイトル"] + "　第2章 総論　執筆の依頼", { size: 18 })] }),
      new Paragraph({ heading: HeadingLevel.TITLE, children: [new TextRun({ text: `総論 ${key}. ${title}`, font: GO, bold: true, size: 32 })], spacing: { before: 100, after: 100 } }),
      para(`2028年版の担当: ${who}`),
      head("1. 依頼事項", HeadingLevel.HEADING_1, 26),
      para("この項目は 2028年版で新設する。2023年版の第2章 総論に、該当する節はない。引用する前版の本文はない。", { indent: { firstLine: 210 } }),
      new Paragraph({ children: [run("1. 文献には PMID を付ける。")], indent: { left: 420, hanging: 420 }, spacing: { after: 60 } }),
      new Paragraph({ children: [run("2. 下の表に、執筆の要点を記入する。")], indent: { left: 420, hanging: 420 }, spacing: { after: 120 } }),
      memoTable(),
    ];
    const name = `総論${key}_${safe(title)}_新設.docx`;
    const doc = new Document({ styles: { default: { document: { run: { font: MIN, size: 21 } } } },
      sections: [{ properties: { page: { size: { width: 11906, height: 16838 }, margin: { top: 1134, bottom: 1134, left: 1134, right: 1134 } } }, footers: { default: footer(`総論 ${key}　執筆の依頼(新設)`) }, children }] });
    fs.writeFileSync(path.join(outDir, name), await Packer.toBuffer(doc)); made.push(name);
  }
  made.sort().forEach((n) => console.log(n));
}
main();
