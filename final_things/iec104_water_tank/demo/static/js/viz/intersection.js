// Traffic-signal intersection visualization (NTCIP / SNMP signal-override attack).
// Live read over SNMP (watch_process SignalReader, plc-signals:161, NTCIP 1202):
//   greens/yellows/reds phase bitmaps -> main street (N/S, phase 2) + cross street
//   (E/W, phase 4) signal state, and a conflict flag when both are green.
//
// Normal operation cycles the two streets safely (never both green). The NTCIP
// signal-override attack SNMP-SETs phaseControlGroupHold so both approaches are held
// green at once - the conflicting-greens condition a controller's conflict monitor
// exists to prevent. Restore clears the hold and the safe cycle resumes.
registerViz({
  kind: "intersection",
  title: "Traffic Signal Controller",

  map(raw) {
    return {
      online: raw.online === true,
      main: raw.main,                 // green | yellow | red | dark   (N/S)
      cross: raw.cross,               // green | yellow | red | dark   (E/W)
      greens: raw.greens,
      conflict: raw.conflict === true,
    };
  },

  build(stage) {
    const head = (id, cx, cy) => `
      <g>
        <rect class="sig-visor" x="${cx - 15}" y="${cy - 35}" width="30" height="70" rx="7"/>
        <rect class="sig-head" x="${cx - 13}" y="${cy - 33}" width="26" height="66" rx="6"/>
        <circle class="sig-lamp sig-red off"   id="${id}-r" cx="${cx}" cy="${cy - 19}" r="8"/>
        <circle class="sig-lamp sig-amber off" id="${id}-y" cx="${cx}" cy="${cy}"      r="8"/>
        <circle class="sig-lamp sig-green off" id="${id}-g" cx="${cx}" cy="${cy + 19}" r="8"/>
      </g>`;

    stage.innerHTML = `
      <div class="viz-readouts">
        <div class="ro"><span class="ro-v" data-r="main">--</span><span class="ro-u">MAIN N/S</span></div>
        <div class="ro"><span class="ro-v" data-r="cross">--</span><span class="ro-u">CROSS E/W</span></div>
        <div class="ro"><span class="ro-v" data-r="grn">--</span><span class="ro-u">GREENS (hex)</span></div>
        <div class="ro"><span class="ro-v" data-r="st">--</span><span class="ro-u">STATUS</span></div>
      </div>
      <svg class="sig-svg" viewBox="0 0 560 300" role="img" aria-label="Traffic signal intersection">
        <rect class="sig-ground" x="0" y="0" width="560" height="300"/>
        <!-- roads -->
        <rect class="sig-road" x="226" y="0" width="108" height="300"/>
        <rect class="sig-road" x="0" y="101" width="560" height="98"/>
        <!-- lane centre-lines (dashed), broken at the junction -->
        <line class="sig-lane" x1="280" y1="4"   x2="280" y2="98"/>
        <line class="sig-lane" x1="280" y1="202" x2="280" y2="296"/>
        <line class="sig-lane" x1="4"   y1="150" x2="222" y2="150"/>
        <line class="sig-lane" x1="338" y1="150" x2="556" y2="150"/>
        <!-- stop bars -->
        <rect class="sig-stop" x="230" y="94"  width="48" height="4"/>
        <rect class="sig-stop" x="282" y="202" width="48" height="4"/>
        <rect class="sig-stop" x="222" y="104" width="4"  height="44"/>
        <rect class="sig-stop" x="334" y="152" width="4"  height="44"/>
        <!-- conflict hazard flash over the junction -->
        <rect class="sig-hazard" id="sig-hazard" x="226" y="101" width="108" height="98" opacity="0"/>
        <!-- four signal heads -->
        ${head("n", 190, 62)}${head("s", 370, 238)}
        ${head("w", 130, 150)}${head("e", 430, 150)}
        <text class="sig-dir" x="190" y="20">N</text>
        <text class="sig-dir" x="370" y="292">S</text>
        <text class="sig-dir" x="130" y="112">W</text>
        <text class="sig-dir" x="430" y="112">E</text>
      </svg>`;

    const q = s => stage.querySelector(s);
    const lamp = id => ({ r: q(`#${id}-r`), y: q(`#${id}-y`), g: q(`#${id}-g`) });
    return {
      stage,
      roMain: q('[data-r="main"]'), roCross: q('[data-r="cross"]'), roGrn: q('[data-r="grn"]'), roSt: q('[data-r="st"]'),
      hazard: q('#sig-hazard'),
      heads: { n: lamp("n"), s: lamp("s"), w: lamp("w"), e: lamp("e") },
    };
  },

  clear(refs) {
    refs.roMain.textContent = refs.roCross.textContent = refs.roGrn.textContent = refs.roSt.textContent = "--";
    [refs.roMain, refs.roCross, refs.roSt].forEach(el => el.style.color = "");
    Object.values(refs.heads).forEach(h => this._setHead(h, "dark"));
    refs.hazard.setAttribute("opacity", "0");
    refs.hazard.setAttribute("class", "sig-hazard");
  },

  _setHead(h, state) {
    const set = (el, base, on) => el.setAttribute("class", "sig-lamp " + base + (on ? " on" : " off"));
    set(h.r, "sig-red", state === "red");
    set(h.y, "sig-amber", state === "yellow");
    set(h.g, "sig-green", state === "green");
  },

  update(refs, v) {
    if (!v.online || v.main == null) { this.clear(refs); return { level: "offline", msg: "" }; }
    const cap = s => (s || "dark").toUpperCase();
    const col = s => s === "green" ? "var(--ok)" : s === "yellow" ? "var(--warn)" : s === "red" ? "var(--bad)" : "var(--muted)";

    this._setHead(refs.heads.n, v.main);
    this._setHead(refs.heads.s, v.main);
    this._setHead(refs.heads.w, v.cross);
    this._setHead(refs.heads.e, v.cross);

    refs.roMain.textContent = cap(v.main);
    refs.roCross.textContent = cap(v.cross);
    refs.roMain.style.color = col(v.main);
    refs.roCross.style.color = col(v.cross);
    refs.roGrn.textContent = v.greens == null ? "--" : "0x" + v.greens.toString(16).padStart(2, "0").toUpperCase();
    refs.roSt.textContent = v.conflict ? "CONFLICT" : "NOMINAL";
    refs.roSt.style.color = v.conflict ? "var(--bad)" : "var(--ok)";

    refs.hazard.setAttribute("class", "sig-hazard" + (v.conflict ? " active" : ""));
    refs.hazard.setAttribute("opacity", v.conflict ? "1" : "0");

    if (v.conflict)
      return { level: "critical", msg: "SIGNAL CONFLICT - N/S and E/W green together, conflict monitor should flash - collision risk" };
    return { level: "normal", msg: "" };
  },
});
