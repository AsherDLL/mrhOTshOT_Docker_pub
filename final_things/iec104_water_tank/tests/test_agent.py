"""Chatbot (Beta) assistant: the two modules' own selftests, wired into CI, plus
the SSE contract the browser depends on.

agent_llm._selftest() and agent_ingest._selftest() already existed and were
runnable standalone, but nothing in tests/ imported them, so `make test` never
executed either. They stub the SDK client / round-trip a real scapy pcap, so
they need no network and no API key.
"""
import json
import os
import sys

import pytest

_HERE = os.path.dirname(os.path.abspath(__file__))
_DEMO = os.path.abspath(os.path.join(_HERE, "..", "demo"))
sys.path.insert(0, _DEMO)

import agent_ingest  # noqa: E402
import agent_llm  # noqa: E402


def test_agent_llm_selftest():
    agent_llm._selftest()


def test_agent_ingest_selftest():
    agent_ingest._selftest()


def test_every_preset_declares_capabilities():
    """Structured output and tool calling are OpenAI extensions the other
    OpenAI-compatible providers support unevenly, so capability is declared,
    never assumed at request time."""
    for name, p in agent_llm.PRESETS.items():
        assert set(p["caps"]) == {"tools", "strict_schema"}, name
        assert isinstance(p["caps"]["tools"], bool)
    assert agent_llm.PRESETS["custom"]["caps"] == {"tools": False, "strict_schema": False}


def test_keys_are_env_only():
    """No preset may carry a literal key, and the config endpoint must only ever
    report whether one is set."""
    for p in agent_llm.PRESETS.values():
        assert p["key_env"].startswith("MRHOTSHOT_")
        assert "key" not in {k for k in p if k != "key_env"}


@pytest.mark.parametrize("url,ok", [
    ("https://api.together.xyz/v1", True),
    ("http://api.together.xyz/v1", False),      # must be https
    ("https://localhost/v1", False),
    ("https://caldera:8888/v1", False),         # our own container
    ("https://169.254.169.254/v1", False),      # cloud metadata
    ("https://10.1.2.3/v1", False),
])
def test_custom_base_url_ssrf_guard(url, ok):
    assert agent_llm._valid_base_url("custom", url)[0] is ok


def _fake_stream(monkeypatch, chunks):
    """Stub the SDK client so no network or key is needed."""
    class D:
        def __init__(self, c):
            self.content = c

    class C:
        def __init__(self, c):
            self.delta = D(c)

    class Chunk:
        def __init__(self, c):
            self.choices = [C(c)]

    class S:
        def __iter__(self):
            return iter([Chunk(c) for c in chunks])

        def close(self):
            pass

    class Completions:
        def create(self, **kw):
            return S()

    class Client:
        def __init__(self):
            self.chat = type("X", (), {"completions": Completions()})()

    monkeypatch.setattr(agent_llm, "_client", lambda *a, **k: Client())


def test_chat_sse_contract_unchanged(monkeypatch):
    """agent.js parses `data: {"delta": ...}` frames terminated by `event: done`.
    The SDK swap must not change a byte of that."""
    _fake_stream(monkeypatch, ["Hel", "lo"])
    monkeypatch.setenv("MRHOTSHOT_OPENAI_KEY", "sk-test")

    from flask import Flask
    app = Flask(__name__)
    app.register_blueprint(agent_llm.agent_bp)
    c = app.test_client()

    r = c.post("/api/agent/chat", json={"provider": "openai", "model": "gpt-4o",
                                        "messages": [{"role": "user", "content": "hi"}]})
    assert r.status_code == 200
    assert r.mimetype == "text/event-stream"
    body = r.get_data(as_text=True)
    deltas = [json.loads(ln[5:])["delta"] for ln in body.splitlines()
              if ln.startswith("data: ") and "delta" in ln]
    assert "".join(deltas) == "Hello"
    assert "event: done" in body


def test_chat_without_a_key_errors_over_sse(monkeypatch):
    """A missing key must degrade to an SSE error frame, not a 500."""
    monkeypatch.delenv("MRHOTSHOT_OPENAI_KEY", raising=False)
    from flask import Flask
    app = Flask(__name__)
    app.register_blueprint(agent_llm.agent_bp)
    r = app.test_client().post("/api/agent/chat", json={"provider": "openai"})
    assert r.status_code == 200
    body = r.get_data(as_text=True)
    assert "event: error" in body and "no API key" in body


def test_real_client_constructs():
    """Every other test stubs _client, so nothing exercised the real one - which
    is how an import of the wrong http library survived. Constructing a client
    makes no network call, so this is cheap and catches it."""
    c = agent_llm._client("https://api.example.com/v1", "sk-test")
    assert c.max_retries == 2
    assert c.timeout.connect == 10 and c.timeout.read == 120


# ── PDF ingestion ──────────────────────────────────────────────────────────
# PDF is the headline input for "submit a report", and nothing exercised it:
# agent_ingest._selftest() covers text, binary and pcap but never PDF, so a
# missing pypdf went unnoticed in the venv until a real report was tried.

def _make_pdf(pages):
    """Smallest valid PDF carrying known text.

    Built from bytes on purpose: pypdf only reads PDFs, so writing one would mean a
    new dependency, and a committed binary fixture would be unreviewable.
    """
    objs, kids = [], []
    first = 3
    font_id = first + 2 * len(pages)
    for i, text in enumerate(pages):
        pid, cid = first + i * 2, first + i * 2 + 1
        kids.append(f"{pid} 0 R")
        esc = text.replace("\\", r"\\").replace("(", r"\(").replace(")", r"\)")
        stream = f"BT /F1 12 Tf 72 720 Td ({esc}) Tj ET".encode()
        objs.append((pid, (f"<</Type/Page/Parent 2 0 R/MediaBox[0 0 612 792]"
                           f"/Contents {cid} 0 R"
                           f"/Resources<</Font<</F1 {font_id} 0 R>>>>>>").encode()))
        objs.append((cid, b"<</Length %d>>stream\n%s\nendstream" % (len(stream), stream)))
    allobjs = sorted(
        [(1, b"<</Type/Catalog/Pages 2 0 R>>"),
         (2, ("<</Type/Pages/Kids[" + " ".join(kids) + f"]/Count {len(pages)}>>").encode()),
         (font_id, b"<</Type/Font/Subtype/Type1/BaseFont/Helvetica>>")] + objs)

    out = bytearray(b"%PDF-1.4\n")
    offsets = {}
    for num, body in allobjs:
        offsets[num] = len(out)
        out += b"%d 0 obj\n" % num + body + b"\nendobj\n"
    xref_at = len(out)
    n = max(offsets) + 1
    out += b"xref\n0 %d\n0000000000 65535 f \n" % n
    for i in range(1, n):
        out += b"%010d 00000 n \n" % offsets.get(i, 0)
    out += b"trailer\n<</Size %d/Root 1 0 R>>\nstartxref\n%d\n%%%%EOF\n" % (n, xref_at)
    return bytes(out)


def test_pypdf_is_installed():
    """requirements.txt declares pypdf for exactly this path. Without it every PDF
    upload degrades to 'could not read', which is easy to miss because the blueprint
    is deliberately fail-open."""
    import pypdf
    assert pypdf


def test_pdf_text_and_page_count_extracted():
    pdf = _make_pdf(["FC05 write coil 3 = OFF on unit 11",
                     "CPU STOP over S7comm port 102"])
    text = agent_ingest.extract("report.pdf", pdf)
    assert "PDF: 2 page(s)" in text
    assert "FC05 write coil 3 = OFF on unit 11" in text      # page 1
    assert "CPU STOP over S7comm port 102" in text           # page 2 - not just the first


def test_pdf_dispatch_is_by_extension_not_sniffing():
    """A PDF must not fall through to the binary hexdump branch."""
    text = agent_ingest.extract("report.pdf", _make_pdf(["holding register 40 = 0xFFFF"]))
    assert "hexdump" not in text
    assert "holding register 40 = 0xFFFF" in text


def test_pdf_output_is_capped():
    big = _make_pdf(["x" * 900] * 200)
    text = agent_ingest.extract("big.pdf", big)
    assert len(text) <= agent_ingest.MAX_CHARS + 200
    if len(text) > agent_ingest.MAX_CHARS:
        assert "truncated at" in text


def test_corrupt_pdf_surfaces_as_an_error_not_a_crash(monkeypatch):
    """A malformed upload must come back as a message the operator can read."""
    monkeypatch.setenv("MRHOTSHOT_OPENAI_KEY", "sk-test")
    from flask import Flask
    app = Flask(__name__)
    app.register_blueprint(agent_llm.agent_bp)
    import io as _io
    r = app.test_client().post(
        "/api/agent/extract",
        data={"file": (_io.BytesIO(b"%PDF-1.4\nnot really a pdf"), "broken.pdf")},
        content_type="multipart/form-data")
    assert r.status_code == 200
    assert "could not read" in r.get_json()["error"]


def test_pdf_upload_round_trips_through_the_endpoint():
    """The path a user actually takes: attach a PDF, get report text back."""
    from flask import Flask
    app = Flask(__name__)
    app.register_blueprint(agent_llm.agent_bp)
    import io as _io
    pdf = _make_pdf(["Section 3.2 - the actor wrote holding register 3 = 12 on unit 11"])
    r = app.test_client().post(
        "/api/agent/extract",
        data={"file": (_io.BytesIO(pdf), "advisory.pdf")},
        content_type="multipart/form-data")
    assert r.status_code == 200
    j = r.get_json()
    assert j["filename"] == "advisory.pdf"
    assert "holding register 3 = 12 on unit 11" in j["text"]
    assert j["chars"] == len(j["text"])


def test_oversized_upload_rejected(monkeypatch):
    monkeypatch.setattr(agent_llm, "MAX_UPLOAD", 1024)
    from flask import Flask
    app = Flask(__name__)
    app.register_blueprint(agent_llm.agent_bp)
    import io as _io
    r = app.test_client().post(
        "/api/agent/extract",
        data={"file": (_io.BytesIO(b"A" * 4096), "big.txt")},
        content_type="multipart/form-data")
    assert r.status_code == 413
