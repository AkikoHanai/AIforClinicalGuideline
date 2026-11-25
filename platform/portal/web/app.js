/* GL作成ポータルの画面。Cognito(認可コード + PKCE)でログインし、API を呼ぶ。
   CIPN診療ガイドライン2023年版の手順(Minds)を踏襲する。判断は委員が行い、画面は本文の該当箇所を示し、記録する。 */
(function () {
  const C = window.PORTAL_CONFIG || {};
  const $ = (s) => document.querySelector(s);
  const esc = (s) => String(s ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
  const S = { token: null, me: null, meta: null, cqs: [] };
  const Q = () => Object.fromEntries(new URLSearchParams((location.hash.split("?")[1] || "")));
  const go = (page, q) => (location.hash = page + (q ? "?" + new URLSearchParams(q) : ""));

  // ---------- ログイン ----------
  const authBase = () => `https://${C.domain}.auth.${C.region}.amazoncognito.com`;
  const redirect = () => location.origin + "/";
  const b64url = (buf) => btoa(String.fromCharCode(...new Uint8Array(buf))).replace(/\+/g, "-").replace(/\//g, "_").replace(/=+$/, "");
  async function login() {
    const verifier = b64url(crypto.getRandomValues(new Uint8Array(32)));
    sessionStorage.setItem("pkce", verifier);
    const challenge = b64url(await crypto.subtle.digest("SHA-256", new TextEncoder().encode(verifier)));
    const q = new URLSearchParams({ response_type: "code", client_id: C.clientId, redirect_uri: redirect(), scope: "openid email profile", code_challenge: challenge, code_challenge_method: "S256" });
    location.href = `${authBase()}/oauth2/authorize?${q}`;
  }
  async function exchange(code) {
    const body = new URLSearchParams({ grant_type: "authorization_code", client_id: C.clientId, code, redirect_uri: redirect(), code_verifier: sessionStorage.getItem("pkce") || "" });
    let r;
    try { r = await fetch(`${authBase()}/oauth2/token`, { method: "POST", headers: { "Content-Type": "application/x-www-form-urlencoded" }, body }); }
    catch (e) { const er = new Error(`Cognito のトークン取得に接続できません(${e.message})`); er.status = 0; throw er; }
    if (!r.ok) { const er = new Error("Cognito のトークン取得に失敗しました(サインインのコードが無効です。もう一度ログインしてください)"); er.status = r.status; throw er; }
    const t = await r.json(); sessionStorage.setItem("id_token", t.id_token);
    history.replaceState({}, "", redirect() + (location.hash || "#dashboard"));
  }
  function logout() { sessionStorage.clear(); location.href = `${authBase()}/logout?${new URLSearchParams({ client_id: C.clientId, logout_uri: redirect() })}`; }
  function tokenValid(t) { try { const p = JSON.parse(atob(t.split(".")[1].replace(/-/g, "+").replace(/_/g, "/"))); return p.exp * 1000 > Date.now() + 60000; } catch { return false; } }

  // ---------- API ----------
  async function api(path, method = "GET", body) {
    let r;
    try { r = await fetch(C.apiUrl + path, { method, headers: { Authorization: "Bearer " + S.token, "Content-Type": "application/json" }, body: body !== undefined ? JSON.stringify(body) : undefined }); }
    catch (e) { const er = new Error(`API に接続できません(${e.message})`); er.status = 0; er.path = path; throw er; }
    const j = await r.json().catch(() => ({}));
    if (!r.ok) { const er = new Error(j.error || j.message || `エラー(${r.status})`); er.status = r.status; er.path = path; throw er; }
    return j;
  }
  // ログイン後の読み込みに失敗したとき、理由を画面に残す(消えるメッセージだけにしない)。自動で再読み込みしない
  function claims(t) { try { return JSON.parse(decodeURIComponent(escape(atob(t.split(".")[1].replace(/-/g, "+").replace(/_/g, "/"))))); } catch { return {}; } }
  function bootFail(step, e) {
    const c = claims(S.token || sessionStorage.getItem("id_token") || ""), g = c["cognito:groups"];
    $("#login").classList.remove("hidden"); $("#app").classList.add("hidden"); $("#gate").classList.add("hidden");
    let box = $("#bootErr"); if (!box) { box = document.createElement("div"); box.id = "bootErr"; box.className = "note need"; $("#login").appendChild(box); }
    box.innerHTML = `<b>サインインは完了しましたが、ポータルを開けませんでした。</b><br>失敗した処理: ${esc(step)}<br>内容: ${esc(e.message || e)}${e.status !== undefined ? `(HTTP ${esc(e.status)})` : ""}<br>
      サインインした利用者: ${esc(c.email || "(メールアドレスが、トークンにありません)")} / グループ: ${esc(Array.isArray(g) ? g.join("・") : g || "(なし)")}<br>トークンの有効期限: ${c.exp ? esc(new Date(c.exp * 1000).toLocaleString("ja-JP")) : "(不明)"}<br>API: ${esc(C.apiUrl || "(設定がありません)")}<br>${e.status === 0 ? "ブラウザの通信が届いていません。API の許可設定(CORS)、API の URL、学内ネットワーク・ブラウザの拡張機能が考えられます。統括委員長は、platform/portal/scripts/check_site.py を実行してください(原因の行が表示されます)。<br>" : ""}
      <button id="bootRetry">もう一度読み込む</button> <button id="bootOut">サインインをやり直す(ログアウト)</button>`;
    $("#bootRetry").addEventListener("click", () => location.reload()); $("#bootOut").addEventListener("click", logout);
  }
  function toast(msg, bad) { const t = $("#toast"); t.textContent = msg; t.className = "toast" + (bad ? " bad" : ""); setTimeout(() => t.classList.add("hidden"), 4000); }
  const can = (...gs) => S.me && S.me.groups.some((g) => gs.includes(g));
  const isAdmin = () => can("統括委員会", "事務局");
  const isLead = () => can("統括委員会", "事務局", "SR委員長");
  const isGroup = () => can("統括委員会", "作成グループ", "SR委員長", "事務局");
  const own = (c) => S.me.name && c.assignees.some((a) => S.me.name.startsWith(a));
  const tag = (v, cls) => `<span class="tag ${cls || (v === "完了" || v === "確定" ? "ok" : v && v !== "未着手" ? "run" : "")}">${esc(v)}</span>`;
  const sel = (opts, cur, attrs = "", blank = false) => `<select class="sm" ${attrs}>${blank ? '<option value="">—</option>' : ""}${opts.map((o) => `<option value="${esc(o)}" ${String(o) === String(cur) ? "selected" : ""}>${esc(o)}</option>`).join("")}</select>`;
  const vsel = (cur, attrs = "") => sel([0, -1, -2], cur === null || cur === undefined ? "" : cur, attrs, true);
  const cqSelect = (cur, id) => `<select id="${id}">${S.cqs.map((c) => `<option value="${esc(c.id)}" ${c.id === cur ? "selected" : ""}>${esc(c.id)} ${esc(c.title)}</option>`).join("")}</select>`;
  const auditTable = (list) => `<table><tr><th>日時</th><th>操作者</th><th>操作</th><th>対象</th><th>内容</th></tr>${list.map((a) => `<tr><td class="small">${esc(a.at.slice(0, 16).replace("T", " "))}</td><td>${esc(a.actor)}</td><td>${esc(a.action)}</td><td>${esc(a.target)}</td><td class="small">${esc(a.detail)}</td></tr>`).join("") || "<tr><td colspan=5 class='muted'>なし</td></tr>"}</table>`;

  // ---------- 本文の参照ウィンドウ ----------
  function paraPanel(text, highlight) {
    const hl = new Set(highlight || []);
    const secJa = { abstract: "抄録", methods: "Method", results: "Result", discussion: "Discussion", other: "その他", references: "文献" };
    const hasMR = text.paragraphs.some((p) => p.section === "methods" || p.section === "results");
    const note = !text.paragraphs.length ? '<p class="muted">文字を取り出せない PDF(画像)です。右の PDF を参照してください。OCR で本文を入れると段落が出ます。</p>' : (!hasMR ? '<p class="muted">Method・Result の見出しを判定できないため、全段落を表示します。</p>' : "");
    return `<div class="paras">${note}<div class="row"><label><input type="checkbox" id="onlyMR" ${hasMR ? "checked" : ""}> Method・Result だけ表示</label><input id="paraFind" placeholder="本文を検索" size="20"> ${text.source && text.source !== "pypdf" ? `<span class="tag">${esc(text.source)}</span>` : ""}</div>
      ${text.paragraphs.map((p) => `<div class="para ${hl.has(p.id) ? "hl" : ""}" data-sec="${p.section}" data-id="${esc(p.id)}"><span class="pid">${esc(p.id)}</span> <span class="tag">${secJa[p.section] || p.section} p.${p.page}</span><div>${esc(p.text)}</div></div>`).join("")}</div>`;
  }
  function wireParas(root) {
    const apply = () => { const only = root.querySelector("#onlyMR")?.checked; const q = (root.querySelector("#paraFind")?.value || "").toLowerCase();
      root.querySelectorAll(".para").forEach((d) => { const okSec = d.classList.contains("hl") || (d.dataset.sec !== "references" && (!only || d.dataset.sec === "methods" || d.dataset.sec === "results")); const okQ = !q || d.textContent.toLowerCase().includes(q); d.style.display = okSec && okQ ? "" : "none"; }); };
    root.querySelector("#onlyMR")?.addEventListener("change", apply); root.querySelector("#paraFind")?.addEventListener("input", apply); apply();
  }

  // ---------- 画面 ----------
  const pages = {
    async dashboard(m) {
      const d = await api("/dashboard"); const showSr = can("統括委員会", "事務局", "SR委員長", "SR委員", "作成グループ"), showSoron = can("統括委員会", "事務局", "総説執筆者");
      const href = (page, q) => "#" + page + (q && Object.keys(q).length ? "?" + new URLSearchParams(q) : "");
      const link = (t, page, q) => `<a href="${href(page, q)}">${t}</a>`;
      const mineA = (d.approvals || []).filter((a) => a.can), grp = {};
      mineA.forEach((a) => (grp[a.kind] = grp[a.kind] || []).push(a));
      const rows = [];
      (d.my_votes || []).forEach((v) => rows.push(`<tr><td>推奨の投票(第${v.round}回${v.deadline ? "、締切 " + esc(v.deadline) : ""})</td><td>${esc(v.cq)} ${esc(v.title)}</td><td class="nw">${link("投票する", "vote", { cq: v.cq })}</td></tr>`));
      Object.entries(grp).forEach(([k, arr]) => rows.push(`<tr><td>${esc(k)}</td><td>${arr.length}件</td><td class="nw">${link("開く", arr[0].page, arr[0].q)}</td></tr>`));
      const work = d.my_work || [];
      const cell = (n, page, q) => (n ? `<b>${n}</b> ${link("開く", page, q)}` : "0");
      const workTable = !work.length ? "" : `<table><tr><th>担当 CQ</th><th>一次スクリーニング<br><span class="small">自分が未判定</span></th><th>二次スクリーニング<br><span class="small">自分が未判定</span></th><th>SR-5<br><span class="small">自分の未提出 / 論文×アウトカム</span></th><th>SR-8<br><span class="small">未記入のアウトカム</span></th></tr>
        ${work.map((w) => `<tr><td>${link(esc(w.cq) + " " + esc(w.title), "papers", { cq: w.cq })}</td><td class="num">${cell(w.s1_open, "screening", { cq: w.cq })}</td><td class="num">${cell(w.s2_open, "screening", { cq: w.cq })}</td>
          <td class="num">${w.f45_need - w.f45_submitted_mine > 0 ? `<b>${w.f45_need - w.f45_submitted_mine}</b> / ${w.f45_need} ${link("開く", "f45", { cq: w.cq })}` : `0 / ${w.f45_need}`}</td><td class="num">${cell(w.sr8_open, "sr8", { cq: w.cq })}</td></tr>`).join("")}</table>`;
      const soronTable = !showSoron || !(d.my_soron || []).length ? "" : `<table><tr><th>担当の総論</th><th>原稿の記録</th><th></th></tr>${d.my_soron.map((x) => `<tr><td>総論${esc(x.label)} ${esc(x.title)}</td><td>${esc(x.status)}</td><td class="nw">${link("開く", "soron")}</td></tr>`).join("")}</table>`;
      const nothing = !rows.length && !work.length && !soronTable;
      const overview = !(showSr && can("統括委員会", "事務局", "SR委員長", "作成グループ")) ? "" : `<div class="card"><h3>全 CQ・FRQ の記録</h3><p class="small">判定済み / 対象、確定 / 必要、記入 / アウトカム の件数。自分の担当は薄い青。</p>
        <div class="scroll"><table><tr><th>CQ・FRQ</th><th>担当</th><th>検索の記録</th><th>一次</th><th>二次</th><th>採用</th><th>SR-5 確定</th><th>SR-8 記入</th></tr>
        ${d.cq.map((c) => { const n = c.counts, f = n.flow, nc = f.s1_conflict + f.s2_conflict; return `<tr class="${c.mine ? "mine" : ""}"><td>${link(esc(c.id) + " " + esc(c.title), "papers", { cq: c.id })}</td><td>${esc((c.assignees || []).join("・"))}</td>
          <td class="num">${link(f.searches, "search", { cq: c.id })}</td><td class="num">${f.s1_target - f.s1_open} / ${f.s1_target}</td><td class="num">${f.s2_target - f.s2_open} / ${f.s2_target}${nc ? ` <a href="${href("screening", { cq: c.id, show: "conflict" })}">不一致 ${nc}</a>` : ""}</td>
          <td class="num">${link(f.s2_include, "screening", { cq: c.id })}</td><td class="num">${n.f45_fixed} / ${n.f45_need}</td><td class="num">${n.sr8} / ${n.outcomes}</td></tr>`; }).join("")}</table></div></div>`;
      m.innerHTML = `<h2>ホーム</h2><p class="small">${esc(S.me.name || S.me.email)}(${esc(S.me.groups.join("・"))})</p>
        ${rows.length ? `<div class="card"><h3>対応が必要なもの</h3><table><tr><th>内容</th><th>対象</th><th></th></tr>${rows.join("")}</table></div>` : ""}
        ${work.length ? `<div class="card"><h3>自分の担当 CQ</h3>${workTable}</div>` : ""}
        ${soronTable ? `<div class="card"><h3>自分の担当の総論</h3>${soronTable}</div>` : ""}
        ${nothing ? `<div class="card"><p class="muted">${S.me.name ? "担当の CQ・総論と、対応が必要なものは、記録にありません。" : "氏名が登録されていません。統括委員長に連絡してください。"}</p></div>` : ""}
        ${overview}`;
    },

    async cq(m) {
      const list = await api("/cq"); S.cqs = list; const p0 = (list[0] || {}).pico || {};
      m.innerHTML = `<h2>CQ一覧</h2>
        <div class="card">全 CQ・FRQ に共通: 対象 <b>${esc(p0.P)}</b>、対照 <b>${esc(p0.C)}</b>、アウトカム <b>${esc(p0.O)}</b>。介入は、CQ ごとに異なる(下表の名称)。</div>
        <table style="margin-top:12px"><tr><th>ID</th><th>区分</th><th>介入(CQ の名称)</th><th>担当</th><th>画面</th></tr>
        ${list.map((c) => `<tr class="${own(c) ? "mine" : ""}"><td class="nw">${esc(c.id)}</td><td>${esc(c.category)}</td><td>${esc(c.title)}${c.pico.O !== p0.O ? ` <span class="small">(アウトカム: ${esc(c.pico.O)})</span>` : ""}</td><td>${esc(c.assignees.join("・"))}</td>
          <td class="nw"><a href="#search?cq=${esc(c.id)}">検索の記録</a> <a href="#screening?cq=${esc(c.id)}">スクリーニング</a> <a href="#papers?cq=${esc(c.id)}">論文</a> <a href="#f45?cq=${esc(c.id)}">SR-5</a> <a href="#sr8?cq=${esc(c.id)}">SR-8</a> <a href="#etd?cq=${esc(c.id)}">EtD</a></td></tr>`).join("")}</table>`;
    },

    async papers(m) {
      const q = Q(); const cqid = q.cq || S.cqs[0]?.id; const c = S.cqs.find((x) => x.id === cqid);
      const list = await api("/papers/" + cqid); const ed = own(c) || isLead();
      m.innerHTML = `<h2>論文</h2><div class="row">CQ ${cqSelect(cqid, "cqSel")}</div>
        <p class="small">二次スクリーニングで採用した論文。PMID を登録し、PDF を置くと、SR-5 で本文の該当箇所を見ながら評価できる。PDF は委員だけが閲覧できる。</p>
        ${ed ? `<div class="card"><div class="row"><input id="pmid" placeholder="PMID" size="10"><input id="ptitle" placeholder="題名(任意)" size="40"><input type="file" id="pdf" accept="application/pdf"><button id="regBtn" class="primary">登録してPDFを置く</button></div></div>` : ""}
        <div class="scroll"><table style="margin-top:12px"><tr><th>PMID</th><th>筆頭著者・雑誌・発行年</th><th>題名</th><th>研究デザイン</th><th>対象者数<br><span class="small">全体 / 介入群</span></th><th>介入</th><th>対照</th><th>評価時点</th><th></th></tr>
        ${list.map((p) => { const ch = p.chars || {}; return `<tr data-pmid="${esc(p.pmid)}"><td><a href="https://pubmed.ncbi.nlm.nih.gov/${esc(p.pmid)}/" target="_blank" rel="noopener">${esc(p.pmid)}</a></td>
          <td class="small">${esc([(p.authors || "").split(/[,;]/)[0], p.journal, p.year].filter(Boolean).join(". "))}</td><td class="w">${esc(p.title)}</td><td>${esc(ch.design || "")}</td>
          <td class="num">${esc(ch.n_total || "")}${ch.n_int ? " / " + esc(ch.n_int) : ""}</td><td class="small">${esc(ch.intervention_detail || "")}</td><td class="small">${esc(ch.comparator_detail || "")}</td><td class="small">${esc(ch.followup || "")}</td>
          <td class="nw">${p.s3_key ? '<button data-act="pdf">PDF</button> ' : ""}${ed && p.s3_key && !String(p.status || "").startsWith("本文抽出済") ? '<button data-act="extract">本文を取り込む</button> ' : ""}${ed ? '<button data-act="chars">研究の特性</button> ' : ""}<a href="#f45?cq=${esc(cqid)}&pmid=${esc(p.pmid)}">SR-5</a></td></tr>`; }).join("") || "<tr><td colspan=9 class='muted'>登録された論文はありません</td></tr>"}</table></div>
        <div id="charsBox"></div>`;
      $("#cqSel").addEventListener("change", () => go("papers", { cq: $("#cqSel").value }));
      $("#regBtn")?.addEventListener("click", async () => {
        const pmid = $("#pmid").value.replace(/\D/g, ""); const f = $("#pdf").files[0];
        if (!pmid) return toast("PMID を入れてください", true);
        try {
          const r = await api(`/papers/${cqid}/${pmid}/upload-url`, "POST", { title: $("#ptitle").value });
          if (f) { const u = await fetch(r.url, { method: "PUT", headers: { "Content-Type": "application/pdf" }, body: f }); if (!u.ok) throw new Error("PDF の送信に失敗しました");
            const x = await api(`/papers/${cqid}/${pmid}/extract`, "POST", {}); toast(`登録し、本文を抽出しました(${x.pages}頁、Method ${x.sections.methods}・Result ${x.sections.results} 段落)`); }
          else toast("登録しました(PDF は後で置けます)");
          render();
        } catch (e) { toast(e.message, true); }
      });
      m.querySelectorAll("button[data-act]").forEach((b) => b.addEventListener("click", async () => {
        const pmid = b.closest("tr").dataset.pmid;
        try {
          if (b.dataset.act === "pdf") { const r = await api(`/papers/${cqid}/${pmid}/pdf-url`); window.open(r.url, "_blank"); }
          if (b.dataset.act === "extract") { const x = await api(`/papers/${cqid}/${pmid}/extract`, "POST", {}); toast(`本文を抽出しました(${x.pages}頁、${x.paragraphs}段落)`); render(); }
          if (b.dataset.act === "chars") {
            const p = list.find((x) => x.pmid === pmid); const ch = p.chars || {};
            $("#charsBox").innerHTML = `<div class="card" style="margin-top:12px"><h3>研究特性 PMID ${esc(pmid)}</h3><div class="row">
              <label class="small">題名 <input data-c="title" value="${esc(p.title)}" size="50"></label>
              <label class="small">デザイン ${sel(["RCT", "non_RCT", "meta_analysis", "other"], ch.design, 'data-c="design"', true)}</label>
              <label class="small">がん腫 <input data-c="cancer" value="${esc(ch.cancer || "")}" size="16"></label>
              <label class="small">化学療法の分類 ${sel(S.meta.chemo_classes, ch.chemo_class, 'data-c="chemo_class"', true)}</label>
              <label class="small">薬剤名(本文のまま) <input data-c="chemo_drugs" value="${esc(ch.chemo_drugs || "")}" size="24"></label>
              <label class="small">N <input data-c="n_total" value="${esc(ch.n_total || "")}" size="5"></label><label class="small">介入群N <input data-c="n_int" value="${esc(ch.n_int || "")}" size="5"></label></div>
              <div class="row"><label class="small">介入 <input data-c="intervention_detail" value="${esc(ch.intervention_detail || "")}" size="40"></label><label class="small">対照 <input data-c="comparator_detail" value="${esc(ch.comparator_detail || "")}" size="30"></label><label class="small">評価時点 <input data-c="followup" value="${esc(ch.followup || "")}" size="20"></label><button id="charsSave" class="primary">保存</button></div></div>`;
            $("#charsSave").addEventListener("click", async () => { const chars = {}; let title = p.title; $("#charsBox").querySelectorAll("[data-c]").forEach((i) => { if (i.dataset.c === "title") title = i.value; else chars[i.dataset.c] = i.value; });
              try { await api(`/papers/${cqid}/${pmid}`, "PUT", { title, chars }); toast("保存しました"); render(); } catch (e) { toast(e.message, true); } });
          }
        } catch (e) { toast(e.message, true); }
      }));
    },

    async f45(m) {
      const q = Q(); const cqid = q.cq || S.cqs[0]?.id; const c = S.cqs.find((x) => x.id === cqid);
      const papers = await api("/papers/" + cqid); const pmid = q.pmid || papers[0]?.pmid; const outcome = q.outcome || (c.outcomes || [])[0];
      m.innerHTML = `<h2>SR-5 個別研究評価シート(介入研究)</h2><div class="row">CQ ${cqSelect(cqid, "cqSel")} 論文 <select id="pmSel">${papers.map((p) => `<option value="${esc(p.pmid)}" ${p.pmid === pmid ? "selected" : ""}>${esc(p.pmid)} ${esc((p.title || "").slice(0, 40))}</option>`).join("")}</select>
        アウトカム <select id="outSel">${(c.outcomes || []).map((o) => `<option ${o === outcome ? "selected" : ""}>${esc(o)}</option>`).join("")}</select></div><div id="f45body"></div>`;
      const nav = () => go("f45", { cq: $("#cqSel").value, pmid: $("#pmSel").value, outcome: $("#outSel").value });
      ["#cqSel", "#pmSel", "#outSel"].forEach((s) => $(s).addEventListener("change", nav));
      if (!pmid) return ($("#f45body").innerHTML = '<p class="muted">この CQ に登録された論文がありません。</p>');
      if (!outcome) return ($("#f45body").innerHTML = '<p class="muted">CQ・PICO・アウトカムの画面で、アウトカムを登録してください。</p>');
      const d = await api(`/f45/${cqid}/${pmid}/${encodeURIComponent(outcome)}`);
      let text = null; try { text = await api(`/papers/${cqid}/${pmid}/text`); } catch {}
      const mine = d.mine || { items: {} }; const ai = d.ai; const fin = d.final; const ed = (own(c) || isLead()) && !(mine.submitted && !isLead());
      const K = S.meta.item_keys, JA = S.meta.item_ja;
      const cell = (rec, k, editable, prefix) => { const it = (rec?.items || {})[k] || {}; return editable
        ? `${vsel(it.v, `data-k="${k}" data-f="v"`)}<br><input data-k="${k}" data-f="evidence" value="${esc((it.evidence || []).join(","))}" placeholder="段落ID" size="12"><br><input data-k="${k}" data-f="quote" value="${esc(it.quote || "")}" placeholder="引用 / 記載なし" size="22">`
        : `<b>${it.v === null || it.v === undefined ? "—" : it.v}</b> <span class="small">${(it.evidence || []).map((e) => `<a href="#" data-para="${esc(e)}">${esc(e)}</a>`).join(" ")}</span><div class="small">${esc(it.quote || "")}</div>`; };
      const mineCell = (k) => {
        if (!ai?.items || !ed) return cell(mine, k, ed);   // 下書きがない、または編集できない: 従来の表示
        const a = ai.items[k] || {}, it = (mine.items || {})[k] || {}, has = it.v !== null && it.v !== undefined, cur = has ? it.v : a.v, same = cur === a.v;
        return `${vsel(cur, `data-k="${k}" data-f="v" data-draft="${a.v === null || a.v === undefined ? "" : a.v}"`)}<input type="hidden" data-k="${k}" data-f="evidence" value="${esc((has ? it.evidence || [] : a.evidence || []).join(","))}"><span class="chg ${same ? "hidden" : ""}"><br><input data-k="${k}" data-f="quote" value="${esc(has && !same ? it.quote || "" : "")}" placeholder="直した理由" size="22"></span>`;
      };
      const dv = (...xs) => { const x = xs.find((v) => v !== null && v !== undefined && v !== "" && v !== "null"); return x === undefined ? "" : x; };
      const nz = (v) => (v === null || v === undefined || v === "" ? "—" : esc(v));
      const hl = new Set(); (ai?.numbers?.evidence || []).forEach((e) => hl.add(e)); [mine, ai, fin, ...Object.values(d.others || {})].forEach((r) => Object.values(r?.items || {}).forEach((it) => (it.evidence || []).forEach((e) => hl.add(e))));
      const otherCols = Object.entries(d.others || {});
      $("#f45body").innerHTML = `<div class="split">
        <div class="card" id="paraBox"><h3>本文の該当箇所 <button id="pdfBtn">PDF</button></h3>${text ? paraPanel(text, [...hl]) : '<p class="muted">本文が未抽出です。論文の画面で PDF を登録し、本文を抽出してください。下書きは本文がなければ作りません。</p>'}</div>
        <div class="card"><h3>判定(0 / -1 / -2) ${mine.submitted ? tag("提出済み", "ok") : ""} ${fin ? tag("確定", "ok") : d.reconcile_open ? tag("照合中", "run") : ""}</h3>
          <ol class="steps">${ai?.items
            ? `<li>Claude の下書き(右の本文の該当箇所つき)を見る</li><li>違う項目だけ、判定を直す(直した項目には、理由を書く)</li><li>「確認して提出」を押す。相手の判定は、2名が提出するまで表示されない</li>`
            : `<li>${ai?.status === "作成中" ? "下書きを作成中です(1〜2分後に、もう一度開く)" : "下書きがありません。「Claude下書きを作る」を押す(本文を取り込んだ論文に限る)。自分で判定してもよい"}</li><li>「提出」を押す。相手の判定は、2名が提出するまで表示されない</li>`}
            ${d.reconcile_open ? "<li>2名が提出したあと、照合して「照合の結果を確定する」を押す(確定できるのは、評価した2名とSR委員長)</li>" : ""}</ol>
          <p class="note">${fin ? `確定済み(${esc(fin.fixed_by || "")})` : d.reconcile_open ? "2名が提出済みです。照合して確定してください。" : `提出済み: ${d.submitted.length} 名(${esc(d.submitted.join("・")) || "なし"})`}。盲検化の2項目は -2 を使わない。</p>
          <div class="row">${ed && text && !ai?.items ? `<button id="draftBtn">Claude下書きを作る</button>` : ""}  ${ai && ai.status !== "下書き" ? `<span class="small">下書き: ${esc(ai.status || "")} ${ai.error ? esc(ai.error) : ""}</span>` : ""}</div>
          <div class="scroll"><table class="f45"><tr><th>項目</th>${ai?.items ? "<th>Claude下書き</th>" : ""}<th>自分(${esc(S.me.name || "—")})</th>${otherCols.map(([n]) => `<th>${esc(n)}</th>`).join("")}${d.reconcile_open || fin || isLead() ? "<th>確定(照合)</th>" : ""}</tr>
            ${K.map((k, i) => `<tr><td>${esc(JA[i])}</td>${ai?.items ? `<td>${cell(ai, k, false)}</td>` : ""}<td data-col="mine">${mineCell(k)}</td>${otherCols.map(([, r]) => `<td>${cell(r, k, false)}</td>`).join("")}
              ${d.reconcile_open || fin || isLead() ? `<td data-col="final">${cell(fin || mine, k, (d.reconcile_open && d.submitted.includes(S.me.name)) || isLead())}</td>` : ""}</tr>`).join("")}</table></div>
          ${ai?.items ? `<p class="note">Claude下書き(本文から): 測定尺度 <b>${esc(ai.study?.instrument || "記載なし")}</b>。対照 ${nz(ai.counts?.ctrl_num)} / ${nz(ai.counts?.ctrl_den)}、介入 ${nz(ai.counts?.int_num)} / ${nz(ai.counts?.int_den)}。効果 ${ai.effect?.measure && ai.effect.measure !== "null" ? `${esc(ai.effect.measure)} ${nz(ai.effect.value)} [${nz(ai.effect.ci_low)}, ${nz(ai.effect.ci_high)}]` : "記載なし"}。
            根拠 ${(ai.numbers?.evidence || []).map((e) => `<a href="#" data-para="${esc(e)}">${esc(e)}</a>`).join(" ") || "なし"} ${esc(ai.numbers?.quote || "")}</p>` : ""}
          <div class="row"><label class="small">測定尺度 <input id="instrument" value="${esc(mine.instrument || ai?.study?.instrument || "")}" size="24"></label>
            <label class="small">対照 分子/分母 <input id="cnum" value="${esc(dv(mine.counts?.ctrl_num, ai?.counts?.ctrl_num))}" size="4">/<input id="cden" value="${esc(dv(mine.counts?.ctrl_den, ai?.counts?.ctrl_den))}" size="4"></label>
            <label class="small">介入 分子/分母 <input id="inum" value="${esc(dv(mine.counts?.int_num, ai?.counts?.int_num))}" size="4">/<input id="iden" value="${esc(dv(mine.counts?.int_den, ai?.counts?.int_den))}" size="4"></label>
            <label class="small">効果 ${sel(["RR", "OR", "HR", "MD", "SMD"], dv(mine.effect?.measure, ai?.effect?.measure), 'id="emeas"', true)} <input id="eval" value="${esc(dv(mine.effect?.value, ai?.effect?.value))}" size="6"> [<input id="elo" value="${esc(dv(mine.effect?.ci_low, ai?.effect?.ci_low))}" size="6">, <input id="ehi" value="${esc(dv(mine.effect?.ci_high, ai?.effect?.ci_high))}" size="6">]</label></div>
          <div class="row"><label class="small">備考 <input id="note45" value="${esc(mine.note || "")}" size="60"></label></div>
          <div class="row">${ed ? `<button id="save45">保存(あとで続ける)</button> <button id="submit45" class="primary">${ai?.items ? "確認して提出" : "提出"}</button>` : ""} ${(d.reconcile_open && d.submitted.includes(S.me.name)) || isLead() ? `<button id="final45" class="approve">照合の結果を確定する</button>` : ""}</div>
          ${ai?.paragraphs_used ? `<p class="small">下書きの根拠: ${ai.paragraphs_used.length} 段落(Method・Result)。モデル ${esc(ai.model)}。下書きは出発点であり、判定は委員が行う。</p>` : ""}</div></div>`;
      if (text) wireParas($("#paraBox"));
      $("#pdfBtn")?.addEventListener("click", async () => { try { const r = await api(`/papers/${cqid}/${pmid}/pdf-url`); window.open(r.url, "_blank"); } catch (e) { toast(e.message, true); } });
      m.querySelectorAll("a[data-para]").forEach((a) => a.addEventListener("click", (ev) => { ev.preventDefault(); const el = m.querySelector(`.para[data-id="${a.dataset.para}"]`); if (el) { el.style.display = ""; el.scrollIntoView({ behavior: "smooth", block: "center" }); el.classList.add("flash"); } }));
      const toggleChg = (sel_) => { const td = sel_.closest("td"), chg = td && td.querySelector(".chg"); if (chg) chg.classList.toggle("hidden", sel_.value === sel_.dataset.draft); };
      m.querySelectorAll('td[data-col="mine"] select[data-draft]').forEach((x) => x.addEventListener("change", () => toggleChg(x)));
      const collect = (col) => { const items = {}; K.forEach((k) => { const g = (f) => m.querySelector(`td[data-col="${col}"] [data-k="${k}"][data-f="${f}"]`); const v = g("v")?.value === "" ? null : Number(g("v")?.value), dr = col === "mine" && ai?.items ? ai.items[k] : null, sameAsDraft = dr && v !== null && v === dr.v;
          items[k] = { v, evidence: (g("evidence")?.value || "").split(/[,\s]+/).filter(Boolean), quote: g("quote")?.value || (sameAsDraft ? dr.quote || "" : "") }; });   // 下書きのまま確認した項目は、下書きの根拠・引用を記録する
        return { items, instrument: $("#instrument").value, counts: { ctrl_num: $("#cnum").value, ctrl_den: $("#cden").value, int_num: $("#inum").value, int_den: $("#iden").value }, effect: { measure: $("#emeas").value, value: $("#eval").value, ci_low: $("#elo").value, ci_high: $("#ehi").value }, note: $("#note45").value }; };
      const path = `/f45/${cqid}/${pmid}/${encodeURIComponent(outcome)}`;
      $("#save45")?.addEventListener("click", async () => { try { await api(path, "PUT", { ...collect("mine"), submitted: false }); toast("保存しました"); render(); } catch (e) { toast(e.message, true); } });
      $("#submit45")?.addEventListener("click", async () => { const b = collect("mine"); if (K.some((k) => b.items[k].v === null)) return toast("空欄の項目があります(非RCTでランダム化・コンシールメントが該当しない場合も、備考に書いて -1 にする)", true);
        try { await api(path, "PUT", { ...b, submitted: true }); toast("提出しました"); render(); } catch (e) { toast(e.message, true); } });
      $("#final45")?.addEventListener("click", async () => { try { await api(path + "/final", "PUT", collect("final")); toast("確定しました"); render(); } catch (e) { toast(e.message, true); } });
      $("#draftBtn")?.addEventListener("click", async () => { try { await api(path + "/draft", "POST", {}); toast("下書きを作成中です(1〜2分後に再読み込み)"); setTimeout(render, 60000); } catch (e) { toast(e.message, true); } });
    },

    async sr8(m) {
      const q = Q(); const cqid = q.cq || S.cqs[0]?.id; const c = S.cqs.find((x) => x.id === cqid); const d = await api("/sr8/" + cqid); const ed = own(c) || isLead();
      m.innerHTML = `<h2>SR-8 エビデンス総体評価シート</h2><div class="row">CQ ${cqSelect(cqid, "cqSel")}</div>
        <p class="small">アウトカムごとに、確定したSR-5(照合後)を化学療法の分類(6区分)の層別行で示す。バイアスリスク・非一貫性・不精確性・非直接性・その他を 0 / -1 / -2、上昇要因を 0 / +1 / +2、エビデンスの確実性を A(強)〜D(非常に弱い)で評価する。SoF表は、この記入から作る。</p>
        ${d.outcomes.map((o) => { const r = o.sr8 || {}; return `<div class="card" style="margin-bottom:12px" data-o="${esc(o.outcome)}"><h3>${esc(o.outcome)} <span class="small">確定済み ${o.n_studies} 研究</span></h3>
          <table><tr><th>化学療法の分類</th><th>研究(PMID)</th><th>バイアスリスクまとめ</th><th>非直接性まとめ</th><th>効果</th></tr>
            ${Object.entries(o.by_chemo_class).map(([cls, rows]) => `<tr><td>${esc(cls)}</td><td>${rows.map((x) => esc(x.pmid)).join(", ")}</td><td>${rows.map((x) => x.bias_summary ?? "—").join(", ")}</td><td>${rows.map((x) => x.ind_summary ?? "—").join(", ")}</td><td class="small">${rows.map((x) => x.effect?.measure ? `${esc(x.effect.measure)} ${esc(x.effect.value)}` : "—").join("; ")}</td></tr>`).join("") || "<tr><td colspan=5 class='muted'>確定したSR-5 がありません</td></tr>"}</table>
          <div class="row">${["rob", "inconsistency", "imprecision", "indirectness", "publication_bias"].map((k, i) => `<label class="small">${esc(S.meta.sr8_ja[i])} ${ed ? vsel(r[k], `data-k="${k}"`) : `<b>${r[k] ?? "—"}</b>`}</label>`).join("")}
            <label class="small">上昇要因 ${ed ? sel([0, 1, 2], r.upgrade ?? "", 'data-k="upgrade"', true) : `<b>${r.upgrade ?? "—"}</b>`}</label>
            <label class="small">確実性 ${ed ? sel(S.meta.cert, r.certainty, 'data-k="certainty"', true) : `<b>${esc(r.certainty || "—")}</b>`}</label></div>
          <p class="small">SR-8 の列: 研究デザイン／研究数、群ごとの分母・分子、効果指標の種類・統合値・95%信頼区間、絶対効果、重要性、コメント。統合値(メタアナリシス)と絶対効果は、委員が計算した値を記入する(ポータルは計算しない)。分母・分子の「記録の合計」は、確定したSR-5 の人数の単純な合計である。</p>
          <div class="row"><label class="small">研究デザイン／研究数 <input data-k="design_n" value="${esc(r.design_n ?? o.design_n)}" size="26" ${ed ? "" : "readonly"}></label>
            ${[["ctrl_den", "対照群 分母"], ["ctrl_num", "対照群 分子"], ["int_den", "介入群 分母"], ["int_num", "介入群 分子"]].map(([k, ja]) => `<label class="small">${ja} <input data-k="${k}" value="${esc(r[k] ?? "")}" size="6" ${ed ? "" : "readonly"}></label>`).join("")}
            ${ed ? `<button data-sum='${esc(JSON.stringify(o.sums))}'>記録の合計(${o.sums.ctrl_num}/${o.sums.ctrl_den}、${o.sums.int_num}/${o.sums.int_den})を入れる</button>` : ""}</div>
          <div class="row"><label class="small">効果指標(種類) <input data-k="eff_type" value="${esc(r.eff_type || "")}" size="10" placeholder="RR など" ${ed ? "" : "readonly"}></label><label class="small">統合値 <input data-k="eff_val" value="${esc(r.eff_val || "")}" size="8" ${ed ? "" : "readonly"}></label><label class="small">95%信頼区間 <input data-k="eff_ci" value="${esc(r.eff_ci || "")}" size="14" ${ed ? "" : "readonly"}></label>
            <label class="small">絶対効果 <input data-k="abs_val" value="${esc(r.abs_val || "")}" size="12" ${ed ? "" : "readonly"}></label><label class="small">絶対効果の95%信頼区間 <input data-k="abs_ci" value="${esc(r.abs_ci || "")}" size="14" ${ed ? "" : "readonly"}></label>
            <label class="small">重要性(1〜9) ${ed ? sel([1, 2, 3, 4, 5, 6, 7, 8, 9], r.importance ?? "", 'data-k="importance"', true) : `<b>${r.importance ?? "—"}</b>`}</label></div>
          <div class="row"><label class="small">層別(分類ごとの結論) <input data-k="strata" value="${esc(r.strata || "")}" size="40" ${ed ? "" : "readonly"}></label><label class="small">効果の要約 <input data-k="effect_summary" value="${esc(r.effect_summary || "")}" size="40" ${ed ? "" : "readonly"}></label><label class="small">備考 <input data-k="note" value="${esc(r.note || "")}" size="30" ${ed ? "" : "readonly"}></label>${ed ? '<button data-act="save">保存</button>' : ""}</div></div>`; }).join("") || '<p class="muted">アウトカムが未登録です。</p>'}`;
      $("#cqSel").addEventListener("change", () => go("sr8", { cq: $("#cqSel").value }));
      m.querySelectorAll("button[data-sum]").forEach((b) => b.addEventListener("click", () => { const s = JSON.parse(b.dataset.sum), c = b.closest(".card"); Object.entries(s).forEach(([k, v]) => { c.querySelector(`[data-k="${k}"]`).value = v; }); }));
      m.querySelectorAll("button[data-act=save]").forEach((b) => b.addEventListener("click", async () => { const d2 = b.closest(".card"); const body = {}; d2.querySelectorAll("[data-k]").forEach((i) => (body[i.dataset.k] = i.value));
        try { await api(`/sr8/${cqid}/${encodeURIComponent(d2.dataset.o)}`, "PUT", body); toast("保存しました"); render(); } catch (e) { toast(e.message, true); } }));
    },

    async etd(m) {
      const q = Q(); const cqid = q.cq || S.cqs[0]?.id; const d = await api("/etd/" + cqid); const e = d.etd; const g = d.gl2023; const ed = isGroup();
      const cons = S.meta.etd_considerations;
      m.innerHTML = `<h2>EtD・推奨(2023年版の体裁)</h2><div class="row">CQ ${cqSelect(cqid, "cqSel")} ${tag(e.status)}</div>
        <ol class="steps"><li>左の 2023年版の記述(推奨文・推奨の強さ・エビデンスの確実性・解説・投票)と、SR-8 の確実性を確認する</li>
          <li>右に 2028年版の案を書く。推奨文には、適用するがん腫・化学療法の分類を明記する。4つの考慮事項には、根拠(論文の段落 ID、2023年版の段落 ID)を書く</li>
          <li>状態を「協議中」にして保存する</li>
          <li>推奨の投票は、「推奨の投票」の画面で、投票者が各自で行う(投票権のある委員の75%以上が参加、80%以上の一致で決定、最大3回。投票除外(直接評価した論文の筆頭著者、そのCQのSR担当者)は分母から除く)</li>
          <li><span class="approve">承認</span> 統括委員会が確定する</li></ol>
        <div class="split">
          <div class="card"><h3>2023年版</h3>${g ? `<p><b>推奨文</b> ${esc(g.rec)}</p><p>強さ ${esc(g.strength)} / 確実性 ${esc(g.certainty)} ${g.votes ? `/ 投票 分母 ${g.votes.denominator} 分布 ${(g.votes.counts || []).join("・")} (COI除外 ${g.votes.coi} SR除外 ${g.votes.sr})` : ""}</p>
            <div class="paras">${(g.paragraphs || []).map((p) => `<div class="para"><span class="pid">${esc(p.id)}</span><div>${esc(p.text)}</div></div>`).join("")}</div>` : '<p class="muted">2023年版の記述が未取り込みです(事務局が etd_2023.json を取り込む)。</p>'}
            <h3 style="margin-top:12px">SR-8 の確実性</h3><ul class="plain">${Object.entries(d.sr8).map(([o, r]) => `<li>${esc(o)}: <b>${esc(r.certainty || "—")}</b> ${esc(r.strata || "")}</li>`).join("") || "<li class='muted'>未記入</li>"}</ul></div>
          <div class="card"><h3>2028年版(案)</h3>
            <label class="small">推奨文(案。癌腫・レジメンを明記)<br><textarea id="rec" rows="3" cols="60" ${ed ? "" : "readonly"}>${esc(e.rec_draft || "")}</textarea></label>
            <div class="row"><label class="small">推奨の強さ ${ed ? sel(S.meta.strength, e.strength, 'id="strength"', true) : `<b>${esc(e.strength || "—")}</b>`}</label><label class="small">エビデンスの確実性 ${ed ? sel(S.meta.cert, e.certainty, 'id="cert"', true) : `<b>${esc(e.certainty || "—")}</b>`}</label></div>
            <label class="small">適用範囲・2023年版からの変更点 <input id="scope" value="${esc(e.scope_note || "")}" size="60" ${ed ? "" : "readonly"}></label>
            <table class="form" style="margin-top:8px"><tr><th>考慮事項</th><th>内容</th><th>根拠(段落ID)</th></tr>
              ${cons.map(([k, ja]) => `<tr><td>${esc(ja)}</td><td><textarea data-ck="${k}" data-f="text" rows="3" cols="40" ${ed ? "" : "readonly"}>${esc(e.considerations?.[k]?.text || "")}</textarea></td><td><input data-ck="${k}" data-f="evidence" value="${esc((e.considerations?.[k]?.evidence || []).join(","))}" size="18" ${ed ? "" : "readonly"}></td></tr>`).join("")}</table>
            <h3 style="margin-top:12px">投票</h3>
            <p>${e.vote?.round ? `第${e.vote.round}回(${esc(e.vote.date)}): ${(e.vote.counts || []).map((n, i) => `${i + 1}: ${n}票`).join("、")}、棄権 ${e.vote.abstain ?? 0}。参加 ${e.vote.denominator} / ${e.vote.eligible ?? "—"}名。最多の選択肢 ${e.vote.agreement ?? "—"}%` : "投票の記録はありません"}<br><a href="#vote?cq=${esc(cqid)}"><b>「推奨の投票」の画面を開く</b></a>(電子投票。委員が、自分で投票する)</p>
            <label class="small">解説(推奨の理由。根拠の段落ID付き)<br><textarea id="narr" rows="6" cols="60" ${ed ? "" : "readonly"}>${esc(e.narrative || "")}</textarea></label>
            <p class="note ${e.status === "協議中" ? "need" : ""}"><span class="approve">承認</span> 確定は、投票の記録のあとに統括委員会が行う。${e.status === "協議中" ? "状態は協議中。確定の記録がない。" : e.status === "確定" ? "確定の記録あり。" : "作成グループが書き終えたら、状態を「協議中」にして保存する。"}</p>
            <div class="row">${ed ? `<button id="etdSave" class="primary">保存</button> 状態 ${sel(["下書き", "協議中"].concat(e.status === "確定" ? ["確定"] : []), e.status, 'id="etdStatus"')} ${can("統括委員会") && e.status !== "確定" ? '<button id="etdFix" class="approve">承認: 確定する(統括委員会)</button>' : ""} <button id="etdDraft">Claude下書きを作る(SR-8・SR-5・2023年版を根拠に)</button>` : ""} <button id="exportBtn">Minds書類(xlsx)を出力</button></div>
            ${e.ai_draft ? `<div class="card" style="margin-top:10px"><h3>Claude下書き <span class="small">${esc(e.ai_draft.status || "")} ${esc((e.ai_draft.at || "").slice(0, 16))} ${e.ai_draft.error ? esc(e.ai_draft.error) : ""}</span></h3>
              ${e.ai_draft.rec_draft ? `<p><b>推奨文案</b> ${esc(e.ai_draft.rec_draft)}</p>${cons.map(([k, ja]) => `<p><b>${esc(ja)}</b> ${esc(e.ai_draft.considerations?.[k]?.text || "")} <span class="small">${esc((e.ai_draft.considerations?.[k]?.evidence || []).join(", "))}</span></p>`).join("")}<p><b>解説文案</b><br>${esc(e.ai_draft.narrative || "").replace(/\n/g, "<br>")}</p><p class="small">2023年版からの変更点: ${esc(e.ai_draft.changes_from_2023 || "")}</p>
              ${ed ? '<button id="etdCopy">下書きを右の欄に取り込んで修正する</button>' : ""}<p class="small">根拠のIDは、SR8-アウトカム、F45-PMID-アウトカム、GL2023-段落。推奨の強さと確実性は、下書きに含めない(投票とSR-8で決める)。</p>` : ""}</div>` : ""}</div></div>`;
      $("#cqSel").addEventListener("change", () => go("etd", { cq: $("#cqSel").value }));
      $("#etdDraft")?.addEventListener("click", async () => { try { await api("/etd/" + cqid + "/draft", "POST", {}); toast("下書きを作成中です(1〜2分後に再読み込み)"); setTimeout(render, 60000); } catch (e2) { toast(e2.message, true); } });
      $("#exportBtn")?.addEventListener("click", async () => { try { const r = await api("/export/" + cqid); toast(`出力しました(${r.sheets.join("・")})`); if (r.url) window.open(r.url, "_blank"); } catch (e2) { toast(e2.message, true); } });
      $("#etdCopy")?.addEventListener("click", () => { const a = e.ai_draft; $("#rec").value = a.rec_draft || ""; cons.forEach(([k]) => { m.querySelector(`[data-ck="${k}"][data-f="text"]`).value = a.considerations?.[k]?.text || ""; m.querySelector(`[data-ck="${k}"][data-f="evidence"]`).value = (a.considerations?.[k]?.evidence || []).join(","); }); $("#narr").value = a.narrative || ""; toast("取り込みました。確認・修正して保存してください"); });
      const saveEtd = async (status) => { const considerations = {}; cons.forEach(([k]) => (considerations[k] = { text: m.querySelector(`[data-ck="${k}"][data-f="text"]`).value, evidence: m.querySelector(`[data-ck="${k}"][data-f="evidence"]`).value.split(/[,\s]+/).filter(Boolean) }));
        try { await api("/etd/" + cqid, "PUT", { rec_draft: $("#rec").value, strength: $("#strength")?.value, certainty: $("#cert")?.value, scope_note: $("#scope").value, considerations, narrative: $("#narr").value, status: status || $("#etdStatus").value }); toast(status ? "確定しました" : "保存しました"); render(); } catch (e2) { toast(e2.message, true); } };
      $("#etdSave")?.addEventListener("click", () => saveEtd());
      $("#etdFix")?.addEventListener("click", () => { if (confirm("この CQ の EtD・推奨を確定しますか(統括委員会の承認として記録されます)")) saveEtd("確定"); });
    },

    async soron(m) {
      const list = await api("/soron"); const admin = isAdmin();
      const mineOnly = !admin && !isLead();
      const rows = list.filter((s) => !mineOnly || (S.me.name && s.author.split("・").some((a) => a && S.me.name.startsWith(a))));
      m.innerHTML = `<h2>総論(A〜N)の執筆・査読</h2>
        <ol class="steps"><li>執筆者が、依頼書(Word。2023年版の全文入り)がある行では、「依頼書・2023年版」から開く</li><li>執筆者が、依頼書を直接修正した原稿(Word)をこの画面で提出し、状態を「査読中」にして保存する</li><li>統括委員会・事務局が査読コメントを書く(状態は「修正中」になる)</li><li>執筆者が修正版を提出する</li><li><span class="approve">承認</span> 統括委員会が「完了」にする</li></ol>
        <p class="note">企画書の総論${list.length}項目と担当。原稿は版ごとに保存される。SRの流れ(CQ)とは独立している。</p>
        <table><tr><th>項目</th><th>題名</th><th>担当</th><th>状態</th><th>期限</th><th>最新の原稿</th><th>査読コメント(統括委員会)</th><th>備考</th><th></th></tr>
        ${rows.map((s) => { const o = S.me.name && s.author.split("・").some((a) => a && S.me.name.startsWith(a)); const ed = o || admin;
          return `<tr data-key="${esc(s.key)}"><td class="nw">${esc(s.label)}</td><td class="w">${esc(s.title)}</td><td class="nw">${esc(s.author)}</td>
            <td>${ed ? sel(S.meta.soron_states.filter((x) => admin || x !== "完了"), s.status, "data-status") : tag(s.status)}</td>
            <td>${ed ? `<input type="date" data-due value="${esc(s.due || "")}">` : esc(s.due || "")}</td>
            <td class="small">${s.file ? `<a href="#" data-dl="${esc(s.key)}">${esc(s.file)}</a><br>${esc((s.file_at || "").slice(0, 16))} ${esc(s.file_by || "")}` : "—"}${ed ? `<br><input type="file" data-up accept=".docx,.doc,.pdf"> <button data-act="upload">提出</button>` : ""}</td>
            <td>${admin ? `<textarea data-review rows="2" cols="24">${esc(s.review || "")}</textarea>` : esc(s.review || "")}${s.review_by ? `<div class="small">${esc(s.review_by)} ${esc((s.review_at || "").slice(0, 16))}</div>` : ""}</td>
            <td>${ed ? `<input data-note value="${esc(s.note || "")}" size="14">` : esc(s.note || "")}</td><td>${ed ? '<button data-act="save">保存</button> ' : ""}<button data-gl="${esc(s.key)}">依頼書・2023年版</button></td></tr>`; }).join("") || "<tr><td colspan=9 class='muted'>担当の総論はありません</td></tr>"}</table><div id="gl2023Box"></div>`;
      m.querySelectorAll("button[data-act=save]").forEach((b) => b.addEventListener("click", async () => { const tr = b.closest("tr"); const body = { status: tr.querySelector("[data-status]").value, due: tr.querySelector("[data-due]").value, note: tr.querySelector("[data-note]").value };
        const rv = tr.querySelector("[data-review]"); if (rv) body.review = rv.value;
        try { await api("/soron/" + tr.dataset.key, "PUT", body); toast("保存しました"); render(); } catch (e) { toast(e.message, true); } }));
      m.querySelectorAll("button[data-act=upload]").forEach((b) => b.addEventListener("click", async () => { const tr = b.closest("tr"); const f = tr.querySelector("[data-up]").files[0]; if (!f) return toast("原稿のファイルを選んでください", true);
        try { const r = await api("/soron/" + tr.dataset.key + "/upload-url", "POST", { filename: f.name, content_type: f.type || "application/octet-stream" });
          const u = await fetch(r.url, { method: "PUT", headers: { "Content-Type": f.type || "application/octet-stream" }, body: f }); if (!u.ok) throw new Error("原稿の送信に失敗しました");
          toast("原稿を提出しました"); render(); } catch (e) { toast(e.message, true); } }));
      m.querySelectorAll("a[data-dl]").forEach((a) => a.addEventListener("click", async (ev) => { ev.preventDefault(); try { const r = await api("/soron/" + a.dataset.dl + "/download-url"); window.open(r.url, "_blank"); } catch (e) { toast(e.message, true); } }));
      m.querySelectorAll("button[data-gl]").forEach((b) => b.addEventListener("click", async () => {
        try { const g = await api("/soron/" + b.dataset.gl + "/gl2023"); const box = $("#gl2023Box");
          if (!g.paragraphs) { box.innerHTML = '<p class="note need">この総論の依頼書は、まだ登録されていません(事務局が登録します)。</p>'; return; }
          box.innerHTML = `<div class="card" style="margin-top:12px"><h3>総論${esc(b.dataset.gl.replace("_", "-"))} ${esc(g.title)}</h3>
            <p>${g.docx_url ? `<a href="${esc(g.docx_url)}" target="_blank" rel="noopener"><b>依頼書(Word)を開く</b></a>。` : ""}${g.paragraphs.length ? `依頼書には、2023年版の全文(${g.paragraphs.length} 段落。表は編集できる表)が入っています。この Word を直接修正し、上の表の「提出」から原稿として提出します。` : "新設の項目です。2023年版に該当する節はありません。依頼書に執筆の要点の記入欄があります。"}</p>
            ${g.paragraphs.length ? '<p class="small">下は 2023年版の本文です。段落 ID を、変更箇所の指示に使えます。</p>' : ""}<div class="paras">${g.paragraphs.map((p) => `<div class="para"><span class="pid">${esc(p.id)}</span><div>${esc(p.text)}</div></div>`).join("")}</div></div>`;
          box.scrollIntoView({ behavior: "smooth" }); } catch (e) { toast(e.message, true); } }));
    },

    async search(m) {
      const q = Q(); const cqid = q.cq || S.cqs[0]?.id; const c = S.cqs.find((x) => x.id === cqid); const ed = own(c) || isLead();
      const [list, ref] = await Promise.all([api("/search/" + cqid), api(`/search/${cqid}/reference`)]); const cur = list.find((r) => r.id === q.edit) || {};
      const refCard = !(ref.formula || []).length && !(ref.prior || []).length ? "" : `<div class="card"><h3>参考: 検索式の案と、2023年版の検索過程</h3>
        <p class="note">この枠は参考資料であり、検索の記録には数えない。検索式の案は、前回Scopeの式(P・C は全CQで共通、I は本CQの介入語)である。検索期間と検索式の変更は、統括委員会の承認が必要である。2023年版の検索過程は、当時の担当者の Word から取り出した記録であり、欠けや誤りがありうる。</p>
        ${(ref.last_search_end_2023 || []).length ? `<p>2023年版の検索の終了日: <b>${esc(ref.last_search_end_2023.join("、"))}</b>(今回の検索期間は、この翌月から)</p>` : '<p>2023年版の検索の終了日: 記録なし(SR委員長に確認する)</p>'}
        ${(ref.formula || []).map((f, i) => `<p><b>検索式の案(${esc(f.dir)})</b>。本CQの介入語: ${esc(f.terms)}<br><span class="mono">${esc(f.query)}</span>${ed ? `<br><button data-fill="${i}">この式を検索式の欄に写す(日付の条件は自分で加える)</button>` : ""}</p>`).join("")}
        ${(ref.prior || []).length ? `<details><summary>2023年版の検索過程(${ref.prior.length} 件)</summary><table><tr><th>CQ</th><th>文書</th><th>データベース</th><th>検索期間(原文)</th><th>検索式(原文)</th><th>件数・除外の記載(原文)</th></tr>
          ${ref.prior.map((p) => `<tr><td>${esc(p.dir)}</td><td>${esc(p.file)}</td><td>${esc(p.database)}</td><td>${esc(p.period_text)}</td><td class="w">${esc(p.query)}</td><td class="w">${esc((p.flow_lines || []).join(" / "))}</td></tr>`).join("")}</table></details>` : ""}
        ${(ref.notes || []).map((n) => `<p class="small">${esc(n)}</p>`).join("")}</div>`;
      const total = list.reduce((a, r) => a + Number(r.hits || 0), 0);
      m.innerHTML = `<h2>検索の記録(Minds SR-1 データベース検索結果)</h2><div class="row">CQ ${cqSelect(cqid, "cqSel")}</div>
        <p class="note">検索を実行するたびに、1 行を記録する(更新検索も 1 行)。検索式は、PubMed の検索窓に入れた文字列を、そのまま貼り付ける。日付の条件は、検索式の中に書く。記録の修正は、作成経過の記録に残る。</p>
        ${ed ? `<div class="card"><h3>${cur.id ? "記録の修正" : "記録の追加"}</h3>
          <div class="row"><label>データベース <input id="sDb" size="14" value="${esc(cur.database || "PubMed")}"></label><label>検索日 <input id="sDate" type="date" value="${esc(cur.date || "")}"></label>
            <label>検索者 <input id="sWho" size="14" value="${esc(cur.searcher || S.me.name || "")}"></label><label>検索期間 <input id="sPeriod" size="26" placeholder="例: 2021-07-01〜2026-10-31" value="${esc(cur.period || "")}"></label>
            <label>件数 <input id="sHits" type="number" min="0" size="8" value="${esc(cur.hits ?? "")}"></label></div>
          <div class="row"><label>検索式<br><textarea id="sQuery" rows="4" cols="90">${esc(cur.query || "")}</textarea></label></div>
          <div class="row"><label>備考 <input id="sNote" size="70" value="${esc(cur.note || "")}"></label><button id="sSave" class="primary">${cur.id ? "修正を保存" : "記録する"}</button>${cur.id ? ` <a href="#search?cq=${esc(cqid)}">修正をやめる</a>` : ""}</div></div>` : ""}
        ${refCard}
        <div class="card"><h3>記録(${list.length} 件。件数の合計 ${total} 件)</h3>
          <table><tr><th>検索日</th><th>データベース</th><th>検索者</th><th>検索期間</th><th>検索式</th><th>件数</th><th>備考</th><th>操作</th></tr>
          ${list.map((r) => `<tr><td class="nw">${esc(r.date)}</td><td>${esc(r.database)}</td><td>${esc(r.searcher)}</td><td>${esc(r.period)}</td><td class="w">${esc(r.query)}</td><td class="num">${esc(r.hits)}</td><td>${esc(r.note)}</td>
            <td class="nw">${ed ? `<a href="#search?cq=${esc(cqid)}&edit=${esc(r.id)}">修正</a> <a href="#screening?cq=${esc(cqid)}&search=${esc(r.id)}">結果を取り込む</a>` : ""}${isLead() ? ` <button data-del="${esc(r.id)}">削除</button>` : ""}</td></tr>`).join("") || '<tr><td colspan="8" class="muted">記録なし</td></tr>'}</table>
          <p class="note">検索結果の文献は、「結果を取り込む」から、スクリーニングの対象に登録する。件数は、文献選択の流れ図(スクリーニングの画面)に使う。</p></div>`;
      $("#cqSel").addEventListener("change", () => go("search", { cq: $("#cqSel").value }));
      $("#sSave")?.addEventListener("click", async () => {
        const b = { database: $("#sDb").value, date: $("#sDate").value, searcher: $("#sWho").value, period: $("#sPeriod").value, query: $("#sQuery").value, hits: $("#sHits").value, note: $("#sNote").value };
        try { await api("/search/" + cqid + (cur.id ? "/" + cur.id : ""), cur.id ? "PUT" : "POST", b); toast("記録しました"); if (cur.id) go("search", { cq: cqid }); else render(); } catch (e) { toast(e.message, true); } });
      m.querySelectorAll("button[data-fill]").forEach((b) => b.addEventListener("click", () => { $("#sQuery").value = ref.formula[Number(b.dataset.fill)].query; $("#sQuery").scrollIntoView({ behavior: "smooth" }); }));
      m.querySelectorAll("button[data-del]").forEach((b) => b.addEventListener("click", async () => { if (!confirm("この検索の記録を削除しますか(削除は作成経過の記録に残ります)")) return;
        try { await api(`/search/${cqid}/${b.dataset.del}`, "DELETE"); render(); } catch (e) { toast(e.message, true); } }));
    },

    async screening(m) {
      const q = Q(); const cqid = q.cq || S.cqs[0]?.id;
      const [d, searches] = await Promise.all([api("/screening/" + cqid), api("/search/" + cqid)]);
      const f = d.flow, P = d.candidates, me = S.me.name; const need = (t) => `<span class="approve">${esc(t)}</span>`;
      const myDec = (p, st) => (p.mine[st] || {}).decision || "";
      const s2ok = (p) => p.direct || ["採用", "保留"].includes(p.s1.decision) || ["採用", "保留"].includes(myDec(p, "s1"));
      const FIL = { all: ["すべて", () => true], my1: ["一次 自分が未判定", (p) => !p.direct && !myDec(p, "s1")], my2: ["二次 自分が未判定", (p) => s2ok(p) && !myDec(p, "s2")],
        conflict: ["不一致(協議の結論が必要)", (p) => p.s1.state === "不一致" || p.s2.state === "不一致"], s2: ["二次の対象", (p) => p.direct || ["採用", "保留"].includes(p.s1.decision)],
        inc: ["採用", (p) => p.s2.decision === "採用"], exc: ["除外", (p) => p.s1.decision === "除外" || p.s2.decision === "除外"] };
      let show = FIL[q.show] ? q.show : "all", page = 0; const PER = 50;   // 絞り込みと頁送りは、画面の中で行う(文献を読み直さない)
      const box = (t, n, sub, cls) => `<div class="fbox ${cls || ""}"><b>${esc(t)}</b>: ${n} 件${sub ? `<br>${sub}` : ""}</div>`;
      const reasons = Object.entries(f.s2_reasons).map(([k, v]) => `${esc(k)} ${v} 件`).join("、");
      const flowHtml = `<div class="flow">
        ${box("データベース検索で得た文献(検索の記録の件数の合計)", f.db_hits, Object.entries(f.by_db).map(([k, v]) => `${esc(k)} ${v} 件`).join("、") || "検索の記録なし")}<div></div>${box("その他の情報源から加えた文献", f.cand_other)}
        <div class="farrow">↓</div><div></div><div class="farrow">↓</div>
        ${box("スクリーニングの対象として登録した文献", f.cands, `データベース検索 ${f.cand_db} 件、その他の情報源 ${f.cand_other} 件。取り込みのときに登録済みのため除いた重複 ${f.duplicates} 件`, "fwide")}
        <div class="farrow">↓</div><div></div><div></div>
        ${box("一次スクリーニング(題名・抄録)の対象", f.s1_target, `結果: 採用 ${f.s1_include} 件、保留 ${f.s1_hold} 件。結果の記録がない文献 ${f.s1_open} 件(うち 2名の判定が不一致 ${f.s1_conflict} 件)`)}<div class="farrow">→</div>${box("一次で除外した文献", f.s1_exclude)}
        <div class="farrow">↓</div><div></div><div></div>
        ${box("二次スクリーニング(全文)の対象", f.s2_target, `一次を経ずに加えた文献 ${f.direct} 件を含む。結果の記録がない文献 ${f.s2_open} 件(うち 2名の判定が不一致 ${f.s2_conflict} 件)`)}<div class="farrow">→</div>${box("二次で除外した文献", f.s2_exclude, reasons ? "除外理由: " + reasons : "")}
        <div class="farrow">↓</div><div></div><div></div>
        ${box("採用した文献", f.s2_include, `うち「論文」の画面に登録済み ${f.registered} 件`)}<div></div>${box("スクリーニングの記録がなく「論文」に登録済みの論文", f.papers_unscreened, "2023年版の引用文献として取り込んだ論文など。上の流れの件数には数えていない")}</div>`;
      const others = (p, st) => p[st + "_others"].map((o) => `${esc(o.reviewer)}: ${esc(o.decision)}${o.reason ? `(${esc(o.reason)})` : ""}`).join("<br>");
      const result = (p, st) => { const r = p[st]; return r.decision ? `${tag(r.decision, r.decision === "除外" ? "" : "ok")} ${esc(r.by)}${r.reason ? `<br>除外理由: ${esc(r.reason)}` : ""}` : (r.state === "不一致" ? need("不一致") : `判定 ${r.n} 名`); };
      const cell = (p, st) => { const opts = st === "s1" ? ["採用", "除外", "保留"] : ["採用", "除外"]; const cur = p.mine[st] || {}; const na = st === "s1" ? p.direct : !s2ok(p);
        if (na) return `<td>${st === "s1" ? "一次を経ない" : "対象外"}</td>`;
        return `<td class="w">${d.reviewer ? `<div>自分: ${sel(opts, cur.decision || "", `data-dec="${st}"`, true)} <select class="sm${cur.decision === "除外" ? "" : " hidden"}" data-reason="${st}"><option value="">(除外理由)</option>${d.reasons.filter((o) => st === "s2" || !d.reasons_s2_only.includes(o)).map((o) => `<option ${o === cur.reason ? "selected" : ""}>${esc(o)}</option>`).join("")}</select></div>` : ""}
          ${st === "s2" && d.reviewer ? `<div>全文: ${sel(["未入手", "入手済", "読了"], p.mine.ft || "未入手", "data-ft")}</div>` : ""}<div>結果: ${result(p, st)}${st === "s2" && p.s2.decision === "採用" ? ` <a href="#papers?cq=${esc(cqid)}">「論文」に登録する</a>` : ""}</div>${others(p, st) ? `<div class="small">${others(p, st)}</div>` : ""}
          ${d.can_edit && (p[st].state === "不一致" || p[st].decision) && p[st].n >= 2 ? `<button class="${p[st].state === "不一致" ? "approve" : "link"}" data-final="${st}">${p[st].state === "不一致" ? "承認: 協議の結論を記録する" : "結果を修正する(協議の結論)"}</button>` : ""}</td>`; };
      const rowHtml = (p) => `<tr data-pmid="${esc(p.pmid)}"><td><a href="https://pubmed.ncbi.nlm.nih.gov/${esc(p.pmid)}/" target="_blank" rel="noopener">${esc(p.pmid)}</a></td>
            <td class="w">${esc(p.title || "(題名は未取得)")}<div class="small">${esc([p.authors, p.journal, p.year].filter(Boolean).join(". "))}</div><div class="small">出典: ${esc(p.source)}${p.added_why ? `(${esc(p.added_why)})` : ""}</div>${p.has_abstract ? `<details data-abs><summary>抄録</summary><div class="abs">読み込み中…</div></details>` : ""}
              ${(p.mine.history || []).length ? `<details><summary>自分の変更の履歴 ${p.mine.history.length} 件</summary>${p.mine.history.map((h) => `${esc(h.at.slice(0, 16).replace("T", " "))} ${esc(h.field)}: ${esc(h.from)} → ${esc(h.to)} ${esc(h.reason)}`).join("<br>")}</details>` : ""}
              ${d.reviewer ? `<div><input data-note size="30" placeholder="備考" value="${esc(p.mine.note || "")}"></div>` : ""}</td>
            ${cell(p, "s1")}${cell(p, "s2")}</tr>`;
      const drawList = () => { const rows = P.filter(FIL[show][1]); page = Math.min(page, Math.max(0, Math.ceil(rows.length / PER) - 1)); const view = rows.slice(page * PER, page * PER + PER);
        $("#scrList").innerHTML = `<h3>文献(${rows.length} 件 / 対象 ${P.length} 件)</h3>
          <div class="row">${Object.entries(FIL).filter(([k]) => d.reviewer || !k.startsWith("my")).map(([k, [ja, fn]]) => `<button class="tag ${k === show ? "run" : ""}" data-show="${k}">${esc(ja)} ${P.filter(fn).length}</button>`).join("")}</div>
          <table class="scr"><tr><th>PMID</th><th>文献</th><th>一次(題名・抄録)</th><th>二次(全文)</th></tr>${view.map(rowHtml).join("") || '<tr><td colspan="4" class="muted">該当する文献はありません</td></tr>'}</table>
          <div class="row">${page > 0 ? `<button data-page="${page - 1}">前の ${PER} 件</button>` : ""} ${rows.length ? `${page * PER + 1}〜${Math.min(rows.length, (page + 1) * PER)} 件目` : ""} ${(page + 1) * PER < rows.length ? `<button data-page="${page + 1}">次の ${PER} 件</button>` : ""}</div>`; };
      m.innerHTML = `<h2>スクリーニング(一次・二次)と文献選択の流れ図</h2><div class="row">CQ ${cqSelect(cqid, "cqSel")}</div>
        <ol class="steps"><li>検索結果(「検索の記録」の件数の文献)と、その他の情報源の文献を、スクリーニングの対象に取り込む</li><li>担当委員 2名が、一次(題名・抄録)の可否を、相手の判定を見ずに入力する。除外には理由を選ぶ。一次では、アウトカムを理由に除外せず、抄録で判断できない文献は残す(Minds 第4章)</li>
          <li>一次の結果が採用・保留の文献について、全文を読み、二次の可否を入力する</li><li>${need("承認")} 2名の判定が不一致の文献は、2名で協議し、SR委員長に報告して第三者の意見を得たうえで、「協議の結論」に結論・協議の内容・第三者の意見を記録する(担当委員。SR委員長も記録できる)</li><li>採用した文献を、「論文」の画面に登録する</li></ol>
        <p class="note">相手の判定は、自分がその文献のその段階を判定した後に表示される(2名独立)。2名の判定がそろった後は、自分の判定を変更できない。結果は、2名の判定の一致、または協議の結論である。</p>
        <div class="card"><h3>文献選択の流れ図(Minds SR-2 文献検索フローチャート)</h3>${flowHtml}
          <p class="note">件数は、検索の記録とスクリーニングの記録から数えた値である(この画面を開いた時点)。判定を入力した後の件数は、「件数を数え直す」で更新する。別添は、流れ図の枠ごとの文献の一覧(PMID・題名・著者。二次の対象と採用の一覧は Minds SR-3 二次スクリーニング後の一覧表の材料)であり、件数と一覧の行数が一致する。</p>
          <div class="row"><button id="scrReload">件数を数え直す</button><button id="scrExport" class="primary">別添(検索の記録・件数・文献の一覧。xlsx)を出力</button></div></div>
        ${d.can_edit ? `<div class="card"><h3>対象の取り込み</h3>
          <div class="row"><label>出典 ${sel(d.sources, q.search ? "検索(PubMed)" : "", 'id="iSrc"')}</label><label>検索の記録 <select id="iSearch"><option value="">—</option>${searches.map((r) => `<option value="${esc(r.id)}" ${r.id === q.search ? "selected" : ""}>${esc(r.date)} ${esc(r.database)} ${esc(r.hits)}件</option>`).join("")}</select></label>
            <label><input type="checkbox" id="iDirect"> 一次を経ない(二次の対象として加える)</label><label>追加の理由(データベース検索以外は必須) <input id="iWhy" size="40"></label></div>
          <div class="row"><label>PubMed の「Save → Format: CSV」の内容、または PMID の行(PMID だけ、または「PMID(タブ)題名」)を貼り付ける<br><textarea id="iText" rows="5" cols="100"></textarea></label></div>
          <div class="row"><input type="file" id="iFile" accept=".csv,.txt"><button id="iBtn" class="primary">取り込む</button><button id="iFetch">題名・抄録を PubMed から取得する</button></div></div>` : ""}
        <div class="card"><div id="scrList"></div><div id="finalBox"></div></div>`;
      drawList();
      $("#cqSel").addEventListener("change", () => go("screening", { cq: $("#cqSel").value }));
      $("#scrReload").addEventListener("click", render);
      $("#scrExport").addEventListener("click", async () => { try { const r = await api(`/export/${cqid}/screening`); if (r.url) window.open(r.url, "_blank"); toast("別添を出力しました"); } catch (e) { toast(e.message, true); } });
      const L = $("#scrList"); const rowOf = (el) => P.find((p) => p.pmid === el.closest("tr").dataset.pmid);
      const put = async (p, body) => { try { const r = await api(`/screening/${cqid}/${p.pmid}`, "PUT", body); Object.assign(p, r.row); toast("記録しました"); } catch (e) { toast(e.message, true); } drawList(); };
      L.addEventListener("click", (ev) => { const b = ev.target.closest("button"); if (!b) return;
        if (b.dataset.show) { show = b.dataset.show; page = 0; return drawList(); }
        if (b.dataset.page !== undefined) { page = Number(b.dataset.page); drawList(); return L.scrollIntoView(); }
        if (b.dataset.final) { const p = rowOf(b), st = b.dataset.final; const ja = st === "s1" ? "一次" : "二次";
          $("#finalBox").innerHTML = `<div class="card"><h3>協議の結論(${ja}) PMID ${esc(p.pmid)}</h3><p>${esc(p.title)}</p>
            <p>判定: ${[...(p.mine[st]?.decision ? [`${esc(me)}: ${esc(p.mine[st].decision)}${p.mine[st].reason ? `(${esc(p.mine[st].reason)})` : ""}`] : []), ...p[st + "_others"].map((o) => `${esc(o.reviewer)}: ${esc(o.decision)}${o.reason ? `(${esc(o.reason)})` : ""}`)].join("、")}</p>
            <div class="row"><label>結論 ${sel(st === "s1" ? ["採用", "除外", "保留"] : ["採用", "除外"], "", 'id="fDec"', true)}</label><label>除外理由 ${sel(d.reasons.filter((o) => st === "s2" || !d.reasons_s2_only.includes(o)), "", 'id="fReason"', true)}</label><label>協議の内容(結論の理由) <input id="fWhy" size="50"></label></div>
            <div class="row"><label>第三者の意見(SR委員長に報告し、述べられた意見) <input id="fOpinion" size="60"></label><label>意見を述べた人 <input id="fOpinionBy" size="12" value="SR委員長"></label>
              <button id="fBtn" class="approve">承認: 協議の結論を記録する</button></div></div>`;
          $("#finalBox").scrollIntoView({ behavior: "smooth" });
          $("#fBtn").addEventListener("click", async () => { try { const r = await api(`/screening/${cqid}/${p.pmid}/final`, "PUT", { stage: st, decision: $("#fDec").value, reason: $("#fReason").value, why: $("#fWhy").value, opinion: $("#fOpinion").value, opinion_by: $("#fOpinionBy").value });
            Object.assign(p, r.row); $("#finalBox").innerHTML = ""; toast("協議の結論を記録しました"); drawList(); } catch (e) { toast(e.message, true); } }); } });
      L.addEventListener("change", (ev) => { const el = ev.target; if (!el.closest("tr[data-pmid]")) return; const p = rowOf(el);
        if (el.dataset.ft !== undefined) return put(p, { ft: el.value });
        if (el.dataset.note !== undefined) return put(p, { note: el.value });
        const st = el.dataset.dec || el.dataset.reason; if (!st) return; const tr = el.closest("tr"); const dec = tr.querySelector(`select[data-dec="${st}"]`).value; const rs = tr.querySelector(`select[data-reason="${st}"]`);
        rs.classList.toggle("hidden", dec !== "除外"); if (!dec) return; if (dec === "除外" && !rs.value) return toast("除外理由を選んでください");
        const cur = p.mine[st] || {}; const body = { stage: st, decision: dec, reason: dec === "除外" ? rs.value : "" };
        if (cur.decision && (cur.decision !== dec || (cur.reason || "") !== body.reason)) { const why = window.prompt(`判定を変更します(${cur.decision} → ${dec})。変更の理由を入力してください。`); if (!why || !why.trim()) return drawList(); body.change_reason = why.trim(); }
        put(p, body); });
      L.addEventListener("toggle", async (ev) => { const dt = ev.target; if (!dt.matches || !dt.matches("details[data-abs]") || !dt.open || dt.dataset.loaded) return; dt.dataset.loaded = "1";
        try { const r = await api(`/screening/${cqid}/${dt.closest("tr").dataset.pmid}/abstract`); dt.querySelector(".abs").textContent = r.abstract || "抄録の記録はありません"; } catch (e) { dt.querySelector(".abs").textContent = e.message; } }, true);
      const parse = (text) => { const out = [], seen = new Set(); const push = (o) => { if (/^\d{5,9}$/.test(o.pmid) && !seen.has(o.pmid)) { seen.add(o.pmid); out.push(o); } };
        const csv = (line) => { const a = []; let cur = "", inq = false; for (let k = 0; k < line.length; k++) { const ch = line[k]; if (inq) { if (ch === '"' && line[k + 1] === '"') { cur += '"'; k++; } else if (ch === '"') inq = false; else cur += ch; } else if (ch === '"') inq = true; else if (ch === ",") { a.push(cur); cur = ""; } else cur += ch; } a.push(cur); return a; };
        const lines = text.replace(/^﻿/, "").split(/\r?\n/).filter((l) => l.trim());
        if (lines.length && /^"?PMID"?,/.test(lines[0])) { const h = csv(lines[0]); const ix = (n) => h.indexOf(n);
          lines.slice(1).forEach((l) => { const a = csv(l); push({ pmid: (a[ix("PMID")] || "").trim(), title: a[ix("Title")] || "", authors: a[ix("Authors")] || "", journal: a[ix("Journal/Book")] || "", year: a[ix("Publication Year")] || "" }); });
        } else lines.forEach((l) => { const mm = l.match(/^\s*"?(\d{5,9})"?\s*(?:[\t,]\s*"?(.*?)"?)?\s*$/); if (mm) push({ pmid: mm[1], title: (mm[2] || "").slice(0, 500) }); });
        return out; };
      $("#iFile")?.addEventListener("change", async () => { const fl = $("#iFile").files[0]; if (fl) $("#iText").value = await fl.text(); });
      $("#iBtn")?.addEventListener("click", async () => { const items = parse($("#iText").value); if (!items.length) return toast("PMID の行がありません", true);
        try { let a = 0, dp = 0; for (let k = 0; k < items.length; k += 500) { const r = await api(`/screening/${cqid}/candidates`, "POST", { source: $("#iSrc").value, search_id: $("#iSearch").value, direct: $("#iDirect").checked, why: $("#iWhy").value, items: items.slice(k, k + 500) }); a += r.added; dp += r.duplicates; }
          toast(`追加 ${a} 件、登録済みのため除いた重複 ${dp} 件`); if (q.search) go("screening", { cq: cqid }); else render(); } catch (e) { toast(e.message, true); } });
      $("#iFetch")?.addEventListener("click", async () => { let n = 0; $("#iFetch").disabled = true;
        try { for (;;) { const r = await api(`/screening/${cqid}/fetch`, "POST", {}); n += r.fetched; if (!r.remaining || !r.asked) break; } toast(`${n} 件の題名・抄録を取得しました`); render(); } catch (e) { toast(e.message, true); $("#iFetch").disabled = false; } });
    },

    async access(m) {
      const list = await api("/access"); const pend = list.filter((a) => a.status === "承認待ち"); const G = S.meta.groups;
      const roleBoxes = (a) => G.map((g) => `<label class="tag"><input type="checkbox" class="aRole" value="${esc(g)}" ${(a.suggest || []).includes(g) ? "checked" : ""}> ${esc(g)}</label>`).join("");
      m.innerHTML = `<h2>利用申請(承認)</h2><p class="note">委員は、ポータルの「Sign up」でアカウントを作り、氏名と所属を申請する。<span class="approve">承認</span> 統括委員長が、委員であることを確認して承認する(役割を付ける)。承認の前は、何も見えない。氏名が企画書の名簿と一致した申請には、名簿に基づく役割の候補を入れてある(候補であり、承認する人が決める)。承認された委員は、もう一度ログインする。</p>
        <div class="card"><h3>承認待ち(${pend.length}件)</h3>
          ${pend.length ? `<div class="row"><button id="aAll" class="approve">承認: 名簿に一致する申請(${pend.filter((a) => (a.suggest || []).length).length}件)を、候補の役割で一括承認する</button></div>` : ""}
          <table><tr><th>申請日</th><th>氏名</th><th>メールアドレス</th><th>所属</th><th>役割(候補を入れてある)</th><th>操作</th></tr>
          ${pend.map((a) => `<tr data-email="${esc(a.email)}"><td class="nw">${esc((a.requested_at || "").slice(0, 10))}</td><td>${esc(a.name)}${(a.suggest || []).length ? "" : ' <span class="tag warn">名簿にない氏名</span>'}</td><td>${esc(a.email)}</td><td>${esc(a.affiliation || "")}</td><td>${roleBoxes(a)}</td>
            <td class="nw"><button class="approve" data-ok>承認</button> <button data-no>却下</button></td></tr>`).join("") || '<tr><td colspan="6" class="muted">承認待ちの申請はありません</td></tr>'}</table></div>
        <div class="card"><h3>処理済み</h3><table><tr><th>氏名</th><th>メールアドレス</th><th>状態</th><th>役割・理由</th></tr>
          ${list.filter((a) => a.status !== "承認待ち").map((a) => `<tr><td>${esc(a.name)}</td><td>${esc(a.email)}</td><td>${esc(a.status)}</td><td>${esc((a.roles || []).join("・") || a.reason || "")}</td></tr>`).join("") || '<tr><td colspan="4" class="muted">なし</td></tr>'}</table></div>`;
      const approve = async (email, roles) => api(`/access/${encodeURIComponent(email)}/approve`, "POST", { roles });
      m.querySelectorAll("button[data-ok]").forEach((b) => b.addEventListener("click", async () => { const tr = b.closest("tr"); const roles = [...tr.querySelectorAll(".aRole:checked")].map((c) => c.value);
        try { await approve(tr.dataset.email, roles); toast("承認しました"); render(); } catch (e) { toast(e.message, true); } }));
      m.querySelectorAll("button[data-no]").forEach((b) => b.addEventListener("click", async () => { const why = window.prompt("却下の理由(申請した人に表示されます)", "委員ではない"); if (why === null) return;
        try { await api(`/access/${encodeURIComponent(b.closest("tr").dataset.email)}/reject`, "POST", { reason: why }); render(); } catch (e) { toast(e.message, true); } }));
      $("#aAll")?.addEventListener("click", async () => { const t = pend.filter((a) => (a.suggest || []).length); if (!confirm(`次の ${t.length} 件を、候補の役割で承認します。メールアドレスが、委員のものであることを確認しましたか。\n\n` + t.map((a) => `${a.name} <${a.email}> ${a.suggest.join("・")}`).join("\n"))) return;
        try { for (const a of t) await approve(a.email, a.suggest); toast(`${t.length}件を承認しました`); render(); } catch (e) { toast(e.message, true); } });
    },

    async vote(m) {
      const q = Q(); const cqid = q.cq || S.cqs[0]?.id; const d = await api("/vote/" + cqid); const adm = d.admin, me = d.me; const L = d.strength_labels; const cur = d.rounds[d.rounds.length - 1];
      const lab = (i) => i === "棄権" ? "棄権" : L[Number(i) - 1];
      const resultHtml = (r) => !r.result ? "" : `<table><tr><th>選択肢</th>${r.result.counts.map((_, i) => `<th>${esc(L[i])}</th>`).join("")}<th>棄権</th><th>参加 / 投票者</th><th>参加率</th><th>最多の割合(参加者に対して)</th><th>判定</th></tr>
        <tr><td>票数</td>${r.result.counts.map((n) => `<td class="num">${n}</td>`).join("")}<td class="num">${r.result.abstain}</td><td class="num">${r.result.participants} / ${r.result.eligible}</td><td class="num">${r.result.participation_pct}%</td><td class="num">${r.result.agreement_pct}%</td>
        <td>${r.result.passed ? `<span class="tag ok">成立: ${esc(L[r.result.strength - 1])}</span>` : r.result.final_none ? '<span class="tag warn">3回で成立せず: 推奨なし</span>' : '<span class="tag warn">不成立</span>'}</td></tr></table>`;
      m.innerHTML = `<h2>推奨の投票(電子投票)</h2><div class="row">CQ ${cqSelect(cqid, "cqSel")}</div>
        <ol class="steps"><li>統括委員会が、推奨文案を確認し、投票のラウンドを開始する(投票者は、統括委員会・作成グループから、そのCQのSR担当と、投票除外を除いた委員)</li><li>投票者が、各自でログインして、投票する(1回だけ。変更できない。無記名)</li>
          <li><span class="approve">承認</span> 統括委員会が、ラウンドを終了し、集計する(参加が投票者の75%以上、最多の選択肢が参加者の80%以上で成立。最大${d.max_rounds}回。3回で成立しなければ「推奨なし」)</li><li>成立した強さが、EtD・推奨に入る。統括委員会が、EtD・推奨を確定する</li></ol>
        <div class="card"><h3>${esc(d.cq)} ${esc(d.title)}</h3><p><b>推奨文案</b><br>${d.rec ? esc(d.rec) : '<span class="muted">未記入(「EtD・推奨」に、推奨文案を書く)</span>'}</p>${d.scope_note ? `<p class="small">適用範囲・変更点: ${esc(d.scope_note)}</p>` : ""}
          <p class="small">SR-8 の確実性: ${d.sr8.map((s) => `${esc(s.outcome)} ${esc(s.certainty || "未記入")}`).join("、") || "未記入"} / EtD の状態: ${esc(d.etd_status)} / <a href="#etd?cq=${esc(cqid)}">EtD・推奨を開く</a></p></div>
        <div class="card"><h3>あなたの投票</h3>
          ${me.round_open && me.eligible && !me.voted ? `<p class="note need"><span class="approve">要投票</span> 第${me.round_open}回が受付中です${cur.deadline ? "(締切 " + esc(cur.deadline) + ")" : ""}。投票は、1回だけで、変更できません。</p>
            ${["1", "2", "3", "4", "5", "棄権"].map((c) => `<div><label><input type="radio" name="vc" value="${c}"> ${esc(lab(c))}</label></div>`).join("")}<p><button id="vGo" class="primary">投票する</button></p>`
          : me.round_open && me.voted ? `<p>第${me.round_open}回に投票しました。結果は、ラウンドの終了の後に表示されます。</p>`
          : me.round_open ? '<p class="muted">この CQ の投票者ではありません(SR担当、投票除外、または投票権のない役割)。</p>' : '<p class="muted">受付中の投票はありません。</p>'}</div>
        ${adm ? `<div class="card"><h3>運営(統括委員会・事務局)</h3>
          <p>投票者(${adm.pool.length}名): ${esc(adm.pool.join("、")) || "なし"}${adm.sr_excluded.length ? `<br>SR担当のため除く: ${esc(adm.sr_excluded.join("、"))}` : ""}</p>
          ${cur && cur.status === "受付中" ? `<p>第${cur.round}回: 投票済み ${cur.voted} / ${cur.eligible}名。未投票: ${esc(adm.not_voted.join("、")) || "なし"}(メールで、投票をお願いする)</p><p><button id="vClose" class="approve">承認: 第${cur.round}回を終了し、集計する</button></p>`
            : `<div class="row"><label class="small">投票除外(COI。1行に 1名: メールアドレス,理由) <textarea id="vExcl" rows="3" cols="60">${esc((adm.exclusions || []).map((x) => x.email + "," + x.reason).join("\n"))}</textarea></label><button id="vExclSave">投票除外を保存</button></div>
              <div class="row"><label class="small">締切(任意) <input id="vDl" type="date"></label><button id="vOpen" class="primary">${cur ? `第${cur.round + 1}回を開始する` : "第1回を開始する"}</button></div>`}</div>` : ""}
        <div class="card"><h3>結果</h3>${d.rounds.map((r) => `<h4>第${r.round}回(${esc(r.opened_at.slice(0, 10))}〜${esc((r.closed_at || "").slice(0, 10)) || "受付中"}。投票者 ${r.eligible}名、SR担当の除外 ${r.sr_excluded}名、投票除外 ${r.coi_excluded}名)</h4>${r.result ? resultHtml(r) : `<p class="muted">受付中。投票済み ${r.voted} / ${r.eligible}名。集計は、終了の後に表示されます。</p>`}`).join("") || '<p class="muted">まだ投票は行われていません。</p>'}</div>`;
      $("#cqSel").addEventListener("change", () => go("vote", { cq: $("#cqSel").value }));
      $("#vGo")?.addEventListener("click", async () => { const c = document.querySelector('input[name=vc]:checked')?.value; if (!c) return toast("選択肢を選んでください", true);
        if (!confirm(`「${lab(c)}」に投票します。投票は 1回だけで、変更できません。よろしいですか。`)) return;
        try { await api(`/vote/${cqid}/cast`, "POST", { round: me.round_open, choice: c }); toast("投票しました"); render(); } catch (e) { toast(e.message, true); } });
      $("#vOpen")?.addEventListener("click", async () => { try { await api(`/vote/${cqid}/open`, "POST", { deadline: $("#vDl").value }); toast("投票を開始しました"); render(); } catch (e) { toast(e.message, true); } });
      $("#vClose")?.addEventListener("click", async () => { if (!confirm(`未投票 ${adm.not_voted.length}名のまま集計します。終了すると、投票できなくなります。よろしいですか。`)) return;
        try { await api(`/vote/${cqid}/close`, "POST", {}); toast("集計しました"); render(); } catch (e) { toast(e.message, true); } });
      $("#vExclSave")?.addEventListener("click", async () => { const items = $("#vExcl").value.split("\n").map((l) => l.trim()).filter(Boolean).map((l) => { const [e, ...r] = l.split(/[,、]/); return { email: e.trim(), reason: r.join(",").trim() }; });
        try { await api(`/vote/${cqid}/exclusions`, "PUT", { items }); toast("保存しました"); render(); } catch (e) { toast(e.message, true); } });
    },

    async users(m) {
      const list = await api("/users"); const ed = isAdmin();
      m.innerHTML = `<h2>利用者(登録済み)</h2><p class="small">利用者は、ポータルの「Sign up」で自分で登録し、「利用申請(承認)」で承認する。この画面は、承認済みの利用者の一覧と、例外の直接登録(招待メールを送る)に使う。名簿と COI は Google フォーム・ドライブで管理する。氏名は企画書の表記(例: 華井明子)と一致させる。担当 CQ・総論の抽出に使う。</p>
        ${ed ? `<div class="card"><div class="row"><input id="uEmail" placeholder="メールアドレス" size="28"><input id="uName" placeholder="氏名" size="12">${S.meta.groups.map((g) => `<label class="tag"><input type="checkbox" class="uRole" value="${esc(g)}"> ${esc(g)}</label>`).join("")}<button id="uAdd" class="primary">登録して招待</button></div>
          <div class="row"><button id="seedBtn">初期データの作成(企画書の CQ・総論。既にある項目は変えない)</button></div></div>` : ""}
        <table style="margin-top:12px"><tr><th>氏名</th><th>メールアドレス</th><th>役割</th>${ed ? "<th></th>" : ""}</tr>${list.map((u) => `<tr><td>${esc(u.name)}</td><td>${esc(u.email)}</td><td>${(u.roles || []).map((r) => tag(r, "")).join("")}</td>${ed ? `<td><button data-del="${esc(u.email)}">削除</button></td>` : ""}</tr>`).join("")}</table>`;
      $("#uAdd")?.addEventListener("click", async () => { const roles = [...m.querySelectorAll(".uRole:checked")].map((c) => c.value);
        try { const r = await api("/users", "POST", { email: $("#uEmail").value, name: $("#uName").value, roles, invite: true }); toast(r.invited ? "招待メールを送りました" : "登録しました"); render(); } catch (e) { toast(e.message, true); } });
      $("#seedBtn")?.addEventListener("click", async () => { try { const r = await api("/admin/seed", "POST", {}); toast(`${r.created}件を作成しました`); S.cqs = await api("/cq"); render(); } catch (e) { toast(e.message, true); } });
      m.querySelectorAll("button[data-del]").forEach((b) => b.addEventListener("click", async () => { if (!confirm(`${b.dataset.del} を削除しますか`)) return; try { await api("/users/" + encodeURIComponent(b.dataset.del), "DELETE"); toast("削除しました"); render(); } catch (e) { toast(e.message, true); } }));
    },

    async docs(m) {
      const list = await api("/docs" + (isAdmin() ? "?missing=1" : ""));
      const have = list.filter((d) => d.available !== false), miss = list.filter((d) => d.available === false);
      m.innerHTML = `<h2>手順書</h2>
        ${have.length ? `<table><tr><th>手順書</th><th>対象</th><th>更新日</th><th></th></tr>${have.map((d) => `<tr><td>${esc(d.name.replace(/\.docx$/, ""))}</td><td>${esc(d.target)}</td><td class="nw">${esc(d.updated)}</td><td class="nw"><a href="${esc(d.url)}" target="_blank" rel="noopener">Word を開く</a></td></tr>`).join("")}</table>` : '<p class="muted">登録されている手順書はありません。</p>'}
        ${miss.length ? `<div class="card"><h3>未登録の手順書</h3><p>${miss.map((x) => esc(x.name)).join("、")}</p><p class="small">統括委員長が、Mac で ./setup_portal.sh を実行すると登録される(この欄は、統括委員会・事務局にだけ表示される)。</p></div>` : ""}`;
    },

    async audit(m) { const list = await api("/audit"); m.innerHTML = `<h2>作成経過の記録</h2><p class="small">全ての操作が追記される。更新・削除の操作はない。${list.length}件</p>${auditTable(list)}`; },
  };

  async function render() {
    const page = (location.hash || "#dashboard").slice(1).split("?")[0];
    document.querySelectorAll(".side a").forEach((a) => a.classList.toggle("active", a.dataset.page === page));
    const m = $("#main"); m.innerHTML = '<p class="muted">読み込み中…</p>';
    try { if (!S.cqs.length) S.cqs = await api("/cq"); await (pages[page] || pages.dashboard)(m);
      // 幅の広い表は、画面全体ではなく表の枠の中で横に送る
      m.querySelectorAll("table").forEach((t) => { if (!t.parentElement.classList.contains("scroll")) { const w = document.createElement("div"); w.className = "scroll"; t.replaceWith(w); w.appendChild(t); } });
    } catch (e) { m.innerHTML = `<p class="note need">${esc(e.message)}</p>`; }
  }

  // ---------- 利用申請(承認の前) ----------
  async function showGate() {
    $("#gate").classList.remove("hidden"); const a = await api("/access/me"), r = a.request, box = $("#gateBody");
    const out = '<p><button id="gateOut">ログアウト</button></p>';
    if (r && r.status === "承認待ち") box.innerHTML = `<p>申請を受け付けました(${esc(r.name)}、${esc(r.affiliation || "")})。統括委員長が承認した後に、ポータルを使えます。</p><p>承認されたら、一度ログアウトして、もう一度ログインしてください。</p>${out}`;
    else if (r && r.status === "却下") box.innerHTML = `<p class="note need">申請は承認されませんでした。${esc(r.reason || "")}<br>委員の方は、統括委員長にメールで連絡してください。</p>${out}`;
    else if (r && r.status === "承認済み") box.innerHTML = `<p>承認されました。一度ログアウトして、もう一度ログインしてください。</p>${out}`;
    else { box.innerHTML = `<p>ログインしました(${esc(a.email)})。利用の申請をしてください。統括委員長が、委員であることを確認して承認します。</p>
      <div class="row"><label>氏名(企画書の表記。例: 華井明子) <input id="gName" size="16"></label></div><div class="row"><label>所属 <input id="gAff" size="30"></label></div>
      <p><button id="gateReq" class="primary">申請する</button> <button id="gateOut">ログアウト</button></p>`;
      $("#gateReq").addEventListener("click", async () => { try { await api("/access/request", "POST", { name: $("#gName").value, affiliation: $("#gAff").value }); showGate(); } catch (e) { toast(e.message, true); } }); }
    $("#gateOut").addEventListener("click", logout);
  }

  async function boot() {
    const code = new URLSearchParams(location.search).get("code");
    $("#loginBtn").addEventListener("click", login);
    if (code) { try { await exchange(code); } catch (e) { $("#login").classList.remove("hidden"); return bootFail("サインインのコードの交換(Cognito のトークン取得)", e); } }
    const t = sessionStorage.getItem("id_token");
    if (!t || !tokenValid(t)) { sessionStorage.removeItem("id_token"); $("#login").classList.remove("hidden"); return; }
    S.token = t;
    try { S.me = await api("/me"); } catch (e) { return bootFail("利用者の確認(GET /me)", e); }
    if (!S.me.groups.length) { try { return await showGate(); } catch (e) { return bootFail("利用申請の確認(GET /access/me)", e); } }
    try { S.meta = await api("/meta"); } catch (e) { return bootFail("設定の取得(GET /meta)", e); }
    $("#meName").textContent = S.me.name || S.me.email; $("#meGroups").textContent = S.me.groups.join("・") || "(グループ未設定)";
    $("#logoutBtn").addEventListener("click", logout);
    // 表示する流れ: SR(担当委員・SR委員長・作成グループ・統括・事務局)、総説(総説執筆者・統括・事務局)、事務局(統括・事務局)
    const showSr = can("統括委員会", "事務局", "SR委員長", "SR委員", "作成グループ"), showSoron = can("統括委員会", "事務局", "総説執筆者"), showAdmin = isAdmin();
    document.querySelector('.navsec[data-flow="sr"]').classList.toggle("hidden", !showSr);
    document.querySelector('.navsec[data-flow="soron"]').classList.toggle("hidden", !showSoron);
    document.querySelector('.navsec[data-flow="admin"]').classList.toggle("hidden", !showAdmin);
    document.querySelector('a[data-page="vote"]').classList.toggle("hidden", !can("統括委員会", "作成グループ", "事務局"));   // 投票者・運営だけ
    $("#app").classList.remove("hidden");
    window.addEventListener("hashchange", render); render();
  }
  boot();
})();
