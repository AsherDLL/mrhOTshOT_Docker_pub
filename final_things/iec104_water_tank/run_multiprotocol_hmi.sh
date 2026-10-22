#!/bin/bash
#
# Multi-Protocol HMI Launcher
#
# Usage:
#   ./run_multiprotocol_hmi.sh iec104
#   ./run_multiprotocol_hmi.sh s7 --port 1102
#   ./run_multiprotocol_hmi.sh modbus
#   ./run_multiprotocol_hmi.sh opcua
#
source env/bin/activate
# Check if protocol argument is provided
if [ -z "$1" ]; then
    echo "Usage: $0 <protocol> [options]"
    echo ""
    echo "Protocols:"
    echo "  iec104  - IEC 60870-5-104"
    echo "  s7      - Siemens S7"
    echo "  modbus  - Modbus TCP"
    echo "  opcua   - OPC-UA"
    echo ""
    echo "Examples:"
    echo "  $0 iec104"
    echo "  $0 s7 --port 1102"
    echo "  $0 modbus --host 192.168.1.100"
    echo "  $0 opcua"
    exit 1
fi

python -m hmi.multiprotocol_hmi "$@"
