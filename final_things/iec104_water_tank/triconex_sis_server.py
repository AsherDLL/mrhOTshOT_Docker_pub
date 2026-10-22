#!/usr/bin/env python3
"""
Triconex Safety Instrumented System (SIS) Server Simulation

Simulates a Schneider Electric Triconex SIS controller for the water tank lab.
The SIS monitors water tank levels via IEC-104 and triggers emergency shutdown
when safety thresholds are exceeded.

Two network interfaces:
1. IEC-104 Client (port 2404) - Monitors PLC water level, sends trip commands
2. TriStation Server (port 1502) - Real TriStation UDP protocol (Triton attack surface)

TriStation protocol (real format, compatible with Wireshark TriStation dissector):
- Transport: UDP port 1502
- Packet: [TCM Header 4B][TS Subheader 10B][Data][CRC16 2B]
- Reconnaissance responses (ATTACH / CP status / chassis status) are produced by
  the vendored Nozomi Networks Triconex honeypot (BSD 3-Clause) under
  vendor/tricotools/ -- byte-for-byte the real honeypot's output. The TRITON
  kill-chain opcodes (HALT / download / run) extend it here, reusing the same
  packet framing.

Usage:
    python3 triconex_sis_server.py --plc-ip 192.168.1.6 --plc-port 2404 --threshold 90

WARNING: This is a SIMULATION for educational purposes only.
         Only use in authorized lab environments.
"""

import os
import sys
import time
import json
import struct
import socket
import signal
import argparse
import logging
import threading
from datetime import datetime

# Add parent directory to path
sys.path.append(os.path.dirname(os.path.abspath(__file__)))

try:
    import c104
    C104_AVAILABLE = True
except ImportError:
    C104_AVAILABLE = False
    print("WARNING: c104 library not available. Install with: pip install c104")

try:
    import crcmod
    CRC_AVAILABLE = True
except ImportError:
    CRC_AVAILABLE = False
    print("WARNING: crcmod not available. Install with: pip install crcmod")

# Vendored Nozomi Networks Triconex honeypot (BSD 3-Clause) -- see
# vendor/tricotools/. TriStation reconnaissance responses are delegated to it so
# they match the real honeypot byte-for-byte instead of being approximated here.
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "vendor", "tricotools"))
import triconex_honeypot as nozomi

from common.config import *

# Setup logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - [TRICONEX-SIS] - %(levelname)s - %(message)s',
    datefmt='%Y-%m-%d %H:%M:%S'
)
logger = logging.getLogger('TriconexSIS')


# TriStation TCM opcodes (real protocol)
TCM_CONNECT_REQUEST = 0x01
TCM_CONNECT_REPLY = 0x02
TCM_DISCONNECT_REPLY = 0x03
TCM_DISCONNECT_REQUEST = 0x04
TCM_COMMAND = 0x05

# TriStation function codes (real protocol - from dissector)
TS_ATTACH_TRICON = 0x0D        # 13: Attach TRICON
TS_GET_CP_STATUS = 0x13        # 19: Get CP status
TS_RUN_PROGRAM = 0x14          # 20: Run program
TS_HALT_PROGRAM = 0x15         # 21: Halt program
TS_GET_CHASSIS_STATUS = 0x18   # 24: Get chassis status
TS_START_DOWNLOAD_ALL = 0x00   # 0: Start download all
TS_END_DOWNLOAD_ALL = 0x0A     # 10: End download all
TS_ALLOCATE_PROGRAM = 0x37     # 55: Allocate program
TS_SET_TS2_DATA = 0x3E         # 62: Set TS2 data
TS_GO_DOWNLOAD_MODE = 0x50     # 80: Go to DOWNLOAD mode

# TriStation response codes
TS_TRICON_ATTACHED = 0x6A      # 106: TRICON attached
TS_CP_STATUS_RESP = 0x6C       # 108: Get CP status response
TS_PROGRAM_RUNNING = 0x6D      # 109: Program is running
TS_PROGRAM_HALTED = 0x6E       # 110: Program is halted
TS_CHASSIS_STATUS_RESP = 0x77  # 119: Get chassis status response
TS_DOWNLOAD_ALL_PERM = 0x65    # 101: Download all permitted
TS_PROGRAM_ACCEPTED = 0x69     # 105: Program accepted
TS_ALLOC_PROG_RESP = 0x99      # 153: Allocate program response
TS_SET_TS2_DATA_RESP = 0x9F    # 159: Set TS2 data response
TS_COMMAND_REJECTED = 0x64     # 100: Command rejected

# SIS states
SIS_STATE_ARMED = "ARMED"
SIS_STATE_TRIPPED = "TRIPPED"
SIS_STATE_DISABLED = "DISABLED"


# TriStation packet framing (build_packet), the CRC-16 (poly 0x18005) and the
# CP-status / chassis-status reconnaissance responses all come from the vendored
# Nozomi honeypot, imported above as `nozomi`. See vendor/tricotools/.


class TriStationServer:
    """
    Real TriStation Protocol Server (UDP)

    Implements the actual TriStation protocol used by Schneider Electric
    Triconex controllers, compatible with the Wireshark TriStation dissector.

    Based on: https://github.com/NozomiNetworks/tricotools/blob/master/triconex_honeypot.py
    """

    def __init__(self, sis_controller, host='0.0.0.0', port=1502):
        self.sis_controller = sis_controller
        self.host = host
        self.port = port
        self.sock = None
        self.running = False
        self.seq = 0

    def start(self):
        """Start TriStation UDP server"""
        self.sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self.sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        self.sock.bind((self.host, self.port))
        self.sock.settimeout(1.0)
        self.running = True

        logger.info(f"TriStation UDP server listening on {self.host}:{self.port}")

        thread = threading.Thread(target=self._receive_loop, daemon=True)
        thread.start()

    def _receive_loop(self):
        """Receive and process UDP packets"""
        while self.running:
            try:
                data, addr = self.sock.recvfrom(4096)
                if len(data) < 4:
                    continue

                response = self._process_packet(data, addr)
                if response:
                    self.sock.sendto(response, addr)

            except socket.timeout:
                continue
            except OSError:
                break
            except Exception as e:
                logger.error(f"[TriStation] Error: {e}")

    def _process_packet(self, data, addr):
        """Process a TriStation UDP packet"""
        mcode = data[0]

        # TCM CONNECT REQUEST
        if mcode == TCM_CONNECT_REQUEST:
            logger.info(f"[TriStation] CONNECT REQUEST from {addr[0]}:{addr[1]}")
            # CONNECT REPLY: [0x02][0x00][0x00 0x00][0x01 0xb8]
            return b'\x02\x00\x00\x00\x01\xb8'

        # TCM DISCONNECT REQUEST
        elif mcode == TCM_DISCONNECT_REQUEST:
            logger.info(f"[TriStation] DISCONNECT REQUEST from {addr[0]}:{addr[1]}")
            return b'\x03\x00\x00\x00\x00\x00'

        # TCM COMMAND (contains TS subheader)
        elif mcode == TCM_COMMAND:
            if len(data) < 14:
                return None

            # Parse TS subheader
            funccode = data[6]
            seq = data[7]

            return self._handle_ts_command(funccode, seq, data, addr)

        else:
            logger.warning(f"[TriStation] Unknown TCM opcode 0x{mcode:02x} from {addr[0]}")
            return None

    def _handle_ts_command(self, funccode, seq, raw_data, addr):
        """Handle a TriStation function command"""

        # Attach TRICON (0x0D) - initial handshake
        if funccode == TS_ATTACH_TRICON:
            logger.info(f"[TriStation] ATTACH REQUEST from {addr[0]}")
            return nozomi.build_tricon_attached(seq=seq)

        # Get CP Status (0x13) - reconnaissance
        elif funccode == TS_GET_CP_STATUS:
            logger.info(f"[TriStation] GET CP STATUS from {addr[0]}")
            return nozomi.build_CP_status_response(seq=seq)

        # Get Chassis Status (0x18) - reconnaissance
        elif funccode == TS_GET_CHASSIS_STATUS:
            logger.info(f"[TriStation] GET CHASSIS STATUS from {addr[0]}")
            # The chassis layout the upstream honeypot emits by default:
            # active MP #3, a COM module in slot 1, all other slots empty.
            return nozomi.build_chassis_status_response(
                seq=seq, mpmodel=0, activemp=2,
                slots=['com', 'empty', 'empty', 'empty', 'empty', 'empty', 'empty', 'empty'])

        # Halt Program (0x15) - Triton disabling safety logic
        elif funccode == TS_HALT_PROGRAM:
            logger.critical(f"[TriStation] HALT PROGRAM from {addr[0]} - TRITON ATTACK: Stopping safety program!")
            self.sis_controller.disable_safety()
            return nozomi.build_packet(0, TS_PROGRAM_HALTED, seq, b'')

        # Go to DOWNLOAD mode (0x50) - Triton preparing to reprogram
        elif funccode == TS_GO_DOWNLOAD_MODE:
            logger.critical(f"[TriStation] GO TO DOWNLOAD MODE from {addr[0]} - TRITON ATTACK: Entering download mode!")
            return nozomi.build_packet(0, TS_DOWNLOAD_ALL_PERM, seq, b'')

        # Start Download All (0x00) - Triton starting reprogramming
        elif funccode == TS_START_DOWNLOAD_ALL:
            logger.critical(f"[TriStation] START DOWNLOAD ALL from {addr[0]} - TRITON ATTACK: Reprogramming SIS!")
            return nozomi.build_packet(0, TS_DOWNLOAD_ALL_PERM, seq, b'')

        # Allocate Program (0x37) - Triton allocating memory
        elif funccode == TS_ALLOCATE_PROGRAM:
            logger.critical(f"[TriStation] ALLOCATE PROGRAM from {addr[0]} - TRITON ATTACK: Allocating malicious program!")
            return nozomi.build_packet(0, TS_ALLOC_PROG_RESP, seq, b'')

        # Set TS2 Data (0x3E) - Triton writing malicious code
        elif funccode == TS_SET_TS2_DATA:
            logger.critical(f"[TriStation] SET TS2 DATA from {addr[0]} - TRITON ATTACK: Writing malicious safety logic!")
            return nozomi.build_packet(0, TS_SET_TS2_DATA_RESP, seq, b'')

        # End Download All (0x0A) - Triton completing reprogramming
        elif funccode == TS_END_DOWNLOAD_ALL:
            logger.critical(f"[TriStation] END DOWNLOAD ALL from {addr[0]} - TRITON ATTACK: Reprogramming complete!")
            return nozomi.build_packet(0, TS_PROGRAM_ACCEPTED, seq, b'')

        # Run Program (0x14) - Triton running compromised program
        elif funccode == TS_RUN_PROGRAM:
            logger.critical(f"[TriStation] RUN PROGRAM from {addr[0]} - TRITON ATTACK: Running compromised safety program!")
            return nozomi.build_packet(0, TS_PROGRAM_RUNNING, seq, b'')

        else:
            logger.warning(f"[TriStation] Unknown function 0x{funccode:02x} from {addr[0]}")
            return nozomi.build_packet(0, TS_COMMAND_REJECTED, seq, b'')

    def stop(self):
        """Stop TriStation server"""
        self.running = False
        if self.sock:
            self.sock.close()
        logger.info("TriStation server stopped")


class SISController:
    """
    Safety Instrumented System Controller

    Monitors the water tank PLC via IEC-104 and triggers safety shutdown
    when water level exceeds the configured threshold.
    """

    def __init__(self, plc_ip, plc_port=2404, threshold=90.0, poll_interval=1.0):
        # c104 requires a numeric IP, not a hostname. Resolve DNS names (e.g.
        # docker service hostnames like "plc-water") to an address up front.
        try:
            socket.inet_aton(plc_ip)
            self.plc_ip = plc_ip
        except OSError:
            self.plc_ip = socket.gethostbyname(plc_ip)
        self.plc_port = plc_port
        self.threshold = threshold
        self.poll_interval = poll_interval

        self.state = SIS_STATE_ARMED
        self.safety_enabled = True
        self.last_water_level = 0.0
        self.last_check_time = None
        self.trip_time = None

        self.client = None
        self.connection = None
        self.station = None
        self.points = {}
        self.running = False
        self.lock = threading.Lock()

    def get_state(self):
        """Get current SIS state (thread-safe)"""
        with self.lock:
            return self.state

    def get_water_level(self):
        """Get last known water level (thread-safe)"""
        with self.lock:
            return self.last_water_level

    def disable_safety(self):
        """Disable safety monitoring (Triton attack)"""
        with self.lock:
            self.safety_enabled = False
            self.state = SIS_STATE_DISABLED
            logger.critical("SAFETY MONITORING DISABLED - System is unprotected!")

    def enable_safety(self):
        """Re-enable safety monitoring"""
        with self.lock:
            self.safety_enabled = True
            if self.state == SIS_STATE_DISABLED:
                self.state = SIS_STATE_ARMED
            logger.info("Safety monitoring re-enabled")

    def _trip(self):
        """Trigger safety trip"""
        with self.lock:
            if self.state == SIS_STATE_DISABLED:
                logger.warning(f"SIS would trip (level: {self.last_water_level:.1f}%) but SAFETY IS DISABLED!")
                return

            self.state = SIS_STATE_TRIPPED
            self.trip_time = datetime.now()
            logger.critical(f"SIS SAFETY TRIP! Water level {self.last_water_level:.1f}% exceeded threshold {self.threshold}%")

        # Send trip command to PLC via IEC-104
        self._send_trip_command(True)

    def _send_trip_command(self, trip_state):
        """Send SIS trip command to PLC"""
        try:
            if IOA_SIS_TRIP_COMMAND in self.points:
                point = self.points[IOA_SIS_TRIP_COMMAND]
                point.value = trip_state
                point.transmit(cause=c104.Cot.ACTIVATION)
                logger.info(f"SIS trip command sent to PLC: {'TRIP' if trip_state else 'RESET'}")
        except Exception as e:
            logger.error(f"Failed to send trip command to PLC: {e}")

    def _on_receive_point(self, point: c104.Point, previous_info: c104.Information, message: c104.IncomingMessage) -> c104.ResponseState:
        """Handle incoming point updates from PLC"""
        ioa = point.io_address

        if ioa == IOA_WATER_LEVEL:
            # Decode scaled value back to percentage
            raw_value = int(point.value)
            water_level = raw_value / 327.67
            with self.lock:
                self.last_water_level = water_level
                self.last_check_time = datetime.now()

        return c104.ResponseState.SUCCESS

    def _on_connection_state(self, connection: c104.Connection, state: c104.ConnectionState) -> None:
        """Handle connection state changes"""
        if state == c104.ConnectionState.OPEN:
            logger.info(f"Connected to PLC at {self.plc_ip}:{self.plc_port}")
        elif state == c104.ConnectionState.CLOSED:
            logger.warning(f"Disconnected from PLC at {self.plc_ip}:{self.plc_port}")

    def start(self):
        """Start SIS controller - connect to PLC and begin monitoring"""
        if not C104_AVAILABLE:
            logger.error("c104 library not available - cannot start SIS controller")
            return False

        try:
            # Create IEC-104 client
            self.client = c104.Client(tick_rate_ms=100)

            # Add connection to PLC
            self.connection = self.client.add_connection(
                ip=self.plc_ip,
                port=self.plc_port,
                init=c104.Init.INTERROGATION
            )
            self.connection.on_state_change(callable=self._on_connection_state)

            # Add station
            self.station = self.connection.add_station(common_address=COMMON_ADDRESS)

            # Add water level monitoring point
            pt = self.station.add_point(
                io_address=IOA_WATER_LEVEL,
                type=c104.Type.M_ME_NB_1
            )
            pt.on_receive(callable=self._on_receive_point)
            self.points[IOA_WATER_LEVEL] = pt

            # Add SIS trip command point
            pt = self.station.add_point(
                io_address=IOA_SIS_TRIP_COMMAND,
                type=c104.Type.C_SC_NA_1
            )
            self.points[IOA_SIS_TRIP_COMMAND] = pt

            # Start client
            self.client.start()
            self.connection.connect()

            self.running = True

            # Start monitoring thread
            monitor_thread = threading.Thread(
                target=self._monitoring_loop,
                daemon=True
            )
            monitor_thread.start()

            logger.info("SIS controller started - monitoring water level")
            return True

        except Exception as e:
            logger.error(f"Failed to start SIS controller: {e}")
            return False

    def _monitoring_loop(self):
        """Main safety monitoring loop"""
        while self.running:
            try:
                with self.lock:
                    level = self.last_water_level
                    safety_on = self.safety_enabled
                    current_state = self.state

                # Only check if safety is enabled and not already tripped
                if safety_on and current_state == SIS_STATE_ARMED:
                    if level >= self.threshold:
                        self._trip()

                time.sleep(self.poll_interval)

            except Exception as e:
                logger.error(f"Monitoring loop error: {e}")
                time.sleep(1)

    def stop(self):
        """Stop SIS controller"""
        self.running = False
        if self.client:
            self.client.stop()
        logger.info("SIS controller stopped")


def main():
    parser = argparse.ArgumentParser(
        description="Triconex SIS Server - Safety Instrumented System Simulation",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
This simulates a Schneider Electric Triconex SIS controller.

The SIS monitors water tank levels via IEC-104 and triggers emergency
shutdown when safety thresholds are exceeded. It also listens on port
1502 (TriStation protocol) for engineering workstation access - this
is the attack surface that Triton/TRISIS malware exploits.

Examples:
    # Basic usage
    python3 triconex_sis_server.py --plc-ip 192.168.1.6

    # Custom threshold
    python3 triconex_sis_server.py --plc-ip 192.168.1.6 --threshold 85

    # Custom ports
    python3 triconex_sis_server.py --plc-ip 192.168.1.6 --plc-port 2404 --sis-port 1502

WARNING: For authorized security testing only.
        """
    )

    parser.add_argument(
        '--plc-ip',
        type=str,
        required=True,
        help='IP address of the water tank PLC'
    )

    parser.add_argument(
        '--plc-port',
        type=int,
        default=IEC104_PORT,
        help=f'PLC IEC-104 port (default: {IEC104_PORT})'
    )

    parser.add_argument(
        '--sis-port',
        type=int,
        default=SIS_PORT,
        help=f'TriStation protocol port (default: {SIS_PORT})'
    )

    parser.add_argument(
        '--threshold',
        type=float,
        default=SIS_SAFETY_THRESHOLD,
        help=f'Safety trip threshold percentage (default: {SIS_SAFETY_THRESHOLD})'
    )

    parser.add_argument(
        '--poll-interval',
        type=float,
        default=SIS_POLL_INTERVAL,
        help=f'Monitoring poll interval in seconds (default: {SIS_POLL_INTERVAL})'
    )

    parser.add_argument(
        '--host',
        type=str,
        default='0.0.0.0',
        help='TriStation bind address (default: 0.0.0.0)'
    )

    args = parser.parse_args()

    # Banner
    print("=" * 70)
    print("  TRICONEX SAFETY INSTRUMENTED SYSTEM (SIS) - SIMULATION")
    print("  Schneider Electric Triconex Controller Emulation")
    print("=" * 70)
    print(f"  PLC Target:        {args.plc_ip}:{args.plc_port} (IEC-104)")
    print(f"  TriStation Port:   {args.sis_port}")
    print(f"  Safety Threshold:  {args.threshold}%")
    print(f"  Poll Interval:     {args.poll_interval}s")
    print("=" * 70)
    print("  WARNING: For authorized security testing only!")
    print("=" * 70)
    print()

    # Create SIS controller
    sis = SISController(
        plc_ip=args.plc_ip,
        plc_port=args.plc_port,
        threshold=args.threshold,
        poll_interval=args.poll_interval
    )

    # Create TriStation server
    tristation = TriStationServer(
        sis_controller=sis,
        host=args.host,
        port=args.sis_port
    )

    # Signal handler
    def signal_handler(signum, frame):
        logger.info("Shutting down...")
        sis.stop()
        tristation.stop()
        sys.exit(0)

    signal.signal(signal.SIGINT, signal_handler)
    signal.signal(signal.SIGTERM, signal_handler)

    # Start components
    tristation.start()

    if not sis.start():
        logger.error("Failed to start SIS controller")
        tristation.stop()
        sys.exit(1)

    logger.info("SIS system fully operational")
    logger.info(f"  State: {sis.get_state()}")
    logger.info(f"  Safety monitoring: ENABLED")
    logger.info(f"  TriStation server: LISTENING on port {args.sis_port}")

    # Status display loop
    try:
        while True:
            state = sis.get_state()
            level = sis.get_water_level()

            if state == SIS_STATE_ARMED:
                status_char = "[ARMED]"
            elif state == SIS_STATE_TRIPPED:
                status_char = "[TRIPPED]"
            elif state == SIS_STATE_DISABLED:
                status_char = "[DISABLED]"
            else:
                status_char = "[UNKNOWN]"

            logger.info(f"SIS {status_char} | Water Level: {level:.1f}% | Threshold: {args.threshold}%")
            time.sleep(5)
    except KeyboardInterrupt:
        pass

    sis.stop()
    tristation.stop()


if __name__ == "__main__":
    main()
