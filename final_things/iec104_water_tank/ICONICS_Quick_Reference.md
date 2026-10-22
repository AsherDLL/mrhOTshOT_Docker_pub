# ICONICS Water Tank - Quick Reference Card

## Connection Settings

```
Protocol:    Modbus TCP
IP Address:  127.0.0.1 (or your server IP)
Port:        502
Unit ID:     1
Byte Order:  Big Endian (AB CD)
Zero-Based:  Yes
```

## Start Server

```bash
cd /opt/mrhOTshOT/final_things/iec104_water_tank
python water_tank_server.py --protocol modbus
```

## Register Map Summary

### Measurements (Input Registers - Function Code 04)
| Address | Tag | Range | Scaling Formula |
|---------|-----|-------|-----------------|
| 30001 (IR0) | Water Level | 0-100% | (Value/65535) × 100 |
| 30002 (IR1) | Pressure | 0-10 bar | (Value/65535) × 10 |
| 30003 (IR2) | Temperature | 0-100°C | (Value/65535) × 100 |

### Status (Discrete Inputs - Function Code 02)
| Address | Tag | Description |
|---------|-----|-------------|
| 10001 (DI0) | Inlet Valve Status | 1=Open, 0=Closed |
| 10002 (DI1) | Outlet Valve Status | 1=Open, 0=Closed |
| 10003 (DI2) | Pump Status | 1=Running, 0=Stopped |
| 10004 (DI3) | Auto Mode Status | 1=Auto, 0=Manual |

### Alarms (Discrete Inputs - Function Code 02)
| Address | Tag | Trigger Condition |
|---------|-----|-------------------|
| 10009 (DI8) | Overflow Alarm | Level > 98% |
| 10010 (DI9) | Low Level Alarm | Level < 10% |
| 10011 (DI10) | High Pressure Alarm | Pressure > 8 bar |
| 10012 (DI11) | Tank Exploded | Pressure > 10 bar |

### Commands (Coils - Function Code 05)
| Address | Tag | Values |
|---------|-----|--------|
| 00001 (C0) | Inlet Valve Command | 1=Open, 0=Close |
| 00002 (C1) | Outlet Valve Command | 1=Open, 0=Close |
| 00003 (C2) | Pump Command | 1=Start, 0=Stop |
| 00004 (C3) | Auto Mode Command | 1=Auto, 0=Manual |

### Setpoints (Holding Registers - Function Code 06)
| Address | Tag | Range | Scaling Formula |
|---------|-----|-------|-----------------|
| 40001 (HR0) | Inlet Valve Setpoint | 0-100% | (Value/100) × 65535 |
| 40002 (HR1) | Outlet Valve Setpoint | 0-100% | (Value/100) × 65535 |

## Scaling Examples

### Reading Measurements
```
Water Level = 32768 → (32768/65535) × 100 = 50%
Pressure = 49151 → (49151/65535) × 10 = 7.5 bar
Temperature = 13107 → (13107/65535) × 100 = 20°C
```

### Writing Setpoints
```
50% valve → (50/100) × 65535 = 32768
75% valve → (75/100) × 65535 = 49151
25% valve → (25/100) × 65535 = 16384
```

## Operation Modes

### AUTO Mode (AutoModeCommand = 1)
- Automatic level control (maintains 20-80%)
- Manual commands disabled
- Overflow/low-level protection active
- Pressure regulation active

### MANUAL Mode (AutoModeCommand = 0)
- Full operator control
- All commands enabled
- Setpoints active
- Manual safety responsibility

## Common Operations

### Switch to Manual Mode
1. Write `0` to Coil 00004 (Auto Mode Command)
2. Verify Discrete Input 10004 = 0

### Open Inlet Valve (Manual)
1. Ensure in manual mode
2. Write `1` to Coil 00001 (Inlet Valve Command)
3. Verify Discrete Input 10001 = 1

### Set Valve Position 50% (Manual)
1. Ensure in manual mode
2. Calculate: (50/100) × 65535 = 32768
3. Write `32768` to Holding Register 40001
4. Verify valve operates at 50%

## Safety Notes

[!] **Pressure Warning:** Pressure builds when:
- Tank is filling (inlet valve open)
- Outlet valve is closed
- Pump is running
- Water level is high (>90%)

[!] **Tank Rupture:** Occurs at >10 bar pressure

[!] **Overflow:** Occurs at >98% level

## Troubleshooting Quick Checks

[-] **Cannot Connect**
```bash
# Check server running
ps aux | grep water_tank_server

# Check port
lsof -i :502
```

[-] **Bad Tag Quality**
- Verify zero-based addressing enabled
- Check function code matches register type
- Confirm byte order = Big Endian

[-] **Cannot Write**
- Verify Access = Read/Write
- Check if in correct mode (Manual vs Auto)
- Confirm value range (0-65535 for registers, 0-1 for coils)

[-] **Wrong Values**
- Check scaling configuration
- Verify Raw Low=0, Raw High=65535
- Confirm scaled range matches tag type

## Testing Commands

### Test Read (pymodbus)
```python
from pymodbus.client import ModbusTcpClient
client = ModbusTcpClient('127.0.0.1', port=502)
client.connect()

# Read water level
result = client.read_input_registers(0, 1, slave=1)
level_raw = result.registers[0]
level = (level_raw / 65535.0) * 100.0
print(f"Water Level: {level:.1f}%")

client.close()
```

### Test Write (pymodbus)
```python
from pymodbus.client import ModbusTcpClient
client = ModbusTcpClient('127.0.0.1', port=502)
client.connect()

# Switch to manual mode
client.write_coil(3, False, slave=1)

# Open inlet valve
client.write_coil(0, True, slave=1)

client.close()
```

## File Locations

- **Integration Guide:** ICONICS_MODBUS_INTEGRATION_GUIDE.md
- **Tag Import CSV:** ICONICS_Tag_Import.csv
- **Server Script:** water_tank_server.py
- **Server Config:** common/config.py
- **Server Adapter:** server/modbus_adapter.py
- **Client Example:** hmi/modbus_client.py

## Support

Full documentation: ICONICS_MODBUS_INTEGRATION_GUIDE.md
Test connectivity: test_modbus_iconics.py
Server logs: iec104_water_tank.log

---

**Version:** 1.0 | **Date:** 2026-01-08
