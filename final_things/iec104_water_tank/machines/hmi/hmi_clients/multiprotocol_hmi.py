"""
Multi-Protocol HMI Client for Water Tank Control

Graphical interface that supports multiple industrial protocols:
- IEC 60870-5-104
- Siemens S7
- Modbus TCP
- OPC-UA

Usage:
    python hmi/multiprotocol_hmi.py --protocol iec104
    python hmi/multiprotocol_hmi.py --protocol s7 --port 1102
    python hmi/multiprotocol_hmi.py --protocol modbus
    python hmi/multiprotocol_hmi.py --protocol opcua
"""

import tkinter as tk
from tkinter import ttk, messagebox
import threading
import time
import sys
import os
import argparse

# Add parent directory to path
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from hmi.protocol_client import ProtocolClient, WaterTankDataPoints, DataUpdate
from hmi.iec104_client import IEC104Client
from hmi.s7_client import S7Client
from hmi.modbus_client import ModbusClient
from hmi.opcua_client import OPCUAClient


class MultiProtocolWaterTankHMI:
    """Multi-protocol HMI Application for Water Tank Control"""

    PROTOCOL_NAMES = {
        'iec104': 'IEC 60870-5-104',
        's7': 'Siemens S7',
        'modbus': 'Modbus TCP',
        'opcua': 'OPC-UA'
    }

    DEFAULT_PORTS = {
        'iec104': 2404,
        's7': 102,
        'modbus': 502,
        'opcua': 4840
    }

    def __init__(self, root, protocol: str, host: str = '127.0.0.1', port: int = None, config: dict = None):
        self.root = root
        self.protocol_type = protocol
        self.host = host
        self.port = port or self.DEFAULT_PORTS.get(protocol, 2404)
        self.config = config or {}

        protocol_name = self.PROTOCOL_NAMES.get(protocol, protocol.upper())
        self.root.title(f"Water Tank Control System - {protocol_name}")
        self.root.geometry("900x700")
        self.root.resizable(False, False)

        # Protocol client
        self.client: ProtocolClient = None
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

        # Setup UI
        self._setup_ui()

        # Start connection thread
        self.connection_thread = threading.Thread(target=self._connection_loop, daemon=True)
        self.connection_thread.start()

        # Start update loop
        self._update_display()

        # Handle window close
        self.root.protocol("WM_DELETE_WINDOW", self._on_closing)

    def _setup_ui(self):
        """Setup the user interface with dark theme"""
        # Title bar
        title_frame = tk.Frame(self.root, bg="#2c3e50", height=60)
        title_frame.pack(fill=tk.X)
        title_frame.pack_propagate(False)

        protocol_name = self.PROTOCOL_NAMES.get(self.protocol_type, self.protocol_type.upper())
        title_label = tk.Label(
            title_frame,
            text=f"Water Tank Control System - {protocol_name}",
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

        # Protocol info label
        protocol_info = tk.Label(
            title_frame,
            text=f"{self.host}:{self.port}",
            font=("Arial", 9),
            bg="#2c3e50",
            fg="#bdc3c7"
        )
        protocol_info.place(relx=0.05, rely=0.5, anchor=tk.W)

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
            bg="#2980b9", fg="#000000", activebackground="#3498db", activeforeground="#FFFFFF",
            disabledforeground="#7f8c8d", state=tk.DISABLED, relief=tk.RAISED, bd=2,
            command=lambda: self._send_command(WaterTankDataPoints.INLET_VALVE_COMMAND, True)
        )
        self.inlet_btn.pack(fill=tk.X, padx=10, pady=5)

        self.inlet_close_btn = tk.Button(
            control_frame, text="Close Inlet Valve", font=("Arial", 10, "bold"),
            bg="#2980b9", fg="#000000", activebackground="#3498db", activeforeground="#FFFFFF",
            disabledforeground="#7f8c8d", state=tk.DISABLED, relief=tk.RAISED, bd=2,
            command=lambda: self._send_command(WaterTankDataPoints.INLET_VALVE_COMMAND, False)
        )
        self.inlet_close_btn.pack(fill=tk.X, padx=10, pady=5)

        # Outlet valve control
        self.outlet_btn = tk.Button(
            control_frame, text="Open Outlet Valve", font=("Arial", 10, "bold"),
            bg="#2980b9", fg="#000000", activebackground="#3498db", activeforeground="#ffffff",
            disabledforeground="#7f8c8d", state=tk.DISABLED, relief=tk.RAISED, bd=2,
            command=lambda: self._send_command(WaterTankDataPoints.OUTLET_VALVE_COMMAND, True)
        )
        self.outlet_btn.pack(fill=tk.X, padx=10, pady=5)

        self.outlet_close_btn = tk.Button(
            control_frame, text="Close Outlet Valve", font=("Arial", 10, "bold"),
            bg="#2980b9", fg="#000000", activebackground="#3498db", activeforeground="#ffffff",
            disabledforeground="#7f8c8d", state=tk.DISABLED, relief=tk.RAISED, bd=2,
            command=lambda: self._send_command(WaterTankDataPoints.OUTLET_VALVE_COMMAND, False)
        )
        self.outlet_close_btn.pack(fill=tk.X, padx=10, pady=5)

        # Pump control
        self.pump_on_btn = tk.Button(
            control_frame, text="Start Pump", font=("Arial", 10, "bold"),
            bg="#2980b9", fg="#000000", activebackground="#3498db", activeforeground="#ffffff",
            disabledforeground="#7f8c8d", state=tk.DISABLED, relief=tk.RAISED, bd=2,
            command=lambda: self._send_command(WaterTankDataPoints.PUMP_COMMAND, True)
        )
        self.pump_on_btn.pack(fill=tk.X, padx=10, pady=5)

        self.pump_off_btn = tk.Button(
            control_frame, text="Stop Pump", font=("Arial", 10, "bold"),
            bg="#2980b9", fg="#000000", activebackground="#3498db", activeforeground="#ffffff",
            disabledforeground="#7f8c8d", state=tk.DISABLED, relief=tk.RAISED, bd=2,
            command=lambda: self._send_command(WaterTankDataPoints.PUMP_COMMAND, False)
        )
        self.pump_off_btn.pack(fill=tk.X, padx=10, pady=5)

        # Alarms
        alarm_frame = tk.LabelFrame(right_panel, text="Alarms", font=("Arial", 12, "bold"),
                                    bg="#1a1a1a", fg="#00ff00", bd=2, relief=tk.GROOVE)
        alarm_frame.pack(fill=tk.X)

        self.overflow_alarm = tk.Label(alarm_frame, text="Overflow: OK", font=("Arial", 11, "bold"),
                                       bg="#1a1a1a", fg="#27ae60")
        self.overflow_alarm.pack(anchor=tk.W, padx=10, pady=5)

        self.low_level_alarm = tk.Label(alarm_frame, text="Low Level: OK", font=("Arial", 11, "bold"),
                                        bg="#1a1a1a", fg="#27ae60")
        self.low_level_alarm.pack(anchor=tk.W, padx=10, pady=5)

        self.high_pressure_alarm = tk.Label(alarm_frame, text="High Pressure: OK", font=("Arial", 11, "bold"),
                                            bg="#1a1a1a", fg="#27ae60")
        self.high_pressure_alarm.pack(anchor=tk.W, padx=10, pady=5)

        self.tank_status = tk.Label(alarm_frame, text="Tank: NORMAL", font=("Arial", 11, "bold"),
                                    bg="#1a1a1a", fg="#27ae60")
        self.tank_status.pack(anchor=tk.W, padx=10, pady=5)

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

        # Update connection status
        if self.connected:
            self.status_label.config(text="Connected", fg="#27ae60")
        else:
            self.status_label.config(text="Disconnected", fg="#e74c3c")

        # Update measurements
        self.level_label.config(text=f"{self.water_level:.1f} %")
        self.pressure_label.config(text=f"{self.pressure:.2f} bar")
        self.temp_label.config(text=f"{self.temperature:.1f} °C")

        # Update status indicators
        self.inlet_indicator.config(fg="#27ae60" if self.inlet_valve_status else "#95a5a6")
        self.outlet_indicator.config(fg="#27ae60" if self.outlet_valve_status else "#95a5a6")
        self.pump_indicator.config(fg="#27ae60" if self.pump_status else "#95a5a6")

        # Update mode display
        if self.auto_mode:
            self.mode_var.set("AUTO")
        else:
            self.mode_var.set("MANUAL")

        # Enable/disable manual controls based on mode and connection
        if self.auto_mode or not self.connected:
            self.inlet_btn.config(state=tk.DISABLED)
            self.inlet_close_btn.config(state=tk.DISABLED)
            self.outlet_btn.config(state=tk.DISABLED)
            self.outlet_close_btn.config(state=tk.DISABLED)
            self.pump_on_btn.config(state=tk.DISABLED)
            self.pump_off_btn.config(state=tk.DISABLED)
        else:
            self.inlet_btn.config(state=tk.NORMAL)
            self.inlet_close_btn.config(state=tk.NORMAL)
            self.outlet_btn.config(state=tk.NORMAL)
            self.outlet_close_btn.config(state=tk.NORMAL)
            self.pump_on_btn.config(state=tk.NORMAL)
            self.pump_off_btn.config(state=tk.NORMAL)

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

        # Update tank visualization
        self._update_tank_visualization()

        # Schedule next update
        self.root.after(100, self._update_display)

    def _create_protocol_client(self) -> ProtocolClient:
        """Create protocol client based on type"""
        if self.protocol_type == 'iec104':
            return IEC104Client(self.host, self.port, self.config)
        elif self.protocol_type == 's7':
            return S7Client(self.host, self.port, self.config)
        elif self.protocol_type == 'modbus':
            return ModbusClient(self.host, self.port, self.config)
        elif self.protocol_type == 'opcua':
            return OPCUAClient(self.host, self.port, self.config)
        else:
            raise ValueError(f"Unsupported protocol: {self.protocol_type}")

    def _connection_loop(self):
        """Connection management loop"""
        while self.running:
            try:
                if not self.connected:
                    print(f"Connecting to {self.protocol_type.upper()} server at {self.host}:{self.port}...")

                    # Create protocol client
                    self.client = self._create_protocol_client()

                    # Register data callback
                    self.client.register_data_callback(self._on_data_update)

                    # Connect
                    if self.client.connect():
                        self.connected = True
                        print(f"[+] Connected to {self.protocol_type.upper()} server")

                        # Start monitoring
                        self.client.start_monitoring()
                    else:
                        print(f"[-] Failed to connect to {self.protocol_type.upper()} server")
                        time.sleep(5)  # Retry after 5 seconds
                else:
                    # Monitor connection
                    if not self.client.connected:
                        self.connected = False
                        print(f"[-] Disconnected from {self.protocol_type.upper()} server")

                time.sleep(1)

            except Exception as e:
                print(f"Connection error: {e}")
                self.connected = False
                time.sleep(5)

    def _on_data_update(self, update: DataUpdate):
        """Handle data updates from protocol client"""
        try:
            name = update.name
            value = update.value

            # Update internal state
            if name == WaterTankDataPoints.WATER_LEVEL:
                self.water_level = float(value)
            elif name == WaterTankDataPoints.PRESSURE:
                self.pressure = float(value)
            elif name == WaterTankDataPoints.TEMPERATURE:
                self.temperature = float(value)
            elif name == WaterTankDataPoints.INLET_VALVE_STATUS:
                self.inlet_valve_status = bool(value)
            elif name == WaterTankDataPoints.OUTLET_VALVE_STATUS:
                self.outlet_valve_status = bool(value)
            elif name == WaterTankDataPoints.PUMP_STATUS:
                self.pump_status = bool(value)
            elif name == WaterTankDataPoints.AUTO_MODE_STATUS:
                self.auto_mode = bool(value)
            elif name == WaterTankDataPoints.OVERFLOW_ALARM:
                self.alarm_overflow = bool(value)
            elif name == WaterTankDataPoints.LOW_LEVEL_ALARM:
                self.alarm_low_level = bool(value)
            elif name == WaterTankDataPoints.HIGH_PRESSURE_ALARM:
                self.alarm_high_pressure = bool(value)
            elif name == WaterTankDataPoints.TANK_EXPLODED_ALARM:
                self.tank_exploded = bool(value)

        except Exception as e:
            print(f"Error processing data update: {e}")

    def _on_mode_change(self):
        """Handle mode change"""
        if self.connected and self.client:
            new_mode = self.mode_var.get()
            auto_mode_state = (new_mode == "AUTO")
            self.client.send_command(WaterTankDataPoints.AUTO_MODE_COMMAND, auto_mode_state)

    def _send_command(self, command: str, value: bool):
        """Send command to server"""
        if self.connected and self.client:
            success = self.client.send_command(command, value)
            if not success:
                print(f"Failed to send command: {command} = {value}")

    def _on_closing(self):
        """Handle window closing"""
        self.running = False

        if self.client:
            self.client.stop_monitoring()
            self.client.disconnect()

        self.root.destroy()


def main():
    """Main entry point"""
    parser = argparse.ArgumentParser(description="Multi-Protocol Water Tank HMI")
    parser.add_argument('--protocol', required=True, choices=['iec104', 's7', 'modbus', 'opcua'],
                       help='Protocol to use')
    parser.add_argument('--host', default='127.0.0.1', help='Server host (default: 127.0.0.1)')
    parser.add_argument('--port', type=int, help='Server port (default: protocol-specific)')

    # Protocol-specific options
    parser.add_argument('--common-address', type=int, default=1, help='IEC-104: Common address (default: 1)')
    parser.add_argument('--rack', type=int, default=0, help='S7: Rack number (default: 0)')
    parser.add_argument('--slot', type=int, default=1, help='S7: Slot number (default: 1)')
    parser.add_argument('--slave-id', type=int, default=1, help='Modbus: Slave ID (default: 1)')

    args = parser.parse_args()

    # Build protocol-specific config
    config = {}
    if args.protocol == 'iec104':
        config['common_address'] = args.common_address
    elif args.protocol == 's7':
        config['rack'] = args.rack
        config['slot'] = args.slot
    elif args.protocol == 'modbus':
        config['slave_id'] = args.slave_id

    # Create and run HMI
    root = tk.Tk()
    app = MultiProtocolWaterTankHMI(root, args.protocol, args.host, args.port, config)
    root.mainloop()


if __name__ == "__main__":
    main()
