"""
Mitsubishi MELSEC Communication Protocol (MC Protocol) Adapter

Emulates a Mitsubishi iQ-R Series R04CPU PLC using the MELSEC MC
(MELSOFT Communication) binary protocol over TCP.

Mitsubishi PLCs are dominant in Asian manufacturing, semiconductor
fabrication, water/wastewater treatment, and building automation.

Protocol: MC Protocol Binary (3E frame)
Port: 5007
Target: Mitsubishi MELSEC iQ-R / Q Series
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

# MC Protocol 3E Frame constants
MC_SUBHEADER_REQ = 0x5000
MC_SUBHEADER_RESP = 0xD000

# MC Protocol Commands
MC_CMD_BATCH_READ = 0x0401
MC_CMD_BATCH_WRITE = 0x1401
MC_CMD_RANDOM_READ = 0x0403
MC_CMD_RANDOM_WRITE = 0x1402
MC_CMD_MONITOR = 0x0801

# MC Protocol Sub-commands
MC_SUBCMD_WORD = 0x0000
MC_SUBCMD_BIT = 0x0001

# Device Codes (binary mode)
DEV_D = 0xA8   # Data register (16-bit word)
DEV_M = 0x90   # Internal relay (bit)
DEV_X = 0x9C   # Input (bit)
DEV_Y = 0x9D   # Output (bit)
DEV_R = 0xAF   # File register (16-bit word)
DEV_W = 0xB4   # Link register (16-bit word)
DEV_B = 0xA0   # Link relay (bit)
DEV_ZR = 0xB0  # Extended file register

# End codes
MC_END_OK = 0x0000
MC_END_WRONG_COMMAND = 0xC059
MC_END_WRONG_DEVICE = 0xC0B5


class MELSECAdapter(ProtocolAdapter):
    """
    MELSEC MC Protocol adapter emulating Mitsubishi iQ-R Series PLC.

    Memory layout:
    - D0-D19: Analog measurements (water level, pressure, temp, flow, etc.)
    - M0-M19: Digital status bits (valve status, alarms, etc.)
    - Y0-Y9:  Digital command outputs (valve commands, pump, etc.)
    - D100-D109: Analog setpoints

    Responds to MC Protocol binary 3E frame requests for:
    - Batch Read (word/bit devices)
    - Batch Write (word/bit devices)
    """

    # Mitsubishi iQ-R identity
    PLC_MODEL = "R04CPU"
    PLC_SERIES = "iQ-R Series"
    CPU_TYPE = 0x0042  # R04CPU type code

    def __init__(self, water_tank, config: Dict[str, Any]):
        super().__init__(water_tank, config)
        self.host = config.get('host', '0.0.0.0')
        self.port = config.get('port', 5007)
        self.server_socket = None
        self.server_thread = None
        self.update_thread = None

        # D registers (16-bit words) - measurements & setpoints
        self.d_registers = [0] * 200  # D0-D199

        # M relays (bits) - status
        self.m_relays = [0] * 100  # M0-M99

        # Y outputs (bits) - commands
        self.y_outputs = [0] * 20  # Y0-Y19

        # X inputs (bits) - mirrored from status
        self.x_inputs = [0] * 20  # X0-X19

        # Track previous command states
        self.previous_command_states = {}

        # D register mapping for measurements
        self.d_map = {
            0: 'water_level',      # D0
            2: 'pressure',         # D2
            4: 'temperature',      # D4
            6: 'inlet_flow_rate',  # D6
            8: 'outlet_flow_rate', # D8
        }

        # M relay mapping for status
        self.m_map = {
            0: 'inlet_valve_status',
            1: 'outlet_valve_status',
            2: 'pump_status',
            3: 'auto_mode_status',
            4: 'alarm_overflow',
            5: 'alarm_low_level',
            6: 'alarm_high_pressure',
            7: 'tank_exploded',
            8: 'sis_tripped',
        }

        # Y output mapping for commands
        self.y_cmd_map = {
            0: 'inlet_valve_command',
            1: 'outlet_valve_command',
            2: 'pump_command',
            3: 'auto_mode_command',
            4: 'sis_trip_command',
        }

        self._create_address_mapping()

    def _create_address_mapping(self):
        data_points = WaterTankProtocolMapper.create_data_points()
        for name, definition in data_points.items():
            dp = DataPoint(
                address={'type': 'melsec'},
                point_type=definition['type'], name=name,
                description=definition['description'],
                min_value=definition.get('min'),
                max_value=definition.get('max')
            )
            self.register_data_point(name, dp)
            callback = WaterTankProtocolMapper.get_command_callback(self.water_tank, name)
            if callback:
                self.register_command_callback(name, callback)

        # Initialize command states
        for y_addr, cmd_name in self.y_cmd_map.items():
            self.previous_command_states[cmd_name] = False

    def initialize(self) -> bool:
        try:
            self.server_socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            self.server_socket.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            self.server_socket.bind((self.host, self.port))
            self.server_socket.listen(5)
            self.server_socket.settimeout(1.0)
            self.logger.info(f"MELSEC MC Protocol initialized on {self.host}:{self.port}")
            self.logger.info(f"  PLC: Mitsubishi {self.PLC_SERIES} {self.PLC_MODEL}")
            self.logger.info(f"  Frame: 3E Binary")
            self.logger.info(f"  D registers: D0-D199, M relays: M0-M99")
            return True
        except Exception as e:
            self.logger.error(f"MELSEC init failed: {e}")
            return False

    def start(self) -> bool:
        try:
            self.running = True
            self.server_thread = threading.Thread(
                target=self._accept_loop, daemon=True, name="MELSECThread")
            self.server_thread.start()
            self.update_thread = threading.Thread(
                target=self._update_loop, daemon=True, name="MELSECUpdateThread")
            self.update_thread.start()
            self.logger.info(f"MELSEC MC Protocol started on port {self.port}")
            return True
        except Exception as e:
            self.logger.error(f"MELSEC start failed: {e}")
            self.running = False
            return False

    def _accept_loop(self):
        while self.running:
            try:
                conn, addr = self.server_socket.accept()
                self.logger.info(f"[MELSEC] Connection from {addr}")
                t = threading.Thread(
                    target=self._handle_connection, args=(conn, addr), daemon=True)
                t.start()
            except socket.timeout:
                continue
            except Exception as e:
                if self.running:
                    self.logger.error(f"MELSEC accept error: {e}")

    def _handle_connection(self, conn: socket.socket, addr):
        conn.settimeout(10.0)
        try:
            while self.running:
                try:
                    # MC 3E frame: subheader(2) + network(1) + pc(1) + dest_io(2)
                    #   + dest_station(1) + data_len(2) + timer(2) + ...
                    header = self._recv_exact(conn, 9)
                    if not header:
                        break

                    subheader = struct.unpack_from('<H', header, 0)[0]
                    if subheader != MC_SUBHEADER_REQ:
                        continue

                    data_len = struct.unpack_from('<H', header, 7)[0]
                    payload = self._recv_exact(conn, data_len)
                    if not payload:
                        break

                    response = self._process_frame(header, payload, addr)
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

    def _process_frame(self, header: bytes, payload: bytes, addr) -> Optional[bytes]:
        """Process MC Protocol 3E frame request."""
        if len(payload) < 4:
            return self._build_error_response(header, MC_END_WRONG_COMMAND)

        # Skip monitoring timer (2 bytes)
        timer = struct.unpack_from('<H', payload, 0)[0]
        command = struct.unpack_from('<H', payload, 2)[0]
        sub_command = struct.unpack_from('<H', payload, 4)[0]
        cmd_data = payload[6:]

        if command == MC_CMD_BATCH_READ:
            return self._handle_batch_read(header, sub_command, cmd_data, addr)
        elif command == MC_CMD_BATCH_WRITE:
            return self._handle_batch_write(header, sub_command, cmd_data, addr)
        else:
            self.logger.info(f"[MELSEC] Unknown command 0x{command:04X} from {addr[0]}")
            return self._build_error_response(header, MC_END_WRONG_COMMAND)

    def _handle_batch_read(self, header, sub_command, data, addr) -> bytes:
        """Handle MC batch read command."""
        if len(data) < 4:
            return self._build_error_response(header, MC_END_WRONG_COMMAND)

        # Parse device: head_device(3 bytes) + device_code(1) + num_points(2)
        head_device = struct.unpack_from('<I', data, 0)[0] & 0xFFFFFF  # 24-bit
        device_code = data[3]
        num_points = struct.unpack_from('<H', data, 4)[0]

        dev_name = {DEV_D: 'D', DEV_M: 'M', DEV_X: 'X', DEV_Y: 'Y',
                    DEV_R: 'R', DEV_W: 'W'}.get(device_code, f'?({device_code:#x})')
        self.logger.info(
            f"[MELSEC] BatchRead {dev_name}{head_device} x{num_points} from {addr[0]}")

        resp_data = b''

        if sub_command == MC_SUBCMD_WORD:
            # Read word devices
            for i in range(num_points):
                addr_i = head_device + i
                val = self._read_word_device(device_code, addr_i)
                resp_data += struct.pack('<H', val & 0xFFFF)

        elif sub_command == MC_SUBCMD_BIT:
            # Read bit devices - pack 2 bits per byte (high/low nibble)
            for i in range(0, num_points, 2):
                lo = self._read_bit_device(device_code, head_device + i)
                hi = self._read_bit_device(device_code, head_device + i + 1) if i + 1 < num_points else 0
                resp_data += struct.pack('B', (hi << 4) | lo)

        return self._build_response(header, resp_data)

    def _handle_batch_write(self, header, sub_command, data, addr) -> bytes:
        """Handle MC batch write command."""
        if len(data) < 4:
            return self._build_error_response(header, MC_END_WRONG_COMMAND)

        head_device = struct.unpack_from('<I', data, 0)[0] & 0xFFFFFF
        device_code = data[3]
        num_points = struct.unpack_from('<H', data, 4)[0]
        val_data = data[6:]

        dev_name = {DEV_D: 'D', DEV_M: 'M', DEV_X: 'X', DEV_Y: 'Y',
                    DEV_R: 'R', DEV_W: 'W'}.get(device_code, '?')

        if sub_command == MC_SUBCMD_WORD:
            for i in range(num_points):
                if 2 * i + 2 <= len(val_data):
                    val = struct.unpack_from('<H', val_data, 2 * i)[0]
                    self._write_word_device(device_code, head_device + i, val)
            self.logger.info(
                f"[MELSEC] BatchWrite {dev_name}{head_device} x{num_points} from {addr[0]}")

        elif sub_command == MC_SUBCMD_BIT:
            for i in range(num_points):
                byte_idx = i // 2
                if byte_idx < len(val_data):
                    nibble = (val_data[byte_idx] >> 4) if (i % 2 == 1) else (val_data[byte_idx] & 0x0F)
                    self._write_bit_device(device_code, head_device + i, nibble)
            self.logger.info(
                f"[MELSEC] BatchWrite(bit) {dev_name}{head_device} x{num_points} from {addr[0]}")

        # Execute command callbacks for Y outputs
        self._check_y_commands()

        return self._build_response(header, b'')

    def _read_word_device(self, dev_code, addr) -> int:
        if dev_code == DEV_D and 0 <= addr < len(self.d_registers):
            return self.d_registers[addr]
        elif dev_code == DEV_R and 0 <= addr < len(self.d_registers):
            return self.d_registers[addr]  # R maps to same store
        elif dev_code in (DEV_M, DEV_X, DEV_Y):
            # Pack 16 bits from bit devices
            store = self._get_bit_store(dev_code)
            val = 0
            for b in range(16):
                idx = addr * 16 + b
                if idx < len(store) and store[idx]:
                    val |= (1 << b)
            return val
        return 0

    def _read_bit_device(self, dev_code, addr) -> int:
        store = self._get_bit_store(dev_code)
        if 0 <= addr < len(store):
            return 1 if store[addr] else 0
        return 0

    def _write_word_device(self, dev_code, addr, val):
        if dev_code == DEV_D and 0 <= addr < len(self.d_registers):
            self.d_registers[addr] = val & 0xFFFF
        elif dev_code == DEV_R and 0 <= addr < len(self.d_registers):
            self.d_registers[addr] = val & 0xFFFF

    def _write_bit_device(self, dev_code, addr, val):
        store = self._get_bit_store(dev_code)
        if 0 <= addr < len(store):
            store[addr] = 1 if val else 0

    def _get_bit_store(self, dev_code) -> list:
        if dev_code == DEV_M:
            return self.m_relays
        elif dev_code == DEV_Y:
            return self.y_outputs
        elif dev_code == DEV_X:
            return self.x_inputs
        return []

    def _check_y_commands(self):
        """Check Y outputs for command changes and execute callbacks."""
        for y_addr, cmd_name in self.y_cmd_map.items():
            current = bool(self.y_outputs[y_addr]) if y_addr < len(self.y_outputs) else False
            prev = self.previous_command_states.get(cmd_name)
            if prev != current:
                self.previous_command_states[cmd_name] = current
                callback = self.command_callbacks.get(cmd_name)
                if callback:
                    callback(current)
                    self.logger.info(f"[MELSEC] Y{y_addr} ({cmd_name}) = {current}")

    def _build_response(self, req_header: bytes, data: bytes) -> bytes:
        """Build MC Protocol 3E response frame."""
        # Response header: subheader(2) + network(1) + pc(1) + dest_io(2)
        #   + dest_station(1) + data_len(2) + end_code(2) + data
        resp = struct.pack('<H', MC_SUBHEADER_RESP)
        resp += req_header[2:7]  # copy network, pc, dest_io, dest_station
        resp += struct.pack('<H', len(data) + 2)  # data_len includes end_code
        resp += struct.pack('<H', MC_END_OK)
        resp += data
        return resp

    def _build_error_response(self, req_header: bytes, end_code: int) -> bytes:
        """Build MC Protocol error response."""
        resp = struct.pack('<H', MC_SUBHEADER_RESP)
        resp += req_header[2:7]
        resp += struct.pack('<H', 2)  # data_len = just end_code
        resp += struct.pack('<H', end_code)
        return resp

    def _update_loop(self):
        """Update MELSEC registers from water tank."""
        while self.running:
            try:
                # Update D registers (measurements) - stored as scaled integers
                for d_addr, point_name in self.d_map.items():
                    cb = WaterTankProtocolMapper.get_measurement_callback(
                        self.water_tank, point_name)
                    if cb:
                        val = float(cb())
                        # Store as fixed-point: value * 100 (2 decimal places)
                        scaled = int(val * 100) & 0xFFFF
                        self.d_registers[d_addr] = scaled & 0xFFFF
                        # High word for 32-bit values
                        self.d_registers[d_addr + 1] = (int(val * 100) >> 16) & 0xFFFF

                # Update M relays (status bits)
                for m_addr, point_name in self.m_map.items():
                    cb = WaterTankProtocolMapper.get_measurement_callback(
                        self.water_tank, point_name)
                    if cb:
                        self.m_relays[m_addr] = 1 if bool(cb()) else 0

                # Mirror M relays to X inputs
                for i in range(min(len(self.m_relays), len(self.x_inputs))):
                    self.x_inputs[i] = self.m_relays[i]

                time.sleep(0.2)
            except Exception as e:
                self.logger.error(f"MELSEC update error: {e}")
                time.sleep(1)

    def stop(self):
        self.running = False
        if self.server_socket:
            self.server_socket.close()
        if self.server_thread:
            self.server_thread.join(timeout=2)
        if self.update_thread:
            self.update_thread.join(timeout=2)
        self.logger.info("MELSEC MC Protocol stopped")

    def update_data_point(self, name: str, value: Any):
        pass
