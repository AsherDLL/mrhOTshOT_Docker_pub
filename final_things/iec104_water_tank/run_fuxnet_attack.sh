#!/bin/bash
# Run Fuxnet attack against M-Bus sensor gateway
# Usage: ./run_fuxnet_attack.sh [--combo]

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
cd "$SCRIPT_DIR"

TARGET_IP="${TARGET_IP:-127.0.0.1}"
MBUS_PORT="${MBUS_PORT:-5000}"
PLC_IP="${PLC_IP:-127.0.0.1}"
PLC_PORT="${PLC_PORT:-2404}"
COMBO=""

for arg in "$@"; do
    case $arg in
        --combo) COMBO="--combo-attack --plc-ip ${PLC_IP} --plc-port ${PLC_PORT}" ;;
    esac
done

if [ -d "venv_hmi" ]; then source venv_hmi/bin/activate
elif [ -d "venv" ]; then source venv/bin/activate; fi

echo "======================================================================"
echo "  FUXNET ATTACK"
echo "  Target: ${TARGET_IP}:${MBUS_PORT}"
if [ -n "$COMBO" ]; then
echo "  Combo: + overflow attack on ${PLC_IP}:${PLC_PORT}"
fi
echo "======================================================================"

python3 perform_malware_simulations/fuxnet_simulation.py \
    --target ${TARGET_IP} --port ${MBUS_PORT} ${COMBO}
