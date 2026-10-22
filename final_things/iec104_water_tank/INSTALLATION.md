# IEC-104 Water Tank System - Installation Guide

## Prerequisites

- Python 3.8+ (tested with Python 3.13.7)
- macOS, Linux, or Windows
- CMake 3.15+
- C++ compiler (Apple Clang 17+ on macOS, GCC/Clang on Linux)

## Installation Steps

### 1. Install c104 Library with Patches (macOS ARM64)

The c104 library requires patches for macOS ARM64 compatibility. Follow these steps:

```bash
cd /opt/mrhOTshOT/final_things/iec104_water_tank

# Extract the patched c104 source
cd c104-2.2.1

# Install from the patched source
source ../env/bin/activate  # or venv/bin/activate depending on your env
pip install .
```

**Applied Patches:**
1. **DateTime constructor fix** - Moved default parameter to header file for Apple Clang 17 compatibility
2. **macOS linker fix** - Removed `-lrt` library (Linux-only) from macOS builds

### 2. Verify Installation

```bash
python -c "import c104; print('c104 version:', c104.__version__)"
```

Expected output: `c104 version: 2.2.1` or similar

## Running the System

### Terminal 1 - Start IEC-104 Server

```bash
cd /opt/mrhOTshOT/final_things/iec104_water_tank
source env/bin/activate
python -m server.iec104_server
```

You should see:
```
2025-12-01 12:00:00 - IEC104Server - INFO - Starting IEC-104 server on 0.0.0.0:2404
2025-12-01 12:00:00 - IEC104Server - INFO - Data points configured successfully
2025-12-01 12:00:00 - IEC104Server - INFO - IEC-104 server started successfully
Water Tank IEC-104 Server running...
Listening on 0.0.0.0:2404
Press Ctrl+C to stop

=== Tank Status ===
Water Level:   50.0%
Pressure:       2.50 bar
Temperature:   20.5°C
Inlet Valve:    100% [OPEN]
Outlet Valve:     0% [CLOSED]
Pump: ON
Mode: AUTO
```

### Terminal 2 - Start HMI Client

```bash
cd /opt/mrhOTshOT/final_things/iec104_water_tank
source env/bin/activate
python -m hmi.hmi_client
```

A graphical window will open showing:
- Animated water tank visualization
- Real-time measurements
- Control panel
- Status indicators
- Alarm displays

## Troubleshooting

### Issue: "ModuleNotFoundError: No module named 'c104'"

**Solution**: Install c104 from the patched source:
```bash
cd c104-2.2.1
source ../env/bin/activate
pip install .
```

### Issue: "Port in use" error

**Solution**: Kill existing server processes:
```bash
lsof -ti:2404 | xargs kill -9
# OR
pkill -f iec104_server
```

### Issue: HMI shows "Disconnected"

**Solution**:
1. Make sure the server is running first
2. Check that port 2404 is not blocked by firewall
3. Verify server is listening: `lsof -i:2404`

### Issue: "Invalid callback signature" error

**Solution**: The c104 library is very strict about type hints. Make sure all callbacks match exactly:

**Server callbacks:**
```python
def on_receive_raw(self, server: c104.Server, data: bytes) -> None:
    ...

def on_clock_sync(self, server: c104.Server, ip: str, date_time: datetime) -> c104.ResponseState:
    ...

def on_receive_command(self, point: c104.Point, previous_info: c104.Information, message: c104.IncomingMessage) -> c104.ResponseState:
    ...
```

**HMI callbacks:**
```python
def _on_connection_state(self, connection: c104.Connection, state: c104.ConnectionState) -> None:
    ...

def _on_receive_point(self, point: c104.Point, previous_info: c104.Information, message: c104.IncomingMessage) -> c104.ResponseState:
    ...
```

### Issue: Compilation errors when installing c104

**macOS ARM64 specific errors:**

1. **"default constructor" error in DateTime.cpp**:
   - Already patched in c104-2.2.1/src/object/DateTime.h and DateTime.cpp

2. **"-lrt" linker error**:
   - Already patched in c104-2.2.1/depends/lib60870/lib60870-C/src/CMakeLists.txt
   - And in c104-2.2.1/depends/lib60870/lib60870-C/src/hal/CMakeLists.txt

If you encounter these, the patches may not have been applied correctly. Verify:
```bash
grep "std::chrono::system_clock::now()" c104-2.2.1/src/object/DateTime.h
# Should show the default parameter in the header

grep "IF(APPLE)" c104-2.2.1/depends/lib60870/lib60870-C/src/CMakeLists.txt
# Should show conditional Apple/Linux linking
```

## Testing Without HMI

For testing server functionality without the GUI:

```bash
python test_standalone.py
```

This runs automated tests of the water tank simulation without requiring IEC-104 or tkinter.

### Testing Manual Mode Operations

To verify all manual mode operations work correctly (including 100% water level):

```bash
python test_manual_operations.py
```

This comprehensive test verifies:
- Mode switching (AUTO ↔ MANUAL)
- Inlet/Outlet valve control
- Pump control
- Full 0-100% water level range
- Overflow and low-level protections
- All IEC-104 measurements

## Network Configuration

**Default Settings:**
- Server Host: `0.0.0.0` (all interfaces)
- Server Port: `2404` (standard IEC-104)
- Common Address: `1`

To change, edit [common/config.py](common/config.py):
```python
IEC104_HOST = "0.0.0.0"
IEC104_PORT = 2404
COMMON_ADDRESS = 1
```

## IEC-104 Traffic Verification

To monitor IEC-104 traffic:

```bash
# Install tcpdump or Wireshark
sudo tcpdump -i lo0 port 2404 -X

# You should see IEC-104 APDU frames with:
# - STARTDT/STOPDT for connection management
# - I-frames with ASDUs for data transfer
# - S-frames for acknowledgments
```

## File Locations

- **Virtual Environment**: `/opt/mrhOTshOT/final_things/iec104_water_tank/env/`
- **Patched c104 Source**: `/opt/mrhOTshOT/final_things/iec104_water_tank/c104-2.2.1/`
- **Server Code**: `/opt/mrhOTshOT/final_things/iec104_water_tank/server/`
- **HMI Code**: `/opt/mrhOTshOT/final_things/iec104_water_tank/hmi/`
- **Configuration**: `/opt/mrhOTshOT/final_things/iec104_water_tank/common/config.py`

## Next Steps

1. **Read the documentation**:
   - [README.md](README.md) - Full project documentation
   - [QUICKSTART.md](QUICKSTART.md) - Quick start guide
   - [PROJECT_SUMMARY.md](PROJECT_SUMMARY.md) - Technical overview

2. **Experiment with the system**:
   - Switch between Auto and Manual modes
   - Trigger alarm conditions
   - Monitor IEC-104 traffic
   - Modify tank parameters in config.py

3. **Extend the system**:
   - Add more sensors
   - Implement additional automation logic
   - Create custom HMI screens
   - Log data to database

## Support

For issues related to:
- **c104 library**: https://github.com/Fraunhofer-FIT-DIEN/iec104-python
- **IEC 60870-5-104 protocol**: https://github.com/mz-automation/lib60870

## License

This water tank simulation project is provided for educational and demonstration purposes.

The c104 library is licensed under GPL v3.
