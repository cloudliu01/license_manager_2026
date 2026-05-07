import importlib.util
import os
import signal
import subprocess
import tempfile
import time
from pathlib import Path
from urllib.request import urlopen

import pytest


def _wait_for_health(port: int, timeout: float = 3.0) -> None:
    end = time.time() + timeout
    while time.time() < end:
        try:
            with urlopen(f"http://127.0.0.1:{port}/v1/health", timeout=0.5):
                return
        except Exception:
            time.sleep(0.1)
    raise AssertionError("Health endpoint not ready")


def _wait_for_file(path: Path, timeout: float = 2.0) -> None:
    end = time.time() + timeout
    while time.time() < end:
        if path.exists():
            return
        time.sleep(0.1)
    raise AssertionError(f"Log file not created: {path}")


def test_lmgrd_and_lmstat_wrappers_integration():
    if (
        importlib.util.find_spec("fastapi") is None
        or importlib.util.find_spec("uvicorn") is None
    ):
        pytest.skip("fastapi/uvicorn not available")
    root = Path(__file__).resolve().parents[1]
    lmgrd = root / "wrappers" / "lmgrd"
    lmstat = root / "wrappers" / "lmstat"

    with tempfile.TemporaryDirectory() as tmpdir:
        license_path = Path(tmpdir) / "license.dat"
        log_path = Path(tmpdir) / "license.log"
        license_path.write_text("PORT 27500\nFEATURE alpha 1\n", encoding="utf-8")

        proc = subprocess.Popen(
            [str(lmgrd), "-c", str(license_path), "-l", str(log_path)]
        )
        try:
            _wait_for_health(27500)
            result = subprocess.run(
                [str(lmstat), "-c", "27500@127.0.0.1", "-a"],
                check=True,
                capture_output=True,
                text=True,
            )
            assert "LMSTAT_SIM_FORMAT_VERSION=1" in result.stdout
            _wait_for_file(log_path)
        finally:
            proc.send_signal(signal.SIGTERM)
            try:
                proc.wait(timeout=2)
            except subprocess.TimeoutExpired:
                proc.kill()
