#!/bin/bash
# Start the Fuxnet M-Bus water tank lab
# Starts: PLC (port 2404), M-Bus Gateway (port 5000), and HMI (GUI)
# Usage: ./start_fuxnet_lab.sh [--no-hmi]

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
cd "$SCRIPT_DIR"

PLC_IP="${PLC_IP:-127.0.0.1}"
PLC_PORT="${PLC_PORT:-2404}"
MBUS_PORT="${MBUS_PORT:-5000}"
SKIP_HMI=false

for arg in "$@"; do
    case $arg in
        --no-hmi) SKIP_HMI=true ;;
    esac
done

if [ -d "venv_hmi" ]; then VENV="venv_hmi"
elif [ -d "venv" ]; then VENV="venv"
else echo "[!] No venv found."; exit 1; fi

echo "======================================================================"
echo "  FUXNET M-BUS WATER TANK LAB"
echo "======================================================================"
echo "  PLC:       ${PLC_IP}:${PLC_PORT} (IEC-104)"
echo "  M-Bus GW:  ${PLC_IP}:${MBUS_PORT} (M-Bus TCP)"
echo "======================================================================"
echo

echo "[*] Cleaning up..."
lsof -t -i :${PLC_PORT} 2>/dev/null | xargs kill 2>/dev/null
lsof -t -i :${MBUS_PORT} 2>/dev/null | xargs kill 2>/dev/null
sleep 1

source "${VENV}/bin/activate"

echo "[*] Starting PLC (port ${PLC_PORT})..."
python3 water_tank_server.py --protocol iec104 --port ${PLC_PORT} > /tmp/plc_server.log 2>&1 &
PLC_PID=$!
sleep 2

echo "[*] Starting M-Bus Gateway (port ${MBUS_PORT})..."
python3 mbus_gateway_server.py --plc-ip ${PLC_IP} --plc-port ${PLC_PORT} --mbus-port ${MBUS_PORT} > /tmp/mbus_gateway.log 2>&1 &
MBUS_PID=$!
sleep 3

echo "${PLC_PID}" > /tmp/fuxnet_lab_plc.pid
echo "${MBUS_PID}" > /tmp/fuxnet_lab_mbus.pid

echo "[+] PLC PID: ${PLC_PID}  (log: /tmp/plc_server.log)"
echo "[+] M-Bus PID: ${MBUS_PID}  (log: /tmp/mbus_gateway.log)"
echo ""
echo "  Wireshark filter: tcp port ${MBUS_PORT} or tcp port ${PLC_PORT}"
echo ""

if [ "$SKIP_HMI" = true ]; then
    echo "[*] HMI skipped. Start manually:"
    echo "    python3 hmi/hmi_client.py --mbus-ip ${PLC_IP} --mbus-port ${MBUS_PORT}"
    echo ""
    echo "Press Ctrl+C to stop..."
    trap "kill ${PLC_PID} ${MBUS_PID} 2>/dev/null; echo '[*] Lab stopped.'; exit 0" INT TERM
    wait
else
    trap "kill ${PLC_PID} ${MBUS_PID} 2>/dev/null; echo '[*] Lab stopped.'; exit 0" INT TERM
    python3 hmi/hmi_client.py --mbus-ip ${PLC_IP} --mbus-port ${MBUS_PORT}
    kill ${PLC_PID} ${MBUS_PID} 2>/dev/null
    echo "[*] Lab stopped."
fi
