"""
mbus_lib.py - M-Bus EN 13757-3 over TCP
Proper Python library: frame building, parsing, and TCP master client.
Used by both the PLC-9 server (mbus_adapter.py) and the HMI client.
"""

import socket
import struct
import time
from typing import Optional, List, Dict, Any

# ─── Protocol constants ───────────────────────────────────────────────────
ACK         = 0xE5
LONG        = 0x68
SHORT       = 0x10
STOP        = 0x16
BROADCAST   = 0xFF

# C-field values
C_SND_NKE   = 0x40   # Init/reset  (master → slave, short frame)
C_SND_UD    = 0x53   # Write data  (master → slave, long frame)
C_REQ_UD2   = 0x5B   # Read class-2 data, FCB=0
C_REQ_UD2B  = 0x7B   # Read class-2 data, FCB=1
C_RSP_UD    = 0x08   # Response    (slave → master, long frame)

# CI-field
CI_RSP_VAR  = 0x72   # Variable data structure

# VIF codes (Value Information Field)
VIF_VOLUME  = 0x13   # Volume      (unit: L/10)
VIF_PRESSURE= 0x48   # Pressure    (unit: 10^-3 bar)
VIF_TEMP    = 0x59   # Temperature (unit: 10^-2 °C)
VIF_FLOW    = 0x3B   # Flow rate   (unit: L/h)


# ─── Frame building helpers ───────────────────────────────────────────────

def _cs(data: bytes) -> int:
    return sum(data) & 0xFF


def short_frame(c: int, addr: int) -> bytes:
    return bytes([SHORT, c, addr, _cs([c, addr]), STOP])


def encode_record(dif: int, vif: int, value: int, width: int) -> bytes:
    """Encode one variable data record (DIF + VIF + value)."""
    if width == 2:
        return bytes([dif, vif]) + struct.pack('<H', value & 0xFFFF)
    return bytes([dif, vif]) + struct.pack('<I', value & 0xFFFFFFFF)


def build_rsp_ud(address: int, records: bytes,
                 device_id: int = 12345678,
                 manufacturer: int = 0x4D41,
                 version: int = 0x01,
                 medium: int = 0x07) -> bytes:
    """
    Build a well-formed M-Bus RSP_UD long frame (CI=0x72 variable data).
    Fixed data header: 12 bytes per EN 13757-3 §6.2.
    """
    fh  = struct.pack('<I', device_id)           # Identification (4 B)
    fh += struct.pack('<H', manufacturer)         # Manufacturer   (2 B)
    fh += struct.pack('BB', version, medium)      # Gen, Medium    (2 B)
    fh += bytes([0x00, 0x00, 0x00, 0x00])         # Acc#,Status,Sig(4 B)
    # total: 12 bytes

    payload  = bytes([CI_RSP_VAR]) + fh + records
    frame_l  = len(payload) + 2                   # L = C + A + payload
    cs       = _cs(bytes([C_RSP_UD, address]) + payload)

    return (bytes([LONG, frame_l, frame_l, LONG]) +
            bytes([C_RSP_UD, address]) +
            payload +
            bytes([cs, STOP]))


# ─── Frame parsing ────────────────────────────────────────────────────────

class MBusRecord:
    def __init__(self, name: str, value: float, unit: str, dif: int, vif: int):
        self.name  = name
        self.value = value
        self.unit  = unit
        self.dif   = dif
        self.vif   = vif

    def __repr__(self):
        return f"MBusRecord({self.name}={self.value} {self.unit})"


class MBusFrame:
    """Parsed M-Bus frame from raw bytes."""

    def __init__(self, raw: bytes):
        self.raw     = raw
        self.valid   = False
        self.is_ack  = False
        self.records: List[MBusRecord] = []
        self._parse()

    def _parse(self):
        if not self.raw:
            return
        if self.raw[0] == ACK:
            self.valid = self.is_ack = True
            return
        if len(self.raw) < 9 or self.raw[0] != LONG:
            return
        frame_l = self.raw[1]
        if len(self.raw) < frame_l + 4:
            return
        # Byte layout: [0x68][L][L][0x68][C][A][CI][fh 12B][records...][CS][0x16]
        ci = self.raw[6]
        if ci != CI_RSP_VAR:
            self.valid = True
            return
        fh_end = 7 + 12           # fixed header ends here
        records_raw = self.raw[fh_end:-2]
        self.valid = True
        self._parse_records(records_raw)

    def _parse_records(self, data: bytes):
        idx = 0
        while idx + 2 <= len(data):
            dif = data[idx]; idx += 1
            if dif in (0x0F, 0x1F):
                break
            vif = data[idx]; idx += 1
            width = {0x02: 2, 0x04: 4, 0x0C: 4}.get(dif & 0x0F, 0)
            if width == 0 or idx + width > len(data):
                break
            raw_val = data[idx:idx + width]; idx += width

            if vif == VIF_TEMP:
                # Temperature is signed (can be negative)
                num = struct.unpack('<h', raw_val)[0]   # signed int16
                self.records.append(MBusRecord('Temperature', num / 100.0, '°C', dif, vif))
            elif width == 2:
                num = struct.unpack('<H', raw_val)[0]   # unsigned int16
                if vif == VIF_FLOW:
                    self.records.append(MBusRecord('Flow', float(num), 'L/h', dif, vif))
                else:
                    self.records.append(MBusRecord(f'VIF={vif:#04x}', float(num), '', dif, vif))
            else:
                num = struct.unpack('<I', raw_val)[0]   # unsigned int32
                if vif == VIF_VOLUME:
                    self.records.append(MBusRecord('Volume',   num / 10.0,   'L',   dif, vif))
                elif vif == VIF_PRESSURE:
                    self.records.append(MBusRecord('Pressure', num / 1000.0, 'bar', dif, vif))
                else:
                    self.records.append(MBusRecord(f'VIF={vif:#04x}', float(num), '', dif, vif))


# ─── TCP Master Client ────────────────────────────────────────────────────

class MBusClient:
    """M-Bus TCP master - connect, ping, read, broadcast reset."""

    def __init__(self, host: str, port: int = 5000, timeout: float = 3.0):
        self.host    = host
        self.port    = port
        self.timeout = timeout
        self._sock: Optional[socket.socket] = None

    # ── context manager ──────────────────────────────────────────────────
    def __enter__(self):
        self.connect(); return self

    def __exit__(self, *_):
        self.disconnect()

    # ── connection ───────────────────────────────────────────────────────
    def connect(self):
        self._sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self._sock.settimeout(self.timeout)
        self._sock.connect((self.host, self.port))

    def disconnect(self):
        if self._sock:
            try: self._sock.close()
            except Exception: pass
            self._sock = None

    # ── low-level I/O ────────────────────────────────────────────────────
    def _send(self, frame: bytes):
        self._sock.sendall(frame)

    def _recv_raw(self, drain_ms: float = 0.3) -> bytes:
        """Read all available bytes with a short drain window."""
        time.sleep(drain_ms)
        buf = b''
        self._sock.settimeout(0.4)
        try:
            while True:
                chunk = self._sock.recv(4096)
                if not chunk: break
                buf += chunk
        except socket.timeout:
            pass
        self._sock.settimeout(self.timeout)
        return buf

    # ── M-Bus operations ─────────────────────────────────────────────────
    def ping(self, address: int = 1) -> bool:
        """SND_NKE → expect ACK (0xE5)."""
        self._send(short_frame(C_SND_NKE, address))
        resp = self._recv_raw(drain_ms=0.15)
        return bool(resp) and resp[0] == ACK

    def read(self, address: int = 1) -> Optional[MBusFrame]:
        """REQ_UD2 → RSP_UD → parsed MBusFrame."""
        self._send(short_frame(C_REQ_UD2B, address))
        resp = self._recv_raw(drain_ms=0.3)
        if not resp:
            return None
        return MBusFrame(resp)

    def reset_broadcast(self):
        """SND_NKE to 0xFF - no ACK expected, drops connection server-side."""
        self._send(short_frame(C_SND_NKE, BROADCAST))
        time.sleep(0.1)
