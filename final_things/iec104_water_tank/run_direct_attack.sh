#!/bin/bash
# Run direct water tank overflow attack (SIS should block this)
#
# This attack tries to overflow the water tank by opening the inlet valve,
# closing the drain, and running the pump at max.
#
# Expected result: SIS trips at 90% and forces safe state. Attack BLOCKED.

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
cd "$SCRIPT_DIR"

PLC_IP="${PLC_IP:-127.0.0.1}"
PLC_PORT="${PLC_PORT:-2404}"
DURATION="${1:-60}"

# Activate venv
if [ -d "venv_hmi" ]; then
    source venv_hmi/bin/activate
elif [ -d "venv" ]; then
    source venv/bin/activate
fi

echo "======================================================================"
echo "  DIRECT WATER TANK OVERFLOW ATTACK"
echo "  Expected: SIS trips and blocks the attack"
echo "======================================================================"
echo "  Target: ${PLC_IP}:${PLC_PORT}"
echo "  Duration: ${DURATION}s"
echo "======================================================================"
echo

python3 perform_malware_simulations/direct_water_tank_attack.py \
    --target ${PLC_IP} --port ${PLC_PORT} --duration ${DURATION}
