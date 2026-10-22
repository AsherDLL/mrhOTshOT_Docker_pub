"""
TriStation Protocol Adapter for Safety Instrumented System (SIS)

Emulates a Schneider Electric Triconex SIS controller using the
TriStation UDP protocol on port 1502. This is the exact attack surface
that TRITON/TRISIS malware (2017) targeted to disable safety systems.

The adapter monitors the water treatment plant level and auto-trips
the SIS when the level exceeds the safety threshold (90%).

Protocol: TriStation UDP (port 1502)
Target: Schneider Electric Triconex controller
Malware: TRITON/TRISIS (2017)
"""

import threading
import time
import struct
import socket
import logging
from typing import Dict, Any, Optional

from server.protocol_adapter import (
    ProtocolAdapter, DataPoint, DataPointType,
    WaterTankProtocolMapper
)

try:
    import crcmod
    CRC_AVAILABLE = True
except ImportError:
    CRC_AVAILABLE = False

# TCM opcodes
TCM_CONNECT_REQUEST = 0x01
TCM_CONNECT_REPLY = 0x02
TCM_DISCONNECT_REQUEST = 0x06
TCM_COMMAND = 0x05

# TriStation function codes
TS_ATTACH_TRICON = 0x0D
TS_GET_CP_STATUS = 0x13
TS_HALT_PROGRAM = 0x15
TS_GET_CHASSIS_STATUS = 0x18
TS_START_DOWNLOAD = 0x2F
TS_ALLOCATE_PROGRAM = 0x37
TS_GO_DOWNLOAD_MODE = 0x50

# Response codes
TS_TRICON_ATTACHED = 0x6A
TS_CP_STATUS_RESP = 0x6C
TS_PROGRAM_RUNNING = 0x6D
TS_PROGRAM_HALTED = 0x6E
TS_CHASSIS_STATUS_RESP = 0x77
TS_COMMAND_REJECTED = 0x64


def _ts_checksum(subheader, data, data_length):
    s = data_length
    for b in subheader: s += b
    for b in data: s += b
    return s & 0xFFFF


def _build_ts_packet(funccode, seq, data, crc_func):
    if isinstance(data, str):
        data = data.encode('latin-1')
    data_length = len(data) + 10
    subheader_nochk = struct.pack('<BBBBHHH', 1, 1, funccode, seq, 0, 0, data_length)
    chk = _ts_checksum(subheader_nochk, data, data_length)
    header = struct.pack('<BBH', TCM_COMMAND, 0, data_length)
    subheader = struct.pack('<BBBBHHH', 1, 1, funccode, seq, 0, chk, data_length)
    packet = header + subheader + data
    if crc_func:
        packet += struct.pack('<H', crc_func(packet))
    return packet


class TriStationAdapter(ProtocolAdapter):
    """
    TriStation UDP protocol adapter for SIS.

    Monitors water level and auto-trips at threshold.
    Responds to TriStation protocol commands (TRITON attack surface).
    """

    SIS_THRESHOLD = 90.0  # Trip at this water level %

    def __init__(self, water_tank, config: Dict[str, Any]):
        super().__init__(water_tank, config)
        self.host = config.get('host', '0.0.0.0')
        self.port = config.get('port', 1502)
        self.sock = None
        self.server_thread = None
        self.monitor_thread = None
        self.crc_func = crcmod.mkCrcFun(0x18005, rev=True, initCrc=0x0000, xorOut=0) if CRC_AVAILABLE else None

        # SIS state
        self.sis_armed = True
        self.sis_tripped = False
        self.safety_disabled = False  # TRITON attack flag
        self.program_running = True
        self.seq = 0

        self._create_address_mapping()

    def _create_address_mapping(self):
        data_points = WaterTankProtocolMapper.create_data_points()
        for name, definition in data_points.items():
            dp = DataPoint(
                address={'type': 'tristation'},
                point_type=definition['type'], name=name,
                description=definition['description'],
                min_value=definition.get('min'),
                max_value=definition.get('max')
            )
            self.register_data_point(name, dp)
            callback = WaterTankProtocolMapper.get_command_callback(self.water_tank, name)
            if callback:
                self.register_command_callback(name, callback)

    def initialize(self) -> bool:
        try:
            self.sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            self.sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            self.sock.bind((self.host, self.port))
            self.sock.settimeout(1.0)
            self.logger.info(f"TriStation SIS initialized on {self.host}:{self.port} (UDP)")
            self.logger.info(f"  Safety threshold: {self.SIS_THRESHOLD}%")
            self.logger.info(f"  Emulating: Schneider Electric Triconex 3008")
            return True
        except Exception as e:
            self.logger.error(f"TriStation init failed: {e}")
            return False

    def start(self) -> bool:
        try:
            self.running = True
            self.server_thread = threading.Thread(
                target=self._udp_loop, daemon=True, name="TriStationThread")
            self.server_thread.start()
            self.monitor_thread = threading.Thread(
                target=self._safety_monitor, daemon=True, name="SISMonitorThread")
            self.monitor_thread.start()
            self.logger.info(f"TriStation SIS started on UDP port {self.port}")
            return True
        except Exception as e:
            self.logger.error(f"TriStation start failed: {e}")
            self.running = False
            return False

    def _udp_loop(self):
        while self.running:
            try:
                data, addr = self.sock.recvfrom(4096)
                if len(data) < 1:
                    continue
                response = self._process_packet(data, addr)
                if response:
                    self.sock.sendto(response, addr)
            except socket.timeout:
                continue
            except Exception as e:
                if self.running:
                    self.logger.error(f"TriStation error: {e}")

    def _process_packet(self, data, addr) -> Optional[bytes]:
        mcode = data[0]

        if mcode == TCM_CONNECT_REQUEST:
            self.logger.info(f"[TriStation] CONNECT from {addr[0]}:{addr[1]}")
            return b'\x02\x00\x00\x00\x01\xb8'

        elif mcode == TCM_DISCONNECT_REQUEST:
            self.logger.info(f"[TriStation] DISCONNECT from {addr[0]}")
            return b'\x03\x00\x00\x00\x00\x00'

        elif mcode == TCM_COMMAND and len(data) >= 14:
            funccode = data[6]
            seq = data[7]
            return self._handle_command(funccode, seq, addr)

        return None

    def _handle_command(self, funccode, seq, addr) -> Optional[bytes]:

        if funccode == TS_ATTACH_TRICON:
            self.logger.info(f"[TriStation] ATTACH from {addr[0]}")
            return _build_ts_packet(TS_TRICON_ATTACHED, seq,
                                     b'\x03\x00\x33\x0a\x04\x00', self.crc_func)

        elif funccode == TS_GET_CP_STATUS:
            self.logger.info(f"[TriStation] GET CP STATUS from {addr[0]}")
            # CP status: running state + project info
            state = 0x03 if self.program_running else 0x01
            cp_data = struct.pack('<BBHH', state, 0x01, 3008, 0x0100)
            cp_data += b'WATERTANK_SIS\x00' + b'\x00' * 18
            # Append SIS status flags for HMI monitoring (byte 14):
            # bit 0 = armed, bit 1 = tripped, bit 2 = disabled (safety neutralized)
            sis = self.water_tank
            try:
                # water_tank is a ProcessFacade - attributes live on .process (SafetySystem)
                proc = sis.process if hasattr(sis, 'process') else sis
                armed    = proc.armed if hasattr(proc, 'armed') else True
                tripped  = proc.tripped if hasattr(proc, 'tripped') else False
                disabled = proc.disabled if hasattr(proc, 'disabled') else False
                mon_val  = float(proc.monitored_value) if hasattr(proc, 'monitored_value') else 0.0
            except Exception:
                armed, tripped, disabled, mon_val = True, False, False, 0.0
            flags = (0x01 if armed else 0) | (0x02 if tripped else 0) | (0x04 if disabled else 0)
            cp_data += struct.pack('>Bf', flags, mon_val)
            return _build_ts_packet(TS_CP_STATUS_RESP, seq, cp_data, self.crc_func)

        elif funccode == TS_GET_CHASSIS_STATUS:
            self.logger.info(f"[TriStation] GET CHASSIS STATUS from {addr[0]}")
            chassis = struct.pack('<BBBBBBBBB', 1, 1, 1, 0, 1, 0, 0, 0, 0)
            return _build_ts_packet(TS_CHASSIS_STATUS_RESP, seq, chassis, self.crc_func)

        elif funccode == TS_HALT_PROGRAM:
            self.logger.critical(f"[TriStation] HALT PROGRAM from {addr[0]} - TRITON ATTACK!")
            self.program_running = False
            self.safety_disabled = True
            self.sis_tripped = False
            # Set disabled=True on the plant process - safety monitoring is now OFF
            sis_cb = self.command_callbacks.get('sis_trip_command')
            if sis_cb:
                sis_cb(True)
                self.logger.critical(f"[TriStation] TRITON payload active - SIS DISABLED")
            return _build_ts_packet(TS_PROGRAM_HALTED, seq, b'\x00', self.crc_func)

        elif funccode == TS_START_DOWNLOAD:
            self.logger.critical(f"[TriStation] START DOWNLOAD from {addr[0]} - TRITON injecting!")
            return _build_ts_packet(0x65, seq, b'\x00', self.crc_func)

        elif funccode == TS_ALLOCATE_PROGRAM:
            self.logger.critical(f"[TriStation] ALLOCATE PROGRAM from {addr[0]} - TRITON payload!")
            return _build_ts_packet(0x99, seq, b'\x00', self.crc_func)

        elif funccode == TS_GO_DOWNLOAD_MODE:
            self.logger.critical(f"[TriStation] GO DOWNLOAD MODE from {addr[0]}")
            return _build_ts_packet(0x65, seq, b'\x00', self.crc_func)

        else:
            self.logger.info(f"[TriStation] Unknown FC=0x{funccode:02x} from {addr[0]}")
            return _build_ts_packet(TS_COMMAND_REJECTED, seq, b'\x00', self.crc_func)

    def _safety_monitor(self):
        """Monitor water level and trigger SIS trip if threshold exceeded."""
        while self.running:
            try:
                if self.safety_disabled:
                    time.sleep(1)
                    continue

                level_cb = WaterTankProtocolMapper.get_measurement_callback(
                    self.water_tank, 'water_level')
                if level_cb:
                    level = float(level_cb())
                    if level >= self.SIS_THRESHOLD and not self.sis_tripped:
                        self.sis_tripped = True
                        self.logger.critical(
                            f"[SIS] TRIP! Level {level:.1f}% >= {self.SIS_THRESHOLD}%")
                        sis_cb = self.command_callbacks.get('sis_trip_command')
                        if sis_cb:
                            sis_cb(True)
                    elif level < self.SIS_THRESHOLD - 5 and self.sis_tripped:
                        self.sis_tripped = False
                        self.logger.info(f"[SIS] Reset. Level {level:.1f}% < threshold")
                        sis_cb = self.command_callbacks.get('sis_trip_command')
                        if sis_cb:
                            sis_cb(False)

                time.sleep(1)
            except Exception as e:
                self.logger.error(f"SIS monitor error: {e}")
                time.sleep(1)

    def stop(self):
        self.running = False
        if self.sock:
            self.sock.close()
        if self.server_thread:
            self.server_thread.join(timeout=2)
        if self.monitor_thread:
            self.monitor_thread.join(timeout=2)
        self.logger.info("TriStation SIS stopped")

    def update_data_point(self, name: str, value: Any):
        pass
