#!/bin/bash
#
# Port Cleanup Script - Multi-Protocol Water Tank Server
#
# This script finds and kills processes using the default ports for:
# - IEC-104 (2404, 2405)
# - Siemens S7 (102)
# - Modbus TCP (502, 5020)
# - OPC-UA (4840, 4841)
#
# Usage:
#     ./cleanup_ports.sh              # Interactive mode (asks before killing)
#     ./cleanup_ports.sh --force      # Force kill without confirmation
#     ./cleanup_ports.sh --list       # List only, don't kill
#

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

# Default ports for each protocol
IEC104_PORTS=(2404 2405)
S7_PORTS=(102)
MODBUS_PORTS=(502 5020)
OPCUA_PORTS=(4840 4841)

# All ports combined
ALL_PORTS=("${IEC104_PORTS[@]}" "${S7_PORTS[@]}" "${MODBUS_PORTS[@]}" "${OPCUA_PORTS[@]}")

# Parse command line arguments
FORCE_KILL=false
LIST_ONLY=false

for arg in "$@"; do
    case $arg in
        --force|-f)
            FORCE_KILL=true
            ;;
        --list|-l)
            LIST_ONLY=true
            ;;
        --help|-h)
            echo "Port Cleanup Script - Multi-Protocol Water Tank Server"
            echo ""
            echo "Usage:"
            echo "  ./cleanup_ports.sh              Interactive mode (asks before killing)"
            echo "  ./cleanup_ports.sh --force      Force kill without confirmation"
            echo "  ./cleanup_ports.sh --list       List only, don't kill"
            echo "  ./cleanup_ports.sh --help       Show this help"
            echo ""
            echo "Ports checked:"
            echo "  IEC-104:  2404, 2405"
            echo "  S7:       102"
            echo "  Modbus:   502, 5020"
            echo "  OPC-UA:   4840, 4841"
            exit 0
            ;;
    esac
done

echo -e "${BLUE}╔══════════════════════════════════════════════════════════════╗${NC}"
echo -e "${BLUE}║     Multi-Protocol Water Tank - Port Cleanup Script         ║${NC}"
echo -e "${BLUE}╔══════════════════════════════════════════════════════════════╗${NC}"
echo ""

# Function to get process info for a port
get_port_info() {
    local port=$1
    # Use lsof to find process using the port
    lsof -ti:$port 2>/dev/null
}

# Function to get detailed process info
get_process_details() {
    local pid=$1
    if [ -n "$pid" ]; then
        ps -p $pid -o pid,ppid,user,command | tail -n +2
    fi
}

# Track if any processes were found
PROCESSES_FOUND=false
TOTAL_PROCESSES=0

# Array to store PIDs to kill
declare -a PIDS_TO_KILL

echo -e "${YELLOW}Scanning for processes using server ports...${NC}"
echo ""

# Check each protocol's ports
for protocol in "IEC-104" "S7" "Modbus" "OPC-UA"; do
    case $protocol in
        "IEC-104")
            ports=("${IEC104_PORTS[@]}")
            ;;
        "S7")
            ports=("${S7_PORTS[@]}")
            ;;
        "Modbus")
            ports=("${MODBUS_PORTS[@]}")
            ;;
        "OPC-UA")
            ports=("${OPCUA_PORTS[@]}")
            ;;
    esac

    protocol_has_processes=false

    for port in "${ports[@]}"; do
        pids=$(get_port_info $port)

        if [ -n "$pids" ]; then
            if [ "$protocol_has_processes" = false ]; then
                echo -e "${RED}${protocol} Protocol:${NC}"
                protocol_has_processes=true
            fi

            PROCESSES_FOUND=true

            for pid in $pids; do
                TOTAL_PROCESSES=$((TOTAL_PROCESSES + 1))
                PIDS_TO_KILL+=($pid)

                echo -e "  ${YELLOW}Port ${port}:${NC}"
                echo -e "$(get_process_details $pid)" | sed 's/^/    /'
            done
        fi
    done

    if [ "$protocol_has_processes" = true ]; then
        echo ""
    fi
done

# Summary
echo -e "${BLUE}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}"

if [ "$PROCESSES_FOUND" = false ]; then
    echo -e "${GREEN}[+] No processes found using server ports${NC}"
    echo ""
    exit 0
fi

echo -e "${YELLOW}Found ${TOTAL_PROCESSES} process(es) using server ports${NC}"
echo ""

# If list-only mode, exit here
if [ "$LIST_ONLY" = true ]; then
    echo -e "${BLUE}List-only mode - no processes killed${NC}"
    exit 0
fi

# Get unique PIDs (in case same process uses multiple ports)
UNIQUE_PIDS=($(printf '%s\n' "${PIDS_TO_KILL[@]}" | sort -u))

# Ask for confirmation unless force mode
if [ "$FORCE_KILL" = false ]; then
    echo -e "${RED}Do you want to kill these processes? (y/N):${NC} "
    read -r response

    if [[ ! "$response" =~ ^[Yy]$ ]]; then
        echo -e "${YELLOW}Cancelled - no processes killed${NC}"
        exit 0
    fi
fi

# Kill processes
echo ""
echo -e "${YELLOW}Terminating processes...${NC}"

KILLED_COUNT=0
FAILED_COUNT=0

for pid in "${UNIQUE_PIDS[@]}"; do
    # Try graceful kill first (SIGTERM)
    if kill $pid 2>/dev/null; then
        echo -e "  ${GREEN}[+] Sent SIGTERM to PID ${pid}${NC}"
        KILLED_COUNT=$((KILLED_COUNT + 1))

        # Wait a moment for graceful shutdown
        sleep 0.5

        # Check if still running
        if ps -p $pid > /dev/null 2>&1; then
            # Force kill if still running (SIGKILL)
            if kill -9 $pid 2>/dev/null; then
                echo -e "  ${YELLOW}  [!] Sent SIGKILL to PID ${pid} (process didn't respond to SIGTERM)${NC}"
            fi
        fi
    else
        echo -e "  ${RED}[-] Failed to kill PID ${pid} (may require sudo)${NC}"
        FAILED_COUNT=$((FAILED_COUNT + 1))
    fi
done

echo ""
echo -e "${BLUE}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}"

if [ $FAILED_COUNT -gt 0 ]; then
    echo -e "${YELLOW}Summary:${NC}"
    echo -e "  Killed: ${GREEN}${KILLED_COUNT}${NC}"
    echo -e "  Failed: ${RED}${FAILED_COUNT}${NC}"
    echo ""
    echo -e "${YELLOW}Some processes require elevated privileges:${NC}"
    echo -e "  ${BLUE}sudo ./cleanup_ports.sh --force${NC}"
else
    echo -e "${GREEN}[+] Successfully killed ${KILLED_COUNT} process(es)${NC}"
fi

echo ""

# Verify ports are now free
echo -e "${YELLOW}Verifying ports are now free...${NC}"
sleep 1

STILL_IN_USE=false
for port in "${ALL_PORTS[@]}"; do
    pids=$(get_port_info $port)
    if [ -n "$pids" ]; then
        echo -e "  ${RED}[-] Port ${port} still in use by PID ${pids}${NC}"
        STILL_IN_USE=true
    fi
done

if [ "$STILL_IN_USE" = false ]; then
    echo -e "  ${GREEN}[+] All server ports are now free${NC}"
fi

echo ""
