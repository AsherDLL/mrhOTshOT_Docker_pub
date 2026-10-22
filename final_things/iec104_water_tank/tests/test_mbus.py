#!/usr/bin/env python3
"""
M-Bus unit + integration tests.

Unit tests: mbus_lib frame building and parsing - no network needed.
Integration tests: live PLC-9 (192.168.1.18:5000) - requires network.

Run all:          python3 tests/test_mbus.py
Unit tests only:  python3 tests/test_mbus.py --unit
Integration only: python3 tests/test_mbus.py --integration --host 192.168.1.18
"""

import sys
import os
import socket
import struct
import argparse
import subprocess
import time
import unittest

try:
    import pytest
    _integration = pytest.mark.integration
except ImportError:                       # standalone `python3 tests/test_mbus.py`
    def _integration(cls):
        return cls

# Make server/ importable
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'server'))
from mbus_lib import (
    ACK, LONG, SHORT, STOP, BROADCAST,
    C_SND_NKE, C_REQ_UD2, C_REQ_UD2B, C_SND_UD, C_RSP_UD,
    VIF_VOLUME, VIF_PRESSURE, VIF_TEMP, VIF_FLOW,
    CI_RSP_VAR,
    short_frame, build_rsp_ud, encode_record,
    MBusFrame, MBusClient, _cs,
)

TARGET_HOST = '192.168.1.18'
TARGET_PORT = 5000

# The broadcast-reset test bricks the gateway, and that is irreversible over M-Bus by
# design: mbus_adapter._trigger_offline() sets state = 'OFFLINE' with no path back
# (Fuxnet semantics - the brick is the point). Restarting the target container is the
# only recovery, so the test does it instead of printing an instruction nobody reads.
_SENSORS_SERVICE = 'plc-sensors'


def _sensors_container():
    """Container id of the M-Bus target, found by its compose service label so this
    does not depend on what the compose project happens to be named."""
    try:
        r = subprocess.run(
            ['docker', 'ps', '-q', '--filter',
             f'label=com.docker.compose.service={_SENSORS_SERVICE}'],
            capture_output=True, text=True, timeout=10)
        lines = r.stdout.strip().splitlines()
        return lines[0] if lines else None
    except Exception:
        return None


def _restart_sensors(container_id, host=TARGET_HOST, port=TARGET_PORT, wait=40):
    """Restart the target and block until the gateway answers a ping again, so the
    next test (or the next `make test-int`) does not race the restart."""
    subprocess.run(['docker', 'restart', container_id],
                   capture_output=True, timeout=60)
    deadline = time.time() + wait
    while time.time() < deadline:
        try:
            with MBusClient(host, port, timeout=2) as m:
                if m.ping(1):
                    return True
        except Exception:
            pass
        time.sleep(1)
    return False


# ─────────────────────────────────────────────────────────────────────────────
# Unit tests - no network
# ─────────────────────────────────────────────────────────────────────────────

class TestChecksum(unittest.TestCase):
    def test_snd_nke_addr1(self):
        # SND_NKE addr=1: C=0x40, A=0x01, CS=(0x40+0x01)&0xFF=0x41
        frame = short_frame(C_SND_NKE, 1)
        self.assertEqual(frame, bytes([0x10, 0x40, 0x01, 0x41, 0x16]))

    def test_snd_nke_broadcast(self):
        # SND_NKE addr=0xFF: CS=(0x40+0xFF)&0xFF=0x3F
        frame = short_frame(C_SND_NKE, BROADCAST)
        self.assertEqual(frame, bytes([0x10, 0x40, 0xFF, 0x3F, 0x16]))
        # This is exactly the HMI "Reset Gateway" frame
        self.assertEqual(frame[2], 0xFF)

    def test_req_ud2b_addr1(self):
        # REQ_UD2B addr=1: C=0x7B, A=0x01, CS=(0x7B+0x01)&0xFF=0x7C
        frame = short_frame(C_REQ_UD2B, 1)
        self.assertEqual(frame, bytes([0x10, 0x7B, 0x01, 0x7C, 0x16]))


class TestEncodeRecord(unittest.TestCase):
    def test_32bit_volume(self):
        # Volume 500L → int(500*10)=5000, packed as <I
        rec = encode_record(0x04, VIF_VOLUME, 5000, 4)
        self.assertEqual(rec[0], 0x04)          # DIF
        self.assertEqual(rec[1], VIF_VOLUME)    # VIF
        self.assertEqual(struct.unpack('<I', rec[2:])[0], 5000)

    def test_16bit_temperature(self):
        # Temp 20.0°C → int(20.0*100)=2000, packed as <H
        rec = encode_record(0x02, VIF_TEMP, int(20.0 * 100), 2)
        self.assertEqual(rec[0], 0x02)
        self.assertEqual(rec[1], VIF_TEMP)
        self.assertEqual(struct.unpack('<H', rec[2:])[0], 2000)

    def test_negative_temp_wraps(self):
        # Temp -40°C → int(-40*100)=-4000 & 0xFFFF=61536
        raw = int(-40.0 * 100) & 0xFFFF
        rec = encode_record(0x02, VIF_TEMP, raw, 2)
        decoded = struct.unpack('<h', rec[2:])[0]  # signed
        self.assertAlmostEqual(decoded / 100.0, -40.0)


class TestBuildRspUd(unittest.TestCase):
    def _make_frame(self, vol=500.0, pres=1.5, temp=20.0, flow=0.0):
        records  = encode_record(0x04, VIF_VOLUME,   int(vol  * 10),           4)
        records += encode_record(0x04, VIF_PRESSURE, int(pres * 1000),         4)
        records += encode_record(0x02, VIF_TEMP,     int(temp * 100) & 0xFFFF, 2)
        records += encode_record(0x02, VIF_FLOW,     int(flow * 3600) & 0xFFFF, 2)
        return build_rsp_ud(1, records)

    def test_frame_structure(self):
        frame = self._make_frame()
        self.assertEqual(frame[0], LONG,         "start byte 0x68")
        self.assertEqual(frame[1], frame[2],     "length repeated")
        self.assertEqual(frame[3], LONG,         "start byte repeated")
        self.assertEqual(frame[4], C_RSP_UD,     "C-field RSP_UD=0x08")
        self.assertEqual(frame[5], 1,            "address=1")
        self.assertEqual(frame[6], CI_RSP_VAR,   "CI=0x72 variable data")
        self.assertEqual(frame[-1], STOP,         "stop byte 0x16")

    def test_checksum_valid(self):
        frame = self._make_frame()
        # CS = sum(C + A + payload) & 0xFF
        frame_len = frame[1]
        payload_bytes = frame[4:-2]  # C through last data byte
        expected_cs = sum(payload_bytes) & 0xFF
        actual_cs   = frame[-2]
        self.assertEqual(actual_cs, expected_cs)

    def test_minimum_length(self):
        frame = self._make_frame()
        # [0x68][L][L][0x68][C][A][CI][fh=12][4 records][CS][0x16]
        # = 4 + 2 + 1 + 12 + (6+6+4+4) + 2 = 41
        self.assertGreaterEqual(len(frame), 30)


class TestMBusFrameParsing(unittest.TestCase):
    def _frame_for(self, vol, pres, temp, flow):
        records  = encode_record(0x04, VIF_VOLUME,   int(vol  * 10),           4)
        records += encode_record(0x04, VIF_PRESSURE, int(pres * 1000),         4)
        records += encode_record(0x02, VIF_TEMP,     int(temp * 100) & 0xFFFF, 2)
        records += encode_record(0x02, VIF_FLOW,     int(flow * 3600) & 0xFFFF, 2)
        return build_rsp_ud(1, records)

    def test_parse_valid(self):
        raw   = self._frame_for(500.0, 1.5, 20.0, 0.0)
        frame = MBusFrame(raw)
        self.assertTrue(frame.valid)
        self.assertFalse(frame.is_ack)
        self.assertEqual(len(frame.records), 4)

    def test_parse_volume(self):
        raw   = self._frame_for(500.0, 1.5, 20.0, 0.0)
        frame = MBusFrame(raw)
        vol_rec = next(r for r in frame.records if r.name == 'Volume')
        self.assertAlmostEqual(vol_rec.value, 500.0, places=0)

    def test_parse_pressure(self):
        raw   = self._frame_for(500.0, 2.5, 20.0, 0.0)
        frame = MBusFrame(raw)
        pres_rec = next(r for r in frame.records if r.name == 'Pressure')
        self.assertAlmostEqual(pres_rec.value, 2.5, places=2)

    def test_parse_temperature(self):
        raw   = self._frame_for(500.0, 1.5, 23.5, 0.0)
        frame = MBusFrame(raw)
        temp_rec = next(r for r in frame.records if r.name == 'Temperature')
        self.assertAlmostEqual(temp_rec.value, 23.5, places=1)

    def test_parse_ack(self):
        frame = MBusFrame(bytes([ACK]))
        self.assertTrue(frame.valid)
        self.assertTrue(frame.is_ack)
        self.assertEqual(len(frame.records), 0)

    def test_parse_empty(self):
        frame = MBusFrame(b'')
        self.assertFalse(frame.valid)

    def test_parse_garbage(self):
        frame = MBusFrame(bytes([0xFF, 0xFE, 0xFD]))
        self.assertFalse(frame.valid)

    def test_corrupted_values(self):
        # Simulate CORRUPTED state (vol=99999.9, temp=-40)
        raw   = self._frame_for(99999.9, 0.0, -40.0, 0.0)
        frame = MBusFrame(raw)
        self.assertTrue(frame.valid)
        temp_rec = next(r for r in frame.records if r.name == 'Temperature')
        self.assertAlmostEqual(temp_rec.value, -40.0, places=0)


# ─────────────────────────────────────────────────────────────────────────────
# Integration tests - requires live PLC-9
# ─────────────────────────────────────────────────────────────────────────────

@_integration
class TestMBusIntegration(unittest.TestCase):
    """Live tests against PLC-9 M-Bus server (192.168.1.18:5000).

    Marked `integration`: these need the lab up, so `make test` deselects them and
    `make test-int` runs them - which is what the Makefile already promised.
    """

    HOST = TARGET_HOST
    PORT = TARGET_PORT

    def _can_connect(self):
        try:
            s = socket.create_connection((self.HOST, self.PORT), timeout=2)
            s.close()
            return True
        except Exception:
            return False

    def setUp(self):
        if not self._can_connect():
            self.skipTest(f"PLC-9 unreachable at {self.HOST}:{self.PORT}")

    def test_ping_addr1(self):
        with MBusClient(self.HOST, self.PORT) as m:
            ok = m.ping(1)
        self.assertTrue(ok, "SND_NKE addr=1 should return ACK")

    def test_read_addr1_valid(self):
        with MBusClient(self.HOST, self.PORT) as m:
            m.ping(1)
            frame = m.read(1)
        self.assertIsNotNone(frame, "REQ_UD2 should return a frame")
        self.assertTrue(frame.valid, "frame should be valid")
        self.assertGreater(len(frame.records), 0, "frame should have records")

    def test_read_returns_temperature(self):
        with MBusClient(self.HOST, self.PORT) as m:
            m.ping(1)
            frame = m.read(1)
        names = [r.name for r in frame.records]
        self.assertIn('Temperature', names, f"expected Temperature in {names}")
        temp = next(r for r in frame.records if r.name == 'Temperature')
        self.assertGreater(temp.value, -50, "temperature sanity check > -50°C")
        self.assertLess(temp.value, 100,  "temperature sanity check < 100°C")

    def test_read_returns_pressure(self):
        with MBusClient(self.HOST, self.PORT) as m:
            m.ping(1)
            frame = m.read(1)
        pres = next((r for r in frame.records if r.name == 'Pressure'), None)
        self.assertIsNotNone(pres, "Pressure record expected")
        self.assertGreater(pres.value, 0, "pressure > 0 bar")

    def test_z_broadcast_reset_takes_offline(self):
        """SND_NKE addr=0xFF must take the gateway offline.

        Destructive and irreversible over the protocol, so it restarts the target on
        cleanup and refuses to run when it cannot. Leaving the gateway bricked used to
        fail every one of this class's other tests on the next run, which looked like a
        regression and was really just this test's litter.
        """
        container = _sensors_container()
        if not container:
            self.skipTest("no docker target to restart afterwards - refusing to brick "
                          "the gateway with no way to recover it")
        self.addCleanup(self._restore_gateway, container)

        # Confirm online first
        with MBusClient(self.HOST, self.PORT) as m:
            ok = m.ping(1)
        self.assertTrue(ok, "gateway must be online before test")

        # Send broadcast reset
        with MBusClient(self.HOST, self.PORT) as m:
            m.reset_broadcast()

        import time; time.sleep(0.5)

        # Now ping should fail (server OFFLINE - drops connection or no ACK)
        try:
            with MBusClient(self.HOST, self.PORT, timeout=2) as m:
                ok = m.ping(1)
            offline = not ok
        except Exception:
            offline = True

        self.assertTrue(offline,
            "After broadcast reset, gateway should be OFFLINE (no ACK to SND_NKE)")

    def _restore_gateway(self, container):
        """Cleanup: bring the bricked gateway back so the suite is repeatable."""
        if not _restart_sensors(container):
            raise AssertionError(
                "M-Bus gateway did not come back after restarting the target - the lab "
                "is left bricked and later runs of this class will fail")


# ─────────────────────────────────────────────────────────────────────────────
# Runner
# ─────────────────────────────────────────────────────────────────────────────

if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--unit',        action='store_true', help='Unit tests only')
    parser.add_argument('--integration', action='store_true', help='Integration tests only')
    parser.add_argument('--host',        default=TARGET_HOST, help='M-Bus gateway IP')
    parser.add_argument('--port',        type=int, default=TARGET_PORT)
    args, remaining = parser.parse_known_args()

    TestMBusIntegration.HOST = args.host
    TestMBusIntegration.PORT = args.port

    loader = unittest.TestLoader()
    suite  = unittest.TestSuite()

    if args.integration and not args.unit:
        suite.addTests(loader.loadTestsFromTestCase(TestMBusIntegration))
    elif args.unit and not args.integration:
        for cls in [TestChecksum, TestEncodeRecord, TestBuildRspUd, TestMBusFrameParsing]:
            suite.addTests(loader.loadTestsFromTestCase(cls))
    else:
        for cls in [TestChecksum, TestEncodeRecord, TestBuildRspUd,
                    TestMBusFrameParsing, TestMBusIntegration]:
            suite.addTests(loader.loadTestsFromTestCase(cls))

    runner = unittest.TextTestRunner(verbosity=2)
    result = runner.run(suite)
    sys.exit(0 if result.wasSuccessful() else 1)
