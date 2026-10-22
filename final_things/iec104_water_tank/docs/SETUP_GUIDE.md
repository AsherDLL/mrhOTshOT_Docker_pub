# mrhOTshOT Complete Setup Guide

> **Step-by-step instructions for someone with NO prior knowledge**

This guide assumes you are a beginner who has never set up a security lab before. We'll walk through everything from scratch.

## What You Need

### Hardware/VMs
You need **4 machines** (virtual machines are fine):

| Machine | Minimum Specs | OS |
|---------|--------------|-----|
| Attacker | 2 CPU, 4GB RAM, 20GB disk | Kali Linux OR Ubuntu |
| Router | 1 CPU, 2GB RAM, 10GB disk | Ubuntu 20.04+ |
| HMI | 2 CPU, 4GB RAM, 40GB disk | Windows 10/11 |
| PLC | 1 CPU, 2GB RAM, 10GB disk | Ubuntu 20.04+ |

###Network Requirements
- All machines must be able to communicate
- Preferably isolated from production networks
- Static IP addresses (see below)

### Time Required
- **Setup**: 1-2 hours
- **First run**: 30 minutes
- **Total**: 2-3 hours

## Step-by-Step Setup

### PART 1: Network Configuration

#### Step 1.1: Configure Attacker Machine (192.168.0.11)

**On Ubuntu/Kali Linux:**

1. Open terminal
2. Edit network configuration:
   ```bash
   sudo nano /etc/netplan/01-netcfg.yaml
   ```

3. Add this configuration:
   ```yaml
   network:
     version: 2
     ethernets:
       ens33:  # Your network interface name
         addresses:
           - 192.168.0.11/24
         gateway4: 192.168.0.1
         nameservers:
           addresses: [8.8.8.8, 8.8.4.4]
   ```

4. Save (Ctrl+X, Y, Enter) and apply:
   ```bash
   sudo netplan apply
   ```

5. Verify:
   ```bash
   ip addr show
   # Should see 192.168.0.11
   ```

#### Step 1.2: Configure Router Machine (192.168.0.13 + others)

**This machine needs 3 network interfaces!**

1. Configure first interface:
   ```bash
   sudo nano /etc/netplan/01-netcfg.yaml
   ```

2. Add:
   ```yaml
   network:
     version: 2
     ethernets:
       ens33:
         addresses:
           - 192.168.0.13/24
       ens34:
         addresses:
           - 192.168.1.4/24
       ens35:
         addresses:
           - 192.168.100.2/24
   ```

3. Apply:
   ```bash
   sudo netplan apply
   ```

#### Step 1.3: Configure HMI Machine (192.168.1.55)

**On Windows:**

1. Open **Settings** → **Network & Internet** → **Ethernet** → **Change adapter options**
2. Right-click your network adapter → **Properties**
3. Select **Internet Protocol Version 4 (TCP/IPv4)** → **Properties**
4. Select **Use the following IP address:**
   - IP address: `192.168.1.55`
   - Subnet mask: `255.255.255.0`
   - Default gateway: `192.168.1.1`
   - DNS: `8.8.8.8`
5. Click **OK**

#### Step 1.4: Configure PLC Machine (192.168.1.6)

Same as Attacker, but use `192.168.1.6/24`:

```bash
sudo nano /etc/netplan/01-netcfg.yaml
```

```yaml
network:
  version: 2
  ethernets:
    ens33:
      addresses:
        - 192.168.1.6/24
      gateway4: 192.168.1.1
      nameservers:
        addresses: [8.8.8.8]
```

```bash
sudo netplan apply
```

#### Step 1.5: Verify Network Connectivity

**From Attacker:**
```bash
ping -c 3 192.168.0.13  # Router
ping -c 3 192.168.1.55  # HMI (via router)
ping -c 3 192.168.1.6   # PLC (via router)
```

All should respond! If not, check your router's IP forwarding.

---

### PART 2: Clone Repository

**Do this on ALL 4 machines:**

```bash
# Install git if not already installed
sudo apt-get update
sudo apt-get install -y git

# Clone repository
cd ~
git clone https://github.com/YOUR_ORG/mrhOTshOT.git
cd mrhOTshOT
```

**On Windows (HMI):**
1. Install [Git for Windows](https://git-scm.com/download/win)
2. Open **Git Bash**
3. Run:
   ```bash
   cd C:\
   git clone https://github.com/YOUR_ORG/mrhOTshOT.git
   cd mrhOTshOT
   ```

---

### PART 3: Machine-Specific Setup

#### Setup 1: Attacker Machine

```bash
cd ~/mrhOTshOT/machines/attacker
sudo chmod +x setup.sh
sudo ./setup.sh
```

**What this does:**
- Installs Python 3
- Installs attack tools (nmap, smbclient, etc.)
- Installs impacket (for WMI/SMB attacks)
- Sets up attack scripts

**Expected output:**
```
[*] Installing system packages...
[*] Installing Python packages...
[*] Installing impacket tools...
[+] Attacker setup complete!
```

**Time:** 5-10 minutes

**Troubleshooting:**
- If `sudo: command not found`, you're already root, just run `./setup.sh`
- If Python errors, ensure you have internet connection
- If permission denied, run `chmod +x setup.sh` first

#### Setup 2: Router Machine

```bash
cd ~/mrhOTshOT/machines/router
sudo chmod +x setup.sh
sudo ./setup.sh
```

**What this does:**
- Installs Flask web server
- Creates user accounts (admin:admin, operator:labpass123)
- Enables SSH server
- Sets up vulnerable web server
- Configures IP forwarding

**Expected output:**
```
[*] Installing system packages...
[*] Configuring SSH server...
[+] Created user: admin (password: admin)
[+] Created user: operator (password: labpass123)
[+] Router setup complete!
```

**Time:** 3-5 minutes

**Test SSH:**
```bash
# From attacker machine
ssh admin@192.168.0.13
# Password: admin
```

#### Setup 3: PLC Machine

```bash
cd ~/mrhOTshOT/machines/plc
sudo chmod +x setup.sh
sudo ./setup.sh
```

**What this does:**
- Installs Python 3
- Installs c104 library (IEC-104 protocol)
- Sets up water tank simulation server
- Creates systemd service

**Expected output:**
```
[*] Installing system packages...
[*] Installing c104 library...
[*] Setting up water tank server...
[+] PLC/RTU setup complete!
```

**Time:** 5-10 minutes

**Troubleshooting:**
- c104 compilation requires build-essential and cmake
- If build fails, ensure you have internet connection

#### Setup 4: HMI Machine (Windows)

**Step 1: Install Python**

1. Download [Python 3.11](https://www.python.org/downloads/)
2. Run installer
3. [+] **CHECK "Add Python to PATH"** (very important!)
4. Click "Install Now"

**Step 2: Run Setup Script**

1. Open **PowerShell as Administrator** (Right-click → "Run as Administrator")
2. Navigate to mrhOTshOT:
   ```powershell
   cd C:\mrhOTshOT\machines\hmi
   ```
3. Allow script execution (first time only):
   ```powershell
   Set-ExecutionPolicy Bypass -Scope Process
   ```
4. Run setup:
   ```powershell
   .\setup.ps1
   ```

**What this does:**
- Installs Python packages
- Enables RDP
- Enables SMB file sharing
- Enables WinRM (remote PowerShell)
- Creates user operator:labpass123
- Sets up working directories

**Expected output:**
```
[*] Checking Python installation...
[+] Found: Python 3.11.x
[*] Installing Python packages...
[*] Enabling RDP...
[+] RDP enabled
[+] Created user: operator (password: labpass123)
[+] HMI setup complete!
```

**Time:** 5-10 minutes

**Troubleshooting:**
- If "Python not found", ensure you checked "Add to PATH" during installation
- If "Execution policy" error, run PowerShell as Administrator
- If package install fails, check internet connection

---

### PART 4: Verify Installation

Run these commands to verify everything is set up correctly:

#### On Attacker:
```bash
cd ~/mrhOTshOT/machines/attacker/scripts
python3 --version              # Should show Python 3.8+
nmap --version                 # Should show nmap 7.x+
impacket-psexec --help         # Should show help text
ls -la *.py                    # Should list attack scripts
```

#### On Router:
```bash
cd ~/mrhOTshOT/machines/router
python3 vulnerable_router_server.py &  # Start in background
curl http://localhost:8080              # Should return HTML
kill %1                                 # Stop server
```

#### On PLC:
```bash
cd ~/mrhOTshOT/machines/plc/server
python3 -c "import c104"       # Should not error
ls -la *.py                    # Should list server files
```

#### On HMI:
```powershell
cd C:\mrhOTshOT\machines\hmi
python --version               # Should show Python 3.x
python -c "import flask"       # Should not error
```

---

### PART 5: Start Services

Now that everything is set up, let's start the services:

#### On PLC Machine:
```bash
cd ~/mrhOTshOT/execution
./start_plc.sh
```

You should see:
```
Starting Water Tank IEC-104 Server
[*] Starting IEC-104 server on port 2404...
[*] Water tank simulation active
```

**Leave this terminal open!** The server is now running.

#### On Router Machine:
```bash
# Open a new terminal
cd ~/mrhOTshOT/execution
./start_router.sh
```

You should see:
```
Starting Vulnerable Router Web Server
[*] Starting vulnerable router on port 8080...
```

**Leave this terminal open!** The router is now running.

**Test from attacker:**
```bash
curl http://192.168.0.13:8080
# Should return HTML
```

---

### PART 6: Run Your First Attack

#### Quick Test:
```bash
# On Attacker machine
cd ~/mrhOTshOT/machines/attacker/scripts

# Test router exploit (Phase 1)
python3 01_router_exploit.py 192.168.0.13 --username admin --password admin --command "whoami"
```

If successful, you should see:
```
[!!!] SUCCESS: Command executed on router
[*] Output: admin
```

#### Full Attack Chain:
```bash
cd ~/mrhOTshOT/execution
./run_attack.sh
```

Follow the prompts:
1. Confirm you want to proceed (y)
2. Select mode:
   - Press `1` for full automated
   - Press `2` for interactive (recommended first time)

**Watch the attack progress through all 7 phases!**

---

## What to Monitor

### During Attack Execution:

1. **On Attacker**: Watch terminal output for phase progression
2. **On HMI**: Watch for file transfers arriving in `C:\Temp\`
3. **On PLC**: Watch IEC-104 server logs for malicious commands

### After Attack:

1. **XSIAM** (if available):
   - Go to Incidents
   - Look for "Industroyer2 Attack Chain Detection"
   - Should show all 7 phases correlated

2. **Cortex XDR** (if running on HMI):
   - Check Alerts
   - Should see 30-50 alerts:
     - LSASS Memory Access
     - Registry Hive Dump
     - Event Log Deletion
     - Process Termination
     - Many more...

3. **Device Security**:
   - Check Threat Logs
   - Should see 15-25 alerts:
     - Command Injection
     - Port Scanning
     - SMB Transfers
     - IEC-104 Anomalies

---

## Understanding the Attack

### Phase Breakdown:

**Phase 1: Initial Access**
- Exploits vulnerable router web server
- Command injection vulnerability
- Alternative: Phishing simulation

**Phase 2: Enumeration**
- Port scanning from compromised router
- Discovers HMI at 192.168.1.55

**Phase 3: Credential Dumping**
- Dumps LSASS memory (actual Windows credentials)
- Dumps registry hives (SAM/SECURITY/SYSTEM)
- **This runs on HMI as part of payload**

**Phase 4: Lateral Movement**
- Uses stolen credentials
- Pivots from IT network to HMI

**Phase 5: Payload Delivery**
- Transfers malware via 4 methods:
  1. SMB file copy
  2. HTTP download
  3. PowerShell in-memory
  4. RDP drive redirection

**Phase 6: Industroyer2 Characteristics**
- Terminates SCADA processes
- Deletes event logs (anti-forensics)
- Destroys files (CaddyWiper)

**Phase 7: OT Attack**
- Sends IEC-104 commands to water tank
- Opens inlet valve
- Closes outlet valve
- Causes overflow and explosion

---

## [!] Common Issues

### "Cannot reach HMI"
**Solution:**
- Check HMI Windows Firewall settings
- Verify IP address is correct
- Ping from router to confirm connectivity

### "Permission denied" on Linux
**Solution:**
- Run with `sudo`
- Or: `chmod +x script.sh`

### "Python not found" on Windows
**Solution:**
- Reinstall Python
- [+] Check "Add Python to PATH"
- Restart PowerShell

### "c104 import error"
**Solution:**
- Reinstall: `pip3 install ~/mrhOTshOT/libs/c104-2.2.1`
- Ensure build-essential installed

### "impacket-psexec not found"
**Solution:**
- Run attacker setup script again
- Or: `pip3 install impacket`

### Attack hangs at Phase 5
**Solution:**
- Check HMI is reachable: `ping 192.168.1.55`
- Verify credentials: `operator:labpass123`
- Check Windows Firewall allows SMB/RDP/WinRM

---

## Next Steps

After successful first run:

1. [+] **Review Logs**:
   - `/tmp/mrhOTshOT/logs/` on attacker
   - `C:\Logs\mrhOTshOT\` on HMI

2. [+] **Check Palo Alto Products**:
   - XSIAM attack chain
   - Cortex XDR alerts
   - Device Security logs
   - WildFire submissions

3. [+] **Run Individual Phases**:
   - Test each attack script separately
   - Understand what each phase does

4. [+] **Customize**:
   - Try different credentials
   - Modify attack parameters
   - Create custom scenarios

---

## Success Criteria

You've successfully completed setup when:

- [+] All 4 machines can ping each other
- [+] Services start without errors
- [+] Attack runs through all 7 phases
- [+] XSIAM shows attack chain correlation
- [+] Cortex XDR generates 30+ alerts
- [+] Water tank simulation responds to IEC-104 commands

---

## Need Help?

If stuck:
1. Check [TROUBLESHOOTING.md](TROUBLESHOOTING.md)
2. Review logs in `/tmp/mrhOTshOT/logs/`
3. Verify network connectivity first
4. Ensure all setup scripts completed successfully

---

**Ready to run?** → [Run Your First Attack](#part-6-run-your-first-attack)

**Need advanced config?** → [EXECUTION_GUIDE.md](EXECUTION_GUIDE.md)
