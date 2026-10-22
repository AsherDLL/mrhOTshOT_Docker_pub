#!/bin/sh
# mrhOTshOT sensor log janitor.
#
# Suricata's eve.json records every flow, so the log dir grows steadily even when
# idle. This keeps /var/log/suricata under a size budget: when a live log file
# passes the rotate threshold it is rotated (renamed with a timestamp) and Suricata
# is told to reopen a fresh file (SIGHUP); whenever the directory total exceeds the
# budget, the OLDEST rotated files are deleted to make room for new logs.
#
# Runs as a background child of the sensor container (started by entrypoint.sh).
# Knobs (env): SENSOR_LOG_MAX_MB (total budget, default 500),
# SENSOR_LOG_ROTATE_MB (per-file rotate size, default 100),
# SENSOR_LOG_CHECK_SEC (poll interval, default 60).
DIR=/var/log/suricata
BUDGET_MB=${SENSOR_LOG_MAX_MB:-500}
ROTATE_MB=${SENSOR_LOG_ROTATE_MB:-100}
INTERVAL=${SENSOR_LOG_CHECK_SEC:-60}

dir_mb()  { du -sm "$DIR" 2>/dev/null | cut -f1; }
file_mb() { [ -f "$1" ] && echo $(( $(wc -c < "$1") / 1048576 )) || echo 0; }

echo "[sensor] log janitor: budget ${BUDGET_MB}MB, rotate at ${ROTATE_MB}MB/file, every ${INTERVAL}s"
while true; do
    sleep "$INTERVAL"
    rotated=0
    for f in eve.json fast.log stats.log; do
        sz=$(file_mb "$DIR/$f")
        if [ "$sz" -ge "$ROTATE_MB" ]; then
            mv "$DIR/$f" "$DIR/$f.$(date +%Y%m%d_%H%M%S)" 2>/dev/null &&
                { echo "[sensor] rotated $f (${sz}MB)"; rotated=1; }
        fi
    done
    # Suricata reopens its log files on SIGHUP; it is PID 1 in this container.
    [ "$rotated" = "1" ] && kill -HUP 1 2>/dev/null
    # Enforce the total budget: delete oldest rotated files until under budget.
    while [ "$(dir_mb)" -gt "$BUDGET_MB" ]; do
        oldest=$(ls -1tr "$DIR"/eve.json.* "$DIR"/fast.log.* "$DIR"/stats.log.* 2>/dev/null | head -n1)
        [ -z "$oldest" ] && break
        rm -f "$oldest" && echo "[sensor] log budget ${BUDGET_MB}MB exceeded - deleted oldest: $(basename "$oldest")"
    done
done
