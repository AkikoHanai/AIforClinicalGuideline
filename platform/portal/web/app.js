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
    const r = await fetch(`${authBase()}/oauth2/token`, { method: "POST", headers: { "Content-Type": "application/x-www-form-urlencoded" }, body });
    if (!r.ok) throw new Error("トークンの取得に失敗しました");
    const t = await r.json(); sessionStorage.setItem("id_token", t.id_token);
    history.replaceState({}, "", redirect() + (location.hash || "#dashboard"));
  }
  function logout() { sessionStorage.clear(); location.href = `${authBase()}/logout?${new URLSearchParams({ client_id: C.clientId, logout_uri: redirect() })}`; }
  function tokenValid(t) { try { const p = JSON.parse(atob(t.split(".")[1].replace(/-/g, "+").replace(/_/g, "/"))); return p.exp * 1000 > Date.now() + 60000; } catch { return false; } }

  // ---------- API ----------
  async function api(path, method = "GET", body) {
    const r = await fetch(C.apiUrl + path, { method, headers: { Authorization: "Bearer " + S.token, "Content-Type": "application/json" }, body: body !== undefined ? JSON.stringify(body) : undefined });
    const j = await r.json().catch(() => ({}));
    if (r.status === 401) { sessionStorage.clear(); location.reload(); }
    if (!r.ok) throw new Error(j.error || `エラー(${r.status})`);
    return j;
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
      const A = d.approvals || [], mineA = A.filter((a) => a.can);
      const need = (t) => `<span class="approve">${esc(t)}</span>`;
      // 手順(SRの流れ)。番号は、左の目次、SR委員の手順書と同じ。承認(確定)が必要な手順は 3・4(不一致のとき)、7、10
      const STEPS = [
        ["1", "CQ・PICO・アウトカムを確認する", "担当委員、SR委員長", "", "cq", "CQ・PICO・アウトカム"],
        ["2", "検索を実行し、検索の記録(データベース、検索日、検索者、検索期間、検索式、件数)を残す", "担当委員、事務局", "", "search", "検索の記録"],
        ["3", "一次スクリーニング(題名・抄録)の可否を、2名独立で入力する", "担当委員 2名", "不一致の文献は、担当委員の協議の結論", "screening", "スクリーニング"],
        ["4", "二次スクリーニング(全文)の可否を、2名独立で入力する。文献選択の流れ図を確認する", "担当委員 2名", "不一致の文献は、担当委員の協議の結論", "screening", "スクリーニング"],
        ["5", "採用した論文を登録する(PDF、本文の抽出、研究特性: がん腫・化学療法の分類)", "担当委員、SR委員長、事務局", "", "papers", "論文"],
        ["6", "様式4-5 を 2名独立で判定し、提出する(本文の Method・Result を根拠にする)", "担当委員 2名", "", "f45", "様式4-5"],
        ["7", "様式4-5 を照合し、確定する", "評価した 2名", "評価した2名(照合)、またはSR委員長", "f45", "様式4-5"],
        ["8", "様式SR-8 を記入する(確定した様式4-5 から。化学療法の分類で層別)", "担当委員、SR委員長", "", "sr8", "様式SR-8"],
        ["9", "EtD・推奨文案・解説を書く(状態を「協議中」にする)", "作成グループ", "", "etd", "EtD・推奨"],
        ["10", "推奨作成会議の投票を記録し、確定する", "作成グループ(記録)", "統括委員会(投票: 75%以上の参加、80%以上の一致)", "etd", "EtD・推奨"]];
      const srCards = !showSr ? "" : `
        <div class="card"><h3>作業手順(SRの流れ)</h3>
          <div class="scroll"><table><tr><th class="nw">手順</th><th>作業</th><th>行う人</th><th>承認(確定)</th><th>画面</th></tr>
          ${STEPS.map(([n, what, who, ap, page, label]) => `<tr><td class="num">${n}</td><td>${esc(what)}</td><td>${esc(who)}</td><td>${ap ? need("承認") + " " + esc(ap) : "承認なし"}</td><td class="nw"><a href="#${page}">${esc(label)}</a></td></tr>`).join("")}</table></div>
          <p class="note">手順の詳細は、左の「手順書」にある「SR委員の手順書」を参照。CQ・FRQ は、統括委員長が承認済み(企画書 Ver1)。Claude 下書きは出発点であり、判定は委員が行う。本文を抽出できない論文では下書きを作らない。</p></div>
        <div class="card"><h3>CQごとの記録</h3>
          <p class="note">記録された件数だけを示す。列の番号は作業手順の番号。「a / b」は、記録 a 件 / 必要 b 件(手順3・4 は 結果のある文献 / 対象の文献、手順5 は 本文抽出済 / 登録、手順7 は 確定 / 論文×アウトカム、手順8 は 確実性の記入 / アウトカム)。スクリーニングの結果は、2名の判定の一致、または協議の結論である。自分が担当の行は淡い青。${need("要承認")} は、確定の記録がない件。名称を押すと、その CQ の論文の画面を開く。</p>
          <div class="scroll"><table><tr><th>ID</th><th>名称</th><th>担当</th><th>手順1<br>アウトカム</th><th>手順2<br>検索の記録</th><th>手順3<br>一次</th><th>手順4<br>二次</th><th>採用</th><th>手順5<br>論文</th><th>手順6<br>様式4-5 提出</th><th>手順7<br>様式4-5 確定</th><th>手順8<br>様式SR-8</th><th>手順9・10<br>EtD・推奨</th></tr>
          ${d.cq.map((c) => { const n = c.counts, f = n.flow, nc = f.s1_conflict + f.s2_conflict; return `<tr class="${c.mine ? "mine" : ""}"><td class="nw">${esc(c.id)}</td><td><a href="${href("papers", { cq: c.id })}">${esc(c.title)}</a></td><td>${esc(c.assignees.join("・"))}</td>
            <td class="num">${n.outcomes}</td><td class="num"><a href="${href("search", { cq: c.id })}">${f.searches}</a></td>
            <td class="num">${f.s1_target - f.s1_open} / ${f.s1_target}</td><td class="num">${f.s2_target - f.s2_open} / ${f.s2_target}${nc ? ` <a href="${href("screening", { cq: c.id, show: "conflict" })}">${need("不一致 " + nc)}</a>` : ""}</td>
            <td class="num"><a href="${href("screening", { cq: c.id })}">${f.s2_include}</a></td><td class="num">${n.extracted} / ${n.papers}</td><td class="num">${n.f45_submitted}</td>
            <td class="num">${n.f45_fixed} / ${n.f45_need}${n.f45_wait ? ` <a href="${href("f45", { cq: c.id })}">${need("要承認 " + n.f45_wait)}</a>` : ""}</td>
            <td class="num">${n.sr8} / ${n.outcomes}</td>
            <td>${n.etd_status ? `<a href="${href("etd", { cq: c.id })}">${esc(n.etd_status)}</a>` : "記録なし"}${n.etd_agreement !== null && n.etd_agreement !== undefined ? ` 合意率 ${n.etd_agreement}%` : ""}${n.etd_status === "協議中" ? " " + need("要承認") : ""}</td></tr>`; }).join("")}</table></div></div>`;
      const soronCard = !showSoron ? "" : `
        <div class="card"><h3>総説の流れ(総論 A〜N)</h3>
          <ol class="steps"><li>執筆者が原稿(Word)を提出し、状態を「査読中」にする</li><li>統括委員会・事務局が査読コメントを書く(状態は「修正中」になる)</li><li>執筆者が修正版を提出する</li><li>${need("承認")} 統括委員会が「完了」にする</li></ol>
          <p>記録: ${Object.entries(d.soron_summary).map(([k, v]) => `${esc(k)} ${v} 件`).join("、")}</p>
          ${d.my_soron.length ? `<p>自分の担当: ${d.my_soron.map((x) => `<a href="#soron">総論${esc(x.label)} ${esc(x.title)}</a> ${tag(x.status)}`).join("、")}</p>` : ""}</div>`;
      m.innerHTML = `<h2>${showSr ? "SR進捗ボード" : "総説の進捗ボード"}</h2>
        <div class="card">現在の段階: <b>${esc(d.phase)}</b> ${isAdmin() ? `<span class="row">${sel(S.meta.phases, d.phase, 'id="phaseSel"')}<button id="phaseBtn">段階を変更</button></span>` : ""}</div>
        <div class="card"><h3>承認(確定)が必要な記録</h3>
          ${A.length ? `<p class="note need">${need("要承認")} 承認(確定)の記録がない件: <b>${d.approvals_count}</b> 件。うち自分が承認できる件: <b>${mineA.length}</b> 件。</p>
            <div class="scroll"><table><tr><th>種類</th><th>対象</th><th>記録</th><th>承認する人</th><th>操作</th></tr>
            ${A.map((a) => `<tr><td>${esc(a.kind)}</td><td>${esc(a.target)}</td><td>${esc(a.record)}</td><td>${esc(a.approver)}</td><td class="nw">${a.can ? `${need("承認できます")} <a href="${href(a.page, a.q)}">画面を開く</a>` : `<a href="${href(a.page, a.q)}">内容を見る</a>`}</td></tr>`).join("")}</table></div>`
            : '<p class="note">承認(確定)の記録がない件は、ありません。</p>'}</div>
        ${showSr ? `<div class="card"><h3>自分の作業(SRの流れ)</h3>${d.user.name ? "" : '<p class="note need">利用者の氏名が未登録のため、担当を抽出できません(事務局に依頼)。</p>'}
          <p>様式4-5 の未提出(担当 CQ の 論文×アウトカム): <b>${d.my_f45_todo_count}</b> 件${d.my_f45_todo_count > 10 ? "(先頭の 10 件を表示)" : ""}</p>
          <ul class="plain">${d.my_f45_todo.slice(0, 10).map((t) => `<li><a href="${href("f45", { cq: t.cq, pmid: t.pmid, outcome: t.outcome })}">${esc(t.cq)} PMID ${esc(t.pmid)} / ${esc(t.outcome)}</a></li>`).join("")}</ul>
          <p>担当 CQ: ${d.my_cq.length ? d.my_cq.map((c) => `<a href="${href("papers", { cq: c.id })}">${esc(c.id)} ${esc(c.title)}</a>`).join("、") : "なし"}</p></div>` : ""}
        ${srCards}${soronCard}
        <div class="card"><h3>作成経過の記録(最新20件)</h3><div class="scroll">${auditTable(d.audit)}</div></div>`;
      $("#phaseBtn")?.addEventListener("click", async () => { await api("/phase", "PUT", { phase: $("#phaseSel").value }); toast("段階を変更しました"); render(); });
    },

    async cq(m) {
      const list = await api("/cq"); S.cqs = list;
      m.innerHTML = `<h2>CQ・PICO・アウトカム</h2><p class="small">SR項目11・FRQ項目4(企画書)。アウトカムは、様式4-5・SR-8 の単位になる(1行に1つ)。PICO の P には、がん腫と化学療法の種類を書く。</p>
        ${list.map((c) => { const ed = own(c) || isLead();
          return `<div class="card" style="margin-bottom:12px" data-id="${esc(c.id)}"><h3>${esc(c.id)} ${esc(c.title)} <span class="tag">${esc(c.kind)}</span> <span class="small">${esc(c.category)}</span></h3>
            <div class="row small">${esc(c.approved || "")} / 担当: ${esc(c.assignees.join("・"))} / 作業フォルダ: ${esc(c.dirs.join(", "))}</div>
            <div class="row">${["P", "I", "C", "O"].map((k) => `<label class="small">${k} <input data-pico="${k}" value="${esc(c.pico[k])}" size="26" ${ed ? "" : "readonly"}></label>`).join("")}</div>
            <div class="row"><label class="small">アウトカム(1行1つ。様式4-5・様式SR-8の単位)<br><textarea data-outcomes rows="3" cols="50" ${ed ? "" : "readonly"}>${esc((c.outcomes || []).join("\n"))}</textarea></label>
              <label class="small">記録<br>${Object.entries(c.stages).map(([k, v]) => `${esc(k)}: ${esc(v)}<br>`).join("")}</label></div>
            <div class="row"><label class="small">備考 <input data-note value="${esc(c.note)}" size="60" ${ed ? "" : "readonly"}></label>${ed ? '<button data-act="save">保存</button>' : ""} <a href="#search?cq=${esc(c.id)}">検索の記録</a> <a href="#screening?cq=${esc(c.id)}">スクリーニング</a> <a href="#papers?cq=${esc(c.id)}">論文</a> <a href="#sr8?cq=${esc(c.id)}">SR-8</a> <a href="#etd?cq=${esc(c.id)}">EtD</a></div></div>`; }).join("")}`;
      m.querySelectorAll("button[data-act=save]").forEach((b) => b.addEventListener("click", async () => {
        const d = b.closest(".card"); const pico = {}; d.querySelectorAll("input[data-pico]").forEach((i) => (pico[i.dataset.pico] = i.value));
        try { await api("/cq/" + d.dataset.id, "PUT", { pico, outcomes: d.querySelector("[data-outcomes]").value.split("\n"), note: d.querySelector("[data-note]").value }); toast("保存しました"); render(); } catch (e) { toast(e.message, true); }
      }));
    },

    async papers(m) {
      const q = Q(); const cqid = q.cq || S.cqs[0]?.id; const c = S.cqs.find((x) => x.id === cqid);
      const list = await api("/papers/" + cqid); const ed = own(c) || isLead();
      m.innerHTML = `<h2>論文(PDF登録・本文)</h2><div class="row">CQ ${cqSelect(cqid, "cqSel")}</div>
        <p class="small">二次スクリーニングで採用した論文を PMID で登録し、PDF を置く。本文を抽出すると、Method・Result の段落に ID が付き、様式4-5 の根拠として引用できる。PDF は委員だけが閲覧できる。</p>
        ${ed ? `<div class="card"><div class="row"><input id="pmid" placeholder="PMID" size="10"><input id="ptitle" placeholder="題名(任意)" size="40"><input type="file" id="pdf" accept="application/pdf"><button id="regBtn" class="primary">登録してPDFを置く</button></div></div>` : ""}
        <table style="margin-top:12px"><tr><th>PMID</th><th>題名</th><th>状態</th><th>本文</th><th>がん腫</th><th>化学療法(分類 / 薬剤)</th><th>デザイン</th><th></th></tr>
        ${list.map((p) => `<tr data-pmid="${esc(p.pmid)}"><td><a href="https://pubmed.ncbi.nlm.nih.gov/${esc(p.pmid)}/" target="_blank" rel="noopener">${esc(p.pmid)}</a></td><td class="w">${esc(p.title)}</td><td>${tag(p.status, p.status.startsWith("本文抽出済") ? "ok" : "warn")}</td>
          <td class="small">${p.n_paragraphs ? `${p.pages}頁 ${p.n_paragraphs}段落(M ${p.sections?.methods ?? 0} / R ${p.sections?.results ?? 0})` : "—"}</td>
          <td>${esc(p.chars?.cancer || "")}</td><td>${esc(p.chars?.chemo_class || "")} ${p.chars?.chemo_drugs ? "/ " + esc(p.chars.chemo_drugs) : ""}</td><td>${esc(p.chars?.design || "")}</td>
          <td><button data-act="pdf">PDF</button> ${ed ? `<button data-act="extract">本文抽出</button> <button data-act="chars">研究特性</button>` : ""} <a href="#f45?cq=${esc(cqid)}&pmid=${esc(p.pmid)}">様式4-5</a></td></tr>`).join("") || "<tr><td colspan=8 class='muted'>登録なし</td></tr>"}</table>
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
      m.innerHTML = `<h2>様式4-5 個別研究評価シート(介入研究)</h2><div class="row">CQ ${cqSelect(cqid, "cqSel")} 論文 <select id="pmSel">${papers.map((p) => `<option value="${esc(p.pmid)}" ${p.pmid === pmid ? "selected" : ""}>${esc(p.pmid)} ${esc((p.title || "").slice(0, 40))}</option>`).join("")}</select>
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
      const nz = (v) => (v === null || v === undefined || v === "" ? "—" : esc(v));
      const hl = new Set(); (ai?.numbers?.evidence || []).forEach((e) => hl.add(e)); [mine, ai, fin, ...Object.values(d.others || {})].forEach((r) => Object.values(r?.items || {}).forEach((it) => (it.evidence || []).forEach((e) => hl.add(e))));
      const otherCols = Object.entries(d.others || {});
      $("#f45body").innerHTML = `<div class="split">
        <div class="card" id="paraBox"><h3>本文の該当箇所 <button id="pdfBtn">PDF</button></h3>${text ? paraPanel(text, [...hl]) : '<p class="muted">本文が未抽出です。論文の画面で PDF を登録し、本文を抽出してください。下書きは本文がなければ作りません。</p>'}</div>
        <div class="card"><h3>判定(0 / -1 / -2) ${mine.submitted ? tag("提出済み", "ok") : ""} ${fin ? tag("確定", "ok") : d.reconcile_open ? tag("照合中", "run") : ""}</h3>
          <ol class="steps"><li>自分の欄に、本文を読んで判定する(バイアスリスク10項目、非直接性5項目を 0 / -1 / -2)。根拠の段落 ID と引用を書く。記載がなければ -1 とし「記載なし」と書く</li>
            <li>「提出」を押す。相手の判定は、2名が提出するまで表示されない(2名独立)</li>
            <li><span class="approve">承認</span> 2名の提出後に確定欄が開く。照合し、「照合の結果を確定する」を押す。確定できるのは、評価した2名とSR委員長</li></ol>
          <p class="note">盲検化の2項目は -2 を使わない(統括委員長の決定)。${fin ? `確定の記録: ${esc(fin.fixed_by || "")}` : d.reconcile_open ? '<span class="approve">要承認</span> 2名が提出済。確定の記録がない。' : `提出済: ${d.submitted.length} 名(${esc(d.submitted.join("・")) || "なし"})`}</p>
          <div class="row">${ed && text ? `<button id="draftBtn">Claude下書きを作る(本文の段落を根拠に)</button>` : ""} ${ed && ai?.items ? `<button id="copyAi">下書き(判定・測定尺度・人数・効果)を自分の欄に取り込んで修正する</button>` : ""} ${ai ? `<span class="small">下書き: ${esc(ai.status || "")} ${ai.error ? esc(ai.error) : ""}</span>` : ""}</div>
          <table class="f45"><tr><th>項目</th>${ai?.items ? "<th>Claude下書き</th>" : ""}<th>自分(${esc(S.me.name || "—")})</th>${otherCols.map(([n]) => `<th>${esc(n)}</th>`).join("")}${d.reconcile_open || fin || isLead() ? "<th>確定(照合)</th>" : ""}</tr>
            ${K.map((k, i) => `<tr><td>${esc(JA[i])}</td>${ai?.items ? `<td>${cell(ai, k, false)}</td>` : ""}<td data-col="mine">${cell(mine, k, ed)}</td>${otherCols.map(([, r]) => `<td>${cell(r, k, false)}</td>`).join("")}
              ${d.reconcile_open || fin || isLead() ? `<td data-col="final">${cell(fin || mine, k, (d.reconcile_open && d.submitted.includes(S.me.name)) || isLead())}</td>` : ""}</tr>`).join("")}</table>
          ${ai?.items ? `<p class="note">Claude下書き(本文から): 測定尺度 <b>${esc(ai.study?.instrument || "記載なし")}</b>。対照 ${nz(ai.counts?.ctrl_num)} / ${nz(ai.counts?.ctrl_den)}、介入 ${nz(ai.counts?.int_num)} / ${nz(ai.counts?.int_den)}。効果 ${ai.effect?.measure && ai.effect.measure !== "null" ? `${esc(ai.effect.measure)} ${nz(ai.effect.value)} [${nz(ai.effect.ci_low)}, ${nz(ai.effect.ci_high)}]` : "記載なし"}。
            根拠 ${(ai.numbers?.evidence || []).map((e) => `<a href="#" data-para="${esc(e)}">${esc(e)}</a>`).join(" ") || "なし"} ${esc(ai.numbers?.quote || "")}</p>` : ""}
          <div class="row"><label class="small">測定尺度 <input id="instrument" value="${esc(mine.instrument || ai?.study?.instrument || "")}" size="24"></label>
            <label class="small">対照 分子/分母 <input id="cnum" value="${esc(mine.counts?.ctrl_num ?? "")}" size="4">/<input id="cden" value="${esc(mine.counts?.ctrl_den ?? "")}" size="4"></label>
            <label class="small">介入 分子/分母 <input id="inum" value="${esc(mine.counts?.int_num ?? "")}" size="4">/<input id="iden" value="${esc(mine.counts?.int_den ?? "")}" size="4"></label>
            <label class="small">効果 ${sel(["RR", "OR", "HR", "MD", "SMD"], mine.effect?.measure, 'id="emeas"', true)} <input id="eval" value="${esc(mine.effect?.value ?? "")}" size="6"> [<input id="elo" value="${esc(mine.effect?.ci_low ?? "")}" size="6">, <input id="ehi" value="${esc(mine.effect?.ci_high ?? "")}" size="6">]</label></div>
          <div class="row"><label class="small">備考 <input id="note45" value="${esc(mine.note || "")}" size="60"></label></div>
          <div class="row">${ed ? `<button id="save45">保存(下書き)</button> <button id="submit45" class="primary">提出(提出後は照合で変更)</button>` : ""} ${(d.reconcile_open && d.submitted.includes(S.me.name)) || isLead() ? `<button id="final45" class="approve">承認: 照合の結果を確定する</button>` : ""}</div>
          ${ai?.paragraphs_used ? `<p class="small">下書きの根拠: ${ai.paragraphs_used.length} 段落(Method・Result)。モデル ${esc(ai.model)}。下書きは出発点であり、判定は委員が行う。</p>` : ""}</div></div>`;
      if (text) wireParas($("#paraBox"));
      $("#pdfBtn")?.addEventListener("click", async () => { try { const r = await api(`/papers/${cqid}/${pmid}/pdf-url`); window.open(r.url, "_blank"); } catch (e) { toast(e.message, true); } });
      m.querySelectorAll("a[data-para]").forEach((a) => a.addEventListener("click", (ev) => { ev.preventDefault(); const el = m.querySelector(`.para[data-id="${a.dataset.para}"]`); if (el) { el.style.display = ""; el.scrollIntoView({ behavior: "smooth", block: "center" }); el.classList.add("flash"); } }));
      const collect = (col) => { const items = {}; K.forEach((k) => { const g = (f) => m.querySelector(`td[data-col="${col}"] [data-k="${k}"][data-f="${f}"]`); items[k] = { v: g("v")?.value === "" ? null : Number(g("v")?.value), evidence: (g("evidence")?.value || "").split(/[,\s]+/).filter(Boolean), quote: g("quote")?.value || "" }; });
        return { items, instrument: $("#instrument").value, counts: { ctrl_num: $("#cnum").value, ctrl_den: $("#cden").value, int_num: $("#inum").value, int_den: $("#iden").value }, effect: { measure: $("#emeas").value, value: $("#eval").value, ci_low: $("#elo").value, ci_high: $("#ehi").value }, note: $("#note45").value }; };
      const path = `/f45/${cqid}/${pmid}/${encodeURIComponent(outcome)}`;
      $("#save45")?.addEventListener("click", async () => { try { await api(path, "PUT", { ...collect("mine"), submitted: false }); toast("保存しました"); render(); } catch (e) { toast(e.message, true); } });
      $("#submit45")?.addEventListener("click", async () => { const b = collect("mine"); if (K.some((k) => b.items[k].v === null)) return toast("空欄の項目があります(非RCTでランダム化・コンシールメントが該当しない場合も、備考に書いて -1 にする)", true);
        try { await api(path, "PUT", { ...b, submitted: true }); toast("提出しました"); render(); } catch (e) { toast(e.message, true); } });
      $("#final45")?.addEventListener("click", async () => { try { await api(path + "/final", "PUT", collect("final")); toast("確定しました"); render(); } catch (e) { toast(e.message, true); } });
      $("#draftBtn")?.addEventListener("click", async () => { try { await api(path + "/draft", "POST", {}); toast("下書きを作成中です(1〜2分後に再読み込み)"); setTimeout(render, 60000); } catch (e) { toast(e.message, true); } });
      $("#copyAi")?.addEventListener("click", () => { K.forEach((k) => { const it = ai.items[k] || {}; const g = (f) => m.querySelector(`td[data-col="mine"] [data-k="${k}"][data-f="${f}"]`); if (g("v")) g("v").value = it.v === null ? "" : it.v; if (g("evidence")) g("evidence").value = (it.evidence || []).join(","); if (g("quote")) g("quote").value = it.quote || ""; });
        // 測定尺度・人数・効果も取り込む(下書きに値があるものだけ)
        const put = (id, v) => { if (v !== null && v !== undefined && v !== "" && v !== "null") $(id).value = v; };
        put("#instrument", ai.study?.instrument); put("#cnum", ai.counts?.ctrl_num); put("#cden", ai.counts?.ctrl_den); put("#inum", ai.counts?.int_num); put("#iden", ai.counts?.int_den);
        put("#emeas", ai.effect?.measure); put("#eval", ai.effect?.value); put("#elo", ai.effect?.ci_low); put("#ehi", ai.effect?.ci_high);
        toast("判定、測定尺度、人数、効果を取り込みました。本文で確認し、修正して提出してください"); });
    },

    async sr8(m) {
      const q = Q(); const cqid = q.cq || S.cqs[0]?.id; const c = S.cqs.find((x) => x.id === cqid); const d = await api("/sr8/" + cqid); const ed = own(c) || isLead();
      m.innerHTML = `<h2>様式SR-8 エビデンス総体評価シート</h2><div class="row">CQ ${cqSelect(cqid, "cqSel")}</div>
        <p class="small">アウトカムごとに、確定した様式4-5(照合後)を化学療法の分類(6区分)の層別行で示す。バイアスリスク・非一貫性・不精確性・非直接性・その他を 0 / -1 / -2、上昇要因を 0 / +1 / +2、エビデンスの確実性を A(強)〜D(非常に弱い)で評価する。SoF表は、この記入から作る。</p>
        ${d.outcomes.map((o) => { const r = o.sr8 || {}; return `<div class="card" style="margin-bottom:12px" data-o="${esc(o.outcome)}"><h3>${esc(o.outcome)} <span class="small">確定済み ${o.n_studies} 研究</span></h3>
          <table><tr><th>化学療法の分類</th><th>研究(PMID)</th><th>バイアスリスクまとめ</th><th>非直接性まとめ</th><th>効果</th></tr>
            ${Object.entries(o.by_chemo_class).map(([cls, rows]) => `<tr><td>${esc(cls)}</td><td>${rows.map((x) => esc(x.pmid)).join(", ")}</td><td>${rows.map((x) => x.bias_summary ?? "—").join(", ")}</td><td>${rows.map((x) => x.ind_summary ?? "—").join(", ")}</td><td class="small">${rows.map((x) => x.effect?.measure ? `${esc(x.effect.measure)} ${esc(x.effect.value)}` : "—").join("; ")}</td></tr>`).join("") || "<tr><td colspan=5 class='muted'>確定した様式4-5 がありません</td></tr>"}</table>
          <div class="row">${["rob", "inconsistency", "imprecision", "indirectness", "publication_bias"].map((k, i) => `<label class="small">${esc(S.meta.sr8_ja[i])} ${ed ? vsel(r[k], `data-k="${k}"`) : `<b>${r[k] ?? "—"}</b>`}</label>`).join("")}
            <label class="small">上昇要因 ${ed ? sel([0, 1, 2], r.upgrade ?? "", 'data-k="upgrade"', true) : `<b>${r.upgrade ?? "—"}</b>`}</label>
            <label class="small">確実性 ${ed ? sel(S.meta.cert, r.certainty, 'data-k="certainty"', true) : `<b>${esc(r.certainty || "—")}</b>`}</label></div>
          <div class="row"><label class="small">層別(分類ごとの結論) <input data-k="strata" value="${esc(r.strata || "")}" size="40" ${ed ? "" : "readonly"}></label><label class="small">効果の要約 <input data-k="effect_summary" value="${esc(r.effect_summary || "")}" size="40" ${ed ? "" : "readonly"}></label><label class="small">備考 <input data-k="note" value="${esc(r.note || "")}" size="30" ${ed ? "" : "readonly"}></label>${ed ? '<button data-act="save">保存</button>' : ""}</div></div>`; }).join("") || '<p class="muted">アウトカムが未登録です。</p>'}`;
      $("#cqSel").addEventListener("change", () => go("sr8", { cq: $("#cqSel").value }));
      m.querySelectorAll("button[data-act=save]").forEach((b) => b.addEventListener("click", async () => { const d2 = b.closest(".card"); const body = {}; d2.querySelectorAll("[data-k]").forEach((i) => (body[i.dataset.k] = i.value));
        try { await api(`/sr8/${cqid}/${encodeURIComponent(d2.dataset.o)}`, "PUT", body); toast("保存しました"); render(); } catch (e) { toast(e.message, true); } }));
    },

    async etd(m) {
      const q = Q(); const cqid = q.cq || S.cqs[0]?.id; const d = await api("/etd/" + cqid); const e = d.etd; const g = d.gl2023; const ed = isGroup();
      const cons = S.meta.etd_considerations;
      m.innerHTML = `<h2>EtD・推奨(2023年版の体裁)</h2><div class="row">CQ ${cqSelect(cqid, "cqSel")} ${tag(e.status)}</div>
        <ol class="steps"><li>左の 2023年版の記述(推奨文・推奨の強さ・エビデンスの確実性・解説・投票)と、様式SR-8 の確実性を確認する</li>
          <li>右に 2028年版の案を書く。推奨文には、適用するがん腫・化学療法の分類を明記する。4つの考慮事項には、根拠(論文の段落 ID、2023年版の段落 ID)を書く</li>
          <li>状態を「協議中」にして保存する</li>
          <li>推奨作成会議の投票を記録する(投票権のある委員の75%以上が参加、80%以上の一致で決定、最大3回。投票除外(直接評価した論文の筆頭著者、そのCQのSR担当者)は分母から除く)</li>
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
            <h3 style="margin-top:12px">投票の記録</h3>
            <div class="row"><label class="small">回 <input id="vround" value="${esc(e.vote?.round ?? 1)}" size="2"></label><label class="small">日付 <input id="vdate" type="date" value="${esc(e.vote?.date || "")}"></label>
              ${[1, 2, 3, 4, 5].map((i) => `<label class="small">${i} <input data-v="${i - 1}" value="${esc(e.vote?.counts?.[i - 1] ?? "")}" size="2"></label>`).join("")}
              <label class="small">分母 <input id="vden" value="${esc(e.vote?.denominator ?? "")}" size="3"></label><label class="small">投票除外(筆頭著者) <input id="vcoi" value="${esc(e.vote?.coi_excluded ?? "")}" size="2"></label><label class="small">投票除外(SR担当) <input id="vsr" value="${esc(e.vote?.sr_excluded ?? "")}" size="2"></label>
              ${e.vote?.agreement !== undefined && e.vote?.agreement !== null ? `<b>合意率 ${e.vote.agreement}%</b>` : ""}</div>
            <label class="small">解説(推奨の理由。根拠の段落ID付き)<br><textarea id="narr" rows="6" cols="60" ${ed ? "" : "readonly"}>${esc(e.narrative || "")}</textarea></label>
            <p class="note ${e.status === "協議中" ? "need" : ""}"><span class="approve">承認</span> 確定は、投票の記録のあとに統括委員会が行う。${e.status === "協議中" ? "状態は協議中。確定の記録がない。" : e.status === "確定" ? "確定の記録あり。" : "作成グループが書き終えたら、状態を「協議中」にして保存する。"}</p>
            <div class="row">${ed ? `<button id="etdSave" class="primary">保存</button> 状態 ${sel(["下書き", "協議中"].concat(e.status === "確定" ? ["確定"] : []), e.status, 'id="etdStatus"')} ${can("統括委員会") && e.status !== "確定" ? '<button id="etdFix" class="approve">承認: 確定する(統括委員会)</button>' : ""} <button id="etdDraft">Claude下書きを作る(SR-8・様式4-5・2023年版を根拠に)</button>` : ""} <button id="exportBtn">Minds書類(xlsx)を出力</button></div>
            ${e.ai_draft ? `<div class="card" style="margin-top:10px"><h3>Claude下書き <span class="small">${esc(e.ai_draft.status || "")} ${esc((e.ai_draft.at || "").slice(0, 16))} ${e.ai_draft.error ? esc(e.ai_draft.error) : ""}</span></h3>
              ${e.ai_draft.rec_draft ? `<p><b>推奨文案</b> ${esc(e.ai_draft.rec_draft)}</p>${cons.map(([k, ja]) => `<p><b>${esc(ja)}</b> ${esc(e.ai_draft.considerations?.[k]?.text || "")} <span class="small">${esc((e.ai_draft.considerations?.[k]?.evidence || []).join(", "))}</span></p>`).join("")}<p><b>解説文案</b><br>${esc(e.ai_draft.narrative || "").replace(/\n/g, "<br>")}</p><p class="small">2023年版からの変更点: ${esc(e.ai_draft.changes_from_2023 || "")}</p>
              ${ed ? '<button id="etdCopy">下書きを右の欄に取り込んで修正する</button>' : ""}<p class="small">根拠のIDは、SR8-アウトカム、F45-PMID-アウトカム、GL2023-段落。推奨の強さと確実性は、下書きに含めない(投票と様式SR-8で決める)。</p>` : ""}</div>` : ""}</div></div>`;
      $("#cqSel").addEventListener("change", () => go("etd", { cq: $("#cqSel").value }));
      $("#etdDraft")?.addEventListener("click", async () => { try { await api("/etd/" + cqid + "/draft", "POST", {}); toast("下書きを作成中です(1〜2分後に再読み込み)"); setTimeout(render, 60000); } catch (e2) { toast(e2.message, true); } });
      $("#exportBtn")?.addEventListener("click", async () => { try { const r = await api("/export/" + cqid); toast(`出力しました(${r.sheets.join("・")})`); if (r.url) window.open(r.url, "_blank"); } catch (e2) { toast(e2.message, true); } });
      $("#etdCopy")?.addEventListener("click", () => { const a = e.ai_draft; $("#rec").value = a.rec_draft || ""; cons.forEach(([k]) => { m.querySelector(`[data-ck="${k}"][data-f="text"]`).value = a.considerations?.[k]?.text || ""; m.querySelector(`[data-ck="${k}"][data-f="evidence"]`).value = (a.considerations?.[k]?.evidence || []).join(","); }); $("#narr").value = a.narrative || ""; toast("取り込みました。確認・修正して保存してください"); });
      const saveEtd = async (status) => { const considerations = {}; cons.forEach(([k]) => (considerations[k] = { text: m.querySelector(`[data-ck="${k}"][data-f="text"]`).value, evidence: m.querySelector(`[data-ck="${k}"][data-f="evidence"]`).value.split(/[,\s]+/).filter(Boolean) }));
        const counts = [0, 1, 2, 3, 4].map((i) => m.querySelector(`[data-v="${i}"]`).value);
        try { await api("/etd/" + cqid, "PUT", { rec_draft: $("#rec").value, strength: $("#strength")?.value, certainty: $("#cert")?.value, scope_note: $("#scope").value, considerations, narrative: $("#narr").value, status: status || $("#etdStatus").value,
          vote: { round: $("#vround").value, date: $("#vdate").value, counts, denominator: $("#vden").value, coi_excluded: $("#vcoi").value, sr_excluded: $("#vsr").value } }); toast(status ? "確定しました" : "保存しました"); render(); } catch (e2) { toast(e2.message, true); } };
      $("#etdSave")?.addEventListener("click", () => saveEtd());
      $("#etdFix")?.addEventListener("click", () => { if (confirm("この CQ の EtD・推奨を確定しますか(統括委員会の承認として記録されます)")) saveEtd("確定"); });
    },

    async soron(m) {
      const list = await api("/soron"); const admin = isAdmin();
      const mineOnly = !admin && !isLead();
      const rows = list.filter((s) => !mineOnly || (S.me.name && s.author.split("・").some((a) => a && S.me.name.startsWith(a))));
      m.innerHTML = `<h2>総説の流れ: 総論(A〜N)の執筆・査読</h2>
        <ol class="steps"><li>執筆者が、各行の「依頼書・2023年版」から依頼書(Word。2023年版の全文入り)を開く</li><li>執筆者が、依頼書を直接修正した原稿(Word)をこの画面で提出し、状態を「査読中」にして保存する</li><li>統括委員会・事務局が査読コメントを書く(状態は「修正中」になる)</li><li>執筆者が修正版を提出する</li><li><span class="approve">承認</span> 統括委員会が「完了」にする</li></ol>
        <p class="note">企画書の総論18項目と担当。原稿は版ごとに保存される。SRの流れ(CQ)とは独立している。</p>
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
      m.innerHTML = `<h2>検索の記録</h2><div class="row">CQ ${cqSelect(cqid, "cqSel")}</div>
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
        return `<td class="w">${d.reviewer ? `<div>自分: ${sel(opts, cur.decision || "", `data-dec="${st}"`, true)} <select class="sm${cur.decision === "除外" ? "" : " hidden"}" data-reason="${st}"><option value="">(除外理由)</option>${d.reasons.map((o) => `<option ${o === cur.reason ? "selected" : ""}>${esc(o)}</option>`).join("")}</select></div>` : ""}
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
        <ol class="steps"><li>検索結果(「検索の記録」の件数の文献)と、その他の情報源の文献を、スクリーニングの対象に取り込む</li><li>担当委員 2名が、一次(題名・抄録)の可否を、相手の判定を見ずに入力する。除外には理由を選ぶ</li>
          <li>一次の結果が採用・保留の文献について、全文を読み、二次の可否を入力する</li><li>${need("承認")} 2名の判定が不一致の文献は、協議して「協議の結論」を記録する(担当委員。決まらない場合は SR委員長)</li><li>採用した文献を、「論文」の画面に登録する</li></ol>
        <p class="note">相手の判定は、自分がその文献のその段階を判定した後に表示される(2名独立)。2名の判定がそろった後は、自分の判定を変更できない。結果は、2名の判定の一致、または協議の結論である。</p>
        <div class="card"><h3>文献選択の流れ図</h3>${flowHtml}
          <p class="note">件数は、検索の記録とスクリーニングの記録から数えた値である(この画面を開いた時点)。判定を入力した後の件数は、「件数を数え直す」で更新する。別添は、流れ図の枠ごとの文献の一覧(PMID・題名・著者)であり、件数と一覧の行数が一致する。</p>
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
            <div class="row"><label>結論 ${sel(st === "s1" ? ["採用", "除外", "保留"] : ["採用", "除外"], "", 'id="fDec"', true)}</label><label>除外理由 ${sel(d.reasons, "", 'id="fReason"', true)}</label><label>協議の内容(結論の理由) <input id="fWhy" size="50"></label>
              <button id="fBtn" class="approve">承認: 協議の結論を記録する</button></div></div>`;
          $("#finalBox").scrollIntoView({ behavior: "smooth" });
          $("#fBtn").addEventListener("click", async () => { try { const r = await api(`/screening/${cqid}/${p.pmid}/final`, "PUT", { stage: st, decision: $("#fDec").value, reason: $("#fReason").value, why: $("#fWhy").value });
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

    async users(m) {
      const list = await api("/users"); const ed = isAdmin();
      m.innerHTML = `<h2>利用者(ログイン)</h2><p class="small">ログイン用の登録だけを行う。名簿と COI は Google フォーム・ドライブで管理する。氏名は企画書の表記(例: 華井明子)と一致させる。担当 CQ・総論の抽出に使う。</p>
        ${ed ? `<div class="card"><div class="row"><input id="uEmail" placeholder="メールアドレス" size="28"><input id="uName" placeholder="氏名" size="12">${S.meta.groups.map((g) => `<label class="tag"><input type="checkbox" class="uRole" value="${esc(g)}"> ${esc(g)}</label>`).join("")}<button id="uAdd" class="primary">登録して招待</button></div>
          <div class="row"><button id="seedBtn">初期データの作成(企画書の CQ・総論。既にある項目は変えない)</button></div></div>` : ""}
        <table style="margin-top:12px"><tr><th>氏名</th><th>メールアドレス</th><th>役割</th>${ed ? "<th></th>" : ""}</tr>${list.map((u) => `<tr><td>${esc(u.name)}</td><td>${esc(u.email)}</td><td>${(u.roles || []).map((r) => tag(r, "")).join("")}</td>${ed ? `<td><button data-del="${esc(u.email)}">削除</button></td>` : ""}</tr>`).join("")}</table>`;
      $("#uAdd")?.addEventListener("click", async () => { const roles = [...m.querySelectorAll(".uRole:checked")].map((c) => c.value);
        try { const r = await api("/users", "POST", { email: $("#uEmail").value, name: $("#uName").value, roles, invite: true }); toast(r.invited ? "招待メールを送りました" : "登録しました"); render(); } catch (e) { toast(e.message, true); } });
      $("#seedBtn")?.addEventListener("click", async () => { try { const r = await api("/admin/seed", "POST", {}); toast(`${r.created}件を作成しました`); S.cqs = await api("/cq"); render(); } catch (e) { toast(e.message, true); } });
      m.querySelectorAll("button[data-del]").forEach((b) => b.addEventListener("click", async () => { if (!confirm(`${b.dataset.del} を削除しますか`)) return; try { await api("/users/" + encodeURIComponent(b.dataset.del), "DELETE"); toast("削除しました"); render(); } catch (e) { toast(e.message, true); } }));
    },

    async docs(m) {
      const list = await api("/docs");
      m.innerHTML = `<h2>手順書</h2><p class="note">自分の役割に必要な手順書を、ここから開きます。総論の依頼書(2023年版の全文)は、「総論の執筆・査読」の画面の各行にあります。</p>
        <table><tr><th>手順書</th><th>対象</th><th>更新日</th><th>操作</th></tr>
        ${list.map((d) => `<tr><td>${esc(d.name.replace(/\.docx$/, ""))}</td><td>${esc(d.target)}</td><td class="nw">${esc(d.updated)}</td><td class="nw"><a href="${esc(d.url)}" target="_blank" rel="noopener">Word を開く</a></td></tr>`).join("") || '<tr><td colspan="4" class="muted">登録された手順書はありません(事務局が登録します)</td></tr>'}</table>`;
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

  async function boot() {
    const code = new URLSearchParams(location.search).get("code");
    if (code) { try { await exchange(code); } catch (e) { toast(e.message, true); } }
    const t = sessionStorage.getItem("id_token");
    if (!t || !tokenValid(t)) { $("#login").classList.remove("hidden"); $("#loginBtn").addEventListener("click", login); return; }
    S.token = t;
    try { S.me = await api("/me"); S.meta = await api("/meta"); } catch (e) { $("#login").classList.remove("hidden"); $("#loginBtn").addEventListener("click", login); return toast(e.message, true); }
    $("#meName").textContent = S.me.name || S.me.email; $("#meGroups").textContent = S.me.groups.join("・") || "(グループ未設定)";
    $("#logoutBtn").addEventListener("click", logout);
    // 表示する流れ: SR(担当委員・SR委員長・作成グループ・統括・事務局)、総説(総説執筆者・統括・事務局)、事務局(統括・事務局)
    const showSr = can("統括委員会", "事務局", "SR委員長", "SR委員", "作成グループ"), showSoron = can("統括委員会", "事務局", "総説執筆者"), showAdmin = isAdmin();
    document.querySelector('.navsec[data-flow="sr"]').classList.toggle("hidden", !showSr);
    document.querySelector('.navsec[data-flow="soron"]').classList.toggle("hidden", !showSoron);
    document.querySelector('.navsec[data-flow="admin"]').classList.toggle("hidden", !showAdmin);
    $("#app").classList.remove("hidden");
    window.addEventListener("hashchange", render); render();
  }
  boot();
})();
