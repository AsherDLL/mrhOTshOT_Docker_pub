#!/bin/sh
# Print the space-separated host bridge interfaces the OT sensor should sniff.
#
# We tap the otlab + it-net docker bridges. it-net is the IT (attacker) zone: a
# console -> OT-IP attack crosses it BEFORE the router SNATs it, so the sensor sees
# the real cross-zone flow (IT attacker 192.168.0.x -> OT target 192.168.1.x) with
# the true source IP, instead of the router's rewritten address on the OT side.
# otlab carries hostname-addressed and Caldera C2 traffic. Together they cover every
# attack path with no SNAT-duplicated alerts. Used by `make sensor-up`.
#
# Docker names a bridge "br-<first 12 chars of the network id>". If a network is
# missing (lab not up) it is skipped; empty output makes the sensor fall back to
# auto-detecting every br-* interface.
out=""
for net in otlab it-net; do
    id=$(docker network inspect -f '{{.Id}}' "$net" 2>/dev/null)
    [ -n "$id" ] && out="$out br-$(printf '%s' "$id" | cut -c1-12)"
done
printf '%s' "${out# }"
