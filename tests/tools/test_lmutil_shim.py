from __future__ import annotations

import os
import socket
import subprocess
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
SHIM = ROOT / "tools" / "flexlm_exporter" / "lmutil"


def _free_port() -> int:
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]


def test_lmutil_shim_reports_lmstat_version():
    result = subprocess.run(
        [str(SHIM), "lmstat", "-v"],
        check=True,
        capture_output=True,
        text=True,
    )

    assert result.stdout.strip() == "lmstat v11.19.5 build 300000 x64_lsb"


def test_lmutil_shim_rejects_unsupported_subcommand():
    result = subprocess.run(
        [str(SHIM), "lmdiag"],
        capture_output=True,
        text=True,
    )

    assert result.returncode == 2
    assert "unsupported lmutil subcommand: lmdiag" in result.stderr


def test_lmutil_shim_forwards_supported_lmstat_invocation():
    port = _free_port()

    result = subprocess.run(
        [str(SHIM), "lmstat", "-c", f"{port}@127.0.0.1", "-a"],
        capture_output=True,
        env={**os.environ, "PYTHON": sys.executable},
        text=True,
    )

    assert result.returncode != 0
    assert "SERVICE_UNREACHABLE" in result.stderr
