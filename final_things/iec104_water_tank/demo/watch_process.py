"""Live process readers for the dashboard "Watch" view.

Reads the real process state of a target PLC so the operator can watch an attack
change the plant in real time. Two protocols are wired: IEC-104 (water / power / SIS
processes on :2404) and Modbus/TCP (district heating on :502). All the PLC sims share
the water-tank data model, so one normalized dict drives one mimic:

    {online, level(%), pressure(bar), temperature(C),
     inlet_valve, outlet_valve, pump, overflow, low_level, high_pressure,
     exploded, sis}   (booleans may be None when a protocol cannot read them)
"""
import os
import sys
import socket
import struct
import itertools

# Heating "restore to normal": clear the injected fake supply temp (HR1 = 0) + auto ON (coil 3)
# (coil 3 = AutoModeCmd) -> HeatingDistrict re-enters its heating branch and recovers.
_HEATING_RESTORE = {"proto": "modbus", "port": 502, "unit": 11, "registers": {1: 0}, "coils": {3: True}}

# Power-substation "restore to normal": re-close all breakers (IOA 300/301/302 = ON =
# Breaker1/3/2 Cmd) and re-enable protection (IOA 303 = ON) -> PowerSubstation
# re-energizes (voltage back to 13.8 kV, blackout clears).
_POWER_RESTORE = {"proto": "iec104", "port": 2404, "ca": 1, "sc": {303: True, 300: True, 301: True, 302: True}}

# Gas-pipeline "restore to normal": re-open the downstream valve + hand back to AUTO so
# the compressor station regulates (relieves overpressure). Only works BEFORE a rupture;
# a ruptured pipeline needs a target reset. OPC-UA command nodes on the GasPipeline object.
_GAS_RESTORE = {"proto": "opcua", "port": 4840,
                "cmds": {"AutoModeCommand": True, "OutletValveCommand": True,
                         "InletValveCommand": True, "PumpCommand": True}}

# BADOMEN (FINS) faults the OMRON CPU so monitoring goes blind; restore = FINS RUN
# (0x0401) brings the CPU back to RUN and reads work again.
_GAS_FINS_RESTORE = {"proto": "fins", "port": 9600}

# TRITON halts the SIS (TriStation) then overflows the tank; restore = drain and hand
# back to AUTO over IEC-104 to the water PLC (close inlet, open drain, pump off, auto on)
# so the tank recovers. Only works BEFORE rupture; a ruptured tank needs a target reset.
# (The SIS controller itself stays halted until the lab is reset - this recovers the
# process, not the safety system.)
_SAFETY_RESTORE = {"proto": "iec104", "port": 2404, "ca": 1,
                   "sc": {300: False, 301: True, 302: False, 303: True}}

# Stuxnet writes malicious speed setpoints to the centrifuge S7 PLC (DB3) and sets
# the DB890 rootkit flag so DB4 is spoofed to the HMI. Restore = write normal
# 1007 Hz setpoints back to DB3 + clear the rootkit flag over S7, so surviving
# rotors spin back to normal and the HMI stops lying. DESTROYED rotors stay
# destroyed (the sim forces their setpoint to 0) -- a wrecked cascade needs a reset.
_CENTRIFUGE_RESTORE = {"proto": "s7", "port": 102, "rack": 0, "slot": 1, "normal_hz": 1007.0}

# DB3 byte 13: the S7 adapter's CPU RUN/STOP mirror. Published as ordinary memory
# because python-snap7's get_cpu_state() never queries the PLC.
S7_CPU_RUN_BYTE = 13

# The BACnet HVAC attack disables the control loop (AutoModeCmd) and forces heating.
# Restore = hand control back to AUTO (AO3=1) + stop forcing heat (AO0=0) over BACnet;
# the DDC's loop then re-cools the zone. Only recovers before the process is left
# too hot for the demo; a reset always returns baseline.
_HVAC_RESTORE = {"proto": "bacnet", "port": 47808}

# Industroyer DNP3 stops the pump stations and seizes manual control via CROB writes.
# Restore = DIRECT OPERATE CROB LATCH_ON on the four binary outputs (BO0 inlet,
# BO1 pump station 2, BO2 pump station 1, BO3 auto mode) so both pumps restart and
# the outstation returns to AUTO -- the operator regains control and the reservoir
# refills. Only recovers a still-supplied utility; a fully drained reservoir needs a reset.
_DNP3_RESTORE = {"proto": "dnp3", "port": 20000, "master": 100, "outstation": 1,
                 "crob": {0: True, 1: True, 2: True, 3: True}}

# CAN injection floods throttle=100 / brake=0 (runaway). Restore returns the vehicle to
# clean normal operation: NMT-reset it (zero speed/throttle/brake, so Start Simulation is
# never polluted by a prior test) then set a steady cruise throttle (~60 km/h), brake off.
_VEHICLE_RESTORE = {"proto": "canopen", "port": 20001, "node": 1, "reset": True,
                    "sdo": [(0x2001, 0), (0x2000, 40)]}   # brake=0, throttle=40 (cruise)

# NTCIP signal override SNMP-SETs phaseControlGroupHold to conflict the rings. Restore =
# SNMP-SET the hold object back to 0x00 so the controller resumes its normal phase cycle.
_SIGNAL_RESTORE = {"proto": "ntcip", "port": 161, "community": "public"}

# Restore tables by name, so a scenario manifest can say `restore: power` instead
# of referencing a Python object. Several scenarios share one table (power serves
# four), which is why these stay here rather than being copied per manifest.
RESTORES = {
    "heating":    _HEATING_RESTORE,
    "power":      _POWER_RESTORE,
    "gas":        _GAS_RESTORE,
    "gas_fins":   _GAS_FINS_RESTORE,
    "safety":     _SAFETY_RESTORE,
    "centrifuge": _CENTRIFUGE_RESTORE,
    "hvac":       _HVAC_RESTORE,
    "dnp3":       _DNP3_RESTORE,
    "vehicle":    _VEHICLE_RESTORE,
    "signal":     _SIGNAL_RESTORE,
}

# Per-scenario watch config now lives in each demo/scenarios/<id>.yaml `watch:`
# block ({plc, proto, unit?, kind, label?, restore?}, or the string "none" for an
# attack with no process to visualize). scenario_loader is imported lazily inside
# the accessors below so this module still stands alone without pulling in yaml.
DEFAULT = {"plc": "water", "proto": "iec104", "kind": "generic"}


def _watch(attack_id):
    import scenario_loader
    return scenario_loader.watch_entry(attack_id)


def no_viz():
    """Attack ids with no process view (initial-access / recon)."""
    import scenario_loader
    return {aid for aid in scenario_loader.docs() if scenario_loader.watch_entry(aid) == "none"}

PROC_LABEL = {
    "water":   "Water Treatment Plant",
    "power":   "Power Substation",
    "heating": "District Heating Substation",
    "gas":     "Gas Compressor Station",
    "sis":     "Safety-Instrumented Process",
    "boiler":  "Boiler House",
    "centrifuge": "Centrifuge Cascade",
    "hvac":    "Building HVAC",
    "dnp3":    "DNP3 Water Utility",
    "sensors": "Sensor Gateway",
    "vehicle": "Vehicle CAN Bus",
    "signals": "Traffic Signal Controller",
}


# Per-protocol I/O point maps for the Watch view's "I/O MAP" panel. These are the
# actual protocol addresses each reader polls (R) and each restore/attack writes (W),
# with `key` = the field in the reader's state dict that carries the live value
# (dotted paths index into lists/dicts, e.g. "setpoints.0"). Sourced from the readers
# and _*_RESTORE tables above -- i.e. the real registers/coils/IOAs/points on the wire.
IO_POINTS = {
    "modbus": {"endpoint": ":502 unit 11", "points": [
        {"rw": "R", "addr": "IR 0", "type": "input-reg", "label": "supply temperature C (real)", "key": "level"},
        {"rw": "R", "addr": "IR 1", "type": "input-reg", "label": "header pressure bar", "key": "pressure"},
        {"rw": "R", "addr": "IR 2", "type": "input-reg", "label": "return temperature C", "key": "temperature"},
        {"rw": "R", "addr": "IR 3", "type": "input-reg", "label": "supply setpoint C", "key": "setpoint"},
        {"rw": "R", "addr": "IR 4", "type": "input-reg", "label": "heat source firing", "key": "heater_on"},
        {"rw": "R", "addr": "IR 5", "type": "input-reg", "label": "reading spoofed", "key": "spoof"},
        {"rw": "R", "addr": "IR 6", "type": "input-reg", "label": "supply temperature C (HMI)", "key": "reported"},
        {"rw": "W", "addr": "HR 1", "type": "holding-reg", "label": "inject fake supply temp"},
        {"rw": "W", "addr": "Coil 3", "type": "coil", "label": "auto-mode cmd"},
    ]},
    "iec104": {"endpoint": ":2404 CA 1", "points": [
        {"rw": "R", "addr": "IOA 100", "type": "M_ME_NB_1", "label": "measured value 1 (level)", "key": "level"},
        {"rw": "R", "addr": "IOA 101", "type": "M_ME_NB_1", "label": "measured value 2 (pressure)", "key": "pressure"},
        {"rw": "R", "addr": "IOA 102", "type": "M_ME_NB_1", "label": "measured value 3 (temp)", "key": "temperature"},
        {"rw": "R", "addr": "IOA 200", "type": "M_SP_NA_1", "label": "inlet valve", "key": "inlet_valve"},
        {"rw": "R", "addr": "IOA 201", "type": "M_SP_NA_1", "label": "outlet valve", "key": "outlet_valve"},
        {"rw": "R", "addr": "IOA 202", "type": "M_SP_NA_1", "label": "pump", "key": "pump"},
        {"rw": "R", "addr": "IOA 206", "type": "M_SP_NA_1", "label": "high-pressure alarm", "key": "high_pressure"},
        {"rw": "R", "addr": "IOA 207", "type": "M_SP_NA_1", "label": "tank exploded", "key": "exploded"},
        {"rw": "R", "addr": "IOA 208", "type": "M_SP_NA_1", "label": "SIS tripped", "key": "sis"},
        {"rw": "W", "addr": "IOA 300", "type": "C_SC_NA_1", "label": "breaker/inlet cmd"},
        {"rw": "W", "addr": "IOA 301", "type": "C_SC_NA_1", "label": "breaker/drain cmd"},
        {"rw": "W", "addr": "IOA 302", "type": "C_SC_NA_1", "label": "breaker/pump cmd"},
        {"rw": "W", "addr": "IOA 303", "type": "C_SC_NA_1", "label": "protection/auto cmd"},
    ]},
    "s7": {"endpoint": ":102 rack0/slot1", "points": [
        {"rw": "RW", "addr": "DB3.DBD0", "type": "REAL", "label": "rotor 1 speed setpoint Hz", "key": "setpoints.0"},
        {"rw": "RW", "addr": "DB3.DBD4", "type": "REAL", "label": "rotor 2 speed setpoint Hz", "key": "setpoints.1"},
        {"rw": "RW", "addr": "DB3.DBD8", "type": "REAL", "label": "rotor 3 speed setpoint Hz", "key": "setpoints.2"},
        {"rw": "R", "addr": "DB4.DBD0", "type": "REAL", "label": "rotor 1 reported speed Hz", "key": "centrifuges.0.reported"},
        {"rw": "R", "addr": "DB4.DBW12", "type": "WORD", "label": "rotor 1 status", "key": "centrifuges.0.status_name"},
        {"rw": "RW", "addr": "DB890.DBX4.0", "type": "BOOL", "label": "rootkit mask flag", "key": "rootkit"},
        {"rw": "R", "addr": "DB3.DBX13.0", "type": "BOOL", "label": "CPU in RUN", "key": "cpu_run",
         "alarm": {"equals": False, "level": "critical",
                   "msg": "CONTROLLER HALTED - CPU in STOP, the process is not being "
                          "controlled and displayed values are frozen"}},
        {"rw": "W", "addr": "PLC STOP", "type": "S7 0x29", "label": "halt the CPU"},
        {"rw": "W", "addr": "PLC COLD START", "type": "S7 0x28", "label": "restart the CPU"},
    ]},
    "dnp3": {"endpoint": ":20000 master100/out1", "points": [
        {"rw": "R", "addr": "AI 0", "type": "g30v5", "label": "reservoir %", "key": "reservoir"},
        {"rw": "R", "addr": "AI 1", "type": "g30v5", "label": "distribution pressure PSI", "key": "pressure_psi"},
        {"rw": "R", "addr": "AI 2", "type": "g30v5", "label": "chlorine residual mg/L", "key": "chlorine"},
        {"rw": "R", "addr": "BI 0", "type": "g1", "label": "pump station 1", "key": "ps1"},
        {"rw": "R", "addr": "BI 1", "type": "g1", "label": "pump station 2", "key": "ps2"},
        {"rw": "R", "addr": "BI 3", "type": "g1", "label": "auto mode", "key": "auto"},
        {"rw": "W", "addr": "BO 0", "type": "g12v1 CROB", "label": "inlet valve latch"},
        {"rw": "W", "addr": "BO 2", "type": "g12v1 CROB", "label": "pump station 1 latch", "key": "ps1"},
        {"rw": "W", "addr": "BO 3", "type": "g12v1 CROB", "label": "auto-mode latch", "key": "auto"},
    ]},
    "opcua": {"endpoint": ":4840", "points": [
        {"rw": "R", "addr": "WaterLevel", "type": "Variable", "label": "outlet pressure", "key": "level"},
        {"rw": "R", "addr": "Pressure", "type": "Variable", "label": "inlet pressure", "key": "pressure"},
        {"rw": "R", "addr": "Temperature", "type": "Variable", "label": "gas temperature", "key": "temperature"},
        {"rw": "R", "addr": "OutletValveStatus", "type": "Variable", "label": "outlet valve", "key": "outlet_valve"},
        {"rw": "R", "addr": "PumpStatus", "type": "Variable", "label": "compressor", "key": "pump"},
        {"rw": "R", "addr": "AlarmHighPressure", "type": "Variable", "label": "high-pressure alarm", "key": "high_pressure"},
        {"rw": "R", "addr": "TankExploded", "type": "Variable", "label": "pipeline ruptured", "key": "exploded"},
        {"rw": "W", "addr": "OutletValveCommand", "type": "Variable", "label": "outlet valve cmd", "key": "outlet_valve"},
        {"rw": "W", "addr": "AutoModeCommand", "type": "Variable", "label": "auto-mode cmd"},
    ]},
    "fins": {"endpoint": ":9600 DM/CIO", "points": [
        {"rw": "R", "addr": "DM 100", "type": "REAL", "label": "outlet pressure (level)", "key": "level"},
        {"rw": "R", "addr": "DM 102", "type": "REAL", "label": "inlet pressure", "key": "pressure"},
        {"rw": "R", "addr": "DM 104", "type": "REAL", "label": "gas temperature", "key": "temperature"},
        {"rw": "R", "addr": "CIO 0.0", "type": "bit", "label": "inlet valve", "key": "inlet_valve"},
        {"rw": "R", "addr": "CIO 0.1", "type": "bit", "label": "outlet valve", "key": "outlet_valve"},
        {"rw": "R", "addr": "CIO 0.2", "type": "bit", "label": "compressor", "key": "pump"},
        {"rw": "R", "addr": "CIO 0.7", "type": "bit", "label": "overpressure/rupture", "key": "exploded"},
        {"rw": "W", "addr": "0x0402", "type": "FINS", "label": "STOP CPU (BADOMEN fault)"},
        {"rw": "W", "addr": "0x0401", "type": "FINS", "label": "RUN CPU (restore)"},
    ]},
    "bacnet": {"endpoint": ":47808 foreign-dev", "points": [
        {"rw": "R", "addr": "AI 0", "type": "analog-input", "label": "zone temperature C", "key": "zone_temp"},
        {"rw": "R", "addr": "AI 2", "type": "analog-input", "label": "supply air C", "key": "supply_air"},
        {"rw": "R", "addr": "AI 3", "type": "analog-input", "label": "heating active", "key": "heating"},
        {"rw": "R", "addr": "AI 5", "type": "analog-input", "label": "fan running", "key": "fan"},
        {"rw": "R", "addr": "AI 6", "type": "analog-input", "label": "auto mode", "key": "auto"},
        {"rw": "R", "addr": "AI 7", "type": "analog-input", "label": "high-temp alarm", "key": "hi_alarm"},
        {"rw": "W", "addr": "AO 0", "type": "analog-output", "label": "hot-water valve cmd", "key": "heating"},
        {"rw": "W", "addr": "AO 3", "type": "analog-output", "label": "auto-mode cmd", "key": "auto"},
    ]},
    "mbus": {"endpoint": ":5000 addr 1", "points": [
        {"rw": "R", "addr": "REQ_UD2", "type": "record", "label": "Volume L", "key": "volume"},
        {"rw": "R", "addr": "REQ_UD2", "type": "record", "label": "Pressure bar", "key": "pressure"},
        {"rw": "R", "addr": "REQ_UD2", "type": "record", "label": "Temperature C", "key": "temperature"},
        {"rw": "R", "addr": "REQ_UD2", "type": "record", "label": "Flow L/h", "key": "flow"},
        {"rw": "W", "addr": "SND_UD", "type": "C=0x53", "label": "poison records (Fuxnet)"},
        {"rw": "W", "addr": "SND_NKE", "type": "broadcast", "label": "brick gateway (irreversible)"},
    ]},
    "canopen": {"endpoint": ":20001 node 1", "points": [
        {"rw": "RW", "addr": "OD 0x2000", "type": "U8", "label": "throttle % (commanded)", "key": "throttle"},
        {"rw": "RW", "addr": "OD 0x2001", "type": "U8", "label": "brake % (commanded)", "key": "brake"},
        {"rw": "R", "addr": "OD 0x2005", "type": "U8", "label": "driver throttle % (real)", "key": "driver_throttle"},
        {"rw": "R", "addr": "OD 0x2006", "type": "U8", "label": "driver brake % (real)", "key": "driver_brake"},
        {"rw": "R", "addr": "OD 0x2002", "type": "U16", "label": "speed km/h", "key": "speed"},
        {"rw": "R", "addr": "OD 0x2003:1", "type": "I16", "label": "accel longitudinal mg", "key": "accel_x"},
        {"rw": "R", "addr": "OD 0x2003:2", "type": "I16", "label": "accel lateral mg", "key": "accel_y"},
        {"rw": "R", "addr": "OD 0x2003:3", "type": "I16", "label": "accel vertical mg", "key": "accel_z"},
        {"rw": "W", "addr": "SDO 0x601", "type": "CANopen", "label": "throttle override (attack)"},
    ]},
    "ntcip": {"endpoint": ":161/udp community public", "points": [
        {"rw": "R", "addr": ".1.4.1.2.1", "type": "OCTET", "label": "phase greens (bitmap)", "key": "greens"},
        {"rw": "R", "addr": ".1.4.1.3.1", "type": "OCTET", "label": "phase yellows (bitmap)", "key": "yellows"},
        {"rw": "R", "addr": ".1.4.1.4.1", "type": "OCTET", "label": "phase reds (bitmap)", "key": "reds"},
        {"rw": "RW", "addr": ".1.5.1.4.1", "type": "OCTET", "label": "phaseControlGroupHold (override)"},
        {"rw": "R", "addr": "sysDescr", "type": "OCTET", "label": "controller identity"},
    ]},
}


def plan(attack_id):
    """Return {plc, proto, unit?, kind, restore?, label, direct, noviz, io} for an attack.

    Signature and return shape are unchanged by the manifest migration - every
    caller (the watch page, its stream, reset and restore) still gets the same dict.
    """
    tgt = _watch(attack_id)
    if tgt == "none":
        return {"noviz": True, "kind": None, "label": "", "direct": False}
    direct = isinstance(tgt, dict)
    tgt = dict(tgt) if direct else dict(DEFAULT)
    # A manifest names its restore table; resolve it to the real one here so
    # scenario_loader never has to know about them.
    if isinstance(tgt.get("restore"), str):
        tgt["restore"] = RESTORES.get(tgt["restore"])
    if tgt.get("restore") is None:
        tgt.pop("restore", None)
    return {**tgt, "kind": tgt.get("kind", "generic"),
            "label": tgt.get("label") or PROC_LABEL.get(tgt["plc"], tgt["plc"]),
            "io": IO_POINTS.get(tgt["proto"], {}),
            "direct": direct, "noviz": False}


def restore(plan_, host):
    """Send a process's normal-op protocol writes so it recovers from an attack.
    Returns True if a restore was issued. Heating = Modbus coil writes (pump + auto ON)."""
    r = plan_.get("restore")
    if not r:
        return False
    ip = socket.gethostbyname(host)
    if r["proto"] == "modbus":
        from pymodbus.client import ModbusTcpClient
        c = ModbusTcpClient(ip, port=r.get("port", 502), timeout=4)
        c.connect()
        try:
            for reg, val in r.get("registers", {}).items():
                c.write_register(int(reg), int(val), slave=r.get("unit", 11))
            for coil, val in r.get("coils", {}).items():
                c.write_coil(int(coil), bool(val), slave=r.get("unit", 11))
        finally:
            c.close()
        return True
    if r["proto"] == "iec104":
        import c104, time
        cl = c104.Client()
        conn = cl.add_connection(ip=ip, port=r.get("port", 2404), init=c104.Init.ALL)
        st = conn.add_station(common_address=r.get("ca", 1))
        pts = {ioa: st.add_point(io_address=int(ioa), type=c104.Type.C_SC_NA_1)
               for ioa in r.get("sc", {})}
        cl.start()
        time.sleep(1.5)
        try:
            for ioa, val in r.get("sc", {}).items():
                pts[ioa].value = bool(val)
                pts[ioa].transmit(cause=c104.Cot.ACTIVATION)
                time.sleep(0.2)
        finally:
            cl.stop()
        return True
    if r["proto"] == "opcua":
        from asyncua.sync import Client
        from asyncua import ua
        cl = Client(f"opc.tcp://{ip}:{r.get('port', 4840)}")
        cl.connect()
        try:
            cmds = _opcua_folder(cl, "Commands")
            for name, val in r.get("cmds", {}).items():
                if name in cmds:
                    cmds[name].write_value(ua.DataValue(ua.Variant(bool(val), ua.VariantType.Boolean)))
        finally:
            cl.disconnect()
        return True
    if r["proto"] == "fins":
        _fins_command(ip, r.get("port", 9600), 0x0401)   # FINS RUN -> clear the fault
        return True
    if r["proto"] == "s7":
        import snap7
        cl = snap7.client.Client()
        cl.connect(ip, r.get("rack", 0), r.get("slot", 1), r.get("port", 102))
        try:
            hz = float(r.get("normal_hz", 1007.0))
            cl.db_write(3, 0, struct.pack(">fff", hz, hz, hz))  # DB3 setpoints -> normal
            cl.db_write(890, 4, bytes([0x00]))                  # clear DB890 rootkit flag
            # Restart a halted CPU LAST, never first: a restarted CPU re-applies whatever
            # DB3 holds on its first scan, so starting before the writes above would
            # briefly re-command the attacker's overspeed on every restore.
            #
            # Ask the CPU-state mirror whether a restart is even needed rather than
            # firing one blind and swallowing the error - a swallowed failure would let
            # this report "restored" with the controller still halted, which is exactly
            # the lying-status problem the mirror exists to remove. A genuine failure
            # propagates; the caller turns it into an error the operator can see.
            if not bool(cl.db_read(3, S7_CPU_RUN_BYTE, 1)[0]):
                cl.plc_cold_start()
        finally:
            cl.disconnect()
        return True
    if r["proto"] == "dnp3":
        import time
        s = socket.socket(); s.settimeout(4); s.connect((ip, r.get("port", 20000)))
        try:
            seq = 0
            for idx, val in r.get("crob", {}).items():   # DIRECT OPERATE CROB LATCH_ON/OFF
                seq = (seq + 1) & 0x0F
                s.sendall(_dnp3_frame(_dnp3_crob_request(int(idx), bool(val), seq),
                                      r.get("master", 100), r.get("outstation", 1)))
                try:
                    s.recv(1024)
                except Exception:
                    pass
                time.sleep(0.2)
        finally:
            s.close()
        return True
    if r["proto"] == "bacnet":
        import asyncio
        async def _do():
            from bacpypes3.argparse import SimpleArgumentParser
            from bacpypes3.app import Application
            app = Application.from_args(SimpleArgumentParser().parse_args(
                ["--foreign", ip, "--ttl", "30", "--instance", "597"]))
            try:
                async def set_ao(inst, val):   # prime-then-set (DDC fires on change only)
                    await app.write_property(ip, "analog-output,%d" % inst, "present-value",
                                             100.0 if val == 0.0 else 0.0)
                    await app.write_property(ip, "analog-output,%d" % inst, "present-value", float(val))
                await set_ao(3, 1.0)   # AutoModeCmd -> ON  (hand control back to the loop)
                await set_ao(0, 0.0)   # HotWaterValveCmd -> 0 (stop forcing heat)
            finally:
                app.close()
        asyncio.run(_do())
        return True
    if r["proto"] == "canopen":
        s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        s.settimeout(4)
        s.connect((ip, r.get("port", 20001)))
        try:
            node = r.get("node", 1)
            if r.get("reset"):                           # zero speed/throttle/brake first (clean baseline)
                s.sendall(struct.pack(">HB", 0x000, 2) + bytes([0x81, node]).ljust(8, b"\x00"))   # NMT reset
            s.sendall(struct.pack(">HB", 0x000, 2) + bytes([0x01, node]).ljust(8, b"\x00"))   # NMT start (operational)
            for index, value in r.get("sdo", []):        # SDO-write brake=0 / throttle=cruise
                frame = (struct.pack(">HB", 0x600 + node, 8)
                         + bytes([0x2F, index & 0xFF, (index >> 8) & 0xFF, 0])
                         + (value & 0xFFFFFFFF).to_bytes(4, "little"))
                s.sendall(frame)
                try:
                    s.recv(64)
                except socket.timeout:
                    pass
        finally:
            s.close()
        return True
    if r["proto"] == "ntcip":                            # SNMP-SET phaseControlGroupHold = 0x00
        hold_oid = (1, 3, 6, 1, 4, 1, 1206, 4, 2, 1, 1, 5, 1, 4, 1)
        vb = _snmp_tlv(0x30, _snmp_oid(hold_oid) + _snmp_tlv(0x04, b"\x00"))
        msg = _snmp_msg(0xA3, [vb], r.get("community", "public").encode(), 0x55)
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.settimeout(4)
        try:
            s.sendto(msg, (ip, r.get("port", 161)))
            try:
                s.recvfrom(2048)
            except socket.timeout:
                pass
        finally:
            s.close()
        return True
    return False


# ---- OMRON FINS/TCP --------------------------------------------------------
def _fins_frame(cmd_code, cmd_data=b""):
    hdr = bytes([0x80, 0x00, 0x02, 0x00, 0x00, 0x00, 0x00, 0x01, 0x00, 0x01])
    return hdr + struct.pack(">H", cmd_code) + cmd_data


def _fins_send(ip, port, cmd_code, cmd_data=b"", timeout=4):
    """FINS/TCP: handshake, send one command, return the FINS response payload."""
    s = socket.socket(); s.settimeout(timeout); s.connect((ip, port))
    try:
        s.sendall(b"FINS" + struct.pack(">III", 12, 0, 0) + struct.pack(">I", 0))
        s.recv(24)   # handshake response
        body = _fins_frame(cmd_code, cmd_data)
        s.sendall(b"FINS" + struct.pack(">III", len(body) + 8, 2, 0) + body)
        resp = s.recv(1024)
        return resp[16:]   # strip 'FINS'+len+cmd+err(16 bytes) -> FINS payload
    finally:
        s.close()


def _fins_command(ip, port, cmd_code):
    try:
        _fins_send(ip, port, cmd_code)
        return True
    except Exception:
        return False


class FinsReader:
    """Reads a process served over OMRON FINS/TCP (gas pipeline on :9600). DM holds
    the measurements as 32-bit floats (2 words): DM[100]=outlet pressure, DM[102]=
    inlet, DM[104]=gas temp; CIO[0] bits = valves/pump/auto + alarm flags. When
    BADOMEN forces the CPU into ERROR mode, reads return end code 0x2201 -> offline,
    i.e. the operator loses monitoring."""

    def __init__(self, host, port=9600):
        self._host, self._port = host, port
        self._ip = socket.gethostbyname(host)

    @staticmethod
    def _flt(words, i):
        return struct.unpack(">f", struct.pack(">HH", words[i], words[i + 1]))[0]

    def read(self):
        d = {"online": False, "level": None, "pressure": None, "temperature": None,
             "inlet_valve": None, "outlet_valve": None, "pump": None,
             "overflow": None, "low_level": None, "high_pressure": None,
             "exploded": None, "sis": None}
        try:
            # FINS payload = [10-byte header][2 cmd][2 end code][data words...]
            dm = _fins_send(self._ip, self._port, 0x0101,
                            struct.pack(">BHBH", 0x82, 100, 0, 6))
            if len(dm) < 26 or struct.unpack(">H", dm[12:14])[0] != 0:
                return d          # faulted (0x2201) or bad -> offline
            data = dm[14:26]
            words = [struct.unpack(">H", data[i:i + 2])[0] for i in range(0, 12, 2)]
            cio = _fins_send(self._ip, self._port, 0x0101, struct.pack(">BHBH", 0xB0, 0, 0, 1))
            cw = struct.unpack(">H", cio[14:16])[0] if len(cio) >= 16 and struct.unpack(">H", cio[12:14])[0] == 0 else 0
            d.update(online=True,
                     level=round(self._flt(words, 0), 1), pressure=round(self._flt(words, 2), 1),
                     temperature=round(self._flt(words, 4), 1),
                     inlet_valve=bool(cw & 1), outlet_valve=bool(cw & 2), pump=bool(cw & 4),
                     high_pressure=bool(cw & 0x40), exploded=bool(cw & 0x80),
                     overflow=bool(cw & 0x80))
        except Exception:
            pass
        return d

    def close(self):
        pass


def _opcua_process_object(client):
    """The process object is the custom one that carries a Measurements folder
    (skips the standard Server/Aliases/Locations objects)."""
    for o in client.nodes.objects.get_children():
        for f in o.get_children():
            if f.read_browse_name().Name == "Measurements":
                return o
    return None


def _opcua_folder(client, folder):
    """Return {variableName: node} for one folder under the process object."""
    obj = _opcua_process_object(client)
    out = {}
    if obj:
        for f in obj.get_children():
            if f.read_browse_name().Name == folder:
                for v in f.get_children():
                    out[v.read_browse_name().Name] = v
    return out


# ---- IEC-104 (c104 master) -------------------------------------------------
_IEC_MEAS = {100: "level", 101: "pressure", 102: "temperature"}
_IEC_STAT = {200: "inlet_valve", 201: "outlet_valve", 202: "pump", 204: "overflow",
             205: "low_level", 206: "high_pressure", 207: "exploded", 208: "sis"}


def _decode(name, raw):
    if raw is None:
        return None
    raw = float(raw)
    if name == "level" or name == "temperature":
        return round(raw / 327.67, 1)      # 0-100% / 0-100C -> 0-32767
    if name == "pressure":
        return round(raw / 2184.5, 1)      # 0-15 bar -> 0-32767
    return round(raw, 1)


class Iec104Reader:
    def __init__(self, host, port=2404):
        import c104
        self._c104 = c104
        ip = socket.gethostbyname(host)
        self.client = c104.Client()
        self.conn = self.client.add_connection(ip=ip, port=port, init=c104.Init.INTERROGATION)
        st = self.conn.add_station(common_address=1)
        self.pts = {}
        for ioa in _IEC_MEAS:
            self.pts[ioa] = st.add_point(io_address=ioa, type=c104.Type.M_ME_NB_1)
        for ioa in _IEC_STAT:
            self.pts[ioa] = st.add_point(io_address=ioa, type=c104.Type.M_SP_NA_1)
        self.client.start()

    def read(self):
        online = bool(self.conn.is_connected)
        d = {"online": online}
        for ioa, nm in _IEC_MEAS.items():
            d[nm] = _decode(nm, self.pts[ioa].value) if online else None
        for ioa, nm in _IEC_STAT.items():
            v = self.pts[ioa].value
            d[nm] = bool(v) if (online and v is not None) else None
        return d

    def close(self):
        try:
            self.client.stop()
        except Exception:
            pass


# ---- Modbus/TCP ------------------------------------------------------------
class ModbusReader:
    """Heating PLC exposes level/pressure/temp on input registers 0-2 (x0.1);
    valves/pump/alarms are not served, so status is derived from thresholds."""

    def __init__(self, host, unit=11, port=502):
        from pymodbus.client import ModbusTcpClient
        self.unit = unit
        self.c = ModbusTcpClient(socket.gethostbyname(host), port=port, timeout=3)
        self.c.connect()

    @staticmethod
    def _s(x):
        return x - 65536 if x > 32767 else x

    def read(self):
        d = {"online": False, "level": None, "pressure": None, "temperature": None,
             "inlet_valve": None, "outlet_valve": None, "pump": None,
             "overflow": None, "low_level": None, "high_pressure": None,
             "exploded": None, "sis": None,
             "setpoint": None, "heater_on": None, "spoof": None, "reported": None}
        try:
            if not getattr(self.c, "connected", True):
                self.c.connect()   # reconnect after the PLC was restarted (reset)
            r = self.c.read_input_registers(0, count=7, slave=self.unit)
            if not r.isError():
                lv, pr, tp = (self._s(x) / 10.0 for x in r.registers[:3])
                d.update(online=True, level=round(lv, 1), pressure=round(pr, 1),
                         temperature=round(tp, 1),
                         low_level=lv < 20, high_pressure=pr > 8, overflow=lv >= 98)
                if len(r.registers) >= 7:   # heating exposes setpoint(IR3), heater(IR4), spoof(IR5), HMI temp(IR6)
                    d.update(setpoint=round(self._s(r.registers[3]) / 10.0, 1),
                             heater_on=bool(r.registers[4]), spoof=bool(r.registers[5]),
                             reported=round(self._s(r.registers[6]) / 10.0, 1))
        except Exception:
            try:
                self.c.connect()
            except Exception:
                pass
        return d

    def close(self):
        try:
            self.c.close()
        except Exception:
            pass


# ---- OPC-UA -----------------------------------------------------------------
class OpcuaReader:
    """Reads a process served over OPC-UA (gas pipeline on :4840). The engineering
    values are real (no water-tank scaling clamp): WaterLevel = outlet pressure,
    Pressure = inlet pressure, Temperature = gas temp, plus valve/compressor/alarm
    booleans on the process object's Measurements/Status/Alarms folders."""

    def __init__(self, host, port=4840):
        from asyncua.sync import Client
        self._host, self._port = host, port
        self.client = None
        self._connect()

    def _connect(self):
        from asyncua.sync import Client
        ip = socket.gethostbyname(self._host)
        self.client = Client(f"opc.tcp://{ip}:{self._port}")
        self.client.connect()
        obj = _opcua_process_object(self.client)
        self.nodes = {}
        if obj:
            for f in obj.get_children():
                if f.read_browse_name().Name in ("Measurements", "Status", "Alarms"):
                    for v in f.get_children():
                        self.nodes[v.read_browse_name().Name] = v

    def read(self):
        d = {"online": False, "level": None, "pressure": None, "temperature": None,
             "inlet_valve": None, "outlet_valve": None, "pump": None,
             "overflow": None, "low_level": None, "high_pressure": None,
             "exploded": None, "sis": None}
        try:
            def rv(name):
                nd = self.nodes.get(name)
                return nd.read_value() if nd is not None else None
            wl, pr, tp = rv("WaterLevel"), rv("Pressure"), rv("Temperature")
            d.update(online=True,
                     level=round(float(wl), 1) if wl is not None else None,          # outlet pressure
                     pressure=round(float(pr), 1) if pr is not None else None,        # inlet pressure
                     temperature=round(float(tp), 1) if tp is not None else None,     # gas temp
                     inlet_valve=_b(rv("InletValveStatus")), outlet_valve=_b(rv("OutletValveStatus")),
                     pump=_b(rv("PumpStatus")), overflow=_b(rv("AlarmOverflow")),
                     high_pressure=_b(rv("AlarmHighPressure")), exploded=_b(rv("TankExploded")),
                     low_level=_b(rv("AlarmLowLevel")), sis=_b(rv("SisTripped")))
        except Exception:
            try:                       # reconnect after the PLC was restarted (reset)
                self.close(); self._connect()
            except Exception:
                pass
        return d

    def close(self):
        try:
            self.client.disconnect()
        except Exception:
            pass


def _b(v):
    return bool(v) if v is not None else None


# ---- Siemens S7 (centrifuge cascade - Stuxnet) -----------------------------
_CENT_STATUS = {0: "NORMAL", 1: "OVERSPEED", 2: "UNDERSTEED", 3: "DAMAGED", 4: "DESTROYED"}


class S7CentrifugeReader:
    """Reads the Siemens S7 centrifuge cascade (Stuxnet target, plc-centrifuge:102).
    Three data blocks tell the whole Stuxnet story:
      DB3   - the speed setpoints the attacker writes (3x REAL Hz) + cascade_enable.
              NOT masked, so the malicious 1410 Hz / 2 Hz command is visible here.
      DB4   - the measurements the HMI trusts (per unit: REAL speed, vib, temp, WORD
              status). The DB890 rootkit MASKS this to a calm 1007 Hz during the attack.
      DB890 - the Stuxnet rootkit flag (byte 4, bit 0). Set => DB4 is spoofed.
    We surface both sides so the operator can be seen being lied to: DB3 commands
    1410 Hz overspeed while DB4 still reports 1007 Hz. The reader does not fit the
    water-tank dict, so it carries its own `centrifuges`/`rootkit` fields; the water
    keys stay None. Multiple snap7 clients (this reader + the attacker) share the PLC."""

    DB_SETPOINTS, DB_MEAS, DB_STUXNET, STRIDE = 3, 4, 890, 16

    def __init__(self, host, port=102, rack=0, slot=1):
        import snap7
        self._snap7 = snap7
        self._ip = socket.gethostbyname(host)
        self._port, self._rack, self._slot = port, rack, slot
        self.client = snap7.client.Client()
        self._connect()

    def _connect(self):
        try:
            self.client.connect(self._ip, self._rack, self._slot, self._port)
        except Exception:
            pass

    @staticmethod
    def _f(buf, off):
        return struct.unpack_from(">f", buf, off)[0]

    def read(self):
        d = {"online": False, "level": None, "pressure": None, "temperature": None,
             "inlet_valve": None, "outlet_valve": None, "pump": None,
             "overflow": None, "low_level": None, "high_pressure": None,
             "exploded": None, "sis": None,
             "rootkit": None, "cascade_enable": None, "centrifuges": None, "setpoints": None,
             "cpu_run": None}
        try:
            if not self.client.get_connected():
                self._connect()
            db3 = self.client.db_read(self.DB_SETPOINTS, 0, 16)
            db4 = self.client.db_read(self.DB_MEAS, 0, 48)
            db890 = self.client.db_read(self.DB_STUXNET, 0, 8)
            setpoints = [round(self._f(db3, i * 4), 1) for i in range(3)]
            cents = []
            for i in range(3):
                b = i * self.STRIDE
                st = struct.unpack_from(">H", db4, b + 12)[0]
                cents.append({
                    "commanded":   setpoints[i],                  # DB3 - the real command
                    "reported":    round(self._f(db4, b), 1),     # DB4 - the HMI value (masked)
                    "vib":         round(self._f(db4, b + 4), 2),
                    "temp":        round(self._f(db4, b + 8), 1),
                    "status":      st,
                    "status_name": _CENT_STATUS.get(min(st, 4), "?"),
                })
            d.update(online=True, rootkit=bool(db890[4] & 0x01),
                     cascade_enable=bool(db3[12]), centrifuges=cents, setpoints=setpoints,
                     # DB3 byte 13: the adapter's CPU RUN/STOP mirror. snap7's client
                     # get_cpu_state() is a stub that always answers Run, so the state
                     # has to be read as ordinary memory. Already inside the DB3[0:16]
                     # fetch above - no extra round trip.
                     cpu_run=bool(db3[13]))
        except Exception:
            try:
                self.client.disconnect()
            except Exception:
                pass
            self._connect()
        return d

    def close(self):
        try:
            self.client.disconnect()
        except Exception:
            pass


# ---- DNP3 (raw outstation client -- Industroyer DNP3) ----------------------
def _dnp3_crc(data):
    crc = 0x0000
    for b in data:
        crc ^= b
        for _ in range(8):
            crc = (crc >> 1) ^ 0xA6BC if crc & 1 else crc >> 1
    return crc ^ 0xFFFF


def _dnp3_frame(app_layer, master, outstation):
    """Wrap an application layer in DNP3 transport + link layers (master -> outstation)."""
    tr = b'\xc0' + app_layer                                  # transport: FIR/FIN
    lh = b'\x05\x64' + bytes([len(tr) + 5, 0x80 | 0x44])      # start, len, ctrl (DIR|PRM|FC4)
    lh += struct.pack('<HH', outstation, master)
    lh += struct.pack('<H', _dnp3_crc(lh[:8]))
    out = lh
    for i in range(0, len(tr), 16):                           # data blocks + CRC each
        blk = tr[i:i + 16]
        out += blk + struct.pack('<H', _dnp3_crc(blk))
    return out


def _dnp3_read_request(seq=1):
    """Class-0 integrity poll (Group 60 Var 1) -- the outstation dumps all objects."""
    return struct.pack('BB', 0xc0 | (seq & 0x0f), 0x01) + struct.pack('BBB', 60, 1, 0x06)


def _dnp3_crob_request(index, value, seq=1):
    """DIRECT OPERATE (FC5) a CROB (Group 12 Var 1) LATCH_ON/LATCH_OFF on one index."""
    crob = struct.pack('BB', 0x03 if value else 0x04, 1) + struct.pack('<II', 1000, 1000) + b'\x00'
    hdr = struct.pack('BBBB', 12, 1, 0x01, 1) + bytes([index & 0xff])
    return struct.pack('BB', 0xc0 | (seq & 0x0f), 0x05) + hdr + crob


def _dnp3_strip_crcs(body):
    """Drop the 2-byte CRC that follows every <=16-byte data block."""
    out, i = b'', 0
    while i < len(body):
        ch = body[i:i + 18]
        if len(ch) < 3:
            break
        out += ch[:-2]
        i += 18
    return out


def _dnp3_parse_response(frame):
    """Parse an outstation read response into (analog-inputs, binary-inputs) dicts."""
    if len(frame) < 12 or frame[0:2] != b'\x05\x64':
        return None, None
    payload = _dnp3_strip_crcs(frame[10:])[:max(0, frame[2] - 5)]
    app = payload[1:]                                         # drop transport byte
    if len(app) < 4 or app[1] != 0x81:                       # FC_RESPONSE (129)
        return None, None
    objs, ai, bi, i = app[4:], {}, {}, 0
    while i + 4 <= len(objs):
        g, v, _q, cnt = objs[i], objs[i + 1], objs[i + 2], objs[i + 3]
        i += 4
        for _ in range(cnt):
            if i + 2 > len(objs):
                return ai, bi
            idx, flags = objs[i], objs[i + 1]
            i += 2
            if g == 30 and v == 5:                            # analog input, float
                if i + 4 > len(objs):
                    return ai, bi
                ai[idx] = struct.unpack_from('<f', objs, i)[0]
                i += 4
            elif g == 40:                                     # analog output status, float
                i += 4
            elif g == 1:                                      # binary input
                bi[idx] = bool(flags & 0x01)
            # g == 10 (binary output status): index+flags already consumed
    return ai, bi


class Dnp3Reader:
    """Reads the DNP3 water-distribution outstation (Industroyer DNP3, plc-dnp3:20000).
    A Class-0 integrity poll returns analog inputs (AI0 reservoir %, AI1 distribution
    pressure PSI, AI2 chlorine residual mg/L) and binary inputs (BI0 pump station 1,
    BI1 pump station 2, BI3 auto mode, BI4 high-chlorine, BI5 low-reservoir, BI6
    low-pressure). Industroyer's DNP3 tradecraft stops the pump stations and forces
    manual mode via CROB writes to the binary outputs; this reader surfaces that so
    the seized control and lost supply are visible."""

    def __init__(self, host, port=20000, master=100, outstation=1):
        self._ip = socket.gethostbyname(host)
        self._port, self._master, self._outstation = port, master, outstation
        self.sock, self._seq = None, 0
        self._connect()

    def _connect(self):
        try:
            self.sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            self.sock.settimeout(4)
            self.sock.connect((self._ip, self._port))
        except Exception:
            self.sock = None

    def read(self):
        d = {"online": False, "level": None, "pressure": None, "temperature": None,
             "inlet_valve": None, "outlet_valve": None, "pump": None,
             "overflow": None, "low_level": None, "high_pressure": None,
             "exploded": None, "sis": None,
             "reservoir": None, "pressure_psi": None, "chlorine": None,
             "ps1": None, "ps2": None, "auto": None,
             "low_reservoir": None, "low_pressure": None, "high_chlorine": None}
        try:
            if self.sock is None:
                self._connect()
                if self.sock is None:
                    return d
            self._seq = (self._seq + 1) & 0x0f
            self.sock.sendall(_dnp3_frame(_dnp3_read_request(self._seq), self._master, self._outstation))
            ai, bi = _dnp3_parse_response(self.sock.recv(4096))
            if ai is None:
                raise ValueError("bad DNP3 response")
            d.update(online=True,
                     reservoir=round(ai[0], 1) if 0 in ai else None,
                     pressure_psi=round(ai[1], 1) if 1 in ai else None,
                     chlorine=round(ai[2], 2) if 2 in ai else None,
                     ps1=bi.get(0), ps2=bi.get(1), auto=bi.get(3),
                     high_chlorine=bi.get(4), low_reservoir=bi.get(5), low_pressure=bi.get(6))
        except Exception:
            try:
                if self.sock:
                    self.sock.close()
            except Exception:
                pass
            self.sock = None
        return d

    def close(self):
        try:
            if self.sock:
                self.sock.close()
        except Exception:
            pass


# ---- M-Bus (sensor gateway -- Fuxnet) --------------------------------------
_MBUS_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))   # iec104_water_tank


class MbusReader:
    """Reads the M-Bus sensor gateway (Fuxnet target, plc-sensors:5000) with the lab's
    mbus_lib master. A REQ_UD2 read returns the gateway's metered records (Volume L,
    Pressure bar, Temperature C, Flow L/h). Fuxnet floods SND_UD frames to CORRUPT the
    gateway -- the records collapse to a poison signature (temperature -40 C, pressure
    0, volume 99999.9 L) -- and then a broadcast SND_NKE bricks it OFFLINE (the gateway
    drops the connection and stops answering). These three wire-observable states are
    surfaced as `gw_state` so the operator can watch the sensor field be poisoned then
    go dark. The bricking is irreversible (as in the real 2024 attack): no restore."""

    def __init__(self, host, port=5000, address=1):
        if _MBUS_ROOT not in sys.path:
            sys.path.insert(0, _MBUS_ROOT)
        from server.mbus_lib import MBusClient
        self._MBusClient = MBusClient
        self._ip = socket.gethostbyname(host)
        self._port, self._addr = port, address
        self.cli = None
        self._connect()

    def _connect(self):
        try:
            self.cli = self._MBusClient(self._ip, self._port, timeout=3)
            self.cli.connect()
        except Exception:
            self.cli = None

    def _reconnect(self):
        try:
            if self.cli:
                self.cli.disconnect()
        except Exception:
            pass
        self._connect()

    def read(self):
        d = {"online": False, "level": None, "pressure": None, "temperature": None,
             "inlet_valve": None, "outlet_valve": None, "pump": None,
             "overflow": None, "low_level": None, "high_pressure": None,
             "exploded": None, "sis": None,
             "gw_state": None, "volume": None, "flow": None, "corrupted": None}
        try:
            if self.cli is None:
                self._connect()
                if self.cli is None:
                    return d                       # gateway unreachable
            frame = self.cli.read(self._addr)
            if frame is None or not frame.valid:
                d.update(online=True, gw_state="offline", corrupted=True)   # bricked
                self._reconnect()
                return d
            rec = {r.name: r.value for r in frame.records}
            vol, pres, temp = rec.get("Volume"), rec.get("Pressure"), rec.get("Temperature")
            flow = rec.get("Flow")
            corrupted = (temp is not None and temp <= -39) or (vol is not None and vol >= 99999)
            d.update(online=True, gw_state=("corrupted" if corrupted else "online"), corrupted=corrupted,
                     volume=round(vol, 1) if vol is not None else None,
                     pressure=round(pres, 2) if pres is not None else None,
                     temperature=round(temp, 1) if temp is not None else None,
                     flow=round(flow, 0) if flow is not None else None)
        except Exception:
            self._reconnect()
        return d

    def close(self):
        try:
            if self.cli:
                self.cli.disconnect()
        except Exception:
            pass


# ---- BACnet/IP (building HVAC - FrostyGoop/BACnet) -------------------------
# Each reader registers with the BBMD under its own BACnet device instance, so
# concurrent watch streams (two HVAC tabs) don't collide. 600+ avoids the fixed
# ids the attacker (599) and restore (597) use. next() is atomic under the GIL.
_bacnet_reader_ids = itertools.count()


class BacnetHvacReader:
    """Reads the BACnet building-HVAC DDC (plc-hvac:47808) via bacpypes3. The DDC
    is a BACnet BBMD, and binding the subnet broadcast socket fails inside a
    container, so we register as a *foreign device* (unicast only) exactly like a
    real off-subnet BAS client. bacpypes3 is async, so a private asyncio loop runs
    in a daemon thread and each read() marshals ReadProperty onto it.
    AI map: 0=zone_temp 2=supply_air 3=heating 4=cooling 5=fan 6=auto 7=hi_temp_alarm.
    Coexists with the attacker (a second foreign device, different instance id)."""

    AIS = {0: "zone_temp", 2: "supply_air", 3: "heating", 4: "cooling",
           5: "fan", 6: "auto", 7: "hi_alarm"}

    def __init__(self, host, port=47808):
        import asyncio
        import threading
        self._ip = socket.gethostbyname(host)
        self._instance = 600 + next(_bacnet_reader_ids) % 4000   # unique per reader
        self._loop = asyncio.new_event_loop()
        self._app = None
        self._err = None
        self._ready = threading.Event()
        threading.Thread(target=self._run, daemon=True).start()
        if not self._ready.wait(timeout=20) or self._err:
            raise RuntimeError("BACnet reader init failed: %s" % self._err)

    def _run(self):
        import asyncio
        asyncio.set_event_loop(self._loop)
        self._loop.run_until_complete(self._setup())
        self._loop.run_forever()

    async def _setup(self):
        try:
            from bacpypes3.argparse import SimpleArgumentParser
            from bacpypes3.app import Application
            self._app = Application.from_args(SimpleArgumentParser().parse_args(
                ["--foreign", self._ip, "--ttl", "60", "--instance", str(self._instance)]))
        except Exception as e:
            self._err = e
        finally:
            self._ready.set()

    async def _read_all(self):
        out = {}
        for inst, name in self.AIS.items():
            try:
                out[name] = float(await self._app.read_property(
                    self._ip, "analog-input,%d" % inst, "present-value"))
            except Exception:
                out[name] = None
        return out

    def read(self):
        import asyncio
        d = {"online": False, "level": None, "pressure": None, "temperature": None,
             "inlet_valve": None, "outlet_valve": None, "pump": None,
             "overflow": None, "low_level": None, "high_pressure": None,
             "exploded": None, "sis": None,
             "zone_temp": None, "supply_air": None, "heating": None,
             "cooling": None, "fan": None, "auto": None, "hi_alarm": None}
        if not self._app:
            return d
        try:
            v = asyncio.run_coroutine_threadsafe(self._read_all(), self._loop).result(timeout=8)
            if v.get("zone_temp") is not None:
                b = lambda x: (x > 0.5) if x is not None else None
                d.update(online=True, zone_temp=round(v["zone_temp"], 1),
                         supply_air=round(v["supply_air"], 1) if v["supply_air"] is not None else None,
                         heating=b(v["heating"]), cooling=b(v["cooling"]), fan=b(v["fan"]),
                         auto=b(v["auto"]), hi_alarm=b(v["hi_alarm"]))
        except Exception:
            pass
        return d

    def close(self):
        import asyncio
        try:
            if self._app:
                asyncio.run_coroutine_threadsafe(self._aclose(), self._loop).result(timeout=5)
        except Exception:
            pass
        try:
            self._loop.call_soon_threadsafe(self._loop.stop)
        except Exception:
            pass

    async def _aclose(self):
        try:
            self._app.close()
        except Exception:
            pass


# ---- CANopen vehicle node (CAN over TCP -- CAN Bus Injection) ---------------
class VehicleReader:
    """Reads the vehicle CANopen node (plc-vehicle:20001) over the CAN-over-TCP gateway
    by SDO-reading the throttle/brake/speed/accelerometer object-dictionary entries."""

    def __init__(self, host, port=20001):
        self._ip = socket.gethostbyname(host)
        self._port = port
        self.sock = None
        self._buf = b""
        self._connect()

    def _connect(self):
        try:
            self.sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            self.sock.settimeout(3)
            self.sock.connect((self._ip, self._port))
            self._buf = b""
        except OSError:
            self.sock = None

    @staticmethod
    def _pack(cob, data):
        data = bytes(data)[:8]
        return struct.pack(">HB", cob, len(data)) + data.ljust(8, b"\x00")

    def _frame(self):
        while len(self._buf) < 11:
            chunk = self.sock.recv(1024)
            if not chunk:
                raise ConnectionError("closed")
            self._buf += chunk
        f, self._buf = self._buf[:11], self._buf[11:]
        cob, dlc = struct.unpack(">HB", f[:3])
        return cob, f[3:3 + dlc]

    def _sdo_read(self, index, sub=0):
        self.sock.sendall(self._pack(0x601, bytes([0x40, index & 0xFF, index >> 8, sub, 0, 0, 0, 0])))
        for _ in range(60):
            cob, data = self._frame()
            if cob == 0x581:
                return None if data[0] == 0x80 else int.from_bytes(data[4:8], "little")
        return None

    def read(self):
        d = {"online": False, "level": None, "pressure": None, "temperature": None,
             "inlet_valve": None, "outlet_valve": None, "pump": None, "overflow": None,
             "low_level": None, "high_pressure": None, "exploded": None, "sis": None,
             "speed": None, "throttle": None, "brake": None,
             "driver_throttle": None, "driver_brake": None,
             "accel_x": None, "accel_y": None, "accel_z": None}
        try:
            if self.sock is None:
                self._connect()
                if self.sock is None:
                    return d
            s16 = lambda v: (v - 65536 if v > 32767 else v) if v is not None else None
            spd = self._sdo_read(0x2002)
            if spd is not None:
                d.update(online=True, speed=round(spd / 10.0, 1),
                         throttle=self._sdo_read(0x2000), brake=self._sdo_read(0x2001),
                         driver_throttle=self._sdo_read(0x2005), driver_brake=self._sdo_read(0x2006),
                         accel_x=s16(self._sdo_read(0x2003, 1)),
                         accel_y=s16(self._sdo_read(0x2003, 2)),
                         accel_z=s16(self._sdo_read(0x2003, 3)))
        except (OSError, ConnectionError):
            try:
                self.sock.close()
            except Exception:
                pass
            self.sock = None
        return d

    def close(self):
        try:
            self.sock.close()
        except Exception:
            pass


# ---- NTCIP traffic-signal controller (SNMP -- Signal Override) --------------
def _snmp_tlv(tag, val):
    if len(val) < 0x80:
        ln = bytes([len(val)])
    else:
        b = b""
        n = len(val)
        while n:
            b = bytes([n & 0xFF]) + b
            n >>= 8
        ln = bytes([0x80 | len(b)]) + b
    return bytes([tag]) + ln + val


def _snmp_oid(arcs):
    b = bytearray([40 * arcs[0] + arcs[1]])
    for a in arcs[2:]:
        if a < 128:
            b.append(a)
        else:
            stack = [a & 0x7F]
            a >>= 7
            while a:
                stack.append((a & 0x7F) | 0x80)
                a >>= 7
            b.extend(reversed(stack))
    return _snmp_tlv(0x06, bytes(b))


def _snmp_ptlv(buf, off=0):
    tag = buf[off]
    off += 1
    ln = buf[off]
    off += 1
    if ln & 0x80:
        nb = ln & 0x7F
        ln = int.from_bytes(buf[off:off + nb], "big")
        off += nb
    return tag, buf[off:off + ln], off + ln


def _snmp_msg(pdu_tag, varbinds, community=b"public", rid=1):
    pdu = _snmp_tlv(pdu_tag, _snmp_tlv(0x02, bytes([rid & 0xFF])) + b"\x02\x01\x00\x02\x01\x00"
                    + _snmp_tlv(0x30, b"".join(varbinds)))
    return _snmp_tlv(0x30, b"\x02\x01\x01" + _snmp_tlv(0x04, community) + pdu)   # v2c


class SignalReader:
    """Reads the NTCIP signal controller (plc-signals:161) over SNMP: the phase-status
    objects (greens/yellows/reds bitmaps) decoded into main (N/S) and cross (E/W) state."""
    _BASE = (1, 3, 6, 1, 4, 1, 1206, 4, 2, 1, 1, 4, 1)
    _OIDS = [_BASE + (2, 1), _BASE + (3, 1), _BASE + (4, 1)]          # greens, yellows, reds
    P_MAIN, P_CROSS = 0x02, 0x08

    def __init__(self, host, port=161, community=b"public"):
        self._addr = (socket.gethostbyname(host), port)
        self._comm = community
        self._rid = 0x70
        self.sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self.sock.settimeout(3)

    @staticmethod
    def _word(mask, g, y, r):
        return "green" if g & mask else "yellow" if y & mask else "red" if r & mask else "dark"

    def read(self):
        d = {"online": False, "level": None, "pressure": None, "temperature": None,
             "inlet_valve": None, "outlet_valve": None, "pump": None, "overflow": None,
             "low_level": None, "high_pressure": None, "exploded": None, "sis": None,
             "greens": None, "yellows": None, "reds": None,
             "main": None, "cross": None, "conflict": None}
        try:
            self._rid = (self._rid + 1) & 0xFF
            vbs = [_snmp_tlv(0x30, _snmp_oid(o) + b"\x05\x00") for o in self._OIDS]
            self.sock.sendto(_snmp_msg(0xA0, vbs, self._comm, self._rid), self._addr)
            data, _ = self.sock.recvfrom(4096)
            # walk to the varbind list and pull each OCTET STRING value in order
            _, body, _ = _snmp_ptlv(data)
            _, _v, o = _snmp_ptlv(body, 0)
            _, _c, o = _snmp_ptlv(body, o)
            _, pdu, _ = _snmp_ptlv(body, o)
            _, _r, po = _snmp_ptlv(pdu, 0)
            _, _es, po = _snmp_ptlv(pdu, po)
            _, _ei, po = _snmp_ptlv(pdu, po)
            _, vbl, _ = _snmp_ptlv(pdu, po)
            octets, o = [], 0
            while o < len(vbl):
                _, vb, o = _snmp_ptlv(vbl, o)
                _, _name, vo = _snmp_ptlv(vb, 0)
                vt, vv, _ = _snmp_ptlv(vb, vo)
                octets.append(vv[0] if (vt == 0x04 and vv) else 0)
            if len(octets) >= 3:
                g, y, r = octets[0], octets[1], octets[2]
                d.update(online=True, greens=g, yellows=y, reds=r,
                         main=self._word(self.P_MAIN, g, y, r),
                         cross=self._word(self.P_CROSS, g, y, r),
                         conflict=bool(g & self.P_MAIN) and bool(g & self.P_CROSS))
        except (OSError, IndexError, ValueError):
            pass
        return d

    def close(self):
        try:
            self.sock.close()
        except OSError:
            pass


def make_reader(proto, host, unit=11):
    if proto == "ntcip":
        return SignalReader(host)
    if proto == "canopen":
        return VehicleReader(host)
    if proto == "modbus":
        return ModbusReader(host, unit=unit)
    if proto == "opcua":
        return OpcuaReader(host)
    if proto == "fins":
        return FinsReader(host)
    if proto == "s7":
        return S7CentrifugeReader(host)
    if proto == "dnp3":
        return Dnp3Reader(host)
    if proto == "mbus":
        return MbusReader(host)
    if proto == "bacnet":
        return BacnetHvacReader(host)
    return Iec104Reader(host)
