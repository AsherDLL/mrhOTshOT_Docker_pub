#!/bin/bash
###############################################################################
# Execute Full Industroyer2 Attack Chain
# Run this on the Attacker machine (192.168.0.11)
###############################################################################

set -e

echo "========================================="
echo "mrhOTshOT - Industroyer2 Attack Chain"
echo "========================================="
echo ""

# Find script directory
SCRIPT_DIR="$( cd "$( dirname "${BASH_SOURCE[0]}" )" && pwd )"
ATTACKER_DIR="$SCRIPT_DIR/../machines/attacker/scripts"

cd "$ATTACKER_DIR"

echo "[!] WARNING: This will execute a REAL attack simulation!"
echo "[!] Only proceed if:"
echo "    1. You are in an authorized lab environment"
echo "    2. All target machines are ready (PLC, Router, HMI)"
echo "    3. Palo Alto products are monitoring"
echo ""
read -p "Continue? [y/N]: " -n 1 -r
echo
if [[ ! $REPLY =~ ^[Yy]$ ]]; then
    echo "[-] Attack cancelled"
    exit 1
fi

echo ""
echo "========================================="
echo "Pre-Flight Checks"
echo "========================================="
echo ""

# Check connectivity
echo "[*] Checking connectivity to target machines..."

echo -n "  - Router (192.168.0.13): "
if ping -c 1 -W 1 192.168.0.13 &> /dev/null; then
    echo "[+] REACHABLE"
else
    echo "[-] UNREACHABLE"
    echo "[-] Cannot reach router. Ensure it's running."
    exit 1
fi

echo -n "  - HMI (192.168.1.55): "
if ping -c 1 -W 1 192.168.1.55 &> /dev/null; then
    echo "[+] REACHABLE"
else
    echo "[-] UNREACHABLE"
    echo "[-] Cannot reach HMI. Ensure it's running."
    exit 1
fi

echo -n "  - PLC (192.168.1.6): "
if ping -c 1 -W 1 192.168.1.6 &> /dev/null; then
    echo "[+] REACHABLE"
else
    echo "[-] UNREACHABLE"
    echo "[-] Cannot reach PLC. Ensure water tank is running."
    exit 1
fi

echo ""
echo "[*] Checking required tools..."
command -v python3 >/dev/null 2>&1 || { echo "[-] python3 not found"; exit 1; }
command -v nmap >/dev/null 2>&1 || { echo "[-] nmap not found"; exit 1; }
command -v smbclient >/dev/null 2>&1 || { echo "[-] smbclient not found"; exit 1; }

echo "[+] All pre-flight checks passed!"
echo ""

echo "========================================="
echo "Attack Execution Options"
echo "========================================="
echo ""
echo "1. Full automated attack (all 7 phases)"
echo "2. Interactive mode (confirm each phase)"
echo "3. Manual phase selection"
echo ""
read -p "Select mode [1-3]: " -n 1 -r
echo ""

case $REPLY in
    1)
        echo "[*] Running full automated attack..."
        python3 MASTER_ATTACK_ORCHESTRATOR.py --auto-yes
        ;;
    2)
        echo "[*] Running interactive attack..."
        python3 MASTER_ATTACK_ORCHESTRATOR.py
        ;;
    3)
        echo "[*] Manual mode - use MASTER_ATTACK_ORCHESTRATOR.py with --help"
        python3 MASTER_ATTACK_ORCHESTRATOR.py --help
        ;;
    *)
        echo "[-] Invalid selection"
        exit 1
        ;;
esac

echo ""
echo "========================================="
echo "Attack Complete"
echo "========================================="
echo ""
echo "Next steps:"
echo "1. Check XSIAM for attack chain correlation"
echo "2. Review Cortex XDR alerts"
echo "3. Verify Device Security detections"
echo "4. Check WildFire submissions"
echo ""
echo "Logs saved to:"
echo "  - $(pwd)/attack_orchestrator_*.log"
echo "  - $(pwd)/attack_log_*.json"
echo ""
