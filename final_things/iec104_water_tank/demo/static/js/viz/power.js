// Power-substation visualization (Industroyer2 / BlackEnergy3 / CrashOverride).
// Live read (IEC-104 via watch_process): level=bus voltage kV, temperature=xfmr oil C,
// inlet_valve=incoming breaker(B1), pump=bus-tie(B2), outlet_valve=outgoing breaker(B3),
// overflow=blackout. The attack trips breakers -> the bus de-energizes -> city blackout.
registerViz({
  kind: "power",
  title: "Power Substation",

  map(raw) {
    const v = raw.level;
    return {
      voltage: v,
      xfmr: raw.temperature,
      b1: raw.inlet_valve,          // incoming feeder breaker
      b2: raw.pump,                 // bus-tie breaker
      b3: raw.outlet_valve,         // outgoing feeder breaker
      blackout: raw.overflow === true || (v != null && v < 1),
      online: raw.online,
    };
  },

  build(stage) {
    stage.innerHTML = `
      <div class="viz-readouts">
        <div class="ro"><span class="ro-v" data-r="volt">--</span><span class="ro-u">BUS kV</span></div>
        <div class="ro"><span class="ro-v" data-r="freq">--</span><span class="ro-u">FREQ Hz</span></div>
        <div class="ro"><span class="ro-v" data-r="xfmr">--</span><span class="ro-u">XFMR &deg;C</span></div>
        <div class="ro"><span class="ro-v" data-r="brk">--</span><span class="ro-u">BREAKERS</span></div>
      </div>
      <svg class="pwr-svg" viewBox="0 0 520 300" role="img" aria-label="power substation single-line diagram">
        <!-- grid source -->
        <g transform="translate(28 108)">
          <path class="p-tower" d="M0 42 L10 0 L20 42 M2 30 H18 M5 16 H15"/>
        </g>
        <text class="p-lbl" x="30" y="168" text-anchor="middle">GRID 110kV</text>

        <!-- feed line: grid -> B1 -> bus -->
        <line id="p-l-feed" class="p-line" x1="48" y1="126" x2="86" y2="126"/>
        <g id="p-b1" class="p-brk" transform="translate(104 126)">
          <circle class="p-term" cx="-16" cy="0" r="3"/><circle class="p-term" cx="16" cy="0" r="3"/>
          <line class="p-arm" x1="-16" y1="0" x2="16" y2="0"/>
        </g>
        <text class="p-lbl" x="104" y="150" text-anchor="middle">B1</text>
        <line id="p-l-b1bus" class="p-line" x1="122" y1="126" x2="150" y2="126"/>

        <!-- the 13.8 kV busbar -->
        <line id="p-bus" class="p-bus" x1="150" y1="126" x2="392" y2="126"/>
        <text class="p-lbl" x="196" y="112" text-anchor="middle">13.8 kV BUS</text>

        <!-- bus-tie breaker on the bus -->
        <g id="p-b2" class="p-brk" transform="translate(250 126)">
          <circle class="p-term" cx="-16" cy="0" r="3"/><circle class="p-term" cx="16" cy="0" r="3"/>
          <line class="p-arm" x1="-16" y1="0" x2="16" y2="0"/>
        </g>
        <text class="p-lbl" x="250" y="150" text-anchor="middle">B2 tie</text>

        <!-- transformer: bus drop -> coils -->
        <line id="p-l-xfmr" class="p-line" x1="322" y1="126" x2="322" y2="168"/>
        <g id="p-xfmr" transform="translate(322 190)">
          <circle class="p-coil" cx="0" cy="-8" r="13"/><circle class="p-coil" cx="0" cy="10" r="13"/>
        </g>
        <text class="p-lbl" x="322" y="224" text-anchor="middle">XFMR</text>

        <!-- outgoing breaker -> feeders -> city -->
        <g id="p-b3" class="p-brk" transform="translate(392 126)">
          <circle class="p-term" cx="-16" cy="0" r="3"/><circle class="p-term" cx="16" cy="0" r="3"/>
          <line class="p-arm" x1="-16" y1="0" x2="16" y2="0"/>
        </g>
        <text class="p-lbl" x="392" y="150" text-anchor="middle">B3</text>
        <polyline id="p-l-feeder" class="p-line" points="410,126 434,126 434,196 450,196"/>

        <!-- city skyline (feeders) -->
        <g id="p-city" class="p-city">
          <g transform="translate(442 200)"><rect class="p-bld" width="32" height="76" rx="2"/>
            <rect class="p-win" x="6" y="9" width="8" height="9"/><rect class="p-win" x="18" y="9" width="8" height="9"/>
            <rect class="p-win" x="6" y="26" width="8" height="9"/><rect class="p-win" x="18" y="26" width="8" height="9"/>
            <rect class="p-win" x="6" y="43" width="8" height="9"/><rect class="p-win" x="18" y="43" width="8" height="9"/></g>
          <g transform="translate(442 176)"><rect class="p-bld" x="36" width="32" height="100" rx="2"/>
            <rect class="p-win" x="42" y="9" width="8" height="9"/><rect class="p-win" x="54" y="9" width="8" height="9"/>
            <rect class="p-win" x="42" y="26" width="8" height="9"/><rect class="p-win" x="54" y="26" width="8" height="9"/>
            <rect class="p-win" x="42" y="43" width="8" height="9"/><rect class="p-win" x="54" y="43" width="8" height="9"/>
            <rect class="p-win" x="42" y="60" width="8" height="9"/><rect class="p-win" x="54" y="60" width="8" height="9"/></g>
        </g>
        <text class="p-lbl" x="476" y="290" text-anchor="middle">CITY FEEDERS</text>
      </svg>`;
    const q = s => stage.querySelector(s);
    return {
      volt: q('[data-r="volt"]'), freq: q('[data-r="freq"]'), xfmr: q('[data-r="xfmr"]'), brk: q('[data-r="brk"]'),
      b1: q('#p-b1'), b2: q('#p-b2'), b3: q('#p-b3'),
      bus: q('#p-bus'), city: q('#p-city'),
      lines: [q('#p-l-feed'), q('#p-l-b1bus'), q('#p-l-xfmr'), q('#p-l-feeder')],
    };
  },

  clear(refs) {
    refs.volt.textContent = refs.freq.textContent = refs.xfmr.textContent = refs.brk.textContent = "--";
    [refs.b1, refs.b2, refs.b3].forEach(b => b && b.classList.remove("open"));
    refs.bus.classList.remove("hot", "dead");
    refs.lines.forEach(l => l && l.classList.remove("hot", "dead"));
    refs.city.setAttribute("class", "p-city");
  },

  update(refs, v) {
    const fmt = (x, d) => (x == null) ? "--" : Number(x).toFixed(d);
    const energized = v.online && !v.blackout && v.voltage != null && v.voltage > 1;
    const degraded = energized && v.voltage < 12.5;         // a breaker open, bus sagging

    refs.volt.textContent = fmt(v.voltage, 1);
    refs.xfmr.textContent = fmt(v.xfmr, 1);
    refs.freq.textContent = !v.online ? "--" : (v.blackout ? "0.0" : (degraded ? "59.4" : "60.0"));
    const closed = [v.b1, v.b2, v.b3].filter(b => b === true).length;
    refs.brk.textContent = (v.b1 == null) ? "--" : `${closed}/3`;

    // breakers: open (red, arm lifted) when their status is false
    const setBrk = (el, st) => el && el.classList.toggle("open", st === false);
    setBrk(refs.b1, v.b1); setBrk(refs.b2, v.b2); setBrk(refs.b3, v.b3);

    // bus + lines energized (amber) / dead (dark)
    refs.bus.classList.toggle("hot", energized);
    refs.bus.classList.toggle("dead", !energized);
    refs.lines.forEach(l => { if (!l) return; l.classList.toggle("hot", energized); l.classList.toggle("dead", !energized); });

    // city lit / dark
    refs.city.setAttribute("class", "p-city " + (!v.online ? "" : energized ? "lit" : "dark"));

    if (!v.online || v.voltage == null) return { level: "offline", msg: "" };
    if (v.blackout) return { level: "critical", msg: "SUBSTATION BLACKOUT - breakers tripped, city feeders de-energized" };
    if (degraded) return { level: "warning", msg: "Breaker open - bus voltage sagging, grid unstable" };
    return { level: "normal", msg: "" };
  },
});
