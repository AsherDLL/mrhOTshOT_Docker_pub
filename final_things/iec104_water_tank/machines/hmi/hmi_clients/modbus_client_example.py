"""
Simple Modbus TCP Client Example for Water Tank Control

This script demonstrates how to connect to the Modbus water tank server
and read measurements/send commands.

Usage:
    python hmi/modbus_client_example.py
"""

from pymodbus.client import ModbusTcpClient
import time


class ModbusWaterTankClient:
    """Simple Modbus TCP client for water tank control"""

    def __init__(self, host='127.0.0.1', port=502, slave_id=1):
        """
        Initialize Modbus client

        Args:
            host: Server IP address
            port: Modbus TCP port
            slave_id: Modbus slave ID
        """
        self.host = host
        self.port = port
        self.slave_id = slave_id
        self.client = ModbusTcpClient(host, port=port)
        self.connected = False

    def connect(self):
        """Connect to Modbus server"""
        try:
            self.connected = self.client.connect()
            if self.connected:
                print(f"[+] Connected to Modbus server at {self.host}:{self.port}")
            else:
                print(f"[-] Failed to connect to Modbus server")
            return self.connected
        except Exception as e:
            print(f"[-] Connection error: {e}")
            self.connected = False
            return False

    def disconnect(self):
        """Disconnect from Modbus server"""
        if self.connected:
            self.client.close()
            self.connected = False
            print("[+] Disconnected from Modbus server")

    # ========== READ MEASUREMENTS (Input Registers 3x) ==========

    def read_water_level(self) -> float:
        """Read water level from Input Register 0"""
        result = self.client.read_input_registers(0, 1, slave=self.slave_id)
        if result.isError():
            return 0.0
        # Scale from 0-65535 to 0-100%
        return (result.registers[0] / 65535.0) * 100.0

    def read_pressure(self) -> float:
        """Read pressure from Input Register 1"""
        result = self.client.read_input_registers(1, 1, slave=self.slave_id)
        if result.isError():
            return 0.0
        # Scale from 0-65535 to 0-10 bar
        return (result.registers[0] / 65535.0) * 10.0

    def read_temperature(self) -> float:
        """Read temperature from Input Register 2"""
        result = self.client.read_input_registers(2, 1, slave=self.slave_id)
        if result.isError():
            return 0.0
        # Scale from 0-65535 to 0-100°C
        return (result.registers[0] / 65535.0) * 100.0

    def read_all_measurements(self):
        """Read all measurements at once"""
        result = self.client.read_input_registers(0, 3, slave=self.slave_id)
        if result.isError():
            return {}
        return {
            'water_level': (result.registers[0] / 65535.0) * 100.0,
            'pressure': (result.registers[1] / 65535.0) * 10.0,
            'temperature': (result.registers[2] / 65535.0) * 100.0,
        }

    # ========== READ STATUS (Discrete Inputs 1x) ==========

    def read_all_status(self):
        """Read all status bits"""
        result = self.client.read_discrete_inputs(0, 12, slave=self.slave_id)
        if result.isError():
            return {}
        bits = result.bits
        return {
            'inlet_valve_status': bits[0],
            'outlet_valve_status': bits[1],
            'pump_status': bits[2],
            'auto_mode_status': bits[3],
            'overflow_alarm': bits[8],
            'low_level_alarm': bits[9],
            'high_pressure_alarm': bits[10],
            'tank_exploded': bits[11],
        }

    # ========== WRITE COMMANDS (Coils 0x) ==========

    def set_inlet_valve(self, state: bool):
        """Set inlet valve command (Coil 0)"""
        self.client.write_coil(0, state, slave=self.slave_id)
        print(f"  → Inlet valve: {'ON' if state else 'OFF'}")

    def set_outlet_valve(self, state: bool):
        """Set outlet valve command (Coil 1)"""
        self.client.write_coil(1, state, slave=self.slave_id)
        print(f"  → Outlet valve: {'ON' if state else 'OFF'}")

    def set_pump(self, state: bool):
        """Set pump command (Coil 2)"""
        self.client.write_coil(2, state, slave=self.slave_id)
        print(f"  → Pump: {'ON' if state else 'OFF'}")

    def set_auto_mode(self, state: bool):
        """Set auto mode command (Coil 3)"""
        self.client.write_coil(3, state, slave=self.slave_id)
        print(f"  → Auto mode: {'ON' if state else 'OFF'}")

    # ========== WRITE SETPOINTS (Holding Registers 4x) ==========

    def set_inlet_valve_setpoint(self, value: float):
        """Set inlet valve setpoint (Holding Register 0)"""
        # Scale from 0-100% to 0-65535
        scaled = int((value / 100.0) * 65535)
        self.client.write_register(0, scaled, slave=self.slave_id)
        print(f"  → Inlet valve setpoint: {value:.1f}%")

    def set_outlet_valve_setpoint(self, value: float):
        """Set outlet valve setpoint (Holding Register 1)"""
        # Scale from 0-100% to 0-65535
        scaled = int((value / 100.0) * 65535)
        self.client.write_register(1, scaled, slave=self.slave_id)
        print(f"  → Outlet valve setpoint: {value:.1f}%")

    # ========== CONVENIENCE METHODS ==========

    def print_status(self):
        """Print current tank status"""
        measurements = self.read_all_measurements()
        status = self.read_all_status()

        print("\n" + "="*60)
        print("WATER TANK STATUS")
        print("="*60)
        print(f"Water Level:    {measurements.get('water_level', 0):.1f}%")
        print(f"Pressure:       {measurements.get('pressure', 0):.2f} bar")
        print(f"Temperature:    {measurements.get('temperature', 0):.1f}°C")
        print("-"*60)
        print(f"Inlet Valve:    {'OPEN' if status.get('inlet_valve_status') else 'CLOSED'}")
        print(f"Outlet Valve:   {'OPEN' if status.get('outlet_valve_status') else 'CLOSED'}")
        print(f"Pump:           {'ON' if status.get('pump_status') else 'OFF'}")
        print(f"Auto Mode:      {'ENABLED' if status.get('auto_mode_status') else 'DISABLED'}")
        print("-"*60)
        if status.get('overflow_alarm'):
            print("[!]  OVERFLOW ALARM!")
        if status.get('low_level_alarm'):
            print("[!]  LOW LEVEL ALARM!")
        if status.get('high_pressure_alarm'):
            print("[!]  HIGH PRESSURE ALARM!")
        if status.get('tank_exploded'):
            print("TANK EXPLODED!")
        print("="*60 + "\n")


def main():
    """Example usage"""
    print("Modbus TCP Water Tank Client Example")
    print("="*60)

    # Create client
    client = ModbusWaterTankClient(host='127.0.0.1', port=502, slave_id=1)

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
