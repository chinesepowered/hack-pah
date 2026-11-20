// CapyTeam town UI. Everything here is read from SingleStore through the CapyTeam API.
(function () {
  const $ = (s, el = document) => el.querySelector(s);
  const $$ = (s, el = document) => [...el.querySelectorAll(s)];
  const params = new URLSearchParams(location.search);
  const VIDEO = params.has("video");
  if (VIDEO) document.body.classList.add("video");
  const { capySVG, townSVG, anchor, VCOLOR } = window.CAPY;
  const api = (p, opt) => fetch(p, opt).then(r => r.json());
  const esc = s => String(s ?? "").replace(/[&<>"]/g, c => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" }[c]));
  const money = v => `$${Number(v || 0).toFixed(Number(v) < 0.1 ? 4 : 2)}`;
  const vcol = v => VCOLOR[v] || "#7a6a58";

  $("#logo").innerHTML = capySVG("#e07b39", { hat: true });

  // ---------------------------------------------------------------- tabs
  function showTab(name) {
    $$("#tabs button").forEach(b => b.classList.toggle("on", b.dataset.tab === name));
    $$(".tab").forEach(t => t.classList.toggle("on", t.id === `tab-${name}`));
    ({ score: renderScore, school: renderSchool, race: renderRaces, shifts: renderShifts })[name]?.();
  }
  $$("#tabs button").forEach(b => b.addEventListener("click", () => showTab(b.dataset.tab)));
  window.capTab = showTab;

  // ---------------------------------------------------------------- caption (video)
  let capTimer;
  window.capCaption = (text, ms = 4000) => {
    const c = $("#caption");
    c.textContent = text;
    c.classList.add("show");
    clearTimeout(capTimer);
    if (ms) capTimer = setTimeout(() => c.classList.remove("show"), ms);
  };

  // ---------------------------------------------------------------- stack pills
  async function stack() {
    try {
      const o = await api("/api/overview");
      window.__overview = o;
      const pills = [
        ["ok", `<b>SingleStore</b> ${o.db.includes("Helios") ? "Helios" : "local"} · ${o.events} events`],
        ["ok", `<b>SIE Serverless</b> Qwen3.8-27B + 5 task models`],
        ["ok", `<b>Amplitude</b> Agent Analytics`],
        o.experiment_provider === "statsig"
          ? ["ok", `<b>Statsig</b> experiment: ${o.candidate ? o.candidate + " vs " + o.shipped : o.shipped + " shipped"}`]
          : ["warn", `<b>Statsig</b> wired · ${o.candidate ? o.candidate + " vs " + o.shipped + " (hash split)" : o.shipped + " shipped"}`],
        ["ok", `<b>Firedrill</b> drills`],
        ["ok", `<b>Airbyte</b> live reads`],
      ];
      $("#stack").innerHTML = pills.map(([k, t]) => `<span class="pill ${k}">${t}</span>`).join("");
    } catch (e) { /* offline */ }
  }

  // ---------------------------------------------------------------- town
  $("#map").innerHTML = townSVG();
  const sprites = $("#sprites");
  const capys = {};       // session_id -> {el, at, name, version, timer}
  const occupancy = {};   // building -> [session_id]
  const stats = { shifts: new Set(), claims: 0, blocked: 0, lessons: 0, refunds: 0 };

  function where(e) {
    if (e.kind === "start") return e.mode === "drill" ? "fire" : "home";
    if (e.kind === "end") return "obs";
    if (e.kind === "verdict") return e.mode === "drill" ? "fire" : "school";
    if (e.kind === "model") return "lab";
    if (e.kind === "lesson" || e.kind === "claim") return "archive";
    return e.building || "home";
  }

  function place(id) {
    const c = capys[id];
    if (!c) return;
    const list = occupancy[c.at] || [];
    const i = list.indexOf(id);
    const a = anchor(c.at);
    const col = i % 6, row = Math.floor(i / 6);
    const dx = (col - 2.5) * 0.034, dy = (row * 0.055) * (a.y > 0.5 ? 1 : -1);
    c.el.style.left = `${(a.x + dx) * 100}%`;
    c.el.style.top = `${(a.y + dy) * 100}%`;
  }

  function moveTo(id, b) {
    const c = capys[id];
    if (c.at === b) return;
    if (c.at && occupancy[c.at]) {
      occupancy[c.at] = occupancy[c.at].filter(x => x !== id);
      occupancy[c.at].forEach(place);
      $(`#b-${c.at}`)?.classList.toggle("busy", occupancy[c.at].length > 0);
    }
    c.at = b;
    (occupancy[b] = occupancy[b] || []).push(id);
    c.el.classList.add("walk");
    setTimeout(() => c.el.classList.remove("walk"), 1100);
    place(id);
    $(`#b-${b}`)?.classList.add("busy");
  }

  function ensureCapy(e) {
    if (capys[e.session_id]) return capys[e.session_id];
    const el = document.createElement("div");
    el.className = "capy";
    const v = e.agent_version || "v1";
    el.innerHTML = `${capySVG(vcol(v))}<div class="capy-name">${esc(e.capy_name)}<span class="ver" style="background:${vcol(v)}">${esc(v)}</span></div><div class="bubble"></div>`;
    const a = anchor("home");
    el.style.left = `${a.x * 100}%`; el.style.top = `${a.y * 100}%`;
    sprites.appendChild(el);
    capys[e.session_id] = { el, at: null, name: e.capy_name, version: v };
    stats.shifts.add(e.session_id);
    return capys[e.session_id];
  }

  function bubble(id, text, cls = "") {
    const c = capys[id];
    if (!c) return;
    for (const other of occupancy[c.at] || []) if (other !== id && capys[other]) $(".bubble", capys[other].el).classList.remove("show");
    const b = $(".bubble", c.el);
    b.classList.toggle("below", anchor(c.at).y < 0.5);
    b.className = `bubble show ${cls}`;
    b.textContent = text.length > 120 ? text.slice(0, 117) + "…" : text;
    clearTimeout(c.timer);
    c.timer = setTimeout(() => b.classList.remove("show"), 3600);
  }

  function stamp(bkey, text, cls) {
    const a = anchor(bkey);
    const s = document.createElement("div");
    s.className = `stamp ${cls}`;
    s.textContent = text;
    s.style.left = `${a.x * 100}%`;
    s.style.top = `${(a.y + (a.y > 0.5 ? 0.17 : -0.2)) * 100}%`;
    sprites.appendChild(s);
    setTimeout(() => s.remove(), 2600);
  }

  function coin(from, to) {
    const a = anchor(from), b = anchor(to);
    const c = document.createElement("div");
    c.className = "coin";
    c.style.left = `${a.x * 100}%`; c.style.top = `${(a.y - 0.04) * 100}%`;
    sprites.appendChild(c);
    requestAnimationFrame(() => requestAnimationFrame(() => { c.style.left = `${b.x * 100}%`; c.style.top = `${(b.y - 0.04) * 100}%`; }));
    setTimeout(() => { c.style.opacity = 0; }, 1300);
    setTimeout(() => c.remove(), 1800);
  }

  function fire(bkey) {
    const b = $(`#b-${bkey}`);
    if (!b) return;
    b.classList.add("fire");
    clearTimeout(b._t);
    b._t = setTimeout(() => b.classList.remove("fire"), 7000);
  }

  const FRIENDLY = {
    gmail_search: "Reading the inbox", gmail_send: "Writing an email", stripe_find_customer: "Looking up the customer",
    stripe_list_charges: "Checking Stripe charges", stripe_list_refunds: "Checking past refunds", stripe_create_refund: "Sending a refund",
    qbo_find_customer: "Finding them in QuickBooks", qbo_list_invoices: "Checking invoices", qbo_list_refunds: "Checking the books",
    qbo_book_refund: "Booking the refund", qbo_create_invoice: "Writing an invoice", qbo_send_invoice: "Sending the invoice",
    qbo_record_payment: "Recording a payment", check_team_board: "Checking the team board",
  };
  function clean(e) {
    const s = e.summary || "";
    if (e.kind === "tool_call") { const t = s.split("(")[0]; return FRIENDLY[t] || t; }
    if (e.kind === "tool_result") {
      const m = s.match(/^(ok|failed): (\w+)/);
      if (!m) return s;
      if (m[1] === "ok") return `done: ${FRIENDLY[m[2]] || m[2]}`;
      const msg = s.match(/"message": "([^"]+)/) || s.match(/"detail": "([^"]+)/) || s.match(/"code": "([^"]+)/);
      return `failed: ${FRIENDLY[m[2]] || m[2]}${msg ? " (" + msg[1].slice(0, 80) + ")" : ""}`;
    }
    return s;
  }
  const KIND = { user: "owner", assistant: "reply", tool_call: "tool", tool_result: "result", model: "SIE", lesson: "lesson", claim: "claim", guard: "guard", verdict: "verdict", start: "in", end: "out" };

  function tick(e) {
    const li = document.createElement("li");
    li.innerHTML = `<span class="k">${KIND[e.kind] || e.kind}</span><span class="who">${esc(e.capy_name)}</span> <span style="color:${vcol(e.agent_version)}">${esc(e.agent_version)}</span> · ${esc(clean(e)).slice(0, 150)}`;
    const t = $("#ticker");
    t.prepend(li);
    while (t.children.length > 16) t.lastChild.remove();
  }

  function dayCard(e) {
    const runId = (e.session_id || "").replace(/-\d\d$/, "").replace(/-(cracked-mug|said-twice|stripe-down|big-deposit|fake-maya-email|workshop-invoice|acme-paid)$/, "");
    $("#day-title").textContent = e.mode === "race" ? `Race in progress (${runId})` : e.mode === "drill" ? "Fire drill at the station" : `Shift: ${runId}`;
    $("#day-stats").innerHTML = [
      [stats.shifts.size, "capybaras on shift"], [stats.claims, "money actions claimed"], [stats.blocked, "duplicates blocked"],
      [stats.refunds, "refunds made"], [stats.lessons, "lessons recalled"],
    ].map(([n, l]) => `<div class="s"><b>${n}</b>${l}</div>`).join("");
  }

  function onEvent(e) {
    const c = ensureCapy(e);
    const b = where(e);
    moveTo(e.session_id, b);
    const s = e.summary || "";
    if (e.kind === "claim") {
      if (s.startsWith("Claim refused")) { stats.blocked++; bubble(e.session_id, "Already handled by another capybara: standing down.", "guard"); stamp("archive", "ALREADY CLAIMED", "block"); }
      else { stats.claims++; bubble(e.session_id, s, "guard"); }
    } else if (e.kind === "guard") bubble(e.session_id, s, "guard");
    else if (e.kind === "verdict") { const pass = s.includes("PASS"); bubble(e.session_id, s, pass ? "good" : "bad"); stamp(b, pass ? "PASS" : "FAIL", pass ? "pass" : "fail"); }
    else if (e.kind === "lesson") { stats.lessons++; bubble(e.session_id, s, "guard"); }
    else if (e.kind === "tool_result") {
      if (s.startsWith("ok: stripe_create_refund")) { stats.refunds++; coin("bank", "home"); bubble(e.session_id, "Refund sent!", "good"); }
      else if (s.startsWith("failed")) {
        const by = s.match(/"by": "([^"]+)"/);
        if (/already_claimed/.test(s)) bubble(e.session_id, `${by ? by[1].replace(/ \(.*\)/, "") : "A teammate"} already did this one. Standing down.`, "guard");
        else if (/needs_owner_approval/.test(s)) bubble(e.session_id, "Over $200: asking Maya first.", "guard");
        else if (/payment_failed/.test(s)) bubble(e.session_id, "Refund didn't go through, so nothing gets booked.", "guard");
        else bubble(e.session_id, clean(e).replace(/^failed: /, "Uh oh: "), "bad");
        if (/unavailable/i.test(s) && b === "bank") fire("bank");
      }
    } else if (e.kind === "tool_call") bubble(e.session_id, clean(e));
    else if (e.kind === "user" || e.kind === "assistant" || e.kind === "model") bubble(e.session_id, s);
    else if (e.kind === "end") {
      bubble(e.session_id, "Clocking out: session sent to Amplitude");
      setTimeout(() => {
        const cc = capys[e.session_id];
        if (!cc) return;
        cc.el.style.transition = "opacity .8s"; cc.el.style.opacity = 0;
        setTimeout(() => { cc.el.remove(); occupancy[cc.at] = (occupancy[cc.at] || []).filter(x => x !== e.session_id); $(`#b-${cc.at}`)?.classList.toggle("busy", (occupancy[cc.at] || []).length > 0); delete capys[e.session_id]; }, 900);
      }, 3200);
    }
    tick(e);
    dayCard(e);
  }
  window.capEvent = onEvent;
  window.capReset = () => {
    for (const id of Object.keys(capys)) { capys[id].el.remove(); delete capys[id]; }
    for (const k of Object.keys(occupancy)) { occupancy[k] = []; $(`#b-${k}`)?.classList.remove("busy"); }
    stats.shifts = new Set(); stats.claims = 0; stats.blocked = 0; stats.lessons = 0; stats.refunds = 0;
    $("#ticker").innerHTML = "";
    window.__replayToken = (window.__replayToken || 0) + 1;
  };

  // live stream or replay
  async function replay(prefixes, speed) {
    let evs = [];
    for (const p of prefixes) evs = evs.concat(await api(`/api/events?run=${encodeURIComponent(p)}&limit=3000`));
    evs.sort((a, b) => (a.ts < b.ts ? -1 : a.ts > b.ts ? 1 : a.seq - b.seq));
    window.__replayTotal = evs.length;
    let prev = null;
    const token = window.__replayToken || 0;
    for (const e of evs) {
      if ((window.__replayToken || 0) !== token) return;
      const t = Date.parse(String(e.ts).replace(" ", "T").slice(0, 23) + "Z");
      if (prev !== null) await new Promise(r => setTimeout(r, Math.min(1400, Math.max(30, (t - prev) / speed))));
      prev = t;
      onEvent(e);
    }
    window.__replayDone = true;
  }
  function live() {
    const es = new EventSource("/api/stream");
    es.onmessage = m => { try { onEvent(JSON.parse(m.data)); } catch (err) { /* ignore */ } };
  }
  window.capReplay = (prefixes, speed = 3) => replay(prefixes.split(","), speed);
  if (params.get("replay")) replay(params.get("replay").split(","), Number(params.get("speed") || 3));
  else if (!params.has("still")) live();

  // controls
  $$("#controls button").forEach(btn => btn.addEventListener("click", async () => {
    const kind = btn.dataset.run;
    const body = kind === "night" ? { base: window.__overview?.shipped || "v1" } : { version: btn.dataset.version || null };
    const r = await api(`/api/run/${kind}`, { method: "POST", headers: { "content-type": "application/json" }, body: JSON.stringify(body) });
    $("#job").textContent = `started ${r.job}${r.run_id ? " · " + r.run_id : ""}`;
  }));

  // ---------------------------------------------------------------- scoreboard
  async function renderScore() {
    const [o, drills] = await Promise.all([api("/api/overview"), api("/api/drills?limit=400")]);
    const byV = {};
    for (const d of drills) {
      const v = d.agent_version;
      const x = (byV[v] = byV[v] || { practice: [], race: [], firedrill: [] });
      if (d.scenario === "race") x.race.push(d);
      else if (d.source === "firedrill") x.firedrill.push(d);
      else x.practice.push(d);
    }
    const cost = Object.fromEntries((o.costs || []).map(c => [c.version, c]));
    const versions = (o.versions || []).filter(v => byV[v.version] || v.status !== "retired");
    $("#score-sub").innerHTML = `All numbers are live queries on <b>${esc(o.db)}</b>: ${o.events} events, ${o.lessons} lessons, ${o.duplicates_blocked} duplicate money actions blocked.`;
    $("#versions").innerHTML = versions.map(v => {
      const x = byV[v.version] || { practice: [], race: [], firedrill: [] };
      const latest = {};
      for (const d of x.practice) if (!latest[d.scenario] || latest[d.scenario].created_at < d.created_at) latest[d.scenario] = d;
      const prac = Object.values(latest);
      const passed = prac.filter(d => d.passed).length;
      const race = x.race.sort((a, b) => (a.created_at < b.created_at ? 1 : -1))[0];
      const rr = race?.results?.race;
      const c = cost[v.version] || {};
      const pols = Object.entries(v.guards || {}).filter(([, val]) => val !== null && val !== false).map(([k, val]) => k === "approval_over_usd" ? `approval over $${val}` : k.replace(/_/g, " "));
      const fd = x.firedrill.length ? `<div class="n"><b>${x.firedrill.filter(d => d.passed).length}/${x.firedrill.length}</b><span>Firedrill drills passed</span></div>` : "";
      return `<div class="vcard" style="border-color:${vcol(v.version)}">
        <h3><span style="color:${vcol(v.version)}">${esc(v.version)}</span><span class="status ${esc(v.status)}">${esc(v.status)}</span></h3>
        <div class="nums">
          <div class="n"><b>${prac.length ? `${passed}/${prac.length}` : "–"}</b><span>practice drills passed</span></div>
          <div class="n"><b>${rr ? rr.refunds : "–"}</b><span>refunds in the race (want 1)</span></div>
          <div class="n"><b>${c.avg_cost_usd != null ? money(c.avg_cost_usd) : "–"}</b><span>SIE cost per shift</span></div>
          <div class="n"><b>${(v.lesson_ids || []).length}</b><span>lessons it ships with</span></div>
          ${fd}
        </div>
        <div class="notes">${esc(v.notes)}</div>
        <div class="pol">${pols.map(p => `<span>${esc(p)}</span>`).join("")}</div>
      </div>`;
    }).join("");
    // pass-rate chart
    const bars = versions.map(v => {
      const latest = {};
      for (const d of (byV[v.version]?.practice || [])) if (!latest[d.scenario] || latest[d.scenario].created_at < d.created_at) latest[d.scenario] = d;
      const p = Object.values(latest);
      return { v: v.version, val: p.length ? p.filter(d => d.passed).length / p.length : 0, label: p.length ? `${p.filter(d => d.passed).length}/${p.length}` : "–" };
    });
    $("#chart-pass").innerHTML = barChart(bars, 1, x => `${Math.round(x * 100)}%`);
    const races = drills.filter(d => d.scenario === "race").sort((a, b) => (a.created_at < b.created_at ? -1 : 1));
    $("#chart-race").innerHTML = barChart(races.map(d => ({ v: d.agent_version, val: d.results?.race?.refunds || 0, label: `${d.results?.race?.refunds} refund${d.results?.race?.refunds === 1 ? "" : "s"}` })), Math.max(3, ...races.map(d => d.results?.race?.refunds || 0)), x => x, true);
    // timeline
    const items = [];
    for (const v of o.versions || []) {
      const x = byV[v.version] || { practice: [], race: [] };
      const latest = {};
      for (const d of x.practice) if (!latest[d.scenario] || latest[d.scenario].created_at < d.created_at) latest[d.scenario] = d;
      const prac = Object.values(latest);
      items.push(`<li><b style="color:${vcol(v.version)}">${esc(v.version)}</b> (${esc(v.status)}): ${esc(v.notes)}${prac.length ? ` <b>${prac.filter(d => d.passed).length}/${prac.length}</b> practice drills.` : ""}</li>`);
      for (const r of x.race) items.push(`<li>Race on <b>${esc(v.version)}</b>: ${r.results?.race?.capybaras} capybaras, ${r.results?.race?.refunds} refunds, ${r.results?.race?.bookings} bookings, ${r.results?.race?.emails} emails to the customer → <b>${r.passed ? "PASS" : "FAIL"}</b></li>`);
    }
    $("#timeline").innerHTML = items.join("");
  }

  function barChart(rows, max, fmt, warnAboveOne = false) {
    const W = 560, H = 260, pad = 40, bw = Math.min(90, (W - pad * 2) / Math.max(1, rows.length) - 22);
    let s = `<line x1="${pad}" y1="${H - 40}" x2="${W - 10}" y2="${H - 40}" stroke="#d8c8ae" stroke-width="2"/>`;
    rows.forEach((r, i) => {
      const x = pad + 14 + i * (bw + 22);
      const h = (H - 80) * (max ? r.val / max : 0);
      const fill = warnAboveOne ? (r.val === 1 ? "#2f9e6a" : "#d2493f") : vcol(r.v);
      s += `<rect x="${x}" y="${H - 40 - h}" width="${bw}" height="${Math.max(2, h)}" rx="10" fill="${fill}"/>`;
      s += `<text class="lbl" x="${x + bw / 2}" y="${H - 48 - h}" text-anchor="middle">${esc(r.label ?? fmt(r.val))}</text>`;
      s += `<text x="${x + bw / 2}" y="${H - 18}" text-anchor="middle">${esc(r.v)}</text>`;
    });
    return s;
  }

  // ---------------------------------------------------------------- night school
  async function renderSchool() {
    const d = await api("/api/lessons");
    $("#lessons").innerHTML = d.lessons.map(l => {
      const g = l.guard || {};
      const guards = (g.guards || []).map(x => x === "approval_over_usd" ? `approval over $${g.approval_over_usd || 200}` : x.replace(/_/g, " "));
      return `<div class="lesson" style="border-left-color:${vcol(l.introduced_in)}">
        <div class="meta">learned for <b>${esc(l.introduced_in)}</b> from failure <b>${esc(l.failure)}</b> · recalled ${l.times_applied || 0}×</div>
        <h3>${esc(l.title)}</h3><p>${esc(l.rule)}</p>
        <div>${guards.map(x => `<span class="g">policy: ${esc(x)}</span>`).join("")}</div>
        <div class="meta" style="margin-top:6px">source shift <code>${esc(l.source_session)}</code></div>
      </div>`;
    }).join("") || `<div class="card">No lessons yet. Night school runs after a practice day.</div>`;
    try {
      const cb = await api("/api/casebook");
      $("#casebook").innerHTML = (cb.answers || []).map(x => `<div class="qa"><div class="q">${esc(x.q)}</div><div class="a">${esc(String(x.a).slice(0, 700)).replace(/\*\*(.+?)\*\*/g, "<b>$1</b>")}</div></div>`).join("")
        || `<div class="meta">The casebook fills as shifts close (Cognee dataset <code>${esc(cb.dataset)}</code>).</div>`;
    } catch (e) { /* casebook optional */ }
    $("#gen-drills").innerHTML = d.scenarios.map(s => `<li><b>${esc(s.name)}</b> <span class="meta">from <code>${esc(s.source_session)}</code></span></li>`).join("");
  }

  // ---------------------------------------------------------------- races
  async function renderRaces() {
    const drills = (await api("/api/drills?limit=400")).filter(d => d.scenario === "race").sort((a, b) => (a.created_at < b.created_at ? -1 : 1)).slice(-2);
    $("#races").innerHTML = drills.map(d => {
      const r = d.results.race;
      let firstRefund = null;
      const cells = r.by_capy.map(c => {
        let cls = "", lab = "saw it was done";
        const claimed = (r.claims || []).length > 0;
        if (c.refunded) { cls = firstRefund ? "dupe" : "won"; lab = firstRefund ? "refunded AGAIN" : (claimed ? "won the claim" : "refunded first"); firstRefund = firstRefund || c.capy; }
        else if (c.blocked_duplicates) { cls = "blocked"; lab = "blocked by claim"; }
        return `<div class="c ${cls}">${capySVG(vcol(c.version))}<div class="r">${esc(c.capy)}</div><div>${lab}</div></div>`;
      }).join("");
      return `<div class="race">
        <h3>Race on <span style="color:${vcol(d.agent_version)}">${esc(d.agent_version)}</span></h3>
        <div class="verdict ${d.passed ? "good" : "bad"}">${d.passed ? "Exactly once. PASS" : "Money moved twice. FAIL"}</div>
        <div class="counters"><div><b>${r.refunds}</b><span>Stripe refunds</span></div><div><b>${r.bookings}</b><span>QuickBooks bookings</span></div><div><b>${r.emails}</b><span>emails to Jess</span></div><div><b>${(r.claims || []).length}</b><span>claims in SingleStore</span></div></div>
        <div class="lineup">${cells}</div>
      </div>`;
    }).join("") || `<div class="card">No races yet.</div>`;
  }

  // ---------------------------------------------------------------- shifts
  async function renderShifts() {
    const rows = await api("/api/sessions?limit=120");
    $("#shift-table").innerHTML = `<tr><th>Capybara</th><th>Version</th><th>Scenario</th><th>Mode</th><th>Result</th><th>Tools</th><th>SIE cost</th></tr>` + rows.map(s => {
      const v = s.verdict || {};
      const res = s.status === "running" ? `<span class="badge run">on shift</span>` : (v.passed === true ? `<span class="badge pass">pass</span>` : v.passed === false ? `<span class="badge fail">fail</span>` : esc(s.status));
      return `<tr data-id="${esc(s.session_id)}"><td><b>${esc(s.capy_name)}</b></td><td style="color:${vcol(s.agent_version)}">${esc(s.agent_version)} <span class="meta">${esc(s.variant)}</span></td><td>${esc(s.scenario || "")}</td><td>${esc(s.mode)}</td><td>${res}</td><td>${s.tool_calls}</td><td>${money(s.cost_usd)}</td></tr>`;
    }).join("");
    $$("#shift-table tr[data-id]").forEach(tr => tr.addEventListener("click", () => transcript(tr.dataset.id)));
    if (rows[0]) transcript(rows[0].session_id);
  }
  async function transcript(id) {
    const d = await api(`/api/session/${encodeURIComponent(id)}`);
    $("#tx-title").textContent = `${d.session?.capy_name} · ${d.session?.agent_version} · ${d.session?.scenario || d.session?.mode}`;
    $("#transcript").innerHTML = d.events.map(e => `<li class="${esc(e.kind)}"><span class="k">${KIND[e.kind] || e.kind}</span>${esc(e.summary)}</li>`).join("");
  }
  window.capTranscript = transcript;

  stack();
  setInterval(stack, 15000);
  if (params.get("tab")) showTab(params.get("tab"));
})();
