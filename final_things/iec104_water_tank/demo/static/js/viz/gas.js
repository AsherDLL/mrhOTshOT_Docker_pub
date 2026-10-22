// Gas compressor-station visualization (PIPEDREAM / gas_pipeline).
// Live read (OPC-UA via watch_process): level=outlet pressure PSI, pressure=inlet PSI,
// temperature=gas temp F, inlet_valve=upstream, outlet_valve=downstream, pump=compressor,
// overflow/exploded=rupture, sis/low_level=ESD. The attack closes the downstream valve
// with the compressor running -> outlet pressure builds past the 1500 PSI redline -> rupture.
registerViz({
  kind: "gas",
  title: "Gas Compressor Station",

  map(raw) {
    return {
      outletP: raw.level,
      inletP: raw.pressure,
      temp: raw.temperature,
      upstream: raw.inlet_valve,
      downstream: raw.outlet_valve,
      compressor: raw.pump,
      rupture: raw.overflow === true || raw.exploded === true,
      esd: raw.sis === true || raw.low_level === true,
      online: raw.online,
    };
  },

  build(stage) {
    stage.innerHTML = `
      <div class="viz-readouts">
        <div class="ro"><span class="ro-v" data-r="out">--</span><span class="ro-u">OUTLET psi</span></div>
        <div class="ro"><span class="ro-v" data-r="in">--</span><span class="ro-u">INLET psi</span></div>
        <div class="ro"><span class="ro-v" data-r="temp">--</span><span class="ro-u">GAS &deg;F</span></div>
        <div class="ro"><span class="ro-v" data-r="red">1500</span><span class="ro-u">REDLINE psi</span></div>
      </div>
      <svg class="gas-svg" viewBox="0 0 520 300" role="img" aria-label="gas compressor station">
        <!-- supply -->
        <rect class="gas-src" x="24" y="98" width="22" height="34" rx="3"/>
        <text class="g-lbl" x="35" y="150" text-anchor="middle">SUPPLY</text>

        <!-- inlet pipe -> upstream valve -> compressor -->
        <line id="g-p-in" class="gas-pipe" x1="46" y1="115" x2="96" y2="115"/>
        <g id="g-vup" class="gas-valve" transform="translate(112 115)">
          <path class="g-vbody" d="M-10,-10 L0,0 L-10,10 Z M10,-10 L0,0 L10,10 Z"/></g>
        <text class="g-lbl" x="112" y="140" text-anchor="middle">INLET</text>
        <line id="g-p-mid1" class="gas-pipe" x1="128" y1="115" x2="170" y2="115"/>

        <!-- compressor -->
        <g id="g-comp" class="gas-comp" transform="translate(200 115)">
          <circle class="g-comp-body" r="27"/>
          <g class="g-imp" id="g-imp"><path d="M0 -18 Q10 -8 0 0 Q-10 8 0 18 M-18 0 Q-8 -10 0 0 Q8 10 18 0"/></g>
        </g>
        <text class="g-lbl" x="200" y="158" text-anchor="middle">COMPRESSOR</text>

        <!-- mid pipe -> downstream valve -> outlet -->
        <line id="g-p-mid2" class="gas-pipe" x1="230" y1="115" x2="300" y2="115"/>
        <g id="g-vdn" class="gas-valve" transform="translate(316 115)">
          <path class="g-vbody" d="M-10,-10 L0,0 L-10,10 Z M10,-10 L0,0 L10,10 Z"/></g>
        <text class="g-lbl" x="316" y="140" text-anchor="middle">OUTLET</text>
        <line id="g-p-out" class="gas-pipe" x1="332" y1="115" x2="446" y2="115"/>

        <!-- distribution -->
        <g id="g-dist" transform="translate(452 92)">
          <rect class="gas-dist" width="18" height="46" rx="2"/><rect class="gas-dist" x="24" width="18" height="46" rx="2"/>
        </g>
        <text class="g-lbl" x="470" y="150" text-anchor="middle">DISTRIBUTION</text>

        <!-- rupture burst (hidden until rupture) -->
        <g id="g-burst" class="gas-burst" transform="translate(389 115)" opacity="0">
          <path d="M0,-30 L8,-11 27,-15 14,0 27,15 8,11 0,30 -8,11 -27,15 -14,0 -27,-15 -8,-11 Z"/>
        </g>

        <!-- outlet pressure bar -->
        <text class="g-lbl" x="40" y="212" text-anchor="start">OUTLET PRESSURE</text>
        <rect class="gas-bar-bg" x="40" y="224" width="440" height="24" rx="3"/>
        <rect id="g-bar" class="gas-bar" x="40" y="224" width="4" height="24" rx="3"/>
        <line class="gas-redline" x1="453" y1="218" x2="453" y2="254"/>
        <text class="g-red" x="453" y="270" text-anchor="middle">1500</text>
        <text class="g-lbl" x="40" y="270" text-anchor="start">0</text>

        <!-- monitoring-lost overlay (BADOMEN FINS fault) -->
        <g id="g-nosig" class="gas-nosig">
          <rect x="0" y="0" width="520" height="300" fill="#0d0f11" opacity="0.9"/>
          <rect x="150" y="118" width="220" height="64" rx="6" fill="none" stroke="#ff6b6b" stroke-width="1.5" opacity="0.5"/>
          <text x="260" y="146" text-anchor="middle" class="g-nosig-t">MONITORING LOST</text>
          <text x="260" y="172" text-anchor="middle" class="g-nosig-s">PLC in ERROR mode - no telemetry</text>
        </g>
      </svg>`;
    const q = s => stage.querySelector(s);
    return {
      out: q('[data-r="out"]'), in: q('[data-r="in"]'), temp: q('[data-r="temp"]'),
      vup: q('#g-vup'), vdn: q('#g-vdn'), comp: q('#g-comp'), bar: q('#g-bar'), burst: q('#g-burst'),
      pipes: [q('#g-p-in'), q('#g-p-mid1'), q('#g-p-mid2'), q('#g-p-out')], outpipe: q('#g-p-out'), stage,
    };
  },

  clear(refs) {
    refs.out.textContent = refs.in.textContent = refs.temp.textContent = "--";
    [refs.vup, refs.vdn].forEach(v => v && v.classList.remove("closed"));
    refs.comp && refs.comp.classList.remove("running");
    refs.pipes.forEach(p => p && (p.style.stroke = "", p.classList.remove("flowing")));
    refs.burst && (refs.burst.setAttribute("opacity", "0"));
    refs.bar && (refs.bar.setAttribute("width", "4"), refs.bar.style.fill = "");
    refs.stage && refs.stage.classList.remove("gas-ruptured", "gas-nosignal");
  },

  update(refs, v) {
    const fmt = (x, d) => (x == null) ? "--" : Number(x).toFixed(d);

    // BADOMEN (FINS) faults the PLC -> no telemetry: show "monitoring lost".
    if (!v.online || v.outletP == null) {
      refs.stage.classList.add("gas-nosignal");
      refs.out.textContent = refs.in.textContent = refs.temp.textContent = "--";
      return { level: "offline", msg: "MONITORING LOST - PLC in ERROR mode, no telemetry" };
    }
    refs.stage.classList.remove("gas-nosignal");

    const rup = v.rupture === true;
    // pressure gauge value: after a rupture the reading collapses to 0; hold the redline so
    // the operator sees WHY it ruptured rather than a misleading 0.
    const shownP = rup ? 1500 : (v.outletP == null ? 0 : v.outletP);
    refs.out.textContent = rup ? "RUPT" : fmt(v.outletP, 0);
    refs.in.textContent = fmt(v.inletP, 0);
    refs.temp.textContent = fmt(v.temp, 0);

    const running = v.compressor === true && !rup;
    refs.comp.classList.toggle("running", running);
    const setV = (el, open) => el && el.classList.toggle("closed", open === false || rup);
    setV(refs.vup, v.upstream); setV(refs.vdn, v.downstream);

    // pipe colour by pressure band (cool-blue normal -> amber -> red near redline)
    const band = shownP >= 1300 ? "#e5484d" : shownP >= 1050 ? "#d8a128" : "#4a86c9";
    const flowing = running && !rup;
    refs.pipes.forEach(p => { if (!p) return; p.classList.toggle("flowing", flowing); });
    if (refs.outpipe) refs.outpipe.style.stroke = rup ? "#5a2a2a" : band;

    // pressure bar
    const frac = Math.max(0, Math.min(1, shownP / 1600));
    refs.bar.setAttribute("width", String(Math.max(4, frac * 440)));
    refs.bar.style.fill = band;

    // rupture
    refs.burst.setAttribute("opacity", rup ? "1" : "0");
    refs.stage.classList.toggle("gas-ruptured", rup);

    if (!v.online || v.outletP == null) return { level: "offline", msg: "" };
    if (rup) return { level: "critical", msg: "PIPELINE RUPTURE - overpressure explosion, gas release" };
    if (v.esd) return { level: "warning", msg: "Emergency shutdown (ESD) active - station tripped" };
    if (v.outletP >= 1050) return { level: "critical", msg: "OVERPRESSURE - downstream valve shut, rupture imminent" };
    if (v.outletP >= 900) return { level: "warning", msg: "Outlet pressure rising above normal" };
    return { level: "normal", msg: "" };
  },
});
