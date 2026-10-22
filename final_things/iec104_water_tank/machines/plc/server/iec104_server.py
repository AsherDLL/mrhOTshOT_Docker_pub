"""
IEC-104 Server for Water Tank Simulation using c104 library
"""
import time
import logging
import threading
import sys
import os
from datetime import datetime
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import c104
from common.config import *
from server.water_tank import WaterTank


class IEC104Server:
    """IEC-104 Server that exposes water tank data and accepts control commands"""

    def __init__(self, water_tank):
        self.water_tank = water_tank
        self.server = None
        self.running = False

        # Setup logging
        logging.basicConfig(
            level=getattr(logging, LOG_LEVEL),
            format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
            handlers=[
                logging.FileHandler(LOG_FILE),
                logging.StreamHandler()
            ]
        )
        self.logger = logging.getLogger("IEC104Server")

        # Storage for data points
        self.points = {}

    def on_receive_raw(self, server: c104.Server, data: bytes) -> None:
        """Handle raw data received"""
        self.logger.debug(f"Received raw data: {data.hex()}")

    def on_receive_command(self, point: c104.Point, previous_info: c104.Information, message: c104.IncomingMessage) -> c104.ResponseState:
        """Handle commands from client"""
        self.logger.info(f"Command received - IOA: {point.io_address}, Value: {point.value}")

        ioa = point.io_address
        success = False

        # Single commands (on/off)
        if point.type == c104.Type.C_SC_NA_1:
            value = bool(point.value)

            if ioa == IOA_INLET_VALVE_COMMAND:
                success = self.water_tank.set_inlet_valve(value)
                self.logger.info(f"Inlet valve command: {value} - {'SUCCESS' if success else 'FAILED'}")

            elif ioa == IOA_OUTLET_VALVE_COMMAND:
                success = self.water_tank.set_outlet_valve(value)
                self.logger.info(f"Outlet valve command: {value} - {'SUCCESS' if success else 'FAILED'}")

            elif ioa == IOA_PUMP_COMMAND:
                success = self.water_tank.set_pump(value)
                self.logger.info(f"Pump command: {value} - {'SUCCESS' if success else 'FAILED'}")

            elif ioa == IOA_AUTO_MODE_COMMAND:
                success = self.water_tank.set_auto_mode(value)
                self.logger.info(f"Auto mode command: {value} - {'SUCCESS' if success else 'FAILED'}")

        # Setpoint commands (analog)
        elif point.type == c104.Type.C_SE_NC_1:
            value = float(point.value)

            if ioa == IOA_INLET_VALVE_SETPOINT:
                success = self.water_tank.set_inlet_valve_position(value)
                self.logger.info(f"Inlet valve setpoint: {value} - {'SUCCESS' if success else 'FAILED'}")

            elif ioa == IOA_OUTLET_VALVE_SETPOINT:
                success = self.water_tank.set_outlet_valve_position(value)
                self.logger.info(f"Outlet valve setpoint: {value} - {'SUCCESS' if success else 'FAILED'}")

        # Return SUCCESS if command was executed, FAILURE otherwise
        return c104.ResponseState.SUCCESS if success else c104.ResponseState.FAILURE

    def on_clock_sync(self, server: c104.Server, ip: str, date_time: datetime) -> c104.ResponseState:
        """Handle clock synchronization"""
        self.logger.debug(f"Clock sync from {ip}: {date_time}")
        return c104.ResponseState.SUCCESS

    def setup_data_points(self):
        """Setup all IEC-104 data points"""
        station = self.server.add_station(common_address=COMMON_ADDRESS)

        # Measurement points (M_ME_NB_1 - Scaled value with Int16, range: -32768 to 32767)
        self.points['water_level'] = station.add_point(
            io_address=IOA_WATER_LEVEL,
            type=c104.Type.M_ME_NB_1,
            report_ms=1000  # Report every second
        )

        self.points['pressure'] = station.add_point(
            io_address=IOA_PRESSURE,
            type=c104.Type.M_ME_NB_1,
            report_ms=1000
        )

        self.points['temperature'] = station.add_point(
            io_address=IOA_TEMPERATURE,
            type=c104.Type.M_ME_NB_1,
            report_ms=1000
        )

        # Status points (M_SP_NA_1 - Single point)
        self.points['inlet_valve_status'] = station.add_point(
            io_address=IOA_INLET_VALVE_STATUS,
            type=c104.Type.M_SP_NA_1,
            report_ms=1000
        )

        self.points['outlet_valve_status'] = station.add_point(
            io_address=IOA_OUTLET_VALVE_STATUS,
            type=c104.Type.M_SP_NA_1,
            report_ms=1000
        )

        self.points['pump_status'] = station.add_point(
            io_address=IOA_PUMP_STATUS,
            type=c104.Type.M_SP_NA_1,
            report_ms=1000
        )

        self.points['auto_mode_status'] = station.add_point(
            io_address=IOA_AUTO_MODE_STATUS,
            type=c104.Type.M_SP_NA_1,
            report_ms=1000
        )

        self.points['alarm_overflow'] = station.add_point(
            io_address=IOA_ALARM_OVERFLOW,
            type=c104.Type.M_SP_NA_1,
            report_ms=1000
        )

        self.points['alarm_low_level'] = station.add_point(
            io_address=IOA_ALARM_LOW_LEVEL,
            type=c104.Type.M_SP_NA_1,
            report_ms=1000
        )

        self.points['alarm_high_pressure'] = station.add_point(
            io_address=IOA_ALARM_HIGH_PRESSURE,
            type=c104.Type.M_SP_NA_1,
            report_ms=1000
        )

        self.points['tank_exploded'] = station.add_point(
            io_address=IOA_TANK_EXPLODED,
            type=c104.Type.M_SP_NA_1,
            report_ms=1000
        )

        # Command points (C_SC_NA_1 - Single command)
        cmd_inlet = station.add_point(
            io_address=IOA_INLET_VALVE_COMMAND,
            type=c104.Type.C_SC_NA_1
        )
        cmd_inlet.on_receive(callable=self.on_receive_command)

        cmd_outlet = station.add_point(
            io_address=IOA_OUTLET_VALVE_COMMAND,
            type=c104.Type.C_SC_NA_1
        )
        cmd_outlet.on_receive(callable=self.on_receive_command)

        cmd_pump = station.add_point(
            io_address=IOA_PUMP_COMMAND,
            type=c104.Type.C_SC_NA_1
        )
        cmd_pump.on_receive(callable=self.on_receive_command)

        cmd_auto = station.add_point(
            io_address=IOA_AUTO_MODE_COMMAND,
            type=c104.Type.C_SC_NA_1
        )
        cmd_auto.on_receive(callable=self.on_receive_command)

        # Setpoint command points (C_SE_NC_1 - Set point command short)
        setp_inlet = station.add_point(
            io_address=IOA_INLET_VALVE_SETPOINT,
            type=c104.Type.C_SE_NC_1
        )
        setp_inlet.on_receive(callable=self.on_receive_command)

        setp_outlet = station.add_point(
            io_address=IOA_OUTLET_VALVE_SETPOINT,
            type=c104.Type.C_SE_NC_1
        )
        setp_outlet.on_receive(callable=self.on_receive_command)

        self.logger.info("Data points configured successfully")

    def update_measurements(self):
        """Update measurement values from water tank"""
        while self.running:
            try:
                # Update measurement values (M_ME_NB_1 requires Int16)
                self.points['water_level'].value = c104.Int16(int(self.water_tank.get_water_level()))
                self.points['pressure'].value = c104.Int16(int(self.water_tank.get_pressure() * 10))  # Scale to preserve decimal
                self.points['temperature'].value = c104.Int16(int(self.water_tank.get_temperature()))

                # Update status points
                self.points['inlet_valve_status'].value = self.water_tank.get_inlet_valve_status()
                self.points['outlet_valve_status'].value = self.water_tank.get_outlet_valve_status()
                self.points['pump_status'].value = self.water_tank.get_pump_status()
                self.points['auto_mode_status'].value = self.water_tank.get_auto_mode()
                self.points['alarm_overflow'].value = self.water_tank.get_alarm_overflow()
                self.points['alarm_low_level'].value = self.water_tank.get_alarm_low_level()
                self.points['alarm_high_pressure'].value = self.water_tank.get_alarm_high_pressure()
                self.points['tank_exploded'].value = self.water_tank.get_tank_exploded()

            except Exception as e:
                self.logger.error(f"Error updating measurements: {e}")

            time.sleep(1.0)  # Update every second

    def start(self):
        """Start the IEC-104 server"""
        self.logger.info(f"Starting IEC-104 server on {IEC104_HOST}:{IEC104_PORT}")

        # Create server
        self.server = c104.Server(ip=IEC104_HOST, port=IEC104_PORT)

        # Set callbacks
        self.server.on_receive_raw(callable=self.on_receive_raw)
        self.server.on_clock_sync(callable=self.on_clock_sync)

        # Setup data points
        self.setup_data_points()

        # Start server
        self.server.start()
        self.running = True
        self.logger.info("IEC-104 server started successfully")

        # Start measurement update thread
        update_thread = threading.Thread(target=self.update_measurements, daemon=True)
        update_thread.start()

    def stop(self):
        """Stop the IEC-104 server"""
        self.logger.info("Stopping IEC-104 server")
        self.running = False
        if self.server:
            self.server.stop()
        self.logger.info("IEC-104 server stopped")


def main():
    """Main function to run the IEC-104 server"""
    # Create water tank simulation
    tank = WaterTank()

    # Create and start IEC-104 server
    server = IEC104Server(tank)
    server.start()

    # Start tank simulation loop
    try:
        print("Water Tank IEC-104 Server running...")
        print(f"Listening on {IEC104_HOST}:{IEC104_PORT}")
        print("Press Ctrl+C to stop\n")

        while True:
            tank.update()
            status = tank.get_status_dict()

            # Print status every 5 seconds
            if int(time.time()) % 5 == 0:
                print(f"\n=== Tank Status ===")
                print(f"Water Level: {status['water_level']:.1f}%")
                print(f"Pressure: {status['pressure']:.2f} bar")
                print(f"Temperature: {status['temperature']:.1f}°C")
                print(f"Inlet Valve: {status['inlet_valve_position']:.0f}%")
                print(f"Outlet Valve: {status['outlet_valve_position']:.0f}%")
                print(f"Pump: {'ON' if status['pump_running'] else 'OFF'}")
                print(f"Mode: {'AUTO' if status['auto_mode'] else 'MANUAL'}")
                if status['tank_exploded']:
                    print("CRITICAL: TANK EXPLODED!")
                if status['alarm_high_pressure']:
                    print("[!]  ALARM: HIGH PRESSURE!")
                if status['alarm_overflow']:
                    print("[!]  ALARM: OVERFLOW!")
                if status['alarm_low_level']:
                    print("[!]  ALARM: LOW LEVEL!")
                time.sleep(1)

            time.sleep(SIMULATION_TICK_RATE)

    except KeyboardInterrupt:
        print("\nShutting down...")
        server.stop()


if __name__ == "__main__":
    main()
