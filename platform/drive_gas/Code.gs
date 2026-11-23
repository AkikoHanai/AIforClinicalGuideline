/**
 * 共有ドライブ「CIPNガイドライン作成」への受け口 — Google Apps Script の Web アプリ
 *
 * ポータル(AWS の Lambda)が、提出物・出力・手順書を、この Web アプリへ送る。統括委員長の Mac を介さない。
 * できること: フォルダを作る、ファイルを置く(同じ名前があれば、飛ばす、または内容を置き換える。置き換えはドライブの版の履歴に残る)、接続の確認。
 * できないこと: 削除、閲覧、移動、共有設定の変更(この Web アプリには、これらの操作がない)。
 * 守り: (1) 合言葉 TOKEN が一致しない要求は、全て断る。(2) 最上位のフォルダは 提出 / 依頼書 / マニュアル に限る。
 *       (3) フォルダ名・ファイル名に / や .. を含む要求は断る。(4) 転送先は ROOT_FOLDER_ID の下に限る。
 * 設定(スクリプトのプロパティ): TOKEN(合言葉)、ROOT_FOLDER_ID(共有ドライブの最上位のフォルダの ID)。手順は README.md。
 */
const TOP = ["提出", "依頼書", "マニュアル"];
const MAX_DEPTH = 5;

function doPost(e) {
  try {
    const req = JSON.parse(e.postData.contents);
    const props = PropertiesService.getScriptProperties();
    const token = props.getProperty("TOKEN") || "";
    if (!token || !same_(String(req.token || ""), token)) return out_({ ok: false, error: "認証できません" });
    const rootId = props.getProperty("ROOT_FOLDER_ID");
    if (!rootId) return out_({ ok: false, error: "ROOT_FOLDER_ID が未設定です" });
    const root = DriveApp.getFolderById(rootId);
    if (req.action === "ping") return out_({ ok: true, root: root.getName() });
    if (req.action === "put") {
      const lock = LockService.getScriptLock(); lock.waitLock(30000);   // 同時の要求で、同じ名前のフォルダを 2つ作らない
      try { return out_(put_(root, req)); } finally { lock.releaseLock(); }
    }
    return out_({ ok: false, error: "不明な操作です" });
  } catch (err) {
    return out_({ ok: false, error: String(err) });
  }
}

function doGet() { return out_({ ok: false, error: "POST だけを受け付けます" }); }

function put_(root, req) {
  const path = req.path;
  if (!Array.isArray(path) || path.length < 2 || path.length > MAX_DEPTH) return { ok: false, error: "パスが不正です" };
  for (const n of path) if (typeof n !== "string" || !n.trim() || n.indexOf("/") >= 0 || n.indexOf("\\") >= 0 || n.indexOf("..") >= 0 || n.length > 200) return { ok: false, error: "名前が不正です" };
  if (TOP.indexOf(path[0]) < 0) return { ok: false, error: "転送先のフォルダが不正です" };
  if (!req.data) return { ok: false, error: "内容がありません" };
  let folder = root;
  for (const n of path.slice(0, -1)) folder = child_(folder, n);
  const name = path[path.length - 1];
  const blob = Utilities.newBlob(Utilities.base64Decode(req.data), String(req.mime || "application/octet-stream"), name);
  const found = folder.getFilesByName(name);
  if (found.hasNext()) {
    const f = found.next();
    if (req.mode !== "overwrite") return { ok: true, action: "same", id: f.getId() };
    Drive.Files.update({}, f.getId(), blob, { supportsAllDrives: true });   // 高度な Google サービス Drive(v3)。内容だけを置き換え、版の履歴に残す
    return { ok: true, action: "updated", id: f.getId() };
  }
  const nf = folder.createFile(blob);
  return { ok: true, action: "created", id: nf.getId() };
}

function child_(parent, name) {
  const it = parent.getFoldersByName(name);
  return it.hasNext() ? it.next() : parent.createFolder(name);
}

function same_(a, b) {   // 合言葉の比較(長さが同じなら、全ての文字を比べる)
  if (a.length !== b.length) return false;
  let d = 0;
  for (let i = 0; i < a.length; i++) d |= a.charCodeAt(i) ^ b.charCodeAt(i);
  return d === 0;
}

function out_(obj) { return ContentService.createTextOutput(JSON.stringify(obj)).setMimeType(ContentService.MimeType.JSON); }

/** 手順 3 の確認用。エディタで実行し、ログにフォルダ名が出れば、ROOT_FOLDER_ID は正しい。 */
function checkSetup() {
  const p = PropertiesService.getScriptProperties();
  Logger.log("TOKEN: " + (p.getProperty("TOKEN") ? "設定済み(" + p.getProperty("TOKEN").length + "文字)" : "未設定"));
  Logger.log("共有ドライブのフォルダ: " + DriveApp.getFolderById(p.getProperty("ROOT_FOLDER_ID")).getName());
}
