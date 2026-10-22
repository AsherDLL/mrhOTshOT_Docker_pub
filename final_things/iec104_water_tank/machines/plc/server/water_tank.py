"""
Water Tank Simulation with Automated Control Logic
"""
import time
import math
import random
import logging
from threading import Lock
import sys
import os
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from common.config import *


class WaterTank:
    """
    Simulates a water tank with:
    - Water level, pressure, and temperature sensors
    - Inlet and outlet valves (with variable position 0-100%)
    - Pump control
    - Automated control logic
    - Manual/Auto mode switching
    """

    def __init__(self):
        self.lock = Lock()

        # Tank state
        self.water_level = 50.0  # percentage
        self.pressure = 2.5  # bar
        self.temperature = TEMPERATURE_AMBIENT  # Celsius

        # Actuator states
        self.inlet_valve_position = 0.0  # 0-100%
        self.outlet_valve_position = 0.0  # 0-100%
        self.pump_running = False

        # Control mode
        self.auto_mode = True

        # Alarms
        self.alarm_overflow = False
        self.alarm_low_level = False
        self.alarm_high_pressure = False

        # Tank integrity
        self.tank_exploded = False

        # Simulation
        self.last_update_time = time.time()
        self.running = True

        logging.info("Water Tank initialized")

    def update(self):
        """Update tank physics simulation"""
        with self.lock:
            # If tank exploded, stop all operations
            if self.tank_exploded:
                self.inlet_valve_position = 0.0
                self.outlet_valve_position = 0.0
                self.pump_running = False
                return

            current_time = time.time()
            dt = current_time - self.last_update_time
            self.last_update_time = current_time

            # Calculate flow rates
            inlet_flow = (self.inlet_valve_position / 100.0) * INLET_FLOW_RATE
            outlet_flow = (self.outlet_valve_position / 100.0) * OUTLET_FLOW_RATE

            # Add pump contribution
            if self.pump_running:
                inlet_flow *= 1.5  # Pump increases inlet flow

            # Simulate leak
            leak_flow = LEAK_RATE if self.water_level > 0 else 0

            # Net flow in liters
            net_flow = inlet_flow - outlet_flow - leak_flow

            # Update water level (convert liters to percentage)
            volume_change = net_flow * dt
            level_change = (volume_change / TANK_CAPACITY) * 100.0
            self.water_level += level_change

            # Clamp water level
            if self.water_level < 0:
                self.water_level = 0
            elif self.water_level > 100:
                self.water_level = 100

            # Calculate pressure based on EMPTY SPACE (compressed air)
            # Using ideal gas law: P1*V1 = P2*V2
            # P2 = P1 * (V1 / V2), where V2 is the compressed volume (empty space)
            # If inlet valve is open and pump is running, air gets compressed into the empty space
            empty_percentage = 100.0 - self.water_level

            if empty_percentage < 1.0:
                # Almost no air space - pressure increases dramatically
                # Calculate compression ratio
                compression_ratio = 100.0 / max(0.1, empty_percentage)
                self.pressure = ATMOSPHERIC_PRESSURE * compression_ratio
            else:
                # Normal case: pressure from compressed air
                # Additional pressure from pump trying to push water in
                compression_ratio = 1.0 + (100.0 - empty_percentage) / 100.0
                pump_pressure = 2.0 if self.pump_running else 0
                self.pressure = ATMOSPHERIC_PRESSURE * compression_ratio + pump_pressure

            # Temperature simulation (ambient + small variations + heating from pump)
            temp_variation = random.uniform(-TEMPERATURE_VARIATION, TEMPERATURE_VARIATION)
            pump_heat = 0.5 if self.pump_running else 0
            self.temperature = TEMPERATURE_AMBIENT + temp_variation + pump_heat

            # Check for tank rupture
            if self.pressure >= MAX_PRESSURE_THRESHOLD:
                self.tank_exploded = True
                logging.critical(f"TANK EXPLOSION! Pressure reached {self.pressure:.2f} bar")
                return

            # Update alarms
            self.alarm_overflow = self.water_level >= OVERFLOW_LEVEL
            self.alarm_low_level = self.water_level <= MIN_SAFE_LEVEL
            self.alarm_high_pressure = self.pressure >= PRESSURE_DANGER_LEVEL

            # Run automated control logic if in auto mode
            if self.auto_mode:
                self._run_automation()

    def _run_automation(self):
        """Automated control logic"""
        # Auto-fill logic
        if self.water_level < AUTO_FILL_LOW_THRESHOLD:
            self.inlet_valve_position = 100.0
            self.pump_running = True
            logging.debug(f"AUTO: Low level ({self.water_level:.1f}%) - Opening inlet valve and pump")
        elif self.water_level > AUTO_FILL_HIGH_THRESHOLD:
            self.inlet_valve_position = 0.0
            self.pump_running = False
            logging.debug(f"AUTO: High level ({self.water_level:.1f}%) - Closing inlet valve and pump")

        # Overflow protection
        if self.water_level >= OVERFLOW_LEVEL:
            self.inlet_valve_position = 0.0
            self.outlet_valve_position = 100.0
            self.pump_running = False
            logging.warning(f"AUTO: OVERFLOW PROTECTION! Level: {self.water_level:.1f}%")

        # Low level protection (prevent pump damage)
        if self.water_level <= MIN_SAFE_LEVEL:
            self.outlet_valve_position = 0.0
            logging.warning(f"AUTO: LOW LEVEL PROTECTION! Level: {self.water_level:.1f}%")

        # Pressure regulation
        if self.pressure > AUTO_PRESSURE_MAX:
            self.outlet_valve_position = min(100.0, self.outlet_valve_position + 10.0)
        elif self.pressure < AUTO_PRESSURE_MIN and self.water_level > 20:
            self.inlet_valve_position = min(100.0, self.inlet_valve_position + 10.0)

    # Getters with thread safety
    def get_water_level(self):
        with self.lock:
            return self.water_level

    def get_pressure(self):
        with self.lock:
            return self.pressure

    def get_temperature(self):
        with self.lock:
            return self.temperature

    def get_inlet_valve_status(self):
        with self.lock:
            return self.inlet_valve_position > 0

    def get_outlet_valve_status(self):
        with self.lock:
            return self.outlet_valve_position > 0

    def get_pump_status(self):
        with self.lock:
            return self.pump_running

    def get_auto_mode(self):
        with self.lock:
            return self.auto_mode

    def get_alarm_overflow(self):
        with self.lock:
            return self.alarm_overflow

    def get_alarm_low_level(self):
        with self.lock:
            return self.alarm_low_level

    def get_alarm_high_pressure(self):
        with self.lock:
            return self.alarm_high_pressure

    def get_tank_exploded(self):
        with self.lock:
            return self.tank_exploded

    def get_inlet_valve_position(self):
        with self.lock:
            return self.inlet_valve_position

    def get_outlet_valve_position(self):
        with self.lock:
            return self.outlet_valve_position

    # Setters (manual commands from HMI)
    def set_inlet_valve(self, state):
        """Set inlet valve on/off (manual mode)"""
        with self.lock:
            if not self.auto_mode:
                self.inlet_valve_position = 100.0 if state else 0.0
                logging.info(f"MANUAL: Inlet valve set to {self.inlet_valve_position}%")
                return True
            logging.warning("Cannot control inlet valve in AUTO mode")
            return False

    def set_outlet_valve(self, state):
        """Set outlet valve on/off (manual mode)"""
        with self.lock:
            if not self.auto_mode:
                self.outlet_valve_position = 100.0 if state else 0.0
                logging.info(f"MANUAL: Outlet valve set to {self.outlet_valve_position}%")
                return True
            logging.warning("Cannot control outlet valve in AUTO mode")
            return False

    def set_pump(self, state):
        """Set pump on/off (manual mode)"""
        with self.lock:
            if not self.auto_mode:
                self.pump_running = state
                logging.info(f"MANUAL: Pump set to {'ON' if state else 'OFF'}")
                return True
            logging.warning("Cannot control pump in AUTO mode")
            return False

    def set_auto_mode(self, auto):
        """Switch between auto and manual mode"""
        with self.lock:
            self.auto_mode = auto
            logging.info(f"Mode switched to {'AUTO' if auto else 'MANUAL'}")
            return True

    def set_inlet_valve_position(self, position):
        """Set inlet valve position 0-100% (manual mode)"""
        with self.lock:
            if not self.auto_mode:
                self.inlet_valve_position = max(0.0, min(100.0, position))
                logging.info(f"MANUAL: Inlet valve position set to {self.inlet_valve_position}%")
                return True
            logging.warning("Cannot control inlet valve position in AUTO mode")
            return False

    def set_outlet_valve_position(self, position):
        """Set outlet valve position 0-100% (manual mode)"""
        with self.lock:
            if not self.auto_mode:
                self.outlet_valve_position = max(0.0, min(100.0, position))
                logging.info(f"MANUAL: Outlet valve position set to {self.outlet_valve_position}%")
                return True
            logging.warning("Cannot control outlet valve position in AUTO mode")
            return False

    def get_status_dict(self):
        """Get all status as dictionary"""
        with self.lock:
            return {
                'water_level': self.water_level,
                'pressure': self.pressure,
                'temperature': self.temperature,
                'inlet_valve_position': self.inlet_valve_position,
                'outlet_valve_position': self.outlet_valve_position,
                'pump_running': self.pump_running,
                'auto_mode': self.auto_mode,
                'alarm_overflow': self.alarm_overflow,
                'alarm_low_level': self.alarm_low_level,
                'alarm_high_pressure': self.alarm_high_pressure,
                'tank_exploded': self.tank_exploded
            }
