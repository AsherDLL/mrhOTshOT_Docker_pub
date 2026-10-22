#!/usr/bin/env python3
"""
Test script to diagnose IOA transmission issues
"""

import c104
import time

# Start server programmatically
print("[*] Starting test IEC-104 server...")
server = c104.Server(ip="127.0.0.1", port=2405)  # Use different port
station = server.add_station(common_address=1)

# Add just a few test IOAs
test_ioas = [1101, 1102, 130202, 260901]

def dummy_handler(point: c104.Point, previous_info: c104.Information, message: c104.IncomingMessage) -> c104.ResponseState:
    print(f"[SERVER] Received command for IOA {point.io_address} = {point.value}")
    return c104.ResponseState.SUCCESS

for ioa in test_ioas:
    point = station.add_point(
        io_address=ioa,
        type=c104.Type.C_DC_NA_1 if ioa < 2000 else c104.Type.C_SC_NA_1
    )
    point.on_receive(dummy_handler)
    print(f"[+] Server: Added IOA {ioa}")

server.start()
print("[+] Server started on port 2405")

time.sleep(2)

# Now connect as client
print("\n[*] Connecting as client...")
client = c104.Client()
connection = client.add_connection(
    ip="127.0.0.1",
    port=2405,
    init=c104.Init.ALL
)

connection.connect()
time.sleep(3)

if connection.is_connected:
    print("[+] Client connected")

    client_station = connection.add_station(common_address=1)

    # Try adding points on client side
    print("\n[*] Adding client-side command points...")
    for ioa in test_ioas:
        try:
            point = client_station.add_point(
                io_address=ioa,
                type=c104.Type.C_DC_NA_1 if ioa < 2000 else c104.Type.C_SC_NA_1
            )
            print(f"[+] Client: Added IOA {ioa}")

            # Try to send command
            point.value = c104.Double.ON if ioa < 2000 else True
            success = point.transmit(c104.Cot.ACTIVATION)
            print(f"    -> Transmit result: {success}")
            time.sleep(0.1)

        except Exception as e:
            print(f"[-] Failed to add/transmit IOA {ioa}: {e}")

    connection.disconnect()
else:
    print("[-] Client connection failed")

server.stop()
print("\n[*] Test complete")
