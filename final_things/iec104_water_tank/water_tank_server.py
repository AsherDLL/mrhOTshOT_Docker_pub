#!/usr/bin/env python3
"""
Multi-Protocol Water Tank Server

Unified server launcher supporting multiple industrial protocols:
- IEC 60870-5-104 (SCADA)
- Siemens S7 (PLC)
- Modbus TCP (Industrial Automation)
- OPC-UA (Industry 4.0)

Usage:
    python water_tank_server.py --protocol iec104
    python water_tank_server.py --protocol s7
    python water_tank_server.py --protocol modbus
    python water_tank_server.py --protocol opcua
"""

import argparse
import signal
import sys
import time
import logging
from logging.handlers import RotatingFileHandler
import threading
from typing import Optional

# Add parent directory to path
import os
sys.path.append(os.path.dirname(os.path.abspath(__file__)))

from server.water_tank import WaterTank
from server.protocol_adapter import ProtocolType
from common.config import *


class MultiProtocolWaterTankServer:
    """
    Multi-protocol water tank server

    Supports running water tank simulation with different industrial protocols
    """

    def __init__(self, protocol: str, config: dict = None, process: str = None):
        """
        Initialize multi-protocol server

        Args:
            protocol: Protocol type ('iec104', 's7', 'modbus', 'opcua', 'dnp3',
                      'iec61850', 'bacnet', or 'all')
            config: Optional protocol-specific configuration
            process: Process type for --process mode (runs all protocols for that process)
        """
        self.protocol = protocol.lower()
        self.process_filter = process
        self.config = config or {}
        self.water_tank = None
        self.adapter = None       # single-protocol mode
        self.adapters = []        # all-protocol mode
        self.plant = None         # PlantSimulator for --all mode
        self.running = False
        self.sim_thread = None

        # Setup logging
        logging.basicConfig(
            level=logging.INFO,
            format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
            handlers=[
                RotatingFileHandler(LOG_FILE, maxBytes=10*1024*1024, backupCount=2),
                logging.StreamHandler()
            ]
        )
        self.logger = logging.getLogger("MultiProtocolServer")

    # Protocol registry: name -> (import_path, class_name, default_port, config_overrides)
    PROTOCOL_REGISTRY = {
        'iec104':   ('server.iec104_adapter',   'IEC104Adapter',   2404,  {}),
        's7':       ('server.s7_adapter',       'S7Adapter',       102,   {}),
        'modbus':   ('server.modbus_adapter',   'ModbusAdapter',   502,   {}),
        'opcua':    ('server.opcua_adapter',    'OPCUAAdapter',    4840,  {}),
        'dnp3':     ('server.dnp3_adapter',     'DNP3Adapter',     20000, {}),
        'iec61850': ('server.iec61850_adapter', 'IEC61850Adapter', 8102,  {}),
        'bacnet':   ('server.bacnet_adapter',   'BACnetAdapter',   47808, {}),
        'fins':     ('server.fins_adapter',     'FINSAdapter',     9600,  {}),
        'mbus':     ('server.mbus_adapter',     'MBusAdapter',     5000,  {}),
        'tristation': ('server.tristation_adapter', 'TriStationAdapter', 1502, {}),
        'enip':      ('server.enip_adapter',      'EtherNetIPAdapter', 44818, {}),
        'melsec':    ('server.melsec_adapter',     'MELSECAdapter',    5007,  {}),
        'abb':       ('server.abb_adapter',        'ABBAdapter',       5020,  {}),
    }

    def _create_adapter(self, proto_name: str, water_tank, config: dict):
        """Create a single protocol adapter by name."""
        if proto_name not in self.PROTOCOL_REGISTRY:
            return None
        mod_path, cls_name, default_port, extra = self.PROTOCOL_REGISTRY[proto_name]
        import importlib
        mod = importlib.import_module(mod_path)
        cls = getattr(mod, cls_name)
        cfg = dict(config)
        cfg.setdefault('port', default_port)
        cfg.update(extra)
        return cls(water_tank, cfg)

    def initialize(self) -> bool:
        """Initialize water tank and protocol adapter(s)"""
        try:
            self.water_tank = WaterTank()
            self.logger.info("Water tank initialized (realistic physics)")

            if self.protocol == 'all' or self.process_filter:
                return self._initialize_all()

            # Single protocol mode
            self.adapter = self._create_adapter(self.protocol, self.water_tank, self.config)
            if self.adapter is None:
                self.logger.error(f"Unsupported protocol: {self.protocol}")
                return False

            if not self.adapter.initialize():
                self.logger.error("Failed to initialize protocol adapter")
                return False

            return True

        except ImportError as e:
            self.logger.error(f"Failed to import protocol adapter (missing dependency?): {e}")
            return False
        except Exception as e:
            self.logger.error(f"Initialization failed: {e}")
            import traceback
            traceback.print_exc()
            return False

    def _initialize_all(self) -> bool:
        """Initialize protocols - all, or filtered by --process type."""
        from server.plant import PlantSimulator, PROTOCOL_PROCESS_MAP

        # Extra protocols each process should also run (in addition to PROTOCOL_PROCESS_MAP)
        EXTRA_PROCESS_PROTOCOLS = {
            # Power substation runs IEC-61850 (protection relay communication) AND
            # IEC-104 (SCADA data exchange with EMS/energy management system).
            # Both coexist in real substations. IEC-104 is the Industroyer2/BlackEnergy3
            # attack surface. Not a compatibility shim - architecturally correct.
            # + Modbus: the operator HMI (FUXA) monitors the substation over Modbus
            # while Industroyer2 attacks over IEC-104 - same process instance, so the
            # operator's screen reacts to the attack (operator-blinding demo).
            'power_substation': ['iec104', 'modbus'],
            # Safety system runs TriStation (proprietary Triconex protocol, UDP:1502) AND
            # IEC-104 (SCADA monitoring channel, TCP:2404). Real Triconex installations
            # expose SIS data to DCS/SCADA via standard protocols alongside TriStation.
            # IEC-104 channel is the TRITON Phase 3 attack surface (process manipulation
            # after SIS is disabled - operators lose safety trip protection).
            'safety_system': ['iec104'],
        }

        # Process-specific Modbus configuration overrides.
        # heating_district emulates ENCO ENC-12X district heating controller:
        #   slave_id=11  (ENCO default - FrostyGoop targets slave 11)
        #   enco_scaling (×10 integer encoding: 75.3°C → register value 753)
        PROCESS_MODBUS_CONFIG = {
            'heating_district': {'slave_id': 11, 'enco_scaling': True},
        }

        if self.process_filter:
            self.logger.info("=" * 70)
            self.logger.info(f"  STARTING PROCESS: {self.process_filter.upper()}")
            self.logger.info("=" * 70)
            target_protocols = {
                p for p, pt in PROTOCOL_PROCESS_MAP.items()
                if pt == self.process_filter
            }
            # Add extra protocols for this process
            for extra in EXTRA_PROCESS_PROTOCOLS.get(self.process_filter, []):
                target_protocols.add(extra)
            self.logger.info(f"  Protocols: {', '.join(sorted(target_protocols))}")
        else:
            self.logger.info("=" * 70)
            self.logger.info("  STARTING MULTI-PROCESS INDUSTRIAL PLANT")
            self.logger.info("=" * 70)
            self.logger.info("  IEC-104/Modbus/DNP3   -> Water Treatment")
            self.logger.info("  IEC 61850/GOOSE       -> Power Substation")
            self.logger.info("  OPC-UA/FINS/MELSEC    -> Gas Pipeline")
            self.logger.info("  Siemens S7/EtherNet/IP -> Manufacturing")
            self.logger.info("  BACnet                -> Building HVAC")
            self.logger.info("  ABB Modbus            -> Boiler House")
            target_protocols = None

        self.logger.info("=" * 70)

        self.plant = PlantSimulator()
        host = self.config.get('host', '0.0.0.0')
        success = 0
        total = 0

        for name, (mod_path, cls_name, default_port, _) in self.PROTOCOL_REGISTRY.items():
            # Skip protocols not matching --process filter
            if target_protocols is not None and name not in target_protocols:
                continue
            total += 1
            try:
                # In --process mode every protocol serves that one process (so the
                # power substation answers on both IEC-104 and IEC-61850). Otherwise
                # each protocol serves its native process.
                if self.process_filter:
                    process_type = self.process_filter
                    process = self.plant.get_process_by_type(process_type)
                else:
                    process = self.plant.get_process_for_protocol(name)
                    process_type = PROTOCOL_PROCESS_MAP.get(name, 'water_treatment')
                cfg = {'host': host, 'port': default_port, 'process_type': process_type}
                # Merge process-specific Modbus overrides (e.g. ENCO slave_id/scaling)
                if name == 'modbus' and self.process_filter in PROCESS_MODBUS_CONFIG:
                    cfg.update(PROCESS_MODBUS_CONFIG[self.process_filter])
                if name == 'iec104':
                    cfg['common_address'] = self.config.get('common_address', 1)
                    cfg['with_sis'] = self.config.get('with_sis', False)
                    cfg['sis_ip'] = self.config.get('sis_ip', '127.0.0.1')

                # CentrifugeCascade uses its own specialised S7 adapter
                from server.plant import CentrifugeCascade
                if isinstance(process, CentrifugeCascade) and name == 's7':
                    from server.s7_centrifuge_adapter import S7CentrifugeAdapter
                    adapter = S7CentrifugeAdapter(process, cfg)
                else:
                    adapter = self._create_adapter(name, process, cfg)
                if adapter and adapter.initialize():
                    process_type = PROTOCOL_PROCESS_MAP.get(name, '?')
                    self.adapters.append((name, default_port, adapter))
                    self.logger.info(f"  [+] {name:10s}  port {default_port:5d}  -> {process_type}")
                    success += 1
                else:
                    self.logger.warning(f"  [-] {name:10s}  init failed")
            except Exception as e:
                self.logger.warning(f"  [-] {name:10s}  {e}")

        self.logger.info(f"  Initialized {success}/{total} protocols across {len(self.plant.processes)} processes")
        return success > 0

    def start(self) -> bool:
        """Start server"""
        try:
            self.logger.info("="*80)
            self.logger.info(f"Starting Water Tank Server - Protocol: {self.protocol.upper()}")
            self.logger.info("="*80)

            if self.protocol == 'all' or self.process_filter:
                # Start all adapters
                for name, port, adapter in self.adapters:
                    try:
                        if adapter.start():
                            self.logger.info(f"  [+] {name} started on port {port}")
                        else:
                            self.logger.warning(f"  [-] {name} failed to start")
                    except Exception as e:
                        self.logger.warning(f"  [-] {name} error: {e}")
            else:
                # Start single protocol adapter
                if not self.adapter.start():
                    self.logger.error("Failed to start protocol adapter")
                    return False

            # Start water tank simulation
            self.running = True
            self.sim_thread = threading.Thread(
                target=self._simulation_loop,
                daemon=True,
                name="WaterTankSimThread"
            )
            self.sim_thread.start()

            self.logger.info("="*80)
            self.logger.info("SERVER STARTED SUCCESSFULLY")
            self.logger.info("="*80)

            # Print protocol-specific information
            self._print_protocol_info()

            return True

        except Exception as e:
            self.logger.error(f"Failed to start server: {e}")
            return False

    def _simulation_loop(self):
        """Run process simulation loop"""
        while self.running:
            try:
                if hasattr(self, 'plant') and self.plant:
                    self.plant.update_all()
                elif self.water_tank:
                    self.water_tank.update()
                time.sleep(SIMULATION_TICK_RATE)
            except Exception as e:
                self.logger.error(f"Simulation error: {e}")
                time.sleep(1)

    def _print_protocol_info(self):
        """Print protocol-specific connection information"""
        print("")
        print("="*80)
        print("PROTOCOL INFORMATION")
        print("="*80)

        if self.protocol == 'all' or self.process_filter:
            mode = f"PROCESS: {self.process_filter}" if self.process_filter else "ALL PROTOCOLS"
            print(f"Mode: {mode}")
            print(f"Host: {self.config.get('host', '0.0.0.0')}")
            print(f"\nRunning protocols:")
            for name, port, adapter in self.adapters:
                print(f"  {name:12s}  port {port}")
            print(f"\nAll protocols share the same physics simulation.")
            print(f"An attacker on any protocol sees the same physical process.")

        elif self.protocol == 'iec104':
            print(f"Protocol: IEC 60870-5-104")
            print(f"Endpoint: {self.config.get('host', IEC104_HOST)}:{self.config.get('port', IEC104_PORT)}")
            print(f"Common Address: {self.config.get('common_address', COMMON_ADDRESS)}")
            print(f"\nConnection example:")
            print(f"  IEC-104 Client -> {self.config.get('host', IEC104_HOST)}:{self.config.get('port', IEC104_PORT)}")
            if hasattr(self.adapter, 'get_ioa_map'):
                print(f"\nIOA Mapping:")
                print(self.adapter.get_ioa_map())

        elif self.protocol == 's7':
            print(f"Protocol: Siemens S7")
            print(f"Endpoint: {self.config.get('host', '0.0.0.0')}:{self.config.get('port', 102)}")
            print(f"Rack: {self.config.get('rack', 0)}, Slot: {self.config.get('slot', 1)}")
            print(f"\nConnection example (using snap7):")
            print(f"  import snap7")
            print(f"  plc = snap7.client.Client()")
            print(f"  plc.connect('{self.config.get('host', '0.0.0.0')}', {self.config.get('rack', 0)}, {self.config.get('slot', 1)})")
            if hasattr(self.adapter, 'get_db_layout'):
                print(f"\nData Block Layout:")
                print(self.adapter.get_db_layout())

        elif self.protocol == 'modbus':
            print(f"Protocol: Modbus TCP")
            print(f"Endpoint: {self.config.get('host', '0.0.0.0')}:{self.config.get('port', 502)}")
            print(f"Slave ID: {self.config.get('slave_id', 1)}")
            print(f"\nConnection example (using pymodbus):")
            print(f"  from pymodbus.client import ModbusTcpClient")
            print(f"  client = ModbusTcpClient('{self.config.get('host', '0.0.0.0')}', port={self.config.get('port', 502)})")
            if hasattr(self.adapter, 'get_register_map'):
                print(f"\nRegister Map:")
                print(self.adapter.get_register_map())

        elif self.protocol == 'opcua':
            print(f"Protocol: OPC-UA")
            print(f"Endpoint: opc.tcp://{self.config.get('host', '0.0.0.0')}:{self.config.get('port', 4840)}/freeopcua/server/")
            print(f"Namespace: {self.config.get('namespace', 'http://watertank.local')}")
            print(f"\nConnection example (using opcua):")
            print(f"  from opcua import Client")
            print(f"  client = Client('opc.tcp://{self.config.get('host', '0.0.0.0')}:{self.config.get('port', 4840)}/freeopcua/server/')")
            print(f"  client.connect()")
            if hasattr(self.adapter, 'get_node_tree'):
                print(f"\nNode Tree:")
                print(self.adapter.get_node_tree())

        elif self.protocol == 'dnp3':
            print(f"Protocol: DNP3 (Distributed Network Protocol 3)")
            print(f"Endpoint: {self.config.get('host', '0.0.0.0')}:{self.config.get('port', 20000)}")
            print(f"Outstation Address: {self.config.get('outstation_address', 1)}")
            print(f"\nDNP3 is the dominant SCADA protocol in North American power/water utilities.")

        elif self.protocol == 'iec61850':
            print(f"Protocol: IEC 61850 (MMS + GOOSE)")
            print(f"MMS Endpoint: {self.config.get('host', '0.0.0.0')}:{self.config.get('port', 8102)}")
            print(f"GOOSE Endpoint: {self.config.get('host', '0.0.0.0')}:{self.config.get('goose_port', 61850)}")
            print(f"Logical Device: WaterTankLD")
            print(f"\nIEC 61850 GOOSE was exploited by Industroyer (2016) to trip circuit breakers.")

        elif self.protocol == 'bacnet':
            print(f"Protocol: BACnet/IP (Building Automation and Control Networks)")
            print(f"Endpoint: {self.config.get('host', '0.0.0.0')}:{self.config.get('port', 47808)} (UDP)")
            print(f"Device Instance: 1000")
            print(f"\nBACnet is the standard protocol for HVAC and building automation systems.")

        # SIS information
        if self.config.get('with_sis'):
            print(f"\nSIS Integration: ENABLED")
            print(f"  SIS Server IP: {self.config.get('sis_ip', '192.168.1.8')}")
            print(f"  SIS Trip Command IOA: 304")
            print(f"  SIS Trip Status IOA: 208")
            print(f"  The SIS server can send trip commands to force safe state")
        else:
            print(f"\nSIS Integration: DISABLED (use --with-sis to enable)")

        print("="*80)
        print("")

    def stop(self):
        """Stop server"""
        self.logger.info("Stopping server...")
        self.running = False

        if self.sim_thread:
            self.sim_thread.join(timeout=2)

        if self.adapter:
            self.adapter.stop()

        for name, port, adapter in self.adapters:
            try:
                adapter.stop()
            except Exception:
                pass

        self.logger.info("Server stopped")

    def run(self):
        """Run server (blocking)"""
        # Setup signal handlers
        signal.signal(signal.SIGINT, self._signal_handler)
        signal.signal(signal.SIGTERM, self._signal_handler)

        if not self.initialize():
            sys.exit(1)

        if not self.start():
            sys.exit(1)

        # Keep running until interrupted
        try:
            while self.running:
                time.sleep(1)
        except KeyboardInterrupt:
            pass

        self.stop()

    def _signal_handler(self, signum, frame):
        """Handle shutdown signals"""
        self.logger.info(f"Received signal {signum}, shutting down...")
        self.running = False


def main():
    """Main entry point"""
    parser = argparse.ArgumentParser(
        description="Multi-Protocol Water Tank Server",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Protocol Options:
  iec104    IEC 60870-5-104 (SCADA protocol)
  s7        Siemens S7 (PLC protocol)
  modbus    Modbus TCP (Industrial automation)
  opcua     OPC-UA (Industry 4.0)

Examples:
  # IEC-104 server on default port 2404
  python water_tank_server.py --protocol iec104

  # Modbus server on custom port
  python water_tank_server.py --protocol modbus --port 5020

  # S7 server with custom rack/slot
  python water_tank_server.py --protocol s7 --rack 0 --slot 2

  # OPC-UA server
  python water_tank_server.py --protocol opcua --port 4840

Dependencies:
  iec104: c104 (already included)
  s7:     pip install python-snap7
  modbus: pip install pymodbus
  opcua:  pip install asyncua
        """
    )

    parser.add_argument(
        '--protocol', '-p',
        type=str,
        choices=['iec104', 's7', 'modbus', 'opcua', 'dnp3', 'iec61850', 'bacnet', 'fins', 'mbus', 'tristation', 'enip', 'melsec', 'abb', 'all'],
        help='Protocol to use (or "all" to start entire plant with all processes)'
    )

    parser.add_argument(
        '--process',
        type=str,
        choices=['water_treatment', 'power_substation', 'gas_pipeline', 'manufacturing', 'building_hvac', 'boiler_house',
                 'heating_district', 'water_utility_dnp3', 'sensor_network', 'safety_system', 'centrifuge'],
        help='Start all protocols for a specific process (for distributed deployment)'
    )

    parser.add_argument(
        '--host',
        type=str,
        default='0.0.0.0',
        help='Bind address (default: 0.0.0.0)'
    )

    parser.add_argument(
        '--port',
        type=int,
        help='Port number (protocol-specific defaults)'
    )

    # S7-specific arguments
    parser.add_argument(
        '--rack',
        type=int,
        default=0,
        help='S7: Rack number (default: 0)'
    )

    parser.add_argument(
        '--slot',
        type=int,
        default=1,
        help='S7: Slot number (default: 1)'
    )

    # Modbus-specific arguments
    parser.add_argument(
        '--slave-id',
        type=int,
        default=1,
        help='Modbus: Slave ID (default: 1)'
    )

    # IEC-104 specific arguments
    parser.add_argument(
        '--common-address',
        type=int,
        default=1,
        help='IEC-104: Common Address (default: 1)'
    )

    # OPC-UA specific arguments
    parser.add_argument(
        '--namespace',
        type=str,
        default='http://watertank.local',
        help='OPC-UA: Namespace URI'
    )

    # SIS (Safety Instrumented System) arguments
    parser.add_argument(
        '--with-sis',
        action='store_true',
        default=False,
        help='Enable SIS integration (accepts trip commands from SIS server)'
    )

    parser.add_argument(
        '--sis-ip',
        type=str,
        default='192.168.1.8',
        help='SIS server IP address (default: 192.168.1.8)'
    )

    args = parser.parse_args()

    # Require either --protocol or --process
    if not args.protocol and not args.process:
        parser.error("Either --protocol or --process is required")

    # Build configuration
    config = {
        'host': args.host,
    }

    # Determine protocol mode
    protocol = args.protocol or 'all'

    # Set default ports if not specified
    if args.port:
        config['port'] = args.port
    else:
        default_ports = {
            'iec104': 2404, 's7': 102, 'modbus': 502, 'opcua': 4840,
            'dnp3': 20000, 'iec61850': 8102, 'bacnet': 47808,
            'fins': 9600, 'mbus': 5000, 'tristation': 1502,
            'enip': 44818, 'melsec': 5007, 'abb': 5020,
        }
        config['port'] = default_ports.get(protocol, 0)

    # Add protocol-specific config
    if protocol == 's7':
        config['rack'] = args.rack
        config['slot'] = args.slot
    elif protocol == 'modbus':
        config['slave_id'] = args.slave_id
    elif protocol == 'iec104':
        config['common_address'] = args.common_address
    elif protocol == 'opcua':
        config['namespace'] = args.namespace

    # SIS configuration
    config['with_sis'] = args.with_sis
    config['sis_ip'] = args.sis_ip

    # Create and run server
    server = MultiProtocolWaterTankServer(protocol, config, process=args.process)
    server.run()


if __name__ == "__main__":
    main()
