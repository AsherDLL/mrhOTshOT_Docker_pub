#!/bin/bash
###############################################################################
# Verify mrhOTshOT Setup
# Run this script to check if your environment is properly configured
# This is helpful after running setup scripts to ensure everything is ready
###############################################################################

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

PASS_COUNT=0
FAIL_COUNT=0
WARN_COUNT=0

echo "========================================="
echo "mrhOTshOT Setup Verification"
echo "========================================="
echo ""

# Function to check and report
check_pass() {
    echo -e "${GREEN}[+]${NC} $1"
    ((PASS_COUNT++))
}

check_fail() {
    echo -e "${RED}[-]${NC} $1"
    ((FAIL_COUNT++))
}

check_warn() {
    echo -e "${YELLOW}[!]${NC} $1"
    ((WARN_COUNT++))
}

echo "=== System Information ==="
echo "Hostname: $(hostname)"
echo "OS: $(uname -s)"
echo "IP Addresses:"
ip -4 addr show | grep inet | awk '{print "  " $NF ": " $2}'
echo ""

echo "=== Python Environment ==="
if command -v python3 &> /dev/null; then
    check_pass "Python3 installed: $(python3 --version)"
else
    check_fail "Python3 NOT installed"
fi

if command -v pip3 &> /dev/null; then
    check_pass "pip3 installed: $(pip3 --version | head -1)"
else
    check_fail "pip3 NOT installed"
fi
echo ""

echo "=== Critical Python Packages ==="
for pkg in requests flask impacket pypykatz c104; do
    if pip3 show $pkg &> /dev/null; then
        version=$(pip3 show $pkg | grep Version | cut -d' ' -f2)
        check_pass "$pkg installed: $version"
    else
        check_warn "$pkg NOT installed (may not be needed on this machine)"
    fi
done
echo ""

echo "=== Network Tools ==="
for tool in nmap smbclient sshpass curl wget nc; do
    if command -v $tool &> /dev/null; then
        check_pass "$tool installed"
    else
        check_warn "$tool NOT installed (may not be needed on this machine)"
    fi
done
echo ""

echo "=== mrhOTshOT Directory Structure ==="
if [ -d "machines/attacker" ]; then
    check_pass "machines/attacker exists"
else
    check_fail "machines/attacker NOT found"
fi

if [ -d "machines/router" ]; then
    check_pass "machines/router exists"
else
    check_fail "machines/router NOT found"
fi

if [ -d "machines/hmi" ]; then
    check_pass "machines/hmi exists"
else
    check_fail "machines/hmi NOT found"
fi

if [ -d "machines/plc" ]; then
    check_pass "machines/plc exists"
else
    check_fail "machines/plc NOT found"
fi

if [ -d "execution" ]; then
    check_pass "execution directory exists"
else
    check_fail "execution directory NOT found"
fi

if [ -d "docs" ]; then
    check_pass "docs directory exists"
else
    check_fail "docs directory NOT found"
fi
echo ""

echo "=== Critical Scripts ==="
if [ -f "machines/attacker/scripts/MASTER_ATTACK_ORCHESTRATOR.py" ]; then
    check_pass "MASTER_ATTACK_ORCHESTRATOR.py exists"
else
    check_fail "MASTER_ATTACK_ORCHESTRATOR.py NOT found"
fi

if [ -f "execution/run_attack.sh" ]; then
    if [ -x "execution/run_attack.sh" ]; then
        check_pass "run_attack.sh exists and is executable"
    else
        check_warn "run_attack.sh exists but is NOT executable (run: chmod +x execution/run_attack.sh)"
    fi
else
    check_fail "run_attack.sh NOT found"
fi

if [ -f "execution/start_router.sh" ]; then
    if [ -x "execution/start_router.sh" ]; then
        check_pass "start_router.sh exists and is executable"
    else
        check_warn "start_router.sh exists but is NOT executable"
    fi
else
    check_warn "start_router.sh NOT found (may not be needed on this machine)"
fi

if [ -f "execution/start_plc.sh" ]; then
    if [ -x "execution/start_plc.sh" ]; then
        check_pass "start_plc.sh exists and is executable"
    else
        check_warn "start_plc.sh exists but is NOT executable"
    fi
else
    check_warn "start_plc.sh NOT found (may not be needed on this machine)"
fi
echo ""

echo "=== Network Connectivity ==="
if ping -c 1 -W 1 192.168.0.13 &> /dev/null; then
    check_pass "Can reach Router (192.168.0.13)"
else
    check_warn "Cannot reach Router (192.168.0.13)"
fi

if ping -c 1 -W 1 192.168.1.55 &> /dev/null; then
    check_pass "Can reach HMI (192.168.1.55)"
else
    check_warn "Cannot reach HMI (192.168.1.55)"
fi

if ping -c 1 -W 1 192.168.1.6 &> /dev/null; then
    check_pass "Can reach PLC (192.168.1.6)"
else
    check_warn "Cannot reach PLC (192.168.1.6)"
fi
echo ""

echo "=== Services ==="
if curl -s http://192.168.0.13:8080 &> /dev/null; then
    check_pass "Router web server is running (port 8080)"
else
    check_warn "Router web server is NOT running (start with: ./execution/start_router.sh)"
fi

if nc -zv 192.168.1.6 2404 2>&1 | grep -q succeeded || nc -zv 192.168.1.6 2404 2>&1 | grep -q open; then
    check_pass "PLC IEC-104 server is running (port 2404)"
else
    check_warn "PLC IEC-104 server is NOT running (start with: ./execution/start_plc.sh)"
fi
echo ""

echo "=== IP Forwarding (Router only) ==="
if sysctl net.ipv4.ip_forward 2>/dev/null | grep -q "= 1"; then
    check_pass "IP forwarding is ENABLED"
elif sysctl net.ipv4.ip_forward 2>/dev/null | grep -q "= 0"; then
    check_fail "IP forwarding is DISABLED (enable with: sudo sysctl -w net.ipv4.ip_forward=1)"
else
    check_warn "Cannot check IP forwarding (may not be Router machine)"
fi
echo ""

echo "========================================="
echo "Verification Summary"
echo "========================================="
echo ""
echo -e "${GREEN}Passed: ${PASS_COUNT}${NC}"
echo -e "${YELLOW}Warnings: ${WARN_COUNT}${NC}"
echo -e "${RED}Failed: ${FAIL_COUNT}${NC}"
echo ""

if [ $FAIL_COUNT -eq 0 ]; then
    echo -e "${GREEN}[+] Setup looks good!${NC}"
    echo ""
    echo "Next steps:"
    echo "  1. Ensure services are running:"
    echo "     - On Router: cd execution && ./start_router.sh"
    echo "     - On PLC: cd execution && ./start_plc.sh"
    echo "  2. Run attack:"
    echo "     - On Attacker: cd execution && ./run_attack.sh"
else
    echo -e "${RED}[-] Setup has issues that need to be fixed${NC}"
    echo ""
    echo "Recommendations:"
    echo "  1. Review failed checks above"
    echo "  2. Re-run appropriate setup script:"
    echo "     - machines/attacker/setup.sh"
    echo "     - machines/router/setup.sh"
    echo "     - machines/plc/setup.sh"
    echo "     - machines/hmi/setup.ps1 (on Windows)"
    echo "  3. Check documentation: docs/SETUP_GUIDE.md"
fi
echo ""

if [ $WARN_COUNT -gt 0 ]; then
    echo "Note: Warnings are OK if you're not on the corresponding machine"
    echo "      (e.g., Router warnings on Attacker machine are normal)"
    echo ""
fi
