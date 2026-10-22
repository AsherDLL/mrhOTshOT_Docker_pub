#!/usr/bin/env python3
"""
Vehicle CANopen gateway - a simulated automotive CAN node reachable over TCP.

CAN is a bus, not TCP/IP, so this lab tunnels CAN frames over a TCP socket (the same
approach the M-Bus / DNP3 / FINS sims use). Each 11-byte TCP record is one CAN frame:

    struct(">H B", cob_id, dlc) + data.ljust(8, 0x00)

On top of the frames it emulates a CANopen node (node id 1) modelling a moving vehicle:

  Object dictionary (SDO 0x601 -> / 0x581 <-):
    0x2000:0  throttle (commanded)  U8  0-100  RW  <- the wire channel the attack writes
    0x2001:0  brake    (commanded)  U8  0-100  RW
    0x2002:0  speed     U16 RO  (km/h x10)
    0x2003:1/2/3  accelerometer x/y/z  I16 RO  (milli-g)
    0x2004:0  NMT state U8  RO
    0x2005:0  driver throttle U8 RO  <- the real driver's pedal (legit source)
    0x2006:0  driver brake    U8 RO

  NMT (0x000): start 0x01 / stop 0x02 / pre-op 0x80 / reset 0x81.
  TPDO1 (0x181) speed+accel and heartbeat (0x701) are pushed to clients ~5 Hz.

Provenance model (real vs injected): a driver ECU continuously emits the real pedal
value (driver_throttle ~cruise, 0x2005). The commanded channel (0x2000) mirrors the
driver unless an external write is holding it: any SDO write to 0x2000/0x2001 stamps
injected_ts, and for HOLD_S seconds the commanded value holds the injected figure;
after that the driver reclaims the channel. Physics integrates the COMMANDED (applied)
value. So a CAN-injection flood pinning 0x2000=100 overrides the driver and runs the
car away; stop flooding and within HOLD_S the driver value wins and the car slows.

Physics (0.1 s step): accel = 0.03*throttle - 0.05*brake - 0.02*speed.

Usage:  vehicle_canopen_server.py --port 20001
"""
import time
import math
import struct
import socket
import random
import argparse
import threading

NODE = 1
COB_NMT = 0x000
COB_SDO_RX = 0x600 + NODE      # client -> server
COB_SDO_TX = 0x580 + NODE      # server -> client
COB_TPDO1 = 0x180 + NODE
COB_HEARTBEAT = 0x700 + NODE

MG_PER_KMHS = 28.3             # 1 km/h/s ~= 0.0283 g
CRUISE = 40                    # the driver's steady cruise throttle (legit baseline)
HOLD_S = 2.5                   # an external write holds the commanded channel this long


def pack_frame(cob_id, data):
    data = bytes(data)[:8]
    return struct.pack(">HB", cob_id, len(data)) + data.ljust(8, b"\x00")


def unpack_frame(raw):
    cob_id, dlc = struct.unpack(">HB", raw[:3])
    return cob_id, dlc, raw[3:11][:dlc]


class Vehicle:
    def __init__(self):
        self.throttle = CRUISE  # commanded/applied channel (mirrors driver when not injected)
        self.brake = 0
        self.driver_throttle = CRUISE   # the real driver's pedal (legit source)
        self.driver_brake = 0
        self.injected_ts = 0.0  # wall-clock of the last external 0x2000/0x2001 write
        self.speed = 0.0        # km/h
        self.ax = 0             # longitudinal milli-g
        self.ay = 0
        self.az = 1000          # gravity
        self.nmt = 0x7F         # pre-operational
        self.lock = threading.Lock()

    def step(self, dt):
        with self.lock:
            # legit driver: gentle cruise around CRUISE with mild variation (always emitted)
            self.driver_throttle = int(max(30, min(50, CRUISE + 5 * math.sin(time.time() * 0.05)
                                                    + random.uniform(-1, 1))))
            self.driver_brake = 0
            # a fresh external write holds the commanded channel; otherwise the driver reclaims it
            if time.time() - self.injected_ts >= HOLD_S:
                self.throttle = self.driver_throttle
                self.brake = self.driver_brake
            accel = 0.03 * self.throttle - 0.05 * self.brake - 0.02 * self.speed
            self.speed = max(0.0, min(300.0, self.speed + accel * dt))
            self.ax = int(accel * MG_PER_KMHS) + random.randint(-3, 3)
            self.ay = random.randint(-8, 8)
            self.az = 1000 + random.randint(-5, 5)

    def read_od(self, index, sub):
        with self.lock:
            if index == 0x2000:
                return self.throttle, 1
            if index == 0x2001:
                return self.brake, 1
            if index == 0x2002:
                return int(self.speed * 10), 2
            if index == 0x2003:
                return {1: self.ax, 2: self.ay, 3: self.az}.get(sub, 0) & 0xFFFF, 2
            if index == 0x2004:
                return self.nmt, 1
            if index == 0x2005:
                return self.driver_throttle, 1
            if index == 0x2006:
                return self.driver_brake, 1
        return None, 0

    def write_od(self, index, value):
        with self.lock:
            if index == 0x2000:
                self.throttle = max(0, min(100, value)); self.injected_ts = time.time(); return True
            if index == 0x2001:
                self.brake = max(0, min(100, value)); self.injected_ts = time.time(); return True
        return False       # read-only / unknown object


class VehicleCanServer:
    def __init__(self, host="0.0.0.0", port=20001):
        self.host, self.port = host, port
        self.vehicle = Vehicle()
        self.running = False
        self.clients = []
        self.lock = threading.Lock()
        self.sock = None

    # ── CANopen dispatch ──────────────────────────────────────────────────────
    def handle_nmt(self, data):
        cmd, node = data[0], (data[1] if len(data) > 1 else 0)
        if node not in (0, NODE):
            return
        with self.vehicle.lock:
            if cmd == 0x01:
                self.vehicle.nmt = 0x05                     # operational
            elif cmd == 0x02:
                self.vehicle.nmt = 0x04                     # stopped
            elif cmd == 0x80:
                self.vehicle.nmt = 0x7F                     # pre-operational
            elif cmd == 0x81:                               # reset node
                self.vehicle.nmt = 0x00
                self.vehicle.throttle = self.vehicle.brake = 0
                self.vehicle.speed = 0.0
                self.vehicle.driver_throttle = CRUISE       # re-establish the driver's cruise baseline
                self.vehicle.driver_brake = 0
                self.vehicle.injected_ts = 0.0              # clear any held injection

    def handle_sdo(self, data):
        cs = data[0]
        index = data[1] | (data[2] << 8)
        sub = data[3]
        if cs == 0x40:                                      # upload (read)
            val, size = self.vehicle.read_od(index, sub)
            if val is None:
                resp = bytes([0x80, data[1], data[2], sub, 0x00, 0x00, 0x02, 0x06])   # abort: no object
            else:
                scs = {1: 0x4F, 2: 0x4B, 4: 0x43}.get(size, 0x42)
                resp = bytes([scs, data[1], data[2], sub]) + int(val).to_bytes(4, "little")
            return pack_frame(COB_SDO_TX, resp)
        if cs in (0x2F, 0x2B, 0x27, 0x23):                  # download (write)
            n = {0x2F: 1, 0x2B: 2, 0x27: 3, 0x23: 4}[cs]
            value = int.from_bytes(data[4:4 + n], "little")
            ok = self.vehicle.write_od(index, value)
            resp = (bytes([0x60, data[1], data[2], sub, 0, 0, 0, 0]) if ok
                    else bytes([0x80, data[1], data[2], sub, 0x02, 0x00, 0x01, 0x06]))   # abort: read only
            return pack_frame(COB_SDO_TX, resp)
        return None

    # ── networking ────────────────────────────────────────────────────────────
    def start(self):
        self.sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self.sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        self.sock.bind((self.host, self.port))
        self.sock.listen(5)
        self.sock.settimeout(1.0)
        self.running = True
        print("[vehicle-canopen] listening on %s:%d (node %d)" % (self.host, self.port, NODE), flush=True)
        threading.Thread(target=self._sim_loop, daemon=True).start()
        while self.running:
            try:
                client, addr = self.sock.accept()
            except socket.timeout:
                continue
            except OSError:
                break
            threading.Thread(target=self._handle_client, args=(client,), daemon=True).start()

    def _broadcast(self, payload):
        with self.lock:
            dead = []
            for c in self.clients:
                try:
                    c.sendall(payload)
                except OSError:
                    dead.append(c)
            for c in dead:
                self.clients.remove(c)

    def _sim_loop(self):
        tick = 0
        while self.running:
            self.vehicle.step(0.1)
            tick += 1
            if tick % 2 == 0:                               # ~5 Hz TPDO + heartbeat
                spd = int(self.vehicle.speed * 10) & 0xFFFF
                tpdo = pack_frame(COB_TPDO1, struct.pack("<HH", spd, self.vehicle.ax & 0xFFFF))
                hb = pack_frame(COB_HEARTBEAT, bytes([self.vehicle.nmt]))
                self._broadcast(tpdo + hb)
            time.sleep(0.1)

    def _handle_client(self, sock):
        with self.lock:
            self.clients.append(sock)
        sock.settimeout(1.0)
        buf = b""
        try:
            while self.running:
                try:
                    data = sock.recv(1024)
                    if not data:
                        break
                    buf += data
                    while len(buf) >= 11:
                        cob_id, dlc, fdata = unpack_frame(buf[:11])
                        buf = buf[11:]
                        if cob_id == COB_NMT:
                            self.handle_nmt(fdata)
                        elif cob_id == COB_SDO_RX:
                            resp = self.handle_sdo(fdata)
                            if resp:
                                sock.sendall(resp)
                except socket.timeout:
                    continue
                except OSError:
                    break
        finally:
            with self.lock:
                if sock in self.clients:
                    self.clients.remove(sock)
            try:
                sock.close()
            except OSError:
                pass


def selftest():
    assert unpack_frame(pack_frame(0x581, b"\x43\x00\x20\x00\x50\x00\x00\x00"))[0] == 0x581
    v = Vehicle()
    v.injected_ts = 0.0                                     # no fresh injection -> driver drives
    for _ in range(50):
        v.step(0.1)
    assert v.speed > 0                                      # the legit driver accelerates the vehicle
    assert v.write_od(0x2000, 100)                          # inject throttle over CAN
    assert v.read_od(0x2000, 0) == (100, 1)                 # commanded channel shows the injection
    assert v.read_od(0x2005, 0)[0] == v.driver_throttle     # driver (real) value stays separate/clean
    assert not v.write_od(0x2002, 5)                        # speed is read-only
    v.injected_ts -= 10                                     # let the injection go stale (> HOLD_S)
    v.step(0.1)
    assert v.throttle == v.driver_throttle                  # driver reclaimed the commanded channel
    print("[+] selftest passed")
    return 0


def main(argv=None):
    p = argparse.ArgumentParser(description="Vehicle CANopen gateway (CAN over TCP)")
    p.add_argument("--host", default="0.0.0.0")
    p.add_argument("--port", type=int, default=20001)
    p.add_argument("--selftest", action="store_true")
    args = p.parse_args(argv)
    if args.selftest:
        return selftest()
    VehicleCanServer(args.host, args.port).start()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
