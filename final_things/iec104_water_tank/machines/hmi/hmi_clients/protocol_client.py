"""
Protocol Client Adapters for HMI

Provides a common interface for different industrial protocols to connect
to the water tank server from the HMI client.
"""

from abc import ABC, abstractmethod
from typing import Callable, Dict, Any, Optional
from dataclasses import dataclass


@dataclass
class DataUpdate:
    """Data update from server"""
    name: str
    value: Any
    timestamp: Optional[float] = None


class ProtocolClient(ABC):
    """
    Abstract base class for protocol client adapters

    All protocol clients must implement these methods to provide
    a unified interface for the HMI.
    """

    def __init__(self, host: str, port: int, config: Dict[str, Any] = None):
        """
        Initialize protocol client

        Args:
            host: Server IP address
            port: Server port
            config: Protocol-specific configuration
        """
        self.host = host
        self.port = port
        self.config = config or {}
        self.connected = False
        self.data_callback = None

    @abstractmethod
    def connect(self) -> bool:
        """
        Connect to server

        Returns:
            True if connected successfully, False otherwise
        """
        pass

    @abstractmethod
    def disconnect(self):
        """Disconnect from server"""
        pass

    @abstractmethod
    def send_command(self, command: str, value: bool) -> bool:
        """
        Send digital command to server

        Args:
            command: Command name (e.g., 'inlet_valve_command', 'pump_command')
            value: Command value (True/False, ON/OFF)

        Returns:
            True if command sent successfully
        """
        pass

    @abstractmethod
    def send_setpoint(self, setpoint: str, value: float) -> bool:
        """
        Send analog setpoint to server

        Args:
            setpoint: Setpoint name (e.g., 'inlet_valve_setpoint')
            value: Setpoint value (float)

        Returns:
            True if setpoint sent successfully
        """
        pass

    @abstractmethod
    def start_monitoring(self):
        """Start monitoring data from server (in background thread)"""
        pass

    @abstractmethod
    def stop_monitoring(self):
        """Stop monitoring data from server"""
        pass

    def register_data_callback(self, callback: Callable[[DataUpdate], None]):
        """
        Register callback for data updates

        Args:
            callback: Function to call when data is received
                     Signature: callback(DataUpdate)
        """
        self.data_callback = callback

    def _notify_data_update(self, name: str, value: Any, timestamp: float = None):
        """
        Notify registered callback of data update

        Args:
            name: Data point name
            value: Data point value
            timestamp: Optional timestamp
        """
        if self.data_callback:
            update = DataUpdate(name=name, value=value, timestamp=timestamp)
            self.data_callback(update)


class WaterTankDataPoints:
    """
    Standard data point names for water tank

    These names are used consistently across all protocols.
    """

    # Measurements (analog inputs)
    WATER_LEVEL = "water_level"
    PRESSURE = "pressure"
    TEMPERATURE = "temperature"

    # Status (digital inputs)
    INLET_VALVE_STATUS = "inlet_valve_status"
    OUTLET_VALVE_STATUS = "outlet_valve_status"
    PUMP_STATUS = "pump_status"
    AUTO_MODE_STATUS = "auto_mode_status"
    OVERFLOW_ALARM = "overflow_alarm"
    LOW_LEVEL_ALARM = "low_level_alarm"
    HIGH_PRESSURE_ALARM = "high_pressure_alarm"
    TANK_EXPLODED_ALARM = "tank_exploded_alarm"

    # Commands (digital outputs)
    INLET_VALVE_COMMAND = "inlet_valve_command"
    OUTLET_VALVE_COMMAND = "outlet_valve_command"
    PUMP_COMMAND = "pump_command"
    AUTO_MODE_COMMAND = "auto_mode_command"

    # Setpoints (analog outputs)
    INLET_VALVE_SETPOINT = "inlet_valve_setpoint"
    OUTLET_VALVE_SETPOINT = "outlet_valve_setpoint"

    @classmethod
    def get_all_measurements(cls):
        """Get all measurement point names"""
        return [cls.WATER_LEVEL, cls.PRESSURE, cls.TEMPERATURE]

    @classmethod
    def get_all_status(cls):
        """Get all status point names"""
        return [
            cls.INLET_VALVE_STATUS,
            cls.OUTLET_VALVE_STATUS,
            cls.PUMP_STATUS,
            cls.AUTO_MODE_STATUS,
            cls.OVERFLOW_ALARM,
            cls.LOW_LEVEL_ALARM,
            cls.HIGH_PRESSURE_ALARM,
            cls.TANK_EXPLODED_ALARM,
        ]

    @classmethod
    def get_all_commands(cls):
        """Get all command point names"""
        return [
            cls.INLET_VALVE_COMMAND,
            cls.OUTLET_VALVE_COMMAND,
            cls.PUMP_COMMAND,
            cls.AUTO_MODE_COMMAND,
        ]

    @classmethod
    def get_all_setpoints(cls):
        """Get all setpoint point names"""
        return [
            cls.INLET_VALVE_SETPOINT,
            cls.OUTLET_VALVE_SETPOINT,
        ]
