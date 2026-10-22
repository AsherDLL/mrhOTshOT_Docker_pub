#!/bin/bash
###############################################################################
# Collect Diagnostic Information for Troubleshooting
# Run this script when you need to gather system state for debugging
###############################################################################

TIMESTAMP=$(date +%Y%m%d_%H%M%S)
OUTPUT_DIR="/tmp/mrhOTshOT_diagnostics_${TIMESTAMP}"
ARCHIVE="/tmp/diagnostics_${TIMESTAMP}.tar.gz"

echo "========================================="
echo "mrhOTshOT Diagnostic Collection"
echo "========================================="
echo ""
echo "[*] Creating diagnostic output directory: ${OUTPUT_DIR}"
mkdir -p "${OUTPUT_DIR}"

# System Information
echo "[*] Collecting system information..."
{
    echo "=== OS Information ==="
    uname -a
    echo ""
    
    echo "=== OS Release ==="
    cat /etc/*-release 2>/dev/null || echo "Not Linux"
    echo ""
    
    echo "=== Kernel Version ==="
    uname -r
    echo ""
    
    echo "=== Hostname ==="
    hostname
    echo ""
} > "${OUTPUT_DIR}/system_info.txt"

# Network Configuration
echo "[*] Collecting network configuration..."
{
    echo "=== IP Addresses ==="
    ip addr show 2>/dev/null || ifconfig 2>/dev/null
    echo ""
    
    echo "=== Routing Table ==="
    ip route show 2>/dev/null || route -n 2>/dev/null
    echo ""
    
    echo "=== IP Forwarding Status ==="
    sysctl net.ipv4.ip_forward 2>/dev/null
    echo ""
    
    echo "=== Firewall Rules ==="
    sudo iptables -L -n -v 2>/dev/null || echo "Cannot read iptables (need sudo)"
    echo ""
    
    echo "=== Active Network Connections ==="
    ss -tulpn 2>/dev/null || netstat -tulpn 2>/dev/null
    echo ""
} > "${OUTPUT_DIR}/network_config.txt"

# Running Processes
echo "[*] Collecting process information..."
{
    echo "=== Python Processes ==="
    ps aux | grep -i python | grep -v grep
    echo ""
    
    echo "=== Attack-Related Processes ==="
    ps aux | grep -E "orchestrator|phishing|vulnerable_router|iec104|water" | grep -v grep
    echo ""
    
    echo "=== All Processes (Top 20 by CPU) ==="
    ps aux --sort=-%cpu | head -20
    echo ""
} > "${OUTPUT_DIR}/processes.txt"

# Connectivity Tests
echo "[*] Testing network connectivity..."
{
    echo "=== Ping Router (192.168.0.13) ==="
    ping -c 3 192.168.0.13 2>&1 || echo "Cannot reach router"
    echo ""
    
    echo "=== Ping HMI (192.168.1.55) ==="
    ping -c 3 192.168.1.55 2>&1 || echo "Cannot reach HMI"
    echo ""
    
    echo "=== Ping PLC (192.168.1.6) ==="
    ping -c 3 192.168.1.6 2>&1 || echo "Cannot reach PLC"
    echo ""
    
    echo "=== Router Web Server (8080) ==="
    curl -I http://192.168.0.13:8080 2>&1 || echo "Cannot reach router web server"
    echo ""
    
    echo "=== PLC IEC-104 Server (2404) ==="
    nc -zv 192.168.1.6 2404 2>&1 || echo "Cannot reach PLC on port 2404"
    echo ""
} > "${OUTPUT_DIR}/connectivity_tests.txt"

# Service Status
echo "[*] Checking service status..."
{
    echo "=== Systemd Services ==="
    systemctl list-units --type=service --state=running | grep -E "vulnerable|water|iec104" || echo "No relevant services running"
    echo ""
    
    echo "=== vulnerable-router service ==="
    systemctl status vulnerable-router 2>&1 || echo "Service not configured"
    echo ""
    
    echo "=== water-tank service ==="
    systemctl status water-tank 2>&1 || echo "Service not configured"
    echo ""
} > "${OUTPUT_DIR}/service_status.txt"

# Python Environment
echo "[*] Collecting Python environment..."
{
    echo "=== Python Version ==="
    python3 --version 2>&1
    echo ""
    
    echo "=== Python Path ==="
    which python3
    echo ""
    
    echo "=== Installed Python Packages ==="
    pip3 list 2>&1 || echo "pip3 not available"
    echo ""
    
    echo "=== Critical Package Versions ==="
    echo -n "impacket: "; pip3 show impacket 2>/dev/null | grep Version || echo "Not installed"
    echo -n "c104: "; pip3 show c104 2>/dev/null | grep Version || echo "Not installed"
    echo -n "flask: "; pip3 show flask 2>/dev/null | grep Version || echo "Not installed"
    echo -n "pypykatz: "; pip3 show pypykatz 2>/dev/null | grep Version || echo "Not installed"
    echo ""
} > "${OUTPUT_DIR}/python_environment.txt"

# System Resources
echo "[*] Collecting resource usage..."
{
    echo "=== Memory Usage ==="
    free -h
    echo ""
    
    echo "=== Disk Usage ==="
    df -h
    echo ""
    
    echo "=== CPU Info ==="
    lscpu 2>/dev/null || sysctl hw.ncpu 2>/dev/null || echo "Cannot determine CPU info"
    echo ""
    
    echo "=== Load Average ==="
    uptime
    echo ""
} > "${OUTPUT_DIR}/resource_usage.txt"

# Recent Logs (if available)
echo "[*] Collecting recent logs..."
LOG_DIR="${OUTPUT_DIR}/logs"
mkdir -p "${LOG_DIR}"

# Copy attack logs if they exist
if [ -f "attack_orchestrator_*.log" ]; then
    echo "  - Copying attack orchestrator logs..."
    cp -f attack_orchestrator_*.log "${LOG_DIR}/" 2>/dev/null || true
fi

if [ -f "attack_log_*.json" ]; then
    echo "  - Copying attack JSON logs..."
    cp -f attack_log_*.json "${LOG_DIR}/" 2>/dev/null || true
fi

# Copy last 100 lines of system logs
echo "  - Collecting system logs..."
{
    echo "=== Last 100 lines of syslog ==="
    tail -100 /var/log/syslog 2>/dev/null || tail -100 /var/log/messages 2>/dev/null || echo "No system logs accessible"
    echo ""
} > "${LOG_DIR}/system_logs.txt"

# Repository Status
echo "[*] Collecting repository information..."
{
    echo "=== Git Status ==="
    git status 2>&1 || echo "Not a git repository"
    echo ""
    
    echo "=== Git Remote ==="
    git remote -v 2>&1 || echo "No git remotes"
    echo ""
    
    echo "=== Last 5 Commits ==="
    git log --oneline -5 2>&1 || echo "No git history"
    echo ""
    
    echo "=== Modified Files ==="
    git diff --name-only 2>&1 || echo "No git changes"
    echo ""
} > "${OUTPUT_DIR}/repository_info.txt"

# mrhOTshOT Configuration
echo "[*] Checking mrhOTshOT configuration..."
{
    echo "=== Directory Structure ==="
    ls -la ~/mrhOTshOT/ 2>/dev/null || ls -la . | grep -E "machines|execution|docs"
    echo ""
    
    echo "=== Attacker Scripts ==="
    ls -la machines/attacker/scripts/*.py 2>/dev/null || echo "Attacker scripts not found"
    echo ""
    
    echo "=== Setup Scripts ==="
    ls -la machines/*/setup.* 2>/dev/null || echo "Setup scripts not found"
    echo ""
} > "${OUTPUT_DIR}/mrhOTshOT_config.txt"

# Create archive
echo ""
echo "[*] Creating diagnostic archive..."
cd /tmp
tar -czf "${ARCHIVE}" "mrhOTshOT_diagnostics_${TIMESTAMP}/" 2>/dev/null

if [ -f "${ARCHIVE}" ]; then
    echo "[+] Diagnostic archive created: ${ARCHIVE}"
    echo "[*] Archive size: $(du -h ${ARCHIVE} | cut -f1)"
    echo ""
    echo "[*] Contents:"
    tar -tzf "${ARCHIVE}" | head -20
    echo "    ..."
    echo ""
    echo "To extract: tar -xzf ${ARCHIVE}"
else
    echo "[-] Failed to create archive"
    echo "[*] Raw diagnostics available in: ${OUTPUT_DIR}"
fi

echo ""
echo "========================================="
echo "Diagnostic Collection Complete"
echo "========================================="
echo ""
echo "Share this archive when asking for help."
echo "Remove any sensitive information before sharing!"
