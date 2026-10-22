// Agent (Beta) - LLM assistant tab. Loads provider presets from the server,
// attaches a report/PDF/pcap, and streams chat responses over SSE. Model output
// is HTML-escaped before render (never innerHTML on raw text); only fenced code
// blocks get special formatting. Keys live server-side only.
"use strict";

(function () {
  let wired = false;
  let presets = [];
  const history = [];   // {role, content} conversation for the model

  const q = (s) => document.querySelector(s);

  function esc(s) {
    return s.replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;");
  }

  // Inline markdown on ALREADY-ESCAPED text. Only wraps fixed tags around escaped
  // content, so raw model text can never inject markup.
  function mdInline(s) {
    s = s.replace(/`([^`]+)`/g, "<code>$1</code>");
    s = s.replace(/\*\*([^*]+)\*\*/g, "<strong>$1</strong>");
    s = s.replace(/(^|[^*])\*([^*\n]+)\*(?!\*)/g, "$1<em>$2</em>");
    return s;
  }

  // Block markdown (headings, lists, paragraphs) on already-escaped text.
  function mdBlocks(escaped) {
    const lines = escaped.split("\n");
    let html = "", listType = "";
    const closeList = () => { if (listType) { html += "</" + listType + ">"; listType = ""; } };
    for (const line of lines) {
      let m;
      if ((m = line.match(/^(#{1,6})\s+(.*)$/))) {
        closeList();
        const lvl = m[1].length;
        html += "<h" + lvl + ">" + mdInline(m[2]) + "</h" + lvl + ">";
      } else if ((m = line.match(/^\s*[-*+]\s+(.*)$/))) {
        if (listType !== "ul") { closeList(); html += "<ul>"; listType = "ul"; }
        html += "<li>" + mdInline(m[1]) + "</li>";
      } else if ((m = line.match(/^\s*\d+\.\s+(.*)$/))) {
        if (listType !== "ol") { closeList(); html += "<ol>"; listType = "ol"; }
        html += "<li>" + mdInline(m[1]) + "</li>";
      } else if (line.trim() === "") {
        closeList();
      } else {
        closeList();
        html += "<p>" + mdInline(line) + "</p>";
      }
    }
    closeList();
    return html;
  }

  // Full message render: split ```fenced``` code (kept literal) first, escape every
  // segment, markdown-render the prose. No raw model text reaches innerHTML unescaped.
  function renderContent(text) {
    const parts = text.split("```");
    let html = "";
    parts.forEach((part, i) => {
      if (i % 2 === 1) {
        const nl = part.indexOf("\n");
        const code = nl >= 0 ? part.slice(nl + 1) : part;
        html += '<pre class="agent-code"><code>' + esc(code) + "</code></pre>";
      } else if (part) {
        html += mdBlocks(esc(part));
      }
    });
    return html;
  }

  function addBubble(role, text) {
    const log = q("#agent-log");
    const el = document.createElement("div");
    el.className = "agent-msg agent-" + role;
    el.innerHTML = renderContent(text || "");
    log.appendChild(el);
    log.scrollTop = log.scrollHeight;
    return el;
  }

  // ── Persistence: one conversation kept in the browser until cleared ──────────
  const STORE_KEY = "mrhotshot.agent.v1";

  function save() {
    const data = {
      messages: history,
      report: q("#agent-report").value,
      provider: q("#agent-provider").value,
      model: q("#agent-model").value,
    };
    try {
      localStorage.setItem(STORE_KEY, JSON.stringify(data));
    } catch (e) {
      // storage full: drop the oldest half of the conversation and retry once
      history.splice(0, Math.ceil(history.length / 2));
      data.messages = history;
      try { localStorage.setItem(STORE_KEY, JSON.stringify(data)); } catch (e2) { /* give up */ }
    }
  }

  function restore() {
    let data;
    try { data = JSON.parse(localStorage.getItem(STORE_KEY) || "null"); } catch (e) { data = null; }
    if (!data) return;
    if (data.report) q("#agent-report").value = data.report;
    if (data.provider) { q("#agent-provider").value = data.provider; syncModel(); }
    if (data.model) q("#agent-model").value = data.model;
    if (Array.isArray(data.messages)) {
      data.messages.forEach((m) => addBubble(m.role, m.content));
      history.length = 0;
      history.push(...data.messages);
    }
  }

  function clearChat() {
    history.length = 0;
    q("#agent-log").innerHTML = "";
    q("#agent-report").value = "";
    q("#agent-file-meta").textContent = "";
    try { localStorage.removeItem(STORE_KEY); } catch (e) { /* ignore */ }
  }

  function currentPreset() {
    return presets.find((p) => p.name === q("#agent-provider").value);
  }

  function syncModel() {
    const p = currentPreset();
    if (p) q("#agent-model").value = p.default_model || "";
  }

  async function loadConfig() {
    try {
      const r = await fetch("/api/agent/config");
      const cfg = await r.json();
      presets = cfg.presets || [];
    } catch (e) {
      presets = [];
    }
    const sel = q("#agent-provider");
    sel.innerHTML = "";
    if (!presets.length) {
      addBubble("system", "Chatbot backend unavailable. Set a provider key in docker/agent.env and restart the console.");
      return;
    }
    presets.forEach((p) => {
      const o = document.createElement("option");
      o.value = p.name;
      o.textContent = p.name + (p.configured ? "" : "  (no key)");
      sel.appendChild(o);
    });
    const ready = presets.find((p) => p.configured);
    sel.value = (ready || presets[0]).name;
    syncModel();
  }

  async function uploadFile(file) {
    const meta = q("#agent-file-meta");
    meta.textContent = "reading " + file.name + " ...";
    const fd = new FormData();
    fd.append("file", file);
    try {
      const r = await fetch("/api/agent/extract", { method: "POST", body: fd });
      const j = await r.json();
      if (j.error) { meta.textContent = "error: " + j.error; return; }
      q("#agent-report").value = j.text;
      meta.textContent = j.filename + " -> " + j.chars + " chars extracted";
    } catch (e) {
      meta.textContent = "upload failed: " + e;
    }
  }

  async function sendChat() {
    const promptEl = q("#agent-prompt");
    const text = promptEl.value.trim();
    if (!text) return;
    const sendBtn = q("#agent-send");
    sendBtn.disabled = true;

    addBubble("user", text);
    history.push({ role: "user", content: text });
    promptEl.value = "";
    save();

    const bubble = addBubble("assistant", "");
    bubble.innerHTML = '<span class="agent-spinner" aria-label="loading"></span>';
    let acc = "";
    const setBubble = () => {
      bubble.innerHTML = renderContent(acc);
      q("#agent-log").scrollTop = q("#agent-log").scrollHeight;
    };

    const payload = {
      provider: q("#agent-provider").value,
      model: q("#agent-model").value.trim(),
      report: q("#agent-report").value,
      messages: history,
    };

    try {
      const res = await fetch("/api/agent/chat", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(payload),
      });
      const reader = res.body.getReader();
      const dec = new TextDecoder();
      let buf = "";
      let stop = false;
      while (!stop) {
        const { done, value } = await reader.read();
        if (done) break;
        buf += dec.decode(value, { stream: true });
        let idx;
        while ((idx = buf.indexOf("\n\n")) >= 0) {
          const frame = buf.slice(0, idx);
          buf = buf.slice(idx + 2);
          let event = "message", data = "";
          frame.split("\n").forEach((ln) => {
            if (ln.startsWith("event:")) event = ln.slice(6).trim();
            else if (ln.startsWith("data:")) data += ln.slice(5).trim();
          });
          if (event === "done") { stop = true; break; }
          if (event === "error") {
            try { acc += "\n\n[error] " + JSON.parse(data).error; } catch (e) { acc += "\n\n[error]"; }
            setBubble();
            stop = true;
            break;
          }
          try {
            const o = JSON.parse(data);
            if (o.delta) { acc += o.delta; setBubble(); }
          } catch (e) { /* ignore partial */ }
        }
      }
    } catch (e) {
      acc += "\n\n[error] " + e;
      setBubble();
    }

    if (acc.trim()) history.push({ role: "assistant", content: acc });
    else bubble.remove();
    save();
    sendBtn.disabled = false;
  }

  const QUICK = {
    explain: "Explain this report: what is the malware, its ICS targets, protocols abused, and the attack stages.",
    python: "Draft a Python re-implementation of the core malicious behavior described in the attached report, for use in this lab. Keep it ASCII-only.",
    detect: "Write high-quality YARA rules and Suricata rules to detect the malware/behavior in this report. Explain what each rule keys on.",
  };

  // ── Scenario build: report -> registered, launched scenario ──────────────
  // Streams each tool call as it happens, then renders the RESOLVED plan (the
  // actual protocol writes and any generated payload source), not the raw YAML.

  function reviewOpen(on) {
    q("#agent-review").classList.toggle("hidden", !on);
  }

  function stepRow(ev) {
    const bad = ev.result && ev.result.error;
    const d = document.createElement("div");
    d.className = "agent-step " + (bad ? "bad" : "good");
    const detail = bad ? ev.result.error
                       : (ev.args && (ev.args.id || ev.args.module || "")) || "ok";
    d.innerHTML = `<span class="agent-step-name">${esc(ev.tool)}</span>` +
                  `<span class="agent-step-detail">${esc(String(detail))}</span>`;
    return d;
  }

  function renderPlan(plan) {
    const el = q("#agent-plan");
    if (plan.error) { el.innerHTML = `<p class="agent-plan-err">${esc(plan.error)}</p>`; return; }
    const rows = (plan.steps || []).map((s, i) => `
      <tr><td>${i + 1}</td><td>${esc(s.label)}</td><td>${s.duration}s</td></tr>
      <tr class="agent-argv"><td></td><td colspan="2"><code>${esc(s.argv.slice(1).join(" "))}</code></td></tr>
    `).join("");
    const payloads = (plan.payloads || []).map(p => `
      <details class="agent-payload" open>
        <summary>generated payload: ${esc(p.filename)} (${p.source.length} bytes) - read this before it runs</summary>
        <pre><code>${esc(p.source)}</code></pre>
      </details>`).join("");
    el.innerHTML = `
      <div class="agent-plan-head">
        <strong>${esc(plan.name || plan.id)}</strong>
        <span class="muted">${esc(plan.protocol || "")} &middot; ${esc(plan.target || "")}</span>
      </div>
      <div class="agent-plan-cap muted">pcap filter: <code>${esc(plan.capture_filter || "(none)")}</code></div>
      ${rows ? `<table class="agent-plan-tbl"><thead><tr><th>#</th><th>operation</th><th>for</th></tr></thead><tbody>${rows}</tbody></table>` : ""}
      ${payloads}
      <div class="agent-plan-actions">
        <a class="btn btn-viz" href="/watch/${encodeURIComponent(plan.id)}" target="_blank" rel="noopener">Visualize &#8599;</a>
        <button class="btn btn-sm" id="agent-goto-attacks">Show in Attacks</button>
      </div>`;
    const go = q("#agent-goto-attacks");
    if (go) go.addEventListener("click", () => switchView("attacks"));
  }

  async function buildScenario() {
    const btn = q("#agent-build");
    const steps = q("#agent-steps");
    btn.disabled = true;
    reviewOpen(true);
    steps.innerHTML = "";
    q("#agent-plan").innerHTML = "";
    q("#agent-rung").textContent = "";

    const body = {
      provider: q("#agent-provider").value,
      model: q("#agent-model").value.trim(),
      report: q("#agent-report").value,
      instruction: q("#agent-prompt").value.trim(),
    };
    try {
      const r = await fetch("/api/agent/scenario", {
        method: "POST", headers: { "Content-Type": "application/json" },
        body: JSON.stringify(body),
      });
      const reader = r.body.getReader();
      const dec = new TextDecoder();
      let buf = "";
      for (;;) {
        const { value, done } = await reader.read();
        if (done) break;
        buf += dec.decode(value, { stream: true });
        const frames = buf.split("\n\n");
        buf = frames.pop();
        for (const f of frames) {
          const isResult = f.startsWith("event: result");
          const line = f.split("\n").find(l => l.startsWith("data: "));
          if (!line) continue;
          let ev;
          try { ev = JSON.parse(line.slice(6)); } catch { continue; }
          if (isResult) {
            if (ev.error) {
              steps.appendChild(stepRow({ tool: "error", result: { error: ev.error } }));
            }
            if (ev.id) {
              const p = await fetch(`/api/agent/scenario/${encodeURIComponent(ev.id)}/plan`);
              renderPlan(await p.json());
            } else if (ev.text) {
              q("#agent-plan").innerHTML = `<p class="muted">${esc(ev.text)}</p>`;
            }
          } else if (ev.rung) {
            q("#agent-rung").textContent = "\u00b7 " + ev.rung;
          } else if (ev.tool) {
            steps.appendChild(stepRow(ev));
            steps.scrollTop = steps.scrollHeight;
            if (ev.tool === "register_scenario" && ev.result && ev.result.ok) {
              const p = await fetch(`/api/agent/scenario/${encodeURIComponent(ev.args.id)}/plan`);
              renderPlan(await p.json());
            }
          }
        }
      }
    } catch (e) {
      steps.appendChild(stepRow({ tool: "error", result: { error: String(e) } }));
    } finally {
      btn.disabled = false;
    }
  }

  function wire() {
    if (wired) return;
    wired = true;
    q("#agent-provider").addEventListener("change", syncModel);
    q("#agent-file").addEventListener("change", (e) => {
      if (e.target.files[0]) uploadFile(e.target.files[0]);
    });
    q("#agent-send").addEventListener("click", sendChat);
    q("#agent-build").addEventListener("click", buildScenario);
    q("#agent-review-close").addEventListener("click", () => reviewOpen(false));
    q("#agent-clear").addEventListener("click", clearChat);
    q("#agent-prompt").addEventListener("keydown", (e) => {
      if (e.key === "Enter" && (e.ctrlKey || e.metaKey)) { e.preventDefault(); sendChat(); }
    });
    document.querySelectorAll("#view-agent .agent-quick button").forEach((b) => {
      b.addEventListener("click", () => {
        q("#agent-prompt").value = QUICK[b.dataset.q] || "";
        q("#agent-prompt").focus();
      });
    });
  }

  // Called by app.js when the Agent tab is opened.
  if (typeof window !== "undefined") {
    window.initAgent = async function () {
      const firstRun = !wired;
      wire();
      if (!presets.length) await loadConfig();
      if (firstRun) restore();   // restore once per page load, after the dropdown is populated
    };
  }
  // Exposed for a headless render/XSS test (no-op in the browser).
  if (typeof module !== "undefined" && module.exports) {
    module.exports = { renderContent, esc };
  }
})();
