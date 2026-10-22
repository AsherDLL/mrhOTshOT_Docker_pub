#!/usr/bin/env python3
"""
Real MMS over ISO-TSAP - a minimal but wire-correct IEC 61850 / MMS (ISO 9506)
server stack, so the substation target answers real Manufacturing Message
Specification instead of a JSON stand-in. Speaks the full OSI-on-TCP stack:

    TPKT (RFC 1006) -> COTP (ISO 8073) -> Session (ISO 8327)
      -> Presentation (ISO 8823) -> ACSE (ISO 8650) -> MMS (ISO 9506)

Hand-rolled BER (no dependency), byte-layout mirrored from a real IEC 61850
client's association flight. Supports: COTP connect, association (Initiate),
GetNameList (browse), Read, Write, and Conclude - enough for a real client
(and Wireshark) to connect, browse and read/write the data model.

The data model is provided by a `provider` object:
    provider.ld               -> logical-device / MMS domain name (str)
    provider.items()          -> list of MMS item names ("MMXU1$MX$PhV$phsA$f")
    provider.read(item)       -> float | bool | None
    provider.write(item, val) -> bool
"""
import struct

# ---- BER helpers -----------------------------------------------------------
def _len(n):
    if n < 0x80:
        return bytes([n])
    b = b""
    while n:
        b = bytes([n & 0xFF]) + b
        n >>= 8
    return bytes([0x80 | len(b)]) + b


def tlv(tag, val):
    return bytes([tag]) + _len(len(val)) + val


def _int(n):
    """Minimal signed INTEGER contents."""
    if n == 0:
        return b"\x00"
    b = b""
    v = n
    while v not in (0, -1):
        b = bytes([v & 0xFF]) + b
        v >>= 8
    if n > 0 and b[0] & 0x80:
        b = b"\x00" + b
    if n < 0 and not (b[0] & 0x80):
        b = b"\xff" + b
    return b


def ber_int(n):
    return tlv(0x02, _int(n))


def parse_tlv(buf, off=0):
    """Return (tag, content_bytes, next_off)."""
    tag = buf[off]
    off += 1
    ln = buf[off]
    off += 1
    if ln & 0x80:
        nb = ln & 0x7F
        ln = int.from_bytes(buf[off:off + nb], "big")
        off += nb
    return tag, buf[off:off + ln], off + ln


def find_tag(buf, tag):
    """Shallow scan for the first TLV with `tag` at this level."""
    off = 0
    while off < len(buf):
        t, content, nxt = parse_tlv(buf, off)
        if t == tag:
            return content
        off = nxt
    return None


def all_tags(buf, tag):
    """All TLV contents with `tag` at this level (in order)."""
    out, off = [], 0
    while off < len(buf):
        t, content, nxt = parse_tlv(buf, off)
        if t == tag:
            out.append(content)
        off = nxt
    return out


# ---- OIDs / constants ------------------------------------------------------
OID_ACSE = bytes([0x52, 0x01, 0x00, 0x01])          # 2.2.1.0.1  acse
OID_MMS_AS = bytes([0x28, 0xca, 0x22, 0x02, 0x01])  # 1.0.9506.2.1  mms abstract syntax
OID_MMS_AC = bytes([0x28, 0xca, 0x22, 0x02, 0x03])  # 1.0.9506.2.3  mms app context
OID_BER = bytes([0x51, 0x01])                        # 2.1.1  basic-encoding
# capability bitstrings (echoed from a real association)
CBB = bytes([0x05, 0xf1, 0x00])
SERVICES_CALLED = bytes([0x03, 0xee, 0x1c, 0x00, 0x00, 0x04, 0x08, 0x00, 0x00, 0x79, 0xef, 0x18])

COTP_DT = b"\x02\xf0\x80"                             # COTP Data, EOT
SESS_DATA = b"\x01\x00\x01\x00"                       # session GIVE-TOKENS + DATA-TRANSFER


def tpkt(payload):
    return b"\x03\x00" + struct.pack(">H", 4 + len(payload)) + payload


# ---- COTP ------------------------------------------------------------------
def cotp_cc(cr):
    """Build a COTP Connection Confirm mirroring the client's CR params."""
    li = cr[4]
    params = cr[11:5 + li]                # params after the class byte
    srcref = cr[8:10]                     # client src-ref -> our dst-ref
    body = bytes([0xD0]) + srcref + b"\x00\x02" + b"\x00" + params
    body = bytes([len(body)]) + body      # LI
    return tpkt(body)


# ---- MMS PDUs --------------------------------------------------------------
def mms_initiate_response():
    detail = (tlv(0x80, _int(1))          # negotiatedVersionNumber
              + tlv(0x81, CBB)            # negotiatedParameterCBB
              + tlv(0x82, SERVICES_CALLED))
    body = (tlv(0x80, _int(65000))        # localDetailCalled
            + tlv(0x81, _int(5))          # maxServOutstandingCalling
            + tlv(0x82, _int(5))          # maxServOutstandingCalled
            + tlv(0x83, _int(10))         # dataStructureNestingLevel
            + tlv(0xA4, detail))
    return tlv(0xA9, body)                # initiate-ResponsePDU [9]


def mms_data(value):
    """Encode one MMS Data value (float or bool)."""
    if isinstance(value, bool):
        return tlv(0x83, b"\xff" if value else b"\x00")           # boolean [3]
    f = struct.pack(">f", float(value))
    return tlv(0x87, b"\x08" + f)                                 # floating-point [7] (8-bit exponent)


def mms_read_response(invoke_id, results):
    """results: list of (ok, value). ok False -> data-access-error."""
    acc = b""
    for ok, val in results:
        if ok:
            acc += mms_data(val)                     # AccessResult success = Data directly (untagged)
        else:
            acc += tlv(0x80, _int(10))               # AccessResult failure [0] = object-non-existent
    # ReadResponse ::= [4] SEQUENCE { listOfAccessResult [1] SEQ OF AccessResult }
    read_resp = tlv(0xA1, acc)
    body = ber_int(invoke_id) + tlv(0xA4, read_resp)
    return tlv(0xA1, body)                            # confirmed-ResponsePDU [1]


def mms_getnamelist_response(invoke_id, names, more=False):
    ident = b"".join(tlv(0x1A, n.encode()) for n in names)   # VisibleString
    body = ber_int(invoke_id) + tlv(0xA1, tlv(0xA0, ident) + tlv(0x81, b"\xff" if more else b"\x00"))
    return tlv(0xA1, body)                            # confirmed-ResponsePDU, GetNameList [1]


def mms_write_response(invoke_id, ok):
    # WriteResponse ::= [5] SEQUENCE OF CHOICE { failure [0], success [1] NULL }
    item = tlv(0x81, b"") if ok else tlv(0x80, _int(3))
    body = ber_int(invoke_id) + tlv(0xA5, item)
    return tlv(0xA1, body)


def mms_conclude_response():
    return tlv(0x8C, b"")                             # conclude-ResponsePDU [12] (primitive, empty)


# ---- association ACCEPT (mirror of the real client's connect flight) -------
def connect_accept():
    mms = mms_initiate_response()
    # ACSE AARE
    user_info = tlv(0xBE, tlv(0x28,
                    ber_int(3) + tlv(0xA0, mms)))                 # association-data EXTERNAL, ctx 3
    aare = tlv(0x61,
               tlv(0xA1, tlv(0x06, OID_MMS_AC))                   # application-context-name
               + tlv(0xA2, ber_int(0))                            # result = accepted
               + tlv(0xA3, tlv(0xA1, ber_int(0)))                 # result-source-diagnostic (acse-service-user)
               + user_info)
    # Presentation CPA
    result_list = (tlv(0x30, tlv(0x80, _int(0)) + tlv(0x81, OID_BER))
                   + tlv(0x30, tlv(0x80, _int(0)) + tlv(0x81, OID_BER)))
    pres_user = tlv(0x61, tlv(0x30, ber_int(1) + tlv(0xA0, aare)))  # ctx 1 = ACSE
    cpa = tlv(0x31,
              tlv(0xA0, tlv(0x80, _int(1)))                       # mode-selector = normal
              + tlv(0xA2,
                    tlv(0x83, b"")                                # responding-presentation-selector
                    + tlv(0xA5, result_list)                     # context-definition-result-list
                    + pres_user))
    # Session ACCEPT SPDU (0x0e)
    sess_params = (bytes([0x05, 0x06, 0x13, 0x01, 0x00, 0x16, 0x01, 0x02])  # connect-accept item
                   + bytes([0x14, 0x02, 0x00, 0x02])                        # session requirement
                   + bytes([0x33, 0x02, 0x00, 0x01])                        # calling session selector
                   + bytes([0x34, 0x02, 0x00, 0x01]))                       # called session selector
    user_pgi = bytes([0xC1]) + _sess_len(len(cpa)) + cpa
    sess = sess_params + user_pgi
    accept = bytes([0x0E]) + _sess_len(len(sess)) + sess
    return tpkt(COTP_DT + accept)


def _sess_len(n):
    """ISO 8327 length: single byte, or 0xFF + 2 bytes when > 254."""
    if n < 0xFF:
        return bytes([n])
    return bytes([0xFF]) + struct.pack(">H", n)


def data_message(mms_pdu):
    pres = tlv(0x61, tlv(0x30, ber_int(3) + tlv(0xA0, mms_pdu)))   # ctx 3 = MMS
    return tpkt(COTP_DT + SESS_DATA + pres)


# ---- incoming parsing ------------------------------------------------------
def extract_mms(after_tpkt):
    """From a message (bytes after the TPKT header) pull the MMS PDU."""
    p = after_tpkt
    if p[:3] == COTP_DT:                      # strip COTP Data header
        p = p[3:]
    while p[:2] == b"\x01\x00":               # skip session GT/DT SPDUs (LI=0 each)
        p = p[2:]
    fed = find_tag(p, 0x61)                   # presentation fully-encoded-data
    if fed is None:
        return None
    pdv = find_tag(fed, 0x30)
    if pdv is None:
        return None
    single = find_tag(pdv, 0xA0)             # single-ASN1-type -> the MMS PDU
    return single


def visible_strings(buf):
    """All VisibleString (tag 0x1A) values, in order (object names in a request)."""
    out, off = [], 0
    def walk(b):
        o = 0
        while o < len(b):
            try:
                t, c, nxt = parse_tlv(b, o)
            except Exception:
                return
            if t == 0x1A:
                out.append(c.decode("latin-1"))
            elif t & 0x20:                    # constructed -> recurse
                walk(c)
            o = nxt
    walk(buf)
    return out


# ---- service dispatch + connection loop ------------------------------------
_FIN = object()


def _dispatch(mms, provider, log):
    tag = mms[0]
    if tag == 0xAB:                                  # conclude-RequestPDU [11]
        return _FIN
    if tag != 0xA0:                                  # only confirmed-Request
        return None
    _, content, _ = parse_tlv(mms, 0)
    t, inv, off = parse_tlv(content, 0)              # invokeID
    invoke = int.from_bytes(inv, "big") if t == 0x02 else 0
    stag, sval, _ = parse_tlv(content, off)          # confirmed service
    if stag == 0xA4:                                 # Read
        strs = visible_strings(sval)
        items = strs[1::2] if strs and len(strs) % 2 == 0 else strs
        results = []
        for it in items:
            v = provider.read(it)
            results.append((v is not None, v))
        log("Read %s" % items)
        return mms_read_response(invoke, results)
    if stag == 0xA1:                                 # GetNameList
        scope = find_tag(sval, 0xA1)                 # objectScope [1]
        dom = find_tag(scope, 0x81) if scope is not None else None   # domainSpecific
        if dom is not None:
            names = provider.items()                 # variables in the domain
        else:
            names = [provider.ld]                    # VMD scope -> the domain itself
        log("GetNameList -> %d name(s)" % len(names))
        return mms_getnamelist_response(invoke, names)
    if stag == 0xA5:                                 # Write
        strs = visible_strings(sval)
        item = (strs[1::2] or strs)[0] if strs else None
        val = _decode_write_value(sval)
        ok = provider.write(item, val) if item is not None else False
        log("Write %s = %r -> %s" % (item, val, ok))
        return mms_write_response(invoke, ok)
    return None


def _decode_write_value(sval):
    # listOfData [0] is the LAST 0xA0 sibling (the first 0xA0 is listOfVariable)
    datas = all_tags(sval, 0xA0)
    scope = datas[-1] if datas else sval
    b = find_tag(scope, 0x83)                         # boolean
    if b is not None:
        return any(b)
    f = find_tag(scope, 0x87)                         # floating-point
    if f is not None and len(f) == 5:
        return struct.unpack(">f", f[1:])[0]
    return None


def serve_mms(conn, provider, log=lambda m: None):
    """Run one MMS/ISO-TSAP session on an accepted socket."""
    conn.settimeout(30)
    buf = b""

    def read_tpkt():
        nonlocal buf
        while len(buf) < 4:
            d = conn.recv(4096)
            if not d:
                return None
            buf += d
        ln = struct.unpack(">H", buf[2:4])[0]
        while len(buf) < ln:
            d = conn.recv(4096)
            if not d:
                return None
            buf += d
        pkt, buf = buf[:ln], buf[ln:]
        return pkt

    cr = read_tpkt()
    if not cr or len(cr) < 6 or cr[5] != 0xE0:       # COTP Connection Request
        return
    conn.sendall(cotp_cc(cr))
    if read_tpkt() is None:                          # association request
        return
    conn.sendall(connect_accept())
    log("association up")
    while True:
        pkt = read_tpkt()
        if pkt is None:
            return
        mms = extract_mms(pkt[4:])
        if not mms:
            continue
        resp = _dispatch(mms, provider, log)
        if resp is _FIN:
            conn.sendall(data_message(mms_conclude_response()))
            return
        if resp:
            conn.sendall(data_message(resp))


def _selftest():
    # BER round-trip
    assert parse_tlv(tlv(0x30, b"\x01\x02"))[:2] == (0x30, b"\x01\x02")
    assert _int(65000) == b"\x00\xfd\xe8" and _int(5) == b"\x05" and _int(0) == b"\x00"
    # connect ACCEPT is a well-formed TPKT carrying a session ACCEPT (0x0e)
    ca = connect_accept()
    assert ca[:2] == b"\x03\x00" and struct.unpack(">H", ca[2:4])[0] == len(ca)
    assert ca[4:7] == COTP_DT and ca[7] == 0x0E
    # a Read-Response round-trips: encode -> wrap -> extract -> decode value
    pdu = mms_read_response(1, [(True, 13.8), (True, True), (False, None)])
    msg = data_message(pdu)
    got = extract_mms(msg[4:])
    assert got == pdu, "extract_mms did not recover the MMS PDU"
    _, body, _ = parse_tlv(got, 0)                      # confirmed-ResponsePDU
    rr = find_tag(body, 0xA4)                            # ReadResponse
    acc = find_tag(rr, 0xA1)                             # listOfAccessResult
    assert acc is not None and acc[0] == 0x87           # first result = floating-point
    # request parsing: pull item names + a write value
    req = tlv(0xA0, ber_int(7) + tlv(0xA4, tlv(0xA1, tlv(0x30, tlv(0xA0,
              tlv(0x1A, b"WaterTankLD") + tlv(0x1A, b"MMXU1$MX$PhV$phsA$f"))))))
    assert "MMXU1$MX$PhV$phsA$f" in visible_strings(req)
    wr = tlv(0xA0, tlv(0x1A, b"WaterTankLD") + tlv(0x1A, b"GGIO1$ST$Ind3$stVal")) \
        + tlv(0xA0, tlv(0x83, b"\xff"))                 # listOfVariable[0], listOfData[0]
    assert _decode_write_value(wr) is True
    print("[OK] mms_iso selftest passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(_selftest())
