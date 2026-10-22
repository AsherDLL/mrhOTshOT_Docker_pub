#!/usr/bin/env bash
#
# setup_vm.sh -- Provision a fresh Ubuntu/Debian VM to run one ICS process
#
# Usage:
#   ./setup_vm.sh <process_name>
#
# Example:
#   ./setup_vm.sh water_treatment
#
# The script:
#   1. Installs system-level dependencies (python3, build tools, etc.)
#   2. Creates a Python virtual environment at /opt/ics-sim/venv
#   3. Copies the project source into /opt/ics-sim/
#   4. Installs Python packages needed by the simulation
#   5. Creates a systemd unit file for auto-start on boot
#   6. Enables and starts the service
#
set -e

# ---------------------------------------------------------------------------
# Argument validation
# ---------------------------------------------------------------------------
PROCESS_NAME="${1:?Usage: $0 <process_name>  (e.g. water_treatment, power_substation, gas_pipeline, manufacturing, building_hvac, boiler_house)}"

VALID_PROCESSES="water_treatment power_substation gas_pipeline manufacturing centrifuge building_hvac boiler_house heating_district water_utility_dnp3 sensor_network safety_system"
if ! echo "$VALID_PROCESSES" | grep -qw "$PROCESS_NAME"; then
    echo "[ERROR] Unknown process: $PROCESS_NAME"
    echo "        Valid processes: $VALID_PROCESSES"
    exit 1
fi

INSTALL_DIR="/opt/ics-sim"
VENV_DIR="${INSTALL_DIR}/venv"
SERVICE_NAME="ics-sim-${PROCESS_NAME}"
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
PROJECT_DIR="$(cd "${SCRIPT_DIR}/.." && pwd)"

echo "======================================================================"
echo "  ICS Simulation VM Setup"
echo "  Process : ${PROCESS_NAME}"
echo "  Target  : ${INSTALL_DIR}"
echo "======================================================================"
echo ""

# ---------------------------------------------------------------------------
# 1. Install system dependencies
# ---------------------------------------------------------------------------
echo "[*] Installing system dependencies..."
export DEBIAN_FRONTEND=noninteractive
sudo apt-get update -qq
sudo apt-get install -y -qq \
    python3 \
    python3-pip \
    python3-venv \
    build-essential \
    libffi-dev \
    > /dev/null 2>&1
echo "[+] System dependencies installed."

# ---------------------------------------------------------------------------
# 2. Create installation directory and Python virtual environment
# ---------------------------------------------------------------------------
echo "[*] Creating installation directory ${INSTALL_DIR}..."
sudo mkdir -p "${INSTALL_DIR}"
sudo chown "$(whoami):$(id -gn)" "${INSTALL_DIR}"

if [ ! -d "${VENV_DIR}" ]; then
    echo "[*] Creating Python virtual environment at ${VENV_DIR}..."
    python3 -m venv "${VENV_DIR}"
fi
echo "[+] Virtual environment ready."

# ---------------------------------------------------------------------------
# 3. Copy project code into /opt/ics-sim/
# ---------------------------------------------------------------------------
echo "[*] Copying project code to ${INSTALL_DIR}..."

# Copy core source files (exclude heavy/unnecessary dirs)
for item in server common hmi deploy \
            water_tank_server.py triconex_sis_server.py mbus_gateway_server.py \
            requirements.txt requirements-modbus.txt requirements-multiprotocol.txt \
            requirements-opcua.txt requirements-s7.txt; do
    if [ -e "${PROJECT_DIR}/${item}" ]; then
        cp -a "${PROJECT_DIR}/${item}" "${INSTALL_DIR}/"
    fi
done

# Ensure the c104 library source is available for building
if [ -d "${PROJECT_DIR}/c104-2.2.1" ]; then
    cp -a "${PROJECT_DIR}/c104-2.2.1" "${INSTALL_DIR}/"
fi
echo "[+] Project code copied."

# ---------------------------------------------------------------------------
# 4. Install Python dependencies
# ---------------------------------------------------------------------------
echo "[*] Installing Python dependencies..."
# shellcheck disable=SC1091
source "${VENV_DIR}/bin/activate"

pip install --upgrade pip -q

# Core dependencies used across processes
pip install -q \
    pymodbus>=3.0.0 \
    python-snap7>=1.3 \
    asyncua>=1.0.0 \
    opcua \
    crcmod>=1.7 \
    setuptools \
    requests \
    flask

# Install the bundled c104 library if present
if [ -d "${INSTALL_DIR}/c104-2.2.1" ]; then
    pip install -q "${INSTALL_DIR}/c104-2.2.1/" 2>/dev/null || true
fi

# Install from requirements.txt as a catch-all
if [ -f "${INSTALL_DIR}/requirements.txt" ]; then
    pip install -q -r "${INSTALL_DIR}/requirements.txt" 2>/dev/null || true
fi

deactivate
echo "[+] Python dependencies installed."

# ---------------------------------------------------------------------------
# 5. Create systemd service file
# ---------------------------------------------------------------------------
echo "[*] Creating systemd service: ${SERVICE_NAME}..."

sudo tee "/etc/systemd/system/${SERVICE_NAME}.service" > /dev/null <<EOF
[Unit]
Description=ICS Simulation - ${PROCESS_NAME}
After=network-online.target
Wants=network-online.target

[Service]
Type=simple
User=$(whoami)
WorkingDirectory=${INSTALL_DIR}
ExecStart=${VENV_DIR}/bin/python ${INSTALL_DIR}/water_tank_server.py --process ${PROCESS_NAME} --host 0.0.0.0
Restart=on-failure
RestartSec=5
StandardOutput=journal+console
StandardError=journal+console

# Hardening
ProtectHome=read-only
NoNewPrivileges=true

[Install]
WantedBy=multi-user.target
EOF
echo "[+] Service file created."

# ---------------------------------------------------------------------------
# 6. Enable and start the service
# ---------------------------------------------------------------------------
echo "[*] Enabling and starting ${SERVICE_NAME}..."
sudo systemctl daemon-reload
sudo systemctl enable "${SERVICE_NAME}"
sudo systemctl start "${SERVICE_NAME}"
echo "[+] Service ${SERVICE_NAME} is active."

# ---------------------------------------------------------------------------
# 7. Print summary
# ---------------------------------------------------------------------------
echo ""
echo "======================================================================"
echo "  DEPLOYMENT COMPLETE"
echo "======================================================================"
echo "  Process  : ${PROCESS_NAME}"
echo "  Service  : ${SERVICE_NAME}"
echo "  Command  : ${VENV_DIR}/bin/python ${INSTALL_DIR}/water_tank_server.py --process ${PROCESS_NAME} --host 0.0.0.0"
echo ""

# Read port info from hmi_config.json if jq is available
CONFIG_FILE="${INSTALL_DIR}/deploy/hmi_config.json"
if command -v jq &> /dev/null && [ -f "${CONFIG_FILE}" ]; then
    echo "  Ports:"
    jq -r ".${PROCESS_NAME}.protocols | to_entries[] | \"    \\(.key): \\(.value)\"" "${CONFIG_FILE}" 2>/dev/null || true
else
    # Fall back to grep-based extraction
    echo "  Ports: (install jq for detailed port listing)"
    grep -A 20 "\"${PROCESS_NAME}\"" "${CONFIG_FILE}" 2>/dev/null | grep -E '"[a-z]+":\s*[0-9]+' | sed 's/[",]//g; s/^/    /' || true
fi

echo ""
echo "  Logs     : journalctl -u ${SERVICE_NAME} -f"
echo "  Status   : systemctl status ${SERVICE_NAME}"
echo "  Stop     : sudo systemctl stop ${SERVICE_NAME}"
echo "======================================================================"
