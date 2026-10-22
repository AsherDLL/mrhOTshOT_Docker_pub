#!/bin/bash
###############################################################################
# Reset mrhOTshOT Environment
# Cleans up attack artifacts and resets services to initial state
# Run this after completing an attack simulation
###############################################################################

echo "========================================="
echo "mrhOTshOT Environment Reset"
echo "========================================="
echo ""

echo "[!] WARNING: This will:"
echo "    - Stop all running services"
echo "    - Delete attack logs and artifacts"
echo "    - Remove transferred payloads"
echo "    - Reset water tank simulation"
echo ""
read -p "Continue? [y/N]: " -n 1 -r
echo
if [[ ! $REPLY =~ ^[Yy]$ ]]; then
    echo "[-] Reset cancelled"
    exit 1
fi

echo ""
echo "========================================="
echo "Stopping Services"
echo "========================================="
echo ""

# Kill any running Python attack processes
echo "[*] Stopping attack orchestrator..."
pkill -f MASTER_ATTACK_ORCHESTRATOR 2>/dev/null && echo "  [+] Stopped" || echo "  - Not running"

echo "[*] Stopping phishing server..."
pkill -f phishing_server 2>/dev/null && echo "  [+] Stopped" || echo "  - Not running"

echo "[*] Stopping HTTP servers..."
pkill -f "http.server" 2>/dev/null && echo "  [+] Stopped" || echo "  - Not running"

echo "[*] Stopping vulnerable router..."
pkill -f vulnerable_router_server 2>/dev/null && echo "  [+] Stopped" || echo "  - Not running"

echo "[*] Stopping water tank server..."
pkill -f iec104_server 2>/dev/null && echo "  [+] Stopped" || echo "  - Not running"

# Stop systemd services if they exist
if command -v systemctl &> /dev/null; then
    echo "[*] Stopping systemd services..."
    sudo systemctl stop vulnerable-router 2>/dev/null && echo "  [+] vulnerable-router stopped" || echo "  - vulnerable-router not running"
    sudo systemctl stop water-tank 2>/dev/null && echo "  [+] water-tank stopped" || echo "  - water-tank not running"
fi

echo ""
echo "========================================="
echo "Cleaning Attack Artifacts"
echo "========================================="
echo ""

# Find script directory
SCRIPT_DIR="$( cd "$( dirname "${BASH_SOURCE[0]}" )" && pwd )"
ROOT_DIR="$(dirname "$SCRIPT_DIR")"

# Clean attacker machine logs
echo "[*] Cleaning attacker logs..."
cd "$ROOT_DIR/machines/attacker/scripts" 2>/dev/null || cd .
rm -f attack_orchestrator_*.log 2>/dev/null && echo "  [+] Removed orchestrator logs" || echo "  - No logs found"
rm -f attack_log_*.json 2>/dev/null && echo "  [+] Removed JSON logs" || echo "  - No logs found"
rm -f phase_*.log 2>/dev/null && echo "  [+] Removed phase logs" || echo "  - No logs found"
rm -f captured_credentials.txt 2>/dev/null && echo "  [+] Removed credentials" || echo "  - No credentials found"
rm -f payload.zip 2>/dev/null && echo "  [+] Removed payload.zip" || echo "  - No payload found"
rm -f PsExec.exe 2>/dev/null && echo "  [+] Removed PsExec.exe" || echo "  - No PsExec found"

# Clean temp directories
echo "[*] Cleaning temporary directories..."
rm -rf /tmp/mrhOTshOT 2>/dev/null && echo "  [+] Removed /tmp/mrhOTshOT" || echo "  - Directory not found"
rm -f /tmp/rdp_transfer.sh 2>/dev/null && echo "  [+] Removed RDP script" || echo "  - No script found"

# Note: HMI cleanup must be done on Windows machine
echo ""
echo "[!] NOTE: On HMI (Windows), manually run:"
echo "    Remove-Item C:\\Temp\\* -Recurse -Force"
echo "    Remove-Item C:\\Logs\\mrhOTshOT\\* -Recurse -Force"

echo ""
echo "========================================="
echo "Restarting Services"
echo "========================================="
echo ""

# Restart services in clean state
if command -v systemctl &> /dev/null; then
    echo "[*] Restarting vulnerable router..."
    sudo systemctl restart vulnerable-router 2>/dev/null && echo "  [+] Router restarted" || echo "  - Service not configured"
    
    echo "[*] Restarting water tank..."
    sudo systemctl restart water-tank 2>/dev/null && echo "  [+] Water tank restarted" || echo "  - Service not configured"
fi

echo ""
echo "========================================="
echo "Verifying Services"
echo "========================================="
echo ""

# Verify router is accessible
echo "[*] Testing router web server..."
if curl -s http://192.168.0.13:8080 >/dev/null 2>&1; then
    echo "  [+] Router web server is running"
else
    echo "  [-] Router web server is NOT running"
    echo "    Start manually: cd $ROOT_DIR/execution && ./start_router.sh"
fi

# Verify PLC is accessible
echo "[*] Testing PLC IEC-104 server..."
if nc -zv 192.168.1.6 2404 2>&1 | grep -q succeeded || nc -zv 192.168.1.6 2404 2>&1 | grep -q open; then
    echo "  [+] PLC IEC-104 server is running"
else
    echo "  [-] PLC IEC-104 server is NOT running"
    echo "    Start manually: cd $ROOT_DIR/execution && ./start_plc.sh"
fi

echo ""
echo "========================================="
echo "Reset Complete"
echo "========================================="
echo ""
echo "Environment has been reset to initial state."
echo "You can now run a new attack simulation."
echo ""
echo "To start services manually:"
echo "  - Router: cd $ROOT_DIR/execution && ./start_router.sh"
echo "  - PLC: cd $ROOT_DIR/execution && ./start_plc.sh"
echo ""
echo "To run attack:"
echo "  cd $ROOT_DIR/execution && ./run_attack.sh"
echo ""
