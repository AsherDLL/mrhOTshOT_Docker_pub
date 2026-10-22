"""
Modbus TCP Protocol Adapter for Water Tank

Implements Modbus TCP server for water tank control.
Maps water tank data to Modbus registers:
- Coils (0x): Digital outputs (commands)
- Discrete Inputs (1x): Digital inputs (status)
- Input Registers (3x): Analog inputs (measurements)
- Holding Registers (4x): Analog outputs (setpoints)
"""

import threading
import time
import struct
from typing import Dict, Any
from pymodbus.server import StartTcpServer
from pymodbus.device import ModbusDeviceIdentification
from pymodbus.datastore import ModbusSequentialDataBlock, ModbusSlaveContext, ModbusServerContext
import pymodbus

from server.protocol_adapter import (
    ProtocolAdapter, DataPoint, DataPointType,
    WaterTankProtocolMapper
)


class ModbusAdapter(ProtocolAdapter):
    """
    Modbus TCP protocol adapter

    Register Mapping:
    - Coils (0x00000-0x09999): Digital outputs (commands)
    - Discrete Inputs (10000-19999): Digital status
    - Input Registers (30000-39999): Analog measurements
    - Holding Registers (40000-49999): Analog setpoints
    """

    # Modbus register base addresses
    COIL_BASE = 0           # Digital outputs (commands)
    DISCRETE_BASE = 0       # Digital inputs (status/alarms)
    INPUT_REG_BASE = 0      # Analog measurements
    HOLDING_REG_BASE = 0    # Analog setpoints

    def __init__(self, water_tank, config: Dict[str, Any]):
        """
        Initialize Modbus adapter

        Args:
            water_tank: WaterTank instance
            config: Configuration dict with keys:
                - host: Bind address (default: '0.0.0.0')
                - port: Modbus port (default: 502)
                - slave_id: Modbus slave ID (default: 1)
        """
        super().__init__(water_tank, config)

        self.host = config.get('host', '0.0.0.0')
        self.port = config.get('port', 502)
        self.slave_id = config.get('slave_id', 1)

        self.server_thread = None
        self.update_thread = None
        self.context = None

        # Track previous command states for change detection
        self.previous_command_states = {}

        # Create register address mapping
        self._create_address_mapping()

    def _create_address_mapping(self):
        """Create Modbus register address mapping for water tank"""
        data_points = WaterTankProtocolMapper.create_data_points()

        # Address counters for each register type
        coil_addr = self.COIL_BASE
        discrete_addr = self.DISCRETE_BASE
        input_reg_addr = self.INPUT_REG_BASE
        holding_reg_addr = self.HOLDING_REG_BASE

        for name, definition in data_points.items():
            point_type = definition['type']

            if point_type == DataPointType.DIGITAL_OUTPUT:
                # Commands -> Coils
                dp = DataPoint(
                    address=coil_addr,
                    point_type=point_type,
                    name=name,
                    description=definition['description']
                )
                coil_addr += 1

            elif point_type == DataPointType.DIGITAL_INPUT:
                # Status/Alarms -> Discrete Inputs
                dp = DataPoint(
                    address=discrete_addr,
                    point_type=point_type,
                    name=name,
                    description=definition['description']
                )
                discrete_addr += 1

            elif point_type == DataPointType.SCALED_VALUE or point_type == DataPointType.ANALOG_INPUT:
                # Measurements -> Input Registers
                dp = DataPoint(
                    address=input_reg_addr,
                    point_type=point_type,
                    name=name,
                    description=definition['description'],
                    min_value=definition.get('min'),
                    max_value=definition.get('max')
                )
                input_reg_addr += 1

            elif point_type == DataPointType.ANALOG_OUTPUT:
                # Setpoints -> Holding Registers
                dp = DataPoint(
                    address=holding_reg_addr,
                    point_type=point_type,
                    name=name,
                    description=definition['description'],
                    min_value=definition.get('min'),
                    max_value=definition.get('max')
                )
                holding_reg_addr += 1

            self.register_data_point(name, dp)

            # Register command callbacks
            callback = WaterTankProtocolMapper.get_command_callback(self.water_tank, name)
            if callback:
                self.register_command_callback(name, callback)

    def initialize(self) -> bool:
        """Initialize Modbus server context"""
        try:
            # Create data blocks
            # Coils: 100 coils starting at address 0
            coils = ModbusSequentialDataBlock(0, [0] * 100)

            # Discrete Inputs: 100 discrete inputs
            discrete_inputs = ModbusSequentialDataBlock(0, [0] * 100)

            # Input Registers: 100 registers (16-bit each)
            input_registers = ModbusSequentialDataBlock(0, [0] * 100)

            # Holding Registers: 100 registers
            holding_registers = ModbusSequentialDataBlock(0, [0] * 100)

            # Create slave context
            slave_context = ModbusSlaveContext(
                di=discrete_inputs,   # Discrete Inputs
                co=coils,              # Coils
                hr=holding_registers,  # Holding Registers
                ir=input_registers     # Input Registers
            )

            # Create server context with single slave
            self.context = ModbusServerContext(slaves={self.slave_id: slave_context}, single=False)

            # Setup device identification
            identity = ModbusDeviceIdentification()
            identity.VendorName = 'Water Tank Simulation'
            identity.ProductCode = 'WT-SIM'
            identity.VendorUrl = 'http://github.com/yourusername/water-tank'
            identity.ProductName = 'Water Tank ICS Simulator'
            identity.ModelName = 'Multi-Protocol Water Tank'
            identity.MajorMinorRevision = pymodbus.__version__

            self.logger.info(f"Modbus server initialized on {self.host}:{self.port}")
            self.logger.info(f"  Slave ID: {self.slave_id}")
            self.logger.info(f"  Coils: {len([dp for dp in self.data_points.values() if dp.point_type == DataPointType.DIGITAL_OUTPUT])}")
            self.logger.info(f"  Discrete Inputs: {len([dp for dp in self.data_points.values() if dp.point_type == DataPointType.DIGITAL_INPUT])}")
            self.logger.info(f"  Input Registers: {len([dp for dp in self.data_points.values() if dp.point_type in [DataPointType.SCALED_VALUE, DataPointType.ANALOG_INPUT]])}")
            self.logger.info(f"  Holding Registers: {len([dp for dp in self.data_points.values() if dp.point_type == DataPointType.ANALOG_OUTPUT])}")

            return True

        except Exception as e:
            self.logger.error(f"Failed to initialize Modbus server: {e}")
            return False

    def start(self) -> bool:
        """Start Modbus TCP server"""
        try:
            self.running = True

            # Start Modbus server in background thread
            self.server_thread = threading.Thread(
                target=self._run_server,
                daemon=True,
                name="ModbusServerThread"
            )
            self.server_thread.start()

            # Start data update thread
            self.update_thread = threading.Thread(
                target=self._update_loop,
                daemon=True,
                name="ModbusUpdateThread"
            )
            self.update_thread.start()

            self.logger.info(f"Modbus TCP server started on {self.host}:{self.port}")
            return True

        except Exception as e:
            self.logger.error(f"Failed to start Modbus server: {e}")
            self.running = False
            return False

    def _run_server(self):
        """Run Modbus TCP server (runs in background thread)"""
        try:
            StartTcpServer(
                context=self.context,
                address=(self.host, self.port)
            )
        except Exception as e:
            self.logger.error(f"Modbus server error: {e}")
            self.running = False

    def _update_loop(self):
        """Update Modbus registers from water tank (runs in background thread)"""
        slave = self.context[self.slave_id]

        while self.running:
            try:
                # Update discrete inputs (status/alarms)
                for name, dp in self.data_points.items():
                    if dp.point_type == DataPointType.DIGITAL_INPUT:
                        callback = WaterTankProtocolMapper.get_measurement_callback(
                            self.water_tank, name
                        )
                        if callback:
                            value = bool(callback())
                            slave.setValues(2, dp.address, [value])  # Function code 2 = Discrete Inputs

                # Update input registers (measurements)
                for name, dp in self.data_points.items():
                    if dp.point_type in [DataPointType.SCALED_VALUE, DataPointType.ANALOG_INPUT]:
                        callback = WaterTankProtocolMapper.get_measurement_callback(
                            self.water_tank, name
                        )
                        if callback:
                            value = float(callback())
                            # Scale to 16-bit integer (0-65535)
                            if dp.min_value is not None and dp.max_value is not None:
                                scaled = int(((value - dp.min_value) / (dp.max_value - dp.min_value)) * 65535)
                                scaled = max(0, min(65535, scaled))
                            else:
                                scaled = int(value)
                            slave.setValues(4, dp.address, [scaled])  # Function code 4 = Input Registers

                # Check for command changes (coils and holding registers)
                self._check_commands(slave)

                time.sleep(0.1)  # Update rate: 10 Hz

            except Exception as e:
                self.logger.error(f"Update loop error: {e}")
                time.sleep(1)

    def _check_commands(self, slave):
        """Check for command changes in coils and holding registers"""
        # Check coils (digital commands)
        for name, dp in self.data_points.items():
            if dp.point_type == DataPointType.DIGITAL_OUTPUT:
                values = slave.getValues(1, dp.address, 1)  # Function code 1 = Read Coils
                if values and len(values) > 0:
                    value = bool(values[0])

                    # Only execute callback if value changed
                    prev_value = self.previous_command_states.get(name)
                    if prev_value is None or prev_value != value:
                        self.previous_command_states[name] = value

                        callback = self.command_callbacks.get(name)
                        if callback:
                            try:
                                success = callback(value)
                                if success:
                                    self.logger.info(f"Command executed: {name} = {value}")
                            except Exception as e:
                                self.logger.error(f"Command execution failed for {name}: {e}")

        # Check holding registers (analog commands/setpoints)
        for name, dp in self.data_points.items():
            if dp.point_type == DataPointType.ANALOG_OUTPUT:
                values = slave.getValues(3, dp.address, 1)  # Function code 3 = Read Holding Registers
                if values and len(values) > 0:
                    # Descale from 16-bit integer
                    scaled_value = values[0]
                    if dp.min_value is not None and dp.max_value is not None:
                        value = dp.min_value + (scaled_value / 65535.0) * (dp.max_value - dp.min_value)
                    else:
                        value = float(scaled_value)

                    # Only execute callback if value changed
                    prev_value = self.previous_command_states.get(name)
                    if prev_value is None or prev_value != value:
                        self.previous_command_states[name] = value

                        callback = self.command_callbacks.get(name)
                        if callback:
                            try:
                                success = callback(value)
                                if success:
                                    self.logger.info(f"Setpoint executed: {name} = {value:.2f}")
                            except Exception as e:
                                self.logger.error(f"Setpoint execution failed for {name}: {e}")

    def stop(self):
        """Stop Modbus server"""
        self.running = False
        if self.server_thread:
            self.server_thread.join(timeout=2)
        if self.update_thread:
            self.update_thread.join(timeout=2)
        self.logger.info("Modbus server stopped")

    def update_data_point(self, name: str, value: Any):
        """
        Update a data point value (manual override)

        Args:
            name: Data point name
            value: New value
        """
        if name in self.data_points:
            dp = self.data_points[name]
            slave = self.context[self.slave_id]

            if dp.point_type == DataPointType.DIGITAL_INPUT:
                slave.setValues(2, dp.address, [bool(value)])
            elif dp.point_type in [DataPointType.SCALED_VALUE, DataPointType.ANALOG_INPUT]:
                if dp.min_value is not None and dp.max_value is not None:
                    scaled = int(((value - dp.min_value) / (dp.max_value - dp.min_value)) * 65535)
                    scaled = max(0, min(65535, scaled))
                else:
                    scaled = int(value)
                slave.setValues(4, dp.address, [scaled])

    def get_register_map(self) -> str:
        """
        Get human-readable register map

        Returns:
            Formatted string with register assignments
        """
        lines = []
        lines.append("=" * 80)
        lines.append("MODBUS REGISTER MAP - Water Tank")
        lines.append("=" * 80)

        # Group by register type
        coils = []
        discrete = []
        input_regs = []
        holding_regs = []

        for name, dp in sorted(self.data_points.items(), key=lambda x: (x[1].point_type.value, x[1].address)):
            if dp.point_type == DataPointType.DIGITAL_OUTPUT:
                coils.append((dp.address, name, dp.description))
            elif dp.point_type == DataPointType.DIGITAL_INPUT:
                discrete.append((dp.address, name, dp.description))
            elif dp.point_type in [DataPointType.SCALED_VALUE, DataPointType.ANALOG_INPUT]:
                input_regs.append((dp.address, name, dp.description))
            elif dp.point_type == DataPointType.ANALOG_OUTPUT:
                holding_regs.append((dp.address, name, dp.description))

        if coils:
            lines.append("\nCOILS (0x) - Digital Outputs / Commands:")
            lines.append("-" * 80)
            for addr, name, desc in coils:
                lines.append(f"  {addr:5d}  {name:30s}  {desc}")

        if discrete:
            lines.append("\nDISCRETE INPUTS (1x) - Digital Status:")
            lines.append("-" * 80)
            for addr, name, desc in discrete:
                lines.append(f"  {addr:5d}  {name:30s}  {desc}")

        if input_regs:
            lines.append("\nINPUT REGISTERS (3x) - Analog Measurements:")
            lines.append("-" * 80)
            for addr, name, desc in input_regs:
                lines.append(f"  {addr:5d}  {name:30s}  {desc}")

        if holding_regs:
            lines.append("\nHOLDING REGISTERS (4x) - Analog Setpoints:")
            lines.append("-" * 80)
            for addr, name, desc in holding_regs:
                lines.append(f"  {addr:5d}  {name:30s}  {desc}")

        lines.append("=" * 80)

        return "\n".join(lines)
