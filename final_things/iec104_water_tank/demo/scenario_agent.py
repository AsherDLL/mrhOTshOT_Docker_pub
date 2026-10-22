#!/usr/bin/env python3
"""Report -> runnable scenario: the tools the Chatbot uses to build one.

The operator attaches a threat report; the model extracts the OT-relevant
indicators (protocol, function codes, register/IOA/point addresses, ports, unit
ids, cadence) and turns them into a scenario manifest it can register and launch,
so the run produces a pcap to replay against a detection engine offline.

Two things keep that from being a blank cheque:

* Grounding. The capability prompt is generated from the LIVE console registry,
  so the model is choosing among protocols and modules that actually exist here
  rather than inventing one.
* Confinement. Writes are restricted to two directories, resolved with realpath
  so `..` and symlinks cannot escape, and every scenario id is charset-checked
  because it is a model-controlled path component. Every tool call is appended
  to an audit log.

A `steps:` scenario is validated by the same build_<proto>_cmd functions that
back POST /custom, so it can express nothing the Custom Target tab cannot. A
generated payload script is the exception, and is confined to GENERATED_DIR.

Standalone check:  python scenario_agent.py --selftest
"""
import json
import os
import re
import time

import scenario_loader
import yaml

DEMO_DIR = os.path.dirname(os.path.abspath(__file__))
SCENARIO_DIR = os.path.join(DEMO_DIR, "scenarios")
GENERATED_DIR = os.path.abspath(os.path.join(DEMO_DIR, "..",
                                             "perform_malware_simulations", "generated"))
VIZ_DIR = os.path.join(DEMO_DIR, "static", "js", "viz")
AUDIT_LOG = os.path.join(DEMO_DIR, "logs", "copilot_audit.log")

# A scenario id becomes a filename, a dict key and a URL path component.
ID_RE = re.compile(r"[a-z][a-z0-9_]{2,31}\Z")

MAX_YAML = 64_000
MAX_PAYLOAD = 200_000
MAX_VIZ = 100_000


class ToolError(ValueError):
    """Surfaced back to the model so it can correct itself, not a crash."""


# ── confinement ────────────────────────────────────────────────────────────

def check_id(scenario_id):
    if not isinstance(scenario_id, str) or not ID_RE.match(scenario_id):
        raise ToolError(
            f"invalid scenario id {scenario_id!r}: 3-32 chars, lowercase letters, "
            "digits and underscore, starting with a letter")
    return scenario_id


def confined(root, *parts):
    """Join under `root` and refuse anything that resolves outside it."""
    root = os.path.realpath(root)
    target = os.path.realpath(os.path.join(root, *parts))
    if target != root and not target.startswith(root + os.sep):
        raise ToolError(f"path escapes {os.path.basename(root)}/: {os.path.join(*parts)!r}")
    return target


def audit(tool, args, outcome):
    """Append-only record of what the agent did. _prune_log_dir keeps logs/ bounded."""
    try:
        os.makedirs(os.path.dirname(AUDIT_LOG), exist_ok=True)
        with open(AUDIT_LOG, "a", encoding="utf-8") as fh:
            fh.write(json.dumps({
                "ts": time.strftime("%Y-%m-%dT%H:%M:%S"),
                "tool": tool,
                "args": {k: (v[:200] + "..." if isinstance(v, str) and len(v) > 200 else v)
                         for k, v in (args or {}).items()},
                "outcome": str(outcome)[:400],
            }) + "\n")
    except OSError:
        pass          # auditing must never block the run


# ── validation ─────────────────────────────────────────────────────────────

def validate_manifest(doc, source="copilot"):
    """Semantic validation, reusing the real validators rather than restating them.

    scenario_loader.validate covers required fields; _step_argvs runs every step
    through its protocol's build_<proto>_cmd, which is what actually bounds what
    a generated scenario can do.
    """
    import attack_demo_ui as ui  # lazy: avoids an import cycle

    if not isinstance(doc, dict):
        raise ToolError("manifest must be a YAML mapping")
    check_id(doc.get("id", ""))
    scenario_loader.validate(doc, doc.get("id", "<manifest>"))

    if doc.get("steps"):
        ui._step_argvs(doc)              # raises ValueError on any bad step

    # A generated scenario may only exec its own payload, never an arbitrary path.
    if source == "copilot":
        for key in ("cmd", "cmd_lab"):
            for tok in doc.get(key) or []:
                tok = str(tok)
                if not tok.endswith(".py"):
                    continue
                resolved = scenario_loader.resolve_path(tok, ui.SCENARIO_ROOTS) \
                    if tok.startswith("$") else tok
                if not os.path.realpath(resolved).startswith(os.path.realpath(GENERATED_DIR)):
                    raise ToolError(
                        "a generated scenario may only run a payload under "
                        f"generated/, not {tok!r}")
    return doc


# ── grounding: what this lab can actually do, from the live registry ───────

def capability_prompt():
    """Protocols, modules and their option fields, straight out of CONSOLE_BUILDERS.

    Generated from the live registry so the model cannot pick a console that does
    not exist. Field names + allowed values only - the full schema is ~35 KB, this
    is a few KB.
    """
    import attack_demo_ui as ui

    lines = ["PROTOCOLS AND MODULES AVAILABLE IN THIS LAB", ""]
    for proto, (label, port, _script, _extra) in sorted(ui.CUSTOM_PROTOCOLS.items()):
        reg = ui.CONSOLE_BUILDERS.get(proto)
        lines.append(f"{proto}  ({label}, default port {port})")
        if not reg:
            lines.append("    no configurable modules; canned scenario only")
            continue
        for mod, spec in reg[0].items():
            fields = []
            for f in spec.get("fields", []):
                opts = f.get("options")
                fields.append(f"{f['name']}={'|'.join(map(str, opts))}" if opts else f["name"])
            lines.append(f"    {mod}: {', '.join(fields) or '(no options)'}")
    # Connection parameters, straight out of IO_POINTS. Without these the model
    # guesses - a real run against an OT survey PDF produced S7 steps with rack0/slot2,
    # which this emulator happens to accept but real S7-300 hardware would not, and
    # which puts a different TSAP in the pcap than every other scenario in the lab.
    lines += ["", "CONNECTION DEFAULTS FOR THIS LAB "
                  "(use these unless the report states otherwise)", ""]
    for proto, block in sorted(ui.wp.IO_POINTS.items()):
        if block.get("endpoint"):
            lines.append(f"    {proto:<10} {block['endpoint']}")

    lines += ["", "TARGET HOSTS (use as `plc:` in a step)", ""]
    lines.append("    " + ", ".join(sorted(ui.PLC)))
    lines += ["", "WATCH VIEW KINDS (use as watch.kind)", ""]
    lines.append("    " + ", ".join(ui.viz_kinds()))
    lines.append("    Prefer `generic` unless an existing kind genuinely fits the process.")
    return "\n".join(lines)



# ── tools ──────────────────────────────────────────────────────────────────

TOOLS = [
    {"type": "function", "function": {
        "name": "get_module_schema",
        "description": "Full option schema for one protocol module: every field, its "
                       "type, default, allowed values and help text. Call this before "
                       "writing steps that use the module.",
        "parameters": {"type": "object", "required": ["protocol", "module"],
                       "properties": {"protocol": {"type": "string"},
                                      "module": {"type": "string"}}}}},
    {"type": "function", "function": {
        "name": "read_scenario",
        "description": "Read an existing scenario manifest as a worked example. "
                       "frostygoop_steps is the reference for the declarative form.",
        "parameters": {"type": "object", "required": ["id"],
                       "properties": {"id": {"type": "string"}}}}},
    {"type": "function", "function": {
        "name": "write_scenario",
        "description": "Write the scenario manifest as YAML. Validated before it is "
                       "saved; on error, fix what the error says and call again.",
        "parameters": {"type": "object", "required": ["id", "manifest_yaml"],
                       "properties": {"id": {"type": "string"},
                                      "manifest_yaml": {"type": "string"}}}}},
    {"type": "function", "function": {
        "name": "write_payload",
        "description": "Write a Python payload for this scenario, ONLY when no existing "
                       "protocol module can express the behaviour. Prefer steps.",
        "parameters": {"type": "object", "required": ["id", "filename", "code"],
                       "properties": {"id": {"type": "string"},
                                      "filename": {"type": "string"},
                                      "code": {"type": "string"}}}}},
    {"type": "function", "function": {
        "name": "write_viz",
        "description": "Write a watch-view module for a process shape none of the "
                       "existing kinds fit. Optional - `generic` already renders a "
                       "usable view from the scenario's I/O points, so only do this "
                       "when a purpose-drawn picture genuinely adds something.",
        "parameters": {"type": "object", "required": ["kind", "code"],
                       "properties": {"kind": {"type": "string"},
                                      "code": {"type": "string"}}}}},
    {"type": "function", "function": {
        "name": "register_scenario",
        "description": "Make a written scenario appear in the Attacks catalog.",
        "parameters": {"type": "object", "required": ["id"],
                       "properties": {"id": {"type": "string"}}}}},
    {"type": "function", "function": {
        "name": "launch_scenario",
        "description": "Run a registered scenario. Capture is on by default so the run "
                       "produces a pcap to replay against a detection engine.",
        "parameters": {"type": "object", "required": ["id"],
                       "properties": {"id": {"type": "string"},
                                      "capture": {"type": "boolean"}}}}},
]


def t_get_module_schema(protocol, module):
    import attack_demo_ui as ui
    reg = ui.CONSOLE_BUILDERS.get(str(protocol).lower())
    if not reg or module not in reg[0]:
        raise ToolError(f"no module {module!r} for protocol {protocol!r}")
    return reg[0][module]


def t_read_scenario(id):                                       # noqa: A002
    path = confined(SCENARIO_DIR, check_id(id) + ".yaml")
    if not os.path.exists(path):
        raise ToolError(f"no scenario {id!r}")
    with open(path, encoding="utf-8") as fh:
        return fh.read()


def t_write_scenario(id, manifest_yaml):                       # noqa: A002
    check_id(id)
    if len(manifest_yaml or "") > MAX_YAML:
        raise ToolError("manifest too large")
    try:
        doc = yaml.safe_load(manifest_yaml)
    except yaml.YAMLError as e:
        raise ToolError(f"manifest is not valid YAML: {e}") from None
    if not isinstance(doc, dict):
        raise ToolError("manifest must be a YAML mapping")

    doc["id"] = id
    doc.setdefault("source", "copilot")
    doc.pop("order", None)                  # generated scenarios sort after the shipped ones
    validate_manifest(doc, source=doc.get("source"))

    # Never silently rewrite one of the shipped scenarios.
    path = confined(SCENARIO_DIR, id + ".yaml")
    if os.path.exists(path):
        with open(path, encoding="utf-8") as fh:
            existing = yaml.safe_load(fh) or {}
        if existing.get("source") != "copilot":
            raise ToolError(f"{id!r} is a shipped scenario; choose another id")

    with open(path, "w", encoding="utf-8") as fh:
        yaml.safe_dump(doc, fh, sort_keys=False, allow_unicode=True,
                       default_flow_style=False, width=100)
    scenario_loader.invalidate()
    return {"written": os.path.relpath(path, DEMO_DIR), "steps": len(doc.get("steps") or [])}


def t_write_payload(id, filename, code):                       # noqa: A002
    check_id(id)
    if not filename.endswith(".py") or "/" in filename or "\\" in filename:
        raise ToolError("filename must be a bare *.py name")
    if len(code or "") > MAX_PAYLOAD:
        raise ToolError("payload too large")
    target = confined(GENERATED_DIR, id, filename)
    os.makedirs(os.path.dirname(target), exist_ok=True)
    with open(target, "w", encoding="utf-8") as fh:
        fh.write(code)
    return {"written": os.path.relpath(target, GENERATED_DIR), "bytes": len(code),
            "run_with": f"$REPO/final_things/iec104_water_tank/perform_malware_simulations/"
                        f"generated/{id}/{filename}"}


def t_write_viz(kind, code):
    """A watch-view module, confined to static/js/viz/.

    The watch page loads registry.js, generic.js and the one module its scenario
    needs, so a broken generated module can only break its own scenario's view.
    """
    import attack_demo_ui as ui

    check_id(kind)
    if len(code or "") > MAX_VIZ:
        raise ToolError("viz module too large")
    shipped = {m[:-3] for m in os.listdir(VIZ_DIR) if m.endswith(".js")}
    if kind in shipped:
        raise ToolError(f"{kind!r} is a shipped visualization; choose another kind")
    if "registerViz" not in code or f'kind: "{kind}"' not in code:
        raise ToolError(
            f'module must call registerViz({{ kind: "{kind}", ... }}) with a matching kind')
    target = confined(VIZ_DIR, kind + ".js")
    with open(target, "w", encoding="utf-8") as fh:
        fh.write(code)
    return {"written": os.path.relpath(target, ui.DEMO_DIR), "kind": kind,
            "note": "set watch.kind to this in the manifest"}


def t_register_scenario(id):                                   # noqa: A002
    import attack_demo_ui as ui
    check_id(id)
    if not os.path.exists(confined(SCENARIO_DIR, id + ".yaml")):
        raise ToolError(f"no manifest for {id!r}; call write_scenario first")
    scenario_loader.invalidate()
    ui._rebuild_catalog()          # also seeds logs/running via _init_state
    if not any(a["id"] == id for a in ui.ATTACKS):
        raise ToolError(f"{id!r} did not appear in the catalog after rebuild")
    return {"registered": id, "catalog_size": len(ui.ATTACKS)}


def t_launch_scenario(id, capture=True):                       # noqa: A002
    import attack_demo_ui as ui
    check_id(id)
    a = next((x for x in ui.ATTACKS if x["id"] == id), None)
    if not a:
        raise ToolError(f"{id!r} is not registered; call register_scenario first")
    # launch() is a Flask view that reads its options from the request body. Rather
    # than duplicate its 200 lines of phase machinery (router phase 0, IT phase 0.5,
    # capture start/stop, STOPPED handling), call it inside a synthetic request.
    with ui.app.test_request_context(json={"capture": bool(capture), "warmup": True}):
        result = ui.launch(id).get_json()
    return {"launch": result, "capture_filter": ui._capture_filter(a)}


DISPATCH = {
    "get_module_schema": t_get_module_schema,
    "read_scenario": t_read_scenario,
    "write_scenario": t_write_scenario,
    "write_payload": t_write_payload,
    "write_viz": t_write_viz,
    "register_scenario": t_register_scenario,
    "launch_scenario": t_launch_scenario,
}


def call_tool(name, args):
    """Run one tool. Errors come back as data so the model can correct itself."""
    fn = DISPATCH.get(name)
    if not fn:
        return {"error": f"unknown tool {name!r}"}
    try:
        out = {"ok": fn(**(args or {}))}
    except ToolError as e:
        out = {"error": str(e)}
    except ValueError as e:                 # e.g. _step_argvs rejecting a step
        out = {"error": str(e)}
    except Exception as e:                  # noqa: BLE001 - never kill the loop
        out = {"error": f"{type(e).__name__}: {e}"}
    audit(name, args, out)
    return out



# ── the agent ──────────────────────────────────────────────────────────────

MAX_TURNS = 12

SYSTEM = """You turn an OT/ICS threat report into a runnable scenario in the \
mrhOTshOT lab, so the operator gets a pcap of the described behaviour to replay \
against their detection engine offline.

Scope: the OT segment only. Do not try to reproduce a whole compromise chain -
extract the parts that put protocol traffic on the wire: protocol, function
codes, register / coil / IOA / point addresses, ports, unit ids, values, and the
cadence or persistence interval.

Strongly prefer `steps:` - an ordered list of protocol operations using the
modules listed below. Every step is validated against the real module schema, so
a rejected step means you should fix the option and try again, not work around
it. Only write a Python payload when no module can express the behaviour.

Rules:
- Cite the part of the report each step comes from, in the briefing.
- Keep everything ASCII. No em dashes.
- The watch view describes a PROCESS. Use process and alarm language ("supply
  temperature collapses", "pump stopped"), never attacker or security wording.
- Prefer watch.kind `generic` unless an existing kind genuinely matches.
- Do not invent a protocol, module, option or target host that is not listed.

Workflow: read_scenario("frostygoop_steps") for the reference form, then
write_scenario, then register_scenario, then launch_scenario with capture on.
If a tool returns an error, correct it and call again."""

MANIFEST_SCHEMA = {
    "type": "object",
    "required": ["id", "name", "protocol", "target", "desc", "steps"],
    "properties": {
        "id": {"type": "string", "description": "3-32 chars, ^[a-z][a-z0-9_]*$"},
        "name": {"type": "string"},
        "family": {"type": "string"},
        "protocol": {"type": "string"},
        "target": {"type": "string", "description": "display only, e.g. 'Heating ({heating}:502)'"},
        "desc": {"type": "string"},
        "briefing": {"type": "array", "items": {"type": "string"}},
        "watch": {"type": "object", "properties": {
            "plc": {"type": "string"}, "proto": {"type": "string"},
            "unit": {"type": "integer"}, "kind": {"type": "string"}}},
        "steps": {"type": "array", "items": {
            "type": "object",
            "required": ["protocol", "module", "plc", "options"],
            "properties": {
                "protocol": {"type": "string"}, "module": {"type": "string"},
                "plc": {"type": "string"}, "port": {"type": "integer"},
                "options": {"type": "object"},
                "mode": {"type": "string", "enum": ["once", "repeat"]},
                "interval": {"type": "number"}, "duration": {"type": "integer"}}}},
    },
}


def _messages(report, instruction):
    user = []
    if report:
        user.append("REPORT\n\n" + report)
    user.append("TASK\n\n" + (instruction or
                "Build a scenario reproducing the OT behaviour described above."))
    return [{"role": "system", "content": SYSTEM + "\n\n" + capability_prompt()},
            {"role": "user", "content": "\n\n".join(user)}]


def _finish_oneshot(text, emit):
    """Rungs 2 and 3 return a manifest in one shot; we drive the tools ourselves."""
    doc = json.loads(text) if text.lstrip().startswith("{") else yaml.safe_load(text)
    if not isinstance(doc, dict):
        raise ToolError("model did not return a manifest object")
    sid = check_id(doc.get("id", ""))
    body = yaml.safe_dump(doc, sort_keys=False, allow_unicode=True)
    for name, args in (("write_scenario", {"id": sid, "manifest_yaml": body}),
                       ("register_scenario", {"id": sid}),
                       ("launch_scenario", {"id": sid, "capture": True})):
        res = call_tool(name, args)
        emit({"tool": name, "args": args, "result": res})
        if "error" in res:
            return sid, res["error"]
    return sid, None


def generate(preset, base_url, model, api_key, report, instruction, emit):
    """Drive the model to a registered, launched scenario.

    Strategy is chosen from the preset's declared capabilities rather than
    assumed, because tool calling and strict structured output are OpenAI
    extensions the other OpenAI-compatible providers support unevenly. Every rung
    ends at the same validators, so a weaker provider loses features, never
    validation.
    """
    import agent_llm

    caps = preset.get("caps") or {}
    client = agent_llm._client(base_url, api_key)
    msgs = _messages(report, instruction)

    if not caps.get("tools"):
        rung = "structured-output" if caps.get("strict_schema") else "json-mode"
        emit({"rung": rung})
        fmt = ({"type": "json_schema",
                "json_schema": {"name": "scenario", "schema": MANIFEST_SCHEMA, "strict": False}}
               if caps.get("strict_schema") else {"type": "json_object"})
        msgs[0]["content"] += ("\n\nReturn ONE JSON object matching the scenario schema. "
                               "No prose, no code fences.")
        r = client.chat.completions.create(model=model, messages=msgs, response_format=fmt)
        sid, err = _finish_oneshot(r.choices[0].message.content, emit)
        return {"id": sid, "error": err, "rung": rung}

    emit({"rung": "agentic"})
    built = None                      # last id the agent successfully wrote
    for _turn in range(MAX_TURNS):
        r = client.chat.completions.create(model=model, messages=msgs,
                                           tools=TOOLS, tool_choice="auto")
        m = r.choices[0].message
        calls = getattr(m, "tool_calls", None) or []
        if not calls:
            return {"id": built, "text": m.content, "rung": "agentic"}
        msgs.append({"role": "assistant", "content": m.content,
                     "tool_calls": [{"id": c.id, "type": "function",
                                     "function": {"name": c.function.name,
                                                  "arguments": c.function.arguments}}
                                    for c in calls]})
        for c in calls:
            try:
                args = json.loads(c.function.arguments or "{}")
            except json.JSONDecodeError:
                args = {}
            res = call_tool(c.function.name, args)
            if c.function.name in ("write_scenario", "register_scenario") and "ok" in res:
                built = args.get("id") or built
            emit({"tool": c.function.name, "args": args, "result": res})
            msgs.append({"role": "tool", "tool_call_id": c.id,
                         "content": json.dumps(res)[:4000]})
    return {"id": built, "error": f"gave up after {MAX_TURNS} turns", "rung": "agentic"}


if __name__ == "__main__":
    import sys
    if "--selftest" in sys.argv:
        from scenario_agent_selftest import main
        main()
