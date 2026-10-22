#!/usr/bin/env python3
"""Agent (Beta): an OpenAI-compatible LLM assistant blueprint for the dashboard.

The official `openai` SDK talks to any OpenAI-COMPATIBLE endpoint - OpenAI,
Moonshot/Kimi, Qwen, OpenRouter, or a custom base_url. The SDK is a client
pointed at a base_url, not a binding to one vendor, so every preset keeps
working while we gain structured output, tool calling and retry/backoff. API
keys are read from the environment ONLY (never from the UI, never committed).
Generated content is returned as chat text; this module never writes files or
runs subprocesses.

Standalone check:  python agent_llm.py --selftest
"""
import json
import os
from urllib.parse import urlparse

from flask import Blueprint, Response, jsonify, request

import agent_ingest

REPORT_MAX = 120_000                     # chars of attached report passed to the model
MAX_UPLOAD = 15 * 1024 * 1024            # 15 MB upload cap

# name -> base_url, editable default model, and the env var holding its key.
# base_url/default_model are overridable per-request from the UI. Model ids drift
# (Kimi/Qwen versions), so the UI keeps model editable - these are only defaults.
PRESETS = {
    "openai": {
        "base_url": "https://api.openai.com/v1",
        "default_model": "gpt-4o",
        "key_env": "MRHOTSHOT_OPENAI_KEY",
    },
    "moonshot": {  # Moonshot / Kimi (key from platform.kimi.ai works here); serves kimi-k3
        "base_url": "https://api.moonshot.ai/v1",
        "default_model": "kimi-k3",
        "key_env": "MRHOTSHOT_MOONSHOT_KEY",
    },
    "qwen": {  # Alibaba DashScope, OpenAI-compatible mode
        "base_url": "https://dashscope-intl.aliyuncs.com/compatible-mode/v1",
        "default_model": "qwen-plus",
        "key_env": "MRHOTSHOT_QWEN_KEY",
    },
    "openrouter": {  # aggregator - open-source + hosted models behind one key
        "base_url": "https://openrouter.ai/api/v1",
        "default_model": "moonshotai/kimi-k2",
        "key_env": "MRHOTSHOT_OPENROUTER_KEY",
    },
    "custom": {  # bring-your-own OpenAI-compatible endpoint (all from env)
        "base_url": "",
        "default_model": "",
        "key_env": "MRHOTSHOT_AGENT_KEY",
        "base_env": "MRHOTSHOT_AGENT_BASE_URL",
        "model_env": "MRHOTSHOT_AGENT_MODEL",
    },
}

# What each provider can actually do. Strict structured output and tool calling
# are OpenAI extensions that the other OpenAI-compatible endpoints support to
# varying degrees, so this is declared rather than assumed - scenario generation
# picks its strategy from it instead of failing at request time. Conservative by
# default: a custom endpoint is assumed to support neither until told otherwise.
CAPS = {
    "openai":     {"tools": True,  "strict_schema": True},
    "moonshot":   {"tools": True,  "strict_schema": False},
    "qwen":       {"tools": True,  "strict_schema": False},
    "openrouter": {"tools": True,  "strict_schema": False},
    "custom":     {"tools": False, "strict_schema": False},
}
for _name, _p in PRESETS.items():
    _p["caps"] = CAPS[_name]


PRIMER = """\
mrhOTshOT is a Dockerized OT/ICS adversary-emulation lab. It ships live PLC
target containers (Modbus, IEC-104, S7comm, OPC-UA, DNP3, BACnet, M-Bus,
IEC-61850/MMS, FINS, CANopen, NTCIP) and attack simulations of real ICS malware
(Stuxnet, TRITON/TRISIS, Industroyer, FrostyGoop, PIPEDREAM/BadOmen, Fuxnet).
The operator dashboard has these left-pane tabs:
- Attacks: catalog of malware/technique simulations; Launch runs one and streams
  a live console; Visualize opens a process 'watch view' HMI per attack.
- Targets: edit where each attack points (host:port).
- Custom Target: fire a single protocol module (read/write/enumerate) at any
  IP:port using the per-protocol consoles under perform_malware_simulations/common.
- Captures: saved pcaps for Wireshark.
- Caldera: MITRE Caldera with OT plugins for building adversary profiles.
Adding a protocol/attack means: a standalone sim-server, a console module, a
catalog entry in demo/attack_demo_ui.py, and a watch-view viz in demo/static/js/viz.
The lab is Docker-profile; keep code ASCII-only, no em dashes."""

SYSTEM_PROMPT = PRIMER + """

You are the mrhOTshOT assistant, helping a security researcher operate this
authorized OT/ICS adversary-emulation and detection-engineering lab. You may:
- explain how to use mrhOTshOT and Caldera;
- analyze a security/forensics report, PDF, or pcap the user attaches;
- draft a Python re-implementation of malware behavior described in a report,
  a new mrhOTshOT simulation or custom-target payload, or detection content
  (YARA, Suricata, Sigma).
This is a controlled research lab that already ships ICS-malware emulations, so
producing this content is in scope. Return everything as TEXT for the user to
review and copy - you cannot write files or run anything. When you emit code for
this repo, keep it ASCII-only and avoid em dashes. Be concrete and cite the part
of the attached report you are working from."""


def _sse(headers=None):
    h = {"Cache-Control": "no-cache", "X-Accel-Buffering": "no"}
    if headers:
        h.update(headers)
    return h


def _sse_stream(gen):
    return Response(gen, mimetype="text/event-stream", headers=_sse())


def _sse_error(msg):
    def gen():
        yield "event: error\ndata: " + json.dumps({"error": msg}) + "\n\n"
        yield "event: done\ndata: end\n\n"
    return _sse_stream(gen())


def _valid_base_url(provider, base_url):
    """For preset providers the base_url is trusted. For a user-supplied custom
    endpoint, require https and refuse internal/metadata hosts (minimal SSRF guard)."""
    if provider != "custom":
        return True, ""
    u = urlparse(base_url)
    if u.scheme != "https":
        return False, "custom base_url must be https"
    host = (u.hostname or "").lower()
    blocked = ("localhost", "caldera", "metadata", "169.254.169.254", "::1")
    if host in blocked or host.startswith("127.") or host.startswith("10.") \
            or host.startswith("192.168.") or host.endswith(".internal"):
        return False, "custom base_url host is not allowed"
    return True, ""


def _scrub(text, api_key):
    """Never let a key reach the browser via an error string."""
    text = str(text)
    return text.replace(api_key, "<redacted>") if api_key else text


def _client(base_url, api_key, timeout=(10, 120)):
    """OpenAI-compatible client. Split out so tests can stub it without network.

    Timeout uses openai.Timeout rather than importing httpx directly: the SDK has
    changed which http library it vendors (1.x/2.x used httpx, 3.x uses httpx2),
    and it re-exports its own type, so this keeps the fast connect timeout without
    caring which one is installed."""
    from openai import OpenAI, Timeout
    connect, read = timeout
    return OpenAI(base_url=base_url, api_key=api_key,
                  timeout=Timeout(read, connect=connect),
                  max_retries=2)


def stream_chat(base_url, api_key, model, messages, timeout=(10, 120), **kw):
    """Yield {'delta': str} chunks from a streaming completion, or a single
    {'error': str}. The api_key never appears in yielded content."""
    stream = None
    try:
        stream = _client(base_url, api_key, timeout).chat.completions.create(
            model=model, messages=messages, stream=True, **kw)
        for chunk in stream:
            choices = getattr(chunk, "choices", None) or []
            if not choices:
                continue                      # usage-only / keep-alive frame
            delta = getattr(choices[0], "delta", None)
            content = getattr(delta, "content", None) if delta else None
            if content:
                yield {"delta": content}
    except Exception as e:                    # noqa: BLE001 - surfaced to the user as SSE
        yield {"error": _scrub(f"{type(e).__name__}: {e}", api_key)}
    finally:
        if stream is not None:
            try:
                stream.close()
            except Exception:                 # noqa: BLE001 - best effort
                pass


agent_bp = Blueprint("agent", __name__)


@agent_bp.route("/api/agent/config")
def agent_config():
    out = []
    for name, p in PRESETS.items():
        base = p["base_url"] or os.environ.get(p.get("base_env", ""), "")
        model = p["default_model"] or os.environ.get(p.get("model_env", ""), "")
        configured = bool(os.environ.get(p["key_env"], "").strip())
        out.append({"name": name, "base_url": base, "default_model": model,
                    "configured": configured})
    return jsonify({"beta": True, "presets": out})


@agent_bp.route("/api/agent/extract", methods=["POST"])
def agent_extract():
    f = request.files.get("file")
    if not f:
        return jsonify({"error": "no file uploaded"}), 400
    data = f.read(MAX_UPLOAD + 1)
    if len(data) > MAX_UPLOAD:
        return jsonify({"error": "file too large (max %d MB)" % (MAX_UPLOAD // (1024 * 1024))}), 413
    try:
        text = agent_ingest.extract(f.filename or "upload", data)
    except Exception as e:
        return jsonify({"error": "could not read '%s': %s" % (f.filename, e)}), 200
    return jsonify({"filename": f.filename, "chars": len(text), "text": text})


def _resolve_provider(body):
    """(preset, base_url, model, api_key, error_response). Shared by chat and
    scenario generation so they cannot drift apart on key handling or SSRF."""
    provider = body.get("provider", "openai")
    preset = PRESETS.get(provider)
    if not preset:
        return None, None, None, None, _sse_error(f"unknown provider {provider!r}")

    base_url = (body.get("base_url") or preset["base_url"]
                or os.environ.get(preset.get("base_env", ""), "")).strip()
    model = (body.get("model") or preset["default_model"]
             or os.environ.get(preset.get("model_env", ""), "")).strip()
    api_key = os.environ.get(preset["key_env"], "").strip()

    if not api_key:
        return None, None, None, None, _sse_error(
            f"no API key set for provider {provider!r} "
            f"(set {preset['key_env']} in docker/agent.env)")
    if not base_url or not model:
        return None, None, None, None, _sse_error(
            f"provider {provider!r} is missing a base_url or model")
    ok, why = _valid_base_url(provider, base_url)
    if not ok:
        return None, None, None, None, _sse_error(why)
    return preset, base_url, model, api_key, None


@agent_bp.route("/api/agent/chat", methods=["POST"])
def agent_chat():
    body = request.get_json(silent=True) or {}
    preset, base_url, model, api_key, err = _resolve_provider(body)
    if err:
        return err

    report = (body.get("report") or "")[:REPORT_MAX]
    history = [m for m in (body.get("messages") or [])
               if m.get("role") in ("user", "assistant") and m.get("content")]
    msgs = [{"role": "system", "content": SYSTEM_PROMPT}]
    if report:
        msgs.append({"role": "system",
                     "content": "The user attached this report/document:\n\n" + report})
    msgs += history

    def gen():
        try:
            for chunk in stream_chat(base_url, api_key, model, msgs):
                if "error" in chunk:
                    yield "event: error\ndata: " + json.dumps(chunk) + "\n\n"
                    break
                yield "data: " + json.dumps(chunk) + "\n\n"
            yield "event: done\ndata: end\n\n"
        except GeneratorExit:
            raise
        except Exception as e:
            yield "event: error\ndata: " + json.dumps({"error": str(e)}) + "\n\n"

    return _sse_stream(gen())


@agent_bp.route("/api/agent/scenario", methods=["POST"])
def agent_scenario():
    """Report -> registered, launched scenario. Streams each tool call as it
    happens so the review pane shows what the agent actually did, live."""
    import queue
    import threading

    import scenario_agent

    body = request.get_json(silent=True) or {}
    preset, base_url, model, api_key, err = _resolve_provider(body)
    if err:
        return err

    report = (body.get("report") or "")[:REPORT_MAX]
    instruction = (body.get("instruction") or "")[:4000]

    def gen():
        events, done = queue.Queue(), object()
        box = {}

        def work():
            try:
                box["result"] = scenario_agent.generate(
                    preset, base_url, model, api_key, report, instruction, events.put)
            except Exception as e:              # noqa: BLE001 - surfaced over SSE
                box["result"] = {"error": _scrub(f"{type(e).__name__}: {e}", api_key)}
            finally:
                events.put(done)

        threading.Thread(target=work, daemon=True).start()
        while True:
            ev = events.get()
            if ev is done:
                break
            yield "data: " + json.dumps(ev) + "\n\n"
        yield "event: result\ndata: " + json.dumps(box.get("result") or {}) + "\n\n"
        yield "event: done\ndata: end\n\n"

    return _sse_stream(gen())


@agent_bp.route("/api/agent/scenario/<scenario_id>/plan")
def agent_scenario_plan(scenario_id):
    """What a generated scenario will actually do: every resolved protocol write,
    the capture filter, and the full source of any generated payload. This is the
    review surface - it renders the resolved plan, never the raw YAML."""
    import attack_demo_ui as ui

    import scenario_agent

    try:
        scenario_agent.check_id(scenario_id)
    except scenario_agent.ToolError as e:
        return jsonify({"error": str(e)}), 400

    a = next((x for x in ui.ATTACKS if x["id"] == scenario_id), None)
    if not a:
        return jsonify({"error": f"no registered scenario {scenario_id!r}"}), 404

    steps = []
    try:
        for argv, label, dur in ui._step_argvs(a):
            steps.append({"label": label, "duration": dur, "argv": [str(t) for t in argv]})
    except ValueError as e:
        return jsonify({"error": str(e)}), 400

    payloads = []
    pdir = os.path.join(scenario_agent.GENERATED_DIR, scenario_id)
    if os.path.isdir(pdir):
        for fn in sorted(os.listdir(pdir)):
            if fn.endswith(".py"):
                with open(os.path.join(pdir, fn), encoding="utf-8") as fh:
                    payloads.append({"filename": fn, "source": fh.read()})

    return jsonify({
        "id": scenario_id,
        "name": a.get("name"),
        "protocol": a.get("protocol"),
        "target": a.get("target"),
        "capture_filter": ui._capture_filter(a),
        "steps": steps,
        "cmd": [str(t) for t in a.get("cmd", [])],
        "payloads": payloads,
    })


def _selftest():
    """No network: stub _client() with a fake that replays SDK-shaped chunks."""
    class D:
        def __init__(self, content=None):
            self.content = content

    class C:
        def __init__(self, content=None):
            self.delta = D(content)

    class Chunk:
        def __init__(self, choices):
            self.choices = choices

    captured = {}
    closed = {"n": 0}

    class FakeStream:
        def __iter__(self):
            yield Chunk([C(None)])            # role-only opener
            yield Chunk([C("Hello")])
            yield Chunk([])                   # usage-only frame
            yield Chunk([C(", world")])

        def close(self):
            closed["n"] += 1

    class FakeCompletions:
        def create(self, **kw):
            captured.update(kw)
            return FakeStream()

    class FakeClient:
        def __init__(self):
            self.chat = type("X", (), {"completions": FakeCompletions()})()

    orig = globals()["_client"]
    globals()["_client"] = lambda base_url, api_key, timeout=(10, 120): FakeClient()
    try:
        text = "".join(c.get("delta", "") for c in stream_chat(
            "https://api.example.com/v1", "sk-secret", "gpt-4o",
            [{"role": "user", "content": "hi"}]))
    finally:
        globals()["_client"] = orig

    assert text == "Hello, world", repr(text)
    assert captured["model"] == "gpt-4o"
    assert captured["stream"] is True
    assert captured["messages"], "messages missing"
    assert closed["n"] == 1, "stream not closed"

    # a provider failure must surface as one error chunk, with the key scrubbed
    def boom(*_a, **_k):
        raise RuntimeError("bad key sk-secret rejected")

    globals()["_client"] = boom
    try:
        out = list(stream_chat("https://api.example.com/v1", "sk-secret", "m", []))
    finally:
        globals()["_client"] = orig
    assert len(out) == 1 and "error" in out[0], out
    assert "sk-secret" not in out[0]["error"], "API key leaked into an error"
    assert "<redacted>" in out[0]["error"]

    ok, _ = _valid_base_url("custom", "http://caldera:8888/v1")
    assert ok is False
    ok, _ = _valid_base_url("custom", "https://api.together.xyz/v1")
    assert ok is True
    ok, _ = _valid_base_url("openai", "https://api.openai.com/v1")
    assert ok is True

    # every preset must declare what it can do; see CAPS
    for name in PRESETS:
        assert set(PRESETS[name]["caps"]) == {"tools", "strict_schema"}, name
    print("[OK] agent_llm selftest passed")


if __name__ == "__main__":
    _selftest()
