'''
Triconex Honeypot emulating arbitrary modules (PoC)

date    : April, 4th 2018
author  : Alessandro Di Pinto (@adipinto)
author  : Andrea Arteaga
author  : Younes Dragoni (@ydragoni)

contact : secresearch [ @ ] nozominetworks [ . ] com

-----------------------------------------------------------------------------
VENDORED into the mrhOTshOT lab from Nozomi Networks' tricotools:
    https://github.com/NozomiNetworks/tricotools
    commit 2f768c8209d96dbb58dfea40c5a5ba9eb51ad6b0  (BSD 3-Clause, see LICENSE)

This is a faithful Python-3 port of the original Python-2 proof-of-concept.
The TriStation wire format is byte-for-byte identical to upstream: packet
framing (build_packet), the CP-status and chassis-status byte structures, the
CRC-16 (poly 0x18005, reflected) and the additive checksum. Only Python-2 ->
Python-3 mechanics changed:
  - print statements       -> print() calls
  - iterating bytes yields ints in py3, so ord() is dropped in the checksum
  - struct 'c' fields are fed length-1 bytes; 'I' fields int(time.time())
  - the CRC function 'cf' is defined at module scope so the packet builders are
    usable when imported as a library (the SIS server delegates its
    reconnaissance responses here instead of re-implementing them)
  - the non-essential debug()/hexdump developer helper was omitted
Nothing about the emitted bytes was altered.

The upstream honeypot answers reconnaissance only: CONNECT / ATTACH / GET CP
STATUS / GET CHASSIS STATUS. The TRITON kill chain (HALT PROGRAM, GO DOWNLOAD,
ALLOCATE, SET TS2 DATA, RUN PROGRAM) is NOT implemented here -- that lives in
triconex_sis_server.py as a lab extension, reusing this module's build_packet()
so those frames stay protocol-consistent.
-----------------------------------------------------------------------------
'''

import sys
import time
import socket
import struct
import argparse

try:
    import crcmod
except ImportError:
    print("[-] Please install the module 'crcmod' (eg, pip install crcmod)")
    sys.exit(1)

# CRC-16 used by the TriStation protocol (poly 0x18005, reflected). Defined at
# module scope -- upstream created it inside __main__, but as a library we need
# build_packet() to find it at import time.
cf = crcmod.mkCrcFun(0x18005, rev=True, initCrc=0x0000, xorOut=0)


def build_slot(leds0, leds1, model, color):
    slotfmt = '<' + 32 * 'B'
    return struct.pack(slotfmt, leds0, leds1, model, color,
                0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0)

# Construct slots
mps = {
        'active' : build_slot(0x15, 0x21, 0xf0, 0x01),
        'passive': build_slot(0x02, 0x01, 0xf0, 0x02)
        }
slotsdesc = {
        'empty': build_slot(0,  0,  0, 0),
        'com'  : build_slot(5, 33, 55, 1),
        'do'   : build_slot(5, 16, 20, 1),
        'di'   : build_slot(5, 32, 11, 1),
        'him'  : build_slot(5, 22, 53, 1),
        'ddo'  : build_slot(0x4F, 0x21, 0x5C, 0x2)
        }


def build_packet(triconId, funccode, seq, data):
    if isinstance(data, str):
        data = data.encode('latin-1')

    # Subheader without checksum
    datalength = len(data) + 10
    subheader = struct.pack('<BBBBHHH', 1, 0, funccode, seq, 0, 0, datalength)

    # Compute checksum (additive over subheader + data, seeded with datalength).
    # py3: iterating bytes yields ints, so no ord(); mask keeps the 'H' pack in
    # range (upstream never overflowed for these payloads, so bytes are unchanged).
    checksum = datalength
    for c in subheader:
        checksum += c
    for c in data:
        checksum += c
    checksum &= 0xFFFF

    # Header and subheader with checksum
    header = struct.pack('<BBH', 5, triconId, datalength)
    subheader = struct.pack('<BBBBHHH', 1, 0, funccode, seq, 0, checksum, datalength)

    # Entire packet, except CRC
    packet = header + subheader + data

    # Compute CRC
    crc = cf(packet)
    packet += struct.pack('<H', crc)

    return packet


def build_chassis_status_response(triconId=0, seq=0, node=2, projname=b'FIRSTPROJ',
                                  activemp=0, mpmodel=1, slots=('com',)):
    # projname is packed one byte at a time via 'c' fields; keep exactly 9 bytes.
    pn = projname[:9].ljust(9, b'\0')

    # Project segment
    data = struct.pack('<HBBHHHIIIHIIccccccccccI', 2, 0xFF, 0x00, 1, 4, 3,
            int(time.time() - 24 * 3600),
            200, 200, 181, 0, 1,
            pn[0:1], pn[1:2], pn[2:3], pn[3:4], pn[4:5],
            pn[5:6], pn[6:7], pn[7:8], pn[8:9], b'\0',
            int(time.time()))

    # Memory segment
    data += struct.pack('<BBBBIIII', 0x56, 0x02, 0x00, 0x00, 8340703, 8251952, 0x1b, 0x32)

    # MPS segment
    for i in range(3):
        data += mps['active' if i == activemp else 'passive']

    # Unknown segment
    data += struct.pack('<HH', 0xa6, 1024)

    # Slots segment
    for i in range(3):
        data += mps['active' if i == activemp else 'passive']
    for s in slots:
        data += slotsdesc[s] if s in slotsdesc else build_slot(*s)
    for i in range(13 - len(slots)):
        data += slotsdesc['empty']

    return build_packet(triconId, 119, seq, data)


def build_CP_status_response(triconId=0, seq=0):
    data = struct.pack('<HBBBBBBB', 1,
            0x0,  # loadIn
            0x0,  # modIn
            0xd,  # loadState
            0x0,  # singleScan
            0x1,  # cpValid
            0x1,  # keyState
            0x1   # runState
            )

    data += struct.pack('<BBBBB', 0x0, 0x0, 0x50, 0x80, 0x0)

    data += struct.pack('<IIIII',
            0x00800000,  # my: 8388608
            0x00400000,  # us: 4194304
            0x00600000,  # ds: 6291456
            0x00fe5000,  # heap_min: 16666624
            0x00ffafff   # heap_max: 16756735
            )

    data += struct.pack('<BBBBBBBBBBBB', 0x0, 0x20, 0x0, 0x20,
            0x0, 0x20, 0x0, 0x0,
            0x0, 0x00, 0x0, 0x0
            )
    data += struct.pack('<BBBBBBBBBBBB', 0x14, 0x1b, 0x00, 0x00,
            0xc8, 0x00, 0xc8, 0x00,
            0xba, 0x00, 0x5c, 0x98
            )

    data += struct.pack('<HH', 4, 3)  # Minor, major
    data += struct.pack('<I', int(time.time()))  # Timestamp
    data += struct.pack('<cccccccccc', b'E', b'C', b'C', b'E', b'C', b'C', b'A', b'H', b'H', b'\0')

    data += struct.pack('<BBBBBBBB', 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00)
    data += struct.pack('<BBBBBBBB', 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00)
    data += struct.pack('<BBBBBBBB', 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00)
    data += struct.pack('<BBBBBBBB', 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00)
    data += struct.pack('<BBBBBBBB', 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00)
    data += struct.pack('<BBBBBBBB', 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00)
    data += struct.pack('<BBBBBBBB', 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00)
    data += struct.pack('<BBBBBBBB', 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00)
    data += struct.pack('<BBBBBBBB', 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00)
    data += struct.pack('<BBBBBBBB', 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00)
    data += struct.pack('<BBBBBBBB', 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00)
    data += struct.pack('<BBBBBBBB', 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00)
    data += struct.pack('<BBBBBBBB', 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00)
    data += struct.pack('<BBBBBB'  , 0x00, 0x00, 0x00, 0x00, 0x00, 0x00            )

    return build_packet(triconId, 108, seq, data)


def f_crc16(data):
    return cf(data)


def checksum(data, init=0):
    summ = init
    for i in data:
        summ += i if isinstance(i, int) else ord(i)
    return summ & 0xFFFF


def udp_send(data, addr, port):
    sock.sendto(data, (addr, port))


def build_tricon_attached(triconId=0, seq=0, string=b'\x03\x00\x33\x0a\x04\x00'):
    return build_packet(triconId, 0x6a, seq, string)


if __name__ == "__main__":
    suppmods = list(slotsdesc.keys())
    parser = argparse.ArgumentParser(
        description="Triconex Honeypot emulating arbitrary modules (PoC)\nSupported modules: %s\n\nAuthors:\n\tAlessandro Di Pinto (@adipinto)\n\tAndrea Arteaga\n\tYounes Dragoni (@br4zzor)" % ', '.join(suppmods),
        formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument("-l", metavar="HONEY_IP", dest="honeyip", help="Honeypot IP address", default="0.0.0.0")
    parser.add_argument("-p", metavar="HONEY_PORT", dest="honeyport", help="Honeypot port", default=1502, type=int)
    parser.add_argument("-s1", metavar="SLOT1", dest="slot1", help="Module to emulate on slot 1", default="empty", choices=suppmods)
    parser.add_argument("-s2", metavar="SLOT2", dest="slot2", help="Module to emulate on slot 2", default="empty", choices=suppmods)
    parser.add_argument("-s3", metavar="SLOT3", dest="slot3", help="Module to emulate on slot 3", default="empty", choices=suppmods)
    parser.add_argument("-s4", metavar="SLOT4", dest="slot4", help="Module to emulate on slot 4", default="empty", choices=suppmods)
    args = parser.parse_args()

    UDP_REMOTE = None
    UDP_IP = args.honeyip
    UDP_PORT = args.honeyport

    print("[*] Binding the honeypot to the address %s:%d" % (UDP_IP, UDP_PORT))
    try:
        sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        sock.bind((UDP_IP, UDP_PORT))
    except socket.error:
        print("[-] Error binding to the specified address")
        sys.exit(2)

    # Print info about modules
    print("[*] Slot 1 module set to: %s" % args.slot1)
    print("[*] Slot 2 module set to: %s" % args.slot2)
    print("[*] Slot 3 module set to: %s" % args.slot3)
    print("[*] Slot 4 module set to: %s" % args.slot4)

    try:
        while True:
            data, addr = sock.recvfrom(1024)
            dport = addr[1]
            UDP_REMOTE = addr[0]

            mcode, chan, dlen, crc16 = struct.unpack("<BBHH", data[0:6])

            # CONNECT REQUEST
            if mcode == 0x1:
                print("[*] CONNECT REQUEST")
                # CONNECT REPLY
                udp_send(b"\x02\x00\x00\x00\x01\xb8", UDP_REMOTE, dport)

            # COMMAND REPLY
            elif mcode == 0x5:
                # Get the function code
                fcode, pseq = struct.unpack("<BB", data[6:8])
                if fcode == 0xD:
                    print("[*] ATTACH REQUEST")
                    udp_send(build_tricon_attached(), UDP_REMOTE, dport)
                elif fcode == 0x13:
                    print("[*] GET CP STATUS")
                    udp_send(build_CP_status_response(seq=pseq), UDP_REMOTE, dport)
                elif fcode == 0x18:
                    print("[*] GET CHASSIS STATUS")
                    udp_send(
                        build_chassis_status_response(
                            seq=pseq,
                            mpmodel=0,
                            activemp=2,
                            slots=['com', args.slot1, 'empty', args.slot2, 'empty', args.slot3, 'empty', args.slot4]
                        ),
                        UDP_REMOTE,
                        dport
                    )
                else:
                    print("[-] UNKNOWN: %s" % hex(fcode))
    except KeyboardInterrupt:
        print("[*] Execution interrupted by the user")
    sys.exit(0)
