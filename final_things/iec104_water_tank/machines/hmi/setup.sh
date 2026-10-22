#!/bin/bash
###############################################################################
# mrhOTshOT - HMI Machine Setup Script (Linux/WSL)
# Platform: WSL on Windows or Linux
# IP: 192.168.1.55
# Purpose: Install Python environment for HMI clients
###############################################################################

set -e

echo "========================================="
echo "mrhOTshOT HMI Setup (Python/WSL)"
echo "========================================="
echo ""

SCRIPT_DIR="$( cd "$( dirname "${BASH_SOURCE[0]}" )" && pwd )"

echo "[*] Installing Python packages..."
pip3 install --upgrade pip
pip3 install \
    flask \
    requests \
    c104 \
    pymodbus \
    python-snap7 \
    opcua

echo ""
echo "[*] Installing c104 library..."
cd "$SCRIPT_DIR/../../libs/c104-2.2.1"
pip3 install .

echo ""
echo "[*] Verifying installations..."
python3 -c "import c104" || { echo "[-] c104 installation failed"; exit 1; }
python3 -c "import flask" || { echo "[-] flask installation failed"; exit 1; }

echo ""
echo "[*] Setting up HMI clients..."
cd "$SCRIPT_DIR/hmi_clients"
chmod +x *.py 2>/dev/null || true

echo ""
echo "========================================="
echo "[+] HMI Python environment ready!"
echo "========================================="
echo ""
echo "To run HMI client:"
echo "  cd hmi_clients"
echo "  python3 iec104_client.py"
echo ""
