#!/usr/bin/env python3
"""Seed the FUXA operator HMI with the OT lab's process views.

FUXA (the lab's operator HMI, http://localhost:1881) starts with an empty project,
so it opens a blank page. This builds two Modbus/TCP devices and two operator views:

  * HS-1 Heating    - district-heating substation (plc-heating, FrostyGoop demo)
  * PS-2 Substation - 13.8 kV power substation (plc-power). The substation answers
                      Modbus AND IEC-104 as the same process, so when Industroyer2
                      trips the breakers over IEC-104 the operator's FUXA screen goes
                      dark in real time (operator-blinding demo).

Navigation is enabled so the operator can switch between them. Non-destructive: it
only re-seeds when a view is missing (use --force to overwrite).

Usage:
    python3 scripts/seed_fuxa_hmi.py [--url http://localhost:1881] [--wait] [--force]

Requires the custom FUXA image (docker/Dockerfile.fuxa) so the Modbus driver's
modbus-serial dependency is present; otherwise the devices show but read no data.
"""
import argparse
import json
import sys
import time
import urllib.request
import urllib.error

# palette: annunciator / anodized gunmetal
BG, PLATE, PLATE2, EDGE, GRID = "#16191c", "#1a1e22", "#1d2126", "#2b3138", "#20242a"
TEXT, MUTED, CYAN, RED, AMBER, GREEN, LAMPOFF = (
    "#e8eaed", "#8b939b", "#4aa3b5", "#c0392b", "#d98a1f", "#3a9d5d", "#242a30")
DISP = "'Saira Semi Condensed','Oswald','IBM Plex Sans Condensed','Arial Narrow',sans-serif"
MONO = "'IBM Plex Mono','DejaVu Sans Mono',monospace"

W, H = 1280, 800


def _helpers(dev):
    """Return SVG/item helper functions bound to one device."""
    svg, items, n = [], {}, [0]

    def esc(s):
        return s.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")

    def uid(p):
        n[0] += 1
        return f"{p}_{dev}_{n[0]:03d}"

    def rect(x, y, w, h, fill, stroke="null", rx=0, sw=1, op=None):
        o = f' opacity="{op}"' if op is not None else ""
        r = f' rx="{rx}"' if rx else ""
        st = f' stroke="{stroke}" stroke-width="{sw}"' if stroke != "null" else ' stroke="null"'
        svg.append(f'<rect x="{x}" y="{y}" width="{w}" height="{h}" fill="{fill}"{st}{r}{o}/>')

    def line(x1, y1, x2, y2, stroke, sw=1, op=None):
        o = f' opacity="{op}"' if op is not None else ""
        svg.append(f'<line x1="{x1}" y1="{y1}" x2="{x2}" y2="{y2}" stroke="{stroke}" stroke-width="{sw}"{o}/>')

    def text(x, y, s, size, fill=TEXT, anchor="start", family=DISP, weight="400", ls=None):
        lsp = f' letter-spacing="{ls}"' if ls else ""
        svg.append(f'<text x="{x}" y="{y}" font-family="{family}" font-size="{size}" '
                   f'fill="{fill}" text-anchor="{anchor}" font-weight="{weight}"{lsp} '
                   f'xml:space="preserve">{esc(s)}</text>')

    def value(x, y, size, tagid, unit, anchor="middle"):
        gid, tid = uid("VAL"), uid("VALT")
        svg.append(f'<g id="{gid}" text-anchor="{anchor}" font-family="{DISP}" '
                   f'stroke-width="0" font-size="{size}" fill="none" type="svg-ext-value">')
        svg.append(f'<text id="{tid}" y="{y}" x="{x}" text-anchor="{anchor}" font-family="{DISP}" '
                   f'font-size="{size}" fill="{TEXT}" font-weight="600" xml:space="preserve">##.#</text>')
        svg.append('</g>')
        items[gid] = {"id": gid, "type": "svg-ext-value", "name": tagid, "property": {
            "events": [], "actions": [], "variable": tagid, "variableId": f"{dev}^~^{tagid}", "variableSrc": dev,
            "alarmId": "", "alarmSrc": "", "alarm": "", "alarmColor": "",
            "ranges": [{"type": "unit", "min": 0, "max": 200, "text": unit}]}, "label": "Value"}

    def lamp(cx, cy, r, tagid, ranges):
        gid, eid = uid("GSE"), uid("GSEE")
        svg.append(f'<g type="svg-ext-gauge_semaphore" fill="{LAMPOFF}" font-size="14" '
                   f'stroke="#000000" font-family="{DISP}" id="{gid}">')
        svg.append(f'<rect x="{cx-r}" y="{cy-r}" width="{2*r}" height="{2*r}" rx="2" '
                   f'fill="{LAMPOFF}" stroke="#0d0f11" stroke-width="1" id="{eid}"/>')
        svg.append('</g>')
        items[gid] = {"id": gid, "type": "svg-ext-gauge_semaphore", "name": tagid, "property": {
            "events": [], "actions": [], "variable": tagid, "variableId": f"{dev}^~^{tagid}", "variableSrc": dev,
            "alarmId": "", "alarmSrc": "", "alarm": "", "alarmColor": "", "ranges": ranges},
            "label": "Semaphore"}

    def progress(x, y, w, h, tagid, vmin, vmax, color):
        gid, a, b, hh = uid("GXP"), uid("A-GXP"), uid("B-GXP"), uid("H-GXP")
        svg.append(f'<g font-family="{DISP}" font-size="14" type="svg-ext-gauge_progress" id="{gid}" stroke="null">')
        svg.append(f'<rect fill="{LAMPOFF}" height="{h}" width="{w}" y="{y}" x="{x}" id="{a}" stroke="null"/>')
        svg.append(f'<rect fill="{color}" height="{h}" width="{w}" y="{y}" x="{x}" id="{b}" stroke="null"/>')
        svg.append(f'<foreignObject font-size="14" id="{hh}" width="{w}" height="{h}" y="{y}" x="{x}"/>')
        svg.append('</g>')
        items[gid] = {"id": gid, "type": "svg-ext-gauge_progress", "name": tagid, "property": {
            "events": [], "actions": [], "alarmId": "", "alarmSrc": "", "alarm": "", "alarmColor": "",
            "ranges": [{"type": "minmax", "min": vmin, "max": str(vmax), "style": [True, True], "color": color}],
            "variable": tagid, "variableId": f"{dev}^~^{tagid}", "variableSrc": dev}, "label": "Progress"}

    def grid_bg():
        rect(0, 0, W, H, BG)
        for gx in range(0, W + 1, 40):
            line(gx, 0, gx, H, GRID, 1, op=0.5)
        for gy in range(0, H + 1, 40):
            line(0, gy, W, gy, GRID, 1, op=0.5)

    def wrap(view_id, name):
        svgcontent = (f'<svg width="{W}" height="{H}" xmlns="http://www.w3.org/2000/svg" '
                      f'xmlns:svg="http://www.w3.org/2000/svg" xmlns:html="http://www.w3.org/1999/xhtml">'
                      f'<g><title>Layer 1</title>' + "".join(svg) + '</g></svg>')
        return {"id": view_id, "name": name,
                "profile": {"width": W, "height": H, "bkcolor": BG + "ff", "margin": 0},
                "items": items, "variables": {}, "svgcontent": svgcontent}

    return dict(rect=rect, line=line, text=text, value=value, lamp=lamp,
                progress=progress, grid_bg=grid_bg, wrap=wrap)


def build_heating_view():
    h = _helpers("HS1")
    rect, line, text = h["rect"], h["line"], h["text"]
    value, lamp, progress = h["value"], h["lamp"], h["progress"]
    h["grid_bg"]()

    rect(0, 0, W, 74, PLATE2)
    line(0, 74, W, 74, CYAN, 2, op=0.7)
    text(32, 34, "DISTRICT HEATING  ·  SUBSTATION HS-1", 26, TEXT, weight="700", ls="1.5")
    text(32, 58, "OTLAB  ·  PLC-HEATING  ·  MODBUS/TCP  ·  UNIT 11", 13, MUTED, family=MONO, ls="1")
    text(1150, 34, "SYSTEM", 13, MUTED, anchor="end", family=MONO, ls="1")
    lamp(1174, 29, 9, "pressure", [{"type": "range", "min": "-9999", "max": "9999", "color": GREEN}])
    text(1150, 54, "LIVE", 12, GREEN, anchor="end", family=MONO, ls="2")

    plates = [("SUPPLY TEMPERATURE", "temperature", " °C", False),
              ("SYSTEM PRESSURE", "pressure", " bar", False),
              ("CIRCUIT LEVEL", "level", " %", True)]
    px0, pw, gap, py, ph = 32, 378, 40, 104, 236
    for i, (lbl, tag, unit, is_level) in enumerate(plates):
        x = px0 + i * (pw + gap)
        rect(x, py, pw, ph, PLATE, stroke=EDGE, sw=1, rx=4)
        rect(x, py, pw, 26, PLATE2)
        text(x + 16, py + 18, lbl, 13, MUTED, family=MONO, ls="2")
        if is_level:
            progress(x + pw - 70, py + 52, 40, 150, tag, 0, 100, GREEN)
            text(x + pw - 50, py + 220, "0-100%", 11, MUTED, anchor="middle", family=MONO)
            value(x + 120, py + 150, 64, tag, unit)
        else:
            value(x + pw / 2, py + 150, 66, tag, unit)
        text(x + 16, py + ph - 16, "MEASURED", 11, MUTED, family=MONO, ls="1")

    ay = 372
    rect(32, ay, W - 64, 150, PLATE, stroke=EDGE, sw=1, rx=4)
    rect(32, ay, W - 64, 26, PLATE2)
    text(48, ay + 18, "ANNUNCIATOR", 13, MUTED, family=MONO, ls="2")
    ann = [("SUPPLY TEMP\nLOW", "temperature", [{"type": "range", "min": "-99", "max": "40", "color": RED},
                                                {"type": "range", "min": "40", "max": "999", "color": LAMPOFF}]),
           ("LOW\nPRESSURE", "pressure", [{"type": "range", "min": "-99", "max": "4", "color": AMBER},
                                          {"type": "range", "min": "4", "max": "999", "color": LAMPOFF}]),
           ("HIGH\nPRESSURE", "pressure", [{"type": "range", "min": "8", "max": "999", "color": RED},
                                           {"type": "range", "min": "-99", "max": "8", "color": LAMPOFF}]),
           ("LOW CIRCUIT\nLEVEL", "level", [{"type": "range", "min": "-99", "max": "30", "color": AMBER},
                                            {"type": "range", "min": "30", "max": "999", "color": LAMPOFF}]),
           ("SYSTEM\nONLINE", "pressure", [{"type": "range", "min": "-9999", "max": "9999", "color": GREEN}])]
    lx0, lgap = 90, 232
    for i, (lbl, tag, ranges) in enumerate(ann):
        cx = lx0 + i * lgap
        lamp(cx, ay + 78, 18, tag, ranges)
        for j, ln in enumerate(lbl.split("\n")):
            text(cx, ay + 120 + j * 15, ln, 12, TEXT, anchor="middle", ls="1")

    text(32, H - 24, "Operator visualization · read-only · values scaled x0.1 (ENCO ENC-12X)",
         12, MUTED, family=MONO)
    text(W - 32, H - 24, "mrhOTshOT OT lab", 12, MUTED, anchor="end", family=MONO)
    return h["wrap"]("v_hs1_overview", "HS-1 Heating")


def build_substation_view():
    h = _helpers("PS2")
    rect, line, text = h["rect"], h["line"], h["text"]
    value, lamp = h["value"], h["lamp"]
    h["grid_bg"]()

    # breaker lamp ranges: closed (1) -> green, open (0) -> red
    BRK = [{"type": "range", "min": "0.5", "max": "9999", "color": GREEN},
           {"type": "range", "min": "-9999", "max": "0.5", "color": RED}]
    # energized ranges on bus voltage: > 1 kV green, else red
    ENER = [{"type": "range", "min": "1", "max": "99999", "color": GREEN},
            {"type": "range", "min": "-99999", "max": "1", "color": RED}]
    BLK = [{"type": "range", "min": "0.5", "max": "9999", "color": RED},
           {"type": "range", "min": "-9999", "max": "0.5", "color": LAMPOFF}]

    rect(0, 0, W, 74, PLATE2)
    line(0, 74, W, 74, CYAN, 2, op=0.7)
    text(32, 34, "POWER SUBSTATION  ·  PS-2  ·  13.8 kV DISTRIBUTION", 26, TEXT, weight="700", ls="1.5")
    text(32, 58, "OTLAB  ·  PLC-POWER  ·  IEC-104 :2404 (SCADA CONTROL)  ·  MODBUS MONITOR",
         13, MUTED, family=MONO, ls="1")
    text(1150, 34, "SYSTEM", 13, MUTED, anchor="end", family=MONO, ls="1")
    lamp(1174, 29, 9, "voltage", ENER)
    text(1150, 54, "LIVE", 12, GREEN, anchor="end", family=MONO, ls="2")

    # top plates: bus voltage, transformer oil temp, feeder status lamp
    px0, pw, gap, py, ph = 32, 378, 40, 104, 150
    rect(px0, py, pw, ph, PLATE, stroke=EDGE, sw=1, rx=4)
    rect(px0, py, pw, 26, PLATE2)
    text(px0 + 16, py + 18, "BUS VOLTAGE", 13, MUTED, family=MONO, ls="2")
    value(px0 + pw / 2, py + 108, 66, "voltage", " kV")
    text(px0 + 16, py + ph - 14, "13.8 kV NOMINAL", 11, MUTED, family=MONO, ls="1")

    x2 = px0 + pw + gap
    rect(x2, py, pw, ph, PLATE, stroke=EDGE, sw=1, rx=4)
    rect(x2, py, pw, 26, PLATE2)
    text(x2 + 16, py + 18, "FEEDER SUPPLY", 13, MUTED, family=MONO, ls="2")
    lamp(x2 + 58, py + 88, 30, "voltage", ENER)
    text(x2 + 118, py + 80, "13.8 kV", 30, TEXT, weight="700", ls="1")
    text(x2 + 118, py + 110, "GREEN = LIVE   ·   RED = DARK", 10, MUTED, family=MONO, ls="1")

    x3 = x2 + pw + gap
    rect(x3, py, pw, ph, PLATE, stroke=EDGE, sw=1, rx=4)
    rect(x3, py, pw, 26, PLATE2)
    text(x3 + 16, py + 18, "PROTECTION RELAY", 13, MUTED, family=MONO, ls="2")
    lamp(x3 + 58, py + 88, 30, "blackout",
         [{"type": "range", "min": "-9999", "max": "0.5", "color": GREEN},
          {"type": "range", "min": "0.5", "max": "9999", "color": RED}])
    text(x3 + 118, py + 80, "GUARDED", 26, TEXT, weight="700", ls="1")
    text(x3 + 118, py + 110, "TRIP ON BLACKOUT", 10, MUTED, family=MONO, ls="1")

    # single-line mimic
    my = 300
    rect(32, my - 24, W - 64, 224, PLATE, stroke=EDGE, sw=1, rx=4)
    rect(32, my - 24, W - 64, 26, PLATE2)
    text(48, my - 6, "SINGLE-LINE MIMIC", 13, MUTED, family=MONO, ls="2")
    busy = my + 70
    line(96, busy, 300, busy, MUTED, 3)            # grid feed
    line(300, busy, 980, busy, CYAN, 6, op=0.8)    # 13.8 kV busbar
    line(760, busy, 760, busy + 70, MUTED, 3)      # transformer drop
    line(980, busy, 1090, busy, MUTED, 3)          # feeder out
    text(70, busy - 18, "GRID", 12, MUTED, anchor="middle", family=MONO)
    text(70, busy + 4, "110kV", 11, MUTED, anchor="middle", family=MONO)
    text(430, busy - 16, "13.8 kV BUS", 13, MUTED, family=MONO, ls="1")
    text(760, busy + 96, "XFMR", 12, MUTED, anchor="middle", family=MONO)
    # transformer coils
    h["line"](760, busy + 70, 760, busy + 72, MUTED, 1)
    # breakers as lamps on the line
    for cx, tag, lbl in [(300, "b1", "B1"), (630, "b2", "B2 tie"), (940, "b3", "B3")]:
        lamp(cx, busy, 13, tag, BRK)
        text(cx, busy + 40, lbl, 12, TEXT, anchor="middle", family=MONO)
    # city blocks + a "feeders" lamp
    for i in range(4):
        bx = 1108 + i * 34
        bh = [70, 96, 60, 84][i]
        rect(bx, busy + 96 - bh, 26, bh, PLATE2, stroke=EDGE, sw=1)
    lamp(1150, busy - 20, 14, "voltage", ENER)
    text(1150, busy + 116, "CITY", 12, TEXT, anchor="middle", family=MONO)

    # annunciator
    ay = 560
    rect(32, ay, W - 64, 174, PLATE, stroke=EDGE, sw=1, rx=4)
    rect(32, ay, W - 64, 26, PLATE2)
    text(48, ay + 18, "ANNUNCIATOR", 13, MUTED, family=MONO, ls="2")
    ann = [("SUBSTATION\nBLACKOUT", "blackout", BLK),
           ("BREAKER B1\nTRIPPED", "b1", [{"type": "range", "min": "-9999", "max": "0.5", "color": RED},
                                          {"type": "range", "min": "0.5", "max": "9999", "color": LAMPOFF}]),
           ("BUS-TIE B2\nTRIPPED", "b2", [{"type": "range", "min": "-9999", "max": "0.5", "color": RED},
                                          {"type": "range", "min": "0.5", "max": "9999", "color": LAMPOFF}]),
           ("BREAKER B3\nTRIPPED", "b3", [{"type": "range", "min": "-9999", "max": "0.5", "color": RED},
                                          {"type": "range", "min": "0.5", "max": "9999", "color": LAMPOFF}]),
           ("BUS\nENERGIZED", "voltage", ENER)]
    lx0, lgap = 120, 250
    for i, (lbl, tag, ranges) in enumerate(ann):
        cx = lx0 + i * lgap
        lamp(cx, ay + 86, 20, tag, ranges)
        for j, ln in enumerate(lbl.split("\n")):
            text(cx, ay + 130 + j * 15, ln, 12, TEXT, anchor="middle", ls="1")

    text(32, H - 24, "Operator visualization · read-only · Industroyer2 trips breakers over IEC-104",
         12, MUTED, family=MONO)
    text(W - 32, H - 24, "mrhOTshOT OT lab", 12, MUTED, anchor="end", family=MONO)
    return h["wrap"]("v_ps2_substation", "PS-2 Substation")


# CRITICAL: a tag's `id` must be the full "<device>^~^<name>" signal id - the SAME
# string the widget binds to as `variableId`. FUXA's runtime routes each broadcast
# value to a gauge by matching value.id (== tag.id) to the gauge's variableId; if the
# tag id is only "level" the gauge (bound to "HS1^~^level") never updates -> "##.#".
def _sid(dev, name):
    return f"{dev}^~^{name}"


def ireg_tag(dev, name, addr, label, rawhigh=65535, scaledhigh=100):
    """Input-register tag scaled from the raw range to an engineering value. Int16:
    the FUXA reader treats registers as signed, so callers keep values under 32767
    (e.g. bus voltage 0-13.8 kV -> raw 0-9044)."""
    return {"id": _sid(dev, name), "name": label, "label": label, "type": "Int16", "memaddress": "300000",
            "address": str(addr), "divisor": 1, "daq": {"enabled": False},
            "scale": {"mode": "linear", "rawLow": 0, "rawHigh": rawhigh, "scaledLow": 0, "scaledHigh": scaledhigh}}


def dinput_tag(dev, name, addr, label):
    """Discrete-input (breaker/status) boolean tag."""
    return {"id": _sid(dev, name), "name": label, "label": label, "type": "Bool", "memaddress": "100000",
            "address": str(addr), "divisor": 1, "daq": {"enabled": False}}


def heating_tag(dev, name, addr, label):
    return {"id": _sid(dev, name), "name": label, "label": label, "type": "Int16", "memaddress": "300000",
            "address": str(addr), "divisor": 1, "daq": {"enabled": False},
            "scale": {"mode": "linear", "rawLow": 0, "rawHigh": 100, "scaledLow": 0, "scaledHigh": 10}}


def build_project():
    heating = build_heating_view()
    substation = build_substation_view()
    return {
        "version": "1.00", "name": "mrhOTshOT",
        "server": {"id": "0", "name": "FUXA Server", "type": "FuxaServer", "property": {}, "polling": 1000},
        "devices": {
            "HS1": {"id": "HS1", "name": "HS1", "type": "ModbusTCP", "enabled": True, "polling": 1000,
                    "property": {"address": "plc-heating:502", "slaveid": "11"},
                    "tags": {_sid("HS1", "level"): heating_tag("HS1", "level", 1, "Circuit Level"),
                             _sid("HS1", "pressure"): heating_tag("HS1", "pressure", 2, "System Pressure"),
                             _sid("HS1", "temperature"): heating_tag("HS1", "temperature", 3, "Supply Temperature")}},
            "PS2": {"id": "PS2", "name": "PS2", "type": "ModbusTCP", "enabled": True, "polling": 1000,
                    "property": {"address": "plc-power:502", "slaveid": "1"},
                    "tags": {_sid("PS2", "voltage"): ireg_tag("PS2", "voltage", 1, "Bus Voltage"),
                             _sid("PS2", "b1"): dinput_tag("PS2", "b1", 1, "Breaker B1"),
                             _sid("PS2", "b3"): dinput_tag("PS2", "b3", 2, "Breaker B3"),
                             _sid("PS2", "b2"): dinput_tag("PS2", "b2", 3, "Bus-tie B2"),
                             _sid("PS2", "blackout"): dinput_tag("PS2", "blackout", 5, "Blackout")}},
        },
        "hmi": {"views": [substation, heating],
                "layout": {"start": "v_ps2_substation",
                           "navigation": {"type": "over", "bkcolor": PLATE2, "fgcolor": TEXT},
                           "header": {"visible": False}, "systemInfo": False, "hidenavigation": False,
                           "hidezoom": True, "grid": 0, "showdev": False, "loginoverlaycolor": BG}},
        "charts": [],
    }


def get_json(url, timeout=6):
    with urllib.request.urlopen(url, timeout=timeout) as r:
        return json.loads(r.read())


def ensure_broadcast_all(base):
    """FUXA only pushes tag values a client has subscribed to unless broadcastAll is
    on. Turn it on so the operator view shows live values without per-tag subscribe."""
    try:
        s = get_json(base + "/api/settings")
    except Exception:
        return
    if s.get("broadcastAll") is True:
        return
    s["broadcastAll"] = True
    req = urllib.request.Request(base + "/api/settings", data=json.dumps(s).encode(),
                                 headers={"Content-Type": "application/json"}, method="POST")
    try:
        urllib.request.urlopen(req, timeout=10)
        print("[OK] set FUXA broadcastAll=true (live values reach the operator view)")
    except Exception as e:
        print("[!] could not set broadcastAll:", e, file=sys.stderr)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--url", default="http://localhost:1881")
    ap.add_argument("--wait", action="store_true", help="wait for FUXA to be reachable")
    ap.add_argument("--force", action="store_true", help="overwrite even if already seeded")
    args = ap.parse_args()

    if args.wait:
        for _ in range(30):
            try:
                get_json(args.url + "/api/settings", timeout=4)
                break
            except Exception:
                time.sleep(3)
        else:
            print("[!] FUXA not reachable at", args.url, file=sys.stderr)
            return 1

    ensure_broadcast_all(args.url)

    try:
        cur = get_json(args.url + "/api/project?views=lazy")
        views = (cur.get("hmi") or {}).get("views") or []
        have = {v.get("id") for v in views}
        if not args.force and {"v_hs1_overview", "v_ps2_substation"} <= have:
            print("[OK] HMI already seeded (heating + substation present); use --force to overwrite")
            return 0
    except Exception as e:
        print("[!] could not read current project:", e, file=sys.stderr)
        return 1

    project = build_project()
    data = json.dumps(project).encode()
    req = urllib.request.Request(args.url + "/api/project", data=data,
                                 headers={"Content-Type": "application/json"}, method="POST")
    try:
        with urllib.request.urlopen(req, timeout=20) as r:
            print(f"[OK] seeded HMI 'PS-2 Substation' + 'HS-1 Heating' -> {args.url}/home (HTTP {r.status})")
    except urllib.error.HTTPError as e:
        print("[!] POST failed", e.code, e.read()[:200].decode(errors="replace"), file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
