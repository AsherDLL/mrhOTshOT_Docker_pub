#!/bin/bash
# Run Triton/TRISIS attack (disables SIS, then overflows tank)
#
# This attack first compromises the SIS via TriStation protocol:
#   1. Connect to SIS (UDP 1502)
#   2. Attach TRICON
#   3. Recon: Get CP status, chassis status
#   4. Halt safety program
#   5. Download malicious safety logic
#   6. Run compromised program
# Then overflows the water tank via IEC-104 (no safety trip).
#
# Expected result: SIS disabled, tank overflows and EXPLODES.

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
cd "$SCRIPT_DIR"

SIS_IP="${SIS_IP:-127.0.0.1}"
SIS_PORT="${SIS_PORT:-1502}"
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
echo "  TRITON / TRISIS ATTACK SIMULATION"
echo "  Expected: SIS disabled, tank explodes"
echo "======================================================================"
echo "  SIS Target: ${SIS_IP}:${SIS_PORT} (TriStation UDP)"
echo "  PLC Target: ${PLC_IP}:${PLC_PORT} (IEC-104)"
echo "  Duration: ${DURATION}s"
echo "======================================================================"
echo

python3 perform_malware_simulations/triton_simulation.py \
    --sis-ip ${SIS_IP} --sis-port ${SIS_PORT} \
    --plc-ip ${PLC_IP} --plc-port ${PLC_PORT} \
    --duration ${DURATION}
