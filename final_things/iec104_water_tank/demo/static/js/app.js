// mrhOTshOT dashboard - view switching, launch + SSE live logs, target editor.
"use strict";

const $  = (s, r = document) => r.querySelector(s);
const $$ = (s, r = document) => [...r.querySelectorAll(s)];
const byId = id => window.ATTACKS.find(a => a.id === id);
const esc = s => String(s == null ? "" : s).replace(/[&<>"]/g, c => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" }[c]));

// ── View switching ───────────────────────────────────────────
// One entry per nav tab: title, subtitle, and an optional loader run on open.
// `load` is a thunk so it can reference functions defined later (or in agent.js).
const VIEWS = {
  attacks:    { title: "Attack Surface", sub: `${window.ATTACKS.length} techniques · profile ${window.PROFILE}` },
  targets:    { title: "Targets", sub: "edit where each attack points", load: () => loadTargets() },
  custom:     { title: "Custom Target", sub: "fire a protocol at any IP:port", load: () => loadCustomProtocols() },
  captures:   { title: "Captures", sub: "saved pcaps - download for Wireshark", load: () => loadCaptures() },
  detections: { title: "Detections", sub: "live IDS alerts from the OT sensor (Beta)", load: () => initDetections() },
  agent:      { title: "Chatbot", sub: "LLM assistant &middot; report to simulation / detections (Beta)", load: () => initAgent() },
  caldera:    { title: "Caldera", sub: "MITRE Caldera + OT plugins", load: () => loadCaldera() },
};
function switchView(view) {
  const v = VIEWS[view] || VIEWS[(view = "attacks")];
  $$(".nav-item").forEach(b => b.classList.toggle("active", b.dataset.view === view));
  $$(".view").forEach(s => s.classList.add("hidden"));
  $(`#view-${view}`).classList.remove("hidden");
  $("#view-title").textContent = v.title;
  $("#view-sub").innerHTML = v.sub;
  try { localStorage.setItem("mrhotshot.view", view); } catch (_) {}
  if (v.load) v.load();
}
$$(".nav-item").forEach(btn => btn.addEventListener("click", () => switchView(btn.dataset.view)));

// ── Console (SSE) ─────────────────────────────────────────────
const consoleEl = $("#console");
const bodyEl = $("#console-body");
let activeStream = null;

function classify(line) {
  const l = line.toLowerCase();
  if (/error|fail|\[-\]|denied|exception|traceback/.test(l)) return "bad";
  if (/warn|\[!\]|alarm|overflow|trip|killdisk|wipe/.test(l)) return "warn";
  if (/\[\+\]|success|found|connected|complete|started/.test(l)) return "ok";
  if (/phase|attack|launch|====|━━/.test(l)) return "info";
  if (/^\s*\[log\]|finished|logfile/.test(l)) return "dim";
  return "";
}
function appendLine(line) {
  const span = document.createElement("span");
  const cls = classify(line);
  if (cls) span.className = cls;
  const m = line.match(/\/download\/(\S+)/);   // linkify pcap download paths
  if (m) {
    span.append(line.slice(0, m.index));
    const link = document.createElement("a");
    link.href = m[0]; link.textContent = m[0]; link.setAttribute("download", "");
    span.append(link, line.slice(m.index + m[0].length) + "\n");
  } else {
    span.textContent = line + "\n";
  }
  bodyEl.appendChild(span);
  while (bodyEl.childElementCount > 500) bodyEl.removeChild(bodyEl.firstElementChild);  // cap DOM growth on long/repeat runs
  bodyEl.scrollTop = bodyEl.scrollHeight;
}
function openConsole(id, title) {
  $("#console-title").textContent = title;
  bodyEl.innerHTML = "";
  consoleEl.classList.remove("hidden");
  $("#console-status").className = "lamp running";
  if (activeStream) activeStream.close();
  activeStream = new EventSource(`/stream/${id}`);
  activeStream.onmessage = e => appendLine(JSON.parse(e.data));
  activeStream.addEventListener("done", () => {
    $("#console-status").className = "lamp done";
    activeStream.close(); activeStream = null;
    setStatus(id, "done");
  });
  activeStream.onerror = () => { /* keep retrying; server closes on done */ };
}
$("#console-close").addEventListener("click", () => {
  consoleEl.classList.add("hidden");
  if (activeStream) { activeStream.close(); activeStream = null; }
});
$("#console-clear").addEventListener("click", () => { bodyEl.innerHTML = ""; });
$("#console-max").addEventListener("click", () => consoleEl.classList.toggle("maximized"));

// ── Launch / Stop ─────────────────────────────────────────────
function setStatus(id, state) {
  $$(`.lamp[data-status="${id}"]`).forEach(d => d.className = "lamp " + (state || ""));
  const running = state === "running";
  const btn = $(`.btn-toggle[data-id="${id}"]`);
  if (btn) {
    btn.classList.toggle("btn-run", !running);
    btn.classList.toggle("btn-stop", running);
    btn.innerHTML = running ? "■ Stop" : "▶ Launch";
    btn.dataset.state = running ? "running" : "idle";
  }
}
async function launch(id) {
  if (!id) return;                       // ignore .btn-run elements that aren't attack cards
  const a = byId(id);
  const card = document.querySelector(`.card[data-id="${id}"]`);
  const cb = card && card.querySelector(".cap-cb");
  const capture = !!(cb && cb.checked);
  setStatus(id, "running");
  openConsole(id, a ? a.name : id);
  // dashboard Launch: start the simulation, run ~10s, then attack (warmup).
  const r = await fetch(`/launch/${id}`, {
    method: "POST", headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ capture, warmup: true }),
  });
  const j = await r.json();
  if (j.status === "already_running") appendLine("[ui] already running");
  else if (j.status === "error") { appendLine("[ui] error: " + (j.msg || "unknown")); setStatus(id, ""); }
}
async function stopAttack(id) {
  appendLine("[ui] stopping ...");
  setStatus(id, "");                      // optimistic - the status poll confirms
  await fetch(`/stop/${id}`, { method: "POST" });
}
// A single Run/Stop toggle per attack card (carries data-id). The Custom Target and
// "Open Caldera" buttons share .btn-run styling but have their own handlers.
$$(".btn-toggle[data-id]").forEach(b => b.addEventListener("click", () =>
  (b.dataset.state === "running" ? stopAttack : launch)(b.dataset.id)));

// ── Briefing modal ────────────────────────────────────────────
$$(".btn-brief").forEach(b => b.addEventListener("click", () => {
  const a = byId(b.dataset.id);
  $("#modal-title").textContent = (a ? a.name : "") + " - briefing";
  $("#modal-body").textContent = (a && a.briefing ? a.briefing : ["(no briefing)"]).join("\n");
  $("#modal").classList.remove("hidden");
}));
$("#modal-close").addEventListener("click", () => $("#modal").classList.add("hidden"));
$("#modal").addEventListener("click", e => { if (e.target.id === "modal") $("#modal").classList.add("hidden"); });

// ── Reset ─────────────────────────────────────────────────────
$("#reset-btn").addEventListener("click", async () => {
  openConsole("reset_plcs", "Reset PLCs");
  await fetch("/reset", { method: "POST" });
});

// Load / reload the operator HMI (FUXA) views on demand.
$("#hmi-seed").addEventListener("click", async e => {
  const b = e.currentTarget, orig = b.textContent;
  b.disabled = true; b.textContent = "loading views...";
  try {
    const j = await (await fetch("/api/seed-fuxa", { method: "POST" })).json();
    b.textContent = j.status === "ok" ? "views loaded [+]" : "failed: " + (j.msg || "");
  } catch (_) { b.textContent = "failed"; }
  setTimeout(() => { b.textContent = orig; b.disabled = false; }, 3500);
});

// ── Profile switch ────────────────────────────────────────────
$("#profile-select").addEventListener("change", async e => {
  const profile = e.target.value;
  const r = await fetch("/api/profile", {
    method: "POST", headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ profile }),
  });
  if (r.ok) location.reload();   // catalog targets change with the profile
});

// ── Targets editor ────────────────────────────────────────────
async function loadTargets() {
  const r = await fetch("/api/targets");
  const j = await r.json();
  const body = $("#targets-body");
  body.innerHTML = "";
  j.targets.forEach(t => {
    const protos = Object.keys(t.protocols);
    const primary = protos[0];
    const tr = document.createElement("tr");
    tr.innerHTML = `
      <td class="t-name">${t.name}</td>
      <td class="t-proto">${protos.map(p => `${p}:${t.protocols[p]}`).join("  ")}</td>
      <td><input type="text" class="t-ip" value="${t.ip}"></td>
      <td><input type="text" class="t-port-input" value="${t.protocols[primary]}"></td>
      <td><button class="btn btn-sm btn-save">Save</button><span class="saved-flash"></span></td>`;
    tr.querySelector(".btn-save").addEventListener("click", async () => {
      const ip = tr.querySelector(".t-ip").value.trim();
      const port = parseInt(tr.querySelector(".t-port-input").value, 10);
      const payload = { name: t.name, ip, protocols: {} };
      if (!Number.isNaN(port)) payload.protocols[primary] = port;
      const resp = await fetch("/api/targets", {
        method: "POST", headers: { "Content-Type": "application/json" },
        body: JSON.stringify(payload),
      });
      const flash = tr.querySelector(".saved-flash");
      flash.textContent = resp.ok ? "[+] saved" : "[-] error";
      setTimeout(() => (flash.textContent = ""), 2000);
    });
    body.appendChild(tr);
  });
}

// ── Captures (pcap) ───────────────────────────────────────────
function fmtSize(b) { return b < 1024 ? b + " B" : (b / 1024).toFixed(1) + " KB"; }
function fmtTime(s) { return new Date(s * 1000).toLocaleString(); }
async function loadCaptures() {
  const j = await (await fetch("/api/captures")).json();
  if (j.path) $("#cap-path").textContent = j.path;
  const body = $("#captures-body");
  body.innerHTML = "";
  if (!j.captures.length) {
    body.innerHTML = `<tr><td colspan="4" class="muted">No captures yet - tick “Capture traffic” when you run an attack.</td></tr>`;
    return;
  }
  j.captures.forEach(c => {
    const tr = document.createElement("tr");
    tr.innerHTML = `
      <td class="t-name">${c.attack}</td>
      <td class="t-proto">${fmtTime(c.mtime)}</td>
      <td>${fmtSize(c.size)}</td>
      <td>
        <a class="btn btn-sm" href="${c.url}" download>Download</a>
        <button class="btn btn-sm btn-ghost cap-del" data-name="${c.name}">Delete</button>
      </td>`;
    tr.querySelector(".cap-del").addEventListener("click", async () => {
      await fetch(`/api/captures/${c.name}`, { method: "DELETE" });
      loadCaptures();
    });
    body.appendChild(tr);
  });
}

// ── Detections (OT IDS sensor) ────────────────────────────────
// A single always-on EventSource (opened on page load) feeds this buffer. The table
// renders from the buffer, and a nav badge counts alerts that arrive while you are on
// another tab - so launching an attack from anywhere lights up Detections live.
const DET_LABEL = { 1: "high", 2: "medium", 3: "low" };
const detAlerts = [];          // oldest..newest, capped at 300
let detStream = null, detUnseen = 0, detSensorRunning = false;

function detActive() { const s = $("#view-detections"); return s && !s.classList.contains("hidden"); }
function rowHtml(a) {
  const sev = a.severity || 3;
  const t = a.ts ? new Date(a.ts).toLocaleTimeString() : "";
  return `
    <td class="t-proto"><a class="det-ts-link" data-ts="${esc(a.ts)}" data-sid="${esc(a.sid)}" title="Open the sensor log for this detection">${esc(t)}</a></td>
    <td><span class="det-sev s${sev}">${DET_LABEL[sev] || "low"}</span></td>
    <td class="t-name">${esc(a.msg)}</td>
    <td><a class="det-rule-link" data-sid="${esc(a.sid)}" title="View the detection rule (read-only)">${esc(a.sid)}</a></td>
    <td>${esc(a.proto)}</td>
    <td>${esc(a.src)}</td>
    <td>${esc(a.dest)}${a.dport ? ":" + esc(a.dport) : ""}</td>`;
}
function detRow(a) {            // prepend one alert to the live table (newest on top)
  const body = $("#detections-body");
  const empty = body.querySelector(".det-empty");
  if (empty) empty.remove();
  const tr = document.createElement("tr");
  tr.innerHTML = rowHtml(a);
  body.insertBefore(tr, body.firstChild);
  while (body.childElementCount > 300) body.removeChild(body.lastElementChild);
}
function detEmpty(txt) {
  $("#detections-body").innerHTML = `<tr class="det-empty"><td colspan="7" class="muted">${esc(txt)}</td></tr>`;
}
function renderDetections() {   // rebuild the whole table from the buffer
  $("#detections-body").innerHTML = "";
  detAlerts.forEach(detRow);   // oldest..newest, each prepended -> newest ends on top
  if (!detAlerts.length) detEmpty(detSensorRunning ? "Sensor online - launch an attack to see alerts." : "No alerts yet.");
}
function setDetBadge(n) {
  const el = $("#det-badge");
  if (!el) return;
  if (n > 0) { el.textContent = n > 99 ? "99+" : String(n); el.classList.remove("hidden"); }
  else el.classList.add("hidden");
}
function onDetAlert(a) {        // a live alert arrived on the global stream
  detAlerts.push(a);
  while (detAlerts.length > 300) detAlerts.shift();
  if (detActive()) detRow(a);
  else { detUnseen++; setDetBadge(detUnseen); }
}
function setDetStatus(running, evePresent) {
  detSensorRunning = !!running;
  const lamp = $("#det-lamp"), st = $("#det-status");
  if (!lamp || !st) return;
  if (running) { lamp.className = "lamp lamp-ok"; st.innerHTML = "sensor <b>online</b> - passive tap active"; }
  else if (evePresent) { lamp.className = "lamp running"; st.textContent = "sensor stopped - showing last alerts (start: make sensor-up)"; }
  else { lamp.className = "lamp"; st.textContent = "sensor offline - start it with: make sensor-up"; }
}
// Show the Suricata rule for a signature id in the shared modal (read-only <pre>).
async function showRule(sid) {
  $("#modal-title").textContent = `Detection rule ${sid} (read-only)`;
  $("#modal-body").textContent = "loading rule...";
  $("#modal").classList.remove("hidden");
  let j = {};
  try { j = await (await fetch(`/api/detections/rule/${sid}`)).json(); } catch (_) {}
  $("#modal-body").textContent = j.found
    ? (j.comment ? j.comment + "\n\n" : "") + j.rule
    : `Rule ${sid} not found in the ruleset.`;
}
// Open the shared console drawer with static content (no stream) - used for the
// per-detection sensor log below. Mirrors openConsole() minus the EventSource.
function openStaticConsole(title) {
  $("#console-title").textContent = title;
  bodyEl.innerHTML = "";
  consoleEl.classList.remove("hidden");
  $("#console-status").className = "lamp done";
  if (activeStream) { activeStream.close(); activeStream = null; }
}
// The actual Suricata log for one detection (fast.log line + full eve.json record),
// shown in the same console view as an attack's output.
async function showDetectionLog(ts, sid) {
  openStaticConsole(`Detection ${sid} - sensor log`);
  appendLine(`[sensor] Suricata OT IDS - detection ${sid}`);
  appendLine(`[query] timestamp ${ts}`);
  appendLine("");
  let j = {};
  try { j = await (await fetch(`/api/detections/log?ts=${encodeURIComponent(ts)}&sid=${encodeURIComponent(sid)}`)).json(); } catch (_) {}
  if (j.fastlog) { appendLine("[fast.log]"); appendLine(j.fastlog); appendLine(""); }
  if (j.found) { appendLine("[eve.json]"); j.eve.split("\n").forEach(appendLine); }
  else if (!j.fastlog) appendLine("[!] this detection is no longer in the sensor log (it may have rotated).");
}
$("#detections-body").addEventListener("click", e => {
  const rule = e.target.closest(".det-rule-link");
  if (rule) { showRule(rule.dataset.sid); return; }
  const tsl = e.target.closest(".det-ts-link");
  if (tsl) showDetectionLog(tsl.dataset.ts, tsl.dataset.sid);
});
$("#det-clear") && $("#det-clear").addEventListener("click", () => { detAlerts.length = 0; renderDetections(); });

// Opening the tab just renders the buffer and clears the badge - the stream is global.
function initDetections() { detUnseen = 0; setDetBadge(0); renderDetections(); }

// Opened once on page load; lives for the whole page so alerts stream in on any tab.
async function startDetections() {
  let j = {};
  try { j = await (await fetch("/api/detections")).json(); } catch (_) {}
  setDetStatus(j.running, j.eve_present);
  (j.alerts || []).forEach(a => detAlerts.push(a));   // seed history (not badged)
  if (detActive()) renderDetections();
  detStream = new EventSource("/api/detections/stream");
  detStream.addEventListener("meta", e => { try { const m = JSON.parse(e.data); setDetStatus(m.running, m.eve_present); } catch (_) {} });
  detStream.onmessage = e => { try { onDetAlert(JSON.parse(e.data)); } catch (_) {} };
  detStream.onerror = () => { /* browser auto-retries; server keep-alives hold it open */ };
}

// ── Caldera ───────────────────────────────────────────────────
async function loadCaldera() {
  const lamp = $("#caldera-lamp"), status = $("#caldera-status"), grid = $("#caldera-grid"), link = $("#caldera-link");
  status.textContent = "checking…"; grid.innerHTML = "";
  let j = {};
  try { j = await (await fetch("/api/caldera/info")).json(); } catch (_) {}
  link.href = `http://${location.hostname}:${j.ui_port || 8889}`;
  if (j.up) {
    lamp.className = "lamp lamp-ok";
    status.innerHTML = `online · Caldera <b>${j.version || ""}</b>`;
    const cells = [["Abilities", j.abilities], ["Agents", j.agents], ["Operations", j.operations]];
    grid.innerHTML = cells.map(([k, v]) => `<div class="caldera-cell"><div class="cv">${v ?? "-"}</div><div class="ck">${k}</div></div>`).join("");
  } else {
    lamp.className = "lamp lamp-bad";
    status.textContent = "offline - start the docker lab (it includes Caldera)";
  }
}

// ── Lab status lamp (sidebar) ─────────────────────────────────
async function loadLabStatus() {
  try {
    const j = await (await fetch("/api/targets")).json();
    const lamp = $("#lab-lamp"), text = $("#lab-text");
    if (!j.lab || !j.lab.available) { lamp.className = "lamp"; text.textContent = "docker n/a"; }
    else {
      const n = Object.keys(j.lab.services || {}).length;
      const up = Object.values(j.lab.services || {}).filter(Boolean).length;
      if (j.lab.up) { lamp.className = "lamp lamp-ok"; text.textContent = `lab up · ${up}/${n}`; }
      else if (up)  { lamp.className = "lamp lamp-run"; text.textContent = `lab ${up}/${n}`; }
      else          { lamp.className = "lamp"; text.textContent = "lab down"; }
    }
    // Gray out profiles whose backend isn't reachable (e.g. esxi with no VMs).
    if (j.reachable) {
      const sel = $("#profile-select");
      [...sel.options].forEach(opt => {
        const ok = j.reachable[opt.value] !== false;
        opt.disabled = !ok && opt.value !== j.profile;
        if (!ok && !opt.textContent.includes("unavailable") && opt.value !== j.profile) {
          opt.textContent = opt.textContent.replace(/ \(unavailable\)$/, "") + " (unavailable)";
        }
      });
    }
    // FUXA operator HMI link + "Load HMI views" (shown only when FUXA is up)
    const hmi = $("#hmi-link"), hmiSeed = $("#hmi-seed");
    if (j.hmi && j.hmi.up) {
      hmi.href = `http://${location.hostname}:${j.hmi.port}/home`;
      hmi.classList.remove("hidden");
      if (hmiSeed) hmiSeed.classList.remove("hidden");
    } else {
      hmi.classList.add("hidden");
      if (hmiSeed) hmiSeed.classList.add("hidden");
    }
  } catch (_) {}
}
loadLabStatus();
setInterval(loadLabStatus, 8000);

// ── Custom Target (Metasploit-style module console) ───────────
let customProtos = null;

function optField(f) {
  const help = f.help ? ` title="${f.help}"` : "";
  const show = f.showFor ? ` data-showfor="${f.showFor.join(",")}"` : "";
  const sff = f.showForField ? ` data-showforfield="${f.showForField}"` : "";
  let ctrl;
  if (f.type === "select") {
    ctrl = `<select data-opt="${f.name}">` +
      f.options.map(o => `<option${o === f.default ? " selected" : ""}>${o}</option>`).join("") +
      "</select>";
  } else {
    ctrl = `<input type="text" data-opt="${f.name}" class="t-port-input" value="${f.default ?? ""}"${help}>`;
  }
  return `<div class="field opt-field"${show}${sff}><label${help}>${f.label}</label>${ctrl}</div>`;
}
function optVal(name) {
  const el = $(`#custom-options [data-opt='${name}']`);
  return el ? el.value : null;
}
function applyActionVis() {
  const first = $("#custom-options select[data-opt]");   // default controller: first select
  $$("#custom-options .opt-field").forEach(el => {
    const sf = el.dataset.showfor;
    if (!sf) return;
    const cur = el.dataset.showforfield ? optVal(el.dataset.showforfield) : (first ? first.value : null);
    el.classList.toggle("hidden", !!(cur && !sf.split(",").includes(cur)));
  });
}
function updateTiming() {
  const repeat = $("#custom-mode").value === "repeat";
  const scenario = $("#custom-module").value === "scenario";
  $("#custom-interval-field").classList.toggle("hidden", !repeat);
  $("#custom-duration-field").classList.toggle("hidden", !(repeat || scenario));
}
function renderModule() {
  const mod = customProtos[$("#custom-proto").value].modules[$("#custom-module").value];
  $("#custom-options").innerHTML = ((mod && mod.fields) || []).map(optField).join("");
  $$("#custom-options select[data-opt]").forEach(s => s.addEventListener("change", applyActionVis));
  applyActionVis();
  updateTiming();
}
function renderModules() {
  const proto = customProtos[$("#custom-proto").value];
  $("#custom-module").innerHTML = Object.entries(proto.modules)
    .map(([k, v]) => `<option value="${k}">${v.label}</option>`).join("");
  $("#custom-port").value = proto.port;
  // suggest the lab host that serves this protocol; keep any manually-typed target
  const ipEl = $("#custom-ip");
  if (proto.host) {
    ipEl.placeholder = proto.host + " (suggested)";
    const known = new Set(Object.values(customProtos).map(p => p.host).filter(Boolean));
    if (!ipEl.value.trim() || known.has(ipEl.value.trim())) ipEl.value = proto.host;
  }
  renderModule();
}
async function loadCustomProtocols() {
  if (!customProtos) customProtos = await (await fetch("/api/custom-protocols")).json();
  const sel = $("#custom-proto");
  if (!sel.options.length) {
    Object.entries(customProtos).forEach(([k, v]) => {
      const o = document.createElement("option");
      o.value = k; o.textContent = v.label;
      sel.appendChild(o);
    });
    sel.addEventListener("change", renderModules);
    $("#custom-module").addEventListener("change", renderModule);
    $("#custom-mode").addEventListener("change", updateTiming);
    renderModules();
  }
}

let customPoll = null;
function customButtons(running) {
  $("#custom-run").classList.toggle("hidden", running);
  $("#custom-stop").classList.toggle("hidden", !running);
}
function watchCustom() {                 // revert Run/Stop when the run ends (custom isn't in /status)
  clearInterval(customPoll);
  customPoll = setInterval(async () => {
    try {
      const j = await (await fetch("/logs/custom?offset=999999")).json();
      if (!j.running) { customButtons(false); clearInterval(customPoll); }
    } catch (_) {}
  }, 1500);
}
$("#custom-run").addEventListener("click", async () => {
  const proto = $("#custom-proto").value;
  const module = $("#custom-module").value;
  const ip = $("#custom-ip").value.trim();
  const msg = $("#custom-msg");
  if (!ip) { msg.textContent = "enter a target host"; return; }
  const options = {};
  $$("#custom-options [data-opt]").forEach(el => { options[el.dataset.opt] = el.value; });
  msg.textContent = "";
  customButtons(true);
  setStatus("custom", "running");
  openConsole("custom", `Custom ${$("#custom-module").selectedOptions[0].textContent}`);
  const r = await fetch("/custom", {
    method: "POST", headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      protocol: proto, module, ip, options,
      port: $("#custom-port").value.trim(),
      mode: $("#custom-mode").value,
      interval: $("#custom-interval").value.trim(),
      duration: $("#custom-duration").value.trim(),
      capture: $("#custom-cap").checked,
    }),
  });
  const j = await r.json();
  if (j.status === "error") {
    appendLine("[ui] error: " + (j.msg || "")); msg.textContent = j.msg || "error";
    setStatus("custom", ""); customButtons(false);
  } else if (j.status === "already_running") {
    appendLine("[ui] a custom run is already active"); watchCustom();
  } else watchCustom();
});
$("#custom-stop").addEventListener("click", async () => {
  appendLine("[ui] stopping ...");
  await fetch("/custom/stop", { method: "POST" });
  customButtons(false);
});

// ── Poll status so cards reflect runs started elsewhere ───────
setInterval(async () => {
  try {
    const s = await (await fetch("/status")).json();
    Object.entries(s).forEach(([id, run]) => {
      const dot = $(`.lamp[data-status="${id}"]`);
      if (dot && !dot.classList.contains("done")) setStatus(id, run ? "running" : "");
    });
  } catch (_) {}
}, 3000);

// ── Page load: restore the last-open tab + start the always-on detections stream ──
(function init() {
  let saved = "attacks";
  try { saved = localStorage.getItem("mrhotshot.view") || "attacks"; } catch (_) {}
  switchView(saved);
  startDetections();
})();
