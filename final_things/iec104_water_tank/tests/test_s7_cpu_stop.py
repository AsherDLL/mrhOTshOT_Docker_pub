"""A CPU STOP must actually halt the emulated S7 controller, and be reportable.

Three faults this covers, found by running AA26-231A against the live lab:
  1. python-snap7's Client.get_cpu_state() never queries the PLC - it returns
     "S7CpuStatusRun" unconditionally - so CPU state has to be published as memory.
  2. The adapter ignored a stop snap7 had already recorded, so the cascade kept
     spinning and DB4 kept being republished.
  3. Nothing could restart a halted CPU from the dashboard.
"""
import os
import struct
import sys

import pytest

_HERE = os.path.dirname(os.path.abspath(__file__))
_ROOT = os.path.abspath(os.path.join(_HERE, ".."))
_DEMO = os.path.join(_ROOT, "demo")
for _p in (_ROOT, _DEMO):
    if _p not in sys.path:
        sys.path.insert(0, _p)

import watch_process as wp  # noqa: E402
from server.plant import CENTRIFUGE_NORMAL_HZ, CentrifugeCascade  # noqa: E402
from server.s7_centrifuge_adapter import S7CentrifugeAdapter  # noqa: E402

RUN, STOP = 8, 4          # snap7 CPUState


class FakeServer:
    """Stands in for snap7's Server: the adapter only reads .cpu_state, and falls back
    to its own ctypes arrays when there are no memory_areas."""

    def __init__(self, state=RUN):
        self.cpu_state = state


@pytest.fixture
def adapter():
    a = S7CentrifugeAdapter(CentrifugeCascade(), {"port": 1102})
    a.server = FakeServer()
    return a


def _db3(a):
    return a._get_area(a.DB_SETPOINTS)


def _reported_speeds(a):
    db4 = a._get_area(a.DB_MEASUREMENTS)
    return [struct.unpack_from(">f", db4, i * 16)[0] for i in range(3)]


def _run_ticks(a, n, dt=0.1):
    """Drive n ticks of simulated time. CentrifugeCascade.update() takes dt from the
    wall clock, so a tight loop would advance the physics by ~0 seconds."""
    for _ in range(n):
        a.cascade.last_t -= dt
        a._tick()


# ── the adapter ────────────────────────────────────────────────────────────

def test_cpu_starts_in_run_and_is_published(adapter):
    adapter._tick()
    assert adapter._cpu_running() is True
    assert _db3(adapter)[adapter.DB3_CPU_RUN] == 1


def test_stop_zeroes_the_drive_setpoints_once(adapter):
    """A real S7 STOP drives outputs to their substitute values, so the drives lose
    their speed reference and coast down."""
    adapter._tick()
    assert all(c.setpoint_hz > 0 for c in adapter.cascade.centrifuges)

    adapter.server.cpu_state = STOP
    adapter._tick()
    assert all(c.setpoint_hz == 0.0 for c in adapter.cascade.centrifuges)
    assert _db3(adapter)[adapter.DB3_CPU_RUN] == 0

    # the falling edge fires once, not every tick
    adapter.cascade.centrifuges[0].setpoint_hz = 123.0
    adapter._tick()
    assert adapter.cascade.centrifuges[0].setpoint_hz == 123.0


def test_rotors_coast_down_while_stopped(adapter):
    adapter._tick()
    adapter.server.cpu_state = STOP
    _run_ticks(adapter, 60)                              # 6 s of simulated coast-down
    assert all(c.speed_hz < 10.0 for c in adapter.cascade.centrifuges), \
        [c.speed_hz for c in adapter.cascade.centrifuges]


def test_process_image_freezes_while_stopped(adapter):
    """DB4 is what the HMI trusts. A halted CPU stops updating it, so the operator's
    screen goes stale while the plant moves - itself a detection signal."""
    adapter._tick()
    frozen = _reported_speeds(adapter)

    adapter.server.cpu_state = STOP
    _run_ticks(adapter, 30)

    assert _reported_speeds(adapter) == frozen           # DB4 untouched
    assert any(c.speed_hz < frozen[i] - 1 for i, c in enumerate(adapter.cascade.centrifuges))


def test_attacker_writes_are_not_acted_on_while_stopped(adapter):
    """DB3 still accepts writes (snap7 serves a stopped CPU), but a halted CPU does not
    execute, so the setpoint must not reach the drives."""
    adapter._tick()
    adapter.server.cpu_state = STOP
    adapter._tick()

    struct.pack_into(">f", _db3(adapter), 0, 9999.0)      # the AA26-231A overspeed write
    _run_ticks(adapter, 5)
    assert adapter.cascade.centrifuges[0].setpoint_hz == 0.0


def test_cold_start_resumes_control(adapter):
    adapter._tick()
    adapter.server.cpu_state = STOP
    adapter._tick()

    struct.pack_into(">f", _db3(adapter), 0, CENTRIFUGE_NORMAL_HZ)
    adapter.server.cpu_state = RUN                        # restore writes DBs, then cold-starts
    adapter._tick()
    assert _db3(adapter)[adapter.DB3_CPU_RUN] == 1
    assert adapter.cascade.centrifuges[0].setpoint_hz == pytest.approx(CENTRIFUGE_NORMAL_HZ)


def test_missing_cpu_state_never_halts(adapter):
    """An older snap7 with no CPU model must not silently freeze every S7 target."""
    adapter.server = object()
    assert adapter._cpu_running() is True


# ── the I/O map contract that drives the generic view ──────────────────────

def test_s7_io_points_publish_cpu_state():
    pts = {p.get("key"): p for p in wp.IO_POINTS["s7"]["points"] if p.get("key")}
    assert "cpu_run" in pts
    alarm = pts["cpu_run"]["alarm"]
    assert alarm["equals"] is False and alarm["level"] == "critical"
    assert "HALTED" in alarm["msg"]
    addrs = [p["addr"] for p in wp.IO_POINTS["s7"]["points"]]
    assert any("STOP" in a for a in addrs)               # the write the scenario performs


def test_every_alarm_uses_a_level_the_shell_knows():
    """visualizer.js does CHIP[level] || CHIP.offline, so an invented level silently
    degrades the banner to OFFLINE."""
    valid = {"normal", "warning", "critical", "offline"}
    for proto, block in wp.IO_POINTS.items():
        for p in block.get("points", []):
            a = p.get("alarm")
            if not a:
                continue
            assert a["level"] in valid, (proto, p.get("key"), a["level"])
            assert a.get("msg"), (proto, p.get("key"))
            assert {"equals", "above", "below"} & set(a), (proto, p.get("key"))


# ── recovery ───────────────────────────────────────────────────────────────

class FakeClient:
    """Records the restore sequence. cpu_run drives the mirror read at DB3.13."""

    def __init__(self, cpu_run, fail_start=False):
        self.calls, self._cpu_run, self._fail = [], cpu_run, fail_start

    def connect(self, *a): self.calls.append(("connect", a))
    def db_write(self, db, start, data): self.calls.append(("db_write", db, start))
    def db_read(self, db, start, size):
        self.calls.append(("db_read", db, start))
        return bytes([1 if self._cpu_run else 0])
    def plc_cold_start(self):
        self.calls.append(("cold_start",))
        if self._fail:
            raise RuntimeError("controller refused the restart")
    def disconnect(self): self.calls.append(("disconnect",))

    @property
    def names(self): return [c[0] for c in self.calls]


def _restore_with(monkeypatch, client):
    import snap7
    monkeypatch.setattr(snap7.client, "Client", lambda *a, **k: client)
    return wp.restore({"restore": wp.RESTORES["centrifuge"]}, "10.0.0.1")


def test_restore_restarts_a_halted_cpu(monkeypatch):
    c = FakeClient(cpu_run=False)
    assert _restore_with(monkeypatch, c) is True
    assert "cold_start" in c.names, c.names
    # Setpoints and the rootkit flag must be written BEFORE the restart: a restarted CPU
    # re-applies whatever DB3 holds on its first scan, so starting first would re-command
    # the attacker's overspeed on every single restore.
    assert c.names.index("cold_start") > max(
        i for i, n in enumerate(c.names) if n == "db_write")


def test_restore_does_not_restart_a_running_cpu(monkeypatch):
    """Stuxnet's restore must not needlessly cold-start a healthy controller."""
    c = FakeClient(cpu_run=True)
    assert _restore_with(monkeypatch, c) is True
    assert "cold_start" not in c.names, c.names
    assert "db_write" in c.names          # setpoints/rootkit still restored


def test_restore_does_not_claim_success_when_the_restart_fails(monkeypatch):
    """A swallowed failure would report 'restored' with the controller still halted -
    the same lying-status problem the CPU mirror exists to remove."""
    c = FakeClient(cpu_run=False, fail_start=True)
    with pytest.raises(RuntimeError):
        _restore_with(monkeypatch, c)
    assert "disconnect" in c.names        # connection still cleaned up


def test_aa26_scenario_can_be_restored():
    plan = wp.plan("s7_aa26_231a")
    assert plan["restore"] is wp.RESTORES["centrifuge"]
    assert plan["proto"] == "s7"
