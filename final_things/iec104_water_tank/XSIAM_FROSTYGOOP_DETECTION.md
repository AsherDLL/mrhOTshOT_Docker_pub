# XSIAM Detection Rules for FrostyGoop Malware

## Executive Summary

This document provides comprehensive detection rules for identifying FrostyGoop malware execution targeting industrial control systems (ICS). FrostyGoop is the 9th known ICS-specific malware that uses Modbus TCP protocol to manipulate industrial processes.

**Target Environment**: Water Tank Control System (IEC104/Modbus TCP)
**Threat Actor**: Nation-state or APT targeting critical infrastructure
**Attack Vector**: Modbus TCP protocol exploitation
**Impact**: System disruption, physical damage (tank overflow/rupture)

---

## Table of Contents

1. [Behavioral Indicators of Compromise (BIOCs)](#biocs)
2. [IoT Security Custom Rules](#iot-security-custom-rules)
3. [XQL Correlation Rules](#xql-correlation-rules)
4. [Alert Prioritization](#alert-prioritization)

---

## BIOCs (Behavioral Indicators of Compromise)

### BIOC-1: Multi-Protocol ICS/SCADA Port Scanning

**Description**: FrostyGoop performs reconnaissance by scanning multiple ICS/SCADA protocol ports sequentially.

**Behavioral Pattern**:
- Single source IP connects to multiple ICS ports within short timeframe (< 60 seconds)
- Target ports: 502 (Modbus), 2404 (IEC104), 102 (S7), 4840 (OPC-UA), 44818 (EtherNet/IP)
- Connection attempts may be short-lived (< 3 seconds)

**Detection Logic**:
```
Source IP → Destination IP with connections to ≥3 different ICS ports within 60 seconds
```

**XSIAM BIOC Rule**:
```yaml
name: "FrostyGoop - ICS Multi-Protocol Port Scan"
description: "Detects scanning of multiple ICS/SCADA protocol ports"
severity: High
mitre_attack:
  - T1046 (Network Service Discovery)
  - T1595.002 (Active Scanning: Vulnerability Scanning)

behavioral_indicators:
  - unique_destination_ports >= 3
  - destination_ports IN [102, 502, 2404, 4840, 44818]
  - timeframe: 60 seconds
  - source_ip: single_ip

risk_score: 75
recommended_action: "Investigate source IP for unauthorized ICS reconnaissance"
```

---

### BIOC-2: Modbus Slave ID Enumeration

**Description**: Sequential connection attempts to enumerate Modbus slave IDs on a target device.

**Behavioral Pattern**:
- Multiple Modbus Read Input Registers (Function Code 4) requests
- Targeting slave IDs: 1, 2, 10, 100, 255 (common defaults)
- Short interval between requests (< 1 second)
- May result in Modbus exceptions from non-existent slaves

**Detection Logic**:
```
Modbus connections with ≥3 different slave IDs tested within 30 seconds
```

**XSIAM BIOC Rule**:
```yaml
name: "FrostyGoop - Modbus Slave ID Enumeration"
description: "Detects enumeration of Modbus slave/unit IDs"
severity: High
mitre_attack:
  - T1046 (Network Service Discovery)

behavioral_indicators:
  - protocol: modbus_tcp
  - unique_slave_ids >= 3
  - timeframe: 30 seconds
  - modbus_function_codes: [3, 4]

risk_score: 70
recommended_action: "Verify if Modbus enumeration is authorized maintenance"
```

---

### BIOC-3: Rapid Modbus Write Operations to Control Coils

**Description**: FrostyGoop writes to multiple coils in quick succession to manipulate physical processes.

**Behavioral Pattern**:
- Modbus Function Code 5 (Write Single Coil) or 15 (Write Multiple Coils)
- ≥3 write operations within 5 seconds
- Targeting coil addresses 0-10 (typical valve/actuator controls)
- May disable automation (coil 3 in this implementation)

**Detection Logic**:
```
≥3 Modbus Write Coil operations (FC 5 or 15) within 5 seconds to same PLC
```

**XSIAM BIOC Rule**:
```yaml
name: "FrostyGoop - Rapid Modbus Control Manipulation"
description: "Detects rapid Modbus write operations to control coils"
severity: Critical
mitre_attack:
  - T0836 (Modify Parameter)
  - T0855 (Unauthorized Command Message)

behavioral_indicators:
  - protocol: modbus_tcp
  - modbus_function_codes: [5, 15]
  - write_operations_count >= 3
  - timeframe: 5 seconds
  - coil_address_range: 0-10

risk_score: 95
recommended_action: "IMMEDIATE investigation - Potential process manipulation attack"
```

---

### BIOC-4: Persistent Modbus Write Commands (Attack Maintenance)

**Description**: FrostyGoop continuously sends identical write commands to maintain attack state and prevent operator recovery.

**Behavioral Pattern**:
- Repeated Modbus writes to same coil addresses
- Identical value being written (e.g., True/ON for valve open)
- Regular interval pattern (e.g., every 5 seconds)
- Duration ≥30 seconds
- Writes to coils 0, 1, 3 (inlet valve, outlet valve, manual mode)

**Detection Logic**:
```
Same Modbus write command (function code + address + value) repeated ≥5 times over ≥25 seconds
```

**XSIAM BIOC Rule**:
```yaml
name: "FrostyGoop - Persistent Control State Manipulation"
description: "Detects continuous Modbus writes maintaining attack state"
severity: Critical
mitre_attack:
  - T0836 (Modify Parameter)
  - T0858 (Change Operating Mode)

behavioral_indicators:
  - protocol: modbus_tcp
  - modbus_function_codes: [5, 6]
  - repeated_commands: same_address_same_value
  - repetition_count >= 5
  - timeframe: >= 25 seconds
  - interval_regularity: true (variance < 20%)

risk_score: 98
recommended_action: "CRITICAL - Active attack in progress. Isolate affected PLC immediately."
```

---

### BIOC-5: Control Mode Change to Manual

**Description**: FrostyGoop disables automation by switching PLCs to manual mode before executing attack.

**Behavioral Pattern**:
- Modbus write to coil/register controlling automation mode
- Change from AUTO (True/1) to MANUAL (False/0)
- Typically coil address 3 or holding register for mode
- Followed by valve manipulation within 10 seconds

**Detection Logic**:
```
Modbus write changing automation mode to MANUAL, followed by ≥2 valve writes within 10 seconds
```

**XSIAM BIOC Rule**:
```yaml
name: "FrostyGoop - Automation Disable Before Attack"
description: "Detects disabling of PLC automation followed by control manipulation"
severity: Critical
mitre_attack:
  - T0858 (Change Operating Mode)
  - T0836 (Modify Parameter)

behavioral_indicators:
  - protocol: modbus_tcp
  - sequence:
      1. modbus_write to coil_3 OR holding_register_mode
      2. value: false OR 0
      3. followed_by: valve_commands (coils 0-2)
  - timeframe_between_steps: <= 10 seconds

risk_score: 92
recommended_action: "Investigate unauthorized mode change and subsequent commands"
```

---

### BIOC-6: Configuration File Access Pattern

**Description**: FrostyGoop loads JSON configuration files with attack parameters.

**Behavioral Pattern**:
- File access to JSON files with specific naming patterns
- Contains Modbus-specific keywords: "function_code", "address", "coil", "register"
- File paths contain "frostygoop", "config", or "modbus"
- Python process reading configuration before Modbus activity

**Detection Logic**:
```
Process reads JSON file containing Modbus keywords, then initiates Modbus TCP connections within 60 seconds
```

**XSIAM BIOC Rule**:
```yaml
name: "FrostyGoop - Malicious Configuration File Loading"
description: "Detects loading of Modbus attack configuration files"
severity: High
mitre_attack:
  - T1005 (Data from Local System)
  - T1027.010 (Obfuscated Files or Information: Command Obfuscation)

behavioral_indicators:
  - file_extension: .json
  - file_content_keywords: ["function_code", "modbus", "coil", "register", "address"]
  - filename_patterns: ["frostygoop", "config", "modbus"]
  - followed_by: network_connection to port 502
  - timeframe: 60 seconds

risk_score: 85
recommended_action: "Examine configuration file contents and associated process"
```

---

### BIOC-7: Tank Overflow Attack Pattern

**Description**: Specific attack pattern to cause water tank overflow (inlet open + outlet closed).

**Behavioral Pattern**:
- Sequence of Modbus writes:
  1. Coil 3 = False (manual mode)
  2. Coil 0 = True (inlet valve OPEN)
  3. Coil 1 = False (outlet valve CLOSED)
- Commands executed within 5 seconds
- Maintained for extended period (≥30 seconds)

**Detection Logic**:
```
Sequential Modbus writes: Manual mode → Inlet OPEN → Outlet CLOSED within 5 seconds
```

**XSIAM BIOC Rule**:
```yaml
name: "FrostyGoop - Water Tank Overflow Attack Signature"
description: "Detects specific command sequence for tank overflow attack"
severity: Critical
mitre_attack:
  - T0831 (Manipulation of Control)
  - T0836 (Modify Parameter)

behavioral_indicators:
  - protocol: modbus_tcp
  - command_sequence:
      - coil_3: false (manual mode)
      - coil_0: true (inlet open)
      - coil_1: false (outlet closed)
  - sequence_timeframe: <= 5 seconds
  - persistence: commands maintained >= 30 seconds

risk_score: 100
recommended_action: "EMERGENCY - Tank overflow attack detected. Execute emergency shutdown."
alert_routing: "SOC, OT Security Team, Plant Operations"
```

---

### BIOC-8: Process Execution with ICS Keywords

**Description**: Execution of Python scripts with ICS/malware-related keywords.

**Behavioral Pattern**:
- Python process execution
- Command line contains: "frostygoop", "modbus", "simulation", "attack", "iec104"
- Process name contains malware/simulation indicators
- May include arguments: --target, --config, --duration

**Detection Logic**:
```
Python process with command line containing ICS attack keywords
```

**XSIAM BIOC Rule**:
```yaml
name: "FrostyGoop - Suspicious Process Execution"
description: "Detects execution of FrostyGoop-related Python scripts"
severity: High
mitre_attack:
  - T1059.006 (Command and Scripting Interpreter: Python)

behavioral_indicators:
  - process_name: python OR python3
  - command_line_keywords: ["frostygoop", "modbus", "attack", "simulation", "iec104"]
  - command_line_arguments: ["--target", "--config", "--port 502"]

risk_score: 80
recommended_action: "Terminate process and investigate execution context"
```

---

## IoT Security Custom Rules

### Custom Rule 1: Modbus Write Frequency Anomaly

**Rule Type**: Statistical Anomaly Detection
**Protocol**: Modbus TCP
**Asset Type**: PLC, RTU, Industrial Controller

**Rule Configuration**:
```yaml
name: "Modbus Write Frequency Anomaly - FrostyGoop Indicator"
category: "Protocol Anomaly"
protocol: modbus_tcp
severity: High

detection_logic:
  baseline_learning_period: 7 days
  anomaly_detection:
    metric: modbus_write_operations_per_minute
    function_codes: [5, 6, 15, 16]
    threshold: 3 standard deviations above baseline
    minimum_baseline_samples: 1000

  anomaly_conditions:
    - write_frequency > (baseline_mean + 3 * baseline_stddev)
    - sustained_duration >= 30 seconds

alert_details:
  message: "Abnormal Modbus write frequency detected - possible FrostyGoop attack"
  include_fields:
    - source_ip
    - destination_ip
    - modbus_unit_id
    - function_codes_used
    - write_operations_count
    - baseline_comparison

response_actions:
  - alert_soc
  - create_incident
  - tag_asset: "potential_compromise"
```

---

### Custom Rule 2: Unauthorized Modbus Source Detection

**Rule Type**: Whitelist Violation
**Protocol**: Modbus TCP
**Asset Type**: All Modbus devices

**Rule Configuration**:
```yaml
name: "Unauthorized Modbus Client - FrostyGoop Source Detection"
category: "Access Control Violation"
protocol: modbus_tcp
severity: Critical

detection_logic:
  whitelist_type: modbus_client_ips
  whitelist_sources:
    - HMI workstations
    - SCADA servers
    - Authorized maintenance laptops

  violation_conditions:
    - source_ip NOT IN whitelist
    - modbus_function_codes IN [5, 6, 15, 16] (write operations)
    - connection_established: true

alert_details:
  message: "Modbus write operation from unauthorized source - FrostyGoop indicator"
  include_fields:
    - unauthorized_source_ip
    - target_plc_ip
    - modbus_unit_id
    - function_code
    - coil_register_addresses

response_actions:
  - block_source_ip (if firewall integration enabled)
  - alert_soc
  - create_critical_incident
  - notify_ot_team
```

---

### Custom Rule 3: Control Coil Manipulation Pattern

**Rule Type**: Behavioral Pattern Matching
**Protocol**: Modbus TCP
**Asset Type**: Water Tank PLC

**Rule Configuration**:
```yaml
name: "Control Coil Manipulation - FrostyGoop Attack Pattern"
category: "Process Manipulation"
protocol: modbus_tcp
severity: Critical

detection_logic:
  pattern_matching:
    target_coils: [0, 1, 2, 3] # inlet, outlet, pump, mode
    function_codes: [5, 15]

  attack_indicators:
    - coil_writes >= 3 within 10 seconds
    - OR sequence_match:
        - coil_3: write false (manual mode)
        - coil_0: write true (inlet open)
        - coil_1: write false (outlet closed)
        - sequence_window: 10 seconds

alert_details:
  message: "Critical control manipulation detected - FrostyGoop attack signature"
  include_fields:
    - source_ip
    - plc_ip
    - coils_modified
    - values_written
    - sequence_timeline

response_actions:
  - create_critical_incident
  - alert_soc
  - alert_ot_team
  - alert_plant_operations
  - recommend_action: "Verify PLC state and consider isolation"
```

---

### Custom Rule 4: Modbus Session Duration Anomaly

**Rule Type**: Session Analysis
**Protocol**: Modbus TCP
**Asset Type**: All Modbus devices

**Rule Configuration**:
```yaml
name: "Extended Modbus Session - FrostyGoop Persistence"
category: "Session Anomaly"
protocol: modbus_tcp
severity: High

detection_logic:
  baseline_learning_period: 7 days
  session_analysis:
    metric: session_duration
    threshold: sessions > 60 seconds
    baseline_comparison: sessions exceeding 95th percentile

  persistence_indicators:
    - session_duration >= 60 seconds
    - repeated_commands: true
    - command_pattern: identical_writes
    - write_interval_regularity: variance < 20%

alert_details:
  message: "Extended Modbus session with repetitive writes - FrostyGoop persistence"
  include_fields:
    - source_ip
    - destination_ip
    - session_duration
    - command_repetition_count
    - command_interval_mean
    - command_interval_variance

response_actions:
  - create_incident
  - alert_soc
  - capture_pcap
```

---

### Custom Rule 5: ICS Multi-Protocol Discovery

**Rule Type**: Network Reconnaissance
**Protocol**: Multi-protocol (TCP)
**Asset Type**: Network-wide

**Rule Configuration**:
```yaml
name: "ICS Multi-Protocol Scanning - FrostyGoop Reconnaissance"
category: "Reconnaissance"
protocol: tcp
severity: High

detection_logic:
  reconnaissance_indicators:
    source_ip: single_ip
    destination_ports: [102, 502, 2404, 4840, 44818]
    unique_ports_contacted: >= 3
    timeframe: 60 seconds
    connection_duration: < 5 seconds (short-lived)

  scan_patterns:
    - sequential_port_probing: true
    - SYN_only_connections: allowed
    - connection_attempts_per_port: 1-3

alert_details:
  message: "ICS/SCADA multi-protocol scanning detected - FrostyGoop reconnaissance phase"
  include_fields:
    - scanner_ip
    - target_ips
    - ports_scanned
    - scan_timeline
    - response_codes

response_actions:
  - create_incident
  - alert_soc
  - monitor_source_ip (enhanced logging)
  - threat_intel_lookup: source_ip
```

---

### Custom Rule 6: Unsafe Valve State Combination

**Rule Type**: Process Safety Violation
**Protocol**: Modbus TCP
**Asset Type**: Water Tank PLC

**Rule Configuration**:
```yaml
name: "Unsafe Valve Configuration - FrostyGoop Overflow Attack"
category: "Process Safety"
protocol: modbus_tcp
severity: Critical

detection_logic:
  safety_monitoring:
    coil_states:
      inlet_valve_coil_0: monitored
      outlet_valve_coil_1: monitored
      auto_mode_coil_3: monitored

  unsafe_conditions:
    - inlet_valve: OPEN (true)
      AND outlet_valve: CLOSED (false)
      AND auto_mode: MANUAL (false)
      AND duration: >= 10 seconds

  process_impact:
    - predicted_outcome: tank_overflow
    - time_to_critical: estimated based on inlet flow rate

alert_details:
  message: "CRITICAL: Unsafe valve state - Tank overflow imminent (FrostyGoop attack)"
  include_fields:
    - current_water_level
    - inlet_valve_state
    - outlet_valve_state
    - control_mode
    - time_in_unsafe_state
    - estimated_time_to_overflow

response_actions:
  - create_critical_incident
  - alert_soc
  - alert_ot_team
  - alert_plant_operations
  - emergency_notification: true
  - recommended_action: "IMMEDIATE VALVE OVERRIDE REQUIRED"
```

---

### Custom Rule 7: Modbus Exception Rate Spike

**Rule Type**: Protocol Error Monitoring
**Protocol**: Modbus TCP
**Asset Type**: All Modbus devices

**Rule Configuration**:
```yaml
name: "Modbus Exception Spike - FrostyGoop Enumeration"
category: "Protocol Anomaly"
protocol: modbus_tcp
severity: Medium

detection_logic:
  baseline_learning_period: 7 days
  error_monitoring:
    metric: modbus_exception_responses_per_minute
    exception_codes: [1, 2, 3, 4, 5, 6] # All Modbus exceptions

  anomaly_conditions:
    - exception_rate > (baseline_mean + 2 * baseline_stddev)
    - OR exception_count >= 10 within 60 seconds
    - source_ip: specific_external_ip

alert_details:
  message: "Modbus exception rate spike - Possible enumeration/reconnaissance"
  include_fields:
    - source_ip
    - destination_ip
    - exception_codes
    - exception_count
    - failed_slave_ids
    - failed_addresses

response_actions:
  - create_incident
  - alert_soc
  - monitor_source_ip
```

---

## XQL Correlation Rules

### XQL Rule 1: Multi-Stage FrostyGoop Attack Detection

**Description**: Correlates multiple attack phases from reconnaissance to payload execution.

```xql
/* FrostyGoop Multi-Stage Attack Correlation */
config case_insensitive = true
| dataset = network_traffic, process_events
| alter attack_score = 0

/* Phase 1: ICS Port Scanning */
| alter attack_score = if(
    network_protocol = "TCP" and
    destination_port in (102, 502, 2404, 4840, 44818) and
    arraycount(arrayunique(destination_port)) >= 3,
    attack_score + 20,
    attack_score
)

/* Phase 2: Modbus Connection */
| alter attack_score = if(
    network_protocol = "TCP" and
    destination_port = 502 and
    modbus_function_code in (3, 4, 5, 6, 15, 16),
    attack_score + 25,
    attack_score
)

/* Phase 3: Control Manipulation */
| alter attack_score = if(
    modbus_function_code in (5, 15) and
    modbus_address in (0, 1, 2, 3) and
    operation_type = "write",
    attack_score + 30,
    attack_score
)

/* Phase 4: Persistence Pattern */
| alter attack_score = if(
    arraycount(arrayfilter(modbus_operations, "@element.function_code" = 5 and "@element.address" = 0)) >= 5,
    attack_score + 25,
    attack_score
)

/* Aggregate and Alert */
| comp max(attack_score) as max_attack_score by source_ip, destination_ip, _time
| filter max_attack_score >= 75
| alter severity = if(max_attack_score >= 95, "Critical", if(max_attack_score >= 75, "High", "Medium"))
| alter alert_name = "FrostyGoop Multi-Stage Attack Detected"
| alter mitre_tactics = "Reconnaissance, Execution, Impact"
| alter recommended_action = "Isolate affected PLC, investigate source IP, review all Modbus commands"
```

---

### XQL Rule 2: FrostyGoop Process + Network Correlation

**Description**: Correlates suspicious process execution with Modbus network activity.

```xql
/* FrostyGoop Process-to-Network Correlation */
config case_insensitive = true
| dataset = process_events, network_traffic

/* Identify Suspicious Process */
| filter (
    process_name in ("python", "python3", "python.exe") and
    (process_cmd_line contains "frostygoop" or
     process_cmd_line contains "modbus" or
     process_cmd_line contains "attack" or
     process_cmd_line contains "--port 502" or
     process_cmd_line contains "--config")
)

/* Correlate with Modbus Network Activity */
| join type = inner (
    dataset = network_traffic
    | filter destination_port = 502 and network_protocol = "TCP"
) as network_events
on process_events.agent_ip = network_events.source_ip
and network_events._time > process_events._time
and network_events._time < process_events._time + interval 5 minutes

/* Enrich and Alert */
| alter alert_name = "FrostyGoop Execution with Modbus Activity"
| alter severity = "Critical"
| alter mitre_techniques = "T1059.006, T0855, T0836"
| alter description = concat("Suspicious Python process '", process_cmd_line, "' followed by Modbus TCP activity to ", network_events.destination_ip)
| alter recommended_action = "Terminate process, isolate host, analyze Modbus commands sent"
| fields alert_name, severity, agent_ip, process_cmd_line, network_events.destination_ip, network_events.destination_port, mitre_techniques, recommended_action
```

---

### XQL Rule 3: Tank Overflow Attack Sequence Detection

**Description**: Detects specific command sequence for water tank overflow attack.

```xql
/* FrostyGoop Tank Overflow Attack Sequence */
config case_insensitive = true
| dataset = iot_security_events
| filter protocol = "modbus_tcp"

/* Extract Modbus write events */
| filter modbus_function_code in (5, 15) and operation_type = "write"

/* Sequence Detection: Manual Mode -> Inlet Open -> Outlet Closed */
| sort asc _time
| alter phase = if(modbus_address = 3 and modbus_value = "false", "manual_mode",
                if(modbus_address = 0 and modbus_value = "true", "inlet_open",
                if(modbus_address = 1 and modbus_value = "false", "outlet_closed", null)))
| filter phase != null

/* Group by attack session */
| comp values(phase) as attack_phases,
       min(_time) as attack_start,
       max(_time) as attack_end,
       count() as command_count
  by source_ip, destination_ip, _time

/* Detect complete sequence */
| filter arraycontains(attack_phases, "manual_mode") and
         arraycontains(attack_phases, "inlet_open") and
         arraycontains(attack_phases, "outlet_closed")
| alter attack_duration = attack_end - attack_start
| filter attack_duration <= interval 10 seconds

/* Alert on match */
| alter alert_name = "FrostyGoop Tank Overflow Attack Sequence Detected"
| alter severity = "Critical"
| alter attack_type = "Process Manipulation - Tank Overflow"
| alter mitre_techniques = "T0831, T0836, T0858"
| alter recommended_action = "EMERGENCY: Execute immediate tank shutdown. Override PLC commands. Isolate attacker."
| fields alert_name, severity, source_ip, destination_ip, attack_phases, attack_start, attack_duration, command_count, recommended_action
```

---

### XQL Rule 4: Modbus Persistence Detection

**Description**: Identifies repetitive Modbus writes characteristic of FrostyGoop persistence.

```xql
/* FrostyGoop Modbus Persistence Pattern */
config case_insensitive = true
| dataset = iot_security_events
| filter protocol = "modbus_tcp" and modbus_function_code in (5, 6)

/* Create command signature */
| alter command_signature = concat(modbus_function_code, "-", modbus_address, "-", modbus_value)

/* Count repetitions over time */
| comp count() as repetition_count,
       values(_time) as timestamps,
       avg(time_between_commands) as avg_interval
  by source_ip, destination_ip, command_signature
| filter repetition_count >= 5

/* Calculate interval regularity */
| alter interval_variance = stdev(time_between_commands) / avg_interval
| filter interval_variance < 0.20  // Less than 20% variance = regular pattern

/* Calculate attack duration */
| alter first_command = arraymin(timestamps)
| alter last_command = arraymax(timestamps)
| alter attack_duration_seconds = (last_command - first_command) / 1000
| filter attack_duration_seconds >= 25

/* Alert */
| alter alert_name = "FrostyGoop Persistence Mechanism Detected"
| alter severity = "Critical"
| alter description = concat("Repeated Modbus command '", command_signature, "' sent ", repetition_count, " times over ", attack_duration_seconds, " seconds")
| alter mitre_techniques = "T0836, T0855"
| alter recommended_action = "Active attack in progress. Isolate PLC from network immediately."
| fields alert_name, severity, source_ip, destination_ip, command_signature, repetition_count, attack_duration_seconds, avg_interval, recommended_action
```

---

## Alert Prioritization

### Critical Priority (Immediate Response Required)

1. **BIOC-7**: Tank Overflow Attack Pattern (Risk Score: 100)
2. **BIOC-4**: Persistent Modbus Write Commands (Risk Score: 98)
3. **BIOC-3**: Rapid Modbus Write Operations (Risk Score: 95)
4. **Custom Rule 6**: Unsafe Valve State Combination
5. **XQL Rule 3**: Tank Overflow Attack Sequence Detection

**Response Actions**:
- Immediate SOC/OT team notification
- Isolate affected PLC from network
- Override PLC commands via manual controls
- Execute emergency shutdown procedures
- Capture network traffic (PCAP)
- Preserve logs and forensic evidence

---

### High Priority (Response within 15 minutes)

1. **BIOC-5**: Control Mode Change to Manual (Risk Score: 92)
2. **BIOC-6**: Configuration File Access Pattern (Risk Score: 85)
3. **BIOC-8**: Process Execution with ICS Keywords (Risk Score: 80)
4. **BIOC-1**: Multi-Protocol ICS/SCADA Port Scanning (Risk Score: 75)
5. **Custom Rule 1**: Modbus Write Frequency Anomaly
6. **Custom Rule 2**: Unauthorized Modbus Source Detection

**Response Actions**:
- Investigate source IP/host
- Review Modbus command history
- Check PLC operational state
- Verify authorized maintenance activities
- Enhanced monitoring on affected assets

---

### Medium Priority (Response within 1 hour)

1. **BIOC-2**: Modbus Slave ID Enumeration (Risk Score: 70)
2. **Custom Rule 4**: Modbus Session Duration Anomaly
3. **Custom Rule 5**: ICS Multi-Protocol Discovery
4. **Custom Rule 7**: Modbus Exception Rate Spike

**Response Actions**:
- Log analysis and correlation
- Threat intelligence lookup
- Asset inventory verification
- Network segmentation review

---

## Implementation Checklist

### XSIAM Configuration

- [ ] Import all BIOC rules into XSIAM
- [ ] Configure IoT Security custom rules
- [ ] Deploy XQL correlation rules
- [ ] Set up alert routing to SOC/OT teams
- [ ] Configure severity-based escalation
- [ ] Enable automated PCAP capture for Critical alerts
- [ ] Integrate with firewall for automated blocking (if applicable)

### Network Monitoring

- [ ] Enable Modbus TCP protocol inspection on IoT Security sensors
- [ ] Deploy sensors at ICS network boundaries
- [ ] Configure Modbus protocol decoder
- [ ] Enable deep packet inspection for Modbus payloads
- [ ] Set up NetFlow/IPFIX for session analysis

### Asset Management

- [ ] Create inventory of all Modbus-capable PLCs
- [ ] Document authorized Modbus clients (HMI, SCADA, maintenance laptops)
- [ ] Create IP whitelists for Modbus access
- [ ] Tag critical assets (water tank PLCs, safety systems)
- [ ] Map control relationships (which HMI controls which PLC)

### Baseline Establishment

- [ ] Collect 7-day baseline of Modbus traffic patterns
- [ ] Document normal write operation frequency
- [ ] Identify typical session durations
- [ ] Record standard coil/register access patterns
- [ ] Establish exception rate baseline

### Response Procedures

- [ ] Create FrostyGoop-specific incident response playbook
- [ ] Define emergency shutdown procedures
- [ ] Establish SOC-to-OT communication channels
- [ ] Document PLC override procedures
- [ ] Schedule tabletop exercises

---

## Testing and Validation

### Test Scenarios

1. **Reconnaissance Test**: Generate ICS port scans and verify BIOC-1 triggers
2. **Enumeration Test**: Perform Modbus slave ID scans and verify BIOC-2 triggers
3. **Write Operation Test**: Execute rapid Modbus writes and verify BIOC-3 triggers
4. **Persistence Test**: Send repetitive commands and verify BIOC-4 triggers
5. **Attack Sequence Test**: Execute full attack chain and verify XQL Rule 3 triggers

### Validation Steps

```bash
# Test FrostyGoop simulation execution
cd /opt/mrhOTshOT/final_things/iec104_water_tank/perform_malware_simulations
python frostygoop_simulation.py --config frostygoop_config.json --duration 30

# Verify XSIAM detection within 5 minutes
# Check for case creation with severity "Critical"
# Validate all expected BIOCs triggered
# Confirm alert routing to SOC/OT teams
```

---

## References

### FrostyGoop Threat Intelligence
- Palo Alto Networks Unit 42: FrostyGoop Analysis
- Dragos: Protecting Against FrostyGoop ICS Malware
- Nozomi Networks: FrostyGoop/BUSTLEBERM Analysis

### MITRE ATT&CK for ICS
- T0836: Modify Parameter
- T0855: Unauthorized Command Message
- T0858: Change Operating Mode
- T0831: Manipulation of Control
- T1046: Network Service Discovery

### Modbus Protocol Resources
- Modbus Organization: Protocol Specification
- ICS-CERT: Modbus Security Recommendations

---

## Document Control

**Version**: 1.0
**Created**: 2026-01-23
**Classification**: Internal - OT Security
**Review Schedule**: Quarterly or after significant threat landscape changes
