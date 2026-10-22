# Process visualization modules

Each attack's Visualizer picture is a self-contained **module**. The shell
(`../visualizer.js`) owns the generic chrome - the alert banner, status chip, the
Simulation / Attack controls, and the narration panel - and delegates the *process
picture* to the module selected by `kind`.

## Add a visualization (3 steps)

1. **Write `viz/<kind>.js`** and register it:

   ```js
   registerViz({
     kind: "power",                          // must match the WATCH_MAP kind
     title: "Power Substation",
     map(raw)            { return { load: raw.level, volts: raw.pressure, ... }; },
     build(stage)        { stage.innerHTML = `...svg + readouts...`; return refs; },
     update(refs, state) {
       // animate the picture from state; return the alert level + message:
       return { level: "critical", msg: "BUSBAR DE-ENERGISED" };
       // level ∈ normal | warning | critical | offline  -> drives the banner
     },
   });
   ```

   `raw` is the live PLC read: `{ online, level, pressure, temperature, ... }` (see
   `../../../watch_process.py`). `map` turns it into process-meaningful fields; `build`
   draws once; `update` runs each tick. Own your own thresholds in `update` - do NOT
   rely on the generic tank flags.

   Optional: `clear(refs)` resets the picture to its pristine "--" state when the
   simulation is stopped. If you omit it, the shell just re-runs `build`, which is
   usually enough.

2. **Include it** in `../../templates/watch.html` next to the others:
   `<script src="{{ url_for('static', filename='js/viz/<kind>.js') }}"></script>`
   (before `visualizer.js`).

3. **Map the attack** in `../../watch_process.py` `WATCH_MAP`: set `"kind": "<kind>"`
   (and, to support Pause->recover, a `"restore"` command). Attacks with no process go
   in `NO_VIZ`.

If `kind` has no module, the shell falls back to `generic` (honest raw channels, no
misleading shape).

## Reference modules

`heating.js` - the district-heating substation (FrostyGoop / evilscholar): heat
exchanger, circulation pump, supply/return pipes, district buildings; alert bands on
supply temperature (>55 normal, 35-55 warning, <35 freeze-protection critical).

`power.js` - the power substation (Industroyer2 / BlackEnergy3 / CrashOverride):
single-line diagram with a 13.8 kV busbar, three breakers (B1/B2/B3), transformer and
city feeders; the attack trips breakers so the bus de-energizes and the city goes dark.
Alert bands on bus voltage (nominal / a breaker open / blackout). Restore re-closes the
breakers over IEC-104 (IOA 300/301/302/303 = ON).

`gas.js` - the gas compressor station (PIPEDREAM): supply -> upstream valve -> compressor
-> downstream valve -> distribution, plus an outlet-pressure bar with a 1500 PSI redline.
The attack shuts the downstream valve with the compressor running so outlet pressure climbs
past the redline -> rupture (burst, dead pipes). Read over **OPC-UA** (real PSI values, no
water-tank scaling). Restore re-opens the downstream valve + hands back to AUTO over OPC-UA,
relieving the overpressure IF done before rupture; a rupture needs a target reset.

`safety.js` - the safety-instrumented system (TRITON / TRISIS): a water tank guarded by an
independent Triconex SIS (SIF-1) with a 90% trip line, an ESD drain, and a "safety loop"
wire from the SIS to the drain actuator. Read over **IEC-104** on the water PLC; the SIS
state is *inferred from live telemetry* - `sis` is the trip status (IOA 208) and `exploded`
the rupture (IOA 207). Level past the 90% trip with the SIS **not** tripped means the safety
program was halted: the Triconex shield turns red (**BYPASSED**) and the safety loop severs;
rupture -> **DEFEATED**. If the SIS instead trips (`sis` true) the shield goes amber and the
tank vents (safety worked). Alert bands: guarding (normal) / approaching-or-tripped (warning)
/ bypassed-or-ruptured (critical). Restore drains the tank + hands back to AUTO over IEC-104,
recovering the *process* (not the halted SIS) IF done before rupture. Note the attack targets
`plc-water`, not the `sis` host - the SIS runs as an IEC-104 client of the water PLC.
