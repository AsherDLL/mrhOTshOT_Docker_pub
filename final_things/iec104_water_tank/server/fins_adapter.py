"""
OMRON FINS Protocol Adapter

Emulates an Omron NJ501-1300 PLC using FINS (Factory Interface Network Service)
over UDP. This is the exact attack surface that PIPEDREAM/INCONTROLLER
malware (2022) targets to manipulate Omron controllers.

FINS Memory Layout (mapped to gas pipeline process):
  CIO[0-7]:   Digital I/O status (valve states, compressor, alarms)
  DM[100]:    Outlet pressure (float as 2 x uint16)
  DM[102]:    Inlet pressure
  DM[104]:    Gas temperature
  DM[106]:    Flow rate
  DM[108]:    Compressor speed
  DM[110]:    Vibration level

Protocol: OMRON FINS UDP
Port: 9600
Target: Omron NJ/NX Series (PIPEDREAM target)
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

# FINS protocol constants
FINS_CMD_MEMORY_READ = 0x0101
FINS_CMD_MEMORY_WRITE = 0x0102
FINS_CMD_CONTROLLER_READ = 0x0501
FINS_CMD_STATUS_READ = 0x0601
FINS_CMD_RUN = 0x0401
FINS_CMD_STOP = 0x0402

FINS_AREA_CIO = 0xB0
FINS_AREA_DM = 0x82
FINS_AREA_WR = 0xB1
FINS_AREA_HR = 0xB2


class FINSAdapter(ProtocolAdapter):
    """OMRON FINS UDP protocol adapter."""

    def __init__(self, water_tank, config: Dict[str, Any]):
        super().__init__(water_tank, config)
        self.host = config.get('host', '0.0.0.0')
        self.port = config.get('port', 9600)
        self.sock = None
        self.server_thread = None
        self.update_thread = None
        # BADOMEN forces the PLC into STOP/ERROR mode -> reads become "not executable",
        # so the operator's FINS polling goes blind. FINS RUN clears it.
        self.faulted = False

        # FINS memory areas
        self.cio = [0] * 256    # Common I/O
        self.dm = [0] * 1024    # Data Memory
        self.wr = [0] * 256     # Work Relay
        self.hr = [0] * 256     # Holding Relay

        self._create_address_mapping()

    def _create_address_mapping(self):
        data_points = WaterTankProtocolMapper.create_data_points()
        for name, definition in data_points.items():
            dp = DataPoint(
                address={'area': 'dm', 'index': 0},
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
            # Also open TCP for nmap omrontcp-info scanning
            self.tcp_sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            self.tcp_sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            self.tcp_sock.bind((self.host, self.port))
            self.tcp_sock.listen(5)
            self.tcp_sock.settimeout(1.0)
            self.logger.info(f"FINS server initialized on {self.host}:{self.port} (UDP+TCP)")
            self.logger.info(f"  PLC: Omron NJ501-1300 (NJ Series Machine Controller)")
            self.logger.info(f"  Firmware: Ver. 1.49")
            return True
        except Exception as e:
            self.logger.error(f"FINS init failed: {e}")
            return False

    def start(self) -> bool:
        try:
            self.running = True
            self.server_thread = threading.Thread(
                target=self._udp_loop, daemon=True, name="FINSServerThread")
            self.server_thread.start()
            threading.Thread(
                target=self._tcp_loop, daemon=True, name="FINSTCPThread").start()
            self.update_thread = threading.Thread(
                target=self._update_loop, daemon=True, name="FINSUpdateThread")
            self.update_thread.start()
            self.logger.info(f"FINS server started on UDP port {self.port}")
            return True
        except Exception as e:
            self.logger.error(f"FINS start failed: {e}")
            self.running = False
            return False

    def _udp_loop(self):
        while self.running:
            try:
                data, addr = self.sock.recvfrom(4096)
                if len(data) < 10:
                    continue
                response = self._process_fins(data, addr)
                if response:
                    self.sock.sendto(response, addr)
            except socket.timeout:
                continue
            except Exception as e:
                if self.running:
                    self.logger.error(f"FINS error: {e}")

    def _tcp_loop(self):
        """Accept FINS/TCP connections (for nmap omrontcp-info scanning)."""
        while self.running:
            try:
                conn, addr = self.tcp_sock.accept()
                self.logger.info(f"[FINS/TCP] Connection from {addr}")
                threading.Thread(target=self._handle_tcp_client,
                                 args=(conn, addr), daemon=True).start()
            except socket.timeout:
                continue
            except Exception as e:
                if self.running:
                    self.logger.error(f"FINS TCP error: {e}")

    def _handle_tcp_client(self, conn, addr):
        """Handle FINS/TCP client - FINS over TCP uses a 16-byte header."""
        conn.settimeout(5.0)
        try:
            while self.running:
                # FINS/TCP header: 'FINS' + length(4) + command(4) + error(4)
                header = b''
                while len(header) < 4:
                    chunk = conn.recv(4 - len(header))
                    if not chunk:
                        return
                    header += chunk
                if header[:4] == b'FINS':
                    # FINS/TCP frame
                    rest = conn.recv(12)
                    if len(rest) < 12:
                        return
                    length = struct.unpack('>I', rest[0:4])[0]
                    tcp_cmd = struct.unpack('>I', rest[4:8])[0]
                    if tcp_cmd == 0:  # Node Address Data Send (handshake)
                        payload = conn.recv(length - 8) if length > 8 else b''
                        # Response: FINS + len + cmd=1 + error=0 + client_node + server_node
                        resp = b'FINS' + struct.pack('>III', 16, 1, 0)
                        resp += struct.pack('>II', 0, 1)  # client=0, server=1
                        conn.sendall(resp)
                    elif tcp_cmd == 2:  # FINS Frame Send
                        payload = conn.recv(length - 8) if length > 8 else b''
                        if len(payload) >= 10:
                            fins_resp = self._process_fins(payload, addr)
                            if fins_resp:
                                tcp_resp = b'FINS' + struct.pack('>III', len(fins_resp) + 8, 2, 0)
                                conn.sendall(tcp_resp + fins_resp)
                else:
                    # Raw FINS frame (no TCP header) - some scanners send this
                    more = conn.recv(4096)
                    data = header + more
                    if len(data) >= 10:
                        resp = self._process_fins(data, addr)
                        if resp:
                            conn.sendall(resp)
        except (socket.timeout, ConnectionResetError, BrokenPipeError):
            pass
        finally:
            conn.close()

    def _process_fins(self, data: bytes, addr) -> Optional[bytes]:
        """Process a FINS UDP frame."""
        # FINS header: 10 bytes (ICF, RSV, GCT, DNA, DA1, DA2, SNA, SA1, SA2, SID)
        if len(data) < 12:
            return None

        header = data[:10]
        cmd_code = struct.unpack('>H', data[10:12])[0]
        cmd_data = data[12:]

        self.logger.info(f"[FINS] CMD={hex(cmd_code)} from {addr}")

        # Build response header (swap source/dest)
        resp_header = bytearray(header)
        resp_header[0] = 0xC0  # Response flag
        resp_header[3], resp_header[6] = header[6], header[3]  # Swap DNA/SNA
        resp_header[4], resp_header[7] = header[7], header[4]  # Swap DA1/SA1
        resp_header[5], resp_header[8] = header[8], header[5]  # Swap DA2/SA2

        # Response code (success)
        resp_code = struct.pack('>HHH', cmd_code, 0x0000, 0x0000)

        # BADOMEN: STOP halts the PLC (error mode); RUN resumes it.
        if cmd_code == FINS_CMD_STOP:
            self.faulted = True
            self.logger.warning("[FINS] STOP/RESET received - PLC entering ERROR mode (monitoring lost)")
            return bytes(resp_header) + struct.pack('>HH', cmd_code, 0x0000)
        if cmd_code == FINS_CMD_RUN:
            self.faulted = False
            self.logger.info("[FINS] RUN received - PLC back to RUN mode")
            return bytes(resp_header) + struct.pack('>HH', cmd_code, 0x0000)
        # While faulted, reads/status are "not executable in current mode" (end code 0x2201).
        if self.faulted and cmd_code in (FINS_CMD_MEMORY_READ, FINS_CMD_STATUS_READ):
            return bytes(resp_header) + struct.pack('>HH', cmd_code, 0x2201)

        if cmd_code == FINS_CMD_MEMORY_READ:
            return bytes(resp_header) + self._handle_memory_read(cmd_data)
        elif cmd_code == FINS_CMD_MEMORY_WRITE:
            return bytes(resp_header) + self._handle_memory_write(cmd_data)
        elif cmd_code == FINS_CMD_CONTROLLER_READ:
            return bytes(resp_header) + self._handle_controller_read()
        elif cmd_code == FINS_CMD_STATUS_READ:
            return bytes(resp_header) + self._handle_status_read()
        else:
            # Unknown command - return success with empty data
            return bytes(resp_header) + resp_code

    def _handle_memory_read(self, data: bytes) -> bytes:
        area_code = data[0] if len(data) > 0 else 0
        address = struct.unpack('>H', data[1:3])[0] if len(data) >= 3 else 0
        bit_pos = data[3] if len(data) > 3 else 0
        count = struct.unpack('>H', data[4:6])[0] if len(data) >= 6 else 1

        memory = self._get_memory_area(area_code)
        resp = struct.pack('>HH', FINS_CMD_MEMORY_READ, 0x0000)  # cmd + end code

        for i in range(count):
            idx = address + i
            if idx < len(memory):
                resp += struct.pack('>H', memory[idx] & 0xFFFF)
            else:
                resp += struct.pack('>H', 0)

        return resp

    def _handle_memory_write(self, data: bytes) -> bytes:
        area_code = data[0] if len(data) > 0 else 0
        address = struct.unpack('>H', data[1:3])[0] if len(data) >= 3 else 0
        bit_pos = data[3] if len(data) > 3 else 0
        count = struct.unpack('>H', data[4:6])[0] if len(data) >= 6 else 1

        memory = self._get_memory_area(area_code)
        write_data = data[6:]

        for i in range(count):
            idx = address + i
            if idx < len(memory) and (i * 2 + 1) < len(write_data):
                memory[idx] = struct.unpack('>H', write_data[i*2:i*2+2])[0]

        # Process commands if CIO area
        if area_code == FINS_AREA_CIO:
            self._process_cio_writes(address, count)

        self.logger.info(f"[FINS] Memory write: area={hex(area_code)} addr={address} count={count}")
        return struct.pack('>HH', FINS_CMD_MEMORY_WRITE, 0x0000)

    def _handle_controller_read(self) -> bytes:
        resp = struct.pack('>HH', FINS_CMD_CONTROLLER_READ, 0x0000)
        # Controller model string (20 bytes) - Omron NJ501-1300
        model = b'NJ501-1300\x00' + b'\x00' * 9
        resp += model[:20]
        # Version (20 bytes)
        version = b'Ver. 1.49\x00' + b'\x00' * 10
        resp += version[:20]
        return resp

    def _handle_status_read(self) -> bytes:
        resp = struct.pack('>HH', FINS_CMD_STATUS_READ, 0x0000)
        resp += struct.pack('B', 0x04)  # CPU mode: RUN
        resp += struct.pack('B', 0x00)  # Fatal error flags
        resp += struct.pack('B', 0x00)  # Non-fatal error flags
        return resp

    def _get_memory_area(self, area_code: int) -> list:
        areas = {
            FINS_AREA_CIO: self.cio,
            FINS_AREA_DM: self.dm,
            FINS_AREA_WR: self.wr,
            FINS_AREA_HR: self.hr,
        }
        return areas.get(area_code, self.dm)

    def _process_cio_writes(self, address: int, count: int):
        """Process CIO writes as commands."""
        # CIO[0] bit 0 = inlet valve, bit 1 = outlet valve, bit 2 = pump, bit 3 = auto mode
        if address == 0:
            val = self.cio[0]
            for bit, name in [(0, 'inlet_valve_command'), (1, 'outlet_valve_command'),
                               (2, 'pump_command'), (3, 'auto_mode_command')]:
                cb = self.command_callbacks.get(name)
                if cb:
                    cb(bool(val & (1 << bit)))

    def _float_to_dm(self, value: float) -> tuple:
        """Convert float to two uint16 words (big-endian)."""
        packed = struct.pack('>f', value)
        w1 = struct.unpack('>H', packed[0:2])[0]
        w2 = struct.unpack('>H', packed[2:4])[0]
        return w1, w2

    def _update_loop(self):
        while self.running:
            try:
                # Update DM with process measurements
                measurements = {
                    'water_level': 100, 'pressure': 102, 'temperature': 104,
                }
                for name, dm_addr in measurements.items():
                    cb = WaterTankProtocolMapper.get_measurement_callback(self.water_tank, name)
                    if cb:
                        w1, w2 = self._float_to_dm(float(cb()))
                        self.dm[dm_addr] = w1
                        self.dm[dm_addr + 1] = w2

                # Update CIO with digital status
                status_bits = {
                    'inlet_valve_status': 0, 'outlet_valve_status': 1,
                    'pump_status': 2, 'auto_mode_status': 3,
                    'alarm_overflow': 4, 'alarm_low_level': 5,
                    'alarm_high_pressure': 6, 'tank_exploded': 7,
                }
                cio_val = 0
                for name, bit in status_bits.items():
                    cb = WaterTankProtocolMapper.get_measurement_callback(self.water_tank, name)
                    if cb and cb():
                        cio_val |= (1 << bit)
                self.cio[0] = cio_val

                time.sleep(0.1)
            except Exception as e:
                self.logger.error(f"FINS update error: {e}")
                time.sleep(1)

    def stop(self):
        self.running = False
        if self.sock:
            self.sock.close()
        if hasattr(self, 'tcp_sock') and self.tcp_sock:
            self.tcp_sock.close()
        if self.server_thread:
            self.server_thread.join(timeout=2)
        if self.update_thread:
            self.update_thread.join(timeout=2)
        self.logger.info("FINS server stopped")

    def update_data_point(self, name: str, value: Any):
        pass
