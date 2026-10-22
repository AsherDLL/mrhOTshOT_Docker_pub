"""
IEC 60870-5-104 Protocol Adapter for Water Tank

Wraps the existing IEC-104 server implementation to conform to the
protocol adapter interface for multi-protocol support.
"""

import threading
import time
from typing import Dict, Any
import c104

from server.protocol_adapter import (
    ProtocolAdapter, DataPoint, DataPointType,
    WaterTankProtocolMapper
)
from common.config import *


class IEC104Adapter(ProtocolAdapter):
    """
    IEC-104 protocol adapter

    Uses the existing c104 library implementation.
    Maps water tank data to Information Object Addresses (IOA).
    """

    def __init__(self, water_tank, config: Dict[str, Any]):
        """
        Initialize IEC-104 adapter

        Args:
            water_tank: WaterTank instance
            config: Configuration dict with keys:
                - host: Bind address (default: '0.0.0.0')
                - port: IEC-104 port (default: 2404)
                - common_address: Common Address (default: 1)
        """
        super().__init__(water_tank, config)

        self.host = config.get('host', IEC104_HOST)
        self.port = config.get('port', IEC104_PORT)
        self.common_address = config.get('common_address', COMMON_ADDRESS)

        self.server = None
        self.station = None
        self.points = {}
        self.update_thread = None

        # Create IOA address mapping from config
        self._create_address_mapping()

    def _create_address_mapping(self):
        """Create IEC-104 IOA address mapping using existing config"""
        # Measurements (M_ME_NB_1)
        measurements = {
            'water_level': IOA_WATER_LEVEL,
            'pressure': IOA_PRESSURE,
            'temperature': IOA_TEMPERATURE
        }

        for name, ioa in measurements.items():
            dp = DataPoint(
                address=ioa,
                point_type=DataPointType.SCALED_VALUE,
                name=name,
                description=f"{name.replace('_', ' ').title()}"
            )
            self.register_data_point(name, dp)

        # Status points (M_SP_NA_1)
        status_points = {
            'inlet_valve_status': IOA_INLET_VALVE_STATUS,
            'outlet_valve_status': IOA_OUTLET_VALVE_STATUS,
            'pump_status': IOA_PUMP_STATUS,
            'auto_mode_status': IOA_AUTO_MODE_STATUS,
            'alarm_overflow': IOA_ALARM_OVERFLOW,
            'alarm_low_level': IOA_ALARM_LOW_LEVEL,
            'alarm_high_pressure': IOA_ALARM_HIGH_PRESSURE,
            'tank_exploded': IOA_TANK_EXPLODED
        }

        for name, ioa in status_points.items():
            dp = DataPoint(
                address=ioa,
                point_type=DataPointType.DIGITAL_INPUT,
                name=name,
                description=f"{name.replace('_', ' ').title()}"
            )
            self.register_data_point(name, dp)

        # Command points (C_SC_NA_1)
        commands = {
            'inlet_valve_command': IOA_INLET_VALVE_COMMAND,
            'outlet_valve_command': IOA_OUTLET_VALVE_COMMAND,
            'pump_command': IOA_PUMP_COMMAND,
            'auto_mode_command': IOA_AUTO_MODE_COMMAND
        }

        for name, ioa in commands.items():
            dp = DataPoint(
                address=ioa,
                point_type=DataPointType.DIGITAL_OUTPUT,
                name=name,
                description=f"{name.replace('_', ' ').title()}"
            )
            self.register_data_point(name, dp)

            # Register callback
            callback = WaterTankProtocolMapper.get_command_callback(self.water_tank, name)
            if callback:
                self.register_command_callback(name, callback)

        # Setpoint commands (C_SE_NC_1)
        setpoints = {
            'inlet_valve_setpoint': IOA_INLET_VALVE_SETPOINT,
            'outlet_valve_setpoint': IOA_OUTLET_VALVE_SETPOINT
        }

        for name, ioa in setpoints.items():
            dp = DataPoint(
                address=ioa,
                point_type=DataPointType.ANALOG_OUTPUT,
                name=name,
                description=f"{name.replace('_', ' ').title()}"
            )
            self.register_data_point(name, dp)

            callback = WaterTankProtocolMapper.get_command_callback(self.water_tank, name)
            if callback:
                self.register_command_callback(name, callback)

    def initialize(self) -> bool:
        """Initialize IEC-104 server"""
        try:
            # Create server
            self.server = c104.Server(ip=self.host, port=self.port)
            self.station = self.server.add_station(common_address=self.common_address)

            # Setup measurement points (report_ms=1000: auto-transmit every 1s)
            for name in ['water_level', 'pressure', 'temperature']:
                dp = self.data_points[name]
                point = self.station.add_point(
                    io_address=dp.address,
                    type=c104.Type.M_ME_NB_1,
                    report_ms=1000
                )
                self.points[name] = point

            # Setup status points (report_ms=500: auto-transmit every 500ms)
            for name in ['inlet_valve_status', 'outlet_valve_status', 'pump_status',
                        'auto_mode_status', 'alarm_overflow', 'alarm_low_level',
                        'alarm_high_pressure', 'tank_exploded']:
                dp = self.data_points[name]
                point = self.station.add_point(
                    io_address=dp.address,
                    type=c104.Type.M_SP_NA_1,
                    report_ms=500
                )
                self.points[name] = point

            # Setup command points
            for name in ['inlet_valve_command', 'outlet_valve_command',
                        'pump_command', 'auto_mode_command']:
                dp = self.data_points[name]
                point = self.station.add_point(
                    io_address=dp.address,
                    type=c104.Type.C_SC_NA_1
                )
                point.on_receive(self._make_command_handler(name))
                self.points[name] = point

            # Setup setpoint points
            for name in ['inlet_valve_setpoint', 'outlet_valve_setpoint']:
                dp = self.data_points[name]
                point = self.station.add_point(
                    io_address=dp.address,
                    type=c104.Type.C_SE_NC_1
                )
                point.on_receive(self._make_setpoint_handler(name))
                self.points[name] = point

            # =============================================================================
            # ADD INDUSTROYER2 IOAs - Accept commands to all malware-targeted IOAs
            # =============================================================================
            self.logger.info("[*] Adding Industroyer2 IOA handlers for malware simulation...")

            # Industroyer2 IOAs (C_DC_NA_1 - Type 46 - Double Command) - Circuit Breakers
            # For each command IOA, also add a status point so it shows up in interrogation
            industroyer2_dc_ioas = []
            for base in [1100, 1200, 1300, 1400]:
                for offset in range(1, 5):
                    industroyer2_dc_ioas.append(base + offset)

            for ioa in industroyer2_dc_ioas:
                try:
                    # Add command point that also serves as status (C_DC_NA_1)
                    # The c104 library allows command points to have handlers AND appear in interrogation
                    point = self.station.add_point(
                        io_address=ioa,
                        type=c104.Type.C_DC_NA_1,  # Type 46 - Double Command
                        report_ms=0  # No periodic reporting
                    )
                    # Initialize to OFF state
                    point.value = c104.Double.OFF
                    # Add handler to accept commands
                    point.on_receive(self._make_wildcard_handler(ioa, "C_DC_NA_1", point))
                    self.points[f'industroyer2_{ioa}'] = point
                except Exception as e:
                    self.logger.warning(f"Could not add IOA {ioa}: {e}")

            # Industroyer2 IOAs (C_SC_NA_1 - Type 45 - Single Command) - Switches
            industroyer2_sc_ioas = [
                130202, 160921, 160922, 160923, 160924, 160925, 160926, 160927, 160928,
                190202, 260202, 260901, 260902, 260903, 260904, 260905, 260906, 260907,
                260908, 260909, 260910, 260911, 260912, 260913, 260914, 260915, 260916,
                260917, 260918, 260919, 260920, 290202, 338501
            ]

            for ioa in industroyer2_sc_ioas:
                try:
                    # Add command point that also serves as status (C_SC_NA_1)
                    # The c104 library allows command points to have handlers AND appear in interrogation
                    point = self.station.add_point(
                        io_address=ioa,
                        type=c104.Type.C_SC_NA_1,  # Type 45 - Single Command
                        report_ms=0  # No periodic reporting
                    )
                    # Initialize to OFF state
                    point.value = False
                    # Add handler to accept commands
                    point.on_receive(self._make_wildcard_handler(ioa, "C_SC_NA_1", point))
                    self.points[f'industroyer2_{ioa}'] = point
                except Exception as e:
                    self.logger.warning(f"Could not add IOA {ioa}: {e}")

            self.logger.info(f"[+] Added {len(industroyer2_dc_ioas)} C_DC_NA_1 (Type 46) IOA handlers with status points")
            self.logger.info(f"[+] Added {len(industroyer2_sc_ioas)} C_SC_NA_1 (Type 45) IOA handlers with status points")

            self.logger.info(f"IEC-104 server initialized on {self.host}:{self.port}")
            self.logger.info(f"  Common Address: {self.common_address}")
            self.logger.info(f"  Data points: {len(self.points)}")

            return True

        except Exception as e:
            self.logger.error(f"Failed to initialize IEC-104 server: {e}")
            return False

    def _make_command_handler(self, name: str):
        """Create command handler for a specific data point"""
        def handler(point: c104.Point, previous_info: c104.Information, message: c104.IncomingMessage) -> c104.ResponseState:
            value = bool(point.value)
            callback = self.command_callbacks.get(name)
            if callback:
                try:
                    success = callback(value)
                    self.logger.info(f"Command: {name} = {value} ({'SUCCESS' if success else 'FAILED'})")
                    return c104.ResponseState.SUCCESS if success else c104.ResponseState.FAILURE
                except Exception as e:
                    self.logger.error(f"Command failed for {name}: {e}")
                    return c104.ResponseState.FAILURE
            return c104.ResponseState.FAILURE
        return handler

    def _make_setpoint_handler(self, name: str):
        """Create setpoint handler for a specific data point"""
        def handler(point: c104.Point, previous_info: c104.Information, message: c104.IncomingMessage) -> c104.ResponseState:
            value = float(point.value)
            callback = self.command_callbacks.get(name)
            if callback:
                try:
                    success = callback(value)
                    self.logger.info(f"Setpoint: {name} = {value:.2f} ({'SUCCESS' if success else 'FAILED'})")
                    return c104.ResponseState.SUCCESS if success else c104.ResponseState.FAILURE
                except Exception as e:
                    self.logger.error(f"Setpoint failed for {name}: {e}")
                    return c104.ResponseState.FAILURE
            return c104.ResponseState.FAILURE
        return handler

    def _make_wildcard_handler(self, ioa: int, cmd_type: str, status_point=None):
        """
        Create wildcard handler for Industroyer2 IOAs

        These handlers accept commands but don't do anything (dummy handlers).
        They exist purely to make the IEC-104 server respond to all Industroyer2 IOAs
        so that Wireshark can capture the full attack traffic.

        Args:
            ioa: Information Object Address
            cmd_type: Command type string for logging
            status_point: Not used (kept for compatibility)
        """
        def handler(point: c104.Point, previous_info: c104.Information, message: c104.IncomingMessage) -> c104.ResponseState:
            value = point.value
            self.logger.info(f"[INDUSTROYER2 IOA] Received {cmd_type} command -> IOA {ioa} = {value}")

            # Always return SUCCESS so the malware simulation sees acknowledgments
            return c104.ResponseState.SUCCESS
        return handler

    def start(self) -> bool:
        """Start IEC-104 server"""
        try:
            self.server.start()
            self.running = True

            # Start update thread
            self.update_thread = threading.Thread(
                target=self._update_loop,
                daemon=True,
                name="IEC104UpdateThread"
            )
            self.update_thread.start()

            self.logger.info(f"IEC-104 server started")
            return True

        except Exception as e:
            self.logger.error(f"Failed to start IEC-104 server: {e}")
            self.running = False
            return False

    def _update_loop(self):
        """Update IEC-104 points from water tank (c104 auto-transmits via report_ms)"""
        while self.running:
            try:
                # Update measurements
                for name in ['water_level', 'pressure', 'temperature']:
                    callback = WaterTankProtocolMapper.get_measurement_callback(
                        self.water_tank, name
                    )
                    if callback:
                        value = float(callback())
                        # Scale to Int16 range for M_ME_NB_1
                        if name == 'water_level':
                            scaled = int(value * 327.67)  # 0-100% -> 0-32767
                        elif name == 'pressure':
                            scaled = int(value * 2184.5)  # 0-15 bar -> 0-32767
                        elif name == 'temperature':
                            scaled = int(value * 327.67)  # 0-100°C -> 0-32767
                        else:
                            scaled = int(value)

                        # Clamp to Int16 valid range (-32768 to 32767)
                        scaled = max(-32768, min(32767, scaled))

                        self.points[name].value = c104.Int16(scaled)

                # Update status
                for name in ['inlet_valve_status', 'outlet_valve_status', 'pump_status',
                            'auto_mode_status', 'alarm_overflow', 'alarm_low_level',
                            'alarm_high_pressure', 'tank_exploded']:
                    callback = WaterTankProtocolMapper.get_measurement_callback(
                        self.water_tank, name
                    )
                    if callback:
                        value = bool(callback())
                        self.points[name].value = value

                time.sleep(0.1)

            except Exception as e:
                self.logger.error(f"Update loop error: {e}")
                time.sleep(1)

    def stop(self):
        """Stop IEC-104 server"""
        self.running = False
        if self.update_thread:
            self.update_thread.join(timeout=2)
        if self.server:
            self.server.stop()
        self.logger.info("IEC-104 server stopped")

    def update_data_point(self, name: str, value: Any):
        """Update a data point value"""
        if name in self.points:
            if self.data_points[name].point_type == DataPointType.DIGITAL_INPUT:
                self.points[name].value = bool(value)
            else:
                self.points[name].value = c104.Int16(int(value))

    def get_ioa_map(self) -> str:
        """Get human-readable IOA mapping"""
        lines = []
        lines.append("=" * 80)
        lines.append("IEC 60870-5-104 IOA MAPPING - Water Tank")
        lines.append("=" * 80)
        lines.append(f"Common Address: {self.common_address}")
        lines.append("")

        # Group by type
        measurements = []
        status = []
        commands = []
        setpoints = []

        for name, dp in sorted(self.data_points.items(), key=lambda x: x[1].address):
            if dp.point_type == DataPointType.SCALED_VALUE:
                measurements.append((dp.address, name, "M_ME_NB_1", dp.description))
            elif dp.point_type == DataPointType.DIGITAL_INPUT:
                status.append((dp.address, name, "M_SP_NA_1", dp.description))
            elif dp.point_type == DataPointType.DIGITAL_OUTPUT:
                commands.append((dp.address, name, "C_SC_NA_1", dp.description))
            elif dp.point_type == DataPointType.ANALOG_OUTPUT:
                setpoints.append((dp.address, name, "C_SE_NC_1", dp.description))

        if measurements:
            lines.append("Measurements (M_ME_NB_1):")
            lines.append("-" * 80)
            for ioa, name, type_id, desc in measurements:
                lines.append(f"  IOA {ioa:3d}  {name:30s}  {desc}")

        if status:
            lines.append("\nStatus Points (M_SP_NA_1):")
            lines.append("-" * 80)
            for ioa, name, type_id, desc in status:
                lines.append(f"  IOA {ioa:3d}  {name:30s}  {desc}")

        if commands:
            lines.append("\nCommands (C_SC_NA_1):")
            lines.append("-" * 80)
            for ioa, name, type_id, desc in commands:
                lines.append(f"  IOA {ioa:3d}  {name:30s}  {desc}")

        if setpoints:
            lines.append("\nSetpoints (C_SE_NC_1):")
            lines.append("-" * 80)
            for ioa, name, type_id, desc in setpoints:
                lines.append(f"  IOA {ioa:3d}  {name:30s}  {desc}")

        lines.append("=" * 80)

        return "\n".join(lines)
