# Quick Start Guide

## Installation & Setup (5 minutes)

### Step 1: Install Dependencies

```bash
cd /opt/mrhOTshOT/final_things/iec104_water_tank

# Create virtual environment
python3 -m venv venv
source venv/bin/activate  # On Windows: venv\Scripts\activate

# Install required packages
pip install lib60870
```

**Note**: tkinter is usually included with Python. If you get an error about tkinter:
- macOS: `brew install python-tk`
- Ubuntu/Debian: `sudo apt-get install python3-tk`
- Windows: Reinstall Python with tkinter option checked

### Step 2: Start the Server

Open a terminal:

```bash
cd /opt/mrhOTshOT/final_things/iec104_water_tank
source venv/bin/activate
python -m server.iec104_server
```

Or use the helper script:
```bash
./run_server.sh
```

You should see:
```
Starting IEC-104 server on 0.0.0.0:2404
IEC-104 server started successfully
Water Tank IEC-104 Server running...
```

### Step 3: Start the HMI

Open a **new** terminal:

```bash
cd /opt/mrhOTshOT/final_things/iec104_water_tank
source venv/bin/activate
python -m hmi.hmi_client
```

Or use the helper script:
```bash
./run_hmi.sh
```

A graphical window will open showing the water tank control system!

## What You'll See

### Server Terminal
```
=== Tank Status ===
Water Level: 52.3%
Pressure: 2.56 bar
Temperature: 20.8°C
Inlet Valve: 100%
Outlet Valve: 0%
Pump: ON
Mode: AUTO
```

### HMI Window
- **Tank Visualization**: Animated water level with color coding
- **Measurements**: Real-time level, pressure, temperature
- **Control Mode**: Switch between Auto/Manual
- **Equipment Status**: Valve and pump indicators (green when active)
- **Manual Controls**: Buttons to control valves and pump (enabled in Manual mode)
- **Alarms**: Overflow and low-level warnings

## Try It Out!

### Test 1: Watch Automatic Control (1 minute)
1. Just watch! The tank will auto-regulate
2. Water level stays between 20-80%
3. Pump turns on/off automatically
4. Status updates every 5 seconds in server terminal

### Test 2: Manual Control (2 minutes)
1. In HMI, click **"Manual Mode"**
2. Click **"Open Inlet Valve"** - watch water level rise
3. Click **"Start Pump"** - faster filling
4. Click **"Close Inlet Valve"** when satisfied
5. Click **"Open Outlet Valve"** - watch water drain
6. Switch back to **"Automatic Mode"** - system takes over

### Test 3: Trigger Alarms (2 minutes)
1. Switch to Manual mode
2. Open inlet valve fully + start pump
3. Close outlet valve
4. Wait for overflow alarm (at 98%)
5. Switch to Auto mode - watch automatic drainage!

## Common Commands

### View Server Logs
```bash
tail -f iec104_water_tank.log
```

### Stop Everything
- HMI: Close the window or press Ctrl+C in terminal
- Server: Press Ctrl+C in server terminal

### Reset Water Level
Edit `server/water_tank.py` line 28:
```python
self.water_level = 50.0  # Change this value (0-100)
```

## Troubleshooting

**Problem**: "ModuleNotFoundError: No module named 'lib60870'"
- **Solution**: `pip install lib60870`

**Problem**: "ModuleNotFoundError: No module named 'tkinter'"
- **Solution**: Install python3-tk for your OS (see Step 1)

**Problem**: HMI shows "Disconnected"
- **Solution**: Make sure server is running first!

**Problem**: Manual controls are grayed out
- **Solution**: Switch to "Manual Mode" first

**Problem**: "Address already in use" error
- **Solution**: Another process is using port 2404
  ```bash
  # Find and kill the process (macOS/Linux)
  lsof -ti:2404 | xargs kill -9
  ```

## Next Steps

- Read [README.md](README.md) for full documentation
- Customize parameters in [common/config.py](common/config.py)
- Explore IEC-104 protocol details
- Modify tank physics in [server/water_tank.py](server/water_tank.py)

## Architecture Overview

```
┌─────────────────┐         IEC-104          ┌──────────────────┐
│   HMI Client    │◄───── Protocol ────────►│  IEC-104 Server  │
│   (Tkinter)     │      (Port 2404)        │                  │
└─────────────────┘                          └────────┬─────────┘
                                                      │
                                                      │
                                              ┌───────▼─────────┐
                                              │  Water Tank     │
                                              │  Simulation     │
                                              │  - Physics      │
                                              │  - Automation   │
                                              └─────────────────┘
```

Enjoy your IEC-104 water tank simulation! 
