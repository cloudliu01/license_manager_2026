"""Run or stop a local SIM1 manager + independent passive PID/port monitor demo.

Linux, loopback IPv4, and passwordless sudo/CAP_NET_RAW required. Never use real
license material: the output includes raw user/host fields and packet bytes.
"""

from __future__ import annotations

import argparse
import json
import os
import signal
import socket
import sqlite3
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "simulators" / "src"))

from license_manager_simulators.lmgrd.wire import (
    CHECKIN,
    CHECKOUT,
    ENQUIRE,
    HEARTBEAT,
    STATUS,
    ProtocolError,
    request,
)


def _free_port() -> int:
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]


def _wait(predicate, timeout: float = 10) -> None:
    end = time.monotonic() + timeout
    while time.monotonic() < end:
        if predicate():
            return
        time.sleep(0.05)
    raise TimeoutError("demo service/monitor not ready")


def _stop(data: dict) -> None:
    if data.get("capture_pid"):
        subprocess.run(["sudo", "-n", "kill", "-TERM", str(data["capture_pid"])], check=False)
    if data.get("manager_pid"):
        try:
            os.kill(data["manager_pid"], signal.SIGTERM)
        except ProcessLookupError:
            pass


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--out", type=Path, default=ROOT / "artifacts" / "sim1-monitor-demo")
    parser.add_argument("--stop", action="store_true")
    args = parser.parse_args()
    output = args.out.resolve()
    manifest = output / "run.json"
    if args.stop:
        _stop(json.loads(manifest.read_text()))
        print("sent SIGTERM to SIM1 monitor and lmgrd")
        return 0
    subprocess.run(["sudo", "-n", "true"], check=True)
    if manifest.exists():
        old = json.loads(manifest.read_text())
        if Path(f"/proc/{old['manager_pid']}").exists():
            raise RuntimeError("previous demo still running; use --stop first")
    output.mkdir(parents=True, exist_ok=True)
    for name in ("capture.sqlite", "capture.sqlite-wal", "capture.sqlite-shm", "monitor.ready"):
        (output / name).unlink(missing_ok=True)
    ports = []
    while len(ports) != 3:
        port = _free_port()
        if port not in ports:
            ports.append(port)
    manager, daemon_a, daemon_b = ports
    license_path = output / "license.dat"
    log_path = output / "lmgrd.log"
    db_path = output / "capture.sqlite"
    ready = output / "monitor.ready"
    license_path.write_text(
        f"PORT {manager}\nSERVER_NAME lic_server\nDAEMON vend_a PORT {daemon_a}\n"
        f"DAEMON vend_b PORT {daemon_b}\nFEATURE alpha 1 DAEMON vend_a\n"
        "FEATURE beta 2 DAEMON vend_b\n", encoding="utf-8",
    )
    env = {**os.environ, "PYTHON": sys.executable}
    with (output / "lmgrd.out").open("w") as stdout, (output / "monitor.out").open("w") as monitor_stdout:
        server = subprocess.Popen(
            [str(ROOT / "simulators/wrappers/lmgrd"), "-c", str(license_path), "-l", str(log_path)],
            env=env, stdout=stdout, stderr=subprocess.STDOUT, start_new_session=True,
        )
        monitor = None
        try:
            def server_ready() -> bool:
                if server.poll() is not None:
                    raise RuntimeError(f"lmgrd exited: {(output / 'lmgrd.out').read_text()}")
                try:
                    request("127.0.0.1", manager, STATUS, {})
                    return True
                except (OSError, ProtocolError):
                    return False

            _wait(server_ready)
            monitor = subprocess.Popen([
                "sudo", "-n", "env", f"PYTHONPATH={ROOT / 'simulators/src'}", sys.executable,
                "-m", "license_manager_simulators.monitor.cli", "--pid", str(server.pid),
                "--db", str(db_path), "--ready-file", str(ready),
            ], stdout=monitor_stdout, stderr=subprocess.STDOUT, start_new_session=True)

            def monitor_ready() -> bool:
                if monitor.poll() is not None:
                    raise RuntimeError(f"monitor exited: {(output / 'monitor.out').read_text()}")
                return ready.exists()

            _wait(monitor_ready)
            child_file = Path(f"/proc/{monitor.pid}/task/{monitor.pid}/children")
            _wait(lambda: child_file.exists() and bool(child_file.read_text().strip()))
            capture_pid = int(child_file.read_text().split()[0])
            a = request("127.0.0.1", manager, ENQUIRE, {"feature": "alpha"})["daemons"]["vend_a"]
            b = request("127.0.0.1", manager, ENQUIRE, {"feature": "beta"})["daemons"]["vend_b"]
            granted = request("127.0.0.1", a["port"], CHECKOUT, {
                "feature": "alpha", "user": "alice", "host": "demo-host", "pid": 1001,
                "request_id": "a-1", "allow_queue": False,
            })
            denied = request("127.0.0.1", a["port"], CHECKOUT, {
                "feature": "alpha", "user": "bob", "host": "demo-host", "pid": 1002,
                "request_id": "a-2", "allow_queue": False,
            })
            beta = request("127.0.0.1", b["port"], CHECKOUT, {
                "feature": "beta", "user": "carol", "host": "demo-host", "pid": 1003,
                "request_id": "b-1", "allow_queue": False,
            })
            request("127.0.0.1", a["port"], HEARTBEAT, {})
            returned = request("127.0.0.1", a["port"], CHECKIN, {
                "checkout_id": granted["checkout_id"], "request_id": "a-3",
            })
            assert [granted["status"], denied["status"], beta["status"], returned["status"]] == [
                "GRANTED", "DENIED", "GRANTED", "RETURNED",
            ]
            features = request("127.0.0.1", manager, STATUS, {})["features"]
            assert [(row["feature"], row["in_use"], row["denied"]) for row in features] == [
                ("alpha", 0, 1), ("beta", 1, 0),
            ]

            def recorded() -> bool:
                with sqlite3.connect(db_path) as conn:
                    return conn.execute("SELECT count(*) FROM license_events").fetchone()[0] == 4

            _wait(recorded)
            with sqlite3.connect(db_path) as conn:
                listeners = conn.execute("SELECT pid,daemon,port FROM listeners ORDER BY port").fetchall()
                assert (server.pid, None, manager) in listeners
                assert (a["pid"], "vend_a", a["port"]) in listeners
                assert (b["pid"], "vend_b", b["port"]) in listeners
                events = conn.execute("""SELECT feature,client_user,status,correlation
                    FROM license_events ORDER BY id""").fetchall()
                assert events == [
                    ("alpha", "alice", "GRANTED", "MATCHED_SIM1_REQUEST"),
                    ("alpha", "bob", "DENIED", "MATCHED_SIM1_REQUEST"),
                    ("beta", "carol", "GRANTED", "MATCHED_SIM1_REQUEST"),
                    ("alpha", None, "RETURNED", "MATCHED_SIM1_REQUEST"),
                ]
                assert conn.execute("SELECT count(*) FROM frames WHERE raw_hex <> lower(hex(raw_bytes))").fetchone()[0] == 0
                assert conn.execute("SELECT count(*) FROM frames WHERE decode_status <> 'SIM1_DECODED'").fetchone()[0] == 0
                assert conn.execute("SELECT count(*) FROM tcp_segments").fetchone()[0] > 0
            log = log_path.read_text()
            assert log.count("OUT:\t") == 2 and log.count("IN:\t") == 1
            assert log.count("DENIED:\t") == 1
            result = {
                "manager_pid": server.pid, "capture_pid": capture_pid,
                "sudo_pid": monitor.pid, "manager_port": manager,
                "vend_a_pid": a["pid"], "vend_a_port": a["port"],
                "vend_b_pid": b["pid"], "vend_b_port": b["port"],
                "events": events, "feature_totals": features,
            }
            manifest.write_text(json.dumps(result, indent=2, ensure_ascii=False), encoding="utf-8")
            print(f"verified 4 decoded license events and raw hex/BLOB in {db_path}")
            print(f"manager PID/port {server.pid}/{manager}; vend_a {a['pid']}/{a['port']}; "
                  f"vend_b {b['pid']}/{b['port']}; monitor PID {capture_pid}")
            print(f"services left running; stop with: {sys.executable} {__file__} --out {output} --stop")
            return 0
        except BaseException:
            if monitor is not None and monitor.poll() is None:
                child = Path(f"/proc/{monitor.pid}/task/{monitor.pid}/children")
                if child.exists():
                    for pid in child.read_text().split():
                        subprocess.run(["sudo", "-n", "kill", "-TERM", pid], check=False)
                else:
                    monitor.terminate()
            server.terminate()
            raise


if __name__ == "__main__":
    raise SystemExit(main())
