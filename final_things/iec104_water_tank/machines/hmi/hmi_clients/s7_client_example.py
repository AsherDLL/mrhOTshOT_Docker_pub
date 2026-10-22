"""
Simple S7 Client Example for Water Tank Control

This script demonstrates how to connect to the S7 water tank server
and read measurements/send commands.

Usage:
    python hmi/s7_client_example.py
"""

import snap7
from snap7.client import Client
import snap7.util as util
import struct
import time


class S7WaterTankClient:
    """Simple S7 client for water tank control"""

    # Data Block numbers (must match server)
    DB_MEASUREMENTS = 1
    DB_STATUS = 2
    DB_COMMANDS = 3
    DB_SETPOINTS = 4

    def __init__(self, host='127.0.0.1', rack=0, slot=1):
        """
        Initialize S7 client

        Args:
            host: Server IP address
            rack: S7 rack number
            slot: S7 slot number
        """
        self.host = host
        self.rack = rack
        self.slot = slot
        self.client = Client()
        self.connected = False

    def connect(self):
        """Connect to S7 server"""
        try:
            self.client.connect(self.host, self.rack, self.slot)
            self.connected = True
            print(f"[+] Connected to S7 server at {self.host}")
            return True
        except Exception as e:
            print(f"[-] Failed to connect: {e}")
            self.connected = False
            return False

    def disconnect(self):
        """Disconnect from S7 server"""
        if self.connected:
            self.client.disconnect()
            self.connected = False
            print("[+] Disconnected from S7 server")

    # ========== READ MEASUREMENTS (DB1 - REAL values) ==========

    def read_water_level(self) -> float:
        """Read water level from DB1.DBD0"""
        data = self.client.db_read(self.DB_MEASUREMENTS, 0, 4)  # 4 bytes for REAL
        return util.get_real(data, 0)

    def read_pressure(self) -> float:
        """Read pressure from DB1.DBD4"""
        data = self.client.db_read(self.DB_MEASUREMENTS, 4, 4)
        return util.get_real(data, 0)

    def read_temperature(self) -> float:
        """Read temperature from DB1.DBD8"""
        data = self.client.db_read(self.DB_MEASUREMENTS, 8, 4)
        return util.get_real(data, 0)

    def read_all_measurements(self):
        """Read all measurements at once"""
        data = self.client.db_read(self.DB_MEASUREMENTS, 0, 12)  # 3 REAL values
        return {
            'water_level': util.get_real(data, 0),
            'pressure': util.get_real(data, 4),
            'temperature': util.get_real(data, 8),
        }

    # ========== READ STATUS (DB2 - BOOL values) ==========

    def read_inlet_valve_status(self) -> bool:
        """Read inlet valve status from DB2.DBX0.0"""
        data = self.client.db_read(self.DB_STATUS, 0, 1)
        return util.get_bool(data, 0, 0)

    def read_outlet_valve_status(self) -> bool:
        """Read outlet valve status from DB2.DBX0.1"""
        data = self.client.db_read(self.DB_STATUS, 0, 1)
        return util.get_bool(data, 0, 1)

    def read_pump_status(self) -> bool:
        """Read pump status from DB2.DBX0.2"""
        data = self.client.db_read(self.DB_STATUS, 0, 1)
        return util.get_bool(data, 0, 2)

    def read_auto_mode_status(self) -> bool:
        """Read auto mode status from DB2.DBX0.3"""
        data = self.client.db_read(self.DB_STATUS, 0, 1)
        return util.get_bool(data, 0, 3)

    def read_all_status(self):
        """Read all status bits at once"""
        data = self.client.db_read(self.DB_STATUS, 0, 2)  # Read 2 bytes
        return {
            'inlet_valve_status': util.get_bool(data, 0, 0),
            'outlet_valve_status': util.get_bool(data, 0, 1),
            'pump_status': util.get_bool(data, 0, 2),
            'auto_mode_status': util.get_bool(data, 0, 3),
            'overflow_alarm': util.get_bool(data, 0, 4),
            'low_level_alarm': util.get_bool(data, 0, 5),
            'high_pressure_alarm': util.get_bool(data, 0, 6),
            'tank_exploded': util.get_bool(data, 0, 7),
        }

    # ========== WRITE COMMANDS (DB3 - BOOL values) ==========

    def set_inlet_valve(self, state: bool):
        """Set inlet valve command (DB3.DBX0.0)"""
        data = bytearray(1)
        util.set_bool(data, 0, 0, state)
        self.client.db_write(self.DB_COMMANDS, 0, data)
        print(f"  → Inlet valve: {'ON' if state else 'OFF'}")

    def set_outlet_valve(self, state: bool):
        """Set outlet valve command (DB3.DBX0.1)"""
        data = bytearray(1)
        util.set_bool(data, 0, 1, state)
        self.client.db_write(self.DB_COMMANDS, 0, data)
        print(f"  → Outlet valve: {'ON' if state else 'OFF'}")

    def set_pump(self, state: bool):
        """Set pump command (DB3.DBX0.2)"""
        data = bytearray(1)
        util.set_bool(data, 0, 2, state)
        self.client.db_write(self.DB_COMMANDS, 0, data)
        print(f"  → Pump: {'ON' if state else 'OFF'}")

    def set_auto_mode(self, state: bool):
        """Set auto mode command (DB3.DBX0.3)"""
        data = bytearray(1)
        util.set_bool(data, 0, 3, state)
        self.client.db_write(self.DB_COMMANDS, 0, data)
        print(f"  → Auto mode: {'ON' if state else 'OFF'}")

    # ========== WRITE SETPOINTS (DB4 - REAL values) ==========

    def set_inlet_valve_setpoint(self, value: float):
        """Set inlet valve setpoint (DB4.DBD0)"""
        data = bytearray(4)
        util.set_real(data, 0, value)
        self.client.db_write(self.DB_SETPOINTS, 0, data)
        print(f"  → Inlet valve setpoint: {value:.1f}%")

    def set_outlet_valve_setpoint(self, value: float):
        """Set outlet valve setpoint (DB4.DBD4)"""
        data = bytearray(4)
        util.set_real(data, 0, value)
        self.client.db_write(self.DB_SETPOINTS, 4, data)
        print(f"  → Outlet valve setpoint: {value:.1f}%")

    # ========== CONVENIENCE METHODS ==========

    def print_status(self):
        """Print current tank status"""
        measurements = self.read_all_measurements()
        status = self.read_all_status()

        print("\n" + "="*60)
        print("WATER TANK STATUS")
        print("="*60)
        print(f"Water Level:    {measurements['water_level']:.1f}%")
        print(f"Pressure:       {measurements['pressure']:.2f} bar")
        print(f"Temperature:    {measurements['temperature']:.1f}°C")
        print("-"*60)
        print(f"Inlet Valve:    {'OPEN' if status['inlet_valve_status'] else 'CLOSED'}")
        print(f"Outlet Valve:   {'OPEN' if status['outlet_valve_status'] else 'CLOSED'}")
        print(f"Pump:           {'ON' if status['pump_status'] else 'OFF'}")
        print(f"Auto Mode:      {'ENABLED' if status['auto_mode_status'] else 'DISABLED'}")
        print("-"*60)
        if status['overflow_alarm']:
            print("[!]  OVERFLOW ALARM!")
        if status['low_level_alarm']:
            print("[!]  LOW LEVEL ALARM!")
        if status['high_pressure_alarm']:
            print("[!]  HIGH PRESSURE ALARM!")
        if status['tank_exploded']:
            print("TANK EXPLODED!")
        print("="*60 + "\n")


def main():
    """Example usage"""
    print("S7 Water Tank Client Example")
    print("="*60)

    # Create client
    client = S7WaterTankClient(host='127.0.0.1', rack=0, slot=1)

    # Connect
    if not client.connect():
        return

    try:
        # Read current status
        client.print_status()

        # Example: Disable auto mode and control manually
        print("\n1. Disabling auto mode...")
        client.set_auto_mode(False)
        time.sleep(0.5)

        # Example: Open inlet valve
        print("\n2. Opening inlet valve...")
        client.set_inlet_valve(True)
        time.sleep(2)

        # Check status
        client.print_status()

        # Example: Turn on pump
        print("\n3. Turning on pump...")
        client.set_pump(True)
        time.sleep(2)

        # Check status again
        client.print_status()

        # Example: Close inlet valve and turn off pump
        print("\n4. Closing inlet valve and turning off pump...")
        client.set_inlet_valve(False)
        client.set_pump(False)
        time.sleep(2)

        # Final status
        client.print_status()

        # Re-enable auto mode
        print("\n5. Re-enabling auto mode...")
        client.set_auto_mode(True)
        time.sleep(1)

        client.print_status()

    except KeyboardInterrupt:
        print("\n\nInterrupted by user")
    except Exception as e:
        print(f"\n\nError: {e}")
    finally:
        # Disconnect
        client.disconnect()


if __name__ == "__main__":
    main()
