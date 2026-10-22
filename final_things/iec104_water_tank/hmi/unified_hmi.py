#!/usr/bin/env python3
"""
Unified Multi-Process Plant HMI

Overview grid shows all 5 industrial processes. Click any process to
open a detail window with controls. Each control action sends commands
via the CORRECT industrial protocol for that process - generating real
network traffic visible in Wireshark.

Process -> Protocol mapping:
  Water Treatment  -> IEC-104 (read) + Modbus TCP (commands)
  Power Substation -> IEC 61850 MMS (read + commands)
  Gas Pipeline     -> OPC-UA (read + commands)
  Building HVAC    -> BACnet/IP (read + commands)
  Centrifuge Cascade -> Siemens S7 (read + commands)
"""

import tkinter as tk
from tkinter import ttk
import threading
import time
import socket
import struct
import json
import math
import sys
import os
import argparse
import logging
from logging.handlers import RotatingFileHandler

# Windows: use SelectorEventLoop to avoid ProactorEventLoop cleanup errors with asyncua
if sys.platform == 'win32':
    import asyncio
    asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())

sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from common.config import *

# ---------------------------------------------------------------------------
# Logging - rotating file + console, 10 MB cap, 5 backups
# ---------------------------------------------------------------------------
_LOG_DIR  = os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', 'logs', 'hmi')
os.makedirs(_LOG_DIR, exist_ok=True)
_LOG_FILE     = os.path.join(_LOG_DIR, 'hmi.log')
_BTN_LOG_FILE = os.path.join(_LOG_DIR, 'hmi_button_actions.log')

_log_handler = RotatingFileHandler(_LOG_FILE, maxBytes=10*1024*1024, backupCount=5, encoding='utf-8')
_log_handler.setFormatter(logging.Formatter(
    '%(asctime)s %(levelname)-8s %(name)s %(message)s',
    datefmt='%Y-%m-%d %H:%M:%S',
))
_console_handler = logging.StreamHandler(sys.stdout)
_console_handler.setFormatter(logging.Formatter('%(asctime)s [%(name)s] %(message)s', datefmt='%H:%M:%S'))

logging.basicConfig(level=logging.INFO, handlers=[_log_handler, _console_handler])
log = logging.getLogger('HMI')

# Dedicated button-action log - plain text, one entry per click
# Format: TIMESTAMP | STATUS | BUTTON | PROTOCOL | SENT | RESPONSE | ERROR | ELAPSED
_btn_handler = RotatingFileHandler(_BTN_LOG_FILE, maxBytes=5*1024*1024, backupCount=10, encoding='utf-8')
_btn_handler.setFormatter(logging.Formatter('%(message)s'))
_btn_log = logging.getLogger('HMI.buttons')
_btn_log.addHandler(_btn_handler)
_btn_log.propagate = False   # don't duplicate into hmi.log

# Silence chatty third-party loggers that spam every poll cycle
for _noisy in ('asyncua', 'snap7', 'opcua', 'pymodbus'):
    logging.getLogger(_noisy).setLevel(logging.WARNING)

PROTOCOLS = [
    ('IEC-104',         2404,  'tcp', 'Water Treatment'),
    ('Modbus TCP',      502,   'tcp', 'Heating District'),
    ('IEC 61850',       8102,  'tcp', 'Power Substation'),
    ('GOOSE',           61850, 'tcp', 'Power Substation'),
    ('OPC-UA',          4840,  'tcp', 'Gas Pipeline'),
    ('OMRON FINS',      9600,  'udp', 'Gas Pipeline'),
    ('Siemens S7',      102,   'tcp', 'Centrifuge Cascade'),
    ('BACnet/IP',       47808, 'udp', 'Building HVAC'),
    ('MELSEC MC',       5007,  'tcp', 'Gas Pipeline'),
    ('ABB Modbus',      5020,  'tcp', 'Boiler House'),
    ('Modbus (Heat)',   502,   'tcp', 'Heating District'),
    ('DNP3',            20000, 'tcp', 'Water Utility DNP3'),
    ('M-Bus',           5000,  'tcp', 'Sensor Network'),
    ('TriStation',      1502,  'udp', 'Safety System'),
]

BG = '#0a0e14'; PANEL = '#111820'; ACCENT = '#00e5ff'
GREEN = '#00e676'; RED = '#ff1744'; AMBER = '#ffab00'
TEXT = '#cfd8dc'; DIM = '#37474f'


def probe(host, port, proto, timeout=0.6):
    try:
        if proto == 'udp':
            s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            s.settimeout(timeout)
            s.sendto(b'\x00', (host, port))
            try: s.recvfrom(64)
            except socket.timeout: pass
            s.close(); return True
        else:
            s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            s.settimeout(timeout)
            ok = s.connect_ex((host, port)) == 0
            s.close(); return ok
    except Exception:
        return False


# =========================================================================
# PROTOCOL-SPECIFIC COMMAND SENDERS
# Each generates real network traffic on the correct protocol
# =========================================================================

def send_iec104(host, ioa, value, port=2404):
    """Send IEC-104 single command (C_SC_NA_1). Traffic on TCP port 2404."""
    import c104
    client = c104.Client()
    conn = client.add_connection(ip=host, port=port, init=c104.Init.ALL)
    station = conn.add_station(common_address=1)
    pt = station.add_point(io_address=ioa, type=c104.Type.C_SC_NA_1)
    client.start(); time.sleep(1.5)
    pt.value = bool(value)
    pt.transmit(cause=c104.Cot.ACTIVATION)
    time.sleep(0.5); client.stop()
    return f"C_SC_NA_1 IOA={ioa} val={'ON' if value else 'OFF'} COT=ACTIVATION -> {host}:{port}"


def send_modbus(host, coil, value, port=502, slave_id=1):
    """Send Modbus TCP write-single-coil (FC05). Traffic on TCP port 502."""
    _plog = logging.getLogger('HMI.proto.modbus')
    s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    s.settimeout(3)
    s.connect((host, port))
    coil_value = 0xFF00 if value else 0x0000
    pdu = struct.pack('>BHH', 0x05, coil, coil_value)
    mbap = struct.pack('>HHHB', 1, 0, len(pdu) + 1, slave_id)
    s.sendall(mbap + pdu)
    resp = s.recv(256)
    s.close()
    resp_fc = resp[7] if len(resp) > 7 else 0
    if resp_fc == 0x85:
        error_code = resp[8] if len(resp) > 8 else 0
        _plog.error("FC05 coil=%d host=%s:%d slave=%d  ERROR fc=%s code=%d", coil, host, port, slave_id, hex(resp_fc), error_code)
        raise RuntimeError(f"Modbus error FC={hex(resp_fc)} code={error_code}")
    _plog.info("FC05  host=%s:%d slave=%d  coil=%d  val=%s  resp=%dB", host, port, slave_id, coil, 'ON' if value else 'OFF', len(resp))
    return f"FC05 coil={coil} {'ON' if value else 'OFF'} slave={slave_id} -> {host}:{port}  resp={resp.hex()}"


def send_tristation_halt(host, port=1502):
    """Send TriStation HALT PROGRAM (TRITON attack). Traffic on UDP port 1502."""
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    s.settimeout(3)
    # TCM CONNECT REQUEST first
    s.sendto(b'\x01\x00\x00\x00\x00\x00', (host, port))
    try: s.recvfrom(256)
    except socket.timeout: pass
    # TCM COMMAND with TS HALT PROGRAM (funccode=0x15)
    # TCM header: mcode=0x05, tricon_id=0, data_len=10
    # TS subheader: path=0, cid=0, fc=0x15, seq=1, unk=0, chk=0, dlen=10
    subheader = struct.pack('<BBBBHHH', 0, 0, 0x15, 1, 0, 0, 10)
    header = struct.pack('<BBH', 0x05, 0, 10)
    packet = header + subheader
    s.sendto(packet, (host, port))
    got_resp = False
    try:
        resp, _ = s.recvfrom(256)
        got_resp = True
        logging.getLogger("HMI.proto.tristation").info("HALT PROGRAM  host=%s:%d  resp=%dB", host, port, len(resp))
    except socket.timeout:
        logging.getLogger("HMI.proto.tristation").info("HALT PROGRAM  host=%s:%d  no-response", host, port)
    s.close()
    return f"TriStation HALT_PROGRAM fc=0x15 UDP -> {host}:{port}  resp={'ACK' if got_resp else 'no-resp'}"


def send_modbus_register(host, register, value, port=502):
    """Send Modbus TCP write-single-register (FC06). Traffic on TCP port 502."""
    s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    s.settimeout(3); s.connect((host, port))
    scaled = int(max(0, min(65535, value / 100.0 * 65535)))
    pdu = struct.pack('>BHH', 0x06, register, scaled)
    mbap = struct.pack('>HHHB', 1, 0, len(pdu) + 1, 1)
    s.sendall(mbap + pdu)
    resp = s.recv(256); s.close()
    return f"FC06 reg={register} scaled={scaled}({value}) -> {host}:{port}  resp={resp.hex()}"


def send_iec61850(host, reference, value, port=8102):
    """Send IEC 61850 MMS write. Traffic on TCP port 8102."""
    s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    s.settimeout(3); s.connect((host, port))
    req = json.dumps({'type': 'write', 'reference': reference, 'value': value})
    s.sendall(req.encode() + b'\n')
    time.sleep(0.3)
    resp = s.recv(4096); s.close()
    return json.loads(resp.decode('utf-8', errors='replace').strip())


def send_iec61850_goose_trip(host, port=8102):
    """Send GOOSE trip command via MMS. Traffic on TCP port 8102."""
    s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    s.settimeout(3); s.connect((host, port))
    req = json.dumps({'type': 'goose-trip'})
    s.sendall(req.encode() + b'\n')
    time.sleep(0.3)
    resp = s.recv(4096); s.close()
    return json.loads(resp.decode('utf-8', errors='replace').strip())


def send_opcua(host, node_path, value, port=4840):
    """Send OPC-UA write via asyncua. Traffic on TCP port 4840."""
    from asyncua import Client as OPCUAClient, ua
    import asyncio
    result = {}
    async def _write():
        url = f"opc.tcp://{host}:{port}/freeopcua/server/"
        client = OPCUAClient(url=url)
        await client.connect()
        ns_array = await client.get_namespace_array()
        ns = None
        for uri in ['http://gaspipeline.local', 'http://watertank.local']:
            if uri in ns_array:
                ns = ns_array.index(uri)
                break
        if ns is None:
            ns = 2
        for obj_name in (['GasPipeline', 'WaterTank'] if 'http://gaspipeline.local' in ns_array else ['WaterTank']):
            try:
                parts = [f"{ns}:{obj_name}"] + [f"{ns}:{seg}" for seg in node_path.split("/")]
                node = await client.nodes.objects.get_child(parts)
                break
            except Exception:
                continue
        else:
            raise RuntimeError(f"OPC-UA node not found: tried GasPipeline/WaterTank under ns={ns}")
        if isinstance(value, bool):
            await node.set_value(ua.Variant(value, ua.VariantType.Boolean))
        else:
            v = struct.unpack('f', struct.pack('f', float(value)))[0]
            await node.set_value(ua.Variant(v, ua.VariantType.Float))
        result['node'] = str(node.nodeid)
        await client.disconnect()
    asyncio.run(_write())
    return f"OPC-UA Write {node_path}={value} node={result.get('node','?')} -> {host}:{port}"


def send_bacnet(host, obj_type, instance, value, port=47808):
    """Send BACnet WriteProperty. Traffic on UDP port 47808."""
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    s.settimeout(2)
    obj_id = (obj_type << 22) | (instance & 0x3FFFFF)
    # Confirmed WriteProperty
    apdu = struct.pack('BBBB', 0x00, 0x04, 0x01, 0x0F)  # ConfirmedReq, MaxSegs=0/MaxApdu=1024, InvokeID=1, WriteProperty
    apdu += struct.pack('B', 0x0C) + struct.pack('>I', obj_id)  # ObjectID
    apdu += struct.pack('BB', 0x19, 85)  # PropertyID = PresentValue
    apdu += struct.pack('B', 0x3E)  # Opening tag
    if isinstance(value, bool):
        apdu += struct.pack('BB', 0x91, 0x01 if value else 0x00)
    else:
        apdu += struct.pack('B', 0x44) + struct.pack('>f', float(value))
    apdu += struct.pack('B', 0x3F)  # Closing tag
    npdu = struct.pack('BB', 0x01, 0x00)
    bvlc = struct.pack('>BBH', 0x81, 0x0A, 4 + len(npdu) + len(apdu))
    s.sendto(bvlc + npdu + apdu, (host, port))
    got = False
    try: s.recvfrom(4096); got = True
    except socket.timeout: pass
    s.close()
    return f"BACnet WriteProperty obj={obj_type}/{instance} val={value} -> {host}:{port}  resp={'ACK' if got else 'no-resp'}"


def send_s7(host, db, offset, value, port=102):
    """Send S7 write via snap7. Traffic on TCP port 102."""
    import snap7
    try:
        from snap7.types import Areas
        area = Areas.DB
    except ImportError:
        area = 0x84
    client = snap7.client.Client()
    client.connect(host, 0, 1, port)
    if isinstance(value, bool):
        data = bytearray(1)
        data[0] = 0x01 if value else 0x00
        client.write_area(area, db, offset, data)
        detail = f"BOOL DB{db}.DBX{offset} = {'TRUE' if value else 'FALSE'}"
    else:
        data = bytearray(4)
        struct.pack_into('>f', data, 0, float(value))
        client.write_area(area, db, offset, data)
        detail = f"REAL DB{db}.DBD{offset} = {float(value):.3f}  bytes={data.hex()}"
    client.disconnect()
    return f"S7 Write {detail} -> {host}:{port}"


def send_enip(host, tag, value, port=44818):
    """Send EtherNet/IP CIP WriteTag. Traffic on TCP port 44818."""
    s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    s.settimeout(3); s.connect((host, port))
    # RegisterSession
    hdr = struct.pack('<HHII', 0x0065, 4, 0, 0) + b'\x00'*8 + struct.pack('<I', 0)
    hdr += struct.pack('<HH', 1, 0)
    s.sendall(hdr)
    resp = s.recv(4096)
    session = struct.unpack_from('<I', resp, 4)[0]
    # CIP WriteTag
    tag_bytes = tag.encode('utf-8')
    cip_path = bytes([0x91, len(tag_bytes)]) + tag_bytes
    if len(cip_path) % 2: cip_path += b'\x00'
    if isinstance(value, bool):
        cip_req = bytes([0x4D, len(cip_path)//2]) + cip_path
        cip_req += struct.pack('<HH', 0x00C1, 1) + struct.pack('B', 1 if value else 0)
    else:
        cip_req = bytes([0x4D, len(cip_path)//2]) + cip_path
        cip_req += struct.pack('<HH', 0x00CA, 1) + struct.pack('<f', float(value))
    cpf = struct.pack('<H', 2) + struct.pack('<HH', 0, 0) + struct.pack('<HH', 0x00B2, len(cip_req)) + cip_req
    rr = struct.pack('<IH', 0, 10) + cpf
    hdr2 = struct.pack('<HHII', 0x006F, len(rr), session, 0) + b'\x00'*8 + struct.pack('<I', 0)
    s.sendall(hdr2 + rr)
    s.recv(4096); s.close()
    logging.getLogger("HMI.proto.enip").info("WriteTag  host=%s:%d  tag=%s  val=%s", host, port, tag, value)
    return f"EtherNet/IP CIP WriteTag tag={tag} val={value} -> {host}:{port}"


def send_melsec(host, y_addr, value, port=5007):
    """Send MELSEC MC batch write to Y output. Traffic on TCP port 5007."""
    s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    s.settimeout(3); s.connect((host, port))
    timer = struct.pack('<H', 10)
    command = struct.pack('<H', 0x1401)
    sub_cmd = struct.pack('<H', 0x0001)  # bit access
    head_dev = struct.pack('<I', y_addr)[:3] + bytes([0x9D])  # Y output device code
    num_pts = struct.pack('<H', 1)
    val_byte = bytes([0x10 if value else 0x00])
    cmd_data = timer + command + sub_cmd + head_dev + num_pts + val_byte
    frame = struct.pack('<H', 0x5000) + bytes([0x00, 0xFF]) + struct.pack('<H', 0x03FF)
    frame += bytes([0x00]) + struct.pack('<H', len(cmd_data)) + cmd_data
    s.sendall(frame)
    resp = s.recv(256); s.close()
    end_code = struct.unpack_from('<H', resp, 9)[0] if len(resp) >= 11 else -1
    logging.getLogger("HMI.proto.melsec").info("Y%d=%s  end=0x%04X  host=%s:%d", y_addr, "ON" if value else "OFF", end_code, host, port)
    return f"MELSEC MC BatchWrite Y{y_addr}={'ON' if value else 'OFF'} end=0x{end_code:04X} -> {host}:{port}"


def send_fins(host, cio_bit, value, port=9600):
    """Send OMRON FINS CIO memory write. Traffic on UDP port 9600."""
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    s.settimeout(2)
    header = bytes([0x80, 0x00, 0x02, 0x00, 0x00, 0x00, 0x00, 0xFE, 0x00, 0x00])
    cmd = struct.pack('>H', 0x0102)  # Memory Write
    area = bytes([0xB0])  # CIO area
    addr = struct.pack('>H', 0)  # CIO word 0
    bit_pos = bytes([0x00])
    count = struct.pack('>H', 1)
    # Set/clear bit in CIO word 0
    new_val = (1 << cio_bit) if value else 0
    data = struct.pack('>H', new_val)
    pkt = header + cmd + area + addr + bit_pos + count + data
    s.sendto(pkt, (host, port))
    try: s.recvfrom(256)
    except socket.timeout: pass
    s.close()
    logging.getLogger("HMI.proto.fins").info("CIO bit %d=%s  host=%s:%d", cio_bit, "ON" if value else "OFF", host, port)
    return f"OMRON FINS MemWrite CIO bit={cio_bit} {'ON' if value else 'OFF'} pkt={pkt.hex()} -> {host}:{port}"


def send_dnp3(host, index, value, port=20000):
    """Send DNP3 Direct Operate CROB. Traffic on TCP port 20000."""
    s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    s.settimeout(3); s.connect((host, port))
    ctrl_code = 0x03 if value else 0x04  # LATCH_ON=0x03 / LATCH_OFF=0x04
    # App layer: DIRECT_OPERATE (0x05), Group 12 Var 1 CROB
    app = struct.pack('BB', 0xC5, 0x05)   # FIN|FIR|seq=0 | DIRECT_OPERATE=0x05
    app += struct.pack('BB', 12, 1)        # group=12, variation=1 (CROB)
    app += struct.pack('B', 0x01)          # qualifier=0x01 (8-bit count + 8-bit index)
    app += struct.pack('BB', 1, index)     # count=1, then object index
    app += struct.pack('<BIBI', ctrl_code, 1000, 0, 0)  # CROB body (ctrl,on,off,status)
    frame = _dnp3_build_frame(dst=1, src=2, app_bytes=app)
    s.sendall(frame)
    got = False
    try: s.recv(256); got = True
    except socket.timeout: pass
    s.close()
    logging.getLogger("HMI.proto.dnp3").info("DO  host=%s:%d  index=%d  val=%s", host, port, index, "ON" if value else "OFF")
    return f"DNP3 DirectOperate CROB index={index} {'LATCH_ON' if value else 'LATCH_OFF'} -> {host}:{port}  resp={'ACK' if got else 'no-resp'}"


# =========================================================================
# READ FUNCTIONS
# =========================================================================

def read_modbus_water(host, port=502):
    """Read water treatment data via Modbus TCP. Fast (~50ms per call)."""
    result = {}
    # Read Input Registers (FC04): level, pressure, temp (addresses 0,1,2)
    s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    s.settimeout(2)
    s.connect((host, port))
    pdu = struct.pack('>BHH', 0x04, 0, 3)  # FC04 Read Input Registers
    mbap = struct.pack('>HHHB', 1, 0, len(pdu) + 1, 1)
    s.sendall(mbap + pdu)
    resp = s.recv(256)
    s.close()
    if len(resp) >= 15:
        regs = [struct.unpack('>H', resp[9+i*2:9+i*2+2])[0] for i in range(3)]
        result['level'] = regs[0] / 65535 * 100
        result['pressure'] = regs[1] / 65535 * 15
        result['temperature'] = regs[2] / 65535 * 100

    # Read Discrete Inputs (FC02): valve/pump/auto/alarms (addresses 0-8)
    s2 = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    s2.settimeout(2)
    s2.connect((host, port))
    pdu2 = struct.pack('>BHH', 0x02, 0, 9)  # FC02 Read Discrete Inputs
    mbap2 = struct.pack('>HHHB', 2, 0, len(pdu2) + 1, 1)
    s2.sendall(mbap2 + pdu2)
    resp2 = s2.recv(256)
    s2.close()
    if len(resp2) >= 11:
        byte_count = resp2[8]
        bits = []
        for b in resp2[9:9+byte_count]:
            for bit in range(8):
                bits.append(bool(b & (1 << bit)))
        names = ['inlet', 'outlet', 'pump', 'auto_mode',
                 'overflow', 'low_level', 'high_pressure', 'exploded', 'sis_tripped']
        for i, name in enumerate(names):
            if i < len(bits):
                result[name] = bits[i]

    return result


def read_iec104_water(host, port=2404):
    """Read water treatment data via IEC-104 (primary protocol on PLC-1 :2404)."""
    result = {}
    try:
        import c104
        client = c104.Client()
        conn = client.add_connection(ip=host, port=port, init=c104.Init.ALL)
        station = conn.add_station(common_address=1)
        # Measurements (M_ME_NB_1 scaled): level=100, pressure=101, temperature=102
        for ioa, t in [(100, c104.Type.M_ME_NB_1), (101, c104.Type.M_ME_NB_1),
                       (102, c104.Type.M_ME_NB_1)]:
            try: station.add_point(io_address=ioa, type=t)
            except Exception: pass
        # Status (M_SP_NA_1): inlet=200, outlet=201, pump=202, auto=203,
        #                      overflow=204, low=205, high_press=206, exploded=207, sis=208
        for ioa in range(200, 209):
            try: station.add_point(io_address=ioa, type=c104.Type.M_SP_NA_1)
            except Exception: pass
        client.start(); time.sleep(3.0)   # 12 data points need ~3s for GI response
        for pt in station.points:
            try:
                val = pt.value
                if   pt.io_address == 100: result['level']        = float(val) / 32767 * 100
                elif pt.io_address == 101: result['pressure']     = float(val) / 32767 * 15
                elif pt.io_address == 102: result['temperature']  = float(val) / 32767 * 100
                elif pt.io_address == 200: result['inlet']        = bool(val)
                elif pt.io_address == 201: result['outlet']       = bool(val)
                elif pt.io_address == 202: result['pump']         = bool(val)
                elif pt.io_address == 203: result['auto_mode']    = bool(val)
                elif pt.io_address == 204: result['overflow']     = bool(val)
                elif pt.io_address == 205: result['low_level']    = bool(val)
                elif pt.io_address == 206: result['high_pressure']= bool(val)
                elif pt.io_address == 207: result['exploded']     = bool(val)
                elif pt.io_address == 208: result['sis_tripped']  = bool(val)
            except Exception: pass
        client.stop()
    except Exception:
        pass
    return result


def read_opcua_gas(host, port=4840):
    """Read gas pipeline data via OPC-UA. Traffic on TCP port 4840."""
    from asyncua import Client as OPCUAClient
    import asyncio, sys
    # Windows ProactorEventLoop + asyncua causes TimeoutError in threads.
    # Force SelectorEventLoop on Windows for compatibility.
    if sys.platform == 'win32':
        asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())
    async def _read():
        url = f"opc.tcp://{host}:{port}/freeopcua/server/"
        client = OPCUAClient(url=url)
        await client.connect()
        ns_array = await client.get_namespace_array()
        ns = None
        for uri in ['http://gaspipeline.local', 'http://watertank.local']:
            if uri in ns_array:
                ns = ns_array.index(uri)
                break
        if ns is None:
            ns = 2
        for obj_name in (['GasPipeline', 'WaterTank'] if 'http://gaspipeline.local' in ns_array else ['WaterTank']):
            try:
                wt = await client.nodes.objects.get_child([f"{ns}:{obj_name}"])
                break
            except Exception:
                continue
        else:
            raise RuntimeError(f"OPC-UA root object not found: tried GasPipeline/WaterTank under ns={ns}")
        result = {}
        # Measurements
        meas = await wt.get_child([f"{ns}:Measurements"])
        for node in await meas.get_children():
            name = (await node.read_browse_name()).Name
            val = await node.get_value()
            if name == 'WaterLevel': result['pressure'] = float(val)       # outlet pressure mapped
            elif name == 'Pressure': result['inlet_pressure'] = float(val)  # inlet pressure
            elif name == 'Temperature': result['temperature'] = float(val)
        # Status
        status = await wt.get_child([f"{ns}:Status"])
        for node in await status.get_children():
            name = (await node.read_browse_name()).Name
            val = await node.get_value()
            if name == 'InletValveStatus': result['upstream'] = bool(val)
            elif name == 'OutletValveStatus': result['downstream'] = bool(val)
            elif name == 'PumpStatus': result['compressor'] = bool(val)
            elif name == 'AutoModeStatus': result['auto_mode'] = bool(val)
            elif name == 'TankExploded': result['rupture'] = bool(val)
            elif name == 'SisTripped': result['esd'] = bool(val)
        await client.disconnect()
        return result
    return asyncio.run(_read())


def read_s7_centrifuge(host, port=102):
    """Read centrifuge cascade data via S7comm. Traffic on TCP port 102."""
    import snap7
    try:
        from snap7.types import Areas
        area = Areas.DB
    except ImportError:
        area = 0x84
    client = snap7.client.Client()
    client.connect(host, 0, 1, port)
    result = {}
    # DB4: 3 centrifuges × 16 bytes (REAL speed, REAL vib, REAL temp, WORD status)
    db4 = client.read_area(area, 4, 0, 48)
    centrifuges = []
    for i in range(3):
        base = i * 16
        speed  = struct.unpack_from('>f', db4, base + 0)[0]
        vib    = struct.unpack_from('>f', db4, base + 4)[0]
        temp   = struct.unpack_from('>f', db4, base + 8)[0]
        status = struct.unpack_from('>H', db4, base + 12)[0]
        centrifuges.append({'speed': speed, 'vib': vib, 'temp': temp, 'status': status})
    result['centrifuges'] = centrifuges
    # DB890: stuxnet_active flag (byte 4 bit 0)
    db890 = client.read_area(area, 890, 0, 8)
    result['rootkit_active'] = bool(db890[4] & 0x01)
    client.disconnect()
    return result


def read_s7_mfg(host, port=102):
    """Read manufacturing data via Siemens S7. Traffic on TCP port 102."""
    import snap7
    try:
        from snap7.types import Areas
        area = Areas.DB
    except ImportError:
        area = 0x84
    client = snap7.client.Client()
    client.connect(host, 0, 1, port)
    result = {}
    # DB1: Measurements (REAL = 4 bytes each at offsets 0, 4, 8)
    db1 = client.read_area(area, 1, 0, 12)
    result['hopper'] = struct.unpack_from('>f', db1, 0)[0]
    result['hydraulic'] = struct.unpack_from('>f', db1, 4)[0]
    result['motor_temp'] = struct.unpack_from('>f', db1, 8)[0]
    # DB2: Status (BOOL bits in first byte)
    db2 = client.read_area(area, 2, 0, 2)
    bits = db2[0]
    result['conveyor'] = bool(bits & 0x01)      # bit 0 = inlet_valve (conveyor)
    result['auto_mode'] = bool(bits & 0x08)      # bit 3 = auto_mode
    result['e_stop'] = bool(bits & 0x10)          # bit 4 = sis_tripped -> e_stop
    client.disconnect()
    return result


def _parse_bacnet_response(data: bytes, is_float: bool):
    """
    Parse a BACnet Complex-ACK ReadProperty response.

    Standard format (bacpypes3 / any compliant stack):
      BVLC(4) + NPDU(2+) + APDU Complex-ACK:
        30 invoke-id 0C          -- Complex-ACK, ReadProperty
        0C obj-id(4)             -- context 0: object identifier
        19 prop-id               -- context 1: property identifier
        3E                       -- context 3 opening tag
        <app-tagged value>       -- 44+float(4) or 91+bool(1) or 21+uint(1)
        3F                       -- context 3 closing tag

    Falls back to legacy naive parse if opening tag not found.
    """
    if not data or len(data) < 8:
        return None
    try:
        # Find opening tag 0x3E in the APDU payload
        idx = data.find(b'\x3E')
        if idx != -1 and idx + 2 < len(data):
            tag  = data[idx + 1]
            rest = data[idx + 2:]
            if tag == 0x44 and len(rest) >= 4:       # Real (float)
                return struct.unpack('>f', rest[:4])[0]
            elif tag == 0x91 and len(rest) >= 1:      # Boolean
                return bool(rest[0])
            elif tag == 0x21 and len(rest) >= 1:      # Unsigned8
                return float(rest[0])
            elif tag == 0x22 and len(rest) >= 2:      # Unsigned16
                return float(struct.unpack('>H', rest[:2])[0])
        # Legacy fallback for raw-socket servers
        if is_float and len(data) >= 4:
            return struct.unpack('>f', data[-4:])[0]
        elif not is_float and len(data) >= 1:
            return bool(data[-1])
    except Exception:
        pass
    return None


def read_bacnet_hvac(host, port=47808):
    """Read HVAC data via BACnet/IP ReadProperty. Traffic on UDP port 47808."""
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    s.settimeout(1.5)
    result = {}

    def _read_obj(obj_type, instance):
        obj_id = (obj_type << 22) | (instance & 0x3FFFFF)
        apdu  = struct.pack('BBBB', 0x00, 0x04, 0x01, 0x0C)  # ConfirmedReq, MaxSegs=0/MaxApdu=1024, InvokeID=1, ReadProperty
        apdu += struct.pack('B', 0x0C) + struct.pack('>I', obj_id)
        apdu += struct.pack('BB', 0x19, 85)              # PresentValue
        npdu  = struct.pack('BB', 0x01, 0x00)
        bvlc  = struct.pack('>BBH', 0x81, 0x0A, 4 + len(npdu) + len(apdu))
        s.sendto(bvlc + npdu + apdu, (host, port))
        try:
            data, _ = s.recvfrom(4096)
            return data
        except socket.timeout:
            return None

    # Analog Inputs: AI[0]=water_level, AI[1]=pressure, AI[2]=temperature
    for idx, key in [(0, 'zone_temp'), (1, 'duct_pressure'), (2, 'supply_air')]:
        resp = _read_obj(0, idx)
        val  = _parse_bacnet_response(resp, is_float=True)
        if val is not None:
            result[key] = val

    # Status booleans are also AnalogInput (as 0.0/1.0) - AI[3..6]
    for idx, key in [(3, 'heating'), (4, 'cooling'), (5, 'fan'), (6, 'auto_mode')]:
        resp = _read_obj(0, idx)
        val  = _parse_bacnet_response(resp, is_float=True)
        if val is not None:
            result[key] = val > 0.5

    s.close()
    return result


def read_iec61850(host, port=8102):
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        s.settimeout(2); s.connect((host, port))
        s.sendall(json.dumps({'type': 'read', 'reference': 'all'}).encode() + b'\n')
        time.sleep(0.3)
        resp = json.loads(s.recv(8192).decode('utf-8', errors='replace').strip())
        s.close()
        if resp.get('type') == 'read-response' and resp.get('data'):
            r = {}
            for ref, info in resp['data'].items():
                val = info.get('value', info) if isinstance(info, dict) else info
                if 'phsA' in ref: r['voltage'] = float(val)
                elif 'phsB' in ref: r['current'] = float(val)
                elif 'phsC' in ref: r['xfmr_temp'] = float(val)
                elif 'Ind1' in ref: r['breaker1'] = bool(val)
                elif 'Ind2' in ref: r['breaker2'] = bool(val)
                elif 'Ind3' in ref: r['breaker3'] = bool(val)
                elif 'Ind4' in ref: r['auto_mode'] = bool(val)
                elif 'Alm1' in ref: r['alarm1'] = bool(val)
                elif 'PTRC1.Tr.general' in ref: r['relay_tripped'] = bool(val)
            return r
    except Exception:
        pass
    return {}


def read_enip_mfg(host, port=44818):
    """Read manufacturing data via EtherNet/IP CIP ReadTag."""
    result = {}
    s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    s.settimeout(3); s.connect((host, port))
    # RegisterSession
    hdr = struct.pack('<HHII', 0x0065, 4, 0, 0) + b'\x00'*8 + struct.pack('<I', 0)
    hdr += struct.pack('<HH', 1, 0)
    s.sendall(hdr)
    resp = s.recv(4096)
    session = struct.unpack_from('<I', resp, 4)[0]

    def _read_tag(tag_name):
        tag_bytes = tag_name.encode('utf-8')
        cip_path = bytes([0x91, len(tag_bytes)]) + tag_bytes
        if len(cip_path) % 2: cip_path += b'\x00'
        cip_req = bytes([0x4C, len(cip_path)//2]) + cip_path + struct.pack('<H', 1)
        cpf = struct.pack('<H', 2) + struct.pack('<HH', 0, 0)
        cpf += struct.pack('<HH', 0x00B2, len(cip_req)) + cip_req
        rr = struct.pack('<IH', 0, 10) + cpf
        h = struct.pack('<HHII', 0x006F, len(rr), session, 0) + b'\x00'*8 + struct.pack('<I', 0)
        s.sendall(h + rr)
        r = s.recv(4096)
        cip_off = 24 + 4 + 2 + 2 + 4 + 4
        if cip_off + 6 < len(r):
            status = struct.unpack_from('<H', r, cip_off + 2)[0]
            if status == 0:
                dtype = struct.unpack_from('<H', r, cip_off + 4)[0]
                if dtype == 0x00CA and cip_off + 10 <= len(r):
                    return struct.unpack_from('<f', r, cip_off + 6)[0]
                elif dtype == 0x00C1 and cip_off + 7 <= len(r):
                    return bool(r[cip_off + 6])
        return None

    for tag, key in [('WaterLevel', 'hopper'), ('Pressure', 'hydraulic'),
                     ('Temperature', 'motor_temp'), ('PumpRunning', 'conveyor'),
                     ('AutoMode', 'auto_mode'), ('AlarmOverflow', 'jam'),
                     ('InletFlowRate', 'motor_current')]:
        v = _read_tag(tag)
        if v is not None:
            result[key] = v
    s.close()
    return result


def read_melsec_gas(host, port=5007):
    """Read gas pipeline data via MELSEC MC Protocol batch read."""
    result = {}
    s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    s.settimeout(3); s.connect((host, port))
    # MC 3E binary batch read D0-D10 (word mode)
    timer = struct.pack('<H', 10)
    command = struct.pack('<H', 0x0401)
    sub_cmd = struct.pack('<H', 0x0000)
    head_dev = struct.pack('<I', 0)[:3] + bytes([0xA8])  # D register, addr 0
    num_pts = struct.pack('<H', 10)
    cmd_data = timer + command + sub_cmd + head_dev + num_pts
    frame = struct.pack('<H', 0x5000) + bytes([0x00, 0xFF]) + struct.pack('<H', 0x03FF)
    frame += bytes([0x00]) + struct.pack('<H', len(cmd_data)) + cmd_data
    s.sendall(frame)
    resp = s.recv(4096); s.close()
    if len(resp) >= 31:
        end_code = struct.unpack_from('<H', resp, 9)[0]
        if end_code == 0:
            # D0+D1 = water_level (outlet pressure), D2+D3 = pressure (inlet), D4+D5 = temp
            d = [struct.unpack_from('<H', resp, 11 + i*2)[0] for i in range(10)]
            result['pressure'] = ((d[1] << 16) | d[0]) / 100.0    # outlet pressure
            result['inlet_pressure'] = ((d[3] << 16) | d[2]) / 100.0
            result['temperature'] = ((d[5] << 16) | d[4]) / 100.0
    return result


def read_fins_gas(host, port=9600):
    """Read gas pipeline data via OMRON FINS DM memory read."""
    result = {}
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    s.settimeout(2)
    # FINS header + Memory Read command
    header = bytes([0x80, 0x00, 0x02, 0x00, 0x00, 0x00, 0x00, 0xFE, 0x00, 0x00])
    cmd = struct.pack('>H', 0x0101)  # Memory Read
    area = bytes([0x82])  # DM area
    addr = struct.pack('>H', 100)  # DM100
    bit_pos = bytes([0x00])
    count = struct.pack('>H', 12)  # 12 words (6 floats)
    pkt = header + cmd + area + addr + bit_pos + count
    s.sendto(pkt, (host, port))
    try:
        resp, _ = s.recvfrom(4096)
        if len(resp) >= 14 + 24:  # header(10) + cmd(2) + endcode(2) + 12 words
            off = 14
            def _dm_float(i):
                w1 = struct.unpack('>H', resp[off+i*4:off+i*4+2])[0]
                w2 = struct.unpack('>H', resp[off+i*4+2:off+i*4+4])[0]
                return struct.unpack('>f', struct.pack('>HH', w1, w2))[0]
            result['pressure'] = _dm_float(0)       # outlet pressure
            result['inlet_pressure'] = _dm_float(1)  # inlet pressure
            result['temperature'] = _dm_float(2)     # gas temp
    except socket.timeout:
        pass
    s.close()
    return result


def read_abb_boiler(host, port=5020):
    """Read boiler data via ABB Modbus TCP (same protocol as Schneider, different port)."""
    result = {}
    s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    s.settimeout(2); s.connect((host, port))
    # Read Input Registers (FC04): measurements - drum_level, steam_pressure, steam_temp
    pdu = struct.pack('>BHH', 0x04, 0, 3)
    mbap = struct.pack('>HHHB', 1, 0, len(pdu) + 1, 1)
    s.sendall(mbap + pdu)
    resp = s.recv(256)
    if len(resp) >= 15:
        regs = [struct.unpack('>H', resp[9+i*2:9+i*2+2])[0] for i in range(3)]
        result['drum_level'] = regs[0] / 65535 * 100
        result['steam_pressure'] = regs[1] / 65535 * 20  # 0-20 bar range
        result['steam_temp'] = regs[2] / 65535 * 300     # 0-300 C range
    # Read Discrete Inputs (FC02): burner, pump, auto_mode status
    pdu2 = struct.pack('>BHH', 0x02, 0, 9)
    mbap2 = struct.pack('>HHHB', 2, 0, len(pdu2) + 1, 1)
    s2 = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    s2.settimeout(2); s2.connect((host, port))
    s2.sendall(mbap2 + pdu2)
    resp2 = s2.recv(256)
    s2.close(); s.close()
    if len(resp2) >= 11:
        bits = []
        for b in resp2[9:9+resp2[8]]:
            for bit in range(8):
                bits.append(bool(b & (1 << bit)))
        names = ['feedwater_pump', 'blowdown', 'burner', 'auto_mode',
                 'high_pressure', 'low_water', 'high_pressure2', 'safety_valve', 'flame_failure']
        for i, name in enumerate(names):
            if i < len(bits): result[name] = bits[i]
    return result


def read_modbus_heating(host, port=502):
    """Read heating district data via Modbus TCP. Slave ID 11 (ENCO ENC-12X default).
    ENCO uses x10 integer encoding: register 753 = 75.3 degC. Registers are signed int16."""
    SLAVE_ID = 11  # ENCO ENC-12X factory default, confirmed from FrostyGoop incident
    result = {}

    def _reg_to_signed(raw):
        return raw if raw < 32768 else raw - 65536

    try:
        # FC04 Input Registers: supply_temp(0), return_temp(1), flow_rate(2), outdoor_temp(3)
        s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        s.settimeout(2); s.connect((host, port))
        pdu = struct.pack('>BHH', 0x04, 0, 4)
        mbap = struct.pack('>HHHB', 1, 0, len(pdu) + 1, SLAVE_ID)
        s.sendall(mbap + pdu); resp = s.recv(256); s.close()
        if len(resp) >= 17:
            regs = [struct.unpack('>H', resp[9+i*2:9+i*2+2])[0] for i in range(4)]
            result['supply_temp']  = _reg_to_signed(regs[0]) / 10.0  # ENCO x10
            result['return_temp']  = _reg_to_signed(regs[1]) / 10.0
            result['flow_rate']    = _reg_to_signed(regs[2]) / 10.0
            # Register 3 = outdoor_temp - Modbus adapter may return 0 if not mapped.
            # If 0, use the known plant design value (-30°C Ukrainian winter baseline).
            raw_outdoor = _reg_to_signed(regs[3]) / 10.0
            result['outdoor_temp'] = raw_outdoor if raw_outdoor != 0.0 else -30.0

        # FC01 Coils: pump(0), valve(1), pump2(2), auto_mode(3)
        s2 = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        s2.settimeout(2); s2.connect((host, port))
        pdu2 = struct.pack('>BHH', 0x01, 0, 4)
        mbap2 = struct.pack('>HHHB', 2, 0, len(pdu2) + 1, SLAVE_ID)
        s2.sendall(mbap2 + pdu2); resp2 = s2.recv(256); s2.close()
        if len(resp2) >= 10:
            byte0 = resp2[9]
            result['pump']      = bool(byte0 & 0x01)
            result['valve']     = bool(byte0 & 0x02)
            result['auto_mode'] = bool(byte0 & 0x08)
    except Exception:
        pass
    return result


def _dnp3_crc16(data: bytes) -> int:
    """DNP3 CRC-16 (poly 0xA6BC, reflected, init 0x0000, final XOR 0xFFFF)."""
    crc = 0
    for b in data:
        crc ^= b
        for _ in range(8):
            crc = (crc >> 1) ^ 0xA6BC if crc & 1 else crc >> 1
    return crc ^ 0xFFFF


def _dnp3_build_frame(dst: int, src: int, app_bytes: bytes) -> bytes:
    """
    Build a DNP3 link-layer frame with correct CRC bytes.
    DNP3 DLL header: START(2) + LENGTH(1 byte!) + CTRL(1) + DST(2) + SRC(2) + CRC(2)
    """
    transport = bytes([0xC0]) + app_bytes          # FIN|FIR|seq=0
    dll_len = len(transport) + 5                   # per DNP3 spec (1 byte, not 2)
    hdr = struct.pack('<BB', 0x05, 0x64)           # start bytes
    hdr += struct.pack('<B', dll_len)              # length: 1 BYTE (not <H)
    hdr += bytes([0xC4])                           # control: DIR=1,PRM=1,FC=4 (UND)
    hdr += struct.pack('<HH', dst, src)            # dst, src (2 bytes each, LE)
    hdr_crc = struct.pack('<H', _dnp3_crc16(hdr))
    data_crc = struct.pack('<H', _dnp3_crc16(transport))
    return hdr + hdr_crc + transport + data_crc


def _dnp3_extract_objects(resp: bytes):
    """Extract app-layer object data from a DNP3 response frame, stripping block CRCs."""
    if len(resp) < 10 or resp[0:2] != b'\x05\x64':
        return b''
    length = resp[2]
    remaining = max(0, length - 5)  # user data bytes (excl CRCs, excl CTRL/DST/SRC)
    pos = 10  # skip 8-byte link header + 2-byte header CRC
    user_data = bytearray()
    while remaining > 0 and pos < len(resp):
        block_size = min(16, remaining)
        user_data += resp[pos:pos + block_size]
        pos += block_size + 2   # skip the 2-byte block CRC
        remaining -= block_size
    # First byte is transport layer header (FIR|FIN|seq), skip it
    return bytes(user_data[1:]) if user_data else b''


def read_dnp3_water_utility(host, port=20000):
    """Read water utility data via DNP3 integrity poll (Class 0). Port 20000 on PLC-8."""
    result = {}
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        s.settimeout(4); s.connect((host, port))
        # App layer: READ, Group 60 Var 1 (Class 0 Integrity Poll)
        app = bytes([0xC0, 0x01, 60, 1, 0x06])
        frame = _dnp3_build_frame(dst=1, src=2, app_bytes=app)
        s.sendall(frame)
        resp = s.recv(4096); s.close()

        app_data = _dnp3_extract_objects(resp)
        # Skip app header (FIN|FIR|seq byte + function code byte + IIN1 + IIN2 = 4 bytes)
        if len(app_data) < 4:
            return result
        idx = 4  # skip app header

        ai_idx = bi_idx = bo_idx = 0
        while idx + 3 < len(app_data):
            grp = app_data[idx]; var = app_data[idx+1]; qual = app_data[idx+2]
            idx += 3
            if qual == 0x01 and idx < len(app_data):  # 8-bit count
                count = app_data[idx]; idx += 1
            elif qual == 0x28 and idx < len(app_data):  # 8-bit count
                count = app_data[idx]; idx += 1
            else:
                count = 1

            for _ in range(count):
                obj_idx = 0
                if qual in (0x01, 0x28) and idx < len(app_data):
                    obj_idx = app_data[idx]; idx += 1

                if grp == 30 and var == 5 and idx + 5 <= len(app_data):  # AI: flags(1) + float(4)
                    idx += 1  # skip flags byte (always 0x80 ONLINE from adapter)
                    val = struct.unpack_from('<f', app_data, idx)[0]; idx += 4
                    if ai_idx == 0:   result['reservoir_level'] = val
                    elif ai_idx == 1: result['pressure']        = val  # AI[1]=distribution_pressure
                    elif ai_idx == 2: result['chlorine_ppm']    = val  # AI[2]=chlorine_residual
                    elif ai_idx == 3: result['flow_rate']       = val
                    ai_idx += 1
                elif grp == 1 and var == 2 and idx + 1 <= len(app_data):  # BI: flags byte
                    flags = app_data[idx]; idx += 1
                    on = bool(flags & 0x01)   # bit 0 = STATE (not 0x80 which is ONLINE)
                    if bi_idx == 0:   result['pump1']     = on  # inlet_valve_status→pump_station_1
                    elif bi_idx == 1: result['pump2']     = on  # outlet_valve_status→pump_station_2
                    elif bi_idx == 3: result['auto_mode'] = on  # auto_mode_status→auto_mode
                    bi_idx += 1
                elif grp == 10 and var == 2 and idx + 1 <= len(app_data):  # BO status
                    idx += 1  # skip
                else:
                    break
    except Exception:
        pass
    return result


def _mbus_lib_path():
    return os.path.join(os.path.dirname(__file__), '..', 'server')


def read_mbus_sensors(host, port=5000):
    """Read M-Bus sensor gateway via mbus_lib.MBusClient."""
    sys.path.insert(0, _mbus_lib_path())
    try:
        from mbus_lib import MBusClient
    except ImportError:
        return {'online_sensors': 0, 'corrupted': True}

    try:
        with MBusClient(host, port, timeout=3.0) as m:
            if not m.ping(1):
                return {'online_sensors': 0, 'corrupted': True}
            frame = m.read(1)

        if frame is None or not frame.valid:
            return {'online_sensors': 0, 'corrupted': True}

        result = {'online_sensors': 12, 'corrupted': False}
        for rec in frame.records:
            name = rec.name.lower()
            val  = rec.value
            if 'volume' in name:
                result['flow_total'] = val / 1000.0   # L → m³
            elif 'pressure' in name:
                result['pressure'] = val
            elif 'temperature' in name:
                result['temperature'] = val
            elif 'flow' in name:
                result['flow_rate'] = val
        return result
    except Exception:
        return {'online_sensors': 0, 'corrupted': True}


def read_safety_system(host, port=1502):
    """
    Read SIS state via TriStation UDP (port 1502) - the primary (and only) protocol on SIS-1.
    Sends TCM_CONNECT_REQUEST then TS_GET_CP_STATUS (funccode 0x13).

    Response layout (per tristation_adapter.py _build_ts_packet + GET_CP_STATUS handler):
      [0-3]   TCM header: B(mcode=0x05) B(tricon_id) H(data_length)
      [4-13]  Subheader: BBBBHHH (path cid funccode seq unk chk dlen)
      [14-15] cp_data: state (B), 0x01 (B)
      [16-19] cp_data: 3008 (H), 0x0100 (H)
      [20-51] cp_data: 'WATERTANK_SIS\x00' + 18 null bytes (32 bytes)
      [52]    flags byte: bit0=armed, bit1=tripped, bit2=disabled
      [53-56] monitored_val: big-endian float
    """
    result = {}
    try:
        import crcmod
        crc16 = crcmod.predefined.mkCrcFun('crc-16')
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.settimeout(2)

        # TCM CONNECT REQUEST
        connect = struct.pack('<BBH', 0x01, 0x00, 0x0000)
        s.sendto(connect, (host, port))
        try: s.recvfrom(256)
        except socket.timeout: pass

        # TS_GET_CP_STATUS (funccode 0x13)
        data_length = 10
        subheader_nc = struct.pack('<BBBBHHH', 1, 1, 0x13, 1, 0, 0, data_length)
        chk = crc16(subheader_nc) & 0xFFFF
        subheader = struct.pack('<BBBBHHH', 1, 1, 0x13, 1, 0, chk, data_length)
        header = struct.pack('<BBH', 0x05, 0, data_length)
        s.sendto(header + subheader, (host, port))

        try:
            resp, _ = s.recvfrom(512)
            # flags at byte 52 (14 header + 6 state/version + 32 name bytes)
            if len(resp) > 52:
                flags = resp[52]
                result['armed']    = bool(flags & 0x01)
                result['tripped']  = bool(flags & 0x02)
                result['disabled'] = bool(flags & 0x04)
            # monitored_val float at byte 53
            if len(resp) >= 57:
                result['monitored_val'] = struct.unpack_from('>f', resp, 53)[0]
            if 'armed' not in result:
                # Server reachable but response shorter than expected - use fallbacks
                result['armed'] = True; result['tripped'] = False; result['disabled'] = False
        except socket.timeout:
            pass
        s.close()
    except Exception:
        pass
    return result


# =========================================================================
# PROCESS VISUALIZATION DRAWING FUNCTIONS
# Each draws on a Canvas with (c, w, h, data) signature
# =========================================================================

def _valve_symbol(c, x, y, open_pct, label, color_on, color_off):
    """Draw a bowtie valve symbol."""
    col = color_on if open_pct > 0 else color_off
    c.create_polygon(x-10, y-12, x+10, y, x-10, y+12, fill=col, outline='')
    c.create_polygon(x+10, y-12, x-10, y, x+10, y+12, fill=col, outline='')
    c.create_text(x, y+20, text=f"{label}", font=("Consolas", 7), fill=col)


def draw_water_tank(c, w, h, d):
    """Water Treatment Plant: tank, pipes, valves, pump."""
    t = time.time()
    level = d.get('level', 50)
    inlet = d.get('inlet', False)
    outlet = d.get('outlet', False)
    pump = d.get('pump', False)
    exploded = d.get('exploded', False)
    sis = d.get('sis_tripped', False)

    # Tank body
    tx, ty, tw, th = w*0.3, h*0.08, w*0.4, h*0.7
    c.create_rectangle(tx, ty, tx+tw, ty+th, outline=DIM, width=2)

    # Water fill
    fill_h = th * (max(0, min(100, level)) / 100.0)
    wy = ty + th - fill_h
    if fill_h > 1:
        col = '#b71c1c' if level > 95 else '#ff6d00' if level > 90 else '#0277bd'
        c.create_rectangle(tx+2, wy, tx+tw-2, ty+th-2, fill=col, outline='')
        # Wave
        pts = []
        for px in range(int(tx+2), int(tx+tw-2), 4):
            pts.extend([px, wy + 3*math.sin(px*0.06 + t*2)])
        if len(pts) >= 4:
            pts += [int(tx+tw-2), wy, int(tx+2), wy]
            c.create_polygon(pts, fill='#0288d1', outline='')

    # Level text
    c.create_text(tx+tw/2, ty+th/2, text=f"{level:.1f}%",
                  font=("Consolas", 18, "bold"), fill='white')

    # Inlet pipe (left, top)
    py = ty + th*0.2
    c.create_line(0, py, tx, py, fill=GREEN if inlet else DIM, width=5)
    _valve_symbol(c, tx*0.45, py, 100 if inlet else 0, "INLET", GREEN, RED)

    # Outlet pipe (right, bottom)
    oy = ty + th*0.8
    c.create_line(tx+tw, oy, w, oy, fill=GREEN if outlet else DIM, width=5)
    _valve_symbol(c, tx+tw+(w-tx-tw)*0.55, oy, 100 if outlet else 0, "OUTLET", GREEN, RED)

    # Pump (circle with P, on inlet pipe)
    px_c, py_c = tx*0.45, py - 35
    pcol = GREEN if pump else DIM
    c.create_oval(px_c-16, py_c-16, px_c+16, py_c+16, outline=pcol, width=2)
    c.create_text(px_c, py_c, text="P", font=("Consolas", 12, "bold"), fill=pcol)
    c.create_line(px_c, py_c+16, px_c, py-5, fill=pcol, width=2)

    # SIS tripped overlay
    if sis and not exploded:
        blink = int(time.time() * 3) % 2 == 0
        border_col = AMBER if blink else RED
        c.create_rectangle(tx-5, ty-5, tx+tw+5, ty+th+5, outline=border_col, width=3)
        c.create_text(tx+tw/2, ty-15, text="SIS TRIPPED - SAFE STATE",
                      font=("Consolas", 10, "bold"), fill=AMBER)
        c.create_text(tx+tw/2, ty+th+20, text="Inlet CLOSED | Outlet OPEN | Pump OFF",
                      font=("Consolas", 7), fill=AMBER)

    # Exploded overlay
    if exploded:
        c.create_rectangle(tx-5, ty-5, tx+tw+5, ty+th+5, outline=RED, width=4, dash=(8, 4))
        c.create_text(tx+tw/2, ty+th+25, text="TANK RUPTURED",
                      font=("Consolas", 14, "bold"), fill=RED)

    # Labels
    c.create_text(w/2, h-15, text="Protocol: Modbus TCP (read + control)",
                  font=("Consolas", 7), fill=DIM)


def draw_substation(c, w, h, d):
    """Power Substation: single-line diagram with breakers."""
    v = d.get('voltage', 13.8)
    brk1 = d.get('breaker1', True)   # read_iec61850 → 'Ind1' ref
    brk2 = d.get('breaker2', True)   # read_iec61850 → 'Ind2' ref
    brk3 = d.get('breaker3', True)   # read_iec61850 → 'Ind3' ref
    tripped = d.get('relay_tripped', False)
    blackout = v == 0

    cx = w / 2
    bus_y = h * 0.25  # horizontal bus bar

    # Incoming feeder (top)
    c.create_line(cx-120, 20, cx-120, bus_y, fill=GREEN if brk1 else RED, width=3)
    c.create_text(cx-120, 10, text="INCOMING", font=("Consolas", 7), fill=TEXT)

    # Breaker 1 symbol
    by1 = bus_y * 0.5
    _draw_breaker(c, cx-120, by1, brk1, "BRK1")

    # Bus bar (horizontal line)
    bus_col = GREEN if not blackout else RED
    c.create_line(cx-180, bus_y, cx+180, bus_y, fill=bus_col, width=4)
    c.create_text(cx, bus_y-12, text=f"13.8kV BUS   {v:.1f}kV", font=("Consolas", 8, "bold"),
                  fill=AMBER if v < 12 else GREEN)

    # Bus-tie breaker (middle of bus)
    _draw_breaker(c, cx, bus_y+20, brk2, "BUS-TIE")

    # Outgoing feeder (bottom right)
    out_y = h * 0.55
    c.create_line(cx+120, bus_y, cx+120, out_y, fill=GREEN if brk3 else RED, width=3)
    _draw_breaker(c, cx+120, (bus_y+out_y)/2, brk3, "BRK3")

    # Transformer (below bus-tie)
    xf_y = h * 0.55
    c.create_oval(cx-20, xf_y-20, cx+20, xf_y+20, outline=AMBER, width=2)
    c.create_oval(cx-14, xf_y-14, cx+14, xf_y+14, outline=AMBER, width=2)
    c.create_text(cx, xf_y, text="T", font=("Consolas", 10, "bold"), fill=AMBER)
    c.create_line(cx, bus_y+30, cx, xf_y-20, fill=AMBER, width=2)

    # Load (below transformer)
    load_y = h * 0.75
    c.create_line(cx, xf_y+20, cx, load_y, fill=TEXT, width=2)
    c.create_text(cx, load_y+10, text=f"LOAD", font=("Consolas", 8), fill=TEXT)

    # Protection relay
    relay_col = RED if tripped else GREEN
    c.create_rectangle(cx+60, h*0.6, cx+130, h*0.7, outline=relay_col, width=2)
    c.create_text(cx+95, h*0.65, text="RELAY", font=("Consolas", 7, "bold"), fill=relay_col)

    # Outgoing load
    c.create_text(cx+120, out_y+15, text="OUTGOING", font=("Consolas", 7), fill=TEXT)

    # Blackout overlay
    if blackout:
        c.create_rectangle(0, 0, w, h, fill='', outline='')
        c.create_text(cx, h*0.85, text="BLACKOUT", font=("Consolas", 20, "bold"), fill=RED)

    c.create_text(w/2, h-10, text="Protocol: IEC 61850 MMS + GOOSE",
                  font=("Consolas", 7), fill=DIM)


def _draw_breaker(c, x, y, closed, label):
    """Draw a circuit breaker symbol."""
    col = GREEN if closed else RED
    if closed:
        c.create_line(x, y-12, x, y+12, fill=col, width=3)
    else:
        c.create_line(x, y-12, x+10, y+8, fill=col, width=3)
    c.create_oval(x-4, y-16, x+4, y-8, outline=col, width=2)
    c.create_oval(x-4, y+8, x+4, y+16, outline=col, width=2)
    c.create_text(x+18, y, text=label, font=("Consolas", 6), fill=col, anchor='w')


def draw_pipeline(c, w, h, d):
    """Gas Pipeline: compressor station with valves."""
    pressure = d.get('pressure', 800)
    flow = d.get('flow', 1000)
    upstream = d.get('upstream', True)
    downstream = d.get('downstream', True)
    compressor = d.get('compressor', True)
    rupture = pressure > 1400

    cy = h * 0.45
    # Pipeline (horizontal)
    pipe_col = RED if rupture else ('#ff6d00' if pressure > 1200 else GREEN)
    c.create_line(20, cy, w-20, cy, fill=pipe_col, width=8)

    # Upstream valve (left)
    _valve_symbol(c, w*0.2, cy, 100 if upstream else 0, "UPSTREAM", GREEN, RED)

    # Compressor (center circle with arrow)
    comp_x = w * 0.5
    comp_col = GREEN if compressor else DIM
    c.create_oval(comp_x-28, cy-28, comp_x+28, cy+28, outline=comp_col, width=3)
    c.create_text(comp_x, cy-5, text="COMP", font=("Consolas", 8, "bold"), fill=comp_col)
    # Spinning arrow
    if compressor:
        t = time.time()
        angle = t * 3
        ax = comp_x + 15*math.cos(angle)
        ay = cy + 10 + 15*math.sin(angle)
        c.create_oval(ax-3, ay-3, ax+3, ay+3, fill=comp_col)

    # Downstream valve (right)
    _valve_symbol(c, w*0.8, cy, 100 if downstream else 0, "DOWNSTREAM", GREEN, RED)

    # Pressure gauges
    inlet_psi = d.get('inlet_pressure', 400)
    c.create_text(w*0.35, cy-45, text=f"IN: {inlet_psi:.0f} PSI", font=("Consolas", 9, "bold"), fill=ACCENT)
    c.create_text(w*0.65, cy-45, text=f"OUT: {pressure:.0f} PSI",
                  font=("Consolas", 9, "bold"), fill=RED if pressure > 1200 else ACCENT)

    # Flow arrow
    if flow > 0:
        ax = w*0.5 + 50
        c.create_line(ax, cy+40, ax+30, cy+40, fill=GREEN, width=2, arrow='last')
        c.create_text(ax+15, cy+55, text=f"{flow:.0f} SCF/m", font=("Consolas", 8), fill=GREEN)

    if rupture:
        c.create_text(w/2, h*0.8, text="PIPELINE RUPTURE", font=("Consolas", 18, "bold"), fill=RED)

    c.create_text(w/2, h-10, text="Protocols: OPC-UA + OMRON FINS",
                  font=("Consolas", 7), fill=DIM)


def draw_hvac(c, w, h, d):
    """Building HVAC: AHU with coils, fan, ducts, room."""
    zone_temp = d.get('zone_temp', 22)
    fan = d.get('fan', True)
    heating = d.get('heating', True)
    cooling = d.get('cooling', False)

    # AHU box
    ax, ay, aw, ah = w*0.1, h*0.15, w*0.35, h*0.5
    c.create_rectangle(ax, ay, ax+aw, ay+ah, outline=DIM, width=2)
    c.create_text(ax+aw/2, ay-10, text="AHU", font=("Consolas", 9, "bold"), fill=ACCENT)

    # Heating coil (red zigzag)
    coil_y = ay + ah*0.3
    coil_col = RED if heating else DIM
    for i in range(6):
        x1 = ax + 10 + i * (aw-20)/6
        x2 = x1 + (aw-20)/12
        c.create_line(x1, coil_y-8, x2, coil_y+8, fill=coil_col, width=2)
        c.create_line(x2, coil_y+8, x1+(aw-20)/6, coil_y-8, fill=coil_col, width=2)
    c.create_text(ax+aw/2, coil_y+18, text="HEAT COIL", font=("Consolas", 6), fill=coil_col)

    # Cooling coil (blue zigzag)
    cool_y = ay + ah*0.55
    cool_col = '#0277bd' if cooling else DIM
    for i in range(6):
        x1 = ax + 10 + i * (aw-20)/6
        x2 = x1 + (aw-20)/12
        c.create_line(x1, cool_y-8, x2, cool_y+8, fill=cool_col, width=2)
    c.create_text(ax+aw/2, cool_y+18, text="COOL COIL", font=("Consolas", 6), fill=cool_col)

    # Fan (circle with blades)
    fan_x, fan_y = ax+aw/2, ay+ah*0.82
    fan_col = GREEN if fan else DIM
    c.create_oval(fan_x-18, fan_y-18, fan_x+18, fan_y+18, outline=fan_col, width=2)
    if fan:
        t = time.time()
        for i in range(3):
            angle = t*4 + i * 2.094
            bx = fan_x + 12*math.cos(angle)
            by = fan_y + 12*math.sin(angle)
            c.create_line(fan_x, fan_y, bx, by, fill=fan_col, width=2)
    c.create_text(fan_x, fan_y+28, text="FAN", font=("Consolas", 6), fill=fan_col)

    # Supply duct (right from AHU to room)
    duct_y = ay + ah*0.4
    c.create_line(ax+aw, duct_y, w*0.9, duct_y, fill=GREEN if fan else DIM, width=4)
    if fan:
        c.create_line(w*0.65, duct_y, w*0.7, duct_y, fill=GREEN, width=2, arrow='last')

    # Return duct (below)
    ret_y = duct_y + 50
    c.create_line(ax+aw, ret_y, w*0.9, ret_y, fill=DIM, width=4, dash=(6,3))

    # Room
    rx, ry, rw, rh = w*0.6, h*0.15, w*0.3, h*0.55
    c.create_rectangle(rx, ry, rx+rw, ry+rh, outline=DIM, width=2)
    temp_col = RED if zone_temp > 30 else ('#0277bd' if zone_temp < 15 else GREEN)
    c.create_text(rx+rw/2, ry+rh/2-10, text=f"{zone_temp:.1f}\u00b0C",
                  font=("Consolas", 20, "bold"), fill=temp_col)
    c.create_text(rx+rw/2, ry+rh/2+15, text="ZONE", font=("Consolas", 8), fill=TEXT)
    c.create_text(rx+rw/2, ry-10, text="CONDITIONED SPACE", font=("Consolas", 7), fill=DIM)

    c.create_text(w/2, h-10, text="Protocol: BACnet/IP (UDP)",
                  font=("Consolas", 7), fill=DIM)


def draw_centrifuge_cascade(c, w, h, d):
    """Centrifuge Cascade: 3 IR-1 centrifuges with speed, vibration, stress indicators."""
    centrifuges = d.get('centrifuges', [
        {'speed': 1007.0, 'vib': 0.15, 'temp': 65.0, 'status': 0},
        {'speed': 1007.0, 'vib': 0.15, 'temp': 65.0, 'status': 0},
        {'speed': 1007.0, 'vib': 0.15, 'temp': 65.0, 'status': 0},
    ])
    rootkit = d.get('rootkit_active', False)

    STATUS_LABELS = ['NORMAL', 'OVERSPEED', 'UNDERSTEED', 'DAMAGED', 'DESTROYED']
    STATUS_COLORS = [GREEN, RED, AMBER, '#ff6d00', DIM]
    COL_X = [w * 0.15, w * 0.50, w * 0.85]
    TUBE_W = max(int(w * 0.10), 20)
    TUBE_H = int(h * 0.40)
    ARC_R  = max(int(w * 0.08), 22)

    t = time.time()

    for i, (cx, cfg) in enumerate(zip(COL_X, centrifuges[:3])):
        speed  = cfg.get('speed', 1007.0)
        vib    = cfg.get('vib', 0.15)
        temp   = cfg.get('temp', 65.0)
        status = cfg.get('status', 0)

        # -- Speed arc tachometer --
        arc_cx, arc_cy = cx, h * 0.18
        arc_r = ARC_R
        # Background arc
        c.create_arc(arc_cx - arc_r, arc_cy - arc_r, arc_cx + arc_r, arc_cy + arc_r,
                     start=225, extent=-270, style='arc', outline=DIM, width=3)
        # Speed fill: 0–1500 Hz maps to 0–270 degrees
        extent = max(0, min(270, speed / 1500.0 * 270))
        if extent > 0:
            arc_col = RED if speed > 1200 else (AMBER if speed > 1007 else GREEN)
            c.create_arc(arc_cx - arc_r, arc_cy - arc_r, arc_cx + arc_r, arc_cy + arc_r,
                         start=225, extent=-extent, style='arc', outline=arc_col, width=4)
        c.create_text(arc_cx, arc_cy, text=f"{speed:.0f}", font=("Consolas", 9, "bold"),
                      fill=GREEN if speed < 1200 else RED)
        c.create_text(arc_cx, arc_cy + 12, text="Hz", font=("Consolas", 6), fill=DIM)

        # -- Centrifuge tube --
        tx, ty = cx - TUBE_W // 2, arc_cy + arc_r + 10
        tube_col = DIM if status == 4 else (RED if status == 1 else (AMBER if status == 2 else '#37474f'))
        c.create_rectangle(tx, ty, tx + TUBE_W, ty + TUBE_H, outline=tube_col, width=2, fill='#1a1a2e')

        if status == 4:  # DESTROYED - hatch pattern + red flash
            flash = int(t * 2) % 2
            if flash:
                c.create_rectangle(tx, ty, tx + TUBE_W, ty + TUBE_H, outline='', fill='#3a0000')
            for yi in range(0, TUBE_H, 8):
                c.create_line(tx, ty + yi, tx + TUBE_W, ty + yi + 10, fill='#5a0000', width=1)
                c.create_line(tx + TUBE_W, ty + yi, tx, ty + yi + 10, fill='#5a0000', width=1)
            c.create_text(cx, ty + TUBE_H // 2 - 8, text="ROTOR", font=("Consolas", 7, "bold"), fill=RED)
            c.create_text(cx, ty + TUBE_H // 2 + 6, text="FAILURE", font=("Consolas", 7, "bold"), fill=RED)
        elif status == 1:  # OVERSPEED flicker
            if int(t * 4) % 2:
                c.create_rectangle(tx + 2, ty + 2, tx + TUBE_W - 2, ty + TUBE_H - 2,
                                   outline='', fill='#2a0000')
        elif status == 2:  # UNDERSTEED amber
            c.create_rectangle(tx + 2, ty + 2, tx + TUBE_W - 2, ty + TUBE_H - 2,
                               outline='', fill='#2a1a00')
        elif speed > 100:  # Normal rotation shimmer
            phase = (t * speed * 0.0005 + i) % 1.0
            shade_y = ty + int(phase * TUBE_H)
            c.create_line(tx + 2, shade_y, tx + TUBE_W - 2, shade_y, fill='#304050', width=2)

        # -- Vibration bar --
        vib_y = ty + TUBE_H + 6
        vib_max_w = TUBE_W
        vib_w = min(vib_max_w, int(vib / 5.0 * vib_max_w))
        vib_col = RED if vib > 3.0 else (AMBER if vib > 1.0 else GREEN)
        c.create_rectangle(tx, vib_y, tx + vib_max_w, vib_y + 4, outline=DIM, width=1)
        if vib_w > 0:
            c.create_rectangle(tx, vib_y, tx + vib_w, vib_y + 4, outline='', fill=vib_col)
        c.create_text(cx, vib_y + 9, text=f"{vib:.2f}g", font=("Consolas", 6), fill=vib_col)

        # -- Bearing temp strip --
        temp_y = vib_y + 18
        temp_norm = min(1.0, max(0, (temp - 60) / 100.0))
        r = int(30 + temp_norm * 225)
        g = int(144 - temp_norm * 144)
        b_val = max(0, int(255 - temp_norm * 255))
        temp_col = f'#{r:02x}{g:02x}{b_val:02x}'
        c.create_rectangle(tx, temp_y, tx + TUBE_W, temp_y + 4, outline='', fill=temp_col)
        c.create_text(cx, temp_y + 9, text=f"{temp:.0f}°C", font=("Consolas", 6), fill=temp_col)

        # -- Status label --
        lbl = STATUS_LABELS[min(status, 4)]
        lbl_col = STATUS_COLORS[min(status, 4)]
        if status in (1, 2) and int(t * 2) % 2 == 0:
            lbl_col = DIM
        c.create_text(cx, temp_y + 22, text=lbl, font=("Consolas", 7, "bold"), fill=lbl_col)

        # -- Centrifuge label --
        c.create_text(cx, ty - 8, text=f"IR-1 #{i+1}", font=("Consolas", 7), fill=TEXT)

    # -- Data integrity alarm overlay (triggered by DB890 stuxnet_active) --
    if rootkit:
        if int(t * 2) % 2 == 0:
            c.create_rectangle(2, 2, w - 2, h - 2, outline='#8b0000', width=2, dash=(4, 4))
        c.create_text(w - 4, 6, text="[!] DATA INTEGRITY ALARM",
                      font=("Consolas", 7, "bold"), fill='#8b0000', anchor='ne')

    c.create_text(w / 2, h - 10, text="Protocol: Siemens S7comm (port 102)  |  Natanz Cascade A",
                  font=("Consolas", 7), fill=DIM)


def draw_manufacturing(c, w, h, d):
    """Manufacturing Line: conveyor, motor, hopper, products."""
    running = d.get('running', True)
    speed = d.get('speed', 60)
    hopper = d.get('hopper', 75)
    e_stop = d.get('e_stop', False)

    # Hopper (trapezoid)
    hx, hy = w*0.15, h*0.1
    hw, hh = w*0.2, h*0.35
    c.create_polygon(hx, hy, hx+hw, hy, hx+hw*0.8, hy+hh, hx+hw*0.2, hy+hh,
                     outline=DIM, width=2, fill='')
    # Fill level
    fill_h = hh * (hopper/100)
    fy = hy + hh - fill_h
    c.create_polygon(hx+hw*0.2+(hh-fill_h)/hh*hw*0.15, fy,
                     hx+hw*0.8-(hh-fill_h)/hh*hw*0.15, fy,
                     hx+hw*0.8, hy+hh, hx+hw*0.2, hy+hh,
                     fill='#795548', outline='')
    c.create_text(hx+hw/2, hy+hh/2, text=f"{hopper:.0f}%", font=("Consolas", 10, "bold"), fill='white')
    c.create_text(hx+hw/2, hy-10, text="HOPPER", font=("Consolas", 7), fill=TEXT)

    # Conveyor belt
    belt_y = hy + hh + 30
    belt_col = GREEN if running and not e_stop else (RED if e_stop else DIM)
    c.create_line(w*0.1, belt_y, w*0.9, belt_y, fill=belt_col, width=6)
    # Rollers
    for rx in range(int(w*0.15), int(w*0.85), int(w*0.08)):
        c.create_oval(rx-5, belt_y+2, rx+5, belt_y+12, outline=belt_col, width=1)

    # Products on belt
    if running and not e_stop:
        t = time.time()
        for i in range(4):
            px = ((t * speed * 0.5 + i * 80) % (w*0.7)) + w*0.1
            c.create_rectangle(px, belt_y-18, px+20, belt_y-4, fill='#42a5f5', outline='#1e88e5')

    # Motor
    mx, my = w*0.75, belt_y + 40
    c.create_oval(mx-22, my-22, mx+22, my+22, outline=belt_col, width=2)
    c.create_text(mx, my, text="M", font=("Consolas", 12, "bold"), fill=belt_col)
    c.create_line(mx, belt_y+6, mx, my-22, fill=belt_col, width=2)

    # Product output
    c.create_text(w*0.9, belt_y-25, text="OUT \u25b6", font=("Consolas", 8), fill=GREEN if running else DIM)

    # E-Stop indicator
    if e_stop:
        c.create_text(w/2, h*0.8, text="E-STOP ACTIVE", font=("Consolas", 18, "bold"), fill=RED)

    c.create_text(w/2, h-10, text="Protocol: Siemens S7 (port 102) + EtherNet/IP (44818)",
                  font=("Consolas", 7), fill=DIM)


def draw_boiler(c, w, h, d):
    """Boiler House: drum, burner, steam header, feedwater."""
    drum_level = d.get('drum_level', 50)
    burner = d.get('burner', True)
    safety = d.get('safety_valve', False)
    flame = d.get('flame_failure', False)

    # Boiler drum (horizontal cylinder)
    dx, dy, dw, dh = w*0.2, h*0.15, w*0.6, h*0.35
    c.create_oval(dx, dy, dx+dh, dy+dh, outline=DIM, width=2)
    c.create_rectangle(dx+dh/2, dy, dx+dw-dh/2, dy+dh, outline=DIM, width=2)
    c.create_oval(dx+dw-dh, dy, dx+dw, dy+dh, outline=DIM, width=2)

    # Water level in drum
    fill_h = dh * (drum_level / 100)
    fill_y = dy + dh - fill_h
    c.create_rectangle(dx+dh/2, fill_y, dx+dw-dh/2, dy+dh, fill='#1565c0', outline='')
    c.create_text(dx+dw/2, dy+dh/2, text=f"{drum_level:.0f}%",
                  font=("Consolas", 14, "bold"), fill='white')
    c.create_text(dx+dw/2, dy-8, text="STEAM DRUM", font=("Consolas", 7), fill=TEXT)

    # Burner (below drum)
    by = dy + dh + 15
    flame_col = '#ff6d00' if burner and not flame else (RED if flame else DIM)
    c.create_rectangle(dx+dw*0.3, by, dx+dw*0.7, by+25, outline=flame_col, width=2)
    if burner and not flame:
        for i in range(5):
            fx = dx + dw*0.35 + i * dw*0.07
            fh = 15 + 5 * math.sin(time.time()*3 + i)
            c.create_polygon(fx, by, fx+5, by-fh, fx+10, by, fill='#ff6d00', outline='')
    c.create_text(dx+dw/2, by+12, text="BURNER", font=("Consolas", 7), fill=flame_col)

    # Steam header (pipe going up-right)
    sx, sy = dx+dw*0.8, dy
    c.create_line(sx, sy, sx+w*0.1, sy-15, fill='#b0bec5', width=4)
    c.create_text(sx+w*0.12, sy-15, text="STEAM", font=("Consolas", 7), fill=AMBER)

    # Feedwater pump (bottom-left)
    px, py = dx, dy+dh+20
    pump_col = GREEN if d.get('feedwater_pump', True) else DIM
    c.create_oval(px-12, py-12, px+12, py+12, outline=pump_col, width=2)
    c.create_text(px, py, text="P", font=("Consolas", 10, "bold"), fill=pump_col)
    c.create_line(px+12, py, dx+dh/2, dy+dh, fill=pump_col, width=2)
    c.create_text(px, py+18, text="FW PUMP", font=("Consolas", 6), fill=pump_col)

    # Safety valve
    if safety:
        c.create_text(w/2, h*0.85, text="SAFETY VALVE OPEN", font=("Consolas", 14, "bold"), fill=RED)
    if flame:
        c.create_text(w/2, h*0.92, text="FLAME FAILURE", font=("Consolas", 14, "bold"), fill=RED)

    c.create_text(w/2, h-10, text="Protocol: ABB Modbus TCP (port 5020)",
                  font=("Consolas", 7), fill=DIM)


def draw_heating_district(c, w, h, d):
    """Heating District: supply/return loops, pump, heat exchanger."""
    supply  = d.get('supply_temp', 75)
    ret     = d.get('return_temp', 45)
    outdoor = d.get('outdoor_temp', -30)
    flow    = d.get('flow_rate', 60)
    pump    = d.get('pump', True)
    valve   = d.get('valve', True)
    attack  = supply < 30 and d           # FrostyGoop killed heating
    blackout = ret < 0                     # return below freezing - heating blackout

    supply_col = '#ff6d00' if supply > 50 else ('#0277bd' if supply < 20 else AMBER)
    ret_col    = '#0277bd'
    cy_sup = h * 0.3
    cy_ret = h * 0.65

    # Supply pipe (hot, top)
    c.create_line(20, cy_sup, w-20, cy_sup, fill=supply_col if not attack else RED, width=8)
    c.create_text(w/2, cy_sup-16, text=f"SUPPLY  {supply:.1f}°C",
                  font=("Consolas", 10, "bold"), fill=supply_col)
    c.create_line(w-20, cy_sup, w-20, cy_ret, fill=DIM, width=4)  # right-side riser

    # Return pipe (cool, bottom)
    c.create_line(20, cy_ret, w-20, cy_ret, fill=ret_col, width=8)
    c.create_text(w/2, cy_ret+16, text=f"RETURN  {ret:.1f}°C",
                  font=("Consolas", 10, "bold"), fill=ret_col)
    c.create_line(20, cy_sup, 20, cy_ret, fill=DIM, width=4)  # left-side riser

    # Circulation pump
    px, py = w*0.35, (cy_sup + cy_ret) / 2
    pcol = GREEN if pump else DIM
    c.create_oval(px-22, py-22, px+22, py+22, outline=pcol, width=2)
    c.create_text(px, py-6, text="CIRC", font=("Consolas", 7, "bold"), fill=pcol)
    c.create_text(px, py+7, text="PUMP", font=("Consolas", 7, "bold"), fill=pcol)
    if pump:
        t = time.time()
        for i in range(3):
            a = t*3 + i*2.094
            bx = px + 14*math.cos(a); by = py + 14*math.sin(a)
            c.create_line(px, py, bx, by, fill=pcol, width=2)

    # Heat exchanger valve
    vx, vy = w*0.65, (cy_sup + cy_ret) / 2
    _valve_symbol(c, vx, vy, 100 if valve else 0, "HEX\nVLV", GREEN, RED)

    # Flow arrow
    if flow > 0 and pump:
        ax = w*0.5
        c.create_line(ax-15, cy_sup-20, ax+15, cy_sup-20, fill=supply_col, width=2, arrow='last')
        c.create_text(ax, cy_sup-32, text=f"{flow:.0f} m³/h", font=("Consolas", 8), fill=supply_col)

    # Outdoor temperature display
    out_col = '#42a5f5' if outdoor > -15 else RED
    c.create_text(20, 12, text=f"OUT: {outdoor:.1f}°C", anchor='w',
                  font=("Consolas", 8, "bold"), fill=out_col)

    if attack:
        c.create_text(w/2, h*0.5, text="HEATING LOSS", font=("Consolas", 20, "bold"), fill=RED)

    # Heating blackout - return temp below 0°C means pipes at risk of freezing
    if blackout:
        c.create_rectangle(0, h*0.62, w, h*0.82, fill='#1a0000', outline='')
        c.create_text(w/2, h*0.68, text="[!] HEATING BLACKOUT [!]",
                      font=("Consolas", 13, "bold"), fill=RED)
        c.create_text(w/2, h*0.76, text="Return temp below 0°C - pipe freeze risk",
                      font=("Consolas", 8), fill='#ff8a80')

    c.create_text(w/2, h-10, text="Protocol: Modbus TCP :502 (FrostyGoop target)",
                  font=("Consolas", 7), fill=DIM)


def draw_water_utility(c, w, h, d):
    """Water Utility: reservoir, pump stations, distribution network."""
    level = d.get('reservoir_level', 75)
    flow  = d.get('flow_rate', 500)
    psi   = d.get('pressure', 65)
    cl    = d.get('chlorine_ppm', 0.5)
    p1    = d.get('pump1', True)
    p2    = d.get('pump2', True)

    # Reservoir tank (left)
    tx, ty, tw, th = w*0.04, h*0.1, w*0.22, h*0.7
    c.create_rectangle(tx, ty, tx+tw, ty+th, outline=DIM, width=2)
    fill_h = th * (max(0, min(100, level)) / 100.0)
    if fill_h > 1:
        wy = ty + th - fill_h
        c.create_rectangle(tx+2, wy, tx+tw-2, ty+th-2, fill='#0277bd', outline='')
    c.create_text(tx+tw/2, ty+th/2, text=f"{level:.0f}%",
                  font=("Consolas", 12, "bold"), fill='white')
    c.create_text(tx+tw/2, ty-12, text="RESERVOIR", font=("Consolas", 7), fill=TEXT)

    # Main distribution pipe (horizontal)
    py_pipe = h * 0.45
    c.create_line(tx+tw, py_pipe, w-20, py_pipe, fill=GREEN if psi > 30 else RED, width=6)

    # Pump station 1
    p1x = w*0.38
    p1col = GREEN if p1 else DIM
    c.create_oval(p1x-18, py_pipe-18, p1x+18, py_pipe+18, outline=p1col, width=2)
    c.create_text(p1x, py_pipe-5, text="PS1", font=("Consolas", 8, "bold"), fill=p1col)
    c.create_text(p1x, py_pipe+8, text=f"{'ON' if p1 else 'OFF'}", font=("Consolas", 7), fill=p1col)

    # Pump station 2
    p2x = w*0.62
    p2col = GREEN if p2 else DIM
    c.create_oval(p2x-18, py_pipe-18, p2x+18, py_pipe+18, outline=p2col, width=2)
    c.create_text(p2x, py_pipe-5, text="PS2", font=("Consolas", 8, "bold"), fill=p2col)
    c.create_text(p2x, py_pipe+8, text=f"{'ON' if p2 else 'OFF'}", font=("Consolas", 7), fill=p2col)

    # Chlorine dosing point
    cl_x = w*0.5
    cl_col = ACCENT if cl > 0.1 else RED
    c.create_rectangle(cl_x-12, py_pipe-30, cl_x+12, py_pipe-8, outline=cl_col, width=1)
    c.create_text(cl_x, py_pipe-19, text="Cl₂", font=("Consolas", 8, "bold"), fill=cl_col)
    c.create_line(cl_x, py_pipe-8, cl_x, py_pipe, fill=cl_col, width=2)

    # Gauges
    c.create_text(w*0.8, py_pipe-30, text=f"{psi:.0f} PSI",
                  font=("Consolas", 10, "bold"), fill=GREEN if psi > 30 else RED)
    c.create_text(w*0.8, py_pipe+25, text=f"Cl: {cl:.2f} ppm",
                  font=("Consolas", 8), fill=cl_col)

    # Distribution laterals (branches up/down)
    for bx in [w*0.45, w*0.6, w*0.75]:
        c.create_line(bx, py_pipe, bx, py_pipe - h*0.2, fill=DIM, width=3)
        c.create_line(bx, py_pipe, bx, py_pipe + h*0.2, fill=DIM, width=3)

    if not p1 and not p2:
        c.create_text(w/2, h*0.85, text="PUMP FAILURE", font=("Consolas", 18, "bold"), fill=RED)

    c.create_text(w/2, h-10, text="Protocol: DNP3 TCP :20000 (Industroyer DNP3 target)",
                  font=("Consolas", 7), fill=DIM)


def draw_sensor_network(c, w, h, d):
    """Moscollector M-Bus gateway: 12 sensor nodes, Fuxnet target (87K sensors)."""
    online = d.get('online_sensors', 12)
    corrupted = d.get('corrupted', False)
    total = 12

    # Moscollector header
    c.create_text(w/2, h*0.06, text="MOSCOLLECTOR", font=("Consolas", 9, "bold"),
                  fill=AMBER if not corrupted else RED)
    c.create_text(w/2, h*0.13, text="Moscow water metering infrastructure",
                  font=("Consolas", 7), fill=DIM)

    # Gateway box (center)
    gx, gy = w/2, h*0.42
    gw, gh = 80, 50
    gc = RED if corrupted else ACCENT
    c.create_rectangle(gx-gw/2, gy-gh/2, gx+gw/2, gy+gh/2, outline=gc, width=2)
    c.create_text(gx, gy-8, text="M-BUS", font=("Consolas", 8, "bold"), fill=gc)
    c.create_text(gx, gy+5, text="GATEWAY", font=("Consolas", 7), fill=gc)

    # Sensor nodes in a ring - stagger corruption over time
    t = time.time()
    radius = min(w, h) * 0.30
    for i in range(total):
        angle = 2 * math.pi * i / total - math.pi/2
        sx = gx + radius * math.cos(angle)
        sy = gy + radius * math.sin(angle)
        # Each sensor node corrupts 0.3s apart for dramatic visual
        node_corrupted = corrupted and (t % (total * 0.3)) > i * 0.3
        if node_corrupted:
            blink = int(t * 4 + i) % 2 == 0
            sc = RED if blink else '#880000'
        else:
            sc = GREEN if i < online else DIM
        c.create_line(gx, gy, sx, sy, fill=sc if not node_corrupted else '#3a0000', width=1, dash=(3, 3))
        c.create_oval(sx-7, sy-7, sx+7, sy+7, outline=sc, width=2)
        if node_corrupted:
            c.create_text(sx, sy, text="X", font=("Consolas", 7, "bold"), fill=sc)
        c.create_text(sx, sy+13, text=f"GW{i+1:02d}", font=("Consolas", 5), fill=sc)

    # Status readout
    if corrupted:
        blink2 = int(t * 1.5) % 2 == 0
        status_text = "87,000 SENSORS OFFLINE" if blink2 else "FUXNET: GATEWAY DESTROYED"
        c.create_text(gx, h*0.82, text=status_text, font=("Consolas", 9, "bold"), fill=RED)
        c.create_text(gx, h*0.89, text="M-Bus flood → firmware brick → sensors dead",
                      font=("Consolas", 6), fill='#8b0000')
    else:
        n_show = min(online, total)
        c.create_text(gx, h*0.82, text=f"{n_show}/{total} gateways online",
                      font=("Consolas", 10, "bold"), fill=GREEN)
        c.create_text(gx, h*0.89, text="87,000 field sensors reporting normally",
                      font=("Consolas", 6), fill=DIM)

    c.create_text(w/2, h-10, text="Protocol: M-Bus TCP :5000  |  Fuxnet (Blackjack, 2024)",
                  font=("Consolas", 7), fill=DIM)


def draw_safety_system(c, w, h, d):
    """Safety Instrumented System: controller, process monitor, trip circuit."""
    armed    = d.get('armed', True)
    tripped  = d.get('tripped', False)
    disabled = d.get('disabled', False)
    mon_val  = d.get('monitored_val', 45.0)
    threshold = 90.0

    cx = w / 2

    # SIS controller box
    bx, by, bw, bh = cx-90, h*0.1, 180, 120
    if disabled:
        border = RED
        state_text = "DISABLED"
        state_col  = RED
    elif tripped:
        blink = int(time.time() * 3) % 2 == 0
        border = RED if blink else AMBER
        state_text = "TRIPPED"
        state_col  = AMBER
    elif armed:
        border = GREEN
        state_text = "ARMED"
        state_col  = GREEN
    else:
        border = DIM
        state_text = "DISARMED"
        state_col  = DIM

    c.create_rectangle(bx, by, bx+bw, by+bh, outline=border, width=3)
    c.create_text(cx, by+20, text="TRICONEX SIS", font=("Consolas", 10, "bold"), fill=TEXT)
    c.create_text(cx, by+42, text="Safety Controller", font=("Consolas", 8), fill=DIM)

    # State LED
    c.create_oval(cx-12, by+58, cx+12, by+82, fill=state_col, outline='')
    c.create_text(cx, by+100, text=state_text, font=("Consolas", 11, "bold"), fill=state_col)

    # Process monitor bar
    bar_y = h * 0.55
    bar_w = w * 0.7
    bx0 = cx - bar_w/2
    c.create_text(cx, bar_y - 20, text="Monitored Process Value",
                  font=("Consolas", 8), fill=TEXT)
    c.create_rectangle(bx0, bar_y, bx0+bar_w, bar_y+20, outline=DIM, width=1)
    fill_w = bar_w * (min(100, mon_val) / 100)
    fill_c = RED if mon_val >= threshold else (AMBER if mon_val > threshold*0.8 else GREEN)
    c.create_rectangle(bx0, bar_y, bx0+fill_w, bar_y+20, fill=fill_c, outline='')
    c.create_text(cx, bar_y+10, text=f"{mon_val:.1f}%", font=("Consolas", 8, "bold"), fill='white')
    # Trip threshold marker
    tx_mark = bx0 + bar_w * (threshold / 100)
    c.create_line(tx_mark, bar_y-5, tx_mark, bar_y+25, fill=RED, width=2)
    c.create_text(tx_mark, bar_y+33, text=f"TRIP {threshold:.0f}%",
                  font=("Consolas", 7), fill=RED)

    # State annotation + unprotected warning
    if disabled:
        # Flash "PROCESS UNPROTECTED" when SIS is disabled AND value is climbing
        blink = int(time.time() * 2) % 2 == 0
        warn_col = RED if blink else '#8b0000'
        c.create_text(cx, h*0.80, text="TRITON: SIS NEUTRALIZED",
                      font=("Consolas", 13, "bold"), fill=RED)
        if mon_val >= threshold:
            c.create_text(cx, h*0.88, text="[!] PROCESS UNPROTECTED [!]",
                          font=("Consolas", 11, "bold"), fill=warn_col)
            c.create_text(cx, h*0.94, text="Safety system offline - process escaping limits",
                          font=("Consolas", 7), fill=RED)
        else:
            c.create_text(cx, h*0.88, text="Safety program halted - no trip capability",
                          font=("Consolas", 7), fill=RED)
    elif tripped:
        c.create_text(cx, h*0.82, text="SIS TRIPPED - PROCESS SAFE",
                      font=("Consolas", 10, "bold"), fill=AMBER)
        c.create_text(cx, h*0.89, text="Re-arming in 3 seconds...",
                      font=("Consolas", 7), fill=DIM)

    c.create_text(w/2, h-10, text="Protocols: TriStation UDP :1502 + IEC-104 TCP :2404",
                  font=("Consolas", 7), fill=DIM)


# =========================================================================
# PROCESS DETAIL WINDOW - opened when user clicks a process panel
# =========================================================================

class ProcessDetailWindow:
    """Detail window for a specific process with visualization and protocol-specific controls."""

    def __init__(self, parent, process_name, host, measurements, controls, color,
                 draw_fn=None):
        """
        Args:
            draw_fn: callable(canvas, width, height, data_dict) - draws the process
        """
        self.host = host
        self.running = True
        self.color = color
        self.draw_fn = draw_fn
        self.live_data = {}

        self.win = tk.Toplevel(parent)
        self.win.title(f"mrhOTshOT \u2014 {process_name}")
        self.win.geometry("900x850")
        self.win.configure(bg=BG)
        self.win.protocol("WM_DELETE_WINDOW", self._close)

        # Header
        hdr = tk.Frame(self.win, bg='#1a237e', height=40)
        hdr.pack(fill=tk.X); hdr.pack_propagate(False)
        tk.Label(hdr, text=process_name, font=("Consolas", 14, "bold"),
                bg='#1a237e', fg='white').pack(side=tk.LEFT, padx=12)
        self.status_lbl = tk.Label(hdr, text="", font=("Consolas", 9),
                                    bg='#1a237e', fg='#90caf9')
        self.status_lbl.pack(side=tk.RIGHT, padx=12)

        body = tk.Frame(self.win, bg=BG)
        body.pack(fill=tk.BOTH, expand=True, padx=8, pady=8)

        # LEFT: Visualization + Measurements
        left = tk.Frame(body, bg=BG)
        left.pack(side=tk.LEFT, fill=tk.BOTH, expand=True, padx=(0, 4))

        # Process visualization canvas
        viz_frame = tk.LabelFrame(left, text="  Process Visualization  ",
                                   font=("Consolas", 10, "bold"),
                                   bg=PANEL, fg=color, bd=1, relief=tk.GROOVE)
        viz_frame.pack(fill=tk.BOTH, expand=True, pady=(0, 6))
        self.canvas = tk.Canvas(viz_frame, bg='#0d1117', highlightthickness=0)
        self.canvas.pack(fill=tk.BOTH, expand=True, padx=4, pady=4)

        # Measurements below canvas
        meas_frame = tk.LabelFrame(left, text="  Measurements  ",
                                    font=("Consolas", 10, "bold"),
                                    bg=PANEL, fg=color, bd=1, relief=tk.GROOVE)
        meas_frame.pack(fill=tk.X)

        self.meas_labels = {}
        for label, unit in measurements:
            row = tk.Frame(meas_frame, bg=PANEL)
            row.pack(fill=tk.X, padx=10, pady=1)
            tk.Label(row, text=f"{label}:", font=("Consolas", 9),
                    bg=PANEL, fg=TEXT).pack(side=tk.LEFT)
            val = tk.Label(row, text="--", font=("Consolas", 11, "bold"),
                          bg=PANEL, fg=color)
            val.pack(side=tk.RIGHT)
            tk.Label(row, text=f" {unit}", font=("Consolas", 8),
                    bg=PANEL, fg=DIM).pack(side=tk.RIGHT)
            self.meas_labels[label] = val

        # RIGHT: Controls (scrollable)
        right = tk.Frame(body, bg=BG, width=320)
        right.pack(side=tk.RIGHT, fill=tk.Y, padx=(4, 0))
        right.pack_propagate(False)

        ctrl_frame = tk.LabelFrame(right, text="  Controls  ",
                                    font=("Consolas", 10, "bold"),
                                    bg=PANEL, fg=AMBER, bd=1, relief=tk.GROOVE)
        ctrl_frame.pack(fill=tk.BOTH, expand=True)

        # Scrollable control list
        ctrl_inner = tk.Frame(ctrl_frame, bg=PANEL)
        ctrl_inner.pack(fill=tk.BOTH, expand=True, padx=4, pady=4)

        for label, proto_desc, cmd_fn in controls:
            btn = tk.Button(ctrl_inner, text=f"  \u25b6  {label}", font=("Consolas", 9),
                           bg='#1a1a1a', fg='#8a9ba8', activebackground='#252525',
                           activeforeground='#b0bec5', bd=1, relief=tk.GROOVE,
                           anchor='w', padx=6, cursor='hand2',
                           command=lambda fn=cmd_fn, l=label, p=proto_desc: self._exec(fn, l, p))
            btn.pack(fill=tk.X, pady=2, padx=2)
            tk.Label(ctrl_inner, text=f"     \u2192 {proto_desc}", font=("Consolas", 7),
                    bg=PANEL, fg='#3d4f5f', anchor='w').pack(fill=tk.X)

        # Start redraw timer
        self._redraw()

    def _redraw(self):
        """Redraw process visualization."""
        if not self.running:
            return
        if self.draw_fn:
            c = self.canvas
            w = c.winfo_width()
            h = c.winfo_height()
            if w > 10 and h > 10:
                c.delete('all')
                self.draw_fn(c, w, h, self.live_data)
        self.canvas.after(200, self._redraw)

    def _exec(self, cmd_fn, label, proto_desc):
        """Execute command in background thread with full button-action logging."""
        import traceback as _tb, datetime as _dt

        self._apply_optimistic_update(label)

        def _run():
            ts      = _dt.datetime.now().strftime('%Y-%m-%d %H:%M:%S.%f')[:-3]
            elapsed = 0.0
            try:
                self.win.after(0, lambda: self.status_lbl.config(
                    text=f"\u23f3 Sending: {label}...", fg='#ffab00'))
                t0     = time.time()
                result = cmd_fn()
                elapsed = time.time() - t0
                response = str(result) if result is not None else 'ACK (no return value)'
                msg    = f"\u2714 {label} ({elapsed:.1f}s)"
                self.win.after(0, lambda: self.status_lbl.config(text=msg, fg='#00e676'))
                _btn_log.info(
                    "[OK]     %s | elapsed=%.3fs\n"
                    "         BUTTON:   %s\n"
                    "         PROTO:    %s\n"
                    "         HOST:     %s\n"
                    "         REQUEST:  %s\n"
                    "         RESPONSE: %s",
                    ts, elapsed,
                    label, proto_desc, self.host,
                    proto_desc,   # request = protocol + params as described by the button
                    response      # response = full return string from send_* (includes bytes)
                )
            except Exception as e:
                elapsed = time.time() - t0 if 't0' in dir() else 0.0
                full_tb = _tb.format_exc().strip()
                msg    = f"\u2718 FAILED: {e}"
                self.win.after(0, lambda: self.status_lbl.config(text=msg, fg='#ff1744'))
                _btn_log.error(
                    "[FAILED] %s | elapsed=%.3fs\n"
                    "         BUTTON:   %s\n"
                    "         PROTO:    %s\n"
                    "         HOST:     %s\n"
                    "         REQUEST:  %s\n"
                    "         ERROR:    %s\n"
                    "         TRACEBACK:\n%s",
                    ts, elapsed,
                    label, proto_desc, self.host,
                    proto_desc,
                    str(e),
                    full_tb
                )
        threading.Thread(target=_run, daemon=True).start()

    def _apply_optimistic_update(self, label):
        """Immediately update live_data based on the button label."""
        l = label.lower()
        d = self.live_data
        if 'open inlet' in l or 'open upstream' in l or 'open hot water' in l:
            d['inlet'] = True; d['upstream'] = True; d['heating'] = True
        elif 'close inlet' in l or 'close upstream' in l or 'close hot water' in l:
            d['inlet'] = False; d['upstream'] = False; d['heating'] = False
        elif 'open outlet' in l or 'open downstream' in l or 'open chilled' in l:
            d['outlet'] = True; d['downstream'] = True; d['cooling'] = True
        elif 'close outlet' in l or 'close downstream' in l or 'close chilled' in l:
            d['outlet'] = False; d['downstream'] = False; d['cooling'] = False
        elif 'start pump' in l or 'start comp' in l or 'start ahu' in l or 'start conv' in l:
            d['pump'] = True; d['compressor'] = True; d['fan'] = True; d['running'] = True
        elif 'stop pump' in l or 'stop comp' in l or 'stop ahu' in l or 'stop conv' in l:
            d['pump'] = False; d['compressor'] = False; d['fan'] = False; d['running'] = False
        elif 'open breaker 1' in l:
            d['brk1'] = False
        elif 'close breaker 1' in l:
            d['brk1'] = True
        elif 'open breaker 2' in l:
            d['brk2'] = False
        elif 'close breaker 2' in l:
            d['brk2'] = True
        elif 'open breaker 3' in l:
            d['brk3'] = False
        elif 'close breaker 3' in l:
            d['brk3'] = True
        elif 'goose trip' in l:
            d['brk1'] = False; d['brk2'] = False; d['brk3'] = False
            d['voltage'] = 0; d['tripped'] = True
        elif 'disable sis' in l or 'triton' in l or 'halt' in l:
            d['disabled'] = True; d['armed'] = False
        elif 'reset sis' in l:
            d['sis_tripped'] = False; d['e_stop'] = False; d['disabled'] = False; d['armed'] = True
        elif 'sis trip' in l or 'trip safety' in l:
            d['tripped'] = True; d['sis_tripped'] = True
            d['inlet'] = False; d['pump'] = False; d['outlet'] = True
        elif 'arm safety' in l:
            d['armed'] = True; d['tripped'] = False; d['disabled'] = False
        elif 'emergency' in l or 'e-stop' in l:
            d['inlet'] = False; d['pump'] = False; d['outlet'] = True
            d['sis_tripped'] = True
            d['upstream'] = False; d['compressor'] = False; d['running'] = False
            d['e_stop'] = True
        elif 'start circulation' in l:
            d['pump'] = True
        elif 'stop circulation' in l:
            d['pump'] = False
        elif 'open heat exchanger' in l:
            d['valve'] = True
        elif 'close heat exchanger' in l:
            d['valve'] = False
        elif 'start pump station 1' in l:
            d['pump1'] = True
        elif 'stop pump station 1' in l:
            d['pump1'] = False
        elif 'start pump station 2' in l:
            d['pump2'] = True
        elif 'stop pump station 2' in l:
            d['pump2'] = False

    def update_measurement(self, label, value, fmt=".1f"):
        if label in self.meas_labels:
            try: text = f"{float(value):{fmt}}"
            except (ValueError, TypeError): text = str(value)
            self.meas_labels[label].config(text=text)

    def _close(self):
        self.running = False
        self.win.destroy()


# =========================================================================
# PROCESS PANEL (overview grid cell - clickable)
# =========================================================================

class ProcessPanel:
    def __init__(self, parent, name, icon, unit_labels, color=ACCENT):
        self.name = name
        self.frame = tk.LabelFrame(parent, text=f"  {icon} {name}  ",
                                    font=("Consolas", 11, "bold"),
                                    bg=PANEL, fg=color, bd=1, relief=tk.GROOVE,
                                    labelanchor='n', cursor='hand2')
        self.frame.pack_propagate(False)
        self.values = {}
        self.statuses = {}
        self.on_click = None
        self._build(unit_labels, color)
        self.frame.bind('<Button-1>', lambda e: self._clicked())
        # Bind children too
        for child in self.frame.winfo_children():
            child.bind('<Button-1>', lambda e: self._clicked())

    def _build(self, unit_labels, color):
        meas_frame = tk.Frame(self.frame, bg=PANEL)
        meas_frame.pack(fill=tk.X, padx=8, pady=(4, 2))
        for label, unit in unit_labels:
            row = tk.Frame(meas_frame, bg=PANEL)
            row.pack(fill=tk.X, pady=1)
            row.bind('<Button-1>', lambda e: self._clicked())
            lbl = tk.Label(row, text=f"{label}:", font=("Consolas", 9), bg=PANEL, fg=DIM)
            lbl.pack(side=tk.LEFT)
            lbl.bind('<Button-1>', lambda e: self._clicked())
            val = tk.Label(row, text="--", font=("Consolas", 11, "bold"), bg=PANEL, fg=color)
            val.pack(side=tk.RIGHT)
            val.bind('<Button-1>', lambda e: self._clicked())
            ulbl = tk.Label(row, text=f" {unit}", font=("Consolas", 8), bg=PANEL, fg=DIM)
            ulbl.pack(side=tk.RIGHT)
            ulbl.bind('<Button-1>', lambda e: self._clicked())
            self.values[label] = val
        self.status_frame = tk.Frame(self.frame, bg=PANEL)
        self.status_frame.pack(fill=tk.X, padx=8, pady=(4, 2))
        self.status_frame.bind('<Button-1>', lambda e: self._clicked())
        self.alarm_bar = tk.Label(self.frame, text="", font=("Consolas", 9, "bold"), bg=PANEL, fg=DIM)
        self.alarm_bar.pack(fill=tk.X, padx=8, pady=(0, 4))
        self.alarm_bar.bind('<Button-1>', lambda e: self._clicked())
        # Click hint
        hint = tk.Label(self.frame, text="click to control \u25b6", font=("Consolas", 7),
                       bg=PANEL, fg=DIM)
        hint.pack(pady=(0, 4))
        hint.bind('<Button-1>', lambda e: self._clicked())

    def _clicked(self):
        if self.on_click:
            self.on_click()

    def set_value(self, label, value, fmt=".1f"):
        if label in self.values:
            try: text = f"{float(value):{fmt}}"
            except (ValueError, TypeError): text = str(value)
            self.values[label].config(text=text)

    def set_alarm(self, text, active=False):
        if active:
            blink = int(time.time() * 2) % 2 == 0
            self.alarm_bar.config(text=f"\u26a0 {text}", fg=RED if blink else AMBER)
        else:
            self.alarm_bar.config(text="Normal", fg=GREEN)

    def add_status_dot(self, name, label_text):
        dot = tk.Label(self.status_frame, text=f"\u25cf {label_text}",
                      font=("Consolas", 8), bg=PANEL, fg=DIM)
        dot.pack(side=tk.LEFT, padx=3)
        dot.bind('<Button-1>', lambda e: self._clicked())
        self.statuses[name] = dot

    def set_status(self, name, active):
        if name in self.statuses:
            self.statuses[name].config(fg=GREEN if active else RED)


# =========================================================================
# MAIN HMI
# =========================================================================

class UnifiedHMI:
    def __init__(self, root, plc_ip='127.0.0.1', config=None):
        log.info("UnifiedHMI.__init__ start  plc_ip=%s", plc_ip)
        self.root = root
        self.plc_ip = plc_ip
        self.config = config or {}
        self.running = True
        self.detail_windows = {}

        self.root.title(f"mrhOTshOT \u2014 Industrial Plant Control [{plc_ip}]")
        self.root.geometry("1400x950")
        self.root.configure(bg=BG)
        log.info("Tk window configured OK")

        self.water_data = {}
        self.power_data = {}
        self.proto_status = {name: False for name, _, _, _ in PROTOCOLS}

        log.info("Calling _build_ui ...")
        self._build_ui()
        log.info("_build_ui complete")

        self.gas_data = {}
        self.hvac_data = {}
        self.mfg_data = {}
        self.centrifuge_data = {}
        self.centrifuge_masked = False
        self.boiler_data = {}
        self.heating_data = {}
        self.water_utility_data = {}
        self.sensor_data = {}
        self.sis_data = {}

        threading.Thread(target=self._poll_protocols, daemon=True).start()
        threading.Thread(target=self._poll_water, daemon=True).start()
        threading.Thread(target=self._poll_power, daemon=True).start()
        threading.Thread(target=self._poll_gas, daemon=True).start()
        threading.Thread(target=self._poll_hvac, daemon=True).start()
        threading.Thread(target=self._poll_centrifuge, daemon=True).start()
        threading.Thread(target=self._poll_boiler, daemon=True).start()
        threading.Thread(target=self._poll_heating, daemon=True).start()
        threading.Thread(target=self._poll_water_utility, daemon=True).start()
        threading.Thread(target=self._poll_sensors, daemon=True).start()
        threading.Thread(target=self._poll_sis, daemon=True).start()
        threading.Thread(target=self._init_auto_mode, daemon=True).start()

        self._tick()
        self.root.protocol("WM_DELETE_WINDOW", self._on_close)

    def _get_host(self, process):
        """Get host IP for a process (from config or default)."""
        if self.config and process in self.config:
            return self.config[process].get('host', self.plc_ip)
        return self.plc_ip

    def _init_auto_mode(self):
        """Send AUTO mode command to all PLCs on startup."""
        import time as _time
        _time.sleep(3)  # Wait for PLCs to be polled at least once
        cmds = [
            ('water_treatment', lambda h: send_modbus(h, 3, True)),        # Modbus coil 3
            ('gas_pipeline',    lambda h: send_opcua(h, 'Commands/AutoModeCommand', True)),  # OPC-UA
            # manufacturing removed - PLC-4 now runs centrifuge cascade
            ('building_hvac',   lambda h: send_bacnet(h, 1, 3, 1.0)),     # BACnet AO[3] = auto ON (Real, not bool)
            ('boiler_house',    lambda h: send_modbus(h, 3, True, 5020)),  # ABB Modbus coil 3
        ]
        for process, cmd in cmds:
            try:
                h = self._get_host(process)
                cmd(h)
                print(f"[INIT] AUTO mode set: {process} ({h})")
            except Exception as e:
                print(f"[INIT] AUTO mode failed: {process} - {e}")

    def _build_ui(self):
        log.info("_build_ui: start")
        try:
            self._build_ui_inner()
        except Exception as e:
            log.critical("_build_ui CRASH: %s", e, exc_info=True)
            raise

    def _build_ui_inner(self):
        top = tk.Frame(self.root, bg='#1a237e', height=40)
        top.pack(fill=tk.X); top.pack_propagate(False)
        tk.Label(top, text="mrhOTshOT \u2014 Multi-Process Industrial Plant",
                font=("Consolas", 14, "bold"), bg='#1a237e', fg='white').pack(side=tk.LEFT, padx=12)
        self.clock_lbl = tk.Label(top, font=("Consolas", 10), bg='#1a237e', fg='#90caf9')
        self.clock_lbl.pack(side=tk.RIGHT, padx=12)

        grid = tk.Frame(self.root, bg=BG)
        grid.pack(fill=tk.BOTH, expand=True, padx=6, pady=6)
        for i in range(3): grid.columnconfigure(i, weight=1)
        for i in range(4): grid.rowconfigure(i, weight=1)

        # 1. Water Treatment
        self.water_panel = ProcessPanel(grid, "Water Treatment Plant", "\U0001F4A7",
            [("Level", "%"), ("Pressure", "bar"), ("Temp", "\u00b0C"),
             ("Mode", "")], ACCENT)
        self.water_panel.frame.grid(row=0, column=0, sticky='nsew', padx=3, pady=3)
        self.water_panel.add_status_dot('inlet', 'Inlet')
        self.water_panel.add_status_dot('outlet', 'Outlet')
        self.water_panel.add_status_dot('pump', 'Pump')
        self.water_panel.on_click = self._open_water_detail

        # 2. Power Substation
        self.power_panel = ProcessPanel(grid, "Power Substation 13.8kV", "\u26a1",
            [("Voltage", "kV"), ("Current", "A"), ("Xfmr Temp", "\u00b0C"),
             ("Power", "MW"), ("Frequency", "Hz")], AMBER)
        self.power_panel.frame.grid(row=0, column=1, sticky='nsew', padx=3, pady=3)
        self.power_panel.add_status_dot('brk1', 'BRK1')
        self.power_panel.add_status_dot('brk2', 'BRK2')
        self.power_panel.add_status_dot('brk3', 'BRK3')
        self.power_panel.on_click = self._open_power_detail

        # 3. Gas Pipeline
        self.gas_panel = ProcessPanel(grid, "Gas Pipeline Compressor", "\U0001F525",
            [("Out Press", "PSI"), ("In Press", "PSI"), ("Gas Temp", "\u00b0F"),
             ("Flow", "SCF/m"), ("Vibration", "mm/s")], '#ff6d00')
        self.gas_panel.frame.grid(row=0, column=2, sticky='nsew', padx=3, pady=3)
        self.gas_panel.add_status_dot('upstream', 'UpVlv')
        self.gas_panel.add_status_dot('downstream', 'DnVlv')
        self.gas_panel.add_status_dot('compressor', 'Comp')
        self.gas_panel.on_click = self._open_gas_detail

        # 4. HVAC
        self.hvac_panel = ProcessPanel(grid, "Building HVAC System", "\u2744",
            [("Zone Temp", "\u00b0C"), ("Supply Air", "\u00b0C"), ("Humidity", "%RH"),
             ("Duct Press", "inWC"), ("Outdoor", "\u00b0C")], GREEN)
        self.hvac_panel.frame.grid(row=1, column=0, sticky='nsew', padx=3, pady=3)
        self.hvac_panel.add_status_dot('fan', 'Fan')
        self.hvac_panel.add_status_dot('heating', 'Heat')
        self.hvac_panel.add_status_dot('cooling', 'Cool')
        self.hvac_panel.on_click = self._open_hvac_detail

        # 5. Centrifuge Cascade (Stuxnet target)
        self.centrifuge_panel = ProcessPanel(grid, "Centrifuge Cascade (Stuxnet)", "\u2622",
            [("C1 Speed", "Hz"), ("C2 Speed", "Hz"), ("C3 Speed", "Hz"),
             ("Max Vib", "g"), ("Status", "")], '#e040fb')
        self.centrifuge_panel.frame.grid(row=1, column=1, sticky='nsew', padx=3, pady=3)
        self.centrifuge_panel.add_status_dot('c1', 'C1')
        self.centrifuge_panel.add_status_dot('c2', 'C2')
        self.centrifuge_panel.add_status_dot('c3', 'C3')
        self.centrifuge_panel.on_click = self._open_centrifuge_detail

        # 6. Boiler House
        self.boiler_panel = ProcessPanel(grid, "Boiler House (ABB)", "\U0001F525",
            [("Drum Level", "%"), ("Steam Press", "bar"), ("Steam Temp", "\u00b0C"),
             ("Fuel Flow", "%")], '#ff8a65')
        self.boiler_panel.frame.grid(row=1, column=2, sticky='nsew', padx=3, pady=3)
        self.boiler_panel.add_status_dot('burner', 'Burner')
        self.boiler_panel.add_status_dot('fw_pump', 'FW Pump')
        self.boiler_panel.add_status_dot('safety', 'Safety')
        self.boiler_panel.on_click = self._open_boiler_detail

        # 7. Heating District
        self.heating_panel = ProcessPanel(grid, "Heating District (FrostyGoop)", "\U0001F321",
            [("Supply Temp", "\u00b0C"), ("Return Temp", "\u00b0C"),
             ("Flow Rate", "m\u00b3/h"), ("Outdoor", "\u00b0C")], '#ff6f00')
        self.heating_panel.frame.grid(row=2, column=0, sticky='nsew', padx=3, pady=3)
        self.heating_panel.add_status_dot('pump', 'Pump')
        self.heating_panel.add_status_dot('valve', 'HEX Vlv')
        self.heating_panel.on_click = self._open_heating_detail

        # 8. Water Utility DNP3
        self.water_utility_panel = ProcessPanel(grid, "Water Utility DNP3", "\U0001F4A7",
            [("Reservoir", "%"), ("Pressure", "PSI"),
             ("Flow Rate", "gal/m"), ("Chlorine", "ppm")], '#29b6f6')
        self.water_utility_panel.frame.grid(row=2, column=1, sticky='nsew', padx=3, pady=3)
        self.water_utility_panel.add_status_dot('pump1', 'PS1')
        self.water_utility_panel.add_status_dot('pump2', 'PS2')
        self.water_utility_panel.on_click = self._open_water_utility_detail

        # 9. Moscollector M-Bus Sensor Network (Fuxnet target)
        self.sensor_panel = ProcessPanel(grid, "Moscollector M-Bus (Fuxnet)", "\U0001F4E1",
            [("Online", "sensors"), ("Avg Flow", "m\u00b3/h"),
             ("Avg Pressure", "bar"), ("Status", "")], '#ab47bc')
        self.sensor_panel.frame.grid(row=2, column=2, sticky='nsew', padx=3, pady=3)
        self.sensor_panel.add_status_dot('gateway', 'GW')
        self.sensor_panel.on_click = self._open_sensors_detail

        # 10. Safety System (SIS)
        self.sis_panel = ProcessPanel(grid, "Safety System (TRITON)", "\U0001F6A8",
            [("State", ""), ("Monitored", "%"),
             ("Threshold", "%"), ("Watchdog", "s")], RED)
        self.sis_panel.frame.grid(row=3, column=0, sticky='nsew', padx=3, pady=3)
        self.sis_panel.add_status_dot('armed', 'Armed')
        self.sis_panel.add_status_dot('disabled', 'Disabled')
        self.sis_panel.on_click = self._open_sis_detail

        # 11. Protocol Status
        proto_frame = tk.LabelFrame(grid, text="  \U0001F4E1 Protocol Status  ",
                                     font=("Consolas", 11, "bold"),
                                     bg=PANEL, fg=ACCENT, bd=1, relief=tk.GROOVE, labelanchor='n')
        proto_frame.grid(row=3, column=1, columnspan=2, sticky='nsew', padx=3, pady=3)

        self.proto_dots = {}
        for name, port, _, process in PROTOCOLS:
            row = tk.Frame(proto_frame, bg=PANEL)
            row.pack(fill=tk.X, padx=6, pady=1)
            dot = tk.Label(row, text="\u25cf", font=("Arial", 10), bg=PANEL, fg=DIM)
            dot.pack(side=tk.LEFT)
            tk.Label(row, text=f" {name}", font=("Consolas", 8), bg=PANEL, fg=TEXT).pack(side=tk.LEFT)
            tk.Label(row, text=f":{port}", font=("Consolas", 7), bg=PANEL, fg=DIM).pack(side=tk.RIGHT)
            self.proto_dots[name] = dot

        self.proto_summary = tk.Label(proto_frame, text="0/10", font=("Consolas", 12, "bold"),
                                       bg=PANEL, fg=DIM)
        self.proto_summary.pack(pady=(6, 2))

        # Bottom bar
        ctrl = tk.Frame(self.root, bg='#1a237e', height=32)
        ctrl.pack(fill=tk.X); ctrl.pack_propagate(False)
        self.status_bar = tk.Label(ctrl, text="Click any process panel to open controls",
                                   font=("Consolas", 9), bg='#1a237e', fg='#90caf9')
        self.status_bar.pack(side=tk.LEFT, padx=12)

    # ---- DETAIL WINDOW OPENERS ----

    def _open_water_detail(self):
        if 'water' in self.detail_windows and self.detail_windows['water'].running:
            self.detail_windows['water'].win.lift()
            return
        h = self._get_host('water_treatment')
        controls = [
            ("Open Inlet Valve",     "IEC-104 :2404 (C_SC_NA_1 IOA 300)",
             lambda: send_iec104(h, 300, True)),
            ("Close Inlet Valve",    "IEC-104 :2404 (C_SC_NA_1 IOA 300)",
             lambda: send_iec104(h, 300, False)),
            ("Open Outlet Valve",    "IEC-104 :2404 (C_SC_NA_1 IOA 301)",
             lambda: send_iec104(h, 301, True)),
            ("Close Outlet Valve",   "IEC-104 :2404 (C_SC_NA_1 IOA 301)",
             lambda: send_iec104(h, 301, False)),
            ("Start Pump",           "IEC-104 :2404 (C_SC_NA_1 IOA 302)",
             lambda: send_iec104(h, 302, True)),
            ("Stop Pump",            "IEC-104 :2404 (C_SC_NA_1 IOA 302)",
             lambda: send_iec104(h, 302, False)),
            ("Switch to MANUAL",     "IEC-104 :2404 (C_SC_NA_1 IOA 303 OFF)",
             lambda: send_iec104(h, 303, False)),
            ("Switch to AUTO",       "IEC-104 :2404 (C_SC_NA_1 IOA 303 ON)",
             lambda: send_iec104(h, 303, True)),
            ("SIS TRIP",             "IEC-104 :2404 (C_SC_NA_1 IOA 304 ON)",
             lambda: send_iec104(h, 304, True)),
            ("Reset SIS",            "IEC-104 :2404 (C_SC_NA_1 IOA 304 OFF)",
             lambda: send_iec104(h, 304, False)),
            ("Disable SIS (TRITON)", "TriStation UDP :1502 (HALT PROGRAM)",
             lambda: send_tristation_halt(h)),
        ]
        self.detail_windows['water'] = ProcessDetailWindow(
            self.root, "Water Treatment Plant", h,
            [("Level", "%"), ("Pressure", "bar"), ("Temp", "\u00b0C"),
             ("Mode", "")],
            controls, ACCENT, draw_fn=draw_water_tank)

    def _open_power_detail(self):
        if 'power' in self.detail_windows and self.detail_windows['power'].running:
            self.detail_windows['power'].win.lift()
            return
        h = self._get_host('power_substation')
        ld = "WaterTankLD"
        controls = [
            ("Open Breaker 1 (Incoming)", "IEC 61850 MMS :8102",
             lambda: send_iec61850(h, f"{ld}/CSWI1.Pos1.Oper.ctlVal", False)),
            ("Close Breaker 1 (Incoming)", "IEC 61850 MMS :8102",
             lambda: send_iec61850(h, f"{ld}/CSWI1.Pos1.Oper.ctlVal", True)),
            ("Open Breaker 2 (Bus-Tie)", "IEC 61850 MMS :8102",
             lambda: send_iec61850(h, f"{ld}/CSWI1.Pos3.Oper.ctlVal", False)),
            ("Close Breaker 2 (Bus-Tie)", "IEC 61850 MMS :8102",
             lambda: send_iec61850(h, f"{ld}/CSWI1.Pos3.Oper.ctlVal", True)),
            ("Open Breaker 3 (Outgoing)", "IEC 61850 MMS :8102",
             lambda: send_iec61850(h, f"{ld}/CSWI1.Pos2.Oper.ctlVal", False)),
            ("Close Breaker 3 (Outgoing)", "IEC 61850 MMS :8102",
             lambda: send_iec61850(h, f"{ld}/CSWI1.Pos2.Oper.ctlVal", True)),
            ("Disable Protection Relay", "IEC 61850 MMS :8102",
             lambda: send_iec61850(h, f"{ld}/CSWI1.Pos4.Oper.ctlVal", False)),
            ("GOOSE TRIP (all breakers)", "IEC 61850 GOOSE :8102",
             lambda: send_iec61850_goose_trip(h)),
        ]
        self.detail_windows['power'] = ProcessDetailWindow(
            self.root, "Power Substation 13.8kV", h,
            [("Voltage", "kV"), ("Current", "A"), ("Xfmr Temp", "\u00b0C"),
             ("Power", "MW"), ("Frequency", "Hz")],
            controls, AMBER, draw_fn=draw_substation)

    def _open_gas_detail(self):
        if 'gas' in self.detail_windows and self.detail_windows['gas'].running:
            self.detail_windows['gas'].win.lift()
            return
        h = self._get_host('gas_pipeline')
        controls = [
            ("Open Upstream Valve",    "OPC-UA :4840 (Commands/InletValveCommand)",
             lambda: send_opcua(h, "Commands/InletValveCommand", True)),
            ("Close Upstream Valve",   "OPC-UA :4840",
             lambda: send_opcua(h, "Commands/InletValveCommand", False)),
            ("Open Downstream Valve",  "OPC-UA :4840 (Commands/OutletValveCommand)",
             lambda: send_opcua(h, "Commands/OutletValveCommand", True)),
            ("Close Downstream Valve", "OPC-UA :4840",
             lambda: send_opcua(h, "Commands/OutletValveCommand", False)),
            ("Start Compressor",       "OPC-UA :4840 (Commands/PumpCommand)",
             lambda: send_opcua(h, "Commands/PumpCommand", True)),
            ("Stop Compressor",        "OPC-UA :4840",
             lambda: send_opcua(h, "Commands/PumpCommand", False)),
            ("Emergency Shutdown",     "OPC-UA :4840 (Commands/SisTrip)",
             lambda: send_opcua(h, "Commands/SisTripCommand", True)),
        ]
        self.detail_windows['gas'] = ProcessDetailWindow(
            self.root, "Gas Pipeline Compressor Station", h,
            [("Outlet Pressure", "PSI"), ("Inlet Pressure", "PSI"),
             ("Gas Temp", "\u00b0F"), ("Flow Rate", "SCF/min"), ("Vibration", "mm/s")],
            controls, '#ff6d00', draw_fn=draw_pipeline)

    def _open_hvac_detail(self):
        if 'hvac' in self.detail_windows and self.detail_windows['hvac'].running:
            self.detail_windows['hvac'].win.lift()
            return
        h = self._get_host('building_hvac')
        controls = [
            # Switch mode FIRST - manual controls only take effect when AUTO is off
            ("Switch to MANUAL",           "BACnet :47808 (AO[3] = 0.0)",
             lambda: send_bacnet(h, 1, 3, 0.0)),
            ("Switch to AUTO",             "BACnet :47808 (AO[3] = 1.0)",
             lambda: send_bacnet(h, 1, 3, 1.0)),
            # Valve controls - send Real floats, not booleans (bacpypes3 requires Real for AO)
            ("Open Hot Water Valve (Heat)", "BACnet :47808 (AO[0] = 100.0%)",
             lambda: send_bacnet(h, 1, 0, 100.0)),
            ("Close Hot Water Valve",       "BACnet :47808 (AO[0] = 0.0%)",
             lambda: send_bacnet(h, 1, 0, 0.0)),
            ("Open Chilled Water (Cool)",   "BACnet :47808 (AO[1] = 100.0%)",
             lambda: send_bacnet(h, 1, 1, 100.0)),
            ("Close Chilled Water",         "BACnet :47808 (AO[1] = 0.0%)",
             lambda: send_bacnet(h, 1, 1, 0.0)),
            ("Start AHU Fan",              "BACnet :47808 (AO[2] = 1.0)",
             lambda: send_bacnet(h, 1, 2, 1.0)),
            ("Stop AHU Fan",               "BACnet :47808 (AO[2] = 0.0)",
             lambda: send_bacnet(h, 1, 2, 0.0)),
        ]
        self.detail_windows['hvac'] = ProcessDetailWindow(
            self.root, "Building HVAC System", h,
            [("Zone Temp", "\u00b0C"), ("Supply Air", "\u00b0C"),
             ("Humidity", "%RH"), ("Duct Pressure", "inWC"), ("Outdoor Temp", "\u00b0C")],
            controls, GREEN, draw_fn=draw_hvac)

    def _open_centrifuge_detail(self):
        if 'centrifuge' in self.detail_windows and self.detail_windows['centrifuge'].running:
            self.detail_windows['centrifuge'].win.lift()
            return
        h = self._get_host('centrifuge_cascade')
        # Operator-only controls - attack actions live in the attacker demo portal
        controls = [
            ("Restore Normal Speed (1007 Hz)", "S7 :102 (DB3 - operator recovery)",
             lambda: [send_s7(h, 3, o, 1007.0) for o in (0, 4, 8)]),
            ("Emergency Stop All",             "S7 :102 (DB3 speed = 0)",
             lambda: [send_s7(h, 3, o, 0.0) for o in (0, 4, 8)]),
        ]
        dw = ProcessDetailWindow(
            self.root, "Centrifuge Cascade A - Natanz FEP", h,
            [("C1 Speed Hz", "Hz"), ("C2 Speed Hz", "Hz"), ("C3 Speed Hz", "Hz"),
             ("Max Vibration g", "g"), ("Rootkit Active", "")],
            controls, '#e040fb', draw_fn=draw_centrifuge_cascade)
        dw.live_data.update(self.centrifuge_data)
        dw.live_data['rootkit_active'] = self.centrifuge_masked
        self.detail_windows['centrifuge'] = dw

    def _open_mfg_detail(self):
        if 'mfg' in self.detail_windows and self.detail_windows['mfg'].running:
            self.detail_windows['mfg'].win.lift()
            return
        h = self._get_host('manufacturing')
        controls = [
            ("Start Conveyor",    "S7 :102 (DB3.DBX0.0 write)",
             lambda: send_s7(h, 3, 0, True)),
            ("Stop Conveyor",     "S7 :102 (DB3.DBX0.0 write)",
             lambda: send_s7(h, 3, 0, False)),
            ("E-STOP",            "S7 :102 (DB3.DBX0.4 write)",
             lambda: send_s7(h, 3, 4, True)),
            ("Reset E-Stop",      "S7 :102 (DB3.DBX0.4 write)",
             lambda: send_s7(h, 3, 4, False)),
            ("Speed 100%",        "S7 :102 (DB4.DBD0 float write)",
             lambda: send_s7(h, 4, 0, 100.0)),
            ("Speed 50%",         "S7 :102 (DB4.DBD0 float write)",
             lambda: send_s7(h, 4, 0, 50.0)),
            ("Switch to AUTO",    "S7 :102 (DB3.DBX0.3 write)",
             lambda: send_s7(h, 3, 3, True)),
        ]
        self.detail_windows['mfg'] = ProcessDetailWindow(
            self.root, "Manufacturing Line", h,
            [("Hopper Level", "%"), ("Hydraulic Press", "bar"),
             ("Motor Temp", "\u00b0C"), ("Motor Current", "A"), ("Product Count", "pcs")],
            controls, '#e040fb', draw_fn=draw_manufacturing)

    def _open_boiler_detail(self):
        if 'boiler' in self.detail_windows and self.detail_windows['boiler'].running:
            self.detail_windows['boiler'].win.lift()
            return
        h = self._get_host('boiler_house')
        controls = [
            ("Start Burner",       "ABB Modbus :5020 (FC05 coil 2)",
             lambda: send_modbus(h, 2, True, 5020)),
            ("Stop Burner",        "ABB Modbus :5020 (FC05 coil 2)",
             lambda: send_modbus(h, 2, False, 5020)),
            ("Start FW Pump",      "ABB Modbus :5020 (FC05 coil 0)",
             lambda: send_modbus(h, 0, True, 5020)),
            ("Stop FW Pump",       "ABB Modbus :5020 (FC05 coil 0)",
             lambda: send_modbus(h, 0, False, 5020)),
            ("Open Blowdown",      "ABB Modbus :5020 (FC05 coil 1)",
             lambda: send_modbus(h, 1, True, 5020)),
            ("Close Blowdown",     "ABB Modbus :5020 (FC05 coil 1)",
             lambda: send_modbus(h, 1, False, 5020)),
            ("Switch to AUTO",     "ABB Modbus :5020 (FC05 coil 3)",
             lambda: send_modbus(h, 3, True, 5020)),
            ("Switch to MANUAL",   "ABB Modbus :5020 (FC05 coil 3)",
             lambda: send_modbus(h, 3, False, 5020)),
            ("Emergency Shutdown",  "ABB Modbus :5020 (FC05 coil 4)",
             lambda: send_modbus(h, 4, True, 5020)),
        ]
        self.detail_windows['boiler'] = ProcessDetailWindow(
            self.root, "Boiler House (ABB AC500)", h,
            [("Drum Level", "%"), ("Steam Pressure", "bar"),
             ("Steam Temp", "\u00b0C"), ("Fuel Flow", "%")],
            controls, '#ff8a65', draw_fn=draw_boiler)

    def _open_heating_detail(self):
        if 'heating' in self.detail_windows and self.detail_windows['heating'].running:
            self.detail_windows['heating'].win.lift(); return
        h = self._get_host('heating_district')
        controls = [
            # ENCO ENC-12X slave ID 11 (FrostyGoop target - non-default ID most tools miss)
            ("Start Circulation Pump",    "Modbus TCP :502 slave=11 (FC05 coil 0=ON)",
             lambda: send_modbus(h, 0, True,  slave_id=11)),
            ("Stop Circulation Pump",     "Modbus TCP :502 slave=11 (FC05 coil 0=OFF)",
             lambda: send_modbus(h, 0, False, slave_id=11)),
            ("Open Heat Exchanger Valve", "Modbus TCP :502 slave=11 (FC05 coil 1=ON)",
             lambda: send_modbus(h, 1, True,  slave_id=11)),
            ("Close Heat Exchanger Valve","Modbus TCP :502 slave=11 (FC05 coil 1=OFF)",
             lambda: send_modbus(h, 1, False, slave_id=11)),
            ("Switch to AUTO",            "Modbus TCP :502 slave=11 (FC05 coil 3=ON)",
             lambda: send_modbus(h, 3, True,  slave_id=11)),
            ("Switch to MANUAL",          "Modbus TCP :502 slave=11 (FC05 coil 3=OFF)",
             lambda: send_modbus(h, 3, False, slave_id=11)),
            ("Emergency Shutdown",        "Modbus TCP :502 slave=11 (FC05 coil 4=ON)",
             lambda: send_modbus(h, 4, True,  slave_id=11)),
        ]
        self.detail_windows['heating'] = ProcessDetailWindow(
            self.root, "Heating District (FrostyGoop Target)", h,
            [("Supply Temp", "\u00b0C"), ("Return Temp", "\u00b0C"),
             ("Flow Rate", "m\u00b3/h"), ("Outdoor Temp", "\u00b0C")],
            controls, '#ff6f00', draw_fn=draw_heating_district)

    def _open_water_utility_detail(self):
        if 'water_utility' in self.detail_windows and self.detail_windows['water_utility'].running:
            self.detail_windows['water_utility'].win.lift(); return
        h = self._get_host('water_utility_dnp3')
        controls = [
            ("Start Pump Station 1", "DNP3 :20000 (CROB index 2 LATCH_ON  → Pump1Cmd)",
             lambda: send_dnp3(h, 2, True)),
            ("Stop Pump Station 1",  "DNP3 :20000 (CROB index 2 LATCH_OFF → Pump1Cmd)",
             lambda: send_dnp3(h, 2, False)),
            ("Start Pump Station 2", "DNP3 :20000 (CROB index 1 LATCH_ON  → Pump2Cmd)",
             lambda: send_dnp3(h, 1, True)),
            ("Stop Pump Station 2",  "DNP3 :20000 (CROB index 1 LATCH_OFF → Pump2Cmd)",
             lambda: send_dnp3(h, 1, False)),
            ("Switch to AUTO",        "DNP3 :20000 (CROB index 3 LATCH_ON  → AutoModeCmd)",
             lambda: send_dnp3(h, 3, True)),
            ("Switch to MANUAL",      "DNP3 :20000 (CROB index 3 LATCH_OFF → AutoModeCmd)",
             lambda: send_dnp3(h, 3, False)),
        ]
        self.detail_windows['water_utility'] = ProcessDetailWindow(
            self.root, "Water Utility DNP3 (Industroyer DNP3 Target)", h,
            [("Reservoir Level", "%"), ("Distribution Pressure", "PSI"),
             ("Flow Rate", "gal/min"), ("Chlorine", "ppm")],
            controls, '#29b6f6', draw_fn=draw_water_utility)

    def _open_sensors_detail(self):
        if 'sensors' in self.detail_windows and self.detail_windows['sensors'].running:
            self.detail_windows['sensors'].win.lift(); return
        h = self._get_host('sensor_network')
        controls = [
            ("Reset Gateway (SND_NKE)", "M-Bus TCP :5000 (SND_NKE broadcast)",
             lambda: self._mbus_reset(h)),
            ("Poll All Sensors",        "M-Bus TCP :5000 (REQ_UD2 broadcast)",
             lambda: self._mbus_poll_all(h)),
        ]
        self.detail_windows['sensors'] = ProcessDetailWindow(
            self.root, "M-Bus Sensor Network (Fuxnet Target)", h,
            [("Online Sensors", ""), ("Total Flow", "m\u00b3"),
             ("Avg Pressure", "bar"), ("Avg Temp", "\u00b0C")],
            controls, '#ab47bc', draw_fn=draw_sensor_network)

    def _open_sis_detail(self):
        if 'sis' in self.detail_windows and self.detail_windows['sis'].running:
            self.detail_windows['sis'].win.lift(); return
        h = self._get_host('safety_system')
        controls = [
            # SIS-1 speaks only TriStation UDP :1502.
            # ARM/RESET are automatic - SIS self-rearms every 3s after a trip.
            # DISABLE (TRITON demo) is the key operator-visible action.
            ("Disable SIS (TRITON)", "TriStation UDP :1502 (HALT PROGRAM 0x15)",
             lambda: send_tristation_halt(h, 1502)),
        ]
        self.detail_windows['sis'] = ProcessDetailWindow(
            self.root, "Safety Instrumented System \u2014 TRITON Target", h,
            [("State", ""), ("Monitored Value", "%"),
             ("Trip Threshold", "%"), ("Watchdog", "s")],
            controls, RED, draw_fn=draw_safety_system)

    def _mbus_reset(self, host, port=5000):
        """Broadcast SND_NKE (addr=0xFF) - takes all M-Bus slaves offline."""
        sys.path.insert(0, _mbus_lib_path())
        from mbus_lib import MBusClient
        with MBusClient(host, port, timeout=3.0) as m:
            m.reset_broadcast()

    def _mbus_poll_all(self, host, port=5000):
        """Scan all 12 M-Bus slave addresses and update detail window data."""
        sys.path.insert(0, _mbus_lib_path())
        from mbus_lib import MBusClient
        found = 0
        with MBusClient(host, port, timeout=3.0) as m:
            for addr in range(1, 13):
                try:
                    if m.ping(addr):
                        frame = m.read(addr)
                        if frame and frame.valid and frame.records:
                            found += 1
                except Exception:
                    pass
        dw = self.detail_windows.get('sensors')
        if dw and dw.running:
            dw.live_data['online_sensors'] = found

    # ---- POLLING ----

    def _poll_protocols(self):
        while self.running:
            for name, port, proto, process in PROTOCOLS:
                # Map process label to config key
                proc_map = {
                    'Water Treatment':    'water_treatment',
                    'Power Substation':   'power_substation',
                    'Gas Pipeline':       'gas_pipeline',
                    'Centrifuge Cascade': 'centrifuge_cascade',
                    'Building HVAC':      'building_hvac',
                    'Boiler House':       'boiler_house',
                    'Heating District':   'heating_district',
                    'Water Utility DNP3': 'water_utility_dnp3',
                    'Sensor Network':     'sensor_network',
                    'Safety System':      'safety_system',
                }
                host = self._get_host(proc_map.get(process, ''))
                self.proto_status[name] = probe(host, port, proto)
            time.sleep(3)

    def _poll_water(self):
        """Poll water treatment via IEC-104 (primary protocol on PLC-1 :2404)."""
        while self.running:
            try:
                data = read_iec104_water(self._get_host('water_treatment'), 2404)
                if data: self.water_data = data
            except Exception as e:
                logging.getLogger("HMI.poll").warning("Water read error: %s", e)
            time.sleep(4)   # read takes ~3s (IEC-104 GI), 4s poll avoids overlap

    def _poll_power(self):
        """Poll power substation via IEC 61850 MMS."""
        while self.running:
            try:
                data = read_iec61850(self._get_host('power_substation'), 8102)
                if data: self.power_data = data
            except Exception as e:
                logging.getLogger("HMI.poll").warning("Power read error: %s", e)
            time.sleep(1)

    def _poll_gas(self):
        """Poll gas pipeline via OPC-UA."""
        while self.running:
            try:
                data = read_opcua_gas(self._get_host('gas_pipeline'), 4840)
                if data: self.gas_data = data
            except Exception as e:
                logging.getLogger("HMI.poll").warning("Gas read error: %s", e)
            time.sleep(1.5)

    def _poll_hvac(self):
        """Poll HVAC via BACnet/IP."""
        while self.running:
            try:
                data = read_bacnet_hvac(self._get_host('building_hvac'), 47808)
                if data: self.hvac_data = data
            except Exception as e:
                logging.getLogger("HMI.poll").warning("HVAC read error: %s", e)
            time.sleep(1.5)

    def _poll_mfg(self):
        """Poll manufacturing via S7."""
        while self.running:
            try:
                data = read_s7_mfg(self._get_host('manufacturing'), 102)
                if data: self.mfg_data = data
            except Exception as e:
                logging.getLogger("HMI.poll").warning("Mfg read error: %s", e)
            time.sleep(1)

    def _poll_centrifuge(self):
        """Poll centrifuge cascade via S7 DB4 + DB890."""
        _plog = logging.getLogger("HMI.poll.centrifuge")
        _plog.info("Poll thread started - host=%s port=102",
                   self._get_host('centrifuge_cascade'))
        while self.running:
            try:
                data = read_s7_centrifuge(self._get_host('centrifuge_cascade'), 102)
                if data:
                    self.centrifuge_data = data
                    self.centrifuge_masked = data.get('rootkit_active', False)
            except Exception as e:
                _plog.debug("Centrifuge read error: %s", e)
            time.sleep(1)

    def _poll_boiler(self):
        """Poll boiler house via ABB Modbus TCP."""
        while self.running:
            try:
                data = read_abb_boiler(self._get_host('boiler_house'), 5020)
                if data: self.boiler_data = data
            except Exception as e:
                logging.getLogger("HMI.poll").warning("Boiler read error: %s", e)
            time.sleep(1)

    def _poll_heating(self):
        """Poll heating district via Modbus TCP."""
        while self.running:
            try:
                data = read_modbus_heating(self._get_host('heating_district'), 502)
                if data: self.heating_data = data
            except Exception as e:
                logging.getLogger("HMI.poll").warning("Heating read error: %s", e)
            time.sleep(1)

    def _poll_water_utility(self):
        """Poll water utility via DNP3."""
        while self.running:
            try:
                data = read_dnp3_water_utility(self._get_host('water_utility_dnp3'), 20000)
                if data: self.water_utility_data = data
            except Exception as e:
                logging.getLogger("HMI.poll").warning("Water utility read error: %s", e)
            time.sleep(2)

    def _poll_sensors(self):
        """Poll M-Bus sensor network."""
        while self.running:
            try:
                data = read_mbus_sensors(self._get_host('sensor_network'), 5000)
                self.sensor_data = data
            except Exception as e:
                logging.getLogger("HMI.poll").warning("Sensors read error: %s", e)
                self.sensor_data = {'online_sensors': 0, 'corrupted': True}
            time.sleep(2)

    def _poll_sis(self):
        """Poll Safety System via TriStation UDP port 1502 - only protocol on SIS-1."""
        while self.running:
            try:
                data = read_safety_system(self._get_host('safety_system'), 1502)
                if data: self.sis_data = data
            except Exception as e:
                logging.getLogger("HMI.poll").warning("SIS read error: %s", e)
            time.sleep(4)

    # ---- TICK ----

    def _tick(self):
        if not self.running: return
        try:
            self._tick_inner()
        except Exception as e:
            log.error("_tick crash: %s", e, exc_info=True)
            self.root.after(200, self._tick)

    def _tick_inner(self):
        self.clock_lbl.config(text=time.strftime('%Y-%m-%d  %H:%M:%S'))

        # Water Treatment (from Modbus TCP)
        wd = self.water_data
        w_level = wd.get('level', 0)
        w_exploded = wd.get('exploded', False)
        w_auto = wd.get('auto_mode', False)
        self.water_panel.set_value('Level', w_level)
        self.water_panel.set_value('Pressure', wd.get('pressure', 0), '.2f')
        self.water_panel.set_value('Temp', wd.get('temperature', 0))
        mode_text = 'AUTO' if w_auto else 'MANUAL'
        self.water_panel.set_value('Mode', mode_text, 's')
        self.water_panel.set_status('inlet', wd.get('inlet', False))
        self.water_panel.set_status('outlet', wd.get('outlet', False))
        self.water_panel.set_status('pump', wd.get('pump', False))
        # Alarm priority: exploded > sis > overflow > normal
        w_sis = wd.get('sis_tripped', False)
        if w_exploded:
            self.water_panel.set_alarm('TANK EXPLODED', True)
        elif w_sis:
            self.water_panel.set_alarm('SIS TRIPPED', True)
        elif w_level > 95:
            self.water_panel.set_alarm('OVERFLOW', True)
        else:
            self.water_panel.set_alarm('', False)
        dw = self.detail_windows.get('water')
        if dw and dw.running: dw.live_data = wd

        # Power
        pd = self.power_data
        v = pd.get('voltage', 0); i = pd.get('current', 0)
        self.power_panel.set_value('Voltage', v, '.1f')
        self.power_panel.set_value('Current', i, '.0f')
        self.power_panel.set_value('Xfmr Temp', pd.get('xfmr_temp', 0), '.1f')
        self.power_panel.set_value('Power', v * i * 0.85 / 1000 if v and i else 0, '.1f')
        self.power_panel.set_value('Frequency', 60.0 if v > 0 else 0, '.2f')
        self.power_panel.set_status('brk1', pd.get('breaker1', False))
        self.power_panel.set_status('brk2', pd.get('breaker2', False))
        self.power_panel.set_status('brk3', pd.get('breaker3', False))
        blackout = v == 0 and bool(pd)
        self.power_panel.set_alarm('BLACKOUT' if blackout else '', blackout)
        dw = self.detail_windows.get('power')
        if dw and dw.running:
            dw.live_data = pd

        # Gas Pipeline (from OPC-UA)
        gd = self.gas_data
        g_pressure = gd.get('pressure', 0)
        self.gas_panel.set_value('Out Press', g_pressure, '.0f')
        self.gas_panel.set_value('In Press', gd.get('inlet_pressure', 0), '.0f')
        self.gas_panel.set_value('Gas Temp', gd.get('temperature', 0), '.0f')
        self.gas_panel.set_value('Flow', 0, '.0f')
        self.gas_panel.set_value('Vibration', 0, '.1f')
        self.gas_panel.set_status('upstream', gd.get('upstream', False))
        self.gas_panel.set_status('downstream', gd.get('downstream', False))
        self.gas_panel.set_status('compressor', gd.get('compressor', False))
        if gd.get('rupture'):
            self.gas_panel.set_alarm('PIPELINE RUPTURE', True)
        elif gd.get('esd'):
            self.gas_panel.set_alarm('ESD ACTIVE', True)
        else:
            self.gas_panel.set_alarm('', False)
        dw = self.detail_windows.get('gas')
        if dw and dw.running: dw.live_data = gd

        # HVAC (from BACnet/IP)
        hd = self.hvac_data
        h_zone = hd.get('zone_temp', 0)
        self.hvac_panel.set_value('Zone Temp', h_zone, '.1f')
        self.hvac_panel.set_value('Supply Air', hd.get('supply_air', 0), '.1f')
        self.hvac_panel.set_value('Humidity', 0, '.0f')
        self.hvac_panel.set_value('Duct Press', hd.get('duct_pressure', 0), '.1f')
        self.hvac_panel.set_value('Outdoor', 0, '.1f')
        self.hvac_panel.set_status('fan', hd.get('fan', False))
        self.hvac_panel.set_status('heating', hd.get('heating', False))
        self.hvac_panel.set_status('cooling', hd.get('cooling', False))
        if h_zone > 35:
            self.hvac_panel.set_alarm('HIGH TEMP', True)
        elif h_zone < 5 and h_zone > 0:
            self.hvac_panel.set_alarm('FREEZE', True)
        else:
            self.hvac_panel.set_alarm('', False)
        dw = self.detail_windows.get('hvac')
        if dw and dw.running: dw.live_data = hd

        # Centrifuge Cascade (from S7 DB4)
        cd = self.centrifuge_data
        cc_list = cd.get('centrifuges', [{'speed': 0, 'vib': 0, 'temp': 0, 'status': 0}] * 3)
        c1, c2, c3 = (cc_list + [{'speed': 0, 'vib': 0, 'temp': 0, 'status': 0}] * 3)[:3]
        self.centrifuge_panel.set_value('C1 Speed', c1.get('speed', 0), '.0f')
        self.centrifuge_panel.set_value('C2 Speed', c2.get('speed', 0), '.0f')
        self.centrifuge_panel.set_value('C3 Speed', c3.get('speed', 0), '.0f')
        max_vib = max(c.get('vib', 0) for c in cc_list) if cc_list else 0
        self.centrifuge_panel.set_value('Max Vib', max_vib, '.2f')
        statuses = [c.get('status', 0) for c in cc_list]
        destroyed = sum(1 for s in statuses if s == 4)
        worst = max(statuses, default=0)
        status_labels = ['NORMAL', 'OVERSPEED', 'UNDERSTEED', 'DAMAGED', 'DESTROYED']
        self.centrifuge_panel.set_value('Status', status_labels[min(worst, 4)], 's')
        self.centrifuge_panel.set_status('c1', c1.get('status', 0) != 4)
        self.centrifuge_panel.set_status('c2', c2.get('status', 0) != 4)
        self.centrifuge_panel.set_status('c3', c3.get('status', 0) != 4)
        if self.centrifuge_masked:
            self.centrifuge_panel.set_alarm('DATA INTEGRITY ALARM', True)
        elif destroyed > 0:
            self.centrifuge_panel.set_alarm(f'ROTOR FAILURE ×{destroyed}', True)
        elif worst == 1:
            self.centrifuge_panel.set_alarm('OVERSPEED ALARM', True)
        else:
            self.centrifuge_panel.set_alarm('', False)

        # Boiler House (from ABB Modbus)
        bd = self.boiler_data
        self.boiler_panel.set_value('Drum Level', bd.get('drum_level', 0), '.0f')
        self.boiler_panel.set_value('Steam Press', bd.get('steam_pressure', 0), '.1f')
        self.boiler_panel.set_value('Steam Temp', bd.get('steam_temp', 0), '.0f')
        self.boiler_panel.set_value('Fuel Flow', 0, '.0f')
        self.boiler_panel.set_status('burner', bd.get('burner', False))
        self.boiler_panel.set_status('fw_pump', bd.get('feedwater_pump', False))
        self.boiler_panel.set_status('safety', not bd.get('safety_valve', False))
        if bd.get('flame_failure'):
            self.boiler_panel.set_alarm('FLAME FAILURE', True)
        elif bd.get('high_pressure'):
            self.boiler_panel.set_alarm('HIGH PRESSURE', True)
        elif bd.get('low_water'):
            self.boiler_panel.set_alarm('LOW WATER', True)
        else:
            self.boiler_panel.set_alarm('', False)
        dw = self.detail_windows.get('boiler')
        if dw and dw.running: dw.live_data = bd

        # Heating District (from Modbus TCP)
        heatd = self.heating_data
        supply = heatd.get('supply_temp', 0)
        ret_t  = heatd.get('return_temp', 0)
        self.heating_panel.set_value('Supply Temp', supply, '.1f')
        self.heating_panel.set_value('Return Temp', ret_t, '.1f')
        self.heating_panel.set_value('Flow Rate', heatd.get('flow_rate', 0), '.0f')
        self.heating_panel.set_value('Outdoor', heatd.get('outdoor_temp', 0), '.1f')
        self.heating_panel.set_status('pump', heatd.get('pump', False))
        self.heating_panel.set_status('valve', heatd.get('valve', False))
        if heatd.get('freeze_alarm') or (supply > 0 and supply < 20):
            self.heating_panel.set_alarm('HEATING LOSS - FROSTYGOOP', True)
        elif supply > 0:
            self.heating_panel.set_alarm('', False)
        dw = self.detail_windows.get('heating')
        if dw and dw.running: dw.live_data = heatd

        # Water Utility DNP3
        wud = self.water_utility_data
        self.water_utility_panel.set_value('Reservoir', wud.get('reservoir_level', 0), '.0f')
        self.water_utility_panel.set_value('Pressure', wud.get('pressure', 0), '.0f')
        self.water_utility_panel.set_value('Flow Rate', wud.get('flow_rate', 0), '.0f')
        self.water_utility_panel.set_value('Chlorine', wud.get('chlorine_ppm', 0), '.2f')
        self.water_utility_panel.set_status('pump1', wud.get('pump1', False))
        self.water_utility_panel.set_status('pump2', wud.get('pump2', False))
        if not wud.get('pump1', True) and not wud.get('pump2', True) and wud:
            self.water_utility_panel.set_alarm('PUMP FAILURE', True)
        else:
            self.water_utility_panel.set_alarm('', False)
        dw = self.detail_windows.get('water_utility')
        if dw and dw.running: dw.live_data = wud

        # Sensor Network (M-Bus)
        sd = self.sensor_data
        n_online = sd.get('online_sensors', 0)
        corrupted = sd.get('corrupted', False)
        self.sensor_panel.set_value('Online', n_online, 'd')
        self.sensor_panel.set_value('Avg Flow', sd.get('flow_total', 0), '.1f')
        self.sensor_panel.set_value('Avg Pressure', sd.get('pressure', 0), '.2f')
        self.sensor_panel.set_value('Status', 'CORRUPTED' if corrupted else 'OK', 's')
        self.sensor_panel.set_status('gateway', not corrupted)
        if corrupted:
            self.sensor_panel.set_alarm('FUXNET - SENSORS CORRUPTED', True)
        elif n_online == 0 and sd:
            self.sensor_panel.set_alarm('ALL SENSORS OFFLINE', True)
        else:
            self.sensor_panel.set_alarm('', False)
        dw = self.detail_windows.get('sensors')
        if dw and dw.running: dw.live_data = sd

        # Safety System (SIS)
        sisd = self.sis_data
        sis_armed    = sisd.get('armed', True)
        sis_tripped  = sisd.get('tripped', False)
        sis_disabled = sisd.get('disabled', False)
        mon_v = sisd.get('monitored_val', 0)
        sis_state = 'DISABLED' if sis_disabled else ('TRIPPED' if sis_tripped else ('ARMED' if sis_armed else 'DISARMED'))
        self.sis_panel.set_value('State', sis_state, 's')
        self.sis_panel.set_value('Monitored', mon_v, '.1f')
        self.sis_panel.set_value('Threshold', 90, '.0f')
        self.sis_panel.set_value('Watchdog', 0, '.0f')
        self.sis_panel.set_status('armed', sis_armed and not sis_disabled)
        self.sis_panel.set_status('disabled', sis_disabled)
        if sis_disabled:
            self.sis_panel.set_alarm('TRITON: SIS NEUTRALIZED', True)
        elif sis_tripped:
            self.sis_panel.set_alarm('SIS TRIPPED - SAFE STATE', True)
        elif sisd:
            self.sis_panel.set_alarm('', False)
        dw = self.detail_windows.get('sis')
        if dw and dw.running: dw.live_data = sisd

        # Protocols
        online = sum(1 for n, _, _, _ in PROTOCOLS if self.proto_status.get(n))
        for name, _, _, _ in PROTOCOLS:
            self.proto_dots[name].config(fg=GREEN if self.proto_status.get(name) else DIM)
        color = GREEN if online >= 8 else AMBER if online >= 4 else RED
        self.proto_summary.config(text=f"{online}/{len(PROTOCOLS)} online", fg=color)

        # Update detail windows - MERGE polled data, don't replace
        # (preserves optimistic state set by button clicks)
        if 'water' in self.detail_windows and self.detail_windows['water'].running:
            dw = self.detail_windows['water']
            # Use polled data directly - Modbus polls at 2Hz, fast enough
            dw.live_data.update({
                'level': w_level,
                'inlet': wd.get('inlet', False),
                'outlet': wd.get('outlet', False),
                'pump': wd.get('pump', False),
                'exploded': w_exploded,
                'sis_tripped': wd.get('sis_tripped', False),
            })
            dw.update_measurement('Level', w_level)
            dw.update_measurement('Pressure', wd.get('pressure', 0), '.2f')
            dw.update_measurement('Temp', wd.get('temperature', 0))
            dw.update_measurement('Mode', 'AUTO' if w_auto else 'MANUAL', 's')
        if 'power' in self.detail_windows and self.detail_windows['power'].running:
            dp = self.detail_windows['power']
            dp.live_data.update({'voltage': pd.get('voltage', dp.live_data.get('voltage', 13.8)),
                                  'brk1': pd.get('breaker1', dp.live_data.get('brk1', True)),
                                  'brk2': pd.get('breaker2', dp.live_data.get('brk2', True)),
                                  'brk3': pd.get('breaker3', dp.live_data.get('brk3', True)),
                                  'tripped': pd.get('relay_tripped', dp.live_data.get('tripped', False))})
            dp.update_measurement('Voltage', dp.live_data['voltage'], '.1f')
            dp.update_measurement('Current', i, '.0f')
            dp.update_measurement('Xfmr Temp', pd.get('xfmr_temp', 0), '.1f')
            dp.update_measurement('Power', v * i * 0.85 / 1000 if v and i else 0, '.1f')
            dp.update_measurement('Frequency', 60.0 if v > 0 else 0, '.2f')
        if 'gas' in self.detail_windows and self.detail_windows['gas'].running:
            dg = self.detail_windows['gas']
            dg.live_data.update({
                'pressure': gd.get('pressure', dg.live_data.get('pressure', 0)),
                'upstream': gd.get('upstream', dg.live_data.get('upstream', False)),
                'downstream': gd.get('downstream', dg.live_data.get('downstream', False)),
                'compressor': gd.get('compressor', dg.live_data.get('compressor', False)),
            })
            dg.update_measurement('Outlet Pressure', g_pressure, '.0f')
            dg.update_measurement('Inlet Pressure', gd.get('inlet_pressure', 0), '.0f')
            dg.update_measurement('Gas Temp', gd.get('temperature', 0), '.0f')
            dg.update_measurement('Flow Rate', 0, '.0f')
            dg.update_measurement('Vibration', 0, '.1f')
        if 'hvac' in self.detail_windows and self.detail_windows['hvac'].running:
            dh = self.detail_windows['hvac']
            dh.live_data.update({
                'zone_temp': hd.get('zone_temp', dh.live_data.get('zone_temp', 0)),
                'fan': hd.get('fan', dh.live_data.get('fan', False)),
                'heating': hd.get('heating', dh.live_data.get('heating', False)),
                'cooling': hd.get('cooling', dh.live_data.get('cooling', False)),
            })
            dh.update_measurement('Zone Temp', h_zone, '.1f')
            dh.update_measurement('Supply Air', hd.get('supply_air', 0), '.1f')
            dh.update_measurement('Humidity', 0, '.0f')
            dh.update_measurement('Duct Pressure', hd.get('duct_pressure', 0), '.1f')
            dh.update_measurement('Outdoor Temp', 0, '.1f')
        if 'mfg' in self.detail_windows and self.detail_windows['mfg'].running:
            dm = self.detail_windows['mfg']
            dm.live_data.update({
                'hopper': md.get('hopper', dm.live_data.get('hopper', 0)),
                'running': md.get('conveyor', dm.live_data.get('running', False)),
                'speed': 60 if md.get('conveyor') else 0,
                'e_stop': md.get('e_stop', False),
            })
            dm.update_measurement('Hopper Level', md.get('hopper', 0), '.0f')
            dm.update_measurement('Hydraulic Press', md.get('hydraulic', 0), '.0f')
            dm.update_measurement('Motor Temp', md.get('motor_temp', 0), '.0f')
            dm.update_measurement('Motor Current', 0, '.0f')
            dm.update_measurement('Product Count', 0, '.0f')
        if 'centrifuge' in self.detail_windows and self.detail_windows['centrifuge'].running:
            dc = self.detail_windows['centrifuge']
            dc.live_data.update({
                'centrifuges': cd.get('centrifuges', dc.live_data.get('centrifuges', [])),
                'rootkit_active': self.centrifuge_masked,
            })
            dc.update_measurement('C1 Speed Hz', c1.get('speed', 0), '.0f')
            dc.update_measurement('C2 Speed Hz', c2.get('speed', 0), '.0f')
            dc.update_measurement('C3 Speed Hz', c3.get('speed', 0), '.0f')
            dc.update_measurement('Max Vibration g', max_vib, '.2f')
            dc.update_measurement('Rootkit Active', 'YES' if self.centrifuge_masked else 'NO', 's')
        if 'boiler' in self.detail_windows and self.detail_windows['boiler'].running:
            db = self.detail_windows['boiler']
            db.live_data.update({
                'drum_level': bd.get('drum_level', db.live_data.get('drum_level', 50)),
                'burner': bd.get('burner', db.live_data.get('burner', True)),
                'feedwater_pump': bd.get('feedwater_pump', True),
                'safety_valve': bd.get('safety_valve', False),
                'flame_failure': bd.get('flame_failure', False),
            })
            db.update_measurement('Drum Level', bd.get('drum_level', 0), '.0f')
            db.update_measurement('Steam Pressure', bd.get('steam_pressure', 0), '.1f')
            db.update_measurement('Steam Temp', bd.get('steam_temp', 0), '.0f')
            db.update_measurement('Fuel Flow', 0, '.0f')
        if 'heating' in self.detail_windows and self.detail_windows['heating'].running:
            dh2 = self.detail_windows['heating']
            dh2.live_data.update({
                'supply_temp':  heatd.get('supply_temp', dh2.live_data.get('supply_temp', 75)),
                'return_temp':  heatd.get('return_temp', dh2.live_data.get('return_temp', 45)),
                'flow_rate':    heatd.get('flow_rate', dh2.live_data.get('flow_rate', 60)),
                'outdoor_temp': heatd.get('outdoor_temp', dh2.live_data.get('outdoor_temp', -30)),
                'pump':  heatd.get('pump', dh2.live_data.get('pump', True)),
                'valve': heatd.get('valve', dh2.live_data.get('valve', True)),
            })
            dh2.update_measurement('Supply Temp', heatd.get('supply_temp', 0), '.1f')
            dh2.update_measurement('Return Temp', heatd.get('return_temp', 0), '.1f')
            dh2.update_measurement('Flow Rate', heatd.get('flow_rate', 0), '.0f')
            dh2.update_measurement('Outdoor Temp', heatd.get('outdoor_temp', 0), '.1f')
        if 'water_utility' in self.detail_windows and self.detail_windows['water_utility'].running:
            dwu = self.detail_windows['water_utility']
            dwu.live_data.update({
                'reservoir_level': wud.get('reservoir_level', dwu.live_data.get('reservoir_level', 75)),
                'pressure':        wud.get('pressure', dwu.live_data.get('pressure', 65)),
                'flow_rate':       wud.get('flow_rate', dwu.live_data.get('flow_rate', 0)),
                'chlorine_ppm':    wud.get('chlorine_ppm', dwu.live_data.get('chlorine_ppm', 0.5)),
                'pump1': wud.get('pump1', dwu.live_data.get('pump1', True)),
                'pump2': wud.get('pump2', dwu.live_data.get('pump2', True)),
            })
            dwu.update_measurement('Reservoir Level', wud.get('reservoir_level', 0), '.0f')
            dwu.update_measurement('Distribution Pressure', wud.get('pressure', 0), '.0f')
            dwu.update_measurement('Flow Rate', wud.get('flow_rate', 0), '.0f')
            dwu.update_measurement('Chlorine', wud.get('chlorine_ppm', 0), '.2f')
        if 'sensors' in self.detail_windows and self.detail_windows['sensors'].running:
            ds = self.detail_windows['sensors']
            ds.live_data.update({
                'online_sensors': sd.get('online_sensors', ds.live_data.get('online_sensors', 12)),
                'corrupted':      sd.get('corrupted', ds.live_data.get('corrupted', False)),
                'flow_total':     sd.get('flow_total', 0),
                'pressure':       sd.get('pressure', 0),
                'temperature':    sd.get('temperature', 0),
            })
            ds.update_measurement('Online Sensors', sd.get('online_sensors', 0), 'd')
            ds.update_measurement('Total Flow', sd.get('flow_total', 0), '.1f')
            ds.update_measurement('Avg Pressure', sd.get('pressure', 0), '.2f')
            ds.update_measurement('Avg Temp', sd.get('temperature', 0), '.1f')
        if 'sis' in self.detail_windows and self.detail_windows['sis'].running:
            dsis = self.detail_windows['sis']
            dsis.live_data.update({
                'armed':         sisd.get('armed', dsis.live_data.get('armed', True)),
                'tripped':       sisd.get('tripped', dsis.live_data.get('tripped', False)),
                'disabled':      sisd.get('disabled', dsis.live_data.get('disabled', False)),
                'monitored_val': sisd.get('monitored_val', dsis.live_data.get('monitored_val', 45)),
            })
            dsis.update_measurement('State', sis_state, 's')
            dsis.update_measurement('Monitored Value', mon_v, '.1f')
            dsis.update_measurement('Trip Threshold', 90, '.0f')
            dsis.update_measurement('Watchdog', 0, '.0f')

        self.root.after(200, self._tick)   # reschedule via outer wrapper

    def _on_close(self):
        self.running = False
        for dw in self.detail_windows.values():
            if dw.running:
                dw._close()
        self.root.destroy()


def main():
    import traceback

    # Crash log - written BEFORE tkinter init so it captures pre-UI failures
    _crash_log = os.path.join(_LOG_DIR, 'hmi_crash.log')

    def _crash(label, exc):
        tb = traceback.format_exc()
        msg = f"[CRASH] {label}: {exc}\n{tb}"
        log.critical(msg)
        try:
            with open(_crash_log, 'a') as f:
                import datetime
                f.write(f"\n{'='*60}\n{datetime.datetime.now()} - {label}\n{tb}\n")
        except Exception:
            pass

    # ── Startup diagnostics ───────────────────────────────────────────────────
    log.info("=" * 60)
    log.info("HMI STARTUP - Python %s on %s", sys.version.split()[0], sys.platform)
    log.info("CWD: %s", os.getcwd())
    log.info("Script: %s", os.path.abspath(__file__))
    log.info("Crash log: %s", _crash_log)

    # Check critical imports
    for mod in ['snap7', 'tkinter']:
        try:
            __import__(mod)
            log.info("  [OK] import %s", mod)
        except ImportError as e:
            log.warning("  [MISSING] import %s - %s", mod, e)

    # ─────────────────────────────────────────────────────────────────────────
    parser = argparse.ArgumentParser(description="Multi-Process Plant HMI")
    parser.add_argument('--plc-ip', default=None, help='Default PLC server IP (all processes)')
    parser.add_argument('--config', type=str, default=None,
                        help='Path to hmi_config.json with per-process IP addresses')
    args = parser.parse_args()

    # Default per-process IP mapping - lab network 192.168.1.x
    DEFAULT_CONFIG = {
        'water_treatment':    {'host': '192.168.1.10'},
        'power_substation':   {'host': '192.168.1.11'},
        'gas_pipeline':       {'host': '192.168.1.12'},
        'centrifuge_cascade': {'host': '192.168.1.13'},
        'building_hvac':      {'host': '192.168.1.14'},
        'boiler_house':       {'host': '192.168.1.15'},
        'heating_district':   {'host': '192.168.1.16'},
        'water_utility_dnp3': {'host': '192.168.1.17'},
        'sensor_network':     {'host': '192.168.1.18'},
        'safety_system':      {'host': '192.168.1.19'},
    }

    config = DEFAULT_CONFIG
    if args.config:
        try:
            with open(args.config) as f:
                loaded = json.load(f)
            if 'plcs' in loaded:
                loaded = loaded['plcs']
            config = {k: {'host': v['ip']} if 'ip' in v else v for k, v in loaded.items()}
            log.info("Loaded config from %s", args.config)
        except Exception as e:
            _crash(f"load config {args.config}", e)
            log.warning("Using DEFAULT_CONFIG as fallback")

    for proc, info in config.items():
        log.info("  Process %-25s host=%s", proc, info.get('host', '?'))

    default_ip = args.plc_ip or '192.168.1.10'

    # Write session-start banner to button log
    import datetime as _dtt
    _btn_log.info("")
    _btn_log.info("=" * 120)
    _btn_log.info("SESSION START  %s  Python=%s  Platform=%s",
                  _dtt.datetime.now().strftime('%Y-%m-%d %H:%M:%S'), sys.version.split()[0], sys.platform)
    _btn_log.info("Button log: %s", _BTN_LOG_FILE)
    _btn_log.info("Format: [STATUS] TIMESTAMP | elapsed  BUTTON / PROTO / HOST / REQUEST / RESPONSE or ERROR+TRACEBACK")
    _btn_log.info("=" * 120)

    try:
        log.info("Creating Tk root window...")
        root = tk.Tk()
        log.info("Tk root OK - starting UnifiedHMI...")
        app = UnifiedHMI(root, plc_ip=default_ip, config=config)
        log.info("UnifiedHMI init complete - entering mainloop")
        root.mainloop()
    except Exception as e:
        _crash("main UI init / mainloop", e)
        raise


if __name__ == '__main__':
    main()
