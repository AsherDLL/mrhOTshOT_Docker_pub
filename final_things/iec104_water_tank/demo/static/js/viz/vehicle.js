// Vehicle CAN-bus visualization (automotive CAN-injection / unintended acceleration).
// Live read over CANopen (watch_process VehicleReader, plc-vehicle:20001, SDO 0x600/0x580):
//   speed (0x2002, km/h), throttle (0x2000, %), brake (0x2001, %),
//   accel_x (0x2003:1, longitudinal milli-g).
//
// The picture is a realistic instrument cluster: an analog needle speedometer and a
// longitudinal G-meter, plus the digital read-outs. Normal operation cruises at a
// steady speed; a CAN-injection attack pins throttle=100 / brake=0 and the needle
// sweeps past the redline (runaway acceleration). Pause/restore returns it to cruise.
registerViz({
  kind: "vehicle",
  title: "Vehicle CAN Bus",

  map(raw) {
    return {
      online: raw.online === true,
      speed: raw.speed,               // km/h
      throttle: raw.throttle,         // % (commanded / applied channel)
      brake: raw.brake,               // %
      driverThr: raw.driver_throttle, // % (the real driver's pedal)
      driverBrk: raw.driver_brake,    // %
      ax: raw.accel_x,                // longitudinal milli-g
    };
  },

  build(stage) {
    const SP = { cx: 176, cy: 162, max: 200, warn: 110, red: 140 };   // speedometer
    const GM = { cx: 440, cy: 162, full: 0.20 };                      // G-meter (+/- g)
    const A0 = -135, SWEEP = 270;                                     // dial sweep

    // geometry helpers (0deg = up, clockwise positive)
    const pt = (cx, cy, r, deg) => {
      const a = (deg) * Math.PI / 180;
      return [cx + r * Math.sin(a), cy - r * Math.cos(a)];
    };
    const spAng = v => A0 + Math.max(0, Math.min(SP.max, v)) / SP.max * SWEEP;
    const arc = (cx, cy, r, d0, d1) => {
      const [x0, y0] = pt(cx, cy, r, d0), [x1, y1] = pt(cx, cy, r, d1);
      return `M ${x0.toFixed(1)} ${y0.toFixed(1)} A ${r} ${r} 0 ${(d1 - d0) > 180 ? 1 : 0} 1 ${x1.toFixed(1)} ${y1.toFixed(1)}`;
    };

    // speedometer ticks + numbers
    let ticks = "", nums = "";
    for (let v = 0; v <= SP.max; v += 5) {
      const d = spAng(v), major = v % 20 === 0;
      const [xo, yo] = pt(SP.cx, SP.cy, 100, d);
      const [xi, yi] = pt(SP.cx, SP.cy, major ? 83 : 93, d);
      ticks += `<line class="veh-tick ${major ? "maj" : "min"}" x1="${xo.toFixed(1)}" y1="${yo.toFixed(1)}" x2="${xi.toFixed(1)}" y2="${yi.toFixed(1)}"/>`;
      if (major) {
        const [xn, yn] = pt(SP.cx, SP.cy, 70, d);
        nums += `<text class="veh-num" x="${xn.toFixed(1)}" y="${(yn + 3.5).toFixed(1)}">${v}</text>`;
      }
    }
    // G-meter ticks
    let gticks = "";
    for (let i = -2; i <= 2; i++) {
      const d = i / 2 * 70;
      const [xo, yo] = pt(GM.cx, GM.cy, 60, d);
      const [xi, yi] = pt(GM.cx, GM.cy, i === 0 ? 46 : 51, d);
      gticks += `<line class="veh-tick ${i === 0 ? "maj" : "min"}" x1="${xo.toFixed(1)}" y1="${yo.toFixed(1)}" x2="${xi.toFixed(1)}" y2="${yi.toFixed(1)}"/>`;
    }

    stage.innerHTML = `
      <div class="viz-readouts cols-5">
        <div class="ro"><span class="ro-v" data-r="spd">--</span><span class="ro-u">SPEED km/h</span></div>
        <div class="ro"><span class="ro-v" data-r="drv">--</span><span class="ro-u">DRIVER PEDAL %</span></div>
        <div class="ro"><span class="ro-v" data-r="inj">--</span><span class="ro-u">COMMANDED %</span></div>
        <div class="ro"><span class="ro-v" data-r="brk">--</span><span class="ro-u">BRAKE %</span></div>
        <div class="ro"><span class="ro-v" data-r="acc">--</span><span class="ro-u">ACCEL x&nbsp;(g)</span></div>
      </div>
      <svg class="veh-svg" viewBox="0 0 560 300" role="img" aria-label="Vehicle instrument cluster over CAN bus">
        <defs>
          <radialGradient id="veh-bezel" cx="42%" cy="34%" r="72%">
            <stop offset="0%" stop-color="#4a525d"/><stop offset="46%" stop-color="#2a2f37"/>
            <stop offset="82%" stop-color="#171a1f"/><stop offset="100%" stop-color="#3a414b"/>
          </radialGradient>
          <radialGradient id="veh-face" cx="50%" cy="40%" r="75%">
            <stop offset="0%" stop-color="#1b2027"/><stop offset="70%" stop-color="#0f1216"/>
            <stop offset="100%" stop-color="#070809"/>
          </radialGradient>
          <radialGradient id="veh-hub" cx="40%" cy="35%" r="70%">
            <stop offset="0%" stop-color="#c2c9d2"/><stop offset="55%" stop-color="#71787f"/>
            <stop offset="100%" stop-color="#2a2e33"/>
          </radialGradient>
          <linearGradient id="veh-glass" x1="0" y1="0" x2="0" y2="1">
            <stop offset="0%" stop-color="#ffffff" stop-opacity="0.14"/>
            <stop offset="42%" stop-color="#ffffff" stop-opacity="0.03"/>
            <stop offset="100%" stop-color="#ffffff" stop-opacity="0"/>
          </linearGradient>
          <filter id="veh-shadow" x="-30%" y="-30%" width="160%" height="160%">
            <feDropShadow dx="0" dy="2.5" stdDeviation="3" flood-color="#000" flood-opacity="0.55"/>
          </filter>
        </defs>

        <!-- ===== SPEEDOMETER ===== -->
        <g filter="url(#veh-shadow)">
          <circle cx="${SP.cx}" cy="${SP.cy}" r="118" fill="url(#veh-bezel)"/>
          <circle cx="${SP.cx}" cy="${SP.cy}" r="107" fill="#0c0e11"/>
          <circle cx="${SP.cx}" cy="${SP.cy}" r="104" fill="url(#veh-face)"/>
        </g>
        <path class="veh-band warn" d="${arc(SP.cx, SP.cy, 101, spAng(SP.warn), spAng(SP.red))}"/>
        <path class="veh-band red"  d="${arc(SP.cx, SP.cy, 101, spAng(SP.red), spAng(SP.max))}"/>
        ${ticks}${nums}
        <text class="veh-cap" x="${SP.cx}" y="${SP.cy + 42}">km/h</text>
        <text class="veh-dig" id="veh-dig" x="${SP.cx}" y="${SP.cy + 74}">--</text>
        <!-- needle -->
        <g class="veh-needle veh-needle-sp" id="veh-sp-needle" style="transform-origin:${SP.cx}px ${SP.cy}px">
          <polygon class="veh-needle-body" id="veh-sp-body"
            points="${SP.cx},${SP.cy - 94} ${SP.cx - 4.5},${SP.cy - 12} ${SP.cx - 3},${SP.cy + 24} ${SP.cx + 3},${SP.cy + 24} ${SP.cx + 4.5},${SP.cy - 12}"/>
        </g>
        <circle cx="${SP.cx}" cy="${SP.cy}" r="13" fill="url(#veh-hub)" stroke="#0a0c0e" stroke-width="1"/>
        <circle cx="${SP.cx}" cy="${SP.cy}" r="3.4" fill="#14171b"/>
        <ellipse cx="${SP.cx}" cy="${SP.cy - 34}" rx="82" ry="52" fill="url(#veh-glass)" pointer-events="none"/>

        <!-- ===== G-METER (longitudinal accelerometer) ===== -->
        <g filter="url(#veh-shadow)">
          <circle cx="${GM.cx}" cy="${GM.cy}" r="78" fill="url(#veh-bezel)"/>
          <circle cx="${GM.cx}" cy="${GM.cy}" r="69" fill="#0c0e11"/>
          <circle cx="${GM.cx}" cy="${GM.cy}" r="66" fill="url(#veh-face)"/>
        </g>
        <path class="veh-band brake" d="${arc(GM.cx, GM.cy, 63, -70, -6)}"/>
        <path class="veh-band accel" d="${arc(GM.cx, GM.cy, 63, 6, 70)}"/>
        ${gticks}
        <text class="veh-gtick" x="${GM.cx - 44}" y="${GM.cy + 30}">BRAKE</text>
        <text class="veh-gtick" x="${GM.cx + 44}" y="${GM.cy + 30}">ACCEL</text>
        <text class="veh-cap" x="${GM.cx}" y="${GM.cy + 50}">LONG. G</text>
        <g class="veh-needle veh-needle-gm" id="veh-gm-needle" style="transform-origin:${GM.cx}px ${GM.cy}px">
          <polygon class="veh-needle-body gm" id="veh-gm-body"
            points="${GM.cx},${GM.cy - 56} ${GM.cx - 3.4},${GM.cy - 6} ${GM.cx - 2.2},${GM.cy + 16} ${GM.cx + 2.2},${GM.cy + 16} ${GM.cx + 3.4},${GM.cy - 6}"/>
        </g>
        <circle cx="${GM.cx}" cy="${GM.cy}" r="9" fill="url(#veh-hub)" stroke="#0a0c0e" stroke-width="1"/>
        <text class="veh-tag" id="veh-tag" x="280" y="292" text-anchor="middle" opacity="0">THROTTLE FAULT</text>
      </svg>`;

    const q = s => stage.querySelector(s);
    return {
      SP, GM,
      roSpd: q('[data-r="spd"]'), roDrv: q('[data-r="drv"]'), roInj: q('[data-r="inj"]'), roBrk: q('[data-r="brk"]'), roAcc: q('[data-r="acc"]'),
      dig: q('#veh-dig'), tag: q('#veh-tag'),
      spNeedle: q('#veh-sp-needle'), spBody: q('#veh-sp-body'),
      gmNeedle: q('#veh-gm-needle'),
      _spAng: v => A0 + Math.max(0, Math.min(SP.max, v)) / SP.max * SWEEP,
    };
  },

  clear(refs) {
    refs.roSpd.textContent = refs.roDrv.textContent = refs.roInj.textContent = refs.roBrk.textContent = refs.roAcc.textContent = "--";
    [refs.roSpd, refs.roDrv, refs.roInj, refs.roBrk, refs.roAcc].forEach(el => { el.style.color = ""; el.classList.remove("injected"); });
    refs.dig.textContent = "--";
    refs.spNeedle.style.transform = `rotate(${refs._spAng(0)}deg)`;
    refs.gmNeedle.style.transform = "rotate(0deg)";
    refs.spBody.setAttribute("class", "veh-needle-body");
    refs.tag.setAttribute("opacity", "0");
  },

  update(refs, v) {
    const REDLINE = refs.SP.red, WARN = refs.SP.warn, AXFULL = refs.GM.full;
    if (!v.online || v.speed == null) { this.clear(refs); return { level: "offline", msg: "" }; }

    const spd = Number(v.speed), thr = Number(v.throttle ?? 0), brk = Number(v.brake ?? 0);
    const dThr = Number(v.driverThr ?? thr), dBrk = Number(v.driverBrk ?? brk);
    const g = v.ax == null ? 0 : v.ax / 1000;                 // milli-g -> g
    // injection = the commanded channel diverging from the real driver's pedal
    const injThr = Math.abs(thr - dThr) > 8;                  // commanded throttle != driver
    const injBrk = Math.abs(brk - dBrk) > 8;                  // commanded brake != driver
    const runaway = (thr - dThr) > 8;                         // throttle forced above the driver
    const brakeOverride = (brk - dBrk) > 8;                   // brake forced above the driver
    const injOn = injThr || injBrk;

    // read-outs: DRIVER (real, green) vs COMMANDED (red-pulse when overridden)
    refs.roSpd.textContent = spd.toFixed(0);
    refs.roDrv.textContent = dThr.toFixed(0);
    refs.roInj.textContent = thr.toFixed(0);
    refs.roBrk.textContent = brk.toFixed(0);
    refs.roAcc.textContent = (g >= 0 ? "+" : "") + g.toFixed(2);
    refs.dig.textContent = spd.toFixed(0);
    refs.roSpd.style.color = spd >= REDLINE ? "var(--bad)" : spd >= WARN ? "var(--warn)" : "";
    refs.roDrv.style.color = "var(--ok)";
    refs.roInj.classList.toggle("injected", injThr);
    refs.roBrk.classList.toggle("injected", injBrk);
    refs.roAcc.style.color = g >= 0.07 ? "var(--bad)" : g <= -0.10 ? "var(--accent)" : "";

    // needles follow the applied speed
    refs.spNeedle.style.transform = `rotate(${refs._spAng(spd)}deg)`;
    refs.spBody.setAttribute("class", "veh-needle-body" + (spd >= REDLINE ? " hot" : spd >= WARN ? " warm" : ""));
    const gAng = Math.max(-1, Math.min(1, g / AXFULL)) * 70;
    refs.gmNeedle.style.transform = `rotate(${gAng.toFixed(1)}deg)`;

    refs.tag.setAttribute("opacity", injOn ? "1" : "0");
    refs.tag.textContent = brakeOverride ? "BRAKE FAULT" : "THROTTLE FAULT";

    // instrument cluster: vehicle-condition warnings only
    if (runaway && spd > 80)
      return { level: "critical", msg: "UNINTENDED ACCELERATION - throttle " + thr.toFixed(0) + "%, not tracking pedal" };
    if (brakeOverride && spd > 10)
      return { level: "critical", msg: "BRAKE FAULT - brakes applied, not tracking pedal" };
    if (injOn)
      return { level: "warning", msg: "PEDAL MISMATCH - commanded value not tracking driver input" };
    if (spd >= REDLINE)
      return { level: "warning", msg: "Overspeed - vehicle above the redline" };
    return { level: "normal", msg: "" };
  },
});
