#!/usr/bin/env python3
"""
OMRON FINS Protocol Scanner

Discovers and fingerprints Omron PLCs using FINS protocol.
Part of PIPEDREAM malware simulation toolkit.

Features:
- Port scanning for FINS (UDP/TCP 9600)
- Device identification
- Memory area enumeration
- PLC status reading

Usage:
    python fins_scanner.py --target 192.168.1.6
    python fins_scanner.py --target 192.168.1.0/24 --scan-network
"""

import socket
import struct
import logging
from typing import Optional, Dict, Any, List
from dataclasses import dataclass
from enum import IntEnum

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - [FINS-SCAN] - %(levelname)s - %(message)s'
)
logger = logging.getLogger('FINSScanner')


class FINSCommand(IntEnum):
    """FINS Command Codes"""
    MEMORY_AREA_READ = 0x0101
    CONTROLLER_DATA_READ = 0x0501
    CONTROLLER_STATUS_READ = 0x0601


@dataclass
class OmronDevice:
    """Omron PLC Device Information"""
    ip: str
    port: int
    model: str = ""
    version: str = ""
    system_version: str = ""
    cpu_mode: str = ""
    reachable: bool = False


class FINSScanner:
    """
    OMRON FINS Protocol Scanner

    Discovers and fingerprints Omron PLCs on the network.
    """

    def __init__(self, timeout: float = 3.0):
        self.timeout = timeout

    def scan_host(self, target: str, port: int = 9600) -> Optional[OmronDevice]:
        """
        Scan single host for FINS service

        Args:
            target: Target IP address
            port: FINS port (default 9600)

        Returns:
            OmronDevice if found, None otherwise
        """
        device = OmronDevice(ip=target, port=port)

        # Check if port is open
        if not self._check_port(target, port):
            return None

        device.reachable = True
        logger.info(f"[+] FINS service detected at {target}:{port}")

        # Get controller data (device identification)
        controller_data = self._get_controller_data(target, port)
        if controller_data:
            device.model = controller_data.get('model', 'Unknown')
            device.version = controller_data.get('version', 'Unknown')
            device.system_version = controller_data.get('system_version', 'Unknown')

            logger.warning(f"[!] Omron PLC Identified:")
            logger.warning(f"    Model:          {device.model}")
            logger.warning(f"    Version:        {device.version}")
            logger.warning(f"    System Version: {device.system_version}")

        # Get status
        status = self._get_status(target, port)
        if status:
            device.cpu_mode = status.get('mode', 'Unknown')
            logger.info(f"    CPU Mode:       {device.cpu_mode}")

        return device

    def _check_port(self, target: str, port: int) -> bool:
        """Check if FINS port is open"""
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
        """
        Get controller identification data

        Returns:
            Dict with model, version, system_version
        """
        try:
            sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            sock.settimeout(self.timeout)
            sock.connect((target, port))

            # Build FINS Controller Data Read command
            header = self._build_fins_header()
            command = struct.pack('>H', FINSCommand.CONTROLLER_DATA_READ)

            request = header + command

            sock.send(request)
            response = sock.recv(2048)
            sock.close()

            if len(response) < 14:
                return None

            # Parse response
            # Skip header (10 bytes) + command code (2 bytes) + end code (4 bytes)
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

    def _get_status(self, target: str, port: int) -> Optional[Dict[str, str]]:
        """
        Get PLC status

        Returns:
            Dict with status and mode
        """
        try:
            sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            sock.settimeout(self.timeout)
            sock.connect((target, port))

            # Build FINS Status Read command
            header = self._build_fins_header()
            command = struct.pack('>H', FINSCommand.CONTROLLER_STATUS_READ)

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

    def scan_network(self, target_range: str, port: int = 9600) -> List[OmronDevice]:
        """
        Scan network range for Omron PLCs

        Args:
            target_range: CIDR notation (e.g., "192.168.1.0/24")
            port: FINS port

        Returns:
            List of discovered devices
        """
        import ipaddress

        devices = []
        network = ipaddress.IPv4Network(target_range, strict=False)

        logger.info(f"Scanning {network} for Omron FINS services...")

        for ip in network.hosts():
            device = self.scan_host(str(ip), port)
            if device and device.reachable:
                devices.append(device)

        logger.info(f"Found {len(devices)} Omron device(s)")
        return devices


def main():
    """Main entry point"""
    import argparse

    parser = argparse.ArgumentParser(
        description='Omron FINS Protocol Scanner',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # Scan single host
  python fins_scanner.py --target 192.168.1.6

  # Scan network range
  python fins_scanner.py --target 192.168.1.0/24 --scan-network

  # Use different port
  python fins_scanner.py --target 192.168.1.6 --port 9601

Output:
  - Detected Omron PLCs
  - Model and version information
  - PLC status (RUN/PROGRAM/etc.)
        """
    )

    parser.add_argument('--target', '-t', required=True,
                        help='Target IP or network range (CIDR)')
    parser.add_argument('--port', '-p', type=int, default=9600,
                        help='FINS port (default: 9600)')
    parser.add_argument('--scan-network', action='store_true',
                        help='Treat target as network range')
    parser.add_argument('--timeout', type=float, default=3.0,
                        help='Connection timeout in seconds')
    parser.add_argument('--verbose', '-v', action='store_true',
                        help='Enable verbose output')

    args = parser.parse_args()

    if args.verbose:
        logging.getLogger().setLevel(logging.DEBUG)

    scanner = FINSScanner(timeout=args.timeout)

    if args.scan_network:
        devices = scanner.scan_network(args.target, args.port)

        print("\n" + "=" * 70)
        print("Scan Results:")
        print("=" * 70)

        for device in devices:
            print(f"\n[Omron PLC] {device.ip}:{device.port}")
            print(f"  Model:          {device.model}")
            print(f"  Version:        {device.version}")
            print(f"  System Version: {device.system_version}")
            print(f"  CPU Mode:       {device.cpu_mode}")

        print("\n" + "=" * 70)
    else:
        device = scanner.scan_host(args.target, args.port)

        if device and device.reachable:
            print("\n" + "=" * 70)
            print(f"Omron PLC Detected: {device.ip}:{device.port}")
            print("=" * 70)
            print(f"  Model:          {device.model}")
            print(f"  Version:        {device.version}")
            print(f"  System Version: {device.system_version}")
            print(f"  CPU Mode:       {device.cpu_mode}")
            print("=" * 70 + "\n")
        else:
            print(f"[-] No Omron PLC found at {args.target}:{args.port}")

    return 0


if __name__ == '__main__':
    import sys
    sys.exit(main())
