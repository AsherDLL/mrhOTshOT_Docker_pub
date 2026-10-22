#!/usr/bin/env bash
#
# start_plc.sh -- Manually start a PLC process (for testing without systemd)
#
# Usage:
#   ./start_plc.sh <process_name>          # foreground (default)
#   ./start_plc.sh <process_name> -d       # background (daemonised)
#
# Examples:
#   ./start_plc.sh water_treatment
#   ./start_plc.sh gas_pipeline -d
#
set -e

# ---------------------------------------------------------------------------
# Argument parsing
# ---------------------------------------------------------------------------
PROCESS_NAME="${1:?Usage: $0 <process_name> [-d]  (e.g. water_treatment, power_substation, gas_pipeline, manufacturing, building_hvac, boiler_house)}"
DAEMONISE=false

# Check for -d flag in any position
for arg in "$@"; do
    if [ "$arg" = "-d" ]; then
        DAEMONISE=true
    fi
done

# Validate process name
VALID_PROCESSES="water_treatment power_substation gas_pipeline manufacturing building_hvac boiler_house"
if ! echo "$VALID_PROCESSES" | grep -qw "$PROCESS_NAME"; then
    echo "[ERROR] Unknown process: $PROCESS_NAME"
    echo "        Valid processes: $VALID_PROCESSES"
    exit 1
fi

# ---------------------------------------------------------------------------
# Resolve paths
# ---------------------------------------------------------------------------
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
PROJECT_DIR="$(cd "${SCRIPT_DIR}/.." && pwd)"

# Try multiple venv locations (deployed vs. development)
if [ -d "/opt/ics-sim/venv" ]; then
    VENV_DIR="/opt/ics-sim/venv"
    WORK_DIR="/opt/ics-sim"
elif [ -d "${PROJECT_DIR}/venv_hmi" ]; then
    VENV_DIR="${PROJECT_DIR}/venv_hmi"
    WORK_DIR="${PROJECT_DIR}"
elif [ -d "${PROJECT_DIR}/venv" ]; then
    VENV_DIR="${PROJECT_DIR}/venv"
    WORK_DIR="${PROJECT_DIR}"
elif [ -d "${PROJECT_DIR}/venv313" ]; then
    VENV_DIR="${PROJECT_DIR}/venv313"
    WORK_DIR="${PROJECT_DIR}"
else
    echo "[ERROR] No Python virtual environment found."
    echo "        Expected one of:"
    echo "          /opt/ics-sim/venv"
    echo "          ${PROJECT_DIR}/venv_hmi"
    echo "          ${PROJECT_DIR}/venv"
    echo "          ${PROJECT_DIR}/venv313"
    exit 1
fi

SERVER_SCRIPT="${WORK_DIR}/water_tank_server.py"
if [ ! -f "${SERVER_SCRIPT}" ]; then
    echo "[ERROR] water_tank_server.py not found at ${SERVER_SCRIPT}"
    exit 1
fi

# ---------------------------------------------------------------------------
# Activate virtual environment and run
# ---------------------------------------------------------------------------
# shellcheck disable=SC1091
source "${VENV_DIR}/bin/activate"

echo "======================================================================"
echo "  ICS PLC - Manual Start"
echo "  Process : ${PROCESS_NAME}"
echo "  Venv    : ${VENV_DIR}"
echo "  Mode    : $(if $DAEMONISE; then echo 'background'; else echo 'foreground (Ctrl+C to stop)'; fi)"
echo "======================================================================"
echo ""

cd "${WORK_DIR}"

if [ "$DAEMONISE" = true ]; then
    # Background mode -- redirect output to log file
    LOG_FILE="/tmp/ics-sim-${PROCESS_NAME}.log"
    PID_FILE="/tmp/ics-sim-${PROCESS_NAME}.pid"

    nohup python3 "${SERVER_SCRIPT}" --process "${PROCESS_NAME}" --host 0.0.0.0 \
        > "${LOG_FILE}" 2>&1 &
    PID=$!
    echo "${PID}" > "${PID_FILE}"

    echo "[+] Started in background (PID ${PID})"
    echo "    Log : ${LOG_FILE}"
    echo "    PID : ${PID_FILE}"
    echo "    Stop: kill \$(cat ${PID_FILE})"
else
    # Foreground mode -- run directly, Ctrl+C to stop
    exec python3 "${SERVER_SCRIPT}" --process "${PROCESS_NAME}" --host 0.0.0.0
fi
