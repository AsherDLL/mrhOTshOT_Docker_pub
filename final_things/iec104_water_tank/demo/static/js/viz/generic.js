// Neutral fallback visualization, driven entirely by the protocol's IO_POINTS table.
//
// It names no process fields of its own. Every readout and every alarm comes from
// watch_process.IO_POINTS[proto], which the server already ships to the page as
// window.WATCH.io - the same table that fills the I/O MAP panel. So adding a channel
// or an alarm to any protocol is one dict row in Python, with no change here, and all
// eleven protocols get a working view rather than only the ones with a bespoke module.
//
// A point may carry an optional alarm:
//   {"key": "cpu_run", "alarm": {"equals": false, "level": "critical", "msg": "..."}}
// Supported tests: equals / above / below. The highest-severity match wins. Stick to
// the four levels visualizer.js knows (normal|warning|critical|offline) - it falls
// back to OFFLINE for anything else.
registerViz({
  kind: "generic",
  title: "Process",

  map(raw) { return raw; },   // the IO_POINTS keys are paths into the raw reader dict

  build(stage) {
    const U = window.VIZ_UTIL;
    const all = ((window.WATCH && window.WATCH.io && window.WATCH.io.points) || [])
      .filter(p => p.key);
    // Alarm-carrying points first so the ones that can raise the banner are always
    // on screen, then the rest, capped so the strip stays readable.
    const tiles = all.slice().sort((a, b) => (b.alarm ? 1 : 0) - (a.alarm ? 1 : 0)).slice(0, 8);

    stage.innerHTML = `
      <div class="viz-readouts">
        ${tiles.map((p, i) => `
          <div class="ro"><span class="ro-v" data-g="${i}">--</span>
          <span class="ro-u">${U.esc(p.label || p.addr || "")}</span></div>`).join("")}
      </div>
      <div class="viz-generic">
        <div class="viz-generic-chip" id="g-chip">CONNECTING</div>
        <p>Live channels read from the target PLC, listed exactly as the protocol's I/O
        map defines them. This process has no purpose-drawn picture, so the real values
        are shown rather than a shape that would imply the wrong process.</p>
      </div>`;

    return {
      tiles,
      cells: tiles.map((_, i) => stage.querySelector(`[data-g="${i}"]`)),
      alarms: all.filter(p => p.alarm),
      chip: stage.querySelector("#g-chip"),
    };
  },

  clear(refs) {
    refs.cells.forEach(c => { c.textContent = "--"; c.classList.remove("injected"); });
    refs.chip.textContent = "CONNECTING";
    refs.chip.className = "viz-generic-chip";
  },

  update(refs, v) {
    const U = window.VIZ_UTIL;
    if (v.online === false) {
      refs.cells.forEach(c => { c.textContent = "--"; c.classList.remove("injected"); });
      refs.chip.textContent = "OFFLINE";
      refs.chip.className = "viz-generic-chip off";
      return { level: "offline", msg: "" };
    }

    const fired = new Set();
    const RANK = { normal: 0, warning: 1, critical: 2 };
    let level = "normal", msg = "";
    for (const p of refs.alarms) {
      const a = p.alarm, val = U.digPath(v, p.key);
      const hit = ("equals" in a) ? val === a.equals
        : ("above" in a) ? (typeof val === "number" && val > a.above)
          : ("below" in a) ? (typeof val === "number" && val < a.below)
            : false;
      if (!hit) continue;
      fired.add(p.key);
      if ((RANK[a.level] || 0) > (RANK[level] || 0)) { level = a.level; msg = a.msg || ""; }
    }

    refs.tiles.forEach((p, i) => {
      refs.cells[i].textContent = U.fmtIo(U.digPath(v, p.key));
      refs.cells[i].classList.toggle("injected", fired.has(p.key));   // red pulse on alarm
    });

    refs.chip.textContent = level === "normal" ? "LIVE" : "ALARM";
    refs.chip.className = "viz-generic-chip " + (level === "normal" ? "live" : "off");
    return { level, msg };
  },
});
