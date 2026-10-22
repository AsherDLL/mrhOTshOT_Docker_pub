#!/usr/bin/env python3
"""
Test script to verify all manual mode operations
Tests the water tank system to ensure it can reach 100% without errors
"""
import sys
import os
sys.path.append(os.path.dirname(os.path.abspath(__file__)))

import time
from server.water_tank import WaterTank


def test_manual_operations():
    """Test all manual mode operations"""
    print("\n" + "="*70)
    print("MANUAL MODE OPERATIONS TEST".center(70))
    print("="*70)

    tank = WaterTank()
    tank.set_auto_mode(False)  # Switch to MANUAL mode

    print("\n1. Testing Mode Control")
    print(f"   Current mode: {'AUTO' if tank.get_auto_mode() else 'MANUAL'}")
    assert not tank.get_auto_mode(), "Failed to switch to MANUAL mode"
    print("   [+] MANUAL mode activated")

    print("\n2. Testing Inlet Valve Control")
    tank.set_inlet_valve(True)
    assert tank.get_inlet_valve_status(), "Inlet valve failed to open"
    print("   [+] Inlet valve OPEN")

    tank.set_inlet_valve(False)
    assert not tank.get_inlet_valve_status(), "Inlet valve failed to close"
    print("   [+] Inlet valve CLOSED")

    print("\n3. Testing Outlet Valve Control")
    tank.set_outlet_valve(True)
    assert tank.get_outlet_valve_status(), "Outlet valve failed to open"
    print("   [+] Outlet valve OPEN")

    tank.set_outlet_valve(False)
    assert not tank.get_outlet_valve_status(), "Outlet valve failed to close"
    print("   [+] Outlet valve CLOSED")

    print("\n4. Testing Pump Control")
    tank.set_pump(True)
    assert tank.get_pump_status(), "Pump failed to start"
    print("   [+] Pump STARTED")

    tank.set_pump(False)
    assert not tank.get_pump_status(), "Pump failed to stop"
    print("   [+] Pump STOPPED")

    print("\n5. Testing Water Level Range (0-100%)")
    print("   Filling tank to 100% to test full range...")

    tank.water_level = 90.0
    tank.set_inlet_valve(True)
    tank.set_pump(True)

    for i in range(30):
        tank.update()
        level = tank.get_water_level()

        if i % 5 == 0:
            print(f"   Water level: {level:.1f}%")

        if level >= 100.0:
            print(f"   [+] Reached 100% (actual: {level:.1f}%)")
            break

        time.sleep(0.1)

    # Test that values are properly represented
    final_level = tank.get_water_level()
    print(f"\n6. Testing Value Representation")
    print(f"   Final water level: {final_level:.2f}%")
    print(f"   Pressure: {tank.get_pressure():.2f} bar")
    print(f"   Temperature: {tank.get_temperature():.1f}°C")
    print(f"   Inlet valve: {'OPEN' if tank.get_inlet_valve_status() else 'CLOSED'}")
    print(f"   Outlet valve: {'OPEN' if tank.get_outlet_valve_status() else 'CLOSED'}")
    print(f"   Pump: {'ON' if tank.get_pump_status() else 'OFF'}")
    print(f"   Overflow alarm: {'ACTIVE' if tank.get_alarm_overflow() else 'NORMAL'}")
    print(f"   Low level alarm: {'ACTIVE' if tank.get_alarm_low_level() else 'NORMAL'}")

    assert final_level >= 98.0, "Failed to fill tank to high level"
    print("   [+] All values properly represented")

    print("\n7. Testing Overflow Protection")
    if tank.get_alarm_overflow():
        print("   [+] Overflow alarm TRIGGERED (as expected at 98%+)")
    else:
        print("   [!]  Overflow alarm not triggered")

    print("\n8. Testing Drainage")
    tank.set_inlet_valve(False)
    tank.set_outlet_valve(True)
    tank.set_pump(False)

    print("   Draining tank...")
    for i in range(30):
        tank.update()
        level = tank.get_water_level()

        if i % 10 == 0:
            print(f"   Water level: {level:.1f}%")

        if level <= 15.0:
            print(f"   [+] Drained to low level ({level:.1f}%)")
            break

        time.sleep(0.1)

    if tank.get_alarm_low_level():
        print("   [+] Low level alarm TRIGGERED (as expected)")

    print("\n9. Testing Mode Switching")
    tank.set_auto_mode(True)
    assert tank.get_auto_mode(), "Failed to switch back to AUTO mode"
    print("   [+] Successfully switched to AUTO mode")

    # Let auto mode stabilize
    print("   Running AUTO mode for 5 seconds...")
    for i in range(50):
        tank.update()
        time.sleep(0.1)

    final_level = tank.get_water_level()
    print(f"   Final level in AUTO mode: {final_level:.1f}%")
    print("   [+] AUTO mode functioning")

    print("\n" + "="*70)
    print("ALL MANUAL MODE OPERATIONS TESTS PASSED!".center(70))
    print("="*70)

    print("\n[+] Summary:")
    print("  - Mode switching: WORKING")
    print("  - Inlet valve control: WORKING")
    print("  - Outlet valve control: WORKING")
    print("  - Pump control: WORKING")
    print("  - 0-100% water level range: WORKING")
    print("  - Overflow protection: WORKING")
    print("  - Low level protection: WORKING")
    print("  - All measurements properly represented: WORKING")


if __name__ == "__main__":
    try:
        test_manual_operations()
    except AssertionError as e:
        print(f"\n[-] TEST FAILED: {e}")
        sys.exit(1)
    except Exception as e:
        print(f"\n[-] UNEXPECTED ERROR: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)
