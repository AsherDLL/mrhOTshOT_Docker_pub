# Multi-Protocol Water Tank Server

## Overview

The water tank simulation now supports **four major industrial communication protocols**:

1. **IEC 60870-5-104** - SCADA protocol for electrical grid monitoring
2. **Siemens S7** - PLC communication protocol
3. **Modbus TCP** - Widely-used industrial automation protocol
4. **OPC-UA** - Modern Industry 4.0 standard

## Quick Start

### Basic Usage

```bash
# IEC-104 (default port 2404)
python water_tank_server.py --protocol iec104

# Siemens S7 (default port 102)
python water_tank_server.py --protocol s7

# Modbus TCP (default port 502)
python water_tank_server.py --protocol modbus

# OPC-UA (default port 4840)
python water_tank_server.py --protocol opcua
```

### Installation

#### Option 1: Install All Protocols (Recommended for development)

```bash
pip install -r requirements-multiprotocol.txt
```

#### Option 2: Install Specific Protocol Only

```bash
# For IEC-104 only (already included with c104)
# No additional dependencies needed

# For S7 only
pip install -r requirements-s7.txt

# For Modbus only
pip install -r requirements-modbus.txt

# For OPC-UA only
pip install -r requirements-opcua.txt
```

## Protocol Details

### 1. IEC 60870-5-104 (SCADA)

**Default Port:** 2404
**Use Case:** SCADA systems, electrical grid monitoring

#### Example

```bash
# Start IEC-104 server
python water_tank_server.py --protocol iec104

# Custom port and common address
python water_tank_server.py --protocol iec104 --port 2405 --common-address 1
```

#### Data Point Mapping

| IOA | Type | Description |
|-----|------|-------------|
| 100 | M_ME_NB_1 | Water level (%) |
| 101 | M_ME_NB_1 | Pressure (bar) |
| 102 | M_ME_NB_1 | Temperature (°C) |
| 200-207 | M_SP_NA_1 | Status points |
| 300-303 | C_SC_NA_1 | Commands |
| 400-401 | C_SE_NC_1 | Setpoints |

#### Client Connection

```python
# Python client example
import c104

client = c104.Client()
connection = client.add_connection(ip="127.0.0.1", port=2404)
connection.connect()
```

---

### 2. Siemens S7 (PLC)

**Default Port:** 102
**Use Case:** Siemens PLC communication, STEP 7 integration

#### Example

```bash
# Start S7 server
python water_tank_server.py --protocol s7

# Custom rack and slot
python water_tank_server.py --protocol s7 --rack 0 --slot 2
```

#### Data Block Layout

| DB | Type | Description |
|----|------|-------------|
| DB1 | REAL | Process measurements (analog) |
| DB2 | BOOL | Process status (digital) |
| DB3 | BOOL | Commands (digital outputs) |
| DB4 | REAL | Setpoints (analog outputs) |

#### Client Connection

```python
# Python client example
import snap7

plc = snap7.client.Client()
plc.connect('127.0.0.1', 0, 1)  # IP, rack, slot

# Read water level from DB1.DBD0
data = plc.db_read(1, 0, 4)  # DB1, offset 0, 4 bytes (REAL)
water_level = snap7.util.get_real(data, 0)

# Write pump command to DB3.DBX0.0
plc.db_write(3, 0, b'\x01')  # Turn pump ON
```

---

### 3. Modbus TCP (Industrial Automation)

**Default Port:** 502
**Slave ID:** 1 (default)
**Use Case:** Industrial automation, HMI/SCADA integration

#### Example

```bash
# Start Modbus server
python water_tank_server.py --protocol modbus

# Custom port and slave ID
python water_tank_server.py --protocol modbus --port 5020 --slave-id 2
```

#### Register Map

| Register Type | Address Range | Description |
|--------------|---------------|-------------|
| Coils (0x) | 0-9 | Digital outputs (commands) |
| Discrete Inputs (1x) | 0-11 | Digital status/alarms |
| Input Registers (3x) | 0-2 | Analog measurements |
| Holding Registers (4x) | 0-1 | Analog setpoints |

#### Client Connection

```python
# Python client example
from pymodbus.client import ModbusTcpClient

client = ModbusTcpClient('127.0.0.1', port=502)
client.connect()

# Read water level (Input Register 0)
result = client.read_input_registers(0, 1, slave=1)
water_level_raw = result.registers[0]
water_level = (water_level_raw / 65535.0) * 100.0  # Scale to 0-100%

# Write pump command (Coil 2)
client.write_coil(2, True, slave=1)  # Turn pump ON

client.close()
```

---

### 4. OPC-UA (Industry 4.0)

**Default Port:** 4840
**Endpoint:** `opc.tcp://0.0.0.0:4840/freeopcua/server/`
**Use Case:** Industry 4.0, modern automation systems

#### Example

```bash
# Start OPC-UA server
python water_tank_server.py --protocol opcua

# Custom port and namespace
python water_tank_server.py --protocol opcua --port 4841 --namespace http://example.com
```

#### Node Hierarchy

```
Objects/
  WaterTank/
    Measurements/
      WaterLevel (Float)
      Pressure (Float)
      Temperature (Float)
    Status/
      InletValveStatus (Boolean)
      OutletValveStatus (Boolean)
      PumpStatus (Boolean)
      AutoModeStatus (Boolean)
    Alarms/
      OverflowAlarm (Boolean)
      LowLevelAlarm (Boolean)
      HighPressureAlarm (Boolean)
    Commands/
      InletValveCommand (Boolean)
      OutletValveCommand (Boolean)
      PumpCommand (Boolean)
      AutoModeCommand (Boolean)
    Setpoints/
      InletValveSetpoint (Float)
      OutletValveSetpoint (Float)
```

#### Client Connection

```python
# Python client example
from opcua import Client

client = Client("opc.tcp://127.0.0.1:4840/freeopcua/server/")
client.connect()

# Browse to water level node
root = client.get_root_node()
water_tank = root.get_child(["0:Objects", "2:WaterTank"])
measurements = water_tank.get_child(["2:Measurements"])
water_level_node = measurements.get_child(["2:WaterLevel"])

# Read value
water_level = water_level_node.get_value()
print(f"Water Level: {water_level}%")

# Write pump command
commands = water_tank.get_child(["2:Commands"])
pump_cmd_node = commands.get_child(["2:PumpCommand"])
pump_cmd_node.set_value(True)  # Turn pump ON

client.disconnect()
```

---

## Command-Line Options

### Common Options (All Protocols)

| Option | Description | Default |
|--------|-------------|---------|
| `--protocol` | Protocol to use (iec104, s7, modbus, opcua) | Required |
| `--host` | Bind address | 0.0.0.0 |
| `--port` | Port number | Protocol-specific |

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

#### OPC-UA

| Option | Description | Default |
|--------|-------------|---------|
| `--namespace` | Namespace URI | http://watertank.local |

---

## Architecture

### Protocol Abstraction Layer

The multi-protocol support is built on a clean abstraction layer:

```
┌─────────────────────────────────────────────────────────┐
│                    Water Tank Core                      │
│                  (server/water_tank.py)                 │
└─────────────────────────────────────────────────────────┘
                           │
                           ▼
┌─────────────────────────────────────────────────────────┐
│              Protocol Adapter Base Class                 │
│            (server/protocol_adapter.py)                 │
└─────────────────────────────────────────────────────────┘
          │           │           │           │
          ▼           ▼           ▼           ▼
    ┌─────────┐ ┌─────────┐ ┌─────────┐ ┌─────────┐
    │ IEC-104 │ │   S7    │ │ Modbus  │ │ OPC-UA  │
    │ Adapter │ │ Adapter │ │ Adapter │ │ Adapter │
    └─────────┘ └─────────┘ └─────────┘ └─────────┘
```

### File Structure

```
iec104_water_tank/
├── water_tank_server.py          # Unified server launcher
├── server/
│   ├── water_tank.py             # Core water tank simulation
│   ├── protocol_adapter.py       # Base adapter class
│   ├── iec104_adapter.py         # IEC-104 adapter
│   ├── s7_adapter.py             # Siemens S7 adapter
│   ├── modbus_adapter.py         # Modbus TCP adapter
│   └── opcua_adapter.py          # OPC-UA adapter
├── requirements-multiprotocol.txt
├── requirements-iec104.txt
├── requirements-s7.txt
├── requirements-modbus.txt
└── requirements-opcua.txt
```

---

## Use Cases

### Development & Testing

Test applications against different industrial protocols:

```bash
# Test IEC-104 client
python water_tank_server.py --protocol iec104

# Test Modbus HMI
python water_tank_server.py --protocol modbus

# Test OPC-UA integration
python water_tank_server.py --protocol opcua
```

### Protocol Comparison

Run different protocols side-by-side (on different ports):

```bash
# Terminal 1: IEC-104 on 2404
python water_tank_server.py --protocol iec104 --port 2404

# Terminal 2: Modbus on 502
python water_tank_server.py --protocol modbus --port 502

# Terminal 3: OPC-UA on 4840
python water_tank_server.py --protocol opcua --port 4840
```

### Training & Education

Demonstrate different industrial protocols using the same process:
- Same water tank behavior
- Different communication methods
- Protocol-specific features

### Security Testing

Test ICS security tools against multiple protocols:
- Protocol fuzzing
- Attack simulation (like CosmicEnergy)
- Intrusion detection testing

---

## Troubleshooting

### Import Errors

**Error:** `ModuleNotFoundError: No module named 'snap7'`

**Solution:**
```bash
pip install python-snap7
```

**Error:** `ModuleNotFoundError: No module named 'pymodbus'`

**Solution:**
```bash
pip install pymodbus
```

**Error:** `ModuleNotFoundError: No module named 'asyncua'`

**Solution:**
```bash
pip install asyncua
```

### Port Already in Use

**Error:** `OSError: [Errno 48] Address already in use`

**Solution:** Use a different port:
```bash
python water_tank_server.py --protocol modbus --port 5020
```

### Connection Refused

**Problem:** Client cannot connect

**Solutions:**
1. Check if server is running
2. Verify correct port number
3. Check firewall settings
4. Ensure correct protocol

---

## Advanced Usage

### Running Multiple Protocols Simultaneously

You can run multiple servers at the same time (different ports required):

```bash
# Terminal 1: IEC-104
python water_tank_server.py --protocol iec104 --port 2404

# Terminal 2: Modbus (requires separate instance)
# Note: Would need separate water tank instance for true multi-protocol
```

### Custom Configuration

Modify `common/config.py` to adjust:
- Tank parameters
- Simulation rates
- Initial conditions
- Safety limits

---

## Protocol Comparison

| Feature | IEC-104 | S7 | Modbus | OPC-UA |
|---------|---------|-----|--------|--------|
| **Typical Use** | SCADA | PLC | Automation | Industry 4.0 |
| **Complexity** | Medium | High | Low | High |
| **Security** | Basic | Limited | None | Strong |
| **Data Types** | Rich | Rich | Simple | Very Rich |
| **Performance** | Good | Excellent | Excellent | Good |
| **Standardization** | IEC | Proprietary | Open | Open |
| **Event Support** | Yes | Limited | No | Yes |

---

## Next Steps

1. **Install dependencies** for your protocol of choice
2. **Start the server** with your desired protocol
3. **Connect a client** to test communication
4. **Explore the API** for your protocol
5. **Build applications** on top of the water tank simulation

---

## Support

For issues or questions:
1. Check the [main README](README.md)
2. Review protocol-specific documentation
3. Examine the example client code above
4. Check server logs in `iec104_water_tank.log`

---

**Created:** December 2024
**Protocols Supported:** IEC-104, S7, Modbus, OPC-UA
**License:** Same as main project
