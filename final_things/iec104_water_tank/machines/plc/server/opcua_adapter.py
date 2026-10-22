"""
OPC-UA Protocol Adapter for Water Tank

Implements OPC-UA server for water tank control using Industry 4.0 standards.
Creates an organized node hierarchy following ISA-95 equipment model.
"""

import threading
import time
from typing import Dict, Any
from asyncua import Server as OPCUAServer, ua
from asyncua.common.methods import uamethod
import asyncio

from server.protocol_adapter import (
    ProtocolAdapter, DataPoint, DataPointType,
    WaterTankProtocolMapper
)


class OPCUAAdapter(ProtocolAdapter):
    """
    OPC-UA protocol adapter

    Node Hierarchy:
    - Objects/
      - WaterTank/
        - Measurements/
          - WaterLevel
          - Pressure
          - Temperature
        - Status/
          - InletValveStatus
          - OutletValveStatus
          - PumpStatus
          - AutoModeStatus
        - Alarms/
          - OverflowAlarm
          - LowLevelAlarm
          - HighPressureAlarm
        - Commands/
          - InletValveCommand
          - OutletValveCommand
          - PumpCommand
          - AutoModeCommand
        - Setpoints/
          - InletValveSetpoint
          - OutletValveSetpoint
    """

    def __init__(self, water_tank, config: Dict[str, Any]):
        """
        Initialize OPC-UA adapter

        Args:
            water_tank: WaterTank instance
            config: Configuration dict with keys:
                - host: Bind address (default: '0.0.0.0')
                - port: OPC-UA port (default: 4840)
                - namespace: Namespace URI (default: 'http://watertank.local')
                - server_name: Server name (default: 'WaterTank OPC-UA Server')
        """
        super().__init__(water_tank, config)

        self.host = config.get('host', '0.0.0.0')
        self.port = config.get('port', 4840)
        self.process_type = config.get('process_type', 'water_treatment')
        self.namespace_uri = config.get('namespace', self._default_namespace())
        self.server_name = config.get('server_name', self._default_server_name())

        self.server = None
        self.loop = None
        self.server_thread = None
        self.update_thread = None

        # Node storage
        self.ua_nodes = {}
        self.namespace_idx = None

        # Track previous command states for change detection
        self.previous_command_states = {}

    def initialize(self) -> bool:
        """Initialize OPC-UA server"""
        try:
            # Create new event loop for this thread
            self.loop = asyncio.new_event_loop()
            asyncio.set_event_loop(self.loop)

            # Initialize server
            self.server = OPCUAServer()
            self.loop.run_until_complete(self._async_initialize())

            self.logger.info(f"OPC-UA server initialized on {self.host}:{self.port}")
            self.logger.info(f"  Namespace: {self.namespace_uri}")
            self.logger.info(f"  Endpoint: opc.tcp://{self.host}:{self.port}/freeopcua/server/")

            return True

        except Exception as e:
            self.logger.error(f"Failed to initialize OPC-UA server: {e}")
            return False

    async def _async_initialize(self):
        """Async initialization of OPC-UA server"""
        # Setup server
        await self.server.init()
        self.server.set_endpoint(f"opc.tcp://{self.host}:{self.port}/freeopcua/server/")
        self.server.set_server_name(self.server_name)

        # Register namespace
        self.namespace_idx = await self.server.register_namespace(self.namespace_uri)

        # Create node hierarchy
        await self._create_node_hierarchy()

    async def _create_node_hierarchy(self):
        """Create OPC-UA node hierarchy for water tank"""
        # Get objects node
        objects = self.server.get_objects_node()

        # Create process-specific root object
        water_tank_obj = await objects.add_object(self.namespace_idx, self._get_object_name())

        # Create folders for organization
        measurements_folder = await water_tank_obj.add_folder(self.namespace_idx, "Measurements")
        status_folder = await water_tank_obj.add_folder(self.namespace_idx, "Status")
        alarms_folder = await water_tank_obj.add_folder(self.namespace_idx, "Alarms")
        commands_folder = await water_tank_obj.add_folder(self.namespace_idx, "Commands")
        setpoints_folder = await water_tank_obj.add_folder(self.namespace_idx, "Setpoints")

        # Get data point definitions
        data_points = WaterTankProtocolMapper.create_data_points()

        # Create nodes for each data point
        for name, definition in data_points.items():
            point_type = definition['type']

            # Determine folder and variable type
            if point_type in [DataPointType.SCALED_VALUE, DataPointType.ANALOG_INPUT]:
                folder = measurements_folder
                vartype = ua.VariantType.Float
                initial_value = 0.0
                writable = False
            elif point_type == DataPointType.DIGITAL_INPUT:
                # Status or alarms
                if 'alarm' in name:
                    folder = alarms_folder
                else:
                    folder = status_folder
                vartype = ua.VariantType.Boolean
                initial_value = False
                writable = False
            elif point_type == DataPointType.DIGITAL_OUTPUT:
                folder = commands_folder
                vartype = ua.VariantType.Boolean
                initial_value = False
                writable = True
            elif point_type == DataPointType.ANALOG_OUTPUT:
                folder = setpoints_folder
                vartype = ua.VariantType.Float
                initial_value = 0.0
                writable = True

            # Create variable node with process-specific name
            node_name = self._get_node_name(name)
            node = await folder.add_variable(
                self.namespace_idx,
                node_name,
                ua.Variant(initial_value, vartype)
            )

            # Set writable attribute for commands/setpoints
            if writable:
                await node.set_writable()

            # Add description using write_attribute
            if 'description' in definition:
                await node.write_attribute(
                    ua.AttributeIds.Description,
                    ua.DataValue(ua.Variant(ua.LocalizedText(definition['description']), ua.VariantType.LocalizedText))
                )

            # Add engineering units for analog values
            if vartype == ua.VariantType.Float:
                if 'level' in name.lower():
                    unit = "%"
                elif 'pressure' in name.lower():
                    unit = "bar"
                elif 'temperature' in name.lower():
                    unit = "°C"
                else:
                    unit = ""

                if unit:
                    await node.write_attribute(
                        ua.AttributeIds.DisplayName,
                        ua.DataValue(ua.Variant(ua.LocalizedText(f"{node_name} [{unit}]"), ua.VariantType.LocalizedText))
                    )

            # Create data point
            dp = DataPoint(
                address=node,
                point_type=point_type,
                name=name,
                description=definition.get('description', ''),
                min_value=definition.get('min'),
                max_value=definition.get('max')
            )

            self.register_data_point(name, dp)
            self.ua_nodes[name] = node

            # Register command callbacks
            callback = WaterTankProtocolMapper.get_command_callback(self.water_tank, name)
            if callback:
                self.register_command_callback(name, callback)

    # Process-specific OPC-UA tag names and object labels
    PROCESS_TAG_NAMES = {
        'gas_pipeline': {
            'object_name': 'GasPipeline',
            'water_level': 'OutletPressure', 'pressure': 'InletPressure', 'temperature': 'GasTemp',
            'inlet_valve_status': 'UpstreamValve', 'outlet_valve_status': 'DownstreamValve',
            'pump_status': 'CompressorRunning', 'auto_mode_status': 'AutoMode',
            'alarm_overflow': 'PipelineRupture', 'alarm_low_level': 'ESDActive',
            'alarm_high_pressure': 'OverpressAlarm', 'tank_exploded': 'PipelineRupture',
            'inlet_valve_command': 'UpstreamValveCmd', 'outlet_valve_command': 'DownstreamValveCmd',
            'pump_command': 'CompressorCmd', 'auto_mode_command': 'AutoModeCmd',
            'sis_trip_command': 'ESDCmd',
            'inlet_valve_setpoint': 'CompressorSpeedSetpoint', 'outlet_valve_setpoint': 'FlowRateSetpoint',
        },
        'power_substation': {
            'object_name': 'PowerSubstation',
            'water_level': 'Voltage_kV', 'pressure': 'Current_A', 'temperature': 'XfmrTemp',
            'inlet_valve_status': 'Breaker1_Incoming', 'outlet_valve_status': 'Breaker3_Outgoing',
            'pump_status': 'Breaker2_BusTie', 'auto_mode_status': 'AutoMode',
            'alarm_overflow': 'Blackout', 'alarm_low_level': 'RelayTripped',
            'alarm_high_pressure': 'OvercurrentAlarm', 'tank_exploded': 'ProtectionTrip',
            'inlet_valve_command': 'Breaker1Cmd', 'outlet_valve_command': 'Breaker3Cmd',
            'pump_command': 'Breaker2Cmd', 'auto_mode_command': 'AutoModeCmd',
            'inlet_valve_setpoint': 'VoltageSetpoint', 'outlet_valve_setpoint': 'FrequencySetpoint',
        },
        'manufacturing': {
            'object_name': 'ManufacturingLine',
            'water_level': 'HopperLevel', 'pressure': 'HydraulicPressure', 'temperature': 'MotorTemp',
            'inlet_valve_status': 'FeedValve', 'outlet_valve_status': 'DischargeValve',
            'pump_status': 'MotorRunning', 'auto_mode_status': 'AutoMode',
            'alarm_overflow': 'HopperOverflow', 'alarm_low_level': 'HopperLowLevel',
            'alarm_high_pressure': 'MotorOvertemp', 'tank_exploded': 'EmergencyStop',
            'inlet_valve_command': 'FeedValveCmd', 'outlet_valve_command': 'DischargeValveCmd',
            'pump_command': 'MotorCmd', 'auto_mode_command': 'AutoModeCmd',
            'inlet_valve_setpoint': 'FeedRateSetpoint', 'outlet_valve_setpoint': 'DischargeSetpoint',
        },
        'building_hvac': {
            'object_name': 'BuildingHVAC',
            'water_level': 'ZoneTemp', 'pressure': 'SupplyAirTemp', 'temperature': 'Humidity',
            'inlet_valve_status': 'HeatingValve', 'outlet_valve_status': 'CoolingValve',
            'pump_status': 'FanRunning', 'auto_mode_status': 'AutoMode',
            'alarm_overflow': 'HighTempAlarm', 'alarm_low_level': 'LowTempAlarm',
            'alarm_high_pressure': 'FilterAlarm', 'tank_exploded': 'CompressorFault',
            'inlet_valve_command': 'HeatingValveCmd', 'outlet_valve_command': 'CoolingValveCmd',
            'pump_command': 'FanCmd', 'auto_mode_command': 'AutoModeCmd',
            'inlet_valve_setpoint': 'HeatingSetpoint', 'outlet_valve_setpoint': 'CoolingSetpoint',
        },
        'boiler_house': {
            'object_name': 'BoilerHouse',
            'water_level': 'DrumLevel', 'pressure': 'SteamPressure', 'temperature': 'SteamTemp',
            'inlet_valve_status': 'FeedwaterPump', 'outlet_valve_status': 'BlowdownValve',
            'pump_status': 'BurnerOn', 'auto_mode_status': 'AutoMode',
            'alarm_overflow': 'HighPressAlarm', 'alarm_low_level': 'LowWaterAlarm',
            'alarm_high_pressure': 'FlameFailure', 'tank_exploded': 'SafetyValveOpen',
            'inlet_valve_command': 'FeedwaterCmd', 'outlet_valve_command': 'BlowdownCmd',
            'pump_command': 'BurnerCmd', 'auto_mode_command': 'AutoModeCmd',
            'inlet_valve_setpoint': 'FuelFlowSetpoint', 'outlet_valve_setpoint': 'SteamTempSetpoint',
        },
        'water_treatment': {
            'object_name': 'WaterTank',
            # Uses default _camel_case names - no remapping needed
        },
    }

    def _default_namespace(self):
        ns_map = {
            'gas_pipeline': 'http://gaspipeline.local',
            'power_substation': 'http://powersubstation.local',
            'manufacturing': 'http://manufacturing.local',
            'building_hvac': 'http://buildinghvac.local',
            'boiler_house': 'http://boilerhouse.local',
        }
        return ns_map.get(self.process_type, 'http://watertank.local')

    def _default_server_name(self):
        name_map = {
            'gas_pipeline': 'Gas Pipeline OPC-UA Server',
            'power_substation': 'Power Substation OPC-UA Server',
            'manufacturing': 'Manufacturing Line OPC-UA Server',
            'building_hvac': 'Building HVAC OPC-UA Server',
            'boiler_house': 'Boiler House OPC-UA Server',
        }
        return name_map.get(self.process_type, 'WaterTank OPC-UA Server')

    def _get_node_name(self, generic_name: str) -> str:
        """Get process-specific OPC-UA node name for a generic tag name."""
        tag_map = self.PROCESS_TAG_NAMES.get(self.process_type, {})
        return tag_map.get(generic_name, self._camel_case(generic_name))

    def _get_object_name(self) -> str:
        """Get process-specific root object name."""
        tag_map = self.PROCESS_TAG_NAMES.get(self.process_type, {})
        return tag_map.get('object_name', 'WaterTank')

    def _camel_case(self, snake_str: str) -> str:
        """Convert snake_case to CamelCase"""
        components = snake_str.split('_')
        return ''.join(x.title() for x in components)

    def start(self) -> bool:
        """Start OPC-UA server"""
        try:
            self.running = True

            # Start server in background thread
            self.server_thread = threading.Thread(
                target=self._run_server,
                daemon=True,
                name="OPCUAServerThread"
            )
            self.server_thread.start()

            # Give server time to start
            time.sleep(1)

            # Start update thread
            self.update_thread = threading.Thread(
                target=self._update_loop,
                daemon=True,
                name="OPCUAUpdateThread"
            )
            self.update_thread.start()

            self.logger.info(f"OPC-UA server started on opc.tcp://{self.host}:{self.port}/freeopcua/server/")
            return True

        except Exception as e:
            self.logger.error(f"Failed to start OPC-UA server: {e}")
            self.running = False
            return False

    def _run_server(self):
        """Run OPC-UA server (runs in background thread)"""
        try:
            async def start_server():
                async with self.server:
                    while self.running:
                        await asyncio.sleep(0.1)

            self.loop.run_until_complete(start_server())

        except Exception as e:
            self.logger.error(f"OPC-UA server error: {e}")
            self.running = False

    def _update_loop(self):
        """Update OPC-UA nodes from water tank (runs in background thread)"""
        while self.running:
            try:
                # Update all measurement and status nodes
                for name, dp in self.data_points.items():
                    if dp.point_type in [DataPointType.SCALED_VALUE, DataPointType.ANALOG_INPUT, DataPointType.DIGITAL_INPUT]:
                        callback = WaterTankProtocolMapper.get_measurement_callback(
                            self.water_tank, name
                        )
                        if callback:
                            value = callback()
                            node = self.ua_nodes[name]

                            # Convert value to appropriate type
                            # For Float nodes, ensure we use float32 to match VariantType.Float
                            if dp.point_type in [DataPointType.SCALED_VALUE, DataPointType.ANALOG_INPUT]:
                                # Python floats are double precision, convert to single precision
                                import struct
                                # Pack as float32 and unpack to ensure it's the right type
                                value = struct.unpack('f', struct.pack('f', float(value)))[0]

                            # Write value asynchronously using set_value with explicit variant type
                            if dp.point_type in [DataPointType.SCALED_VALUE, DataPointType.ANALOG_INPUT]:
                                variant = ua.Variant(value, ua.VariantType.Float)
                            else:
                                variant = ua.Variant(value, ua.VariantType.Boolean)

                            asyncio.run_coroutine_threadsafe(
                                node.set_value(variant),
                                self.loop
                            )

                # Check for command changes
                self._check_commands()

                time.sleep(0.1)  # Update rate: 10 Hz

            except Exception as e:
                self.logger.error(f"Update loop error: {e}")
                time.sleep(1)

    def _check_commands(self):
        """Check for command changes from OPC-UA clients"""
        for name, dp in self.data_points.items():
            if dp.point_type in [DataPointType.DIGITAL_OUTPUT, DataPointType.ANALOG_OUTPUT]:
                try:
                    node = self.ua_nodes[name]

                    # Read value asynchronously using get_value
                    future = asyncio.run_coroutine_threadsafe(
                        node.get_value(),
                        self.loop
                    )
                    value = future.result(timeout=0.5)

                    # Only execute callback if value changed
                    prev_value = self.previous_command_states.get(name)
                    if prev_value is None or prev_value != value:
                        self.previous_command_states[name] = value

                        # Execute command
                        callback = self.command_callbacks.get(name)
                        if callback:
                            success = callback(value)
                            if success:
                                self.logger.info(f"Command executed: {name} = {value}")

                except Exception as e:
                    # Silently ignore - likely timeout or node not ready
                    pass

    def stop(self):
        """Stop OPC-UA server"""
        self.running = False

        if self.update_thread:
            self.update_thread.join(timeout=2)

        if self.server_thread:
            self.server_thread.join(timeout=2)

        if self.loop:
            self.loop.close()

        self.logger.info("OPC-UA server stopped")

    def update_data_point(self, name: str, value: Any):
        """
        Update a data point value (manual override)

        Args:
            name: Data point name
            value: New value
        """
        if name in self.ua_nodes and name in self.data_points:
            node = self.ua_nodes[name]
            dp = self.data_points[name]

            # Convert value to appropriate type with correct variant
            if dp.point_type in [DataPointType.SCALED_VALUE, DataPointType.ANALOG_INPUT, DataPointType.ANALOG_OUTPUT]:
                # Convert to float32 to match VariantType.Float
                import struct
                float_value = struct.unpack('f', struct.pack('f', float(value)))[0]
                variant = ua.Variant(float_value, ua.VariantType.Float)
            else:
                # Digital values are Boolean
                variant = ua.Variant(bool(value), ua.VariantType.Boolean)

            asyncio.run_coroutine_threadsafe(
                node.set_value(variant),
                self.loop
            )

    def get_node_tree(self) -> str:
        """
        Get human-readable node tree

        Returns:
            Formatted string with node hierarchy
        """
        lines = []
        lines.append("=" * 80)
        lines.append("OPC-UA NODE TREE - Water Tank")
        lines.append("=" * 80)
        lines.append(f"Namespace: {self.namespace_uri}")
        lines.append(f"Endpoint: opc.tcp://{self.host}:{self.port}/freeopcua/server/")
        lines.append("")
        lines.append("Objects/")
        lines.append("  WaterTank/")

        # Group by category
        categories = {
            'Measurements': [],
            'Status': [],
            'Alarms': [],
            'Commands': [],
            'Setpoints': []
        }

        for name, dp in self.data_points.items():
            if dp.point_type in [DataPointType.SCALED_VALUE, DataPointType.ANALOG_INPUT]:
                categories['Measurements'].append((name, dp))
            elif dp.point_type == DataPointType.DIGITAL_INPUT:
                if 'alarm' in name:
                    categories['Alarms'].append((name, dp))
                else:
                    categories['Status'].append((name, dp))
            elif dp.point_type == DataPointType.DIGITAL_OUTPUT:
                categories['Commands'].append((name, dp))
            elif dp.point_type == DataPointType.ANALOG_OUTPUT:
                categories['Setpoints'].append((name, dp))

        for category, points in categories.items():
            if points:
                lines.append(f"    {category}/")
                for name, dp in sorted(points):
                    node_name = self._camel_case(name)
                    type_str = "Float" if dp.point_type in [DataPointType.SCALED_VALUE, DataPointType.ANALOG_INPUT, DataPointType.ANALOG_OUTPUT] else "Boolean"
                    lines.append(f"      {node_name} ({type_str}) - {dp.description}")

        lines.append("=" * 80)

        return "\n".join(lines)
