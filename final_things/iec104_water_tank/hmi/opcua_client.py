"""
OPC-UA Client Adapter for HMI

Handles communication with OPC-UA water tank server.
"""

import threading
import time
from opcua import Client as OPCUAClientLib
from opcua import ua
from typing import Dict
from hmi.protocol_client import ProtocolClient, WaterTankDataPoints


class OPCUAClient(ProtocolClient):
    """OPC-UA protocol client adapter"""

    # Node path mapping: data point name -> node path
    # Path relative to Objects/WaterTank
    NODE_MAP = {
        # Measurements
        WaterTankDataPoints.WATER_LEVEL: "Measurements/WaterLevel",
        WaterTankDataPoints.PRESSURE: "Measurements/Pressure",
        WaterTankDataPoints.TEMPERATURE: "Measurements/Temperature",

        # Status
        WaterTankDataPoints.INLET_VALVE_STATUS: "Status/InletValveStatus",
        WaterTankDataPoints.OUTLET_VALVE_STATUS: "Status/OutletValveStatus",
        WaterTankDataPoints.PUMP_STATUS: "Status/PumpStatus",
        WaterTankDataPoints.AUTO_MODE_STATUS: "Status/AutoModeStatus",
        WaterTankDataPoints.OVERFLOW_ALARM: "Alarms/OverflowAlarm",
        WaterTankDataPoints.LOW_LEVEL_ALARM: "Alarms/LowLevelAlarm",
        WaterTankDataPoints.HIGH_PRESSURE_ALARM: "Alarms/HighPressureAlarm",
        WaterTankDataPoints.TANK_EXPLODED_ALARM: "Alarms/TankExplodedAlarm",

        # Commands
        WaterTankDataPoints.INLET_VALVE_COMMAND: "Commands/InletValveCommand",
        WaterTankDataPoints.OUTLET_VALVE_COMMAND: "Commands/OutletValveCommand",
        WaterTankDataPoints.PUMP_COMMAND: "Commands/PumpCommand",
        WaterTankDataPoints.AUTO_MODE_COMMAND: "Commands/AutoModeCommand",

        # Setpoints
        WaterTankDataPoints.INLET_VALVE_SETPOINT: "Setpoints/InletValveSetpoint",
        WaterTankDataPoints.OUTLET_VALVE_SETPOINT: "Setpoints/OutletValveSetpoint",
    }

    def __init__(self, host: str, port: int = 4840, config: Dict = None):
        """Initialize OPC-UA client"""
        super().__init__(host, port, config)

        # Build endpoint URL
        self.endpoint = f"opc.tcp://{host}:{port}/freeopcua/server/"

        self.client = OPCUAClientLib(self.endpoint)
        self.nodes = {}
        self.monitoring = False
        self.monitor_thread = None
        self.subscription = None

    def connect(self) -> bool:
        """Connect to OPC-UA server"""
        try:
            self.client.connect()
            self.connected = True

            # Get all nodes
            self._setup_nodes()

            return True

        except Exception as e:
            print(f"OPC-UA connection error: {e}")
            self.connected = False
            return False

    def disconnect(self):
        """Disconnect from OPC-UA server"""
        self.stop_monitoring()

        if self.connected:
            self.client.disconnect()
            self.connected = False
            self.nodes = {}

    def send_command(self, command: str, value: bool) -> bool:
        """Send digital command"""
        try:
            if command not in self.nodes:
                return False

            node = self.nodes[command]
            node.set_value(ua.DataValue(ua.Variant(value, ua.VariantType.Boolean)))
            return True

        except Exception as e:
            print(f"Failed to send command {command}: {e}")
            return False

    def send_setpoint(self, setpoint: str, value: float) -> bool:
        """Send analog setpoint"""
        try:
            if setpoint not in self.nodes:
                return False

            node = self.nodes[setpoint]
            node.set_value(ua.DataValue(ua.Variant(value, ua.VariantType.Float)))
            return True

        except Exception as e:
            print(f"Failed to send setpoint {setpoint}: {e}")
            return False

    def start_monitoring(self):
        """Start monitoring data using OPC-UA subscriptions"""
        if not self.monitoring:
            self.monitoring = True

            # Create subscription for efficient monitoring
            try:
                self.subscription = self.client.create_subscription(500, self)  # 500ms interval

                # Subscribe to all monitored nodes
                for name in (WaterTankDataPoints.get_all_measurements() +
                           WaterTankDataPoints.get_all_status()):
                    if name in self.nodes:
                        node = self.nodes[name]
                        # Subscribe with data change callback
                        handle = self.subscription.subscribe_data_change(node)

            except Exception as e:
                print(f"Failed to create OPC-UA subscription: {e}")
                # Fallback to polling
                self.monitor_thread = threading.Thread(
                    target=self._monitor_loop,
                    daemon=True,
                    name="OPCUAMonitorThread"
                )
                self.monitor_thread.start()

    def stop_monitoring(self):
        """Stop monitoring data"""
        self.monitoring = False

        if self.subscription:
            try:
                self.subscription.delete()
            except:
                pass
            self.subscription = None

        if self.monitor_thread:
            self.monitor_thread.join(timeout=2)
            self.monitor_thread = None

    def datachange_notification(self, node, val, data):
        """OPC-UA subscription callback for data changes"""
        try:
            # Find which data point this node corresponds to
            for name, cached_node in self.nodes.items():
                if cached_node == node:
                    self._notify_data_update(name, val)
                    break
        except Exception as e:
            print(f"Error in datachange_notification: {e}")

    def _setup_nodes(self):
        """Setup all OPC-UA nodes"""
        try:
            # Get root objects node
            root = self.client.get_root_node()
            objects = root.get_child(["0:Objects"])

            # Get WaterTank folder (namespace index 2 for custom namespace)
            water_tank = objects.get_child(["2:WaterTank"])

            # Get all nodes
            for name, path in self.NODE_MAP.items():
                try:
                    # Parse path (e.g., "Measurements/WaterLevel")
                    path_parts = ["2:" + part for part in path.split("/")]
                    node = water_tank.get_child(path_parts)
                    self.nodes[name] = node
                except Exception as e:
                    print(f"Warning: Could not find node {name} at {path}: {e}")

        except Exception as e:
            print(f"Error setting up OPC-UA nodes: {e}")

    def _monitor_loop(self):
        """Polling monitoring loop (fallback if subscriptions fail)"""
        while self.monitoring and self.connected:
            try:
                # Read all measurements
                for name in WaterTankDataPoints.get_all_measurements():
                    if name in self.nodes:
                        value = self.nodes[name].get_value()
                        self._notify_data_update(name, value)

                # Read all status
                for name in WaterTankDataPoints.get_all_status():
                    if name in self.nodes:
                        value = self.nodes[name].get_value()
                        self._notify_data_update(name, value)

                # Poll rate: 500ms
                time.sleep(0.5)

            except Exception as e:
                print(f"OPC-UA monitor error: {e}")
                time.sleep(1)
