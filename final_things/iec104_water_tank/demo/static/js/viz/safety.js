// Safety-Instrumented System visualization (TRITON / TRISIS).
// Live read (IEC-104 via watch_process, on the water PLC): level=tank %, pressure=bar,
// sis=SIS trip status (IOA 208), exploded=rupture (207), inlet_valve/outlet_valve/pump.
//
// The story TRITON tells: an independent SIS (Triconex safety controller) guards the
// tank - if level crosses the 90% trip point it commands an emergency shutdown (close
// inlet, open the ESD drain). TRITON first HALTS the safety program over TriStation, then
// overflows the tank. The SIS never trips, so the tank fills past 90% and ruptures. We
// read that straight off the process: level past the trip line with sis=false means the
// safety function was defeated.
registerViz({
  kind: "safety",
  title: "Safety-Instrumented System",

  map(raw) {
    return {
      level: raw.level,
      pressure: raw.pressure,
      tripped: raw.sis === true,          // SIS commanded emergency shutdown (IOA 208)
      exploded: raw.exploded === true,    // tank ruptured (IOA 207)
      inlet: raw.inlet_valve,
      outlet: raw.outlet_valve,           // ESD drain valve
      pump: raw.pump,
      online: raw.online,
    };
  },

  build(stage) {
    stage.innerHTML = `
      <div class="viz-readouts">
        <div class="ro"><span class="ro-v" data-r="lvl">--</span><span class="ro-u">LEVEL %</span></div>
        <div class="ro"><span class="ro-v" data-r="prs">--</span><span class="ro-u">PRESS bar</span></div>
        <div class="ro"><span class="ro-v" data-r="trip">90</span><span class="ro-u">SIS TRIP %</span></div>
        <div class="ro"><span class="ro-v" data-r="sis">--</span><span class="ro-u">SAFETY</span></div>
      </div>
      <svg class="sis-svg" viewBox="0 0 520 300" role="img" aria-label="safety-instrumented water tank with SIS controller">
        <!-- supply -> inlet valve -> tank -->
        <rect class="sis-src" x="12" y="72" width="20" height="34" rx="2"/>
        <text class="sis-lbl" x="22" y="120" text-anchor="middle">SUPPLY</text>
        <line id="sis-inpipe" class="sis-pipe" x1="32" y1="89" x2="96" y2="89"/>
        <g id="sis-inlet" class="sis-valve" transform="translate(60 89)">
          <path class="sis-vbody" d="M-9,-9 L0,0 L-9,9 Z M9,-9 L0,0 L9,9 Z"/></g>
        <text class="sis-lbl" x="60" y="76" text-anchor="middle">INLET</text>

        <!-- tank -->
        <rect class="sis-tank" x="96" y="52" width="150" height="204" rx="4"/>
        <rect id="sis-fill" class="sis-fill sis-fill-lo" x="101" y="235" width="140" height="16"/>
        <line id="sis-surf" class="sis-surf" x1="101" y1="235" x2="241" y2="235"/>
        <!-- 90% trip line + 98% overflow line -->
        <line class="sis-trip" x1="96" y1="76" x2="246" y2="76"/>
        <text class="sis-trip-lbl" x="242" y="72" text-anchor="end">TRIP 90%</text>
        <line class="sis-over" x1="96" y1="61" x2="246" y2="61"/>
        <!-- rupture burst -->
        <g id="sis-burst" class="sis-burst" transform="translate(171 150)" opacity="0">
          <path d="M0,-46 L12,-16 42,-22 20,0 42,22 12,16 0,46 -12,16 -42,22 -20,0 -42,-22 -12,-16 Z"/>
        </g>

        <!-- ESD drain valve (the SIS actuator) -->
        <line id="sis-drainpipe" class="sis-pipe" x1="171" y1="256" x2="171" y2="286"/>
        <g id="sis-drain" class="sis-valve" transform="translate(171 271) rotate(90)">
          <path class="sis-vbody" d="M-8,-8 L0,0 L-8,8 Z M8,-8 L0,0 L8,8 Z"/></g>
        <rect class="sis-src" x="192" y="279" width="20" height="14" rx="2"/>
        <text class="sis-lbl" x="222" y="290" text-anchor="start">ESD DRAIN</text>

        <!-- SIS controller -->
        <g id="sis-box" class="sis-box">
          <rect class="sis-box-bg" x="322" y="58" width="182" height="154" rx="6"/>
          <rect class="sis-box-hdr" x="322" y="58" width="182" height="26" rx="6"/>
          <rect class="sis-box-hdr2" x="322" y="74" width="182" height="10"/>
          <text class="sis-box-title" x="336" y="76">SIF-1 · TRICONEX SIS</text>
          <!-- shield -->
          <g id="sis-shield" class="sis-shield guarding" transform="translate(413 108)">
            <path class="sis-shield-body" d="M0,-24 L26,-14 26,10 Q26,32 0,44 Q-26,32 -26,10 L-26,-14 Z"/>
            <path id="sis-ic-ok"   class="sis-ic" d="M-11,8 L-2,17 L13,-6"/>
            <path id="sis-ic-trip" class="sis-ic" d="M0,-8 L0,16 M-9,7 L0,16 L9,7"/>
            <path id="sis-ic-bad"  class="sis-ic" d="M-11,-3 L11,19 M11,-3 L-11,19"/>
          </g>
          <text id="sis-detail" class="sis-detail" x="413" y="190" text-anchor="middle">watching &middot; trip 90%</text>
        </g>

        <!-- safety loop: SIS -> ESD drain actuator -->
        <polyline id="sis-loop" class="sis-loop armed" points="413,212 413,293 171,293 171,286"/>
        <text class="sis-loop-lbl" x="360" y="289" text-anchor="middle">SAFETY LOOP</text>
      </svg>`;
    const q = s => stage.querySelector(s);
    return {
      lvl: q('[data-r="lvl"]'), prs: q('[data-r="prs"]'), sis: q('[data-r="sis"]'),
      fill: q('#sis-fill'), surf: q('#sis-surf'), burst: q('#sis-burst'),
      inlet: q('#sis-inlet'), inpipe: q('#sis-inpipe'), drain: q('#sis-drain'),
      shield: q('#sis-shield'), icOk: q('#sis-ic-ok'), icTrip: q('#sis-ic-trip'),
      icBad: q('#sis-ic-bad'), detail: q('#sis-detail'), loop: q('#sis-loop'), stage,
    };
  },

  clear(refs) {
    refs.lvl.textContent = refs.prs.textContent = "--";
    refs.sis.textContent = "--"; refs.sis.style.color = "";
    refs.fill.setAttribute("y", "235"); refs.fill.setAttribute("height", "16");
    refs.fill.setAttribute("class", "sis-fill sis-fill-lo");
    refs.surf.setAttribute("y1", "235"); refs.surf.setAttribute("y2", "235");
    refs.inlet.classList.remove("open"); refs.inpipe.classList.remove("flowing");
    refs.drain.classList.remove("open");
    refs.shield.setAttribute("class", "sis-shield guarding");
    refs.detail.textContent = "watching · trip 90%";
    refs.loop.setAttribute("class", "sis-loop armed");
    refs.burst.setAttribute("opacity", "0");
    refs.stage.classList.remove("sis-ruptured");
  },

  update(refs, v) {
    const TRIP = 90, INNER_BOT = 251, INNER_H = 194;
    const fmt = (x, d) => (x == null) ? "--" : Number(x).toFixed(d);
    const online = v.online && v.level != null;

    refs.lvl.textContent = online ? fmt(v.level, 1) : "--";
    refs.prs.textContent = online ? fmt(v.pressure, 1) : "--";

    if (!online) {
      refs.sis.textContent = "--"; refs.sis.style.color = "";
      return { level: "offline", msg: "" };
    }

    const ruptured = v.exploded;
    const tripped = v.tripped;
    const bypassed = !tripped && !ruptured && v.level >= TRIP;   // past trip, no shutdown
    const approaching = !tripped && !ruptured && !bypassed && v.level >= 75;

    // tank fill + surface
    const lvl = Math.max(0, Math.min(100, v.level));
    const h = (lvl / 100) * INNER_H, y = INNER_BOT - h;
    refs.fill.setAttribute("y", y.toFixed(1));
    refs.fill.setAttribute("height", h.toFixed(1));
    refs.surf.setAttribute("y1", y.toFixed(1)); refs.surf.setAttribute("y2", y.toFixed(1));
    const band = ruptured ? "rupt" : lvl >= 90 ? "hi" : lvl >= 75 ? "mid" : "lo";
    refs.fill.setAttribute("class", "sis-fill sis-fill-" + band);

    // valves: inlet open (attack fills), ESD drain open (SIS shutdown) reflect live state
    refs.inlet.classList.toggle("open", v.inlet === true);
    refs.inpipe.classList.toggle("flowing", v.inlet === true && !ruptured);
    refs.drain.classList.toggle("open", v.outlet === true);

    // SIS controller state
    let sisState, word, detail;
    if (ruptured)      { sisState = "bypassed"; word = "FAULT";   detail = "no shutdown response"; }
    else if (bypassed) { sisState = "bypassed"; word = "NO TRIP"; detail = "level past 90%, no shutdown"; }
    else if (tripped)  { sisState = "tripped";  word = "TRIP";     detail = "emergency shutdown active"; }
    else if (approaching) { sisState = "guarding"; word = "ARMED"; detail = "level rising · trip 90%"; }
    else               { sisState = "guarding"; word = "ARMED";    detail = "watching · trip 90%"; }

    refs.shield.setAttribute("class", "sis-shield " + sisState);
    refs.detail.textContent = detail;
    refs.sis.textContent = word;
    refs.sis.style.color = sisState === "bypassed" ? "var(--bad)"
                          : sisState === "tripped" ? "var(--warn)" : "var(--ok)";

    // safety loop wire: armed (green) / active (amber, tripping) / severed (grey, halted)
    refs.loop.setAttribute("class", "sis-loop " +
      (sisState === "bypassed" ? "severed" : sisState === "tripped" ? "active" : "armed"));

    // rupture
    refs.burst.setAttribute("opacity", ruptured ? "1" : "0");
    refs.stage.classList.toggle("sis-ruptured", ruptured);

    if (ruptured) return { level: "critical", msg: "TANK RUPTURE - level past overflow, no emergency shutdown, SIS fault" };
    if (bypassed) return { level: "critical", msg: `SIS NOT READY - level ${fmt(v.level, 0)}% past 90% trip, no shutdown response` };
    if (tripped)  return { level: "warning", msg: "SIS TRIP - emergency shutdown active, tank venting to safe state" };
    if (approaching) return { level: "warning", msg: "Level approaching the 90% safety trip point" };
    return { level: "normal", msg: "" };
  },
});
