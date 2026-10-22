"""
Siemens S7 Centrifuge Cascade Adapter

Emulates a Siemens S7-315-2 PLC controlling a 3-unit IR-1 centrifuge cascade,
matching the Natanz Fuel Enrichment Plant configuration targeted by Stuxnet (2010).

Data Block layout (matches real Stuxnet target):
  DB3  - Setpoints (Stuxnet writes here): 3x REAL speed (Hz) + BOOL cascade_enable
  DB4  - Measurements (HMI reads, rootkit spoofs): 3x [REAL speed, REAL vib, REAL temp, WORD status]
  DB890 - Stuxnet signature block: REAL speed_override + BOOL stuxnet_active (rootkit flag)

When DB890.stuxnet_active = True, DB4 is populated with fake normal values (1007 Hz)
instead of actual centrifuge state - this is the HMI rootkit / masking behavior.

Port: 102 (S7comm / ISO-on-TCP)
"""

import threading
import time
import struct
import ctypes
import logging
from typing import Dict, Any

import snap7

try:
    from snap7.server import Server
    try:
        from snap7.type import SrvArea
        srvAreaDB = SrvArea.DB
    except ImportError:
        from snap7.types import srvAreaDB
except ImportError:
    Server = snap7.Server
    srvAreaDB = snap7.SrvArea.DB

# snap7 tracks a CPU RUN/STOP state (plc_stop -> CPUState.STOP) but never acts on it,
# so every halt behaviour below is ours. Fall back to the wire value if the installed
# snap7 predates the enum.
try:
    from snap7.server import CPUState
    _CPU_STOP = int(CPUState.STOP)
except Exception:            # noqa: BLE001 - older snap7
    _CPU_STOP = 4

from server.plant import (
    CentrifugeCascade,
    CENTRIFUGE_NORMAL_HZ,
    CENTRIFUGE_OVERSPEED_LIMIT,
    CENTRIFUGE_UNDERSTEED_LIMIT,
    CENTRIFUGE_DESTROYED,
)


# DB sizes
_DB3_SIZE  = 16    # 3 x REAL (12 bytes) + 4 bytes BOOL padding
_DB4_SIZE  = 48    # 3 x 16 bytes (REAL + REAL + REAL + WORD + 2 pad)
_DB890_SIZE = 8    # REAL (4) + 4 bytes (BOOL at offset 4)

# DB4 per-centrifuge stride
_DB4_STRIDE = 16   # bytes per centrifuge


class S7CentrifugeAdapter:
    """
    S7 server adapter for the centrifuge cascade process.
    Does not use ProcessFacade - takes CentrifugeCascade directly.
    """

    DB_SETPOINTS   = 3
    DB_MEASUREMENTS = 4
    DB_STUXNET     = 890

    # DB3 byte 13: 1 = CPU RUN, 0 = CPU STOP. A diagnostic mirror, not process data -
    # python-snap7's client cannot ask for CPU state (get_cpu_state() is a stub that
    # always answers "S7CpuStatusRun") and this server implements no SZL 0x0424, so the
    # only way to make the state readable is to publish it as ordinary memory. Same
    # approach the TriStation adapter takes with program_running. Byte 13 is free
    # padding beside cascade_enable at 12, so no reader changes its read length.
    DB3_CPU_RUN = 13

    # What the outputs do when the CPU halts. A real S7-300 drives each output to its
    # configured substitute value, and for most modules that default is zero, so the
    # drives lose their speed reference and coast down. "hold" is the other real
    # option (some modules keep last state) - flip this if you model such a rack.
    STOP_OUTPUTS = "zero"

    def __init__(self, cascade: CentrifugeCascade, config: Dict[str, Any]):
        self.cascade = cascade
        self.host = config.get('host', '0.0.0.0')
        self.port = config.get('port', 102)
        self.rack = config.get('rack', 0)
        self.slot = config.get('slot', 1)

        self.server = None
        self.update_thread = None
        self.running = False

        self.logger = logging.getLogger('S7CentrifugeAdapter')

        # ctypes byte arrays (snap7 memory areas)
        self._db3   = (ctypes.c_ubyte * _DB3_SIZE)()
        self._db4   = (ctypes.c_ubyte * _DB4_SIZE)()
        self._db890 = (ctypes.c_ubyte * _DB890_SIZE)()

        # Initialise DB3 with normal operating setpoints
        for i in range(3):
            struct.pack_into('>f', self._db3, i * 4, CENTRIFUGE_NORMAL_HZ)
        self._db3[12] = 0x01  # cascade_enable = True

        # Track previous setpoints to detect Stuxnet writes (> 1 Hz change)
        self._prev_setpoints = [CENTRIFUGE_NORMAL_HZ] * 3

        self._db3[self.DB3_CPU_RUN] = 0x01     # CPU starts in RUN
        self._cpu_was_running = True

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    def initialize(self) -> bool:
        try:
            self.server = Server()
            self.server.register_area(srvAreaDB, self.DB_SETPOINTS,   self._db3)
            self.server.register_area(srvAreaDB, self.DB_MEASUREMENTS, self._db4)
            self.server.register_area(srvAreaDB, self.DB_STUXNET,     self._db890)
            self.logger.info("S7 centrifuge adapter initialised")
            self.logger.info("  PLC: Siemens SIMATIC S7-315-2 DP  Rack:0 Slot:1")
            self.logger.info("  DB3 (setpoints) | DB4 (measurements) | DB890 (Stuxnet block)")
            return True
        except Exception as e:
            self.logger.error(f"Init failed: {e}")
            return False

    def start(self) -> bool:
        try:
            try:
                self.server.start(tcp_port=self.port)
            except TypeError:
                self.server.start(tcpport=self.port)
            self.running = True
            self.update_thread = threading.Thread(
                target=self._update_loop, daemon=True, name="S7CentrifugeUpdate"
            )
            self.update_thread.start()
            self.logger.info(f"S7 centrifuge server on port {self.port}")
            return True
        except Exception as e:
            self.logger.error(f"Start failed: {e}")
            return False

    def stop(self):
        self.running = False
        if self.update_thread:
            self.update_thread.join(timeout=2)
        if self.server:
            self.server.stop()
        self.logger.info("S7 centrifuge server stopped")

    # ------------------------------------------------------------------
    # 10 Hz update loop
    # ------------------------------------------------------------------

    def _update_loop(self):
        while self.running:
            try:
                self._tick()
            except Exception as e:
                self.logger.error(f"Update loop error: {e}")
            time.sleep(0.1)

    def _tick(self):
        """One 10 Hz cycle. Split out from the loop so it can be driven directly by tests."""
        running = self._cpu_running()
        if self._cpu_was_running and not running:
            self._on_cpu_stop()
        elif running and not self._cpu_was_running:
            self.logger.warning("[S7] CPU back in RUN - program executing, control resumed")
        self._cpu_was_running = running

        if running:
            self._apply_setpoints()

        # Physics runs whether or not the CPU does - that is the point of a halt: the
        # plant keeps moving while nothing is controlling it. Same model as
        # SafetySystem.disabled in plant.py.
        self.cascade.update()

        if running:
            self._publish_measurements(mask=self._is_stuxnet_active())
        # else: process image frozen - DB4 keeps serving the last values the HMI saw,
        # which is what a halted CPU does, and what a stale-data alarm is there to catch.

        # CPU status is diagnostic, not part of the process image, so it stays current
        # even while DB4 is frozen.
        self._write_cpu_flag(running)

    # ------------------------------------------------------------------
    # CPU RUN / STOP
    # ------------------------------------------------------------------

    def _cpu_running(self) -> bool:
        """True while the CPU is in RUN.

        Polled, because snap7 emits no event for PLC control: set_events_callback
        stores a callable it never invokes and the event queue only ever receives the
        startup event. The 10 Hz loop is already here, so polling costs nothing.
        """
        state = getattr(self.server, "cpu_state", None)
        if state is None:
            return True                      # snap7 with no CPU model: never halt
        return int(state) != _CPU_STOP

    def _on_cpu_stop(self):
        """RUN -> STOP edge. Outputs go to their substitute values, so the drives lose
        their speed reference and coast down on friction."""
        self.logger.critical("[S7] CPU STOP - controller halted, process no longer controlled")
        if self.STOP_OUTPUTS == "zero":
            for i in range(3):
                self.cascade.execute_command(f"SpeedCmd{i + 1}", 0.0)
            # Forget the previous setpoints so a later RUN re-applies whatever DB3 then
            # holds, exactly as a restarted CPU would on its first scan.
            self._prev_setpoints = [0.0] * 3
            self.logger.critical("[S7] outputs to substitute values - drives coasting down")

    def _write_cpu_flag(self, running: bool):
        db3 = self._get_area(self.DB_SETPOINTS)
        db3[self.DB3_CPU_RUN] = 0x01 if running else 0x00

    def _apply_setpoints(self):
        """Poll DB3 for new speed setpoints and forward to cascade."""
        db3 = self._get_area(self.DB_SETPOINTS)
        for i in range(3):
            hz = struct.unpack_from('>f', db3, i * 4)[0]
            if abs(hz - self._prev_setpoints[i]) > 1.0:
                self._prev_setpoints[i] = hz
                self.cascade.execute_command(f'SpeedCmd{i + 1}', hz)
                if hz > CENTRIFUGE_OVERSPEED_LIMIT or hz < CENTRIFUGE_UNDERSTEED_LIMIT:
                    self.logger.warning(
                        f"[STUXNET] Centrifuge {i+1} setpoint = {hz:.1f} Hz "
                        f"({'OVERSPEED' if hz > CENTRIFUGE_OVERSPEED_LIMIT else 'UNDERSTEED'})"
                    )

    def _publish_measurements(self, mask: bool):
        """Write centrifuge state to DB4. If mask=True, report fake normal values."""
        db4 = self._get_area(self.DB_MEASUREMENTS)
        with self.cascade.lock:
            for i, c in enumerate(self.cascade.centrifuges):
                base = i * _DB4_STRIDE
                if mask and c.status != CENTRIFUGE_DESTROYED:
                    # Rootkit: serve 1007 Hz regardless of actual speed
                    struct.pack_into('>f', db4, base + 0,  CENTRIFUGE_NORMAL_HZ)
                    struct.pack_into('>f', db4, base + 4,  0.15)
                    struct.pack_into('>f', db4, base + 8,  65.0)
                    struct.pack_into('>H', db4, base + 12, 0)
                else:
                    struct.pack_into('>f', db4, base + 0,  c.speed_hz)
                    struct.pack_into('>f', db4, base + 4,  c.vibration_g)
                    struct.pack_into('>f', db4, base + 8,  c.bearing_temp_c)
                    struct.pack_into('>H', db4, base + 12, c.status)

    def _is_stuxnet_active(self) -> bool:
        """Read DB890 byte 4 bit 0 - set by Stuxnet to activate HMI masking."""
        db890 = self._get_area(self.DB_STUXNET)
        return bool(db890[4] & 0x01)

    # ------------------------------------------------------------------
    # Memory area access (snap7 2.x / 3.x compat)
    # ------------------------------------------------------------------

    def _get_area(self, db: int):
        """Return the live ctypes byte array for a registered DB."""
        if self.server and hasattr(self.server, 'memory_areas'):
            for key, area in self.server.memory_areas.items():
                if key[1] == db:
                    return area
        # Fallback to local ctypes arrays
        return {
            self.DB_SETPOINTS:    self._db3,
            self.DB_MEASUREMENTS: self._db4,
            self.DB_STUXNET:      self._db890,
        }[db]
