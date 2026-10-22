#!/bin/bash
# Run the full Triton demo: start lab, run direct attack, restart, run Triton attack
#
# This script runs both attack scenarios back-to-back:
#   1. Direct attack (SIS blocks it)
#   2. Triton attack (SIS disabled, tank explodes)
#
# Usage: ./run_full_demo.sh [--no-hmi]

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
cd "$SCRIPT_DIR"

PLC_IP="${PLC_IP:-127.0.0.1}"
PLC_PORT="${PLC_PORT:-2404}"
SIS_IP="${SIS_IP:-127.0.0.1}"
SIS_PORT="${SIS_PORT:-1502}"
SIS_THRESHOLD="${SIS_THRESHOLD:-90}"
SKIP_HMI=false

for arg in "$@"; do
    case $arg in
        --no-hmi) SKIP_HMI=true ;;
    esac
done

# Activate venv
if [ -d "venv_hmi" ]; then
    source venv_hmi/bin/activate
elif [ -d "venv" ]; then
    source venv/bin/activate
fi

start_lab() {
    echo "[*] Cleaning up..."
    lsof -t -i :${PLC_PORT} 2>/dev/null | xargs kill 2>/dev/null
    lsof -t -i :${SIS_PORT} 2>/dev/null | xargs kill 2>/dev/null
    sleep 2

    echo "[*] Starting PLC..."
    python3 water_tank_server.py --protocol iec104 --port ${PLC_PORT} --with-sis --sis-ip ${SIS_IP} > /tmp/plc_server.log 2>&1 &
    echo $! > /tmp/triton_lab_plc.pid
    sleep 2

    echo "[*] Starting SIS..."
    python3 triconex_sis_server.py --plc-ip ${SIS_IP} --plc-port ${PLC_PORT} --sis-port ${SIS_PORT} --threshold ${SIS_THRESHOLD} > /tmp/sis_server.log 2>&1 &
    echo $! > /tmp/triton_lab_sis.pid
    sleep 4

    echo "[+] Lab ready"
}

stop_lab() {
    [ -f /tmp/triton_lab_plc.pid ] && kill $(cat /tmp/triton_lab_plc.pid) 2>/dev/null
    [ -f /tmp/triton_lab_sis.pid ] && kill $(cat /tmp/triton_lab_sis.pid) 2>/dev/null
    lsof -t -i :${PLC_PORT} 2>/dev/null | xargs kill 2>/dev/null
    lsof -t -i :${SIS_PORT} 2>/dev/null | xargs kill 2>/dev/null
    sleep 2
}

echo "======================================================================"
echo "  TRITON/SIS FULL DEMO"
echo "======================================================================"
echo "  Wireshark: capture on lo0, filter: udp port 1502 or tcp port 2404"
echo "======================================================================"
echo
echo "Press Enter to start Scenario 1 (Direct Attack - SIS blocks it)..."
read

# =========================================================================
# SCENARIO 1: Direct Attack (SIS should block it)
# =========================================================================
echo
echo "######################################################################"
echo "  SCENARIO 1: DIRECT ATTACK (SIS SHOULD BLOCK)"
echo "######################################################################"
echo

start_lab

if [ "$SKIP_HMI" = false ]; then
    echo "[*] Starting HMI in background..."
    python3 hmi/hmi_client.py --sis-ip ${SIS_IP} --sis-port ${SIS_PORT} &
    HMI_PID=$!
    sleep 3
fi

echo
echo "[*] Running direct attack..."
echo
python3 perform_malware_simulations/direct_water_tank_attack.py \
    --target ${PLC_IP} --port ${PLC_PORT} --duration 30

[ -n "$HMI_PID" ] && kill $HMI_PID 2>/dev/null
stop_lab

echo
echo "######################################################################"
echo "  SCENARIO 1 COMPLETE"
echo "  Result: SIS tripped and blocked the overflow"
echo "######################################################################"
echo
echo "Press Enter to start Scenario 2 (Triton Attack - SIS disabled)..."
read

# =========================================================================
# SCENARIO 2: Triton Attack (SIS disabled, tank explodes)
# =========================================================================
echo
echo "######################################################################"
echo "  SCENARIO 2: TRITON ATTACK (SIS WILL BE DISABLED)"
echo "######################################################################"
echo

start_lab

if [ "$SKIP_HMI" = false ]; then
    echo "[*] Starting HMI in background..."
    python3 hmi/hmi_client.py --sis-ip ${SIS_IP} --sis-port ${SIS_PORT} &
    HMI_PID=$!
    sleep 3
fi

echo
echo "[*] Running Triton attack..."
echo
python3 perform_malware_simulations/triton_simulation.py \
    --sis-ip ${SIS_IP} --sis-port ${SIS_PORT} \
    --plc-ip ${PLC_IP} --plc-port ${PLC_PORT} \
    --duration 60

[ -n "$HMI_PID" ] && kill $HMI_PID 2>/dev/null
stop_lab

echo
echo "######################################################################"
echo "  SCENARIO 2 COMPLETE"
echo "  Result: SIS disabled by Triton, tank exploded"
echo "######################################################################"
echo
echo "======================================================================"
echo "  FULL DEMO COMPLETE"
echo "======================================================================"
echo "  Scenario 1: Direct attack -> BLOCKED by SIS"
echo "  Scenario 2: Triton attack -> SIS disabled -> TANK EXPLODED"
echo "======================================================================"
