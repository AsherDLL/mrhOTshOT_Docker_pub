#!/bin/bash
###############################################################################
# Start PLC/RTU Water Tank Server
# Run this on the PLC machine (192.168.1.6)
###############################################################################

echo "========================================="
echo "Starting Water Tank IEC-104 Server"
echo "========================================="
echo ""

# Find script directory
SCRIPT_DIR="$( cd "$( dirname "${BASH_SOURCE[0]}" )" && pwd )"
PLC_DIR="$SCRIPT_DIR/../machines/plc"

cd "$PLC_DIR/server"

echo "[*] Starting IEC-104 server on port 2404..."
echo "[*] Water tank simulation active"
echo "[*] Press Ctrl+C to stop"
echo ""

python3 iec104_server.py

# Alternative: run as systemd service
# sudo systemctl start water-tank
# sudo systemctl status water-tank
