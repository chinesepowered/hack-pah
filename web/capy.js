// CapyTeam artwork: original capybara sprites and town buildings, drawn as inline SVG.
(function () {
  const VCOLOR = { v1: "#9a8f84", v2: "#2f9e8f", v3: "#e07b39", v4: "#c2477f", v5: "#3f6fd8" };

  // A chibi capybara: loaf body, big round head facing you, sparkly eyes, blush, and a scarf in its version color.
  // opts.acc picks a little extra on its head: "yuzu" (the classic capybara citrus), "flower", "leaf" or none.
  const INK = "#6b4325";
  const ACCESSORIES = {
    yuzu: `<g><circle cx="44.5" cy="5.4" r="3.7" fill="#f8a532" stroke="#b5650f" stroke-width=".9"/>
           <circle cx="43.3" cy="4.3" r=".9" fill="#fff" opacity=".55"/>
           <path d="M44.6 1.9 q2.4 -1.9 4.6 -.3 q-2.3 1.5 -4.6 .3 z" fill="#5fb55a" stroke="#3d7f39" stroke-width=".5"/></g>`,
    flower: `<g transform="translate(55.2 6.6)">${[0, 72, 144, 216, 288].map(a =>
              `<ellipse cx="0" cy="-2" rx="1.3" ry="1.9" fill="#ffd9e6" stroke="#e58fb0" stroke-width=".45" transform="rotate(${a})"/>`).join("")}
             <circle r="1.1" fill="#f7c948"/></g>`,
    leaf: `<path d="M42 7.2 q1.5 -5.6 7 -5.4 q-1.2 5.3 -7 5.4 z" fill="#79c267" stroke="#3f8a35" stroke-width=".6"/>
           <path d="M42.4 6.8 q2.6 -2.3 5.6 -4.4" stroke="#3f8a35" stroke-width=".45" fill="none"/>`,
  };

  function capySVG(scarf, opts = {}) {
    const flip = opts.flip ? 'transform="translate(64,0) scale(-1,1)"' : "";
    const acc = ACCESSORIES[opts.hat ? "yuzu" : opts.acc] || "";
    return `<svg viewBox="0 0 64 46" xmlns="http://www.w3.org/2000/svg"><g ${flip}>
      <g fill="#9e6c44" stroke="${INK}" stroke-width="1.1">
        <rect x="8.5" y="35" width="6.5" height="9.5" rx="3.2"/><rect x="17" y="36" width="6.5" height="8.5" rx="3.2"/>
        <rect x="31" y="36" width="6.5" height="8.5" rx="3.2"/><rect x="39.5" y="35" width="6.5" height="9.5" rx="3.2"/>
      </g>
      <ellipse cx="24.5" cy="29.5" rx="20" ry="12.8" fill="#c79461" stroke="${INK}" stroke-width="1.3"/>
      <ellipse cx="20.5" cy="24.6" rx="12" ry="5" fill="#d9ab78" opacity=".7"/>
      <path d="M8.5 31 q2.5 3.5 6.5 4.5" stroke="${INK}" stroke-width=".8" fill="none" opacity=".45" stroke-linecap="round"/>
      <rect x="29.5" y="7.5" width="30" height="25" rx="11" fill="#d3a06d" stroke="${INK}" stroke-width="1.3"/>
      <g stroke="${INK}" stroke-width="1"><ellipse cx="32.6" cy="10.4" rx="2.6" ry="2.2" fill="#a8734a"/><ellipse cx="56.5" cy="10.1" rx="2.6" ry="2.2" fill="#a8734a"/></g>
      <ellipse cx="32.7" cy="10.7" rx="1.2" ry=".95" fill="#eeb097"/><ellipse cx="56.4" cy="10.4" rx="1.2" ry=".95" fill="#eeb097"/>
      <ellipse cx="47" cy="24.4" rx="10.4" ry="6.6" fill="#e6c096"/>
      <g class="eyes">
        <circle cx="39" cy="16.4" r="2.6" fill="#24160c"/><circle cx="39.9" cy="15.4" r=".95" fill="#fff"/><circle cx="38.3" cy="17.3" r=".42" fill="#fff"/>
        <circle cx="55" cy="16" r="2.6" fill="#24160c"/><circle cx="55.9" cy="15" r=".95" fill="#fff"/><circle cx="54.3" cy="16.9" r=".42" fill="#fff"/>
      </g>
      <g class="eyes-happy" fill="none" stroke="#24160c" stroke-width="1.5" stroke-linecap="round">
        <path d="M36.5 17.4 q2.5 -3.4 5 0"/><path d="M52.5 17 q2.5 -3.4 5 0"/>
      </g>
      <path class="sweat" d="M61 8.6 q2.6 3.8 0 5.6 q-2.6 -1.8 0 -5.6 z" fill="#8fd0f5" stroke="#3b8fc4" stroke-width=".6"/>
      <ellipse cx="35.8" cy="22.6" rx="2.7" ry="1.6" fill="#f3887c" opacity=".55"/><ellipse cx="57.2" cy="22.2" rx="1.9" ry="1.5" fill="#f3887c" opacity=".55"/>
      <rect x="43.4" y="19.4" width="7.2" height="3.3" rx="1.65" fill="#5a3620"/><ellipse cx="45.3" cy="21.1" rx=".75" ry=".55" fill="#24140a"/><ellipse cx="48.7" cy="21.1" rx=".75" ry=".55" fill="#24140a"/><ellipse cx="45.6" cy="19.9" rx="1.1" ry=".35" fill="#fff" opacity=".45"/>
      <path d="M44.55 25 q1.22 1.5 2.45 0 q1.22 1.5 2.45 0" stroke="#4a2c18" stroke-width="1" fill="none" stroke-linecap="round"/>
      <path d="M32 29.6 q12.5 6.4 25.5 0 l.6 3.6 q-13.3 6.8 -26.7 0 z" fill="${scarf}" stroke="${INK}" stroke-width=".9" stroke-linejoin="round"/>
      <path d="M36.2 32.6 l-.8 7.2 q2.1 1.2 4.3 0 l-.2 -6.4 z" fill="${scarf}" stroke="${INK}" stroke-width=".9" stroke-linejoin="round"/>
      ${acc}
    </g></svg>`;
  }

  // the same capybara always wears the same accessory
  function accessoryFor(name) {
    let h = 0;
    for (const ch of String(name || "")) h = (h * 31 + ch.charCodeAt(0)) >>> 0;
    return ["yuzu", "flower", "", "leaf", "yuzu", ""][h % 6];
  }

  const B = {
    home:    { x: 40,   y: 70,  name: "Maya's House",  sub: "the owner's chat",     wall: "#f6c28f", roof: "#c2603d", icon: "heart" },
    post:    { x: 300,  y: 70,  name: "Post Office",   sub: "Gmail",                wall: "#f9dc7c", roof: "#d0453a", icon: "mail" },
    bank:    { x: 560,  y: 70,  name: "Stripe Bank",   sub: "Stripe",               wall: "#c9c5fb", roof: "#635bff", icon: "coin" },
    ledger:  { x: 820,  y: 70,  name: "Ledger Hall",   sub: "QuickBooks",           wall: "#b6e6ad", roof: "#2ca01c", icon: "book" },
    fire:    { x: 1080, y: 70,  name: "Fire Station",  sub: "Firedrill drills",     wall: "#f6b0ab", roof: "#c0392b", icon: "bell" },
    obs:     { x: 1340, y: 70,  name: "Observatory",   sub: "Amplitude + Statsig",  wall: "#b9d3f8", roof: "#1e61f0", icon: "scope" },
    lab:     { x: 170,  y: 470, name: "SIE Lab",       sub: "Superlinked models",   wall: "#dfcdf3", roof: "#7c4dbe", icon: "flask" },
    archive: { x: 500,  y: 470, name: "The Archive",   sub: "SingleStore",          wall: "#d6c8f7", roof: "#8a35d1", icon: "db" },
    harbor:  { x: 830,  y: 470, name: "Harbor",        sub: "Airbyte",              wall: "#c4e6f2", roof: "#615efc", icon: "boat" },
    school:  { x: 1160, y: 470, name: "Night School",  sub: "the coach",            wall: "#f6dcae", roof: "#8a5a33", icon: "cap" },
  };
  const W = 220, H = 175;

  function icon(kind, cx, cy, color) {
    const c = color;
    switch (kind) {
      case "heart": return `<path d="M${cx} ${cy + 12} l-15 -15 a8 8 0 0 1 15 -9 a8 8 0 0 1 15 9 z" fill="${c}"/>`;
      case "mail": return `<rect x="${cx - 20}" y="${cy - 12}" width="40" height="26" rx="4" fill="#fff" stroke="${c}" stroke-width="3"/><path d="M${cx - 20} ${cy - 10} l20 14 l20 -14" fill="none" stroke="${c}" stroke-width="3"/>`;
      case "coin": return `<circle cx="${cx}" cy="${cy}" r="16" fill="#ffd75e" stroke="#b9801a" stroke-width="3"/><text x="${cx}" y="${cy + 7}" text-anchor="middle" font-family="Fredoka" font-weight="700" font-size="20" fill="#8a5a10">$</text>`;
      case "book": return `<path d="M${cx - 20} ${cy - 12} h18 v26 h-18 z M${cx + 2} ${cy - 12} h18 v26 h-18 z" fill="#fff" stroke="${c}" stroke-width="3"/><path d="M${cx - 16} ${cy - 4} h10 M${cx - 16} ${cy + 3} h10 M${cx + 6} ${cy - 4} h10 M${cx + 6} ${cy + 3} h10" stroke="${c}" stroke-width="2"/>`;
      case "bell": return `<path d="M${cx - 14} ${cy + 9} q0 -22 14 -22 q14 0 14 22 z" fill="#ffd75e" stroke="#b9801a" stroke-width="3"/><circle cx="${cx}" cy="${cy + 13}" r="4" fill="#b9801a"/>`;
      case "scope": return `<path d="M${cx - 22} ${cy + 10} a22 22 0 0 1 44 0 z" fill="#e8f0ff" stroke="${c}" stroke-width="3"/><rect x="${cx - 3}" y="${cy - 20}" width="6" height="20" fill="${c}" transform="rotate(30 ${cx} ${cy})"/>`;
      case "flask": return `<path d="M${cx - 6} ${cy - 16} h12 v10 l10 18 a4 4 0 0 1 -4 6 h-24 a4 4 0 0 1 -4 -6 l10 -18 z" fill="#fff" stroke="${c}" stroke-width="3"/><path d="M${cx - 11} ${cy + 8} h22 l3 6 h-28 z" fill="${c}" opacity=".6"/>`;
      case "db": return `<ellipse cx="${cx}" cy="${cy - 12}" rx="18" ry="6" fill="#fff" stroke="${c}" stroke-width="3"/><path d="M${cx - 18} ${cy - 12} v22 a18 6 0 0 0 36 0 v-22" fill="#fff" stroke="${c}" stroke-width="3"/><path d="M${cx - 18} ${cy - 1} a18 6 0 0 0 36 0" fill="none" stroke="${c}" stroke-width="3"/>`;
      case "boat": return `<path d="M${cx - 22} ${cy + 4} h44 l-8 12 h-28 z" fill="${c}"/><path d="M${cx} ${cy + 4} v-24 l14 18 z" fill="#fff" stroke="${c}" stroke-width="2"/>`;
      case "cap": return `<path d="M${cx - 24} ${cy - 4} l24 -12 l24 12 l-24 12 z" fill="#3a2a1a"/><path d="M${cx - 12} ${cy + 2} v9 q12 7 24 0 v-9" fill="#3a2a1a"/><path d="M${cx + 20} ${cy - 2} v14" stroke="#e0a527" stroke-width="3"/>`;
    }
    return "";
  }

  function building(key) {
    const b = B[key];
    const x = b.x, y = b.y;
    const roofPts = `${x - 10},${y + 52} ${x + W / 2},${y} ${x + W + 10},${y + 52}`;
    const windows = [0, 1, 2].map(i => `<rect class="win" x="${x + 22 + i * 64}" y="${y + 70}" width="44" height="30" rx="6" fill="#fffbe9" stroke="#7a5b3c" stroke-width="2"/>`).join("");
    return `<g class="building" id="b-${key}">
      <ellipse class="glow" cx="${x + W / 2}" cy="${y + H - 10}" rx="${W * 0.72}" ry="62" fill="${b.roof}"/>
      <rect x="${x + 6}" y="${y + 50}" width="${W - 12}" height="${H - 50}" rx="10" fill="${b.wall}" stroke="#7a5b3c" stroke-width="3"/>
      <polygon points="${roofPts}" fill="${b.roof}" stroke="#5c3d24" stroke-width="3" stroke-linejoin="round"/>
      ${windows}
      <rect x="${x + W / 2 - 20}" y="${y + H - 52}" width="40" height="52" rx="8" fill="#8a5a33" stroke="#5c3d24" stroke-width="2"/>
      <circle cx="${x + W / 2 + 10}" cy="${y + H - 26}" r="2.6" fill="#ffd75e"/>
      <g transform="translate(0,0)">${icon(b.icon, x + W / 2, y + 30, b.roof)}</g>
      <rect x="${x + 14}" y="${y + H + 10}" width="${W - 28}" height="50" rx="12" fill="#fffaf2" stroke="#cdb593" stroke-width="2"/>
      <text class="bname" x="${x + W / 2}" y="${y + H + 32}" text-anchor="middle">${b.name}</text>
      <text class="bsub" x="${x + W / 2}" y="${y + H + 51}" text-anchor="middle">${b.sub}</text>
      <g class="flame"><path d="M${x + W - 40} ${y + 30} q-14 -22 6 -40 q-2 16 10 22 q6 -10 4 -18 q16 18 2 36 z" fill="#ff7a1a" stroke="#d04a10" stroke-width="2"/>
        <text x="${x + W - 40}" y="${y + 52}" text-anchor="middle" font-family="Fredoka" font-weight="700" font-size="15" fill="#d04a10">OUTAGE</text></g>
    </g>`;
  }

  function townSVG() {
    const trees = [[300, 330], [1060, 330], [120, 690], [1480, 690], [1490, 420], [80, 420], [700, 700], [1020, 700]]
      .map(([tx, ty]) => `<g><rect x="${tx - 5}" y="${ty}" width="10" height="22" fill="#8a5a33"/><circle cx="${tx}" cy="${ty - 6}" r="24" fill="#8cc46c"/><circle cx="${tx - 12}" cy="${ty + 2}" r="15" fill="#7db85e"/></g>`).join("");
    const flowers = Array.from({ length: 26 }, (_, i) => {
      const fx = (i * 157) % 1580 + 10, fy = 360 + ((i * 89) % 2 ? 76 : -18) + (i % 3) * 3;
      return `<circle cx="${fx}" cy="${fy + 350 * (i % 2)}" r="4" fill="${["#f7a1c4", "#fff2a8", "#ffffff"][i % 3]}" opacity=".85"/>`;
    }).join("");
    return `
      <defs><pattern id="grass" width="40" height="40" patternUnits="userSpaceOnUse"><rect width="40" height="40" fill="#cfe6b4"/><path d="M8 30 l3 -7 l3 7 M26 14 l3 -7 l3 7" stroke="#b5d895" stroke-width="2" fill="none"/></pattern></defs>
      <rect width="1600" height="760" fill="url(#grass)"/>
      <rect x="0" y="335" width="1600" height="92" fill="#ead9bf"/>
      <rect x="0" y="333" width="1600" height="6" fill="#d9c3a0"/><rect x="0" y="423" width="1600" height="6" fill="#d9c3a0"/>
      ${Array.from({ length: 32 }, (_, i) => `<rect x="${i * 52 + 8}" y="378" width="28" height="6" rx="3" fill="#fff6e3"/>`).join("")}
      <path d="M790 640 q120 -30 260 0 v120 h-260 z" fill="#9fd3ea" opacity=".9"/>
      ${trees}${flowers}
      ${Object.keys(B).filter(k => k !== "school").map(building).join("")}
      <rect class="nightshade" width="1600" height="760" fill="#131c44"/>
      <g class="nightsky">${Array.from({ length: 34 }, (_, i) => `<circle cx="${(i * 211 + 37) % 1580 + 10}" cy="${(i * 97 + 13) % 300 + 8 + (i % 3) * 150}" r="${1.2 + (i % 3) * 0.7}" fill="#fff6c9" opacity="${0.5 + (i % 4) * 0.12}"/>`).join("")}
        <path transform="translate(1540 46) rotate(-24)" d="M0 -26 A26 26 0 0 0 0 26 A36 36 0 0 1 0 -26 Z" fill="#fff3bf"/></g>
      ${building("school")}
    `;
  }

  function anchor(key) {
    const b = B[key];
    if (!b) return anchor("home");
    const below = b.y > 300;
    return { x: (b.x + W / 2) / 1600, y: (below ? 400 : 372) / 760 };
  }

  window.CAPY = { capySVG, accessoryFor, townSVG, anchor, BUILDINGS: B, VCOLOR };
})();
