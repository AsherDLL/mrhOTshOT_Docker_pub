"""Phase 3 tests: the redesigned dashboard (demo/attack_demo_ui.py).

Uses Flask's test client - no server, no network. Points the target-overrides
file at a temp path (via MRHOTSHOT_TARGETS_FILE, read at import) so editing
endpoints don't touch the real config/targets.yaml.
"""
import importlib
import os
import sys
import tempfile

import pytest

_HERE = os.path.dirname(os.path.abspath(__file__))
_DEMO = os.path.abspath(os.path.join(_HERE, "..", "demo"))
_PMS = os.path.abspath(os.path.join(_HERE, "..", "perform_malware_simulations"))

# Isolate the overrides file BEFORE importing the app (path is bound at import).
_TMP_YAML = os.path.join(tempfile.mkdtemp(prefix="mrhot_targets_"), "targets.yaml")
os.environ["MRHOTSHOT_TARGETS_FILE"] = _TMP_YAML
# Pin esxi at import so _autostart() doesn't try to start Docker during tests.
os.environ["MRHOTSHOT_PROFILE"] = "esxi"

sys.path.insert(0, _PMS)
sys.path.insert(0, _DEMO)
ui = importlib.import_module("attack_demo_ui")


@pytest.fixture
def client():
    """Authenticated test client (logged in via the session)."""
    ui.app.config["TESTING"] = True
    c = ui.app.test_client()
    with c.session_transaction() as s:
        s["auth"] = True
    return c


@pytest.fixture
def anon():
    """Unauthenticated test client."""
    ui.app.config["TESTING"] = True
    return ui.app.test_client()


def test_index_renders(client):
    r = client.get("/")
    assert r.status_code == 200
    html = r.get_data(as_text=True)
    assert "mrhOTshOT" in html
    assert "app.css" in html and "app.js" in html      # external assets, not inline
    assert "FrostyGoop" in html                          # catalog rendered


def test_static_assets(client):
    assert client.get("/static/css/app.css").status_code == 200
    assert client.get("/static/js/app.js").status_code == 200


def test_api_targets_lists_resolved(client):
    j = client.get("/api/targets").get_json()
    assert j["profile"] == "esxi"
    assert set(j["profiles"]) == {"esxi", "docker", "local"}
    water = next(t for t in j["targets"] if t["name"] == "water")
    assert water["ip"] == "192.168.1.10"
    assert water["protocols"]["iec104"] == 2404


def test_status_lists_attacks(client):
    j = client.get("/status").get_json()
    assert "frostygoop" in j and j["frostygoop"] is False


def test_save_target_persists_and_rebuilds(client):
    r = client.post("/api/targets", json={"name": "heating", "ip": "10.0.0.77",
                                          "protocols": {"modbus": 1502}})
    assert r.status_code == 200
    # persisted to the temp yaml
    import yaml
    with open(_TMP_YAML) as fh:
        saved = yaml.safe_load(fh)
    assert saved["targets"]["heating"]["ip"] == "10.0.0.77"
    # and the live catalog rebuilt with the new target baked into the argv
    fg = next(a for a in ui.ATTACKS if a["id"] == "frostygoop")
    assert "10.0.0.77" in " ".join(map(str, fg["cmd"]))


def test_set_profile_switches_and_persists(client, monkeypatch):
    # Keep the test hermetic: don't actually start Docker or inspect containers.
    monkeypatch.setattr(ui, "ensure_lab_up", lambda: False)
    monkeypatch.setattr(ui, "_container_ip", lambda host: None)  # fall back to hostname
    r = client.post("/api/profile", json={"profile": "docker"})
    assert r.status_code == 200
    assert r.get_json()["profile"] == "docker"
    j = client.get("/api/targets").get_json()
    water = next(t for t in j["targets"] if t["name"] == "water")
    assert water["ip"] == "plc-water"
    # restore for other tests
    client.post("/api/profile", json={"profile": "esxi"})


def test_unknown_profile_rejected(client):
    assert client.post("/api/profile", json={"profile": "bogus"}).status_code == 400


def test_stop_when_nothing_running(client):
    assert client.post("/stop/frostygoop").get_json()["status"] == "not_running"


def test_launch_accepts_capture_flag(client):
    # esxi target is unreachable, but the launch endpoint must accept the flag
    # and echo it without error.
    r = client.post("/launch/frostygoop", json={"capture": True})
    assert r.status_code == 200
    assert r.get_json().get("capture") is True
    # let the worker thread settle so it doesn't dangle into other tests
    import time
    time.sleep(0.3)
    ui.PROCS.pop("frostygoop", None)


def test_router_exploit_has_profile_specific_commands():
    rx = next(a for a in ui.ATTACKS if a["id"] == "router_exploit")
    full = " ".join(map(str, rx["cmd"]))
    lab = " ".join(map(str, rx["cmd_lab"]))
    assert "router_initial_access.py" in full and "--deploy-phishing" in full   # esxi full chain
    assert "01_router_exploit.py" in lab and "--deploy-phishing" not in lab      # trimmed lab variant


def test_catalog_json_strips_all_cmd_keys(client):
    html = client.get("/").get_data(as_text=True)
    # The browser payload must not leak any command (cmd or cmd_lab).
    assert "router_initial_access.py" not in html
    assert "01_router_exploit.py" not in html


def test_esxi_only_attacks_hidden_under_docker(monkeypatch):
    monkeypatch.setattr(ui, "CURRENT_PROFILE", "docker")
    vis = {a["id"] for a in ui._visible_attacks()}
    assert "cosmicenergy" not in vis and "havex" not in vis   # need VM-lab hosts
    assert "frostygoop" in vis
    monkeypatch.setattr(ui, "CURRENT_PROFILE", "esxi")
    vis2 = {a["id"] for a in ui._visible_attacks()}
    assert {"cosmicenergy", "havex"} <= vis2                   # available under esxi


def test_launch_esxi_only_blocked_under_docker(client, monkeypatch):
    monkeypatch.setattr(ui, "CURRENT_PROFILE", "docker")
    r = client.post("/launch/cosmicenergy", json={})
    assert r.status_code == 400
    assert "esxi" in r.get_json()["msg"].lower()


def test_caldera_info(client):
    j = client.get("/api/caldera/info").get_json()
    assert "ui_port" in j and "up" in j     # degrades gracefully when Caldera is down


def test_caldera_proxy_unreachable_is_502(client, monkeypatch):
    # With no reachable Caldera, the proxy should fail cleanly (not 500).
    assert client.get("/api/caldera/agents").status_code in (200, 502)


def test_captures_endpoint(client):
    j = client.get("/api/captures").get_json()
    assert "captures" in j and "capturing" in j and "path" in j
    assert isinstance(j["captures"], list)


def test_capture_delete_missing(client):
    assert client.delete("/api/captures/nope_does_not_exist.pcap").status_code == 404


def test_custom_protocols_listed(client):
    j = client.get("/api/custom-protocols").get_json()
    assert {"modbus", "iec104", "s7", "opcua", "bacnet", "dnp3", "fins", "iec61850", "mbus"} <= set(j)
    assert j["modbus"]["port"] == 502 and j["iec104"]["port"] == 2404


def test_custom_rejects_unknown_protocol(client):
    r = client.post("/custom", json={"protocol": "telnet", "ip": "127.0.0.1"})
    assert r.status_code == 400


def test_custom_rejects_bad_ip(client):
    r = client.post("/custom", json={"protocol": "modbus", "ip": "not-an-ip; rm -rf /"})
    assert r.status_code == 400      # also guards against argv injection


def test_custom_dispatch_targets_real_clients():
    # Each protocol maps to an existing parameterized client script.
    for spec in ui.CUSTOM_PROTOCOLS.values():
        script = spec[2]
        assert script.endswith(".py")


def test_frostygoop_unit_kwarg_matches_pymodbus():
    """The FrostyGoop sim must pass the unit-id kwarg the installed pymodbus accepts
    (slave on <3.7, device_id on >=3.7), or every write silently hits the wrong slave."""
    import inspect

    from frostygoop import simulation as fg
    from pymodbus.client import ModbusTcpClient
    params = inspect.signature(ModbusTcpClient.write_coil).parameters
    assert fg._UNIT_KW in params
    assert fg._UNIT_KW == ("device_id" if "device_id" in params else "slave")


def test_fuxnet_has_direct_lab_variant():
    fx = next(a for a in ui.ATTACKS if a["id"] == "fuxnet")
    lab = " ".join(map(str, fx["cmd_lab"]))
    full = " ".join(map(str, fx["cmd"]))
    assert "--direct" in lab                      # docker/local: no SSH router pivot
    assert "--router" in full and "--direct" not in full   # esxi: full SSH pivot


def test_capture_filter_derivation():
    fg = next(a for a in ui.ATTACKS if a["id"] == "frostygoop")
    assert "port 502" in ui._capture_filter(fg)            # Modbus TCP
    tri = next(a for a in ui.ATTACKS if a["id"] == "triton")
    assert "port 1502" in ui._capture_filter(tri)          # TriStation


def test_lab_status_only_counts_known_services(monkeypatch):
    # A stray container must not inflate the count beyond our 11 lab services.
    fake = "plc-water running\nsnapshot running\nrouter running\n"

    class R:
        stdout = fake
        returncode = 0

    monkeypatch.setattr(ui.subprocess, "run", lambda *a, **k: R())
    monkeypatch.setattr(ui, "_docker_available", lambda: True)
    st = ui.lab_status()
    assert "snapshot" not in st
    assert set(st) == set(ui.LAB_SERVICES)
    assert st["plc-water"] is True and st["plc-gas"] is False


def test_login_required_for_browser_and_api(anon):
    # Browser GET -> redirect to /login; API/XHR -> 401; static + /login open.
    r = anon.get("/", headers={"Accept": "text/html"})
    assert r.status_code == 302 and "/login" in r.headers["Location"]
    assert anon.get("/api/targets").status_code == 401
    assert anon.get("/login").status_code == 200
    assert anon.get("/static/css/app.css").status_code == 200


def test_login_flow(anon):
    assert anon.post("/login", data={"username": "root", "password": "nope"}).status_code == 401
    r = anon.post("/login", data={"username": "root", "password": "root"})
    assert r.status_code == 302
    assert anon.get("/api/targets").status_code == 200      # session now authenticated
    anon.get("/logout")
    assert anon.get("/api/targets").status_code == 401


def test_token_still_works_for_api(anon, monkeypatch):
    monkeypatch.setattr(ui, "UI_TOKEN", "s3cret")
    assert anon.get("/api/targets", headers={"X-Auth-Token": "s3cret"}).status_code == 200


def test_profile_reachability_reported(client, monkeypatch):
    monkeypatch.setattr(ui, "_esxi_available", lambda: False)
    monkeypatch.setattr(ui, "_docker_available", lambda: True)
    j = client.get("/api/targets").get_json()
    assert j["reachable"]["esxi"] is False
    assert j["reachable"]["docker"] is True and j["reachable"]["local"] is True


# ── Phase 0 regressions ────────────────────────────────────────────────────
# _PROTO_PORTS is substring-matched against a free-text "protocol" field, so a
# name it does not recognise yields an EMPTY filter -- and _start_capture then
# runs tshark with no BPF at all, dumping every packet on the interface. Six
# attacks were in that state (four empty, plus cosmicenergy/evilscholar which
# captured only their first stage).

@pytest.mark.parametrize("attack_id,port", [
    ("industroyer2",   "2404"),    # "IEC 60870-5-104" matched no key at all
    ("cosmicenergy",   "2404"),    # matched only the MSSQL delivery stage
    ("canbus_inject",  "20001"),   # "CANopen (CAN/TCP)"
    ("canbus_brake",   "20001"),
    ("ntcip_override", "161"),     # "NTCIP (SNMP)"
    ("evilscholar",    "27127"),   # UDP MODICON discovery stage
])
def test_capture_filter_covers_own_protocol(attack_id, port):
    a = next(x for x in ui.ATTACKS if x["id"] == attack_id)
    assert f"port {port}" in ui._capture_filter(a)


def test_no_attack_captures_everything():
    """An empty filter means tshark records the whole interface. Never acceptable."""
    empty = [a["id"] for a in ui.ATTACKS if not ui._capture_filter(a)]
    assert empty == [], f"attacks with no capture filter: {empty}"


def test_attacker_scripts_single_definition():
    """ATTACKER_SCRIPTS was assigned twice (abspath at :51, then a relative
    reassignment that won). IT_PHASE_SCRIPTS was built from the first and the
    catalog from the second, so the same directory had two spellings."""
    root = ui.ATTACKER_SCRIPTS
    assert root == os.path.normpath(root)
    assert ui.IT_PHASE_SCRIPTS["frostygoop"].startswith(root)
    rx = next(a for a in ui.ATTACKS if a["id"] == "router_exploit")
    assert rx["cmd"][1].startswith(root)


def test_every_script_path_exists():
    """Permanent guard: every .py an attack would exec must be on disk. This
    outlives the YAML migration and is what catches a bad path in a manifest."""
    for a in ui.ATTACKS:
        for tok in list(a.get("cmd", [])) + list(a.get("cmd_lab", [])):
            if str(tok).endswith(".py"):
                assert os.path.exists(tok), (a["id"], tok)


def test_sim_package_imports():
    """perform_malware_simulations/__init__.py re-exported three modules that no
    longer exist, so importing the package raised ImportError."""
    import importlib
    assert importlib.import_module("perform_malware_simulations") is not None


# ── Phase 2: watch config derived from the manifests ───────────────────────

def test_no_viz_derived_from_manifests():
    """Initial-access / recon attacks have no process to visualize."""
    assert set(ui.wp.no_viz()) == {"router_exploit", "havex"}


def test_plan_shape_unchanged_for_every_attack():
    """plan() is the single merge point the whole watch view hangs off; its
    return shape must survive the move from WATCH_MAP to YAML."""
    for a in ui.ATTACKS:
        p = ui.wp.plan(a["id"])
        assert {"kind", "label", "direct", "noviz"} <= set(p)
        if p["noviz"]:
            continue
        assert p["plc"] and p["proto"]
        assert isinstance(p["io"], dict)


def test_plan_resolves_restore_name_to_a_real_table():
    """Manifests name a restore table; plan() must hand back the table itself."""
    fg = ui.wp.plan("frostygoop")
    assert fg["restore"] is ui.wp.RESTORES["heating"]
    assert fg["restore"]["proto"] == "modbus"
    # power is shared by four scenarios - all must resolve to the same object
    shared = [ui.wp.plan(a)["restore"] for a in
              ("industroyer2", "blackenergy3", "crashoverride", "cosmicenergy")]
    assert all(r is ui.wp.RESTORES["power"] for r in shared)


def test_plan_omits_restore_when_manifest_has_none():
    """Fuxnet bricks the gateway irreversibly - it must not offer a restore."""
    assert "restore" not in ui.wp.plan("fuxnet")


def test_it_phase_scripts_derived_and_present():
    assert len(ui.IT_PHASE_SCRIPTS) == 14
    for aid, path in ui.IT_PHASE_SCRIPTS.items():
        assert os.path.isabs(path), (aid, path)
        assert os.path.exists(path), (aid, path)


def test_watch_page_loads_only_the_module_it_needs(client):
    """viz modules are discovered from disk, so adding viz/<kind>.js is enough -
    there is no script tag left to forget in watch.html. A page loads registry.js,
    generic.js (the fallback) and its own kind, so one broken module - a generated
    one, say - cannot take down every other watch page."""
    import re
    html = client.get("/watch/frostygoop").get_data(as_text=True)
    loaded = re.findall(r"js/viz/([a-z_]+\.js)", html)
    assert loaded == ["registry.js", "generic.js", "heating.js"]
    assert "js/visualizer.js" in html

    stux = client.get("/watch/stuxnet").get_data(as_text=True)
    assert re.findall(r"js/viz/([a-z_]+\.js)", stux) == \
        ["registry.js", "generic.js", "centrifuge.js"]


def test_watch_page_noviz_loads_no_modules(client):
    html = client.get("/watch/router_exploit").get_data(as_text=True)
    assert "js/viz/" not in html


# ── Phase 3: declarative `steps:` scenarios ────────────────────────────────

def _steps_attack():
    return next(a for a in ui.ATTACKS if a["id"] == "frostygoop_steps")


def test_steps_scenario_builds_validated_argvs():
    """Every step routes through the same build_<proto>_cmd the Custom Target
    tab uses, so a steps scenario can express nothing you could not do by hand."""
    argvs = ui._step_argvs(_steps_attack())
    assert len(argvs) == 4
    joined = [" ".join(map(str, argv)) for argv, _label, _dur in argvs]
    assert all("modbus_console.py" in j for j in joined)
    assert "-a WRITE_COIL" in joined[0] and "--address 3" in joined[0]
    assert "-a WRITE_REGISTER" in joined[3] and "--data 590" in joined[3]
    assert "--mode repeat" in joined[3]


def test_steps_resolve_plc_to_live_ip():
    """plc: heating must resolve through the live target map, not be baked in."""
    moved = dict(ui.PLC, heating="10.9.9.9")
    argvs = ui._step_argvs(_steps_attack(), moved)
    assert all("10.9.9.9" in " ".join(map(str, argv)) for argv, _l, _d in argvs)


@pytest.mark.parametrize("step,why", [
    ({"protocol": "telnet", "module": "x"}, "unknown protocol"),
    ({"protocol": "modbus", "module": "nope"}, "unknown module"),
    ({"protocol": "modbus", "module": "modbusclient", "host": "bad; rm -rf /"}, "invalid target host"),
    ({"protocol": "modbus", "module": "modbusclient", "host": "h", "port": 99999}, "invalid port"),
    ({"protocol": "modbus", "module": "modbusclient", "host": "h",
      "options": {"action": "WRITE_REGISTER", "data": 999999}}, ""),
])
def test_steps_rejected_before_anything_runs(step, why):
    """A bad step must raise while argvs are being built - a partially applied
    scenario is worse than a rejected one."""
    with pytest.raises(ValueError) as e:
        ui._step_argvs({"id": "t", "steps": [step]})
    if why:
        assert why in str(e.value)


def test_steps_total_duration_capped():
    long_run = [{"protocol": "modbus", "module": "modbusclient", "host": "h",
                 "options": {"action": "READ_COILS", "address": 0, "number": 1},
                 "duration": 400} for _ in range(3)]
    with pytest.raises(ValueError) as e:
        ui._step_argvs({"id": "t", "steps": long_run})
    assert "total step duration" in str(e.value)


def test_steps_capture_filter_comes_from_step_ports():
    """Steps state their ports outright, so the pcap filter never depends on the
    free-text protocol name matching a _PROTO_PORTS key."""
    a = dict(_steps_attack(), protocol="something unrecognisable")
    assert "port 502" in ui._capture_filter(a)


def test_launch_accepts_a_steps_scenario(client):
    import time
    r = client.post("/launch/frostygoop_steps", json={})
    assert r.status_code == 200
    time.sleep(0.3)
    ui.PROCS.pop("frostygoop_steps", None)
    ui.running["frostygoop_steps"] = False


def test_unknown_plc_error_names_the_valid_targets():
    """This error is read by the copilot, which cannot correct an unknown plc
    name unless it is shown the alternatives."""
    with pytest.raises(ValueError) as e:
        ui._step_argvs({"id": "t", "steps": [
            {"protocol": "s7", "module": "cpu_info", "plc": "nosuch"}]})
    msg = str(e.value)
    assert "unknown plc 'nosuch'" in msg
    assert "heating" in msg and "mfg" in msg      # the known names are listed
