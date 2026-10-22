"""Phase 2 tests: the unified target registry (common/targets.py).

All unit tests - no Docker, no network. They construct TargetRegistry directly
with an explicit (nonexistent) overrides path so the shipped config/targets.yaml
can't perturb default-parity assertions.
"""
import os
import sys

import pytest

# perform_malware_simulations/ holds the `common` package (PLC map + registry).
_PMS = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "perform_malware_simulations"))
sys.path.insert(0, _PMS)

from common.targets import Target, TargetRegistry  # noqa: E402

NO_YAML = "/nonexistent/targets.yaml"  # force pure profile defaults

# The original static routes - the registry must reproduce these exactly (esxi).
ESXI_IPS = {
    "legacy": "192.168.1.6", "water": "192.168.1.10", "power": "192.168.1.11",
    "gas": "192.168.1.12", "centrifuge": "192.168.1.13", "hvac": "192.168.1.14",
    "boiler": "192.168.1.15", "heating": "192.168.1.16", "dnp3": "192.168.1.17",
    "sensors": "192.168.1.18", "sis": "192.168.1.19", "historian": "192.168.1.9",
    "iconics": "192.168.1.20", "hmi": "192.168.1.55", "router": "192.168.0.13",
}


def reg(profile="esxi", env=None):
    return TargetRegistry(profile=profile, overrides_path=NO_YAML, env=env or {})


# ── default parity (the "static routes are the default" guarantee) ────────────

@pytest.mark.parametrize("name,ip", ESXI_IPS.items())
def test_esxi_defaults_byte_identical(name, ip):
    assert reg("esxi").ip(name) == ip


def test_default_ports_match_protocol_constants():
    r = reg("esxi")
    assert r.port("water", "iec104") == 2404
    assert r.port("heating", "modbus") == 502
    assert r.port("centrifuge", "s7") == 102
    assert r.port("dnp3", "dnp3") == 20000
    assert r.port("sis", "tristation") == 1502


def test_primary_port_is_first_declared_protocol():
    # power declares iec61850 first, then iec104
    assert reg("esxi").port("power") == 8102


# ── profiles ──────────────────────────────────────────────────────────────────

def test_docker_profile_uses_service_hostnames():
    r = reg("docker")
    assert r.ip("water") == "plc-water"
    assert r.ip("sis") == "sis"
    assert r.ip("router") == "router"
    assert r.ip("legacy") == "plc-water"  # tunnel default maps to the water PLC


def test_docker_placeholders_keep_esxi_ip():
    # No container for these yet -> they retain their ESXi addresses.
    r = reg("docker")
    assert r.ip("iconics") == "192.168.1.20"
    assert r.ip("historian") == "192.168.1.9"
    assert r.ip("hmi") == "192.168.1.55"


def test_local_profile_is_loopback():
    r = reg("local")
    assert all(r.ip(n) == "127.0.0.1" for n in ESXI_IPS)


def test_unknown_profile_falls_back_to_esxi():
    assert reg("bogus").ip("water") == "192.168.1.10"


# ── resolution precedence: explicit > env > yaml > profile default ────────────

def test_explicit_arg_wins():
    r = reg("esxi", env={"MRHOTSHOT_WATER_IP": "10.0.0.9"})
    assert r.ip("water", explicit="172.16.0.1") == "172.16.0.1"
    assert r.resolve("water", "iec104", ip="172.16.0.1", port=9999) == ("172.16.0.1", 9999)


def test_env_overrides_profile_default():
    r = reg("esxi", env={"MRHOTSHOT_WATER_IP": "10.0.0.9", "MRHOTSHOT_WATER_PORT": "12404"})
    assert r.resolve("water", "iec104") == ("10.0.0.9", 12404)


def test_env_protocol_specific_port():
    r = reg("esxi", env={"MRHOTSHOT_POWER_IEC104_PORT": "30000"})
    assert r.port("power", "iec104") == 30000
    assert r.port("power", "iec61850") == 8102  # untouched


def test_yaml_overrides_then_env_beats_yaml(tmp_path):
    import textwrap
    f = tmp_path / "t.yaml"
    f.write_text(textwrap.dedent("""
        profile: local
        targets:
          water:
            ip: 172.30.0.5
            protocols: {iec104: 11104}
          router:
            creds: {username: operator, password: secret}
    """))
    # yaml profile applies (no env profile set)
    r = TargetRegistry(overrides_path=str(f), env={})
    assert r._profile == "local"
    assert r.resolve("water", "iec104") == ("172.30.0.5", 11104)
    assert r.creds("router") == {"username": "operator", "password": "secret"}
    assert r.ip("gas") == "127.0.0.1"  # unset target -> local profile default

    # env beats yaml for both profile and value
    r2 = TargetRegistry(overrides_path=str(f),
                        env={"MRHOTSHOT_PROFILE": "esxi", "MRHOTSHOT_WATER_IP": "8.8.8.8"})
    assert r2._profile == "esxi"
    assert r2.ip("water") == "8.8.8.8"
    assert r2.ip("gas") == "192.168.1.12"


# ── aliases, creds, plc_map, dataclass ────────────────────────────────────────

def test_mfg_is_alias_for_centrifuge():
    r = reg("esxi")
    assert r.ip("mfg") == r.ip("centrifuge") == "192.168.1.13"


def test_default_and_per_target_creds():
    r = reg("esxi")
    assert r.creds("water") == {"username": "operator", "password": "labpass123"}
    assert r.creds("router") == {"username": "admin", "password": "admin"}
    assert r.creds("hmi") == {"username": "operator", "password": "labpass123"}


def test_plc_map_covers_all_demo_keys():
    m = reg("esxi").plc_map()
    for k in list(ESXI_IPS) + ["mfg"]:
        assert k in m, f"plc_map missing {k}"
    assert m["mfg"] == "192.168.1.13"


def test_get_returns_resolved_target():
    t = reg("docker").get("power")
    assert isinstance(t, Target)
    assert t.name == "power"
    assert t.ip == "plc-power"
    assert t.protocols == {"iec61850": 8102, "iec104": 2404}
    assert t.port() == 8102 and t.port("iec104") == 2404
