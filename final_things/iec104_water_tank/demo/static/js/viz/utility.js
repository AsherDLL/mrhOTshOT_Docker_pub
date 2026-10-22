// DNP3 water-distribution utility visualization (Industroyer DNP3 module).
// Live read over DNP3 (watch_process Dnp3Reader, on plc-dnp3:20000, Class-0 poll):
//   reservoir = AI0 reservoir level %, pressure = AI1 distribution pressure PSI,
//   chlorine = AI2 residual mg/L, ps1/ps2 = BI0/BI1 pump-station run status,
//   auto = BI3 (AUTO vs MANUAL), low_reservoir/low_pressure = BI5/BI6 alarms.
//
// The story: Industroyer's signature move was masquerading as the SCADA master and
// issuing legitimate control commands to de-energize the process. Adapted to a DNP3
// water utility, the attacker DIRECT-OPERATEs CROBs to stop a pump station and force
// the outstation into MANUAL -- denial of control (T0803/T0813). We surface exactly
// that: pump stations dropping offline, the control mode seized, and supply falling.
registerViz({
  kind: "utility",
  title: "DNP3 Water Utility",

  map(raw) {
    return {
      online: raw.online === true && raw.reservoir != null,
      reservoir: raw.reservoir,
      pressure: raw.pressure_psi,
      chlorine: raw.chlorine,
      ps1: raw.ps1 === true,
      ps2: raw.ps2 === true,
      auto: raw.auto === true,
      lowRes: raw.low_reservoir === true,
      lowPress: raw.low_pressure === true,
    };
  },

  build(stage) {
    const RB = 250, RT = 62, RH = RB - RT;                 // reservoir fill track
    const pump = (id, cx, cy, label) => `
      <g class="ut-pump running" id="${id}">
        <circle class="ut-pump-c" cx="${cx}" cy="${cy}" r="21"/>
        <g class="ut-imp">
          <line x1="${cx - 13}" y1="${cy}" x2="${cx + 13}" y2="${cy}"/>
          <line x1="${cx}" y1="${cy - 13}" x2="${cx}" y2="${cy + 13}"/>
        </g>
        <text class="ut-lbl" x="${cx}" y="${cy + 37}" text-anchor="middle">${label}</text>
        <text class="ut-pump-st" id="${id}-st" x="${cx}" y="${cy + 49}" text-anchor="middle">RUN</text>
      </g>`;

    stage.innerHTML = `
      <div class="viz-readouts">
        <div class="ro"><span class="ro-v" data-r="res">--</span><span class="ro-u">RESERVOIR %</span></div>
        <div class="ro"><span class="ro-v" data-r="prs">--</span><span class="ro-u">PRESSURE PSI</span></div>
        <div class="ro"><span class="ro-v" data-r="cl">--</span><span class="ro-u">CHLORINE mg/L</span></div>
        <div class="ro"><span class="ro-v" data-r="mode">--</span><span class="ro-u">CONTROL</span></div>
      </div>
      <svg class="ut-svg" viewBox="0 0 580 300" role="img" aria-label="DNP3 water distribution utility">
        <text class="ut-title" x="16" y="24">WATER DISTRIBUTION &middot; DNP3 OUTSTATION 1</text>

        <!-- pump stations feeding the reservoir -->
        ${pump("ut-ps1", 44, 96, "PS-1")}
        ${pump("ut-ps2", 44, 186, "PS-2")}
        <path class="ut-pipe" id="ut-pipe1" d="M65,96 H100"/>
        <path class="ut-pipe" id="ut-pipe2" d="M65,186 H82 V150 H100"/>

        <!-- reservoir -->
        <rect class="ut-tank" x="100" y="56" width="96" height="200" rx="4"/>
        <rect class="ut-fill" id="ut-fill" x="104" y="${RB - RH * 0.6}" width="88" height="${RH * 0.6}"/>
        <line class="ut-surf" id="ut-surf" x1="104" y1="${RB - RH * 0.6}" x2="192" y2="${RB - RH * 0.6}"/>
        <line class="ut-low" x1="100" y1="${RB - RH * 0.2}" x2="196" y2="${RB - RH * 0.2}"/>
        <text class="ut-low-lbl" x="192" y="${RB - RH * 0.2 - 4}" text-anchor="end">LOW 20%</text>
        <text class="ut-lbl" x="148" y="272" text-anchor="middle">RESERVOIR</text>

        <!-- distribution main -> chlorination -> pressure -> city -->
        <path class="ut-pipe" id="ut-main" d="M196,230 H360"/>
        <g id="ut-cl-inj">
          <path class="ut-cl-body" d="M232,214 l10,16 l-10,16 l-10,-16 Z"/>
          <text class="ut-lbl" x="232" y="196" text-anchor="middle">Cl2</text>
          <text class="ut-cl-v" id="ut-cl-v" x="232" y="262" text-anchor="middle">--</text>
        </g>
        <!-- pressure gauge (vertical bar on the main) -->
        <rect class="ut-prs-track" x="286" y="150" width="16" height="80" rx="3"/>
        <rect class="ut-prs-fill" id="ut-prs-fill" x="286" y="180" width="16" height="50"/>
        <line class="ut-prs-red" x1="283" y1="${230 - 35 / 80 * 80}" x2="305" y2="${230 - 35 / 80 * 80}"/>
        <text class="ut-lbl" x="294" y="244" text-anchor="middle">PSI</text>

        <!-- city -->
        <g class="ut-city" id="ut-city">
          <rect class="ut-bldg" x="320" y="176" width="26" height="74"/>
          <rect class="ut-bldg" x="350" y="150" width="26" height="100"/>
          <rect class="ut-bldg" x="380" y="192" width="22" height="58"/>
          <rect class="ut-win" x="326" y="186" width="5" height="5"/><rect class="ut-win" x="336" y="186" width="5" height="5"/>
          <rect class="ut-win" x="326" y="202" width="5" height="5"/><rect class="ut-win" x="336" y="202" width="5" height="5"/>
          <rect class="ut-win" x="356" y="162" width="5" height="5"/><rect class="ut-win" x="366" y="162" width="5" height="5"/>
          <rect class="ut-win" x="356" y="180" width="5" height="5"/><rect class="ut-win" x="366" y="180" width="5" height="5"/>
          <rect class="ut-win" x="356" y="198" width="5" height="5"/><rect class="ut-win" x="366" y="198" width="5" height="5"/>
        </g>
        <text class="ut-lbl" x="361" y="270" text-anchor="middle">DISTRIBUTION</text>

        <!-- DNP3 / control panel -->
        <g class="ut-panel" id="ut-panel">
          <rect class="ut-panel-bg" x="418" y="44" width="150" height="212" rx="6"/>
          <rect class="ut-panel-hdr" x="418" y="44" width="150" height="24" rx="6"/>
          <rect class="ut-panel-hdr2" x="418" y="58" width="150" height="10"/>
          <text class="ut-panel-title" x="430" y="61">DNP3 CONTROL</text>
          <text class="ut-panel-sub" x="430" y="88">outstation 1 &middot; master 100</text>

          <text class="ut-k" x="430" y="116">MODE</text>
          <rect class="ut-chip auto" id="ut-mode-chip" x="486" y="103" width="74" height="18" rx="4"/>
          <text class="ut-chip-t" id="ut-mode-t" x="523" y="116" text-anchor="middle">AUTO</text>

          <text class="ut-k" x="430" y="144">CMD SOURCE</text>
          <rect class="ut-chip ok" id="ut-src-chip" x="486" y="131" width="74" height="18" rx="4"/>
          <text class="ut-chip-t" id="ut-src-t" x="523" y="144" text-anchor="middle">SCADA</text>

          <line class="ut-rule" x1="430" y1="160" x2="556" y2="160"/>
          <circle class="ut-led" id="ut-al-res" cx="436" cy="180" r="5"/>
          <text class="ut-al" x="448" y="184">LOW RESERVOIR</text>
          <circle class="ut-led" id="ut-al-prs" cx="436" cy="202" r="5"/>
          <text class="ut-al" x="448" y="206">LOW PRESSURE</text>
          <circle class="ut-led" id="ut-al-ps" cx="436" cy="224" r="5"/>
          <text class="ut-al" x="448" y="228">PUMP STATION DOWN</text>

          <text class="ut-note" id="ut-note" x="430" y="248">outstation nominal</text>
        </g>
      </svg>`;

    const q = s => stage.querySelector(s);
    return {
      stage, RB, RH,
      roRes: q('[data-r="res"]'), roPrs: q('[data-r="prs"]'), roCl: q('[data-r="cl"]'), roMode: q('[data-r="mode"]'),
      ps1: q('#ut-ps1'), ps2: q('#ut-ps2'), ps1st: q('#ut-ps1-st'), ps2st: q('#ut-ps2-st'),
      pipe1: q('#ut-pipe1'), pipe2: q('#ut-pipe2'), main: q('#ut-main'),
      fill: q('#ut-fill'), surf: q('#ut-surf'), clv: q('#ut-cl-v'),
      prsFill: q('#ut-prs-fill'), city: q('#ut-city'),
      modeChip: q('#ut-mode-chip'), modeT: q('#ut-mode-t'),
      srcChip: q('#ut-src-chip'), srcT: q('#ut-src-t'),
      alRes: q('#ut-al-res'), alPrs: q('#ut-al-prs'), alPs: q('#ut-al-ps'), note: q('#ut-note'),
    };
  },

  clear(refs) {
    refs.roRes.textContent = refs.roPrs.textContent = refs.roCl.textContent = "--";
    refs.roMode.textContent = "--"; refs.roMode.style.color = "";
    [refs.ps1, refs.ps2].forEach(p => p.setAttribute("class", "ut-pump running"));
    refs.ps1st.textContent = refs.ps2st.textContent = "RUN";
    refs.pipe1.setAttribute("class", "ut-pipe flowing");
    refs.pipe2.setAttribute("class", "ut-pipe flowing");
    refs.main.setAttribute("class", "ut-pipe flowing");
    refs.modeChip.setAttribute("class", "ut-chip auto"); refs.modeT.textContent = "AUTO";
    refs.srcChip.setAttribute("class", "ut-chip ok"); refs.srcT.textContent = "SCADA";
    [refs.alRes, refs.alPrs, refs.alPs].forEach(a => a.setAttribute("class", "ut-led"));
    refs.city.setAttribute("class", "ut-city");
    refs.note.textContent = "outstation nominal";
  },

  update(refs, v) {
    const fmt = (x, d) => (x == null ? "--" : Number(x).toFixed(d));
    if (!v.online) {
      refs.roRes.textContent = refs.roPrs.textContent = refs.roCl.textContent = "--";
      refs.roMode.textContent = "--"; refs.roMode.style.color = "";
      return { level: "offline", msg: "" };
    }
    const { RB, RH } = refs;
    const res = Math.max(0, Math.min(100, v.reservoir));
    const seized = !v.auto;
    const stopped = (v.ps1 ? 0 : 1) + (v.ps2 ? 0 : 1);
    const supplyLost = stopped === 2 || v.lowRes || res < 20;

    // reservoir fill
    const h = RH * res / 100, y = RB - h;
    refs.fill.setAttribute("y", y.toFixed(1)); refs.fill.setAttribute("height", h.toFixed(1));
    refs.surf.setAttribute("y1", y.toFixed(1)); refs.surf.setAttribute("y2", y.toFixed(1));
    refs.fill.setAttribute("class", "ut-fill" + (v.lowRes || res < 20 ? " lowres" : res < 40 ? " warn" : ""));

    // pumps
    const setPump = (grp, st, run) => {
      grp.setAttribute("class", "ut-pump " + (run ? "running" : "stopped"));
      st.textContent = run ? "RUN" : "STOP";
    };
    setPump(refs.ps1, refs.ps1st, v.ps1);
    setPump(refs.ps2, refs.ps2st, v.ps2);
    refs.pipe1.setAttribute("class", "ut-pipe" + (v.ps1 ? " flowing" : ""));
    refs.pipe2.setAttribute("class", "ut-pipe" + (v.ps2 ? " flowing" : ""));
    refs.main.setAttribute("class", "ut-pipe" + (!supplyLost ? " flowing" : ""));

    // pressure bar (0..80 PSI, red below 35)
    const psi = Math.max(0, Math.min(80, v.pressure == null ? 0 : v.pressure));
    const ph = 80 * psi / 80, py = 230 - ph;
    refs.prsFill.setAttribute("y", py.toFixed(1)); refs.prsFill.setAttribute("height", ph.toFixed(1));
    refs.prsFill.setAttribute("class", "ut-prs-fill" + (psi < 35 || v.lowPress ? " low" : ""));

    refs.clv.textContent = fmt(v.chlorine, 2);
    refs.city.setAttribute("class", "ut-city" + (supplyLost ? " dark" : res < 40 ? " dim" : ""));

    // readouts
    refs.roRes.textContent = fmt(res, 0);
    refs.roPrs.textContent = fmt(v.pressure, 0);
    refs.roCl.textContent = fmt(v.chlorine, 2);
    refs.roMode.textContent = seized ? "MANUAL" : "AUTO";
    refs.roMode.style.color = seized ? "var(--bad)" : "var(--ok)";

    // DNP3 panel
    refs.modeChip.setAttribute("class", "ut-chip " + (seized ? "manual" : "auto"));
    refs.modeT.textContent = seized ? "MANUAL" : "AUTO";
    const rogue = seized || stopped > 0;                 // control commands not from the trusted master
    refs.srcChip.setAttribute("class", "ut-chip " + (rogue ? "rogue" : "ok"));
    refs.srcT.textContent = rogue ? "MANUAL" : "SCADA";
    refs.alRes.setAttribute("class", "ut-led" + (v.lowRes || res < 20 ? " bad" : ""));
    refs.alPrs.setAttribute("class", "ut-led" + (v.lowPress || (v.pressure != null && v.pressure < 35) ? " warn" : ""));
    refs.alPs.setAttribute("class", "ut-led" + (stopped ? " bad" : ""));

    // banner + note (operator HMI: process conditions only)
    if (supplyLost) {
      refs.note.textContent = "supply lost";
      return { level: "critical", msg: `SUPPLY LOST - ${stopped === 2 ? "both pump stations stopped" : "reservoir critically low"}, distribution failing` };
    }
    if (seized && stopped) {
      refs.note.textContent = "pump station stopped";
      return { level: "critical", msg: `PUMP STATION ${v.ps1 ? "2" : "1"} STOPPED - distribution pressure falling, station in manual` };
    }
    if (seized) {
      refs.note.textContent = "manual mode";
      return { level: "warning", msg: "OUTSTATION IN MANUAL - automatic control not active" };
    }
    if (stopped) {
      refs.note.textContent = "pump station down";
      return { level: "warning", msg: `Pump Station ${v.ps1 ? "2" : "1"} stopped - low discharge pressure` };
    }
    refs.note.textContent = "outstation nominal";
    return { level: "normal", msg: "" };
  },
});
