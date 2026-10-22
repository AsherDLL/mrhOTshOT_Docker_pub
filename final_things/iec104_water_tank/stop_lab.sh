#!/bin/bash
# Stop the Triton/SIS water tank lab

echo "[*] Stopping lab processes..."

# Kill by saved PIDs
if [ -f /tmp/triton_lab_plc.pid ]; then
    PLC_PID=$(cat /tmp/triton_lab_plc.pid)
    kill ${PLC_PID} 2>/dev/null && echo "[+] PLC stopped (PID ${PLC_PID})"
    rm -f /tmp/triton_lab_plc.pid
fi

if [ -f /tmp/triton_lab_sis.pid ]; then
    SIS_PID=$(cat /tmp/triton_lab_sis.pid)
    kill ${SIS_PID} 2>/dev/null && echo "[+] SIS stopped (PID ${SIS_PID})"
    rm -f /tmp/triton_lab_sis.pid
fi

# Also kill by port as fallback
lsof -t -i :2404 2>/dev/null | xargs kill 2>/dev/null
lsof -t -i :1502 2>/dev/null | xargs kill 2>/dev/null

echo "[*] Lab stopped."
