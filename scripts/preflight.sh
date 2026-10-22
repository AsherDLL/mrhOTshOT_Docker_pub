#!/usr/bin/env sh
# Host checks for the mrhOTshOT Docker profile. Run it on its own to see whether
# this machine can host the lab, or let scripts/install.sh call it for you.
#
# Exits non-zero only on a hard blocker (no docker, no compose, no python3).
# Port conflicts and low memory are warnings: the lab may still come up, but
# those are the two things that actually bite people, so they are reported.

ok()   { printf '[OK]  %s\n' "$1"; }
warn() { printf '[!]   %s\n' "$1"; WARN=$((WARN+1)); }
bad()  { printf '[!!]  %s\n' "$1"; FAIL=$((FAIL+1)); }

WARN=0
FAIL=0

echo "mrhOTshOT preflight"
echo "-------------------"

# --- hard requirements ---------------------------------------------------
if command -v docker >/dev/null 2>&1; then
    ok "docker found: $(docker --version 2>/dev/null | head -1)"
    if docker info >/dev/null 2>&1; then
        ok "docker daemon reachable"
    else
        bad "docker is installed but the daemon is not reachable. Start Docker, or add your user to the docker group."
    fi
else
    bad "docker not found. Install Docker Engine 20.10 or newer."
fi

if docker compose version >/dev/null 2>&1; then
    ok "compose plugin: $(docker compose version 2>/dev/null | head -1)"
else
    bad "the 'docker compose' plugin is missing. This lab needs Compose v2, not docker-compose v1."
fi

if command -v python3 >/dev/null 2>&1; then
    ok "python3 found: $(python3 --version 2>&1)"
else
    bad "python3 not found. It is needed to seed the operator HMI."
fi

# --- disk ----------------------------------------------------------------
FREE_GB=$(df -Pk . 2>/dev/null | awk 'NR==2 {printf "%d", $4/1048576}')
if [ -n "$FREE_GB" ]; then
    if [ "$FREE_GB" -ge 6 ]; then
        ok "disk free here: ${FREE_GB} GB"
    else
        warn "only ${FREE_GB} GB free on this filesystem. The images need about 4.5 GB, Caldera being 2.3 GB of it."
    fi
fi

# --- memory --------------------------------------------------------------
AVAIL_MB=""
if [ -r /proc/meminfo ]; then
    AVAIL_MB=$(awk '/MemAvailable/ {printf "%d", $2/1024}' /proc/meminfo)
elif command -v sysctl >/dev/null 2>&1; then
    TOTAL=$(sysctl -n hw.memsize 2>/dev/null)
    [ -n "$TOTAL" ] && AVAIL_MB=$((TOTAL / 1048576))
fi
if [ -n "$AVAIL_MB" ]; then
    if [ "$AVAIL_MB" -ge 4096 ]; then
        ok "memory available: ${AVAIL_MB} MB"
    elif [ "$AVAIL_MB" -ge 2048 ]; then
        warn "memory available: ${AVAIL_MB} MB. Enough to run the lab, tight for the first build."
    else
        warn "memory available: ${AVAIL_MB} MB. That is below the 2 GB the running lab needs. Expect containers to be killed."
    fi
fi

# --- ports ---------------------------------------------------------------
# Every port docker-compose.yml publishes on the host.
TCP_PORTS="102 502 1881 2404 4840 5000 5020 8080 8102 8888 8889 9600 20000 20001"
UDP_PORTS="161 1502 47808"

listening() {   # listening <port> <tcp|udp>
    _p=$1; _proto=$2
    if command -v ss >/dev/null 2>&1; then
        [ "$_proto" = tcp ] && _f=-ltn || _f=-lun
        ss $_f 2>/dev/null | awk '{print $5}' | grep -qE "[:.]${_p}\$"
    elif command -v lsof >/dev/null 2>&1; then
        lsof -nP -i "${_proto}:${_p}" 2>/dev/null | grep -q LISTEN 2>/dev/null ||
            lsof -nP -i "${_proto}:${_p}" 2>/dev/null | grep -q .
    else
        return 1
    fi
}

BUSY=""
for p in $TCP_PORTS; do listening "$p" tcp && BUSY="$BUSY ${p}/tcp"; done
for p in $UDP_PORTS; do listening "$p" udp && BUSY="$BUSY ${p}/udp"; done

if [ -n "$BUSY" ]; then
    warn "these published ports are already in use:$BUSY"
    printf '      Free them, or edit the ports: lines in docker/docker-compose.yml.\n'
else
    ok "all published ports are free"
fi

# --- verdict -------------------------------------------------------------
echo "-------------------"
if [ "$FAIL" -gt 0 ]; then
    printf 'Not ready: %d blocker(s), %d warning(s).\n' "$FAIL" "$WARN"
    exit 1
fi
if [ "$WARN" -gt 0 ]; then
    printf 'Ready, with %d warning(s) above.\n' "$WARN"
else
    echo "Ready."
fi
exit 0
