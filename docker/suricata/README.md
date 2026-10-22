# mrhOTshOT Detection Engine (Suricata sensor, Beta)

A passive **Suricata** IDS that watches the lab's OT network live and raises an alert
the moment an attack's control or command traffic crosses the wire. Built for
purple-team use: run an attack, watch the detection fire in real time, tune the
rules, or point your own detection engine at the same traffic.

This is a self-contained, opt-in add-on. It does not modify the core lab
(`docker/docker-compose.yml`) or the ESXi setup.

## Quick start

Start the lab first so the network bridges exist, then bring up the sensor:

```bash
make lab-up        # start the OT lab
make sensor-up     # build + start the passive Suricata sensor
make sensor-logs   # live one-line alerts on the CLI (fast.log)
make sensor-down   # stop the sensor
```

Then launch any attack from the dashboard (`http://127.0.0.1:8888`) and watch the
**Detections** tab, or the CLI via `make sensor-logs`, light up.

## How it works (why a passive tap)

Docker bridge networks are switched, so a container attached to a network cannot see
other containers' traffic. The sensor therefore runs in the host network namespace
and passively sniffs the lab's bridge interfaces - the software equivalent of a
SPAN/tap. It never forwards or blocks packets.

It taps the `otlab` and `it-net` bridges. The lab is zoned like a real plant: the
attacker console lives in the IT zone (`192.168.0.0/24`) and the PLCs live in the OT
zone (`192.168.1.0/24`), with a router between them. Tapping `it-net` (the IT/attacker
zone) lets the sensor see an attack the moment it crosses from IT into OT, with the
real attacker source IP - before the router's SNAT rewrites it. So an alert reads as a
true cross-zone event, e.g. `192.168.0.11 (IT) -> 192.168.1.16 (OT)`. `otlab` carries
hostname-addressed and Caldera C2 traffic.

`make sensor-up` resolves the bridge names and passes them in `SENSOR_IFACES`; if that
is empty the sensor auto-detects every `br-*` interface. Alerts are written to
`final_things/iec104_water_tank/demo/detections/` (`eve.json` + `fast.log`), which the
dashboard reads live over Server-Sent Events.

## What it detects (zone / policy based)

In a segmented (Purdue-style) network, control and write operations to field devices
are only legitimate from the authorized OT zone. The rules detect the OPERATION
generally (a write or control command per protocol) and flag it when the source is
OUTSIDE that zone - an operator workstation in IT, a C2 pivot, an external host. So
alerts read as `... from unauthorized zone`, and benign HMI polling from inside the OT
zone (neither a write nor from an unauthorized source) produces zero alerts.

The authorized zone is `$OT_ZONE`, set by the sensor entrypoint (default the OT control
subnet `192.168.1.0/24`; override with `SENSOR_OT_ZONE`).

| Protocol | Port | Flags (from outside $OT_ZONE) |
|----------|------|-------------------------------|
| Modbus/TCP | 502 | any write (coil/register) |
| IEC-104 | 2404 | any control command (cause = ACTIVATION) |
| S7comm | 102 | Write Var to a data block |
| TriStation | 1502/udp | any command to the SIS |
| M-Bus | 5000 | user-data write / broadcast reset |
| OPC-UA | 4840 | WriteRequest |
| DNP3 | 20000 | control output (CROB) |
| CANopen | 20001 | SDO write |
| BACnet/IP | 47808/udp | WriteProperty (confirmed) |
| IEC-61850 | 8102 | control operate (CSWI ...Oper.ctlVal) |
| SNMP/NTCIP | 161/udp | SET-request |
| OMRON FINS | 9600 | memory-area write |
| OPC-DA/DCOM | 135 | endpoint-mapper enumeration |

Plus zone-agnostic recon (Modbus device enumeration - Read Device ID / Report Server ID),
which the HMI never performs.

This catches the whole class of unauthorized control rather than one malware's byte
pattern, and the operation matches are position-independent (relative content / the
Modbus app-layer parser), so they fire even when an attack does reconnaissance reads
first and the write is deeper in the stream.

## Editing rules / bringing your own engine

The ruleset lives in `docker/suricata/rules/ot.rules`, bind-mounted read-only - edit
it, then reload with:

```bash
make sensor-down && make sensor-up
```

The sensor is a separate opt-in Compose project (`docker/sensor.yml`). To use a
different detection engine, swap the `image` and entrypoint there - it only needs host
networking and the bridge interfaces; the tap and the shared log directory stay the
same.

## Log management

`eve.json` records every flow, so it grows over time. A background janitor keeps the
log directory under a size budget: when a log file passes the per-file rotate size it
is rotated and Suricata reopens a fresh one, and whenever the directory total exceeds
the budget the OLDEST rotated files are deleted to make room for new logs.

Defaults (override in `docker/sensor.yml` or the environment):

| Variable | Default | Meaning |
|----------|---------|---------|
| `SENSOR_LOG_MAX_MB` | 500 | total log-dir budget; oldest rotated files deleted past this |
| `SENSOR_LOG_ROTATE_MB` | 100 | rotate a log file once it reaches this size |
| `SENSOR_LOG_CHECK_SEC` | 60 | how often the janitor checks |

## Files

- `docker/sensor.yml` - opt-in Compose project (host-net, NET_RAW/NET_ADMIN).
- `docker/Dockerfile.suricata` - extends the upstream Suricata image.
- `docker/suricata/entrypoint.sh` - resolves interfaces, starts the janitor, runs Suricata.
- `docker/suricata/logrotate.sh` - the log-size janitor.
- `docker/suricata/rules/ot.rules` - the OT ruleset (editable).
- `docker/sensor_ifaces.sh` - resolves the otlab/ot-net bridge names for `make sensor-up`.

## Revert

Everything is additive. To remove: `make sensor-down`, then delete the files above and
the `detections/` output directory. A `pre-detection-engine` git tag marks the state
before this add-on.
