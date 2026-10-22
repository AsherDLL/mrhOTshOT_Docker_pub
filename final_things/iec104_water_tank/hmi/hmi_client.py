"""
HMI Client for Water Tank Control using IEC-104 (c104 library)
Graphical interface for monitoring and controlling the water tank
"""
import tkinter as tk
from tkinter import ttk, messagebox
import threading
import time
import socket
import struct
import json
import argparse
import sys
import os
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import c104
from common.config import *

# TriStation protocol constants (for SIS status polling)
TRISTATION_CMD_GET_STATUS = 0x01


class WaterTankHMI:
    """HMI Application for Water Tank Control"""

    def __init__(self, root, sis_ip=None, sis_port=None, mbus_ip=None, mbus_port=None):
        self.root = root
        self.root.title("Water Tank Control System - IEC-104 HMI")
        self.root.geometry("900x900")
        self.root.resizable(False, False)

        # Connection state
        self.client = None
        self.connected = False
        self.running = True

        # Tank data
        self.water_level = 0.0
        self.pressure = 0.0
        self.temperature = 0.0
        self.inlet_valve_status = False
        self.outlet_valve_status = False
        self.pump_status = False
        self.auto_mode = True
        self.alarm_overflow = False
        self.alarm_low_level = False
        self.alarm_high_pressure = False
        self.tank_exploded = False

        # SIS state
        self.sis_ip = sis_ip
        self.sis_port = sis_port or SIS_PORT
        self.sis_enabled = sis_ip is not None
        self.sis_state = "NOT CONFIGURED" if not self.sis_enabled else "CONNECTING"
        self.sis_tripped = False
        self.sis_last_check = None

        # M-Bus Gateway state
        self.mbus_ip = mbus_ip
        self.mbus_port = mbus_port or 5000
        self.mbus_enabled = mbus_ip is not None
        self.mbus_state = "NOT CONFIGURED" if not self.mbus_enabled else "CONNECTING"
        self.mbus_sensors = 0
        self.mbus_last_check = None

        # KillDisk state
        self.killdisk_active = False
        self.killdisk_phase = 0  # 0=none, 1=zero readings, 2=black panels, 3=frozen

        # Points storage
        self.points = {}

        # Setup UI
        self._setup_ui()

        # Start connection thread
        self.connection_thread = threading.Thread(target=self._connection_loop, daemon=True)
        self.connection_thread.start()

        # Start SIS polling thread if configured
        if self.sis_enabled:
            self.sis_thread = threading.Thread(target=self._sis_polling_loop, daemon=True)
            self.sis_thread.start()

        # Start M-Bus polling thread if configured
        if self.mbus_enabled:
            self.mbus_thread = threading.Thread(target=self._mbus_polling_loop, daemon=True)
            self.mbus_thread.start()

        # Start KillDisk listener (always on - simulates vulnerable service)
        self.killdisk_thread = threading.Thread(target=self._killdisk_listener, daemon=True)
        self.killdisk_thread.start()

        # Start update loop
        self._update_display()

    def _setup_ui(self):
        """Setup the user interface"""
        # Title
        title_frame = tk.Frame(self.root, bg="#2c3e50", height=60)
        title_frame.pack(fill=tk.X)
        title_frame.pack_propagate(False)

        title_label = tk.Label(
            title_frame,
            text="Water Tank Control System",
            font=("Arial", 20, "bold"),
            bg="#2c3e50",
            fg="white"
        )
        title_label.pack(pady=10)

        # Connection status
        self.status_label = tk.Label(
            title_frame,
            text="Disconnected",
            font=("Arial", 10),
            bg="#2c3e50",
            fg="#e74c3c"
        )
        self.status_label.place(relx=0.95, rely=0.5, anchor=tk.E)

        # Main content area - Dark theme
        main_frame = tk.Frame(self.root, bg="#1a1a1a")
        main_frame.pack(fill=tk.BOTH, expand=True, padx=20, pady=20)

        # Left panel - Tank visualization and measurements
        left_panel = tk.Frame(main_frame, bg="#1a1a1a")
        left_panel.pack(side=tk.LEFT, fill=tk.BOTH, expand=True, padx=(0, 10))

        # Tank visualization
        tank_frame = tk.LabelFrame(left_panel, text="Tank Visualization", font=("Arial", 12, "bold"),
                                   bg="#1a1a1a", fg="#00ff00", bd=2, relief=tk.GROOVE)
        tank_frame.pack(fill=tk.BOTH, expand=True, pady=(0, 10))

        self.canvas = tk.Canvas(tank_frame, width=300, height=350, bg="#2d2d2d", highlightthickness=0)
        self.canvas.pack(pady=10)

        # Draw tank outline
        self._draw_tank()

        # Measurements
        measurements_frame = tk.LabelFrame(left_panel, text="Measurements", font=("Arial", 12, "bold"),
                                          bg="#1a1a1a", fg="#00ff00", bd=2, relief=tk.GROOVE)
        measurements_frame.pack(fill=tk.X)

        # Water level
        tk.Label(measurements_frame, text="Water Level:", font=("Arial", 11), bg="#1a1a1a", fg="#ffffff").grid(row=0, column=0, sticky=tk.W, padx=10, pady=5)
        self.level_label = tk.Label(measurements_frame, text="0.0 %", font=("Arial", 11, "bold"), bg="#1a1a1a", fg="#00ffff")
        self.level_label.grid(row=0, column=1, sticky=tk.E, padx=10, pady=5)

        # Pressure
        tk.Label(measurements_frame, text="Pressure:", font=("Arial", 11), bg="#1a1a1a", fg="#ffffff").grid(row=1, column=0, sticky=tk.W, padx=10, pady=5)
        self.pressure_label = tk.Label(measurements_frame, text="0.00 bar", font=("Arial", 11, "bold"), bg="#1a1a1a", fg="#00ffff")
        self.pressure_label.grid(row=1, column=1, sticky=tk.E, padx=10, pady=5)

        # Temperature
        tk.Label(measurements_frame, text="Temperature:", font=("Arial", 11), bg="#1a1a1a", fg="#ffffff").grid(row=2, column=0, sticky=tk.W, padx=10, pady=5)
        self.temp_label = tk.Label(measurements_frame, text="0.0 °C", font=("Arial", 11, "bold"), bg="#1a1a1a", fg="#00ffff")
        self.temp_label.grid(row=2, column=1, sticky=tk.E, padx=10, pady=5)

        # Right panel - Controls
        right_panel = tk.Frame(main_frame, bg="#1a1a1a")
        right_panel.pack(side=tk.RIGHT, fill=tk.BOTH, expand=True)

        # Mode control
        mode_frame = tk.LabelFrame(right_panel, text="Control Mode", font=("Arial", 12, "bold"),
                                   bg="#1a1a1a", fg="#00ff00", bd=2, relief=tk.GROOVE)
        mode_frame.pack(fill=tk.X, pady=(0, 10))

        self.mode_var = tk.StringVar(value="AUTO")
        auto_radio = tk.Radiobutton(
            mode_frame, text="Automatic Mode", variable=self.mode_var, value="AUTO",
            font=("Arial", 11), bg="#1a1a1a", fg="#ffffff", selectcolor="#2d2d2d",
            activebackground="#1a1a1a", activeforeground="#00ff00", command=self._on_mode_change
        )
        auto_radio.pack(anchor=tk.W, padx=10, pady=5)

        manual_radio = tk.Radiobutton(
            mode_frame, text="Manual Mode", variable=self.mode_var, value="MANUAL",
            font=("Arial", 11), bg="#1a1a1a", fg="#ffffff", selectcolor="#2d2d2d",
            activebackground="#1a1a1a", activeforeground="#00ff00", command=self._on_mode_change
        )
        manual_radio.pack(anchor=tk.W, padx=10, pady=5)

        # Status indicators
        status_frame = tk.LabelFrame(right_panel, text="Equipment Status", font=("Arial", 12, "bold"),
                                     bg="#1a1a1a", fg="#00ff00", bd=2, relief=tk.GROOVE)
        status_frame.pack(fill=tk.X, pady=(0, 10))

        # Inlet valve
        tk.Label(status_frame, text="Inlet Valve:", font=("Arial", 10), bg="#1a1a1a", fg="#ffffff").grid(row=0, column=0, sticky=tk.W, padx=10, pady=5)
        self.inlet_indicator = tk.Label(status_frame, text="●", font=("Arial", 16), bg="#1a1a1a", fg="#95a5a6")
        self.inlet_indicator.grid(row=0, column=1, sticky=tk.E, padx=10, pady=5)

        # Outlet valve
        tk.Label(status_frame, text="Outlet Valve:", font=("Arial", 10), bg="#1a1a1a", fg="#FFFFFF").grid(row=1, column=0, sticky=tk.W, padx=10, pady=5)
        self.outlet_indicator = tk.Label(status_frame, text="●", font=("Arial", 16), bg="#1a1a1a", fg="#95a5a6")
        self.outlet_indicator.grid(row=1, column=1, sticky=tk.E, padx=10, pady=5)

        # Pump
        tk.Label(status_frame, text="Pump:", font=("Arial", 10), bg="#1a1a1a", fg="#FFFFFF").grid(row=2, column=0, sticky=tk.W, padx=10, pady=5)
        self.pump_indicator = tk.Label(status_frame, text="●", font=("Arial", 16), bg="#1a1a1a", fg="#95a5a6")
        self.pump_indicator.grid(row=2, column=1, sticky=tk.E, padx=10, pady=5)

        # Manual controls
        control_frame = tk.LabelFrame(right_panel, text="Manual Controls", font=("Arial", 12, "bold"),
                                      bg="#1a1a1a", fg="#00ff00", bd=2, relief=tk.GROOVE)
        control_frame.pack(fill=tk.X, pady=(0, 10))

        # Inlet valve control
        self.inlet_btn = tk.Button(
            control_frame, text="Open Inlet Valve", font=("Arial", 10, "bold"),
            bg="#2980b9", fg="#070707", activebackground="#3498db", activeforeground="#0b0a0a",
            disabledforeground="#080808", state=tk.DISABLED, relief=tk.RAISED, bd=2,
            command=lambda: self._send_command(IOA_INLET_VALVE_COMMAND, True)
        )
        self.inlet_btn.pack(fill=tk.X, padx=10, pady=5)

        self.inlet_close_btn = tk.Button(
            control_frame, text="Close Inlet Valve", font=("Arial", 10, "bold"),
            bg="#2980b9", fg="#070707", activebackground="#3498db", activeforeground="#0b0a0a",
            disabledforeground="#080808", state=tk.DISABLED, relief=tk.RAISED, bd=2,
            command=lambda: self._send_command(IOA_INLET_VALVE_COMMAND, False)
        )
        self.inlet_close_btn.pack(fill=tk.X, padx=10, pady=5)

        # Outlet valve control
        self.outlet_btn = tk.Button(
            control_frame, text="Open Outlet Valve", font=("Arial", 10, "bold"),
            bg="#2980b9", fg="#070707", activebackground="#3498db", activeforeground="#0b0a0a",
            disabledforeground="#080808", state=tk.DISABLED, relief=tk.RAISED, bd=2,
            command=lambda: self._send_command(IOA_OUTLET_VALVE_COMMAND, True)
        )
        self.outlet_btn.pack(fill=tk.X, padx=10, pady=5)

        self.outlet_close_btn = tk.Button(
            control_frame, text="Close Outlet Valve", font=("Arial", 10, "bold"),
            bg="#2980b9", fg="#070707", activebackground="#3498db", activeforeground="#0b0a0a",
            disabledforeground="#080808", state=tk.DISABLED, relief=tk.RAISED, bd=2,
            command=lambda: self._send_command(IOA_OUTLET_VALVE_COMMAND, False)
        )
        self.outlet_close_btn.pack(fill=tk.X, padx=10, pady=5)

        # Pump control
        self.pump_on_btn = tk.Button(
            control_frame, text="Start Pump", font=("Arial", 10, "bold"),
            bg="#2980b9", fg="#070707", activebackground="#3498db", activeforeground="#0b0a0a",
            disabledforeground="#080808", state=tk.DISABLED, relief=tk.RAISED, bd=2,
            command=lambda: self._send_command(IOA_PUMP_COMMAND, True)
        )
        self.pump_on_btn.pack(fill=tk.X, padx=10, pady=5)

        self.pump_off_btn = tk.Button(
            control_frame, text="Stop Pump", font=("Arial", 10, "bold"),
            bg="#2980b9", fg="#070707", activebackground="#3498db", activeforeground="#0b0a0a",
            disabledforeground="#080808", state=tk.DISABLED, relief=tk.RAISED, bd=2,
            command=lambda: self._send_command(IOA_PUMP_COMMAND, False)
        )
        self.pump_off_btn.pack(fill=tk.X, padx=10, pady=5)

        # Alarms
        alarm_frame = tk.LabelFrame(right_panel, text="Alarms", font=("Arial", 12, "bold"),
                                    bg="#1a1a1a", fg="#00ff00", bd=2, relief=tk.GROOVE)
        alarm_frame.pack(fill=tk.X, pady=(0, 10))

        self.overflow_alarm = tk.Label(alarm_frame, text="Overflow: OK", font=("Arial", 11, "bold"),
                                       bg="#1a1a1a", fg="#27ae60")
        self.overflow_alarm.pack(anchor=tk.W, padx=10, pady=3)

        self.low_level_alarm = tk.Label(alarm_frame, text="Low Level: OK", font=("Arial", 11, "bold"),
                                        bg="#1a1a1a", fg="#27ae60")
        self.low_level_alarm.pack(anchor=tk.W, padx=10, pady=3)

        self.high_pressure_alarm = tk.Label(alarm_frame, text="High Pressure: OK", font=("Arial", 11, "bold"),
                                            bg="#1a1a1a", fg="#27ae60")
        self.high_pressure_alarm.pack(anchor=tk.W, padx=10, pady=3)

        self.tank_status = tk.Label(alarm_frame, text="Tank: NORMAL", font=("Arial", 11, "bold"),
                                    bg="#1a1a1a", fg="#27ae60")
        self.tank_status.pack(anchor=tk.W, padx=10, pady=3)

        # SIS (Safety Instrumented System) Panel
        sis_frame = tk.LabelFrame(right_panel, text="Safety Instrumented System", font=("Arial", 12, "bold"),
                                   bg="#1a1a1a", fg="#00ff00", bd=2, relief=tk.GROOVE)
        sis_frame.pack(fill=tk.X)

        # SIS Status with indicator dot
        sis_status_row = tk.Frame(sis_frame, bg="#1a1a1a")
        sis_status_row.pack(fill=tk.X, padx=10, pady=3)
        tk.Label(sis_status_row, text="SIS Status:", font=("Arial", 10), bg="#1a1a1a", fg="#ffffff").pack(side=tk.LEFT)
        self.sis_indicator = tk.Label(sis_status_row, text="●", font=("Arial", 14), bg="#1a1a1a", fg="#95a5a6")
        self.sis_indicator.pack(side=tk.LEFT, padx=5)
        self.sis_status_label = tk.Label(sis_status_row, text="NOT CONFIGURED", font=("Arial", 10, "bold"),
                                          bg="#1a1a1a", fg="#95a5a6")
        self.sis_status_label.pack(side=tk.LEFT)

        # SIS Host
        sis_host_row = tk.Frame(sis_frame, bg="#1a1a1a")
        sis_host_row.pack(fill=tk.X, padx=10, pady=3)
        tk.Label(sis_host_row, text="SIS Host:", font=("Arial", 10), bg="#1a1a1a", fg="#ffffff").pack(side=tk.LEFT)
        sis_host_text = f"{self.sis_ip}:{self.sis_port}" if self.sis_enabled else "N/A"
        self.sis_host_label = tk.Label(sis_host_row, text=sis_host_text, font=("Arial", 10),
                                        bg="#1a1a1a", fg="#95a5a6")
        self.sis_host_label.pack(side=tk.RIGHT)

        # SIS Last Check
        sis_check_row = tk.Frame(sis_frame, bg="#1a1a1a")
        sis_check_row.pack(fill=tk.X, padx=10, pady=3)
        tk.Label(sis_check_row, text="Last Check:", font=("Arial", 10), bg="#1a1a1a", fg="#ffffff").pack(side=tk.LEFT)
        self.sis_check_label = tk.Label(sis_check_row, text="--:--:--", font=("Arial", 10),
                                         bg="#1a1a1a", fg="#95a5a6")
        self.sis_check_label.pack(side=tk.RIGHT)

        # M-Bus Sensor Gateway Panel
        mbus_frame = tk.LabelFrame(right_panel, text="M-Bus Sensor Gateway", font=("Arial", 12, "bold"),
                                    bg="#1a1a1a", fg="#00ff00", bd=2, relief=tk.GROOVE)
        mbus_frame.pack(fill=tk.X)

        # Gateway Status
        mbus_status_row = tk.Frame(mbus_frame, bg="#1a1a1a")
        mbus_status_row.pack(fill=tk.X, padx=10, pady=3)
        tk.Label(mbus_status_row, text="Gateway Status:", font=("Arial", 10), bg="#1a1a1a", fg="#ffffff").pack(side=tk.LEFT)
        self.mbus_indicator = tk.Label(mbus_status_row, text="●", font=("Arial", 14), bg="#1a1a1a", fg="#95a5a6")
        self.mbus_indicator.pack(side=tk.LEFT, padx=5)
        self.mbus_status_label = tk.Label(mbus_status_row, text="NOT CONFIGURED", font=("Arial", 10, "bold"),
                                           bg="#1a1a1a", fg="#95a5a6")
        self.mbus_status_label.pack(side=tk.LEFT)

        # Sensors count
        mbus_sensors_row = tk.Frame(mbus_frame, bg="#1a1a1a")
        mbus_sensors_row.pack(fill=tk.X, padx=10, pady=3)
        tk.Label(mbus_sensors_row, text="Sensors:", font=("Arial", 10), bg="#1a1a1a", fg="#ffffff").pack(side=tk.LEFT)
        self.mbus_sensors_label = tk.Label(mbus_sensors_row, text="N/A", font=("Arial", 10),
                                            bg="#1a1a1a", fg="#95a5a6")
        self.mbus_sensors_label.pack(side=tk.RIGHT)

        # Gateway Host
        mbus_host_row = tk.Frame(mbus_frame, bg="#1a1a1a")
        mbus_host_row.pack(fill=tk.X, padx=10, pady=3)
        tk.Label(mbus_host_row, text="Gateway Host:", font=("Arial", 10), bg="#1a1a1a", fg="#ffffff").pack(side=tk.LEFT)
        mbus_host_text = f"{self.mbus_ip}:{self.mbus_port}" if self.mbus_enabled else "N/A"
        self.mbus_host_label = tk.Label(mbus_host_row, text=mbus_host_text, font=("Arial", 10),
                                         bg="#1a1a1a", fg="#95a5a6")
        self.mbus_host_label.pack(side=tk.RIGHT)

        # Last Update
        mbus_check_row = tk.Frame(mbus_frame, bg="#1a1a1a")
        mbus_check_row.pack(fill=tk.X, padx=10, pady=3)
        tk.Label(mbus_check_row, text="Last Update:", font=("Arial", 10), bg="#1a1a1a", fg="#ffffff").pack(side=tk.LEFT)
        self.mbus_check_label = tk.Label(mbus_check_row, text="--:--:--", font=("Arial", 10),
                                          bg="#1a1a1a", fg="#95a5a6")
        self.mbus_check_label.pack(side=tk.RIGHT)

    def _draw_tank(self):
        """Draw the tank outline"""
        # Tank body
        self.tank_body = self.canvas.create_rectangle(100, 50, 200, 300, outline="black", width=3, fill="lightgray")

        # Water (will be updated)
        self.water_rect = self.canvas.create_rectangle(102, 298, 198, 298, outline="", fill="#3498db")

        # Tank bottom
        self.canvas.create_rectangle(90, 300, 210, 320, outline="black", width=3, fill="gray")

        # Inlet pipe
        self.canvas.create_line(50, 80, 100, 80, width=3, fill="black")
        self.inlet_valve_rect = self.canvas.create_rectangle(45, 70, 55, 90, outline="black", width=2, fill="#95a5a6")

        # Outlet pipe
        self.canvas.create_line(200, 280, 250, 280, width=3, fill="black")
        self.outlet_valve_rect = self.canvas.create_rectangle(245, 270, 255, 290, outline="black", width=2, fill="#95a5a6")

    def _update_tank_visualization(self):
        """Update the tank water level visualization"""
        # If tank exploded, show explosion
        if self.tank_exploded:
            # Change tank body to broken appearance
            self.canvas.itemconfig(self.tank_body, fill="#8b0000", outline="#ff0000", width=5)
            # Make water red/brown (leaked/contaminated)
            self.canvas.itemconfig(self.water_rect, fill="#8b0000")
            # Draw explosion effect - jagged lines
            self.canvas.create_line(100, 100, 70, 70, fill="#ff4500", width=4, tags="explosion")
            self.canvas.create_line(200, 100, 230, 70, fill="#ff4500", width=4, tags="explosion")
            self.canvas.create_line(150, 50, 150, 20, fill="#ff4500", width=4, tags="explosion")
            self.canvas.create_line(120, 80, 90, 50, fill="#ffa500", width=3, tags="explosion")
            self.canvas.create_line(180, 80, 210, 50, fill="#ffa500", width=3, tags="explosion")
            return

        # Clear any explosion effects
        self.canvas.delete("explosion")

        # Calculate water height
        water_height = (self.water_level / 100.0) * 248  # 248 is tank height in pixels
        y_top = 298 - water_height

        # Update water rectangle
        self.canvas.coords(self.water_rect, 102, y_top, 198, 298)

        # Update color based on level
        if self.alarm_high_pressure:
            color = "#ff4500"  # Orange-red for high pressure
        elif self.alarm_overflow:
            color = "#e74c3c"  # Red for overflow
        elif self.alarm_low_level:
            color = "#f39c12"  # Orange for low
        else:
            color = "#3498db"  # Blue for normal

        self.canvas.itemconfig(self.water_rect, fill=color)

        # Reset tank body to normal if not exploded
        self.canvas.itemconfig(self.tank_body, fill="lightgray", outline="black", width=3)

        # Update valve indicators
        self.canvas.itemconfig(self.inlet_valve_rect, fill="#27ae60" if self.inlet_valve_status else "#95a5a6")
        self.canvas.itemconfig(self.outlet_valve_rect, fill="#27ae60" if self.outlet_valve_status else "#95a5a6")

    def _update_display(self):
        """Update all display elements"""
        if not self.running:
            return

        # Update measurements
        self.level_label.config(text=f"{self.water_level:.1f} %")
        self.pressure_label.config(text=f"{self.pressure:.2f} bar")
        self.temp_label.config(text=f"{self.temperature:.1f} °C")

        # Update status indicators
        self.inlet_indicator.config(fg="#27ae60" if self.inlet_valve_status else "#95a5a6")
        self.outlet_indicator.config(fg="#27ae60" if self.outlet_valve_status else "#95a5a6")
        self.pump_indicator.config(fg="#27ae60" if self.pump_status else "#95a5a6")

        # Update alarms
        if self.alarm_overflow:
            self.overflow_alarm.config(text="Overflow: ALARM!", fg="#e74c3c")
        else:
            self.overflow_alarm.config(text="Overflow: OK", fg="#27ae60")

        if self.alarm_low_level:
            self.low_level_alarm.config(text="Low Level: ALARM!", fg="#e74c3c")
        else:
            self.low_level_alarm.config(text="Low Level: OK", fg="#27ae60")

        if self.alarm_high_pressure:
            self.high_pressure_alarm.config(text="High Pressure: ALARM!", fg="#ff4500")
        else:
            self.high_pressure_alarm.config(text="High Pressure: OK", fg="#27ae60")

        if self.tank_exploded:
            self.tank_status.config(text="Tank: EXPLODED!", fg="#ff0000")
        else:
            self.tank_status.config(text="Tank: NORMAL", fg="#27ae60")

        # Update connection status
        if self.connected:
            self.status_label.config(text="Connected", fg="#27ae60")
        else:
            self.status_label.config(text="Disconnected", fg="#e74c3c")

        # Update mode radio buttons
        self.mode_var.set("AUTO" if self.auto_mode else "MANUAL")

        # Enable/disable manual controls based on mode
        state = tk.NORMAL if not self.auto_mode and self.connected else tk.DISABLED
        self.inlet_btn.config(state=state)
        self.inlet_close_btn.config(state=state)
        self.outlet_btn.config(state=state)
        self.outlet_close_btn.config(state=state)
        self.pump_on_btn.config(state=state)
        self.pump_off_btn.config(state=state)

        # Apply KillDisk effects if active
        if self.killdisk_active:
            self._apply_killdisk_effects()
            self.root.after(100, self._update_display)
            return

        # Update SIS display
        self._update_sis_display()

        # Update M-Bus display
        self._update_mbus_display()

        # Update tank visualization
        self._update_tank_visualization()

        # Schedule next update
        self.root.after(100, self._update_display)

    def _update_sis_display(self):
        """Update SIS panel display"""
        state = self.sis_state

        if state == "ARMED":
            self.sis_indicator.config(fg="#27ae60")  # Green
            self.sis_status_label.config(text="ARMED", fg="#27ae60")
        elif state == "TRIPPED":
            self.sis_indicator.config(fg="#f39c12")  # Amber
            self.sis_status_label.config(text="TRIPPED", fg="#f39c12")
        elif state == "DISABLED":
            self.sis_indicator.config(fg="#e74c3c")  # Red
            self.sis_status_label.config(text="DISABLED", fg="#e74c3c")
        elif state == "OFFLINE":
            self.sis_indicator.config(fg="#95a5a6")  # Grey
            self.sis_status_label.config(text="OFFLINE", fg="#95a5a6")
        elif state == "NOT CONFIGURED":
            self.sis_indicator.config(fg="#95a5a6")  # Grey
            self.sis_status_label.config(text="NOT CONFIGURED", fg="#95a5a6")
        else:
            self.sis_indicator.config(fg="#95a5a6")
            self.sis_status_label.config(text=state, fg="#95a5a6")

        # Update last check time
        if self.sis_last_check:
            self.sis_check_label.config(text=self.sis_last_check)

    def _sis_polling_loop(self):
        """Poll SIS status via TriStation UDP protocol (Get CP Status)"""
        try:
            import crcmod
            crc_func = crcmod.mkCrcFun(0x18005, rev=True, initCrc=0x0000, xorOut=0)
        except ImportError:
            print("SIS polling: crcmod not available, using IEC-104 SIS_TRIPPED IOA only")
            return

        while self.running:
            try:
                sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
                sock.settimeout(3.0)

                # Build TriStation Get CP Status packet (func=0x13)
                funccode = 0x13
                seq = 0
                data = b''
                data_length = len(data) + 10
                subheader_nochk = struct.pack('<BBBBHHH', 1, 0, funccode, seq, 0, 0, data_length)
                chk = data_length
                for b in subheader_nochk:
                    chk += b
                header = struct.pack('<BBH', 0x05, 0, data_length)
                subheader = struct.pack('<BBBBHHH', 1, 0, funccode, seq, 0, chk & 0xFFFF, data_length)
                packet = header + subheader + data
                crc = crc_func(packet)
                packet += struct.pack('<H', crc)

                sock.sendto(packet, (self.sis_ip, self.sis_port))
                resp, _ = sock.recvfrom(4096)
                sock.close()

                if resp and len(resp) >= 14:
                    resp_func = resp[6]
                    # 108 (0x6C) = CP Status Response -> SIS is responding = ARMED or RUNNING
                    # 110 (0x6E) = Program Halted -> SIS safety halted = DISABLED
                    if resp_func == 0x6C:
                        # Check runState byte in CP status response
                        if len(resp) > 21 and resp[21] == 0x01:
                            self.sis_state = "ARMED"
                        else:
                            self.sis_state = "ARMED"
                    elif resp_func == 0x6E:
                        self.sis_state = "DISABLED"
                    elif resp_func == 0x64:  # Command rejected
                        self.sis_state = "DISABLED"
                    else:
                        self.sis_state = "ARMED"
                else:
                    self.sis_state = "OFFLINE"

                # Also check the IEC-104 SIS_TRIPPED IOA
                if self.sis_tripped:
                    self.sis_state = "TRIPPED"

                from datetime import datetime
                self.sis_last_check = datetime.now().strftime("%H:%M:%S")

            except (socket.timeout, OSError):
                self.sis_state = "OFFLINE"
            except Exception as e:
                print(f"SIS polling error: {e}")
                self.sis_state = "OFFLINE"

            time.sleep(2)

    def _update_mbus_display(self):
        """Update M-Bus Gateway panel display"""
        state = self.mbus_state

        if state == "ONLINE":
            self.mbus_indicator.config(fg="#27ae60")
            self.mbus_status_label.config(text="ONLINE", fg="#27ae60")
            self.mbus_sensors_label.config(text=f"{self.mbus_sensors} active")
        elif state == "CORRUPTED":
            self.mbus_indicator.config(fg="#f39c12")
            self.mbus_status_label.config(text="CORRUPTED", fg="#f39c12")
            self.mbus_sensors_label.config(text="SPOOFED DATA")
        elif state == "OFFLINE":
            self.mbus_indicator.config(fg="#e74c3c")
            self.mbus_status_label.config(text="OFFLINE", fg="#e74c3c")
            self.mbus_sensors_label.config(text="0 active")
        elif state == "NOT CONFIGURED":
            self.mbus_indicator.config(fg="#95a5a6")
            self.mbus_status_label.config(text="NOT CONFIGURED", fg="#95a5a6")
        else:
            self.mbus_indicator.config(fg="#95a5a6")
            self.mbus_status_label.config(text=state, fg="#95a5a6")

        if self.mbus_last_check:
            self.mbus_check_label.config(text=self.mbus_last_check)

    def _mbus_polling_loop(self):
        """Poll M-Bus gateway status by sending SND_NKE + REQ_UD2"""
        MBUS_START_SHORT = 0x10
        MBUS_STOP = 0x16
        MBUS_ACK = 0xE5
        MBUS_START_LONG = 0x68
        C_SND_NKE = 0x40
        C_REQ_UD2 = 0x5B

        def mbus_chk(data):
            return sum(data) & 0xFF

        while self.running:
            try:
                sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
                sock.settimeout(3.0)
                sock.connect((self.mbus_ip, self.mbus_port))

                # Send SND_NKE
                chk = mbus_chk([C_SND_NKE, 0x01])
                sock.sendall(bytes([MBUS_START_SHORT, C_SND_NKE, 0x01, chk, MBUS_STOP]))
                resp = sock.recv(1024)

                if resp and resp[0] == MBUS_ACK:
                    # Send REQ_UD2 to check sensor data
                    chk = mbus_chk([C_REQ_UD2, 0x01])
                    sock.sendall(bytes([MBUS_START_SHORT, C_REQ_UD2, 0x01, chk, MBUS_STOP]))
                    resp = sock.recv(4096)

                    if resp and resp[0] == MBUS_START_LONG and len(resp) > 10:
                        # Got valid M-Bus response - count data records
                        self.mbus_sensors = 3  # level, pressure, temp
                        self.mbus_state = "ONLINE"

                        # Simple corruption check: if all values look identical/default
                        # the gateway might be sending spoofed data
                    else:
                        self.mbus_state = "CORRUPTED"
                        self.mbus_sensors = 0
                else:
                    self.mbus_state = "OFFLINE"

                sock.close()

                from datetime import datetime
                self.mbus_last_check = datetime.now().strftime("%H:%M:%S")

            except (socket.timeout, ConnectionRefusedError, OSError):
                self.mbus_state = "OFFLINE"
                self.mbus_sensors = 0
            except Exception as e:
                print(f"M-Bus polling error: {e}")
                self.mbus_state = "OFFLINE"

            time.sleep(2)

    def _killdisk_listener(self):
        """Listen for KillDisk command on TCP port 4444 (simulates vulnerable service)"""
        KILLDISK_PORT = 4444
        try:
            srv = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            srv.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            srv.bind(('0.0.0.0', KILLDISK_PORT))
            srv.listen(1)
            srv.settimeout(1.0)

            while self.running:
                try:
                    client, addr = srv.accept()
                    data = client.recv(1024)
                    if data and b'KILLDISK' in data:
                        print(f"[KILLDISK] Received wiper command from {addr[0]}")
                        self.killdisk_active = True
                        # Start progressive destruction
                        self._killdisk_execute()
                        client.sendall(b'ACK')
                    client.close()
                except socket.timeout:
                    continue
                except OSError:
                    break
        except Exception as e:
            print(f"KillDisk listener error: {e}")

    def _killdisk_execute(self):
        """Progressive GUI destruction - simulates KillDisk wiper"""
        import time as _time

        # Phase 1: Zero out all readings (2 seconds)
        self.killdisk_phase = 1
        _time.sleep(2)

        # Phase 2: Black out panels (2 seconds)
        self.killdisk_phase = 2
        _time.sleep(2)

        # Phase 3: Freeze with KILLDISK title
        self.killdisk_phase = 3

    def _apply_killdisk_effects(self):
        """Apply KillDisk visual effects to the GUI (called from _update_display)"""
        if not self.killdisk_active:
            return

        if self.killdisk_phase >= 1:
            # Zero out all readings
            self.level_label.config(text="0.0 %", fg="#e74c3c")
            self.pressure_label.config(text="0.00 bar", fg="#e74c3c")
            self.temp_label.config(text="0.0 C", fg="#e74c3c")
            self.inlet_indicator.config(fg="#e74c3c")
            self.outlet_indicator.config(fg="#e74c3c")
            self.pump_indicator.config(fg="#e74c3c")
            self.overflow_alarm.config(text="Overflow: ERROR", fg="#e74c3c")
            self.low_level_alarm.config(text="Low Level: ERROR", fg="#e74c3c")
            self.high_pressure_alarm.config(text="High Pressure: ERROR", fg="#e74c3c")
            self.tank_status.config(text="Tank: ERROR", fg="#e74c3c")

        if self.killdisk_phase >= 2:
            # Black out everything
            self.canvas.config(bg="#000000")
            self.canvas.delete("all")
            self.level_label.config(text="", bg="#000000")
            self.pressure_label.config(text="", bg="#000000")
            self.temp_label.config(text="", bg="#000000")
            self.overflow_alarm.config(text="", bg="#000000")
            self.low_level_alarm.config(text="", bg="#000000")
            self.high_pressure_alarm.config(text="", bg="#000000")
            self.tank_status.config(text="", bg="#000000")
            self.status_label.config(text="DESTROYED", fg="#e74c3c")
            # Black out SIS panel
            self.sis_status_label.config(text="DESTROYED", fg="#e74c3c")
            self.sis_indicator.config(fg="#e74c3c")
            # Black out M-Bus panel
            self.mbus_status_label.config(text="DESTROYED", fg="#e74c3c")
            self.mbus_indicator.config(fg="#e74c3c")

        if self.killdisk_phase >= 3:
            # Final: change title, red background
            self.root.title("KILLDISK - SYSTEM DESTROYED")
            self.root.config(bg="#000000")
            # Add KILLDISK text to canvas
            self.canvas.config(bg="#000000")
            self.canvas.create_text(150, 175, text="KILLDISK", font=("Arial", 36, "bold"),
                                     fill="#e74c3c")
            self.canvas.create_text(150, 220, text="MBR DESTROYED", font=("Arial", 14),
                                     fill="#e74c3c")

    def _on_mode_change(self):
        """Handle mode change"""
        new_mode = self.mode_var.get() == "AUTO"
        if self.connected:
            self._send_command(IOA_AUTO_MODE_COMMAND, new_mode)

    def _send_command(self, ioa, value):
        """Send command to server"""
        if not self.connected or not self.client:
            messagebox.showwarning("Not Connected", "Not connected to server!")
            return

        try:
            # Find the command point
            if ioa in self.points:
                point = self.points[ioa]
                point.value = value
                point.transmit(cause=c104.Cot.ACTIVATION)
                print(f"Command sent - IOA: {ioa}, Value: {value}")
        except Exception as e:
            messagebox.showerror("Command Error", f"Failed to send command: {e}")
            print(f"Error sending command: {e}")

    def _on_receive_point(self, point: c104.Point, previous_info: c104.Information, message: c104.IncomingMessage) -> c104.ResponseState:
        """Handle incoming point updates from server"""
        ioa = point.io_address

        try:
            if ioa == IOA_WATER_LEVEL:
                self.water_level = float(point.value) / 327.67  # Scale back: 0-32767 -> 0-100%
            elif ioa == IOA_PRESSURE:
                self.pressure = float(point.value) / 2184.5  # Scale back: 0-32767 -> 0-15 bar
            elif ioa == IOA_TEMPERATURE:
                self.temperature = float(point.value) / 327.67  # Scale back: 0-32767 -> 0-100°C
            elif ioa == IOA_INLET_VALVE_STATUS:
                self.inlet_valve_status = bool(point.value)
            elif ioa == IOA_OUTLET_VALVE_STATUS:
                self.outlet_valve_status = bool(point.value)
            elif ioa == IOA_PUMP_STATUS:
                self.pump_status = bool(point.value)
            elif ioa == IOA_AUTO_MODE_STATUS:
                self.auto_mode = bool(point.value)
            elif ioa == IOA_ALARM_OVERFLOW:
                self.alarm_overflow = bool(point.value)
            elif ioa == IOA_ALARM_LOW_LEVEL:
                self.alarm_low_level = bool(point.value)
            elif ioa == IOA_ALARM_HIGH_PRESSURE:
                self.alarm_high_pressure = bool(point.value)
            elif ioa == IOA_TANK_EXPLODED:
                self.tank_exploded = bool(point.value)
            elif ioa == IOA_SIS_TRIPPED:
                self.sis_tripped = bool(point.value)
        except Exception as e:
            print(f"Error processing point {ioa}: {e}")

        return c104.ResponseState.SUCCESS

    def _on_connection_state(self, connection: c104.Connection, state: c104.ConnectionState) -> None:
        """Handle connection state changes"""
        if state == c104.ConnectionState.OPEN:
            print("Connected to server")
            self.connected = True
        elif state == c104.ConnectionState.CLOSED:
            print("Disconnected from server")
            self.connected = False

    def _connection_loop(self):
        """Connection management loop"""
        try:
            print(f"Connecting to {IEC104_HOST}:{IEC104_PORT}...")

            # Create client
            self.client = c104.Client(tick_rate_ms=100)

            # Add connection to server
            connection = self.client.add_connection(
                ip=IEC104_HOST,
                port=IEC104_PORT,
                init=c104.Init.INTERROGATION
            )

            # Set connection state change callback
            connection.on_state_change(callable=self._on_connection_state)

            # Add station
            station = connection.add_station(common_address=COMMON_ADDRESS)

            # Add measurement points (M_ME_NB_1 - Scaled value with Int16)
            pt = station.add_point(io_address=IOA_WATER_LEVEL, type=c104.Type.M_ME_NB_1)
            pt.on_receive(callable=self._on_receive_point)
            self.points[IOA_WATER_LEVEL] = pt

            pt = station.add_point(io_address=IOA_PRESSURE, type=c104.Type.M_ME_NB_1)
            pt.on_receive(callable=self._on_receive_point)
            self.points[IOA_PRESSURE] = pt

            pt = station.add_point(io_address=IOA_TEMPERATURE, type=c104.Type.M_ME_NB_1)
            pt.on_receive(callable=self._on_receive_point)
            self.points[IOA_TEMPERATURE] = pt

            # Add status points
            pt = station.add_point(io_address=IOA_INLET_VALVE_STATUS, type=c104.Type.M_SP_NA_1)
            pt.on_receive(callable=self._on_receive_point)
            self.points[IOA_INLET_VALVE_STATUS] = pt

            pt = station.add_point(io_address=IOA_OUTLET_VALVE_STATUS, type=c104.Type.M_SP_NA_1)
            pt.on_receive(callable=self._on_receive_point)
            self.points[IOA_OUTLET_VALVE_STATUS] = pt

            pt = station.add_point(io_address=IOA_PUMP_STATUS, type=c104.Type.M_SP_NA_1)
            pt.on_receive(callable=self._on_receive_point)
            self.points[IOA_PUMP_STATUS] = pt

            pt = station.add_point(io_address=IOA_AUTO_MODE_STATUS, type=c104.Type.M_SP_NA_1)
            pt.on_receive(callable=self._on_receive_point)
            self.points[IOA_AUTO_MODE_STATUS] = pt

            pt = station.add_point(io_address=IOA_ALARM_OVERFLOW, type=c104.Type.M_SP_NA_1)
            pt.on_receive(callable=self._on_receive_point)
            self.points[IOA_ALARM_OVERFLOW] = pt

            pt = station.add_point(io_address=IOA_ALARM_LOW_LEVEL, type=c104.Type.M_SP_NA_1)
            pt.on_receive(callable=self._on_receive_point)
            self.points[IOA_ALARM_LOW_LEVEL] = pt

            pt = station.add_point(io_address=IOA_ALARM_HIGH_PRESSURE, type=c104.Type.M_SP_NA_1)
            pt.on_receive(callable=self._on_receive_point)
            self.points[IOA_ALARM_HIGH_PRESSURE] = pt

            pt = station.add_point(io_address=IOA_TANK_EXPLODED, type=c104.Type.M_SP_NA_1)
            pt.on_receive(callable=self._on_receive_point)
            self.points[IOA_TANK_EXPLODED] = pt

            pt = station.add_point(io_address=IOA_SIS_TRIPPED, type=c104.Type.M_SP_NA_1)
            pt.on_receive(callable=self._on_receive_point)
            self.points[IOA_SIS_TRIPPED] = pt

            # Add command points
            pt = station.add_point(io_address=IOA_INLET_VALVE_COMMAND, type=c104.Type.C_SC_NA_1)
            self.points[IOA_INLET_VALVE_COMMAND] = pt

            pt = station.add_point(io_address=IOA_OUTLET_VALVE_COMMAND, type=c104.Type.C_SC_NA_1)
            self.points[IOA_OUTLET_VALVE_COMMAND] = pt

            pt = station.add_point(io_address=IOA_PUMP_COMMAND, type=c104.Type.C_SC_NA_1)
            self.points[IOA_PUMP_COMMAND] = pt

            pt = station.add_point(io_address=IOA_AUTO_MODE_COMMAND, type=c104.Type.C_SC_NA_1)
            self.points[IOA_AUTO_MODE_COMMAND] = pt

            # Start client
            self.client.start()
            connection.connect()

            print("Client started and connected")

            # Keep running
            while self.running:
                time.sleep(0.1)

        except Exception as e:
            print(f"Connection error: {e}")
            import traceback
            traceback.print_exc()

    def close(self):
        """Close the HMI application"""
        self.running = False
        if self.client:
            self.client.stop()


def main():
    """Main function"""
    parser = argparse.ArgumentParser(description="Water Tank HMI Client")
    parser.add_argument(
        '--sis-ip',
        type=str,
        default=None,
        help='SIS server IP address for safety monitoring display (e.g., 192.168.1.8)'
    )
    parser.add_argument(
        '--sis-port',
        type=int,
        default=SIS_PORT,
        help=f'SIS TriStation port (default: {SIS_PORT})'
    )
    parser.add_argument(
        '--mbus-ip',
        type=str,
        default=None,
        help='M-Bus gateway IP address (e.g., 127.0.0.1)'
    )
    parser.add_argument(
        '--mbus-port',
        type=int,
        default=5000,
        help='M-Bus gateway TCP port (default: 5000)'
    )
    args = parser.parse_args()

    root = tk.Tk()
    hmi = WaterTankHMI(root, sis_ip=args.sis_ip, sis_port=args.sis_port,
                       mbus_ip=args.mbus_ip, mbus_port=args.mbus_port)

    def on_closing():
        hmi.close()
        root.destroy()

    root.protocol("WM_DELETE_WINDOW", on_closing)
    root.mainloop()


if __name__ == "__main__":
    main()
