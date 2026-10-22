"""
MOUSEHOLE - OPC-UA Attack Module for PIPEDREAM

Part of the PIPEDREAM (INCONTROLLER) ICS malware framework.
MOUSEHOLE handles all OPC-UA server attacks and reconnaissance.

Capabilities:
- OPC-UA server discovery and scanning
- Credential brute-forcing
- Server fingerprinting
- Denial-of-service attacks
- Node manipulation
- Process control interference

WARNING: For authorized security testing only.
"""

from .scanner import OPCUAScanner
from .attack import AttackResult
from .bruteforce import OPCUABruteforcer
from .fingerprint import OPCUAFingerprinter
from .dos import OPCUADoS

__all__ = [
    'OPCUAScanner',
    'AttackResult',
    'OPCUABruteforcer',
    'OPCUAFingerprinter',
    'OPCUADoS',
]

__version__ = '1.0.0'
__author__ = 'PIPEDREAM Research Team'
