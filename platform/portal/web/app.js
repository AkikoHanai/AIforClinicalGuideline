/* GL作成ポータルの画面。Cognito(認可コード + PKCE)でログインし、API を呼ぶ。判断は委員が行い、画面は記録と集計を表示する。 */
(function () {
  const C = window.PORTAL_CONFIG || {};
  const $ = (s) => document.querySelector(s);
  const esc = (s) => String(s ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
  const S = { token: null, me: null, meta: null, members: [] };

  // ---------- ログイン ----------
  const authBase = () => `https://${C.domain}.auth.${C.region}.amazoncognito.com`;
  const redirect = () => location.origin + "/";
  function b64url(buf) { return btoa(String.fromCharCode(...new Uint8Array(buf))).replace(/\+/g, "-").replace(/\//g, "_").replace(/=+$/, ""); }
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
    const t = await r.json();
    sessionStorage.setItem("id_token", t.id_token);
    history.replaceState({}, "", redirect() + (location.hash || "#dashboard"));
  }
  function logout() {
    sessionStorage.clear();
    const q = new URLSearchParams({ client_id: C.clientId, logout_uri: redirect() });
    location.href = `${authBase()}/logout?${q}`;
  }
  function tokenValid(t) {
    try { const p = JSON.parse(atob(t.split(".")[1].replace(/-/g, "+").replace(/_/g, "/"))); return p.exp * 1000 > Date.now() + 60000; } catch { return false; }
  }

  // ---------- API ----------
  async function api(path, method = "GET", body) {
    const r = await fetch(C.apiUrl + path, { method, headers: { Authorization: "Bearer " + S.token, "Content-Type": "application/json" }, body: body ? JSON.stringify(body) : undefined });
    const j = await r.json().catch(() => ({}));
    if (r.status === 401) { sessionStorage.clear(); location.reload(); }
    if (!r.ok) throw new Error(j.error || `エラー(${r.status})`);
    return j;
  }
  function toast(msg, bad) { const t = $("#toast"); t.textContent = msg; t.className = "toast" + (bad ? " bad" : ""); setTimeout(() => t.classList.add("hidden"), 3500); }
  const can = (...gs) => S.me && S.me.groups.some((g) => gs.includes(g));
  const isAdmin = () => can("統括委員会", "事務局");
  const isLead = () => can("統括委員会", "事務局", "SR委員長");
  const stateTag = (v) => `<span class="tag ${v === "完了" ? "ok" : v === "進行中" || v === "執筆中" || v === "査読中" ? "run" : ""}">${esc(v)}</span>`;
  const sel = (opts, cur, attrs = "") => `<select class="sm" ${attrs}>${opts.map((o) => `<option ${o === cur ? "selected" : ""}>${esc(o)}</option>`).join("")}</select>`;
  const names = () => S.members.map((m) => m.name);

  // ---------- 画面 ----------
  const pages = {
    async dashboard(m) {
      const d = await api("/dashboard");
      const cqRows = d.cq.map((c) => `<tr><td>${esc(c.id)}</td><td>${esc(c.title)}</td><td>${esc(c.assignees.join("・"))}</td><td><span class="bar"><i style="width:${c.progress}%"></i></span> ${c.progress}%</td><td>${Object.entries(c.stages).filter(([, v]) => v === "進行中").map(([k]) => esc(k)).join("、") || "—"}</td></tr>`).join("");
      m.innerHTML = `<h2>ダッシュボード</h2>
        <div class="card phase">現在の段階: <b>${esc(d.phase)}</b> ${isAdmin() ? `<span class="row">${sel(S.meta.phases, d.phase, 'id="phaseSel"')}<button id="phaseBtn">変更</button></span>` : ""}</div>
        <div class="grid">
          <div class="card"><h3>自分のタスク</h3>${d.user.name ? "" : '<p class="small">名簿のメールアドレスと一致しないため、担当の抽出ができません。メンバー管理でメールアドレスを登録してください。</p>'}
            <ul class="plain">${d.my_tasks.map((t) => `<li>${esc(t.title)} <span class="small">${esc(t.due || "")} ${stateTag(t.status)}</span></li>`).join("") || "<li class='muted'>なし</li>"}</ul>
            ${d.my_cq.length ? `<h3>担当CQ</h3><ul class="plain">${d.my_cq.map((c) => `<li>${esc(c.id)} ${esc(c.title)} <span class="small">${c.progress}%</span></li>`).join("")}</ul>` : ""}
            ${d.my_soron.length ? `<h3>担当の総論</h3><ul class="plain">${d.my_soron.map((s) => `<li>${esc(s.label)} ${esc(s.title)} ${stateTag(s.status)}</li>`).join("")}</ul>` : ""}</div>
          <div class="card"><h3>承認リクエスト(申請中 ${d.pending_approvals.length}件)</h3>
            <ul class="plain">${d.pending_approvals.slice(0, 6).map((a) => `<li>${esc(a.subject)} <span class="small">${esc(a.requester)}</span></li>`).join("") || "<li class='muted'>なし</li>"}</ul>
            <div class="row"><a href="#approvals">承認リクエスト一覧へ</a></div></div>
          <div class="card"><h3>総論の執筆状況</h3>${Object.entries(d.soron_summary).map(([k, v]) => `${stateTag(k)} ${v}件 `).join("")}<div class="row"><a href="#soron">総論一覧へ</a></div></div>
        </div>
        <div class="card"><h3>CQごとの進捗</h3><table><tr><th>ID</th><th>名称</th><th>担当</th><th>進捗</th><th>進行中の段階</th></tr>${cqRows}</table></div>
        <div class="card" style="margin-top:14px"><h3>承認ログ(最新20件)</h3>${auditTable(d.audit)}</div>`;
      $("#phaseBtn")?.addEventListener("click", async () => { await api("/phase", "PUT", { phase: $("#phaseSel").value }); toast("段階を変更しました"); render(); });
    },

    async members(m) {
      const list = await api("/members"); S.members = list;
      const ed = isAdmin();
      m.innerHTML = `<h2>メンバー管理</h2><p class="small">名簿は企画書(Ver1 2026-06-17)の体制です。COI の申告は学会が管理するため、ここには置きません。メールアドレスを登録し「招待」を押すと、Cognito から招待メールが送られます。</p>
        <table><tr><th>氏名</th><th>役割(グループ)</th><th>メールアドレス</th><th>備考</th>${ed ? "<th></th>" : ""}</tr>
        ${list.map((x, i) => `<tr data-i="${i}"><td>${esc(x.name)}</td><td>${ed ? S.meta.groups.map((g) => `<label class="tag"><input type="checkbox" value="${esc(g)}" ${x.roles.includes(g) ? "checked" : ""}> ${esc(g)}</label>`).join("") : x.roles.map((r) => `<span class="tag">${esc(r)}</span>`).join("")}</td>
          <td>${ed ? `<input value="${esc(x.email)}" placeholder="example@..." size="28">` : esc(x.email)}</td><td>${ed ? `<input value="${esc(x.note)}" size="16">` : esc(x.note)}</td>
          ${ed ? `<td><button data-act="save">保存</button> <button data-act="invite" class="primary">招待</button></td>` : ""}</tr>`).join("")}</table>
        ${ed ? `<div class="row"><button id="seedBtn">初期データの作成(企画書の名簿・CQ・総論。既にある項目は変えない)</button></div>` : ""}`;
      $("#seedBtn")?.addEventListener("click", async () => { try { const r = await api("/admin/seed", "POST", {}); toast(`${r.created}件を作成しました`); render(); } catch (e) { toast(e.message, true); } });
      m.querySelectorAll("button[data-act]").forEach((b) => b.addEventListener("click", async () => {
        const tr = b.closest("tr"); const x = list[+tr.dataset.i];
        const roles = [...tr.querySelectorAll("input[type=checkbox]:checked")].map((c) => c.value);
        const [email, note] = [...tr.querySelectorAll("input[type=text], input:not([type])")].map((i) => i.value);
        try { const r = await api("/members", "PUT", { name: x.name, roles, email, note, invite: b.dataset.act === "invite" }); toast(r.invited ? `${x.name} に招待メールを送りました` : "保存しました"); } catch (e) { toast(e.message, true); }
      }));
    },

    async cq(m) {
      const list = await api("/cq");
      m.innerHTML = `<h2>CQ・PICO一覧</h2><p class="small">SR項目11・FRQ項目4(企画書)。段階の状態は、担当委員・SR委員長・統括委員会・事務局が更新できます。</p>
        ${list.map((c) => {
          const own = S.me.name && c.assignees.some((a) => S.me.name.startsWith(a)); const ed = own || isLead();
          return `<div class="card" style="margin-bottom:12px" data-id="${esc(c.id)}"><h3>${esc(c.id)} ${esc(c.title)} <span class="tag">${esc(c.kind)}</span> <span class="small">${esc(c.category)}</span></h3>
            <div class="row"><span class="small">担当: ${esc(c.assignees.join("・"))} / 作業フォルダ: ${esc(c.dirs.join(", "))}</span> <span class="bar"><i style="width:${c.progress}%"></i></span> ${c.progress}%</div>
            <div class="row">${S.meta.stages.map((s) => `<span class="small">${esc(s)}</span>${ed ? sel(S.meta.stage_states, c.stages[s], `data-stage="${esc(s)}"`) : stateTag(c.stages[s])}`).join(" ")}</div>
            <div class="row">${["P", "I", "C", "O"].map((k) => `<label class="small">${k} <input data-pico="${k}" value="${esc(c.pico[k])}" size="22" ${ed ? "" : "readonly"}></label>`).join("")}</div>
            <div class="row"><label class="small">備考 <input data-note value="${esc(c.note)}" size="60" ${ed ? "" : "readonly"}></label>${ed ? '<button data-act="save">保存</button>' : ""}</div></div>`;
        }).join("")}`;
      m.querySelectorAll("button[data-act=save]").forEach((b) => b.addEventListener("click", async () => {
        const d = b.closest(".card"); const stages = {}; d.querySelectorAll("select[data-stage]").forEach((s) => (stages[s.dataset.stage] = s.value));
        const pico = {}; d.querySelectorAll("input[data-pico]").forEach((i) => (pico[i.dataset.pico] = i.value));
        try { await api("/cq/" + d.dataset.id, "PUT", { stages, pico, note: d.querySelector("input[data-note]").value }); toast("保存しました"); render(); } catch (e) { toast(e.message, true); }
      }));
    },

    async soron(m) {
      const list = await api("/soron");
      m.innerHTML = `<h2>総論(A〜N)</h2><p class="small">企画書の総論18項目と担当。執筆者本人・SR委員長・統括委員会・事務局が状態を更新できます。原稿は Google ドライブ JASCC_GL の URL を記録します。</p>
        <table><tr><th>項目</th><th>題名</th><th>担当</th><th>状態</th><th>期限</th><th>原稿(URL)</th><th>備考</th><th></th></tr>
        ${list.map((s) => { const own = S.me.name && s.author.split("・").some((a) => a && S.me.name.startsWith(a)); const ed = own || isLead();
          return `<tr data-key="${esc(s.key)}"><td>${esc(s.label)}</td><td>${esc(s.title)}</td><td>${esc(s.author)}</td><td>${ed ? sel(S.meta.soron_states, s.status, "data-status") : stateTag(s.status)}</td>
            <td>${ed ? `<input type="date" data-due value="${esc(s.due)}">` : esc(s.due)}</td><td>${ed ? `<input data-url value="${esc(s.draft_url)}" size="24">` : s.draft_url ? `<a href="${esc(s.draft_url)}" target="_blank" rel="noopener">原稿</a>` : ""}</td>
            <td>${ed ? `<input data-note value="${esc(s.note)}" size="18">` : esc(s.note)}</td><td>${ed ? '<button data-act="save">保存</button>' : ""}</td></tr>`; }).join("")}</table>`;
      m.querySelectorAll("button[data-act=save]").forEach((b) => b.addEventListener("click", async () => {
        const tr = b.closest("tr");
        try { await api("/soron/" + tr.dataset.key, "PUT", { status: tr.querySelector("[data-status]").value, due: tr.querySelector("[data-due]").value, draft_url: tr.querySelector("[data-url]").value, note: tr.querySelector("[data-note]").value }); toast("保存しました"); } catch (e) { toast(e.message, true); }
      }));
    },

    async screening(m) {
      const prog = await api("/screening"); const cqs = await api("/cq");
      m.innerHTML = `<h2>SR作業(スクリーニング)</h2><p class="small">スクリーニング管理シート(各CQの HTML)で「JSONを書き出す」を押して保存したファイルを、ここに取り込みます。判定は変えません。担当者ごとの進捗を表示し、照合(merge_screening.py)用に同じ JSON を返します。</p>
        <div class="card"><div class="row"><label>CQ ${`<select id="scrCq">${cqs.flatMap((c) => c.dirs).map((d) => `<option>${esc(d)}</option>`).join("")}</select>`}</label><input type="file" id="scrFile" accept=".json"><button id="scrUp" class="primary">取り込む</button></div></div>
        ${Object.keys(prog).length ? Object.entries(prog).sort().map(([cq, rs]) => `<div class="card" style="margin-top:12px"><h3>${esc(cq)}</h3><table><tr><th>担当</th><th>保存日時</th><th>文献</th><th>一次 判定済/未</th><th>二次 判定済/未</th><th>全文 未入手</th><th>全文 読了</th><th>除外で理由未記入</th><th></th></tr>
          ${rs.map((r) => `<tr><td>${esc(r.reviewer)}</td><td>${esc((r.saved_at || "").slice(0, 16))}</td><td>${r.papers}</td><td>${r.s1_done} / ${r.s1_todo}</td><td>${r.s2_done} / ${r.s2_todo}</td><td>${r.ft_missing}</td><td>${r.ft_read}</td><td>${r.no_reason ? `<span class="tag warn">${r.no_reason}</span>` : 0}</td><td><button data-raw="${esc(r.sk)}">JSON</button></td></tr>`).join("")}</table></div>`).join("") : '<p class="muted" style="margin-top:12px">取り込み済みの JSON はありません。</p>'}`;
      $("#scrUp").addEventListener("click", async () => {
        const f = $("#scrFile").files[0]; if (!f) return toast("JSON ファイルを選んでください", true);
        try { const d = JSON.parse(await f.text()); const r = await api("/screening/" + encodeURIComponent($("#scrCq").value), "POST", d); toast(`取り込みました(${r.reviewer}: 文献${r.papers}件)`); render(); } catch (e) { toast(e.message, true); }
      });
      m.querySelectorAll("button[data-raw]").forEach((b) => b.addEventListener("click", async () => {
        const d = await api("/screening/raw/" + encodeURIComponent(b.dataset.raw)); const a = document.createElement("a");
        a.href = URL.createObjectURL(new Blob([JSON.stringify(d, null, 1)], { type: "application/json" })); a.download = b.dataset.raw.replace("#", "_") + ".screening.json"; a.click();
      }));
    },

    async decision(m) {
      const cqs = await api("/cq");
      m.innerHTML = `<h2>推奨決定・原稿執筆</h2><p class="small">推奨の決定は推奨作成会議(決定記録シート)で行い、その結果の段階をここに反映します。EtD と解説文の状態は CQ・PICO一覧の段階と同じです。</p>
        <table><tr><th>ID</th><th>名称</th><th>様式4-5</th><th>様式SR-8・SoF</th><th>EtD</th><th>解説文</th></tr>
        ${cqs.map((c) => `<tr><td>${esc(c.id)}</td><td>${esc(c.title)}</td>${["様式4-5", "様式SR-8・SoF", "EtD", "解説文"].map((s) => `<td>${stateTag(c.stages[s])}</td>`).join("")}</tr>`).join("")}</table>`;
    },

    async tasks(m) {
      const list = await api("/tasks"); if (!S.members.length) S.members = await api("/members");
      const lead = isLead();
      m.innerHTML = `<h2>依頼事項</h2>
        ${lead ? `<div class="card"><div class="row"><input id="tTitle" placeholder="内容" size="40"><select id="tAssignee"><option value="">(担当)</option>${names().map((n) => `<option>${esc(n)}</option>`).join("")}</select><input id="tRef" placeholder="CQ/総論" size="10"><input type="date" id="tDue"><button id="tAdd" class="primary">追加</button></div></div>` : ""}
        <table style="margin-top:12px"><tr><th>内容</th><th>担当</th><th>対象</th><th>期限</th><th>状態</th><th>作成者</th></tr>
        ${list.map((t) => { const ed = lead || t.assignee === S.me.name; return `<tr data-id="${esc(t.id)}"><td>${esc(t.title)}</td><td>${esc(t.assignee)}</td><td>${esc(t.ref)}</td><td>${esc(t.due)}</td><td>${ed ? sel(S.meta.task_states, t.status, "data-status") : stateTag(t.status)}</td><td class="small">${esc(t.created_by)}</td></tr>`; }).join("")}</table>`;
      $("#tAdd")?.addEventListener("click", async () => { try { await api("/tasks", "POST", { title: $("#tTitle").value, assignee: $("#tAssignee").value, ref: $("#tRef").value, due: $("#tDue").value }); toast("追加しました"); render(); } catch (e) { toast(e.message, true); } });
      m.querySelectorAll("select[data-status]").forEach((s) => s.addEventListener("change", async () => { try { await api("/tasks/" + s.closest("tr").dataset.id, "PUT", { status: s.value }); toast("更新しました"); } catch (e) { toast(e.message, true); } }));
    },

    async approvals(m) {
      const list = await api("/approvals"); const chair = can("統括委員会");
      m.innerHTML = `<h2>承認リクエスト</h2><p class="small">決定は統括委員会が行います。申請・承認・差戻しは承認ログに自動で記録されます。</p>
        <div class="card"><div class="row"><input id="aSubject" placeholder="件名" size="30"><input id="aRef" placeholder="CQ/総論" size="10"><input id="aDetail" placeholder="内容" size="50"><button id="aAdd" class="primary">申請</button></div></div>
        <table style="margin-top:12px"><tr><th>申請日時</th><th>件名</th><th>対象</th><th>内容</th><th>申請者</th><th>状態</th><th>決定</th></tr>
        ${list.map((a) => `<tr data-id="${esc(a.id)}"><td class="small">${esc(a.requested_at.slice(0, 16))}</td><td>${esc(a.subject)}</td><td>${esc(a.ref)}</td><td>${esc(a.detail)}</td><td>${esc(a.requester)}</td><td>${stateTag(a.status === "承認" ? "完了" : a.status)} ${esc(a.status)}</td>
          <td>${a.status === "申請中" && chair ? `<input data-comment placeholder="コメント" size="14"> <button data-dec="承認" class="primary">承認</button> <button data-dec="差戻し">差戻し</button>` : `<span class="small">${esc(a.decided_by)} ${esc(a.decided_at.slice(0, 16))} ${esc(a.comment)}</span>`}</td></tr>`).join("")}</table>`;
      $("#aAdd").addEventListener("click", async () => { try { await api("/approvals", "POST", { subject: $("#aSubject").value, ref: $("#aRef").value, detail: $("#aDetail").value }); toast("申請しました"); render(); } catch (e) { toast(e.message, true); } });
      m.querySelectorAll("button[data-dec]").forEach((b) => b.addEventListener("click", async () => { const tr = b.closest("tr"); try { await api("/approvals/" + tr.dataset.id, "PUT", { status: b.dataset.dec, comment: tr.querySelector("[data-comment]").value }); toast(b.dataset.dec + "しました"); render(); } catch (e) { toast(e.message, true); } }));
    },

    async audit(m) {
      const list = await api("/audit");
      m.innerHTML = `<h2>承認ログ(Audit Trail)</h2><p class="small">全ての変更が追記されます。更新・削除の操作はありません。${list.length}件</p>${auditTable(list)}`;
    },
  };
  function auditTable(list) {
    return `<table><tr><th>日時</th><th>操作者</th><th>操作</th><th>対象</th><th>内容</th></tr>${list.map((a) => `<tr><td class="small">${esc(a.at.slice(0, 16).replace("T", " "))}</td><td>${esc(a.actor)}</td><td>${esc(a.action)}</td><td>${esc(a.target)}</td><td class="small">${esc(a.detail)}</td></tr>`).join("") || "<tr><td colspan=5 class='muted'>なし</td></tr>"}</table>`;
  }

  async function render() {
    const page = (location.hash || "#dashboard").slice(1);
    document.querySelectorAll(".side a").forEach((a) => a.classList.toggle("active", a.dataset.page === page));
    const m = $("#main"); m.innerHTML = '<p class="muted">読み込み中…</p>';
    try { await (pages[page] || pages.dashboard)(m); } catch (e) { m.innerHTML = `<p class="tag bad">${esc(e.message)}</p>`; }
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
    $("#app").classList.remove("hidden");
    window.addEventListener("hashchange", render); render();
  }
  boot();
})();
