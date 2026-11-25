// Scope(スコープ)を Minds診療ガイドライン作成マニュアル2020 ver.3.0 第3章の様式(SC-1 疾患トピックの基本的特徴、SC-2 診療アルゴリズム、SC-3 スコープ、SC-4 CQの設定)の項目順で、Word(.docx)に生成する
//   node build_scope_minds.js     出力: out/Scope_2028年版_Minds書式.docx
// 出典: 提案書v2(目的・疾患トピックの基本的特徴・重要臨床課題・範囲・出版時期)、承認済み企画書(CQ・FRQ・外部評価委員)、前回Scope(2021-07-02)、統括委員長の決定(approved_plan.json)、2023年版 総論(units.json。原文のまま引用)。
// 出典にない内容は書かない。出典にないMindsの項目は「記載なし」と書く。
const fs = require("fs");
const { Document, Packer, Paragraph, TextRun, HeadingLevel, Table, TableRow, TableCell, WidthType, AlignmentType, BorderStyle, ShadingType, LevelFormat, Footer, PageNumber } = require("docx");
const PLAN = JSON.parse(fs.readFileSync(__dirname + "/../governance/approved_plan.json", "utf8"));
const UNITS = Object.fromEntries(JSON.parse(fs.readFileSync(__dirname + "/../data/gl2023/units.json", "utf8")).map((u) => [u.key, u]));
const FONT = "Yu Gothic";
const T = (t, o = {}) => new TextRun({ text: t, font: FONT, size: 20, ...o });
const P = (t, o = {}) => new Paragraph({ children: Array.isArray(t) ? t : [T(t)], spacing: { after: 100 }, ...o });
const H1 = (t, brk = true) => new Paragraph({ heading: HeadingLevel.HEADING_1, children: [new TextRun({ text: t, font: FONT, bold: true, size: 26 })], spacing: { before: 300, after: 120 }, pageBreakBefore: brk });
const H2 = (t) => new Paragraph({ heading: HeadingLevel.HEADING_2, children: [new TextRun({ text: t, font: FONT, bold: true, size: 22 })], spacing: { before: 200, after: 80 } });
const B = (t) => new Paragraph({ numbering: { reference: "b", level: 0 }, children: Array.isArray(t) ? t : [T(t)], spacing: { after: 50 } });
const src = (t) => T(`(${t})`, { size: 16, color: "555555" });
const bord = { style: BorderStyle.SINGLE, size: 4, color: "000000" }, borders = { top: bord, bottom: bord, left: bord, right: bord };
function table(widths, rows, opts = {}) {
  return new Table({ columnWidths: widths, width: { size: widths.reduce((a, b) => a + b, 0), type: WidthType.DXA },
    rows: rows.map((r, i) => new TableRow({ tableHeader: i === 0 && !opts.noHeader, cantSplit: true, children: r.map((c, j) => new TableCell({
      width: { size: widths[j], type: WidthType.DXA }, borders, shading: (i === 0 && !opts.noHeader) || (opts.labelCol && j === 0) ? { type: ShadingType.CLEAR, fill: "EDEDED", color: "auto" } : undefined,
      margins: { top: 40, bottom: 40, left: 80, right: 80 },
      children: (Array.isArray(c) ? c : String(c ?? "").split("\n")).map((line) => new Paragraph({ children: typeof line === "string" ? [T(line, { size: opts.size || 18, bold: (i === 0 && !opts.noHeader) || (opts.labelCol && j === 0) })] : line })) })) })) });
}
// 2023年版 総論の原文の文(引用の番号 ^n)^ は除く)
const sentences = (key, idx) => UNITS[key].paras[idx].replace(/\^[^^]*\^/g, "").split(/(?<=。)/).map((s) => s.trim()).filter(Boolean);
const quote = (key, idx, which) => which.map((i) => sentences(key, idx)[i]).join("");
const TITLE = PLAN["タイトル"];
const ids = (list) => list.map((x) => x.id);
const kubun = (s) => (s || "FRQ").replace(/\(監修:.*\)/, "");
const items = PLAN["SR項目"].concat(PLAN["FRQ項目"]);
const byName = (id) => items.find((x) => x.id === id).名称;

const out = [];
out.push(new Paragraph({ heading: HeadingLevel.TITLE, children: [new TextRun({ text: "Scope(スコープ)", font: FONT, bold: true, size: 34 })], spacing: { after: 80 } }));
out.push(P(TITLE, { }));
out.push(P("日本がんサポーティブケア学会 編　／　Minds診療ガイドライン作成マニュアル2020 ver.3.0 第3章の様式(SC-1〜SC-4)の項目順"));
out.push(table([2200, 7300], [["版", "第1版"], ["作成日", "2026年11月25日"], ["作成者", "ガイドライン統括委員会 委員長 華井明子"], ["改訂の関係", "改訂版(前回: がん薬物療法に伴う末梢神経障害診療ガイドライン2023年版、2023年6月20日発刊)"]], { noHeader: true, labelCol: true }));

// ------------------------------------------------------------------ SC-1
out.push(H1("SC-1 疾患トピックの基本的特徴", false));
out.push(H2("臨床的特徴"));
out.push(P([T(PLAN_FEATURE()), src("提案書v2")]));
function PLAN_FEATURE() { return "がん薬物療法に伴う末梢神経障害(CIPN)は、がん薬物療法に関連して高頻度にみられる有害事象である。主な症状には、しびれ、疼痛、感覚低下、異常感覚、運動障害などがあり、患者の生活の質(quality of life:QOL)の低下、日常生活動作(activities of daily living:ADL)の制限、治療継続への影響、および全人的苦痛の増大につながる重要な病態である。"; }
out.push(P([T(quote("B", 0, [0, 1])), src("2023年版 総論B 原文")]));
out.push(H2("疫学的特徴"));
out.push(P([T(quote("A", 0, [0, 2])), src("2023年版 総論A 原文")]));
out.push(P([T(quote("E", 0, [0])), src("2023年版 総論E 原文")]));
out.push(H2("診療の全体的な流れ"));
out.push(P([T(quote("H", 1, [0])), src("2023年版 総論H 原文")]));
out.push(P([T(quote("J_1", 5, [0])), src("2023年版 総論J-1 原文")]));
out.push(P("本ガイドラインは、CIPNの予防(薬物療法・非薬物療法)と治療(薬物療法・非薬物療法)をCQとして扱う(SC-2、SC-4)。"));

// ------------------------------------------------------------------ SC-2
out.push(H1("SC-2 診療アルゴリズム"));
out.push(P("診療の流れと選択肢を示す。推奨を作成していない選択肢は、対応するCQ・FRQの番号で示す。"));
const box = (lines) => lines;
const cell = (ids_) => ids_.map((i) => `${i} ${byName(i)}`).join("\n");
out.push(table([9500], [["がん薬物療法を受ける患者(CIPNを呈しうる、あるいは呈している)"]], { noHeader: true, labelCol: true }));
out.push(P("↓", { alignment: AlignmentType.CENTER }));
out.push(table([4750, 4750], [["予防", "治療(CIPNを呈している患者)"],
  ["薬物療法による予防\n" + cell(["P1", "P2", "P3"]) + "\n\n非薬物療法による予防\n" + cell(["N1", "N2", "N3"]),
   "CIPNの評価(総論H)\n↓\n被疑薬の延期・減量・中止(総論J-1)\n↓\n薬物療法による治療\n" + cell(["T1", "T2", "T3"]) + "\n\nFRQ(薬物療法による治療)\n" + cell(["F1", "F2", "F3", "F4"]) + "\n\n非薬物療法による治療\n" + cell(["N4", "N5"])]], { size: 18 }));
out.push(P(" "));
out.push(P("CQ・FRQの番号は、承認済み企画書のSR項目・FRQ項目に対応する。"));

// ------------------------------------------------------------------ SC-3
out.push(H1("SC-3 スコープ"));
out.push(H2("診療ガイドラインがカバーする内容に関する事項"));
const cqNames = PLAN["SR項目"].map((x) => `${x.id} ${x.名称}`).join("、");
const frqNames = PLAN["FRQ項目"].map((x) => `${x.id} ${x.名称}`).join("、");
out.push(table([2400, 7100], [["項目", "内容"],
  ["1. タイトル", TITLE + "(日本がんサポーティブケア学会 編)"],
  ["2. 目的", "がん薬物療法に伴う末梢神経障害(chemotherapy-induced peripheral neuropathy:CIPN)を有する、または発症する可能性のある成人がん患者を対象とし、医師、看護師、薬剤師、作業療法士、理学療法士などを含む多職種医療チームが診療に活用できる指針を示すことを目的とする。(提案書v2)\n改善するアウトカム: 予防としてはCIPNの発症頻度や症状(しびれ、疼痛)の軽減、治療としては症状(しびれ、疼痛)の軽減。(前回Scope)"],
  ["3. トピック", "がん薬物療法に伴う末梢神経障害(CIPN)の診療(予防・治療)"],
  ["4. 視点", "記載なし(前回Scope、提案書v2、企画書に記載がない。統括委員会が決める)"],
  ["5. 想定される利用者、利用施設", "医師、看護師、薬剤師、理学療法士、作業療法士など、がん薬物療法に関わる医療者。がん薬物療法に関わる医療施設。"],
  ["6. 既存ガイドラインとの関係", "米国臨床腫瘍学会(ASCO)2014年版、ASCO 2020年update版、欧州臨床腫瘍学会(ESMO)2020年版のガイドライン、およびがん薬物療法に伴う末梢神経障害マネジメントの手引き2017年版が存在する。本ガイドラインは、2023年版の改訂であり、今回新規の海外ガイドラインはない。(前回Scope、企画書)"],
  ["7. 診療ガイドラインがカバーする範囲", "カバーする範囲: がん薬物療法に伴う末梢神経障害を呈しうる、あるいは呈している成人(18歳以上)のがん患者。\nカバーしない範囲: 急性神経障害、神経疾患の合併例。糖尿病性神経障害や脊髄・脳病変など他の原因による神経障害、診断・治療上の境界領域は、必要に応じて総論で解説する。小児患者のCIPN対策は、総論Nとしてガイドライン委員会に依頼する。(前回Scope、提案書v2、企画書)"],
  ["8. 重要臨床課題", "1. CIPNの予防(薬物療法および非薬物療法)\n2. CIPNの治療(薬物療法および非薬物療法)\n日本国内で使用されているものの海外ガイドラインでは扱いが少ない薬剤(ビタミンB12製剤、漢方薬、NSAIDs、オピオイドなど)と、冷却、圧迫、運動療法、鍼灸などの非薬物療法について、有効性と安全性を検討し、国内の診療実態に即した推奨を示す。前回エビデンスが不足していた項目は、FRQ(Future Research Question)として今回新設した。(提案書v2、前回Scope、企画書)"],
  ["9. CQリスト", "SR項目(CQ)11: " + cqNames + "\nFRQ項目4: " + frqNames + "\n詳細はSC-4。企画書にない項目は追加しない。"]], { labelCol: true }));

out.push(H2("作成方法に関する事項: システマティックレビュー"));
out.push(table([2400, 7100], [["項目", "内容"],
  ["実施スケジュール", "検索期間は2026年10月1日まで。出版は2028年6月頃(提案書v2)。作業日程は、統括委員会が承認した日程に従う。"],
  ["エビデンスの検索", "文献データベース: PubMed(英語)。Cochrane Library、医中誌Webは検索しない(理由は方法に記載する)。\n検索期間: 前回の検索の終了日の翌日から2026年10月1日まで。\n検索式: 前回(2023年版)の式を用いる。担当者は、自分の担当部分で該当しない介入語を省いて検索してよい。\n既存のガイドライン: ASCO 2014年版・2020年update版、ESMO 2020年版。\n文献のソース: ① PubMedを用いた系統的文献検索、② 既存のガイドラインに引用されている文献、③ がん薬物療法に伴う末梢神経障害マネジメントの手引き2017年版に引用されている文献、④ 作成委員の任意のサーベイランスにより抽出した文献。\n検索の過程は、再現できるように記録し、ガイドライン内に記載する。\n効果のサーベイランスの範囲は、CIPNに限定する。(統括委員長の決定、前回Scope)"],
  ["文献の選択基準、除外基準", "適格基準: 18歳以上を対象とする。英語(総説および原著)で記載されている。対象患者はがん患者である。国内で施行可能な方法・薬物である(保険適応の有無は問わない)。原著は、メタアナリシス、無作為化比較試験、または分析疫学的研究(コホート研究、症例対照研究、横断研究)、記述研究(症例報告、ケースシリーズ)のいずれかである。\n記述研究と英語総説の内容は、解説で紹介してよいが、推奨の根拠にはしない。\n原著は英語に限定する(予備調査で、評価に値する日本語論文がなかったため)。\n選択の手順: 一次スクリーニング(題名・抄録)と二次スクリーニング(全文)を、それぞれ2名が独立に行う。2名の判定が一致しないときは、2名の協議に第三者の意見(SR委員長への報告)を加えて決める。(前回Scope、統括委員長の決定)"],
  ["エビデンスの評価と統合の方法", "個別研究の評価: Minds SR-5(旧称 様式4-5)。バイアスリスクと非直接性を、0/-1/-2で、2名が独立に評価する。盲検化は、二重盲検=0、単盲検=-1、非盲検=-1、記載なし=-1とし、-2は使わない。\n研究特性: 癌腫、薬剤名、化学療法の分類を記録し、エビデンス総体(SR-8)とSoFは、分類で層別する。\nエビデンス総体: Minds SR-8(絶対効果指標の結果を記入する場合)。確実性は、A(強)〜D(非常に弱い)。統合値と絶対効果は、委員が記入する。\nアウトカムは、全CQ・FRQで「CIPN」である。(統括委員長の決定)"]], { labelCol: true }));

out.push(H2("作成方法に関する事項: 推奨作成から公開まで"));
out.push(table([2400, 7100], [["項目", "内容"],
  ["推奨作成", "推奨の決定は、エビデンスの評価と統合で作成した資料を参考に、「アウトカム全体にわたる総括的なエビデンスの確実性」「望ましい効果と望ましくない効果のバランス」「患者・市民の価値観と希望」を考慮して行う。資源の利用(コスト)は、特に高額が予想される場合にのみ検討する。\n投票: 会議は開かず、ポータルの電子投票で行う(1人1票、変更不可、無記名、終了まで集計を表示しない)。投票者は、統括委員会と診療ガイドライン作成グループであり、患者代表は含めない。COIなどで除外された委員、直接評価された論文の筆頭著者、そのCQのSRを行った委員は、そのCQに投票しない。\n成立: 資格のある委員の75%以上が参加し、参加者の80%以上が同じ選択肢を選んだとき。意見の一致をみないときは、投票を繰り返し、3回で一致をみないときは「推奨なし」とする。\n推奨の強さ: 1 強い推奨(行う)、2 弱い推奨(行う)、3 なし(明確な推奨はできない)、4 弱い推奨(行わない)、5 強い推奨(行わない)。(前回Scope、統括委員長の決定)"],
  ["最終調整", "追加すべき事項(活用方法、評価方法など)を記載し、草案を作成する。草案に対して、外部評価とパブリックコメントを募集する。評価を参考にして、最終調整する。(前回Scope)"],
  ["外部評価", "外部評価委員(仮。" + "松岡歩、横田知哉、浜野純、桜井なおみ" + ")が、Scopeの完成前と、ガイドラインの完成前に、個別にコメントを提出する。診療ガイドライン作成グループは、各コメントについて、内容を変更する必要性を討議して、対応を決定する。パブリックコメントも同様とする。(企画書、前回Scope)"],
  ["公開", "外部評価とパブリックコメントへの対応が終了したら、診療ガイドライン統括委員会が公開の最終決定をする。出版は2028年6月頃。書籍(予定出版社 金原出版)、学会ホームページ(出版1年後より)、Mindsホームページ。継続的な改訂体制は、有り。(前回Scope、提案書v2)"]], { labelCol: true }));

// ------------------------------------------------------------------ SC-4
out.push(H1("SC-4 クリニカルクエスチョン(CQ)の設定"));
out.push(H2("全CQ・FRQに共通する構成要素"));
out.push(table([2400, 7100], [["構成要素", "内容"],
  ["P(患者)", "疾患・病態: がん化学療法を受ける患者(CIPNを呈しうる、あるいは呈している)\n年齢: 18歳以上(成人)\n性別、地理的要件: 記載なし"],
  ["I(介入)", "CQごとに異なる(下表)"], ["C(対照)", "無治療"],
  ["O(アウトカム)", "内容: CIPN(症状の有無で評価する。予防・治療とも)\n益/害: 益\n重要度(1〜9): 記載なし(統括委員会が決める)\n採用: 採用"]], { labelCol: true }));
out.push(H2("CQ・FRQの一覧"));
const plain = (n) => n.replace(/\((予防|治療)\)$/, "").replace(/による治療$/, "");
const cqSentence = (x) => (x.id.startsWith("F") || x.区分?.includes("治療") ? `CIPNを呈している患者に対して、CIPNの治療として、${plain(x.名称)}は推奨されるか。` : `がん化学療法を受ける患者に対して、CIPNの予防として、${plain(x.名称)}は推奨されるか。`);
const rows = [["番号", "区分(重要臨床課題)", "I(介入)", "CQ文"]];
for (const x of items) rows.push([x.id, x.id.startsWith("F") ? "FRQ(薬物療法による治療)" : kubun(x.区分), x.名称, cqSentence(x)]);
out.push(table([800, 2300, 2700, 3700], rows, { size: 17 }));
out.push(P(" "));
out.push(P("FRQは、前回エビデンスが不足していた項目について、今回より新設した(企画書)。"));

const doc = new Document({ styles: { default: { document: { run: { font: FONT, size: 20 } } } },
  numbering: { config: [{ reference: "b", levels: [{ level: 0, format: LevelFormat.BULLET, text: "・", alignment: AlignmentType.LEFT, style: { paragraph: { indent: { left: 440, hanging: 280 } } } }] }] },
  sections: [{ properties: { page: { size: { width: 11906, height: 16838 }, margin: { top: 1134, bottom: 1134, left: 1134, right: 1134 } } },
    footers: { default: new Footer({ children: [new Paragraph({ alignment: AlignmentType.CENTER, children: [T("Scope 2028年版　", { size: 16 }), new TextRun({ children: [PageNumber.CURRENT], font: FONT, size: 16 })] })] }) }, children: out.flat() }] });
fs.mkdirSync(__dirname + "/out", { recursive: true });
Packer.toBuffer(doc).then((buf) => { fs.writeFileSync(__dirname + "/out/Scope_2028年版_Minds書式.docx", buf); console.log("out/Scope_2028年版_Minds書式.docx"); });
