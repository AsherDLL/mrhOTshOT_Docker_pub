#!/usr/bin/env python3
"""
Omron PLC Scanner (Enhanced)

Advanced scanning and fingerprinting for Omron PLCs.
Part of BADOMEN attack module for PIPEDREAM.

WARNING: For authorized security testing only.
"""

import socket
import struct
import logging
from typing import Optional, List, Dict
from dataclasses import dataclass

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - [BADOMEN-SCAN] - %(levelname)s - %(message)s'
)
logger = logging.getLogger('OmronScanner')


@dataclass
class OmronDevice:
    """Enhanced Omron PLC Device Information"""
    ip: str
    port: int = 9600
    model: str = ""
    version: str = ""
    system_version: str = ""
    cpu_mode: str = ""
    mac_address: str = ""
    serial_number: str = ""
    http_port: int = 80
    telnet_enabled: bool = False
    reachable: bool = False


class OmronScanner:
    """Enhanced Omron PLC Scanner with full BADOMEN capabilities"""

    FINS_PORT = 9600
    HTTP_PORT = 80

    # Target Omron models from PIPEDREAM
    TARGET_MODELS = [
        'NX1P2', 'NX-SL3300', 'NX-ECC203',
        'NJ501-1300', 'S8VK', 'R88D-1SN10F-ECT',
        'NJ', 'NX', 'CJ', 'CP', 'CS'
    ]

    def __init__(self, timeout: float = 3.0):
        self.timeout = timeout

    def scan_host(self, target: str, port: int = 9600) -> Optional[OmronDevice]:
        """Enhanced host scanning with full device enumeration"""
        logger.info(f"[*] Scanning {target}:{port} for Omron FINS service...")

        device = OmronDevice(ip=target, port=port)

        if not self._check_port(target, port):
            return None

        device.reachable = True
        logger.warning(f"[!] Omron PLC detected at {target}:{port}")

        # Get controller data
        controller_data = self._get_controller_data(target, port)
        if controller_data:
            device.model = controller_data.get('model', 'Unknown')
            device.version = controller_data.get('version', 'Unknown')
            device.system_version = controller_data.get('system_version', 'Unknown')

            logger.info(f"    Model:          {device.model}")
            logger.info(f"    Version:        {device.version}")

            # Check if target model
            for target_model in self.TARGET_MODELS:
                if target_model in device.model.upper():
                    logger.critical(f"[!!!] TARGET MODEL DETECTED: {device.model}")
                    break

        # Get MAC address
        mac = self._get_mac_address(target, port)
        if mac:
            device.mac_address = mac
            logger.info(f"    MAC Address:    {mac}")

        # Get status
        status = self._get_status(target, port)
        if status:
            device.cpu_mode = status.get('mode', 'Unknown')
            logger.info(f"    CPU Mode:       {device.cpu_mode}")

        # Check for HTTP interface
        if self._check_port(target, 80):
            device.http_port = 80
            logger.warning("    [!] HTTP interface available")

        # Check for Telnet
        if self._check_port(target, 23):
            device.telnet_enabled = True
            logger.critical("    [!!!] TELNET ENABLED - VULNERABLE")

        return device

    def _check_port(self, target: str, port: int) -> bool:
        """Check if port is open"""
        try:
            sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            sock.settimeout(self.timeout)
            result = sock.connect_ex((target, port))
            sock.close()
            return result == 0
        except:
            return False

    def _build_fins_header(self, sid: int = 0x01) -> bytes:
        """Build FINS command header"""
        header = bytearray()
        header.append(0x80)  # ICF
        header.append(0x00)  # RSV
        header.append(0x02)  # GCT
        header.append(0x00)  # DNA
        header.append(0x00)  # DA1
        header.append(0x00)  # DA2
        header.append(0x00)  # SNA
        header.append(0x00)  # SA1
        header.append(0x00)  # SA2
        header.append(sid)   # SID

        return bytes(header)

    def _get_controller_data(self, target: str, port: int) -> Optional[Dict[str, str]]:
        """Get controller identification data"""
        try:
            sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            sock.settimeout(self.timeout)
            sock.connect((target, port))

            # Build FINS Controller Data Read command
            header = self._build_fins_header()
            command = struct.pack('>H', 0x0501)  # Controller Data Read

            request = header + command

            sock.send(request)
            response = sock.recv(2048)
            sock.close()

            if len(response) < 16:
                return None

            # Parse response
            data_start = 16

            if len(response) < data_start + 80:
                return None

            # Extract device information
            model_bytes = response[data_start:data_start + 20]
            version_bytes = response[data_start + 20:data_start + 40]
            sys_version_bytes = response[data_start + 40:data_start + 80]

            model = model_bytes.rstrip(b'\x00').decode('ascii', errors='ignore')
            version = version_bytes.rstrip(b'\x00').decode('ascii', errors='ignore')
            system_version = sys_version_bytes.rstrip(b'\x00').decode('ascii', errors='ignore')

            return {
                'model': model,
                'version': version,
                'system_version': system_version
            }

        except Exception as e:
            logger.debug(f"Controller data read error: {e}")
            return None

    def _get_mac_address(self, target: str, port: int) -> Optional[str]:
        """Retrieve MAC address from Omron PLC"""
        try:
            sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            sock.settimeout(self.timeout)
            sock.connect((target, port))

            # Build FINS MAC address read command
            header = self._build_fins_header()
            # Custom command to read MAC address
            command = struct.pack('>HBB', 0x0101, 0x82, 0x00)  # Memory area read for MAC

            request = header + command

            sock.send(request)
            response = sock.recv(2048)
            sock.close()

            if len(response) >= 22:
                # Parse MAC address from response
                mac_bytes = response[16:22]
                mac = ':'.join([f'{b:02X}' for b in mac_bytes])
                return mac

        except Exception as e:
            logger.debug(f"MAC address read error: {e}")

        return None

    def _get_status(self, target: str, port: int) -> Optional[Dict[str, str]]:
        """Get PLC status"""
        try:
            sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            sock.settimeout(self.timeout)
            sock.connect((target, port))

            # Build FINS Status Read command
            header = self._build_fins_header()
            command = struct.pack('>H', 0x0601)  # Controller Status Read

            request = header + command

            sock.send(request)
            response = sock.recv(2048)
            sock.close()

            if len(response) < 18:
                return None

            # Parse response
            status_byte = response[16]
            mode_byte = response[17]

            # Decode mode
            mode_map = {
                0x00: "PROGRAM",
                0x01: "DEBUG",
                0x02: "MONITOR",
                0x04: "RUN"
            }

            mode = mode_map.get(mode_byte, f"UNKNOWN(0x{mode_byte:02X})")

            return {
                'status': status_byte,
                'mode': mode
            }

        except Exception as e:
            logger.debug(f"Status read error: {e}")
            return None


def main():
    """Main entry point"""
    import argparse

    parser = argparse.ArgumentParser(
        description='Omron PLC Scanner (BADOMEN)',
        epilog="WARNING: For authorized security testing only!"
    )

    parser.add_argument('--target', '-t', required=True,
                        help='Target PLC IP')
    parser.add_argument('--port', '-p', type=int, default=9600,
                        help='FINS port (default: 9600)')
    parser.add_argument('--verbose', '-v', action='store_true',
                        help='Verbose output')

    args = parser.parse_args()

    if args.verbose:
        logging.getLogger().setLevel(logging.DEBUG)

    scanner = OmronScanner()
    device = scanner.scan_host(args.target, args.port)

    if device:
        print("\n" + "=" * 70)
        print(f"Omron PLC Detected: {device.ip}:{device.port}")
        print("=" * 70)
        print(f"  Model:          {device.model}")
        print(f"  Version:        {device.version}")
        print(f"  System Version: {device.system_version}")
        print(f"  CPU Mode:       {device.cpu_mode}")
        print(f"  MAC Address:    {device.mac_address}")
        if device.telnet_enabled:
            print(f"  Telnet:         ENABLED (VULNERABLE)")
        print("=" * 70 + "\n")

    return 0


if __name__ == '__main__':
    import sys
    sys.exit(main())
