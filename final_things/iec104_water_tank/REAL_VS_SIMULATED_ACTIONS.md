# Real vs Simulated Actions - Clarity Guide

## Overview

As requested, all scripts now execute **REAL** commands that will generate **AUTHENTIC** alerts in your Palo Alto Networks security products. This document clarifies what is real vs what is simulated.

## Scripts That Execute REAL Commands

### 1. Phishing Server (`00_phishing_server.py`)
**REAL:**
- [+] Hosts actual web server on port 8080
- [+] Captures real credentials when submitted
- [+] Sends actual HTTP requests to malicious domains (for URL filtering alerts)
- [+] JavaScript beacons to known-bad IPs/domains

**Expected Alerts:** URL Filtering, DNS Security, WildFire (JavaScript analysis)

---

### 2. Router Exploit (`01_router_exploit.py`)
**REAL:**
- [+] Actually connects to router web interface
- [+] Actually authenticates with provided credentials
- [+] Actually injects commands via vulnerable endpoint
- [+] Actually executes commands on router (whoami, reverse shell, etc.)
- [+] Actually establishes reverse shell connections

**Expected Alerts:** Command Injection (Device Security), Reverse Shell Detection, Outbound C2 Traffic

---

### 3. Post-Exploitation Enumeration (`02_post_exploit_enum.sh`)
**REAL:**
- [+] Actually performs ICMP ping sweeps
- [+] Actually scans ports with netcat/nmap
- [+] Actually enumerates SMB shares
- [+] Actually searches for credential files
- [+] Actually writes discovered data to /tmp/.system_cache/

**Expected Alerts:** ICMP Flood, Port Scan, SMB Enumeration, Suspicious File Access

---

### 4. Lateral Movement (`03_lateral_movement.py`)
**REAL:**
- [+] Actually attempts SMB brute force (if --brute-force flag used)
- [+] Actually uses impacket to execute PsExec, WMI, WinRM
- [+] Actually transfers files to target machine
- [+] Actually executes remote commands
- [+] Actually creates remote services

**Expected Alerts:** Brute Force, Lateral Movement, Remote Code Execution, Service Creation

---

### 5. Credential Dumper (`05_credential_dumper.py`) [!] UPDATED TO BE REAL
**REAL:**
- [+] Actually searches for lsass.exe process
- [+] **Actually attempts LSASS memory dump using comsvcs.dll**
- [+] **Actually executes `rundll32.exe C:\Windows\System32\comsvcs.dll, MiniDump <PID> lsass.dmp full`**
- [+] **Actually dumps registry hives (SAM, SECURITY, SYSTEM) using `reg save`**
- [+] Actually enumerates saved credentials with cmdkey/vaultcmd
- [+] Actually searches filesystem for credential-containing files

**SIMULATED ONLY:**
- Credential extraction from dump files (displays fake creds for demo)

**Expected Alerts:** LSASS Memory Access, Credential Dumping, Registry Hive Dump, SAM Database Access

**IMPORTANT:** This requires Administrator privileges. If run without admin rights, the actual dump commands will fail, but will still generate behavioral alerts from attempting to access LSASS/registry.

---

### 6. Industroyer2 Characteristics (`industroyer2_payload/industroyer2_characteristics.py`) [!] UPDATED TO BE REAL
**REAL:**
- [+] Actually searches for target process (PService_PPD.exe)
- [+] **Actually terminates the process with `taskkill /F /IM`**
- [+] **Actually deletes Windows Event Logs with `wevtutil cl Security/System/Application`**
- [+] **Actually overwrites files in test_configuration_files/ folder**
- [+] **Actually deletes the entire configuration folder**

**SIMULATED ONLY:**
- Scheduled execution check (doesn't actually wait for specific time, just checks)

**Expected Alerts:** Critical Process Termination, Event Log Tampering, Data Destruction, Wiper Activity, Ransomware-like Behavior

**IMPORTANT:** Event log deletion requires Administrator privileges. Process termination only works if PService_PPD.exe is actually running.

---

### 7. IEC-104 Attack (`industroyer2_simulation.py`)
**REAL:**
- [+] Actually connects to IEC-104 RTU on port 2404
- [+] Actually sends IEC-104 protocol commands
- [+] **Actually sets control mode to MANUAL**
- [+] **Actually opens inlet valve (IOA 300)**
- [+] **Actually closes outlet valve (IOA 301)**
- [+] **Actually causes tank to overflow and explode (in simulation)**
- [+] Actually sends historical Industroyer2 IOA patterns

**Expected Alerts:** IEC-104 Protocol Anomalies, OT Attack Pattern, Malicious Industrial Control Commands

---

### 8. PService_PPD.exe (`industroyer2_payload/PService_PPD.py`)
**REAL:**
- [+] Actually runs as background process
- [+] Actually writes log file
- [+] Actually displays GUI (if tkinter available)
- [+] Can actually be terminated by industroyer2_characteristics.py

**Expected Alerts:** None (this is the victim process, not the attacker)

---

## Privilege Requirements

### Commands That REQUIRE Administrator/Root:

**Windows (Administrator required):**
- LSASS memory dump (comsvcs.dll)
- Registry hive dump (reg save HKLM\SAM)
- Event log deletion (wevtutil cl)
- Process termination (taskkill /F)

**Linux (Root required):**
- Router web server (port 8080 if <1024)
- Network routing configuration
- iptables modifications

### Commands That Work WITHOUT Admin:
- Network reconnaissance (ping, port scans)
- File searches
- Process enumeration
- Credential vault enumeration (cmdkey /list)
- IEC-104 network attacks (just needs network access)

---

## What Happens If Commands Fail?

### If LSASS Dump Fails:
1. Script attempts real dump with comsvcs.dll
2. If fails (permissions/EDR block), logs error
3. Creates **placeholder file** with MDMP magic bytes
4. Placeholder still triggers **file-based YARA signatures**
5. Attempt alone generates **behavioral alerts**

### If Registry Dump Fails:
1. Script attempts real reg save command
2. If fails, logs error
3. Creates placeholder .hiv file
4. Placeholder has 'regf' magic bytes
5. Attempt triggers **registry access alerts**

### If Event Log Delete Fails:
1. Script attempts real wevtutil cl command
2. If fails (permissions), logs error
3. **Attempt alone generates anti-forensics alerts**
4. Cortex XDR detects the attempt

---

## Expected Alert Counts (Full Attack Chain)

### XSIAM (Priority 1 - Correlation)
- **1 Complete Attack Chain** (all 7 phases correlated)
- 40-60 individual events correlated into chain

### Device Security (Priority 2 - Network)
- 10-15 alerts:
  - Command injection
  - Reverse shell
  - Port scan
  - ICMP flood
  - SMB brute force
  - IEC-104 anomalies

### Cortex XDR (Priority 3 - Endpoint)
- 25-40 alerts:
  - LSASS access attempt
  - Registry hive access
  - Event log tampering attempt
  - Process termination
  - Lateral movement (WMI/PsExec)
  - Suspicious PowerShell
  - Data destruction
  - File modification patterns

### WildFire (Priority 5 - Malware Analysis)
- 3-8 submissions:
  - payload.zip
  - Python scripts (if uploaded)
  - Executables (if .exe built)
  - JavaScript from phishing page

---

## How to Maximize Alert Generation

### 1. Run with Administrator Privileges
To get REAL dumps that generate maximum alerts:
```powershell
# On HMI, open PowerShell as Administrator
python C:\Temp\05_credential_dumper.py --method all
python C:\Temp\industroyer2_characteristics.py
```

### 2. Start PService_PPD.exe First
To get process termination alerts:
```powershell
# Start the dummy process
python C:\Temp\PService_PPD.py

# Then run characteristics (will terminate it)
python C:\Temp\industroyer2_characteristics.py --mode terminate
```

### 3. Ensure Water Tank Server is Running
To get IEC-104 attack alerts:
```bash
# On PLC (192.168.1.6)
python3 water_tank_server.py

# Then from HMI
python C:\Temp\industroyer2_simulation.py --target 192.168.1.6
```

### 4. Use Actual Brute Force
To get authentication alerts:
```bash
python3 03_lateral_movement.py -t 192.168.1.55 --brute-force
# This will try multiple passwords and generate failed login alerts
```

---

## Safety Notes

All these commands are REAL but designed for controlled lab testing:

1. **Credential Dumps**: Real dumps created, but no actual credentials exposed (test environment)
2. **Event Logs**: Real deletion, but in test VM (can restore from backups/snapshots)
3. **Process Termination**: Real termination, but only dummy process
4. **Data Destruction**: Real file deletion, but only test_configuration_files folder
5. **IEC-104 Attack**: Real protocol commands, but simulated water tank (no physical damage)

**ALWAYS:**
- Have VM snapshots before testing
- Test in isolated network
- Have backups of any important data
- Get proper authorization

---

## Verification Checklist

Before declaring "success", verify:

- [ ] Cortex XDR shows LSASS access attempt (even if blocked)
- [ ] Registry access alerts generated
- [ ] Event log tampering detected
- [ ] Process termination logged
- [ ] Lateral movement chain visible
- [ ] IEC-104 commands detected
- [ ] XSIAM shows full attack chain correlation
- [ ] All 7 phases linked in XSIAM attack visualization

---

## Conclusion

**NO SHORTCUTS** - All critical attack commands execute for real:
- Credential dumping actually attempts LSASS/registry access
- Event log deletion actually attempts to clear logs
- Process termination actually kills target process
- IEC-104 attack actually sends malicious protocol commands
- Lateral movement actually uses impacket for SMB/WMI/RDP

The only "simulated" parts are:
- Credential extraction (shows fake creds, not real ones)
- Scheduled execution wait (checks time but doesn't wait)
- Some fallback behaviors when commands fail

This ensures **maximum realistic alert generation** for your Palo Alto Networks security products testing.
