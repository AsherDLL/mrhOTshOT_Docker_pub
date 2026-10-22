"""
M-Bus (Meter-Bus) Sensor Gateway Adapter

Emulates an M-Bus TCP gateway (EN 13757-3) for field sensor metering.
Serves water tank sensor data over M-Bus protocol - the attack surface
that Fuxnet malware exploits to destroy sensor gateways.

Port: 5000 (standard M-Bus TCP gateway port)
"""

import threading
import time
import socket
import logging
from typing import Dict, Any, Optional

from server.protocol_adapter import (
    ProtocolAdapter, DataPoint, DataPointType,
    WaterTankProtocolMapper
)
from server.mbus_lib import (
    ACK, LONG, SHORT, BROADCAST,
    C_SND_NKE, C_SND_UD, C_REQ_UD2, C_REQ_UD2B,
    VIF_VOLUME, VIF_PRESSURE, VIF_TEMP, VIF_FLOW,
    build_rsp_ud, encode_record,
)


class MBusAdapter(ProtocolAdapter):
    """M-Bus TCP gateway adapter for sensor metering."""

    def __init__(self, water_tank, config: Dict[str, Any]):
        super().__init__(water_tank, config)
        self.host = config.get('host', '0.0.0.0')
        self.port = config.get('port', 5000)
        self.server_socket = None
        self.server_thread = None
        self.update_thread = None

        # Sensor values (updated from water tank)
        self.volume = 500.0       # liters
        self.pressure = 1.5       # bar
        self.temperature = 20.0   # C
        self.flow_rate = 0.0      # L/s

        # Gateway state (for Fuxnet simulation)
        self.state = 'ONLINE'  # ONLINE, CORRUPTED, OFFLINE
        self._junk_count = 0   # frames that are garbage/SND_UD floods

        self._create_address_mapping()

    def _create_address_mapping(self):
        data_points = WaterTankProtocolMapper.create_data_points()
        for name, definition in data_points.items():
            dp = DataPoint(
                address={'type': 'mbus_record'},
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
            self.logger.info(f"M-Bus gateway initialized on {self.host}:{self.port}")
            return True
        except Exception as e:
            self.logger.error(f"M-Bus init failed: {e}")
            return False

    def start(self) -> bool:
        try:
            self.running = True
            self.server_thread = threading.Thread(
                target=self._accept_loop, daemon=True, name="MBusAcceptThread")
            self.server_thread.start()
            self.update_thread = threading.Thread(
                target=self._update_loop, daemon=True, name="MBusUpdateThread")
            self.update_thread.start()
            self.logger.info(f"M-Bus gateway started on port {self.port}")
            return True
        except Exception as e:
            self.logger.error(f"M-Bus start failed: {e}")
            self.running = False
            return False

    def _accept_loop(self):
        while self.running:
            try:
                conn, addr = self.server_socket.accept()
                self.logger.info(f"[M-Bus] Connection from {addr}")
                t = threading.Thread(
                    target=self._handle_connection, args=(conn, addr), daemon=True)
                t.start()
            except socket.timeout:
                continue
            except Exception as e:
                if self.running:
                    self.logger.error(f"M-Bus accept error: {e}")

    def _handle_connection(self, conn: socket.socket, addr):
        conn.settimeout(5.0)
        try:
            while self.running:
                try:
                    data = conn.recv(256)
                    if not data:
                        break
                    response = self._process_frame(data)
                    if response is None and self.state == 'OFFLINE':
                        break  # gateway bricked - drop connection
                    elif response:
                        conn.sendall(response)
                except socket.timeout:
                    continue
        except Exception:
            pass
        finally:
            conn.close()

    def _process_frame(self, data: bytes) -> Optional[bytes]:
        if self.state == 'OFFLINE':
            return None

        if len(data) < 5:
            self._count_junk()
            return None

        start = data[0]

        if start == SHORT:
            c_field = data[1]
            address = data[2]
            if c_field == C_SND_NKE:
                if address == BROADCAST:
                    # Broadcast reset - kill shot (same frame as HMI Reset Gateway button)
                    self._trigger_offline()
                    return None
                self.logger.info(f"[M-Bus] SND_NKE addr={address}")
                return bytes([ACK])
            elif c_field in (C_REQ_UD2, C_REQ_UD2B):
                self.logger.info(f"[M-Bus] REQ_UD2 addr={address}")
                return self._build_data_response(address)
            else:
                self._count_junk()
                return bytes([ACK])

        elif start == LONG:
            length = data[1]
            if len(data) >= 4 + length:
                c_field = data[4]
                self.logger.info(f"[M-Bus] Long frame C={c_field:#04x}")
                if c_field == C_SND_UD:   # Fuxnet Phase 2 corruption payload
                    self._count_junk()
                return bytes([ACK])
            else:
                self._count_junk()
                return bytes([ACK])
        else:
            self._count_junk()
            return None

    def _count_junk(self):
        self._junk_count += 1
        if self._junk_count == 10 and self.state == 'ONLINE':
            self.state = 'CORRUPTED'
            try:
                self.water_tank.process.execute_command('CorruptCmd', True)
            except Exception:
                pass
            self.logger.critical("[FUXNET] GATEWAY CORRUPTED - sensor data poisoned!")

    def _trigger_offline(self):
        """Broadcast SND_NKE (addr=0xFF) - the M-Bus kill shot."""
        self.state = 'OFFLINE'
        try:
            self.water_tank.process.execute_command('CorruptCmd', True)
            self.water_tank.process.execute_command('GatewayShutdownCmd', True)
        except Exception:
            pass
        self.logger.critical("[FUXNET] GATEWAY OFFLINE - broadcast reset destroyed all slaves!")

    def _build_data_response(self, address: int) -> Optional[bytes]:
        """Build M-Bus RSP_UD response using mbus_lib."""
        if self.state == 'OFFLINE':
            return None

        corrupted = self.state == 'CORRUPTED'
        vol  = self.volume      if not corrupted else 99999.9
        pres = self.pressure    if not corrupted else 0.0
        temp = self.temperature if not corrupted else -40.0
        flow = self.flow_rate   if not corrupted else 0.0

        records  = encode_record(0x04, VIF_VOLUME,   int(vol  * 10),          4)  # L/10
        records += encode_record(0x04, VIF_PRESSURE, int(pres * 1000),        4)  # 10^-3 bar
        records += encode_record(0x02, VIF_TEMP,     int(temp * 100) & 0xFFFF, 2) # 10^-2 °C
        records += encode_record(0x02, VIF_FLOW,     int(flow * 3600) & 0xFFFF, 2) # L/h

        return build_rsp_ud(address, records)

    def _update_loop(self):
        while self.running:
            try:
                level_cb = WaterTankProtocolMapper.get_measurement_callback(self.water_tank, 'water_level')
                pres_cb = WaterTankProtocolMapper.get_measurement_callback(self.water_tank, 'pressure')
                temp_cb = WaterTankProtocolMapper.get_measurement_callback(self.water_tank, 'temperature')

                if level_cb:
                    self.volume = float(level_cb()) / 100.0 * 1000.0  # % to liters
                if pres_cb:
                    self.pressure = float(pres_cb())
                if temp_cb:
                    self.temperature = float(temp_cb())

                time.sleep(0.5)
            except Exception as e:
                self.logger.error(f"M-Bus update error: {e}")
                time.sleep(1)

    def stop(self):
        self.running = False
        if self.server_socket:
            self.server_socket.close()
        if self.server_thread:
            self.server_thread.join(timeout=2)
        if self.update_thread:
            self.update_thread.join(timeout=2)
        self.logger.info("M-Bus gateway stopped")

    def update_data_point(self, name: str, value: Any):
        pass
