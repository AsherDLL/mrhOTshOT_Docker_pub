#!/bin/bash
# Stop all lab processes

echo "[*] Stopping all lab processes..."

for f in /tmp/lab_*.pid; do
    if [ -f "$f" ]; then
        pid=$(cat "$f")
        kill $pid 2>/dev/null && echo "[+] Killed PID $pid ($(basename $f .pid))"
        rm -f "$f"
    fi
done

# Fallback: kill by port
for port in 2404 502 102 4840 9600 1502 5000 4444 20000 8102 61850 47808; do
    lsof -t -i :${port} 2>/dev/null | xargs kill 2>/dev/null
done

echo "[*] All stopped."
