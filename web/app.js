// CapyTeam town UI. Everything here is read from SingleStore through the CapyTeam API.
(function () {
  const $ = (s, el = document) => el.querySelector(s);
  const $$ = (s, el = document) => [...el.querySelectorAll(s)];
  const params = new URLSearchParams(location.search);
  const VIDEO = params.has("video");
  if (VIDEO) document.body.classList.add("video");
  const { capySVG, accessoryFor, townSVG, anchor, VCOLOR } = window.CAPY;
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
  const CHIPS = { singlestore: "SingleStore", amplitude: "Amplitude", statsig: "Statsig", sie: "Superlinked SIE", firedrill: "Firedrill", airbyte: "Airbyte", cognee: "Cognee" };
  const chipHTML = chips => (chips || []).map(k => `<span class="chip ${esc(k)}">${esc(CHIPS[k] || k)}</span>`).join("");
  window.capCaption = (text, ms = 4000, chips = []) => {
    const c = $("#caption");
    c.innerHTML = `${chipHTML(chips)}<span>${esc(text)}</span>`;
    c.classList.add("show");
    clearTimeout(capTimer);
    if (ms) capTimer = setTimeout(() => c.classList.remove("show"), ms);
    const lt = $("#cap-text");
    if (lt) { lt.textContent = text; $("#cap-chips").innerHTML = chipHTML(chips); }
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
  const stats = { shifts: new Set(), claims: 0, blocked: 0, lessons: 0, refunds: 0, emails: 0 };
  let refundsBy = {};     // "run|charge" -> refunds seen, to spot money moving twice
  const onStage = () => document.body.classList.contains("stage");
  const crowded = () => onStage() && stats.shifts.size > 4;   // in a crowd, only the moments that matter get a bubble

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
    const per = onStage() ? 5 : 6, sx = onStage() ? 0.05 : 0.034, sy = onStage() ? 0.088 : 0.055;
    const col = i % per, row = Math.floor(i / per);
    const dx = (col - (per - 1) / 2) * sx + (row % 2 ? sx / 2 : 0), dy = (row * sy) * (a.y > 0.5 ? 1 : -1);
    c.el.style.left = `${Math.min(0.955, Math.max(0.045, a.x + dx)) * 100}%`;
    c.el.style.top = `${(a.y + dy) * 100}%`;
    c.el.style.zIndex = String(10 + (a.y > 0.5 ? row : -row));
    c.el.classList.toggle("crowd", list.length > 3);
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
    el.style.setProperty("--blink", `${(-Math.random() * 5).toFixed(2)}s`);  // capybaras blink on their own schedules
    el.innerHTML = `${capySVG(vcol(v), { acc: accessoryFor(e.capy_name) })}<div class="capy-name">${esc(e.capy_name)}<span class="ver" style="background:${vcol(v)}">${esc(v)}</span></div><div class="bubble"></div>`;
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
    // one speaker per building; in a crowd, one speaker in the whole town
    for (const other of crowded() ? Object.keys(capys) : (occupancy[c.at] || [])) if (other !== id && capys[other]) { $(".bubble", capys[other].el).classList.remove("show"); capys[other].el.classList.remove("talk"); }
    c.el.classList.add("talk");
    const b = $(".bubble", c.el);
    b.classList.toggle("below", anchor(c.at).y < 0.5);
    b.className = `bubble show ${cls}`;
    b.textContent = text.length > 120 ? text.slice(0, 117) + "…" : text;
    clearTimeout(c.timer);
    c.timer = setTimeout(() => { b.classList.remove("show"); c.el.classList.remove("talk"); }, 3600);
  }

  // little expressions: happy eyes and sparkles, or a sweat drop
  function emote(id, kind) {
    const c = capys[id];
    if (!c) return;
    c.el.classList.remove("happy", "oops");
    c.el.classList.add(kind);
    clearTimeout(c.emo);
    c.emo = setTimeout(() => c.el.classList.remove(kind), 2600);
    if (kind !== "happy") return;
    for (let i = 0; i < 5; i++) {
      const sp = document.createElement("i");
      sp.className = "spark";
      sp.style.setProperty("--dx", `${(i - 2) * 0.3 + (Math.random() * 0.16 - 0.08)}`);
      sp.style.setProperty("--dy", `${-0.55 - Math.random() * 0.4}`);
      sp.style.animationDelay = `${i * 70}ms`;
      c.el.appendChild(sp);
      setTimeout(() => sp.parentNode && sp.parentNode.removeChild(sp), 1500);
    }
  }

  const stamps = {};      // "building|text" -> live stamp, so repeats re-ink one stamp instead of piling up
  function stamp(bkey, text, cls) {
    const key = `${bkey}|${text}`;
    let s = stamps[key];
    if (s && s.isConnected) {
      s.style.animation = "none"; void s.offsetWidth; s.style.animation = "";
    } else {
      const a = anchor(bkey);
      s = stamps[key] = document.createElement("div");
      s.className = `stamp ${cls}`;
      s.textContent = text;
      s.style.left = `${a.x * 100}%`;
      s.style.top = `${(a.y + (a.y > 0.5 ? 0.17 : -0.2)) * 100}%`;
      sprites.appendChild(s);
    }
    clearTimeout(s._t);
    s._t = setTimeout(() => { if (s.parentNode) s.parentNode.removeChild(s); }, 2600);
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
    lowTick(e, li);
  }

  // the stage's ticker shows one readable line at a time: the most telling event of each short window
  const LOW_RANK = { claim: 5, guard: 5, verdict: 5, lesson: 4, tool_result: 2, assistant: 2, user: 2, tool_call: 1 };
  let lowBest = null, lowTimer = null;
  function lowTick(e, li) {
    const lt = $("#lowtick");
    if (!lt || !(e.kind in LOW_RANK)) return;
    const rank = LOW_RANK[e.kind] + (e.kind === "tool_result" && (e.summary || "").startsWith("failed") ? 2 : 0);
    if (!lowBest || rank >= lowBest.rank) lowBest = { rank, li };
    if (lowTimer) return;
    const flush = () => {
      lowTimer = null;
      if (!lowBest) return;
      lt.prepend(lowBest.li.cloneNode(true));
      lowBest = null;
      while (lt.children.length > 4) lt.removeChild(lt.lastChild);
      lowTimer = setTimeout(flush, 850);
    };
    flush();
  }

  function hud() {
    const el = $("#hud-counters");
    if (!el) return;
    const twice = !!stats.twice;   // red only when the same charge really was refunded twice
    const items = [[stats.shifts.size, "on shift", ""], [stats.refunds, stats.refunds === 1 ? "refund made" : "refunds made", twice ? "bad" : ""],
                   [stats.emails, stats.emails === 1 ? "email sent" : "emails sent", ""], [stats.blocked, "duplicates blocked", "guard"]];
    el.innerHTML = items.filter(([n], i) => i === 0 || n > 0).map(([n, l, cls]) => `<span class="hc ${cls}"><b>${n}</b>${l}</span>`).join("");
  }

  function dayCard(e) {
    const runId = (e.session_id || "").replace(/-\d\d$/, "").replace(/-(cracked-mug|said-twice|stripe-down|big-deposit|fake-maya-email|workshop-invoice|acme-paid)$/, "");
    $("#day-title").textContent = e.mode === "race" ? `Race in progress (${runId})` : e.mode === "drill" ? "Fire drill at the station" : `Shift: ${runId}`;
    $("#day-stats").innerHTML = [
      [stats.shifts.size, "capybaras on shift"], [stats.claims, "money actions claimed"], [stats.blocked, "duplicates blocked"],
      [stats.refunds, "refunds made"], [stats.lessons, "lessons recalled"],
    ].map(([n, l]) => `<div class="s"><b>${n}</b>${l}</div>`).join("");
    hud();
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
    else if (e.kind === "verdict") { const pass = s.includes("PASS"); bubble(e.session_id, s, pass ? "good" : "bad"); stamp(b, pass ? "PASS" : "FAIL", pass ? "pass" : "fail"); emote(e.session_id, pass ? "happy" : "oops"); }
    else if (e.kind === "lesson") { stats.lessons++; bubble(e.session_id, s, "guard"); }
    else if (e.kind === "tool_result") {
      if (s.startsWith("ok: stripe_create_refund")) {
        stats.refunds++; coin("bank", "home");
        const run = e.mode === "race" ? String(e.session_id).replace(/-\d\d$/, "") : e.session_id;
        const key = `${run}|${(s.match(/"charge": "([^"]+)"/) || [])[1] || "?"}`;
        refundsBy[key] = (refundsBy[key] || 0) + 1;
        if (refundsBy[key] > 1) { stats.twice = true; bubble(e.session_id, "Refund sent... again?!", "bad"); stamp("bank", "PAID TWICE", "fail"); emote(e.session_id, "oops"); }
        else { bubble(e.session_id, "Refund sent!", "good"); emote(e.session_id, "happy"); }
      } else if (s.startsWith("ok: gmail_send")) { stats.emails++; if (!crowded()) bubble(e.session_id, "Email sent"); }
      else if (s.startsWith("failed")) {
        const by = s.match(/"by": "([^"]+)"/);
        if (/already_claimed/.test(s)) bubble(e.session_id, `${by ? by[1].replace(/ \(.*\)/, "") : "A teammate"} already did this one. Standing down.`, "guard");
        else if (/needs_owner_approval/.test(s)) bubble(e.session_id, "Over $200: asking Maya first.", "guard");
        else if (/payment_failed/.test(s)) bubble(e.session_id, "Refund didn't go through, so nothing gets booked.", "guard");
        else bubble(e.session_id, clean(e).replace(/^failed: /, "Uh oh: "), "bad");
        if (/unavailable/i.test(s) && b === "bank") { fire("bank"); emote(e.session_id, "oops"); }
      }
    } else if (e.kind === "tool_call") { if (!crowded()) bubble(e.session_id, clean(e)); }
    else if (e.kind === "user" || e.kind === "assistant" || e.kind === "model") { if (!crowded()) bubble(e.session_id, s); }
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
    stats.shifts = new Set(); stats.claims = 0; stats.blocked = 0; stats.lessons = 0; stats.refunds = 0; stats.emails = 0;
    refundsBy = {}; stats.twice = false;
    for (const x of $$(".stamp, .coin", sprites)) sprites.removeChild(x);
    $$(".building.fire").forEach(x => x.classList.remove("fire"));
    $("#ticker").innerHTML = "";
    if ($("#lowtick")) $("#lowtick").innerHTML = "";
    hud();
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
  // replay the same events squeezed into exactly `seconds` (long model waits are capped first)
  // `anchor` = {match, nth, at}: the nth event whose summary contains `match` lands `at` seconds in (narration sync)
  async function replayFit(prefixes, seconds, capGap = 2500, anchor = null) {
    let evs = [];
    for (const p of prefixes) evs = evs.concat(await api(`/api/events?run=${encodeURIComponent(p)}&limit=3000`));
    evs.sort((a, b) => (a.ts < b.ts ? -1 : a.ts > b.ts ? 1 : a.seq - b.seq));
    const ts = evs.map(e => Date.parse(String(e.ts).replace(" ", "T").slice(0, 23) + "Z"));
    const gaps = ts.map((t, i) => (i ? Math.min(capGap, Math.max(0, t - ts[i - 1])) : 0));
    const sum = (a, b) => gaps.slice(a, b).reduce((x, y) => x + y, 0) || 1;
    let j = -1, seen = 0;
    if (anchor) j = evs.findIndex(e => (e.summary || "").includes(anchor.match) && ++seen === (anchor.nth || 1));
    const k1 = j > 0 ? (anchor.at * 1000) / sum(0, j + 1) : (seconds * 1000) / sum(0, gaps.length);
    const k2 = j > 0 ? (Math.max(0.5, seconds - anchor.at) * 1000) / sum(j + 1, gaps.length) : k1;
    const token = window.__replayToken || 0;
    const t0 = performance.now();
    let acc = 0;
    for (let i = 0; i < evs.length; i++) {
      acc += gaps[i] * (i <= j ? k1 : k2);
      const wait = t0 + acc - performance.now();
      if (wait > 4) await new Promise(r => setTimeout(r, wait));
      if ((window.__replayToken || 0) !== token) return;
      onEvent(evs[i]);
    }
  }
  window.capReplayFit = (prefixes, seconds, capGap, anchor) => { replayFit(String(prefixes).split(","), seconds, capGap || 2500, anchor || null); };
  window.CAPUI = { ensureCapy, moveTo, bubble, stamp, emote, coin, capys, occupancy, stats, hud, anchor, capySVG, vcol, esc, api };
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
    api("/api/analytics").then(renderAnalytics).catch(() => {});
  }

  // the release experiment (Statsig assigns, SingleStore records) and the same sessions as Amplitude reports them
  const hbar = (label, n, of, color, note = "") => `<div class="hbar"><span class="hl">${label}</span>
      <span class="ht"><i style="width:${of ? Math.max(3, Math.round(100 * n / of)) : 0}%;background:${color}"></i></span>
      <span class="hv"><b>${of ? Math.round(100 * n / of) : 0}%</b> ${n}/${of}${note ? ` <em>${esc(note)}</em>` : ""}</span></div>`;
  function renderAnalytics(a) {
    window.__analytics = a;
    const x = a.experiment || {};
    const arms = (x.arms || []).map(r => hbar(`<b>${esc(r.variant)}</b> runs <b style="color:${vcol(r.version)}">${esc(r.version)}</b>`, Number(r.done), Number(r.shifts), vcol(r.version), "shifts done right")).join("");
    $("#exp").innerHTML = arms
      ? `${arms}<p class="meta">${x.assigned_by_statsig} of ${x.shifts} shifts were assigned by Statsig's <code>${esc(x.name)}</code> experiment. Each shift reports its outcome back to Statsig (<code>capyteam_shift_done</code> or <code>capyteam_shift_failed</code>).</p>`
      : `<p class="meta">No experiment shifts yet. Run <code>python scripts/experiment.py</code> once the <code>${esc(x.name || "capyteam_agent_release")}</code> experiment is started in Statsig.</p>`;
    const amp = a.amplitude || {};
    if (!amp.available) { $("#amp").innerHTML = `<p class="meta">Set <code>AMPLITUDE_SECRET_KEY</code> to read Amplitude's numbers back here.</p>`; return; }
    const byV = Object.entries(amp.by_version || {}).map(([v, d]) => hbar(`<b style="color:${vcol(v)}">${esc(v)}</b> drill pass rate`, d.passed, d.scored, vcol(v), `${d.sessions} sessions`)).join("");
    const xa = Object.entries(amp.experiment || {}).map(([g, d]) => `<b>${esc(g)}</b> ${d.passed}/${d.scored}`).join(" · ");
    $("#amp").innerHTML = `${byV}<p class="meta">${amp.totals.sessions} sessions, ${amp.totals.ai_responses} model responses and ${amp.totals.tool_calls} tool calls in Amplitude${xa ? `; the Statsig experiment by group: ${xa}` : ""}.
      Amplitude keeps our earlier test runs too, so its totals are larger than the final-run tables above.</p>`;
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
    try {
      const fd = await api("/api/firedrill");
      window.__firedrill = fd;
      const row = (x, extra) => `<li><b>${esc(x.name)}</b>${(x.checks || []).map(c => `<code class="chk">${esc(c)}</code>`).join("")}${(x.events || []).map(c => `<code class="chk ev">${esc(c)}</code>`).join("")} <span class="meta">${extra}</span></li>`;
      $("#gen-drills").innerHTML = fd.generated.map(x => row(x, `written by night school from <code>${esc(x.source)}</code>`)).join("");
      $("#lib-drills").innerHTML = fd.library.map(x => row(x, x.twin ? `practice-yard twin: <code>${esc(x.twin)}</code>` : "")).join("");
    } catch (e) { /* drill files optional */ }
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
        return `<div class="c ${cls}">${capySVG(vcol(c.version), { acc: accessoryFor(c.capy) })}<div class="r">${esc(c.capy)}</div><div>${lab}</div></div>`;
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
