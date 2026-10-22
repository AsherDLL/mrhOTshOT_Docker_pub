# mrhOTshOT Network Topology

## Overview

The mrhOTshOT lab simulates a realistic OT/ICS environment with distinct IT and OT network zones connected via a router.

## Network Diagram

```
                        INTERNET
                           |
                           |
                    ┌──────┴──────┐
                    │  Firewall   │
                    │  (Optional) │
                    └──────┬──────┘
                           |
    ┌──────────────────────┴──────────────────────┐
    │         Corporate/IT Network                 │
    │            192.168.0.0/24                    │
    └──────────────────────┬──────────────────────┘
                           |
            ┌──────────────┼──────────────┐
            |              |              |
       ┌────▼────┐    ┌────▼────┐   ┌────▼────┐
       │Attacker │    │Corporate│   │  Other  │
       │  Kali   │    │Workstatn│   │ Systems │
       │ .0.11   │    │  .0.x   │   │  .0.x   │
       └─────────┘    └─────────┘   └─────────┘


    ┌──────────────────────────────────────────┐
    │           Multi-Homed Router              │
    │                                           │
    │   eth0: 192.168.0.13   (IT Network)      │
    │   eth1: 192.168.1.4    (OT Network)      │
    │   eth2: 192.168.100.2  (Management)      │
    │                                           │
    │   • Vulnerable Web Server (Port 8080)    │
    │   • SSH Access (Port 22)                 │
    │   • IP Forwarding Enabled                │
    └──────────────────────────────────────────┘
                           |
            ┌──────────────┴──────────────┐
            │                             │
    ┌───────▼────────┐          ┌────────▼────────┐
    │  OT Network 1  │          │  OT Network 2   │
    │ 192.168.1.0/24 │          │192.168.100.0/24 │
    └────────┬───────┘          └─────────────────┘
             |
     ┌───────┼────────┐
     |       |        |
┌────▼───┐ ┌▼────┐ ┌─▼──────┐
│  HMI   │ │Hist.│ │ Other  │
│Windows │ │.1.27│ │ .1.x   │
│ .1.55  │ └─────┘ └────────┘
└────┬───┘
     |
     | IEC-104 (Port 2404)
     |
┌────▼───────┐
│  PLC/RTU   │
│Water Tank  │
│   .1.6     │
└────────────┘
```

## Network Zones

### Zone 1: Corporate/IT Network (192.168.0.0/24)

**Purpose**: Simulates corporate IT environment where initial compromise occurs

**Hosts**:
- **192.168.0.11** - Attacker (Kali Linux)
  - Role: Execute attack scripts
  - Services: None (client only)
  - Access: Outbound to all networks

- **192.168.0.13** - Router (eth0 interface)
  - Role: Entry point for attacks
  - Services:
    - TCP/8080 - Vulnerable web server
    - TCP/22 - SSH (admin:admin, operator:labpass123)
  - Vulnerabilities:
    - Command injection via `/execute` endpoint
    - Weak credentials

**Security Products (Optional)**:
- Palo Alto Firewall monitoring egress traffic
- Palo Alto Device Security (inline or monitor)

### Zone 2: OT Network (192.168.1.0/24)

**Purpose**: Simulates operational technology environment

**Hosts**:
- **192.168.1.4** - Router (eth1 interface)
  - Role: Gateway between IT and OT
  - Services: IP routing

- **192.168.1.55** - HMI (Windows 10/11)
  - Role: Human-Machine Interface, attack target
  - Services:
    - TCP/445 - SMB (file sharing)
    - TCP/3389 - RDP (remote desktop)
    - TCP/5985 - WinRM (remote PowerShell)
    - TCP/135 - WMI (Windows Management)
  - Credentials: operator:labpass123
  - Security: Cortex XDR agent (monitoring)

- **192.168.1.10** - PLC-1 Water Treatment (Kali Linux)
  - Protocols: IEC-104 (TCP/2404)
  - Attacks: Industroyer2, BlackEnergy3, CosmicEnergy

- **192.168.1.11** - PLC-2 Power Substation (Kali Linux)
  - Protocols: IEC 61850 (TCP/8102)
  - Attacks: Industroyer GOOSE

- **192.168.1.12** - PLC-3 Gas Pipeline (Kali Linux)
  - Protocols: OPC-UA (TCP/4840), FINS (UDP/9600), MELSEC (TCP/5007)
  - Attacks: PipeDream

- **192.168.1.13** - PLC-4 Manufacturing (Kali Linux)
  - Protocols: S7 (TCP/102), EtherNet/IP (TCP/44818)
  - Attacks: Stuxnet

- **192.168.1.14** - PLC-5 Building HVAC (Kali Linux)
  - Protocols: BACnet/IP (UDP/47808)
  - Attacks: FrostyGoop-BACnet

- **192.168.1.15** - PLC-6 Boiler House (Kali Linux)
  - Protocols: ABB Modbus (TCP/5020)

- **192.168.1.16** - PLC-7 Heating District (Kali Linux)
  - Protocols: Modbus TCP (TCP/502)
  - Attacks: FrostyGoop

- **192.168.1.17** - PLC-8 Water Utility DNP3 (Kali Linux)
  - Protocols: DNP3 (TCP/20000)
  - Attacks: Industroyer DNP3

- **192.168.1.18** - PLC-9 Sensor Network (Kali Linux)
  - Protocols: M-Bus (TCP/5000)
  - Attacks: Fuxnet

- **192.168.1.19** - SIS-1 Safety System (Kali Linux)
  - Protocols: TriStation (UDP/1502), IEC-104 (TCP/2404)
  - Attacks: TRITON

- **192.168.1.9** - Historian (Windows 10, ICONICS GENESIS64)
  - Role: Data logging, SCADA historian
  - Services: SQL Server, OPC-UA, Modbus polling

**Security Products (Optional)**:
- Palo Alto Device Security monitoring OT traffic
- XSIAM collecting logs from all zones

### Zone 3: Management Network (192.168.100.0/24)

**Purpose**: Out-of-band management (optional)

**Hosts**:
- **192.168.100.2** - Router (eth2 interface)
- Management access to all devices

## Traffic Flows

### Normal Operations

```
HMI (192.168.1.55) ──IEC-104──> PLC (192.168.1.6)
                Port 2404
```

**Description**: HMI sends control commands and receives telemetry from PLC

### Attack Traffic Flows

#### Phase 1: Initial Access
```
Attacker (.0.11) ──HTTP──> Router (.0.13:8080)
                Command Injection
```

#### Phase 2: Reconnaissance
```
Attacker (.0.11) ──SSH──> Router (.0.13:22)
Router (.0.13) ──NMAP──> HMI (.1.55)
```

#### Phase 4: Lateral Movement
```
Attacker (.0.11) ──via Router──> HMI (.1.55)
                SMB/WMI/RDP
```

#### Phase 5: Payload Delivery (4 Methods)
```
Method 1: Attacker ──SMB (445)──> HMI
Method 2: Attacker ──HTTP (8000)──> HMI
Method 3: Attacker ──PS Encoded──> HMI
Method 4: Attacker ──RDP (3389)──> HMI
```

#### Phase 7: OT Attack
```
HMI (.1.55) ──IEC-104──> PLC (.1.6:2404)
            Malicious commands
```

## Firewall Rules (Recommended)

### Allow Rules (Minimum Required)

**IT → Router:**
```
Source: 192.168.0.0/24
Destination: 192.168.0.13
Services: TCP/8080, TCP/22
Action: Allow + Log
```

**Router → OT:**
```
Source: 192.168.0.13
Destination: 192.168.1.0/24
Services: TCP/445, TCP/3389, TCP/5985
Action: Allow + Log + Alert
```

**HMI → PLC:**
```
Source: 192.168.1.55
Destination: 192.168.1.6
Services: TCP/2404
Action: Allow + Log
```

### Block Rules (For Testing Detection)

**Direct IT → OT (Should be blocked):**
```
Source: 192.168.0.0/24
Destination: 192.168.1.0/24
Action: Block + Alert
```

## Port Reference

| Port | Protocol | Service | Used By |
|------|----------|---------|---------|
| 22 | TCP | SSH | Router |
| 102 | TCP | S7comm | PLC-4 Manufacturing |
| 135 | TCP | WMI | HMI |
| 445 | TCP | SMB | HMI |
| 502 | TCP | Modbus TCP | PLC-7 Heating District |
| 1502 | UDP | TriStation | SIS-1 Safety System |
| 2404 | TCP | IEC-104 | PLC-1 Water, SIS-1 |
| 3389 | TCP | RDP | HMI |
| 4840 | TCP | OPC-UA | PLC-3 Gas Pipeline |
| 5000 | TCP | M-Bus | PLC-9 Sensor Network |
| 5007 | TCP | MELSEC | PLC-3 Gas Pipeline |
| 5020 | TCP | ABB Modbus | PLC-6 Boiler House |
| 5985 | TCP | WinRM | HMI |
| 8000 | TCP | HTTP (temp) | Attacker payload server |
| 8080 | TCP | HTTP | Router web server |
| 8102 | TCP | IEC 61850 | PLC-2 Power Substation |
| 9600 | UDP | FINS | PLC-3 Gas Pipeline |
| 20000 | TCP | DNP3 | PLC-8 Water Utility |
| 44818 | TCP | EtherNet/IP | PLC-4 Manufacturing |
| 47808 | UDP | BACnet/IP | PLC-5 Building HVAC |

## IP Address Summary

| IP | Hostname | OS | Role |
|----|----------|----| -----|
| 192.168.0.11 | attacker | Kali Linux | Attack source |
| 192.168.0.13 | router-eth0 | Linux | IT interface |
| 192.168.1.4 | router-eth1 | Linux | OT interface |
| 192.168.1.9 | historian | Windows 10 | ICONICS Historian |
| 192.168.1.10 | PLC-1 | Kali Linux | Water Treatment (IEC-104) |
| 192.168.1.11 | PLC-2 | Kali Linux | Power Substation (IEC 61850) |
| 192.168.1.12 | PLC-3 | Kali Linux | Gas Pipeline (OPC-UA/FINS/MELSEC) |
| 192.168.1.13 | PLC-4 | Kali Linux | Manufacturing (S7/EtherNet/IP) |
| 192.168.1.14 | PLC-5 | Kali Linux | Building HVAC (BACnet) |
| 192.168.1.15 | PLC-6 | Kali Linux | Boiler House (ABB Modbus) |
| 192.168.1.16 | PLC-7 | Kali Linux | Heating District (Modbus TCP) |
| 192.168.1.17 | PLC-8 | Kali Linux | Water Utility (DNP3) |
| 192.168.1.18 | PLC-9 | Kali Linux | Sensor Network (M-Bus) |
| 192.168.1.19 | SIS-1 | Kali Linux | Safety System (TriStation) |
| 192.168.1.55 | hmi | Windows 10 | HMI/SCADA |
| 192.168.100.2 | router-eth2 | Linux | Management (optional) |

## Credentials Reference

| System | Username | Password | Access Method |
|--------|----------|----------|---------------|
| Router | admin | admin | SSH, Web |
| Router | operator | labpass123 | SSH |
| HMI | operator | labpass123 | RDP, SMB, WinRM |

## VLAN Configuration (Optional)

If using VLANs:

- **VLAN 10**: Corporate IT (192.168.0.0/24)
- **VLAN 20**: OT Network (192.168.1.0/24)
- **VLAN 99**: Management (192.168.100.0/24)

## DNS Configuration (Optional)

If using DNS in your lab:

```
attacker.lab.local     → 192.168.0.11
router.lab.local       → 192.168.0.13
hmi.lab.local          → 192.168.1.55
plc.lab.local          → 192.168.1.6
historian.lab.local    → 192.168.1.27
```

## Security Monitoring Points

### Where to Place Sensors:

1. **Corporate Egress**:
   - Between attacker and router
   - Detects initial reconnaissance

2. **IT/OT Boundary**:
   - Between 192.168.0.0/24 and 192.168.1.0/24
   - **Most important monitoring point!**
   - Detects lateral movement

3. **OT Traffic**:
   - Between HMI and PLC
   - Detects malicious IEC-104 commands

### Palo Alto Product Placement:

```
Attacker ──> [Device Security] ──> Router ──> [Device Security] ──> HMI
                                                      |
                                                      ├──> [XSIAM] (Log collection)
                                                      |
                                                 [Cortex XDR] (On HMI)
```

## Network Requirements Checklist

Before starting lab:

- [ ] All machines can ping each other
- [ ] Router has IP forwarding enabled
- [ ] Windows Firewall allows SMB/RDP/WinRM on HMI
- [ ] PLC is listening on port 2404
- [ ] Router web server running on port 8080
- [ ] Static IPs configured on all machines
- [ ] DNS resolution working (optional)
- [ ] Palo Alto products configured (optional)

## Troubleshooting Network Issues

### Cannot reach HMI from Attacker

**Check**:
1. Can attacker ping router? `ping 192.168.0.13`
2. Can router ping HMI? `ping 192.168.1.55`
3. Is IP forwarding enabled on router? `sysctl net.ipv4.ip_forward`
4. Are firewall rules blocking? Check Windows Firewall on HMI

**Solution**:
```bash
# On router
sudo sysctl -w net.ipv4.ip_forward=1
sudo iptables -A FORWARD -i eth0 -o eth1 -j ACCEPT
sudo iptables -A FORWARD -i eth1 -o eth0 -j ACCEPT
```

### IEC-104 Connection Failed

**Check**:
1. Is PLC server running? `netstat -ln | grep 2404`
2. Can HMI reach PLC? `telnet 192.168.1.6 2404`

**Solution**:
```bash
# On PLC
sudo systemctl start water-tank
sudo systemctl status water-tank
```

---

**Need setup help?** → [SETUP_GUIDE.md](docs/SETUP_GUIDE.md)

**Ready to attack?** → [EXECUTION_GUIDE.md](docs/EXECUTION_GUIDE.md)
