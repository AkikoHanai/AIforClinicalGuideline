/**
 * 総論(総説 A〜N)執筆システム — Google Apps Script(管理用スプレッドシートに結合)
 *
 * 機能: 前回版(2023年版)の閲覧 / 2028年版原稿(Google ドキュメント)の作成と共有 / 要約の作成 /
 *       サマリー図表の自動提案と挿入(表の骨組み、グラフ画像) / 共有保存(Google ドライブ、版は Docs の版履歴) / 作成経過の記録
 * 使い方: README.md。メニュー「総論」→「作業パネルを開く」。
 * 規則: 判断と文章の責任は執筆者。AI(Claude)は提案と下書きに限る。企画書にない項目・介入を提案に含めない。
 */
const CFG = {
  rootName: "JASCC_GL_総論",          // マイドライブ直下に作る作業フォルダ
  src2023: "2023年版原文(docx)",     // ここに platform/soron/out の docx を置く
  model: "anthropic.claude-sonnet-4-5",
  region: "ap-northeast-1",
  tabs: { list: "担当表", ideas: "図表案", log: "作成経過", rules: "規則" },
};
// 企画書(Ver1 2026-06-17)の総論と担当。ここが基準。変更は統括委員会の承認が必要
const SORON = [
  ["A", "CIPNの頻度", "内藤"], ["B", "症候学的分類", "松岡宏"], ["C", "病理組織学的分類と症状", "武井"], ["D", "CIPNと神経障害性疼痛の関係", "中川貴之"],
  ["E", "リスク因子", "宇和川"], ["F", "鑑別診断に用いられる検査項目", "田辺"], ["G", "各薬剤によるCIPNの症状", "神林・縄田・坂下"], ["H", "CIPNの評価", "華井"],
  ["I_1", "中枢神経障害", "平川"], ["I_2", "感覚器障害", "古川"], ["J_1", "被疑薬の減量・中止", "吉田"], ["J_2", "デュロキセチン", "中島"], ["J_3", "誘発性急性神経障害", "菊池"],
  ["J_4", "看護", "荒尾"], ["J_5", "理学的手法", "中川夏樹"], ["K", "漢方・鍼灸治療", "元雄"], ["L", "手引き2023年版の効果検証", "山本"], ["M", "普及と活用促進", "華井"], ["N", "小児患者のCIPN対策", "GL委員会に依頼"],
];
const RULES = [
  "企画書(Ver1 2026-06-17)にない項目・介入・担当を、提案に含めない。",
  "引用文献は PMID を付ける。数値は出典の論文の記載のまま。推測の数値を書かない。",
  "総論には推奨の強さを書かない。CQ の推奨・確実性は推奨作成会議の決定に従う。",
  "曖昧な語(厳密、目安、適宜、十分、質の高い など)を使わない。基準は数または条件で書く。",
  "図表の元の論文の PMID と、転載許諾の要否を記録する。",
];

// ---------- メニュー ----------
function onOpen() {
  SpreadsheetApp.getUi().createMenu("総論").addItem("作業パネルを開く", "openPanel").addSeparator()
    .addItem("初期設定(フォルダ・原稿の作成)", "setup").addItem("2023年版 docx を取り込む", "import2023").addToUi();
}
function openPanel() {
  const html = HtmlService.createHtmlOutputFromFile("Sidebar").setTitle("総論の執筆").setWidth(420);
  SpreadsheetApp.getUi().showSidebar(html);
}

// ---------- 初期設定 ----------
function setup() {
  const ss = SpreadsheetApp.getActive();
  const root = folderByName(DriveApp.getRootFolder(), CFG.rootName);
  folderByName(root, CFG.src2023);
  const list = sheet(ss, CFG.tabs.list, ["項目", "題名", "担当", "メールアドレス", "状態", "2028年版原稿", "2023年版原文", "期限", "備考"]);
  if (list.getLastRow() < 2) list.getRange(2, 1, SORON.length, 3).setValues(SORON).offset(0, 4, SORON.length, 1).setValue("原稿未作成");
  sheet(ss, CFG.tabs.ideas, ["項目", "種類(表/図)", "題名", "内容・列", "データの出典(PMID)", "転載許諾", "採否(執筆者)", "作成日時", "作成"]);
  sheet(ss, CFG.tabs.log, ["日時", "操作者", "操作", "対象", "内容"]);
  const r = sheet(ss, CFG.tabs.rules, ["規則"]);
  if (r.getLastRow() < 2) r.getRange(2, 1, RULES.length, 1).setValues(RULES.map((x) => [x]));
  // 2028年版原稿(各総論に1つ)。既にあれば作らない
  const drafts = folderByName(root, "2028年版原稿");
  const rows = list.getRange(2, 1, list.getLastRow() - 1, 9).getValues();
  rows.forEach((row, i) => {
    if (row[5]) return;
    const sub = folderByName(drafts, `総論${row[0].replace("_", "-")}`);
    const doc = DocumentApp.create(`総論${row[0].replace("_", "-")} ${row[1]} 2028年版 原稿`);
    const b = doc.getBody();
    b.appendParagraph(`総論${row[0].replace("_", "-")}. ${row[1]}`).setHeading(DocumentApp.ParagraphHeading.HEADING1);
    b.appendParagraph(`担当: ${row[2]}　／　がん薬物療法に伴う末梢神経障害診療ガイドライン2028年版`);
    ["1. 2023年版からの変更点(箇条書き。根拠の PMID を付ける)", "2. 本文", "3. 図表(作業パネルの提案から挿入)", "4. 文献(PMID 付き)"].forEach((h) => { b.appendParagraph(h).setHeading(DocumentApp.ParagraphHeading.HEADING2); b.appendParagraph(""); });
    DriveApp.getFileById(doc.getId()).moveTo(sub);
    list.getRange(i + 2, 6).setValue(doc.getUrl()); list.getRange(i + 2, 5).setValue("原稿未提出");
    if (row[3]) DriveApp.getFileById(doc.getId()).addEditor(row[3]);
  });
  log("初期設定", "全体", `フォルダ ${root.getName()}、原稿 ${rows.length}件`);
  SpreadsheetApp.getUi().alert(`準備できました。docx を「${CFG.rootName}/${CFG.src2023}」に置き、「2023年版 docx を取り込む」を実行してください。`);
}

/** platform/soron/out の docx(総論A_A.CIPNの頻度.docx など)を Google ドキュメントに変換し、担当表に記録する */
function import2023() {
  const ss = SpreadsheetApp.getActive();
  const root = folderByName(DriveApp.getRootFolder(), CFG.rootName);
  const src = folderByName(root, CFG.src2023); const dst = folderByName(root, "2023年版原文");
  const list = ss.getSheetByName(CFG.tabs.list); const rows = list.getRange(2, 1, list.getLastRow() - 1, 7).getValues();
  const files = src.getFilesByType(MimeType.MICROSOFT_WORD); let n = 0;
  while (files.hasNext()) {
    const f = files.next(); const m = f.getName().match(/^総論([A-M](?:_\d)?)_/);
    if (!m) continue;
    const key = m[1]; const i = rows.findIndex((r) => r[0] === key);
    if (i < 0 || rows[i][6]) continue;
    const g = Drive.Files.create({ name: `総論${key.replace("_", "-")} 2023年版 原文`, mimeType: MimeType.GOOGLE_DOCS, parents: [dst.getId()] }, f.getBlob());
    list.getRange(i + 2, 7).setValue(`https://docs.google.com/document/d/${g.id}/edit`); n++;
  }
  log("2023年版の取り込み", "総論", `${n}件`);
  SpreadsheetApp.getUi().alert(`${n}件を取り込みました。`);
}

// ---------- パネルから呼ぶ関数 ----------
function getState() {
  const ss = SpreadsheetApp.getActive(); const list = ss.getSheetByName(CFG.tabs.list);
  if (!list) return { error: "初期設定(メニュー「総論」)を先に実行してください" };
  const me = Session.getActiveUser().getEmail();
  const rows = list.getRange(2, 1, list.getLastRow() - 1, 9).getValues().map((r) => ({ key: r[0], title: r[1], author: r[2], email: r[3], status: r[4], doc2028: r[5], doc2023: r[6], due: r[7], note: r[8] }));
  const admin = isAdmin(me);
  return { me, admin, items: rows.filter((r) => admin || (r.email && r.email.toLowerCase() === me.toLowerCase())), rules: ss.getSheetByName(CFG.tabs.rules).getRange(2, 1, RULES.length, 1).getValues().map((r) => r[0]) };
}
function isAdmin(email) {
  const owner = DriveApp.getFileById(SpreadsheetApp.getActive().getId()).getOwner().getEmail();
  return email.toLowerCase() === owner.toLowerCase();
}
/** 2023年版原文の本文を段落 ID 付きで返す(閲覧用。編集しない) */
function get2023(key) {
  const row = findRow(key); if (!row.doc2023) return { paragraphs: [], note: "2023年版の原文は未取り込み(新設の節、または取り込み待ち)" };
  const doc = DocumentApp.openByUrl(row.doc2023); const ps = doc.getBody().getParagraphs().map((p) => p.getText().trim()).filter((t) => t);
  const start = ps.findIndex((t) => /^3\.\s*2023年版\s*原文/.test(t)); const body = start >= 0 ? ps.slice(start + 1) : ps;
  const end = body.findIndex((t) => /^(4\.|文献$)/.test(t)); const sel = end >= 0 ? body.slice(0, end) : body;
  return { url: row.doc2023, paragraphs: sel.map((t, i) => ({ id: `GL2023-総論${key.replace("_", "-")}-p${String(i + 1).padStart(3, "0")}`, text: t })) };
}
/** 2028年版原稿の本文(確認用) */
function getDraft(key) {
  const row = findRow(key); const doc = DocumentApp.openByUrl(row.doc2028);
  return { url: row.doc2028, text: doc.getBody().getText(), status: row.status };
}
function setStatus(key, status, note) {
  const list = SpreadsheetApp.getActive().getSheetByName(CFG.tabs.list); const i = findIndex(key);
  if (!["原稿未提出", "執筆中", "査読中", "修正中", "完了"].includes(status)) throw new Error("状態の値が不正です");
  if (status === "完了" && !isAdmin(Session.getActiveUser().getEmail())) throw new Error("完了は統括委員会が決めます");
  list.getRange(i + 2, 5).setValue(status); if (note !== undefined) list.getRange(i + 2, 9).setValue(note);
  log("状態の変更", `総論${key}`, status); return getState();
}

/** 要約図表の自動提案: 2023年版の本文と現在の原稿から、表・図の案を作り、図表案タブと原稿の「3. 図表」に書く */
function proposeFigures(key) {
  const g = get2023(key); const d = getDraft(key); const row = findRow(key);
  const rules = SpreadsheetApp.getActive().getSheetByName(CFG.tabs.rules).getRange(2, 1, RULES.length, 1).getValues().map((r) => r[0]).join("\n");
  const prompt = `総論${key.replace("_", "-")} ${row.title}(担当: ${row.author})のサマリー図表の案を作る。
規則:
${rules}
- 2023年版の本文と現在の原稿に書かれている内容だけを図表にする。本文にない数値や介入を加えない。
- 表は列の定義まで、図は種類(棒・折れ線・フロー図・模式図)と軸・要素まで具体的に書く。数値を使う図表は、元の段落 ID と PMID を書く。
- 3〜6 件。JSON の配列だけを返す: [{"kind":"表|図","title":"題名","content":"内容・列(表)または種類・軸・要素(図)","columns":["列1","列2"],"source":"段落IDとPMID","permission":"転載許諾の要否"}]

--- 2023年版の本文 ---
${g.paragraphs.map((p) => `[${p.id}] ${p.text}`).join("\n").slice(0, 60000)}
--- 現在の原稿 ---
${d.text.slice(0, 30000)}`;
  const out = callClaude("あなたは診療ガイドラインの総論の執筆補助です。渡された本文だけを根拠に、要約図表の案を JSON で返します。判断は執筆者が行います。", prompt);
  const m = out.match(/\[[\s\S]*\]/); const items = JSON.parse(m ? m[0] : out);
  const ideas = SpreadsheetApp.getActive().getSheetByName(CFG.tabs.ideas); const now = new Date();
  items.forEach((it) => ideas.appendRow([key, it.kind, it.title, (it.columns || []).join(" / ") || it.content, it.source || "", it.permission || "", "", now, "Claude(案)"]));
  const doc = DocumentApp.openByUrl(row.doc2028); const b = doc.getBody();
  const h = b.getParagraphs().find((p) => /^3\.\s*図表/.test(p.getText()));
  const idx = h ? b.getChildIndex(h) + 1 : b.getNumChildren();
  const t = b.insertTable(idx, [["図表案(Claude。採否は執筆者)", "種類", "内容", "出典"]].concat(items.map((it) => [it.title, it.kind, it.content, it.source || ""])));
  t.getRow(0).editAsText().setBold(true);
  log("図表案の提案", `総論${key}`, `${items.length}件`);
  return items;
}
/** 表の骨組みを原稿に挿入する(図表案の列から) */
function insertTable(key, title, columns) {
  const row = findRow(key); const doc = DocumentApp.openByUrl(row.doc2028); const b = doc.getBody();
  const h = b.getParagraphs().find((p) => /^3\.\s*図表/.test(p.getText())); const idx = h ? b.getChildIndex(h) + 1 : b.getNumChildren();
  b.insertParagraph(idx, `表. ${title}`).setBold(true);
  const t = b.insertTable(idx + 1, [columns, columns.map(() => "")]); t.getRow(0).editAsText().setBold(true);
  log("表の挿入", `総論${key}`, title); return true;
}
/** グラフ画像を作って原稿に挿入する。data: [[ラベル, 値], ...](先頭行は見出し)。type: 棒|折れ線 */
function insertChart(key, title, data, type) {
  const ss = SpreadsheetApp.getActive(); const name = `データ_${key}`;
  const sh = ss.getSheetByName(name) || ss.insertSheet(name); const r0 = sh.getLastRow() + 2;
  sh.getRange(r0, 1).setValue(title); sh.getRange(r0 + 1, 1, data.length, data[0].length).setValues(data);
  const range = sh.getRange(r0 + 1, 1, data.length, data[0].length);
  const ct = type === "折れ線" ? Charts.ChartType.LINE : Charts.ChartType.COLUMN;
  const chart = sh.newChart().setChartType(ct).addRange(range).setPosition(r0, data[0].length + 2, 0, 0).setOption("title", title).setOption("legend", { position: "bottom" }).build();
  sh.insertChart(chart);
  const blob = chart.getBlob().setName(`${title}.png`);
  const row = findRow(key); const doc = DocumentApp.openByUrl(row.doc2028); const b = doc.getBody();
  const h = b.getParagraphs().find((p) => /^3\.\s*図表/.test(p.getText())); const idx = h ? b.getChildIndex(h) + 1 : b.getNumChildren();
  b.insertParagraph(idx, `図. ${title}(データ: スプレッドシート「${name}」。出典の PMID を図の説明に書く)`).setBold(true);
  b.insertImage(idx + 1, blob).setWidth(480).setHeight(300);
  log("グラフの挿入", `総論${key}`, title); return true;
}
/** 学外の執筆者はスクリプトを使えないため、2023年版の本文(段落ID付き)を原稿の冒頭「0. 2023年版 原文(参照)」に差し込む。原稿だけで作業できるようにする */
function embed2023(key) {
  const g = get2023(key); const row = findRow(key); const doc = DocumentApp.openByUrl(row.doc2028); const b = doc.getBody();
  if (b.getParagraphs().some((p) => /^0\.\s*2023年版 原文/.test(p.getText()))) return "既に差し込み済みです";
  const h1 = b.getParagraphs().find((p) => /^1\.\s*2023年版からの変更点/.test(p.getText())); let idx = h1 ? b.getChildIndex(h1) : 2;
  b.insertParagraph(idx++, "0. 2023年版 原文(参照。編集しない。段落IDを変更箇所の指示と根拠に使う)").setHeading(DocumentApp.ParagraphHeading.HEADING2);
  g.paragraphs.forEach((p) => { const para = b.insertParagraph(idx++, `[${p.id}] ${p.text}`); para.setForegroundColor("#555555").setFontSize(9); });
  b.insertParagraph(idx++, "");
  log("2023年版の差し込み", `総論${key}`, `${g.paragraphs.length}段落`); return `${g.paragraphs.length}段落を差し込みました`;
}
/** 要約の下書きを原稿の「2. 本文」の冒頭に「要点(下書き)」として書く(執筆者が確認・修正する) */
function writeSummary(key) {
  const text = summarize(key); const row = findRow(key); const doc = DocumentApp.openByUrl(row.doc2028); const b = doc.getBody();
  const h = b.getParagraphs().find((p) => /^2\.\s*本文/.test(p.getText())); let idx = h ? b.getChildIndex(h) + 1 : b.getNumChildren();
  b.insertParagraph(idx++, "要点(Claude の下書き。執筆者が確認・修正する)").setBold(true);
  text.split(/\n/).filter((l) => l.trim()).forEach((l) => b.insertParagraph(idx++, l.trim()));
  return text;
}
/** 要約(箇条書き)の下書き。原稿の末尾ではなく、パネルに返す(執筆者が貼る) */
function summarize(key) {
  const d = getDraft(key); const row = findRow(key);
  const out = callClaude("あなたは診療ガイドラインの総論の執筆補助です。渡された原稿だけを根拠に要約します。原稿にない内容を加えません。",
    `総論${key.replace("_", "-")} ${row.title} の原稿を、臨床医向けの要点 3〜6 行(各行 60 字以内、根拠の PMID があれば付ける)に要約する。箇条書きの文字列だけを返す。\n\n${d.text.slice(0, 40000)}`);
  log("要約の下書き", `総論${key}`, `${out.length}文字`); return out;
}

// ---------- Claude(Amazon Bedrock、API キー) ----------
function callClaude(system, user) {
  const props = PropertiesService.getScriptProperties(); const key = props.getProperty("BEDROCK_API_KEY"); const model = props.getProperty("MODEL_ID") || CFG.model;
  if (!key) throw new Error("スクリプト プロパティ BEDROCK_API_KEY を設定してください(README)");
  const url = `https://bedrock-runtime.${CFG.region}.amazonaws.com/model/${encodeURIComponent(model)}/converse`;
  const res = UrlFetchApp.fetch(url, { method: "post", contentType: "application/json", headers: { Authorization: "Bearer " + key }, muteHttpExceptions: true,
    payload: JSON.stringify({ system: [{ text: system }], messages: [{ role: "user", content: [{ text: user }] }], inferenceConfig: { maxTokens: 4000, temperature: 0 } }) });
  if (res.getResponseCode() !== 200) throw new Error(`Bedrock ${res.getResponseCode()}: ${res.getContentText().slice(0, 200)}`);
  return JSON.parse(res.getContentText()).output.message.content[0].text;
}

// ---------- 補助 ----------
function folderByName(parent, name) { const it = parent.getFoldersByName(name); return it.hasNext() ? it.next() : parent.createFolder(name); }
function sheet(ss, name, header) { let s = ss.getSheetByName(name); if (!s) { s = ss.insertSheet(name); s.appendRow(header); s.setFrozenRows(1); } return s; }
function findIndex(key) { const list = SpreadsheetApp.getActive().getSheetByName(CFG.tabs.list); const keys = list.getRange(2, 1, list.getLastRow() - 1, 1).getValues().map((r) => r[0]); const i = keys.indexOf(key); if (i < 0) throw new Error("総論がありません: " + key); return i; }
function findRow(key) { const list = SpreadsheetApp.getActive().getSheetByName(CFG.tabs.list); const r = list.getRange(findIndex(key) + 2, 1, 1, 9).getValues()[0]; return { key: r[0], title: r[1], author: r[2], email: r[3], status: r[4], doc2028: r[5], doc2023: r[6], due: r[7], note: r[8] }; }
function log(action, target, detail) { SpreadsheetApp.getActive().getSheetByName(CFG.tabs.log).appendRow([new Date(), Session.getActiveUser().getEmail(), action, target, detail]); }
