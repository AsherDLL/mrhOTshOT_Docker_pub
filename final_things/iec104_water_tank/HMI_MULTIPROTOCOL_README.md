# Multi-Protocol HMI Client

## Overview

The water tank HMI client now supports **all four industrial protocols** with a single unified interface:

1. **IEC 60870-5-104** - SCADA protocol
2. **Siemens S7** - PLC communication
3. **Modbus TCP** - Industrial automation
4. **OPC-UA** - Industry 4.0 standard

The HMI provides the same graphical interface regardless of which protocol is used to communicate with the server.

## Quick Start

### Using the Launcher Script

```bash
# IEC-104
./run_multiprotocol_hmi.sh iec104

# Siemens S7
./run_multiprotocol_hmi.sh s7

# Modbus TCP
./run_multiprotocol_hmi.sh modbus

# OPC-UA
./run_multiprotocol_hmi.sh opcua
```

### Direct Python Invocation

```bash
# IEC-104 (default port 2404)
python -m hmi.multiprotocol_hmi --protocol iec104

# S7 (default port 102)
python -m hmi.multiprotocol_hmi --protocol s7

# Modbus (default port 502)
python -m hmi.multiprotocol_hmi --protocol modbus

# OPC-UA (default port 4840)
python -m hmi.multiprotocol_hmi --protocol opcua
```

## Command-Line Options

### Common Options

| Option | Description | Default |
|--------|-------------|---------|
| `--protocol` | Protocol to use (iec104, s7, modbus, opcua) | Required |
| `--host` | Server IP address | 127.0.0.1 |
| `--port` | Server port | Protocol-specific |

### Protocol-Specific Options

#### IEC-104
| Option | Description | Default |
|--------|-------------|---------|
| `--common-address` | Common Address (COA) | 1 |

#### Siemens S7
| Option | Description | Default |
|--------|-------------|---------|
| `--rack` | Rack number | 0 |
| `--slot` | Slot number | 1 |

#### Modbus
| Option | Description | Default |
|--------|-------------|---------|
| `--slave-id` | Modbus slave ID | 1 |

## Usage Examples

### Example 1: Connect to IEC-104 Server

```bash
# Start server in Terminal 1
python water_tank_server.py --protocol iec104

# Start HMI in Terminal 2
./run_multiprotocol_hmi.sh iec104
```

### Example 2: Connect to S7 Server on Custom Port

```bash
# Start server in Terminal 1
python water_tank_server.py --protocol s7 --port 1102

# Start HMI in Terminal 2
./run_multiprotocol_hmi.sh s7 --port 1102
```

### Example 3: Connect to Modbus Server

```bash
# Start server in Terminal 1
python water_tank_server.py --protocol modbus

# Start HMI in Terminal 2
./run_multiprotocol_hmi.sh modbus
```

### Example 4: Connect to OPC-UA Server

```bash
# Start server in Terminal 1
python water_tank_server.py --protocol opcua

# Start HMI in Terminal 2
./run_multiprotocol_hmi.sh opcua
```

### Example 5: Remote Server Connection

```bash
# Connect to remote Modbus server
python -m hmi.multiprotocol_hmi --protocol modbus --host 192.168.1.100 --port 502
```

## HMI Features

The HMI provides:

### Real-Time Monitoring
- **Water Level** (0-100%)
- **Pressure** (0-10 bar)
- **Temperature** (0-100°C)
- **Visual tank display** with animated water level

### Control Functions
- **Auto Mode Toggle** - Enable/disable automatic control
- **Manual Control** - Direct control of:
  - Inlet valve (OPEN/CLOSED)
  - Outlet valve (OPEN/CLOSED)
  - Pump (ON/OFF)

### Alarm Display
- **Overflow Alarm** - Tank level > 95%
- **Low Level Alarm** - Tank level < 10%
- **High Pressure Alarm** - Pressure > 9 bar
- **Tank Exploded** - Critical failure

## Architecture

### Protocol Client Adapters

The HMI uses protocol-specific client adapters that all implement a common interface:

```
┌─────────────────────────────────────────────┐
│          Multi-Protocol HMI GUI              │
│       (hmi/multiprotocol_hmi.py)            │
└─────────────────────────────────────────────┘
                     │
                     ▼
┌─────────────────────────────────────────────┐
│        Protocol Client Interface             │
│        (hmi/protocol_client.py)             │
└─────────────────────────────────────────────┘
        │         │         │         │
        ▼         ▼         ▼         ▼
  ┌─────────┐ ┌─────────┐ ┌─────────┐ ┌─────────┐
  │ IEC-104 │ │   S7    │ │ Modbus  │ │ OPC-UA  │
  │ Client  │ │ Client  │ │ Client  │ │ Client  │
  └─────────┘ └─────────┘ └─────────┘ └─────────┘
```

### Files

| File | Purpose |
|------|---------|
| `hmi/protocol_client.py` | Base class and common interface |
| `hmi/iec104_client.py` | IEC-104 client adapter |
| `hmi/s7_client.py` | Siemens S7 client adapter |
| `hmi/modbus_client.py` | Modbus TCP client adapter |
| `hmi/opcua_client.py` | OPC-UA client adapter |
| `hmi/multiprotocol_hmi.py` | Main HMI application |
| `run_multiprotocol_hmi.sh` | Launcher script |

## Data Point Mapping

All protocols use the same internal data point names, which are mapped to protocol-specific addresses:

### Measurements (Analog Inputs)
- `water_level` - Water level percentage (0-100%)
- `pressure` - Pressure in bar (0-10)
- `temperature` - Temperature in °C (0-100)

### Status (Digital Inputs)
- `inlet_valve_status` - Inlet valve state
- `outlet_valve_status` - Outlet valve state
- `pump_status` - Pump state
- `auto_mode_status` - Auto mode state
- `overflow_alarm` - Overflow alarm
- `low_level_alarm` - Low level alarm
- `high_pressure_alarm` - High pressure alarm
- `tank_exploded_alarm` - Tank exploded alarm

### Commands (Digital Outputs)
- `inlet_valve_command` - Inlet valve control
- `outlet_valve_command` - Outlet valve control
- `pump_command` - Pump control
- `auto_mode_command` - Auto mode control

### Setpoints (Analog Outputs)
- `inlet_valve_setpoint` - Inlet valve position (0-100%)
- `outlet_valve_setpoint` - Outlet valve position (0-100%)

## Protocol Comparison

| Feature | IEC-104 | S7 | Modbus | OPC-UA |
|---------|---------|-----|--------|--------|
| **Data Updates** | Event-driven | Polling | Polling | Subscription |
| **Update Rate** | Real-time | 500ms | 500ms | 500ms |
| **Connection** | Automatic reconnect | Manual reconnect | Manual reconnect | Manual reconnect |
| **Complexity** | Medium | Medium | Low | High |
| **Best For** | SCADA systems | PLCs | Simple automation | Industry 4.0 |

## Troubleshooting

### HMI Won't Connect

1. **Check server is running:**
   ```bash
   # For S7 on port 1102
   lsof -i:1102
   ```

2. **Verify protocol and port match:**
   - Server and HMI must use same protocol
   - Port numbers must match

3. **Check firewall settings:**
   - Ensure ports are not blocked

### Missing Dependencies

```bash
# IEC-104
# Already included with c104

# S7
pip install python-snap7

# Modbus
pip install pymodbus

# OPC-UA
pip install opcua
```

### Connection Timeout

- **IEC-104**: Check common address matches server
- **S7**: Verify rack and slot numbers
- **Modbus**: Check slave ID
- **OPC-UA**: Verify namespace matches server

## Advanced Usage

### Custom Configuration

You can create a config dictionary for protocol-specific settings:

```python
from hmi.multiprotocol_hmi import MultiProtocolWaterTankHMI
import tkinter as tk

# S7 with custom rack/slot
config = {'rack': 0, 'slot': 2}
root = tk.Tk()
app = MultiProtocolWaterTankHMI(root, 's7', '127.0.0.1', 1102, config)
root.mainloop()
```

### Using Protocol Clients Directly

You can use the protocol client adapters in your own applications:

```python
from hmi.s7_client import S7Client
from hmi.protocol_client import WaterTankDataPoints

# Create client
client = S7Client('127.0.0.1', 1102)

# Register callback
def on_data(update):
    print(f"{update.name}: {update.value}")

client.register_data_callback(on_data)

# Connect and start monitoring
if client.connect():
    client.start_monitoring()

    # Send commands
    client.send_command(WaterTankDataPoints.PUMP_COMMAND, True)

    # Send setpoint
    client.send_setpoint(WaterTankDataPoints.INLET_VALVE_SETPOINT, 50.0)
```

## Legacy HMI

The original IEC-104-only HMI is still available:

```bash
./run_hmi.sh
```

This uses the legacy `hmi/hmi_client.py` which only supports IEC-104.

---

**Created:** December 2024
**Protocols Supported:** IEC-104, S7, Modbus, OPC-UA
**Status:** [+] Complete and Tested
