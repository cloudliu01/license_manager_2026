"""Opt-in real AF_PACKET audit test; RUN_RAW_CAPTURE_TEST=1 requires passwordless sudo."""

from __future__ import annotations

import json
import os
import signal
import socket
import sqlite3
import subprocess
import sys
import time
from pathlib import Path

import pytest
from license_manager_simulators.lmgrd.wire import (
    CHECKIN,
    CHECKOUT,
    ENQUIRE,
    HEARTBEAT,
    STATUS,
    request,
)

pytestmark = pytest.mark.skipif(
    sys.platform != "linux" or os.environ.get("RUN_RAW_CAPTURE_TEST") != "1",
    reason="opt-in Linux AF_PACKET test (RUN_RAW_CAPTURE_TEST=1)",
)
ROOT = Path(__file__).resolve().parents[3]


def test_monitor_decodes_native_style_lmstat_traffic(tmp_path):
    """The native lmstat path must be captured and decoded as FLEXLM traffic
    while SIM1 checkout traffic on the same server stays SIM1_DECODED."""
    subprocess.run(["sudo", "-n", "true"], check=True, capture_output=True)
    port = _port()
    license_path = tmp_path / "license.dat"
    db_path = tmp_path / "audit.sqlite"
    ready = tmp_path / "monitor.ready"
    license_path.write_text(f"PORT {port}\nFEATURE alpha 3 EXP 2026-11-01\n", encoding="utf-8")
    env = {**os.environ, "PYTHON": sys.executable}
    proc = subprocess.Popen(
        [str(ROOT / "simulators/wrappers/lmgrd"), "-c", str(license_path), "-l", str(tmp_path / "debug.log")],
        env=env,
    )
    monitor = None
    try:
        def server_ready() -> bool:
            if proc.poll() is not None:
                raise AssertionError("lmgrd exited")
            try:
                request("127.0.0.1", port, STATUS, {})
                return True
            except OSError:
                return False

        _wait(server_ready)
        monitor = subprocess.Popen([
            "sudo", "-n", "env", f"PYTHONPATH={ROOT / 'simulators/src'}", sys.executable,
            "-m", "license_manager_simulators.monitor.cli", "--pid", str(proc.pid),
            "--db", str(db_path), "--ready-file", str(ready),
        ])

        def monitor_ready() -> bool:
            if monitor.poll() is not None:
                raise AssertionError("monitor exited")
            return ready.exists()

        _wait(monitor_ready)
        request("127.0.0.1", _route_to_daemon(port, "alpha")["port"], CHECKOUT, {
            "feature": "alpha", "user": "native_probe", "host": "demo", "pid": 42,
            "allow_queue": False,
        })
        result = subprocess.run(
            [sys.executable, "-m", "license_manager_simulators.lmstat.cli",
             "-c", f"{port}@127.0.0.1", "-a"],
            check=True, capture_output=True, text=True,
            env={**os.environ, "PYTHONPATH": str(ROOT / "simulators/src")},
        )
        assert "Users of alpha:" in result.stdout
        assert '"native_probe" demo /dev/pts/42' in result.stdout

        def recorded() -> bool:
            with sqlite3.connect(db_path) as conn:
                flex = conn.execute("""SELECT count(*) FROM frames
                    WHERE decode_status='FLEXLM_DECODED'
                    AND decoded_json LIKE '%alpha%'""").fetchone()[0]
                greeting = conn.execute("""SELECT count(*) FROM frames
                    WHERE decoded_json LIKE '%eda-greeting%'""").fetchone()[0]
                sim1 = conn.execute("""SELECT count(*) FROM frames
                    WHERE decode_status='SIM1_DECODED'""").fetchone()[0]
                return flex >= 1 and greeting >= 1 and sim1 >= 1

        _wait(recorded)
        with sqlite3.connect(db_path) as conn:
            statuses = dict(conn.execute(
                "SELECT decode_status, count(*) FROM frames GROUP BY 1").fetchall())
            assert statuses.get("FLEXLM_DECODED", 0) >= 1
            assert statuses.get("SIM1_DECODED", 0) >= 1
            flex_rows = conn.execute("""SELECT direction, decoded_json FROM frames
                WHERE decode_status='FLEXLM_DECODED'
                AND decoded_json LIKE '%alpha%' LIMIT 3""").fetchall()
            assert any('"strings"' in row[1] or '"fields"' in row[1] for row in flex_rows)
    finally:
        if monitor is not None:
            children = Path(f"/proc/{monitor.pid}/task/{monitor.pid}/children")
            if children.exists():
                for pid in children.read_text().split():
                    subprocess.run(["sudo", "-n", "kill", "-TERM", pid], check=False)
            else:
                monitor.send_signal(signal.SIGTERM)
            try:
                monitor.wait(timeout=5)
            except subprocess.TimeoutExpired:
                monitor.kill()
                monitor.wait(timeout=5)
        proc.send_signal(signal.SIGTERM)
        try:
            proc.wait(timeout=5)
        except subprocess.TimeoutExpired:
            proc.kill()
            proc.wait(timeout=5)


def _route_to_daemon(port: int, feature: str) -> dict:
    route = request("127.0.0.1", port, ENQUIRE, {"feature": feature})
    return next(iter(route["daemons"].values()))


def _port() -> int:
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]


def _wait(predicate, timeout: float = 8) -> None:
    until = time.monotonic() + timeout
    while time.monotonic() < until:
        if predicate():
            return
        time.sleep(0.05)
    raise AssertionError("process did not become ready")


def test_attach_capture_decode_and_reconcile(tmp_path):
    subprocess.run(["sudo", "-n", "true"], check=True, capture_output=True)
    manager, daemon = _port(), _port()
    while manager == daemon:
        daemon = _port()
    license_path = tmp_path / "license.dat"
    log_path = tmp_path / "debug.log"
    db_path = tmp_path / "audit.sqlite"
    ready = tmp_path / "monitor.ready"
    license_path.write_text(
        f"PORT {manager}\nSERVER_NAME lic_server\nDAEMON vend PORT {daemon}\n"
        "FEATURE alpha 1 DAEMON vend\n",
        encoding="utf-8",
    )
    env = {**os.environ, "PYTHON": sys.executable}
    proc = subprocess.Popen(
        [str(ROOT / "simulators/wrappers/lmgrd"), "-c", str(license_path), "-l", str(log_path)],
        env=env,
    )
    monitor = None
    try:
        def server_ready() -> bool:
            if proc.poll() is not None:
                raise AssertionError("lmgrd exited")
            try:
                request("127.0.0.1", manager, STATUS, {})
                return True
            except OSError:
                return False

        _wait(server_ready)
        monitor = subprocess.Popen([
            "sudo", "-n", "env", f"PYTHONPATH={ROOT / 'simulators/src'}", sys.executable,
            "-m", "license_manager_simulators.monitor.cli", "--pid", str(proc.pid),
            "--db", str(db_path), "--ready-file", str(ready),
        ])

        def monitor_ready() -> bool:
            if monitor.poll() is not None:
                raise AssertionError("monitor exited")
            return ready.exists()

        _wait(monitor_ready)
        route = request("127.0.0.1", manager, ENQUIRE, {"feature": "alpha"})["daemons"]["vend"]
        assert route["pid"] != proc.pid
        checkout = request("127.0.0.1", daemon, CHECKOUT, {
            "feature": "alpha", "user": "alice", "host": "demo", "pid": 17,
            "allow_queue": False,
        })
        assert checkout["status"] == "GRANTED"
        denied = request("127.0.0.1", daemon, CHECKOUT, {
            "feature": "alpha", "user": "bob", "host": "demo", "pid": 18,
            "allow_queue": False,
        })
        assert denied["status"] == "DENIED"
        request("127.0.0.1", daemon, HEARTBEAT, {})
        returned = request("127.0.0.1", daemon, CHECKIN, {"checkout_id": checkout["checkout_id"]})
        assert returned["status"] == "RETURNED"
        status = request("127.0.0.1", manager, STATUS, {})["features"][0]
        assert (status["in_use"], status["denied"]) == (0, 1)

        def recorded() -> bool:
            with sqlite3.connect(db_path) as conn:
                count = conn.execute("""SELECT count(*) FROM frames
                    WHERE direction='server_to_client' AND opcode IN (131,132)
                    AND json_extract(decoded_json,'$.status') IN ('GRANTED','DENIED','RETURNED')""").fetchone()[0]
                return count >= 3

        _wait(recorded)
        with sqlite3.connect(db_path) as conn:
            assert conn.execute("SELECT count(*) FROM listeners WHERE pid=? AND port=?", (proc.pid, manager)).fetchone()[0] == 1
            assert conn.execute("SELECT count(*) FROM listeners WHERE pid=? AND port=?", (route["pid"], daemon)).fetchone()[0] == 1
            rows = conn.execute("""SELECT decoded_json, raw_hex, raw_bytes FROM frames
                WHERE direction='server_to_client' AND opcode IN (131,132)""").fetchall()
            assert {json.loads(row[0])["status"] for row in rows} == {"GRANTED", "DENIED", "RETURNED"}
            assert all(row[1] == row[2].hex() for row in rows)
            assert conn.execute("SELECT count(*) FROM tcp_segments").fetchone()[0] > 0
            events = conn.execute("""SELECT client_user,status,correlation,request_frame_id,response_frame_id
                FROM license_events ORDER BY id""").fetchall()
            assert [(item[0], item[1]) for item in events] == [
                ("alice", "GRANTED"), ("bob", "DENIED"), (None, "RETURNED"),
            ]
            assert all(item[2] == "MATCHED_SIM1_REQUEST" and item[3] and item[4] for item in events)
        lines = log_path.read_text()
        assert lines.count('OUT:\t"alpha"') == lines.count('IN:\t"alpha"') == 1
        assert lines.count('DENIED:\t"alpha"') == 1
    finally:
        if monitor is not None:
            # sudo does not forward SIGTERM to its Python child on this host.
            children = Path(f"/proc/{monitor.pid}/task/{monitor.pid}/children")
            if children.exists():
                for pid in children.read_text().split():
                    subprocess.run(["sudo", "-n", "kill", "-TERM", pid], check=False)
            else:
                monitor.send_signal(signal.SIGTERM)
            try:
                monitor.wait(timeout=5)
            except subprocess.TimeoutExpired:
                monitor.kill()
                monitor.wait(timeout=5)
        proc.send_signal(signal.SIGTERM)
        proc.wait(timeout=5)
