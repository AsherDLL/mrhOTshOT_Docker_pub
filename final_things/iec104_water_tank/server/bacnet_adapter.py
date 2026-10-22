"""
BACnet/IP Adapter using bacpypes3 in BBMD mode.

BBMD mode (address with /mask) handles:
- Register-Foreign-Device (0x05) from clients like DeviceXplorer
- WhoIs/IAm discovery
- ReadProperty / ReadPropertyMultiple
- WriteProperty

Install: pip install bacpypes3
"""

import asyncio
import threading
import time
import logging
from typing import Dict, Any

from bacpypes3.ipv4.app import BBMDApplication
from bacpypes3.pdu import IPv4Address
from bacpypes3.local.device import DeviceObject
from bacpypes3.local.analog import AnalogInputObject, AnalogOutputObject
from bacpypes3.local.binary import BinaryInputObject, BinaryOutputObject
from bacpypes3.primitivedata import Real, Boolean
from bacpypes3.basetypes import EngineeringUnits, BinaryPV

from server.protocol_adapter import (
    ProtocolAdapter, DataPoint, DataPointType,
    WaterTankProtocolMapper
)

OBJ_ANALOG_INPUT  = 0
OBJ_ANALOG_OUTPUT = 1
OBJ_BINARY_INPUT  = 3
OBJ_BINARY_OUTPUT = 4


class BACnetAdapter(ProtocolAdapter):
    """
    BACnet/IP adapter using bacpypes3 BBMD mode.

    BBMD mode is enabled by passing the local IP with a network mask
    (e.g. "192.168.1.14/24") to Application.from_object_list().
    This causes bacpypes3 to use BIPBBMD instead of BIPSimple, which
    responds correctly to Register-Foreign-Device (BVLC 0x05) from
    clients like ICONICS DeviceXplorer.
    """

    DEVICE_INSTANCE = 1000
    DEVICE_NAME     = "AS-P DDC Controller"
    VENDOR_NAME     = "Schneider Electric"
    VENDOR_ID       = 10
    MODEL_NAME      = "SmartStruxure AS-P"

    def __init__(self, water_tank, config: Dict[str, Any]):
        super().__init__(water_tank, config)
        self.host = config.get('host', '0.0.0.0')
        self.port = config.get('port', 47808)

        self._app           = None
        self._loop          = None
        self._loop_thread   = None
        self._update_thread = None

        self._bacnet_objs: Dict[tuple, Any] = {}
        self.name_to_obj:  Dict[str, tuple] = {}

        self._create_address_mapping()

    # ------------------------------------------------------------------
    # Address mapping
    # ------------------------------------------------------------------

    def _create_address_mapping(self):
        """
        Map all data points to AnalogInput (read-only) or AnalogOutput (writable).

        DeviceXplorer's BACnet driver addresses all objects as AnalogInput regardless
        of the BACnet object type specified in the tag - BinaryInput/BinaryOutput objects
        are not resolved correctly. Using only AI/AO ensures all tags connect properly:
          AnalogInput  0-11: measurements + status/alarm booleans (as 0.0/1.0)
          AnalogOutput 0-6 : setpoints + command booleans (as 0.0/1.0)
        """
        data_points = WaterTankProtocolMapper.create_data_points()
        ai = ao = 0

        for name, defn in data_points.items():
            pt    = defn['type']
            label = name.replace('_', ' ').title()

            if pt in (DataPointType.SCALED_VALUE, DataPointType.ANALOG_INPUT,
                      DataPointType.DIGITAL_INPUT):
                # Measurements and boolean status → AnalogInput (booleans as 0.0/1.0)
                self.name_to_obj[name] = (OBJ_ANALOG_INPUT, ai)
                dp = DataPoint(address={'type': OBJ_ANALOG_INPUT, 'instance': ai},
                               point_type=pt, name=name, description=defn['description'],
                               min_value=defn.get('min', 0.0), max_value=defn.get('max', 1.0))
                ai += 1

            elif pt in (DataPointType.DIGITAL_OUTPUT, DataPointType.ANALOG_OUTPUT):
                # Commands and setpoints → AnalogOutput (booleans as 0.0/1.0)
                self.name_to_obj[name] = (OBJ_ANALOG_OUTPUT, ao)
                dp = DataPoint(address={'type': OBJ_ANALOG_OUTPUT, 'instance': ao},
                               point_type=pt, name=name, description=defn['description'],
                               min_value=defn.get('min', 0.0), max_value=defn.get('max', 1.0))
                ao += 1
            else:
                continue

            self.register_data_point(name, dp)
            cb = WaterTankProtocolMapper.get_command_callback(self.water_tank, name)
            if cb:
                self.register_command_callback(name, cb)

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    def initialize(self) -> bool:
        try:
            self._loop = asyncio.new_event_loop()
            self.logger.info(f"BACnet/IP adapter initialised (bacpypes3 BBMD) on port {self.port}")
            return True
        except Exception as e:
            self.logger.error(f"BACnet init failed: {e}")
            return False

    def start(self) -> bool:
        try:
            self.running = True
            self._loop_thread = threading.Thread(
                target=self._run_loop, daemon=True, name="BACnetLoop")
            self._loop_thread.start()

            # Wait for the app to initialise before starting the update loop
            for _ in range(30):
                if self._app is not None:
                    break
                time.sleep(0.2)

            self._update_thread = threading.Thread(
                target=self._update_loop, daemon=True, name="BACnetUpdate")
            self._update_thread.start()

            self.logger.info(f"BACnet/IP device started on UDP port {self.port}")
            return True
        except Exception as e:
            self.logger.error(f"BACnet start failed: {e}")
            self.running = False
            return False

    def stop(self):
        self.running = False
        if self._loop and self._loop.is_running():
            self._loop.call_soon_threadsafe(self._loop.stop)
        if self._loop_thread:
            self._loop_thread.join(timeout=3)
        if self._update_thread:
            self._update_thread.join(timeout=2)
        self.logger.info("BACnet/IP device stopped")

    # ------------------------------------------------------------------
    # Async BACnet application
    # ------------------------------------------------------------------

    def _run_loop(self):
        asyncio.set_event_loop(self._loop)
        self._loop.run_until_complete(self._async_main())

    async def _async_main(self):
        device = DeviceObject(
            objectIdentifier=('device', self.DEVICE_INSTANCE),
            objectName=self.DEVICE_NAME,
            vendorIdentifier=self.VENDOR_ID,
            vendorName=self.VENDOR_NAME,
            modelName=self.MODEL_NAME,
            description='DDC Controller for AHU-1 Air Handling Unit',
            location='Building A, Mechanical Room 3',
            firmwareRevision='V4.2.1',
            applicationSoftwareVersion='HVAC-Controller-v2.3',
        )

        # BBMDApplication uses BIPBBMD link layer which responds to
        # Register-Foreign-Device (BVLC 0x05) - required by DeviceXplorer
        local_ip  = self.host if self.host != '0.0.0.0' else self._get_local_ip()
        addr      = IPv4Address(local_ip, self.port)
        self._app = BBMDApplication(device, addr)

        # Create BACnet objects - all as AnalogInput or AnalogOutput
        for name, dp in self.data_points.items():
            obj_type, instance = self.name_to_obj[name]
            label = name.replace('_', ' ').title()

            if obj_type == OBJ_ANALOG_INPUT:
                obj = AnalogInputObject(
                    objectIdentifier=('analogInput', instance),
                    objectName=label,
                    presentValue=Real(0.0),
                    units=EngineeringUnits('noUnits'),
                    description=dp.description,
                )
            elif obj_type == OBJ_ANALOG_OUTPUT:
                obj = AnalogOutputObject(
                    objectIdentifier=('analogOutput', instance),
                    objectName=label,
                    presentValue=Real(0.0),
                    units=EngineeringUnits('noUnits'),
                    description=dp.description,
                    relinquishDefault=Real(0.0),
                )
            else:
                continue

            self._app.add_object(obj)
            self._bacnet_objs[(obj_type, instance)] = obj

        self.logger.info(f"BACnet BBMD device {self.DEVICE_INSTANCE} live - "
                         f"{len(self._bacnet_objs)} objects on {addr}")

        # Run until stopped
        stop_event = asyncio.Event()
        def _stop():
            stop_event.set()

        self._loop.add_signal_handler = lambda *a, **kw: None  # suppress signal warnings
        while self.running:
            await asyncio.sleep(0.5)

    def _get_local_ip(self) -> str:
        """Discover the local OT interface IP."""
        import socket
        try:
            s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            s.connect(('192.168.1.1', 80))
            ip = s.getsockname()[0]
            s.close()
            return ip
        except Exception:
            return '192.168.1.14'

    # ------------------------------------------------------------------
    # Update loop - water tank → BACnet objects
    # ------------------------------------------------------------------

    def _update_loop(self):
        logged      = False
        _prev_ao    = {}   # name -> last AO presentValue seen; only fire callback on change
        _ao_seeded  = False

        while self.running:
            try:
                if self._app is None:
                    time.sleep(0.5)
                    continue

                # On first pass: seed AO presentValues from actual process state
                # so startup callbacks don't override constructor defaults
                if not _ao_seeded:
                    for name, (obj_type, instance) in self.name_to_obj.items():
                        if obj_type != OBJ_ANALOG_OUTPUT:
                            continue
                        obj = self._bacnet_objs.get((obj_type, instance))
                        if obj is None:
                            continue
                        # Read actual current state via measurement callback
                        # (command names map to status counterparts for init)
                        status_name = name.replace('_command', '_status').replace('_setpoint', '_actual')
                        init_cb = WaterTankProtocolMapper.get_measurement_callback(
                            self.water_tank, status_name)
                        if init_cb:
                            try:
                                init_val = float(init_cb())
                                obj.presentValue = Real(init_val)
                                _prev_ao[name]   = init_val
                            except Exception:
                                _prev_ao[name] = 0.0
                        else:
                            _prev_ao[name] = 0.0
                    _ao_seeded = True

                for name, (obj_type, instance) in self.name_to_obj.items():
                    obj = self._bacnet_objs.get((obj_type, instance))
                    if obj is None:
                        continue

                    if obj_type == OBJ_ANALOG_INPUT:
                        cb = WaterTankProtocolMapper.get_measurement_callback(self.water_tank, name)
                        if cb:
                            obj.presentValue = Real(float(cb()))
                            if not logged:
                                self.logger.info(f"  BACnet [AI/{instance}] {name}")

                    elif obj_type == OBJ_ANALOG_OUTPUT:
                        # Only fire command callback when HMI writes a new value
                        val  = float(obj.presentValue)
                        prev = _prev_ao.get(name)
                        if prev is None or abs(val - prev) > 0.001:
                            _prev_ao[name] = val
                            cb2 = self.command_callbacks.get(name)
                            if cb2:
                                try:
                                    cb2(val)
                                except Exception:
                                    pass

                logged = True
                time.sleep(0.5)

            except Exception as e:
                self.logger.error(f"BACnet update error: {e}")
                import traceback; traceback.print_exc()
                time.sleep(1)

    def update_data_point(self, name: str, value: Any):
        obj_info = self.name_to_obj.get(name)
        if not obj_info:
            return
        obj_type, instance = obj_info
        obj = self._bacnet_objs.get((obj_type, instance))
        if obj is None:
            return
        if obj_type == OBJ_ANALOG_INPUT:
            obj.presentValue = Real(float(value))
