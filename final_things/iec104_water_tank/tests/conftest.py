"""Shared pytest fixtures for the mrhOTshOT canonical test suite.

Unit tests run with no external dependencies. Integration tests that need a
live target server or a Docker daemon are auto-skipped when those are absent,
so `pytest` is always green on a bare checkout.
"""
import os
import shutil
import socket
import subprocess

import pytest

# Repo root and the docker compose stack live two levels up from this file.
REPO_ROOT = subprocess.run(
    ["git", "rev-parse", "--show-toplevel"],
    capture_output=True, text=True, cwd=__file__.rsplit("/", 1)[0],
).stdout.strip() or "/opt/mrhOTshOT"
COMPOSE_FILE = f"{REPO_ROOT}/docker/docker-compose.yml"


def _docker_ok() -> bool:
    """True if a Docker daemon is reachable."""
    if not shutil.which("docker"):
        return False
    try:
        return subprocess.run(
            ["docker", "info"], capture_output=True, timeout=10
        ).returncode == 0
    except Exception:
        return False


def port_open(host: str, port: int, timeout: float = 2.0) -> bool:
    """True if a TCP connection to host:port succeeds."""
    try:
        with socket.create_connection((host, port), timeout=timeout):
            return True
    except OSError:
        return False


@pytest.fixture(scope="session")
def docker_available() -> bool:
    """Skip the test when no Docker daemon is reachable."""
    if not _docker_ok():
        pytest.skip("Docker daemon not available")
    return True


@pytest.fixture(scope="session")
def otlab():
    """Ensure the docker/ OT lab is reachable for integration tests.

    Non-destructive: if the lab is already up (port 2404 published on loopback),
    it is left as-is. Otherwise, when AUTO_LAB=1 and Docker is available, the
    stack is started for the session and torn down afterwards. If neither holds,
    the dependent tests skip - so `pytest` stays green on a bare checkout.
    """
    if port_open("127.0.0.1", 2404):
        yield "otlab"  # already running; don't manage it
        return
    if os.environ.get("AUTO_LAB") != "1" or not _docker_ok():
        pytest.skip("OT lab not running (start it with `make lab-up`, or set AUTO_LAB=1)")
    up = subprocess.run(
        ["docker", "compose", "-f", COMPOSE_FILE, "up", "-d", "--build"],
        capture_output=True, text=True,
    )
    if up.returncode != 0:
        pytest.skip(f"docker compose up failed:\n{up.stderr}")
    try:
        yield "otlab"
    finally:
        subprocess.run(
            ["docker", "compose", "-f", COMPOSE_FILE, "down", "-v"],
            capture_output=True, text=True,
        )
