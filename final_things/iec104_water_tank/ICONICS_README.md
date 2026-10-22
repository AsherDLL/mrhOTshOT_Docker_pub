# ICONICS Integration - Water Tank Modbus Device

## Overview

This package contains everything you need to integrate the Water Tank ICS Simulator with ICONICS GENESIS64 or FrameWorX using Modbus TCP protocol.

## Complete Package Contents

### Documentation Files
1. **ICONICS_MODBUS_INTEGRATION_GUIDE.md** - Complete integration guide (70+ pages)
2. **ICONICS_Quick_Reference.md** - Quick reference card for daily use
3. **ICONICS_Tag_Import.csv** - Ready-to-import tag database
4. **ICONICS_README.md** - This file

### Code & Configuration
- **water_tank_server.py** - Multi-protocol server (supports Modbus)
- **server/modbus_adapter.py** - Modbus TCP adapter implementation
- **server/water_tank.py** - Water tank physics simulation
- **common/config.py** - Configuration parameters
- **hmi/modbus_client.py** - Example Modbus client

### Testing
- **test_modbus_iconics.py** - Connectivity validation script

---

## Quick Start (5 Minutes)

### Step 1: Start the Modbus Server
```bash
cd /opt/mrhOTshOT/final_things/iec104_water_tank
python water_tank_server.py --protocol modbus
```

### Step 2: Test Connectivity
```bash
python test_modbus_iconics.py
```

### Step 3: Configure ICONICS
1. Open ICONICS Workbench
2. Add Modbus TCP driver
3. Configure connection:
   - IP: 127.0.0.1
   - Port: 502
   - Unit ID: 1
4. Import tags from `ICONICS_Tag_Import.csv`
5. Test connectivity

**Done!** You're ready to build HMI displays.

---

## Device Specifications

### Water Tank System
- **Type:** Industrial water tank simulator
- **Capacity:** 1000 liters
- **Control:** Auto/Manual modes
- **Measurements:** Level, Pressure, Temperature
- **Actuators:** Inlet valve, Outlet valve, Pump
- **Safety:** Overflow protection, pressure alarms

### Modbus Configuration
- **Protocol:** Modbus TCP
- **IP Address:** 127.0.0.1 (configurable)
- **Port:** 502 (standard Modbus)
- **Unit ID:** 1
- **Registers:** 17 total (Coils, Discrete Inputs, Input Registers, Holding Registers)
- **Byte Order:** Big Endian (Modbus standard)

---

## Complete Register Map

### Input Registers (3x) - Measurements
| Address | Tag | Range | Units |
|---------|-----|-------|-------|
| 30001 | Water Level | 0-100 | % |
| 30002 | Pressure | 0-10 | bar |
| 30003 | Temperature | 0-100 | °C |

### Discrete Inputs (1x) - Status & Alarms
| Address | Tag | Type |
|---------|-----|------|
| 10001 | Inlet Valve Status | Status |
| 10002 | Outlet Valve Status | Status |
| 10003 | Pump Status | Status |
| 10004 | Auto Mode Status | Status |
| 10009 | Overflow Alarm | Alarm |
| 10010 | Low Level Alarm | Alarm |
| 10011 | High Pressure Alarm | Alarm |
| 10012 | Tank Exploded Alarm | Alarm |

### Coils (0x) - Commands
| Address | Tag | Function |
|---------|-----|----------|
| 00001 | Inlet Valve Command | Open/Close |
| 00002 | Outlet Valve Command | Open/Close |
| 00003 | Pump Command | Start/Stop |
| 00004 | Auto Mode Command | Enable/Disable |

### Holding Registers (4x) - Setpoints
| Address | Tag | Range | Units |
|---------|-----|-------|-------|
| 40001 | Inlet Valve Setpoint | 0-100 | % |
| 40002 | Outlet Valve Setpoint | 0-100 | % |

---

## Documentation Guide

### For Initial Setup
**Start here:** `ICONICS_MODBUS_INTEGRATION_GUIDE.md`
- Complete step-by-step setup instructions
- Detailed tag configuration
- Troubleshooting section
- Advanced configuration options

### For Daily Use
**Reference:** `ICONICS_Quick_Reference.md`
- Connection settings
- Register map summary
- Common operations
- Quick troubleshooting

### For Tag Configuration
**Import:** `ICONICS_Tag_Import.csv`
- Pre-configured tag database
- Ready to import into ICONICS
- All 17 tags with scaling

---

## Testing & Validation

### Automated Testing
Run the comprehensive test suite:
```bash
python test_modbus_iconics.py
```

**Tests include:**
- [+] Connection verification
- [+] Input register reading (measurements)
- [+] Discrete input reading (status/alarms)
- [+] Coil reading/writing (commands)
- [+] Holding register reading/writing (setpoints)
- [+] Scaling accuracy validation

### Manual Testing with pymodbus
```python
from pymodbus.client import ModbusTcpClient

client = ModbusTcpClient('127.0.0.1', port=502)
client.connect()

# Read water level
result = client.read_input_registers(0, 1, slave=1)
level = (result.registers[0] / 65535.0) * 100.0
print(f"Water Level: {level:.1f}%")

# Switch to manual mode
client.write_coil(3, False, slave=1)

# Open inlet valve
client.write_coil(0, True, slave=1)

client.close()
```

---

## Operation Modes

### AUTO Mode (Default)
- **Behavior:** Automatic level control
- **Target:** Maintains 20-80% water level
- **Protection:** Overflow and low-level protection active
- **Commands:** Manual valve/pump commands disabled

### MANUAL Mode
- **Behavior:** Full operator control
- **Commands:** All valve and pump commands enabled
- **Setpoints:** Valve position setpoints active
- **Responsibility:** Operator must prevent unsafe conditions

### Switching Modes
**To Manual:** Write `0` to Coil 00004 (Auto Mode Command)
**To Auto:** Write `1` to Coil 00004 (Auto Mode Command)

---

## [!] Safety & Alarms

### Critical Alarms
| Alarm | Trigger | Action Required |
|-------|---------|-----------------|
| Tank Exploded | Pressure > 10 bar | **CRITICAL** - All operations cease |
| Overflow Alarm | Level > 98% | Close inlet, open outlet |
| High Pressure | Pressure > 8 bar | Reduce filling, increase outflow |
| Low Level | Level < 10% | Stop outlet, increase inlet |

### Understanding Pressure
Pressure in the tank builds due to **compressed air** in the empty space:
- As water level rises, air space decreases
- Compressed air creates higher pressure
- Pump operation adds additional pressure
- Can lead to tank rupture if uncontrolled

This simulates real industrial behavior!

---

## Troubleshooting

### Cannot Connect to Server
```bash
# Check if server is running
ps aux | grep water_tank_server

# Check if port is open
lsof -i :502

# Start server if needed
cd /opt/mrhOTshOT/final_things/iec104_water_tank
python water_tank_server.py --protocol modbus
```

### Bad Tag Quality in ICONICS
- [+] Verify zero-based addressing is enabled
- [+] Check byte order = Big Endian
- [+] Confirm correct function codes
- [+] Review address notation (30001 vs IR0)

### Values Not Updating
- [+] Check scan rate (recommended: 1000ms)
- [+] Verify server simulation is running
- [+] Review server logs: `iec104_water_tank.log`

### Cannot Write Commands
- [+] Verify device is in MANUAL mode (for valve/pump commands)
- [+] Check tag access is set to Read/Write
- [+] Confirm value range (0-1 for coils, 0-65535 for registers)

---

## File Structure

```
iec104_water_tank/
├── ICONICS_README.md                    ← You are here
├── ICONICS_MODBUS_INTEGRATION_GUIDE.md  ← Complete guide
├── ICONICS_Quick_Reference.md           ← Quick reference
├── ICONICS_Tag_Import.csv               ← Tag database
├── test_modbus_iconics.py              ← Test script
├── water_tank_server.py                ← Server launcher
├── common/
│   └── config.py                       ← Configuration
├── server/
│   ├── water_tank.py                   ← Tank simulation
│   ├── modbus_adapter.py               ← Modbus implementation
│   └── protocol_adapter.py             ← Base adapter
└── hmi/
    └── modbus_client.py                ← Example client
```

---

## ICONICS Integration Workflow

### Phase 1: Setup & Testing
1. [+] Start Modbus server
2. [+] Run connectivity tests
3. [+] Verify all registers accessible
4. [+] Validate scaling

### Phase 2: ICONICS Configuration
1. [+] Install Modbus TCP driver
2. [+] Configure device connection
3. [+] Import tags from CSV
4. [+] Verify tag quality

### Phase 3: HMI Development
1. [+] Create GraphWorX displays
2. [+] Add tank visualization
3. [+] Configure alarm banners
4. [+] Setup trending

### Phase 4: Testing & Validation
1. [+] Test all read tags
2. [+] Test all write commands
3. [+] Verify alarms trigger
4. [+] Validate scaling accuracy

### Phase 5: Deployment
1. [+] Document custom displays
2. [+] Train operators
3. [+] Setup alarm logging
4. [+] Configure data historians

---

## Tips & Best Practices

### Performance Optimization
- Use scan rate 1000ms for normal tags
- Use 500ms for critical alarms
- Use on-demand for commands/setpoints
- Group similar tags together

### Alarming
- Configure critical alarms with audio notification
- Use color coding: Red=Critical, Yellow=Warning
- Enable alarm acknowledgment
- Log all alarm events

### Display Design
- Show tank with animated level indicator
- Color-code by safety zones (green/yellow/red)
- Display mode prominently (AUTO/MANUAL)
- Disable controls when in AUTO mode

### Data Logging
- Trend water level (most important)
- Log pressure for safety analysis
- Record all alarm events
- Track mode changes

---

## Support & Resources

### Documentation
- **Full Guide:** ICONICS_MODBUS_INTEGRATION_GUIDE.md
- **Quick Ref:** ICONICS_Quick_Reference.md
- **Multi-Protocol:** MULTI_PROTOCOL_README.md
- **Main README:** README.md

### Testing Tools
- **Test Script:** `python test_modbus_iconics.py`
- **Modbus Poll:** Commercial Windows tool
- **QModMaster:** Free cross-platform tool
- **pymodbus:** Python library for scripting

### Log Files
- **Server Log:** iec104_water_tank.log
- **ICONICS Logs:** Workbench → System Diagnostics

### Example Code
- **Python Client:** hmi/modbus_client.py
- **Server Implementation:** server/modbus_adapter.py

---

## Configuration Summary

### Connection String
```
Protocol: Modbus TCP
Endpoint: 127.0.0.1:502
Unit ID: 1
Byte Order: Big Endian (AB CD)
Word Order: Big Endian
Zero-Based: Yes
```

### Scaling Configuration
```
Input Registers:
  Raw: 0-65535 (UINT16)
  Scaled: 0-MaxRange (Linear)
  Formula: Actual = (Raw / 65535) × MaxRange

Holding Registers:
  Raw: 0-65535 (UINT16)
  Scaled: 0-MaxRange (Linear)
  Formula: Raw = (Actual / MaxRange) × 65535
```

### Recommended Poll Rates
```
Measurements: 1000 ms
Status: 1000 ms
Alarms: 500 ms
Commands: On-demand
Setpoints: On-demand
```

---

## Next Steps

### Beginner Path
1. Read Quick Reference
2. Start server and run tests
3. Follow ICONICS setup guide
4. Create simple display

### Advanced Path
1. Study complete integration guide
2. Customize server configuration
3. Build advanced HMI displays
4. Integrate with data historian

### Expert Path
1. Multi-device setup (multiple tanks)
2. Custom alarming logic
3. Advanced automation
4. Integration with other protocols

---

## [+] Checklist for ICONICS Integration

### Pre-Integration
- [ ] Server installed and configured
- [ ] Dependencies installed (pymodbus)
- [ ] Network connectivity verified
- [ ] Firewall rules configured (port 502)

### ICONICS Setup
- [ ] Modbus TCP driver installed
- [ ] Device configured with correct IP/port
- [ ] Tags imported from CSV
- [ ] Tag quality verified (all Good)
- [ ] Write access tested

### Testing
- [ ] All measurements reading correctly
- [ ] All status bits working
- [ ] All alarms triggering
- [ ] Commands executing (manual mode)
- [ ] Setpoints applying correctly
- [ ] Scaling validated

### HMI Development
- [ ] Tank visualization created
- [ ] Control panel designed
- [ ] Alarm banner configured
- [ ] Trends setup
- [ ] Navigation implemented

### Deployment
- [ ] Operator training completed
- [ ] Documentation updated
- [ ] Backup created
- [ ] Go-live plan executed

---

## Getting Help

If you encounter issues:

1. **Check Quick Reference** - Common issues and solutions
2. **Review Integration Guide** - Detailed troubleshooting section
3. **Run Test Script** - Identifies connectivity/configuration issues
4. **Check Logs** - Server and ICONICS diagnostic logs
5. **Verify Configuration** - Compare with documented settings

---

## System Statistics

- **Total Tags:** 17
- **Measurements:** 3 (Water Level, Pressure, Temperature)
- **Status Points:** 4 (Valves, Pump, Mode)
- **Alarms:** 4 (Overflow, Low Level, High Pressure, Exploded)
- **Commands:** 4 (Valves, Pump, Mode)
- **Setpoints:** 2 (Inlet Valve, Outlet Valve)

---

## Version History

| Version | Date | Changes |
|---------|------|---------|
| 1.0 | 2026-01-08 | Initial ICONICS integration package |

---

## License

Same as main Water Tank ICS Simulator project.

---

**Ready to integrate? Start with the Quick Reference or dive into the Complete Integration Guide!**

For questions or support, refer to the main project documentation.

---

**Document Version:** 1.0  
**Last Updated:** January 8, 2026  
**For:** ICONICS GENESIS64 / FrameWorX Integration
