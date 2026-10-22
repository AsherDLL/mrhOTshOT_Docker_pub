"""
ABB AC500 PM583-ETH Modbus TCP Adapter

Thin subclass of ModbusAdapter that overrides device identification
to present as an ABB AC500 PLC controlling a boiler house.
Runs on port 5020 to coexist with the Schneider Modbus server on 502.
"""

import logging
from typing import Dict, Any

from server.modbus_adapter import ModbusAdapter


class ABBAdapter(ModbusAdapter):
    """
    ABB AC500 PM583-ETH Modbus TCP adapter.

    Identical wire protocol to ModbusAdapter but identifies as an ABB PLC
    via Modbus Device Identification (FC43/MEI).
    Default port: 5020.
    """

    def __init__(self, water_tank, config: Dict[str, Any]):
        # Default to port 5020 so it does not collide with the Schneider adapter
        config.setdefault('port', 5020)
        super().__init__(water_tank, config)
        self.logger = logging.getLogger('ABBAdapter')

    def initialize(self) -> bool:
        """Initialize Modbus server context, then replace identity with ABB AC500."""
        result = super().initialize()
        if not result:
            return False

        # Override device identification to ABB AC500
        if self.identity is not None:
            self.identity.VendorName = 'ABB'
            self.identity.ProductCode = 'PM583-ETH'
            self.identity.ProductName = 'AC500 PM583-ETH'
            self.identity.ModelName = 'PM583-ETH'
            self.identity.MajorMinorRevision = 'V3.1'
            self.identity.VendorUrl = 'https://www.abb.com'
            self.identity.UserApplicationName = 'Boiler Control PLC'

        self.logger.info(f"  PLC: ABB AC500 PM583-ETH")

        return True
