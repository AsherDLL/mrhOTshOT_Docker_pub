"""
IEC 60870-5-104 Client Adapter for HMI

Handles communication with IEC-104 water tank server.
"""

import threading
import time
import c104
from typing import Dict
from hmi.protocol_client import ProtocolClient, WaterTankDataPoints

# Import IOA definitions from config
import sys
import os
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from common.config import *


class IEC104Client(ProtocolClient):
    """IEC 60870-5-104 protocol client adapter"""

    # IOA Mapping: data point name -> IOA address
    IOA_MAP = {
        # Measurements
        WaterTankDataPoints.WATER_LEVEL: IOA_WATER_LEVEL,
        WaterTankDataPoints.PRESSURE: IOA_PRESSURE,
        WaterTankDataPoints.TEMPERATURE: IOA_TEMPERATURE,

        # Status
        WaterTankDataPoints.INLET_VALVE_STATUS: IOA_INLET_VALVE_STATUS,
        WaterTankDataPoints.OUTLET_VALVE_STATUS: IOA_OUTLET_VALVE_STATUS,
        WaterTankDataPoints.PUMP_STATUS: IOA_PUMP_STATUS,
        WaterTankDataPoints.AUTO_MODE_STATUS: IOA_AUTO_MODE_STATUS,
        WaterTankDataPoints.OVERFLOW_ALARM: IOA_ALARM_OVERFLOW,
        WaterTankDataPoints.LOW_LEVEL_ALARM: IOA_ALARM_LOW_LEVEL,
        WaterTankDataPoints.HIGH_PRESSURE_ALARM: IOA_ALARM_HIGH_PRESSURE,
        WaterTankDataPoints.TANK_EXPLODED_ALARM: IOA_TANK_EXPLODED,

        # Commands
        WaterTankDataPoints.INLET_VALVE_COMMAND: IOA_INLET_VALVE_COMMAND,
        WaterTankDataPoints.OUTLET_VALVE_COMMAND: IOA_OUTLET_VALVE_COMMAND,
        WaterTankDataPoints.PUMP_COMMAND: IOA_PUMP_COMMAND,
        WaterTankDataPoints.AUTO_MODE_COMMAND: IOA_AUTO_MODE_COMMAND,

        # Setpoints
        WaterTankDataPoints.INLET_VALVE_SETPOINT: IOA_INLET_VALVE_SETPOINT,
        WaterTankDataPoints.OUTLET_VALVE_SETPOINT: IOA_OUTLET_VALVE_SETPOINT,
    }

    def __init__(self, host: str, port: int, config: Dict = None):
        """Initialize IEC-104 client"""
        super().__init__(host, port, config)
        self.common_address = config.get('common_address', COMMON_ADDRESS) if config else COMMON_ADDRESS

        self.client = None
        self.connection = None
        self.station = None
        self.points = {}
        self.monitoring = False
        self.monitor_thread = None

    def connect(self) -> bool:
        """Connect to IEC-104 server"""
        try:
            # Create client
            self.client = c104.Client(tick_rate_ms=100)

            # Add connection
            self.connection = self.client.add_connection(
                ip=self.host,
                port=self.port,
                init=c104.Init.INTERROGATION
            )

            # Set state change callback
            self.connection.on_state_change(callable=self._on_connection_state)

            # Add station
            self.station = self.connection.add_station(common_address=self.common_address)

            # Add all points
            self._setup_points()

            # Start client
            self.client.start()

            # Wait for connection
            timeout = 5
            start_time = time.time()
            while not self.connected and (time.time() - start_time) < timeout:
                time.sleep(0.1)

            return self.connected

        except Exception as e:
            print(f"IEC-104 connection error: {e}")
            return False

    def disconnect(self):
        """Disconnect from IEC-104 server"""
        self.stop_monitoring()

        if self.client:
            self.client.stop()
            self.client = None

        self.connected = False
        self.connection = None
        self.station = None
        self.points = {}

    def send_command(self, command: str, value: bool) -> bool:
        """Send digital command"""
        try:
            ioa = self.IOA_MAP.get(command)
            if not ioa or ioa not in self.points:
                return False

            point = self.points[ioa]
            # Set the value first, then transmit
            point.value = value
            point.transmit(c104.Cot.ACTIVATION)
            return True

        except Exception as e:
            print(f"Failed to send command {command}: {e}")
            return False

    def send_setpoint(self, setpoint: str, value: float) -> bool:
        """Send analog setpoint"""
        try:
            ioa = self.IOA_MAP.get(setpoint)
            if not ioa or ioa not in self.points:
                return False

            point = self.points[ioa]
            # Set the value first, then transmit
            point.value = int(value)
            point.transmit(c104.Cot.ACTIVATION)
            return True

        except Exception as e:
            print(f"Failed to send setpoint {setpoint}: {e}")
            return False

    def start_monitoring(self):
        """Start monitoring data (runs in background)"""
        if not self.monitoring:
            self.monitoring = True
            # IEC-104 client already handles monitoring via callbacks
            # No additional thread needed

    def stop_monitoring(self):
        """Stop monitoring data"""
        self.monitoring = False

    def _setup_points(self):
        """Setup all IEC-104 points"""
        # Measurement points (M_ME_NB_1 - Scaled value)
        for name in WaterTankDataPoints.get_all_measurements():
            ioa = self.IOA_MAP[name]
            pt = self.station.add_point(io_address=ioa, type=c104.Type.M_ME_NB_1)
            # Create a properly typed callback closure
            def make_callback(data_name):
                def callback(point: c104.Point, previous_info: c104.Information, message: c104.IncomingMessage) -> c104.ResponseState:
                    return self._on_receive_point(point, previous_info, message, data_name)
                return callback
            pt.on_receive(callable=make_callback(name))
            self.points[ioa] = pt

        # Status points (M_SP_NA_1 - Single point)
        for name in WaterTankDataPoints.get_all_status():
            ioa = self.IOA_MAP[name]
            pt = self.station.add_point(io_address=ioa, type=c104.Type.M_SP_NA_1)
            # Create a properly typed callback closure
            def make_callback(data_name):
                def callback(point: c104.Point, previous_info: c104.Information, message: c104.IncomingMessage) -> c104.ResponseState:
                    return self._on_receive_point(point, previous_info, message, data_name)
                return callback
            pt.on_receive(callable=make_callback(name))
            self.points[ioa] = pt

        # Command points (C_SC_NA_1 - Single command)
        for name in WaterTankDataPoints.get_all_commands():
            ioa = self.IOA_MAP[name]
            pt = self.station.add_point(io_address=ioa, type=c104.Type.C_SC_NA_1)
            self.points[ioa] = pt

        # Setpoint points (C_SE_NC_1 - Setpoint command)
        for name in WaterTankDataPoints.get_all_setpoints():
            ioa = self.IOA_MAP[name]
            pt = self.station.add_point(io_address=ioa, type=c104.Type.C_SE_NC_1)
            self.points[ioa] = pt

    def _on_connection_state(self, connection: c104.Connection, state: c104.ConnectionState) -> None:
        """Handle connection state changes"""
        if state == c104.ConnectionState.OPEN:
            self.connected = True
        else:
            self.connected = False

    def _on_receive_point(self, point: c104.Point, previous_info: c104.Information, message: c104.IncomingMessage, name: str) -> c104.ResponseState:
        """Handle received point data"""
        try:
            value = point.value
            # Timestamp is on the message, not the point
            timestamp = message.timestamp_ms / 1000.0 if hasattr(message, 'timestamp_ms') and message.timestamp_ms else None

            # Convert to appropriate type
            if name in WaterTankDataPoints.get_all_measurements():
                # Measurements are Int16, scale to float
                if isinstance(value, c104.Int16):
                    # Convert Int16 to int, then scale based on measurement type
                    int_value = int(value)
                    if name == WaterTankDataPoints.WATER_LEVEL:
                        value = (int_value / 32767.0) * 100.0  # 0-100%
                    elif name == WaterTankDataPoints.PRESSURE:
                        value = (int_value / 32767.0) * 10.0  # 0-10 bar
                    elif name == WaterTankDataPoints.TEMPERATURE:
                        value = (int_value / 32767.0) * 100.0  # 0-100°C
            elif name in WaterTankDataPoints.get_all_status():
                # Status are boolean
                value = bool(value)

            # Notify callback
            self._notify_data_update(name, value, timestamp)
            return c104.ResponseState.SUCCESS

        except Exception as e:
            print(f"Error processing point {name}: {e}")
            return c104.ResponseState.FAILURE
