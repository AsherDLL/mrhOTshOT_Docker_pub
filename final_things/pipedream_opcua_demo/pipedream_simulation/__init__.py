"""
PIPEDREAM Attack Simulation Package

Simulates PIPEDREAM (INCONTROLLER) attack patterns against OPC-UA servers.
Based on the 2022 discovery by Dragos of this ICS-targeted malware framework.

Components:
- OPCUAScanner: Network scanning and OPC-UA enumeration
- OPCUAAttack: Base class for OPC-UA attacks
- AttackWaterTank: Water tank overflow attack
- AttackPowerGrid: Power grid blackout attack
- AttackGasPipeline: Gas pipeline overpressure attack
- PIPEDREAMSimulation: Main attack orchestrator
- OPCUAFingerprinter: Server fingerprinting and reconnaissance
- OPCUABruteforcer: Credential brute-force attacks
- OPCUADoS: Denial of Service attacks
"""

from .attack_water_tank import AttackWaterTank
from .attack_power_grid import AttackPowerGrid
from .attack_gas_pipeline import AttackGasPipeline
from .pipedream_simulation import PIPEDREAMSimulation

# Import MOUSEHOLE components
from .mousehole import OPCUAScanner, OPCUAFingerprinter, OPCUABruteforcer, OPCUADoS
from .mousehole.attack import OPCUAAttack

# Import PIPEDREAM component modules
from . import mousehole

__all__ = [
    # Main orchestrator
    'PIPEDREAMSimulation',

    # Attack modules
    'AttackWaterTank',
    'AttackPowerGrid',
    'AttackGasPipeline',

    # MOUSEHOLE (OPC-UA attacks)
    'OPCUAScanner',
    'OPCUAAttack',
    'OPCUAFingerprinter',
    'OPCUABruteforcer',
    'OPCUADoS',
    'mousehole'
]
