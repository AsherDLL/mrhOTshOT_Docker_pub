#!/usr/bin/env python3
"""
OPC-UA Scanner for PIPEDREAM Attack Simulation

Provides network scanning and OPC-UA server enumeration capabilities.
Mimics PIPEDREAM's reconnaissance phase.
"""

import socket
import logging
import time
from typing import Dict, Any, List, Optional
from dataclasses import dataclass

# Setup logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger('OPCUAScanner')


@dataclass
class ScanResult:
    """Result of a port scan"""
    ip: str
    port: int
    open: bool
    service: str
    banner: Optional[str] = None


@dataclass
class OPCUAServerInfo:
    """Information about discovered OPC-UA server"""
    endpoint: str
    server_name: str
    security_policies: List[str]
    namespaces: List[str]
    nodes: Dict[str, Any]


class OPCUAScanner:
    """
    OPC-UA Scanner for Device Enumeration

    Capabilities:
    - Port scanning for ICS protocols
    - OPC-UA endpoint discovery
    - OPC-UA node tree enumeration
    - Server security policy detection
    """

    # Industrial protocol ports
    ICS_PORTS = {
        4840: "OPC-UA",
        502: "Modbus TCP",
        102: "Siemens S7",
        2404: "IEC 60870-5-104",
        47808: "BACnet",
        20000: "DNP3",
        44818: "Ethernet/IP"
    }

    def __init__(self, timeout: float = 3.0):
        """
        Initialize scanner

        Args:
            timeout: Socket timeout in seconds
        """
        self.timeout = timeout
        self.discovered_servers = []
        self.scan_results = []

    def port_scan(self, target: str, ports: List[int] = None) -> List[ScanResult]:
        """
        Scan target for open ports

        Args:
            target: Target IP address
            ports: List of ports to scan (default: ICS ports)

        Returns:
            List of ScanResult objects
        """
        if ports is None:
            ports = list(self.ICS_PORTS.keys())

        results = []
        logger.info(f"[*] Scanning {target} for ICS protocol ports...")

        for port in ports:
            service = self.ICS_PORTS.get(port, "Unknown")
            result = self._scan_port(target, port, service)
            results.append(result)

            if result.open:
                logger.warning(f"[!] {service} FOUND on {target}:{port}")
            else:
                logger.debug(f"[-] Port {port} closed")

        self.scan_results = results
        return results

    def _scan_port(self, ip: str, port: int, service: str) -> ScanResult:
        """Scan a single port"""
        try:
            sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            sock.settimeout(self.timeout)
            result = sock.connect_ex((ip, port))
            sock.close()

            return ScanResult(
                ip=ip,
                port=port,
                open=(result == 0),
                service=service
            )
        except Exception as e:
            return ScanResult(ip=ip, port=port, open=False, service=service)

    def enumerate_opcua(self, target: str, port: int = 4840) -> Optional[OPCUAServerInfo]:
        """
        Enumerate OPC-UA server

        Args:
            target: Target IP address
            port: OPC-UA port (default: 4840)

        Returns:
            OPCUAServerInfo or None if enumeration fails
        """
        endpoint = f"opc.tcp://{target}:{port}/freeopcua/server/"
        logger.info(f"[*] Enumerating OPC-UA server at {endpoint}...")

        try:
            from opcua import Client

            client = Client(endpoint)
            client.connect()

            # Get server info
            server_name = "Unknown"
            try:
                server_node = client.get_server_node()
                server_name = server_node.get_browse_name().Name
            except:
                pass

            # Get namespaces
            namespaces = []
            try:
                ns_array = client.get_namespace_array()
                namespaces = list(ns_array)
            except:
                pass

            # Get security policies
            security_policies = ["NoSecurity"]  # Default for this simulation

            # Enumerate nodes
            nodes = self._enumerate_nodes(client)

            client.disconnect()

            server_info = OPCUAServerInfo(
                endpoint=endpoint,
                server_name=server_name,
                security_policies=security_policies,
                namespaces=namespaces,
                nodes=nodes
            )

            self.discovered_servers.append(server_info)
            logger.warning(f"[!] OPC-UA Server Enumerated Successfully")
            logger.info(f"    Server: {server_name}")
            logger.info(f"    Namespaces: {namespaces}")
            logger.info(f"    Nodes found: {len(nodes)}")

            return server_info

        except Exception as e:
            logger.error(f"[-] OPC-UA enumeration failed: {e}")
            return None

    def _enumerate_nodes(self, client) -> Dict[str, Any]:
        """Enumerate OPC-UA node tree"""
        nodes = {}

        try:
            root = client.get_root_node()
            objects = root.get_child(["0:Objects"])

            # Look for known process objects
            for process in ['WaterTank', 'PowerGrid', 'GasPipeline']:
                try:
                    process_node = objects.get_child([f"2:{process}"])
                    nodes[process] = self._enumerate_process_nodes(process_node)
                    logger.info(f"    [+] Found process: {process}")
                except:
                    pass

        except Exception as e:
            logger.debug(f"Node enumeration error: {e}")

        return nodes

    def _enumerate_process_nodes(self, process_node) -> Dict[str, List[str]]:
        """Enumerate nodes within a process"""
        result = {}

        for category in ['Measurements', 'Status', 'Alarms', 'Commands']:
            try:
                category_node = process_node.get_child([f"2:{category}"])
                children = category_node.get_children()
                result[category] = [child.get_browse_name().Name for child in children]
            except:
                pass

        return result

    def scan_network(self, network: str, port: int = 4840) -> List[str]:
        """
        Scan network range for OPC-UA servers

        Args:
            network: Network in CIDR notation (e.g., '192.168.1.0/24')
            port: Port to scan

        Returns:
            List of IP addresses with open port
        """
        import ipaddress

        logger.info(f"[*] Scanning network {network} for OPC-UA servers...")

        try:
            net = ipaddress.ip_network(network, strict=False)
            hosts_with_opcua = []

            for ip in net.hosts():
                ip_str = str(ip)
                result = self._scan_port(ip_str, port, "OPC-UA")
                if result.open:
                    hosts_with_opcua.append(ip_str)
                    logger.warning(f"[!] OPC-UA found at {ip_str}:{port}")

            logger.info(f"[+] Found {len(hosts_with_opcua)} OPC-UA servers")
            return hosts_with_opcua

        except Exception as e:
            logger.error(f"[-] Network scan error: {e}")
            return []

    def print_scan_results(self):
        """Print formatted scan results"""
        print("\n" + "=" * 60)
        print("SCAN RESULTS")
        print("=" * 60)

        open_ports = [r for r in self.scan_results if r.open]
        if open_ports:
            print(f"\nOpen ports found: {len(open_ports)}")
            for result in open_ports:
                print(f"  {result.ip}:{result.port} - {result.service}")
        else:
            print("\nNo open ICS ports found")

        if self.discovered_servers:
            print(f"\nOPC-UA Servers enumerated: {len(self.discovered_servers)}")
            for server in self.discovered_servers:
                print(f"\n  Endpoint: {server.endpoint}")
                print(f"  Server: {server.server_name}")
                print(f"  Namespaces: {server.namespaces}")
                print(f"  Processes found: {list(server.nodes.keys())}")

        print("=" * 60 + "\n")


def main():
    """Test the scanner"""
    import argparse

    parser = argparse.ArgumentParser(description='OPC-UA Scanner')
    parser.add_argument('--target', default='192.168.1.6', help='Target IP (default: 192.168.1.6)')
    parser.add_argument('--port', type=int, default=4840, help='OPC-UA port')

    args = parser.parse_args()

    scanner = OPCUAScanner()

    # Port scan
    scanner.port_scan(args.target)

    # Enumerate OPC-UA
    scanner.enumerate_opcua(args.target, args.port)

    # Print results
    scanner.print_scan_results()


if __name__ == '__main__':
    main()
