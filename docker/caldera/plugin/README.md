# mrhOTshOT - Caldera OT lab pack

A small, data-only Caldera plugin that ships **ready-to-run OT attack content for the
mrhOTshOT lab**: Modbus abilities tuned to the containerized heating PLC, a fact source
pre-pointed at it, and a FrostyGoop-style sabotage adversary. It rides on top of the stock
`modbus` plugin's `modbus_cli` payload - it adds no payloads or code of its own.

> Scope: everything here targets the **simulated `plc-heating` container** on the `otlab`
> lab network. It sends real Modbus commands to that emulated PLC and to nothing else.

---

## The adversary: `mrhOTshOT - FrostyGoop-style Heating Sabotage`

Emulates the behaviour of **FrostyGoop** (a.k.a. BUSTLEBERM) - malware that abuses Modbus/TCP
to manipulate ENCO heating controllers. The adversary walks a four-step kill chain against the
lab's **ENCO ENC-12X emulation** (`plc-heating`, Modbus **unit id 11**, port **502**):

```
1. Read Coils            (recon:  pump / valve / auto-mode state)
2. Read Holding Registers(recon:  setpoints / process values)
3. Stop Circulation Pump (IMPACT: write coil 0 = OFF)
4. Read Coils            (verify: confirm the pump coil flipped)
```

Adversary id: `e53c1311-9b6b-4701-af5e-3a2c96e8ca14`.

### What "unit 11" means (and why it matters)
The stock caldera-ot Modbus abilities address **unit id 1**. This lab's heating PLC only
answers on **unit id 11**, so the abilities here pass `-d #{modbus.device.id}` (the CLI's
`--device` flag). Point them at a different Modbus device and no reply comes back - set the
right unit id in the fact source first.

---

## Prerequisites

- **Docker profile, lab up** - `make lab-up` (brings up `plc-heating` and the Caldera stack).
- **Logged in to Caldera as the red team** - `http://<host>:8889`, `root` / `root`. The
  Agents view and operations are red-team features; a blue login sees nothing.
- **An agent is present** - the `caldera-agent` sandcat agent auto-deploys on `otlab` and
  shows up under *Agents* (host `caldera-agent`, group `red`). It is the host that actually
  sends the Modbus packets to `plc-heating`.
- **Pair the adversary with its fact source** (below) - the abilities use trait names that
  only this pack's source provides, so they must be run together or the `#{...}` variables
  won't resolve.

---

## Fact source: `mrhOTshOT Heating (plc-heating, unit 11)`

Id `d350e038-ba6a-423b-b016-4eaee4cf9477`. Every ability draws its target/parameters from here:

| Trait | Value | Meaning |
|---|---|---|
| `modbus.server.ip` | `plc-heating` | target PLC (container DNS name on `otlab`) |
| `modbus.server.port` | `502` | Modbus/TCP port |
| `modbus.device.id` | `11` | Modbus **unit id** (passed via `-d`) |
| `modbus.read_coil.start` | `0` | first coil to read |
| `modbus.read_coil.count` | `4` | read coils 0–3 (pump / valve / auto-mode / …) |
| `modbus.read_holding.start` | `0` | first holding register to read |
| `modbus.read_holding.count` | `8` | read holding registers 0–7 |
| `modbus.write_coil.start` | `0` | coil to write - **0 = circulation pump** |
| `modbus.write_coil.value` | `"OFF"` | value to write (quoted on purpose - see note) |

> **YAML gotcha:** an *unquoted* `OFF` (or `ON`/`YES`/`NO`) is parsed by YAML as a boolean,
> which reaches the CLI as `False`. The value is quoted (`"OFF"`) so the command reads
> literally `write_c 0 OFF`.

---

## Abilities (in kill-chain order)

All run on the Linux agent (`sh` executor) and invoke the stock `modbus_cli` payload with
`-d #{modbus.device.id}` to reach unit 11.

| # | Ability | Tactic (ATT&CK for ICS) | Modbus function | Command (facts resolved) |
|---|---|---|---|---|
| 1 | Modbus Read Coils (heating, unit 11) | Collection - **T0861** Point & Tag Identification | FC1 Read Coils | `modbus_cli plc-heating --port 502 read_c 0 4 -d 11` |
| 2 | Modbus Read Holding Registers (heating, unit 11) | Collection - **T0861** | FC3 Read Holding Registers | `modbus_cli plc-heating --port 502 read_hr 0 8 -d 11` |
| 3 | Modbus Stop Circulation Pump (write coil, unit 11) | Impair Process Control - **T0855** Unauthorized Command Message | FC5 Write Single Coil | `modbus_cli plc-heating --port 502 write_c 0 OFF -d 11` |
| 4 | Modbus Read Coils (verify impact, unit 11) | Collection - **T0861** | FC1 Read Coils | `modbus_cli plc-heating --port 502 read_c 0 4 -d 11` |

Ability ids: 1 `da6481e0-…`, 2 `581f5b39-…`, 3 `a1567b21-…`, 4 `e6bd50b7-…`.

Abilities 1 and 4 are intentionally identical reads - the second is a distinct ability so the
same read runs again at the end to prove the coil changed (Caldera would otherwise not re-run
one ability twice in a chain).

> **Finding step 3 in the GUI:** its file lives under `data/abilities/impact/`, but its
> declared `tactic` is `impair-process-control`. Caldera groups by the `tactic` field, so look
> for it under **Impair Process Control (T0855)**, not "Impact".

---

## Running it

1. Caldera → **Operations** → **＋**.
2. **Adversary:** `mrhOTshOT - FrostyGoop-style Heating Sabotage`.
3. **Group:** `red`. **Fact source:** `mrhOTshOT Heating (plc-heating, unit 11)`.
   **Planner:** `atomic`. **Start**.
4. Click each step to see decoded output.

### Expected output

```
[1] read_c 0 4 -d 11    ->  coil 0 = ON  (pump running), coil 1 = OFF, coil 2 = ON, coil 3 = OFF
[2] read_hr 0 8 -d 11   ->  holding register 0..7 (setpoints / process values)
[3] write_c 0 OFF -d 11 ->  Write successful            (pump coil driven OFF)
[4] read_c 0 4 -d 11    ->  coil 0 = OFF (pump stopped) - impact confirmed
```

The `coil 0: ON → OFF` transition **is** the attack: an unauthorized Modbus Write Single Coil
that stops the circulation pump, the FrostyGoop effect.

> **Timing:** an operation runs at the agent's beacon interval (~1 check-in/minute, one step
> per check-in), so all four steps land over a couple of minutes. Steps appearing one at a
> time is normal, not a hang.

### Reset after a run
The run leaves the pump coil OFF. To restore it:
- edit the fact source `modbus.write_coil.value` to `"ON"` and run the sabotage step once, or
- restart the heating simulation (`docker compose ... restart plc-heating`).

---

## Blue-team / detection angle

mrhOTshOT is also a **detection-testing** lab, so this adversary is a clean, repeatable
stimulus for OT monitoring. On the wire a defender should see, sourced from the agent host
(`caldera-agent`) to `plc-heating:502`:

- FC1 **Read Coils** and FC3 **Read Holding Registers** to **unit id 11** (recon), then
- FC5 **Write Single Coil**, address **0**, value **0x0000 (OFF)** to unit id 11 - the
  unauthorized command (ATT&CK for ICS **T0855**).

Detection ideas to exercise: alert on any Modbus **write** function (FC5/FC6/FC15/FC16) to the
heating PLC, on writes from an unexpected source host, or on a coil-0 state change. Capture the
exchange with the dashboard's **pcap capture** (filter `tcp port 502 and host plc-heating`) to
feed an IDS/Zeek/Suricata ruleset.

---

## Files

```
docker/caldera/plugin/
├── hook.py                                   # registers the (data-only) plugin
└── data/
    ├── abilities/collection/da6481e0-*.yml   # 1. Read Coils
    ├── abilities/collection/581f5b39-*.yml   # 2. Read Holding Registers
    ├── abilities/impact/a1567b21-*.yml       # 3. Stop Circulation Pump (T0855)
    ├── abilities/collection/e6bd50b7-*.yml   # 4. Read Coils (verify)
    ├── adversaries/e53c1311-*.yml            # the FrostyGoop-style adversary
    └── sources/d350e038-*.yml                # the heating fact source
```

The pack is enabled via `docker/caldera/local.yml` (`plugins: [ … mrhotshot ]`) and copied into
the image by `docker/Dockerfile.caldera`, so it reloads on every `make lab-up`.
