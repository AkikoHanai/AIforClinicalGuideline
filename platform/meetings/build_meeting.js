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
const G = head("SR委員長との打ち合わせ　アジェンダ", "日時: 2026年10月26日　時刻: (　　:　　〜　　:　　)　／　出席: 華井明子(統括委員長)、中川夏樹(SRチーム委員長)　／　所要: 100分(案)");
G.push(H1("1. 目的"));
G.push(P("2026年11月のキックオフ会議と、SRの作業開始に向けて、体制、検索の起点、作業の規則、EtD(推奨作成の記録)の様式、スケジュールを確認し、決める。基準は、承認済み企画書(Ver1 2026年6月17日)と提案書v2である。"));
G.push(H1("2. 事前に見ていただく資料"));
["操作マニュアル(第3〜5章: フォルダ管理、2023年版のEtD)", "SR委員長の業務手順、SR委員の手順書", "EtD 2023年版準拠(Excel。17CQ)、EtD 2028年版様式案(Excel。16シート)、EtD案の説明(Word)", "統括委員会へのお願い(スケジュール案、決定が必要な事項)"].forEach(t => G.push(B(t)));
G.push(H1("3. 議題"));
G.push(table([500, 900, 2700, 4300, 1700], [["No", "時間", "議題", "内容", "決めること"],
 ["1", "5分", "開会", "目的と資料の確認", "—"],
 ["2", "10分", "現状の報告", "アプリ(論文概要、決定記録シート、Minds書類の出力、Googleドライブ JASCC_GL での管理)と、動作検証(画面22項目、テスト27件)の結果。未実施: Bedrockによる論文からの抽出(AWS認証が必要)、論文PDFの入手(検証用データで未入手66件。実データの件数は、papers コマンドの後に確認)", "—"],
 ["3", "15分", "体制の確認", "担当表(SR項目11、FRQ4)。参画打診中の久保絵美(鍼灸・治療)、川口展子(冷却・圧迫・予防)、在原洋平(カルニチン・予防)の返事の状況。処理量の少ない項目(カルニチン、FRQ)を1名で作業するか。中川夏樹先生自身の担当(運動・予防)の協議に、第三者を加えるか", "打診の期限、代替の担当、1名作業の項目"],
 ["4", "15分", "検索の起点", "前回の検索終了日の翌月から2026年10月まで(別表)。記録のない4項目(プレガバリン・予防、アミトリプチリン、オピオイド、併用療法)の起点。牛車腎気丸は、検索過程の文書が2016年5月まで、2023年版のワークシートが2021年6月で、記録が一致しない", "各CQの起点(別表の要確認)"],
 ["5", "20分", "作業の規則", "化学療法の分類6区分。盲検化の基準(二重盲検 0、単盲検 -1、非盲検 -1、記載なし -1)。予防か治療かはMethodで判定。スクリーニングの基準(前回Scope)。照合で決まらない項目の最終決定者(案: 担当2名の協議、SR委員長の案、統括委員長が決定)。同じ担当の別チーム(運動、鍼灸の予防と治療)の情報共有。ガバペンチノイド(プレガバリン、ミロガバリン)を別CQにする案", "規則の確定(キックオフで全委員に伝える)"],
 ["6", "20分", "EtD案", "様式案(A 推奨、B アウトカム別のエビデンス、C 考慮する項目、D 変更点と理由、E 投票)。記入する人、時期、入力元。判断の選択肢(案)。患者・市民の価値観の記録方法", "様式、選択肢、記入の分担"],
 ["7", "10分", "スケジュール", "キックオフ(2026年11月)。12月末: 検索・一次スクリーニング。2027年1月末: 二次。2月末: 研究特性。3月末: 4-5。4月中旬: 照合。4月末: SR-8。5月上旬: 草案とEtD。5月: 推奨作成会議。毎月末の書類の作成状況の点検と、月次報告の形式", "キックオフの日程、月次報告の形式"],
 ["8", "5分", "決定事項と宿題の確認", "第4章の表を確認し、担当と期限を記入する", "—"]], { size: 15 }));
G.push(H1("4. 別表: 前回(2023年版)の検索終了日(SR統括ファイルの検索過程の記録)"));
G.push(table([3400, 2000, 4700], [["CQ", "前回の検索終了日", "備考"],
 ["CQ1-牛車腎気丸", "要確認", "検索過程の文書: 2016年5月31日(手引き2017の検索)。2023年版のワークシート: 2021年6月"],
 ["CQ1-プレガバリン(予防)", "記録なし", "CQ2-プレガバリンの記録(2021年8月12日)を使えるか"],
 ["CQ1-カルニチン", "2021年6月30日", ""],
 ["CQ1-冷却・圧迫", "2021年8月3日", "2021年6月の記録もある(圧迫)。統合CQの起点を1つに決める"],
 ["CQ1-運動、CQ2-運動", "2021年9月4日", "同じ検索過程。予防と治療で共有"],
 ["CQ1-鍼灸、CQ2-鍼灸", "2021年(月の記録なし)", "同じ検索過程。月を確認する"],
 ["CQ2-デュロキセチン", "2021年12月12日", "2021年7月31日の検索もある"],
 ["CQ2-アミトリプチリン", "記録なし", ""],
 ["CQ2-プレガバリン、CQ2-ミロガバリン", "2021年8月12日", "同じ検索過程"],
 ["FRQ ビタミンB12", "2021年6月", "検索期間 2016年6月〜2021年6月"],
 ["FRQ NSAIDs", "2021年6月30日", "検索期間 2016年6月〜2021年6月"],
 ["FRQ オピオイド", "記録なし", ""],
 ["FRQ 併用療法", "記録なし", ""]], { size: 15 }));
G.push(H1("5. 決定事項と宿題(記入欄)"));
G.push(table([500, 4400, 2000, 1500, 1700], [["No", "事項", "決定", "担当", "期限"],
 ["1", "キックオフ会議の日程(2026年11月)", "", "", ""],
 ["2", "久保・川口・在原の打診の期限と、返事がない場合の代替", "", "", ""],
 ["3", "1名で作業する項目", "", "", ""],
 ["4", "検索の起点が記録にない4項目と、牛車腎気丸の起点", "", "", ""],
 ["5", "ガバペンチノイド(プレガバリン、ミロガバリン)を別CQにするか", "", "", ""],
 ["6", "照合で決まらない項目の最終決定者", "", "", ""],
 ["7", "EtD様式案の承認(判断の選択肢を含む)", "", "", ""],
 ["8", "月次報告の形式と提出日", "", "", ""],
 ["9", "アウトカムの重要度(1〜9)を決める時期と方法(委員が決める)", "", "", ""]], { size: 15 }));

// ===================================================================== EtD案の説明
const E = head("EtD(推奨作成の記録)案の説明", "SR委員長との打ち合わせ用(2026年10月26日)　／　様式案のExcel: CIPN_EtD_2028様式案.xlsx");
E.push(H1("1. 位置づけ"));
E.push(P("EtDは、SR作業の結果(様式4-5、SR-8、SoF)を、推奨作成会議の判断につなぐ記録である。2023年版の各CQは、推奨文、推奨の強さ・エビデンスの確実性・合意率、解説、投票結果の順に書かれている。2023年版の推奨決定の方針は、「アウトカム全体にわたる総括的なエビデンスの確実性」「望ましい効果と望ましくない効果のバランス」「患者・市民の価値観と希望」を考慮し、「資源の利用(コスト)」は特に高額が予想される場合にだけ検討する、である。この様式案は、この方針と2023年版の体裁を残し、2028年版の記入欄を並べた。"));
E.push(H1("2. 様式案の構成(CQごとに1シート)"));
E.push(table([1500, 3200, 2500, 2400], [["区分", "内容", "入力元", "記入する人・時期"],
 ["A 推奨", "2023年版(推奨文、強さ、確実性、投票結果)と、2028年版案(推奨文案、強さ案、確実性)を並べる。2023年版の欄は入力済み", "2023年版(PDFから取り出し済み)。2028年版案は、SR担当の草案", "SR担当2名。2027年5月上旬"],
 ["B アウトカム別のエビデンス", "アウトカム、重要度(1〜9)、研究数、化学療法の層(白金製剤・タキサン系など)ごとの結果、効果の要約、確実性(A〜D)", "様式SR-8、SoF", "SR担当2名。2027年4月末"],
 ["C 考慮する項目", "C-1 総括的な確実性、C-2 益と害のバランス、C-3 患者・市民の価値観と希望、C-4 資源(高額な場合のみ)。2023年版の記載と、2028年版の判断・根拠を並べる", "C-1: SR-8。C-2〜C-4: SR担当の案と会議の議論", "SR担当2名(案)。会議で確認・修正"],
 ["D 変更点と理由", "2023年版からの変更点と理由。新規文献のPMIDを書く", "SR担当", "SR担当2名。2027年5月上旬"],
 ["E 投票", "確定した強さ、投票の回、有資格者数を転記する。投票は決定記録シートで記録する", "決定記録シート", "記録者。会議の後"]], { size: 15 }));
E.push(H1("3. 判断の選択肢(案。承認が必要)"));
E.push(table([3200, 6400], [["項目", "選択肢"],
 ["C-1 総括的な確実性", "A(強)、B(中)、C(弱)、D(非常に弱い)。様式SR-8の結果をそのまま使う"],
 ["C-2 益と害のバランス", "望ましい効果が大きく上回る / 望ましい効果がやや上回る / 同等 / 望ましくない効果がやや上回る / 望ましくない効果が大きく上回る / 判断できない"],
 ["C-3 患者・市民の価値観と希望", "ばらつきはない / ばらつきがある / 判断できない。根拠欄に、判断の元(文献、外部評価委員の意見など)を書く"],
 ["C-4 資源の利用", "検討が必要(高額が予想される) / 検討は不要。検討が必要な場合は、根拠欄に費用を書く"]], { size: 15 }));
E.push(note("選択肢は、プルダウンで選ぶ。判断は委員が行う。AIは、2023年版の記載の取り出しと、SR-8の数値の転記の補助に限る。"));
E.push(H1("4. 記入例(2023年版の記載のみ。2028年版は空欄)"));
E.push(table([2600, 7000], [["項目", "内容"],
 ["CQ", "CQ1 薬物療法による予防: 牛車腎気丸"],
 ["推奨文(2023年版)", "CIPN症状(白金製剤由来に限る)の予防として、牛車腎気丸を投与しないことを提案する"],
 ["推奨の強さ・確実性(2023年版)", "4(弱)、B(中)。合意率 100%(13/13)"],
 ["投票結果(2023年版)", "13名(棄権: 利益相反0名・SR0名)。4「投与しないことを提案する」13票(13/13)"],
 ["解説の要点(2023年版の原文から)", "RCT 5件。大規模RCT(Oki)で有効性を示せず、中間解析で介入群のCIPN発症が有意に多かったため試験中止。メタ解析でも、Grade 2以上の発現率に有意差なし。以上より、予防効果が期待できず、CIPNが増悪する可能性があるため、投与しないことを提案する"],
 ["2028年版案", "(SR担当が、新しい論文の評価とSR-8の後に記入する)"]], { size: 15 }));
E.push(H1("5. 運用"));
["様式案のExcelは、CQごとにシートがある。SR担当の2名が、作業ブックの「EtD(2023年版)」シートと同じ内容を見ながら、2028年版の欄に記入する。",
 "記入の時期は、SR-8の完了(2027年4月末)から、草案の提出(2027年5月上旬)まで。提出は、会議の3週間前。",
 "会議では、決定記録シートの「2023年版の記載」の欄と、このEtDを見ながら、投票する。投票者は、統括委員と作成グループ委員で、有資格者数は、CQごとのCOI除外で変わる。",
 "会議の後、確定した強さ・回・有資格者数を、EtDのEに転記する。Minds書類の一式(推奨作成の記録.xlsx)にも、同じ内容が出力される。"].forEach(t => E.push(B(t)));
E.push(H1("6. 打ち合わせで決めたい点"));
["様式案(A〜E)の構成でよいか。", "判断の選択肢(C-2、C-3、C-4)の案でよいか。", "C-3(患者・市民の価値観と希望)の根拠を、何で記録するか。推奨作成の投票者に患者代表は含めない。外部評価委員(浜野純、桜井なおみ)の意見、患者の価値観を調べた文献などが候補である。", "Bのアウトカム別の表は、SoFの出力から転記するか、SR-8を直接参照するか。", "FRQのEtDは、研究課題の記載を中心にし、C-2〜C-4を省くか。"].forEach(t => E.push(B(t)));

(async () => {
  const save = async (name, d) => { fs.writeFileSync(__dirname + "/out/" + name, await Packer.toBuffer(d)); console.log(name); };
  await save("SR委員長との打ち合わせ_アジェンダ.docx", doc([G], "SR委員長との打ち合わせ アジェンダ"));
  await save("EtD案の説明.docx", doc([E], "EtD案の説明"));
})();
