# Triton/TRISIS Malware Simulation Design

## Overview

Add a Triton/TRISIS malware simulation to the mrhOTshOT ICS security lab. The simulation adds a Safety Instrumented System (SIS) to the water tank setup and demonstrates how the Triton malware disables safety protections before attacking the process.

## Architecture

```
ATTACKER (192.168.0.11)
    │
    │ Phase 1-4: Same attack chain (router exploit → recon → lateral movement → HMI)
    ▼
ROUTER (192.168.0.13 / 192.168.1.4)
    │
    ├──────────────────────────────────┐
    ▼                                  ▼
HMI (192.168.1.55)                 SIS (192.168.1.8) ◄── NEW
    │                                  │
    │ Triton payload                   │ IEC-104 monitoring
    │ (TriStation, port 1502)          │ (reads from PLC:2404)
    │                                  │
    ▼                                  ▼
    └──────────────────────────────► PLC (192.168.1.6)
         Direct attack                 Water Tank
         (IEC-104, port 2404)          (port 2404)
```

## Components

### 1. SIS Server (`triconex_sis_server.py`) - NEW

Runs on 192.168.1.8. Two roles:

**IEC-104 client (monitoring):**
- Connects to PLC at 192.168.1.6:2404
- Reads water level every 1-2 seconds
- When level exceeds threshold (90%), sends trip command to PLC
- Broadcasts status: ARMED / TRIPPED / DISABLED

**TriStation server (attack surface):**
- Listens on TCP port 1502
- Simulated TriStation protocol commands: GET_STATUS, GET_CONFIG, DISABLE_SAFETY, ENABLE_SAFETY
- DISABLE_SAFETY stops the monitoring loop (Triton's target)

### 2. Water Tank PLC Changes (`water_tank_server.py`) - MODIFY

- Add `--with-sis` and `--sis-ip` flags
- Accept trip commands from SIS over IEC-104
- New IOA for SIS trip status
- When tripped: inlet valve closes, pump stops, drain opens (safe state)
- Without `--with-sis`, behavior is unchanged

### 3. Direct Water Tank Attack (`direct_water_tank_attack.py`) - NEW

- Simple IEC-104 attack: opens inlet, closes drain, max pump
- Demonstrates that SIS catches overflow and trips
- Uses c104 library, follows existing simulation patterns

### 4. Triton Malware Script (`triton_simulation.py`) - NEW

- Runs from HMI (192.168.1.55)
- Phase 1: Connect to SIS at 192.168.1.8:1502, send DISABLE_SAFETY
- Phase 2: Launch IEC-104 overflow attack against PLC at 192.168.1.6:2404
- Result: SIS disabled, overflow succeeds

### 5. HMI GUI Changes - MODIFY

- Add SIS status panel: status indicator, threshold, host, last check time
- Three states: ARMED (green), TRIPPED (amber), DISABLED (red)
- Polls SIS on port 1502 every 2 seconds
- Shows "NOT CONFIGURED" when PLC started without `--with-sis`

## Demo Flow

```
Step 1: Start PLC with SIS → python3 water_tank_server.py --port 2404 --with-sis --sis-ip 192.168.1.8
Step 2: Start SIS server   → python3 triconex_sis_server.py --plc-ip 192.168.1.6 --threshold 90
Step 3: Start HMI          → HMI shows water tank + SIS panel (ARMED, green)
Step 4: Direct attack       → SIS trips at 90% → HMI flashes amber → attack blocked
Step 5: Reset, restart
Step 6: Triton attack       → SIS disabled (red) → overflow past 90% → no trip → damage
```

## File Layout

New files:
- `final_things/iec104_water_tank/triconex_sis_server.py`
- `final_things/iec104_water_tank/perform_malware_simulations/triton_simulation.py`
- `final_things/iec104_water_tank/perform_malware_simulations/direct_water_tank_attack.py`

Modified files:
- `final_things/iec104_water_tank/water_tank_server.py`
- `final_things/iec104_water_tank/hmi/` (GUI files)
