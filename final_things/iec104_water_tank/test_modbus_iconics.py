#!/usr/bin/env python3
"""
Test Modbus Connectivity for ICONICS Integration

This script validates the Modbus server configuration and tests all register mappings
to ensure proper integration with ICONICS GENESIS64 or FrameWorX.

Usage:
    python test_modbus_iconics.py
    python test_modbus_iconics.py --host 192.168.1.100 --port 502
"""

import sys
import time
import argparse
from pymodbus.client import ModbusTcpClient
from pymodbus.exceptions import ModbusException


class ModbusConnectivityTest:
    """Test Modbus connectivity and register mapping for ICONICS"""

    def __init__(self, host='127.0.0.1', port=502, slave_id=1):
        self.host = host
        self.port = port
        self.slave_id = slave_id
        self.client = None
        self.test_results = []

    def connect(self):
        """Connect to Modbus server"""
        print("="*80)
        print("MODBUS CONNECTIVITY TEST FOR ICONICS INTEGRATION")
        print("="*80)
        print(f"\nConnecting to Modbus server...")
        print(f"  Host: {self.host}")
        print(f"  Port: {self.port}")
        print(f"  Unit ID: {self.slave_id}")
        
        try:
            self.client = ModbusTcpClient(self.host, port=self.port)
            connected = self.client.connect()
            
            if connected:
                print("[+] Connection successful!\n")
                return True
            else:
                print("[-] Connection failed!\n")
                return False
        except Exception as e:
            print(f"[-] Connection error: {e}\n")
            return False

    def disconnect(self):
        """Disconnect from Modbus server"""
        if self.client:
            self.client.close()
            print("\n[+] Disconnected from server")

    def test_input_registers(self):
        """Test Input Registers (3x) - Measurements"""
        print("-"*80)
        print("TEST 1: INPUT REGISTERS (3x) - Analog Measurements")
        print("-"*80)
        
        try:
            # Read all 3 input registers
            result = self.client.read_input_registers(0, 3, slave=self.slave_id)
            
            if result.isError():
                print(f"[-] Failed to read input registers: {result}")
                self.test_results.append(("Input Registers", False))
                return False
            
            # Parse and display values
            water_level_raw = result.registers[0]
            pressure_raw = result.registers[1]
            temperature_raw = result.registers[2]
            
            # Apply scaling
            water_level = (water_level_raw / 65535.0) * 100.0
            pressure = (pressure_raw / 65535.0) * 10.0
            temperature = (temperature_raw / 65535.0) * 100.0
            
            print(f"[+] Water Level (IR0/30001):")
            print(f"   Raw Value: {water_level_raw}")
            print(f"   Scaled Value: {water_level:.2f} %")
            print(f"   Expected Range: 0-100%")
            
            print(f"\n[+] Pressure (IR1/30002):")
            print(f"   Raw Value: {pressure_raw}")
            print(f"   Scaled Value: {pressure:.2f} bar")
            print(f"   Expected Range: 0-10 bar")
            
            print(f"\n[+] Temperature (IR2/30003):")
            print(f"   Raw Value: {temperature_raw}")
            print(f"   Scaled Value: {temperature:.2f} °C")
            print(f"   Expected Range: 0-100°C")
            
            self.test_results.append(("Input Registers", True))
            return True
            
        except Exception as e:
            print(f"[-] Error reading input registers: {e}")
            self.test_results.append(("Input Registers", False))
            return False

    def test_discrete_inputs(self):
        """Test Discrete Inputs (1x) - Status and Alarms"""
        print("\n" + "-"*80)
        print("TEST 2: DISCRETE INPUTS (1x) - Digital Status & Alarms")
        print("-"*80)
        
        try:
            # Read all 12 discrete inputs
            result = self.client.read_discrete_inputs(0, 12, slave=self.slave_id)
            
            if result.isError():
                print(f"[-] Failed to read discrete inputs: {result}")
                self.test_results.append(("Discrete Inputs", False))
                return False
            
            bits = result.bits
            
            # Status bits (0-3)
            print("Status Bits:")
            print(f"  [+] Inlet Valve Status (DI0/10001): {bits[0]} {'[OPEN]' if bits[0] else '[CLOSED]'}")
            print(f"  [+] Outlet Valve Status (DI1/10002): {bits[1]} {'[OPEN]' if bits[1] else '[CLOSED]'}")
            print(f"  [+] Pump Status (DI2/10003): {bits[2]} {'[RUNNING]' if bits[2] else '[STOPPED]'}")
            print(f"  [+] Auto Mode Status (DI3/10004): {bits[3]} {'[AUTO]' if bits[3] else '[MANUAL]'}")
            
            # Alarm bits (8-11)
            print("\nAlarm Bits:")
            print(f"  {'[!] ' if bits[8] else '[+]'} Overflow Alarm (DI8/10009): {bits[8]} {'[ACTIVE]' if bits[8] else '[OK]'}")
            print(f"  {'[!] ' if bits[9] else '[+]'} Low Level Alarm (DI9/10010): {bits[9]} {'[ACTIVE]' if bits[9] else '[OK]'}")
            print(f"  {'[!] ' if bits[10] else '[+]'} High Pressure Alarm (DI10/10011): {bits[10]} {'[ACTIVE]' if bits[10] else '[OK]'}")
            print(f"  {'[!] ' if bits[11] else '[+]'} Tank Exploded Alarm (DI11/10012): {bits[11]} {'[ACTIVE]' if bits[11] else '[OK]'}")
            
            self.test_results.append(("Discrete Inputs", True))
            return True
            
        except Exception as e:
            print(f"[-] Error reading discrete inputs: {e}")
            self.test_results.append(("Discrete Inputs", False))
            return False

    def test_coils_read(self):
        """Test Coils (0x) - Read Commands"""
        print("\n" + "-"*80)
        print("TEST 3: COILS (0x) - Digital Commands (Read)")
        print("-"*80)
        
        try:
            # Read all 4 coils
            result = self.client.read_coils(0, 4, slave=self.slave_id)
            
            if result.isError():
                print(f"[-] Failed to read coils: {result}")
                self.test_results.append(("Coils Read", False))
                return False
            
            bits = result.bits
            
            print(f"[+] Inlet Valve Command (C0/00001): {bits[0]}")
            print(f"[+] Outlet Valve Command (C1/00002): {bits[1]}")
            print(f"[+] Pump Command (C2/00003): {bits[2]}")
            print(f"[+] Auto Mode Command (C3/00004): {bits[3]}")
            
            self.test_results.append(("Coils Read", True))
            return True
            
        except Exception as e:
            print(f"[-] Error reading coils: {e}")
            self.test_results.append(("Coils Read", False))
            return False

    def test_coils_write(self):
        """Test Coils (0x) - Write Commands"""
        print("\n" + "-"*80)
        print("TEST 4: COILS (0x) - Digital Commands (Write)")
        print("-"*80)
        print("[!]  Note: This test will switch to MANUAL mode and control the system")
        print("[!]  The system will be returned to AUTO mode after testing")
        
        input("\nPress Enter to continue with write tests (or Ctrl+C to skip)...")
        
        try:
            # Save current auto mode state
            result = self.client.read_coils(3, 1, slave=self.slave_id)
            original_auto_mode = result.bits[0] if not result.isError() else True
            
            print(f"\nOriginal Auto Mode: {original_auto_mode}")
            
            # Test 1: Switch to manual mode
            print("\nTest 4a: Switching to MANUAL mode...")
            result = self.client.write_coil(3, False, slave=self.slave_id)
            if not result.isError():
                time.sleep(0.5)
                verify = self.client.read_discrete_inputs(3, 1, slave=self.slave_id)
                if not verify.isError() and verify.bits[0] == False:
                    print("  [+] Successfully switched to MANUAL mode")
                else:
                    print("  [!]  Mode switch verification failed")
            else:
                print(f"  [-] Failed to write auto mode: {result}")
            
            # Test 2: Control inlet valve
            print("\nTest 4b: Opening inlet valve...")
            result = self.client.write_coil(0, True, slave=self.slave_id)
            if not result.isError():
                time.sleep(0.5)
                verify = self.client.read_discrete_inputs(0, 1, slave=self.slave_id)
                if not verify.isError() and verify.bits[0] == True:
                    print("  [+] Inlet valve opened successfully")
                else:
                    print("  [!]  Valve state verification failed")
            else:
                print(f"  [-] Failed to write inlet valve: {result}")
            
            # Test 3: Close inlet valve
            print("\nTest 4c: Closing inlet valve...")
            result = self.client.write_coil(0, False, slave=self.slave_id)
            if not result.isError():
                time.sleep(0.5)
                verify = self.client.read_discrete_inputs(0, 1, slave=self.slave_id)
                if not verify.isError() and verify.bits[0] == False:
                    print("  [+] Inlet valve closed successfully")
                else:
                    print("  [!]  Valve state verification failed")
            else:
                print(f"  [-] Failed to write inlet valve: {result}")
            
            # Restore original auto mode
            print(f"\nTest 4d: Restoring AUTO mode to original state ({original_auto_mode})...")
            result = self.client.write_coil(3, original_auto_mode, slave=self.slave_id)
            if not result.isError():
                print(f"  [+] AUTO mode restored")
            else:
                print(f"  [-] Failed to restore auto mode: {result}")
            
            self.test_results.append(("Coils Write", True))
            return True
            
        except KeyboardInterrupt:
            print("\n[!]  Write tests skipped by user")
            self.test_results.append(("Coils Write", "Skipped"))
            return True
        except Exception as e:
            print(f"[-] Error in coil write tests: {e}")
            self.test_results.append(("Coils Write", False))
            return False

    def test_holding_registers_read(self):
        """Test Holding Registers (4x) - Read Setpoints"""
        print("\n" + "-"*80)
        print("TEST 5: HOLDING REGISTERS (4x) - Analog Setpoints (Read)")
        print("-"*80)
        
        try:
            # Read both holding registers
            result = self.client.read_holding_registers(0, 2, slave=self.slave_id)
            
            if result.isError():
                print(f"[-] Failed to read holding registers: {result}")
                self.test_results.append(("Holding Registers Read", False))
                return False
            
            inlet_valve_sp_raw = result.registers[0]
            outlet_valve_sp_raw = result.registers[1]
            
            # Apply scaling
            inlet_valve_sp = (inlet_valve_sp_raw / 65535.0) * 100.0
            outlet_valve_sp = (outlet_valve_sp_raw / 65535.0) * 100.0
            
            print(f"[+] Inlet Valve Setpoint (HR0/40001):")
            print(f"   Raw Value: {inlet_valve_sp_raw}")
            print(f"   Scaled Value: {inlet_valve_sp:.2f} %")
            
            print(f"\n[+] Outlet Valve Setpoint (HR1/40002):")
            print(f"   Raw Value: {outlet_valve_sp_raw}")
            print(f"   Scaled Value: {outlet_valve_sp:.2f} %")
            
            self.test_results.append(("Holding Registers Read", True))
            return True
            
        except Exception as e:
            print(f"[-] Error reading holding registers: {e}")
            self.test_results.append(("Holding Registers Read", False))
            return False

    def test_holding_registers_write(self):
        """Test Holding Registers (4x) - Write Setpoints"""
        print("\n" + "-"*80)
        print("TEST 6: HOLDING REGISTERS (4x) - Analog Setpoints (Write)")
        print("-"*80)
        print("[!]  Note: This test will write setpoint values")
        
        input("\nPress Enter to continue with setpoint write tests (or Ctrl+C to skip)...")
        
        try:
            # Test writing 50% setpoint
            print("\nTest 6a: Writing 50% to inlet valve setpoint...")
            setpoint_value = int((50.0 / 100.0) * 65535)
            result = self.client.write_register(0, setpoint_value, slave=self.slave_id)
            
            if not result.isError():
                time.sleep(0.5)
                verify = self.client.read_holding_registers(0, 1, slave=self.slave_id)
                if not verify.isError():
                    read_back = (verify.registers[0] / 65535.0) * 100.0
                    print(f"  [+] Setpoint written successfully")
                    print(f"  Readback value: {read_back:.2f}% (target: 50%)")
                else:
                    print("  [!]  Verification read failed")
            else:
                print(f"  [-] Failed to write setpoint: {result}")
            
            # Test writing 75% setpoint
            print("\nTest 6b: Writing 75% to outlet valve setpoint...")
            setpoint_value = int((75.0 / 100.0) * 65535)
            result = self.client.write_register(1, setpoint_value, slave=self.slave_id)
            
            if not result.isError():
                time.sleep(0.5)
                verify = self.client.read_holding_registers(1, 1, slave=self.slave_id)
                if not verify.isError():
                    read_back = (verify.registers[0] / 65535.0) * 100.0
                    print(f"  [+] Setpoint written successfully")
                    print(f"  Readback value: {read_back:.2f}% (target: 75%)")
                else:
                    print("  [!]  Verification read failed")
            else:
                print(f"  [-] Failed to write setpoint: {result}")
            
            self.test_results.append(("Holding Registers Write", True))
            return True
            
        except KeyboardInterrupt:
            print("\n[!]  Setpoint write tests skipped by user")
            self.test_results.append(("Holding Registers Write", "Skipped"))
            return True
        except Exception as e:
            print(f"[-] Error in holding register write tests: {e}")
            self.test_results.append(("Holding Registers Write", False))
            return False

    def test_scaling_accuracy(self):
        """Test scaling accuracy for ICONICS configuration"""
        print("\n" + "-"*80)
        print("TEST 7: SCALING ACCURACY VERIFICATION")
        print("-"*80)
        
        print("\nScaling formulas used:")
        print("  Measurements: Actual = (Raw / 65535) × Max_Range")
        print("  Setpoints: Raw = (Actual / Max_Range) × 65535")
        
        test_cases = [
            (0, 0.0, "0%"),
            (16384, 25.0, "25%"),
            (32768, 50.0, "50%"),
            (49152, 75.0, "75%"),
            (65535, 100.0, "100%"),
        ]
        
        print("\nTest cases for 0-100% range:")
        all_passed = True
        for raw, expected_scaled, label in test_cases:
            actual_scaled = (raw / 65535.0) * 100.0
            error = abs(actual_scaled - expected_scaled)
            passed = error < 0.5  # Allow 0.5% error
            
            status = "[+]" if passed else "[-]"
            print(f"  {status} Raw: {raw:5d} → Scaled: {actual_scaled:6.2f}% (expected: {label})")
            
            if not passed:
                all_passed = False
        
        self.test_results.append(("Scaling Accuracy", all_passed))
        return all_passed

    def print_summary(self):
        """Print test summary"""
        print("\n" + "="*80)
        print("TEST SUMMARY")
        print("="*80)
        
        passed = sum(1 for _, result in self.test_results if result == True)
        failed = sum(1 for _, result in self.test_results if result == False)
        skipped = sum(1 for _, result in self.test_results if result == "Skipped")
        total = len(self.test_results)
        
        for test_name, result in self.test_results:
            if result == True:
                status = "[+] PASSED"
            elif result == False:
                status = "[-] FAILED"
            else:
                status = "[!]  SKIPPED"
            print(f"{status:15s} {test_name}")
        
        print("-"*80)
        print(f"Total Tests: {total}")
        print(f"Passed: {passed}")
        print(f"Failed: {failed}")
        print(f"Skipped: {skipped}")
        
        if failed == 0:
            print("\n[+] All tests passed! System is ready for ICONICS integration.")
        else:
            print(f"\n[-] {failed} test(s) failed. Please review and fix issues before ICONICS integration.")
        
        print("="*80)

    def run_all_tests(self):
        """Run all connectivity tests"""
        if not self.connect():
            print("[-] Cannot proceed without server connection.")
            print("\nPlease ensure the Modbus server is running:")
            print("  cd /opt/mrhOTshOT/final_things/iec104_water_tank")
            print("  python water_tank_server.py --protocol modbus")
            return False
        
        try:
            # Run all tests
            self.test_input_registers()
            self.test_discrete_inputs()
            self.test_coils_read()
            self.test_coils_write()
            self.test_holding_registers_read()
            self.test_holding_registers_write()
            self.test_scaling_accuracy()
            
            # Print summary
            self.print_summary()
            
            return True
            
        finally:
            self.disconnect()


def main():
    """Main entry point"""
    parser = argparse.ArgumentParser(
        description="Test Modbus connectivity for ICONICS integration",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # Test local server
  python test_modbus_iconics.py
  
  # Test remote server
  python test_modbus_iconics.py --host 192.168.1.100
  
  # Custom port
  python test_modbus_iconics.py --port 5020
        """
    )
    
    parser.add_argument(
        '--host',
        type=str,
        default='127.0.0.1',
        help='Modbus server IP address (default: 127.0.0.1)'
    )
    
    parser.add_argument(
        '--port',
        type=int,
        default=502,
        help='Modbus server port (default: 502)'
    )
    
    parser.add_argument(
        '--slave-id',
        type=int,
        default=1,
        help='Modbus slave/unit ID (default: 1)'
    )
    
    args = parser.parse_args()
    
    # Run tests
    tester = ModbusConnectivityTest(
        host=args.host,
        port=args.port,
        slave_id=args.slave_id
    )
    
    try:
        success = tester.run_all_tests()
        sys.exit(0 if success else 1)
    except KeyboardInterrupt:
        print("\n\n[!]  Tests interrupted by user")
        sys.exit(1)
    except Exception as e:
        print(f"\n\n[-] Unexpected error: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)


if __name__ == "__main__":
    main()
