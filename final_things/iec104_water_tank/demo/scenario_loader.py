#!/usr/bin/env python3
"""Scenario manifests: one YAML per attack, loaded into the catalog dict shape.

The files under scenarios/ are the source of truth for the attack catalog. This
module turns them back into exactly the dict shape build_attacks() used to
return - cmd/cmd_lab keys included - so launch(), _capture_filter(),
_visible_attacks() and index()'s "strip any key starting with cmd" filter all
keep working untouched. The YAML changes where the data comes from, not what it
looks like in memory.

Portable forms a manifest may use:
    argv roots      $PY  $SIM  $SCRIPTS  $REPO
    target hosts    {heating}, {power}, ... resolved against the live PLC map

.format() is applied to argv tokens and `target` ONLY. briefing and desc are
static text and must never be formatted: router_exploit's briefing contains a
literal {'tool':'ping',...} payload example that would raise KeyError.

Standalone check:  python scenario_loader.py --selftest
"""
import os

import yaml

SCENARIO_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "scenarios")

ARGV_KEYS = ("cmd", "cmd_lab", "it_phase_args")
FORMAT_TEXT = ("target",)
INTERNAL = ("order", "watch", "it_phase")   # manifest-only; never reaches the catalog
                                           # ("watch"/"it_phase" feed plan() and
                                           #  IT_PHASE_SCRIPTS, not the attack cards)
REQUIRED = ("id", "name", "protocol", "target", "desc")

# Display defaults, so a generated manifest need not invent a family or a colour.
DEFAULTS = {"family": "", "year": "", "color": "#888888", "briefing": []}


def manifest_paths(directory=None):
    """Manifest files, sorted. Leading-underscore files are shared data, not scenarios."""
    d = directory or SCENARIO_DIR
    if not os.path.isdir(d):
        return []
    return [os.path.join(d, f) for f in sorted(os.listdir(d))
            if f.endswith((".yaml", ".yml")) and not f.startswith("_")]


def _resolve(tok, roots, plc):
    """One argv token: $ROOT prefix -> real path, {plc} -> live IP."""
    if not isinstance(tok, str):
        return tok
    if tok.startswith("$"):
        # longest root name first so $SCRIPTS is not shadowed by a shorter match
        for name in sorted(roots, key=len, reverse=True):
            marker = "$" + name
            if tok == marker:
                return roots[name]
            if tok.startswith(marker + "/"):
                return os.path.join(roots[name], tok[len(marker) + 1:])
        raise ValueError(f"unknown root in argv token: {tok!r}")
    return tok.format(**plc) if "{" in tok else tok


_DOCS = None            # id -> raw manifest dict; see invalidate()


def docs(directory=None):
    """All manifests keyed by id. Cached: manifests are read from disk once per
    process, the same way the build_attacks() literal was evaluated once at
    import. Call invalidate() after writing a new manifest."""
    global _DOCS
    if _DOCS is None or directory is not None:
        found = {}
        for path in manifest_paths(directory):
            with open(path, encoding="utf-8") as fh:
                doc = yaml.safe_load(fh) or {}
            validate(doc, path)
            found[doc["id"]] = doc
        if directory is not None:
            return found
        _DOCS = found
    return _DOCS


def invalidate():
    """Drop the manifest cache (after a scenario is added or edited)."""
    global _DOCS
    _DOCS = None


def watch_entry(attack_id):
    """The manifest's `watch:` block: a WATCH_MAP-shaped dict, the string "none"
    for an attack with no process to visualize, or None when unspecified (the
    caller falls back to its own default).

    `restore` is returned as a NAME, not a table. watch_process owns the tables
    and resolves the name, so the dependency stays one-way.
    """
    doc = docs().get(attack_id)
    return doc.get("watch") if doc else None


def it_phase_map():
    """attack_id -> the manifest's `it_phase:` script, still in $ROOT form."""
    return {aid: d["it_phase"] for aid, d in docs().items() if d.get("it_phase")}


def resolve_path(tok, roots):
    """Expand a single $ROOT-prefixed path from a manifest."""
    return _resolve(tok, roots, {})


def validate(doc, path="<manifest>"):
    missing = [k for k in REQUIRED if not doc.get(k)]
    if missing:
        raise ValueError(f"{path}: missing required field(s): {', '.join(missing)}")
    if not doc.get("cmd") and not doc.get("steps"):
        raise ValueError(f"{path}: needs either cmd or steps")
    return doc


def resolve(doc, plc, roots):
    """Manifest dict -> catalog entry, in build_attacks()'s exact shape."""
    out = dict(DEFAULTS)
    for k, v in doc.items():
        if k in INTERNAL or k.startswith("_"):
            continue
        if k in ARGV_KEYS:
            out[k] = [_resolve(t, roots, plc) for t in v]
        elif k in FORMAT_TEXT:
            out[k] = v.format(**plc)
        else:
            out[k] = v
    return out


def load(plc, roots, directory=None):
    """All manifests -> the ATTACKS list, ordered by `order` then id.

    Generated scenarios carry no `order`, so they default to 999 and sort by id
    after the shipped catalog rather than interleaving with it."""
    found = list(docs(directory).values())
    found.sort(key=lambda d: (d.get("order", 999), d.get("id", "")))
    return [resolve(d, plc, roots) for d in found]


def _selftest():
    plc = {"heating": "10.0.0.1", "water": "10.0.0.2"}
    roots = {"PY": "/usr/bin/python3", "SIM": "/sim", "SCRIPTS": "/scripts", "REPO": "/repo"}

    doc = {
        "order": 1, "id": "demo", "name": "Demo", "protocol": "Modbus TCP",
        "target": "Heating ({heating}:502)", "desc": "d",
        "briefing": ["literal {'tool':'ping'} stays untouched"],
        "cmd": ["$PY", "$SIM/x/sim.py", "--target", "{heating}", "--port", "502"],
    }
    got = resolve(doc, plc, roots)
    assert got["cmd"] == ["/usr/bin/python3", "/sim/x/sim.py",
                          "--target", "10.0.0.1", "--port", "502"], got["cmd"]
    assert got["target"] == "Heating (10.0.0.1:502)"
    assert "order" not in got                      # internal key never leaks
    assert got["color"] == "#888888"               # default applied
    assert "{'tool':'ping'}" in got["briefing"][0]  # briefing NOT formatted

    # $SCRIPTS must not be shadowed by a shorter root name
    r2 = dict(roots, S="/short")
    assert _resolve("$SCRIPTS/a.py", r2, plc) == "/scripts/a.py"

    for bad, why in [({"id": "x"}, "missing"), ({"id": "x", "name": "n", "protocol": "p",
                                                 "target": "t", "desc": "d"}, "cmd or steps")]:
        try:
            validate(bad)
        except ValueError as e:
            assert why in str(e), e
        else:
            raise AssertionError(f"should have rejected {bad!r}")

    try:
        _resolve("$NOPE/x", roots, plc)
    except ValueError as e:
        assert "unknown root" in str(e)
    else:
        raise AssertionError("unknown root should raise")

    print("[OK] scenario_loader selftest passed")


if __name__ == "__main__":
    _selftest()
