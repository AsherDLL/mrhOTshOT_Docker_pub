"""
Water Tank Simulation with Realistic Physics

Models a closed industrial water storage tank with:
- Hydrostatic pressure from water column (P = rho * g * h)
- Ullage gas compression when tank is sealed (ideal gas law)
- Thermal inertia and heat exchange with environment
- Valve slew rate (valves don't snap instantly)
- Pump curves (flow decreases with back-pressure, cavitation at low levels)
- Sensor noise for realistic measurement readings
- Configurable leak simulation

Physical parameters are based on a typical municipal water
treatment holding tank (1000L, 2m height, 0.8m diameter).
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

# Physical constants
WATER_DENSITY = 997.0       # kg/m^3 at 20 C
GRAVITY = 9.81              # m/s^2
BAR_PER_PASCAL = 1e-5       # 1 bar = 100000 Pa

# Realistic flow rates for a 1000L municipal tank
REALISTIC_INLET_MAX = 10.0  # L/s max through a 2-inch supply pipe (doubled for demo pacing)
REALISTIC_OUTLET_MAX = 3.0  # L/s max through a 1.5-inch drain pipe
REALISTIC_LEAK = 0.02       # L/s slow seepage

# Valve dynamics
VALVE_SLEW_RATE = 50.0      # percent per second (full stroke ~2s)

# Pump characteristics
PUMP_HEAD_MAX = 3.0         # bar - pump shutoff head
PUMP_FLOW_MAX = 6.0         # L/s - pump max flow (at zero head)
PUMP_CAVITATION_LEVEL = 5.0 # percent - pump loses prime below this

# Thermal model
SPECIFIC_HEAT_WATER = 4186.0  # J/(kg*K)
PUMP_HEAT_INPUT = 500.0       # Watts dissipated as heat when pump runs
TANK_UA = 10.0                # W/K overall heat transfer to ambient


class WaterTank:
    """
    High-fidelity water tank simulation.

    Designed so that an attacker scanning the protocols sees
    physically consistent, believable sensor data across all
    10 protocol interfaces simultaneously.
    """

    def __init__(self):
        self.lock = Lock()

        # --- Primary state variables ---
        self.water_volume = TANK_CAPACITY * 0.25   # liters (start at 25% - below auto-fill low, so auto fills immediately)
        self.water_temp = TEMPERATURE_AMBIENT       # Celsius
        self.ullage_pressure = ATMOSPHERIC_PRESSURE  # bar (gas above water)

        # --- Actuator physical positions (not commands) ---
        self.inlet_valve_actual = 0.0    # 0-100% actual position
        self.outlet_valve_actual = 0.0   # 0-100% actual position
        self.pump_running = False

        # --- Actuator targets (set by commands) ---
        self.inlet_valve_target = 0.0
        self.outlet_valve_target = 0.0

        # --- Derived measurements (computed each tick) ---
        self.water_level = 25.0          # percentage
        self.pressure = 2.5              # bar (at tank bottom)
        self.temperature = TEMPERATURE_AMBIENT
        self.inlet_flow_rate = 0.0       # L/s current
        self.outlet_flow_rate = 0.0      # L/s current

        # Control mode
        self.auto_mode = True

        # Alarms
        self.alarm_overflow = False
        self.alarm_low_level = False
        self.alarm_high_pressure = False

        # Tank integrity
        self.tank_exploded = False

        # SIS
        self.sis_tripped = False

        # Timing
        self.last_update_time = time.time()
        self.running = True

        # Sensor noise seeds (fixed per sensor for consistency)
        self._noise_phase = random.uniform(0, 2 * math.pi)

        logging.info("Water Tank initialized (realistic physics)")

    # ---- PHYSICS UPDATE ----

    def update(self):
        """Advance simulation by one time step."""
        with self.lock:
            if self.tank_exploded:
                self.inlet_valve_actual = 0.0
                self.outlet_valve_actual = 0.0
                self.pump_running = False
                return

            if self.sis_tripped:
                self.inlet_valve_target = 0.0
                self.outlet_valve_target = 100.0
                self.pump_running = False

            now = time.time()
            dt = min(now - self.last_update_time, 1.0)  # cap to 1s
            self.last_update_time = now

            # 1) Valve dynamics -- slew toward target
            self._update_valves(dt)

            # 2) Flow calculation
            inlet_flow, outlet_flow = self._calculate_flows(dt)

            # 3) Mass balance
            net_flow = inlet_flow - outlet_flow - self._leak_flow()
            dv = net_flow * dt
            self.water_volume = max(0.0, min(TANK_CAPACITY, self.water_volume + dv))

            self.inlet_flow_rate = inlet_flow
            self.outlet_flow_rate = outlet_flow

            # 4) Derived level
            self.water_level = (self.water_volume / TANK_CAPACITY) * 100.0

            # 5) Pressure model
            self._update_pressure()

            # 6) Thermal model
            self._update_temperature(dt, inlet_flow)

            # 7) Add sensor noise
            self._apply_sensor_noise()

            # 8) Check rupture
            if self.pressure >= MAX_PRESSURE_THRESHOLD:
                self.tank_exploded = True
                logging.critical(
                    f"TANK RUPTURE! Pressure {self.pressure:.2f} bar "
                    f"exceeded {MAX_PRESSURE_THRESHOLD} bar threshold"
                )
                return

            # 9) Alarms
            self.alarm_overflow = self.water_level >= OVERFLOW_LEVEL
            self.alarm_low_level = self.water_level <= MIN_SAFE_LEVEL
            self.alarm_high_pressure = self.pressure >= PRESSURE_DANGER_LEVEL

            # 10) Auto control
            if self.auto_mode:
                self._run_automation()

    def _update_valves(self, dt: float):
        """Slew valve positions toward targets at realistic rate."""
        max_move = VALVE_SLEW_RATE * dt
        for attr in ('inlet_valve', 'outlet_valve'):
            actual = getattr(self, f'{attr}_actual')
            target = getattr(self, f'{attr}_target')
            if abs(actual - target) < max_move:
                setattr(self, f'{attr}_actual', target)
            elif actual < target:
                setattr(self, f'{attr}_actual', actual + max_move)
            else:
                setattr(self, f'{attr}_actual', actual - max_move)

    def _calculate_flows(self, dt: float) -> tuple:
        """
        Calculate inlet and outlet flow rates (L/s).

        Uses valve position, back-pressure, and pump curve.
        """
        valve_fraction = self.inlet_valve_actual / 100.0

        if self.pump_running:
            # Pump curve: flow decreases linearly with back-pressure
            back_pressure = max(0, self.ullage_pressure - ATMOSPHERIC_PRESSURE)
            pump_efficiency = max(0.0, 1.0 - back_pressure / PUMP_HEAD_MAX)

            # Cavitation: pump loses prime at very low water levels
            if self.water_level < PUMP_CAVITATION_LEVEL:
                cav_factor = self.water_level / PUMP_CAVITATION_LEVEL
                pump_efficiency *= cav_factor

            pump_flow = PUMP_FLOW_MAX * pump_efficiency
            inlet = valve_fraction * (REALISTIC_INLET_MAX + pump_flow)
        else:
            inlet = valve_fraction * REALISTIC_INLET_MAX

        # Outlet: valve fraction * max flow * sqrt(head) for realistic drain
        outlet_valve_fraction = self.outlet_valve_actual / 100.0
        head_factor = math.sqrt(max(0, self.water_level) / 100.0)
        outlet = outlet_valve_fraction * REALISTIC_OUTLET_MAX * max(0.3, head_factor)

        return inlet, outlet

    def _leak_flow(self) -> float:
        if self.water_volume > 0:
            return REALISTIC_LEAK
        return 0.0

    def _update_pressure(self):
        """
        Pressure at tank bottom = hydrostatic + ullage gas.

        Hydrostatic: P = rho * g * h
        Ullage: ideal gas law P2 = P1 * V1/V2
        """
        fill_fraction = self.water_volume / TANK_CAPACITY
        water_height = fill_fraction * TANK_HEIGHT

        # Hydrostatic pressure (bar)
        hydrostatic = WATER_DENSITY * GRAVITY * water_height * BAR_PER_PASCAL

        # Ullage gas compression
        ullage_fraction = max(0.005, 1.0 - fill_fraction)
        reference_fraction = 0.50
        self.ullage_pressure = ATMOSPHERIC_PRESSURE * (reference_fraction / ullage_fraction)

        # Pump adds to ullage when forcing water in
        if self.pump_running and self.inlet_valve_actual > 0:
            pump_dp = 0.3 * (self.inlet_valve_actual / 100.0)
            self.ullage_pressure += pump_dp

        self.pressure = hydrostatic + self.ullage_pressure

    def _update_temperature(self, dt: float, inlet_flow: float):
        """Thermal model with inertia."""
        water_mass = self.water_volume * (WATER_DENSITY / 1000.0)
        if water_mass < 0.1:
            self.water_temp = TEMPERATURE_AMBIENT
            return

        heat_capacity = water_mass * SPECIFIC_HEAT_WATER

        q_pump = PUMP_HEAT_INPUT * dt if self.pump_running else 0.0
        q_ambient = -TANK_UA * (self.water_temp - TEMPERATURE_AMBIENT) * dt

        if inlet_flow > 0:
            inlet_mass = inlet_flow * dt * (WATER_DENSITY / 1000.0)
            mixing_heat = inlet_mass * SPECIFIC_HEAT_WATER * (TEMPERATURE_AMBIENT - self.water_temp)
        else:
            mixing_heat = 0.0

        delta_t = (q_pump + q_ambient + mixing_heat) / heat_capacity
        self.water_temp += delta_t

    def _apply_sensor_noise(self):
        """Add realistic sensor noise."""
        t = time.time()
        drift = 0.1 * math.sin(t * 0.05 + self._noise_phase)
        noise = random.gauss(0, 0.05)
        self.water_level = (self.water_volume / TANK_CAPACITY) * 100.0 + drift + noise
        self.pressure += random.gauss(0, 0.01)
        self.temperature = self.water_temp + random.gauss(0, 0.05)

    def _run_automation(self):
        """
        Hysteresis control loop:
          - Pump always OFF in auto mode
          - Level < 30%: open inlet, close outlet (fill)
          - Level > 70%: close inlet, open outlet (drain)
          - 30% <= level <= 70%: hold current state (hysteresis band, no change)
          - Safety overrides always apply regardless
        """
        level = self.water_volume / TANK_CAPACITY * 100.0

        # Pump always off in auto
        self.pump_running = False

        # Hysteresis band control
        if level < AUTO_FILL_LOW_THRESHOLD:       # below 30% - fill
            self.inlet_valve_target = 100.0
            self.outlet_valve_target = 0.0
        elif level > AUTO_FILL_HIGH_THRESHOLD:    # above 70% - drain
            self.inlet_valve_target = 0.0
            self.outlet_valve_target = 100.0
        # between 30-70%: maintain current targets (hysteresis, no override)

        # Safety overrides
        if level >= OVERFLOW_LEVEL:               # emergency drain
            self.inlet_valve_target = 0.0
            self.outlet_valve_target = 100.0

        if level <= MIN_SAFE_LEVEL:               # protect against dry-run
            self.outlet_valve_target = 0.0

    # ---- GETTERS (thread-safe) ----

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
            return self.inlet_valve_actual > 0.5

    def get_outlet_valve_status(self):
        with self.lock:
            return self.outlet_valve_actual > 0.5

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

    def get_sis_tripped(self):
        with self.lock:
            return self.sis_tripped

    def get_inlet_valve_position(self):
        with self.lock:
            return self.inlet_valve_actual

    def get_outlet_valve_position(self):
        with self.lock:
            return self.outlet_valve_actual

    def get_inlet_flow_rate(self):
        with self.lock:
            return self.inlet_flow_rate

    def get_outlet_flow_rate(self):
        with self.lock:
            return self.outlet_flow_rate

    # ---- SETTERS (commands from HMI / attacker) ----

    def set_inlet_valve(self, state):
        with self.lock:
            if self.auto_mode:
                self.auto_mode = False
                logging.info("AUTO -> MANUAL (operator command override)")
            self.inlet_valve_target = 100.0 if state else 0.0
            logging.info(f"Inlet valve target -> {'OPEN' if state else 'CLOSED'}")
            return True

    def set_outlet_valve(self, state):
        with self.lock:
            if self.auto_mode:
                self.auto_mode = False
                logging.info("AUTO -> MANUAL (operator command override)")
            self.outlet_valve_target = 100.0 if state else 0.0
            logging.info(f"Outlet valve target -> {'OPEN' if state else 'CLOSED'}")
            return True

    def set_pump(self, state):
        with self.lock:
            if self.auto_mode:
                self.auto_mode = False
                logging.info("AUTO -> MANUAL (operator command override)")
            self.pump_running = state
            logging.info(f"Pump -> {'ON' if state else 'OFF'}")
            return True

    def set_auto_mode(self, auto):
        with self.lock:
            self.auto_mode = auto
            logging.info(f"Mode -> {'AUTO' if auto else 'MANUAL'}")
            return True

    def set_sis_trip(self, state):
        with self.lock:
            self.sis_tripped = state
            if state:
                logging.critical("SIS TRIP ACTIVATED")
                self.inlet_valve_target = 0.0
                self.outlet_valve_target = 100.0
                self.pump_running = False
            else:
                logging.info("SIS trip reset")
            return True

    def set_inlet_valve_position(self, position):
        with self.lock:
            if self.auto_mode:
                self.auto_mode = False
            self.inlet_valve_target = max(0.0, min(100.0, position))
            logging.info(f"Inlet valve target -> {self.inlet_valve_target:.1f}%")
            return True

    def set_outlet_valve_position(self, position):
        with self.lock:
            if self.auto_mode:
                self.auto_mode = False
            self.outlet_valve_target = max(0.0, min(100.0, position))
            logging.info(f"Outlet valve target -> {self.outlet_valve_target:.1f}%")
            return True

    def get_status_dict(self):
        with self.lock:
            return {
                'water_level': self.water_level,
                'pressure': self.pressure,
                'temperature': self.temperature,
                'inlet_valve_position': self.inlet_valve_actual,
                'outlet_valve_position': self.outlet_valve_actual,
                'inlet_flow_rate': self.inlet_flow_rate,
                'outlet_flow_rate': self.outlet_flow_rate,
                'pump_running': self.pump_running,
                'auto_mode': self.auto_mode,
                'alarm_overflow': self.alarm_overflow,
                'alarm_low_level': self.alarm_low_level,
                'alarm_high_pressure': self.alarm_high_pressure,
                'tank_exploded': self.tank_exploded,
                'sis_tripped': self.sis_tripped,
            }
