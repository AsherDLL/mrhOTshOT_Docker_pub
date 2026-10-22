#!/usr/bin/env python3
"""
Schneider Electric PLC Scanner

Discovers Schneider Electric PLCs using UDP multicast (port 27127).
Part of EVILSCHOLAR attack module for PIPEDREAM.

Features:
- UDP multicast discovery on port 27127
- Device identification and fingerprinting
- Model detection (M340, M258, TM251, etc.)
- Version enumeration
- Network topology mapping

WARNING: For authorized security testing only.
"""

import socket
import struct
import logging
import select
from typing import List, Optional, Dict, Any
from dataclasses import dataclass
from enum import IntEnum

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - [EVILSCHOLAR-SCAN] - %(levelname)s - %(message)s'
)
logger = logging.getLogger('SchneiderScanner')


@dataclass
class SchneiderDevice:
    """Schneider Electric PLC Device Information"""
    ip: str
    port: int = 502
    model: str = ""
    firmware_version: str = ""
    serial_number: str = ""
    device_type: str = ""
    codesys_port: int = 1740
    reachable: bool = False
    supports_codesys: bool = False


class SchneiderScanner:
    """
    Schneider Electric PLC Scanner

    Discovers Schneider PLCs via UDP multicast and TCP Modbus.
    """

    # UDP multicast discovery
    MULTICAST_GROUP = '224.0.0.1'
    DISCOVERY_PORT = 27127

    # Schneider PLC models targeted by PIPEDREAM
    TARGET_MODELS = [
        'TM251', 'TM241', 'M258', 'M238', 'M340',
        'LMC058', 'LMC078', 'MODICON', 'MOMENTUM'
    ]

    def __init__(self, timeout: float = 3.0):
        self.timeout = timeout
        self.discovered_devices: List[SchneiderDevice] = []

    def udp_multicast_scan(self, interface_ip: str = '0.0.0.0') -> List[SchneiderDevice]:
        """
        Scan network using UDP multicast (Schneider discovery protocol)

        Args:
            interface_ip: Interface to send from

        Returns:
            List of discovered Schneider devices
        """
        logger.info("[*] Starting UDP multicast scan for Schneider PLCs...")
        logger.info(f"    Multicast group: {self.MULTICAST_GROUP}:{self.DISCOVERY_PORT}")

        devices = []

        try:
            # Create UDP socket
            sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM, socket.IPPROTO_UDP)
            sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            sock.settimeout(self.timeout)

            # Bind to discovery port
            sock.bind((interface_ip, 0))

            # Construct Schneider discovery packet
            # This is a simplified representation of the actual protocol
            discovery_packet = self._build_discovery_packet()

            # Send multicast discovery
            sock.sendto(discovery_packet, (self.MULTICAST_GROUP, self.DISCOVERY_PORT))
            logger.info("[+] Discovery packet sent")

            # Listen for responses
            import time as _time
            start_time = _time.time()
            while _time.time() - start_time < self.timeout:
                try:
                    ready = select.select([sock], [], [], 1.0)
                    if ready[0]:
                        data, addr = sock.recvfrom(4096)
                        device = self._parse_discovery_response(data, addr[0])
                        if device:
                            devices.append(device)
                            logger.warning(f"[!] Schneider PLC discovered: {addr[0]}")
                            logger.info(f"    Model: {device.model}")
                except socket.timeout:
                    break

            sock.close()

        except Exception as e:
            logger.error(f"Multicast scan error: {e}")

        logger.info(f"[+] Discovered {len(devices)} Schneider PLC(s)")
        self.discovered_devices.extend(devices)
        return devices

    def _build_discovery_packet(self) -> bytes:
        """Build Schneider discovery packet"""
        # Simplified Schneider discovery protocol packet
        # Real implementation would match actual Schneider protocol
        packet = bytearray()

        # Header
        packet.extend(b'\x00\x01')  # Version
        packet.extend(b'\x00\x00')  # Transaction ID
        packet.extend(b'\x00\x06')  # Length
        packet.extend(b'\xFF')      # Broadcast
        packet.extend(b'\x00')      # Function: Discover

        return bytes(packet)

    def _parse_discovery_response(self, data: bytes, ip: str) -> Optional[SchneiderDevice]:
        """Parse discovery response packet"""
        if len(data) < 10:
            return None

        device = SchneiderDevice(ip=ip, port=502)
        device.reachable = True

        # Parse response (simplified)
        # Real implementation would parse actual Schneider protocol
        try:
            # Extract model information
            if len(data) >= 50:
                model_bytes = data[10:30]
                model = model_bytes.rstrip(b'\x00').decode('ascii', errors='ignore')
                device.model = model.strip()

                # Check if it's a target model
                for target in self.TARGET_MODELS:
                    if target in device.model.upper():
                        logger.critical(f"[!!!] TARGET MODEL DETECTED: {device.model}")
                        break

                # Extract firmware version
                if len(data) >= 70:
                    fw_bytes = data[30:50]
                    device.firmware_version = fw_bytes.rstrip(b'\x00').decode('ascii', errors='ignore').strip()

        except Exception as e:
            logger.debug(f"Parse error: {e}")

        return device

    def scan_modbus_devices(self, targets: List[str]) -> List[SchneiderDevice]:
        """
        Scan specific IPs for Schneider PLCs via Modbus TCP

        Args:
            targets: List of IP addresses

        Returns:
            List of Schneider devices
        """
        logger.info(f"[*] Scanning {len(targets)} target(s) via Modbus TCP...")

        devices = []

        for target in targets:
            device = self._scan_modbus_single(target)
            if device:
                devices.append(device)

        logger.info(f"[+] Found {len(devices)} Schneider device(s) via Modbus")
        self.discovered_devices.extend(devices)
        return devices

    def _scan_modbus_single(self, target: str, port: int = 502) -> Optional[SchneiderDevice]:
        """Scan single target via Modbus TCP"""
        try:
            import sys
            import os
            sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
            from modbus_scanner import ModbusScanner

            scanner = ModbusScanner(timeout=self.timeout)
            modbus_dev = scanner.scan_host(target, port)

            if modbus_dev and modbus_dev.reachable:
                # Check if it's a Schneider device
                if 'schneider' in modbus_dev.vendor_name.lower():
                    device = SchneiderDevice(
                        ip=target,
                        port=port,
                        model=modbus_dev.model_name,
                        firmware_version=modbus_dev.version,
                        device_type=modbus_dev.product_code,
                        reachable=True
                    )

                    logger.warning(f"[!] Schneider PLC detected: {target}")
                    logger.info(f"    Model:    {device.model}")
                    logger.info(f"    Firmware: {device.firmware_version}")

                    # Check for CODESYS port
                    if self._check_codesys_port(target):
                        device.supports_codesys = True
                        logger.critical(f"[!!!] CODESYS port 1740 OPEN - vulnerable to brute-force")

                    return device

        except Exception as e:
            logger.debug(f"Modbus scan error for {target}: {e}")

        return None

    def _check_codesys_port(self, target: str, port: int = 1740) -> bool:
        """Check if CODESYS port is open"""
        try:
            sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            sock.settimeout(2.0)
            result = sock.connect_ex((target, port))
            sock.close()
            return result == 0
        except:
            return False

    def enumerate_network(self, network_range: str) -> List[SchneiderDevice]:
        """
        Enumerate entire network for Schneider PLCs

        Args:
            network_range: CIDR notation

        Returns:
            List of devices
        """
        import ipaddress

        logger.info(f"[*] Enumerating network {network_range}...")

        devices = []
        network = ipaddress.IPv4Network(network_range, strict=False)

        # First try multicast discovery
        multicast_devices = self.udp_multicast_scan()
        devices.extend(multicast_devices)

        # Then scan each IP via Modbus
        targets = [str(ip) for ip in network.hosts()]
        modbus_devices = self.scan_modbus_devices(targets)

        # Merge results (avoid duplicates)
        existing_ips = {d.ip for d in devices}
        for device in modbus_devices:
            if device.ip not in existing_ips:
                devices.append(device)

        logger.info(f"[+] Total Schneider devices found: {len(devices)}")

        return devices

    def generate_target_report(self) -> Dict[str, Any]:
        """Generate attack target report"""
        report = {
            'total_devices': len(self.discovered_devices),
            'codesys_vulnerable': sum(1 for d in self.discovered_devices if d.supports_codesys),
            'target_models': [],
            'devices': []
        }

        for device in self.discovered_devices:
            dev_info = {
                'ip': device.ip,
                'model': device.model,
                'firmware': device.firmware_version,
                'codesys': device.supports_codesys
            }
            report['devices'].append(dev_info)

            # Check if target model
            for target_model in self.TARGET_MODELS:
                if target_model in device.model.upper():
                    if device not in report['target_models']:
                        report['target_models'].append(dev_info)

        return report


def main():
    """Main entry point"""
    import argparse

    parser = argparse.ArgumentParser(
        description='Schneider Electric PLC Scanner (EVILSCHOLAR)',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # UDP multicast discovery
  python scanner.py --multicast

  # Scan specific network
  python scanner.py --network 192.168.1.0/24

  # Scan specific targets
  python scanner.py --targets 192.168.1.6 192.168.1.7

Target Models:
  - Schneider Electric MODICON M340, M258, M238
  - MODICON Nano: TM251, TM241
  - MODICON LMC: LMC058, LMC078

WARNING: For authorized security testing only!
        """
    )

    parser.add_argument('--multicast', action='store_true',
                        help='Perform UDP multicast discovery')
    parser.add_argument('--network', '-n',
                        help='Network range to scan (CIDR notation)')
    parser.add_argument('--targets', '-t', nargs='+',
                        help='Specific IP addresses to scan')
    parser.add_argument('--report', action='store_true',
                        help='Generate target report')
    parser.add_argument('--timeout', type=float, default=3.0,
                        help='Timeout for scans')
    parser.add_argument('--verbose', '-v', action='store_true',
                        help='Verbose output')

    args = parser.parse_args()

    if args.verbose:
        logging.getLogger().setLevel(logging.DEBUG)

    scanner = SchneiderScanner(timeout=args.timeout)

    # Perform scans
    if args.multicast:
        scanner.udp_multicast_scan()

    if args.network:
        scanner.enumerate_network(args.network)

    if args.targets:
        scanner.scan_modbus_devices(args.targets)

    # Generate report
    if args.report or scanner.discovered_devices:
        report = scanner.generate_target_report()

        print("\n" + "=" * 70)
        print("EVILSCHOLAR - Schneider PLC Scan Report")
        print("=" * 70)
        print(f"Total Devices:         {report['total_devices']}")
        print(f"CODESYS Vulnerable:    {report['codesys_vulnerable']}")
        print(f"Target Models Found:   {len(report['target_models'])}")
        print("\n" + "=" * 70)
        print("Discovered Devices:")
        print("=" * 70)

        for dev in report['devices']:
            print(f"\n[{dev['ip']}]")
            print(f"  Model:    {dev['model']}")
            print(f"  Firmware: {dev['firmware']}")
            print(f"  CODESYS:  {'VULNERABLE' if dev['codesys'] else 'Not detected'}")

        print("\n" + "=" * 70 + "\n")

    return 0


if __name__ == '__main__':
    import sys
    sys.exit(main())
