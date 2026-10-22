"""
EVILSCHOLAR - Schneider Electric Attack Module for PIPEDREAM

Part of the PIPEDREAM (INCONTROLLER) ICS malware framework.
EVILSCHOLAR handles all Schneider Electric PLC attacks.

Capabilities:
- UDP multicast scanning (port 27127) for Schneider PLCs
- CODESYS brute-force attacks (port 1740)
- Modbus TCP manipulation and custom commands
- Denial-of-service attacks
- PLC crash and configuration recovery
- File operations (list, delete, transfer)
- Network route manipulation
- Credential dropping and gathering

Target Devices:
- Schneider Electric MODICON M340, M258, M238
- MODICON Nano: TM251, TM241, LMC058, LMC078

WARNING: For authorized security testing only.
"""

from .scanner import SchneiderScanner, SchneiderDevice
from .codesys import CodesysBruteforcer, CodesysAttack
from .modbus_attack import ModbusAttack
from .dos import SchneiderDoS
from .file_ops import SchneiderFileOps

__all__ = [
    'SchneiderScanner',
    'SchneiderDevice',
    'CodesysBruteforcer',
    'CodesysAttack',
    'ModbusAttack',
    'SchneiderDoS',
    'SchneiderFileOps',
]

__version__ = '1.0.0'
__author__ = 'PIPEDREAM Research Team'
__component__ = 'EVILSCHOLAR'
