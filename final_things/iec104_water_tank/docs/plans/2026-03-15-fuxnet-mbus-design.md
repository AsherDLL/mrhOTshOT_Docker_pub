# Fuxnet Malware Simulation Design

## Overview

Add Fuxnet malware simulation targeting M-Bus sensor gateways. Separate M-Bus gateway process on 192.168.1.6:5000 reads water tank data from PLC via IEC-104 and serves it over M-Bus TCP. Fuxnet corrupts sensors then bricks the gateway.

## Components

1. **M-Bus Gateway Server** (`mbus_gateway_server.py`) - Port 5000, real M-Bus protocol
2. **Fuxnet Simulation** (`fuxnet_simulation.py`) - 3-phase: recon, corrupt, brick
3. **HMI M-Bus Panel** - ONLINE/CORRUPTED/OFFLINE status display
4. **Lab scripts** - start_fuxnet_lab.sh, run_fuxnet_attack.sh
5. **Setup directory** - setup/fuxnet/

## Attack Flow

Phase 1: Recon - SND_NKE + REQ_UD2 to enumerate sensors
Phase 2: Corrupt - SND_UD with bad data, gateway spoofs readings
Phase 3: Brick - Flood malformed frames, gateway goes offline
Combo: Chain with direct overflow attack while operator is blind
