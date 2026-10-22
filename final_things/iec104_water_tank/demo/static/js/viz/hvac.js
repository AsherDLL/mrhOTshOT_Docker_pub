// Building-HVAC visualization (FrostyGoop-on-BACnet / air-handling unit).
// Live read over BACnet/IP (watch_process BacnetHvacReader, on plc-hvac:47808):
//   zone_temp, supply_air (C), heating/cooling/fan (bool), auto (control loop on),
//   hi_alarm (high-temp alarm). The DDC serves these as BACnet AnalogInputs.
//
// The story: a Schneider DDC keeps the zone in band by modulating a cooling and a
// heating coil under an AUTO control loop. The attack writes BACnet AnalogOutputs to
// DISABLE the loop (AutoModeCmd), force cooling OFF and heating to 100%, and run the
// fan -- so it pumps hot air into the space and the zone climbs to the high-temp
// alarm with the operator's loop locked out. We read that straight off the DDC.
registerViz({
  kind: "hvac",
  title: "Building HVAC",

  map(raw) {
    return {
      online: raw.online === true && raw.zone_temp != null,
      zone: raw.zone_temp,
      supply: raw.supply_air,
      heating: raw.heating === true,
      cooling: raw.cooling === true,
      fan: raw.fan === true,
      auto: raw.auto === true,
      alarm: raw.hi_alarm === true,
    };
  },

  build(stage) {
    const TMIN = 10, TMAX = 55, BAR_BOT = 232, BAR_TOP = 70;   // thermometer scale
    const yFor = t => BAR_BOT - (Math.max(TMIN, Math.min(TMAX, t)) - TMIN) / (TMAX - TMIN) * (BAR_BOT - BAR_TOP);
    stage.innerHTML = `
      <div class="viz-readouts">
        <div class="ro"><span class="ro-v" data-r="zone">--</span><span class="ro-u">ZONE &deg;C</span></div>
        <div class="ro"><span class="ro-v" data-r="supply">--</span><span class="ro-u">SUPPLY AIR &deg;C</span></div>
        <div class="ro"><span class="ro-v" data-r="mode">--</span><span class="ro-u">CONTROL LOOP</span></div>
        <div class="ro"><span class="ro-v" data-r="alarm">--</span><span class="ro-u">HIGH-TEMP</span></div>
      </div>
      <svg class="hv-svg" viewBox="0 0 560 300" role="img" aria-label="air-handling unit feeding a building zone">
        <!-- outdoor intake -->
        <text class="hv-lbl" x="34" y="120" text-anchor="middle">OUTDOOR</text>
        <text class="hv-lbl2" x="34" y="132" text-anchor="middle">45&deg;C</text>
        <line class="hv-air" id="hv-intake" x1="12" y1="150" x2="60" y2="150"/>

        <!-- air-handling unit housing -->
        <rect class="hv-ahu" x="60" y="96" width="250" height="108" rx="6"/>
        <text class="hv-ahu-tag" x="70" y="112">AIR-HANDLING UNIT</text>

        <!-- cooling coil -->
        <g id="hv-cool">
          <rect class="hv-coil hv-coil-c" x="86" y="128" width="44" height="60" rx="3"/>
          <path class="hv-coil-pipe" d="M92,138 h32 M92,150 h32 M92,162 h32 M92,174 h32"/>
          <text class="hv-coil-lbl" x="108" y="200" text-anchor="middle">COOL</text>
        </g>
        <!-- heating coil -->
        <g id="hv-heat">
          <rect class="hv-coil hv-coil-h" x="148" y="128" width="44" height="60" rx="3"/>
          <path class="hv-coil-pipe" d="M154,138 h32 M154,150 h32 M154,162 h32 M154,174 h32"/>
          <text class="hv-coil-lbl" x="170" y="200" text-anchor="middle">HEAT</text>
        </g>
        <!-- supply fan -->
        <g id="hv-fan" transform="translate(258 158)">
          <circle class="hv-fan-ring" r="26"/>
          <g class="hv-fan-blades" id="hv-fan-blades">
            <path d="M0,-22 Q7,-8 0,0 Q-7,-8 0,-22 Z"/>
            <path d="M22,0 Q8,7 0,0 Q8,-7 22,0 Z"/>
            <path d="M0,22 Q-7,8 0,0 Q7,8 0,22 Z"/>
            <path d="M-22,0 Q-8,-7 0,0 Q-8,7 -22,0 Z"/>
          </g>
          <circle class="hv-fan-hub" r="4"/>
        </g>
        <text class="hv-coil-lbl" x="258" y="200" text-anchor="middle">FAN</text>

        <!-- supply duct into the zone -->
        <line class="hv-air" id="hv-supply" x1="310" y1="150" x2="392" y2="150"/>
        <text class="hv-lbl" x="352" y="142" text-anchor="middle">SUPPLY</text>

        <!-- zone / occupied space with a thermometer -->
        <rect class="hv-zone" x="392" y="60" width="156" height="180" rx="6"/>
        <text class="hv-zone-tag" x="400" y="76">OCCUPIED ZONE</text>
        <!-- thermometer -->
        <rect class="hv-therm-track" x="500" y="${BAR_TOP}" width="20" height="${BAR_BOT - BAR_TOP}" rx="10"/>
        <rect class="hv-therm-fill hv-ok" id="hv-fill" x="500" y="${yFor(20)}" width="20" height="${BAR_BOT - yFor(20)}" rx="10"/>
        <circle class="hv-therm-bulb" id="hv-bulb" cx="510" cy="244" r="15"/>
        <line class="hv-therm-alarm" x1="472" y1="${yFor(50)}" x2="522" y2="${yFor(50)}"/>
        <text class="hv-tick" x="470" y="${yFor(50) + 3}" text-anchor="end">50</text>
        <line class="hv-therm-set" x1="480" y1="${yFor(40)}" x2="522" y2="${yFor(40)}"/>
        <text class="hv-tick" x="470" y="${yFor(40) + 3}" text-anchor="end">40</text>
        <!-- occupants: warm -> distressed by zone temp -->
        <g id="hv-occ">
          <circle class="hv-occ-dot" cx="412" cy="150" r="7"/>
          <circle class="hv-occ-dot" cx="436" cy="176" r="7"/>
          <circle class="hv-occ-dot" cx="420" cy="205" r="7"/>
        </g>

        <!-- DDC controller state banner -->
        <g id="hv-ddc">
          <rect class="hv-ddc-bg" id="hv-ddc-bg" x="60" y="222" width="250" height="30" rx="5"/>
          <text class="hv-ddc-t" id="hv-ddc-t" x="185" y="242" text-anchor="middle">DDC &middot; AUTO</text>
        </g>
      </svg>`;
    const q = s => stage.querySelector(s);
    return {
      stage, yFor, TMIN, TMAX, BAR_BOT,
      zone: q('[data-r="zone"]'), supply: q('[data-r="supply"]'),
      mode: q('[data-r="mode"]'), alarm: q('[data-r="alarm"]'),
      fill: q('#hv-fill'), bulb: q('#hv-bulb'), heat: q('#hv-heat'), cool: q('#hv-cool'),
      fan: q('#hv-fan'), blades: q('#hv-fan-blades'), supplyAir: q('#hv-supply'),
      intake: q('#hv-intake'), occ: q('#hv-occ'), ddcBg: q('#hv-ddc-bg'), ddcT: q('#hv-ddc-t'),
    };
  },

  clear(refs) {
    refs.zone.textContent = refs.supply.textContent = refs.mode.textContent = refs.alarm.textContent = "--";
    refs.mode.style.color = refs.alarm.style.color = "";
    refs.fill.setAttribute("y", refs.yFor(20));
    refs.fill.setAttribute("height", refs.BAR_BOT - refs.yFor(20));
    refs.fill.setAttribute("class", "hv-therm-fill hv-ok");
    refs.bulb.setAttribute("class", "hv-therm-bulb hv-ok");
    refs.heat.classList.remove("on"); refs.cool.classList.remove("on");
    refs.fan.classList.remove("on"); refs.supplyAir.setAttribute("class", "hv-air");
    refs.occ.setAttribute("class", ""); refs.ddcBg.setAttribute("class", "hv-ddc-bg");
    refs.ddcT.textContent = "DDC · AUTO";
  },

  update(refs, v) {
    if (!v.online) {
      refs.zone.textContent = refs.supply.textContent = "--";
      refs.mode.textContent = refs.alarm.textContent = "--";
      refs.mode.style.color = refs.alarm.style.color = "";
      return { level: "offline", msg: "" };
    }
    const zone = v.zone, seized = !v.auto;
    const hot = v.alarm || zone >= 48, warm = !hot && zone >= 41;
    const band = hot ? "hot" : warm ? "warm" : "ok";

    // thermometer
    const y = refs.yFor(zone);
    refs.fill.setAttribute("y", y);
    refs.fill.setAttribute("height", refs.BAR_BOT - y);
    refs.fill.setAttribute("class", "hv-therm-fill hv-" + band);
    refs.bulb.setAttribute("class", "hv-therm-bulb hv-" + band);

    // coils + fan + airflow
    refs.heat.classList.toggle("on", v.heating);
    refs.cool.classList.toggle("on", v.cooling);
    refs.fan.classList.toggle("on", v.fan);
    // supply-air duct tint: hot air (heating) red, cooled air blue, neutral grey
    refs.supplyAir.setAttribute("class", "hv-air" +
      (v.fan ? (v.heating && !v.cooling ? " flow-hot" : v.cooling ? " flow-cold" : " flow") : ""));
    refs.occ.setAttribute("class", band === "hot" ? "hv-distress" : "");

    // readouts
    refs.zone.textContent = zone.toFixed(1);
    refs.supply.textContent = v.supply != null ? v.supply.toFixed(1) : "--";
    refs.mode.textContent = seized ? "MANUAL" : "AUTO";
    refs.mode.style.color = seized ? "var(--bad)" : "var(--ok)";
    refs.alarm.textContent = v.alarm ? "ALARM" : "ok";
    refs.alarm.style.color = v.alarm ? "var(--bad)" : "var(--ok)";

    // DDC banner
    refs.ddcBg.setAttribute("class", "hv-ddc-bg" + (seized ? " seized" : ""));
    refs.ddcT.textContent = seized ? "DDC · MANUAL" : "DDC · AUTO";

    // alert level + banner message (operator HMI: process conditions only)
    if (v.alarm)
      return { level: "critical", msg: `ZONE TEMP HIGH - zone ${zone.toFixed(0)}°C, cooling unavailable, heating at max` };
    if (seized && zone >= 44)
      return { level: "critical", msg: `ZONE OVERHEAT - heating at max, cooling off, zone ${zone.toFixed(0)}°C rising` };
    if (seized)
      return { level: "warning", msg: "AHU IN MANUAL - control loop not regulating, setpoint not held" };
    if (warm)
      return { level: "warning", msg: `Zone above setpoint (${zone.toFixed(0)}°C)` };
    return { level: "normal", msg: "" };
  },
});
