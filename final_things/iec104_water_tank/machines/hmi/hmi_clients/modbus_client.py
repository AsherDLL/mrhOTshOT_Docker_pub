"""
Modbus TCP Client Adapter for HMI

Handles communication with Modbus water tank server.
"""

import threading
import time
from pymodbus.client import ModbusTcpClient
from typing import Dict
from hmi.protocol_client import ProtocolClient, WaterTankDataPoints


class ModbusClient(ProtocolClient):
    """Modbus TCP protocol client adapter"""

    # Register mapping: data point name -> (register_type, address)
    # register_type: 'coil', 'discrete', 'input', 'holding'
    REG_MAP = {
        # Measurements (Input Registers 3x)
        WaterTankDataPoints.WATER_LEVEL: ('input', 0),
        WaterTankDataPoints.PRESSURE: ('input', 1),
        WaterTankDataPoints.TEMPERATURE: ('input', 2),

        # Status (Discrete Inputs 1x)
        WaterTankDataPoints.INLET_VALVE_STATUS: ('discrete', 0),
        WaterTankDataPoints.OUTLET_VALVE_STATUS: ('discrete', 1),
        WaterTankDataPoints.PUMP_STATUS: ('discrete', 2),
        WaterTankDataPoints.AUTO_MODE_STATUS: ('discrete', 3),
        WaterTankDataPoints.OVERFLOW_ALARM: ('discrete', 8),
        WaterTankDataPoints.LOW_LEVEL_ALARM: ('discrete', 9),
        WaterTankDataPoints.HIGH_PRESSURE_ALARM: ('discrete', 10),
        WaterTankDataPoints.TANK_EXPLODED_ALARM: ('discrete', 11),

        # Commands (Coils 0x)
        WaterTankDataPoints.INLET_VALVE_COMMAND: ('coil', 0),
        WaterTankDataPoints.OUTLET_VALVE_COMMAND: ('coil', 1),
        WaterTankDataPoints.PUMP_COMMAND: ('coil', 2),
        WaterTankDataPoints.AUTO_MODE_COMMAND: ('coil', 3),

        # Setpoints (Holding Registers 4x)
        WaterTankDataPoints.INLET_VALVE_SETPOINT: ('holding', 0),
        WaterTankDataPoints.OUTLET_VALVE_SETPOINT: ('holding', 1),
    }

    def __init__(self, host: str, port: int = 502, config: Dict = None):
        """Initialize Modbus client"""
        super().__init__(host, port, config)
        self.slave_id = config.get('slave_id', 1) if config else 1

        self.client = ModbusTcpClient(host, port=port)
        self.monitoring = False
        self.monitor_thread = None

    def connect(self) -> bool:
        """Connect to Modbus server"""
        try:
            self.connected = self.client.connect()
            return self.connected
        except Exception as e:
            print(f"Modbus connection error: {e}")
            self.connected = False
            return False

    def disconnect(self):
        """Disconnect from Modbus server"""
        self.stop_monitoring()

        if self.connected:
            self.client.close()
            self.connected = False

    def send_command(self, command: str, value: bool) -> bool:
        """Send digital command"""
        try:
            if command not in self.REG_MAP:
                return False

            reg_type, address = self.REG_MAP[command]

            if reg_type == 'coil':
                result = self.client.write_coil(address, value, slave=self.slave_id)
                return not result.isError()

            return False

        except Exception as e:
            print(f"Failed to send command {command}: {e}")
            return False

    def send_setpoint(self, setpoint: str, value: float) -> bool:
        """Send analog setpoint"""
        try:
            if setpoint not in self.REG_MAP:
                return False

            reg_type, address = self.REG_MAP[setpoint]

            if reg_type == 'holding':
                # Scale value to 0-65535 based on expected range
                if 'valve' in setpoint.lower():
                    # Valve setpoints are 0-100%
                    scaled = int((value / 100.0) * 65535)
                else:
                    scaled = int(value)

                result = self.client.write_register(address, scaled, slave=self.slave_id)
                return not result.isError()

            return False

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
                name="ModbusMonitorThread"
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
                print(f"Modbus monitor error: {e}")
                time.sleep(1)

    def _read_measurements(self):
        """Read all measurement values"""
        try:
            # Read all 3 input registers
            result = self.client.read_input_registers(0, 3, slave=self.slave_id)

            if result.isError():
                return

            # Scale values from 0-65535 to actual ranges
            water_level = (result.registers[0] / 65535.0) * 100.0  # 0-100%
            pressure = (result.registers[1] / 65535.0) * 10.0      # 0-10 bar
            temperature = (result.registers[2] / 65535.0) * 100.0  # 0-100°C

            # Notify callbacks
            self._notify_data_update(WaterTankDataPoints.WATER_LEVEL, water_level)
            self._notify_data_update(WaterTankDataPoints.PRESSURE, pressure)
            self._notify_data_update(WaterTankDataPoints.TEMPERATURE, temperature)

        except Exception as e:
            print(f"Error reading measurements: {e}")

    def _read_status(self):
        """Read all status bits"""
        try:
            # Read all 12 discrete inputs
            result = self.client.read_discrete_inputs(0, 12, slave=self.slave_id)

            if result.isError():
                return

            bits = result.bits

            # Map bits to data points
            status_map = {
                WaterTankDataPoints.INLET_VALVE_STATUS: 0,
                WaterTankDataPoints.OUTLET_VALVE_STATUS: 1,
                WaterTankDataPoints.PUMP_STATUS: 2,
                WaterTankDataPoints.AUTO_MODE_STATUS: 3,
                WaterTankDataPoints.OVERFLOW_ALARM: 8,
                WaterTankDataPoints.LOW_LEVEL_ALARM: 9,
                WaterTankDataPoints.HIGH_PRESSURE_ALARM: 10,
                WaterTankDataPoints.TANK_EXPLODED_ALARM: 11,
            }

            for name, bit_index in status_map.items():
                self._notify_data_update(name, bits[bit_index])

        except Exception as e:
            print(f"Error reading status: {e}")
