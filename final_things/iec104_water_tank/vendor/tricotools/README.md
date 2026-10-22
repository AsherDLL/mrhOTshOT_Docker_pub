# Vendored: Nozomi Networks `tricotools` (Triconex honeypot)

The TriStation SIS emulator in this lab (`../../triconex_sis_server.py`) speaks
the wire protocol using the **real Nozomi Networks Triconex honeypot** as its
baseline, rather than a hand-rolled approximation.

## Provenance

- **Upstream:** https://github.com/NozomiNetworks/tricotools
- **Commit:** `2f768c8209d96dbb58dfea40c5a5ba9eb51ad6b0`
- **License:** BSD 3-Clause (see `LICENSE`, copied verbatim)
- **Authors:** Alessandro Di Pinto, Andrea Arteaga, Younes Dragoni (Nozomi Networks, 2018)

The honeypot was published alongside Nozomi's TRITON/TRISIS malware analysis and
their Wireshark TriStation dissector; it is the reference open-source emulator
defenders use to fingerprint TriStation reconnaissance.

## What we changed

`triconex_honeypot.py` here is a **faithful Python-3 port** of the upstream
Python-2 file. The emitted bytes are unchanged; only Python-2 -> Python-3
mechanics were adapted (print calls, byte-iteration returns ints so `ord()` is
dropped, `struct` `c`/`I` fields fed bytes / `int(time.time())`, and the CRC
function is defined at module scope so the builders work when imported as a
library). The non-essential `debug()` hexdump helper was omitted. The header of
the file documents each change.

## How the SIS server uses it

`triconex_sis_server.py` imports this module and delegates its **reconnaissance**
responses to it, so they are byte-for-byte the honeypot's output:

| TriStation request      | fc     | handled by                            |
|-------------------------|--------|---------------------------------------|
| CONNECT REQUEST         | `0x01` | literal CONNECT REPLY (as upstream)   |
| ATTACH TRICON           | `0x0D` | `build_tricon_attached()`             |
| GET CP STATUS           | `0x13` | `build_CP_status_response()`          |
| GET CHASSIS STATUS      | `0x18` | `build_chassis_status_response()`     |

The upstream honeypot is **reconnaissance-only**. The TRITON kill-chain opcodes
that actually disable the safety program (HALT `0x15`, GO DOWNLOAD `0x50`,
ALLOCATE `0x37`, SET TS2 DATA `0x3E`, RUN `0x14`, ...) are a lab extension living
in `triconex_sis_server.py`; they reuse this module's `build_packet()` so the
frames stay protocol-consistent with the honeypot's framing.
