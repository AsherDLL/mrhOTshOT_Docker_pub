#!/usr/bin/env python3
"""
Modbus TCP Scanner and Fingerprinter

Discovers and fingerprints Modbus TCP devices (Schneider Electric, etc.).
Part of PIPEDREAM malware simulation toolkit.

Features:
- Port scanning for Modbus TCP (502)
- Device identification via MEI function
- Vendor/model fingerprinting
- Register enumeration

Usage:
    python modbus_scanner.py --target 192.168.1.6
    python modbus_scanner.py --target 192.168.1.0/24 --scan-network
"""

import socket
import struct
import logging
from typing import Optional, Dict, Any, List
from dataclasses import dataclass

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - [MODBUS-SCAN] - %(levelname)s - %(message)s'
)
logger = logging.getLogger('ModbusScanner')


@dataclass
class ModbusDevice:
    """Modbus Device Information"""
    ip: str
    port: int
    vendor_name: str = ""
    product_code: str = ""
    product_name: str = ""
    model_name: str = ""
    version: str = ""
    vendor_url: str = ""
    application_name: str = ""
    reachable: bool = False


class ModbusScanner:
    """
    Modbus TCP Scanner and Fingerprinter

    Discovers Modbus devices and extracts vendor/model information.
    """

    # Modbus function codes
    READ_HOLDING_REGISTERS = 0x03
    READ_DEVICE_IDENTIFICATION = 0x2B

    # MEI type
    MEI_READ_DEVICE_ID = 0x0E

    # Device ID objects
    OBJ_VENDOR_NAME = 0x00
    OBJ_PRODUCT_CODE = 0x01
    OBJ_MAJOR_MINOR_REVISION = 0x02
    OBJ_VENDOR_URL = 0x03
    OBJ_PRODUCT_NAME = 0x04
    OBJ_MODEL_NAME = 0x05
    OBJ_USER_APPLICATION_NAME = 0x06

    def __init__(self, timeout: float = 3.0):
        self.timeout = timeout
        self.transaction_id = 1

    def scan_host(self, target: str, port: int = 502) -> Optional[ModbusDevice]:
        """
        Scan single host for Modbus service

        Args:
            target: Target IP address
            port: Modbus port (default 502)

        Returns:
            ModbusDevice if found, None otherwise
        """
        device = ModbusDevice(ip=target, port=port)

        # Check if port is open
        if not self._check_port(target, port):
            return None

        device.reachable = True
        logger.info(f"[+] Modbus TCP service detected at {target}:{port}")

        # Get device identification
        device_info = self._get_device_identification(target, port)
        if device_info:
            device.vendor_name = device_info.get(self.OBJ_VENDOR_NAME, 'Unknown')
            device.product_code = device_info.get(self.OBJ_PRODUCT_CODE, 'Unknown')
            device.version = device_info.get(self.OBJ_MAJOR_MINOR_REVISION, 'Unknown')
            device.vendor_url = device_info.get(self.OBJ_VENDOR_URL, '')
            device.product_name = device_info.get(self.OBJ_PRODUCT_NAME, '')
            device.model_name = device_info.get(self.OBJ_MODEL_NAME, '')
            device.application_name = device_info.get(self.OBJ_USER_APPLICATION_NAME, '')

            logger.warning(f"[!] Modbus Device Identified:")
            logger.warning(f"    Vendor:  {device.vendor_name}")
            logger.warning(f"    Product: {device.product_code}")
            logger.warning(f"    Model:   {device.model_name}")
            logger.warning(f"    Version: {device.version}")

            # Detect Schneider Electric devices
            if "schneider" in device.vendor_name.lower():
                logger.critical(f"[!!!] SCHNEIDER ELECTRIC PLC DETECTED")
                logger.critical(f"      Target for PIPEDREAM Codesys attack")

        return device

    def _check_port(self, target: str, port: int) -> bool:
        """Check if Modbus port is open"""
        try:
            sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            sock.settimeout(self.timeout)
            result = sock.connect_ex((target, port))
            sock.close()
            return result == 0
        except:
            return False

    def _build_modbus_request(self, function_code: int, data: bytes, unit_id: int = 1) -> bytes:
        """Build Modbus TCP request"""
        # MBAP Header
        transaction_id = self.transaction_id
        self.transaction_id += 1

        protocol_id = 0
        length = len(data) + 2  # Function code + data

        mbap_header = struct.pack('>HHHB',
                                  transaction_id,
                                  protocol_id,
                                  length,
                                  unit_id)

        # PDU
        pdu = struct.pack('B', function_code) + data

        return mbap_header + pdu

    def _get_device_identification(self, target: str, port: int) -> Optional[Dict[int, str]]:
        """
        Get device identification using MEI function 0x2B/0x0E

        Returns:
            Dict mapping object ID to value string
        """
        try:
            sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            sock.settimeout(self.timeout)
            sock.connect((target, port))

            # Build Read Device Identification request
            # MEI Type (0x0E), Read Device ID Code (0x01=basic), Object ID (0x00=start)
            data = struct.pack('BBB', self.MEI_READ_DEVICE_ID, 0x01, 0x00)
            request = self._build_modbus_request(self.READ_DEVICE_IDENTIFICATION, data)

            sock.send(request)
            response = sock.recv(2048)
            sock.close()

            if len(response) < 7:
                return None

            # Parse MBAP header
            trans_id, proto_id, length, unit_id = struct.unpack('>HHHB', response[:7])

            # Parse PDU
            pdu = response[7:]
            if len(pdu) < 6:
                return None

            function_code = pdu[0]

            # Check for exception
            if function_code & 0x80:
                logger.debug("Device Identification not supported")
                return None

            # Parse MEI response
            mei_type = pdu[1]
            read_dev_id_code = pdu[2]
            conformity_level = pdu[3]
            more_follows = pdu[4]
            next_obj_id = pdu[5]
            num_objects = pdu[6]

            # Parse objects
            device_info = {}
            offset = 7

            for _ in range(num_objects):
                if offset + 2 > len(pdu):
                    break

                obj_id = pdu[offset]
                obj_len = pdu[offset + 1]
                offset += 2

                if offset + obj_len > len(pdu):
                    break

                obj_value = pdu[offset:offset + obj_len].decode('ascii', errors='ignore')
                device_info[obj_id] = obj_value

                offset += obj_len

            return device_info

        except Exception as e:
            logger.debug(f"Device identification error: {e}")
            return None

    def scan_network(self, target_range: str, port: int = 502) -> List[ModbusDevice]:
        """
        Scan network range for Modbus devices

        Args:
            target_range: CIDR notation (e.g., "192.168.1.0/24")
            port: Modbus port

        Returns:
            List of discovered devices
        """
        import ipaddress

        devices = []
        network = ipaddress.IPv4Network(target_range, strict=False)

        logger.info(f"Scanning {network} for Modbus TCP services...")

        for ip in network.hosts():
            device = self.scan_host(str(ip), port)
            if device and device.reachable:
                devices.append(device)

        logger.info(f"Found {len(devices)} Modbus device(s)")
        return devices

    def enumerate_registers(self, target: str, port: int = 502,
                           start: int = 0, count: int = 10) -> Optional[List[int]]:
        """
        Enumerate holding registers (for reconnaissance)

        Args:
            target: Target IP
            port: Modbus port
            start: Starting register address
            count: Number of registers to read

        Returns:
            List of register values or None on error
        """
        try:
            sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            sock.settimeout(self.timeout)
            sock.connect((target, port))

            # Build Read Holding Registers request
            data = struct.pack('>HH', start, count)
            request = self._build_modbus_request(self.READ_HOLDING_REGISTERS, data)

            sock.send(request)
            response = sock.recv(2048)
            sock.close()

            if len(response) < 9:
                return None

            # Parse response
            pdu = response[7:]
            function_code = pdu[0]

            if function_code & 0x80:
                return None

            byte_count = pdu[1]
            register_data = pdu[2:2 + byte_count]

            # Unpack registers
            registers = struct.unpack(f'>{count}H', register_data)
            return list(registers)

        except Exception as e:
            logger.debug(f"Register enumeration error: {e}")
            return None


def main():
    """Main entry point"""
    import argparse

    parser = argparse.ArgumentParser(
        description='Modbus TCP Scanner and Fingerprinter',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # Scan single host
  python modbus_scanner.py --target 192.168.1.6

  # Scan network range
  python modbus_scanner.py --target 192.168.1.0/24 --scan-network

  # Enumerate registers
  python modbus_scanner.py --target 192.168.1.6 --enumerate --start 0 --count 20

Output:
  - Detected Modbus devices
  - Vendor and model information
  - Device identification details
        """
    )

    parser.add_argument('--target', '-t', required=True,
                        help='Target IP or network range (CIDR)')
    parser.add_argument('--port', '-p', type=int, default=502,
                        help='Modbus port (default: 502)')
    parser.add_argument('--scan-network', action='store_true',
                        help='Treat target as network range')
    parser.add_argument('--enumerate', action='store_true',
                        help='Enumerate holding registers')
    parser.add_argument('--start', type=int, default=0,
                        help='Starting register address for enumeration')
    parser.add_argument('--count', type=int, default=10,
                        help='Number of registers to read')
    parser.add_argument('--timeout', type=float, default=3.0,
                        help='Connection timeout in seconds')
    parser.add_argument('--verbose', '-v', action='store_true',
                        help='Enable verbose output')

    args = parser.parse_args()

    if args.verbose:
        logging.getLogger().setLevel(logging.DEBUG)

    scanner = ModbusScanner(timeout=args.timeout)

    if args.scan_network:
        devices = scanner.scan_network(args.target, args.port)

        print("\n" + "=" * 70)
        print("Scan Results:")
        print("=" * 70)

        for device in devices:
            print(f"\n[Modbus Device] {device.ip}:{device.port}")
            print(f"  Vendor:      {device.vendor_name}")
            print(f"  Product:     {device.product_code}")
            print(f"  Model:       {device.model_name}")
            print(f"  Version:     {device.version}")
            if device.vendor_url:
                print(f"  Vendor URL:  {device.vendor_url}")
            if device.application_name:
                print(f"  Application: {device.application_name}")

        print("\n" + "=" * 70)
    else:
        device = scanner.scan_host(args.target, args.port)

        if device and device.reachable:
            print("\n" + "=" * 70)
            print(f"Modbus Device Detected: {device.ip}:{device.port}")
            print("=" * 70)
            print(f"  Vendor:      {device.vendor_name}")
            print(f"  Product:     {device.product_code}")
            print(f"  Model:       {device.model_name}")
            print(f"  Version:     {device.version}")
            if device.vendor_url:
                print(f"  Vendor URL:  {device.vendor_url}")
            if device.product_name:
                print(f"  Product:     {device.product_name}")
            if device.application_name:
                print(f"  Application: {device.application_name}")
            print("=" * 70 + "\n")

            # Enumerate registers if requested
            if args.enumerate:
                print("Enumerating Holding Registers:")
                print("-" * 70)
                registers = scanner.enumerate_registers(
                    args.target, args.port, args.start, args.count
                )

                if registers:
                    for i, value in enumerate(registers):
                        addr = args.start + i
                        print(f"  Register {addr:5d}: {value:5d} (0x{value:04X})")
                    print("=" * 70 + "\n")
                else:
                    print("  Failed to read registers")
        else:
            print(f"[-] No Modbus device found at {args.target}:{args.port}")

    return 0


if __name__ == '__main__':
    import sys
    sys.exit(main())
