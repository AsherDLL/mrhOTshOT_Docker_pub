#!/usr/bin/env bash
#
# deploy_all.sh -- Deploy the ICS simulation to all ESXi Linux VMs
#
# Reads hmi_config.json to discover each process and its target IP, then
# copies the project files via SCP and runs setup_vm.sh via SSH.
#
# Usage:
#   ./deploy_all.sh <ssh_user>
#
# Example:
#   ./deploy_all.sh admin
#   ./deploy_all.sh root
#
# Prerequisites:
#   - SSH key-based auth configured for all target VMs
#   - Target VMs running Ubuntu/Debian with sudo access for <ssh_user>
#   - jq installed on the machine running this script
#
set -e

# ---------------------------------------------------------------------------
# Argument validation
# ---------------------------------------------------------------------------
SSH_USER="${1:?Usage: $0 <ssh_user>  (e.g. admin, root)}"

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
PROJECT_DIR="$(cd "${SCRIPT_DIR}/.." && pwd)"
CONFIG_FILE="${SCRIPT_DIR}/hmi_config.json"
REMOTE_DIR="/opt/ics-sim"

if [ ! -f "${CONFIG_FILE}" ]; then
    echo "[ERROR] hmi_config.json not found at ${CONFIG_FILE}"
    exit 1
fi

# Require jq for JSON parsing
if ! command -v jq &> /dev/null; then
    echo "[ERROR] jq is required but not installed."
    echo "        Install it with: brew install jq  (macOS) or apt-get install jq  (Linux)"
    exit 1
fi

# ---------------------------------------------------------------------------
# Collect processes and IPs from config
# ---------------------------------------------------------------------------
PROCESSES=$(jq -r 'keys[]' "${CONFIG_FILE}")
TOTAL=$(echo "$PROCESSES" | wc -w | tr -d ' ')

echo "======================================================================"
echo "  ICS Simulation -- Multi-VM Deployment"
echo "======================================================================"
echo "  SSH user   : ${SSH_USER}"
echo "  Config     : ${CONFIG_FILE}"
echo "  Project    : ${PROJECT_DIR}"
echo "  Remote dir : ${REMOTE_DIR}"
echo "  VMs        : ${TOTAL}"
echo "======================================================================"
echo ""

# Track results for the summary
declare -a RESULTS_PROCESS
declare -a RESULTS_IP
declare -a RESULTS_STATUS

INDEX=0

for PROCESS in $PROCESSES; do
    IP=$(jq -r ".${PROCESS}.host" "${CONFIG_FILE}")
    PORTS=$(jq -r ".${PROCESS}.protocols | to_entries[] | \"\(.key):\(.value)\"" "${CONFIG_FILE}" | tr '\n' ' ')

    INDEX=$((INDEX + 1))
    echo "----------------------------------------------------------------------"
    echo "[${INDEX}/${TOTAL}] ${PROCESS} -> ${IP}"
    echo "         Ports: ${PORTS}"
    echo "----------------------------------------------------------------------"

    RESULTS_PROCESS+=("${PROCESS}")
    RESULTS_IP+=("${IP}")

    # --- Step 1: Test SSH connectivity ----------------------------------
    echo "  [*] Testing SSH connectivity to ${SSH_USER}@${IP}..."
    if ! ssh -o ConnectTimeout=5 -o BatchMode=yes "${SSH_USER}@${IP}" "echo ok" > /dev/null 2>&1; then
        echo "  [!] FAILED -- cannot reach ${SSH_USER}@${IP} via SSH"
        RESULTS_STATUS+=("FAILED (SSH unreachable)")
        echo ""
        continue
    fi
    echo "  [+] SSH connection OK."

    # --- Step 2: Create remote directory --------------------------------
    echo "  [*] Preparing remote directory ${REMOTE_DIR}..."
    ssh "${SSH_USER}@${IP}" "sudo mkdir -p ${REMOTE_DIR} && sudo chown \$(whoami):\$(id -gn) ${REMOTE_DIR}"

    # --- Step 3: Copy project files -------------------------------------
    echo "  [*] Copying project files to ${SSH_USER}@${IP}:${REMOTE_DIR}..."

    # Use rsync if available (faster for repeated deployments), fall back to scp
    if command -v rsync &> /dev/null; then
        rsync -az --delete \
            --exclude 'venv*' \
            --exclude 'node_modules' \
            --exclude '__pycache__' \
            --exclude '*.log' \
            --exclude '.git' \
            --exclude '*.pyc' \
            "${PROJECT_DIR}/" "${SSH_USER}@${IP}:${REMOTE_DIR}/"
    else
        scp -r -q \
            "${PROJECT_DIR}/server" \
            "${PROJECT_DIR}/common" \
            "${PROJECT_DIR}/hmi" \
            "${PROJECT_DIR}/deploy" \
            "${PROJECT_DIR}/water_tank_server.py" \
            "${PROJECT_DIR}/triconex_sis_server.py" \
            "${PROJECT_DIR}/mbus_gateway_server.py" \
            "${PROJECT_DIR}/requirements.txt" \
            "${SSH_USER}@${IP}:${REMOTE_DIR}/"
        # Copy c104 library if present
        if [ -d "${PROJECT_DIR}/c104-2.2.1" ]; then
            scp -r -q "${PROJECT_DIR}/c104-2.2.1" "${SSH_USER}@${IP}:${REMOTE_DIR}/"
        fi
    fi
    echo "  [+] Files copied."

    # --- Step 4: Run setup_vm.sh on the remote host ---------------------
    echo "  [*] Running setup_vm.sh ${PROCESS} on ${IP}..."
    if ssh "${SSH_USER}@${IP}" "cd ${REMOTE_DIR} && chmod +x deploy/setup_vm.sh && ./deploy/setup_vm.sh ${PROCESS}"; then
        echo "  [+] Setup completed successfully."
        RESULTS_STATUS+=("OK")
    else
        echo "  [!] Setup script returned non-zero exit code."
        RESULTS_STATUS+=("FAILED (setup_vm.sh error)")
    fi

    echo ""
done

# ---------------------------------------------------------------------------
# Summary
# ---------------------------------------------------------------------------
echo "======================================================================"
echo "  DEPLOYMENT SUMMARY"
echo "======================================================================"
printf "  %-20s %-16s %s\n" "PROCESS" "IP" "STATUS"
printf "  %-20s %-16s %s\n" "-------" "--" "------"

for i in "${!RESULTS_PROCESS[@]}"; do
    printf "  %-20s %-16s %s\n" "${RESULTS_PROCESS[$i]}" "${RESULTS_IP[$i]}" "${RESULTS_STATUS[$i]}"
done

echo "======================================================================"
echo ""

# Check if any failed
FAIL_COUNT=0
for status in "${RESULTS_STATUS[@]}"; do
    if [ "$status" != "OK" ]; then
        FAIL_COUNT=$((FAIL_COUNT + 1))
    fi
done

if [ "$FAIL_COUNT" -gt 0 ]; then
    echo "[!] ${FAIL_COUNT} of ${TOTAL} deployments failed. Check output above."
    exit 1
else
    echo "[+] All ${TOTAL} VMs deployed successfully."
fi
