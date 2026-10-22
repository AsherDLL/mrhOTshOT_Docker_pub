# FrostyGoop Detection Quick Reference

## Critical Indicators - Require Immediate Response

### 1. Tank Overflow Attack Signature (Risk Score: 100)
**Pattern**: Sequential Modbus writes within 5 seconds:
- Coil 3 = False (Manual mode)
- Coil 0 = True (Inlet valve OPEN)
- Coil 1 = False (Outlet valve CLOSED)
- **Maintained for ≥30 seconds**

**XSIAM Rule**: BIOC-FG-007
**Response**: Emergency PLC shutdown, isolate network, override valves

---

### 2. Persistent Attack Maintenance (Risk Score: 98)
**Pattern**: Same Modbus command repeated ≥5 times over ≥25 seconds
- Function Code 5 or 6
- Same address and value
- Regular interval (variance < 20%)

**XSIAM Rule**: BIOC-FG-004
**Response**: Isolate PLC, block attacker IP, investigate

---

### 3. Rapid Control Manipulation (Risk Score: 95)
**Pattern**: ≥3 Modbus write operations within 5 seconds
- Function Code 5 or 15
- Coil addresses 0-10

**XSIAM Rule**: BIOC-FG-003
**Response**: Verify PLC state, capture traffic, investigate source

---

## High-Priority Indicators

### 4. Automation Disable + Valve Control (Risk Score: 92)
**Pattern**: Mode change to MANUAL followed by valve commands within 10 seconds

**XSIAM Rule**: BIOC-FG-005
**Response**: Investigate authorization, verify mode changes

---

### 5. Configuration File Loading (Risk Score: 85)
**Pattern**: JSON file with Modbus keywords → Modbus connection within 60s
- File contains: "function_code", "modbus", "coil", "register"
- Filename: "frostygoop", "config", "modbus"

**XSIAM Rule**: BIOC-FG-006
**Response**: Quarantine file, analyze contents, check process

---

### 6. Suspicious Process Execution (Risk Score: 80)
**Pattern**: Python process with ICS attack keywords
- Command line contains: "frostygoop", "modbus", "attack", "--port 502"

**XSIAM Rule**: BIOC-FG-008
**Response**: Terminate process, isolate host, collect forensics

---

## Network Indicators

### 7. Multi-Protocol ICS Scanning (Risk Score: 75)
**Pattern**: Single source IP → ≥3 ICS ports within 60 seconds
- Ports: 102, 502, 2404, 4840, 44818

**XSIAM Rule**: BIOC-FG-001, IOT-FG-005
**Response**: Monitor source IP, check authorization

---

### 8. Modbus Slave Enumeration (Risk Score: 70)
**Pattern**: ≥3 different slave IDs tested within 30 seconds
- Function Code 3 or 4

**XSIAM Rule**: BIOC-FG-002
**Response**: Verify if authorized maintenance

---

## IoT Security Rule Quick Checks

### Unauthorized Modbus Client
**Check**: Is source IP in whitelist?
- HMI workstations: 10.0.10.0/24
- SCADA servers: 10.0.20.0/24
- Maintenance: 10.0.30.0/24

**If NO → Alert Critical**

---

### Unsafe Valve State
**Check**: Current valve configuration
- Inlet OPEN + Outlet CLOSED + Manual mode = **CRITICAL**
- Sustained for ≥10 seconds = **EMERGENCY**

**Response**: Immediate valve override

---

### Modbus Write Frequency
**Check**: Write operations per minute
- Baseline + 3σ = anomaly
- Sustained for ≥30 seconds = attack

---

## Attack Timeline Recognition

```
[Reconnaissance]
  ↓ Port scanning (502, 2404, 102, 4840, 44818)
  ↓ Slave ID enumeration (1, 2, 10, 100, 255)

[Target Validation]
  ↓ Configuration file loading
  ↓ Process execution (frostygoop_simulation.py)

[Pre-Attack]
  ↓ Set Manual Mode (Coil 3 = False)

[Attack Execution]
  ↓ Open Inlet (Coil 0 = True)
  ↓ Close Outlet (Coil 1 = False)

[Persistence]
  ↓ Repeated commands every 5 seconds
  ↓ Maintain attack state for 60+ seconds

[Impact]
  ↓ Tank overflow
  ↓ Pressure buildup
  ↓ Potential rupture/explosion
```

---

## Modbus Function Codes Used by FrostyGoop

| Code | Function | Purpose |
|------|----------|---------|
| 3 | Read Holding Registers | Reconnaissance |
| 4 | Read Input Registers | Enumeration |
| 5 | Write Single Coil | Valve control |
| 6 | Write Single Register | Parameter modification |
| 15 | Write Multiple Coils | Bulk valve control |
| 16 | Write Multiple Registers | Bulk parameter modification |

---

## Target Coil/Register Mapping

### Water Tank System Addresses

| Address | Type | Description | Attack Value |
|---------|------|-------------|--------------|
| Coil 0 | Write | Inlet Valve | True (OPEN) |
| Coil 1 | Write | Outlet Valve | False (CLOSED) |
| Coil 2 | Write | Pump Control | Variable |
| Coil 3 | Write | Auto Mode | False (MANUAL) |
| Coil 100 | Read | Inlet Status | Monitor |
| Coil 101 | Read | Outlet Status | Monitor |
| Coil 104 | Read | Overflow Alarm | Monitor |
| Coil 107 | Read | Tank Exploded | Monitor |
| Register 0 | Read | Water Level (%) | Monitor |
| Register 1 | Read | Pressure (bar × 10) | Monitor |

---

## Detection Rule Priority Matrix

| Rule ID | Severity | Response Time | Auto-Block | PCAP Capture |
|---------|----------|---------------|------------|--------------|
| BIOC-FG-007 | Critical | Immediate | Yes | 15 min |
| BIOC-FG-004 | Critical | Immediate | Yes | 10 min |
| BIOC-FG-003 | Critical | < 5 min | Optional | 5 min |
| BIOC-FG-005 | Critical | < 5 min | No | 5 min |
| BIOC-FG-006 | High | < 15 min | No | No |
| BIOC-FG-008 | High | < 15 min | No | No |
| BIOC-FG-001 | High | < 15 min | No | No |
| BIOC-FG-002 | High | < 15 min | No | No |
| IOT-FG-001 | High | < 15 min | No | No |
| IOT-FG-002 | Critical | Immediate | Yes | 10 min |
| IOT-FG-003 | Critical | Immediate | No | 10 min |
| IOT-FG-006 | Critical | Immediate | No | 10 min |

---

## Alert Escalation Path

### P0 - Critical (BIOC-FG-007, IOT-FG-006)
1. **Immediate**: SMS to SOC on-call, OT Manager, Incident Commander
2. **+5 min**: Escalate to Security Director, CISO if not acknowledged
3. **Notify**: SOC, OT Security Team, Plant Operations

### P1 - Critical (BIOC-FG-003, BIOC-FG-004, BIOC-FG-005)
1. **Immediate**: Email + Teams alert to SOC, OT Security
2. **+15 min**: Escalate to SOC Lead, OT Security Lead if not acknowledged

### P2 - High (All others)
1. **Immediate**: Email + Teams alert to SOC
2. **+1 hour**: Escalate to SOC Lead if not triaged

---

## Response Playbooks

### Emergency: Tank Overflow Attack (BIOC-FG-007)
1. [+] Execute emergency PLC shutdown
2. [+] Override valves to safe state (inlet CLOSED, outlet OPEN)
3. [+] Block attacker IP on firewall
4. [+] Isolate PLC from network
5. [+] Capture network traffic (15 min)
6. [+] Notify plant operations
7. [+] Investigate attack source
8. [+] Check for lateral movement
9. [+] Restore from known-good configuration
10. [+] Monitor for persistence attempts

### Critical: Active Attack in Progress (BIOC-FG-004)
1. [+] Isolate PLC from network
2. [+] Block attacker IP
3. [+] Capture network traffic (10 min)
4. [+] Analyze Modbus commands
5. [+] Check PLC memory/configuration
6. [+] Verify no unauthorized changes
7. [+] Restore if necessary
8. [+] Monitor for recurrence

### High: Reconnaissance Detected (BIOC-FG-001, BIOC-FG-002)
1. [+] Monitor source IP (enhanced logging)
2. [+] Threat intel lookup
3. [+] Check access authorization
4. [+] Review firewall rules
5. [+] Check for follow-on attacks
6. [+] Update IoC feeds

---

## Key Log Patterns to Search

### FrostyGoop Execution Logs
```
[FROSTYGOOP-SIM]
FROSTYGOOP-INSPIRED ATTACK SIMULATION
Phase 1: Network Reconnaissance
Phase 2: Modbus TCP PLC Enumeration
Phase 3: Target Validation
Phase 4: Process Termination
Phase 5: Payload Execution
```

### Modbus Traffic Patterns
```
Modbus Function Code: 5 (Write Single Coil)
Address: 3, Value: false (Manual Mode)
Address: 0, Value: true (Inlet OPEN)
Address: 1, Value: false (Outlet CLOSED)
```

---

## Testing and Validation

### Test Commands
```bash
# Execute simulation with config file
python frostygoop_simulation.py --config frostygoop_config.json --duration 30

# Execute simulation with CLI args
python frostygoop_simulation.py --target 127.0.0.1 --port 502 --duration 30
```

### Expected Detections
- [+] BIOC-FG-001 (Port scanning)
- [+] BIOC-FG-002 (Slave enumeration)
- [+] BIOC-FG-005 (Manual mode change)
- [+] BIOC-FG-007 (Overflow attack sequence)
- [+] BIOC-FG-004 (Persistence)
- [+] IOT-FG-003 (Control manipulation)
- [+] IOT-FG-006 (Unsafe valve state)

### Validation Checklist
- [ ] All BIOCs trigger within 5 minutes
- [ ] Critical case created in XSIAM
- [ ] Alerts routed to SOC/OT teams
- [ ] PCAP capture initiated
- [ ] Correct severity assigned
- [ ] Enrichment data populated
- [ ] Response playbook recommended

---

## MITRE ATT&CK Mapping

| Tactic | Technique | Rule |
|--------|-----------|------|
| Discovery | T1046 - Network Service Discovery | BIOC-FG-001, BIOC-FG-002 |
| Execution | T1059.006 - Python | BIOC-FG-008 |
| Execution | T0855 - Unauthorized Command | BIOC-FG-003, BIOC-FG-004 |
| Impact | T0836 - Modify Parameter | All BIOCs |
| Impact | T0858 - Change Operating Mode | BIOC-FG-005 |
| Impact | T0831 - Manipulation of Control | BIOC-FG-007 |

---

## Contact Information

| Team | Contact | Use Case |
|------|---------|----------|
| SOC | soc@company.com | All alerts |
| OT Security | ot-security@company.com | Critical ICS alerts |
| Plant Operations | plant-ops@company.com | Emergency shutdown |
| Incident Commander | oncall-ic@company.com | P0 incidents |
| CISO | ciso@company.com | Escalations |

---

## Document Version

**Version**: 1.0
**Created**: 2026-01-23
**Last Updated**: 2026-01-23
**Review Schedule**: Quarterly
**Classification**: Internal - OT Security
