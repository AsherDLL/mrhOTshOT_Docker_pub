// Visualizer shell: owns the generic chrome (alert banner, status chip, controls,
// narration) and delegates the process picture to a per-process module (window.VIZ).
//
// Two independent lifecycles, in separate panes:
//   SIMULATION  (Start <-> End simulation, Reset target) - drives the live view.
//   ATTACK      (Launch / Pause / Resume / Stop, + capture) - drives the real attack.
// Nothing auto-starts: on load the view is idle (readouts "--") unless an attack is
// already running elsewhere. Pause stops the attacker AND restores normal control so
// the plant recovers; Resume re-launches it.
(() => {
  const byId = id => document.getElementById(id);
  const cfg = window.WATCH || {};
  const id = cfg.id;
  const mod = window.VIZ && (window.VIZ[cfg.kind] || window.VIZ.generic);
  const stage = byId("viz-stage");
  if (!mod || !stage) return;
  let refs = mod.build(stage);

  // ---- alert banner + status chip (driven by the module's {level,msg}) ----
  const banner = byId("viz-banner"), chip = byId("viz-status"), chipLamp = byId("viz-chip-lamp");
  const CHIP = { normal: ["NOMINAL", "lamp lamp-ok"], warning: ["WARNING", "lamp lamp-run"],
                 critical: ["EMERGENCY", "lamp lamp-bad"], offline: ["OFFLINE", "lamp"] };
  function setAlert(level, msg) {
    const [t, l] = CHIP[level] || CHIP.offline;
    chip.textContent = t; chipLamp.className = l; chip.className = "viz-status s-" + level;
    if (level === "warning" || level === "critical") {
      banner.className = "viz-banner show " + level;
      banner.innerHTML = "<span>&#9888;</span> " + (level === "critical" ? "EMERGENCY: " : "WARNING: ") + (msg || "");
    } else {
      banner.className = "viz-banner";
    }
  }
  function idleChip() {   // simulation stopped: neutral, no target reading
    chip.textContent = "-"; chipLamp.className = "lamp"; chip.className = "viz-status s-offline";
    banner.className = "viz-banner";
  }

  // ---- protocol I/O map (the registers/coils/points this attack touches) ----
  const ioEl = byId("viz-io"), ioBody = byId("viz-io-body"), ioEp = byId("viz-io-ep");
  let ioCells = [];
  const { digPath, fmtIo } = window.VIZ_UTIL;   // shared with the viz modules (registry.js)
  function buildIoMap(io) {
    const pts = (io && io.points) || [];
    if (!ioEl || !ioBody || !pts.length) { if (ioEl) ioEl.hidden = true; return; }
    if (ioEp) ioEp.textContent = ((cfg.proto || "").toUpperCase() + " · " + (cfg.plc || "") + (io.endpoint || "")).trim();
    ioBody.textContent = "";
    ioCells = [];
    const cell = (cls, txt) => { const td = document.createElement("td"); if (cls) td.className = cls; td.textContent = txt || ""; return td; };
    for (const p of pts) {
      const tr = document.createElement("tr");
      tr.append(cell("io-dir io-" + (p.rw || "R").toLowerCase(), p.rw || "R"),
                cell("io-addr", p.addr), cell("io-type", p.type),
                cell(null, p.label), cell("io-val", p.key ? "--" : ""));
      ioBody.appendChild(tr);
      if (p.key) ioCells.push({ el: tr.lastChild, key: p.key });
    }
    ioEl.hidden = false;
  }
  function updateIoMap(raw) { for (const c of ioCells) c.el.textContent = fmtIo(digPath(raw, c.key)); }
  function clearIoMap() { for (const c of ioCells) c.el.textContent = "--"; }

  // ---- process stream (the live mimic) ----
  let procStream = null;
  function openProcessStream() {
    if (procStream) procStream.close();
    stage.classList.remove("sim-off");
    procStream = new EventSource(cfg.stream);
    procStream.addEventListener("meta", ev => {
      try { byId("viz-proc").textContent = (JSON.parse(ev.data).process) || cfg.name; } catch (e) { /* */ }
    });
    procStream.onmessage = ev => {
      try {
        const raw = JSON.parse(ev.data);
        const res = mod.update(refs, mod.map(raw)) || {};
        setAlert(res.level || "normal", res.msg || "");
        updateIoMap(raw);
      } catch (e) { /* */ }
    };
    procStream.onerror = () => { /* server-side reader reconnects */ };
  }
  function closeProcessStream() {
    if (procStream) { procStream.close(); procStream = null; }
  }
  function clearStage() {          // reset the picture to its pristine "--" state
    closeProcessStream();
    if (mod.clear) mod.clear(refs); else refs = mod.build(stage);
    stage.classList.add("sim-off");
    idleChip();
    clearIoMap();
  }

  // ---- narration / lifecycle state ----
  const logEl = byId("viz-log"), logLamp = byId("viz-log-lamp"), logHint = byId("viz-log-hint");
  const logGroup = byId("viz-log-group"), btnExpand = byId("viz-log-expand");
  const btnStart = byId("viz-start"), btnReset = byId("viz-reset"), btnLaunch = byId("viz-launch"),
        btnPause = byId("viz-pause"), btnResume = byId("viz-resume"), btnStop = byId("viz-stop"),
        capCb = byId("viz-capture");
  let logStream = null, simState = "stopped", attackState = "idle",
      suppressDone = false, busy = false;

  function classify(l) {
    l = l.toLowerCase();
    if (/error|fail|denied|exception|traceback/.test(l)) return "bad";
    if (/warn|alarm|overflow|trip|freeze|forcing|\bstop/.test(l)) return "warn";
    if (/\[\+\]|success|connected|complete|started|restored|reset|compromised|root shell/.test(l)) return "ok";
    if (/phase|attack|launch|===|coil|fc0|fc5|fc6|modbus|write|inject|router|pivot/.test(l)) return "info";
    if (/\[log\]|finished|\[ui\]/.test(l)) return "dim";
    return "";
  }
  function logln(line) {
    const s = document.createElement("span");
    const c = classify(line); if (c) s.className = c;
    s.textContent = line + "\n";
    logEl.appendChild(s);
    while (logEl.childElementCount > 500) logEl.removeChild(logEl.firstElementChild);  // cap DOM growth
    logEl.scrollTop = logEl.scrollHeight;
  }

  function updateAttackAvailability() {
    if (btnLaunch) {
      const blocked = simState !== "running";
      btnLaunch.disabled = blocked;
      btnLaunch.title = blocked ? "Start the simulation first" : "";
    }
  }
  function setSimState(st) {
    simState = st;
    if (st === "running") { btnStart.className = "btn btn-stop"; btnStart.innerHTML = "&#9632; End simulation"; }
    else { btnStart.className = "btn btn-run"; btnStart.innerHTML = "&#9654; Start simulation"; }
    updateAttackAvailability();
  }
  function setAttackState(st) {
    attackState = st;
    const show = (b, on) => b && b.classList.toggle("hidden", !on);
    show(btnLaunch, st === "idle");
    show(btnPause, st === "running");
    show(btnResume, st === "paused");
    show(btnStop, st === "running" || st === "paused");
    logLamp.className = "lamp" + (st === "running" ? " running" : st === "paused" ? " lamp-run" : "");
    logHint.textContent = st;
    updateAttackAvailability();
  }
  function openLog() {   // call AFTER launch, so the stream reflects a running attack
    if (logStream) logStream.close();
    logStream = new EventSource(`/stream/${id}`);
    logStream.onmessage = e => { try { logln(JSON.parse(e.data)); } catch (x) { /* */ } };
    logStream.addEventListener("done", () => {
      if (logStream) { logStream.close(); logStream = null; }
      if (!suppressDone && attackState === "running") setAttackState("idle");   // natural finish
      suppressDone = false;
    });
  }
  const post = async (url, bodyObj) => {
    try {
      return await (await fetch(url, { method: "POST", headers: { "Content-Type": "application/json" },
                                       body: JSON.stringify(bodyObj || {}) })).json();
    } catch (e) { return {}; }
  };

  // ---- SIMULATION lifecycle ----
  async function startSim() {
    if (busy) return; busy = true;
    logln("[ui] starting simulation - bringing the target to normal operation...");
    await post(`/restore/${id}`);        // fast normal-control restore where defined
    openProcessStream();
    setSimState("running");
    logln("[ui] simulation running - live values from the target");
    busy = false;
  }
  async function endSim() {
    if (busy) return; busy = true;
    if (attackState !== "idle") { suppressDone = true; await post(`/stop/${id}`); setAttackState("idle"); }
    clearStage();
    setSimState("stopped");
    logln("[ui] simulation stopped");
    busy = false;
  }
  if (btnStart) btnStart.addEventListener("click", () => { simState === "running" ? endSim() : startSim(); });
  if (btnReset) btnReset.addEventListener("click", async () => {
    if (busy) return; busy = true;
    suppressDone = true;
    logln("[ui] resetting target to a clean baseline (stopping everything)...");
    if (attackState !== "idle") await post(`/stop/${id}`);
    await post(`/reset/${id}`);
    clearStage();
    setSimState("stopped"); setAttackState("idle");
    logln("[ui] target reset - idle, nothing running");
    busy = false;
  });

  // ---- ATTACK lifecycle ----
  async function launch(resume) {
    if (busy) return; busy = true;
    if (simState !== "running") { logln("[ui] start the simulation first"); busy = false; return; }
    setAttackState("running");
    const capture = !!(capCb && capCb.checked);
    logln((resume ? "[ui] resuming attack" : "[ui] launching attack") + (capture ? " (capturing traffic)" : "") + "...");
    const j = await post(`/launch/${id}`, { capture });
    if (j.status === "error") { logln("[ui] error: " + (j.msg || "")); setAttackState("idle"); busy = false; return; }
    openLog();
    busy = false;
  }
  if (btnLaunch) btnLaunch.addEventListener("click", () => launch(false));
  if (btnResume) btnResume.addEventListener("click", () => launch(true));
  if (btnPause) btnPause.addEventListener("click", async () => {
    if (busy) return; busy = true;
    suppressDone = true;
    logln("[ui] PAUSE - attacker stopped; restoring normal control...");
    await post(`/stop/${id}`);
    const r = await post(`/restore/${id}`);
    logln(r.status === "restored" ? "[ui] restore sent - plant recovering" : "[ui] no restore wired for this process yet");
    openProcessStream(); setAttackState("paused");
    busy = false;
  });
  if (btnStop) btnStop.addEventListener("click", async () => {
    if (busy) return; busy = true;
    suppressDone = true;
    logln("[ui] stopping attack...");
    await post(`/stop/${id}`); setAttackState("idle");
    busy = false;
  });

  // ---- expandable Activity pane ---- (glyphs as entities: expand U+2922, close U+2715)
  const EXP = "&#10530;", CLOSE = "&#10005;";
  function collapseLog() { if (logGroup) logGroup.classList.remove("expanded"); if (btnExpand) btnExpand.innerHTML = EXP; }
  if (btnExpand) btnExpand.addEventListener("click", () => {
    const on = logGroup.classList.toggle("expanded");
    btnExpand.innerHTML = on ? CLOSE : EXP;
    btnExpand.title = on ? "Collapse" : "Expand";
    logEl.scrollTop = logEl.scrollHeight;
  });
  document.addEventListener("keydown", e => { if (e.key === "Escape") collapseLog(); });

  // ---- load: idle unless an attack is already running elsewhere ----
  buildIoMap(cfg.io);            // show the address map immediately (values fill in when streaming)
  clearStage();
  setSimState("stopped"); setAttackState("idle");
  (async () => {
    let st = { lines: [], running: false };
    try { st = await (await fetch(`/logs/${id}`)).json(); } catch (e) { /* */ }
    if (st.running) {                       // state-sync: reflect an in-flight attack
      openProcessStream(); setSimState("running"); setAttackState("running"); openLog();
    } else if (st.lines && st.lines.length) {
      st.lines.forEach(logln); logLamp.className = "lamp done"; logHint.textContent = "last run";
    }
  })();
})();
