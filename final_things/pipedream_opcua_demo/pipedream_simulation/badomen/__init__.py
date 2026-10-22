"""
BADOMEN - Omron PLC Attack Module for PIPEDREAM

Part of the PIPEDREAM (INCONTROLLER) ICS malware framework.
BADOMEN handles all Omron PLC attacks via FINS protocol.

Capabilities:
- FINS protocol scanning (port 9600)
- HTTP response parsing
- MAC address retrieval
- Device polling and enumeration
- File backup and restoration
- Custom agent loading
- Memory wiping and device reset
- Telnet daemon activation
- Network packet capture
- Process killing
- File transfer
- Servo drive communication

Target Devices:
- Omron Sysmac NJ and NX PLCs
- NEX NX1P2, NX-SL3300, NX-ECC203
- NJ501-1300, S8VK, R88D-1SN10F-ECT

WARNING: For authorized security testing only.
"""

from .scanner import OmronScanner, OmronDevice
from .fins_attack import FINSAttack
from .http_parser import OmronHTTPParser
from .file_ops import OmronFileOps
from .telnet_attack import TelnetAttack
from .servo_attack import ServoAttack

__all__ = [
    'OmronScanner',
    'OmronDevice',
    'FINSAttack',
    'OmronHTTPParser',
    'OmronFileOps',
    'TelnetAttack',
    'ServoAttack',
]

__version__ = '1.0.0'
__author__ = 'PIPEDREAM Research Team'
__component__ = 'BADOMEN'
