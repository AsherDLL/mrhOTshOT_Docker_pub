#!/bin/bash
###############################################################################
# mrhOTshOT - PLC/RTU Machine Setup Script
# Platform: Ubuntu/Debian Linux
# IP: 192.168.1.6
# Purpose: Setup water tank IEC-104 server
###############################################################################

set -e

echo "========================================="
echo "mrhOTshOT PLC/RTU Setup"
echo "========================================="
echo ""

# Check if running as root
if [[ $EUID -ne 0 ]]; then
   echo "[!] This script must be run as root (sudo)"
   exit 1
fi

ACTUAL_USER=${SUDO_USER:-$USER}
SCRIPT_DIR="$( cd "$( dirname "${BASH_SOURCE[0]}" )" && pwd )"

echo "[*] Installing system packages..."
apt-get update
apt-get install -y \
    python3 \
    python3-pip \
    python3-dev \
    build-essential \
    cmake \
    git

echo ""
echo "[*] Installing Python packages..."
pip3 install --upgrade pip
pip3 install \
    flask \
    requests \
    pymodbus

echo ""
echo "[*] Installing c104 library for IEC-104..."
cd "$SCRIPT_DIR/../../libs/c104-2.2.1"
pip3 install .

echo ""
echo "[*] Verifying c104 installation..."
python3 -c "import c104" || { echo "[-] c104 installation failed"; exit 1; }

echo ""
echo "[*] Setting up water tank server..."
cd "$SCRIPT_DIR/server"
chmod +x water_tank.py iec104_server.py

# Create systemd service for water tank
cat > /etc/systemd/system/water-tank.service << 'EOFSERVICE'
[Unit]
Description=Water Tank IEC-104 Server (mrhOTshOT)
After=network.target

[Service]
Type=simple
User=root
WorkingDirectory=SCRIPT_DIR_PLACEHOLDER/server
ExecStart=/usr/bin/python3 SCRIPT_DIR_PLACEHOLDER/server/iec104_server.py
Restart=always
RestartSec=10

[Install]
WantedBy=multi-user.target
EOFSERVICE

# Replace placeholder
sed -i "s|SCRIPT_DIR_PLACEHOLDER|$SCRIPT_DIR|g" /etc/systemd/system/water-tank.service

systemctl daemon-reload
systemctl enable water-tank.service

echo ""
echo "[*] Creating working directories..."
mkdir -p /var/log/mrhOTshOT
chown -R $ACTUAL_USER:$ACTUAL_USER /var/log/mrhOTshOT

echo ""
echo "========================================="
echo "[+] PLC/RTU setup complete!"
echo "========================================="
echo ""
echo "Configuration:"
echo "  - IEC-104 server on port 2404"
echo "  - Water tank simulation active"
echo "  - Logs: /var/log/mrhOTshOT/"
echo ""
echo "To start water tank:"
echo "  sudo systemctl start water-tank"
echo ""
echo "To test:"
echo "  sudo systemctl status water-tank"
echo "  nc -zv localhost 2404"
echo ""
