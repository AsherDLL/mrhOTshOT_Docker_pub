"""
Siemens S7 Client Adapter for HMI

Handles communication with S7 water tank server.
"""

import threading
import time
import snap7
from snap7.client import Client
import snap7.util as util
from typing import Dict
from hmi.protocol_client import ProtocolClient, WaterTankDataPoints


class S7Client(ProtocolClient):
    """Siemens S7 protocol client adapter"""

    # Data Block numbers (must match server)
    DB_MEASUREMENTS = 1
    DB_STATUS = 2
    DB_COMMANDS = 3
    DB_SETPOINTS = 4

    # Data point mapping: name -> (DB, offset, type)
    DATA_MAP = {
        # Measurements (DB1, REAL)
        WaterTankDataPoints.WATER_LEVEL: (DB_MEASUREMENTS, 0, 'REAL'),
        WaterTankDataPoints.PRESSURE: (DB_MEASUREMENTS, 4, 'REAL'),
        WaterTankDataPoints.TEMPERATURE: (DB_MEASUREMENTS, 8, 'REAL'),

        # Status (DB2, BOOL - byte.bit)
        WaterTankDataPoints.INLET_VALVE_STATUS: (DB_STATUS, (0, 0), 'BOOL'),
        WaterTankDataPoints.OUTLET_VALVE_STATUS: (DB_STATUS, (0, 1), 'BOOL'),
        WaterTankDataPoints.PUMP_STATUS: (DB_STATUS, (0, 2), 'BOOL'),
        WaterTankDataPoints.AUTO_MODE_STATUS: (DB_STATUS, (0, 3), 'BOOL'),
        WaterTankDataPoints.OVERFLOW_ALARM: (DB_STATUS, (0, 4), 'BOOL'),
        WaterTankDataPoints.LOW_LEVEL_ALARM: (DB_STATUS, (0, 5), 'BOOL'),
        WaterTankDataPoints.HIGH_PRESSURE_ALARM: (DB_STATUS, (0, 6), 'BOOL'),
        WaterTankDataPoints.TANK_EXPLODED_ALARM: (DB_STATUS, (0, 7), 'BOOL'),

        # Commands (DB3, BOOL - byte.bit)
        WaterTankDataPoints.INLET_VALVE_COMMAND: (DB_COMMANDS, (0, 0), 'BOOL'),
        WaterTankDataPoints.OUTLET_VALVE_COMMAND: (DB_COMMANDS, (0, 1), 'BOOL'),
        WaterTankDataPoints.PUMP_COMMAND: (DB_COMMANDS, (0, 2), 'BOOL'),
        WaterTankDataPoints.AUTO_MODE_COMMAND: (DB_COMMANDS, (0, 3), 'BOOL'),

        # Setpoints (DB4, REAL)
        WaterTankDataPoints.INLET_VALVE_SETPOINT: (DB_SETPOINTS, 0, 'REAL'),
        WaterTankDataPoints.OUTLET_VALVE_SETPOINT: (DB_SETPOINTS, 4, 'REAL'),
    }

    def __init__(self, host: str, port: int = 102, config: Dict = None):
        """Initialize S7 client"""
        super().__init__(host, port, config)
        self.rack = config.get('rack', 0) if config else 0
        self.slot = config.get('slot', 1) if config else 1

        self.client = Client()
        self.monitoring = False
        self.monitor_thread = None

    def connect(self) -> bool:
        """Connect to S7 server"""
        try:
            self.client.connect(self.host, self.rack, self.slot)
            self.connected = True
            return True
        except Exception as e:
            print(f"S7 connection error: {e}")
            self.connected = False
            return False

    def disconnect(self):
        """Disconnect from S7 server"""
        self.stop_monitoring()

        if self.connected:
            self.client.disconnect()
            self.connected = False

    def send_command(self, command: str, value: bool) -> bool:
        """Send digital command"""
        try:
            if command not in self.DATA_MAP:
                return False

            db, (byte_offset, bit_offset), data_type = self.DATA_MAP[command]

            # Read current byte value
            data = bytearray(self.client.db_read(db, byte_offset, 1))

            # Set the bit
            util.set_bool(data, 0, bit_offset, value)

            # Write back
            self.client.db_write(db, byte_offset, data)
            return True

        except Exception as e:
            print(f"Failed to send command {command}: {e}")
            return False

    def send_setpoint(self, setpoint: str, value: float) -> bool:
        """Send analog setpoint"""
        try:
            if setpoint not in self.DATA_MAP:
                return False

            db, offset, data_type = self.DATA_MAP[setpoint]

            # Create REAL value
            data = bytearray(4)
            util.set_real(data, 0, value)

            # Write to DB
            self.client.db_write(db, offset, data)
            return True

        except Exception as e:
            print(f"Failed to send setpoint {setpoint}: {e}")
            return False

    def start_monitoring(self):
        """Start monitoring data"""
        if not self.monitoring:
            self.monitoring = True
            self.monitor_thread = threading.Thread(
                target=self._monitor_loop,
                daemon=True,
                name="S7MonitorThread"
            )
            self.monitor_thread.start()

    def stop_monitoring(self):
        """Stop monitoring data"""
        self.monitoring = False
        if self.monitor_thread:
            self.monitor_thread.join(timeout=2)
            self.monitor_thread = None

    def _monitor_loop(self):
        """Monitoring loop - polls server for data"""
        while self.monitoring and self.connected:
            try:
                # Read all measurements
                self._read_measurements()

                # Read all status
                self._read_status()

                # Poll rate: 500ms
                time.sleep(0.5)

            except Exception as e:
                print(f"S7 monitor error: {e}")
                time.sleep(1)

    def _read_measurements(self):
        """Read all measurement values"""
        try:
            # Read all 3 REAL values from DB1 (12 bytes)
            data = self.client.db_read(self.DB_MEASUREMENTS, 0, 12)

            # Parse values
            water_level = util.get_real(data, 0)
            pressure = util.get_real(data, 4)
            temperature = util.get_real(data, 8)

            # Notify callbacks
            self._notify_data_update(WaterTankDataPoints.WATER_LEVEL, water_level)
            self._notify_data_update(WaterTankDataPoints.PRESSURE, pressure)
            self._notify_data_update(WaterTankDataPoints.TEMPERATURE, temperature)

        except Exception as e:
            print(f"Error reading measurements: {e}")

    def _read_status(self):
        """Read all status bits"""
        try:
            # Read 2 bytes from DB2 (covers all 8 status bits)
            data = self.client.db_read(self.DB_STATUS, 0, 2)

            # Parse status bits
            status_map = {
                WaterTankDataPoints.INLET_VALVE_STATUS: (0, 0),
                WaterTankDataPoints.OUTLET_VALVE_STATUS: (0, 1),
                WaterTankDataPoints.PUMP_STATUS: (0, 2),
                WaterTankDataPoints.AUTO_MODE_STATUS: (0, 3),
                WaterTankDataPoints.OVERFLOW_ALARM: (0, 4),
                WaterTankDataPoints.LOW_LEVEL_ALARM: (0, 5),
                WaterTankDataPoints.HIGH_PRESSURE_ALARM: (0, 6),
                WaterTankDataPoints.TANK_EXPLODED_ALARM: (0, 7),
            }

            for name, (byte_offset, bit_offset) in status_map.items():
                value = util.get_bool(data, byte_offset, bit_offset)
                self._notify_data_update(name, value)

        except Exception as e:
            print(f"Error reading status: {e}")
