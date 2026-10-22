"""
Industrial Plant Simulator

Manages multiple industrial processes that run on a shared simulation clock.
Each protocol adapter is assigned to the process type that protocol is
actually used for in the real world:

  IEC-104, Modbus, DNP3    ->  Water Treatment Plant
  IEC 61850 / GOOSE        ->  Power Substation
  OPC-UA, OMRON FINS       ->  Gas Pipeline
  Mitsubishi MELSEC        ->  Gas Pipeline (MC Protocol)
  BACnet                   ->  Building HVAC
  Siemens S7, EtherNet/IP  ->  Manufacturing Line
  TriStation               ->  Safety System (cross-plant)
  M-Bus                    ->  Sensor Network (water plant meters)
  ABB AC500 (Modbus)        ->  Boiler House (steam plant)

An attacker scanning each protocol sees a DIFFERENT realistic process
with physically correct data for that domain.
"""

import time
import math
import random
import logging
import threading
from threading import Lock
from typing import Dict, Any

import sys, os
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from common.config import *


class ProcessFacade:
    """
    Wraps any industrial process to expose the WaterTank getter/setter
    interface that all existing protocol adapters expect.

    Maps generic names (water_level, pressure, temperature, inlet_valve, etc.)
    to process-specific measurements and commands via a configurable mapping.
    """

    def __init__(self, process, mapping: Dict[str, str]):
        """
        Args:
            process: An object with get_*/set_*/execute_command methods
            mapping: Maps standard names to process attribute/method names
                     e.g. {'water_level': 'reservoir_level', ...}
        """
        self.process = process
        self.mapping = mapping
        self.lock = Lock()

        # Internal state for unmapped points
        self._defaults = {
            'water_level': 50.0, 'pressure': 1.5, 'temperature': 20.0,
            'inlet_valve_actual': 0.0, 'outlet_valve_actual': 0.0,
            'inlet_valve_target': 0.0, 'outlet_valve_target': 0.0,
            'pump_running': False, 'auto_mode': True,
            'alarm_overflow': False, 'alarm_low_level': False,
            'alarm_high_pressure': False, 'tank_exploded': False,
            'sis_tripped': False, 'inlet_flow_rate': 0.0,
            'outlet_flow_rate': 0.0,
        }

    def _get(self, name: str):
        mapped = self.mapping.get(name)
        if mapped and hasattr(self.process, mapped):
            return getattr(self.process, mapped)
        if mapped and hasattr(self.process, f'get_{mapped}'):
            return getattr(self.process, f'get_{mapped}')()
        return self._defaults.get(name, 0)

    def update(self):
        if hasattr(self.process, 'update'):
            self.process.update()

    # Standard WaterTank getters
    def get_water_level(self): return self._get('water_level')
    def get_pressure(self): return self._get('pressure')
    def get_temperature(self): return self._get('temperature')
    def get_inlet_valve_status(self): return self._get('inlet_valve_status')
    def get_outlet_valve_status(self): return self._get('outlet_valve_status')
    def get_pump_status(self): return self._get('pump_running')
    def get_auto_mode(self): return self._get('auto_mode')
    def get_alarm_overflow(self): return self._get('alarm_overflow')
    def get_alarm_low_level(self): return self._get('alarm_low_level')
    def get_alarm_high_pressure(self): return self._get('alarm_high_pressure')
    def get_tank_exploded(self): return self._get('tank_exploded')
    def get_sis_tripped(self): return self._get('sis_tripped')
    def get_inlet_valve_position(self): return self._get('inlet_valve_actual')
    def get_outlet_valve_position(self): return self._get('outlet_valve_actual')
    def get_inlet_flow_rate(self): return self._get('inlet_flow_rate')
    def get_outlet_flow_rate(self): return self._get('outlet_flow_rate')

    # Standard WaterTank setters
    def set_inlet_valve(self, v):
        return self._exec_cmd('inlet_valve_command', v)
    def set_outlet_valve(self, v):
        return self._exec_cmd('outlet_valve_command', v)
    def set_pump(self, v):
        return self._exec_cmd('pump_command', v)
    def set_auto_mode(self, v):
        return self._exec_cmd('auto_mode_command', v)
    def set_sis_trip(self, v):
        return self._exec_cmd('sis_trip_command', v)
    def set_inlet_valve_position(self, v):
        return self._exec_cmd('inlet_valve_setpoint', v)
    def set_outlet_valve_position(self, v):
        return self._exec_cmd('outlet_valve_setpoint', v)

    def _exec_cmd(self, std_name: str, value) -> bool:
        mapped = self.mapping.get(std_name)
        if not mapped:
            return False
        # Boolean-to-analog: valve/speed commands that expect 0-100 float
        # but receive True/False from protocol adapters (BACnet BO, Modbus coil)
        if isinstance(value, bool) and any(k in std_name for k in ['valve_command', 'valve_setpoint']):
            value = 100.0 if value else 0.0
        if hasattr(self.process, 'execute_command'):
            return self.process.execute_command(mapped, value)
        if hasattr(self.process, f'set_{mapped}'):
            return getattr(self.process, f'set_{mapped}')(value)
        return False

    def get_status_dict(self):
        return {
            'water_level': self.get_water_level(),
            'pressure': self.get_pressure(),
            'temperature': self.get_temperature(),
            'pump_running': self.get_pump_status(),
            'auto_mode': self.get_auto_mode(),
            'alarm_overflow': self.get_alarm_overflow(),
            'alarm_low_level': self.get_alarm_low_level(),
            'alarm_high_pressure': self.get_alarm_high_pressure(),
            'tank_exploded': self.get_tank_exploded(),
            'sis_tripped': self.get_sis_tripped(),
        }


# ---------------------------------------------------------------------------
# Standalone process classes (no external deps, self-contained physics)
# ---------------------------------------------------------------------------

class PowerSubstation:
    """
    IEC 61850 power substation - 13.8kV distribution.
    Breakers, protection relays, voltage/current/frequency.
    """
    def __init__(self):
        self.lock = Lock()
        self.breaker1 = True  # incoming
        self.breaker2 = True  # bus-tie
        self.breaker3 = True  # outgoing
        self.relay_enabled = True
        self.relay_tripped = False
        self.voltage = 13.8     # kV
        self.frequency = 60.0   # Hz
        self.current = 500.0    # A
        self.power = 0.0        # MW
        self.xfmr_temp = 45.0   # transformer oil temp C
        self.blackout = False
        self.auto_mode = True
        self.last_t = time.time()

    def update(self):
        with self.lock:
            dt = min(time.time() - self.last_t, 1.0)
            self.last_t = time.time()

            closed = sum([self.breaker1, self.breaker2, self.breaker3])
            if closed == 0:
                self.blackout = True
                self.voltage = 0; self.frequency = 0; self.current = 0; self.power = 0
                return

            self.blackout = False
            base_v = 13.8 * (closed / 3.0) ** 0.5
            self.voltage = base_v + random.gauss(0, 0.02)
            load_factor = self.current / 500.0
            self.frequency = 60.0 - (load_factor - 1.0) * 0.3 + random.gauss(0, 0.01)
            if not self.breaker3:
                self.current = max(0, self.current - 200 * dt)
            else:
                self.current = 500 + random.gauss(0, 5)
            self.power = self.voltage * self.current * 0.85 / 1000  # MW
            self.xfmr_temp = 45.0 + self.power * 2 + random.gauss(0, 0.1)

            # Protection
            if self.relay_enabled and not self.relay_tripped:
                if self.current > 800:
                    self.relay_tripped = True
                    self.breaker1 = self.breaker2 = self.breaker3 = False

    def execute_command(self, cmd, val):
        with self.lock:
            cmds = {
                'Breaker1Cmd': lambda v: setattr(self, 'breaker1', bool(v)),
                'Breaker2Cmd': lambda v: setattr(self, 'breaker2', bool(v)),
                'Breaker3Cmd': lambda v: setattr(self, 'breaker3', bool(v)),
                'RelayEnableCmd': lambda v: setattr(self, 'relay_enabled', bool(v)),
                'AutoModeCmd': lambda v: setattr(self, 'auto_mode', bool(v)),
                'RelayResetCmd': lambda v: setattr(self, 'relay_tripped', False) if v else None,
            }
            fn = cmds.get(cmd)
            if fn:
                fn(val)
                return True
            return False


class GasPipelineStation:
    """
    OPC-UA gas pipeline compressor station.
    Compressor, valves, pressure, flow, temperature.
    """
    def __init__(self):
        self.lock = Lock()
        self.upstream_valve = True
        self.downstream_valve = True
        self.compressor_on = True
        self.compressor_speed = 50.0  # %
        self.inlet_pressure = 400.0   # PSI
        self.outlet_pressure = 800.0  # PSI
        self.flow_rate = 1000.0       # SCF/min
        self.gas_temp = 85.0          # F
        self.vibration = 2.5          # mm/s
        self.esd_active = False
        self.pipeline_rupture = False
        self.auto_mode = True
        self.last_t = time.time()

    def update(self):
        with self.lock:
            dt = min(time.time() - self.last_t, 1.0)
            self.last_t = time.time()

            if self.pipeline_rupture:
                self.inlet_pressure = self.outlet_pressure = 0
                self.flow_rate = 0; self.compressor_on = False
                return
            if self.esd_active:
                self.compressor_on = False
                self.upstream_valve = self.downstream_valve = False
                self.compressor_speed = 0
                return

            if self.upstream_valve:
                self.inlet_pressure = 400 + random.gauss(0, 3)
            else:
                self.inlet_pressure = max(0, self.inlet_pressure - 50 * dt)

            if self.compressor_on and self.inlet_pressure > 50:
                ratio = 1 + (self.compressor_speed / 100) * 1.5
                target = self.inlet_pressure * ratio
            else:
                target = self.inlet_pressure

            if not self.downstream_valve:
                self.outlet_pressure += 100 * dt * (self.compressor_speed / 100)
            else:
                self.outlet_pressure += (target - self.outlet_pressure) * dt
            self.outlet_pressure += random.gauss(0, 2)

            if self.outlet_pressure >= 1500:
                self.pipeline_rupture = True
                return

            if self.upstream_valve and self.downstream_valve:
                self.flow_rate = 1000 * (self.outlet_pressure / 800) * 0.5 + random.gauss(0, 15)
            else:
                self.flow_rate = max(0, self.flow_rate - 200 * dt)

            self.gas_temp = 85 + self.compressor_speed * 0.5 + random.gauss(0, 0.5)
            self.vibration = (self.compressor_speed / 100) * 5 + random.gauss(0, 0.2) if self.compressor_on else 0.1

    def execute_command(self, cmd, val):
        with self.lock:
            cmds = {
                'UpstreamValveCmd': lambda v: setattr(self, 'upstream_valve', bool(v)),
                'DownstreamValveCmd': lambda v: setattr(self, 'downstream_valve', bool(v)),
                'CompressorRunCmd': lambda v: setattr(self, 'compressor_on', bool(v)),
                'CompressorSpeedCmd': lambda v: setattr(self, 'compressor_speed', max(0, min(100, float(v)))),
                'ESDCmd': lambda v: setattr(self, 'esd_active', bool(v)),
                'AutoModeCmd': lambda v: setattr(self, 'auto_mode', bool(v)),
            }
            fn = cmds.get(cmd)
            if fn:
                fn(val)
                return True
            return False


class BuildingHVAC:
    """
    BACnet building automation - HVAC air handling unit.
    Hot summer scenario: outdoor 45°C, auto mode oscillates zone 20-40°C.
    Auto: cool above 40°C, heat below 20°C, ~1°C/min at full coil load.
    """
    # Hysteresis band - cool above 40°C, heat below 20°C
    COOL_ON_SETPOINT = 40.0   # start cooling above this
    HEAT_ON_SETPOINT = 20.0   # start heating below this
    OUTDOOR_TEMP     = 45.0   # fixed hot summer outdoor temperature

    def __init__(self):
        self.lock = Lock()
        self.zone_temp = 45.0        # C - start at outdoor (building not yet cooled)
        self.zone_humidity = 65.0    # %RH - hot humid outdoor
        self.supply_air_temp = 45.0  # C - set when fan starts
        self.return_air_temp = 45.0  # C
        self.outdoor_temp = self.OUTDOOR_TEMP
        self.hot_water_valve = 0.0   # % - heating valve (normally 0 in summer)
        self.chw_valve = 0.0         # % - cooling valve
        self.fan_running = True      # fan always on in auto
        self.fan_speed = 80.0        # %
        self.duct_pressure = 1.2     # inWC
        self.heating_active = False
        self.cooling_active = False
        self.freeze_alarm = False
        self.high_temp_alarm = False
        self.auto_mode = True
        self.last_t = time.time()

    def update(self):
        with self.lock:
            dt = min(time.time() - self.last_t, 1.0)
            self.last_t = time.time()

            # Fixed hot outdoor temp
            self.outdoor_temp = self.OUTDOOR_TEMP

            # Supply air: fixed once fan starts
            # Cooling coil: max -15°C below mixed air
            # Heating coil: max +15°C above mixed air
            if self.fan_running:
                mixed = self.outdoor_temp * 0.2 + self.return_air_temp * 0.8
                cooling_delta = -(self.chw_valve / 100.0) * 15.0
                heating_delta =  (self.hot_water_valve / 100.0) * 15.0
                self.supply_air_temp = mixed + heating_delta + cooling_delta
            else:
                self.supply_air_temp = self.outdoor_temp

            # Zone temperature physics - net HVAC effect = heating - cooling.
            # Demo-accelerated: a real building's thermal mass moves ~1°C/min, far too
            # slow to watch. 6°C/min drives a visible overheat within an attack window
            # (~38->50°C alarm in ~2 min). Tune here if the pace needs adjusting.
            RATE_DEG_PER_MIN = 6.0
            if self.fan_running:
                cool_effect = -(self.chw_valve / 100.0) * RATE_DEG_PER_MIN / 60.0
                heat_effect  =  (self.hot_water_valve / 100.0) * RATE_DEG_PER_MIN / 60.0
                # Small outdoor infiltration - hot building gains heat constantly
                infiltration = (self.outdoor_temp - self.zone_temp) * 0.0002
                self.zone_temp += (cool_effect + heat_effect + infiltration) * dt
            else:
                # Fan off: drift toward outdoor quickly
                self.zone_temp += (self.outdoor_temp - self.zone_temp) * 0.005 * dt

            self.zone_temp = max(0.0, min(55.0, self.zone_temp))
            self.return_air_temp = self.zone_temp

            # Humidity: outdoor 65%RH, cooling dehumidifies, heating dries further
            if self.fan_running:
                if self.chw_valve > 5:
                    target_rh = 65 - (self.chw_valve / 100.0) * 25  # cooling: 40-65%
                elif self.hot_water_valve > 5:
                    target_rh = 65 - (self.hot_water_valve / 100.0) * 20  # heating: 45-65%
                else:
                    target_rh = 65.0
            else:
                target_rh = 65.0
            self.zone_humidity += (target_rh - self.zone_humidity) * 0.015 * dt
            self.zone_humidity = max(30.0, min(90.0, self.zone_humidity))

            # Duct pressure: changes with fan speed
            if self.fan_running:
                load = max(self.chw_valve, self.hot_water_valve) / 100.0
                self.duct_pressure = (self.fan_speed / 100.0) * (1.5 + load * 0.5)
            else:
                self.duct_pressure = 0.0

            # AUTO mode: oscillate between 20-40°C, fan always on
            if self.auto_mode:
                self.fan_running = True
                if self.zone_temp > self.COOL_ON_SETPOINT:
                    # Too hot - full cooling, no heating
                    self.chw_valve       = min(100.0, self.chw_valve + 20 * dt)
                    self.hot_water_valve = max(0.0,   self.hot_water_valve - 20 * dt)
                elif self.zone_temp < self.HEAT_ON_SETPOINT:
                    # Too cold - full heating, no cooling
                    self.hot_water_valve = min(100.0, self.hot_water_valve + 20 * dt)
                    self.chw_valve       = max(0.0,   self.chw_valve - 20 * dt)
                # Between 20-40°C: hold current valve states (hysteresis)

            # Status flags
            self.heating_active = self.hot_water_valve > 5
            self.cooling_active = self.chw_valve > 5
            self.freeze_alarm    = self.zone_temp < 5
            self.high_temp_alarm = self.zone_temp > 50

    def execute_command(self, cmd, val):
        with self.lock:
            cmds = {
                'HotWaterValveCmd': lambda v: setattr(self, 'hot_water_valve', max(0, min(100, float(v)))),
                'ChilledWaterValveCmd': lambda v: setattr(self, 'chw_valve', max(0, min(100, float(v)))),
                'FanRunCmd': lambda v: setattr(self, 'fan_running', bool(v)),
                'FanSpeedCmd': lambda v: setattr(self, 'fan_speed', max(0, min(100, float(v)))),
                'AutoModeCmd': lambda v: setattr(self, 'auto_mode', bool(v)),
            }
            fn = cmds.get(cmd)
            if fn:
                fn(val)
                return True
            return False


class ManufacturingLine:
    """
    Siemens S7 manufacturing line - conveyor + motor + counter.
    Motor speed, position, product count, hydraulic pressure.
    """
    def __init__(self):
        self.lock = Lock()
        self.conveyor_running = True
        self.conveyor_speed = 60.0   # %
        self.motor_current = 45.0    # A
        self.motor_temp = 55.0       # C
        self.hydraulic_pressure = 180.0  # bar
        self.product_count = 0
        self.hopper_level = 75.0     # %
        self.position = 0.0          # encoder position (0-360)
        self.e_stop = False
        self.jam_alarm = False
        self.overtemp_alarm = False
        self.auto_mode = True
        self.last_t = time.time()
        self._count_accum = 0.0

    def update(self):
        with self.lock:
            dt = min(time.time() - self.last_t, 1.0)
            self.last_t = time.time()

            if self.e_stop:
                self.conveyor_running = False
                self.conveyor_speed = 0
                self.motor_current = 0
                return

            if self.conveyor_running:
                # Motor dynamics
                self.motor_current = 30 + self.conveyor_speed * 0.5 + random.gauss(0, 0.5)
                self.motor_temp += (self.motor_current * 0.02 - (self.motor_temp - 40) * 0.01) * dt * 10
                self.motor_temp += random.gauss(0, 0.05)

                # Position encoder (revolves)
                self.position = (self.position + self.conveyor_speed * dt * 10) % 360

                # Product counting
                self._count_accum += (self.conveyor_speed / 100.0) * dt * 2
                if self._count_accum >= 1.0:
                    self.product_count += int(self._count_accum)
                    self._count_accum -= int(self._count_accum)

                # Hopper depletes as products are made
                self.hopper_level = max(0, self.hopper_level - (self.conveyor_speed / 100) * dt * 0.5)
                if self.hopper_level <= 0 and self.auto_mode:
                    self.hopper_level = 80  # auto-refill

                # Hydraulic pressure
                self.hydraulic_pressure = 180 + self.conveyor_speed * 0.5 + random.gauss(0, 1)
            else:
                self.motor_current = max(0, self.motor_current - 20 * dt)
                self.motor_temp += (40 - self.motor_temp) * 0.02 * dt * 10
                self.hydraulic_pressure = max(0, self.hydraulic_pressure - 30 * dt)

            # Alarms
            self.jam_alarm = self.conveyor_running and self.motor_current > 80
            self.overtemp_alarm = self.motor_temp > 120

    def execute_command(self, cmd, val):
        with self.lock:
            cmds = {
                'ConveyorRunCmd': lambda v: setattr(self, 'conveyor_running', bool(v)),
                'ConveyorSpeedCmd': lambda v: setattr(self, 'conveyor_speed', max(0, min(100, float(v)))),
                'EStopCmd': lambda v: setattr(self, 'e_stop', bool(v)),
                'AutoModeCmd': lambda v: setattr(self, 'auto_mode', bool(v)),
                'ResetCounterCmd': lambda v: setattr(self, 'product_count', 0) if v else None,
            }
            fn = cmds.get(cmd)
            if fn:
                fn(val)
                return True
            return False


class BoilerHouse:
    """
    ABB AC500 boiler house -- steam generation plant.
    Steam pressure, drum level, burner, feedwater, safety systems.
    """
    def __init__(self):
        self.lock = Lock()
        self.steam_pressure = 12.0    # bar (normal operating)
        self.steam_temp = 185.0       # C
        self.feedwater_temp = 80.0    # C
        self.drum_level = 50.0        # %
        self.fuel_flow = 60.0         # % (gas burner)
        self.flue_gas_temp = 200.0    # C
        self.o2_percent = 3.5         # %
        self.burner_on = True
        self.feedwater_pump = True
        self.blowdown_valve = False   # opens to reduce drum level
        self.safety_valve_open = False  # opens if pressure > 16 bar
        self.flame_failure = False
        self.high_pressure_alarm = False  # > 14 bar
        self.low_water_alarm = False      # drum_level < 20%
        self.auto_mode = True
        self.last_t = time.time()

    def update(self):
        with self.lock:
            dt = min(time.time() - self.last_t, 1.0)
            self.last_t = time.time()

            # Flame failure shuts everything down
            if self.flame_failure:
                self.burner_on = False
                self.fuel_flow = 0
                self.steam_pressure = max(0, self.steam_pressure - 0.5 * dt)
                self.steam_temp = max(25, self.steam_temp - 2.0 * dt)
                self.flue_gas_temp = max(25, self.flue_gas_temp - 5.0 * dt)
                return

            # Steam pressure dynamics
            if self.burner_on and self.feedwater_pump:
                # Pressure rises when burner is on and feedwater is supplied
                heat_input = (self.fuel_flow / 100.0) * 0.3
                self.steam_pressure += heat_input * dt + random.gauss(0, 0.02)
            elif self.burner_on and not self.feedwater_pump:
                # Burner on but no water -- pressure rises slowly, dangerous
                self.steam_pressure += 0.1 * dt
            else:
                # Burner off -- pressure decays
                self.steam_pressure = max(0, self.steam_pressure - 0.2 * dt)

            # Safety valve opens automatically at 16 bar
            if self.steam_pressure > 16.0:
                self.safety_valve_open = True
                self.steam_pressure = max(12.0, self.steam_pressure - 1.0 * dt)
            elif self.steam_pressure < 14.0:
                self.safety_valve_open = False

            self.steam_pressure = max(0, self.steam_pressure)

            # Drum level dynamics
            if self.feedwater_pump:
                self.drum_level += 0.5 * dt + random.gauss(0, 0.05)
            else:
                self.drum_level -= 0.3 * dt

            if self.blowdown_valve:
                self.drum_level -= 1.0 * dt

            # Steam consumption draws down drum level when producing steam
            if self.burner_on:
                self.drum_level -= 0.2 * dt

            self.drum_level = max(0, min(100, self.drum_level))

            # Steam temperature tracks pressure
            self.steam_temp = 100.0 + self.steam_pressure * 7.0 + random.gauss(0, 0.3)

            # Feedwater temperature
            self.feedwater_temp = 80.0 + random.gauss(0, 0.5)

            # Flue gas temperature tracks fuel flow
            if self.burner_on:
                self.flue_gas_temp = 150.0 + self.fuel_flow * 1.5 + random.gauss(0, 1.0)
            else:
                self.flue_gas_temp = max(25, self.flue_gas_temp - 3.0 * dt)

            # O2 percentage (lower fuel flow = more excess air = higher O2)
            if self.burner_on:
                self.o2_percent = 6.0 - (self.fuel_flow / 100.0) * 4.0 + random.gauss(0, 0.1)
                self.o2_percent = max(0.5, min(10.0, self.o2_percent))

            # Alarms
            self.high_pressure_alarm = self.steam_pressure > 14.0
            self.low_water_alarm = self.drum_level < 20.0

            # Auto mode: maintain 50% drum level and 12 bar steam pressure
            if self.auto_mode:
                # Drum level control
                if self.drum_level < 45:
                    self.feedwater_pump = True
                    self.blowdown_valve = False
                elif self.drum_level > 55:
                    self.feedwater_pump = False
                    self.blowdown_valve = True
                else:
                    self.feedwater_pump = True
                    self.blowdown_valve = False

                # Pressure control via fuel flow
                if self.steam_pressure < 11.5:
                    self.fuel_flow = min(100, self.fuel_flow + 2.0 * dt)
                elif self.steam_pressure > 12.5:
                    self.fuel_flow = max(10, self.fuel_flow - 2.0 * dt)

    def execute_command(self, cmd, val):
        with self.lock:
            cmds = {
                'BurnerCmd': lambda v: setattr(self, 'burner_on', bool(v)),
                'FeedwaterPumpCmd': lambda v: setattr(self, 'feedwater_pump', bool(v)),
                'BlowdownCmd': lambda v: setattr(self, 'blowdown_valve', bool(v)),
                'FuelFlowCmd': lambda v: setattr(self, 'fuel_flow', max(0, min(100, float(v)))),
                'AutoModeCmd': lambda v: setattr(self, 'auto_mode', bool(v)),
                'EmergencyShutdownCmd': lambda v: setattr(self, 'flame_failure', bool(v)),
            }
            fn = cmds.get(cmd)
            if fn:
                fn(val)
                return True
            return False


class HeatingDistrict:
    """
    District heating loop - supply/return temps, circulation, heat exchanger.
    FrostyGoop's real-world target was Lviv district heating (Modbus TCP).
    """
    # heat-transfer rates (per second; dt-scaled in update)
    _LOSS_K = 0.009      # heat lost to the freezing outdoors, proportional to (supply - outdoor)
    _HEAT_GAIN = 2.6     # C/s the heat source (boiler/HX) adds to the supply while firing

    def __init__(self):
        self.lock = Lock()
        self.supply_temp = 62.0       # C - REAL supply water to buildings (starts warm, above setpoint)
        self.return_temp = 44.0       # C - cooled water back
        self.outdoor_temp = -30.0     # C (Ukrainian winter - Lviv January, the real FrostyGoop target)
        self.flow_rate = 120.0        # m3/h
        self.circulation_pump = True  # the pump keeps circulating; the HEAT SOURCE is the thermostat output
        self.pump_speed = 70.0        # %
        self.heat_exchanger_valve = 65.0  # % open
        self.boiler_temp = 90.0       # C (primary side)
        self.supply_pressure = 6.0    # bar
        self.return_pressure = 3.0    # bar
        self.differential_pressure = 3.0  # bar
        self.heat_output = 2.8        # MW thermal
        self.freeze_protection = False
        self.high_temp_alarm = False
        self.low_pressure_alarm = False
        self.auto_mode = True
        # --- FrostyGoop false-data-injection model -----------------------------------
        # The heating controller runs a thermostat: it fires the heat source whenever the
        # MEASURED supply temperature falls below a setpoint. FrostyGoop writes a fake
        # supply-temperature value into the controller's measurement register (Modbus),
        # holding a "warm enough" reading ABOVE the setpoint - the thermostat is deceived
        # into never firing the heater, while the REAL supply water collapses toward the
        # -30 C outside. The operator's HMI shows the injected value, so nothing looks wrong.
        self.supply_temp_setpoint = 55.0   # C - thermostat target
        self.deadband = 2.0                # C - hysteresis
        self.reported_supply_temp = 62.0   # C - value the controller/HMI measures (spoofable)
        self.spoof_hold = None             # None = honest; else a fixed reading held above the setpoint
        self.heater_on = False             # heat source firing = thermostat output
        self.pump_legit = True             # kept for compatibility (honest heating intent)
        self.last_t = time.time()

    def update(self):
        with self.lock:
            now = time.time()
            dt = min(now - self.last_t, 1.0)
            self.last_t = now
            self.outdoor_temp = -30.0 + 1.5 * math.sin(now * 0.0001) + random.gauss(0, 0.2)

            # (1) the supply water always loses heat to the freezing outdoors
            self.supply_temp += (self.outdoor_temp - self.supply_temp) * self._LOSS_K * dt

            # (2) the controller MEASURES the supply temp - but FrostyGoop can spoof it,
            #     holding a fixed "warm" reading above the setpoint. This is what the HMI shows.
            self.reported_supply_temp = ((self.supply_temp if self.spoof_hold is None
                                          else self.spoof_hold) + random.gauss(0, 0.05))

            # (3) hysteresis thermostat acts on the MEASURED (possibly spoofed) value: fire the
            #     heater below setpoint-deadband, stop above setpoint+deadband. When the reading
            #     is spoofed above setpoint, the heater never fires even as the real temp drops.
            if self.reported_supply_temp <= self.supply_temp_setpoint - self.deadband:
                self.heater_on = True
            elif self.reported_supply_temp >= self.supply_temp_setpoint + self.deadband:
                self.heater_on = False
            self.pump_legit = self.heater_on

            # (4) the heat source adds heat to the real supply while firing
            if self.heater_on:
                self.supply_temp += self._HEAT_GAIN * dt + random.gauss(0, 0.05)

            self.supply_temp = max(-15, min(110, self.supply_temp))
            self.return_temp = max(-15, self.supply_temp - 18 + random.gauss(0, 0.2))
            self.flow_rate = (120 * (self.pump_speed / 100.0) if self.circulation_pump
                              else max(0, self.flow_rate - 30 * dt))
            self.heat_output = max(0, self.flow_rate * 4.186 * max(0, self.supply_temp - self.return_temp) / 3600)
            self.supply_pressure = 6.0 + (self.pump_speed / 100.0) * 2 * (1 if self.circulation_pump else 0) + random.gauss(0, 0.05)
            self.return_pressure = max(0, self.supply_pressure - self.differential_pressure)

            self.freeze_protection = self.supply_temp < 35
            self.high_temp_alarm = self.supply_temp > 95
            self.low_pressure_alarm = self.supply_pressure < 2.0

    def execute_command(self, cmd, val):
        with self.lock:
            if cmd == 'SupplyTempInject':
                # FrostyGoop writes a FAKE supply temperature into the controller's measurement
                # register. That injected value becomes what the thermostat and HMI read: a value
                # above the setpoint keeps the heater from ever firing while the real water freezes.
                # Injecting 0 (the restore path) clears it and honest reporting resumes.
                fv = float(val)
                self.spoof_hold = fv if fv > 1.0 else None
                return True
            if cmd == 'CircPumpCmd':
                self.circulation_pump = bool(val)
            elif cmd == 'PumpSpeedCmd':
                self.pump_speed = max(0, min(100, float(val)))
            elif cmd == 'HeatExValveCmd':
                self.heat_exchanger_valve = max(0, min(100, float(val)))
            elif cmd == 'AutoModeCmd':
                self.auto_mode = bool(val)
            else:
                return False
            return True


class WaterUtility:
    """
    DNP3 water distribution utility - reservoir, chlorination, pumping.
    DNP3 is the dominant SCADA protocol in North American water utilities.
    """
    def __init__(self):
        self.lock = Lock()
        self.reservoir_level = 65.0   # %
        self.distribution_pressure = 55.0  # PSI
        self.chlorine_residual = 1.2  # mg/L (target 0.5-2.0)
        self.chlorine_dose_rate = 2.5 # mg/L injection
        self.turbidity = 0.3          # NTU
        self.ph_level = 7.2
        self.pump_station_1 = True
        self.pump_station_2 = True
        self.pump1_speed = 75.0       # %
        self.pump2_speed = 60.0       # %
        self.inlet_valve = True
        self.outlet_valve = True
        self.flow_rate = 850.0        # GPM
        self.daily_demand = 800.0     # GPM average
        self.low_reservoir_alarm = False
        self.high_chlorine_alarm = False
        self.low_pressure_alarm = False
        self.auto_mode = True
        self.last_t = time.time()

    def update(self):
        with self.lock:
            dt = min(time.time() - self.last_t, 1.0)
            self.last_t = time.time()

            demand = self.daily_demand * (1 + 0.3 * math.sin(time.time() * 0.0002))
            supply = 0
            if self.pump_station_1 and self.inlet_valve:
                supply += 500 * (self.pump1_speed / 100.0)
            if self.pump_station_2 and self.inlet_valve:
                supply += 400 * (self.pump2_speed / 100.0)

            if self.outlet_valve:
                net = (supply - demand) * dt * 0.001
            else:
                net = supply * dt * 0.001
            self.reservoir_level += net
            self.reservoir_level = max(0, min(100, self.reservoir_level + random.gauss(0, 0.05)))

            self.flow_rate = supply if self.outlet_valve else 0
            self.distribution_pressure = 40 + (self.reservoir_level / 100.0) * 30 + random.gauss(0, 0.5)

            decay = 0.001 * dt * 10
            injection = (self.chlorine_dose_rate / 5.0) * 0.002 * dt * 10 if self.flow_rate > 0 else 0
            self.chlorine_residual += injection - decay + random.gauss(0, 0.01)
            self.chlorine_residual = max(0, min(5.0, self.chlorine_residual))

            self.turbidity = 0.3 + random.gauss(0, 0.02)
            self.ph_level = 7.2 + random.gauss(0, 0.05)

            if self.auto_mode:
                if self.reservoir_level < 40:
                    self.pump1_speed = min(100, self.pump1_speed + 5 * dt)
                    self.pump2_speed = min(100, self.pump2_speed + 5 * dt)
                elif self.reservoir_level > 80:
                    self.pump1_speed = max(30, self.pump1_speed - 5 * dt)
                    self.pump2_speed = max(0, self.pump2_speed - 5 * dt)

            self.low_reservoir_alarm = self.reservoir_level < 20
            self.high_chlorine_alarm = self.chlorine_residual > 3.0
            self.low_pressure_alarm = self.distribution_pressure < 30

    def execute_command(self, cmd, val):
        with self.lock:
            cmds = {
                'Pump1Cmd': lambda v: setattr(self, 'pump_station_1', bool(v)),
                'Pump2Cmd': lambda v: setattr(self, 'pump_station_2', bool(v)),
                'Pump1SpeedCmd': lambda v: setattr(self, 'pump1_speed', max(0, min(100, float(v)))),
                'Pump2SpeedCmd': lambda v: setattr(self, 'pump2_speed', max(0, min(100, float(v)))),
                'InletValveCmd': lambda v: setattr(self, 'inlet_valve', bool(v)),
                'OutletValveCmd': lambda v: setattr(self, 'outlet_valve', bool(v)),
                'ChlorineDoseCmd': lambda v: setattr(self, 'chlorine_dose_rate', max(0, min(10, float(v)))),
                'AutoModeCmd': lambda v: setattr(self, 'auto_mode', bool(v)),
            }
            fn = cmds.get(cmd)
            if fn:
                fn(val)
                return True
            return False


class SensorNetwork:
    """
    M-Bus sensor gateway - multiple metered endpoints.
    Fuxnet (2024) bricked 87,000 Moskollector sensors via M-Bus.
    """
    def __init__(self):
        self.lock = Lock()
        self.sensor_count = 12
        self.sensors_online = 12
        self.flow_meter_1 = 45.2      # L/s
        self.flow_meter_2 = 38.7      # L/s
        self.pressure_sensor_1 = 4.2  # bar
        self.pressure_sensor_2 = 3.8  # bar
        self.temp_probe_1 = 18.5      # C
        self.temp_probe_2 = 19.2      # C
        self.level_sensor_1 = 72.0    # %
        self.level_sensor_2 = 58.0    # %
        self.energy_meter = 1250.5    # kWh cumulative
        self.battery_voltage = 3.6    # V (sensor node batteries)
        self.gateway_status = True    # True=ONLINE
        self.corrupted = False
        self.firmware_version = 0x0312
        self.comm_errors = 0
        self.auto_mode = True
        self.last_t = time.time()

    def update(self):
        with self.lock:
            dt = min(time.time() - self.last_t, 1.0)
            self.last_t = time.time()

            if not self.gateway_status:
                return

            if self.corrupted:
                self.flow_meter_1 = random.uniform(-100, 999)
                self.flow_meter_2 = random.uniform(-100, 999)
                self.pressure_sensor_1 = random.uniform(-10, 50)
                self.pressure_sensor_2 = random.uniform(-10, 50)
                self.comm_errors += random.randint(1, 10)
                self.sensors_online = random.randint(0, 4)
                return

            self.flow_meter_1 = 45.2 + 5 * math.sin(time.time() * 0.001) + random.gauss(0, 0.3)
            self.flow_meter_2 = 38.7 + 3 * math.sin(time.time() * 0.0015) + random.gauss(0, 0.2)
            self.pressure_sensor_1 = 4.2 + random.gauss(0, 0.05)
            self.pressure_sensor_2 = 3.8 + random.gauss(0, 0.04)
            self.temp_probe_1 = 18.5 + 2 * math.sin(time.time() * 0.0001) + random.gauss(0, 0.1)
            self.temp_probe_2 = 19.2 + 2 * math.sin(time.time() * 0.00012) + random.gauss(0, 0.1)
            self.level_sensor_1 = max(0, min(100, self.level_sensor_1 + random.gauss(0, 0.3)))
            self.level_sensor_2 = max(0, min(100, self.level_sensor_2 + random.gauss(0, 0.2)))
            self.energy_meter += 0.05 * dt
            self.battery_voltage = max(2.8, 3.6 - time.time() % 86400 * 0.000001 + random.gauss(0, 0.01))
            self.sensors_online = self.sensor_count

    def execute_command(self, cmd, val):
        with self.lock:
            cmds = {
                'GatewayResetCmd': lambda v: (setattr(self, 'gateway_status', True),
                                               setattr(self, 'corrupted', False),
                                               setattr(self, 'comm_errors', 0)),
                'GatewayShutdownCmd': lambda v: setattr(self, 'gateway_status', not bool(v)),
                'CorruptCmd': lambda v: setattr(self, 'corrupted', bool(v)),
                'AutoModeCmd': lambda v: setattr(self, 'auto_mode', bool(v)),
            }
            fn = cmds.get(cmd)
            if fn:
                fn(val)
                return True
            return False


class SafetySystem:
    """
    TriStation Safety Instrumented System (SIS) controller.
    TRITON/TRISIS (2017) targeted Schneider Triconex to disable safety protections.
    Monitors a process via IEC-104, trips on threshold breach.
    """
    def __init__(self):
        self.lock = Lock()
        self.armed = True
        self.tripped = False
        self.disabled = False         # TRITON's goal
        self.monitored_value = 15.0   # starts low, rises autonomously
        self.trip_threshold = 90.0    # trip above this
        self.reset_threshold = 80.0   # reset below this
        self.program_checksum = 0xA5B4C3D2
        self.firmware_version = 0x0310
        self.key_switch = 'RUN'       # RUN / PROGRAM / REMOTE
        self.output_energized = True  # fail-safe: de-energized = trip
        self.diagnostics_ok = True
        self.watchdog_timer = 0.0
        self.scan_cycle_ms = 100      # SIS scan rate
        self.last_trip_time = 0.0
        self.trip_count = 0
        self.auto_mode = True
        self.last_t = time.time()
        self._cooldown_remaining = 0.0   # seconds before re-arm after trip

    def update(self):
        with self.lock:
            dt = min(time.time() - self.last_t, 1.0)
            self.last_t = time.time()

            self.watchdog_timer += dt * 1000

            if self.disabled:
                self.armed = False
                self.output_energized = True
                # Process runs uncontrolled - value climbs without limit
                self.monitored_value = min(120.0, self.monitored_value + 3.0 * dt)
                return

            # Cooldown after trip before re-arming
            if self._cooldown_remaining > 0:
                self._cooldown_remaining -= dt
                self.monitored_value = max(15.0, self.monitored_value - 5.0 * dt)
                if self._cooldown_remaining <= 0:
                    self.armed = True
                    self.tripped = False
                    self.output_energized = True
                    self.monitored_value = 15.0
                return

            if not self.armed:
                return

            # Autonomous process value rising (3 units/second → hits 90 in ~25s)
            self.monitored_value = min(self.trip_threshold + 5, self.monitored_value + 3.0 * dt)

            if self.monitored_value >= self.trip_threshold:
                self.tripped = True
                self.armed = False
                self.output_energized = False
                self.last_trip_time = time.time()
                self.trip_count += 1
                self._cooldown_remaining = 3.0   # 3s before re-arm

    def execute_command(self, cmd, val):
        with self.lock:
            cmds = {
                'DisableSafetyCmd': lambda v: setattr(self, 'disabled', bool(v)),
                'ResetCmd': lambda v: (setattr(self, 'tripped', False),
                                       setattr(self, 'armed', True),
                                       setattr(self, 'disabled', False),
                                       setattr(self, 'output_energized', True)),
                'SetThresholdCmd': lambda v: setattr(self, 'trip_threshold', max(50, min(99, float(v)))),
                'KeySwitchCmd': lambda v: setattr(self, 'key_switch', str(v) if str(v) in ('RUN', 'PROGRAM', 'REMOTE') else self.key_switch),
                'UpdateValueCmd': lambda v: setattr(self, 'monitored_value', float(v)),
                'AutoModeCmd': lambda v: setattr(self, 'auto_mode', bool(v)),
            }
            fn = cmds.get(cmd)
            if fn:
                fn(val)
                return True
            return False


# ---------------------------------------------------------------------------
# Centrifuge Cascade (Stuxnet target - Natanz IR-1 centrifuges)
# ---------------------------------------------------------------------------

# Status codes for Centrifuge.status
CENTRIFUGE_NORMAL    = 0
CENTRIFUGE_OVERSPEED = 1
CENTRIFUGE_UNDERSTEED = 2
CENTRIFUGE_DAMAGED   = 3
CENTRIFUGE_DESTROYED = 4

# IR-1 centrifuge operating constants (Natanz Fuel Enrichment Plant)
CENTRIFUGE_NORMAL_HZ    = 1007.0   # design operating speed
CENTRIFUGE_OVERSPEED_LIMIT = 1200.0
CENTRIFUGE_STUXNET_FAST = 1410.0   # Stuxnet Phase 1 - overspeed
CENTRIFUGE_STUXNET_SLOW = 2.0      # Stuxnet Phase 2 - near-stop oscillation
CENTRIFUGE_UNDERSTEED_LIMIT = 50.0  # below this: bearing lubrication failure


class Centrifuge:
    """Single IR-1 centrifuge with rotor physics."""
    def __init__(self, centrifuge_id: int):
        self.id = centrifuge_id
        self.speed_hz = CENTRIFUGE_NORMAL_HZ + random.gauss(0, 2)
        self.setpoint_hz = CENTRIFUGE_NORMAL_HZ
        self.vibration_g = 0.15
        self.bearing_temp_c = 65.0 + random.gauss(0, 2)
        self.rotor_stress = 0.0    # cumulative 0–100%
        self.status = CENTRIFUGE_NORMAL

    def step(self, dt: float):
        if self.status == CENTRIFUGE_DESTROYED:
            self.speed_hz = 0.0
            self.vibration_g = 0.0
            return

        # Speed tracks setpoint with ~1s time constant (demo-accelerated; real = ~30s)
        tau = 1.0
        self.speed_hz += (self.setpoint_hz - self.speed_hz) * (1.0 - math.exp(-dt / tau))
        self.speed_hz += random.gauss(0, 0.5)

        # Vibration quadratic with fractional deviation from normal
        dev = abs(self.speed_hz - CENTRIFUGE_NORMAL_HZ) / CENTRIFUGE_NORMAL_HZ
        self.vibration_g = 0.15 + dev ** 2 * 8.0

        # Bearing temperature
        target_temp = 65.0 + self.vibration_g * 12.0
        self.bearing_temp_c += (target_temp - self.bearing_temp_c) * dt * 0.3
        self.bearing_temp_c = max(20.0, min(400.0, self.bearing_temp_c))

        # Rotor stress accumulation (demo-accelerated: 60s demo ≈ 18 months real)
        # Real Stuxnet rate would be ~0.001%/s; 4.0/s achieves destruction in ~40-60s
        if self.speed_hz > CENTRIFUGE_OVERSPEED_LIMIT:
            overshoot = (self.speed_hz - CENTRIFUGE_OVERSPEED_LIMIT) / (
                CENTRIFUGE_STUXNET_FAST - CENTRIFUGE_OVERSPEED_LIMIT)
            self.rotor_stress += overshoot * 4.0 * dt
        elif 1.0 < self.speed_hz < CENTRIFUGE_UNDERSTEED_LIMIT:
            undershoot = (CENTRIFUGE_UNDERSTEED_LIMIT - self.speed_hz) / CENTRIFUGE_UNDERSTEED_LIMIT
            self.rotor_stress += undershoot * 2.0 * dt
        else:
            self.rotor_stress = max(0.0, self.rotor_stress - 0.05 * dt)

        self.rotor_stress = min(100.0, self.rotor_stress)

        # Status
        if self.rotor_stress >= 100.0:
            self.status = CENTRIFUGE_DESTROYED
            self.speed_hz = 0.0
            self.setpoint_hz = 0.0
            self.vibration_g = 0.0
        elif self.speed_hz > CENTRIFUGE_OVERSPEED_LIMIT:
            self.status = CENTRIFUGE_OVERSPEED
        elif 0.0 < self.speed_hz < CENTRIFUGE_UNDERSTEED_LIMIT:
            self.status = CENTRIFUGE_UNDERSTEED
        elif self.rotor_stress > 60.0:
            self.status = CENTRIFUGE_DAMAGED
        else:
            self.status = CENTRIFUGE_NORMAL


class CentrifugeCascade:
    """
    3-unit IR-1 centrifuge cascade - Natanz Fuel Enrichment Plant Cascade A.
    Stuxnet (NSA/Unit 8200, 2010) specifically targeted these centrifuges by
    writing malicious speed setpoints to S7 data blocks while masking the
    manipulation from HMI operators via a rootkit.
    """
    def __init__(self):
        self.lock = Lock()
        self.centrifuges = [Centrifuge(i + 1) for i in range(3)]
        self.cascade_enable = True
        self.uf6_feed_rate = 100.0   # g/h uranium hexafluoride feed
        self.enrichment_level = 3.5  # % U-235 (Natanz target: 3.5% LEU)
        self.last_t = time.time()

    def update(self):
        with self.lock:
            dt = min(time.time() - self.last_t, 1.0)
            self.last_t = time.time()
            for c in self.centrifuges:
                c.step(dt)
            active = sum(1 for c in self.centrifuges if c.status != CENTRIFUGE_DESTROYED)
            self.enrichment_level = 3.5 * (active / 3.0) + random.gauss(0, 0.02)

    def execute_command(self, cmd: str, val) -> bool:
        with self.lock:
            cmds = {
                'SpeedCmd1': lambda v: setattr(self.centrifuges[0], 'setpoint_hz',
                    0.0 if self.centrifuges[0].status == CENTRIFUGE_DESTROYED
                    else max(0.0, min(2000.0, float(v)))),
                'SpeedCmd2': lambda v: setattr(self.centrifuges[1], 'setpoint_hz',
                    0.0 if self.centrifuges[1].status == CENTRIFUGE_DESTROYED
                    else max(0.0, min(2000.0, float(v)))),
                'SpeedCmd3': lambda v: setattr(self.centrifuges[2], 'setpoint_hz',
                    0.0 if self.centrifuges[2].status == CENTRIFUGE_DESTROYED
                    else max(0.0, min(2000.0, float(v)))),
                'CascadeEnableCmd': lambda v: setattr(self, 'cascade_enable', bool(v)),
                'ResetStressCmd': lambda v: [setattr(c, 'rotor_stress', 0.0)
                                              and setattr(c, 'status', CENTRIFUGE_NORMAL)
                                              and setattr(c, 'speed_hz', CENTRIFUGE_NORMAL_HZ)
                                              and setattr(c, 'setpoint_hz', CENTRIFUGE_NORMAL_HZ)
                                              for c in self.centrifuges] if v else None,
            }
            fn = cmds.get(cmd)
            if fn:
                fn(val)
                return True
            return False


# ---------------------------------------------------------------------------
# Process-to-WaterTank mappings
# ---------------------------------------------------------------------------

def create_substation_facade() -> ProcessFacade:
    """IEC 61850 power substation mapped to WaterTank interface."""
    proc = PowerSubstation()
    return ProcessFacade(proc, {
        'water_level':          'voltage',        # 13.8 kV scaled as "level"
        'pressure':             'current',        # 500 A as "pressure"
        'temperature':          'xfmr_temp',      # transformer temp
        'inlet_valve_status':   'breaker1',       # incoming breaker
        'outlet_valve_status':  'breaker3',       # outgoing breaker
        'pump_running':         'breaker2',       # bus-tie breaker
        'auto_mode':            'auto_mode',
        'alarm_overflow':       'blackout',
        'alarm_low_level':      'relay_tripped',
        'alarm_high_pressure':  'blackout',
        'tank_exploded':        'blackout',
        'sis_tripped':          'relay_tripped',
        'inlet_valve_actual':   'breaker1',
        'outlet_valve_actual':  'breaker3',
        # Commands
        'inlet_valve_command':  'Breaker1Cmd',
        'outlet_valve_command': 'Breaker3Cmd',
        'pump_command':         'Breaker2Cmd',
        'auto_mode_command':    'AutoModeCmd',
        'sis_trip_command':     'RelayResetCmd',
    })


def create_pipeline_facade() -> ProcessFacade:
    """OPC-UA / FINS gas pipeline mapped to WaterTank interface."""
    proc = GasPipelineStation()
    return ProcessFacade(proc, {
        'water_level':          'outlet_pressure',
        'pressure':             'inlet_pressure',
        'temperature':          'gas_temp',
        'inlet_valve_status':   'upstream_valve',
        'outlet_valve_status':  'downstream_valve',
        'pump_running':         'compressor_on',
        'auto_mode':            'auto_mode',
        'alarm_overflow':       'pipeline_rupture',
        'alarm_low_level':      'esd_active',
        'alarm_high_pressure':  'pipeline_rupture',
        'tank_exploded':        'pipeline_rupture',
        'sis_tripped':          'esd_active',
        'inlet_valve_actual':   'upstream_valve',
        'outlet_valve_actual':  'downstream_valve',
        'inlet_flow_rate':      'flow_rate',
        'outlet_flow_rate':     'vibration',
        # Commands
        'inlet_valve_command':  'UpstreamValveCmd',
        'outlet_valve_command': 'DownstreamValveCmd',
        'pump_command':         'CompressorRunCmd',
        'auto_mode_command':    'AutoModeCmd',
        'sis_trip_command':     'ESDCmd',
        'inlet_valve_setpoint': 'CompressorSpeedCmd',
    })


def create_hvac_facade() -> ProcessFacade:
    """BACnet building HVAC mapped to WaterTank interface."""
    proc = BuildingHVAC()
    return ProcessFacade(proc, {
        'water_level':          'zone_temp',         # 22C zone temp
        'pressure':             'duct_pressure',     # 1.2 inWC
        'temperature':          'supply_air_temp',   # supply air
        'inlet_valve_status':   'heating_active',
        'outlet_valve_status':  'cooling_active',
        'pump_running':         'fan_running',
        'auto_mode':            'auto_mode',
        'alarm_overflow':       'high_temp_alarm',
        'alarm_low_level':      'freeze_alarm',
        'alarm_high_pressure':  'high_temp_alarm',
        'tank_exploded':        'freeze_alarm',
        'sis_tripped':          'freeze_alarm',
        'inlet_valve_actual':   'hot_water_valve',
        'outlet_valve_actual':  'chw_valve',
        # Commands
        'inlet_valve_command':  'HotWaterValveCmd',
        'outlet_valve_command': 'ChilledWaterValveCmd',
        'pump_command':         'FanRunCmd',
        'auto_mode_command':    'AutoModeCmd',
        'inlet_valve_setpoint': 'FanSpeedCmd',
    })


def create_manufacturing_facade() -> ProcessFacade:
    """Siemens S7 manufacturing line mapped to WaterTank interface."""
    proc = ManufacturingLine()
    return ProcessFacade(proc, {
        'water_level':          'hopper_level',
        'pressure':             'hydraulic_pressure',
        'temperature':          'motor_temp',
        'inlet_valve_status':   'conveyor_running',
        'outlet_valve_status':  'conveyor_running',
        'pump_running':         'conveyor_running',
        'auto_mode':            'auto_mode',
        'alarm_overflow':       'jam_alarm',
        'alarm_low_level':      'overtemp_alarm',
        'alarm_high_pressure':  'jam_alarm',
        'tank_exploded':        'e_stop',
        'sis_tripped':          'e_stop',
        'inlet_valve_actual':   'conveyor_speed',
        'outlet_valve_actual':  'conveyor_speed',
        'inlet_flow_rate':      'motor_current',
        # Commands
        'inlet_valve_command':  'ConveyorRunCmd',
        'outlet_valve_command': 'ConveyorRunCmd',
        'pump_command':         'ConveyorRunCmd',
        'auto_mode_command':    'AutoModeCmd',
        'sis_trip_command':     'EStopCmd',
        'inlet_valve_setpoint': 'ConveyorSpeedCmd',
    })


def create_boiler_facade() -> ProcessFacade:
    """ABB AC500 boiler house mapped to WaterTank interface."""
    proc = BoilerHouse()
    return ProcessFacade(proc, {
        'water_level':          'drum_level',
        'pressure':             'steam_pressure',
        'temperature':          'steam_temp',
        'inlet_valve_status':   'feedwater_pump',
        'outlet_valve_status':  'blowdown_valve',
        'pump_running':         'burner_on',
        'auto_mode':            'auto_mode',
        'alarm_overflow':       'high_pressure_alarm',
        'alarm_low_level':      'low_water_alarm',
        'alarm_high_pressure':  'high_pressure_alarm',
        'tank_exploded':        'safety_valve_open',
        'sis_tripped':          'flame_failure',
        'inlet_valve_actual':   'fuel_flow',
        'outlet_valve_actual':  'blowdown_valve',
        # Commands
        'inlet_valve_command':  'FeedwaterPumpCmd',
        'outlet_valve_command': 'BlowdownCmd',
        'pump_command':         'BurnerCmd',
        'auto_mode_command':    'AutoModeCmd',
        'sis_trip_command':     'EmergencyShutdownCmd',
        'inlet_valve_setpoint': 'FuelFlowCmd',
    })


def create_heating_district_facade() -> ProcessFacade:
    """Modbus TCP district heating mapped to WaterTank interface."""
    proc = HeatingDistrict()
    return ProcessFacade(proc, {
        'water_level':          'supply_temp',
        'pressure':             'supply_pressure',
        'temperature':          'return_temp',
        'inlet_valve_status':   'circulation_pump',
        'outlet_valve_status':  'circulation_pump',
        'pump_running':         'circulation_pump',
        'auto_mode':            'auto_mode',
        'alarm_overflow':       'high_temp_alarm',
        'alarm_low_level':      'freeze_protection',
        'alarm_high_pressure':  'high_temp_alarm',
        'tank_exploded':        'freeze_protection',
        'sis_tripped':          'freeze_protection',
        'inlet_valve_actual':   'heat_exchanger_valve',
        'outlet_valve_actual':  'pump_speed',
        'inlet_flow_rate':      'flow_rate',
        'outlet_flow_rate':     'heat_output',
        # Commands
        'inlet_valve_command':  'HeatExValveCmd',
        'outlet_valve_command': 'CircPumpCmd',
        'pump_command':         'CircPumpCmd',
        'auto_mode_command':    'AutoModeCmd',
        'inlet_valve_setpoint': 'PumpSpeedCmd',
        'outlet_valve_setpoint': 'SupplyTempInject',   # FrostyGoop writes a fake supply temp here
    })


def create_water_utility_facade() -> ProcessFacade:
    """DNP3 water utility mapped to WaterTank interface."""
    proc = WaterUtility()
    return ProcessFacade(proc, {
        'water_level':          'reservoir_level',
        'pressure':             'distribution_pressure',
        'temperature':          'chlorine_residual',
        'inlet_valve_status':   'pump_station_1',   # BI[0] = PS1 status
        'outlet_valve_status':  'pump_station_2',   # BI[1] = PS2 status
        'pump_running':         'pump_station_1',   # BI[2] = PS1 (via pump_status cb)
        'auto_mode':            'auto_mode',
        'alarm_overflow':       'high_chlorine_alarm',
        'alarm_low_level':      'low_reservoir_alarm',
        'alarm_high_pressure':  'low_pressure_alarm',
        'tank_exploded':        'low_reservoir_alarm',
        'sis_tripped':          'low_pressure_alarm',
        'inlet_valve_actual':   'pump1_speed',
        'outlet_valve_actual':  'pump2_speed',
        'inlet_flow_rate':      'flow_rate',
        # Commands
        'inlet_valve_command':  'InletValveCmd',
        'outlet_valve_command': 'Pump2Cmd',         # BO[1] → stop pump station 2
        'pump_command':         'Pump1Cmd',          # BO[2] → stop pump station 1
        'auto_mode_command':    'AutoModeCmd',
        'inlet_valve_setpoint': 'Pump1SpeedCmd',
        'outlet_valve_setpoint':'Pump2SpeedCmd',
    })


def create_sensor_network_facade() -> ProcessFacade:
    """M-Bus sensor gateway mapped to WaterTank interface."""
    proc = SensorNetwork()
    return ProcessFacade(proc, {
        'water_level':          'level_sensor_1',
        'pressure':             'pressure_sensor_1',
        'temperature':          'temp_probe_1',
        'inlet_valve_status':   'gateway_status',
        'outlet_valve_status':  'gateway_status',
        'pump_running':         'gateway_status',
        'auto_mode':            'auto_mode',
        'alarm_overflow':       'corrupted',
        'alarm_low_level':      'corrupted',
        'alarm_high_pressure':  'corrupted',
        'tank_exploded':        'corrupted',
        'sis_tripped':          'corrupted',
        'inlet_valve_actual':   'flow_meter_1',
        'outlet_valve_actual':  'flow_meter_2',
        'inlet_flow_rate':      'flow_meter_1',
        'outlet_flow_rate':     'flow_meter_2',
        # Commands
        'inlet_valve_command':  'GatewayResetCmd',
        'outlet_valve_command': 'GatewayShutdownCmd',
        'pump_command':         'GatewayResetCmd',
        'auto_mode_command':    'AutoModeCmd',
    })


def create_safety_system_facade() -> ProcessFacade:
    """TriStation SIS mapped to WaterTank interface."""
    proc = SafetySystem()
    return ProcessFacade(proc, {
        'water_level':          'monitored_value',
        'pressure':             'trip_threshold',
        'temperature':          'watchdog_timer',
        'inlet_valve_status':   'armed',
        'outlet_valve_status':  'output_energized',
        'pump_running':         'armed',
        'auto_mode':            'auto_mode',
        'alarm_overflow':       'tripped',
        'alarm_low_level':      'disabled',
        'alarm_high_pressure':  'tripped',
        'tank_exploded':        'disabled',
        'sis_tripped':          'tripped',
        'inlet_valve_actual':   'monitored_value',
        'outlet_valve_actual':  'trip_threshold',
        # Commands
        'inlet_valve_command':  'ResetCmd',
        'outlet_valve_command': 'DisableSafetyCmd',
        'pump_command':         'ResetCmd',
        'auto_mode_command':    'AutoModeCmd',
        'sis_trip_command':     'DisableSafetyCmd',
        'inlet_valve_setpoint': 'SetThresholdCmd',
    })


# Protocol -> process type mapping
PROTOCOL_PROCESS_MAP = {
    'iec104':     'water_treatment',     # IEC-104 is standard for water utilities
    'modbus':     'heating_district',    # FrostyGoop targeted Modbus on heating infra
    'dnp3':       'water_utility_dnp3',  # DNP3 is dominant in North American water utilities
    'iec61850':   'power_substation',    # IEC 61850 is exclusively for power substations
    'opcua':      'gas_pipeline',        # OPC-UA used in oil & gas SCADA
    's7':         'centrifuge',           # S7 → Natanz centrifuge cascade (Stuxnet target)
    'bacnet':     'building_hvac',       # BACnet is exclusively building automation
    'fins':       'gas_pipeline',        # OMRON FINS used in pipeline/process SCADA
    'mbus':       'sensor_network',      # M-Bus sensor gateway (Fuxnet target)
    'tristation': 'safety_system',       # TriStation SIS (TRITON target)
    'enip':       'centrifuge',           # EtherNet/IP co-located with S7 on centrifuge PLC
    'melsec':     'gas_pipeline',        # Mitsubishi MELSEC process/pipeline SCADA
    'abb':        'boiler_house',        # ABB AC500 boiler/steam plant control
}


class PlantSimulator:
    """
    Manages the full industrial plant with multiple processes.
    Creates the right process for each protocol.
    """

    def __init__(self):
        self.logger = logging.getLogger('PlantSimulator')
        self.processes: Dict[str, Any] = {}  # process_type -> facade
        self.running = True

    def get_process_for_protocol(self, protocol: str):
        """
        Get or create the appropriate process for a protocol.
        Returns a ProcessFacade with WaterTank interface.
        """
        process_type = PROTOCOL_PROCESS_MAP.get(protocol, 'water_treatment')
        return self.get_process_by_type(process_type)

    def get_process_by_type(self, process_type: str):
        """Get or create a process by its type name (e.g. 'power_substation').
        Used in `--process` mode so every protocol on the container serves that one
        process - e.g. the power substation is reachable over BOTH IEC-104 (the
        Industroyer2/BlackEnergy3 attack surface) and IEC-61850, per config."""
        if process_type not in self.processes:
            self.processes[process_type] = self._create_process(process_type)
            self.logger.info(f"  Created {process_type} process")
        return self.processes[process_type]

    def _create_process(self, process_type: str):
        """Create a process by type."""
        from server.water_tank import WaterTank

        factories = {
            'water_treatment':    lambda: WaterTank(),
            'power_substation':   create_substation_facade,
            'gas_pipeline':       create_pipeline_facade,
            'building_hvac':      create_hvac_facade,
            'manufacturing':      create_manufacturing_facade,
            'centrifuge':         lambda: CentrifugeCascade(),
            'boiler_house':       create_boiler_facade,
            'heating_district':   create_heating_district_facade,
            'water_utility_dnp3': create_water_utility_facade,
            'sensor_network':     create_sensor_network_facade,
            'safety_system':      create_safety_system_facade,
        }
        factory = factories.get(process_type, factories['water_treatment'])
        return factory()

    def update_all(self):
        """Update all process simulations."""
        for proc in self.processes.values():
            try:
                proc.update()
            except Exception as e:
                self.logger.error(f"Process update error: {e}")

    def get_all_status(self) -> Dict[str, Dict]:
        """Get status from all processes."""
        result = {}
        for name, proc in self.processes.items():
            if hasattr(proc, 'get_status_dict'):
                result[name] = proc.get_status_dict()
        return result

    def stop(self):
        self.running = False
