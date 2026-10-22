"""
HMI Client for Water Tank Control using IEC-104 (c104 library)
Graphical interface for monitoring and controlling the water tank
"""
import tkinter as tk
from tkinter import ttk, messagebox
import threading
import time
import sys
import os
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import c104
from common.config import *


class WaterTankHMI:
    """HMI Application for Water Tank Control"""

    def __init__(self, root):
        self.root = root
        self.root.title("Water Tank Control System - IEC-104 HMI")
        self.root.geometry("900x700")
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

        # Points storage
        self.points = {}

        # Setup UI
        self._setup_ui()

        # Start connection thread
        self.connection_thread = threading.Thread(target=self._connection_loop, daemon=True)
        self.connection_thread.start()

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

        # Update tank visualization
        self._update_tank_visualization()

        # Schedule next update
        self.root.after(100, self._update_display)

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
                self.water_level = float(point.value)
            elif ioa == IOA_PRESSURE:
                self.pressure = float(point.value) / 10.0  # Scale back from Int16
            elif ioa == IOA_TEMPERATURE:
                self.temperature = float(point.value)
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
    root = tk.Tk()
    hmi = WaterTankHMI(root)

    def on_closing():
        hmi.close()
        root.destroy()

    root.protocol("WM_DELETE_WINDOW", on_closing)
    root.mainloop()


if __name__ == "__main__":
    main()
