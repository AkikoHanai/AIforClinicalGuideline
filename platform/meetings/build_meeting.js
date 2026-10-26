// SR委員長との打ち合わせ資料(アジェンダ、EtD案)を Word(.docx)で生成する。 node build_meeting.js
const fs = require("fs");
const { Document, Packer, Paragraph, TextRun, HeadingLevel, Table, TableRow, TableCell, WidthType, AlignmentType,
        BorderStyle, ShadingType, LevelFormat, PageOrientation, Footer, PageNumber } = require("docx");

const FONT = "Yu Gothic";
const T = (t, o = {}) => new TextRun({ text: t, font: FONT, size: 20, ...o });
const P = (t, o = {}) => {
  if (typeof t === "string" && t.includes("\n")) return t.split("\n").map(l => new Paragraph({ children: [T(l)], spacing: { after: 100 }, ...o }));
  return new Paragraph({ children: Array.isArray(t) ? t : [T(t)], spacing: { after: 100 }, ...o });
};
const H1 = (t) => new Paragraph({ heading: HeadingLevel.HEADING_1, children: [new TextRun({ text: t, font: FONT, bold: true, size: 26 })], spacing: { before: 280, after: 120 } });
const H2 = (t) => new Paragraph({ heading: HeadingLevel.HEADING_2, children: [new TextRun({ text: t, font: FONT, bold: true, size: 22 })], spacing: { before: 200, after: 80 } });
const B = (t, lvl = 0) => new Paragraph({ numbering: { reference: "b", level: lvl }, children: Array.isArray(t) ? t : [T(t)], spacing: { after: 50 } });
const N = (t) => new Paragraph({ numbering: { reference: "n", level: 0 }, children: Array.isArray(t) ? t : [T(t)], spacing: { after: 60 } });
const note = (t) => P([T(t, { size: 18, italics: true })]);
const bord = { style: BorderStyle.SINGLE, size: 4, color: "000000" };
const borders = { top: bord, bottom: bord, left: bord, right: bord };
function table(widths, rows, opts = {}) {
  const total = widths.reduce((a, b) => a + b, 0);
  return new Table({ columnWidths: widths, width: { size: total, type: WidthType.DXA },
    rows: rows.map((r, i) => new TableRow({ tableHeader: i === 0 && !opts.noHeader, cantSplit: true, children: r.map((c, j) => new TableCell({
      width: { size: widths[j], type: WidthType.DXA }, borders,
      shading: (i === 0 && !opts.noHeader) ? { type: ShadingType.CLEAR, fill: "EDEDED", color: "auto" } : undefined,
      margins: { top: 40, bottom: 40, left: 80, right: 80 },
      children: String(c ?? "").split("\n").map(line => new Paragraph({ children: [T(line, { size: opts.size || 18, bold: i === 0 && !opts.noHeader })] })) })) })) });
}
const numbering = { config: [
  { reference: "b", levels: [{ level: 0, format: LevelFormat.BULLET, text: "・", alignment: AlignmentType.LEFT, style: { paragraph: { indent: { left: 440, hanging: 280 } } } },
                              { level: 1, format: LevelFormat.BULLET, text: "－", alignment: AlignmentType.LEFT, style: { paragraph: { indent: { left: 880, hanging: 280 } } } }] },
  { reference: "n", levels: [{ level: 0, format: LevelFormat.DECIMAL, text: "%1.", alignment: AlignmentType.LEFT, style: { paragraph: { indent: { left: 440, hanging: 360 } } } }] }] };
const footer = (t) => new Footer({ children: [new Paragraph({ alignment: AlignmentType.CENTER, children: [T(t + "　", { size: 16 }), new TextRun({ children: [PageNumber.CURRENT], font: FONT, size: 16 })] })] });
const PORTRAIT = { page: { size: { width: 11906, height: 16838 }, margin: { top: 1134, bottom: 1134, left: 1134, right: 1134 } } };
const LANDSCAPE = { page: { size: { width: 11906, height: 16838, orientation: PageOrientation.LANDSCAPE }, margin: { top: 1000, bottom: 1000, left: 1000, right: 1000 } } };
const doc = (children, foot, extraSections = []) => new Document({ styles: { default: { document: { run: { font: FONT, size: 20 } } } }, numbering,
  sections: [{ properties: PORTRAIT, footers: { default: footer(foot) }, children: children.flat() }, ...extraSections.map(s => ({ properties: s.landscape ? LANDSCAPE : PORTRAIT, footers: { default: footer(foot) }, children: s.children.flat() }))] });
const plan = JSON.parse(fs.readFileSync(__dirname + "/../governance/approved_plan.json", "utf8"));
const TITLE = plan["タイトル"];
const head = (name, sub) => [new Paragraph({ children: [T(TITLE, { size: 18 })] }),
  new Paragraph({ heading: HeadingLevel.TITLE, children: [new TextRun({ text: name, font: FONT, bold: true, size: 34 })], spacing: { before: 100, after: 80 } }), P(sub)];

// ===================================================================== アジェンダ
const G = head("SR委員長との打ち合わせ　アジェンダ", "日時: 2026年10月26日　時刻: (　　:　　〜　　:　　)　／　出席: 華井明子(統括委員長)、中川夏樹(SRチーム委員長)　／　所要: 60分(案)");
G.push(P("前提: SRチームの体制(担当表)は、Googleフォームで内諾を得ている。基準は、承認済み企画書(Ver1)と提案書v2。"));
G.push(H1("1. SR委員長への依頼事項(40分)"));
G.push(table([500, 2300, 5100, 1700], [["No", "依頼事項", "内容", "期限"],
 ["1", "検索期間の起点の確定", "前回の検索終了日の翌月から2026年10月までを検索する。記録のない4項目(プレガバリン・予防、アミトリプチリン、オピオイド、併用療法)と、記録が一致しない牛車腎気丸(2016年5月と2021年6月)について、担当者に確認し、起点を確定する(別表)", "キックオフ(2026年11月)の前"],
 ["2", "作業規則の確定と周知", "化学療法の6区分、盲検化の基準(二重盲検 0、単盲検 -1、非盲検 -1、記載なし -1)、予防か治療かはMethodで判定、スクリーニング基準(前回Scope)、照合で決まらない項目の最終決定の手続(案: 担当2名の協議、SR委員長の案、統括委員長が決定)。ガバペンチノイド(プレガバリン、ミロガバリン)を別CQとする案の可否。確定後、キックオフで全SR委員に周知する", "キックオフ(2026年11月)"],
 ["3", "進捗管理", "毎月末に、書類の作成状況(Excel)を確認し、遅延している担当者に連絡し、統括委員長へ月次報告を行う。工程の期限: 検索・一次スクリーニング 12月末、二次スクリーニング 1月末、研究特性 2月末、様式4-5 3月末、照合 4月中旬、様式SR-8 4月末、草案とEtD 5月上旬", "毎月末"],
 ["4", "EtDの実施責任", "様式案の承認後、記入の分担と時期(4月末〜5月上旬)を担当者に指示し、記入内容を点検する", "2027年4月"],
 ["5", "利益相反の把握", "直接評価する論文の筆頭著者に当たる委員を、担当ごとに把握し、投票除外の候補表を作成する。中川先生自身の担当(運動・予防)の協議には、第三者を加える", "2026年11月末"],
 ["6", "キックオフ会議の準備", "日程調整と、周知事項(依頼事項2)の資料化", "2026年11月"]], { size: 15 }));
G.push(H1("2. EtD様式案の確認(15分)"));
G.push(P("様式案(A 推奨、B アウトカム別のエビデンス、C 考慮する項目、D 変更点と理由、E 投票)と、C-2〜C-4の判断の選択肢を承認する。C-3(患者・市民の価値観と希望)の根拠の記録方法を決める。説明は、EtD案の説明を参照。"));
G.push(H1("3. 決定事項の記録(5分)"));
G.push(table([500, 4300, 2200, 1500, 1500], [["No", "決定事項", "決定内容", "担当", "期限"],
 ["1", "検索期間の起点が記録にない4項目と、牛車腎気丸の起点", "", "", ""],
 ["2", "ガバペンチノイド(プレガバリン、ミロガバリン)を別CQとするか", "", "", ""],
 ["3", "照合で決まらない項目の最終決定の手続", "", "", ""],
 ["4", "EtD様式案の承認(判断の選択肢を含む)", "", "", ""],
 ["5", "キックオフ会議の日程、月次報告の形式", "", "", ""]], { size: 15 }));
G.push(H1("別表　前回(2023年版)の検索終了日"));
G.push(table([3400, 2000, 4700], [["CQ", "前回の検索終了日", "備考"],
 ["CQ1-牛車腎気丸", "要確認", "検索過程の文書: 2016年5月31日。2023年版のワークシート: 2021年6月"],
 ["CQ1-プレガバリン(予防)", "記録なし", "CQ2-プレガバリン(2021年8月12日)を使用できるか"],
 ["CQ1-カルニチン", "2021年6月30日", ""],
 ["CQ1-冷却・圧迫", "2021年8月3日", "2021年6月の記録もある。統合CQの起点を1つに決める"],
 ["CQ1・CQ2-運動", "2021年9月4日", "予防と治療で同じ検索過程"],
 ["CQ1・CQ2-鍼灸", "2021年(月の記録なし)", "月を確認する"],
 ["CQ2-デュロキセチン", "2021年12月12日", "2021年7月31日の検索もある"],
 ["CQ2-アミトリプチリン", "記録なし", ""],
 ["CQ2-プレガバリン、ミロガバリン", "2021年8月12日", "同じ検索過程"],
 ["FRQ ビタミンB12", "2021年6月", ""],
 ["FRQ NSAIDs", "2021年6月30日", ""],
 ["FRQ オピオイド、併用療法", "記録なし", ""]], { size: 15 }));

// ===================================================================== EtD案の説明
const E = head("EtD(推奨作成の記録)案の説明", "SR委員長との打ち合わせ用(2026年10月26日)　／　様式案: CIPN_EtD_2028様式案.xlsx(CQごとに1シート)");
E.push(P("EtDは、SR作業の結果(様式4-5、SR-8、SoF)を、推奨作成会議の判断につなぐ記録である。2023年版の体裁(推奨文、強さ・確実性・合意率、解説、投票結果)と、2023年版の推奨決定の方針(総括的なエビデンスの確実性、望ましい効果と望ましくない効果のバランス、患者・市民の価値観と希望、資源の利用(高額が予想される場合のみ))を残し、2028年版の記入欄を並べた。2023年版の記載は、刊行版PDFから取り出して入力済みである。"));
E.push(H1("1. 構成"));
E.push(table([1800, 3500, 2000, 2300], [["区分", "内容", "入力元", "記入者・時期"],
 ["A 推奨", "2023年版と2028年版案(推奨文、強さ、確実性)", "2023年版(入力済み)、SR担当の草案", "SR担当 / 2027年5月上旬"],
 ["B アウトカム別のエビデンス", "重要度、研究数、化学療法の層ごとの結果、効果の要約、確実性", "様式SR-8、SoF", "SR担当 / 2027年4月末"],
 ["C 考慮する項目", "C-1 総括的な確実性、C-2 益と害のバランス、C-3 患者・市民の価値観と希望、C-4 資源", "C-1: SR-8。C-2〜C-4: SR担当の案", "SR担当(案)、会議で確認"],
 ["D 変更点と理由", "2023年版からの変更点、新規文献のPMID", "SR担当", "SR担当 / 2027年5月上旬"],
 ["E 投票", "確定した強さ、回、有資格者数", "決定記録シート", "記録者 / 会議後"]], { size: 15 }));
E.push(H1("2. 判断の選択肢(案)"));
E.push(table([3000, 6600], [["項目", "選択肢"],
 ["C-1", "A / B / C / D(様式SR-8の結果)"],
 ["C-2 益と害のバランス", "望ましい効果が大きく上回る / やや上回る / 同等 / 望ましくない効果がやや上回る / 大きく上回る / 判断できない"],
 ["C-3 患者・市民の価値観と希望", "ばらつきはない / ばらつきがある / 判断できない(根拠欄に判断の元を記載)"],
 ["C-4 資源", "検討が必要(高額が予想される) / 検討は不要"]], { size: 15 }));
E.push(H1("3. 検討事項"));
["構成(A〜E)と選択肢の承認。", "C-3の根拠の記録方法。投票者に患者代表は含まないため、外部評価委員(浜野純、桜井なおみ)の意見、患者の価値観を調べた文献を候補とする。", "FRQのEtDは、研究課題の記載を中心とし、C-2〜C-4を省略するか。", "提供されたGRADE EtD(11基準)の下書き(17CQ、2023年版の記載から作成済み)を採用するか。2023年版の方針は4項目である。"].forEach(t => E.push(B(t)));

(async () => {
  const save = async (name, d) => { fs.writeFileSync(__dirname + "/out/" + name, await Packer.toBuffer(d)); console.log(name); };
  await save("SR委員長との打ち合わせ_アジェンダ.docx", doc([G], "SR委員長との打ち合わせ アジェンダ"));
  await save("EtD案の説明.docx", doc([E], "EtD案の説明"));
})();
