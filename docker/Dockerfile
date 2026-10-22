# Single image for every OT *target* role (PLC / SIS / router). Each compose
# service runs the same image with a different command. Build context is the
# repo root so we can copy the pinned requirements and the canonical tree.
#
#   docker build -f docker/Dockerfile -t mrhotshot/target .
#
FROM python:3.12-slim

# DNP3/M-Bus/FINS/etc. adapters are pure-Python raw sockets; the libs below cover
# c104 (manylinux wheel), pymodbus, asyncua, snap7 (bundled .so), bacpypes3.
ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1

# iproute2 + iptables: the `router` role uses these to forward/NAT/log traffic
# between the IT/OT/Mgmt zones (router_simulation/router_init.sh). The PLC roles
# never invoke them - harmless extra packages.
RUN apt-get update && apt-get install -y --no-install-recommends iproute2 iptables \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY docker/requirements-target.txt /tmp/requirements-target.txt
RUN pip install --no-cache-dir -r /tmp/requirements-target.txt

# Canonical tree only (node_modules, venvs, pipedream, zips excluded via .dockerignore)
COPY final_things/iec104_water_tank/ /app/

# Protocol ports (documentation; compose decides what to publish).
# IEC-104 2404 | IEC-61850 8102 | Modbus 502 | DNP3 20000 | M-Bus 5000
# TriStation 1502/udp | OPC-UA 4840 | BACnet 47808/udp | S7 102 | router 8080
EXPOSE 2404 8102 502 20000 5000 4840 102 8080

# Default role is a single-protocol PLC; compose overrides `command` per service.
ENTRYPOINT ["python3"]
CMD ["water_tank_server.py", "--protocol", "iec104", "--port", "2404"]
