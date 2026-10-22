"""
IEC 61850 / GOOSE Protocol Adapter for Water Tank

Simulates an IEC 61850 MMS server and GOOSE publisher for substation automation.
This is the protocol Industroyer (2016) used to trip circuit breakers in Ukraine.

IEC 61850 Structure:
- Logical Device: WaterTankLD
  - Logical Nodes:
    - MMXU1 (Measurement): water level, pressure, temperature
    - GGIO1 (Generic I/O): valve status, pump status, alarms
    - CSWI1 (Switch Control): valve commands, pump commands
    - PTRC1 (Protection Trip): SIS trip, emergency stop

GOOSE (Generic Object Oriented Substation Event):
- Multicast protocol for fast event distribution
- Used by Industroyer to send fake trip commands
- No authentication in standard implementations

Port: 102 (MMS over TCP) - we use 8102 to avoid conflict with S7
GOOSE: Multicast on Ethernet layer (simulated via TCP for portability)
"""

import threading
import time
import struct
import socket
import json
import logging
from typing import Dict, Any, Optional

from server.protocol_adapter import (
    ProtocolAdapter, DataPoint, DataPointType,
    WaterTankProtocolMapper
)


# IEC 61850 MMS-like protocol constants
MMS_INITIATE_REQUEST = 0xA8
MMS_INITIATE_RESPONSE = 0xA9
MMS_CONFIRMED_REQUEST = 0xA0
MMS_CONFIRMED_RESPONSE = 0xA1
MMS_READ_REQUEST = 0xA4
MMS_WRITE_REQUEST = 0xA5

# GOOSE constants
GOOSE_ETHERTYPE = 0x88B8
GOOSE_APPID_TRIP = 0x0001
GOOSE_APPID_STATUS = 0x0002


def _ref_to_mms_item(ref, ld):
    """IEC 61850 object ref 'LD/MMXU1.PhV.phsA.f' -> MMS item 'MMXU1$MX$PhV$phsA$f'
    (LN $ functional-constraint $ data-object $ data-attribute...)."""
    if not ref.startswith(ld + "/"):
        return None
    parts = ref[len(ld) + 1:].split(".")
    ln, das = parts[0], parts[1:]
    if "Oper" in das and "ctlVal" in das:
        fc = "CO"
    elif "setMag" in das:
        fc = "SP"
    elif das and das[-1] in ("stVal", "general"):
        fc = "ST"
    elif ln.startswith("MMXU"):
        fc = "MX"
    else:
        fc = "ST"
    return ln + "$" + fc + "$" + "$".join(das)


class _MmsProvider:
    """Adapts the adapter's live data model to mms_iso.serve_mms()."""

    def __init__(self, adapter):
        self.ld = adapter.LOGICAL_DEVICE
        self._a = adapter
        self._item2ref = {}
        for ref in adapter.data_attributes:
            item = _ref_to_mms_item(ref, self.ld)
            if item:
                self._item2ref[item] = ref

    def items(self):
        return list(self._item2ref)

    def read(self, item):
        ref = self._item2ref.get(item)
        return None if ref is None else self._a.data_attributes.get(ref)

    def write(self, item, val):
        ref = self._item2ref.get(item)
        if ref is None or val is None:
            return False
        self._a.data_attributes[ref] = val
        name = self._a.ref_to_name.get(ref)
        cb = self._a.command_callbacks.get(name) if name else None
        if cb:
            try:
                cb(val)
            except Exception:
                pass
        self._a.goose_st_num += 1
        return True


class IEC61850Adapter(ProtocolAdapter):
    """
    IEC 61850 protocol adapter

    Implements:
    1. MMS-like TCP server for reading/writing data attributes
    2. GOOSE message simulation for protection events

    IEC 61850 Data Model:
    - WaterTankLD/MMXU1.PhV.phsA.f  -> Water level
    - WaterTankLD/MMXU1.PhV.phsB.f  -> Pressure
    - WaterTankLD/MMXU1.PhV.phsC.f  -> Temperature
    - WaterTankLD/GGIO1.Ind1.stVal  -> Inlet valve status
    - WaterTankLD/GGIO1.Ind2.stVal  -> Outlet valve status
    - WaterTankLD/GGIO1.Ind3.stVal  -> Pump status
    - WaterTankLD/CSWI1.Pos1.Oper  -> Inlet valve command
    - WaterTankLD/CSWI1.Pos2.Oper  -> Outlet valve command
    - WaterTankLD/CSWI1.Pos3.Oper  -> Pump command
    - WaterTankLD/PTRC1.Tr.general  -> Protection trip
    """

    LOGICAL_DEVICE = "WaterTankLD"

    def __init__(self, water_tank, config: Dict[str, Any]):
        super().__init__(water_tank, config)

        self.host = config.get('host', '0.0.0.0')
        self.port = config.get('port', 8102)
        self.goose_port = config.get('goose_port', 61850)

        self.server_socket = None
        self.goose_socket = None
        self.server_thread = None
        self.update_thread = None
        self.goose_thread = None

        # IEC 61850 data model
        self.data_attributes: Dict[str, Any] = {}
        self.goose_sq_num = 0
        self.goose_st_num = 0

        # Mapping from data point names to IEC 61850 references
        self.ref_map: Dict[str, str] = {}
        self.ref_to_name: Dict[str, str] = {}

        self._create_address_mapping()

    def _create_address_mapping(self):
        """Create IEC 61850 data attribute mapping"""
        data_points = WaterTankProtocolMapper.create_data_points()

        # Measurement mapping (MMXU - Measurement)
        measurement_refs = {
            'water_level': f"{self.LOGICAL_DEVICE}/MMXU1.PhV.phsA.f",
            'pressure': f"{self.LOGICAL_DEVICE}/MMXU1.PhV.phsB.f",
            'temperature': f"{self.LOGICAL_DEVICE}/MMXU1.PhV.phsC.f",
        }

        # Status mapping (GGIO - Generic I/O)
        status_refs = {
            'inlet_valve_status': f"{self.LOGICAL_DEVICE}/GGIO1.Ind1.stVal",
            'outlet_valve_status': f"{self.LOGICAL_DEVICE}/GGIO1.Ind2.stVal",
            'pump_status': f"{self.LOGICAL_DEVICE}/GGIO1.Ind3.stVal",
            'auto_mode_status': f"{self.LOGICAL_DEVICE}/GGIO1.Ind4.stVal",
            'alarm_overflow': f"{self.LOGICAL_DEVICE}/GGIO1.Alm1.stVal",
            'alarm_low_level': f"{self.LOGICAL_DEVICE}/GGIO1.Alm2.stVal",
            'alarm_high_pressure': f"{self.LOGICAL_DEVICE}/GGIO1.Alm3.stVal",
            'tank_exploded': f"{self.LOGICAL_DEVICE}/GGIO1.Alm4.stVal",
            'sis_tripped': f"{self.LOGICAL_DEVICE}/PTRC1.Tr.general",
        }

        # Command mapping (CSWI - Switch Controller)
        command_refs = {
            'inlet_valve_command': f"{self.LOGICAL_DEVICE}/CSWI1.Pos1.Oper.ctlVal",
            'outlet_valve_command': f"{self.LOGICAL_DEVICE}/CSWI1.Pos2.Oper.ctlVal",
            'pump_command': f"{self.LOGICAL_DEVICE}/CSWI1.Pos3.Oper.ctlVal",
            'auto_mode_command': f"{self.LOGICAL_DEVICE}/CSWI1.Pos4.Oper.ctlVal",
            'sis_trip_command': f"{self.LOGICAL_DEVICE}/PTRC1.Tr.Oper.ctlVal",
        }

        # Setpoint mapping
        setpoint_refs = {
            'inlet_valve_setpoint': f"{self.LOGICAL_DEVICE}/CSWI1.Pos1.Oper.setMag.f",
            'outlet_valve_setpoint': f"{self.LOGICAL_DEVICE}/CSWI1.Pos2.Oper.setMag.f",
        }

        all_refs = {}
        all_refs.update(measurement_refs)
        all_refs.update(status_refs)
        all_refs.update(command_refs)
        all_refs.update(setpoint_refs)

        for name, ref in all_refs.items():
            definition = data_points.get(name)
            if not definition:
                continue

            point_type = definition['type']
            self.ref_map[name] = ref
            self.ref_to_name[ref] = name

            if point_type in [DataPointType.SCALED_VALUE, DataPointType.ANALOG_INPUT]:
                self.data_attributes[ref] = 0.0
            elif point_type == DataPointType.DIGITAL_INPUT:
                self.data_attributes[ref] = False
            elif point_type == DataPointType.DIGITAL_OUTPUT:
                self.data_attributes[ref] = False
            elif point_type == DataPointType.ANALOG_OUTPUT:
                self.data_attributes[ref] = 0.0

            dp = DataPoint(
                address={'ref': ref},
                point_type=point_type, name=name,
                description=definition['description'],
                min_value=definition.get('min'),
                max_value=definition.get('max')
            )
            self.register_data_point(name, dp)

            callback = WaterTankProtocolMapper.get_command_callback(self.water_tank, name)
            if callback:
                self.register_command_callback(name, callback)

    def initialize(self) -> bool:
        try:
            # MMS TCP server
            self.server_socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            self.server_socket.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            self.server_socket.bind((self.host, self.port))
            self.server_socket.listen(5)
            self.server_socket.settimeout(1.0)

            # GOOSE TCP server (simulated - real GOOSE is Ethernet multicast)
            self.goose_socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            self.goose_socket.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            self.goose_socket.bind((self.host, self.goose_port))
            self.goose_socket.listen(5)
            self.goose_socket.settimeout(1.0)

            self.logger.info(f"IEC 61850 server initialized on {self.host}:{self.port}")
            self.logger.info(f"  GOOSE listener on port {self.goose_port}")
            self.logger.info(f"  Logical Device: {self.LOGICAL_DEVICE}")
            self.logger.info(f"  Data Attributes: {len(self.data_attributes)}")
            return True
        except Exception as e:
            self.logger.error(f"Failed to initialize IEC 61850 server: {e}")
            return False

    def start(self) -> bool:
        try:
            self.running = True

            self.server_thread = threading.Thread(
                target=self._mms_accept_loop, daemon=True, name="IEC61850MmsThread"
            )
            self.server_thread.start()

            self.goose_thread = threading.Thread(
                target=self._goose_accept_loop, daemon=True, name="IEC61850GooseThread"
            )
            self.goose_thread.start()

            self.update_thread = threading.Thread(
                target=self._update_loop, daemon=True, name="IEC61850UpdateThread"
            )
            self.update_thread.start()

            self.logger.info(f"IEC 61850 server started (MMS:{self.port}, GOOSE:{self.goose_port})")
            return True
        except Exception as e:
            self.logger.error(f"Failed to start IEC 61850 server: {e}")
            self.running = False
            return False

    def _mms_accept_loop(self):
        """Accept MMS TCP connections"""
        while self.running:
            try:
                conn, addr = self.server_socket.accept()
                self.logger.info(f"MMS connection from {addr}")
                t = threading.Thread(
                    target=self._handle_mms_connection, args=(conn, addr), daemon=True
                )
                t.start()
            except socket.timeout:
                continue
            except Exception as e:
                if self.running:
                    self.logger.error(f"MMS accept error: {e}")

    def _goose_accept_loop(self):
        """Accept GOOSE TCP connections (simulated multicast)"""
        while self.running:
            try:
                conn, addr = self.goose_socket.accept()
                self.logger.info(f"[GOOSE] Connection from {addr}")
                t = threading.Thread(
                    target=self._handle_goose_connection, args=(conn, addr), daemon=True
                )
                t.start()
            except socket.timeout:
                continue
            except Exception as e:
                if self.running:
                    self.logger.error(f"GOOSE accept error: {e}")

    def _handle_mms_connection(self, conn: socket.socket, addr):
        """Handle an MMS client: real MMS over ISO-TSAP (TPKT/COTP) when the peer
        speaks it, else the JSON stand-in (kept for the console/HMI clients)."""
        conn.settimeout(5.0)
        try:
            first = conn.recv(1, socket.MSG_PEEK)
        except (socket.timeout, OSError):
            first = b""
        if first[:1] == b"\x03":                       # TPKT -> real MMS/ISO-TSAP
            from server import mms_iso
            try:
                mms_iso.serve_mms(conn, _MmsProvider(self),
                                  log=lambda m: self.logger.debug("[MMS] %s" % m))
            except Exception as e:
                self.logger.debug(f"MMS/ISO session error: {e}")
            finally:
                try:
                    conn.close()
                except OSError:
                    pass
            return
        try:
            while self.running:
                try:
                    data = conn.recv(4096)
                    if not data:
                        break
                    try:
                        request = json.loads(data.decode('utf-8', errors='replace'))
                    except (json.JSONDecodeError, UnicodeDecodeError):
                        # Binary MMS - respond with data model as JSON
                        response = json.dumps({
                            'type': 'initiate-response',
                            'logical_device': self.LOGICAL_DEVICE,
                            'data_attributes': {k: str(v) for k, v in self.data_attributes.items()}
                        })
                        conn.sendall(response.encode() + b'\n')
                        continue

                    response = self._process_mms_request(request)
                    conn.sendall(json.dumps(response).encode() + b'\n')
                except socket.timeout:
                    continue
        except Exception as e:
            self.logger.debug(f"MMS connection error: {e}")
        finally:
            conn.close()

    def _process_mms_request(self, request: dict) -> dict:
        """Process MMS request"""
        req_type = request.get('type', '')

        if req_type == 'read':
            ref = request.get('reference', '')
            if ref in self.data_attributes:
                return {
                    'type': 'read-response',
                    'reference': ref,
                    'value': self.data_attributes[ref],
                    'quality': 'good',
                    'timestamp': time.time()
                }
            elif ref == 'all' or ref == '':
                return {
                    'type': 'read-response',
                    'data': {k: {'value': v, 'quality': 'good'}
                             for k, v in self.data_attributes.items()}
                }
            else:
                return {'type': 'error', 'message': f'Unknown reference: {ref}'}

        elif req_type == 'write':
            ref = request.get('reference', '')
            value = request.get('value')
            if ref in self.data_attributes:
                name = self.ref_to_name.get(ref)
                if name:
                    callback = self.command_callbacks.get(name)
                    if callback:
                        self.data_attributes[ref] = value
                        callback(value)
                        self.logger.info(f"[MMS] Write: {ref} = {value}")
                        self.goose_st_num += 1
                        return {'type': 'write-response', 'success': True}
                return {'type': 'error', 'message': 'Not writable'}
            return {'type': 'error', 'message': f'Unknown reference: {ref}'}

        elif req_type == 'goose-trip':
            # Simulate receiving a GOOSE trip command (Industroyer attack vector)
            self.logger.warning(f"[GOOSE TRIP] Received GOOSE trip command!")
            trip_ref = f"{self.LOGICAL_DEVICE}/PTRC1.Tr.Oper.ctlVal"
            self.data_attributes[trip_ref] = True
            name = self.ref_to_name.get(trip_ref, 'sis_trip_command')
            callback = self.command_callbacks.get(name)
            if callback:
                callback(True)
            self.goose_st_num += 1
            return {'type': 'goose-trip-response', 'success': True,
                    'message': 'GOOSE trip executed - breakers opened'}

        elif req_type == 'get-model':
            return {
                'type': 'get-model-response',
                'logical_device': self.LOGICAL_DEVICE,
                'logical_nodes': ['MMXU1', 'GGIO1', 'CSWI1', 'PTRC1'],
                'data_attributes': list(self.data_attributes.keys())
            }

        return {'type': 'error', 'message': f'Unknown request type: {req_type}'}

    def _handle_goose_connection(self, conn: socket.socket, addr):
        """Handle GOOSE subscriber connection - stream GOOSE messages"""
        conn.settimeout(1.0)
        try:
            while self.running:
                goose_msg = self._build_goose_message()
                try:
                    conn.sendall(json.dumps(goose_msg).encode() + b'\n')
                except (BrokenPipeError, ConnectionResetError):
                    break
                time.sleep(1.0)  # GOOSE retransmit interval
        except Exception as e:
            self.logger.debug(f"GOOSE connection error: {e}")
        finally:
            conn.close()

    def _build_goose_message(self) -> dict:
        """Build a GOOSE status message"""
        self.goose_sq_num += 1
        return {
            'type': 'goose',
            'appid': GOOSE_APPID_STATUS,
            'gocbRef': f"{self.LOGICAL_DEVICE}/LLN0$GO$gcb01",
            'datSet': f"{self.LOGICAL_DEVICE}/LLN0$ds01",
            'goID': f"{self.LOGICAL_DEVICE}_Status",
            'stNum': self.goose_st_num,
            'sqNum': self.goose_sq_num,
            'confRev': 1,
            'ndsCom': False,
            'numDatSetEntries': 5,
            'allData': {
                'inlet_valve': self.data_attributes.get(
                    f"{self.LOGICAL_DEVICE}/GGIO1.Ind1.stVal", False),
                'outlet_valve': self.data_attributes.get(
                    f"{self.LOGICAL_DEVICE}/GGIO1.Ind2.stVal", False),
                'pump': self.data_attributes.get(
                    f"{self.LOGICAL_DEVICE}/GGIO1.Ind3.stVal", False),
                'protection_trip': self.data_attributes.get(
                    f"{self.LOGICAL_DEVICE}/PTRC1.Tr.general", False),
                'water_level': self.data_attributes.get(
                    f"{self.LOGICAL_DEVICE}/MMXU1.PhV.phsA.f", 0.0),
            },
            'timestamp': time.time()
        }

    def _update_loop(self):
        """Update IEC 61850 data from water tank"""
        while self.running:
            try:
                for name, ref in self.ref_map.items():
                    callback = WaterTankProtocolMapper.get_measurement_callback(
                        self.water_tank, name
                    )
                    if callback:
                        value = callback()
                        if isinstance(self.data_attributes.get(ref), bool):
                            self.data_attributes[ref] = bool(value)
                        else:
                            self.data_attributes[ref] = float(value)
                time.sleep(0.1)
            except Exception as e:
                self.logger.error(f"IEC 61850 update error: {e}")
                time.sleep(1)

    def stop(self):
        self.running = False
        if self.server_socket:
            self.server_socket.close()
        if self.goose_socket:
            self.goose_socket.close()
        if self.server_thread:
            self.server_thread.join(timeout=2)
        if self.goose_thread:
            self.goose_thread.join(timeout=2)
        if self.update_thread:
            self.update_thread.join(timeout=2)
        self.logger.info("IEC 61850 server stopped")

    def update_data_point(self, name: str, value: Any):
        ref = self.ref_map.get(name)
        if ref:
            self.data_attributes[ref] = value
