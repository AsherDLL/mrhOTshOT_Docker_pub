#!/bin/sh
# Emulated L3 router for the otlab zones. The same container is the IT-facing
# vulnerable web app (initial-access pivot) AND the multi-homed router between
# the IT (192.168.0.0/24), OT (192.168.1.0/24) and Mgmt (192.168.100.0/24)
# zones. It enables IPv4 forwarding and SNATs IT->OT so that attacker traffic
# aimed at OT zone IPs actually traverses this container (the inter-zone
# chokepoint - a future tap/SPAN point). PLCs reply to the directly-connected
# router, so no per-PLC routes are needed. Then it execs the web server.
#
# All rules are best-effort (guarded): if NET_ADMIN / iptables are unavailable
# the chokepoint is simply dormant and the web app still starts.

echo "[router] configuring IPv4 forwarding + IT->OT NAT"
sysctl -w net.ipv4.ip_forward=1 2>/dev/null || true

# SNAT IT (192.168.0.0/24) -> OT (192.168.1.0/24). Idempotent: delete then add.
iptables -t nat -D POSTROUTING -s 192.168.0.0/24 -d 192.168.1.0/24 -j MASQUERADE 2>/dev/null || true
iptables -t nat -A POSTROUTING -s 192.168.0.0/24 -d 192.168.1.0/24 -j MASQUERADE 2>/dev/null \
  || echo "[router] WARN: could not add NAT rule (chokepoint dormant)"

# Log packets crossing the chokepoint (rate-limited so historian/watch polling
# does not flood the kernel log). Falls back to unlimited if -m limit is absent.
iptables -D FORWARD -j LOG --log-prefix "OTLAB-FWD " 2>/dev/null || true
iptables -A FORWARD -m limit --limit 10/sec --limit-burst 20 -j LOG --log-prefix "OTLAB-FWD " 2>/dev/null \
  || iptables -A FORWARD -j LOG --log-prefix "OTLAB-FWD " 2>/dev/null || true

echo "[router] ready; starting service: $*"
exec python3 "$@"
