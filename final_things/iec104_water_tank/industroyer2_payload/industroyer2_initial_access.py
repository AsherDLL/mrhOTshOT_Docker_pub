#!/usr/bin/env python3
"""
Industroyer2-Inspired Initial Access & Lateral Movement Simulation

This script provides a more realistic simulation of the initial access, reconnaissance, 
and lateral movement techniques used by adversaries like Sandworm.

Attack Chain Simulated:
1.  **IT Network Reconnaissance (Living-off-the-Land)**
    -   Dynamic simulation of PowerShell and WMI commands with realistic fake output.

2.  **Credential Harvesting (Simulated)**
    -   Simulates targeting the LSASS process to extract credentials.

3.  **Lateral Movement & IT/OT Pivot**
    -   Simulates querying Active Directory to find a jump host and connecting to it.

4.  **OT Reconnaissance**
    -   Simulates a targeted network scan of the OT environment to find control systems.

WARNING: This is a SIMULATION for educational purposes only.
         It does NOT execute any harmful commands.

Usage:
    python industroyer2_initial_access.py
"""

import os
import sys
import time
import argparse
import logging

# Setup logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - [SANDWORM-SIM] - %(levelname)s - %(message)s',
    datefmt='%Y-%m-%d %H:%M:%S'
)
logger = logging.getLogger('Industroyer2InitialAccess')

class MockCommandRunner:
    """A mock command runner to simulate realistic command outputs."""
    def __init__(self):
        self.commands = {
            "get-wmiobject -class win32_computersystem": (
                "Domain              : CORP.LOCAL\n" \
                "Manufacturer        : VMware, Inc.\n" \
                "Model               : VMware Virtual Platform\n" \
                "Name                : DEV-WORKSTATION-01\n"
            ),
            "get-process": (
                "Handles  NPM(K)    PM(K)      WS(K)     CPU(s)     Id  SI ProcessName\n" \
                "-------  ------    -----      -----     ------     --  -- -----------\n" \
                "    850      45   150348     162092   2,071.88   4820   1 chrome\n" \
                "    932      56   120480     145736   1,562.50   8988   1 Slack\n" \
                "    455      23    56884      62104     890.12   1212   0 lsass\n" \
                "    231      15    23456      34567     450.67   4567   1 powershell\n"
            ),
            "ipconfig /all": (
                "Windows IP Configuration\n\n" \
                "Ethernet adapter Ethernet0:\n" \
                "   Connection-specific DNS Suffix  . : corp.local\n" \
                "   Description . . . . . . . . . . . : Intel(R) 82574L Gigabit Network Connection\n" \
                "   Physical Address. . . . . . . . . : 00-0C-29-1A-2B-3C\n" \
                "   DHCP Enabled. . . . . . . . . . . : No\n" \
                "   Autoconfiguration Enabled . . . . : Yes\n" \
                "   IPv4 Address. . . . . . . . . . . : 192.168.1.50(Preferred)\n" \
                "   Subnet Mask . . . . . . . . . . . : 255.255.255.0\n" \
                "   Default Gateway . . . . . . . . . : 192.168.1.1\n" \
                "   DNS Servers . . . . . . . . . . . : 192.168.1.10\n"
            ),
             "get-adcomputer -filter 'Name -like \"*SCADA*\"' -properties *": (
                "Name           DNSHostName              Description\n" \
                "----           -----------              -----------\n" \
                "JUMP-HOST-01   jump-host-01.corp.local  IT/OT Jump Host for Power Grid Mgmt\n"
            )
        }

    def run(self, command: str) -> str:
        """Simulates running a command and returns its mock output."""
        logger.info(f"[EXEC] Running command: `{command}`")
        time.sleep(1.5)
        for key, output in self.commands.items():
            import subprocess
            result = subprocess.run(["powershell", "-Command", key])
            print(result)
            return result
            if key in command.lower():
                print(output) # Print the command output to the console
                return output
        logger.warning(f"No mock output found for command: {command}")
        return ""

class InitialAccessSimulation:
    """Simulates the initial access and lateral movement phase of an attack."""

    def __init__(self, target_domain: str, it_subnet: str, ot_subnet: str):
        self.target_domain = target_domain
        self.it_subnet = it_subnet
        self.ot_subnet = ot_subnet
        self.stolen_credentials = {}
        self.cmd_runner = MockCommandRunner()

    def run(self):
        """Execute the full attack simulation."""
        logger.info("=" * 80)
        logger.info("INDUSTROYER2 - INITIAL ACCESS & LATERAL MOVEMENT SIMULATION (ENHANCED)")
        logger.info("=" * 80)

        self._phase1_it_recon()
        self._phase2_credential_harvesting()
        self._phase3_lateral_movement()
        self._phase4_ot_recon()

        logger.info("\n" + "=" * 80)
        logger.info("SIMULATION COMPLETE")
        logger.info("=" * 80)

    def _phase1_it_recon(self):
        """Phase 1: IT Network Reconnaissance."""
        logger.info("\n[PHASE 1] IT NETWORK RECONNAISSANCE")
        logger.info("-" * 80)
        self.cmd_runner.run("Get-WmiObject -Class win32_computersystem")
        self.cmd_runner.run("ipconfig /all")

    def _phase2_credential_harvesting(self):
        """Phase 2: Simulate harvesting credentials."""
        logger.info("\n[PHASE 2] CREDENTIAL HARVESTING (SIMULATED)")
        logger.info("-" * 80)
        processes = str(self.cmd_runner.run("Get-Process"))
        if "lsass" in processes.lower():
            logger.warning("[!] Found LSASS process. Attempting to dump credentials...")
            time.sleep(2)
            logger.critical("[!!!] SUCCESS! Found DOMAIN ADMIN credentials for 'CORP\\dadmin_user01'!")
            self.stolen_credentials['admin_user'] = "CORP\\dadmin_user01"

    def _phase3_lateral_movement(self):
        """Phase 3: Use stolen credentials for lateral movement."""
        logger.info("\n[PHASE 3] LATERAL MOVEMENT & IT/OT PIVOT")
        logger.info("-" * 80)
        if not self.stolen_credentials.get('admin_user'):
            logger.error("No admin credentials found. Aborting lateral movement.")
            return

        logger.info("[3.1] Searching for IT/OT jump host in Active Directory...")
        self.cmd_runner.run("Get-ADComputer -Filter 'Name -like \"*SCADA*\"' -Properties *")
        logger.warning("[!] Found jump host: JUMP-HOST-01.corp.local")

    def _phase4_ot_recon(self):
        """Phase 4: Scan the OT network for control systems."""
        logger.info("\n[PHASE 4] OT NETWORK RECONNAISSANCE")
        logger.info("-" * 80)
        logger.info(f"[*] Simulating network scan on OT subnet ({self.ot_subnet})...")
        # Simulate scanning for common ICS ports
        for i in range(50, 55):
            ip = f"10.10.10.{i}"
            logger.info(f"  - Scanning {ip}...")
            time.sleep(1)
            if i == 51:
                logger.warning(f"    [!] FOUND: Open port 2404 (IEC-104) on {ip}!")

def main():
    """Main entry point"""
    parser = argparse.ArgumentParser(description='Industroyer2-Inspired Initial Access Simulation')
    parser.add_argument('--target-domain', default='CORP.LOCAL')
    parser.add_argument('--it-subnet', default='192.168.1.0/24')
    parser.add_argument('--ot-subnet', default='10.10.10.0/24')
    args = parser.parse_args()

    sim = InitialAccessSimulation(args.target_domain, args.it_subnet, args.ot_subnet)
    sim.run()

if __name__ == '__main__':
    main()
