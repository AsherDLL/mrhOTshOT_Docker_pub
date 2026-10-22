#!/bin/bash
# Script to run IEC-104 Water Tank HMI

echo "Starting IEC-104 Water Tank HMI..."
echo "===================================="

cd "$(dirname "$0")"

# Activate virtual environment if it exists
if [ -d "venv" ]; then
    source venv/bin/activate
elif [ -d "../env" ]; then
    source env/bin/activate
fi

# Run the HMI
python -m hmi.hmi_client
