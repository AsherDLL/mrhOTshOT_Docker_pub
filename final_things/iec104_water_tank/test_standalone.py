#!/usr/bin/env python3
"""
Standalone Water Tank Simulation Test
Tests the water tank physics and automation without IEC-104 dependencies
"""
import sys
import os
sys.path.append(os.path.dirname(os.path.abspath(__file__))))

import time
from server.water_tank import WaterTank


def print_status(tank):
    """Print tank status"""
    status = tank.get_status_dict()
    print(f"\n{'='*50}")
    print(f"Water Level:     {status['water_level']:6.1f}%")
    print(f"Pressure:        {status['pressure']:6.2f} bar")
    print(f"Temperature:     {status['temperature']:6.1f}°C")
    print(f"Inlet Valve:     {status['inlet_valve_position']:6.0f}% {'[OPEN]' if status['inlet_valve_position'] > 0 else '[CLOSED]'}")
    print(f"Outlet Valve:    {status['outlet_valve_position']:6.0f}% {'[OPEN]' if status['outlet_valve_position'] > 0 else '[CLOSED]'}")
    print(f"Pump:            {'ON ' if status['pump_running'] else 'OFF'}")
    print(f"Mode:            {'AUTO' if status['auto_mode'] else 'MANUAL'}")

    if status['alarm_overflow']:
        print(f"[!]  ALARM: OVERFLOW!")
    if status['alarm_low_level']:
        print(f"[!]  ALARM: LOW LEVEL!")
    print(f"{'='*50}")


def test_automatic_mode():
    """Test automatic mode operation"""
    print("\n" + "="*60)
    print("TEST 1: Automatic Mode Operation")
    print("="*60)

    tank = WaterTank()
    tank.water_level = 50.0  # Start at 50%

    print("\nStarting with 50% water level in AUTO mode...")
    print("The tank will self-regulate between 20-80%")
    print("Running for 30 seconds...\n")

    for i in range(30):
        tank.update()
        if i % 5 == 0:  # Print every 5 seconds
            print_status(tank)
        time.sleep(1)

    print("\n[+] Automatic mode test completed")


def test_low_level_protection():
    """Test low level protection"""
    print("\n" + "="*60)
    print("TEST 2: Low Level Protection")
    print("="*60)

    tank = WaterTank()
    tank.water_level = 15.0  # Start at 15%

    print("\nStarting with 15% water level (below auto-fill threshold)")
    print("System should automatically fill the tank...")
    print("Running for 30 seconds...\n")

    for i in range(30):
        tank.update()
        if i % 5 == 0:
            print_status(tank)
        time.sleep(1)

    print("\n[+] Low level protection test completed")


def test_overflow_protection():
    """Test overflow protection"""
    print("\n" + "="*60)
    print("TEST 3: Overflow Protection")
    print("="*60)

    tank = WaterTank()
    tank.water_level = 90.0  # Start at 90%
    tank.inlet_valve_position = 100.0  # Force inlet open
    tank.pump_running = True

    print("\nStarting with 90% water level, inlet open, pump ON")
    print("System should trigger overflow protection at 98%...")
    print("Running for 30 seconds...\n")

    for i in range(30):
        tank.update()
        if i % 5 == 0:
            print_status(tank)
        time.sleep(1)

    print("\n[+] Overflow protection test completed")


def test_manual_mode():
    """Test manual mode operation"""
    print("\n" + "="*60)
    print("TEST 4: Manual Mode Control")
    print("="*60)

    tank = WaterTank()
    tank.water_level = 50.0
    tank.set_auto_mode(False)  # Switch to manual

    print("\nStarting in MANUAL mode at 50%")
    print_status(tank)

    print("\n[Action] Opening inlet valve manually...")
    tank.set_inlet_valve(True)
    for i in range(10):
        tank.update()
        time.sleep(1)
    print_status(tank)

    print("\n[Action] Starting pump...")
    tank.set_pump(True)
    for i in range(10):
        tank.update()
        time.sleep(1)
    print_status(tank)

    print("\n[Action] Closing inlet valve, opening outlet valve...")
    tank.set_inlet_valve(False)
    tank.set_outlet_valve(True)
    for i in range(10):
        tank.update()
        time.sleep(1)
    print_status(tank)

    print("\n[Action] Stopping all equipment...")
    tank.set_pump(False)
    tank.set_outlet_valve(False)
    for i in range(5):
        tank.update()
        time.sleep(1)
    print_status(tank)

    print("\n[+] Manual mode test completed")


def test_mode_switching():
    """Test switching between auto and manual modes"""
    print("\n" + "="*60)
    print("TEST 5: Mode Switching")
    print("="*60)

    tank = WaterTank()
    tank.water_level = 50.0

    print("\nStarting in AUTO mode...")
    print_status(tank)

    print("\n[Action] Switching to MANUAL mode...")
    tank.set_auto_mode(False)
    tank.set_inlet_valve(True)
    for i in range(10):
        tank.update()
        time.sleep(1)
    print_status(tank)

    print("\n[Action] Switching back to AUTO mode...")
    tank.set_auto_mode(True)
    for i in range(10):
        tank.update()
        time.sleep(1)
    print_status(tank)

    print("\n[+] Mode switching test completed")


def interactive_mode():
    """Interactive mode for manual testing"""
    print("\n" + "="*60)
    print("INTERACTIVE MODE")
    print("="*60)

    tank = WaterTank()

    print("\nCommands:")
    print("  a - Toggle Auto/Manual mode")
    print("  i - Toggle inlet valve (manual mode)")
    print("  o - Toggle outlet valve (manual mode)")
    print("  p - Toggle pump (manual mode)")
    print("  s - Show status")
    print("  q - Quit")
    print("\nTank will update automatically every second")

    import threading

    def update_loop():
        while not stop_event.is_set():
            tank.update()
            time.sleep(1)

    stop_event = threading.Event()
    update_thread = threading.Thread(target=update_loop, daemon=True)
    update_thread.start()

    try:
        while True:
            print_status(tank)
            cmd = input("\nCommand: ").lower().strip()

            if cmd == 'q':
                break
            elif cmd == 'a':
                new_mode = not tank.get_auto_mode()
                tank.set_auto_mode(new_mode)
                print(f"Mode switched to {'AUTO' if new_mode else 'MANUAL'}")
            elif cmd == 'i':
                if not tank.get_auto_mode():
                    new_state = not tank.get_inlet_valve_status()
                    tank.set_inlet_valve(new_state)
                    print(f"Inlet valve {'opened' if new_state else 'closed'}")
                else:
                    print("Cannot control in AUTO mode")
            elif cmd == 'o':
                if not tank.get_auto_mode():
                    new_state = not tank.get_outlet_valve_status()
                    tank.set_outlet_valve(new_state)
                    print(f"Outlet valve {'opened' if new_state else 'closed'}")
                else:
                    print("Cannot control in AUTO mode")
            elif cmd == 'p':
                if not tank.get_auto_mode():
                    new_state = not tank.get_pump_status()
                    tank.set_pump(new_state)
                    print(f"Pump {'started' if new_state else 'stopped'}")
                else:
                    print("Cannot control in AUTO mode")
            elif cmd == 's':
                pass  # Status will be printed in next loop
            else:
                print("Unknown command")

            time.sleep(0.5)

    except KeyboardInterrupt:
        print("\nExiting...")
    finally:
        stop_event.set()


def main():
    """Main test runner"""
    print("\n" + "#"*60)
    print("#" + " "*58 + "#")
    print("#" + "  WATER TANK SIMULATION - STANDALONE TEST SUITE  ".center(58) + "#")
    print("#" + " "*58 + "#")
    print("#"*60)

    print("\nThis test suite demonstrates the water tank simulation")
    print("without requiring IEC-104 library dependencies.\n")

    tests = [
        ("1", "Automatic Mode Operation", test_automatic_mode),
        ("2", "Low Level Protection", test_low_level_protection),
        ("3", "Overflow Protection", test_overflow_protection),
        ("4", "Manual Mode Control", test_manual_mode),
        ("5", "Mode Switching", test_mode_switching),
        ("i", "Interactive Mode", interactive_mode),
        ("a", "Run All Tests", None),
    ]

    print("Available Tests:")
    for key, name, _ in tests:
        print(f"  {key} - {name}")
    print(f"  q - Quit")

    choice = input("\nSelect test (or 'a' for all): ").lower().strip()

    if choice == 'q':
        print("Exiting...")
        return

    if choice == 'a':
        for key, name, func in tests:
            if func and key != 'i':
                func()
                time.sleep(2)
        print("\n" + "="*60)
        print("ALL TESTS COMPLETED")
        print("="*60)
    else:
        for key, name, func in tests:
            if key == choice and func:
                func()
                break
        else:
            print("Invalid choice")


if __name__ == "__main__":
    main()
