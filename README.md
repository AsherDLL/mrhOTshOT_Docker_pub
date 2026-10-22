# mrhOTshOT Docker profile

A containerized OT/ICS lab for detection engineering and purple-team work. It
runs twelve emulated PLCs, a safety controller and a vulnerable edge router,
each speaking a real industrial protocol on its own container IP, plus an
operator HMI, a Caldera server for adversary emulation, and a web dashboard that
launches scripted attacks against the targets and shows the process reacting.

The attacks are modelled on published OT incidents (FrostyGoop, Industroyer2,
TRITON, PIPEDREAM, Stuxnet, Fuxnet and others). Nothing here touches real
hardware. The point is to generate realistic OT traffic and process behaviour so
you can test detection rules against it, and to keep pcaps you can replay later.

## Minimum requirements

| | |
|---|---|
| OS | Linux or macOS. x86_64 or arm64. |
| Docker Engine | 20.10 or newer, with the Compose v2 plugin (`docker compose`). Tested on 28.5.1 and Compose v2.40.0. |
| Python | 3.8 or newer on the host, standard library only. Used for one HMI seeding script. Tested on 3.12. |
| RAM | 2 GB free to run the lab. 4 GB free for the first build. |
| Disk | About 4.5 GB of images. Caldera is 2.3 GB of that. |
| Network | Required for the first build. It pulls base images and clones the MITRE OT plugins. After that the lab runs offline. |
| Privileges | Whatever your Docker setup needs. The lab publishes ports below 1024 (102, 161, 502), which the daemon binds for you. |

Ports published on the host: 102, 161/udp, 502, 1502/udp, 1881, 2404, 4840,
5000, 5020, 8080, 8102, 8888, 8889, 9600, 20000, 20001, 47808/udp. The installer
warns you if any are already taken.

## Quick start

```
git clone https://github.com/AsherDLL/mrhOTshOT_Docker_pub.git
cd mrhOTshOT_Docker_pub
./scripts/install.sh
```

The first run builds the images, which takes a while. When it finishes:

- Dashboard: http://127.0.0.1:8888 (login `root` / `root`)
- Operator HMI (FUXA): http://localhost:1881/home
- Caldera: http://localhost:8889 (login `root` / `root`)

Change the dashboard login with `MRHOTSHOT_UI_USER` and `MRHOTSHOT_UI_PASS`, or
set `MRHOTSHOT_UI_PASS_HASH` to a sha256 digest, which takes precedence.

Pick an attack in the dashboard, press Launch, then open its Visualize view to
watch the process respond. Restore puts the plant back.

To check your host before installing anything, run `./scripts/preflight.sh` on
its own.

## The lab

| Service | Role | Protocol and port |
|---|---|---|
| plc-water | Water treatment | IEC-104 2404 |
| plc-power | Power substation | IEC-61850 8102 |
| plc-gas | Gas pipeline | OPC-UA 4840, FINS 9600 |
| plc-centrifuge | Centrifuge cascade | S7comm 102 |
| plc-hvac | Building HVAC | BACnet/IP 47808/udp |
| plc-boiler | Boiler house | Modbus 5020 |
| plc-heating | District heating | Modbus TCP 502 |
| plc-dnp3 | Water utility | DNP3 20000 |
| plc-sensors | Sensor network | M-Bus 5000 |
| plc-vehicle | Vehicle CAN bus | CANopen over TCP 20001 |
| plc-signals | Traffic signals | NTCIP over SNMP 161/udp |
| sis | Safety system | TriStation 1502/udp |
| router | Edge router and IT/OT chokepoint | HTTP 8080 |
| fuxa | Operator HMI | 1881 |
| caldera | Adversary emulation | 8889 |
| console | Dashboard and attack runner | 8888 |

Three zone subnets model a Purdue layout on top of a flat management network:
IT 192.168.0.0/24, OT 192.168.1.0/24, management 192.168.100.0/24. The router is
multi-homed across them and NATs IT to OT, so an attack aimed at an OT address
crosses it the way it would in a real plant.

## Make targets

```
make install        preflight, build, start everything
make lab-up         build and start the target lab
make lab-down       stop the lab and remove its volumes
make lab-ps         container status
make console-up     start the dashboard
make console-down   stop the dashboard
make console-logs   follow dashboard logs
make hmi-seed       load the operator view into FUXA
make sensor-up      start the passive Suricata IDS (optional)
make sensor-down    stop the sensor
make sensor-logs    follow IDS alerts
make test           unit tests
make lint           ruff
make clean          stop everything and remove the images
```

`make lab-down` removes the FUXA volume, so the seeded HMI view goes with it.
Use `make lab-stop` if you just want the containers stopped.

## Scope and safe use

This lab runs working attack code against emulated targets. Keep it on a host
you control. The containers sit on private Docker bridges and only the ports
listed above are published, but the dashboard can run arbitrary scripted attacks
and the Caldera agent beacons out to its own server inside the lab network.

Two things to know before you expose anything:

- `docker/caldera/local.yml` ships MITRE Caldera's stock defaults, including the
  `root:root` login and `ADMIN123` encryption key. That is fine for a local lab
  and it is why the dashboard can reach the API without a second login. Do not
  put port 8889 on an untrusted network without changing them.
- The safety-system service implements the Triconex TriStation protocol, which
  is the TRITON attack surface. It is here because the TRITON scenario needs a
  target to talk to.

Do not point the attack scripts at equipment you are not authorized to test.

## Optional: the report-to-scenario assistant

The dashboard has a Chatbot tab that can read a threat report and turn its OT
indicators into a new scenario. It is off unless you supply an API key:

```
cp docker/agent.env.example docker/agent.env
# edit docker/agent.env and add a key for one provider
make console-down && make console-up
```

Keys are read from the environment only. `docker/agent.env` is gitignored and no
key is ever read from the browser. The lab works fine without this.

## Adding a scenario

Attacks are YAML, one file per scenario in
`final_things/iec104_water_tank/demo/scenarios/`. A manifest names the protocol,
the target, the argv to run and which watch view to use. Drop a new file in and
the dashboard picks it up, so you do not need to touch any Python or JavaScript
to onboard one. See `frostygoop_steps.yaml` for a worked example.

## Credit

mrhOTshOT was created and developed jointly by Asher Davila and Malav Vyas, who
are equal authors of the work. Published here with permission. The vendored
Triconex honeypot is from Nozomi Networks under BSD 3-Clause. See NOTICE.
