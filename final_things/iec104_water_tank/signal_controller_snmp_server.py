#!/usr/bin/env python3
"""
Traffic-signal controller - a real SNMP / NTCIP 1202 agent (UDP 161).

NTCIP (National Transportation Communications for ITS Protocol) is how traffic
signal controllers talk on the wire, and NTCIP rides on SNMP. This emulates an
actuated signal controller (NEMA phases 2 = main street N/S, 4 = cross street
E/W) that cycles green -> yellow -> all-red, and answers real SNMP GET / GETNEXT
/ SET (v1 and v2c, community "public") so net-snmp, nmap and any NMS see it.

Hand-rolled SNMP BER (no dependency), like the other lab targets. Objects:

  MIB-II system (1.3.6.1.2.1.1)      sysDescr / sysObjectID / sysUpTime / ...
  NTCIP 1202 phase status  1.3.6.1.4.1.1206.4.2.1.1.4.1.{2,3,4}.1  greens/yellows/reds
  NTCIP 1202 phase control 1.3.6.1.4.1.1206.4.2.1.1.5.1.4.1        phaseControlGroupHold (RW)

Writing phaseControlGroupHold with two conflicting phases set forces both rings
green at once (the signal-override attack - a compromised controller bypassing
the conflict monitor). Clearing it resumes the normal cycle.

Usage:  signal_controller_snmp_server.py --port 161
"""
import time
import socket
import struct
import argparse
import threading

# ---- BER ------------------------------------------------------------------
def _len(n):
    if n < 0x80:
        return bytes([n])
    b = b""
    while n:
        b = bytes([n & 0xFF]) + b
        n >>= 8
    return bytes([0x80 | len(b)]) + b


def tlv(tag, val):
    return bytes([tag]) + _len(len(val)) + val


def _int_bytes(n):
    if n == 0:
        return b"\x00"
    neg = n < 0
    b = b""
    v = n
    while v not in (0, -1):
        b = bytes([v & 0xFF]) + b
        v >>= 8
    if not neg and (b[0] & 0x80):
        b = b"\x00" + b
    if neg and not (b[0] & 0x80):
        b = b"\xFF" + b
    return b


def _uint_bytes(n):
    if n == 0:
        return b"\x00"
    b = b""
    while n:
        b = bytes([n & 0xFF]) + b
        n >>= 8
    if b[0] & 0x80:
        b = b"\x00" + b
    return b


def enc_int(n):
    return tlv(0x02, _int_bytes(n))


def enc_str(s):
    return tlv(0x04, s if isinstance(s, bytes) else s.encode())


def enc_null():
    return tlv(0x05, b"")


def enc_ticks(n):
    return tlv(0x43, _uint_bytes(n))


def enc_gauge(n):
    return tlv(0x42, _uint_bytes(n))


def oid_body(arcs):
    b = bytearray([40 * arcs[0] + arcs[1]])
    for a in arcs[2:]:
        if a < 128:
            b.append(a)
        else:
            stack = [a & 0x7F]
            a >>= 7
            while a:
                stack.append((a & 0x7F) | 0x80)
                a >>= 7
            b.extend(reversed(stack))
    return bytes(b)


def enc_oid(arcs):
    return tlv(0x06, oid_body(arcs))


def oid_decode(body):
    arcs = [body[0] // 40, body[0] % 40]
    v = 0
    for byte in body[1:]:
        v = (v << 7) | (byte & 0x7F)
        if not (byte & 0x80):
            arcs.append(v)
            v = 0
    return tuple(arcs)


def parse_tlv(buf, off=0):
    tag = buf[off]
    off += 1
    ln = buf[off]
    off += 1
    if ln & 0x80:
        nb = ln & 0x7F
        ln = int.from_bytes(buf[off:off + nb], "big")
        off += nb
    return tag, buf[off:off + ln], off + ln


def enc_value(typ, val):
    return {"int": enc_int, "str": enc_str, "oid": enc_oid,
            "ticks": enc_ticks, "gauge": enc_gauge}[typ](val)


# ---- OIDs -----------------------------------------------------------------
SYS = (1, 3, 6, 1, 2, 1, 1)
NTCIP = (1, 3, 6, 1, 4, 1, 1206, 4, 2, 1)
O_GREENS = NTCIP + (1, 4, 1, 2, 1)
O_YELLOWS = NTCIP + (1, 4, 1, 3, 1)
O_REDS = NTCIP + (1, 4, 1, 4, 1)
O_HOLD = NTCIP + (1, 5, 1, 4, 1)


# ---- signal controller ----------------------------------------------------
class SignalController:
    """NEMA phase 2 = main street (N/S), phase 4 = cross street (E/W)."""
    ORDER = ["main_green", "main_yellow", "all_red_1", "cross_green", "cross_yellow", "all_red_2"]
    DUR = {"main_green": 15, "main_yellow": 3, "all_red_1": 2,
           "cross_green": 12, "cross_yellow": 3, "all_red_2": 2}
    P_MAIN, P_CROSS = 0x02, 0x08                       # phase 2 / phase 4 bit masks

    def __init__(self):
        self.lock = threading.Lock()
        self.phase = "main_green"
        self.timer = 0.0
        self.uptime = 0.0
        self.hold = 0x00                               # phaseControlGroupHold (attack SETs this)

    def step(self, dt):
        with self.lock:
            self.uptime += dt
            if bin(self.hold & (self.P_MAIN | self.P_CROSS)).count("1") >= 2:
                self.phase = "conflict"                # conflicting hold -> both rings green
                return
            if self.phase == "conflict":
                self.phase = "main_green"
                self.timer = 0.0
            self.timer += dt
            if self.timer >= self.DUR.get(self.phase, 5):
                self.timer = 0.0
                self.phase = self.ORDER[(self.ORDER.index(self.phase) + 1) % len(self.ORDER)]

    def greens(self):
        return {"conflict": self.P_MAIN | self.P_CROSS, "main_green": self.P_MAIN,
                "cross_green": self.P_CROSS}.get(self.phase, 0x00)

    def yellows(self):
        return {"main_yellow": self.P_MAIN, "cross_yellow": self.P_CROSS}.get(self.phase, 0x00)

    def reds(self):
        active = self.greens() | self.yellows()
        return (self.P_MAIN | self.P_CROSS) & ~active


# ---- MIB ------------------------------------------------------------------
def build_mib(ctl):
    """Ordered list of (oid_tuple, type, getter, setter|None), sorted by OID."""
    rows = [
        (SYS + (1, 0), "str", lambda: "Econolite Cobalt ASC/3 Traffic Signal Controller - NTCIP 1202 v03", None),
        (SYS + (2, 0), "oid", lambda: NTCIP, None),
        (SYS + (3, 0), "ticks", lambda: int(ctl.uptime * 100), None),
        (SYS + (4, 0), "str", lambda: "traffic.ops@city.example", None),
        (SYS + (5, 0), "str", lambda: "ASC-INT-0042", None),
        (SYS + (6, 0), "str", lambda: "Main St & 1st Ave", None),
        (NTCIP + (1, 1, 0), "int", lambda: 8, None),                       # maxPhases
        (O_GREENS, "str", lambda: bytes([ctl.greens()]), None),
        (O_YELLOWS, "str", lambda: bytes([ctl.yellows()]), None),
        (O_REDS, "str", lambda: bytes([ctl.reds()]), None),
        (O_HOLD, "str", lambda: bytes([ctl.hold]), lambda v: _set_hold(ctl, v)),
    ]
    return sorted(rows, key=lambda r: r[0])


def _set_hold(ctl, v):
    if not v:
        return False
    with ctl.lock:
        ctl.hold = v[0] if isinstance(v, (bytes, bytearray)) else int(v) & 0xFF
    return True


# ---- SNMP server ----------------------------------------------------------
class SnmpAgent:
    def __init__(self, host="0.0.0.0", port=161, community="public"):
        self.host, self.port, self.community = host, port, community
        self.ctl = SignalController()
        self.mib = build_mib(self.ctl)
        self.running = False

    def _get_row(self, oid):
        for row in self.mib:
            if row[0] == oid:
                return row
        return None

    def _next_row(self, oid):
        for row in self.mib:
            if row[0] > oid:
                return row
        return None

    def _varbind(self, oid, typ, val):
        return tlv(0x30, enc_oid(oid) + enc_value(typ, val))

    def handle(self, data):
        try:
            _, body, _ = parse_tlv(data)                       # outer SEQUENCE
            tag, version, off = parse_tlv(body, 0)             # version INTEGER
            ver = int.from_bytes(version, "big")
            tag, comm, off = parse_tlv(body, off)              # community
            ptag, pdu, _ = parse_tlv(body, off)                # PDU
        except Exception:
            return None
        if comm != self.community.encode():
            return None
        # PDU: request-id, error-status, error-index, varbinds
        try:
            _, rid, o = parse_tlv(pdu, 0)
            _, _es, o = parse_tlv(pdu, o)
            _, _ei, o = parse_tlv(pdu, o)
            _, vbl, _ = parse_tlv(pdu, o)                      # varbind-list SEQUENCE
        except Exception:
            return None
        reqs, o = [], 0
        while o < len(vbl):
            _, vb, o = parse_tlv(vbl, o)
            _, name, vo = parse_tlv(vb, 0)
            vtag, vval, _ = parse_tlv(vb, vo)
            reqs.append((oid_decode(name), vtag, vval))

        err_status, err_index, out = 0, 0, b""
        for i, (oid, vtag, vval) in enumerate(reqs, 1):
            if ptag == 0xA0:                                   # GetRequest
                row = self._get_row(oid)
                if row:
                    out += self._varbind(oid, row[1], row[2]())
                elif ver == 0:                                 # v1: noSuchName
                    err_status, err_index = 2, i
                    out = b""
                    break
                else:
                    out += tlv(0x30, enc_oid(oid) + tlv(0x80, b""))   # noSuchObject
            elif ptag == 0xA1:                                 # GetNextRequest
                row = self._next_row(oid)
                if row:
                    out += self._varbind(row[0], row[1], row[2]())
                elif ver == 0:
                    err_status, err_index = 2, i
                    out = b""
                    break
                else:
                    out += tlv(0x30, enc_oid(oid) + tlv(0x82, b""))   # endOfMibView
            elif ptag == 0xA3:                                 # SetRequest
                row = self._get_row(oid)
                if row and row[3]:
                    row[3](vval)
                    out += self._varbind(oid, row[1], row[2]())
                else:
                    err_status, err_index = (4 if row else 2), i   # readOnly / noSuchName
                    out = b""
                    break

        resp_pdu = tlv(0xA2, tlv(0x02, rid) + enc_int(err_status) + enc_int(err_index) + tlv(0x30, out))
        return tlv(0x30, enc_int(ver) + enc_str(self.community) + resp_pdu)

    def _sim_loop(self):
        while self.running:
            self.ctl.step(0.5)
            time.sleep(0.5)

    def start(self):
        self.sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self.sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        self.sock.bind((self.host, self.port))
        self.running = True
        print("[signal-ntcip] SNMP agent on %s:%d/udp (community %s)" % (self.host, self.port, self.community), flush=True)
        threading.Thread(target=self._sim_loop, daemon=True).start()
        while self.running:
            try:
                data, addr = self.sock.recvfrom(4096)
            except OSError:
                break
            resp = self.handle(data)
            if resp:
                try:
                    self.sock.sendto(resp, addr)
                except OSError:
                    pass


def selftest():
    assert oid_decode(oid_body(NTCIP)) == NTCIP
    assert oid_decode(oid_body((1, 3, 6, 1, 2, 1, 1, 1, 0))) == (1, 3, 6, 1, 2, 1, 1, 1, 0)
    assert _int_bytes(8) == b"\x08" and _int_bytes(0) == b"\x00"
    c = SignalController()
    assert c.greens() == 0x02 and c.reds() == 0x08          # main green, cross red
    c.hold = 0x0A
    c.step(0.5)
    assert c.phase == "conflict" and c.greens() == 0x0A     # attack -> both green
    a = SnmpAgent()
    # build a v2c GET for sysDescr and feed it back through handle()
    getpdu = tlv(0xA0, enc_int(1) + enc_int(0) + enc_int(0) + tlv(0x30, tlv(0x30, enc_oid(SYS + (1, 0)) + enc_null())))
    msg = tlv(0x30, enc_int(1) + enc_str("public") + getpdu)
    resp = a.handle(msg)
    assert resp and b"Econolite" in resp
    print("[+] selftest passed")
    return 0


def main(argv=None):
    p = argparse.ArgumentParser(description="Traffic-signal controller (SNMP / NTCIP 1202)")
    p.add_argument("--host", default="0.0.0.0")
    p.add_argument("--port", type=int, default=161)
    p.add_argument("--community", default="public")
    p.add_argument("--selftest", action="store_true")
    args = p.parse_args(argv)
    if args.selftest:
        return selftest()
    SnmpAgent(args.host, args.port, args.community).start()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
