#!/bin/sh
# mrhOTshOT OT sensor - passive multi-bridge Suricata IDS.
#
# Docker bridge networks are switched, so a container joined to a network sees only
# its own traffic. To watch ALL inter-container OT traffic we run in the host
# network namespace and sniff the host-side bridge interfaces (br-*). This is a
# passive tap - the sensor never forwards or blocks packets.
#
# SENSOR_IFACES (space-separated) pins the exact interfaces to sniff; when unset we
# auto-detect every br-* bridge. `make sensor-up` fills it with the otlab + it-net
# bridges: it-net is the IT (attacker) zone, so cross-zone attacks are seen with the
# real source IP before the router SNATs them; otlab carries hostname/C2 traffic.
set -e

IFACES="$SENSOR_IFACES"
if [ -z "$IFACES" ]; then
    for i in $(ls /sys/class/net 2>/dev/null | grep '^br-'); do
        IFACES="$IFACES $i"
    done
fi

if [ -z "$IFACES" ]; then
    echo "[sensor] no bridge interfaces found - is the lab running? (make lab-up)" >&2
    exit 1
fi

ARGS=""
for i in $IFACES; do ARGS="$ARGS -i $i"; done

# Background janitor caps /var/log/suricata (rotate + delete-oldest). It signals
# Suricata (PID 1) with SIGHUP to reopen rotated logs, so start it before exec.
/usr/local/bin/sensor-logrotate.sh &

# OT_ZONE = the authorized OT control network. Control/write operations to field
# devices are only legitimate from inside it; the rules flag anything from outside
# (the IT/enterprise zone, C2, external). Override with SENSOR_OT_ZONE if your
# authorized zone differs.
OT_ZONE="${SENSOR_OT_ZONE:-[192.168.1.0/24]}"

echo "[sensor] Suricata passive tap on:$IFACES  (authorized OT zone: $OT_ZONE)"
# Enable the Modbus app-layer parser so the Modbus rules match per transaction
# (read vs write), instead of scanning raw stream bytes - this is what keeps the
# operator HMI's benign register polling from raising false alerts.
exec suricata $ARGS -S /rules/ot.rules -l /var/log/suricata \
    --set app-layer.protocols.modbus.enabled=yes \
    --set "vars.address-groups.OT_ZONE=$OT_ZONE" "$@"
