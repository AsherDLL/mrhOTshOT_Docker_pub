"""
Protocol Adapter - Abstract Base Class for Multi-Protocol Support

This module provides an abstraction layer for different industrial protocols:
- IEC 60870-5-104 (SCADA)
- Siemens S7 (PLC)
- Modbus TCP (Industrial automation)
- OPC-UA (Industry 4.0)
"""

from abc import ABC, abstractmethod
from typing import Dict, Any, Callable
from enum import Enum
import logging


class ProtocolType(Enum):
    """Supported industrial protocols"""
    IEC104 = "iec104"
    S7 = "s7"
    MODBUS = "modbus"
    OPCUA = "opcua"


class DataPointType(Enum):
    """Data point types (protocol-agnostic)"""
    # Measurements
    ANALOG_INPUT = "analog_input"       # Float measurements
    SCALED_VALUE = "scaled_value"       # Integer measurements

    # Status
    DIGITAL_INPUT = "digital_input"     # Boolean status

    # Commands
    DIGITAL_OUTPUT = "digital_output"   # Boolean commands
    ANALOG_OUTPUT = "analog_output"     # Float commands/setpoints


class DataPoint:
    """
    Protocol-agnostic data point representation

    Maps to protocol-specific representations:
    - IEC-104: Information Object Address (IOA)
    - S7: Data Block (DB) address
    - Modbus: Register address
    - OPC-UA: Node ID
    """

    def __init__(self, address: Any, point_type: DataPointType,
                 name: str, description: str = "",
                 min_value: float = None, max_value: float = None):
        """
        Initialize data point

        Args:
            address: Protocol-specific address
            point_type: Type of data point
            name: Human-readable name
            description: Optional description
            min_value: Minimum value (for analog points)
            max_value: Maximum value (for analog points)
        """
        self.address = address
        self.point_type = point_type
        self.name = name
        self.description = description
        self.min_value = min_value
        self.max_value = max_value
        self.value = None

    def __repr__(self):
        return f"DataPoint({self.name}, {self.point_type}, addr={self.address})"


class ProtocolAdapter(ABC):
    """
    Abstract base class for protocol adapters

    All protocol implementations must inherit from this class
    and implement the required methods.
    """

    def __init__(self, water_tank, config: Dict[str, Any]):
        """
        Initialize protocol adapter

        Args:
            water_tank: WaterTank instance to control
            config: Protocol-specific configuration
        """
        self.water_tank = water_tank
        self.config = config
        self.running = False
        self.logger = logging.getLogger(f"{self.__class__.__name__}")

        # Data point registry
        self.data_points: Dict[str, DataPoint] = {}

        # Command callbacks
        self.command_callbacks: Dict[str, Callable] = {}

    @abstractmethod
    def initialize(self) -> bool:
        """
        Initialize protocol-specific server/connection

        Returns:
            True if initialization successful, False otherwise
        """
        pass

    @abstractmethod
    def start(self) -> bool:
        """
        Start protocol server

        Returns:
            True if server started successfully, False otherwise
        """
        pass

    @abstractmethod
    def stop(self):
        """Stop protocol server"""
        pass

    @abstractmethod
    def update_data_point(self, name: str, value: Any):
        """
        Update a data point value

        Args:
            name: Data point name
            value: New value
        """
        pass

    def register_data_point(self, name: str, data_point: DataPoint):
        """
        Register a data point

        Args:
            name: Unique identifier for the data point
            data_point: DataPoint instance
        """
        self.data_points[name] = data_point
        self.logger.debug(f"Registered data point: {name} -> {data_point}")

    def register_command_callback(self, name: str, callback: Callable):
        """
        Register a callback for handling commands

        Args:
            name: Data point name
            callback: Function to call when command received
        """
        self.command_callbacks[name] = callback
        self.logger.debug(f"Registered command callback for: {name}")

    def get_protocol_name(self) -> str:
        """Get protocol name"""
        return self.__class__.__name__.replace("Adapter", "")

    def get_protocol_info(self) -> Dict[str, Any]:
        """
        Get protocol information

        Returns:
            Dictionary with protocol details
        """
        return {
            'protocol': self.get_protocol_name(),
            'running': self.running,
            'data_points': len(self.data_points),
            'config': self.config
        }


class WaterTankProtocolMapper:
    """
    Maps water tank parameters to protocol-agnostic data points

    This class defines the standard data point layout for the water tank,
    which is then translated to protocol-specific addresses by each adapter.
    """

    @staticmethod
    def create_data_points() -> Dict[str, Dict[str, Any]]:
        """
        Create standard water tank data point definitions

        Returns:
            Dictionary mapping data point names to their definitions
        """
        return {
            # Measurements (Analog Inputs)
            'water_level': {
                'type': DataPointType.SCALED_VALUE,
                'description': 'Water level percentage (0-100%)',
                'min': 0.0,
                'max': 100.0,
                'update_rate': 1000  # ms
            },
            'pressure': {
                'type': DataPointType.SCALED_VALUE,
                'description': 'Tank pressure in bar',
                'min': 0.0,
                'max': 15.0,
                'update_rate': 1000
            },
            'temperature': {
                'type': DataPointType.SCALED_VALUE,
                'description': 'Water temperature in Celsius',
                'min': 0.0,
                'max': 100.0,
                'update_rate': 1000
            },

            # Status Points (Digital Inputs)
            'inlet_valve_status': {
                'type': DataPointType.DIGITAL_INPUT,
                'description': 'Inlet valve open/closed status',
                'update_rate': 500
            },
            'outlet_valve_status': {
                'type': DataPointType.DIGITAL_INPUT,
                'description': 'Outlet valve open/closed status',
                'update_rate': 500
            },
            'pump_status': {
                'type': DataPointType.DIGITAL_INPUT,
                'description': 'Pump running/stopped status',
                'update_rate': 500
            },
            'auto_mode_status': {
                'type': DataPointType.DIGITAL_INPUT,
                'description': 'Auto/Manual mode status',
                'update_rate': 1000
            },

            # Alarms (Digital Inputs)
            'alarm_overflow': {
                'type': DataPointType.DIGITAL_INPUT,
                'description': 'Overflow alarm',
                'update_rate': 500
            },
            'alarm_low_level': {
                'type': DataPointType.DIGITAL_INPUT,
                'description': 'Low level alarm',
                'update_rate': 500
            },
            'alarm_high_pressure': {
                'type': DataPointType.DIGITAL_INPUT,
                'description': 'High pressure alarm',
                'update_rate': 500
            },
            'tank_exploded': {
                'type': DataPointType.DIGITAL_INPUT,
                'description': 'Tank rupture/explosion status',
                'update_rate': 500
            },

            # Command Points (Digital Outputs)
            'inlet_valve_command': {
                'type': DataPointType.DIGITAL_OUTPUT,
                'description': 'Inlet valve ON/OFF command',
            },
            'outlet_valve_command': {
                'type': DataPointType.DIGITAL_OUTPUT,
                'description': 'Outlet valve ON/OFF command',
            },
            'pump_command': {
                'type': DataPointType.DIGITAL_OUTPUT,
                'description': 'Pump ON/OFF command',
            },
            'auto_mode_command': {
                'type': DataPointType.DIGITAL_OUTPUT,
                'description': 'Auto/Manual mode command',
            },

            # Setpoint Commands (Analog Outputs)
            'inlet_valve_setpoint': {
                'type': DataPointType.ANALOG_OUTPUT,
                'description': 'Inlet valve position setpoint (0-100%)',
                'min': 0.0,
                'max': 100.0
            },
            'outlet_valve_setpoint': {
                'type': DataPointType.ANALOG_OUTPUT,
                'description': 'Outlet valve position setpoint (0-100%)',
                'min': 0.0,
                'max': 100.0
            }
        }

    @staticmethod
    def get_measurement_callback(water_tank, point_name: str) -> Callable:
        """
        Get callback function to read measurement from water tank

        Args:
            water_tank: WaterTank instance
            point_name: Data point name

        Returns:
            Callable that returns current value
        """
        callbacks = {
            'water_level': water_tank.get_water_level,
            'pressure': water_tank.get_pressure,
            'temperature': water_tank.get_temperature,
            'inlet_valve_status': water_tank.get_inlet_valve_status,
            'outlet_valve_status': water_tank.get_outlet_valve_status,
            'pump_status': water_tank.get_pump_status,
            'auto_mode_status': water_tank.get_auto_mode,
            'alarm_overflow': water_tank.get_alarm_overflow,
            'alarm_low_level': water_tank.get_alarm_low_level,
            'alarm_high_pressure': water_tank.get_alarm_high_pressure,
            'tank_exploded': water_tank.get_tank_exploded
        }
        return callbacks.get(point_name)

    @staticmethod
    def get_command_callback(water_tank, point_name: str) -> Callable:
        """
        Get callback function to execute command on water tank

        Args:
            water_tank: WaterTank instance
            point_name: Data point name

        Returns:
            Callable that executes the command
        """
        callbacks = {
            'inlet_valve_command': water_tank.set_inlet_valve,
            'outlet_valve_command': water_tank.set_outlet_valve,
            'pump_command': water_tank.set_pump,
            'auto_mode_command': water_tank.set_auto_mode,
            'inlet_valve_setpoint': water_tank.set_inlet_valve_position,
            'outlet_valve_setpoint': water_tank.set_outlet_valve_position
        }
        return callbacks.get(point_name)
