#!/bin/bash
# Run BlackEnergy 3 attack (IEC-104 overflow + KillDisk wiper simultaneously)
#
# Requires: PLC running on port 2404, HMI running with KillDisk listener (port 4444)
#
# Usage: ./run_blackenergy3_attack.sh

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
cd "$SCRIPT_DIR"

PLC_IP="${PLC_IP:-127.0.0.1}"
PLC_PORT="${PLC_PORT:-2404}"
HMI_IP="${HMI_IP:-127.0.0.1}"
HMI_PORT="${HMI_PORT:-4444}"
DURATION="${1:-60}"

if [ -d "venv_hmi" ]; then source venv_hmi/bin/activate
elif [ -d "venv" ]; then source venv/bin/activate; fi

echo "======================================================================"
echo "  BLACKENERGY 3 ATTACK"
echo "  PLC: ${PLC_IP}:${PLC_PORT} (IEC-104)"
echo "  HMI: ${HMI_IP}:${HMI_PORT} (KillDisk)"
echo "======================================================================"

python3 perform_malware_simulations/blackenergy3_simulation.py \
    --plc-ip ${PLC_IP} --plc-port ${PLC_PORT} \
    --hmi-ip ${HMI_IP} --hmi-port ${HMI_PORT} \
    --duration ${DURATION}
