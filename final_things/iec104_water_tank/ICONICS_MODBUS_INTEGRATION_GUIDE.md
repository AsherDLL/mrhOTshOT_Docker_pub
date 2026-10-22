# ICONICS Suite Integration Guide - Water Tank Modbus Device

## Document Information
- **Device Name:** Water Tank ICS Simulator
- **Protocol:** Modbus TCP
- **Vendor:** Water Tank Simulation
- **Model:** Multi-Protocol Water Tank
- **Product Code:** WT-SIM
- **Date Created:** January 8, 2026

---

## Table of Contents
1. [Quick Start](#quick-start)
2. [Device Overview](#device-overview)
3. [Network Configuration](#network-configuration)
4. [Complete Register Map](#complete-register-map)
5. [ICONICS GENESIS64 Setup](#iconics-genesis64-setup)
6. [Tag Configuration](#tag-configuration)
7. [Testing & Validation](#testing--validation)
8. [Troubleshooting](#troubleshooting)
9. [Advanced Configuration](#advanced-configuration)

---

## Quick Start

### Prerequisites
- ICONICS GENESIS64 or FrameWorX installed
- Water Tank Modbus server running
- Network connectivity to device

### 5-Minute Setup
1. Start the Modbus server: `python water_tank_server.py --protocol modbus`
2. Open ICONICS Workbench
3. Add new Modbus TCP device driver
4. Configure IP address and port
5. Import tags from this document
6. Test communication

---

## Device Overview

### Physical Process Description
The water tank system simulates a 1000-liter industrial water tank with:
- **Inlet valve** (variable position 0-100%)
- **Outlet valve** (variable position 0-100%)
- **Circulation pump** (on/off)
- **Level sensor** (0-100%)
- **Pressure sensor** (0-10 bar)
- **Temperature sensor** (0-100°C)
- **Automated control logic** (Auto/Manual modes)

### Control Modes
- **AUTO Mode:** Automated level control, maintains 20-80% level
- **MANUAL Mode:** Direct operator control of valves and pump

### Safety Features
- Overflow protection (>98% level)
- Low level protection (<10% level)
- High pressure alarm (>8 bar)
- Tank rupture simulation (>10 bar)

---

## Network Configuration

### Connection Parameters

| Parameter | Value | Notes |
|-----------|-------|-------|
| **Protocol** | Modbus TCP | TCP/IP based |
| **IP Address** | 127.0.0.1 (local) or server IP | Configurable |
| **Port** | 502 | Standard Modbus TCP port |
| **Unit ID (Slave ID)** | 1 | Default, can be changed |
| **Byte Order** | Big Endian (AB CD) | Modbus standard |
| **Word Order** | Big Endian | For 32-bit values |
| **Poll Rate** | 500-1000 ms | Recommended |
| **Timeout** | 5000 ms | Connection timeout |

### Starting the Modbus Server

```bash
# Default configuration
cd /opt/mrhOTshOT/final_things/iec104_water_tank
python water_tank_server.py --protocol modbus

# Custom configuration
python water_tank_server.py --protocol modbus --host 0.0.0.0 --port 502 --slave-id 1
```

---

## Complete Register Map

### Overview by Register Type

| Register Type | Count | Function Codes | Purpose |
|--------------|-------|----------------|---------|
| **Coils (0x)** | 4 | 01, 05, 15 | Digital commands |
| **Discrete Inputs (1x)** | 8 | 02 | Digital status/alarms |
| **Input Registers (3x)** | 3 | 04 | Analog measurements |
| **Holding Registers (4x)** | 2 | 03, 06, 16 | Analog setpoints |

---

### COILS (0x) - Digital Commands/Outputs

Function Codes: 01 (Read), 05 (Write Single), 15 (Write Multiple)

| Address | Name | Description | Data Type | Access |
|---------|------|-------------|-----------|--------|
| 0 | INLET_VALVE_COMMAND | Inlet valve on/off command | BOOL | R/W |
| 1 | OUTLET_VALVE_COMMAND | Outlet valve on/off command | BOOL | R/W |
| 2 | PUMP_COMMAND | Pump on/off command | BOOL | R/W |
| 3 | AUTO_MODE_COMMAND | Auto mode enable/disable | BOOL | R/W |

**Details:**
- **INLET_VALVE_COMMAND (Address 0)**
  - TRUE (1) = Open inlet valve (100% position)
  - FALSE (0) = Close inlet valve (0% position)
  - Only works in MANUAL mode
  
- **OUTLET_VALVE_COMMAND (Address 1)**
  - TRUE (1) = Open outlet valve (100% position)
  - FALSE (0) = Close outlet valve (0% position)
  - Only works in MANUAL mode
  
- **PUMP_COMMAND (Address 2)**
  - TRUE (1) = Start pump
  - FALSE (0) = Stop pump
  - Only works in MANUAL mode
  
- **AUTO_MODE_COMMAND (Address 3)**
  - TRUE (1) = Enable auto mode (automated control)
  - FALSE (0) = Disable auto mode (manual control)
  - Can be changed anytime

---

### DISCRETE INPUTS (1x) - Digital Status

Function Code: 02 (Read)

| Address | Name | Description | Data Type | Access |
|---------|------|-------------|-----------|--------|
| 0 | INLET_VALVE_STATUS | Inlet valve status (open/closed) | BOOL | R |
| 1 | OUTLET_VALVE_STATUS | Outlet valve status (open/closed) | BOOL | R |
| 2 | PUMP_STATUS | Pump running status | BOOL | R |
| 3 | AUTO_MODE_STATUS | Auto mode active status | BOOL | R |
| 8 | OVERFLOW_ALARM | Tank overflow alarm (>98%) | BOOL | R |
| 9 | LOW_LEVEL_ALARM | Low level alarm (<10%) | BOOL | R |
| 10 | HIGH_PRESSURE_ALARM | High pressure alarm (>8 bar) | BOOL | R |
| 11 | TANK_EXPLODED_ALARM | Tank explosion alarm (>10 bar) | BOOL | R |

**Details:**
- **Status Bits (0-3):** Reflect actual equipment state
- **Alarm Bits (8-11):** Active high (TRUE = alarm active)
- **Note:** Addresses 4-7 are reserved for future use

---

### INPUT REGISTERS (3x) - Analog Measurements

Function Code: 04 (Read)

| Address | Name | Description | Data Type | Range | Unit | Scaling |
|---------|------|-------------|-----------|-------|------|---------|
| 0 | WATER_LEVEL | Tank water level | UINT16 | 0-65535 | % | 0-100% |
| 1 | PRESSURE | Tank pressure | UINT16 | 0-65535 | bar | 0-10 bar |
| 2 | TEMPERATURE | Water temperature | UINT16 | 0-65535 | °C | 0-100°C |

**Scaling Formulas:**
```
Actual Value = (Register Value / 65535) × Max Range

Examples:
- Water Level (%) = (Register_Value / 65535) × 100
- Pressure (bar) = (Register_Value / 65535) × 10
- Temperature (°C) = (Register_Value / 65535) × 100
```

**Details:**
- **WATER_LEVEL (Address 0)**
  - Range: 0-100%
  - Normal operation: 20-80%
  - Low alarm: <10%
  - High alarm: >95%
  - Overflow: >98%
  
- **PRESSURE (Address 1)**
  - Range: 0-10 bar
  - Normal operation: 1-5 bar
  - High alarm: >8 bar
  - Critical: >10 bar (tank rupture)
  
- **TEMPERATURE (Address 2)**
  - Range: 0-100°C
  - Normal: ~20-22°C
  - Influenced by ambient and pump operation

---

### HOLDING REGISTERS (4x) - Analog Setpoints

Function Codes: 03 (Read), 06 (Write Single), 16 (Write Multiple)

| Address | Name | Description | Data Type | Range | Unit | Scaling |
|---------|------|-------------|-----------|-------|------|---------|
| 0 | INLET_VALVE_SETPOINT | Inlet valve position setpoint | UINT16 | 0-65535 | % | 0-100% |
| 1 | OUTLET_VALVE_SETPOINT | Outlet valve position setpoint | UINT16 | 0-65535 | % | 0-100% |

**Scaling Formulas:**
```
Register Value = (Desired Value / Max Range) × 65535

Examples:
- For 50% valve position: (50 / 100) × 65535 = 32768
- For 75% valve position: (75 / 100) × 65535 = 49151
```

**Details:**
- **INLET_VALVE_SETPOINT (Address 0)**
  - Sets inlet valve opening percentage
  - 0 = Fully closed, 65535 = Fully open (100%)
  - Only works in MANUAL mode
  
- **OUTLET_VALVE_SETPOINT (Address 1)**
  - Sets outlet valve opening percentage
  - 0 = Fully closed, 65535 = Fully open (100%)
  - Only works in MANUAL mode

---

## ICONICS GENESIS64 Setup

### Step 1: Install Modbus TCP Driver

1. Open **ICONICS Workbench**
2. Navigate to **System Configuration** → **Device Drivers**
3. Right-click and select **New Device Driver**
4. Choose **Modbus TCP/IP** from the list
5. Click **OK**

### Step 2: Configure Device Driver

**General Settings:**
```
Driver Name: WaterTankModbus
Description: Water Tank ICS Simulator - Modbus TCP
Driver Type: Modbus TCP/IP Client
```

**Network Settings:**
```
IP Address: 127.0.0.1 (or your server IP)
Port: 502
Unit ID: 1
Connection Timeout: 5000 ms
```

**Protocol Settings:**
```
Byte Order: Big Endian (AB CD)
Word Order: Big Endian (AB CD)
Zero Based Addressing: Yes
Max Items Per Request: 100
```

**Timing Settings:**
```
Scan Rate: 1000 ms (1 second)
Failed Connect Retry: 30000 ms (30 seconds)
Request Timeout: 5000 ms
```

### Step 3: Add Device

1. Right-click on **WaterTankModbus** driver
2. Select **New Device**
3. Configure:
   ```
   Device Name: WaterTank01
   IP Address: 127.0.0.1
   Port: 502
   Unit ID: 1
   Enabled: Yes
   ```

### Step 4: Create Tag Groups

Create organized tag groups for better management:

**Recommended Structure:**
```
WaterTank01/
├── Measurements/
│   ├── WaterLevel
│   ├── Pressure
│   └── Temperature
├── Status/
│   ├── InletValveStatus
│   ├── OutletValveStatus
│   ├── PumpStatus
│   └── AutoModeStatus
├── Alarms/
│   ├── OverflowAlarm
│   ├── LowLevelAlarm
│   ├── HighPressureAlarm
│   └── TankExplodedAlarm
├── Commands/
│   ├── InletValveCommand
│   ├── OutletValveCommand
│   ├── PumpCommand
│   └── AutoModeCommand
└── Setpoints/
    ├── InletValveSetpoint
    └── OutletValveSetpoint
```

---

## Tag Configuration

### Measurements Tags (Input Registers)

#### Water Level
```
Tag Name: WaterLevel
Description: Tank water level percentage
Data Type: Analog
Address: 400001 (or IR0 or 30001 depending on ICONICS notation)
Function Code: 04 (Read Input Registers)
Scaling: Linear
  - Raw Low: 0
  - Raw High: 65535
  - Scaled Low: 0.0
  - Scaled High: 100.0
Engineering Units: %
Scan Rate: 1000 ms
```

#### Pressure
```
Tag Name: Pressure
Description: Tank pressure in bar
Data Type: Analog
Address: 400002 (or IR1 or 30002)
Function Code: 04 (Read Input Registers)
Scaling: Linear
  - Raw Low: 0
  - Raw High: 65535
  - Scaled Low: 0.0
  - Scaled High: 10.0
Engineering Units: bar
Scan Rate: 1000 ms
Alarm: High > 8.0 bar
```

#### Temperature
```
Tag Name: Temperature
Description: Water temperature
Data Type: Analog
Address: 400003 (or IR2 or 30003)
Function Code: 04 (Read Input Registers)
Scaling: Linear
  - Raw Low: 0
  - Raw High: 65535
  - Scaled Low: 0.0
  - Scaled High: 100.0
Engineering Units: °C
Scan Rate: 1000 ms
```

### Status Tags (Discrete Inputs)

#### Inlet Valve Status
```
Tag Name: InletValveStatus
Description: Inlet valve open/closed status
Data Type: Digital
Address: 100001 (or DI0 or 10001)
Function Code: 02 (Read Discrete Inputs)
Scan Rate: 1000 ms
```

#### Outlet Valve Status
```
Tag Name: OutletValveStatus
Description: Outlet valve open/closed status
Data Type: Digital
Address: 100002 (or DI1 or 10002)
Function Code: 02 (Read Discrete Inputs)
Scan Rate: 1000 ms
```

#### Pump Status
```
Tag Name: PumpStatus
Description: Pump running status
Data Type: Digital
Address: 100003 (or DI2 or 10003)
Function Code: 02 (Read Discrete Inputs)
Scan Rate: 1000 ms
```

#### Auto Mode Status
```
Tag Name: AutoModeStatus
Description: Automatic mode active
Data Type: Digital
Address: 100004 (or DI3 or 10004)
Function Code: 02 (Read Discrete Inputs)
Scan Rate: 1000 ms
```

### Alarm Tags (Discrete Inputs)

#### Overflow Alarm
```
Tag Name: OverflowAlarm
Description: Tank overflow alarm (>98%)
Data Type: Digital
Address: 100009 (or DI8 or 10009)
Function Code: 02 (Read Discrete Inputs)
Scan Rate: 500 ms
Alarm: On = Critical
```

#### Low Level Alarm
```
Tag Name: LowLevelAlarm
Description: Low water level alarm (<10%)
Data Type: Digital
Address: 100010 (or DI9 or 10010)
Function Code: 02 (Read Discrete Inputs)
Scan Rate: 500 ms
Alarm: On = Warning
```

#### High Pressure Alarm
```
Tag Name: HighPressureAlarm
Description: High pressure alarm (>8 bar)
Data Type: Digital
Address: 100011 (or DI10 or 10011)
Function Code: 02 (Read Discrete Inputs)
Scan Rate: 500 ms
Alarm: On = High
```

#### Tank Exploded Alarm
```
Tag Name: TankExplodedAlarm
Description: Tank rupture/explosion (>10 bar)
Data Type: Digital
Address: 100012 (or DI11 or 10012)
Function Code: 02 (Read Discrete Inputs)
Scan Rate: 500 ms
Alarm: On = Critical
```

### Command Tags (Coils)

#### Inlet Valve Command
```
Tag Name: InletValveCommand
Description: Open/close inlet valve (manual mode)
Data Type: Digital
Address: 000001 (or C0 or 00001)
Function Code: 05 (Write Single Coil)
Access: Read/Write
```

#### Outlet Valve Command
```
Tag Name: OutletValveCommand
Description: Open/close outlet valve (manual mode)
Data Type: Digital
Address: 000002 (or C1 or 00002)
Function Code: 05 (Write Single Coil)
Access: Read/Write
```

#### Pump Command
```
Tag Name: PumpCommand
Description: Start/stop pump (manual mode)
Data Type: Digital
Address: 000003 (or C2 or 00003)
Function Code: 05 (Write Single Coil)
Access: Read/Write
```

#### Auto Mode Command
```
Tag Name: AutoModeCommand
Description: Enable/disable auto mode
Data Type: Digital
Address: 000004 (or C3 or 00004)
Function Code: 05 (Write Single Coil)
Access: Read/Write
```

### Setpoint Tags (Holding Registers)

#### Inlet Valve Setpoint
```
Tag Name: InletValveSetpoint
Description: Inlet valve position setpoint (manual mode)
Data Type: Analog
Address: 400001 (or HR0 or 40001)
Function Code: 06 (Write Single Register)
Scaling: Linear
  - Raw Low: 0
  - Raw High: 65535
  - Scaled Low: 0.0
  - Scaled High: 100.0
Engineering Units: %
Access: Read/Write
```

#### Outlet Valve Setpoint
```
Tag Name: OutletValveSetpoint
Description: Outlet valve position setpoint (manual mode)
Data Type: Analog
Address: 400002 (or HR1 or 40002)
Function Code: 06 (Write Single Register)
Scaling: Linear
  - Raw Low: 0
  - Raw High: 65535
  - Scaled Low: 0.0
  - Scaled High: 100.0
Engineering Units: %
Access: Read/Write
```

---

## Testing & Validation

### Step 1: Verify Server is Running

```bash
# Check if server is running
ps aux | grep water_tank_server

# Check if port 502 is listening
netstat -an | grep 502

# Or on macOS
lsof -i :502
```

### Step 2: Test Connectivity in ICONICS

1. Open **Workbench**
2. Navigate to your device **WaterTank01**
3. Right-click → **Device Diagnostics**
4. Verify:
   - Connection Status: **Connected**
   - Last Successful Read: Recent timestamp
   - Error Count: 0

### Step 3: Verify Tag Quality

1. Open **GraphWorX**
2. Create a test display
3. Add tags to watch window
4. Verify:
   - Quality: **Good**
   - Values updating
   - Timestamps current

### Step 4: Test Write Operations

**Test Auto Mode Switch:**
1. Write `1` to `AutoModeCommand`
2. Verify `AutoModeStatus` becomes `1`
3. Observe water level auto-regulating 20-80%

**Test Manual Control:**
1. Write `0` to `AutoModeCommand` (switch to manual)
2. Write `1` to `InletValveCommand`
3. Verify `InletValveStatus` becomes `1`
4. Observe `WaterLevel` increasing

### Step 5: Validate Scaling

Check that scaled values match expected ranges:

```
Water Level:
  - Raw: 32768 → Scaled: ~50%
  - Raw: 65535 → Scaled: 100%

Pressure:
  - Raw: 32768 → Scaled: ~5 bar
  - Raw: 65535 → Scaled: 10 bar

Temperature:
  - Raw: 13107 → Scaled: ~20°C
  - Raw: 32768 → Scaled: ~50°C
```

---

## Troubleshooting

### Cannot Connect to Device

**Symptoms:** Device status shows "Disconnected" or "Error"

**Solutions:**
1. Verify server is running:
   ```bash
   python water_tank_server.py --protocol modbus
   ```

2. Check IP address and port:
   ```bash
   # Test with Modbus client tool
   # Or telnet to check port
   telnet 127.0.0.1 502
   ```

3. Verify firewall settings allow port 502

4. Check Unit ID matches (default: 1)

### Tags Show "Bad Quality"

**Symptoms:** Tag quality shows Bad, Uncertain, or Error

**Solutions:**
1. Check address notation (ICONICS may use different formats)
2. Verify function code is correct for register type
3. Check scaling configuration
4. Review driver logs in Workbench

### Values Not Updating

**Symptoms:** Tags connected but values don't change

**Solutions:**
1. Check scan rate (recommended: 1000 ms)
2. Verify server simulation is running
3. Check if manual mode is active (auto mode has automation)
4. Review server logs for errors

### Cannot Write to Tags

**Symptoms:** Write commands fail or have no effect

**Solutions:**
1. Verify tag access is set to Read/Write
2. Check if device is in correct mode:
   - Commands only work in MANUAL mode
   - Auto mode command works anytime
3. Verify correct function code (05 for coils, 06 for holding registers)
4. Check value range (0-65535 for registers, 0-1 for coils)

### Scaling Issues

**Symptoms:** Values display incorrectly or out of range

**Solutions:**
1. Verify linear scaling configuration:
   ```
   Raw Low: 0
   Raw High: 65535
   Scaled Low: 0 (or minimum)
   Scaled High: 100 (or maximum)
   ```

2. Check byte order (should be Big Endian)

3. Ensure zero-based addressing is enabled

### High Pressure or Overflow Alarms

**Symptoms:** Alarms trigger unexpectedly

**This is normal behavior - the simulation includes physics!**

**Understanding:**
- Tank pressure increases as water level rises (compressed air)
- Pump operation adds additional pressure
- In auto mode with closed outlet valve, pressure can build quickly
- This simulates real industrial behavior

**Solutions:**
1. Switch to manual mode
2. Open outlet valve to reduce pressure
3. Reduce inlet flow
4. Stop pump
5. Monitor water level to prevent overflow

---

## Advanced Configuration

### Optimizing Poll Rates

For better performance, use different poll rates for different tag groups:

```
Measurements (analog): 1000 ms (1 second)
Status (digital): 1000 ms
Alarms (critical): 500 ms (faster response)
Commands: On-demand (event-based)
Setpoints: On-demand
```

### Alarming in ICONICS

Configure GENESIS64 alarms for critical conditions:

**High Priority Alarms:**
- Tank Exploded Alarm
- Overflow Alarm
- High Pressure Alarm (>8 bar)

**Medium Priority Alarms:**
- Low Level Alarm
- Water Level >90%

**Advisory:**
- Pressure >6 bar
- Water Level <15%

### Trending Configuration

Recommended trend tags:
- Water Level (primary process variable)
- Pressure (safety indicator)
- Temperature (process monitor)
- Inlet Valve Status
- Outlet Valve Status
- Pump Status

### Creating Custom Displays

**Recommended GraphWorX Elements:**

1. **Tank Visualization:**
   - Animated tank with level indicator
   - Color-coded by level (green/yellow/red)
   - Real-time percentage display

2. **Valve Controls:**
   - Toggle buttons for manual control
   - Position indicators
   - Disabled when in auto mode

3. **Gauges:**
   - Water Level: 0-100%
   - Pressure: 0-10 bar with red zone >8
   - Temperature: 0-100°C

4. **Alarm Banner:**
   - Active alarms display
   - Color-coded by severity
   - Acknowledgment functionality

5. **Mode Indicator:**
   - AUTO/MANUAL mode display
   - Mode switch button
   - Clear visual indication

### Multi-Device Setup

To monitor multiple water tanks:

```
Device 1: WaterTank01 - Unit ID 1 - Port 502
Device 2: WaterTank02 - Unit ID 2 - Port 503
Device 3: WaterTank03 - Unit ID 3 - Port 504
```

Start multiple servers:
```bash
# Terminal 1
python water_tank_server.py --protocol modbus --port 502 --slave-id 1

# Terminal 2
python water_tank_server.py --protocol modbus --port 503 --slave-id 2

# Terminal 3
python water_tank_server.py --protocol modbus --port 504 --slave-id 3
```

---

## Quick Reference Tables

### Address Quick Reference

| Tag | Type | Address | Function | Range |
|-----|------|---------|----------|-------|
| Water Level | Input Reg | 30001 | 04 | 0-100% |
| Pressure | Input Reg | 30002 | 04 | 0-10 bar |
| Temperature | Input Reg | 30003 | 04 | 0-100°C |
| Inlet Valve Status | Discrete | 10001 | 02 | 0/1 |
| Outlet Valve Status | Discrete | 10002 | 02 | 0/1 |
| Pump Status | Discrete | 10003 | 02 | 0/1 |
| Auto Mode Status | Discrete | 10004 | 02 | 0/1 |
| Overflow Alarm | Discrete | 10009 | 02 | 0/1 |
| Low Level Alarm | Discrete | 10010 | 02 | 0/1 |
| High Pressure Alarm | Discrete | 10011 | 02 | 0/1 |
| Tank Exploded | Discrete | 10012 | 02 | 0/1 |
| Inlet Valve Cmd | Coil | 00001 | 05 | 0/1 |
| Outlet Valve Cmd | Coil | 00002 | 05 | 0/1 |
| Pump Cmd | Coil | 00003 | 05 | 0/1 |
| Auto Mode Cmd | Coil | 00004 | 05 | 0/1 |
| Inlet Valve SP | Holding Reg | 40001 | 06 | 0-100% |
| Outlet Valve SP | Holding Reg | 40002 | 06 | 0-100% |

### Function Code Reference

| Code | Name | Description | Access |
|------|------|-------------|--------|
| 01 | Read Coils | Read digital outputs | Read |
| 02 | Read Discrete Inputs | Read digital inputs | Read |
| 03 | Read Holding Registers | Read analog outputs | Read |
| 04 | Read Input Registers | Read analog inputs | Read |
| 05 | Write Single Coil | Write digital output | Write |
| 06 | Write Single Register | Write analog output | Write |
| 15 | Write Multiple Coils | Write multiple digitals | Write |
| 16 | Write Multiple Registers | Write multiple analogs | Write |

---

## Support & Resources

### Log Files
- **Server Log:** `iec104_water_tank.log` (in server directory)
- **ICONICS Logs:** Check Workbench → System Diagnostics → Log Viewer

### Testing Tools
- **Modbus Poll** - Windows Modbus client for testing
- **QModMaster** - Cross-platform Modbus testing tool
- **pymodbus** - Python library for scripting tests

### Additional Documentation
- Main README: `README.md`
- Multi-Protocol Guide: `MULTI_PROTOCOL_README.md`
- Installation Guide: `INSTALLATION.md`
- Quick Start: `QUICKSTART.md`

---

## Revision History

| Version | Date | Author | Changes |
|---------|------|--------|---------|
| 1.0 | 2026-01-08 | System | Initial release |

---

**End of Document**

For additional support or questions, please refer to the project documentation or contact the system administrator.
