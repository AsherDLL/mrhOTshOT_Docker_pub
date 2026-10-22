// M-Bus sensor-gateway visualization (Fuxnet / Moscollector, 2024).
// Live read over M-Bus (watch_process MbusReader, on plc-sensors:5000, REQ_UD2):
//   gw_state = online | corrupted | offline (inferred from the wire),
//   volume/pressure/temperature = the gateway's metered records.
//
// The story Fuxnet tells: the Blackjack group flooded municipal M-Bus gateways to
// destroy them -- 87,000 Moscow sensors bricked in January 2024. First an SND_UD
// flood CORRUPTS the gateway so every reading collapses to garbage (temp -40, pressure
// 0, volume 99999.9) -- operators see spoofed data. Then a broadcast SND_NKE (0xFF)
// bricks it OFFLINE: the gateway drops the bus and the whole field goes dark. We read
// those three states straight off M-Bus and show the field being poisoned, then lost.
registerViz({
  kind: "sensors",
  title: "M-Bus Sensor Gateway",

  map(raw) {
    return {
      online: raw.online === true,
      gw: raw.gw_state || (raw.online ? "online" : null),
      volume: raw.volume,
      pressure: raw.pressure,
      temperature: raw.temperature,
    };
  },

  build(stage) {
    const COLS = 6, ROWS = 4, X0 = 246, DX = 52, Y0 = 86, DY = 40;
    let nodes = "", cols = "";
    for (let c = 0; c < COLS; c++) {
      const x = X0 + c * DX;
      cols += `<line class="sn-branch" x1="${x}" y1="72" x2="${x}" y2="220"/>`;
      for (let r = 0; r < ROWS; r++) {
        const i = c * ROWS + r;
        nodes += `<circle class="sn-node live" id="sn-n-${i}" cx="${x}" cy="${Y0 + r * DY}" r="7" style="animation-delay:${(i % 7) * 0.18}s"/>`;
      }
    }

    stage.innerHTML = `
      <div class="viz-readouts">
        <div class="ro"><span class="ro-v" data-r="vol">--</span><span class="ro-u">VOLUME L</span></div>
        <div class="ro"><span class="ro-v" data-r="prs">--</span><span class="ro-u">PRESSURE bar</span></div>
        <div class="ro"><span class="ro-v" data-r="tmp">--</span><span class="ro-u">TEMP &deg;C</span></div>
        <div class="ro"><span class="ro-v" data-r="tel">--</span><span class="ro-u">TELEMETRY</span></div>
      </div>
      <svg class="sn-svg" viewBox="0 0 560 300" role="img" aria-label="M-Bus sensor gateway and field">
        <text class="sn-lbl" x="246" y="58">FIELD SENSORS &middot; M-BUS EN 13757-3 &middot; (87,000 in Moscow)</text>

        <!-- M-Bus trunk + column branches + sensor nodes -->
        <line class="sn-trunk" id="sn-trunk" x1="152" y1="150" x2="510" y2="150"/>
        ${cols}
        ${nodes}

        <!-- gateway -->
        <g class="sn-gw online" id="sn-gw">
          <rect class="sn-gw-bg" x="20" y="92" width="132" height="118" rx="6"/>
          <rect class="sn-gw-hdr" x="20" y="92" width="132" height="24" rx="6"/>
          <rect class="sn-gw-hdr2" x="20" y="106" width="132" height="10"/>
          <text class="sn-gw-title" x="32" y="109">M-BUS GATEWAY</text>
          <text class="sn-gw-sub" x="32" y="134">Moscollector PLC-9</text>
          <text class="sn-gw-sub" x="32" y="148">TCP :5000</text>
          <circle class="sn-gw-led" id="sn-gw-led" cx="38" cy="172" r="6"/>
          <text class="sn-gw-st" id="sn-gw-st" x="52" y="176">ONLINE</text>
          <text class="sn-gw-kill" id="sn-gw-kill" x="32" y="198" opacity="0">COMM FAILURE</text>
        </g>
      </svg>`;

    const q = s => stage.querySelector(s);
    const nodeEls = [];
    for (let i = 0; i < COLS * ROWS; i++) nodeEls.push(q(`#sn-n-${i}`));
    return {
      stage, nodeEls,
      roVol: q('[data-r="vol"]'), roPrs: q('[data-r="prs"]'), roTmp: q('[data-r="tmp"]'), roTel: q('[data-r="tel"]'),
      gw: q('#sn-gw'), gwLed: q('#sn-gw-led'), gwSt: q('#sn-gw-st'), gwKill: q('#sn-gw-kill'),
      trunk: q('#sn-trunk'),
    };
  },

  clear(refs) {
    refs.roVol.textContent = refs.roPrs.textContent = refs.roTmp.textContent = "--";
    refs.roTel.textContent = "--"; refs.roTel.style.color = "";
    refs.gw.setAttribute("class", "sn-gw online");
    refs.gwSt.textContent = "ONLINE"; refs.gwKill.setAttribute("opacity", "0");
    refs.trunk.setAttribute("class", "sn-trunk");
    refs.nodeEls.forEach(n => n.setAttribute("class", "sn-node live"));
  },

  update(refs, v) {
    const fmt = (x, d) => (x == null ? "--" : Number(x).toFixed(d));
    if (!v.online) {
      refs.roVol.textContent = refs.roPrs.textContent = refs.roTmp.textContent = "--";
      refs.roTel.textContent = "--"; refs.roTel.style.color = "";
      return { level: "offline", msg: "" };
    }
    const gw = v.gw;                                   // online | corrupted | offline
    const nodeCls = gw === "offline" ? "sn-node dark" : gw === "corrupted" ? "sn-node poison" : "sn-node live";
    refs.nodeEls.forEach(n => n.setAttribute("class", nodeCls));

    refs.gw.setAttribute("class", "sn-gw " + gw);
    refs.gwSt.textContent = gw === "offline" ? "OFFLINE" : gw === "corrupted" ? "CORRUPTED" : "ONLINE";
    refs.gwKill.setAttribute("opacity", gw === "offline" ? "1" : "0");
    refs.trunk.setAttribute("class", "sn-trunk" + (gw === "offline" ? " severed" : ""));

    // readouts (show the poison values verbatim when corrupted -- that IS the tell)
    const dead = gw === "offline";
    refs.roVol.textContent = dead ? "--" : fmt(v.volume, 0);
    refs.roPrs.textContent = dead ? "--" : fmt(v.pressure, 2);
    refs.roTmp.textContent = dead ? "--" : fmt(v.temperature, 0);
    const bad = gw !== "online";
    [refs.roVol, refs.roPrs, refs.roTmp].forEach(el => el.style.color = bad ? "var(--bad)" : "");
    refs.roTel.textContent = gw === "offline" ? "LOST" : gw === "corrupted" ? "INVALID" : "LIVE";
    refs.roTel.style.color = gw === "offline" ? "var(--bad)" : gw === "corrupted" ? "var(--warn)" : "var(--ok)";

    // operator HMI: process/telemetry conditions only
    if (gw === "offline")
      return { level: "critical", msg: "SENSOR COMM FAILURE - gateway offline, no data from field meters" };
    if (gw === "corrupted")
      return { level: "warning", msg: "SENSOR DATA INVALID - readings out of range, meter fault" };
    return { level: "normal", msg: "" };
  },
});
