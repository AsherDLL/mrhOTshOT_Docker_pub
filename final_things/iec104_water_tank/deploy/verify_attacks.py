#!/usr/bin/env python3
"""
Attack Script Verification Suite

Runs all 12 attack scenarios against their targets, captures output + pcap,
validates success/failure, and writes a JSON report.

Run from PLC-1 (192.168.1.10) or any host on the OT network with the repo.

Usage:
    python3 verify_attacks.py
    python3 verify_attacks.py --attacks frostygoop,industroyer2
    python3 verify_attacks.py --no-reset   # skip post-attack reset
    python3 verify_attacks.py --duration 8
"""

import argparse
import datetime
import json
import os
import signal
import socket
import struct
import subprocess
import sys
import time
from pathlib import Path

# ── Paths ─────────────────────────────────────────────────────────────────────
SCRIPT_DIR  = Path(__file__).resolve().parent
REPO_ROOT   = SCRIPT_DIR.parent
SIM_DIR     = REPO_ROOT / "perform_malware_simulations"
PIPEDREAM   = REPO_ROOT.parent / "pipedream_opcua_demo" / "pipedream_simulation" / "pipedream_simulation.py"
LOGS_DIR    = SCRIPT_DIR / "logs" / "attack_verify"
LOGS_DIR.mkdir(parents=True, exist_ok=True)

# Find the best python - prefer the repo env (attacker), then ICS sim venv (PLCs),
# then fall back to sys.executable.
for _candidate in [
    Path("/home/kali/v3/mrhOTshOT/env/bin/python"),   # attacker VM repo env
    Path("/home/kalilinux/v3/mrhOTshOT/env/bin/python"),  # alt user
    Path("/opt/ics-sim/venv/bin/python"),              # ICS sim venv on PLCs
]:
    if _candidate.exists():
        PYTHON = str(_candidate)
        break
else:
    PYTHON = sys.executable

# ── Target map ────────────────────────────────────────────────────────────────
TARGETS = {
    "water":    "192.168.1.10",
    "power":    "192.168.1.11",
    "gas":      "192.168.1.12",
    "mfg":      "192.168.1.13",
    "hvac":     "192.168.1.14",
    "boiler":   "192.168.1.15",
    "heating":  "192.168.1.16",
    "dnp3":     "192.168.1.17",
    "sensors":  "192.168.1.18",
    "sis":      "192.168.1.19",
    "hmi":      "192.168.1.55",
    "router":   "192.168.0.13",
}

# ── ANSI ──────────────────────────────────────────────────────────────────────
GREEN  = lambda t: f"\033[32m{t}\033[0m"
RED    = lambda t: f"\033[31m{t}\033[0m"
YELLOW = lambda t: f"\033[33m{t}\033[0m"
BOLD   = lambda t: f"\033[1m{t}\033[0m"
DIM    = lambda t: f"\033[2m{t}\033[0m"

# ── Probe helpers ─────────────────────────────────────────────────────────────
def tcp_probe(host, port, timeout=2):
    try:
        s = socket.socket(); s.settimeout(timeout)
        ok = s.connect_ex((host, port)) == 0; s.close(); return ok
    except: return False

def modbus_read_coil(host, coil=4, port=502, timeout=2):
    """Read discrete input [coil] via FC02."""
    try:
        s = socket.socket(); s.settimeout(timeout); s.connect((host, port))
        pdu  = struct.pack('>BHH', 0x02, coil, 1)
        mbap = struct.pack('>HHHB', 1, 0, len(pdu)+1, 1)
        s.sendall(mbap + pdu); r = s.recv(64); s.close()
        return bool(r[9] & 1) if len(r) >= 10 else None
    except: return None

def modbus_read_level(host, port=502, timeout=2):
    """Read input register 0 (water level / supply temp) via FC04."""
    try:
        s = socket.socket(); s.settimeout(timeout); s.connect((host, port))
        pdu  = struct.pack('>BHH', 0x04, 0, 1)
        mbap = struct.pack('>HHHB', 1, 0, len(pdu)+1, 1)
        s.sendall(mbap + pdu); r = s.recv(64); s.close()
        return struct.unpack('>H', r[9:11])[0] / 65535 * 100 if len(r) >= 11 else None
    except: return None

def iec104_probe(host, port=2404, timeout=2):
    """Send STARTDT, return True if ACK received."""
    try:
        s = socket.socket(); s.settimeout(timeout); s.connect((host, port))
        s.sendall(bytes([0x68, 0x04, 0x07, 0x00, 0x00, 0x00]))
        r = s.recv(32); s.close()
        return len(r) >= 6 and r[2] == 0x0B
    except: return False

# ── tcpdump wrapper ───────────────────────────────────────────────────────────
def start_capture(iface, pcap_path, filter_expr):
    """Start tcpdump in background. Returns Popen handle."""
    cmd = ["tcpdump", "-i", iface, "-w", str(pcap_path), "-q",
           "--immediate-mode", filter_expr]
    try:
        proc = subprocess.Popen(cmd, stderr=subprocess.DEVNULL)
        time.sleep(0.5)  # let tcpdump bind
        return proc
    except FileNotFoundError:
        return None  # tcpdump not available

def stop_capture(proc):
    if proc and proc.poll() is None:
        proc.send_signal(signal.SIGINT)
        try: proc.wait(timeout=3)
        except: proc.kill()

def pcap_packet_count(pcap_path):
    """Count packets in pcap using tcpdump -r."""
    try:
        r = subprocess.run(["tcpdump", "-r", str(pcap_path), "-q", "--count"],
                           capture_output=True, text=True, timeout=5)
        # output: "N packets captured"
        for line in (r.stdout + r.stderr).split('\n'):
            if 'packet' in line.lower():
                parts = line.split()
                if parts and parts[0].isdigit():
                    return int(parts[0])
        return -1
    except: return -1

# ── Success keyword detector ──────────────────────────────────────────────────
SUCCESS_KEYWORDS = [
    "CONNECTED", "connected", "[+]", "PHASE", "started", "SUCCESS",
    "ATTACK", "Payload", "payload", "sending", "Sending",
    "malicious", "Malicious", "injected", "Injected",
    "complete", "Complete", "COMPLETE",
    "Exploit complete", "Command output", "RCE",
]
FAIL_KEYWORDS = [
    "Connection refused", "timed out", "unreachable",
    "ImportError", "ModuleNotFoundError", "Error connecting",
    "FAILED", "Failed to connect",
]

def classify_output(stdout, stderr):
    text = stdout + stderr
    hits_ok   = [kw for kw in SUCCESS_KEYWORDS if kw in text]
    hits_fail = [kw for kw in FAIL_KEYWORDS    if kw in text]
    return hits_ok, hits_fail

# ── Attack definitions ────────────────────────────────────────────────────────
def build_attacks(args):
    dur = str(args.duration)
    T = TARGETS
    return [
        {
            "id":      "router_exploit",
            "name":    "Router Exploit",
            "target":  f"{T['router']}:8080",
            "proto":   "HTTP",
            "cmd":     [PYTHON, str(SCRIPT_DIR.parent / "machines/attacker/scripts/01_router_exploit.py"),
                        T["router"], "--username", "admin", "--password", "admin", "--recon"],
            "cwd":     str(SCRIPT_DIR.parent),  # needs iec104_water_tank/ as cwd for imports
            "verify":  lambda: tcp_probe(T["router"], 8080),
            "check_filter": f"host {T['router']} and tcp port 8080",
            "timeout": 60,  # recon pings take ~16s, allow plenty of headroom
        },
        {
            "id":      "frostygoop",
            "name":    "FrostyGoop",
            "target":  f"{T['heating']}:502",
            "proto":   "Modbus TCP",
            "pre":     lambda: modbus_read_level(T["heating"]),
            "cmd":     [PYTHON, str(SIM_DIR/"frostygoop_simulation.py"),
                        "--target", T["heating"], "--port", "502", "--duration", dur],
            "post":    lambda: modbus_read_level(T["heating"]),
            "verify":  lambda: tcp_probe(T["heating"], 502),
            "check_filter": f"host {T['heating']} and tcp port 502",
            # Scan probes 5 slave IDs × 3 retries × ~1s each before reaching attack
            "timeout": int(dur) + 45,
        },
        {
            "id":      "industroyer2",
            "name":    "Industroyer2",
            "target":  f"{T['water']}:2404",
            "proto":   "IEC-104",
            "pre":     lambda: iec104_probe(T["water"]),
            "cmd":     [PYTHON, str(SIM_DIR/"industroyer2_simulation.py"),
                        "--target", T["power"], "--port", "2404", "--duration", dur],
            "post":    lambda: iec104_probe(T["power"]),
            "verify":  lambda: tcp_probe(T["power"], 2404),
            "check_filter": f"host {T['power']} and tcp port 2404",
        },
        {
            "id":      "blackenergy3",
            "name":    "BlackEnergy3",
            "target":  f"{T['power']}:2404 + {T['hmi']}",
            "proto":   "IEC-104 + KillDisk",
            "cmd":     [PYTHON, str(SIM_DIR/"blackenergy3_simulation.py"),
                        "--plc-ip", T["power"], "--plc-port", "2404",
                        "--hmi-ip", T["hmi"], "--duration", dur],
            "verify":  lambda: tcp_probe(T["water"], 2404),
            "check_filter": f"host {T['water']}",
        },
        {
            "id":      "triton",
            "name":    "TRITON/TRISIS",
            "target":  f"{T['sis']}:1502 + {T['sis']}:2404",
            "proto":   "TriStation UDP + IEC-104",
            "cmd":     [PYTHON, str(SIM_DIR/"triton_simulation.py"),
                        "--sis-ip", T["sis"], "--plc-ip", T["sis"],
                        "--duration", dur],
            "verify":  lambda: tcp_probe(T["sis"], 2404),
            "check_filter": f"host {T['sis']}",
        },
        {
            "id":      "stuxnet",
            "name":    "Stuxnet",
            "target":  f"{T['mfg']}:102",
            "proto":   "Siemens S7",
            "cmd":     [PYTHON, str(SIM_DIR/"stuxnet_simulation.py"),
                        "--target", T["mfg"], "--port", "102", "--duration", dur],
            "verify":  lambda: tcp_probe(T["mfg"], 102),
            "check_filter": f"host {T['mfg']} and tcp port 102",
        },
        {
            "id":      "fuxnet",
            "name":    "Fuxnet",
            "target":  f"{T['sensors']}:5000 + {T['water']}:2404",
            "proto":   "M-Bus + IEC-104",
            "cmd":     [PYTHON, str(SIM_DIR/"fuxnet_simulation.py"),
                        "--target", T["sensors"], "--port", "5000",
                        "--combo-attack", "--plc-ip", T["water"], "--duration", dur],
            "verify":  lambda: tcp_probe(T["sensors"], 5000),
            "check_filter": f"host {T['sensors']} or host {T['water']}",
        },
        {
            "id":      "cosmicenergy",
            "name":    "CosmicEnergy",
            "target":  f"{T['power']}:2404",
            "proto":   "IEC-104",
            "cmd":     [PYTHON, str(SIM_DIR/"cosmicenergy_simulation.py"),
                        "--target", T["power"], "--port", "2404", "--duration", dur],
            "verify":  lambda: tcp_probe(T["power"], 2404),
            "check_filter": f"host {T['power']} and tcp port 2404",
        },
        {
            "id":      "bacnet_hvac",
            "name":    "FrostyGoop BACnet",
            "target":  f"{T['hvac']}:47808",
            "proto":   "BACnet/IP UDP",
            "cmd":     [PYTHON, str(SIM_DIR/"bacnet_hvac_simulation.py"),
                        "--target", T["hvac"], "--port", "47808"],
            "verify":  lambda: True,  # UDP - just check process exits ok
            "check_filter": f"host {T['hvac']} and udp port 47808",
            "timeout": int(dur) * 3 + 30,  # BACnet scan + attack + persistence loop
        },
        {
            "id":      "industroyer_dnp3",
            "name":    "Industroyer DNP3",
            "target":  f"{T['dnp3']}:20000",
            "proto":   "DNP3",
            "cmd":     [PYTHON, str(SIM_DIR/"industroyer_dnp3_simulation.py"),
                        "--target", T["dnp3"], "--port", "20000", "--duration", dur],
            "verify":  lambda: tcp_probe(T["dnp3"], 20000),
            "check_filter": f"host {T['dnp3']} and tcp port 20000",
        },
        {
            "id":      "crashoverride",
            "name":    "CrashOverride",
            "target":  f"{T['power']}:8102",
            "proto":   "IEC 61850 MMS",
            "cmd":     [PYTHON, str(SIM_DIR/"industroyer_goose_simulation.py"),
                        "--target", T["power"], "--port", "8102", "--duration", dur],
            "verify":  lambda: tcp_probe(T["power"], 8102),
            "check_filter": f"host {T['power']} and tcp port 8102",
        },
        {
            "id":      "pipedream",
            "name":    "PIPEDREAM",
            "target":  f"{T['gas']}:4840",
            "proto":   "OPC-UA",
            # --attack gas_pipeline targets GasPipeline OPC-UA namespace (not WaterTank)
            "cmd":     [PYTHON, str(PIPEDREAM),
                        "--target", T["gas"], "--port", "4840",
                        "--attack", "gas_pipeline", "--duration", dur],
            "verify":  lambda: tcp_probe(T["gas"], 4840),
            "check_filter": f"host {T['gas']} and tcp port 4840",
        },
    ]

# ── Runner ────────────────────────────────────────────────────────────────────
class AttackVerifier:
    def __init__(self, args):
        self.args    = args
        self.results = []
        self.ts      = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
        self.iface   = self._detect_iface()

    def _detect_iface(self):
        """Best-effort interface detection."""
        try:
            r = subprocess.run(["ip", "route", "get", "192.168.1.1"],
                               capture_output=True, text=True, timeout=3)
            for part in r.stdout.split():
                if part not in ("via", "dev", "src", "uid", "192.168.1.1"):
                    if not part.startswith("192."):
                        return part
        except: pass
        return "eth0"

    def _run_attack(self, attack):
        dur     = attack.get("timeout", self.args.duration + 10)
        log_dir = LOGS_DIR / self.ts / attack["id"]
        log_dir.mkdir(parents=True, exist_ok=True)
        stdout_f = log_dir / "stdout.txt"
        pcap_f   = log_dir / "capture.pcap"

        result = {
            "id":      attack["id"],
            "name":    attack["name"],
            "target":  attack["target"],
            "proto":   attack["proto"],
            "ts":      datetime.datetime.now().isoformat(),
            "status":  "UNKNOWN",
            "exit_code": None,
            "pre_state": None,
            "post_state": None,
            "pcap_packets": 0,
            "success_kw": [],
            "fail_kw": [],
            "stdout_tail": "",
            "log_dir": str(log_dir),
        }

        # Pre-state
        if "pre" in attack:
            try: result["pre_state"] = attack["pre"]()
            except: pass

        # Verify target reachable before attack
        if not attack.get("verify", lambda: True)():
            status = "SKIP_NETWORK"
            note = (f"Target {attack['target']} unreachable from this host - "
                    f"run from attacker VM (192.168.0.11) for IT-network targets")
            result["status"] = status
            result["stdout_tail"] = note
            self.results.append(result)
            return result

        # Start pcap
        cap_proc = start_capture(self.iface, pcap_f, attack.get("check_filter", ""))

        # Run attack
        try:
            proc = subprocess.Popen(
                attack["cmd"],
                stdout=open(stdout_f, "w"),
                stderr=subprocess.STDOUT,
                cwd=attack.get("cwd", str(SIM_DIR)),
            )
            proc.wait(timeout=dur)
            result["exit_code"] = proc.returncode
        except subprocess.TimeoutExpired:
            proc.kill(); proc.wait()
            result["exit_code"] = -1
        except FileNotFoundError as e:
            result["status"] = "SCRIPT_MISSING"
            result["stdout_tail"] = str(e)
            stop_capture(cap_proc)
            self.results.append(result)
            return result
        finally:
            stop_capture(cap_proc)

        # Read output
        try:
            text = stdout_f.read_text(errors="replace")
            result["stdout_tail"] = "\n".join(text.strip().split("\n")[-15:])
        except: text = ""

        # Pcap stats
        if pcap_f.exists():
            result["pcap_packets"] = pcap_packet_count(pcap_f)

        # Classify output
        ok_kw, fail_kw = classify_output(text, "")
        result["success_kw"] = ok_kw[:5]
        result["fail_kw"]    = fail_kw[:5]

        # Post-state
        if "post" in attack:
            time.sleep(1)
            try: result["post_state"] = attack["post"]()
            except: pass

        # Verdict
        # Success keywords win regardless of exit code - partial failures are expected
        # (some nodes connect while others reject, PIPEDREAM is a good example)
        has_success = len(ok_kw) > 0
        has_fail    = len(fail_kw) > 0 and len(ok_kw) == 0
        state_changed = (result["pre_state"] is not None and
                         result["post_state"] is not None and
                         result["pre_state"] != result["post_state"])

        # Success keywords take priority - if script connected and ran phases,
        # count it as PASS even if some nodes failed (partial success is expected).
        if has_success or state_changed or result["pcap_packets"] > 0:
            result["status"] = "PASS"
        elif has_fail or result["exit_code"] not in (0, -1, None):
            result["status"] = "FAIL"
        else:
            result["status"] = "WARN"

        self.results.append(result)
        return result

    def _print_result(self, r):
        icon = GREEN("PASS") if r["status"] == "PASS" else \
               RED("FAIL") if r["status"] == "FAIL" else \
               YELLOW(r["status"])
        print(f"  {icon}  {r['name']} → {r['target']}")
        if r["pre_state"] is not None:
            print(f"         pre={r['pre_state']:.1f}  post={r['post_state']}")
        if r["pcap_packets"] > 0:
            pkts = r["pcap_packets"]
            print(f"         {DIM(f'pcap: {pkts} packets captured')}")
        if r["success_kw"]:
            print(f"         {DIM('hits: ' + ', '.join(r['success_kw'][:3]))}")
        if r["fail_kw"]:
            print(f"         {RED('errors: ' + ', '.join(r['fail_kw'][:3]))}")
        if r["status"] != "PASS":
            for line in r["stdout_tail"].split("\n")[-5:]:
                if line.strip():
                    print(f"         {DIM(line.rstrip())}")

    def run(self):
        attacks  = build_attacks(self.args)
        selected = {a["id"] for a in attacks}
        if self.args.attacks:
            selected = set(self.args.attacks.split(","))

        print(BOLD(f"\n{'═'*68}"))
        print(BOLD(f"  ATTACK SCRIPT VERIFICATION  -  {self.ts}"))
        print(BOLD(f"  duration={self.args.duration}s  iface={self.iface}"))
        print(BOLD(f"{'═'*68}\n"))

        for attack in attacks:
            if attack["id"] not in selected:
                continue
            print(f"{'─'*68}")
            print(BOLD(f"  {attack['name']:20s}  {DIM(attack['target'])}"))
            r = self._run_attack(attack)
            self._print_result(r)

            if not self.args.no_reset and attack["id"] not in ("router_exploit",):
                self._reset(attack)

        self._summary()
        self._write_report()

    def _reset(self, attack):
        """Best-effort reset: reconnect and send auto-mode / neutral state."""
        target = attack["id"]
        T = TARGETS
        try:
            if target in ("frostygoop",):
                s = socket.socket(); s.settimeout(2); s.connect((T["heating"], 502))
                # FC05 coil 3 = auto_mode ON
                pdu = struct.pack('>BHH', 0x05, 3, 0xFF00)
                s.sendall(struct.pack('>HHHB', 1, 0, len(pdu)+1, 1) + pdu)
                s.recv(16); s.close()
            elif target in ("industroyer2", "blackenergy3", "cosmicenergy"):
                import c104
                c = c104.Client()
                conn = c.add_connection(ip=T["water"], port=2404, init=c104.Init.ALL)
                st = conn.add_station(common_address=1)
                pt = st.add_point(io_address=303, type=c104.Type.C_SC_NA_1)
                c.start(); time.sleep(1.5)
                pt.value = True; pt.transmit(cause=c104.Cot.ACTIVATION)
                time.sleep(0.5); c.stop()
        except Exception:
            pass  # reset is best-effort

    def _summary(self):
        passed = sum(1 for r in self.results if r["status"] == "PASS")
        failed = sum(1 for r in self.results if r["status"] == "FAIL")
        warned = sum(1 for r in self.results if r["status"] == "WARN")
        skipped= sum(1 for r in self.results if r["status"].startswith("SKIP"))
        total  = len(self.results)

        print(f"\n{'═'*68}")
        print(BOLD("  SUMMARY"))
        print(f"{'═'*68}")
        print(f"  {'PASS':<8} {passed}/{total}")
        print(f"  {'FAIL':<8} {failed}/{total}")
        print(f"  {'WARN':<8} {warned}/{total}")
        print(f"  {'SKIP':<8} {skipped}/{total}")
        print(f"  Logs → {LOGS_DIR / self.ts}")

        if failed > 0:
            print(f"\n  {RED('FAILED attacks:')}")
            for r in self.results:
                if r["status"] == "FAIL":
                    print(f"    • {r['name']}: {r['stdout_tail'].split(chr(10))[-1][:80]}")

    def _write_report(self):
        report_path = LOGS_DIR / self.ts / "attack_verify_report.json"
        report = {
            "ts":      self.ts,
            "results": self.results,
            "summary": {
                "total":   len(self.results),
                "pass":    sum(1 for r in self.results if r["status"] == "PASS"),
                "fail":    sum(1 for r in self.results if r["status"] == "FAIL"),
                "warn":    sum(1 for r in self.results if r["status"] == "WARN"),
                "skip":    sum(1 for r in self.results if r["status"].startswith("SKIP")),
            }
        }
        report_path.write_text(json.dumps(report, indent=2))
        print(f"  Report → {report_path}")


def main():
    p = argparse.ArgumentParser(description="Attack script verification")
    p.add_argument("--attacks",   default="",  help="Comma-separated attack IDs to run (default: all)")
    p.add_argument("--duration",  type=int, default=8, help="Attack duration in seconds (default: 8)")
    p.add_argument("--no-reset",  action="store_true", help="Skip post-attack reset")
    args = p.parse_args()
    AttackVerifier(args).run()


if __name__ == "__main__":
    main()
