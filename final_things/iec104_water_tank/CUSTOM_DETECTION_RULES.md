# Custom Detection Rules & BIOCs for Industroyer2 Simulation

This guide provides custom detection rules for Palo Alto Networks products to detect the Industroyer2 attack chain.

---

## Table of Contents

1. [XSIAM Custom Correlation Rules](#xsiam-custom-correlation-rules)
2. [Cortex XDR BIOC Rules](#cortex-xdr-bioc-rules)
3. [Firewall Custom Threat Signatures](#firewall-custom-threat-signatures)
4. [WildFire Custom Analysis](#wildfire-custom-analysis)
5. [IOCs to Monitor](#iocs-to-monitor)

---

## XSIAM Custom Correlation Rules

### Rule 1: Industroyer2 Full Attack Chain

**Purpose:** Detect the complete 7-phase attack chain

**Configuration:**
```yaml
rule_name: "Industroyer2 Attack Chain Detection"
severity: Critical
description: "Detects multi-phase Industroyer2-style attack from initial access to OT disruption"

correlation_logic:
  time_window: 2 hours
  minimum_phases: 4

phases:
  - phase_1_initial_access:
      any_of:
        - event_type: "Command Injection"
          signature_contains: "router"
        - event_type: "Reverse Shell"
          destination_port: [4444, 4445, 1337]
        - event_type: "Phishing"
          url_category: "malware"

  - phase_2_discovery:
      any_of:
        - event_type: "Port Scan"
          ports_scanned: "> 10"
        - event_type: "ICMP Flood"
        - event_type: "SMB Enumeration"

  - phase_3_credential_access:
      any_of:
        - process_name: "rundll32.exe"
          command_line_contains: "comsvcs.dll"
        - process_name: "reg.exe"
          command_line_contains: ["save", "HKLM\\SAM"]
        - process_name: "pypykatz"

  - phase_4_lateral_movement:
      any_of:
        - event_type: "PsExec Execution"
        - event_type: "WMI Remote Execution"
        - authentication_type: "NTLM"
          authentication_count: "> 5"

  - phase_5_execution:
      any_of:
        - process_name: "powershell.exe"
          command_line_contains: "EncodedCommand"
        - file_created: "*.zip"
          file_path_contains: "Temp"
        - process_name: "taskkill.exe"

  - phase_6_impact:
      any_of:
        - process_terminated: "PService_PPD.exe"
        - event_log_cleared: ["Security", "System", "Application"]
        - file_deletion_count: "> 10"

  - phase_7_ot_attack:
      any_of:
        - destination_port: 2404
          protocol: "IEC-104"
        - network_bytes_out: "> 10000"
          destination_ip: "192.168.1.6"

alerts:
  - type: "email"
    recipients: ["soc@company.com"]
  - type: "incident"
    auto_assign: true
  - type: "slack"
    channel: "#security-alerts"

mitre_attack:
  - T1190  # Exploit Public-Facing Application
  - T1003  # OS Credential Dumping
  - T1021  # Remote Services
  - T1059  # Command and Scripting Interpreter
  - T1070  # Indicator Removal
  - T1485  # Data Destruction
  - T1489  # Service Stop
```

**How to Create in XSIAM:**
1. Navigate to: **Response → Correlation Rules**
2. Click **+ New Rule**
3. Select **"Multi-Event Correlation"**
4. Copy logic from above
5. Set severity: **Critical**
6. Enable: **Auto-create Incident**

---

### Rule 2: IT-to-OT Pivot Detection

**Purpose:** Detect lateral movement from IT network to OT network

```yaml
rule_name: "IT-to-OT Network Pivot"
severity: High
description: "Detects suspicious traffic from IT network to OT network"

query: |
  config case_sensitive = false
  | dataset = xdr_data
  | filter source_ip in ("192.168.1.0/24")
  | filter destination_ip in ("192.168.1.6")
  | filter destination_port in (2404, 502, 102, 4840, 44818)
  | alter is_ot_protocol = if(destination_port in (2404, 502, 102, 4840, 44818), "true", "false")
  | filter is_ot_protocol = "true"
  | comp count() as connection_count by source_ip, destination_port
  | filter connection_count > 5

time_window: 10 minutes

alerts:
  severity: High
  action: "Create Incident"
  tags: ["OT Security", "Network Segmentation Bypass"]
```

**XQL Query for XSIAM:**
```xql
config case_sensitive = false
| dataset = xdr_data
| filter event_timestamp > ago(1h)
| filter source_ip in ("192.168.1.0/24")
| filter destination_ip = "192.168.1.6"
| filter destination_port = 2404
| fields event_timestamp, source_ip, destination_ip, destination_port, action_process_image_name
| sort asc event_timestamp
```

---

### Rule 3: Credential Dumping Sequence

**Purpose:** Detect LSASS + Registry credential dumping

```yaml
rule_name: "Credential Dumping Sequence Detection"
severity: Critical
description: "Detects sequential LSASS dump and registry hive dump"

query: |
  config case_sensitive = false
  | dataset = xdr_data
  | filter event_timestamp > ago(30m)
  | filter (
      (actor_process_image_name = "rundll32.exe" and
       actor_process_command_line contains "comsvcs.dll" and
       actor_process_command_line contains "MiniDump")
      OR
      (actor_process_image_name = "reg.exe" and
       actor_process_command_line contains "save" and
       actor_process_command_line contains "HKLM")
    )
  | comp count_distinct(actor_process_image_name) as unique_techniques by agent_hostname
  | filter unique_techniques >= 2

time_window: 30 minutes

alerts:
  severity: Critical
  action: "Isolate Endpoint"
  notification: "Immediate"
```

---

### Rule 4: Multi-Method File Transfer

**Purpose:** Detect file transferred via multiple methods (SMB, HTTP, PowerShell, RDP)

```yaml
rule_name: "Multi-Method File Transfer Detection"
severity: Medium
description: "Detects same file transferred via multiple methods - possible evasion"

query: |
  config case_sensitive = false
  | dataset = xdr_data
  | filter event_timestamp > ago(1h)
  | filter (
      event_type = "FILE_WRITE" OR
      event_type = "FILE_CREATE" OR
      action_process_image_name in ("powershell.exe", "certutil.exe", "xfreerdp")
    )
  | filter action_file_name contains ".zip" OR action_file_name contains ".exe"
  | comp count_distinct(action_process_image_name) as transfer_methods by action_file_name, agent_hostname
  | filter transfer_methods >= 2

time_window: 1 hour

alerts:
  severity: Medium
  tags: ["Evasion", "Lateral Movement"]
```

---

## Cortex XDR BIOC Rules

### BIOC 1: LSASS Memory Dump Detection

**Configuration:**
```yaml
bioc_name: "LSASS Memory Dump via comsvcs.dll"
severity: Critical
category: "Credential Access"

rule_logic:
  event_type: PROCESS_EXECUTION

  conditions:
    all_of:
      - actor_process_image_name: "rundll32.exe"
      - actor_process_command_line:
          contains_all:
            - "comsvcs.dll"
            - "MiniDump"
      - target_process_name: "lsass.exe"  # If accessible

  exclusions:
    - actor_process_signature_vendor: "Microsoft Corporation"
      actor_process_signature_status: "Signed"

actions:
  - alert_severity: Critical
  - create_incident: true
  - isolate_endpoint: false  # For testing, set to true in production
  - terminate_process: false  # For testing

mitre_attack:
  technique: "T1003.001"
  tactic: "Credential Access"
```

**How to Create:**
1. Cortex XDR → **Response → BIOC Rules**
2. Click **+ New Rule**
3. Select **"Process Execution"**
4. Add conditions above
5. Set action: **Alert Only** (for testing)

---

### BIOC 2: Registry Hive Dump Detection

```yaml
bioc_name: "Registry SAM/SECURITY/SYSTEM Hive Dump"
severity: High
category: "Credential Access"

rule_logic:
  event_type: PROCESS_EXECUTION

  conditions:
    all_of:
      - actor_process_image_name: "reg.exe"
      - actor_process_command_line:
          contains: "save"
      - actor_process_command_line:
          contains_any: ["HKLM\\SAM", "HKLM\\SECURITY", "HKLM\\SYSTEM"]

actions:
  - alert_severity: High
  - create_incident: true

mitre_attack:
  technique: "T1003.002"
  tactic: "Credential Access"
```

---

### BIOC 3: Event Log Deletion

```yaml
bioc_name: "Windows Event Log Deletion"
severity: High
category: "Defense Evasion"

rule_logic:
  event_type: PROCESS_EXECUTION

  conditions:
    any_of:
      - actor_process_image_name: "wevtutil.exe"
        actor_process_command_line:
          contains_all: ["cl", "Security"]
      - actor_process_image_name: "wevtutil.exe"
        actor_process_command_line:
          contains_all: ["clear-log"]
      - actor_process_image_name: "powershell.exe"
        actor_process_command_line:
          contains: "Clear-EventLog"

actions:
  - alert_severity: High
  - create_incident: true

mitre_attack:
  technique: "T1070.001"
  tactic: "Defense Evasion"
```

---

### BIOC 4: Critical Process Termination (PService_PPD.exe)

```yaml
bioc_name: "SCADA Process Termination (Industroyer2 TTP)"
severity: Critical
category: "Impact"

rule_logic:
  event_type: PROCESS_TERMINATE

  conditions:
    any_of:
      - target_process_name:
          matches_regex: "PService.*\\.exe"
      - actor_process_image_name: "taskkill.exe"
        actor_process_command_line:
          contains: "/F"
          contains: "PService"

actions:
  - alert_severity: Critical
  - create_incident: true
  - alert_description: "SCADA monitoring process terminated - possible Industroyer2 attack"

mitre_attack:
  technique: "T1489"
  tactic: "Impact"
```

---

### BIOC 5: PowerShell Encoded Command with File Transfer

```yaml
bioc_name: "PowerShell Encoded File Transfer"
severity: Medium
category: "Execution"

rule_logic:
  event_type: PROCESS_EXECUTION

  conditions:
    all_of:
      - actor_process_image_name: "powershell.exe"
      - actor_process_command_line:
          contains_any: ["-EncodedCommand", "-enc", "-e"]
      - actor_process_command_line:
          contains_any: ["FromBase64String", "WriteAllBytes", "DownloadFile"]

actions:
  - alert_severity: Medium
  - create_incident: false
  - add_to_investigation: true

mitre_attack:
  technique: "T1027"
  tactic: "Defense Evasion"
```

---

### BIOC 6: Multiple Failed Auth + Successful Auth (Brute Force)

```yaml
bioc_name: "SMB Brute Force Then Success"
severity: High
category: "Credential Access"

rule_logic:
  event_type: AUTHENTICATION

  conditions:
    sequence:
      - event_id: 4625  # Failed logon
        count: "> 5"
        timeframe: "5 minutes"
        same_source_ip: true
      - event_id: 4624  # Successful logon
        timeframe: "within 2 minutes after"
        same_source_ip: true
        logon_type: 3  # Network logon

actions:
  - alert_severity: High
  - create_incident: true
  - alert_description: "Brute force attack followed by successful authentication"

mitre_attack:
  technique: "T1110.001"
  tactic: "Credential Access"
```

---

### BIOC 7: CaddyWiper File Destruction Pattern

```yaml
bioc_name: "Mass File Deletion/Overwrite (CaddyWiper)"
severity: Critical
category: "Impact"

rule_logic:
  event_type: FILE_DELETE

  conditions:
    all_of:
      - file_count: "> 20"
        timeframe: "1 minute"
        same_process: true
      - file_path:
          contains_any: ["config", "backup", "data"]
      - actor_process_name:
          not_in: ["explorer.exe", "cleanmgr.exe"]

actions:
  - alert_severity: Critical
  - create_incident: true
  - isolate_endpoint: true  # Consider enabling for production
  - alert_description: "Potential wiper malware - mass file deletion detected"

mitre_attack:
  technique: "T1485"
  tactic: "Impact"
```

---

## Firewall Custom Threat Signatures

### Signature 1: IEC-104 Command Injection Pattern

**Purpose:** Detect malicious IEC-104 commands to RTU

```
signature_name: "IEC-104 Malicious Command Pattern"
category: "ics-malware"
severity: critical

pattern:
  protocol: tcp
  destination_port: 2404

  payload_pattern:
    # IEC-104 APDU format with suspicious IOAs
    hex_pattern: "68.*45.*"  # Type 45 (C_SC_NA_1) commands

    # Industroyer2 specific IOAs
    ioa_pattern:
      - "1101" to "1404"  # Circuit breaker IOAs
      - "130202"          # Switch IOAs
      - "260202"

  threshold:
    count: "> 10"
    timeframe: "10 seconds"

action:
  - alert
  - log
  - reset_both  # Drop connection

application: "iec-104"
```

**How to Create:**
1. Firewall → **Objects → Security Profiles → Vulnerability Protection**
2. Click **Add** → **Vulnerability Exception**
3. Enter pattern above (or use custom app-id)

---

### Signature 2: Reverse Shell Detection

```
signature_name: "Reverse Shell Connection Pattern"
category: "malware"
severity: high

pattern:
  protocol: tcp
  destination_port: [4444, 4445, 1337, 31337]
  direction: outbound

  payload_pattern:
    # Common reverse shell indicators
    regex: "(/bin/sh|/bin/bash|cmd.exe|powershell.exe)"

  connection_properties:
    - long_lived: true
    - bidirectional_traffic: true

action:
  - alert
  - reset_client
  - block_ip: "24 hours"

application: "unknown-tcp"
```

---

### Signature 3: SMB Lateral Movement

```
signature_name: "SMB Lateral Movement to Admin Share"
category: "lateral-movement"
severity: medium

pattern:
  protocol: smb
  smb_command: "TREE_CONNECT"
  share_name: ["ADMIN$", "C$", "IPC$"]

  conditions:
    - multiple_hosts: "> 3"
    - timeframe: "5 minutes"
    - authentication: "NTLM"

action:
  - alert
  - log

application: "smb"
```

---

## WildFire Custom Analysis

### YARA Rule 1: Industroyer2 Payload Detection

```yara
rule Industroyer2_Simulation_Payload
{
    meta:
        description = "Detects Industroyer2 simulation payload components"
        author = "Security Team"
        severity = "high"

    strings:
        $s1 = "industroyer2_simulation.py" ascii
        $s2 = "industroyer2_characteristics.py" ascii
        $s3 = "PService_PPD.exe" ascii nocase
        $s4 = "IEC 60870-5-104" ascii
        $s5 = "INDUSTROYER2" ascii nocase

        $ioa1 = "IOA_INLET_VALVE" ascii
        $ioa2 = "IOA_OUTLET_VALVE" ascii
        $ioa3 = "IOA_AUTO_MODE" ascii

        $cmd1 = "comsvcs.dll" ascii
        $cmd2 = "MiniDump" ascii
        $cmd3 = "wevtutil" ascii
        $cmd4 = "taskkill /F /IM" ascii

    condition:
        (2 of ($s*)) or
        (2 of ($ioa*)) or
        (2 of ($cmd*)) or
        (filesize < 10MB and any of them)
}
```

**How to Add to WildFire:**
1. WildFire → **Analysis Profiles**
2. **Custom Signatures** → **Add YARA Rule**
3. Paste rule above
4. Enable for: **All file types**

---

### YARA Rule 2: Base64 Encoded PowerShell Payload

```yara
rule Encoded_PowerShell_File_Transfer
{
    meta:
        description = "Detects base64 encoded PowerShell file transfer"
        severity = "medium"

    strings:
        $b64_1 = "FromBase64String" ascii
        $b64_2 = "ToBase64String" ascii
        $b64_3 = "[Convert]::FromBase64String" ascii

        $file_1 = "WriteAllBytes" ascii
        $file_2 = "[System.IO.File]::WriteAllBytes" ascii

        $encoded = /[A-Za-z0-9+\/]{100,}={0,2}/ ascii

    condition:
        (any of ($b64_*)) and
        (any of ($file_*)) and
        #encoded > 5
}
```

---

## IOCs to Monitor

### Malicious Domains (from Phishing Page)
```yaml
domains:
  - "malware-test-domain.com"
  - "evil-c2-server.net"
  - "phishing-kit-download.org"
  - "evil-phishing-site.com"
  - "known-malware-domain.com"

action: "Block and Alert"
category: "command-and-control"
```

**Add to URL Filtering:**
1. Firewall → **Objects → Custom Objects → URL Category**
2. Create category: **"Lab-Malicious-Domains"**
3. Add domains above
4. URL Filtering Profile → Block category

---

### Malicious IPs
```yaml
ips:
  - "192.0.2.1"        # TEST-NET-1
  - "198.51.100.1"     # TEST-NET-2
  - "203.0.113.1"      # TEST-NET-3

action: "Alert Only"  # Don't block (they're test IPs)
```

---

### File Hashes (After First Run)

After first attack run, add actual hashes:

```yaml
file_hashes:
  payload_zip:
    md5: "<calculate_after_creation>"
    sha256: "<calculate_after_creation>"

  lsass_dump:
    filename_pattern: "lsass_*.dmp"
    size: "> 1MB"

  registry_hives:
    filename_pattern: "SAM_*.hiv"
    filename_pattern: "SECURITY_*.hiv"
    filename_pattern: "SYSTEM_*.hiv"

action: "Alert and Quarantine"
```

**Calculate hashes:**
```bash
# On attacker machine
md5sum payload.zip
sha256sum payload.zip

# On Windows
Get-FileHash payload.zip -Algorithm SHA256
```

---

### Suspicious Processes to Monitor

```yaml
process_monitoring:
  - process: "rundll32.exe"
    parent_process: "cmd.exe OR powershell.exe"
    command_line_contains: "comsvcs.dll"

  - process: "reg.exe"
    command_line_contains: "save"
    command_line_contains: "HKLM"

  - process: "wevtutil.exe"
    command_line_contains: "cl"

  - process: "taskkill.exe"
    command_line_contains: "/F"
    target_process: "PService_PPD.exe"

  - process: "powershell.exe"
    command_line_contains: "-EncodedCommand"
    command_line_length: "> 1000"

  - process: "certutil.exe"
    command_line_contains: "-urlcache"
    command_line_contains: "http"
```

---

## Summary Checklist

Before running attack, configure:

### XSIAM
- [ ] Correlation Rule: "Industroyer2 Attack Chain Detection"
- [ ] Correlation Rule: "IT-to-OT Network Pivot"
- [ ] Correlation Rule: "Credential Dumping Sequence"
- [ ] Correlation Rule: "Multi-Method File Transfer"

### Cortex XDR
- [ ] BIOC: LSASS Memory Dump Detection
- [ ] BIOC: Registry Hive Dump Detection
- [ ] BIOC: Event Log Deletion
- [ ] BIOC: Critical Process Termination
- [ ] BIOC: PowerShell Encoded File Transfer
- [ ] BIOC: SMB Brute Force
- [ ] BIOC: CaddyWiper File Destruction

### Firewall
- [ ] Custom Signature: IEC-104 Malicious Commands
- [ ] Custom Signature: Reverse Shell Detection
- [ ] Custom Signature: SMB Lateral Movement
- [ ] URL Category: Lab-Malicious-Domains (block phishing domains)
- [ ] Threat Prevention Profile: Enable all custom signatures

### WildFire
- [ ] YARA Rule: Industroyer2 Payload Detection
- [ ] YARA Rule: Encoded PowerShell File Transfer
- [ ] Enable: Unknown file forwarding to WildFire

### General
- [ ] Add IOC domains to URL filtering
- [ ] Configure alert forwarding (email, Slack, etc.)
- [ ] Test each rule individually before full attack
- [ ] Verify XSIAM log ingestion is working
- [ ] Ensure Cortex XDR agent is reporting

---

## Testing Individual Rules

### Test LSASS BIOC
```bash
# On HMI (as Administrator)
python 05_credential_dumper.py --method lsass
# Should trigger: "LSASS Memory Dump via comsvcs.dll" alert
```

### Test Registry Dump BIOC
```bash
python 05_credential_dumper.py --method registry
# Should trigger: "Registry SAM/SECURITY/SYSTEM Hive Dump" alert
```

### Test Event Log Deletion BIOC
```bash
python industroyer2_characteristics.py --mode logs
# Should trigger: "Windows Event Log Deletion" alert
```

### Test Process Termination BIOC
```bash
# Start dummy process
python PService_PPD.py &

# Terminate it
python industroyer2_characteristics.py --mode terminate
# Should trigger: "SCADA Process Termination" alert
```

### Test Multi-Method Transfer
```bash
python3 06_file_transfer_all_methods.py --target 192.168.1.55 --method all --file payload.zip
# Should trigger: "Multi-Method File Transfer Detection" after 2+ methods succeed
```

---

## Expected Alert Timeline

When running full attack chain:

```
T+0min:   Router Exploit → Command Injection signature
T+1min:   Reverse Shell → Outbound C2 connection
T+5min:   Port Scan → Network reconnaissance
T+10min:  SMB Brute Force → Multiple failed auth + success
T+12min:  Lateral Movement → PsExec/WMI execution
T+15min:  LSASS Dump → Critical BIOC alert
T+16min:  Registry Dump → High BIOC alert
T+17min:  File Transfer (SMB) → Lateral movement
T+18min:  File Transfer (HTTP) → PowerShell network activity
T+19min:  File Transfer (PS) → Encoded command alert
T+20min:  File Transfer (RDP) → RDP auth + drive redirect
T+21min:  Multi-Method Transfer → Correlation alert
T+25min:  Process Termination → Critical BIOC
T+26min:  Event Log Deletion → Defense evasion BIOC
T+27min:  CaddyWiper → Mass file deletion alert
T+30min:  IEC-104 Attack → OT protocol anomaly
T+35min:  XSIAM: Full attack chain correlation alert!
```

---

## Notes

1. **Start with Alert-Only mode** for all rules during testing
2. **Adjust thresholds** based on your environment (timeframes, counts)
3. **Test each BIOC individually** before enabling all
4. **Monitor false positives** and tune accordingly
5. **Document baseline** alert counts before attack
6. **XSIAM correlation** may take 5-10 minutes to detect full chain
7. **Some alerts require time** to correlate events (be patient!)

All rules are designed to be **production-ready** but start in **monitoring mode** for testing.
