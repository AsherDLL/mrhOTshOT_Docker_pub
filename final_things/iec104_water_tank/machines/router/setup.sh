#!/bin/bash
###############################################################################
# mrhOTshOT - Router Machine Setup Script
# Platform: Ubuntu/Debian Linux
# IP: 192.168.0.13 (external), 192.168.1.4 (internal), 192.168.100.2 (OT)
# Purpose: Setup vulnerable router web server
###############################################################################

set -e

echo "========================================="
echo "mrhOTshOT Router Setup"
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
    nmap \
    openssh-server \
    net-tools \
    iptables

echo ""
echo "[*] Installing Python packages..."
pip3 install --upgrade pip
pip3 install flask requests

echo ""
echo "[*] Configuring SSH server..."
# Enable SSH password authentication
sed -i 's/#PasswordAuthentication yes/PasswordAuthentication yes/' /etc/ssh/sshd_config
sed -i 's/PasswordAuthentication no/PasswordAuthentication yes/' /etc/ssh/sshd_config
systemctl restart sshd

echo ""
echo "[*] Creating router users..."
# Create admin user (password: admin)
if ! id "admin" &>/dev/null; then
    useradd -m -s /bin/bash admin
    echo "admin:admin" | chpasswd
    echo "[+] Created user: admin (password: admin)"
fi

# Create operator user (password: labpass123)
if ! id "operator" &>/dev/null; then
    useradd -m -s /bin/bash operator
    echo "operator:labpass123" | chpasswd
    echo "[+] Created user: operator (password: labpass123)"
fi

echo ""
echo "[*] Configuring network interfaces..."
# Enable IP forwarding for routing
echo 1 > /proc/sys/net/ipv4/ip_forward
sed -i 's/#net.ipv4.ip_forward=1/net.ipv4.ip_forward=1/' /etc/sysctl.conf

echo ""
echo "[*] Setting up vulnerable router server..."
cd "$SCRIPT_DIR"
chmod +x vulnerable_router_server.py

# Create systemd service
cat > /etc/systemd/system/vulnerable-router.service << 'EOFSERVICE'
[Unit]
Description=Vulnerable Router Web Server (mrhOTshOT)
After=network.target

[Service]
Type=simple
User=root
WorkingDirectory=SCRIPT_DIR_PLACEHOLDER
ExecStart=/usr/bin/python3 SCRIPT_DIR_PLACEHOLDER/vulnerable_router_server.py
Restart=always

[Install]
WantedBy=multi-user.target
EOFSERVICE

# Replace placeholder with actual path
sed -i "s|SCRIPT_DIR_PLACEHOLDER|$SCRIPT_DIR|g" /etc/systemd/system/vulnerable-router.service

systemctl daemon-reload
systemctl enable vulnerable-router.service

echo ""
echo "========================================="
echo "[+] Router setup complete!"
echo "========================================="
echo ""
echo "Configuration:"
echo "  - SSH enabled (port 22)"
echo "  - Users: admin:admin, operator:labpass123"
echo "  - Web server will run on port 8080"
echo ""
echo "To start vulnerable router:"
echo "  sudo systemctl start vulnerable-router"
echo ""
echo "To test:"
echo "  curl http://localhost:8080"
echo ""
