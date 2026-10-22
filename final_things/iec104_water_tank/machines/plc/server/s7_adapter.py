"""
Siemens S7 Protocol Adapter for Water Tank

Implements Siemens S7 PLC communication for water tank control.
Maps water tank data to S7 Data Blocks (DB):
- DB1: Process measurements (inputs)
- DB2: Process status (digital inputs)
- DB3: Command outputs (digital outputs)
- DB4: Setpoint outputs (analog outputs)
"""

import threading
import time
import struct
import ctypes
from typing import Dict, Any
import snap7
from snap7.server import Server
try:
    from snap7.types import srvAreaDB, srvAreaMK, srvAreaPE, srvAreaPA, srvAreaCT, srvAreaTM
except ImportError:
    # snap7 3.x moved the enum
    srvAreaDB = snap7.SrvArea.DB
    srvAreaMK = snap7.SrvArea.MK
    srvAreaPE = snap7.SrvArea.PE
    srvAreaPA = snap7.SrvArea.PA
    srvAreaCT = snap7.SrvArea.CT
    srvAreaTM = snap7.SrvArea.TM

from server.protocol_adapter import (
    ProtocolAdapter, DataPoint, DataPointType,
    WaterTankProtocolMapper
)


class S7Adapter(ProtocolAdapter):
    """
    Siemens S7 protocol adapter

    Data Block (DB) Layout:
    - DB1: Analog measurements (REAL - 4 bytes each)
    - DB2: Digital status bits (BOOL - 1 bit each, packed into bytes)
    - DB3: Digital command bits (BOOL - 1 bit each)
    - DB4: Analog setpoints (REAL - 4 bytes each)
    """

    # Data Block numbers
    DB_MEASUREMENTS = 1
    DB_STATUS = 2
    DB_COMMANDS = 3
    DB_SETPOINTS = 4

    def __init__(self, water_tank, config: Dict[str, Any]):
        """
        Initialize S7 adapter

        Args:
            water_tank: WaterTank instance
            config: Configuration dict with keys:
                - host: Bind address (default: '0.0.0.0')
                - port: S7 port (default: 102)
                - rack: S7 rack number (default: 0)
                - slot: S7 slot number (default: 1)
        """
        super().__init__(water_tank, config)

        self.host = config.get('host', '0.0.0.0')
        self.port = config.get('port', 102)
        self.rack = config.get('rack', 0)
        self.slot = config.get('slot', 1)

        self.server = None
        self.update_thread = None

        # Data block storage - must use ctypes arrays for snap7
        self.db_data = {
            self.DB_MEASUREMENTS: (ctypes.c_ubyte * 100)(),   # 100 bytes
            self.DB_STATUS: (ctypes.c_ubyte * 10)(),          # 10 bytes (80 bits)
            self.DB_COMMANDS: (ctypes.c_ubyte * 10)(),        # 10 bytes
            self.DB_SETPOINTS: (ctypes.c_ubyte * 100)()       # 100 bytes
        }

        # Standard S7 memory areas (Merker, I/O, Counters, Timers)
        # M area layout mirrors DB data:
        #   MD0  (bytes 0-3)   = Measurement 1 (REAL)
        #   MD4  (bytes 4-7)   = Measurement 2 (REAL)
        #   MD8  (bytes 8-11)  = Measurement 3 (REAL)
        #   M12.0-M12.7        = Status bits (8 bools)
        #   M13.0-M13.3        = Command bits (4 bools)
        #   MD16 (bytes 16-19) = Setpoint 1 (REAL)
        #   MD20 (bytes 20-23) = Setpoint 2 (REAL)
        self.mk_data = (ctypes.c_ubyte * 256)()    # Merker (M) area - 256 bytes
        self.pe_data = (ctypes.c_ubyte * 128)()     # Process Inputs (I) area
        self.pa_data = (ctypes.c_ubyte * 128)()     # Process Outputs (Q) area
        self.ct_data = (ctypes.c_ubyte * 64)()      # Counters
        self.tm_data = (ctypes.c_ubyte * 64)()      # Timers

        # Track previous command states for change detection
        self.previous_command_states = {}

        # Create address mapping
        self._create_address_mapping()

    def _create_address_mapping(self):
        """Create S7 Data Block address mapping for water tank"""
        data_points = WaterTankProtocolMapper.create_data_points()

        # Address counters for each DB
        measurement_offset = 0   # Byte offset in DB1
        status_bit = 0           # Bit offset in DB2
        command_bit = 0          # Bit offset in DB3
        setpoint_offset = 0      # Byte offset in DB4

        for name, definition in data_points.items():
            point_type = definition['type']

            if point_type in [DataPointType.SCALED_VALUE, DataPointType.ANALOG_INPUT]:
                # Measurements -> DB1 (REAL = 4 bytes)
                dp = DataPoint(
                    address={'db': self.DB_MEASUREMENTS, 'offset': measurement_offset, 'type': 'REAL'},
                    point_type=point_type,
                    name=name,
                    description=definition['description'],
                    min_value=definition.get('min'),
                    max_value=definition.get('max')
                )
                measurement_offset += 4  # REAL is 4 bytes

            elif point_type == DataPointType.DIGITAL_INPUT:
                # Status -> DB2 (BOOL = 1 bit)
                byte_offset = status_bit // 8
                bit_offset = status_bit % 8
                dp = DataPoint(
                    address={'db': self.DB_STATUS, 'byte': byte_offset, 'bit': bit_offset, 'type': 'BOOL'},
                    point_type=point_type,
                    name=name,
                    description=definition['description']
                )
                status_bit += 1

            elif point_type == DataPointType.DIGITAL_OUTPUT:
                # Commands -> DB3 (BOOL = 1 bit)
                byte_offset = command_bit // 8
                bit_offset = command_bit % 8
                dp = DataPoint(
                    address={'db': self.DB_COMMANDS, 'byte': byte_offset, 'bit': bit_offset, 'type': 'BOOL'},
                    point_type=point_type,
                    name=name,
                    description=definition['description']
                )
                command_bit += 1

            elif point_type == DataPointType.ANALOG_OUTPUT:
                # Setpoints -> DB4 (REAL = 4 bytes)
                dp = DataPoint(
                    address={'db': self.DB_SETPOINTS, 'offset': setpoint_offset, 'type': 'REAL'},
                    point_type=point_type,
                    name=name,
                    description=definition['description'],
                    min_value=definition.get('min'),
                    max_value=definition.get('max')
                )
                setpoint_offset += 4

            self.register_data_point(name, dp)

            # Register command callbacks
            callback = WaterTankProtocolMapper.get_command_callback(self.water_tank, name)
            if callback:
                self.register_command_callback(name, callback)

    def initialize(self) -> bool:
        """Initialize S7 server"""
        try:
            # Create Snap7 server
            self.server = Server()

            # Register data blocks
            for db_num, data in self.db_data.items():
                self.server.register_area(srvAreaDB, db_num, data)

            # Register standard S7 memory areas (makes it look like a real PLC)
            self.server.register_area(srvAreaMK, 0, self.mk_data)   # Merker/Flags
            self.server.register_area(srvAreaPE, 0, self.pe_data)   # Process Inputs
            self.server.register_area(srvAreaPA, 0, self.pa_data)   # Process Outputs
            self.server.register_area(srvAreaCT, 0, self.ct_data)   # Counters
            self.server.register_area(srvAreaTM, 0, self.tm_data)   # Timers

            # Initialize command DB with default values matching water tank initial state
            # Water tank starts in auto mode, so set auto_mode_command = True
            for name, dp in self.data_points.items():
                if name == 'auto_mode_command' and dp.point_type == DataPointType.DIGITAL_OUTPUT:
                    self._write_bool(dp.address['db'], dp.address['byte'], dp.address['bit'], True)
                    self.previous_command_states[name] = True  # Track initial state
                    self.logger.info(f"Initialized {name} = True (auto mode)")

            self.logger.info(f"S7 server initialized")
            self.logger.info(f"  Rack: {self.rack}, Slot: {self.slot}")
            self.logger.info(f"  DB1 (Measurements): {len([dp for dp in self.data_points.values() if isinstance(dp.address, dict) and dp.address.get('db') == self.DB_MEASUREMENTS])} REAL values")
            self.logger.info(f"  DB2 (Status): {len([dp for dp in self.data_points.values() if isinstance(dp.address, dict) and dp.address.get('db') == self.DB_STATUS])} BOOL values")
            self.logger.info(f"  DB3 (Commands): {len([dp for dp in self.data_points.values() if isinstance(dp.address, dict) and dp.address.get('db') == self.DB_COMMANDS])} BOOL values")
            self.logger.info(f"  DB4 (Setpoints): {len([dp for dp in self.data_points.values() if isinstance(dp.address, dict) and dp.address.get('db') == self.DB_SETPOINTS])} REAL values")

            return True

        except Exception as e:
            self.logger.error(f"Failed to initialize S7 server: {e}")
            return False

    def start(self) -> bool:
        """Start S7 server"""
        try:
            # Start server - snap7 3.x renamed tcpport → tcp_port
            try:
                self.server.start(tcp_port=self.port)
            except TypeError:
                self.server.start(tcpport=self.port)
            self.running = True

            # Start data update thread
            self.update_thread = threading.Thread(
                target=self._update_loop,
                daemon=True,
                name="S7UpdateThread"
            )
            self.update_thread.start()

            self.logger.info(f"S7 server started on port {self.port}")
            return True

        except Exception as e:
            self.logger.error(f"Failed to start S7 server: {e}")
            self.running = False
            return False

    def _update_loop(self):
        """Update S7 data blocks from water tank (runs in background thread)"""
        while self.running:
            try:
                # Update measurements (DB1)
                for name, dp in self.data_points.items():
                    if dp.point_type in [DataPointType.SCALED_VALUE, DataPointType.ANALOG_INPUT]:
                        callback = WaterTankProtocolMapper.get_measurement_callback(
                            self.water_tank, name
                        )
                        if callback:
                            value = float(callback())
                            self._write_real(dp.address['db'], dp.address['offset'], value)

                # Update status (DB2)
                for name, dp in self.data_points.items():
                    if dp.point_type == DataPointType.DIGITAL_INPUT:
                        callback = WaterTankProtocolMapper.get_measurement_callback(
                            self.water_tank, name
                        )
                        if callback:
                            value = bool(callback())
                            self._write_bool(dp.address['db'], dp.address['byte'], dp.address['bit'], value)

                # Check for commands (DB3 and DB4)
                self._check_commands()

                # Mirror DB data into M (Merker) area for clients using M addresses
                # MD0/4/8 = measurements, M12 = status bits, M13 = cmd bits, MD16/20 = setpoints
                struct.pack_into('>fff', self.mk_data, 0,
                    struct.unpack_from('>f', self.db_data[self.DB_MEASUREMENTS], 0)[0],
                    struct.unpack_from('>f', self.db_data[self.DB_MEASUREMENTS], 4)[0],
                    struct.unpack_from('>f', self.db_data[self.DB_MEASUREMENTS], 8)[0])
                self.mk_data[12] = self.db_data[self.DB_STATUS][0]      # status byte
                self.mk_data[13] = self.db_data[self.DB_COMMANDS][0]     # command byte
                struct.pack_into('>ff', self.mk_data, 16,
                    struct.unpack_from('>f', self.db_data[self.DB_SETPOINTS], 0)[0],
                    struct.unpack_from('>f', self.db_data[self.DB_SETPOINTS], 4)[0])

                time.sleep(0.1)  # Update rate: 10 Hz

            except Exception as e:
                self.logger.error(f"Update loop error: {e}")
                time.sleep(1)

    def _check_commands(self):
        """Check for command changes in DB3 and DB4"""
        # Check digital commands (DB3)
        for name, dp in self.data_points.items():
            if dp.point_type == DataPointType.DIGITAL_OUTPUT:
                value = self._read_bool(dp.address['db'], dp.address['byte'], dp.address['bit'])

                # Only execute callback if value changed
                prev_value = self.previous_command_states.get(name)
                if prev_value != value:
                    self.previous_command_states[name] = value
                    callback = self.command_callbacks.get(name)
                    if callback:
                        try:
                            success = callback(value)
                            if success:
                                self.logger.info(f"Command executed: {name} = {value}")
                        except Exception as e:
                            self.logger.error(f"Command execution failed for {name}: {e}")

        # Check analog setpoints (DB4)
        for name, dp in self.data_points.items():
            if dp.point_type == DataPointType.ANALOG_OUTPUT:
                value = self._read_real(dp.address['db'], dp.address['offset'])

                # Only execute callback if value changed significantly (> 0.1 difference)
                prev_value = self.previous_command_states.get(name)
                if prev_value is None or abs(prev_value - value) > 0.1:
                    self.previous_command_states[name] = value
                    callback = self.command_callbacks.get(name)
                    if callback:
                        try:
                            success = callback(value)
                            if success:
                                self.logger.info(f"Setpoint executed: {name} = {value:.2f}")
                        except Exception as e:
                            self.logger.error(f"Setpoint execution failed for {name}: {e}")

    def _write_bool(self, db: int, byte_offset: int, bit_offset: int, value: bool):
        """Write BOOL value to data block"""
        # Directly modify the registered ctypes array
        data = self.db_data[db]
        if value:
            data[byte_offset] |= (1 << bit_offset)
        else:
            data[byte_offset] &= ~(1 << bit_offset)
        # No need to call set_area - the registered array is automatically updated

    def _read_bool(self, db: int, byte_offset: int, bit_offset: int) -> bool:
        """Read BOOL value from data block"""
        # Read directly from the registered ctypes array
        data = self.db_data[db]
        return bool(data[byte_offset] & (1 << bit_offset))

    def _write_real(self, db: int, offset: int, value: float):
        """Write REAL (float) value to data block"""
        # Directly modify the registered ctypes array
        data = self.db_data[db]
        struct.pack_into('>f', data, offset, value)  # Big-endian float
        # No need to call set_area - the registered array is automatically updated

    def _read_real(self, db: int, offset: int) -> float:
        """Read REAL (float) value from data block"""
        # Read directly from the registered ctypes array
        data = self.db_data[db]
        return struct.unpack_from('>f', data, offset)[0]

    def stop(self):
        """Stop S7 server"""
        self.running = False
        if self.update_thread:
            self.update_thread.join(timeout=2)
        if self.server:
            self.server.stop()
        self.logger.info("S7 server stopped")

    def update_data_point(self, name: str, value: Any):
        """
        Update a data point value (manual override)

        Args:
            name: Data point name
            value: New value
        """
        if name in self.data_points:
            dp = self.data_points[name]

            if dp.point_type == DataPointType.DIGITAL_INPUT:
                self._write_bool(dp.address['db'], dp.address['byte'], dp.address['bit'], bool(value))
            elif dp.point_type in [DataPointType.SCALED_VALUE, DataPointType.ANALOG_INPUT]:
                self._write_real(dp.address['db'], dp.address['offset'], float(value))

    def get_db_layout(self) -> str:
        """
        Get human-readable Data Block layout

        Returns:
            Formatted string with DB layout
        """
        lines = []
        lines.append("=" * 80)
        lines.append("SIEMENS S7 DATA BLOCK LAYOUT - Water Tank")
        lines.append("=" * 80)

        # Group by DB
        db_points = {
            self.DB_MEASUREMENTS: [],
            self.DB_STATUS: [],
            self.DB_COMMANDS: [],
            self.DB_SETPOINTS: []
        }

        for name, dp in self.data_points.items():
            if isinstance(dp.address, dict):
                db_num = dp.address['db']
                if db_num in db_points:
                    db_points[db_num].append((name, dp))

        # DB1 - Measurements
        if db_points[self.DB_MEASUREMENTS]:
            lines.append(f"\nDB{self.DB_MEASUREMENTS} - Process Measurements (Analog Inputs):")
            lines.append("-" * 80)
            for name, dp in sorted(db_points[self.DB_MEASUREMENTS], key=lambda x: x[1].address['offset']):
                offset = dp.address['offset']
                lines.append(f"  DBD{offset:3d}  (REAL)  {name:30s}  {dp.description}")

        # DB2 - Status
        if db_points[self.DB_STATUS]:
            lines.append(f"\nDB{self.DB_STATUS} - Process Status (Digital Inputs):")
            lines.append("-" * 80)
            for name, dp in sorted(db_points[self.DB_STATUS], key=lambda x: (x[1].address['byte'], x[1].address['bit'])):
                byte_offset = dp.address['byte']
                bit_offset = dp.address['bit']
                lines.append(f"  DBX{byte_offset:3d}.{bit_offset} (BOOL)  {name:30s}  {dp.description}")

        # DB3 - Commands
        if db_points[self.DB_COMMANDS]:
            lines.append(f"\nDB{self.DB_COMMANDS} - Commands (Digital Outputs):")
            lines.append("-" * 80)
            for name, dp in sorted(db_points[self.DB_COMMANDS], key=lambda x: (x[1].address['byte'], x[1].address['bit'])):
                byte_offset = dp.address['byte']
                bit_offset = dp.address['bit']
                lines.append(f"  DBX{byte_offset:3d}.{bit_offset} (BOOL)  {name:30s}  {dp.description}")

        # DB4 - Setpoints
        if db_points[self.DB_SETPOINTS]:
            lines.append(f"\nDB{self.DB_SETPOINTS} - Setpoints (Analog Outputs):")
            lines.append("-" * 80)
            for name, dp in sorted(db_points[self.DB_SETPOINTS], key=lambda x: x[1].address['offset']):
                offset = dp.address['offset']
                lines.append(f"  DBD{offset:3d}  (REAL)  {name:30s}  {dp.description}")

        lines.append("=" * 80)

        return "\n".join(lines)
