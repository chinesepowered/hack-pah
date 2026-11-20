// CapyTeam stage: a full-screen presentation of the town, used to record the demo video.
// Nothing here invents data. Boards, captions and replays are filled from the same API the app uses.
(function () {
  const $ = (s, el = document) => el.querySelector(s);
  const $$ = (s, el = document) => [...el.querySelectorAll(s)];
  const UI = window.CAPUI;
  const el = (tag, cls, html, id) => {
    const x = document.createElement(tag);
    if (cls) x.className = cls;
    if (html != null) x.innerHTML = html;
    if (id) x.id = id;
    return x;
  };
  let built = false;

  function build() {
    if (built) return;
    built = true;
    const town = $("#town");
    town.appendChild(el("div", "hud", `<div class="hud-label" id="hud-label"></div><div class="hud-counters" id="hud-counters"></div>`));
    town.appendChild(el("div", "fireflies", Array.from({ length: 18 }, (_, i) =>
      `<i style="left:${(i * 61 + 7) % 94 + 3}%;top:${(i * 37 + 11) % 78 + 12}%;animation-delay:${-(i * 0.8)}s;animation-duration:${5 + (i % 4)}s"></i>`).join("")));
    document.body.appendChild(el("div", "lower",
      `<div class="cap"><div class="cap-chips" id="cap-chips"></div><div class="cap-text" id="cap-text"></div></div>
       <div class="lowwrap"><div class="lowhead"><i></i>Live from SingleStore</div><ol class="lowtick" id="lowtick"></ol></div>`, "lower"));
    document.body.appendChild(el("aside", "board", "", "board"));
    document.body.appendChild(el("div", "curtain", "", "curtain"));
    document.body.appendChild(el("div", "toast", "", "toast"));
    document.body.appendChild(el("div", "shots", "", "shots"));
  }

  // ---- modes
  window.capStage = on => { build(); document.body.classList.toggle("stage", !!on); document.body.classList.add("intown"); UI.hud(); };
  window.capShow = name => { window.capTab(name); document.body.classList.toggle("intown", name === "town"); window.scrollTo(0, 0); };
  window.capSplit = on => document.body.classList.toggle("split", !!on);
  window.capNight = on => document.body.classList.toggle("night", !!on);
  window.capHud = (label, counters = true) => {
    build();
    $("#hud-label").textContent = label || "";
    $("#hud-label").style.visibility = label ? "visible" : "hidden";
    $("#hud-counters").style.visibility = counters ? "visible" : "hidden";
  };

  // ---- board: a big readable panel. spec = {eyebrow, title, big, bigNote, sub, items:[{h, p, tags, cls, html}], foot, wide}
  window.capBoard = spec => {
    build();
    const b = $("#board");
    const items = (spec.items || []).map(it =>
      `<div class="b-item ${it.cls || ""}">${it.h ? `<h3>${it.h}</h3>` : ""}${it.p ? `<p>${it.p}</p>` : ""}${it.html || ""}${(it.tags || []).map(t => `<span class="tag">${t}</span>`).join("")}</div>`).join("");
    // mascots: capybaras at the foot of a side board, e.g. [{scarf: "#9a8f84", acc: "leaf", mood: "oops"}]
    const mascots = (spec.mascots || []).map(m => `<div class="b-mascot ${m.mood || ""}">${UI.capySVG(m.scarf || "#e07b39", { acc: m.acc || "" })}${m.label ? `<span style="background:${m.scarf}">${UI.esc(m.label)}</span>` : ""}</div>`).join("");
    b.className = `board ${spec.wide ? "wide" : ""}`;
    b.innerHTML = `${spec.eyebrow ? `<div class="b-eyebrow">${spec.eyebrow}</div>` : ""}${spec.title ? `<h2>${spec.title}</h2>` : ""}`
      + `${spec.big ? `<div class="b-big">${spec.big}${spec.bigNote ? `<small>${spec.bigNote}</small>` : ""}</div>` : ""}${spec.sub ? `<div class="b-sub">${spec.sub}</div>` : ""}`
      + `<div class="b-items">${items}</div>${spec.foot ? `<div class="b-foot">${spec.foot}</div>` : ""}${mascots ? `<div class="b-mascots">${mascots}</div>` : ""}`;
    void b.offsetWidth;
    b.classList.add("show");
  };
  window.capBoardReveal = n => $$("#board .b-item").forEach((x, i) => x.classList.toggle("show", i < n));
  window.capBoardFoot = () => $("#board .b-foot")?.classList.add("show");
  window.capBoardHide = () => $("#board")?.classList.remove("show");

  // ---- actors
  window.capWalk = (id, name, version, building) => { UI.ensureCapy({ session_id: id, capy_name: name, agent_version: version }); UI.moveTo(id, building); UI.hud(); };
  window.capSay = (id, text, cls) => UI.bubble(id, text, cls || "");
  window.capEmote = (id, kind) => UI.emote(id, kind);
  window.capStampAt = (building, text, cls) => UI.stamp(building, text, cls || "pass");

  // ---- spotlight an element of the real app (proof shots)
  window.capSpot = (sel, block = "center") => {
    $$(".spot").forEach(x => x.classList.remove("spot"));
    const x = sel && $(sel);
    if (!x) return;
    x.classList.add("spot");
    x.scrollIntoView({ behavior: "smooth", block });
  };

  // spotlight the first element matching `sel` whose text contains `text`
  window.capSpotText = (sel, text, block = "center") => {
    $$(".spot").forEach(x => x.classList.remove("spot"));
    const x = $$(sel).find(n => n.textContent.includes(text));
    if (!x) return;
    x.classList.add("spot");
    x.scrollIntoView({ behavior: "smooth", block });
  };

  // ---- title and end cards
  window.capCurtain = (kind, data = {}) => {
    build();
    const c = $("#curtain");
    document.body.classList.toggle("curtained", !!kind);
    if (!kind) { c.classList.remove("show"); return; }
    if (kind === "title") {
      c.innerHTML = `<div class="c-logo">${UI.capySVG("#e07b39", { acc: "yuzu" })}</div><h1>CapyTeam</h1><p>${UI.esc(data.line || "Your back office, run by capybaras that learn from every shift")}</p>`;
    } else {
      const row = ["v1", "v2", "v3"].map((v, i) => `<div class="c-mini">${UI.capySVG(UI.vcol(v), { acc: ["leaf", "flower", "yuzu"][i] })}<span style="background:${UI.vcol(v)}">${v}</span></div>`).join("");
      c.innerHTML = `<div class="c-row">${row}</div><h1>CapyTeam</h1><p>${UI.esc(data.line || "Better every night")}</p>`
        + `<div class="c-stack">${(data.stack || []).map(([k, label]) => `<span class="chip ${UI.esc(k)}">${UI.esc(label)}</span>`).join("")}</div>`;
    }
    c.classList.add("show");
  };

  // ---- a centered announcement (for example a new lesson)
  window.capToast = (html, ms = 3200) => {
    build();
    const t = $("#toast");
    t.innerHTML = html;
    t.classList.add("show");
    clearTimeout(t._t);
    if (ms) t._t = setTimeout(() => t.classList.remove("show"), ms);
  };

  // ---- full-screen screenshots (for example Amplitude's own charts), cross-fading with a slow zoom
  window.capShots = (urls, ms) => {
    build();
    const o = $("#shots");
    if (!urls || !urls.length) { o.classList.remove("show"); o.innerHTML = ""; return; }
    const per = ms / urls.length;
    o.innerHTML = urls.map(u => `<img src="${UI.esc(u)}">`).join("");
    o.classList.add("show");
    $$("img", o).forEach((im, i) => {
      im.style.transitionDuration = `.7s, ${per / 1000 + 1}s`;
      setTimeout(() => { im.style.opacity = 1; im.style.transform = "scale(1.045)"; }, i * per + 30);
      if (i < urls.length - 1) setTimeout(() => { im.style.opacity = 0; }, (i + 1) * per);
    });
  };
})();
