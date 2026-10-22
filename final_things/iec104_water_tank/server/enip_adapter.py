"""
Allen-Bradley EtherNet/IP CIP Protocol Adapter

Emulates a Rockwell Automation CompactLogix 5370 PLC (1769-L33ER)
using EtherNet/IP encapsulation protocol with CIP (Common Industrial Protocol).

This is the primary protocol for Allen-Bradley PLCs used across
North American manufacturing, automotive, and process industries.

Protocol: EtherNet/IP (ODVA) over TCP
Port: 44818
Target: Allen-Bradley CompactLogix / ControlLogix
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

# EtherNet/IP Encapsulation Commands
ENCAP_NOP = 0x0000
ENCAP_LIST_SERVICES = 0x0004
ENCAP_LIST_IDENTITY = 0x0063
ENCAP_LIST_INTERFACES = 0x0064
ENCAP_REGISTER_SESSION = 0x0065
ENCAP_UNREGISTER_SESSION = 0x0066
ENCAP_SEND_RR_DATA = 0x006F
ENCAP_SEND_UNIT_DATA = 0x0070

# CIP Service Codes
CIP_GET_ATTRIBUTE_ALL = 0x01
CIP_GET_ATTRIBUTE_SINGLE = 0x0E
CIP_READ_TAG = 0x4C
CIP_WRITE_TAG = 0x4D
CIP_READ_TAG_FRAGMENTED = 0x52
CIP_MULTI_REQUEST = 0x0A

# CIP Object Classes
CIP_CLASS_IDENTITY = 0x01
CIP_CLASS_MESSAGE_ROUTER = 0x02
CIP_CLASS_CONNECTION_MANAGER = 0x06
CIP_CLASS_TCP_IP = 0xF5
CIP_CLASS_ETHERNET_LINK = 0xF6

# CIP Data Types
CIP_BOOL = 0x00C1
CIP_SINT = 0x00C2
CIP_INT = 0x00C3
CIP_DINT = 0x00C4
CIP_REAL = 0x00CA
CIP_STRING = 0x00DA

ENCAP_HEADER_SIZE = 24


def _build_encap_header(command, session, data, context=b'\x00' * 8):
    """Build EtherNet/IP encapsulation header + data."""
    return struct.pack('<HHIQI4s',
                       command, len(data), session,
                       0,  # status
                       int.from_bytes(context[:8].ljust(8, b'\x00'), 'little'),
                       b'\x00\x00\x00\x00') + data


class EtherNetIPAdapter(ProtocolAdapter):
    """
    EtherNet/IP CIP adapter emulating Allen-Bradley CompactLogix.

    Responds to:
    - ListIdentity (Nmap/scanner fingerprinting)
    - RegisterSession / UnRegisterSession
    - SendRRData with CIP Read Tag / Write Tag
    - CIP Identity Object Get Attribute All
    """

    # Allen-Bradley CompactLogix 5370 identity
    VENDOR_ID = 0x0001          # Rockwell Automation
    DEVICE_TYPE = 0x000E        # Programmable Logic Controller
    PRODUCT_CODE = 55           # CompactLogix 5370
    REVISION_MAJOR = 30
    REVISION_MINOR = 11
    SERIAL_NUMBER = 0x1234ABCD
    PRODUCT_NAME = "1769-L33ER CompactLogix 5370"
    STATE_RUNNING = 0x03

    def __init__(self, water_tank, config: Dict[str, Any]):
        super().__init__(water_tank, config)
        self.host = config.get('host', '0.0.0.0')
        self.port = config.get('port', 44818)
        self.server_socket = None
        self.server_thread = None
        self.update_thread = None

        self._next_session = 1
        self._sessions = set()

        # Tag store (CIP tags mapped from water tank)
        self.tags: Dict[str, Any] = {
            'WaterLevel':       0.0,
            'Pressure':         0.0,
            'Temperature':      0.0,
            'InletValve':       False,
            'OutletValve':      False,
            'PumpRunning':      False,
            'AutoMode':         True,
            'AlarmOverflow':    False,
            'AlarmLowLevel':    False,
            'AlarmHighPressure': False,
            'InletFlowRate':    0.0,
            'OutletFlowRate':   0.0,
        }
        # Tag type mapping
        self.tag_types: Dict[str, int] = {
            'WaterLevel': CIP_REAL, 'Pressure': CIP_REAL,
            'Temperature': CIP_REAL, 'InletFlowRate': CIP_REAL,
            'OutletFlowRate': CIP_REAL,
            'InletValve': CIP_BOOL, 'OutletValve': CIP_BOOL,
            'PumpRunning': CIP_BOOL, 'AutoMode': CIP_BOOL,
            'AlarmOverflow': CIP_BOOL, 'AlarmLowLevel': CIP_BOOL,
            'AlarmHighPressure': CIP_BOOL,
        }

        # Command tags (writable)
        self.command_tags = {
            'InletValveCmd':  'inlet_valve_command',
            'OutletValveCmd': 'outlet_valve_command',
            'PumpCmd':        'pump_command',
            'AutoModeCmd':    'auto_mode_command',
        }
        for tag in self.command_tags:
            self.tags[tag] = False
            self.tag_types[tag] = CIP_BOOL

        self._create_address_mapping()

    def _create_address_mapping(self):
        data_points = WaterTankProtocolMapper.create_data_points()
        for name, definition in data_points.items():
            dp = DataPoint(
                address={'type': 'cip_tag'},
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
            self.server_socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            self.server_socket.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            self.server_socket.bind((self.host, self.port))
            self.server_socket.listen(5)
            self.server_socket.settimeout(1.0)
            self.logger.info(f"EtherNet/IP initialized on {self.host}:{self.port}")
            self.logger.info(f"  PLC: {self.PRODUCT_NAME}")
            self.logger.info(f"  Vendor: Rockwell Automation (0x{self.VENDOR_ID:04X})")
            self.logger.info(f"  Serial: 0x{self.SERIAL_NUMBER:08X}")
            return True
        except Exception as e:
            self.logger.error(f"EtherNet/IP init failed: {e}")
            return False

    def start(self) -> bool:
        try:
            self.running = True
            self.server_thread = threading.Thread(
                target=self._accept_loop, daemon=True, name="EtherNetIPThread")
            self.server_thread.start()
            self.update_thread = threading.Thread(
                target=self._update_loop, daemon=True, name="EtherNetIPUpdateThread")
            self.update_thread.start()
            self.logger.info(f"EtherNet/IP started on port {self.port}")
            return True
        except Exception as e:
            self.logger.error(f"EtherNet/IP start failed: {e}")
            self.running = False
            return False

    def _accept_loop(self):
        while self.running:
            try:
                conn, addr = self.server_socket.accept()
                self.logger.info(f"[EtherNet/IP] Connection from {addr}")
                t = threading.Thread(
                    target=self._handle_connection, args=(conn, addr), daemon=True)
                t.start()
            except socket.timeout:
                continue
            except Exception as e:
                if self.running:
                    self.logger.error(f"EtherNet/IP accept error: {e}")

    def _handle_connection(self, conn: socket.socket, addr):
        conn.settimeout(10.0)
        session = 0
        try:
            while self.running:
                try:
                    header = self._recv_exact(conn, ENCAP_HEADER_SIZE)
                    if not header:
                        break
                    command, length, sess_handle = struct.unpack_from('<HHI', header, 0)
                    context = header[12:20]
                    data = self._recv_exact(conn, length) if length > 0 else b''

                    response = self._process_encap(command, sess_handle, context, data, addr)
                    if response:
                        conn.sendall(response)
                except socket.timeout:
                    continue
        except Exception:
            pass
        finally:
            conn.close()

    def _recv_exact(self, conn, n):
        buf = b''
        while len(buf) < n:
            chunk = conn.recv(n - len(buf))
            if not chunk:
                return None
            buf += chunk
        return buf

    def _process_encap(self, command, session, context, data, addr) -> Optional[bytes]:

        if command == ENCAP_LIST_IDENTITY:
            self.logger.info(f"[EtherNet/IP] ListIdentity from {addr[0]}")
            return self._build_list_identity(context)

        elif command == ENCAP_LIST_SERVICES:
            self.logger.info(f"[EtherNet/IP] ListServices from {addr[0]}")
            return self._build_list_services(context)

        elif command == ENCAP_REGISTER_SESSION:
            session = self._next_session
            self._next_session += 1
            self._sessions.add(session)
            self.logger.info(f"[EtherNet/IP] RegisterSession #{session} from {addr[0]}")
            resp_data = struct.pack('<HH', 1, 0)  # protocol version 1, options 0
            return self._build_response(command, session, context, resp_data)

        elif command == ENCAP_UNREGISTER_SESSION:
            self._sessions.discard(session)
            self.logger.info(f"[EtherNet/IP] UnRegisterSession #{session}")
            return None  # no response per spec

        elif command == ENCAP_SEND_RR_DATA:
            return self._handle_send_rr_data(session, context, data, addr)

        elif command == ENCAP_NOP:
            return None

        return self._build_response(command, session, context, b'', status=0x0001)

    def _build_response(self, command, session, context, data, status=0):
        header = struct.pack('<HHII', command, len(data), session, status)
        header += context[:8].ljust(8, b'\x00')
        header += struct.pack('<I', 0)  # options
        return header + data

    def _build_list_identity(self, context) -> bytes:
        """Build ListIdentity response with Allen-Bradley device fingerprint."""
        # Identity item
        name_bytes = self.PRODUCT_NAME.encode('utf-8')

        identity = struct.pack('<HH', 1, 0)  # encap version, socket family
        identity += struct.pack('>H', self.port)  # sin_port (big-endian)
        identity += socket.inet_aton('0.0.0.0')   # sin_addr
        identity += b'\x00' * 8                    # sin_zero

        identity += struct.pack('<HHH', self.VENDOR_ID, self.DEVICE_TYPE, self.PRODUCT_CODE)
        identity += struct.pack('<BB', self.REVISION_MAJOR, self.REVISION_MINOR)
        identity += struct.pack('<H', 0x0030)  # status: configured, minor fault
        identity += struct.pack('<I', self.SERIAL_NUMBER)
        identity += struct.pack('<B', len(name_bytes)) + name_bytes
        identity += struct.pack('<B', self.STATE_RUNNING)

        # CPF items wrapper
        items = struct.pack('<HH', 1, 0)  # item count=1, type=0x000C (CIP Identity)
        items = struct.pack('<HHH', 1, 0x000C, len(identity)) + identity

        return self._build_response(ENCAP_LIST_IDENTITY, 0, context, items)

    def _build_list_services(self, context) -> bytes:
        """Build ListServices response."""
        svc_name = b'Communications\x00'
        svc_data = struct.pack('<HHH', 1, 0x0100, 0x0120)  # version, cap flags
        svc_data += svc_name.ljust(16, b'\x00')
        items = struct.pack('<HHH', 1, 0x0100, len(svc_data)) + svc_data
        return self._build_response(ENCAP_LIST_SERVICES, 0, context, items)

    def _handle_send_rr_data(self, session, context, data, addr) -> Optional[bytes]:
        """Handle SendRRData - parse CPF items and route CIP request."""
        if len(data) < 10:
            return self._build_response(ENCAP_SEND_RR_DATA, session, context, b'', status=1)

        # Skip interface handle (4) + timeout (2)
        item_count = struct.unpack_from('<H', data, 6)[0]
        offset = 8

        # Parse CPF items
        for _ in range(item_count):
            if offset + 4 > len(data):
                break
            type_id, length = struct.unpack_from('<HH', data, offset)
            offset += 4
            if type_id == 0x00B2:  # Unconnected Data Item
                cip_data = data[offset:offset + length]
                cip_response = self._handle_cip(cip_data, addr)
                # Build response CPF
                resp = struct.pack('<IH', 0, 0)  # interface=0, timeout=0
                resp += struct.pack('<H', 2)  # 2 items
                resp += struct.pack('<HH', 0x0000, 0)  # Null Address
                resp += struct.pack('<HH', 0x00B2, len(cip_response))  # Data Item
                resp += cip_response
                return self._build_response(ENCAP_SEND_RR_DATA, session, context, resp)
            offset += length

        return self._build_response(ENCAP_SEND_RR_DATA, session, context, b'', status=1)

    def _handle_cip(self, data: bytes, addr) -> bytes:
        """Handle CIP request and return CIP response."""
        if len(data) < 2:
            return struct.pack('<BB', 0x80 | 0x01, 0) + struct.pack('<BB', 0x08, 0)

        service = data[0]
        path_size = data[1]  # in 16-bit words
        path = data[2:2 + path_size * 2]
        payload = data[2 + path_size * 2:]

        # Parse path to get class/instance
        class_id, instance_id = self._parse_epath(path)

        if service == CIP_GET_ATTRIBUTE_ALL and class_id == CIP_CLASS_IDENTITY:
            self.logger.info(f"[EtherNet/IP] CIP GetAttributeAll Identity from {addr[0]}")
            return self._build_identity_object_response(service)

        elif service == CIP_READ_TAG:
            tag_name = self._extract_tag_name(path)
            self.logger.info(f"[EtherNet/IP] CIP ReadTag '{tag_name}' from {addr[0]}")
            return self._build_read_tag_response(service, tag_name)

        elif service == CIP_WRITE_TAG:
            tag_name = self._extract_tag_name(path)
            self.logger.info(f"[EtherNet/IP] CIP WriteTag '{tag_name}' from {addr[0]}")
            return self._handle_write_tag(service, tag_name, payload, addr)

        # Unknown service - generic error
        return struct.pack('<BBH', service | 0x80, 0, 0x0008)  # service not supported

    def _parse_epath(self, path: bytes) -> tuple:
        """Parse CIP EPATH segments."""
        class_id = 0
        instance_id = 1
        offset = 0
        while offset + 2 <= len(path):
            seg_type = path[offset]
            if seg_type == 0x20:  # 8-bit Class ID
                class_id = path[offset + 1]
                offset += 2
            elif seg_type == 0x24:  # 8-bit Instance ID
                instance_id = path[offset + 1]
                offset += 2
            elif seg_type == 0x21:  # 16-bit Class ID
                if offset + 4 <= len(path):
                    class_id = struct.unpack_from('<H', path, offset + 2)[0]
                    offset += 4
                else:
                    break
            elif seg_type == 0x25:  # 16-bit Instance ID
                if offset + 4 <= len(path):
                    instance_id = struct.unpack_from('<H', path, offset + 2)[0]
                    offset += 4
                else:
                    break
            elif seg_type == 0x91:  # ANSI Extended Symbol segment (tag name)
                break
            else:
                offset += 2
        return class_id, instance_id

    def _extract_tag_name(self, path: bytes) -> str:
        """Extract tag name from ANSI Extended Symbol segment in path."""
        offset = 0
        while offset < len(path):
            if path[offset] == 0x91:  # ANSI Extended Symbol
                name_len = path[offset + 1]
                name = path[offset + 2:offset + 2 + name_len].decode('utf-8', errors='replace')
                return name
            offset += 2
        return ''

    def _build_identity_object_response(self, service) -> bytes:
        """Build CIP Identity Object Get Attribute All response."""
        name_bytes = self.PRODUCT_NAME.encode('utf-8')
        resp = struct.pack('<BBH', service | 0x80, 0, 0x0000)  # success
        resp += struct.pack('<H', self.VENDOR_ID)
        resp += struct.pack('<H', self.DEVICE_TYPE)
        resp += struct.pack('<H', self.PRODUCT_CODE)
        resp += struct.pack('<BB', self.REVISION_MAJOR, self.REVISION_MINOR)
        resp += struct.pack('<H', 0x0030)  # status
        resp += struct.pack('<I', self.SERIAL_NUMBER)
        resp += struct.pack('<B', len(name_bytes)) + name_bytes
        resp += struct.pack('<B', self.STATE_RUNNING)
        return resp

    def _build_read_tag_response(self, service, tag_name: str) -> bytes:
        """Build CIP ReadTag response with tag value."""
        value = self.tags.get(tag_name)
        if value is None:
            return struct.pack('<BBH', service | 0x80, 0, 0x0005)  # path destination unknown

        tag_type = self.tag_types.get(tag_name, CIP_REAL)

        resp = struct.pack('<BBH', service | 0x80, 0, 0x0000)  # success
        resp += struct.pack('<H', tag_type)

        if tag_type == CIP_REAL:
            resp += struct.pack('<f', float(value))
        elif tag_type == CIP_BOOL:
            resp += struct.pack('<B', 1 if value else 0)
        elif tag_type == CIP_DINT:
            resp += struct.pack('<i', int(value))
        elif tag_type == CIP_INT:
            resp += struct.pack('<h', int(value))
        else:
            resp += struct.pack('<f', float(value))

        return resp

    def _handle_write_tag(self, service, tag_name: str, payload: bytes, addr) -> bytes:
        """Handle CIP WriteTag - execute command if mapped."""
        if tag_name not in self.tags:
            return struct.pack('<BBH', service | 0x80, 0, 0x0005)

        # Parse type and value from payload
        if len(payload) >= 2:
            data_type = struct.unpack_from('<H', payload, 0)[0]
            val_data = payload[2:]

            if data_type == CIP_REAL and len(val_data) >= 4:
                value = struct.unpack_from('<f', val_data, 0)[0]
            elif data_type == CIP_BOOL and len(val_data) >= 1:
                value = bool(val_data[0])
            elif data_type == CIP_DINT and len(val_data) >= 4:
                value = struct.unpack_from('<i', val_data, 0)[0]
            else:
                value = bool(val_data[0]) if val_data else False
        else:
            value = False

        self.tags[tag_name] = value

        # Execute command callback if this is a command tag
        mapped_point = self.command_tags.get(tag_name)
        if mapped_point:
            callback = self.command_callbacks.get(mapped_point)
            if callback:
                callback(value)
                self.logger.info(
                    f"[EtherNet/IP] WriteTag {tag_name}={value} -> {mapped_point}")

        return struct.pack('<BBH', service | 0x80, 0, 0x0000)  # success

    def _update_loop(self):
        """Update CIP tags from water tank."""
        tag_map = {
            'WaterLevel': 'water_level', 'Pressure': 'pressure',
            'Temperature': 'temperature',
            'InletValve': 'inlet_valve_status',
            'OutletValve': 'outlet_valve_status',
            'PumpRunning': 'pump_status',
            'AutoMode': 'auto_mode_status',
            'AlarmOverflow': 'alarm_overflow',
            'AlarmLowLevel': 'alarm_low_level',
            'AlarmHighPressure': 'alarm_high_pressure',
            'InletFlowRate': 'inlet_flow_rate',
            'OutletFlowRate': 'outlet_flow_rate',
        }
        while self.running:
            try:
                for tag, point in tag_map.items():
                    cb = WaterTankProtocolMapper.get_measurement_callback(
                        self.water_tank, point)
                    if cb:
                        val = cb()
                        self.tags[tag] = float(val) if isinstance(val, (int, float)) else bool(val)
                time.sleep(0.2)
            except Exception as e:
                self.logger.error(f"EtherNet/IP update error: {e}")
                time.sleep(1)

    def stop(self):
        self.running = False
        if self.server_socket:
            self.server_socket.close()
        if self.server_thread:
            self.server_thread.join(timeout=2)
        if self.update_thread:
            self.update_thread.join(timeout=2)
        self.logger.info("EtherNet/IP stopped")

    def update_data_point(self, name: str, value: Any):
        pass
