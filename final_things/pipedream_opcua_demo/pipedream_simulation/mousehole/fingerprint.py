#!/usr/bin/env python3
"""
OPC-UA Server Fingerprinting Module

PIPEDREAM-style server fingerprinting that extracts:
- Server identity and build info
- Security policies and modes
- Supported endpoints
- Namespace array
- Server capabilities
- User token policies

This replicates the reconnaissance capabilities of real ICS malware.
"""

import asyncio
import socket
import logging
import sys
from typing import Dict, List, Optional, Any
from dataclasses import dataclass, field
from datetime import datetime

# Setup logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    handlers=[logging.StreamHandler(sys.stdout)]
)
logger = logging.getLogger('OPCUAFingerprint')


@dataclass
class ServerIdentity:
    """OPC-UA Server identity information"""
    application_uri: str = ""
    product_uri: str = ""
    application_name: str = ""
    application_type: str = ""
    gateway_server_uri: str = ""
    discovery_profile_uri: str = ""
    discovery_urls: List[str] = field(default_factory=list)


@dataclass
class BuildInfo:
    """OPC-UA Server build information"""
    product_uri: str = ""
    manufacturer_name: str = ""
    product_name: str = ""
    software_version: str = ""
    build_number: str = ""
    build_date: str = ""


@dataclass
class SecurityEndpoint:
    """OPC-UA Security endpoint information"""
    endpoint_url: str = ""
    security_mode: str = ""
    security_policy: str = ""
    user_token_policies: List[str] = field(default_factory=list)
    transport_profile: str = ""
    security_level: int = 0


@dataclass
class ServerFingerprint:
    """Complete server fingerprint"""
    target: str = ""
    port: int = 4840
    scan_time: str = ""
    reachable: bool = False

    # Identity
    identity: Optional[ServerIdentity] = None
    build_info: Optional[BuildInfo] = None

    # Capabilities
    namespaces: List[str] = field(default_factory=list)
    server_capabilities: List[str] = field(default_factory=list)

    # Security
    security_endpoints: List[SecurityEndpoint] = field(default_factory=list)
    anonymous_allowed: bool = False
    username_allowed: bool = False
    certificate_allowed: bool = False

    # Status
    server_state: str = ""
    current_time: str = ""
    start_time: str = ""

    # Nodes
    root_nodes: List[str] = field(default_factory=list)


class OPCUAFingerprinter:
    """
    OPC-UA Server Fingerprinting

    Extracts detailed information about OPC-UA servers
    for reconnaissance and attack planning.
    """

    # Known security policies
    SECURITY_POLICIES = {
        "None": "http://opcfoundation.org/UA/SecurityPolicy#None",
        "Basic128Rsa15": "http://opcfoundation.org/UA/SecurityPolicy#Basic128Rsa15",
        "Basic256": "http://opcfoundation.org/UA/SecurityPolicy#Basic256",
        "Basic256Sha256": "http://opcfoundation.org/UA/SecurityPolicy#Basic256Sha256",
        "Aes128_Sha256_RsaOaep": "http://opcfoundation.org/UA/SecurityPolicy#Aes128_Sha256_RsaOaep",
        "Aes256_Sha256_RsaPss": "http://opcfoundation.org/UA/SecurityPolicy#Aes256_Sha256_RsaPss",
    }

    # Security modes
    SECURITY_MODES = {
        1: "None",
        2: "Sign",
        3: "SignAndEncrypt"
    }

    def __init__(self, target: str, port: int = 4840, timeout: float = 10.0):
        self.target = target
        self.port = port
        self.timeout = timeout
        self.endpoint = f"opc.tcp://{target}:{port}"
        self.fingerprint = ServerFingerprint(
            target=target,
            port=port,
            scan_time=datetime.now().isoformat()
        )

    def check_port(self) -> bool:
        """Check if OPC-UA port is open"""
        try:
            sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            sock.settimeout(self.timeout)
            result = sock.connect_ex((self.target, self.port))
            sock.close()
            return result == 0
        except:
            return False

    async def get_endpoints(self) -> List[SecurityEndpoint]:
        """Get all security endpoints without connecting"""
        endpoints = []

        try:
            from asyncua import Client
            from asyncua.ua import MessageSecurityMode

            # Create client just for endpoint discovery
            client = Client(url=f"{self.endpoint}/freeopcua/server/")
            client.set_timeout(self.timeout)

            # Get endpoints (doesn't require authentication)
            eps = await client.connect_and_get_server_endpoints()

            for ep in eps:
                sec_endpoint = SecurityEndpoint(
                    endpoint_url=ep.EndpointUrl,
                    security_mode=self.SECURITY_MODES.get(ep.SecurityMode, str(ep.SecurityMode)),
                    security_policy=self._parse_policy_uri(ep.SecurityPolicyUri),
                    transport_profile=ep.TransportProfileUri,
                    security_level=ep.SecurityLevel
                )

                # Parse user token policies
                for token in ep.UserIdentityTokens:
                    token_type = str(token.TokenType).split('.')[-1]
                    sec_endpoint.user_token_policies.append(token_type)

                    if "Anonymous" in token_type:
                        self.fingerprint.anonymous_allowed = True
                    elif "UserName" in token_type:
                        self.fingerprint.username_allowed = True
                    elif "Certificate" in token_type:
                        self.fingerprint.certificate_allowed = True

                endpoints.append(sec_endpoint)

        except Exception as e:
            logger.debug(f"Endpoint discovery error: {e}")

        return endpoints

    def _parse_policy_uri(self, uri: str) -> str:
        """Parse security policy URI to friendly name"""
        for name, policy_uri in self.SECURITY_POLICIES.items():
            if policy_uri == uri:
                return name
        return uri.split('#')[-1] if '#' in uri else uri

    async def get_server_info(self) -> bool:
        """Connect and extract server information"""
        try:
            from asyncua import Client

            # Try anonymous connection first
            client = Client(url=f"{self.endpoint}/freeopcua/server/")
            client.set_timeout(self.timeout)

            await client.connect()

            try:
                # Get server node
                server_node = client.get_server_node()

                # Get namespaces
                ns_array = await client.get_namespace_array()
                self.fingerprint.namespaces = list(ns_array)

                # Get server status
                try:
                    status_node = client.get_node("ns=0;i=2256")  # ServerStatus
                    status = await status_node.read_value()

                    if hasattr(status, 'State'):
                        self.fingerprint.server_state = str(status.State).split('.')[-1]
                    if hasattr(status, 'CurrentTime'):
                        self.fingerprint.current_time = str(status.CurrentTime)
                    if hasattr(status, 'StartTime'):
                        self.fingerprint.start_time = str(status.StartTime)

                    # Build info
                    if hasattr(status, 'BuildInfo'):
                        bi = status.BuildInfo
                        self.fingerprint.build_info = BuildInfo(
                            product_uri=str(getattr(bi, 'ProductUri', '')),
                            manufacturer_name=str(getattr(bi, 'ManufacturerName', '')),
                            product_name=str(getattr(bi, 'ProductName', '')),
                            software_version=str(getattr(bi, 'SoftwareVersion', '')),
                            build_number=str(getattr(bi, 'BuildNumber', '')),
                            build_date=str(getattr(bi, 'BuildDate', ''))
                        )
                except Exception as e:
                    logger.debug(f"Could not read server status: {e}")

                # Get root object nodes
                try:
                    objects = client.get_objects_node()
                    children = await objects.get_children()
                    for child in children:
                        name = await child.read_browse_name()
                        self.fingerprint.root_nodes.append(name.Name)
                except Exception as e:
                    logger.debug(f"Could not browse objects: {e}")

                # Get server capabilities
                try:
                    caps_node = client.get_node("ns=0;i=2268")  # ServerCapabilities
                    children = await caps_node.get_children()
                    for child in children:
                        name = await child.read_browse_name()
                        self.fingerprint.server_capabilities.append(name.Name)
                except:
                    pass

                return True

            finally:
                await client.disconnect()

        except Exception as e:
            logger.debug(f"Server info extraction error: {e}")
            return False

    async def fingerprint_server(self) -> ServerFingerprint:
        """Perform complete server fingerprinting"""
        logger.info(f"\n{'='*60}")
        logger.info(f"OPC-UA SERVER FINGERPRINTING")
        logger.info(f"{'='*60}")
        logger.info(f"Target: {self.target}:{self.port}")
        logger.info(f"{'='*60}\n")

        # Check port
        logger.info("[*] Checking port accessibility...")
        self.fingerprint.reachable = self.check_port()

        if not self.fingerprint.reachable:
            logger.error(f"[-] Port {self.port} not accessible")
            return self.fingerprint

        logger.info(f"[+] Port {self.port} is OPEN")

        # Get security endpoints
        logger.info("\n[*] Enumerating security endpoints...")
        self.fingerprint.security_endpoints = await self.get_endpoints()

        if self.fingerprint.security_endpoints:
            logger.info(f"[+] Found {len(self.fingerprint.security_endpoints)} endpoint(s)")
            for ep in self.fingerprint.security_endpoints:
                logger.info(f"    - {ep.security_mode}/{ep.security_policy}")
                logger.info(f"      Tokens: {', '.join(ep.user_token_policies)}")

        # Get server info
        logger.info("\n[*] Extracting server information...")
        if await self.get_server_info():
            logger.info("[+] Server information extracted")
        else:
            logger.warning("[!] Could not extract full server info")

        # Print summary
        self._print_summary()

        return self.fingerprint

    def _print_summary(self):
        """Print fingerprint summary"""
        fp = self.fingerprint

        print(f"\n{'='*60}")
        print("FINGERPRINT SUMMARY")
        print(f"{'='*60}")

        print(f"\n[TARGET]")
        print(f"  Address:     {fp.target}:{fp.port}")
        print(f"  Reachable:   {fp.reachable}")
        print(f"  Scan Time:   {fp.scan_time}")

        if fp.build_info:
            print(f"\n[BUILD INFO]")
            print(f"  Product:     {fp.build_info.product_name}")
            print(f"  Vendor:      {fp.build_info.manufacturer_name}")
            print(f"  Version:     {fp.build_info.software_version}")
            print(f"  Build:       {fp.build_info.build_number}")

        print(f"\n[SERVER STATUS]")
        print(f"  State:       {fp.server_state}")
        print(f"  Start Time:  {fp.start_time}")

        print(f"\n[SECURITY]")
        print(f"  Anonymous:   {'ALLOWED' if fp.anonymous_allowed else 'Not allowed'}")
        print(f"  Username:    {'ALLOWED' if fp.username_allowed else 'Not allowed'}")
        print(f"  Certificate: {'ALLOWED' if fp.certificate_allowed else 'Not allowed'}")

        if fp.security_endpoints:
            print(f"\n[ENDPOINTS]")
            for ep in fp.security_endpoints:
                print(f"  - {ep.security_mode} / {ep.security_policy}")

        if fp.namespaces:
            print(f"\n[NAMESPACES]")
            for i, ns in enumerate(fp.namespaces):
                print(f"  {i}: {ns}")

        if fp.root_nodes:
            print(f"\n[ROOT OBJECTS]")
            for node in fp.root_nodes:
                print(f"  - {node}")

        print(f"\n{'='*60}\n")


async def main():
    """Test fingerprinting"""
    import argparse

    parser = argparse.ArgumentParser(description='OPC-UA Server Fingerprinting')
    parser.add_argument('--target', '-t', default='192.168.1.6',
                        help='Target IP (default: 192.168.1.6)')
    parser.add_argument('--port', '-p', type=int, default=4840,
                        help='OPC-UA port (default: 4840)')
    parser.add_argument('--timeout', type=float, default=10.0,
                        help='Connection timeout')

    args = parser.parse_args()

    fingerprinter = OPCUAFingerprinter(args.target, args.port, args.timeout)
    await fingerprinter.fingerprint_server()


if __name__ == '__main__':
    asyncio.run(main())
