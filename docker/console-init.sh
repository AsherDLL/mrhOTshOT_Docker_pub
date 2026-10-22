#!/bin/sh
# Console (operator/attacker workstation, IT zone 192.168.0.11) route-init.
# Reach the OT and Mgmt zones via the emulated router (192.168.0.13) so traffic
# aimed at zone IPs traverses the chokepoint. The console keeps its otlab
# interface for management + Docker DNS, so these routes only affect explicit
# 192.168.x.x zone-IP targets (set in config/targets.yaml). Best-effort: if the
# route add fails, hostname/otlab traffic is unaffected. Then start the dashboard.

ip route add 192.168.1.0/24 via 192.168.0.13 2>/dev/null || true
ip route add 192.168.100.0/24 via 192.168.0.13 2>/dev/null || true

exec "$@"
