"""
Configuration for IEC-104 Water Tank Simulation
"""

# IEC-104 Server Configuration
IEC104_HOST = "0.0.0.0"
IEC104_PORT = 2404
COMMON_ADDRESS = 1

# Water Tank Physical Parameters
TANK_CAPACITY = 1000.0  # liters
TANK_HEIGHT = 2.0  # meters
TANK_DIAMETER = 0.8  # meters
MIN_SAFE_LEVEL = 10.0  # percentage
MAX_SAFE_LEVEL = 95.0  # percentage
OVERFLOW_LEVEL = 98.0  # percentage

# Flow Rates
INLET_FLOW_RATE = 50.0  # liters per second (when valve fully open)
OUTLET_FLOW_RATE = 30.0  # liters per second (when valve fully open)
LEAK_RATE = 0.5  # liters per second (simulated leak)

# Automation Logic Parameters
AUTO_FILL_LOW_THRESHOLD = 20.0  # percentage - start filling
AUTO_FILL_HIGH_THRESHOLD = 80.0  # percentage - stop filling
AUTO_PRESSURE_MIN = 1.0  # bar
AUTO_PRESSURE_MAX = 5.0  # bar

# Pressure Physics Parameters
ATMOSPHERIC_PRESSURE = 1.0  # bar (standard atmospheric pressure)
MAX_PRESSURE_THRESHOLD = 10.0  # bar (tank rupture threshold)
PRESSURE_DANGER_LEVEL = 8.0  # bar (high pressure warning)

# Simulation Parameters
SIMULATION_TICK_RATE = 0.1  # seconds
TEMPERATURE_AMBIENT = 20.0  # Celsius
TEMPERATURE_VARIATION = 2.0  # Celsius

# IEC-104 IOA (Information Object Address) Mapping
IOA_WATER_LEVEL = 100  # M_ME_NB_1 (Measured value, scaled value with Int16, range: -32768 to 32767)
IOA_PRESSURE = 101  # M_ME_NB_1
IOA_TEMPERATURE = 102  # M_ME_NB_1
IOA_INLET_VALVE_STATUS = 200  # M_SP_NA_1 (Single point information)
IOA_OUTLET_VALVE_STATUS = 201  # M_SP_NA_1
IOA_PUMP_STATUS = 202  # M_SP_NA_1
IOA_AUTO_MODE_STATUS = 203  # M_SP_NA_1
IOA_ALARM_OVERFLOW = 204  # M_SP_NA_1
IOA_ALARM_LOW_LEVEL = 205  # M_SP_NA_1
IOA_ALARM_HIGH_PRESSURE = 206  # M_SP_NA_1
IOA_TANK_EXPLODED = 207  # M_SP_NA_1

# Control IOAs (Commands from HMI)
IOA_INLET_VALVE_COMMAND = 300  # C_SC_NA_1 (Single command)
IOA_OUTLET_VALVE_COMMAND = 301  # C_SC_NA_1
IOA_PUMP_COMMAND = 302  # C_SC_NA_1
IOA_AUTO_MODE_COMMAND = 303  # C_SC_NA_1
IOA_INLET_VALVE_SETPOINT = 400  # C_SE_NC_1 (Set point command, short float)
IOA_OUTLET_VALVE_SETPOINT = 401  # C_SE_NC_1

# Logging
LOG_FILE = "iec104_water_tank.log"
LOG_LEVEL = "INFO"
