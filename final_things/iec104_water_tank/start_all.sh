#!/bin/bash
# Start all PLC protocols, SIS, M-Bus gateway, and HMI displays
# Usage: ./start_all.sh [--no-hmi]

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
cd "$SCRIPT_DIR"

SKIP_HMI=false
for arg in "$@"; do
    case $arg in --no-hmi) SKIP_HMI=true ;; esac
done

if [ -d "venv_hmi" ]; then VENV="venv_hmi"
elif [ -d "venv" ]; then VENV="venv"
else echo "[!] No venv found."; exit 1; fi

source "${VENV}/bin/activate"

echo "======================================================================"
echo "  STARTING ALL PLCs + SECURITY SYSTEMS"
echo "======================================================================"

# Kill any existing processes
for port in 2404 502 102 4840 9600 1502 5000 20000 8102 61850 47808; do
    lsof -t -i :${port} 2>/dev/null | xargs kill 2>/dev/null
done
sleep 1

check_port() {
    local name=$1 port=$2
    sleep 1
    if ss -tlnp 2>/dev/null | grep -q ":${port} " || ss -ulnp 2>/dev/null | grep -q ":${port} "; then
        echo "[+] ${name} - port ${port} OK"
    else
        echo "[!] ${name} - port ${port} FAILED (check /tmp/${3}.log)"
    fi
}

# PLC: IEC-104 (port 2404) - used by Industroyer2, CosmicEnergy, BlackEnergy3, Triton
echo "[*] Starting PLC - IEC-104 (port 2404)..."
python3 water_tank_server.py --protocol iec104 --port 2404 --with-sis --sis-ip 127.0.0.1 > /tmp/plc_iec104.log 2>&1 &
echo $! > /tmp/lab_plc_iec104.pid
sleep 2
check_port "IEC-104 PLC" 2404 plc_iec104

# PLC: Modbus TCP (port 502) - used by FrostyGoop
echo "[*] Starting PLC - Modbus TCP (port 502)..."
python3 water_tank_server.py --protocol modbus --port 502 > /tmp/plc_modbus.log 2>&1 &
echo $! > /tmp/lab_plc_modbus.pid
sleep 2
check_port "Modbus PLC" 502 plc_modbus

# PLC: Siemens S7 (port 102) - used by Stuxnet
echo "[*] Starting PLC - Siemens S7 (port 102)..."
python3 water_tank_server.py --protocol s7 --port 102 > /tmp/plc_s7.log 2>&1 &
echo $! > /tmp/lab_plc_s7.pid
sleep 2
check_port "S7 PLC" 102 plc_s7

# PLC: OPC-UA (port 4840) + FINS (port 9600) - used by PIPEDREAM
PIPEDREAM_DIR="${SCRIPT_DIR}/../pipedream_opcua_demo/machines/plc/server"
if [ -d "${PIPEDREAM_DIR}" ]; then
    echo "[*] Starting PLC - OPC-UA/PIPEDREAM (port 4840)..."
    cd "${PIPEDREAM_DIR}"
    python3 opcua_server.py --host 0.0.0.0 --port 4840 > /tmp/plc_opcua.log 2>&1 &
    echo $! > /tmp/lab_plc_opcua.pid
    sleep 3
    check_port "OPC-UA PLC" 4840 plc_opcua

    echo "[*] Starting PLC - OMRON FINS (port 9600)..."
    python3 fins_server.py --host 0.0.0.0 --port 9600 > /tmp/plc_fins.log 2>&1 &
    echo $! > /tmp/lab_plc_fins.pid
    cd "${SCRIPT_DIR}"
    sleep 2
    check_port "FINS PLC" 9600 plc_fins
else
    echo "[!] PIPEDREAM directory not found - skipping OPC-UA/FINS"
fi

# SIS: TriStation (port 1502) - used by Triton
echo "[*] Starting SIS - TriStation (port 1502)..."
python3 triconex_sis_server.py --plc-ip 127.0.0.1 --plc-port 2404 --sis-port 1502 --threshold 90 > /tmp/sis_server.log 2>&1 &
echo $! > /tmp/lab_sis.pid
sleep 2
check_port "TriStation SIS" 1502 sis_server

# M-Bus Gateway (port 5000) - used by Fuxnet
echo "[*] Starting M-Bus Gateway (port 5000)..."
python3 mbus_gateway_server.py --plc-ip 127.0.0.1 --plc-port 2404 --mbus-port 5000 > /tmp/mbus_gateway.log 2>&1 &
echo $! > /tmp/lab_mbus.pid
sleep 2
check_port "M-Bus Gateway" 5000 mbus_gateway

# PLC: DNP3 (port 20000) - used by Industroyer DNP3 module
echo "[*] Starting PLC - DNP3 (port 20000)..."
python3 water_tank_server.py --protocol dnp3 --port 20000 > /tmp/plc_dnp3.log 2>&1 &
echo $! > /tmp/lab_plc_dnp3.pid
sleep 2
check_port "DNP3 PLC" 20000 plc_dnp3

# PLC: IEC 61850 MMS+GOOSE (port 8102/61850) - used by Industroyer GOOSE module
echo "[*] Starting PLC - IEC 61850 MMS (port 8102) + GOOSE (port 61850)..."
python3 water_tank_server.py --protocol iec61850 --port 8102 > /tmp/plc_iec61850.log 2>&1 &
echo $! > /tmp/lab_plc_iec61850.pid
sleep 2
check_port "IEC 61850 MMS" 8102 plc_iec61850

# PLC: BACnet/IP (port 47808) - used by BACnet HVAC attack
echo "[*] Starting PLC - BACnet/IP (port 47808)..."
python3 water_tank_server.py --protocol bacnet --port 47808 > /tmp/plc_bacnet.log 2>&1 &
echo $! > /tmp/lab_plc_bacnet.pid
sleep 2
check_port "BACnet/IP" 47808 plc_bacnet

echo ""
echo "======================================================================"
echo "  ALL SYSTEMS STATUS"
echo "======================================================================"
echo "  IEC-104:    port 2404   (Industroyer2, CosmicEnergy, BlackEnergy3)"
echo "  Modbus TCP: port 502    (FrostyGoop)"
echo "  Siemens S7: port 102    (Stuxnet)"
echo "  OPC-UA:     port 4840   (PIPEDREAM)"
echo "  OMRON FINS: port 9600   (PIPEDREAM)"
echo "  TriStation: port 1502   (Triton SIS)"
echo "  M-Bus:      port 5000   (Fuxnet gateway)"
echo "  DNP3:       port 20000  (Industroyer DNP3 module)"
echo "  IEC 61850:  port 8102   (Industroyer GOOSE module)"
echo "  GOOSE:      port 61850  (GOOSE event listener)"
echo "  BACnet/IP:  port 47808  (BACnet HVAC attack)"
echo "  KillDisk:   port 4444   (BlackEnergy3, on HMI)"
echo "======================================================================"
echo ""

if [ "$SKIP_HMI" = true ]; then
    echo "[*] HMI skipped. Start manually on the HMI machine (Windows):"
    echo ""
    echo "  # IEC-104 HMI (with SIS + M-Bus panels):"
    echo "  python hmi/multiprotocol_hmi.py --protocol iec104 --host 192.168.1.6 --sis-ip 192.168.1.6 --mbus-ip 192.168.1.6"
    echo ""
    echo "  # Modbus HMI:"
    echo "  python hmi/multiprotocol_hmi.py --protocol modbus --host 192.168.1.6"
    echo ""
    echo "  # S7 HMI:"
    echo "  python hmi/multiprotocol_hmi.py --protocol s7 --host 192.168.1.6"
    echo ""
    echo "  # OPC-UA HMI:"
    echo "  python hmi/multiprotocol_hmi.py --protocol opcua --host 192.168.1.6"
    echo ""
    echo "Press Ctrl+C to stop all..."
    trap "$(cat <<'TRAP'
for f in /tmp/lab_*.pid; do
    [ -f "$f" ] && kill $(cat "$f") 2>/dev/null && rm -f "$f"
done
echo "[*] All stopped."
TRAP
)" INT TERM
    wait
else
    echo "[*] Starting HMI displays..."
    echo ""
    trap "$(cat <<'TRAP'
for f in /tmp/lab_*.pid; do
    [ -f "$f" ] && kill $(cat "$f") 2>/dev/null && rm -f "$f"
done
echo "[*] All stopped."
TRAP
)" INT TERM

    # Launch all 4 HMI windows
    python3 hmi/multiprotocol_hmi.py --protocol iec104 --host 127.0.0.1 --sis-ip 127.0.0.1 --mbus-ip 127.0.0.1 &
    echo $! > /tmp/lab_hmi_iec104.pid
    sleep 1

    python3 hmi/multiprotocol_hmi.py --protocol modbus --host 127.0.0.1 &
    echo $! > /tmp/lab_hmi_modbus.pid
    sleep 1

    python3 hmi/multiprotocol_hmi.py --protocol s7 --host 127.0.0.1 &
    echo $! > /tmp/lab_hmi_s7.pid
    sleep 1

    python3 hmi/multiprotocol_hmi.py --protocol opcua --host 127.0.0.1 &
    echo $! > /tmp/lab_hmi_opcua.pid

    echo "[*] All HMI displays launched. Press Ctrl+C to stop all..."
    wait
fi
