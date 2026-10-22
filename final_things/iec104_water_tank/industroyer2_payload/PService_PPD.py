#!/usr/bin/env python3
"""
PService_PPD.exe Simulation
Simulates the PowerSystemDistributed SCADA monitoring process that was
terminated by the real Industroyer2 malware

This dummy process:
- Displays a system tray icon (on Windows)
- Shows periodic status messages
- Logs activity to file
- Can be terminated by the Industroyer2 characteristics simulator

Real PService_PPD.exe:
- Was part of SCADA monitoring software in Ukrainian power grid
- Monitored IEC-104 RTU communication
- Industroyer2 terminated it before attacking

Usage:
    python PService_PPD.py

To build as Windows executable:
    pyinstaller --onefile --windowed --icon=icon.ico --name PService_PPD PService_PPD.py
"""

import sys
import time
import logging
from datetime import datetime
from pathlib import Path

# Try to import Windows-specific modules
try:
    import tkinter as tk
    from tkinter import messagebox
    GUI_AVAILABLE = True
except ImportError:
    GUI_AVAILABLE = False

# Setup logging
log_file = Path("PService_PPD.log")
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - [PService_PPD] - %(levelname)s - %(message)s',
    datefmt='%Y-%m-%d %H:%M:%S',
    handlers=[
        logging.FileHandler(log_file),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger('PService_PPD')


class SCADAMonitoringService:
    """
    Simulates a SCADA monitoring service
    This dummy process runs in the background to be terminated by Industroyer2 simulation
    """

    def __init__(self):
        self.running = True
        self.start_time = datetime.now()
        self.check_count = 0

    def run_console_mode(self):
        """Run in console mode (no GUI)"""
        logger.info("=" * 60)
        logger.info("PowerSystemDistributed Monitoring Service")
        logger.info("Version 3.2.1 - Build 4892")
        logger.info("=" * 60)
        logger.info(f"Started at: {self.start_time.strftime('%Y-%m-%d %H:%M:%S')}")
        logger.info("Monitoring IEC-104 RTU connections...")
        logger.info("=" * 60)

        try:
            while self.running:
                self.check_count += 1
                uptime = (datetime.now() - self.start_time).total_seconds()

                logger.info(f"[Check #{self.check_count}] Uptime: {uptime:.0f}s | RTU Status: CONNECTED | Data Flow: NORMAL")

                # Simulate monitoring activity
                time.sleep(10)  # Check every 10 seconds

        except KeyboardInterrupt:
            logger.info("\n[!] Service interrupted by user")
            self.shutdown()

    def run_gui_mode(self):
        """Run with GUI (Windows)"""
        root = tk.Tk()
        root.title("PService_PPD - SCADA Monitoring")
        root.geometry("600x400")
        root.resizable(False, False)

        # Create main frame
        main_frame = tk.Frame(root, bg="#2c3e50")
        main_frame.pack(fill=tk.BOTH, expand=True)

        # Title
        title_label = tk.Label(
            main_frame,
            text="PowerSystemDistributed Monitoring Service",
            font=("Arial", 16, "bold"),
            bg="#2c3e50",
            fg="white"
        )
        title_label.pack(pady=20)

        # Version info
        version_label = tk.Label(
            main_frame,
            text="Version 3.2.1 - Build 4892",
            font=("Arial", 10),
            bg="#2c3e50",
            fg="#95a5a6"
        )
        version_label.pack()

        # Status frame
        status_frame = tk.LabelFrame(
            main_frame,
            text="System Status",
            font=("Arial", 12, "bold"),
            bg="#34495e",
            fg="white",
            bd=2,
            relief=tk.GROOVE
        )
        status_frame.pack(fill=tk.BOTH, expand=True, padx=20, pady=20)

        # Status indicators
        indicators = [
            ("RTU Connection:", "CONNECTED", "#27ae60"),
            ("Data Flow:", "NORMAL", "#27ae60"),
            ("IEC-104 Protocol:", "ACTIVE", "#27ae60"),
            ("Alarm Status:", "NO ALARMS", "#27ae60"),
        ]

        for i, (label_text, value_text, color) in enumerate(indicators):
            label = tk.Label(
                status_frame,
                text=label_text,
                font=("Arial", 11),
                bg="#34495e",
                fg="white",
                anchor=tk.W
            )
            label.grid(row=i, column=0, sticky=tk.W, padx=20, pady=10)

            value = tk.Label(
                status_frame,
                text=value_text,
                font=("Arial", 11, "bold"),
                bg="#34495e",
                fg=color,
                anchor=tk.E
            )
            value.grid(row=i, column=1, sticky=tk.E, padx=20, pady=10)

        # Uptime
        self.uptime_label = tk.Label(
            main_frame,
            text=f"Uptime: 0 seconds",
            font=("Arial", 10),
            bg="#2c3e50",
            fg="#95a5a6"
        )
        self.uptime_label.pack(pady=10)

        # Start button
        stop_button = tk.Button(
            main_frame,
            text="Stop Service",
            font=("Arial", 11, "bold"),
            bg="#e74c3c",
            fg="white",
            command=lambda: self.shutdown_gui(root)
        )
        stop_button.pack(pady=10)

        # Update uptime periodically
        def update_uptime():
            if self.running:
                uptime = (datetime.now() - self.start_time).total_seconds()
                self.uptime_label.config(text=f"Uptime: {uptime:.0f} seconds")
                root.after(1000, update_uptime)

        update_uptime()

        # Handle window close
        def on_closing():
            self.shutdown_gui(root)

        root.protocol("WM_DELETE_WINDOW", on_closing)

        logger.info("GUI mode started")
        root.mainloop()

    def shutdown_gui(self, root):
        """Shutdown GUI gracefully"""
        if messagebox.askokcancel("Quit", "Stop SCADA monitoring service?"):
            logger.info("Service stopped by user")
            self.running = False
            root.destroy()

    def shutdown(self):
        """Shutdown the service"""
        logger.info("=" * 60)
        logger.info("Service shutting down...")
        uptime = (datetime.now() - self.start_time).total_seconds()
        logger.info(f"Total uptime: {uptime:.0f} seconds")
        logger.info(f"Total checks: {self.check_count}")
        logger.info("=" * 60)


def main():
    """Main entry point"""
    print("""
    ╔══════════════════════════════════════════════════════════════╗
    ║     PowerSystemDistributed Monitoring Service v3.2.1        ║
    ╚══════════════════════════════════════════════════════════════╝

    This is a DUMMY process for Industroyer2 simulation testing.

    Real PService_PPD.exe was:
    - SCADA monitoring software used in Ukrainian power grid
    - Terminated by Industroyer2 malware before IEC-104 attack
    - Part of the attack chain to blind operators

    This simulation:
    - Runs as background process (like real SCADA service)
    - Can be terminated by industroyer2_characteristics.py
    - Generates process termination alerts in Cortex XDR

    Press Ctrl+C to stop
    """)

    service = SCADAMonitoringService()

    if GUI_AVAILABLE and "--console" not in sys.argv:
        try:
            service.run_gui_mode()
        except Exception as e:
            logger.error(f"GUI mode failed: {e}")
            logger.info("Falling back to console mode")
            service.run_console_mode()
    else:
        service.run_console_mode()


if __name__ == '__main__':
    main()
