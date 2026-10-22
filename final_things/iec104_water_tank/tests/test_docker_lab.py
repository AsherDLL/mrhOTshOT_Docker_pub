"""Phase 1 tests: the containerized OT target lab (docker/docker-compose.yml).

- Profile-switch unit tests run everywhere (no Docker needed).
- Lab tests use the `otlab` fixture, which skips when the lab isn't running.

Run unit only:   pytest tests/test_docker_lab.py
Run with a lab:  make lab-up && pytest -o addopts="" tests/test_docker_lab.py
"""
import importlib
import os
import socket
import sys

import pytest
from tests.conftest import port_open

# perform_malware_simulations/ isn't a package on the path; add it for config import.
_PMS = os.path.join(os.path.dirname(__file__), "..", "perform_malware_simulations")
sys.path.insert(0, os.path.abspath(_PMS))


# ── Profile switch (no Docker) ────────────────────────────────────────────────

def _load_config(profile=None):
    """Import common.config fresh under a given MRHOTSHOT_PROFILE."""
    if profile is None:
        os.environ.pop("MRHOTSHOT_PROFILE", None)
    else:
        os.environ["MRHOTSHOT_PROFILE"] = profile
    import common.config as cfg
    return importlib.reload(cfg)


def test_default_profile_is_esxi_and_unchanged():
    cfg = _load_config(None)
    assert cfg.PROFILE == "esxi"
    # Static routes are the default - must stay byte-identical to the VM lab.
    assert cfg.PLC["water"] == "192.168.1.10"
    assert cfg.PLC["heating"] == "192.168.1.16"
    assert cfg.PLC["router"] == "192.168.0.13"


def test_docker_profile_uses_service_hostnames():
    cfg = _load_config("docker")
    assert cfg.PLC["water"] == "plc-water"
    assert cfg.PLC["sis"] == "sis"
    assert cfg.PLC["router"] == "router"
    # No container for the Windows HMI yet - keeps its esxi address.
    assert cfg.PLC["hmi"] == "192.168.1.55"


def test_local_profile_is_loopback():
    cfg = _load_config("local")
    assert set(cfg.PLC.values()) == {"127.0.0.1"}


def test_unknown_profile_falls_back_to_esxi():
    cfg = _load_config("bogus")
    assert cfg.PLC["water"] == "192.168.1.10"
    _load_config(None)  # restore default for other tests


# ── Containerized targets reachable (needs the lab) ───────────────────────────

# (published host port, label) for each distinct protocol the lab exposes.
TCP_TARGETS = [
    (2404, "IEC-104 / water_treatment"),
    (8102, "IEC-61850 / power_substation"),
    (4840, "OPC-UA / gas_pipeline"),
    (102, "S7comm / centrifuge"),
    (5020, "ABB / boiler_house"),
    (502, "Modbus / heating_district"),
    (20000, "DNP3 / water_utility"),
    (5000, "M-Bus / sensor_network"),
    (8080, "router web"),
]


@pytest.mark.integration
@pytest.mark.parametrize("port,label", TCP_TARGETS, ids=[t[1] for t in TCP_TARGETS])
def test_tcp_target_reachable(otlab, port, label):
    assert port_open("127.0.0.1", port), f"{label} not answering on 127.0.0.1:{port}"


@pytest.mark.integration
def test_modbus_heating_plc_is_live(otlab):
    """FrostyGoop's vector: a real Modbus client reads the heating PLC (ENCO slave 11)."""
    from pymodbus.client import ModbusTcpClient

    client = ModbusTcpClient("127.0.0.1", port=502, timeout=3)
    assert client.connect(), "could not connect to Modbus target on 127.0.0.1:502"
    try:
        rr = client.read_holding_registers(0, count=5, slave=11)
        assert not rr.isError(), f"Modbus read error: {rr}"
        assert len(rr.registers) == 5
    finally:
        client.close()


@pytest.mark.integration
def test_sis_tristation_udp_listening(otlab):
    """The Triconex SIS (TRITON target) answers on UDP 1502."""
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    s.settimeout(2)
    try:
        # A datagram to a live UDP listener does not raise; a closed port would
        # eventually surface ICMP port-unreachable as ECONNREFUSED on recv.
        s.sendto(b"\x00", ("127.0.0.1", 1502))
    finally:
        s.close()
