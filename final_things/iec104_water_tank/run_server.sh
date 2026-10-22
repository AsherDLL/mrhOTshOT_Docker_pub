#!/bin/bash
# Script to run IEC-104 Water Tank Server

echo "Starting IEC-104 Water Tank Server..."
echo "======================================="

cd "$(dirname "$0")"

# Activate virtual environment if it exists
if [ -d "venv" ]; then
    source venv/bin/activate
elif [ -d "../env" ]; then
    source env/bin/activate
fi

# Run the server
python -m server.iec104_server
