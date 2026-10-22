#!/usr/bin/env python3
"""
M-Bus Sensor Gateway Server Simulation

Simulates an M-Bus (Meter-Bus, EN 13757-3) sensor gateway for the water tank lab.
Reads water tank sensor data from the PLC via IEC-104 and serves it over M-Bus TCP
on port 5000 - the standard port for M-Bus TCP gateways (Relay/Elvaco/Moxa devices).

This is the attack surface that Fuxnet malware exploits.

M-Bus Frame Format (EN 13757-3):
    Short frame:  [0x10][C][A][checksum][0x16]
    Long frame:   [0x68][L][L][0x68][C][A][CI][data...][checksum][0x16]
    Single char:  [0xE5] (ACK)

Gateway States:
    ONLINE    - Normal operation, returns real sensor values
    CORRUPTED - Returns spoofed sensor values (Fuxnet Phase 2)
    OFFLINE   - Gateway bricked, refuses connections (Fuxnet Phase 3)

Usage:
    python3 mbus_gateway_server.py --plc-ip 127.0.0.1 --plc-port 2404 --mbus-port 5000

WARNING: For authorized security testing only.
"""

import os
import sys
import time
import struct
import socket
import signal
import argparse
import logging
import threading
from datetime import datetime

sys.path.append(os.path.dirname(os.path.abspath(__file__)))

try:
    import c104
    C104_AVAILABLE = True
except ImportError:
    C104_AVAILABLE = False
    print("WARNING: c104 library not available. Install with: pip install c104")

from common.config import *

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - [MBUS-GW] - %(levelname)s - %(message)s',
    datefmt='%Y-%m-%d %H:%M:%S'
)
logger = logging.getLogger('MBusGateway')

# M-Bus protocol constants (EN 13757-3)
MBUS_FRAME_START_LONG = 0x68
MBUS_FRAME_START_SHORT = 0x10
MBUS_FRAME_STOP = 0x16
MBUS_FRAME_ACK = 0xE5

# M-Bus C-field (Control field) values
MBUS_C_SND_NKE = 0x40    # Master: initialization
MBUS_C_SND_UD = 0x53      # Master: send user data (FCB=0)
MBUS_C_SND_UD2 = 0x73     # Master: send user data (FCB=1)
MBUS_C_REQ_UD1 = 0x5A     # Master: request alarm data (FCB=0)
MBUS_C_REQ_UD1_2 = 0x7A   # Master: request alarm data (FCB=1)
MBUS_C_REQ_UD2 = 0x5B     # Master: request user data (FCB=0)
MBUS_C_REQ_UD2_2 = 0x7B   # Master: request user data (FCB=1)
MBUS_C_RSP_UD = 0x08      # Slave: response

# M-Bus CI-field (Control Information) values
MBUS_CI_RSP_VARIABLE = 0x72   # Variable data structure response
MBUS_CI_SND_UD = 0x51         # Send user data

# M-Bus VIF (Value Information Field) - defines units
MBUS_VIF_VOLUME_LITERS = 0x13      # Volume in liters (10^0)
MBUS_VIF_PRESSURE_BAR = 0x48       # Pressure in bar (10^-3)
MBUS_VIF_TEMP_C = 0x59             # Flow temperature in °C (10^-1)
MBUS_VIF_FABRICATION = 0x78        # Fabrication number

# M-Bus DIF (Data Information Field)
MBUS_DIF_INT32 = 0x04   # 32-bit integer, instantaneous
MBUS_DIF_INT16 = 0x02   # 16-bit integer, instantaneous
MBUS_DIF_BCD8 = 0x0C    # 8-digit BCD, instantaneous

# Gateway states
GW_STATE_ONLINE = "ONLINE"
GW_STATE_CORRUPTED = "CORRUPTED"
GW_STATE_OFFLINE = "OFFLINE"


def mbus_checksum(data):
    """Calculate M-Bus checksum (sum of bytes mod 256)"""
    return sum(data) & 0xFF


def build_mbus_short_frame(c_field, address):
    """Build M-Bus short frame: [0x10][C][A][checksum][0x16]"""
    chk = mbus_checksum([c_field, address])
    return bytes([MBUS_FRAME_START_SHORT, c_field, address, chk, MBUS_FRAME_STOP])


def build_mbus_long_frame(c_field, address, ci_field, data):
    """Build M-Bus long frame: [0x68][L][L][0x68][C][A][CI][data...][checksum][0x16]"""
    payload = bytes([c_field, address, ci_field]) + data
    length = len(payload)
    chk = mbus_checksum(payload)
    frame = bytes([MBUS_FRAME_START_LONG, length, length, MBUS_FRAME_START_LONG])
    frame += payload
    frame += bytes([chk, MBUS_FRAME_STOP])
    return frame


def build_mbus_variable_data_record(dif, vif, value_bytes):
    """Build a single M-Bus variable data record: [DIF][VIF][data]"""
    return bytes([dif, vif]) + value_bytes


def build_sensor_response(address, water_level, pressure, temperature, serial=0x12345678):
    """
    Build a complete M-Bus RSP_UD frame with water tank sensor data.

    Fixed data header (12 bytes):
        ID (4 bytes), Manufacturer (2 bytes), Version (1), Medium (1),
        Access number (1), Status (1), Signature (2)

    Variable data blocks:
        Water level (liters), Pressure (bar), Temperature (°C)
    """
    # Fixed data header
    id_bytes = struct.pack('<I', serial)
    manufacturer = struct.pack('<H', 0x4D2A)  # "MCS" - Moscollector Sensors (fake)
    version = bytes([0x01])
    medium = bytes([0x07])  # 0x07 = Water
    access_nr = bytes([0x01])
    status = bytes([0x00])  # 0x00 = no errors
    signature = struct.pack('<H', 0x0000)

    fixed_header = id_bytes + manufacturer + version + medium + access_nr + status + signature

    # Variable data blocks
    # Water level: DIF=0x04 (32-bit int), VIF=0x13 (volume liters)
    level_value = struct.pack('<I', int(water_level * 10))  # 0.1 liter resolution
    level_record = build_mbus_variable_data_record(MBUS_DIF_INT32, MBUS_VIF_VOLUME_LITERS, level_value)

    # Pressure: DIF=0x02 (16-bit int), VIF=0x48 (pressure mbar)
    pressure_value = struct.pack('<H', int(pressure * 1000))  # millibar
    pressure_record = build_mbus_variable_data_record(MBUS_DIF_INT16, MBUS_VIF_PRESSURE_BAR, pressure_value)

    # Temperature: DIF=0x02 (16-bit int), VIF=0x59 (temp 0.1°C)
    temp_value = struct.pack('<H', int(temperature * 10))  # 0.1°C resolution
    temp_record = build_mbus_variable_data_record(MBUS_DIF_INT16, MBUS_VIF_TEMP_C, temp_value)

    data = fixed_header + level_record + pressure_record + temp_record

    return build_mbus_long_frame(MBUS_C_RSP_UD, address, MBUS_CI_RSP_VARIABLE, data)


def build_corrupted_response(address, serial=0x12345678):
    """Build M-Bus response with spoofed/fake sensor values"""
    id_bytes = struct.pack('<I', serial)
    manufacturer = struct.pack('<H', 0x4D2A)
    version = bytes([0x01])
    medium = bytes([0x07])
    access_nr = bytes([0x01])
    status = bytes([0x00])
    signature = struct.pack('<H', 0x0000)

    fixed_header = id_bytes + manufacturer + version + medium + access_nr + status + signature

    # Spoofed values: always show safe readings
    level_record = build_mbus_variable_data_record(MBUS_DIF_INT32, MBUS_VIF_VOLUME_LITERS,
                                                    struct.pack('<I', 500))  # 50.0 liters (fake safe)
    pressure_record = build_mbus_variable_data_record(MBUS_DIF_INT16, MBUS_VIF_PRESSURE_BAR,
                                                       struct.pack('<H', 2500))  # 2.5 bar (fake safe)
    temp_record = build_mbus_variable_data_record(MBUS_DIF_INT16, MBUS_VIF_TEMP_C,
                                                    struct.pack('<H', 200))  # 20.0°C (fake safe)

    data = fixed_header + level_record + pressure_record + temp_record

    return build_mbus_long_frame(MBUS_C_RSP_UD, address, MBUS_CI_RSP_VARIABLE, data)


def parse_mbus_frame(data):
    """Parse an incoming M-Bus frame, return (frame_type, c_field, address, payload)"""
    if len(data) < 1:
        return None

    # Single character ACK
    if data[0] == MBUS_FRAME_ACK:
        return ('ack', 0, 0, b'')

    # Short frame
    if data[0] == MBUS_FRAME_START_SHORT and len(data) >= 5:
        c_field = data[1]
        address = data[2]
        return ('short', c_field, address, b'')

    # Long frame
    if data[0] == MBUS_FRAME_START_LONG and len(data) >= 9:
        length = data[1]
        c_field = data[4]
        address = data[5]
        ci_field = data[6] if length > 3 else 0
        payload = data[7:4 + length] if length > 3 else b''
        return ('long', c_field, address, payload)

    return None


class MBusGatewayServer:
    """
    M-Bus TCP Gateway Server

    Listens on TCP port 5000 for M-Bus protocol requests.
    Serves water tank sensor data in real M-Bus frame format.
    """

    def __init__(self, sensor_source, host='0.0.0.0', port=5000):
        self.sensor_source = sensor_source
        self.host = host
        self.port = port
        self.server_socket = None
        self.running = False
        self.state = GW_STATE_ONLINE
        self.lock = threading.Lock()
        self.clients = []
        self.request_count = 0
        self.corrupt_count = 0

    def get_state(self):
        with self.lock:
            return self.state

    def set_state(self, new_state):
        with self.lock:
            old = self.state
            self.state = new_state
            if old != new_state:
                logger.warning(f"Gateway state: {old} -> {new_state}")

    def start(self):
        """Start M-Bus TCP gateway"""
        self.server_socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self.server_socket.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        self.server_socket.bind((self.host, self.port))
        self.server_socket.listen(5)
        self.server_socket.settimeout(1.0)
        self.running = True

        logger.info(f"M-Bus TCP gateway listening on {self.host}:{self.port}")

        thread = threading.Thread(target=self._accept_loop, daemon=True)
        thread.start()

    def _accept_loop(self):
        while self.running:
            try:
                # If OFFLINE (bricked), reject connections
                if self.get_state() == GW_STATE_OFFLINE:
                    time.sleep(0.5)
                    continue

                client_sock, addr = self.server_socket.accept()
                logger.info(f"[M-Bus] Client connected from {addr[0]}:{addr[1]}")
                client_thread = threading.Thread(
                    target=self._handle_client,
                    args=(client_sock, addr),
                    daemon=True
                )
                client_thread.start()
                self.clients.append(client_sock)
            except socket.timeout:
                continue
            except OSError:
                break

    def _handle_client(self, client_sock, addr):
        client_sock.settimeout(5.0)
        try:
            while self.running:
                state = self.get_state()

                # If bricked, drop connection
                if state == GW_STATE_OFFLINE:
                    logger.warning(f"[M-Bus] Gateway OFFLINE - dropping {addr[0]}")
                    break

                try:
                    data = client_sock.recv(1024)
                    if not data:
                        break

                    response = self._process_frame(data, addr, state)
                    if response:
                        client_sock.sendall(response)
                except socket.timeout:
                    continue
                except ConnectionResetError:
                    break
        except Exception as e:
            logger.error(f"[M-Bus] Client error: {e}")
        finally:
            client_sock.close()
            if client_sock in self.clients:
                self.clients.remove(client_sock)

    def _process_frame(self, data, addr, state):
        """Process incoming M-Bus frame"""
        parsed = parse_mbus_frame(data)
        if parsed is None:
            # Check for Fuxnet attack: rapid malformed frames
            self.corrupt_count += 1
            if self.corrupt_count > 50:
                logger.critical(f"[M-Bus] FIRMWARE CORRUPTION DETECTED - Gateway bricked!")
                self.set_state(GW_STATE_OFFLINE)
                return None
            logger.warning(f"[M-Bus] Malformed frame from {addr[0]} (corrupt count: {self.corrupt_count})")
            return None

        frame_type, c_field, address, payload = parsed
        self.request_count += 1

        # SND_NKE - Initialization
        if c_field in (MBUS_C_SND_NKE,):
            logger.info(f"[M-Bus] SND_NKE (init) from {addr[0]}, address={address}")
            return bytes([MBUS_FRAME_ACK])

        # REQ_UD2 - Request user data
        elif c_field in (MBUS_C_REQ_UD2, MBUS_C_REQ_UD2_2):
            logger.info(f"[M-Bus] REQ_UD2 (data request) from {addr[0]}, address={address}")

            if state == GW_STATE_CORRUPTED:
                logger.warning(f"[M-Bus] Returning SPOOFED sensor data")
                return build_corrupted_response(address)
            else:
                # Normal: return real sensor data
                level, pressure, temp = self.sensor_source.get_readings()
                return build_sensor_response(address, level, pressure, temp)

        # REQ_UD1 - Request alarm data
        elif c_field in (MBUS_C_REQ_UD1, MBUS_C_REQ_UD1_2):
            logger.info(f"[M-Bus] REQ_UD1 (alarm request) from {addr[0]}")
            return bytes([MBUS_FRAME_ACK])

        # SND_UD - Send user data (Fuxnet corruption vector)
        elif c_field in (MBUS_C_SND_UD, MBUS_C_SND_UD2):
            logger.warning(f"[M-Bus] SND_UD from {addr[0]} - potential attack!")

            # Check if this is a corruption attempt
            if payload and len(payload) > 0:
                # Any SND_UD with data is treated as firmware write attempt
                self.corrupt_count += 1
                if self.corrupt_count >= 10:
                    logger.critical(f"[M-Bus] SENSOR CORRUPTION - Gateway entering CORRUPTED state!")
                    self.set_state(GW_STATE_CORRUPTED)

            return bytes([MBUS_FRAME_ACK])

        else:
            logger.warning(f"[M-Bus] Unknown C-field 0x{c_field:02x} from {addr[0]}")
            return bytes([MBUS_FRAME_ACK])

    def stop(self):
        self.running = False
        for c in self.clients:
            try:
                c.close()
            except Exception:
                pass
        if self.server_socket:
            self.server_socket.close()
        logger.info("M-Bus gateway stopped")


class SensorSource:
    """
    Reads water tank sensor data from PLC via IEC-104.
    Provides readings to the M-Bus gateway.
    """

    def __init__(self, plc_ip, plc_port=2404):
        self.plc_ip = plc_ip
        self.plc_port = plc_port
        self.water_level = 50.0
        self.pressure = 2.5
        self.temperature = 20.0
        self.client = None
        self.running = False
        self.lock = threading.Lock()

    def get_readings(self):
        with self.lock:
            return (self.water_level, self.pressure, self.temperature)

    def _on_receive_point(self, point: c104.Point, previous_info: c104.Information, message: c104.IncomingMessage) -> c104.ResponseState:
        ioa = point.io_address
        with self.lock:
            if ioa == IOA_WATER_LEVEL:
                self.water_level = float(point.value) / 327.67
            elif ioa == IOA_PRESSURE:
                self.pressure = float(point.value) / 2184.5
            elif ioa == IOA_TEMPERATURE:
                self.temperature = float(point.value) / 327.67
        return c104.ResponseState.SUCCESS

    def _on_connection_state(self, connection: c104.Connection, state: c104.ConnectionState) -> None:
        if state == c104.ConnectionState.OPEN:
            logger.info(f"Sensor source connected to PLC at {self.plc_ip}:{self.plc_port}")
        elif state == c104.ConnectionState.CLOSED:
            logger.warning(f"Sensor source disconnected from PLC")

    def start(self):
        if not C104_AVAILABLE:
            logger.error("c104 not available")
            return False

        try:
            self.client = c104.Client(tick_rate_ms=100)
            conn = self.client.add_connection(
                ip=self.plc_ip, port=self.plc_port,
                init=c104.Init.INTERROGATION
            )
            conn.on_state_change(callable=self._on_connection_state)
            station = conn.add_station(common_address=COMMON_ADDRESS)

            for ioa in [IOA_WATER_LEVEL, IOA_PRESSURE, IOA_TEMPERATURE]:
                pt = station.add_point(io_address=ioa, type=c104.Type.M_ME_NB_1)
                pt.on_receive(callable=self._on_receive_point)

            self.client.start()
            conn.connect()
            self.running = True
            logger.info("Sensor source started")
            return True
        except Exception as e:
            logger.error(f"Sensor source failed: {e}")
            return False

    def stop(self):
        self.running = False
        if self.client:
            self.client.stop()


def main():
    parser = argparse.ArgumentParser(
        description="M-Bus Sensor Gateway - Water Tank Sensor Simulation",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Simulates an M-Bus TCP sensor gateway (like Relay/Elvaco/Moxa devices).
Reads water tank data from PLC via IEC-104 and serves over M-Bus TCP.
This is the attack surface for Fuxnet malware.

Examples:
    python3 mbus_gateway_server.py --plc-ip 127.0.0.1
    python3 mbus_gateway_server.py --plc-ip 192.168.1.6 --mbus-port 5000

WARNING: For authorized security testing only.
        """
    )

    parser.add_argument('--plc-ip', type=str, required=True, help='PLC IP address')
    parser.add_argument('--plc-port', type=int, default=IEC104_PORT, help=f'PLC IEC-104 port (default: {IEC104_PORT})')
    parser.add_argument('--mbus-port', type=int, default=5000, help='M-Bus TCP port (default: 5000)')
    parser.add_argument('--host', type=str, default='0.0.0.0', help='Bind address (default: 0.0.0.0)')

    args = parser.parse_args()

    print("=" * 70)
    print("  M-BUS SENSOR GATEWAY - SIMULATION")
    print("  Meter-Bus (EN 13757-3) TCP Gateway")
    print("=" * 70)
    print(f"  PLC Source:    {args.plc_ip}:{args.plc_port} (IEC-104)")
    print(f"  M-Bus Port:    {args.mbus_port} (TCP)")
    print(f"  Sensors:       Water Level, Pressure, Temperature")
    print("=" * 70)
    print()

    sensor_source = SensorSource(args.plc_ip, args.plc_port)
    gateway = MBusGatewayServer(sensor_source, args.host, args.mbus_port)

    def signal_handler(signum, frame):
        logger.info("Shutting down...")
        sensor_source.stop()
        gateway.stop()
        sys.exit(0)

    signal.signal(signal.SIGINT, signal_handler)
    signal.signal(signal.SIGTERM, signal_handler)

    gateway.start()

    if not sensor_source.start():
        logger.error("Failed to start sensor source")
        gateway.stop()
        sys.exit(1)

    logger.info("M-Bus gateway fully operational")

    try:
        while True:
            state = gateway.get_state()
            level, pressure, temp = sensor_source.get_readings()
            logger.info(f"GW [{state}] | Level: {level:.1f}% | Pressure: {pressure:.2f} bar | Temp: {temp:.1f}C | Requests: {gateway.request_count}")
            time.sleep(5)
    except KeyboardInterrupt:
        pass

    sensor_source.stop()
    gateway.stop()


if __name__ == "__main__":
    main()
