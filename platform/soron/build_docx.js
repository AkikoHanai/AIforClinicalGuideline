const fs = require("fs");
const { Document, Packer, Paragraph, TextRun, HeadingLevel, Table, TableRow, TableCell, WidthType,
        ImageRun, AlignmentType, BorderStyle, ShadingType, LevelFormat, PageBreak } = require("docx");
const units = JSON.parse(fs.readFileSync("units.json", "utf8"));
const IDEAS = JSON.parse(fs.readFileSync("ideas.json", "utf8"));
const FONT = "Yu Mincho";
const run = (t, o = {}) => new TextRun({ text: t, font: FONT, size: 21, ...o });
const para = (t, o = {}) => new Paragraph({ children: [run(t)], spacing: { after: 120 }, ...o });
const h = (t, lvl) => new Paragraph({ heading: lvl, children: [new TextRun({ text: t, font: "Yu Gothic", bold: true })], spacing: { before: 240, after: 120 } });
const bullet = (t) => new Paragraph({ numbering: { reference: "b", level: 0 }, children: [run(t)], spacing: { after: 60 } });
const bord = { style: BorderStyle.SINGLE, size: 4, color: "000000" };
const borders = { top: bord, bottom: bord, left: bord, right: bord };
const cell = (t, w, head = false) => new TableCell({ width: { size: w, type: WidthType.DXA }, borders,
  shading: head ? { type: ShadingType.CLEAR, fill: "EDEDED", color: "auto" } : undefined,
  children: [new Paragraph({ children: [run(t, { bold: head })] })] });
function memoTable() {
  const W = [2600, 6760];
  const rows = [["項目", "記入欄（担当委員）"], ["改訂の要点（2023年版から何を変えるか）", ""], ["追加・更新する図表（下の提案から選ぶ／独自案）", ""],
                ["追加する文献（PMID）", ""], ["2023年版から削除する記述", ""], ["事務局への依頼（作図・データ収集など）", ""]];
  return new Table({ columnWidths: W, width: { size: 9360, type: WidthType.DXA },
    rows: rows.map((r, i) => new TableRow({ children: r.map((c, j) => cell(c, W[j], i === 0 || j === 0)) })) });
}
function bodyParas(paras) {
  const out = [];
  for (const p of paras) {
    if (p === "##文献") { out.push(h("文献（2023年版）", HeadingLevel.HEADING_2)); continue; }
    if (p.startsWith("#")) { out.push(h(p.slice(1), HeadingLevel.HEADING_3)); continue; }
    if (/^(表|図)\s*\d+．/.test(p)) {
      out.push(new Paragraph({ children: [run("［" + p.slice(0, 40) + "…］ 表・図の本文は末尾のページ画像を参照（テキストは参考）", { italics: true, color: "444444" })], spacing: { after: 120 } }));
      continue;
    }
    const runs = []; const parts = p.split(/\^([^^]+)\^/);
    parts.forEach((s, i) => { if (!s) return; runs.push(i % 2 ? run(s, { superScript: true }) : run(s)); });
    out.push(new Paragraph({ children: runs, spacing: { after: 120 }, indent: { firstLine: 210 } }));
  }
  return out;
}
for (const u of units) {
  const idea = IDEAS[u.key] || { existing: [], proposals: [] };
  const children = [
    new Paragraph({ children: [run("がん薬物療法に伴う末梢神経障害診療ガイドライン 改訂版　第2章 総論　改訂原稿", { size: 18 })] }),
    new Paragraph({ heading: HeadingLevel.TITLE, children: [new TextRun({ text: u.title, font: "Yu Gothic", bold: true, size: 32 })] }),
    para(`担当：${u.who}　／　2023年版 第2章 pp.${u.pages} の原文を起こしたもの`),
    h("1. 改訂の進め方", HeadingLevel.HEADING_1),
    para("「3. 2023年版 原文」を直接書き換えてください（変更履歴をオンにして編集）。2023年版以降の知見の追加、図表の追加、古い記述の削除が改訂の中心です。図表は下の提案から選んでも、独自に提案しても構いません。作図は事務局で行えるので、内容（項目・数値・順序）を指定してください。"),
    memoTable(),
    h("2. 図表の提案（事務局案）", HeadingLevel.HEADING_1),
    para("2023年版に既にある図表：" + (idea.existing.length ? idea.existing.join("、") : "なし")),
    ...idea.proposals.map(bullet),
    h("3. 2023年版 原文", HeadingLevel.HEADING_1),
    ...bodyParas(u.paras),
  ];
  if (u.images.length) {
    children.push(new Paragraph({ children: [new PageBreak()] }));
    children.push(h("4. 2023年版の図表（ページ画像・参照用）", HeadingLevel.HEADING_1));
    for (const im of u.images) {
      children.push(para(`2023年版 p.${im.page}`));
      children.push(new Paragraph({ alignment: AlignmentType.CENTER,
        children: [new ImageRun({ type: "png", data: fs.readFileSync(im.file), transformation: { width: 520, height: 734 } })] }));
    }
  }
  const doc = new Document({
    styles: { default: { document: { run: { font: FONT, size: 21 } } } },
    numbering: { config: [{ reference: "b", levels: [{ level: 0, format: LevelFormat.BULLET, text: "・", alignment: AlignmentType.LEFT, style: { paragraph: { indent: { left: 420, hanging: 280 } } } }] }] },
    sections: [{ properties: { page: { margin: { top: 1418, bottom: 1418, left: 1418, right: 1418 } } }, children }],
  });
  const name = `総論${u.key}_${u.title.replace(/[\/／「」]/g, "").replace(/\s+/g, "").slice(0, 30)}.docx`;
  Packer.toBuffer(doc).then(b => { fs.mkdirSync("out", { recursive: true }); fs.writeFileSync("out/" + name, b); console.log(name); });
}
