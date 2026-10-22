# mrhOTshOT - Industroyer2 Attack Simulation Lab

> **Complete OT/ICS Attack Simulation for Palo Alto Networks Security Testing**

This repository contains a **production-ready** Industroyer2 attack simulation framework designed to test and demonstrate Palo Alto Networks security products (XSIAM, Cortex XDR, Device Security, WildFire) in an OT/ICS environment.

## What is mrhOTshOT?

**mrhOTshOT** (Mr. OT-shot) is a complete lab environment that simulates the full Industroyer2 attack chain from initial access through OT disruption. It recreates the 2022 attack on Ukraine's power grid, adapted for water tank infrastructure.

### Attack Chain (7 Phases)

```
Phase 1: Initial Access       → Phishing OR Router Exploit
Phase 2: Enumeration           → Network reconnaissance
Phase 3: Credential Dumping    → LSASS + Registry extraction
Phase 4: Lateral Movement      → IT → HMI pivot
Phase 5: Payload Delivery      → All 4 transfer methods
Phase 6: Industroyer2 Traits   → Process kill + CaddyWiper
Phase 7: OT Attack             → IEC-104 commands to PLC
```

## Lab Architecture

```
┌─────────────────────────────────────────────────────────────────┐
│                     NETWORK TOPOLOGY                             │
└─────────────────────────────────────────────────────────────────┘

   [Internet/Corporate]              [OT Network]
          |                                |
    192.168.0.0/24                  192.168.1.0/24
          |                                |
          |                                |
    ┌─────────┐                      ┌─────────┐
    │ Attacker│─────┐           ┌────│   HMI   │
    │Kali/Ubnt│     │           │    │ Windows │
    │.0.11    │     │           │    │ .1.55   │
    └─────────┘     │           │    └─────────┘
                    │           │          │
                ┌───▼───────────▼───┐      │
                │      Router       │      │
                │  .0.13 / .1.4     │◄─────┘
                │  3 NICs           │
                └───────────────────┘
                         │
                         │ .100.2
                  ┌──────▼──────┐
                  │   PLC/RTU   │
                  │   Linux     │
                  │   .1.6      │
                  │ Water Tank  │
                  └─────────────┘
```

### Machine Roles

| Machine | IP | OS | Purpose |
|---------|----|----|---------|
| **Attacker** | 192.168.0.11 | Kali Linux | Execute attack scripts |
| **Router** | 192.168.0.13<br>192.168.1.4<br>192.168.100.2 | Linux | Vulnerable entry point<br>Network routing |
| **HMI** | 192.168.1.55 | Windows 10/11 | Human-Machine Interface<br>Attack target |
| **PLC/RTU** | 192.168.1.6 | Linux | IEC-104 water tank simulation |

## Quick Start (For Beginners)

### Prerequisites

- **4 machines** (can be VMs) with network connectivity
- **Basic Linux knowledge** (how to run commands)
- **Palo Alto products** installed (optional but recommended)
- **1-2 hours** for complete setup

### Step 1: Clone Repository (On ALL Machines)

```bash
# On each machine, run:
git clone https://github.com/YOUR_ORG/mrhOTshOT.git
cd mrhOTshOT
```

### Step 2: Setup Each Machine

#### On Attacker Machine (192.168.0.11)
```bash
cd machines/attacker
sudo chmod +x setup.sh
sudo ./setup.sh
```

#### On Router Machine (192.168.0.13)
```bash
cd machines/router
sudo chmod +x setup.sh
sudo ./setup.sh
```

#### On HMI Machine (192.168.1.55)
```powershell
# In PowerShell as Administrator:
cd machines\hmi
.\setup.ps1
```

#### On PLC Machine (192.168.1.6)
```bash
cd machines/plc
sudo chmod +x setup.sh
sudo ./setup.sh
```

### Step 3: Start Services

#### Start PLC (Water Tank)
```bash
# On PLC machine
cd execution
chmod +x start_plc.sh
./start_plc.sh
```

#### Start Router
```bash
# On Router machine
cd execution
chmod +x start_router.sh
./start_router.sh
```

### Step 4: Run Attack

```bash
# On Attacker machine
cd execution
chmod +x run_attack.sh
./run_attack.sh
```

**That's it!** The attack will run through all 7 phases automatically.

## Repository Structure

```
mrhOTshOT/
├── README.md                       ← You are here
├── NETWORK_TOPOLOGY.md             ← Network details
├── CUSTOM_DETECTION_RULES.md       ← Palo Alto rules
├── machines/
│   ├── attacker/
│   │   ├── setup.sh               ← Attacker setup
│   │   └── scripts/               ← All attack tools
│   ├── router/
│   │   ├── setup.sh               ← Router setup
│   │   └── vulnerable_router_server.py
│   ├── hmi/
│   │   ├── setup.ps1              ← HMI Windows setup
│   │   ├── hmi_clients/           ← HMI interface code
│   │   └── payload/               ← Industroyer2 malware
│   └── plc/
│       ├── setup.sh               ← PLC setup
│       └── server/                ← Water tank server
├── execution/
│   ├── start_plc.sh               ← Start water tank
│   ├── start_router.sh            ← Start router
│   └── run_attack.sh              ← Execute full attack
├── docs/
│   ├── SETUP_GUIDE.md             ← Detailed setup
│   ├── EXECUTION_GUIDE.md         ← How to run
│   └── TROUBLESHOOTING.md         ← Common issues
└── libs/
    └── c104-2.2.1/                ← IEC-104 library
```

## Attack Execution Modes

### 1. Fully Automated (Recommended for demos)
```bash
cd machines/attacker/scripts
python3 MASTER_ATTACK_ORCHESTRATOR.py --auto-yes
```

### 2. Interactive (Step-by-step)
```bash
python3 MASTER_ATTACK_ORCHESTRATOR.py
# Prompts before each phase
```

### 3. Individual Phases
```bash
# Phase 1: Router Exploit
python3 01_router_exploit.py 192.168.0.13

# Phase 5: File Transfer (all 4 methods)
python3 06_file_transfer_all_methods.py --target 192.168.1.55 --method all

# Phase 7: IEC-104 Attack
cd ../machines/hmi/payload/perform_malware_simulations
python3 industroyer2_simulation.py --target 192.168.1.6
```

## Expected Security Alerts

### XSIAM (PRIMARY GOAL)
- **Complete 7-phase attack chain correlation**
- 50-70 individual events linked into attack graph
- MITRE ATT&CK TTPs mapped
- Timeline visualization

### Cortex XDR
**30-50 alerts:**
- LSASS memory access
- Registry hive dump
- Event log deletion
- Process termination
- PowerShell encoded commands
- SMB lateral movement
- WMI remote execution
- CaddyWiper file destruction
- PsExec.exe LOLBin execution

### Device Security
**15-25 alerts:**
- Command injection
- Port scanning
- SMB file transfers (4 methods)
- RDP connections
- IEC-104 protocol anomalies

### WildFire
**5-10 submissions:**
- payload.zip analysis
- PsExec.exe LOLBin
- Python scripts

## Pre-Configured Detection Rules

Import these **before** running the attack:

See [CUSTOM_DETECTION_RULES.md](CUSTOM_DETECTION_RULES.md) for:
- 4 XSIAM Correlation Rules
- 7 Cortex XDR BIOC Rules
- 3 Firewall Threat Signatures
- 2 WildFire YARA Rules

## Default Credentials

| System | Username | Password | Purpose |
|--------|----------|----------|---------|
| Router | admin | admin | SSH/Web |
| Router | operator | labpass123 | SSH |
| HMI | operator | labpass123 | RDP/SMB/WinRM |

## [!] Safety & Legal Warnings

### CRITICAL: Authorized Use Only

This framework executes **REAL attack techniques**:

[+] **Actually Executes:**
- LSASS memory dumping
- Registry hive extraction
- Event log deletion
- Process termination
- File overwriting/deletion
- IEC-104 protocol commands
- Network reconnaissance
- SMB/RDP/HTTP file transfers

[-] **Only Use In:**
- Isolated lab environments
- Authorized security testing
- Palo Alto Networks demos
- Educational purposes

**NEVER:**
- Use against production systems
- Deploy on public networks
- Run without authorization
- Use for malicious purposes

## Documentation

| Document | What's Inside |
|----------|---------------|
| **[SETUP_GUIDE.md](docs/SETUP_GUIDE.md)** | Complete setup walkthrough |
| **[EXECUTION_GUIDE.md](docs/EXECUTION_GUIDE.md)** | How to run attacks |
| **[CUSTOM_DETECTION_RULES.md](CUSTOM_DETECTION_RULES.md)** | Palo Alto rules |
| **[TROUBLESHOOTING.md](docs/TROUBLESHOOTING.md)** | Common issues & fixes |
| **[NETWORK_TOPOLOGY.md](NETWORK_TOPOLOGY.md)** | Network architecture |

## What You'll Learn

After completing this lab:

1. [+] How Industroyer2 attacks ICS/SCADA systems
2. [+] Full cyber kill chain from phishing → OT impact
3. [+] MITRE ATT&CK TTPs for OT environments
4. [+] How XSIAM correlates multi-phase attacks
5. [+] IEC-104 protocol structure and vulnerabilities
6. [+] IT → OT lateral movement techniques
7. [+] Detection strategies for OT threats

## Getting Started Checklist

- [ ] Clone repository on all 4 machines
- [ ] Run setup scripts (attacker, router, HMI, PLC)
- [ ] Verify network connectivity between machines
- [ ] Import Palo Alto detection rules (optional)
- [ ] Start PLC water tank server
- [ ] Start vulnerable router
- [ ] Execute attack from attacker machine
- [ ] Monitor XSIAM for attack chain correlation

## Quick Tips

**For First-Time Users:**
1. Start with the automated mode (`--auto-yes`)
2. Monitor attack logs in real-time
3. Check XSIAM 5-10 minutes after attack completion
4. Review detection rules beforehand for better understanding

**For Troubleshooting:**
- All scripts have verbose logging
- Check `/tmp/mrhOTshOT/logs/` on attacker
- Verify network connectivity first
- Ensure all services are running

## Support

This is a Palo Alto Networks internal lab environment.

**Questions?**
- See [SETUP_GUIDE.md](docs/SETUP_GUIDE.md) for detailed instructions
- See [TROUBLESHOOTING.md](docs/TROUBLESHOOTING.md) for common issues
- Contact: [Your Palo Alto contact]

## Version

**v1.0.0** - Complete Industroyer2 simulation with all 7 attack phases

---

**Ready to start?** → [Step 1: Clone Repository](#step-1-clone-repository-on-all-machines)

**Need help?** → [Troubleshooting Guide](docs/TROUBLESHOOTING.md)

**Want to learn more?** → [Setup Guide](docs/SETUP_GUIDE.md)
