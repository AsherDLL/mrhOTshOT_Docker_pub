#!/bin/bash
# Start the full Triton/SIS water tank lab
# Usage: ./start_lab.sh [--no-hmi]
#
# Starts: PLC (port 2404), SIS (port 1502), and HMI (GUI)
# Use --no-hmi to skip the HMI (e.g., when running headless)

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
cd "$SCRIPT_DIR"

# Default config
PLC_IP="${PLC_IP:-0.0.0.0}"
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
    VENV="venv_hmi"
elif [ -d "venv" ]; then
    VENV="venv"
else
    echo "[!] No venv found. Create one first:"
    echo "    python3 -m venv venv && source venv/bin/activate"
    echo "    pip install crcmod && pip install ./c104-2.2.1/"
    exit 1
fi

echo "======================================================================"
echo "  TRITON/SIS WATER TANK LAB"
echo "======================================================================"
echo "  PLC:  ${PLC_IP}:${PLC_PORT} (IEC-104)"
echo "  SIS:  ${SIS_IP}:${SIS_PORT} (TriStation UDP)"
echo "  Threshold: ${SIS_THRESHOLD}%"
echo "  venv: ${VENV}"
echo "======================================================================"
echo

# Kill any existing processes on our ports
echo "[*] Cleaning up old processes..."
lsof -t -i :${PLC_PORT} 2>/dev/null | xargs kill 2>/dev/null
lsof -t -i :${SIS_PORT} 2>/dev/null | xargs kill 2>/dev/null
sleep 1

# Start PLC
echo "[*] Starting Water Tank PLC (port ${PLC_PORT})..."
source "${VENV}/bin/activate"
python3 water_tank_server.py --protocol iec104 --port ${PLC_PORT} --with-sis --sis-ip ${SIS_IP} > /tmp/plc_server.log 2>&1 &
PLC_PID=$!
echo "    PID: ${PLC_PID}"
sleep 2

# Verify PLC started
if ! kill -0 ${PLC_PID} 2>/dev/null; then
    echo "[!] PLC failed to start. Check /tmp/plc_server.log"
    exit 1
fi
echo "[+] PLC started"

# Start SIS
echo "[*] Starting Triconex SIS (port ${SIS_PORT}, threshold ${SIS_THRESHOLD}%)..."
python3 triconex_sis_server.py --plc-ip ${SIS_IP} --plc-port ${PLC_PORT} --sis-port ${SIS_PORT} --threshold ${SIS_THRESHOLD} > /tmp/sis_server.log 2>&1 &
SIS_PID=$!
echo "    PID: ${SIS_PID}"
sleep 3

# Verify SIS started
if ! kill -0 ${SIS_PID} 2>/dev/null; then
    echo "[!] SIS failed to start. Check /tmp/sis_server.log"
    kill ${PLC_PID} 2>/dev/null
    exit 1
fi
echo "[+] SIS started and monitoring"

# Save PIDs for stop script
echo "${PLC_PID}" > /tmp/triton_lab_plc.pid
echo "${SIS_PID}" > /tmp/triton_lab_sis.pid

echo
echo "======================================================================"
echo "  LAB RUNNING"
echo "======================================================================"
echo "  PLC PID: ${PLC_PID}  (log: /tmp/plc_server.log)"
echo "  SIS PID: ${SIS_PID}  (log: /tmp/sis_server.log)"
echo
echo "  Wireshark filter: udp port ${SIS_PORT} or tcp port ${PLC_PORT}"
echo "  Capture on: lo0 (loopback)"
echo "======================================================================"
echo

if [ "$SKIP_HMI" = true ]; then
    echo "[*] HMI skipped (--no-hmi). Start manually:"
    echo "    source ${VENV}/bin/activate"
    echo "    python3 hmi/hmi_client.py --sis-ip ${SIS_IP} --sis-port ${SIS_PORT}"
    echo
    echo "Press Ctrl+C to stop the lab..."
    trap "kill ${PLC_PID} ${SIS_PID} 2>/dev/null; echo; echo '[*] Lab stopped.'; exit 0" INT TERM
    wait
else
    echo "[*] Starting HMI..."
    echo "    Close the HMI window or press Ctrl+C to stop the lab."
    echo
    trap "kill ${PLC_PID} ${SIS_PID} 2>/dev/null; echo; echo '[*] Lab stopped.'; exit 0" INT TERM
    python3 hmi/hmi_client.py --sis-ip ${SIS_IP} --sis-port ${SIS_PORT}
    # HMI closed, clean up
    kill ${PLC_PID} ${SIS_PID} 2>/dev/null
    echo "[*] Lab stopped."
fi
