#!/usr/bin/env python3
"""Server-side document extraction for the Agent (Beta) assistant.

Turns an uploaded file (report, PDF, pcap, or plain text) into a compact text
digest the LLM can read. Everything runs in memory - uploads are never written
to disk or logged. pypdf is imported lazily (PDF only); scapy (already in the
image) handles pcaps.
"""
import io

MAX_CHARS = 120_000          # cap on the text handed back to the model
MAX_PKTS = 2000              # cap on packets summarized from a pcap
MAX_PKT_LINES = 40           # per-packet one-liners kept in the digest

TEXT_EXTS = {
    "txt", "md", "markdown", "json", "yaml", "yml", "log", "csv", "tsv",
    "xml", "html", "htm", "ini", "conf", "cfg", "rules", "yar", "yara",
    "py", "c", "h", "sh", "ps1", "js", "sql", "toml",
}


def _cap(text):
    if len(text) > MAX_CHARS:
        return text[:MAX_CHARS] + "\n\n[... truncated at %d chars ...]" % MAX_CHARS
    return text


def _looks_text(data):
    sample = data[:4096]
    if not sample:
        return True
    printable = sum(1 for c in sample if c == 9 or c == 10 or c == 13 or 32 <= c < 127)
    return printable / len(sample) > 0.85


def _hexdump(data, limit=2048):
    chunk = data[:limit]
    out = []
    for i in range(0, len(chunk), 16):
        b = chunk[i:i + 16]
        hexs = " ".join("%02x" % c for c in b)
        text = "".join(chr(c) if 32 <= c < 127 else "." for c in b)
        out.append("%08x  %-47s  %s" % (i, hexs, text))
    note = "" if len(data) <= limit else "\n[... %d more bytes ...]" % (len(data) - limit)
    return "\n".join(out) + note


def _pdf_text(data):
    from pypdf import PdfReader  # lazy: only needed for PDFs
    reader = PdfReader(io.BytesIO(data))
    parts = []
    for i, page in enumerate(reader.pages):
        try:
            parts.append(page.extract_text() or "")
        except Exception as e:
            parts.append("[page %d: extract failed: %s]" % (i + 1, e))
    return "PDF: %d page(s)\n\n%s" % (len(reader.pages), "\n\n".join(parts))


def _pcap_digest(data):
    from collections import Counter
    from scapy.utils import rdpcap                       # scapy already in the image
    from scapy.layers.inet import IP, TCP, UDP

    pkts = rdpcap(io.BytesIO(data), count=MAX_PKTS)
    talkers, protos, ports = Counter(), Counter(), Counter()
    lines = []
    for i, p in enumerate(pkts):
        if p.haslayer(IP):
            talkers["%s -> %s" % (p[IP].src, p[IP].dst)] += 1
        if p.haslayer(TCP):
            protos["TCP"] += 1
            ports["tcp/%d" % int(p[TCP].dport)] += 1
        elif p.haslayer(UDP):
            protos["UDP"] += 1
            ports["udp/%d" % int(p[UDP].dport)] += 1
        else:
            protos[p.lastlayer().name] += 1
        if i < MAX_PKT_LINES:
            try:
                lines.append("  %3d. %s" % (i + 1, p.summary()))
            except Exception:
                lines.append("  %3d. <unparsed>" % (i + 1))

    def _top(counter, n=10):
        return "\n".join("  %-28s %d" % (k, v) for k, v in counter.most_common(n)) or "  (none)"

    capped = " (first %d)" % MAX_PKTS if len(pkts) >= MAX_PKTS else ""
    return (
        "pcap digest\n"
        "packets: %d%s\n\n"
        "top talkers (src -> dst):\n%s\n\n"
        "transport / protocol:\n%s\n\n"
        "top destination ports:\n%s\n\n"
        "first %d packets:\n%s\n"
        % (len(pkts), capped, _top(talkers), _top(protos), _top(ports),
           min(len(pkts), MAX_PKT_LINES), "\n".join(lines) or "  (none)")
    )


def extract(filename, data):
    """filename + raw bytes -> text digest for the model. Never raises for
    format issues except where the caller wants to surface them; binary blobs
    fall back to a hexdump preview."""
    ext = (filename.rsplit(".", 1)[-1].lower() if "." in filename else "")
    if ext == "pdf":
        return _cap(_pdf_text(data))
    if ext in ("pcap", "pcapng", "cap"):
        return _cap(_pcap_digest(data))
    if ext in TEXT_EXTS or _looks_text(data):
        return _cap(data.decode("utf-8", errors="replace"))
    return _cap("binary file '%s' (%d bytes), hexdump preview:\n\n%s"
                % (filename, len(data), _hexdump(data)))


def _selftest():
    import os
    import tempfile
    # text
    assert "hello world" in extract("note.md", b"# hello world\nbody")
    # binary -> hexdump
    hd = extract("blob.bin", bytes(range(256)))
    assert "hexdump" in hd and "00000000" in hd
    # pcap via scapy round-trip
    from scapy.layers.inet import IP, TCP
    from scapy.layers.l2 import Ether
    from scapy.utils import wrpcap
    pkts = [Ether() / IP(src="10.0.0.1", dst="10.0.0.2") / TCP(dport=502),
            Ether() / IP(src="10.0.0.2", dst="10.0.0.1") / TCP(sport=502)]
    fd, path = tempfile.mkstemp(suffix=".pcap")
    os.close(fd)
    try:
        wrpcap(path, pkts)
        with open(path, "rb") as fh:
            raw = fh.read()
    finally:
        os.remove(path)
    dig = extract("cap.pcap", raw)
    assert "packets: 2" in dig, dig
    assert "10.0.0.1 -> 10.0.0.2" in dig, dig
    assert "tcp/502" in dig, dig
    print("[OK] agent_ingest selftest passed")


if __name__ == "__main__":
    _selftest()
