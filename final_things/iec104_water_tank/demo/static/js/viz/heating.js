// District-heating substation visualization (FrostyGoop, Lviv 2024).
// Live read over Modbus (watch_process ModbusReader, plc-heating:502 unit 11):
//   level=REAL supply temp C (IR0), reported=HMI-shown supply temp C (IR6, spoofable),
//   setpoint=thermostat target C (IR3), heater_on=heat source firing (IR4),
//   spoof=reading being held/spoofed (IR5), temperature=return temp C (IR2).
//
// The story FrostyGoop tells: the heating controller runs a thermostat - it fires the heat
// source whenever the MEASURED supply temp drops below the setpoint. The attacker (in via
// a vulnerable edge router, then Modbus) writes the controller so it holds a "warm" reading
// ABOVE the setpoint. The thermostat is deceived, never fires the heater, and the REAL
// supply water freezes toward -30 C - while the operator's HMI still shows a normal value.
registerViz({
  kind: "heating",
  title: "District Heating Substation",

  map(raw) {
    return {
      online: raw.online === true,
      real: raw.level,            // REAL supply temp
      hmi: raw.reported,          // what the controller/HMI reads (spoofed under attack)
      ret: raw.temperature,       // return temp
      setpoint: raw.setpoint,
      heaterOn: raw.heater_on === true,
      spoof: raw.spoof === true,
    };
  },

  build(stage) {
    const TMIN = 0, TMAX = 80, BAR_BOT = 240, BAR_TOP = 64, X = 250, W = 26;
    const yFor = t => BAR_BOT - (Math.max(TMIN, Math.min(TMAX, t)) - TMIN) / (TMAX - TMIN) * (BAR_BOT - BAR_TOP);
    stage.innerHTML = `
      <div class="viz-readouts">
        <div class="ro"><span class="ro-v" data-r="real">--</span><span class="ro-u">REAL SUPPLY &deg;C</span></div>
        <div class="ro"><span class="ro-v" data-r="hmi">--</span><span class="ro-u">HMI SHOWS &deg;C</span></div>
        <div class="ro"><span class="ro-v" data-r="sp">--</span><span class="ro-u">SETPOINT &deg;C</span></div>
        <div class="ro"><span class="ro-v" data-r="heat">--</span><span class="ro-u">HEAT SOURCE</span></div>
      </div>
      <svg class="heat-svg" viewBox="0 0 560 300" role="img" aria-label="district heating substation control loop">
        <defs>
          <linearGradient id="h-bezel" x1="0" y1="0" x2="0" y2="1">
            <stop offset="0%" stop-color="#333a44"/><stop offset="48%" stop-color="#1b1f26"/>
            <stop offset="100%" stop-color="#0d1015"/>
          </linearGradient>
          <linearGradient id="h-panel" x1="0" y1="0" x2="0" y2="1">
            <stop offset="0%" stop-color="#1c2129"/><stop offset="100%" stop-color="#12151b"/>
          </linearGradient>
          <linearGradient id="h-hdrgrad" x1="0" y1="0" x2="0" y2="1">
            <stop offset="0%" stop-color="#2b323c"/><stop offset="100%" stop-color="#1a1f26"/>
          </linearGradient>
          <linearGradient id="h-glass" x1="0" y1="0" x2="1" y2="0">
            <stop offset="0%" stop-color="#ffffff" stop-opacity="0.16"/>
            <stop offset="45%" stop-color="#ffffff" stop-opacity="0.03"/>
            <stop offset="100%" stop-color="#ffffff" stop-opacity="0"/>
          </linearGradient>
          <radialGradient id="h-flameglow" cx="50%" cy="62%" r="58%">
            <stop offset="0%" stop-color="#ffb14a" stop-opacity="0.95"/>
            <stop offset="55%" stop-color="#ff6a1a" stop-opacity="0.4"/>
            <stop offset="100%" stop-color="#ff6a1a" stop-opacity="0"/>
          </radialGradient>
          <filter id="h-shadow" x="-40%" y="-40%" width="180%" height="180%">
            <feDropShadow dx="0" dy="2.5" stdDeviation="3.5" flood-color="#000" flood-opacity="0.55"/>
          </filter>
        </defs>
        <text class="h-title" x="16" y="24">DISTRICT HEATING SUBSTATION</text>
        <text class="h-lbl" x="544" y="24" text-anchor="end" id="h-outlbl">OUTDOOR -30&deg;C</text>

        <!-- heat source (boiler) - fires only on heat demand -->
        <g filter="url(#h-shadow)">
          <rect class="h-boiler" x="26" y="150" width="92" height="102" rx="9"/>
        </g>
        <rect class="h-boiler-lip" x="26" y="150" width="92" height="9" rx="9"/>
        <text class="h-eq-tag" x="72" y="145" text-anchor="middle">HEAT SOURCE</text>
        <rect class="h-firebox" x="40" y="184" width="64" height="56" rx="5"/>
        <ellipse class="h-glow" id="h-glow" cx="72" cy="214" rx="30" ry="24"/>
        <g class="h-flame" id="h-flame">
          <path class="h-flame-o" d="M72,238 C58,222 55,204 65,192 C63,204 71,206 70,197 C77,208 84,203 80,192 C90,206 86,230 72,238 Z"/>
          <path class="h-flame-i" d="M72,234 C63,223 62,210 70,200 C69,210 75,211 74,204 C81,213 78,228 72,234 Z"/>
        </g>
        <text class="h-src-st" id="h-src-st" x="72" y="266" text-anchor="middle">OFF</text>

        <!-- supply header to the gauge / district -->
        <path id="h-supply" class="h-pipe" d="M118,178 H236"/>
        <text class="h-lbl" x="176" y="168" text-anchor="middle">SUPPLY</text>

        <!-- supply-temp gauge: beveled tube, REAL fill under glass, setpoint + HMI markers -->
        <g filter="url(#h-shadow)">
          <rect class="h-gauge-case" x="236" y="52" width="54" height="200" rx="12"/>
        </g>
        <rect class="h-therm-track" x="${X}" y="${BAR_TOP}" width="${W}" height="${BAR_BOT - BAR_TOP}" rx="13"/>
        <rect class="h-freeze" id="h-freeze" x="${X}" y="${yFor(35)}" width="${W}" height="${BAR_BOT - yFor(35)}"/>
        <rect class="h-therm-fill h-warm" id="h-fill" x="${X}" y="${yFor(55)}" width="${W}" height="${BAR_BOT - yFor(55)}" rx="13"/>
        <rect class="h-gauge-glass" x="${X}" y="${BAR_TOP}" width="${W}" height="${BAR_BOT - BAR_TOP}" rx="13"/>
        <text class="h-gauge-lbl" x="${X + W / 2}" y="266" text-anchor="middle">SUPPLY &deg;C</text>
        ${[0, 10, 20, 30, 40, 50, 60, 70, 80].map(t => {
          const maj = t % 20 === 0;
          return `<line class="h-tickline ${maj ? "maj" : ""}" x1="${X - (maj ? 8 : 4)}" y1="${yFor(t)}" x2="${X}" y2="${yFor(t)}"/>`
            + (maj ? `<text class="h-tick" x="${X - 11}" y="${yFor(t) + 3}" text-anchor="end">${t}</text>` : "");
        }).join("")}
        <!-- setpoint reference marker -->
        <line class="h-sp-line" id="h-sp-line" x1="${X}" y1="${yFor(55)}" x2="${X + W}" y2="${yFor(55)}"/>
        <path class="h-sp-tri" d="M${X - 2},${yFor(55)} l-9,-5 l0,10 Z"/>
        <text class="h-sp-lbl" id="h-sp-lbl" x="${X - 14}" y="${yFor(55) + 3}" text-anchor="end">SP</text>
        <!-- HMI marker: the value the controller/HMI reads -->
        <g id="h-hmi-mark" transform="translate(${X + W}, ${yFor(60)})">
          <path class="h-hmi-tri" d="M2,0 l11,-6 l0,12 Z"/>
          <text class="h-hmi-txt" x="17" y="4" text-anchor="start">HMI</text>
        </g>

        <!-- heating controller faceplate -->
        <g filter="url(#h-shadow)">
          <rect class="h-ctl-bg" x="366" y="60" width="180" height="200" rx="9"/>
        </g>
        <rect class="h-ctl-hdr" x="366" y="60" width="180" height="26" rx="9"/>
        <rect class="h-ctl-hdr-b" x="366" y="78" width="180" height="8"/>
        <text class="h-ctl-title" x="380" y="78">HEATING CONTROLLER</text>
        <text class="h-ctl-sub" x="380" y="104">PLC-7 &middot; Modbus :502</text>
        <text class="h-ctl-k" x="380" y="132">MEASURED</text>
        <text class="h-ctl-v" id="h-ctl-meas" x="532" y="133" text-anchor="end">-- &deg;C</text>
        <text class="h-ctl-k" x="380" y="154">SETPOINT</text>
        <text class="h-ctl-v" id="h-ctl-sp" x="532" y="155" text-anchor="end">55 &deg;C</text>
        <line class="h-ctl-rule" x1="380" y1="167" x2="532" y2="167"/>
        <text class="h-ctl-k" x="380" y="190">HEAT DEMAND</text>
        <rect class="h-chip off" id="h-chip-heat" x="466" y="177" width="66" height="19" rx="4"/>
        <text class="h-chip-t" id="h-chip-heat-t" x="499" y="190" text-anchor="middle">OFF</text>
        <text class="h-ctl-k" x="380" y="216">READING</text>
        <rect class="h-chip ok" id="h-chip-read" x="466" y="203" width="66" height="19" rx="4"/>
        <text class="h-chip-t" id="h-chip-read-t" x="499" y="216" text-anchor="middle">LIVE</text>
        <text class="h-ctl-note" id="h-ctl-note" x="380" y="244">supply at setpoint</text>
      </svg>`;
    const q = s => stage.querySelector(s);
    return {
      stage, yFor, BAR_BOT, W,
      real: q('[data-r="real"]'), hmi: q('[data-r="hmi"]'), sp: q('[data-r="sp"]'), heat: q('[data-r="heat"]'),
      fill: q('#h-fill'), freeze: q('#h-freeze'),
      spLine: q('#h-sp-line'), spLbl: q('#h-sp-lbl'), hmiMark: q('#h-hmi-mark'),
      flame: q('#h-flame'), glow: q('#h-glow'), pipe: q('#h-supply'), srcSt: q('#h-src-st'),
      meas: q('#h-ctl-meas'), ctlSp: q('#h-ctl-sp'),
      chipHeat: q('#h-chip-heat'), chipHeatT: q('#h-chip-heat-t'),
      chipRead: q('#h-chip-read'), chipReadT: q('#h-chip-read-t'), note: q('#h-ctl-note'),
    };
  },

  clear(refs) {
    refs.real.textContent = refs.hmi.textContent = refs.sp.textContent = "--";
    refs.heat.textContent = "--"; refs.real.style.color = ""; refs.heat.style.color = "";
    refs.hmi.classList.remove("injected");
    refs.fill.setAttribute("y", refs.yFor(55)); refs.fill.setAttribute("height", refs.BAR_BOT - refs.yFor(55));
    refs.fill.setAttribute("class", "h-therm-fill h-warm");
    refs.hmiMark.setAttribute("transform", `translate(276, ${refs.yFor(60)})`);
    refs.hmiMark.setAttribute("class", "");
    refs.flame.classList.remove("on"); refs.glow.classList.remove("on");
    refs.pipe.setAttribute("class", "h-pipe h-warm"); refs.srcSt.textContent = "OFF";
    refs.meas.textContent = "-- °C"; refs.chipHeat.setAttribute("class", "h-chip off"); refs.chipHeatT.textContent = "OFF";
    refs.chipRead.setAttribute("class", "h-chip ok"); refs.chipReadT.textContent = "LIVE"; refs.note.textContent = "supply at setpoint";
  },

  update(refs, v) {
    const fmt = x => (x == null) ? "--" : Number(x).toFixed(1);
    const real = (v.real == null) ? null : Number(v.real);
    const hmi = (v.hmi == null) ? null : Number(v.hmi);
    const sp = (v.setpoint == null) ? 55 : Number(v.setpoint);
    const online = v.online === true;
    if (!online || real == null) {
      refs.real.textContent = refs.hmi.textContent = "--";
      refs.real.style.color = "";
      return { level: "offline", msg: "" };
    }

    // number tiles
    const bandOf = t => t < 35 ? "cold" : t < sp - 1 ? "warm" : "hot";
    const sBand = bandOf(real);
    refs.real.textContent = fmt(real);
    refs.real.style.color = real < 35 ? "var(--bad)" : real < sp - 3 ? "var(--warn)" : "";
    refs.hmi.textContent = fmt(hmi);
    const spoofed = v.spoof || (hmi != null && Math.abs(hmi - real) > 5);
    // The HMI shows a normal-looking value with NO warning - that is exactly the attack.
    // Colour it like a healthy reading (green when at/above setpoint), never alarming red.
    refs.hmi.style.color = (hmi != null && hmi >= sp - 5) ? "var(--ok)" : "";
    refs.sp.textContent = fmt(sp);
    refs.heat.textContent = v.heaterOn ? "FIRING" : "OFF";
    refs.heat.style.color = v.heaterOn ? "var(--ok)" : "var(--muted)";

    // thermometer: REAL supply temp
    const y = refs.yFor(real);
    refs.fill.setAttribute("y", y.toFixed(1));
    refs.fill.setAttribute("height", (refs.BAR_BOT - y).toFixed(1));
    refs.fill.setAttribute("class", "h-therm-fill h-" + sBand);

    // HMI marker: where the controller/HMI reads. Neutral - it looks like a normal
    // reading to the operator; the tell is that it sits above setpoint while REAL is below.
    if (hmi != null) {
      refs.hmiMark.setAttribute("transform", `translate(276, ${refs.yFor(hmi).toFixed(1)})`);
      refs.hmiMark.setAttribute("class", "");
    }

    // heat source fires only on demand
    refs.flame.classList.toggle("on", v.heaterOn);
    refs.glow.classList.toggle("on", v.heaterOn);
    refs.srcSt.textContent = v.heaterOn ? "FIRING" : "OFF";
    refs.pipe.setAttribute("class", "h-pipe h-" + sBand + (v.heaterOn ? " flowing" : ""));

    // heating controller faceplate: it acts on the MEASURED (spoofed) value
    refs.meas.textContent = fmt(hmi) + " °C";
    refs.ctlSp.textContent = fmt(sp) + " °C";
    refs.chipHeat.setAttribute("class", "h-chip " + (v.heaterOn ? "on" : "off"));
    refs.chipHeatT.textContent = v.heaterOn ? "ON" : "OFF";
    refs.chipRead.setAttribute("class", "h-chip " + (spoofed ? "held" : "ok"));
    refs.chipReadT.textContent = spoofed ? "HELD" : "LIVE";
    refs.note.textContent = spoofed
      ? `measured ${fmt(hmi)} >= setpoint, no heat demand`
      : v.heaterOn ? "below setpoint, heating" : "supply at setpoint";

    // Stealthy attack: the HMI shows a normal (spoofed) value, so NO operator alarm fires -
    // that is the point of FrostyGoop. The thermometer, tiles and controller faceplate carry
    // the ground truth for the analyst.
    return { level: "normal", msg: "" };
  },
});
