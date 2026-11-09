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
    const secJa = { abstract: "抄録", methods: "Method", results: "Result", discussion: "Discussion", other: "その他" };
    const hasMR = text.paragraphs.some((p) => p.section === "methods" || p.section === "results");
    const note = !text.paragraphs.length ? '<p class="muted">文字を取り出せない PDF(画像)です。右の PDF を参照してください。OCR で本文を入れると段落が出ます。</p>' : (!hasMR ? '<p class="muted">Method・Result の見出しを判定できないため、全段落を表示します。</p>' : "");
    return `<div class="paras">${note}<div class="row"><label><input type="checkbox" id="onlyMR" ${hasMR ? "checked" : ""}> Method・Result だけ表示</label><input id="paraFind" placeholder="本文を検索" size="20"> ${text.source && text.source !== "pypdf" ? `<span class="tag">${esc(text.source)}</span>` : ""}</div>
      ${text.paragraphs.map((p) => `<div class="para ${hl.has(p.id) ? "hl" : ""}" data-sec="${p.section}" data-id="${esc(p.id)}"><span class="pid">${esc(p.id)}</span> <span class="tag">${secJa[p.section] || p.section} p.${p.page}</span><div>${esc(p.text)}</div></div>`).join("")}</div>`;
  }
  function wireParas(root) {
    const apply = () => { const only = root.querySelector("#onlyMR")?.checked; const q = (root.querySelector("#paraFind")?.value || "").toLowerCase();
      root.querySelectorAll(".para").forEach((d) => { const okSec = !only || d.dataset.sec === "methods" || d.dataset.sec === "results" || d.classList.contains("hl"); const okQ = !q || d.textContent.toLowerCase().includes(q); d.style.display = okSec && okQ ? "" : "none"; }); };
    root.querySelector("#onlyMR")?.addEventListener("change", apply); root.querySelector("#paraFind")?.addEventListener("input", apply); apply();
  }

  // ---------- 画面 ----------
  const pages = {
    async dashboard(m) {
      const d = await api("/dashboard"); const showSr = can("統括委員会", "事務局", "SR委員長", "SR委員", "作成グループ"), showSoron = can("統括委員会", "事務局", "総説執筆者");
      m.innerHTML = `<h2>ダッシュボード</h2>
        <div class="card phase">現在の段階: <b>${esc(d.phase)}</b> ${isAdmin() ? `<span class="row">${sel(S.meta.phases, d.phase, 'id="phaseSel"')}<button id="phaseBtn">変更</button></span>` : ""}</div>
        <div class="grid">
          ${showSr ? `<div class="card"><h3>SRの流れ: 自分の作業</h3>${d.user.name ? "" : '<p class="small">利用者の氏名が未登録のため、担当の抽出ができません(事務局に依頼)。</p>'}
            <p class="small">手順: 論文(PDF登録・本文) → 様式4-5(2名独立、照合) → 様式SR-8 → SoF表 → 推奨作成会議(投票)</p>
            <p>様式4-5 の未提出: <b>${d.my_f45_todo_count}</b> 件</p>
            <ul class="plain">${d.my_f45_todo.slice(0, 8).map((t) => `<li><a href="#f45?cq=${esc(t.cq)}&pmid=${esc(t.pmid)}&outcome=${encodeURIComponent(t.outcome)}">${esc(t.cq)} PMID ${esc(t.pmid)} / ${esc(t.outcome)}</a></li>`).join("")}</ul>
            ${d.my_cq.length ? `<h3>担当CQ</h3><ul class="plain">${d.my_cq.map((c) => `<li><a href="#papers?cq=${esc(c.id)}">${esc(c.id)} ${esc(c.title)}</a> <span class="small">${c.progress === null ? "" : "様式4-5 確定 " + c.progress + "%"}</span></li>`).join("")}</ul>` : ""}</div>` : ""}
          ${showSoron ? `<div class="card"><h3>総説の流れ: 自分の作業</h3><p class="small">手順: 原稿(Word)を提出 → 統括委員会の査読 → 修正 → 完了。原稿はこの画面で提出し、ドライブの共有は不要。</p>
            ${d.my_soron.length ? `<ul class="plain">${d.my_soron.map((s) => `<li><a href="#soron">${esc(s.label)} ${esc(s.title)}</a> ${tag(s.status)}</li>`).join("")}</ul>` : '<p class="muted">担当の総論はありません</p>'}
            <p>全体: ${Object.entries(d.soron_summary).map(([k, v]) => `${tag(k)} ${v}件 `).join("")}</p></div>` : ""}
        </div>
        ${showSr ? `<div class="card"><h3>CQごとの記録(登録された件数だけを表示する)</h3><table><tr><th>ID</th><th>名称</th><th>担当</th>${S.meta.stages.map((s) => `<th class="small">${esc(s)}</th>`).join("")}</tr>
          ${d.cq.map((c) => `<tr><td>${esc(c.id)}</td><td><a href="#papers?cq=${esc(c.id)}">${esc(c.title)}</a></td><td>${esc(c.assignees.join("・"))}</td>${S.meta.stages.map((s) => `<td class="small">${esc(c.stages[s])}</td>`).join("")}</tr>`).join("")}</table></div>` : ""}
        <div class="card" style="margin-top:14px"><h3>作成経過の記録(最新20件)</h3>${auditTable(d.audit)}</div>`;
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
            <div class="row"><label class="small">備考 <input data-note value="${esc(c.note)}" size="60" ${ed ? "" : "readonly"}></label>${ed ? '<button data-act="save">保存</button>' : ""} <a href="#papers?cq=${esc(c.id)}">論文</a> <a href="#sr8?cq=${esc(c.id)}">SR-8</a> <a href="#etd?cq=${esc(c.id)}">EtD</a></div></div>`; }).join("")}`;
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
        ${list.map((p) => `<tr data-pmid="${esc(p.pmid)}"><td><a href="https://pubmed.ncbi.nlm.nih.gov/${esc(p.pmid)}/" target="_blank" rel="noopener">${esc(p.pmid)}</a></td><td>${esc(p.title)}</td><td>${tag(p.status, p.status.startsWith("本文抽出済") ? "ok" : "warn")}</td>
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
      const hl = new Set(); [mine, ai, fin, ...Object.values(d.others || {})].forEach((r) => Object.values(r?.items || {}).forEach((it) => (it.evidence || []).forEach((e) => hl.add(e))));
      const otherCols = Object.entries(d.others || {});
      $("#f45body").innerHTML = `<div class="split">
        <div class="card" id="paraBox"><h3>本文の該当箇所 <button id="pdfBtn">PDF</button></h3>${text ? paraPanel(text, [...hl]) : '<p class="muted">本文が未抽出です。論文の画面で PDF を登録し、本文を抽出してください。下書きは本文がなければ作りません。</p>'}</div>
        <div class="card"><h3>判定(0 / -1 / -2) ${mine.submitted ? tag("提出済み", "ok") : ""} ${fin ? tag("確定", "ok") : d.reconcile_open ? tag("照合中", "run") : ""}</h3>
          <p class="small">2名独立: 自分の欄に、本文を読んで判定する(バイアスリスク10項目、非直接性5項目を 0 / -1 / -2)。根拠の段落 ID と引用を書く。記載がなければ -1 とし「記載なし」と書く。相手の判定は、2名が提出するまで表示されない。提出後に照合し、確定する。盲検化の2項目は -2 を使わない(統括委員長の決定)。</p>
          <div class="row">${ed && text ? `<button id="draftBtn">Claude下書きを作る(本文の段落を根拠に)</button>` : ""} ${ed && ai?.items ? `<button id="copyAi">下書きを自分の欄に取り込んで修正する</button>` : ""} ${ai ? `<span class="small">下書き: ${esc(ai.status || "")} ${ai.error ? esc(ai.error) : ""}</span>` : ""}</div>
          <table class="f45"><tr><th>項目</th>${ai?.items ? "<th>Claude下書き</th>" : ""}<th>自分(${esc(S.me.name || "—")})</th>${otherCols.map(([n]) => `<th>${esc(n)}</th>`).join("")}${d.reconcile_open || fin || isLead() ? "<th>確定(照合)</th>" : ""}</tr>
            ${K.map((k, i) => `<tr><td>${esc(JA[i])}</td>${ai?.items ? `<td>${cell(ai, k, false)}</td>` : ""}<td data-col="mine">${cell(mine, k, ed)}</td>${otherCols.map(([, r]) => `<td>${cell(r, k, false)}</td>`).join("")}
              ${d.reconcile_open || fin || isLead() ? `<td data-col="final">${cell(fin || mine, k, (d.reconcile_open && d.submitted.includes(S.me.name)) || isLead())}</td>` : ""}</tr>`).join("")}</table>
          <div class="row"><label class="small">測定尺度 <input id="instrument" value="${esc(mine.instrument || ai?.study?.instrument || "")}" size="24"></label>
            <label class="small">対照 分子/分母 <input id="cnum" value="${esc(mine.counts?.ctrl_num ?? "")}" size="4">/<input id="cden" value="${esc(mine.counts?.ctrl_den ?? "")}" size="4"></label>
            <label class="small">介入 分子/分母 <input id="inum" value="${esc(mine.counts?.int_num ?? "")}" size="4">/<input id="iden" value="${esc(mine.counts?.int_den ?? "")}" size="4"></label>
            <label class="small">効果 ${sel(["RR", "OR", "HR", "MD", "SMD"], mine.effect?.measure, 'id="emeas"', true)} <input id="eval" value="${esc(mine.effect?.value ?? "")}" size="6"> [<input id="elo" value="${esc(mine.effect?.ci_low ?? "")}" size="6">, <input id="ehi" value="${esc(mine.effect?.ci_high ?? "")}" size="6">]</label></div>
          <div class="row"><label class="small">備考 <input id="note45" value="${esc(mine.note || "")}" size="60"></label></div>
          <div class="row">${ed ? `<button id="save45">保存(下書き)</button> <button id="submit45" class="primary">提出(確定後は照合で変更)</button>` : ""} ${(d.reconcile_open && d.submitted.includes(S.me.name)) || isLead() ? `<button id="final45" class="primary">照合の結果を確定する</button>` : ""}</div>
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
      $("#copyAi")?.addEventListener("click", () => { K.forEach((k) => { const it = ai.items[k] || {}; const g = (f) => m.querySelector(`td[data-col="mine"] [data-k="${k}"][data-f="${f}"]`); if (g("v")) g("v").value = it.v === null ? "" : it.v; if (g("evidence")) g("evidence").value = (it.evidence || []).join(","); if (g("quote")) g("quote").value = it.quote || ""; }); toast("取り込みました。本文で確認し、修正して提出してください"); });
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
        <p class="small">左に 2023年版の記述(推奨文・推奨の強さ・エビデンスの確実性・解説・投票)、右に 2028年版の案。4つの考慮事項には根拠(論文の段落 ID、2023年版の段落 ID)を書く。推奨文には適用するがん腫・化学療法の分類を明記する。推奨作成会議で投票し(投票権のある委員の75%以上が参加、80%以上の一致で決定、最大3回)、結果を記録する。投票除外(直接評価した論文の筆頭著者、そのCQのSR担当者)は分母から除く。</p>
        <div class="split">
          <div class="card"><h3>2023年版</h3>${g ? `<p><b>推奨文</b> ${esc(g.rec)}</p><p>強さ ${esc(g.strength)} / 確実性 ${esc(g.certainty)} ${g.votes ? `/ 投票 分母 ${g.votes.denominator} 分布 ${(g.votes.counts || []).join("・")} (COI除外 ${g.votes.coi} SR除外 ${g.votes.sr})` : ""}</p>
            <div class="paras">${(g.paragraphs || []).map((p) => `<div class="para"><span class="pid">${esc(p.id)}</span><div>${esc(p.text)}</div></div>`).join("")}</div>` : '<p class="muted">2023年版の記述が未取り込みです(事務局が etd_2023.json を取り込む)。</p>'}
            <h3 style="margin-top:12px">SR-8 の確実性</h3><ul class="plain">${Object.entries(d.sr8).map(([o, r]) => `<li>${esc(o)}: <b>${esc(r.certainty || "—")}</b> ${esc(r.strata || "")}</li>`).join("") || "<li class='muted'>未記入</li>"}</ul></div>
          <div class="card"><h3>2028年版(案)</h3>
            <label class="small">推奨文(案。癌腫・レジメンを明記)<br><textarea id="rec" rows="3" cols="60" ${ed ? "" : "readonly"}>${esc(e.rec_draft || "")}</textarea></label>
            <div class="row"><label class="small">推奨の強さ ${ed ? sel(S.meta.strength, e.strength, 'id="strength"', true) : `<b>${esc(e.strength || "—")}</b>`}</label><label class="small">エビデンスの確実性 ${ed ? sel(S.meta.cert, e.certainty, 'id="cert"', true) : `<b>${esc(e.certainty || "—")}</b>`}</label></div>
            <label class="small">適用範囲・2023年版からの変更点 <input id="scope" value="${esc(e.scope_note || "")}" size="60" ${ed ? "" : "readonly"}></label>
            <table style="margin-top:8px"><tr><th>考慮事項</th><th>内容</th><th>根拠(段落ID)</th></tr>
              ${cons.map(([k, ja]) => `<tr><td>${esc(ja)}</td><td><textarea data-ck="${k}" data-f="text" rows="3" cols="40" ${ed ? "" : "readonly"}>${esc(e.considerations?.[k]?.text || "")}</textarea></td><td><input data-ck="${k}" data-f="evidence" value="${esc((e.considerations?.[k]?.evidence || []).join(","))}" size="18" ${ed ? "" : "readonly"}></td></tr>`).join("")}</table>
            <h3 style="margin-top:12px">投票の記録</h3>
            <div class="row"><label class="small">回 <input id="vround" value="${esc(e.vote?.round ?? 1)}" size="2"></label><label class="small">日付 <input id="vdate" type="date" value="${esc(e.vote?.date || "")}"></label>
              ${[1, 2, 3, 4, 5].map((i) => `<label class="small">${i} <input data-v="${i - 1}" value="${esc(e.vote?.counts?.[i - 1] ?? "")}" size="2"></label>`).join("")}
              <label class="small">分母 <input id="vden" value="${esc(e.vote?.denominator ?? "")}" size="3"></label><label class="small">投票除外(筆頭著者) <input id="vcoi" value="${esc(e.vote?.coi_excluded ?? "")}" size="2"></label><label class="small">投票除外(SR担当) <input id="vsr" value="${esc(e.vote?.sr_excluded ?? "")}" size="2"></label>
              ${e.vote?.agreement !== undefined && e.vote?.agreement !== null ? `<b>合意率 ${e.vote.agreement}%</b>` : ""}</div>
            <label class="small">解説(推奨の理由。根拠の段落ID付き)<br><textarea id="narr" rows="6" cols="60" ${ed ? "" : "readonly"}>${esc(e.narrative || "")}</textarea></label>
            <div class="row">${ed ? `<button id="etdSave" class="primary">保存</button> ${sel(["下書き", "協議中", "確定"], e.status, 'id="etdStatus"')} <button id="etdDraft">Claude下書きを作る(SR-8・様式4-5・2023年版を根拠に)</button>` : ""} <button id="exportBtn">Minds書類(xlsx)を出力</button></div>
            ${e.ai_draft ? `<div class="card" style="margin-top:10px"><h3>Claude下書き <span class="small">${esc(e.ai_draft.status || "")} ${esc((e.ai_draft.at || "").slice(0, 16))} ${e.ai_draft.error ? esc(e.ai_draft.error) : ""}</span></h3>
              ${e.ai_draft.rec_draft ? `<p><b>推奨文案</b> ${esc(e.ai_draft.rec_draft)}</p>${cons.map(([k, ja]) => `<p><b>${esc(ja)}</b> ${esc(e.ai_draft.considerations?.[k]?.text || "")} <span class="small">${esc((e.ai_draft.considerations?.[k]?.evidence || []).join(", "))}</span></p>`).join("")}<p><b>解説文案</b><br>${esc(e.ai_draft.narrative || "").replace(/\n/g, "<br>")}</p><p class="small">2023年版からの変更点: ${esc(e.ai_draft.changes_from_2023 || "")}</p>
              ${ed ? '<button id="etdCopy">下書きを右の欄に取り込んで修正する</button>' : ""}<p class="small">根拠のIDは、SR8-アウトカム、F45-PMID-アウトカム、GL2023-段落。推奨の強さと確実性は、下書きに含めない(投票と様式SR-8で決める)。</p>` : ""}</div>` : ""}</div></div>`;
      $("#cqSel").addEventListener("change", () => go("etd", { cq: $("#cqSel").value }));
      $("#etdDraft")?.addEventListener("click", async () => { try { await api("/etd/" + cqid + "/draft", "POST", {}); toast("下書きを作成中です(1〜2分後に再読み込み)"); setTimeout(render, 60000); } catch (e2) { toast(e2.message, true); } });
      $("#exportBtn")?.addEventListener("click", async () => { try { const r = await api("/export/" + cqid); toast(`出力しました(${r.sheets.join("・")})`); if (r.url) window.open(r.url, "_blank"); } catch (e2) { toast(e2.message, true); } });
      $("#etdCopy")?.addEventListener("click", () => { const a = e.ai_draft; $("#rec").value = a.rec_draft || ""; cons.forEach(([k]) => { m.querySelector(`[data-ck="${k}"][data-f="text"]`).value = a.considerations?.[k]?.text || ""; m.querySelector(`[data-ck="${k}"][data-f="evidence"]`).value = (a.considerations?.[k]?.evidence || []).join(","); }); $("#narr").value = a.narrative || ""; toast("取り込みました。確認・修正して保存してください"); });
      $("#etdSave")?.addEventListener("click", async () => { const considerations = {}; cons.forEach(([k]) => (considerations[k] = { text: m.querySelector(`[data-ck="${k}"][data-f="text"]`).value, evidence: m.querySelector(`[data-ck="${k}"][data-f="evidence"]`).value.split(/[,\s]+/).filter(Boolean) }));
        const counts = [0, 1, 2, 3, 4].map((i) => m.querySelector(`[data-v="${i}"]`).value);
        try { await api("/etd/" + cqid, "PUT", { rec_draft: $("#rec").value, strength: $("#strength")?.value, certainty: $("#cert")?.value, scope_note: $("#scope").value, considerations, narrative: $("#narr").value, status: $("#etdStatus").value,
          vote: { round: $("#vround").value, date: $("#vdate").value, counts, denominator: $("#vden").value, coi_excluded: $("#vcoi").value, sr_excluded: $("#vsr").value } }); toast("保存しました"); render(); } catch (e2) { toast(e2.message, true); } });
    },

    async soron(m) {
      const list = await api("/soron"); const admin = isAdmin();
      const mineOnly = !admin && !isLead();
      const rows = list.filter((s) => !mineOnly || (S.me.name && s.author.split("・").some((a) => a && S.me.name.startsWith(a))));
      m.innerHTML = `<h2>総説の流れ: 総論(A〜N)の執筆・査読</h2>
        <p class="small">企画書の総論18項目と担当。執筆者は原稿(Word)をこの画面で提出し、状態を「査読中」にする。統括委員会が査読コメントを書くと「修正中」になり、執筆者が修正版を提出する。完了は統括委員会が決める。原稿は版ごとに保存される。SRの流れ(CQ)とは独立している。</p>
        <table><tr><th>項目</th><th>題名</th><th>担当</th><th>状態</th><th>期限</th><th>最新の原稿</th><th>査読コメント(統括委員会)</th><th>備考</th><th></th></tr>
        ${rows.map((s) => { const o = S.me.name && s.author.split("・").some((a) => a && S.me.name.startsWith(a)); const ed = o || admin;
          return `<tr data-key="${esc(s.key)}"><td>${esc(s.label)}</td><td>${esc(s.title)}</td><td>${esc(s.author)}</td>
            <td>${ed ? sel(S.meta.soron_states.filter((x) => admin || x !== "完了"), s.status, "data-status") : tag(s.status)}</td>
            <td>${ed ? `<input type="date" data-due value="${esc(s.due || "")}">` : esc(s.due || "")}</td>
            <td class="small">${s.file ? `<a href="#" data-dl="${esc(s.key)}">${esc(s.file)}</a><br>${esc((s.file_at || "").slice(0, 16))} ${esc(s.file_by || "")}` : "—"}${ed ? `<br><input type="file" data-up accept=".docx,.doc,.pdf"> <button data-act="upload">提出</button>` : ""}</td>
            <td>${admin ? `<textarea data-review rows="2" cols="24">${esc(s.review || "")}</textarea>` : esc(s.review || "")}${s.review_by ? `<div class="small">${esc(s.review_by)} ${esc((s.review_at || "").slice(0, 16))}</div>` : ""}</td>
            <td>${ed ? `<input data-note value="${esc(s.note || "")}" size="14">` : esc(s.note || "")}</td><td>${ed ? '<button data-act="save">保存</button> ' : ""}<button data-gl="${esc(s.key)}">2023年版</button></td></tr>`; }).join("") || "<tr><td colspan=9 class='muted'>担当の総論はありません</td></tr>"}</table><div id="gl2023Box"></div>`;
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
          if (!g.paragraphs) { box.innerHTML = '<p class="muted">この総論の 2023年版の本文は未取り込みです(新設の節、または事務局の取り込み待ち)。</p>'; return; }
          box.innerHTML = `<div class="card" style="margin-top:12px"><h3>2023年版 総論${esc(b.dataset.gl.replace("_", "-"))} ${esc(g.title)} <span class="small">${g.paragraphs.length}段落</span> ${g.docx_url ? `<a href="${esc(g.docx_url)}" target="_blank" rel="noopener">Word(原文)</a>` : ""}</h3>
            <p class="small">段落 ID を、原稿の根拠や変更箇所の指示に使う。</p><div class="paras">${g.paragraphs.map((p) => `<div class="para"><span class="pid">${esc(p.id)}</span><div>${esc(p.text)}</div></div>`).join("")}</div></div>`;
          box.scrollIntoView({ behavior: "smooth" }); } catch (e) { toast(e.message, true); } }));
    },

    async screening(m) {
      const prog = await api("/screening");
      m.innerHTML = `<h2>スクリーニングの進捗</h2><p class="small">スクリーニング管理シート(CQごとの HTML)で書き出した JSON を取り込む。判定は変えない。担当者ごとの進捗を表示し、照合(merge_screening.py)用に同じ JSON を返す。</p>
        <div class="card"><div class="row"><label>CQ <select id="scrCq">${S.cqs.flatMap((c) => c.dirs).map((d) => `<option>${esc(d)}</option>`).join("")}</select></label><input type="file" id="scrFile" accept=".json"><button id="scrUp" class="primary">取り込む</button></div></div>
        ${Object.entries(prog).sort().map(([cq, rs]) => `<div class="card" style="margin-top:12px"><h3>${esc(cq)}</h3><table><tr><th>担当</th><th>保存日時</th><th>文献</th><th>一次 判定済/未</th><th>二次 判定済/未</th><th>全文 未入手</th><th>全文 読了</th><th>除外で理由未記入</th><th></th></tr>
          ${rs.map((r) => `<tr><td>${esc(r.reviewer)}</td><td>${esc((r.saved_at || "").slice(0, 16))}</td><td>${r.papers}</td><td>${r.s1_done} / ${r.s1_todo}</td><td>${r.s2_done} / ${r.s2_todo}</td><td>${r.ft_missing}</td><td>${r.ft_read}</td><td>${r.no_reason ? tag(r.no_reason, "warn") : 0}</td><td><button data-raw="${esc(r.sk)}">JSON</button></td></tr>`).join("")}</table></div>`).join("") || '<p class="muted" style="margin-top:12px">取り込み済みの JSON はありません。</p>'}`;
      $("#scrUp").addEventListener("click", async () => { const f = $("#scrFile").files[0]; if (!f) return toast("JSON ファイルを選んでください", true);
        try { const d = JSON.parse(await f.text()); const r = await api("/screening/" + encodeURIComponent($("#scrCq").value), "POST", d); toast(`取り込みました(${r.reviewer}: 文献${r.papers}件)`); render(); } catch (e) { toast(e.message, true); } });
      m.querySelectorAll("button[data-raw]").forEach((b) => b.addEventListener("click", async () => { const d = await api("/screening/raw/" + encodeURIComponent(b.dataset.raw)); const a = document.createElement("a"); a.href = URL.createObjectURL(new Blob([JSON.stringify(d, null, 1)], { type: "application/json" })); a.download = b.dataset.raw.replace("#", "_") + ".screening.json"; a.click(); }));
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

    async audit(m) { const list = await api("/audit"); m.innerHTML = `<h2>作成経過の記録</h2><p class="small">全ての操作が追記される。更新・削除の操作はない。${list.length}件</p>${auditTable(list)}`; },
  };

  async function render() {
    const page = (location.hash || "#dashboard").slice(1).split("?")[0];
    document.querySelectorAll(".side a").forEach((a) => a.classList.toggle("active", a.dataset.page === page));
    const m = $("#main"); m.innerHTML = '<p class="muted">読み込み中…</p>';
    try { if (!S.cqs.length) S.cqs = await api("/cq"); await (pages[page] || pages.dashboard)(m); } catch (e) { m.innerHTML = `<p class="tag bad">${esc(e.message)}</p>`; }
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
