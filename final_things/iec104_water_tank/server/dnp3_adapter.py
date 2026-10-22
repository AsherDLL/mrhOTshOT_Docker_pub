"""
DNP3 (Distributed Network Protocol 3) Adapter for Water Tank

Implements DNP3 outstation (server) for water tank control.
Maps water tank data to DNP3 data types:
- Binary Inputs: Digital status (valve states, alarms)
- Analog Inputs: Measurements (level, pressure, temperature)
- Binary Outputs (CROBs): Digital commands
- Analog Outputs: Setpoints

DNP3 is the dominant SCADA protocol in North American power and water utilities.
Port: 20000 (default, standard is 20000)

This adapter uses a pure-Python DNP3 TCP implementation to avoid
compiled library dependencies, making it portable across platforms.
"""

import threading
import time
import struct
import socket
import logging
from typing import Dict, Any, List, Optional

from server.protocol_adapter import (
    ProtocolAdapter, DataPoint, DataPointType,
    WaterTankProtocolMapper
)


# DNP3 Protocol Constants
DNP3_START_BYTES = b'\x05\x64'
DNP3_DIR_PRM = 0x80  # Direction: master, Primary
DNP3_DIR_SEC = 0x00  # Direction: outstation, Secondary

# Function Codes
FC_CONFIRM = 0
FC_READ = 1
FC_WRITE = 2
FC_SELECT = 3
FC_OPERATE = 4
FC_DIRECT_OPERATE = 5
FC_DIRECT_OPERATE_NR = 6
FC_FREEZE = 7
FC_RESPONSE = 129   # 0x81
FC_UNSOLICITED = 130  # 0x82

# Object Groups
GROUP_BINARY_INPUT = 1
GROUP_BINARY_OUTPUT_STATUS = 10
GROUP_BINARY_OUTPUT_CMD = 12
GROUP_ANALOG_INPUT = 30
GROUP_ANALOG_OUTPUT_STATUS = 40
GROUP_ANALOG_OUTPUT_CMD = 41
GROUP_CLASS_0 = 60

# Variations
VAR_PACKED = 1
VAR_WITH_FLAGS = 2
VAR_FLOAT = 5
VAR_CROB = 1
VAR_INT16 = 2
VAR_FLOAT_CMD = 3

# Internal Indications (IIN)
IIN_RESTART = 0x8000
IIN_NEED_TIME = 0x1000


def _crc16_dnp3(data: bytes) -> int:
    """Calculate DNP3 CRC-16 (polynomial 0x3D65, initial 0x0000, reflected)"""
    crc = 0x0000
    for byte in data:
        crc ^= byte
        for _ in range(8):
            if crc & 0x0001:
                crc = (crc >> 1) ^ 0xA6BC
            else:
                crc >>= 1
    return crc ^ 0xFFFF


class DNP3Adapter(ProtocolAdapter):
    """
    DNP3 protocol adapter - pure-Python outstation

    Implements a simplified DNP3 TCP outstation that handles:
    - Read requests (Class 0 polls, specific object reads)
    - Direct Operate commands (CROBs, analog outputs)
    - Integrity polls
    - Unsolicited responses (optional)

    Data Mapping:
    - Binary Inputs  (Group 1): valve status, pump status, alarms
    - Analog Inputs  (Group 30): water level, pressure, temperature
    - Binary Outputs (Group 10/12): valve commands, pump command, mode
    - Analog Outputs (Group 40/41): valve setpoints
    """

    def __init__(self, water_tank, config: Dict[str, Any]):
        super().__init__(water_tank, config)

        self.host = config.get('host', '0.0.0.0')
        self.port = config.get('port', 20000)
        self.outstation_addr = config.get('outstation_address', 1)
        self.master_addr = config.get('master_address', 100)

        self.server_socket = None
        self.server_thread = None
        self.update_thread = None

        # DNP3 data stores
        self.binary_inputs: Dict[int, bool] = {}    # index -> value
        self.analog_inputs: Dict[int, float] = {}    # index -> value
        self.binary_outputs: Dict[int, bool] = {}    # index -> value
        self.analog_outputs: Dict[int, float] = {}   # index -> value

        # Name-to-index mapping
        self.bi_map: Dict[str, int] = {}
        self.ai_map: Dict[str, int] = {}
        self.bo_map: Dict[str, int] = {}
        self.ao_map: Dict[str, int] = {}

        self.iin = IIN_RESTART  # Initial IIN: device restart

        self._create_address_mapping()

    def _create_address_mapping(self):
        """Create DNP3 point index mapping"""
        data_points = WaterTankProtocolMapper.create_data_points()

        bi_idx = 0
        ai_idx = 0
        bo_idx = 0
        ao_idx = 0

        for name, definition in data_points.items():
            point_type = definition['type']

            if point_type == DataPointType.DIGITAL_INPUT:
                self.bi_map[name] = bi_idx
                self.binary_inputs[bi_idx] = False
                dp = DataPoint(
                    address={'group': GROUP_BINARY_INPUT, 'index': bi_idx},
                    point_type=point_type, name=name,
                    description=definition['description']
                )
                bi_idx += 1

            elif point_type in [DataPointType.SCALED_VALUE, DataPointType.ANALOG_INPUT]:
                self.ai_map[name] = ai_idx
                self.analog_inputs[ai_idx] = 0.0
                dp = DataPoint(
                    address={'group': GROUP_ANALOG_INPUT, 'index': ai_idx},
                    point_type=point_type, name=name,
                    description=definition['description'],
                    min_value=definition.get('min'),
                    max_value=definition.get('max')
                )
                ai_idx += 1

            elif point_type == DataPointType.DIGITAL_OUTPUT:
                self.bo_map[name] = bo_idx
                self.binary_outputs[bo_idx] = False
                dp = DataPoint(
                    address={'group': GROUP_BINARY_OUTPUT_CMD, 'index': bo_idx},
                    point_type=point_type, name=name,
                    description=definition['description']
                )
                bo_idx += 1

            elif point_type == DataPointType.ANALOG_OUTPUT:
                self.ao_map[name] = ao_idx
                self.analog_outputs[ao_idx] = 0.0
                dp = DataPoint(
                    address={'group': GROUP_ANALOG_OUTPUT_CMD, 'index': ao_idx},
                    point_type=point_type, name=name,
                    description=definition['description'],
                    min_value=definition.get('min'),
                    max_value=definition.get('max')
                )
                ao_idx += 1
            else:
                continue

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

            self.logger.info(f"DNP3 outstation initialized on {self.host}:{self.port}")
            self.logger.info(f"  Outstation Address: {self.outstation_addr}")
            self.logger.info(f"  Binary Inputs: {len(self.binary_inputs)}")
            self.logger.info(f"  Analog Inputs: {len(self.analog_inputs)}")
            self.logger.info(f"  Binary Outputs: {len(self.binary_outputs)}")
            self.logger.info(f"  Analog Outputs: {len(self.analog_outputs)}")
            return True
        except Exception as e:
            self.logger.error(f"Failed to initialize DNP3 outstation: {e}")
            return False

    def start(self) -> bool:
        try:
            self.running = True
            self.server_thread = threading.Thread(
                target=self._accept_loop, daemon=True, name="DNP3AcceptThread"
            )
            self.server_thread.start()

            self.update_thread = threading.Thread(
                target=self._update_loop, daemon=True, name="DNP3UpdateThread"
            )
            self.update_thread.start()

            self.logger.info(f"DNP3 outstation started on port {self.port}")
            return True
        except Exception as e:
            self.logger.error(f"Failed to start DNP3 outstation: {e}")
            self.running = False
            return False

    def _accept_loop(self):
        """Accept incoming DNP3 TCP connections"""
        while self.running:
            try:
                conn, addr = self.server_socket.accept()
                self.logger.info(f"DNP3 connection from {addr}")
                t = threading.Thread(
                    target=self._handle_connection, args=(conn, addr),
                    daemon=True
                )
                t.start()
            except socket.timeout:
                continue
            except Exception as e:
                if self.running:
                    self.logger.error(f"Accept error: {e}")

    def _handle_connection(self, conn: socket.socket, addr):
        """Handle a single DNP3 TCP connection"""
        conn.settimeout(5.0)
        buf = b''
        try:
            while self.running:
                try:
                    data = conn.recv(4096)
                    if not data:
                        break
                    buf += data
                    while len(buf) >= 10:
                        # Find start bytes
                        idx = buf.find(DNP3_START_BYTES)
                        if idx < 0:
                            buf = b''
                            break
                        if idx > 0:
                            buf = buf[idx:]
                        if len(buf) < 10:
                            break
                        frame_len = buf[2]
                        # Total link frame = header(10) + user data blocks
                        total = 10 + max(0, frame_len - 5)
                        # Add CRC bytes for data blocks
                        user_data_len = max(0, frame_len - 5)
                        num_blocks = (user_data_len + 15) // 16 if user_data_len > 0 else 0
                        total = 10 + user_data_len + num_blocks * 2
                        if len(buf) < total:
                            # May not have CRCs, try without
                            total = 10 + user_data_len
                        if len(buf) < total:
                            break
                        frame = buf[:max(total, 10 + user_data_len)]
                        buf = buf[len(frame):]
                        response = self._process_frame(frame)
                        if response:
                            conn.sendall(response)
                except socket.timeout:
                    continue
        except Exception as e:
            self.logger.debug(f"Connection handler error: {e}")
        finally:
            conn.close()
            self.logger.info(f"DNP3 connection closed from {addr}")

    def _process_frame(self, frame: bytes) -> Optional[bytes]:
        """Process a DNP3 link-layer frame and return response"""
        if len(frame) < 10 or frame[0:2] != DNP3_START_BYTES:
            return None

        length = frame[2]
        ctrl = frame[3]
        dst = struct.unpack_from('<H', frame, 4)[0]
        src = struct.unpack_from('<H', frame, 6)[0]

        # Extract transport + application layer (skip link CRCs)
        if length > 5:
            user_data = frame[10:10 + length - 5]
        else:
            user_data = b''

        if len(user_data) < 2:
            # Just a link layer frame, send ACK
            return None

        # Transport layer: first byte
        transport_byte = user_data[0]
        app_data = user_data[1:]

        if len(app_data) < 2:
            return None

        # Application layer
        app_ctrl = app_data[0]
        func_code = app_data[1]
        seq = app_ctrl & 0x0F

        self.logger.info(f"[DNP3] Received FC={func_code} from master {src}")

        if func_code == FC_READ:
            return self._handle_read(src, seq, app_data[2:])
        elif func_code in (FC_DIRECT_OPERATE, FC_DIRECT_OPERATE_NR, FC_OPERATE, FC_SELECT):
            return self._handle_operate(src, seq, app_data[2:], func_code)
        elif func_code == FC_CONFIRM:
            self.iin &= ~IIN_RESTART  # Clear restart bit on confirm
            return None
        else:
            return self._build_response(src, seq, b'')

    def _handle_read(self, master_addr: int, seq: int, obj_data: bytes) -> bytes:
        """Handle Read request - return all data (Class 0 integrity poll)"""
        response_objects = b''

        # Binary Inputs (Group 1, Var 2 - with flags)
        if self.binary_inputs:
            # Object header: group=1, var=2, qualifier=0x01 (8-bit count + index)
            count = len(self.binary_inputs)
            header = struct.pack('BBB', GROUP_BINARY_INPUT, VAR_WITH_FLAGS, 0x01)
            header += struct.pack('B', count)
            obj_bytes = b''
            for idx in sorted(self.binary_inputs.keys()):
                val = self.binary_inputs[idx]
                # Flag byte: bit 7 = online, bit 0 = value
                flags = 0x01 if val else 0x00
                flags |= 0x01 << 7  # ONLINE flag
                obj_bytes += struct.pack('BB', idx, flags)
            response_objects += header + obj_bytes

        # Analog Inputs (Group 30, Var 5 - single-precision float)
        if self.analog_inputs:
            count = len(self.analog_inputs)
            header = struct.pack('BBB', GROUP_ANALOG_INPUT, VAR_FLOAT, 0x01)
            header += struct.pack('B', count)
            obj_bytes = b''
            for idx in sorted(self.analog_inputs.keys()):
                val = self.analog_inputs[idx]
                flags = 0x01 << 7  # ONLINE
                obj_bytes += struct.pack('BB', idx, flags) + struct.pack('<f', val)
            response_objects += header + obj_bytes

        # Binary Output Status (Group 10, Var 2)
        if self.binary_outputs:
            count = len(self.binary_outputs)
            header = struct.pack('BBB', GROUP_BINARY_OUTPUT_STATUS, VAR_WITH_FLAGS, 0x01)
            header += struct.pack('B', count)
            obj_bytes = b''
            for idx in sorted(self.binary_outputs.keys()):
                val = self.binary_outputs[idx]
                flags = 0x01 if val else 0x00
                flags |= 0x01 << 7
                obj_bytes += struct.pack('BB', idx, flags)
            response_objects += header + obj_bytes

        # Analog Output Status (Group 40, Var 3 - float)
        if self.analog_outputs:
            count = len(self.analog_outputs)
            header = struct.pack('BBB', GROUP_ANALOG_OUTPUT_STATUS, VAR_FLOAT_CMD, 0x01)
            header += struct.pack('B', count)
            obj_bytes = b''
            for idx in sorted(self.analog_outputs.keys()):
                val = self.analog_outputs[idx]
                flags = 0x01 << 7
                obj_bytes += struct.pack('BB', idx, flags) + struct.pack('<f', val)
            response_objects += header + obj_bytes

        return self._build_response(master_addr, seq, response_objects)

    def _handle_operate(self, master_addr: int, seq: int,
                        obj_data: bytes, func_code: int) -> bytes:
        """Handle Direct Operate / Select / Operate commands"""
        if len(obj_data) < 3:
            return self._build_response(master_addr, seq, b'')

        group = obj_data[0]
        variation = obj_data[1]
        qualifier = obj_data[2]

        pos = 3
        if qualifier == 0x01:
            # 8-bit count
            if pos >= len(obj_data):
                return self._build_response(master_addr, seq, b'')
            count = obj_data[pos]
            pos += 1

        if group == GROUP_BINARY_OUTPUT_CMD and variation == VAR_CROB:
            # CROB: 1 byte index + 1 byte control + 1 byte count + 4 bytes on-time + 4 bytes off-time + 1 byte status
            while pos + 1 < len(obj_data):
                idx = obj_data[pos]
                pos += 1
                if pos >= len(obj_data):
                    break
                control = obj_data[pos]
                pos += 1
                # Skip count, on-time, off-time, status (9 bytes)
                pos += 9
                op_type = control & 0x0F
                value = (op_type == 3 or op_type == 1)  # LATCH_ON or PULSE_ON

                self.logger.info(f"[DNP3] Binary Output command: idx={idx} value={value}")
                self.binary_outputs[idx] = value

                # Find and execute callback
                for name, bo_idx in self.bo_map.items():
                    if bo_idx == idx:
                        callback = self.command_callbacks.get(name)
                        if callback:
                            callback(value)
                        break

        elif group == GROUP_ANALOG_OUTPUT_CMD:
            while pos + 1 < len(obj_data):
                idx = obj_data[pos]
                pos += 1
                if variation == VAR_FLOAT_CMD and pos + 5 <= len(obj_data):
                    value = struct.unpack_from('<f', obj_data, pos)[0]
                    pos += 4
                    status = obj_data[pos] if pos < len(obj_data) else 0
                    pos += 1
                elif pos + 3 <= len(obj_data):
                    value = float(struct.unpack_from('<h', obj_data, pos)[0])
                    pos += 2
                    status = obj_data[pos] if pos < len(obj_data) else 0
                    pos += 1
                else:
                    break

                self.logger.info(f"[DNP3] Analog Output command: idx={idx} value={value:.2f}")
                self.analog_outputs[idx] = value

                for name, ao_idx in self.ao_map.items():
                    if ao_idx == idx:
                        callback = self.command_callbacks.get(name)
                        if callback:
                            callback(value)
                        break

        return self._build_response(master_addr, seq, b'')

    def _build_response(self, master_addr: int, seq: int, app_objects: bytes) -> bytes:
        """Build a DNP3 response frame"""
        # Application layer
        app_ctrl = 0xC0 | (seq & 0x0F)  # FIR=1, FIN=1, SEQ
        iin_bytes = struct.pack('>H', self.iin)
        app_layer = struct.pack('BB', app_ctrl, FC_RESPONSE) + iin_bytes + app_objects

        # Transport layer
        transport = struct.pack('B', 0xC0) + app_layer  # FIR=1, FIN=1

        # Link layer
        length = len(transport) + 5  # 5 = ctrl(1) + dst(2) + src(2)
        link_header = DNP3_START_BYTES + struct.pack('B', length)
        link_header += struct.pack('B', DNP3_DIR_SEC)  # Direction: outstation
        link_header += struct.pack('<H', master_addr)
        link_header += struct.pack('<H', self.outstation_addr)
        crc = _crc16_dnp3(link_header[0:8])
        link_header += struct.pack('<H', crc)

        # Add data block CRCs (every 16 bytes)
        frame = link_header
        for i in range(0, len(transport), 16):
            block = transport[i:i+16]
            crc = _crc16_dnp3(block)
            frame += block + struct.pack('<H', crc)

        return frame

    def _update_loop(self):
        """Update DNP3 data from water tank"""
        while self.running:
            try:
                for name, idx in self.ai_map.items():
                    callback = WaterTankProtocolMapper.get_measurement_callback(
                        self.water_tank, name
                    )
                    if callback:
                        self.analog_inputs[idx] = float(callback())

                for name, idx in self.bi_map.items():
                    callback = WaterTankProtocolMapper.get_measurement_callback(
                        self.water_tank, name
                    )
                    if callback:
                        self.binary_inputs[idx] = bool(callback())

                time.sleep(0.1)
            except Exception as e:
                self.logger.error(f"DNP3 update loop error: {e}")
                time.sleep(1)

    def stop(self):
        self.running = False
        if self.server_socket:
            self.server_socket.close()
        if self.server_thread:
            self.server_thread.join(timeout=2)
        if self.update_thread:
            self.update_thread.join(timeout=2)
        self.logger.info("DNP3 outstation stopped")

    def update_data_point(self, name: str, value: Any):
        if name in self.bi_map:
            self.binary_inputs[self.bi_map[name]] = bool(value)
        elif name in self.ai_map:
            self.analog_inputs[self.ai_map[name]] = float(value)
