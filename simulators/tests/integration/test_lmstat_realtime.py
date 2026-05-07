from __future__ import annotations

import json
import signal
import socket
import subprocess
import time
from pathlib import Path
from urllib.request import Request, urlopen


def test_lmstat_retrieves_realtime_usage_and_lmgrd_appends_activity_log(tmp_path):
    port = _free_port()
    root = Path(__file__).resolve().parents[2]
    lmgrd = root / "wrappers" / "lmgrd"
    lmstat = root / "wrappers" / "lmstat"
    license_path = tmp_path / "license.dat"
    log_path = tmp_path / "license.log"
    license_path.write_text(f"PORT {port}\nFEATURE alpha 1\n", encoding="utf-8")

    proc = subprocess.Popen([str(lmgrd), "-c", str(license_path), "-l", str(log_path)])
    try:
        _wait_for_health(port)
        checkout = _post_json(
            port,
            "/v1/checkout",
            {"request_id": "r1", "feature": "alpha", "user": "user1", "host": "host1", "pid": 101},
        )
        result = subprocess.run(
            [str(lmstat), "-c", f"{port}@127.0.0.1", "-a", "-i"],
            check=True,
            capture_output=True,
            text=True,
        )
        assert "feature: alpha total=1 in_use=1 queued=0 expired=false" in result.stdout
        assert f"checkout_id={checkout['checkout_id']}" in result.stdout

        _post_json(port, "/v1/return", {"request_id": "r2", "checkout_id": checkout["checkout_id"]})
        result = subprocess.run(
            [str(lmstat), "-c", f"{port}@127.0.0.1", "-a"],
            check=True,
            capture_output=True,
            text=True,
        )
        assert "feature: alpha total=1 in_use=0 queued=0 expired=false" in result.stdout

        content = log_path.read_text(encoding="utf-8")
        assert 'OUT: "alpha" user1@host1' in content
        assert 'IN: "alpha" user1@host1' in content
    finally:
        proc.send_signal(signal.SIGTERM)
        try:
            proc.wait(timeout=3)
        except subprocess.TimeoutExpired:
            proc.kill()


def test_lmstat_exits_nonzero_when_service_unreachable():
    port = _free_port()
    root = Path(__file__).resolve().parents[2]
    lmstat = root / "wrappers" / "lmstat"

    result = subprocess.run(
        [str(lmstat), "-c", f"{port}@127.0.0.1", "-a"],
        capture_output=True,
        text=True,
    )

    assert result.returncode != 0
    assert "SERVICE_UNREACHABLE" in result.stderr


def _free_port() -> int:
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


def _wait_for_health(port: int, timeout: float = 5.0) -> None:
    end = time.time() + timeout
    while time.time() < end:
        try:
            with urlopen(f"http://127.0.0.1:{port}/v1/health", timeout=0.5):
                return
        except Exception:
            time.sleep(0.1)
    raise AssertionError("Health endpoint not ready")


def _post_json(port: int, path: str, payload: dict) -> dict:
    request = Request(
        f"http://127.0.0.1:{port}{path}",
        data=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    with urlopen(request, timeout=2) as response:
        return json.loads(response.read().decode("utf-8"))
