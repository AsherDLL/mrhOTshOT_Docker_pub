#!/bin/bash
###############################################################################
# mrhOTshOT - Attacker Machine Setup Script
# Platform: Kali Linux or Ubuntu
# IP: 192.168.0.11
# Purpose: Install all dependencies for Industroyer2 attack simulation
###############################################################################

set -e  # Exit on error

echo "========================================="
echo "mrhOTshOT Attacker Setup"
echo "========================================="
echo ""

# Check if running as root
if [[ $EUID -ne 0 ]]; then
   echo "[!] This script must be run as root (sudo)"
   exit 1
fi

# Get the actual user (not root)
ACTUAL_USER=${SUDO_USER:-$USER}
SCRIPT_DIR="$( cd "$( dirname "${BASH_SOURCE[0]}" )" && pwd )"

echo "[*] Installing system packages..."
apt-get update
apt-get install -y \
    python3 \
    python3-pip \
    python3-dev \
    nmap \
    smbclient \
    sshpass \
    xfreerdp \
    xvfb \
    curl \
    wget \
    git \
    build-essential

echo ""
echo "[*] Installing Python packages..."
pip3 install --upgrade pip
pip3 install \
    requests \
    flask \
    impacket \
    pypykatz \
    pywinrm \
    pwntools

echo ""
echo "[*] Installing impacket tools..."
# Ensure impacket scripts are in PATH
if ! command -v impacket-psexec &> /dev/null; then
    echo "[*] Installing impacket from GitHub..."
    cd /tmp
    git clone https://github.com/fortra/impacket.git
    cd impacket
    pip3 install .
    python3 setup.py install
    cd ..
    rm -rf impacket
fi

echo ""
echo "[*] Verifying installations..."
command -v python3 >/dev/null 2>&1 || { echo "[-] Python3 not found"; exit 1; }
command -v nmap >/dev/null 2>&1 || { echo "[-] nmap not found"; exit 1; }
command -v smbclient >/dev/null 2>&1 || { echo "[-] smbclient not found"; exit 1; }
command -v sshpass >/dev/null 2>&1 || { echo "[-] sshpass not found"; exit 1; }
command -v xfreerdp >/dev/null 2>&1 || { echo "[-] xfreerdp not found"; exit 1; }
python3 -c "import impacket" >/dev/null 2>&1 || { echo "[-] impacket not found"; exit 1; }

echo ""
echo "[*] Setting up attack scripts..."
cd "$SCRIPT_DIR/scripts"
chmod +x *.py 2>/dev/null || true

echo ""
echo "[*] Creating working directories..."
mkdir -p /tmp/mrhOTshOT/{logs,payloads,dumps}
chown -R $ACTUAL_USER:$ACTUAL_USER /tmp/mrhOTshOT

echo ""
echo "========================================="
echo "[+] Attacker setup complete!"
echo "========================================="
echo ""
echo "Next steps:"
echo "1. Verify network connectivity: ping 192.168.1.55"
echo "2. Test SSH to router: ssh admin@192.168.0.13"
echo "3. Run attack: cd scripts && sudo ./MASTER_ATTACK_ORCHESTRATOR.py"
echo ""
