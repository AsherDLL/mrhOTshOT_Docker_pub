#!/bin/bash
###############################################################################
# Start Vulnerable Router Web Server
# Run this on the Router machine (192.168.0.13)
###############################################################################

echo "========================================="
echo "Starting Vulnerable Router Web Server"
echo "========================================="
echo ""

# Find script directory
SCRIPT_DIR="$( cd "$( dirname "${BASH_SOURCE[0]}" )" && pwd )"
ROUTER_DIR="$SCRIPT_DIR/../machines/router"

cd "$ROUTER_DIR"

echo "[*] Starting vulnerable router on port 8080..."
echo "[*] WARNING: This server has intentional vulnerabilities!"
echo "[*] Command injection via /execute endpoint"
echo "[*] Press Ctrl+C to stop"
echo ""

python3 vulnerable_router_server.py

# Alternative: run as systemd service
# sudo systemctl start vulnerable-router
# sudo systemctl status vulnerable-router
