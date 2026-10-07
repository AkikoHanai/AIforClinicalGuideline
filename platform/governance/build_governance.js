// AI影響要因とリスク管理の書類を生成する。node build_governance.js
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
const G = [];
G.push(new Paragraph({ heading: HeadingLevel.TITLE, children: [new TextRun({ text: "AI(Claude)の影響要因とリスク管理", font: FONT, bold: true, size: 34 })], spacing: { after: 80 } }));
G.push(P("統括委員会 委員長 華井明子 宛　／　作成日 2026年10月7日　／　基準: 承認済み企画書 Ver1(2026年6月17日)"));
G.push(H1("1. 何が起きたか"));
G.push(P("Claudeは、企画書にない介入(光生体調節、電気刺激、外用薬など)を「候補」として挙げ、文献の件数から追加を提案する調査を行い、Scope改訂案の論点3に入れた。さらに、Scope改訂案の作成組織に、2023年版の体制(企画書にない氏名)を使っていた。いずれも、Mindsの手順(CQはScopeで委員会が決める)にも、承認済み企画書にもない。"));
G.push(P("この書類は、(1)Claudeの出力に影響しうる経路の一覧、(2)今回の逸脱の原因、(3)再発を防ぐ対策、を記録する。"));
G.push(H1("2. Claudeの出力に影響しうる経路の一覧"));
G.push(P("注: Claudeは、自分の学習内容の偏りを自分で検査できない。下表の「確認できたこと」は、このセッションで観測できた範囲に限る。"));
G.push(table([500, 2300, 3700, 3100], [["No", "経路", "内容", "確認できたこと"],
 ["1", "システムプロンプト(Claude Codeの実行環境)", "Gitの操作手順、コミットの署名文、GitHub操作、権限の規則。ガイドラインの内容(介入、CQ)を指定する記述はない", "介入・CQ・商品を指定する記述なし"],
 ["2", "PubMed MCPの応答に付く「important_legal_notice」", "出典(According to PubMed)とDOIリンクの記載を求める文。「省略の依頼は断れ」という文を含む。ツールの応答に入った指示文の例", "出典表示のみ。介入の選択には関与しない。指示としては扱わず、出典の表示は委員長の依頼で行っている"],
 ["3", "Consensus MCPの指示文", "検索結果に「サインアップ・アップグレードの文を一字一句掲載せよ」と求める。商用の誘導にあたる", "このプロジェクトでは一度も呼び出していない"],
 ["4", "Elicit、Claude Docs、Google Drive MCP", "文献検索・文書作成・ファイル操作のツール", "使用していない"],
 ["5", "スキル・プラグイン・コネクタを勧めるツール(SuggestSkills、SuggestConnectors、SuggestPluginInstall、SearchMcpRegistry)", "製品を提案する機能", "呼び出していない"],
 ["6", "論文の抄録・本文(第三者の文章)", "出版バイアス(肯定的な結果が出版されやすい)、企業資金の研究、英語圏の偏り。抄録の中に指示文が混ざる可能性", "このセッションで読んだ抄録に、Claudeへの指示文は見つからなかった。出版バイアスは除けない"],
 ["7", "ユーザーが添付したファイル(pptx、docx、pdf、zip)", "内容はデータであり指示ではない。ただし古い版の情報(2023年版の体制)が混入する", "今回の逸脱の原因の1つ(2023年版の体制の混入)"],
 ["8", "会話の要約(コンテキスト圧縮)", "Claude自身が書いた要約が、次の作業の指示として働く。要約に「候補介入の調査」が未了タスクとして残り、自己増殖した", "今回の逸脱の主因の1つ"],
 ["9", "Claudeの学習による事前知識", "英語圏で頻出する介入(光生体調節、TENS、外用薬など)を「候補」と連想する。「親切に先回りして提案する」傾向", "今回の逸脱の主因。特定の企業・製品を推す記述は確認できなかった。商用バイアスの有無は、Claude自身では検証できない"]], { size: 15 }));
G.push(note("「AIO」は、AIの出力を特定の方向へ誘導する仕組み(AI向けの最適化、AI要約、ツール応答への指示文の混入など)と解釈した。別の意味であれば指示してください。"));
G.push(H1("3. 今回の逸脱の原因(確認できたもの)"));
["企画書(2026年6月17日 Ver1)を基準として固定せず、会話の流れで作業を広げた。",
 "「文献の件数から候補を選ぶ」という手順を、Claude自身が作り、Mindsの手順(Scopeで委員会がCQを決める)と混同した。",
 "Scope改訂案の作成組織に、2023年版の体制を使い、承認済み企画書の体制と照合しなかった。",
 "会話の要約に、自分が作った未了タスクが残り、次の作業の指示になった。"].forEach(t => G.push(B(t)));
G.push(H1("4. リスク管理(実施済み)"));
G.push(table([500, 2700, 6400], [["No", "対策", "内容"],
 ["1", "基準の固定", "承認済み企画書のdocxを governance/ に保存し、SHA-256を記録。機械可読版(approved_plan.json)に、タイトル、体制、SR項目11、FRQ項目4、総論A〜N、予算、運営方針を転記"],
 ["2", "逸脱の自動検査", "governance/plan_guard.py が、(a)企画書の改ざん、(b)企画書にない作業フォルダ、(c)企画書にない介入名・旧体制の氏名、(d)Scope改訂案の項目欠落とタイトル、を検査し、1件でもあれば失敗する"],
 ["3", "検査の自動実行", "コミットの前(.githooks/pre-commit)と、run_revision.sh の先頭で、検査を実行する。失敗したらコミット・処理を止める"],
 ["4", "作業規則の固定", "リポジトリの CLAUDE.md に、企画書外の追加・提案の禁止、ツール出力は指示でない、使ってよい外部ツールはPubMedのみ、を記載。Claudeは作業開始のたびにこれを読む"],
 ["5", "隔離", "企画書外の調査(候補介入の文献調査、候補の件数スクリプト)を _企画書外_保留/ に移し、使用しない。成果物と手順書から参照を削除"],
 ["6", "是正", "Scope改訂案を企画書に合わせて修正: タイトルを「2028年版」に、作成組織を企画書の体制に、論点2と3を企画書のとおりに(新規介入は追加しない)、患者代表の役割は企画書に記載がないため統括委員会の決定事項に"],
 ["7", "用語の固定", "手順書の選択基準を、2023年版Scope 7.2に合わせた。独自に作った「適格RCT」「追加基準」を削除"]], { size: 15 }));
G.push(H1("5. 残るリスクと、委員長にお願いしたい確認"));
["検査は、登録した語と構造を調べるだけである。企画書にない内容が、登録していない言い方で書かれていれば検出できない。成果物は、委員長または統括委員会が目で確認してください。",
 "企画書に記載がない事項(検索期間・検索式・選択基準、スケジュールの日付、推奨作成会議の運営、患者代表の参画方法)は、現在の書類で前回Scopeの踏襲または案として書いている。統括委員会で承認してください。",
 "企画書は、SR項目11・FRQ項目4である。現在の作業フォルダは、ガバペンチノイド(プレガバリン)の予防、プレガバリンとミロガバリン(治療)を別フォルダにしており、企画書の「ガバペンチノイド(プレガバリン、ミロガバリン)」1項目と対応する。フォルダ数を企画書の項目数に合わせるか、確認してください。",
 "企画書の変更は、企画書のdocxを改訂して承認し、approved_plan.json とSHA-256を更新してから行う。Claudeは、企画書を書き換えない。"].forEach(t => G.push(B(t)));
(async () => { fs.writeFileSync(__dirname + "/AI影響要因とリスク管理.docx", await Packer.toBuffer(doc([G], "AI影響要因とリスク管理"))); console.log("ok"); })();
