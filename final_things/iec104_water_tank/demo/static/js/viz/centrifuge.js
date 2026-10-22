// Centrifuge-cascade visualization (Stuxnet / Natanz IR-1 centrifuges).
// Live read over S7comm (watch_process S7CentrifugeReader, on plc-centrifuge:102):
//   commanded = DB3 setpoint Hz (the attacker's real command, NOT masked)
//   reported  = DB4 measurement Hz (what the HMI shows -- MASKED to ~1007 by the rootkit)
//   status    = DB4 status word (0 NORMAL .. 4 DESTROYED)
//   rootkit   = DB890 stuxnet_active flag (when set, DB4 is spoofed)
//
// The story Stuxnet tells: the PLC rootkit feeds operators a calm 1007 Hz while the
// centrifuges are driven to 1410 Hz overspeed / 2 Hz near-stop until the rotors fail.
// We drive the rotor picture from the COMMANDED speed (the physical reality) and show
// the REPORTED value next to it flagged SPOOFED -- you watch the operator being lied
// to. When the attack lifts the mask (its final phase), DB4 reveals the destroyed rotors.
registerViz({
  kind: "centrifuge",
  title: "Centrifuge Cascade",

  map(raw) {
    return {
      online: raw.online === true && Array.isArray(raw.centrifuges),
      rootkit: raw.rootkit === true,
      // null on an older target that does not publish the mirror -> treat as running
      cpuStopped: raw.cpu_run === false,
      cents: Array.isArray(raw.centrifuges) ? raw.centrifuges : [],
    };
  },

  build(stage) {
    const NORMAL = 1007, OVER = 1200, UNDER = 50, SMAX = 1500;
    const FB = 228, FT = 74, TH = FB - FT;            // fill track bottom/top/height
    const yFor = hz => FB - Math.max(0, Math.min(SMAX, hz)) / SMAX * TH;
    const rotor = (i) => {
      const x = 20 + i * 100, xc = x + 28;
      return `
      <g class="cent" id="cent-g-${i}">
        <g class="cent-rotor" id="cent-rot-${i}">
          <!-- rotor cap + spokes (spin speed set from commanded Hz) -->
          <ellipse class="cent-cap" cx="${xc}" cy="50" rx="18" ry="6"/>
          <g class="cent-spin" id="cent-spin-${i}">
            <line class="cent-spoke" x1="${xc - 15}" y1="50" x2="${xc + 15}" y2="50"/>
            <line class="cent-spoke" x1="${xc}" y1="45" x2="${xc}" y2="55"/>
          </g>
          <!-- casing -->
          <rect class="cent-casing" x="${x}" y="56" width="56" height="182" rx="7"/>
          <!-- speed track + fill + overspeed redzone + normal tick -->
          <rect class="cent-track" x="${x + 13}" y="${FT}" width="30" height="${TH}" rx="3"/>
          <rect class="cent-redzone" x="${x + 13}" y="${FT}" width="30" height="${yFor(OVER) - FT}"/>
          <rect class="cent-fill cent-ok" id="cent-fill-${i}" x="${x + 13}" y="${yFor(NORMAL)}" width="30" height="${FB - yFor(NORMAL)}"/>
          <line class="cent-tick" x1="${x + 10}" y1="${yFor(NORMAL)}" x2="${x + 46}" y2="${yFor(NORMAL)}"/>
          <!-- crack overlay (destroyed) -->
          <g class="cent-crack" id="cent-crack-${i}">
            <polyline points="${x + 28},60 ${x + 20},110 ${x + 34},150 ${x + 22},200 ${x + 30},234"/>
            <polyline points="${x + 12},96 ${x + 30},120 ${x + 16},160 ${x + 40},188"/>
          </g>
        </g>
        <text class="cent-name" x="${xc}" y="255" text-anchor="middle">R-${i + 1}</text>
        <text class="cent-status cent-t-ok" id="cent-st-${i}" x="${xc}" y="269" text-anchor="middle">NORMAL</text>
        <text class="cent-cmd" id="cent-cmd-${i}" x="${xc}" y="286" text-anchor="middle">CMD --</text>
        <text class="cent-hmi" id="cent-hmi-${i}" x="${xc}" y="299" text-anchor="middle">HMI --</text>
        <line class="cent-stub" x1="${xc}" y1="238" x2="${xc}" y2="312"/>
      </g>`;
    };

    stage.innerHTML = `
      <div class="viz-readouts">
        <div class="ro"><span class="ro-v" data-r="active">--</span><span class="ro-u">ROTORS OK</span></div>
        <div class="ro"><span class="ro-v" data-r="cmd">--</span><span class="ro-u">COMMANDED Hz</span></div>
        <div class="ro"><span class="ro-v" data-r="hmi">--</span><span class="ro-u">HMI SHOWS Hz</span></div>
        <div class="ro"><span class="ro-v" data-r="rk">--</span><span class="ro-u">HMI FEED</span></div>
      </div>
      <svg class="cent-svg" viewBox="0 0 560 332" role="img" aria-label="Natanz IR-1 centrifuge cascade with Siemens S7 PLC">
        <text class="cent-cascade-lbl" x="20" y="26">NATANZ FEP &middot; CASCADE A &middot; IR-1</text>
        ${[0, 1, 2].map(rotor).join("")}
        <!-- UF6 feed manifold -->
        <line class="cent-pipe" x1="48" y1="312" x2="248" y2="312"/>
        <rect class="cent-src" x="8" y="304" width="16" height="16" rx="2"/>
        <text class="cent-lbl" x="16" y="330" text-anchor="middle">UF6</text>

        <!-- Siemens S7 PLC -->
        <g class="cent-plc" id="cent-plc">
          <rect class="cent-plc-bg" x="330" y="44" width="220" height="252" rx="6"/>
          <rect class="cent-plc-hdr" x="330" y="44" width="220" height="26" rx="6"/>
          <rect class="cent-plc-hdr2" x="330" y="60" width="220" height="10"/>
          <text class="cent-plc-title" x="344" y="62">SIMATIC S7-315-2 DP</text>
          <text class="cent-plc-sub" x="344" y="92">CENTRIFUGE DRIVE CONTROLLER</text>

          <text class="cent-db-k" x="344" y="126">DB3 setpoint</text>
          <text class="cent-db-v" id="cent-db3" x="536" y="126" text-anchor="end">-- Hz</text>
          <line class="cent-db-rule" x1="344" y1="134" x2="536" y2="134"/>

          <text class="cent-db-k" x="344" y="158">DB4 to HMI</text>
          <text class="cent-db-v" id="cent-db4" x="536" y="158" text-anchor="end">-- Hz</text>
          <line class="cent-db-rule" x1="344" y1="166" x2="536" y2="166"/>

          <text class="cent-db-k" x="344" y="190">DB890 integrity</text>
          <g id="cent-db890">
            <rect class="cent-chip secure" id="cent-chip" x="452" y="176" width="84" height="20" rx="4"/>
            <text class="cent-chip-t" id="cent-chip-t" x="494" y="190" text-anchor="middle">LIVE</text>
          </g>

          <text class="cent-plc-note" id="cent-plc-note" x="344" y="232">setpoints nominal</text>
          <text class="cent-plc-note2" id="cent-plc-note2" x="344" y="252">HMI tracking drive</text>
        </g>
      </svg>`;

    const q = s => stage.querySelector(s);
    const cents = [0, 1, 2].map(i => ({
      g: q(`#cent-g-${i}`), rot: q(`#cent-rot-${i}`), fill: q(`#cent-fill-${i}`),
      spin: q(`#cent-spin-${i}`), crack: q(`#cent-crack-${i}`),
      st: q(`#cent-st-${i}`), cmd: q(`#cent-cmd-${i}`), hmi: q(`#cent-hmi-${i}`),
    }));
    return {
      stage, cents,
      roActive: q('[data-r="active"]'), roCmd: q('[data-r="cmd"]'),
      roHmi: q('[data-r="hmi"]'), roRk: q('[data-r="rk"]'),
      db3: q('#cent-db3'), db4: q('#cent-db4'),
      chip: q('#cent-chip'), chipT: q('#cent-chip-t'),
      note: q('#cent-plc-note'), note2: q('#cent-plc-note2'),
      Y: yFor, C: { NORMAL, OVER, UNDER, SMAX, FB },
    };
  },

  clear(refs) {
    refs.roActive.textContent = refs.roCmd.textContent = refs.roHmi.textContent = "--";
    refs.roRk.textContent = "--"; refs.roRk.style.color = "";
    refs.db3.textContent = refs.db4.textContent = "-- Hz";
    refs.chip.setAttribute("class", "cent-chip secure"); refs.chipT.textContent = "LIVE";
    refs.note.textContent = "setpoints nominal"; refs.note2.textContent = "HMI tracking drive";
    refs.cents.forEach(c => {
      c.g.setAttribute("class", "cent");
      c.fill.setAttribute("class", "cent-fill cent-ok");
      c.fill.setAttribute("y", refs.Y(refs.C.NORMAL)); c.fill.setAttribute("height", refs.C.FB - refs.Y(refs.C.NORMAL));
      c.spin.style.animationDuration = "";
      c.st.textContent = "NORMAL"; c.st.setAttribute("class", "cent-status cent-t-ok");
      c.cmd.textContent = "CMD --"; c.hmi.textContent = "HMI --";
      c.hmi.setAttribute("class", "cent-hmi");
    });
  },

  update(refs, v) {
    const fmt = x => (x == null ? "--" : Math.round(x));
    if (!v.online) {
      refs.roActive.textContent = refs.roCmd.textContent = refs.roHmi.textContent = "--";
      refs.roHmi.classList.remove("injected");
      refs.roRk.textContent = "--"; refs.roRk.style.color = "";
      return { level: "offline", msg: "" };
    }
    const { NORMAL, OVER, UNDER, SMAX, FB } = refs.C;
    const cents = v.cents;
    let destroyed = 0, worstCmd = NORMAL, anyAbnormal = false;

    cents.forEach((c, i) => {
      const r = refs.cents[i];
      const cmd = c.commanded, rep = c.reported, dead = c.status === 4;
      if (dead) destroyed++;
      const abnormal = cmd > OVER || cmd < UNDER;
      if (abnormal) anyAbnormal = true;
      if (Math.abs(cmd - NORMAL) > Math.abs(worstCmd - NORMAL)) worstCmd = cmd;

      // rotor fill driven by the COMMANDED speed (the physical reality)
      const band = dead ? "dead" : cmd > OVER ? "over" : cmd < UNDER ? "under" : "ok";
      const y = dead ? FB : refs.Y(cmd);
      r.fill.setAttribute("y", y); r.fill.setAttribute("height", Math.max(0, FB - y));
      r.fill.setAttribute("class", "cent-fill cent-" + band);

      // spin faster with speed; stop when destroyed or when the CPU is halted (the
      // drives have lost their speed reference and are coasting); shake when overspeed
      const spd = (dead || v.cpuStopped) ? 0 : cmd;
      r.spin.style.animationDuration = spd < 3 ? "0s" : (Math.max(0.12, Math.min(4, 190 / spd)) + "s");
      r.g.setAttribute("class", "cent" + (dead ? " dead" : band === "over" ? " over" : ""));

      r.st.textContent = c.status_name || "?";
      r.st.setAttribute("class", "cent-status " +      // colour by damage severity
        (c.status >= 3 ? "cent-t-bad" : c.status === 0 ? "cent-t-ok" : "cent-t-warn"));

      r.cmd.textContent = "CMD " + fmt(cmd);
      // the reported value is a lie while the rootkit masks it and disagrees with the command
      const spoofed = v.rootkit && !dead && Math.abs(cmd - rep) > 50;
      r.hmi.textContent = "HMI " + fmt(rep);            // styling (red + strike) marks the spoof
      r.hmi.setAttribute("class", "cent-hmi" + (spoofed ? " spoofed injected" : ""));
    });

    // top readouts
    refs.roActive.textContent = (cents.length - destroyed) + "/" + cents.length;
    refs.roCmd.textContent = fmt(worstCmd);
    refs.roHmi.textContent = cents.length ? fmt(cents[0].reported) : "--";
    // HMI-shows tile is the injected (masked) value: pulse it red while the rootkit lies
    const anySpoofed = v.rootkit && cents.some(c => c.status !== 4 && Math.abs(c.commanded - c.reported) > 50);
    refs.roHmi.classList.toggle("injected", anySpoofed);
    refs.roRk.textContent = v.rootkit ? "HELD" : "LIVE";
    refs.roRk.style.color = v.rootkit ? "var(--bad)" : "var(--ok)";

    // S7 PLC panel
    refs.db3.textContent = fmt(worstCmd) + " Hz";
    refs.db4.textContent = (cents.length ? fmt(cents[0].reported) : "--") + " Hz";
    refs.chip.setAttribute("class", "cent-chip " + (v.rootkit ? "infected" : "secure"));
    refs.chipT.textContent = v.rootkit ? "HELD" : "LIVE";
    if (v.cpuStopped) {
      refs.note.textContent = "CPU in STOP - program not executing";
      refs.note2.textContent = "DB4 frozen, drives coasting";
    } else if (destroyed > 0) {
      refs.note.textContent = destroyed + " of " + cents.length + " drives failed";
      refs.note2.textContent = "cascade fault";
    } else if (v.rootkit) {
      refs.note.textContent = "DB4 held at ~" + NORMAL + " Hz";
      refs.note2.textContent = "HMI not tracking drive";
    } else if (anyAbnormal) {
      refs.note.textContent = "abnormal setpoint written";
      refs.note2.textContent = "cascade out of spec";
    } else {
      refs.note.textContent = "setpoints nominal";
      refs.note2.textContent = "HMI reading trusted";
    }

    // banner / alert level (operator HMI: process conditions only)
    // A halted controller outranks everything below it: nothing is being controlled and
    // the values on screen stopped updating, so no other reading can be trusted.
    if (v.cpuStopped)
      return { level: "critical",
               msg: "CONTROLLER HALTED - CPU in STOP, drives coasting down and displayed values frozen" };
    if (destroyed > 0)
      return { level: "critical", msg: `ROTOR FAILURE - ${destroyed} of ${cents.length} drives failed on overspeed` };
    if (v.rootkit && anyAbnormal)
      return { level: "critical", msg: `DRIVE SPEED ABNORMAL - drives at ${fmt(worstCmd)} Hz, HMI showing ~${NORMAL} Hz` };
    if (v.rootkit)
      return { level: "warning", msg: "HMI SPEED NOT TRACKING - displayed value held, not matching drive feedback" };
    if (anyAbnormal)
      return { level: "warning", msg: `Abnormal centrifuge setpoint commanded (${fmt(worstCmd)} Hz)` };
    return { level: "normal", msg: "" };
  },
});
