"""Report -> scenario: the tools, their guards, and the full agent loop.

No network and no API key: the SDK client is stubbed with a fake that replays a
scripted sequence of tool calls, which is enough to exercise the real tool
implementations, the real validators and the real catalog registration.
"""
import json
import os
import shutil
import sys
import tempfile

import pytest

_HERE = os.path.dirname(os.path.abspath(__file__))
_DEMO = os.path.abspath(os.path.join(_HERE, "..", "demo"))
_PMS = os.path.abspath(os.path.join(_HERE, "..", "perform_malware_simulations"))

os.environ.setdefault("MRHOTSHOT_TARGETS_FILE",
                      os.path.join(tempfile.mkdtemp(prefix="mrhot_sa_"), "targets.yaml"))
os.environ.setdefault("MRHOTSHOT_PROFILE", "esxi")
sys.path.insert(0, _PMS)
sys.path.insert(0, _DEMO)

import agent_llm  # noqa: E402
import attack_demo_ui as ui  # noqa: E402
import scenario_agent as sa  # noqa: E402
import scenario_loader  # noqa: E402

GOOD = """
name: Report Derived Heating Attack
protocol: Modbus TCP
target: Heating ({heating}:502)
desc: Reproduces the Modbus writes described in the attached report.
briefing:
  - 'Report section 3.2: FC06 write to holding register 1'
watch: {plc: heating, proto: modbus, unit: 11, kind: generic}
steps:
  - protocol: modbus
    module: modbusclient
    plc: heating
    port: 502
    options: {action: WRITE_REGISTER, address: 1, data: 590, unit: 11}
    duration: 5
"""


@pytest.fixture
def clean():
    """Remove any scenario/payload this test created, and restore the catalog."""
    made = []
    yield made
    for sid in made:
        for path in (os.path.join(sa.SCENARIO_DIR, sid + ".yaml"),):
            if os.path.exists(path):
                os.remove(path)
        pdir = os.path.join(sa.GENERATED_DIR, sid)
        if os.path.isdir(pdir):
            shutil.rmtree(pdir)
    scenario_loader.invalidate()
    ui._rebuild_catalog()


# ── guards ─────────────────────────────────────────────────────────────────

@pytest.mark.parametrize("bad", ["../../etc/passwd", "a/b", "", "ab", "X" * 64,
                                 "9lives", "Has_Caps", "trailing-dash"])
def test_scenario_id_charset(bad):
    """The id is a model-controlled filename, dict key and URL component."""
    with pytest.raises(sa.ToolError):
        sa.check_id(bad)


def test_confined_refuses_escapes(tmp_path):
    root = tmp_path / "root"
    (root / "sub").mkdir(parents=True)
    outside = tmp_path / "outside.txt"
    outside.write_text("secret")
    (root / "link").symlink_to(outside)

    assert sa.confined(str(root), "sub", "a.yaml").startswith(str(root))
    for esc in (["..", "outside.txt"], ["link"], ["sub", "..", "..", "outside.txt"]):
        with pytest.raises(sa.ToolError):
            sa.confined(str(root), *esc)


def test_cannot_overwrite_a_shipped_scenario():
    res = sa.call_tool("write_scenario", {"id": "frostygoop", "manifest_yaml": GOOD})
    assert "shipped scenario" in res["error"]


def test_generated_scenario_cannot_run_foreign_argv(clean):
    manifest = GOOD + "\ncmd: ['$PY', '$SIM/frostygoop/simulation.py', '--target', '{heating}']\n"
    res = sa.call_tool("write_scenario", {"id": "evil_run", "manifest_yaml": manifest})
    assert "only run a payload under" in res["error"]
    assert not os.path.exists(os.path.join(sa.SCENARIO_DIR, "evil_run.yaml"))


def test_bad_step_option_rejected_by_the_real_validator(clean):
    res = sa.call_tool("write_scenario",
                       {"id": "bad_opt", "manifest_yaml": GOOD.replace("data: 590", "data: 999999")})
    assert "out of range" in res["error"]


def test_payload_filename_must_be_bare(clean):
    res = sa.call_tool("write_payload",
                       {"id": "ok_id", "filename": "../../../etc/cron.d/x.py", "code": "x"})
    assert "bare *.py" in res["error"]


def test_unknown_tool_is_data_not_a_crash():
    assert "unknown tool" in sa.call_tool("nope", {})["error"]


# ── grounding ──────────────────────────────────────────────────────────────

def test_capability_prompt_covers_the_live_registry():
    p = sa.capability_prompt()
    for proto in ui.CONSOLE_BUILDERS:
        assert proto in p, proto
    for module in ui.CONSOLE_BUILDERS["modbus"][0]:
        assert module in p, module
    assert "WRITE_REGISTER" in p          # allowed values, so options are not guessed
    assert "heating" in p                 # real target names
    assert "generic" in p                 # viz kinds


# ── the loop ───────────────────────────────────────────────────────────────

def _scripted_client(monkeypatch, script):
    """Fake SDK client replaying `script`: a list of turns, each either a list of
    (tool_name, args) or a final string."""
    turns = list(script)

    class F:
        def __init__(self, n, a):
            self.name, self.arguments = n, json.dumps(a)

    class TC:
        def __init__(self, i, n, a):
            self.id, self.type, self.function = f"c{i}", "function", F(n, a)

    class M:
        def __init__(self, content=None, calls=None):
            self.content, self.tool_calls = content, calls

    class R:
        def __init__(self, m):
            self.choices = [type("C", (), {"message": m})()]

    class Completions:
        def create(self, **kw):
            turn = turns.pop(0)
            if isinstance(turn, str):
                return R(M(content=turn))
            return R(M(calls=[TC(i, n, a) for i, (n, a) in enumerate(turn)]))

    class Client:
        def __init__(self):
            self.chat = type("X", (), {"completions": Completions()})()

    monkeypatch.setattr(agent_llm, "_client", lambda *a, **k: Client())


def test_agentic_loop_writes_registers_and_launches(monkeypatch, clean):
    """The whole point: a report becomes a registered, launchable scenario."""
    clean.append("rep_derived")
    seen = []
    _scripted_client(monkeypatch, [
        [("read_scenario", {"id": "frostygoop_steps"})],
        [("write_scenario", {"id": "rep_derived", "manifest_yaml": GOOD})],
        [("register_scenario", {"id": "rep_derived"})],
        "Registered rep_derived from the report.",
    ])
    out = sa.generate({"caps": {"tools": True}}, "https://x/v1", "m", "sk-x",
                      "report text", "", seen.append)

    assert out["rung"] == "agentic"
    assert out["id"] == "rep_derived"               # result names what it built
    tools = [e for e in seen if "tool" in e]        # first event is the rung marker
    assert [e["tool"] for e in tools] == ["read_scenario", "write_scenario", "register_scenario"]
    assert all("error" not in e["result"] for e in tools), tools
    assert os.path.exists(os.path.join(sa.SCENARIO_DIR, "rep_derived.yaml"))
    a = next(x for x in ui.ATTACKS if x["id"] == "rep_derived")
    assert a["name"] == "Report Derived Heating Attack"
    # steps resolved through the real builder, against the live target map
    argvs = ui._step_argvs(a)
    assert len(argvs) == 1 and "--data 590" in " ".join(map(str, argvs[0][0]))
    # and it is watchable + capturable
    assert ui.wp.plan("rep_derived")["kind"] == "generic"
    assert "port 502" in ui._capture_filter(a)


def test_loop_recovers_from_a_rejected_step(monkeypatch, clean):
    """A tool error must come back as data the model can correct, not a crash."""
    clean.append("fixed_up")
    seen = []
    _scripted_client(monkeypatch, [
        [("write_scenario", {"id": "fixed_up",
                             "manifest_yaml": GOOD.replace("data: 590", "data: 999999")})],
        [("write_scenario", {"id": "fixed_up", "manifest_yaml": GOOD})],
        "Fixed the out-of-range value.",
    ])
    sa.generate({"caps": {"tools": True}}, "https://x/v1", "m", "sk-x", "r", "", seen.append)
    tools = [e for e in seen if "tool" in e]
    assert "out of range" in tools[0]["result"]["error"]
    assert "ok" in tools[1]["result"]
    assert any(x["id"] == "fixed_up" for x in ui.ATTACKS) is False   # not registered yet
    assert os.path.exists(os.path.join(sa.SCENARIO_DIR, "fixed_up.yaml"))


def test_oneshot_rung_for_a_provider_without_tools(monkeypatch, clean):
    """A provider that cannot call tools still produces a validated scenario."""
    clean.append("oneshot_gen")
    import yaml
    doc = yaml.safe_load(GOOD)
    doc["id"] = "oneshot_gen"
    seen = []
    _scripted_client(monkeypatch, [json.dumps(doc)])
    out = sa.generate({"caps": {"tools": False, "strict_schema": True}},
                      "https://x/v1", "m", "sk-x", "r", "", seen.append)
    assert out["rung"] == "structured-output"
    assert [e.get("tool") for e in seen if "tool" in e][:2] == ["write_scenario", "register_scenario"]
    assert any(x["id"] == "oneshot_gen" for x in ui.ATTACKS)


def test_json_mode_rung_when_provider_supports_neither(monkeypatch, clean):
    clean.append("jsonmode_gen")
    import yaml
    doc = yaml.safe_load(GOOD)
    doc["id"] = "jsonmode_gen"
    seen = []
    _scripted_client(monkeypatch, [json.dumps(doc)])
    out = sa.generate({"caps": {"tools": False, "strict_schema": False}},
                      "https://x/v1", "m", "sk-x", "r", "", seen.append)
    assert out["rung"] == "json-mode"
    assert any(x["id"] == "jsonmode_gen" for x in ui.ATTACKS)


def test_audit_log_records_every_tool_call(clean):
    sa.call_tool("read_scenario", {"id": "frostygoop_steps"})
    with open(sa.AUDIT_LOG, encoding="utf-8") as fh:
        last = json.loads(fh.readlines()[-1])
    assert last["tool"] == "read_scenario"
    assert "ts" in last and "outcome" in last


# ── endpoints + review surface ─────────────────────────────────────────────

@pytest.fixture
def client():
    ui.app.config["TESTING"] = True
    c = ui.app.test_client()
    with c.session_transaction() as s:
        s["auth"] = True
    return c


def test_plan_endpoint_resolves_every_write(client):
    """The review pane renders the RESOLVED plan, so the operator sees the actual
    protocol writes rather than YAML they have to interpret."""
    j = client.get("/api/agent/scenario/frostygoop_steps/plan").get_json()
    assert j["capture_filter"] == "port 502"
    assert len(j["steps"]) == 4
    assert "--address 3" in " ".join(j["steps"][0]["argv"])
    assert "--data 590" in " ".join(j["steps"][3]["argv"])
    assert j["payloads"] == []


def test_plan_endpoint_guards_the_id(client):
    assert client.get("/api/agent/scenario/..%2F..%2Fetc/plan").status_code in (400, 404)
    assert client.get("/api/agent/scenario/no_such_scenario/plan").status_code == 404


def test_plan_endpoint_returns_generated_payload_source(client, clean):
    """LLM-authored code the dashboard will execute must be shown in full."""
    clean.append("with_payload")
    sa.call_tool("write_scenario", {"id": "with_payload", "manifest_yaml": GOOD})
    sa.call_tool("write_payload", {"id": "with_payload", "filename": "sim.py",
                                   "code": "print('hello from generated payload')\n"})
    sa.call_tool("register_scenario", {"id": "with_payload"})
    j = client.get("/api/agent/scenario/with_payload/plan").get_json()
    assert len(j["payloads"]) == 1
    assert j["payloads"][0]["filename"] == "sim.py"
    assert "hello from generated payload" in j["payloads"][0]["source"]


def test_scenario_endpoint_requires_a_key(client, monkeypatch):
    monkeypatch.delenv("MRHOTSHOT_OPENAI_KEY", raising=False)
    r = client.post("/api/agent/scenario", json={"provider": "openai"})
    assert r.status_code == 200                       # degrades over SSE, never a 500
    assert "no API key" in r.get_data(as_text=True)


def test_scenario_endpoint_is_behind_auth():
    anon = ui.app.test_client()
    assert anon.post("/api/agent/scenario", json={}).status_code == 401
    assert anon.get("/api/agent/scenario/x/plan").status_code == 401


def test_build_ui_present(client):
    html = client.get("/").get_data(as_text=True)
    for frag in ("agent-build", "agent-review", "agent-steps", "agent-plan"):
        assert frag in html, frag


# ── generated watch views ──────────────────────────────────────────────────

GOOD_VIZ = '''registerViz({
  kind: "reporttest",
  title: "Report Test Process",
  map(raw) { return { level: raw.level }; },
  build(stage) { stage.innerHTML = "<div class='ro'></div>"; return {}; },
  update(refs, v) { return { level: "normal", msg: "" }; },
});
'''


@pytest.fixture
def viz_cleanup():
    made = []
    yield made
    for kind in made:
        path = os.path.join(sa.VIZ_DIR, kind + ".js")
        if os.path.exists(path):
            os.remove(path)


def test_write_viz_creates_a_loadable_module(viz_cleanup):
    viz_cleanup.append("reporttest")
    res = sa.call_tool("write_viz", {"kind": "reporttest", "code": GOOD_VIZ})
    assert "ok" in res, res
    assert os.path.exists(os.path.join(sa.VIZ_DIR, "reporttest.js"))
    # the Jinja loop picks it up with no script tag to add
    assert "reporttest.js" in ui.viz_modules("reporttest")


def test_write_viz_cannot_replace_a_shipped_module():
    for shipped in ("heating", "generic", "vehicle"):
        res = sa.call_tool("write_viz", {"kind": shipped, "code": GOOD_VIZ})
        assert "shipped visualization" in res["error"]


def test_write_viz_requires_a_matching_registration():
    """A module that never calls registerViz with its own kind would load and do
    nothing, leaving the page silently on the generic fallback."""
    res = sa.call_tool("write_viz", {"kind": "nomatch", "code": "console.log('hi')"})
    assert "registerViz" in res["error"]
    res = sa.call_tool("write_viz", {"kind": "nomatch", "code": GOOD_VIZ})   # kind mismatch
    assert "registerViz" in res["error"]
    assert not os.path.exists(os.path.join(sa.VIZ_DIR, "nomatch.js"))


@pytest.mark.parametrize("bad", ["../../../app", "a/b", "Caps"])
def test_write_viz_id_guarded(bad):
    assert "error" in sa.call_tool("write_viz", {"kind": bad, "code": GOOD_VIZ})


def test_one_broken_module_cannot_break_other_pages(client, viz_cleanup):
    """Blast radius: a page loads only registry, generic and its own kind."""
    viz_cleanup.append("reporttest")
    sa.call_tool("write_viz", {"kind": "reporttest", "code": GOOD_VIZ})
    import re
    html = client.get("/watch/frostygoop").get_data(as_text=True)
    assert "reporttest.js" not in html
    assert re.findall(r"js/viz/([a-z_]+\.js)", html) == \
        ["registry.js", "generic.js", "heating.js"]


# ── grounding regressions found by running on a real PDF ───────────────────

def test_capability_prompt_lists_every_viz_kind():
    """viz_modules() answers 'what does THIS page load' and returns only registry +
    generic + the kind in use. Grounding must use viz_kinds() instead, or the model
    is told `generic` is the only watch view that exists and can never pick a
    process picture that genuinely fits."""
    p = sa.capability_prompt()
    kinds = ui.viz_kinds()
    assert len(kinds) > 5, kinds
    for k in kinds:
        assert k in p, k


def test_capability_prompt_carries_connection_defaults():
    """Without these the model guesses rack/slot/unit. A real run against an OT
    survey PDF produced S7 steps with rack0/slot2 - which this emulator accepts but
    real S7-300 hardware would not, and which puts a different TSAP in the pcap than
    every other scenario in the lab."""
    p = sa.capability_prompt()
    assert "CONNECTION DEFAULTS" in p
    assert "rack0/slot1" in p          # s7
    assert "unit 11" in p              # modbus
    assert "CA 1" in p                 # iec104
    for proto, block in ui.wp.IO_POINTS.items():
        if block.get("endpoint"):
            assert block["endpoint"] in p, proto
