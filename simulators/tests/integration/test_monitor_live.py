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
from license_manager_simulators.lmstat.client import NativeSession

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
        daemon_port = _route_to_daemon(port, "alpha")["port"]
        request("127.0.0.1", daemon_port, CHECKOUT, {
            "feature": "alpha", "user": "native_probe", "host": "demo", "pid": 42,
            "allow_queue": False,
        })

        def lmstat():
            return subprocess.run(
                [sys.executable, "-m", "license_manager_simulators.lmstat.cli",
                 "-c", f"{port}@127.0.0.1", "-a"],
                check=True, capture_output=True, text=True,
                env={**os.environ, "PYTHONPATH": str(ROOT / "simulators/src")},
            )

        result = lmstat()
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

        # shape-only native checkout exchange: the client's 0x3d epoch must
        # tie its attempt to the seat row via the start-epoch join
        with NativeSession("127.0.0.1", daemon_port) as session:
            session.checkout("alpha")
        probe_pid = str(os.getpid())
        lmstat()  # second dump: the new seat joins to its recorded attempt

        def joined() -> bool:
            with sqlite3.connect(db_path) as conn:
                attempt = conn.execute("""SELECT checkout_ts, request_frame_id FROM license_events
                    WHERE status='FLEXLM_CHECKOUT_ATTEMPT' AND client_pid = ?
                    AND checkout_ts IS NOT NULL AND request_frame_id IS NOT NULL""",
                    (probe_pid,)).fetchone()
                if attempt is None:
                    return False
                seat = conn.execute("""SELECT checkout_ts FROM license_events
                    WHERE status='FLEXLM_IN_USE' AND client_pid = ?
                    AND correlation='MATCHED_CHECKOUT_TS' AND checkout_ts = ?""",
                    (probe_pid, attempt[0])).fetchone()
                backfill = conn.execute("""SELECT feature FROM license_events
                    WHERE status='FLEXLM_CHECKOUT_ATTEMPT' AND client_pid = ?
                    AND correlation='FEATURE_FROM_SEAT_TS' AND feature = 'alpha'""",
                    (probe_pid,)).fetchone()
                return seat is not None and backfill is not None

        _wait(joined)
        with sqlite3.connect(db_path) as conn:
            statuses = dict(conn.execute(
                "SELECT decode_status, count(*) FROM frames GROUP BY 1").fetchall())
            assert statuses.get("FLEXLM_DECODED", 0) >= 1
            assert statuses.get("SIM1_DECODED", 0) >= 1
            flex_rows = conn.execute("""SELECT direction, decoded_json FROM frames
                WHERE decode_status='FLEXLM_DECODED'
                AND decoded_json LIKE '%alpha%' LIMIT 3""").fetchall()
            assert any('"strings"' in row[1] or '"fields"' in row[1] for row in flex_rows)
            # The native lmstat query path must feed FlexLM license events with
            # the stream-context feature attribution; poller seat summaries
            # land in their own table.
            events = conn.execute("""SELECT status, feature, client_user FROM license_events
                WHERE status = 'FLEXLM_IN_USE'""").fetchall()
            assert any(
                status == "FLEXLM_IN_USE" and feature == "alpha"
                and client_user == "native_probe"
                for status, feature, client_user in events
            )
            summaries = conn.execute(
                "SELECT feature FROM poller_summaries WHERE feature = 'alpha'"
            ).fetchall()
            assert summaries
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


def test_monitor_self_query_records_poller_tables(tmp_path):
    """--self-query spawns its own lmstat poller and fills poller_summaries /
    poller_details from the captured loopback query traffic."""
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
        # hermetic lmutil stand-in: forward to the simulator's lmstat CLI
        wrapper = tmp_path / "lmutil-wrapper"
        wrapper.write_text(
            f"#!{sys.executable}\n"
            "import os, sys\n"
            "target = next(a for a in sys.argv[1:] if '@' in a)\n"
            "os.execv(sys.executable, [sys.executable, '-m', "
            "'license_manager_simulators.lmstat.cli', '-c', target, '-a'])\n",
            encoding="utf-8",
        )
        wrapper.chmod(0o755)
        daemon_port = _route_to_daemon(port, "alpha")["port"]
        request("127.0.0.1", daemon_port, CHECKOUT, {
            "feature": "alpha", "user": "selfq_probe", "host": "demo", "pid": 7,
            "allow_queue": False,
        })
        monitor = subprocess.Popen([
            "sudo", "-n", "env", f"PYTHONPATH={ROOT / 'simulators/src'}",
            f"LM_MONITOR_LMUTIL={wrapper}", sys.executable,
            "-m", "license_manager_simulators.monitor.cli", "--pid", str(proc.pid),
            "--db", str(db_path), "--ready-file", str(ready), "--self-query",
        ])

        def monitor_ready() -> bool:
            if monitor.poll() is not None:
                raise AssertionError("monitor exited")
            return ready.exists()

        _wait(monitor_ready)

        def recorded() -> bool:
            with sqlite3.connect(db_path) as conn:
                summary = conn.execute(
                    "SELECT COUNT(*) FROM poller_summaries WHERE feature='alpha'"
                ).fetchone()[0]
                detail = conn.execute(
                    "SELECT COUNT(*) FROM poller_details WHERE feature='alpha'"
                    " AND client_user='selfq_probe'").fetchone()[0]
                return summary >= 1 and detail >= 1

        _wait(recorded, timeout=15)
        with sqlite3.connect(db_path) as conn:
            detail = conn.execute("""SELECT checkout_id, checkout_ts, client_pid
                FROM poller_details WHERE feature='alpha' AND client_user='selfq_probe'
                ORDER BY id DESC LIMIT 1""").fetchone()
            assert detail is not None and detail[0] is not None
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


def test_monitor_multiple_services(tmp_path):
    """One monitor instance tracks two independent sim lmgrd trees: merged
    discovery, per-service attribution (server_port/manager_pid), per-service
    seat join and per-service self-query polling."""
    subprocess.run(["sudo", "-n", "true"], check=True, capture_output=True)
    port_a, port_b = _port(), _port()
    while port_b == port_a:
        port_b = _port()
    lic_a = tmp_path / "license_a.dat"
    lic_b = tmp_path / "license_b.dat"
    lic_a.write_text(f"PORT {port_a}\nFEATURE alpha 3 EXP 2026-11-01\n", encoding="utf-8")
    lic_b.write_text(f"PORT {port_b}\nFEATURE beta 5 EXP 2026-11-01\n", encoding="utf-8")
    db_path = tmp_path / "audit.sqlite"
    ready = tmp_path / "monitor.ready"
    env = {**os.environ, "PYTHON": sys.executable}
    proc_a = subprocess.Popen(
        [str(ROOT / "simulators/wrappers/lmgrd"), "-c", str(lic_a), "-l", str(tmp_path / "a.log")],
        env=env,
    )
    proc_b = subprocess.Popen(
        [str(ROOT / "simulators/wrappers/lmgrd"), "-c", str(lic_b), "-l", str(tmp_path / "b.log")],
        env=env,
    )
    monitor = None
    try:
        def server_ready(port: int) -> bool:
            if proc_a.poll() is not None or proc_b.poll() is not None:
                raise AssertionError("lmgrd exited")
            try:
                request("127.0.0.1", port, STATUS, {})
                return True
            except OSError:
                return False

        _wait(lambda: server_ready(port_a) and server_ready(port_b))
        wrapper = tmp_path / "lmutil-wrapper"
        wrapper.write_text(
            f"#!{sys.executable}\n"
            "import os, sys\n"
            "target = next(a for a in sys.argv[1:] if '@' in a)\n"
            "os.execv(sys.executable, [sys.executable, '-m', "
            "'license_manager_simulators.lmstat.cli', '-c', target, '-a'])\n",
            encoding="utf-8",
        )
        wrapper.chmod(0o755)
        monitor = subprocess.Popen([
            "sudo", "-n", "env", f"PYTHONPATH={ROOT / 'simulators/src'}",
            f"LM_MONITOR_LMUTIL={wrapper}", sys.executable,
            "-m", "license_manager_simulators.monitor.cli",
            "--pid", str(proc_a.pid), "--pid", str(proc_b.pid),
            "--db", str(db_path), "--ready-file", str(ready), "--self-query",
        ])

        def monitor_ready() -> bool:
            if monitor.poll() is not None:
                raise AssertionError("monitor exited")
            return ready.exists()

        _wait(monitor_ready)
        daemon_a = _route_to_daemon(port_a, "alpha")["port"]
        daemon_b = _route_to_daemon(port_b, "beta")["port"]
        request("127.0.0.1", daemon_a, CHECKOUT, {
            "feature": "alpha", "user": "multi_a", "host": "demoA", "pid": 11,
            "allow_queue": False,
        })
        request("127.0.0.1", daemon_b, CHECKOUT, {
            "feature": "beta", "user": "multi_b", "host": "demoB", "pid": 22,
            "allow_queue": False,
        })
        # native-style checkouts: greeting + encrypted 0x3d/0x61 exchange so
        # each service's seat can ts-join to its own attempt
        with NativeSession("127.0.0.1", daemon_a) as session:
            session.checkout("alpha")
        with NativeSession("127.0.0.1", daemon_b) as session:
            session.checkout("beta")

        # the first self-query fires at startup (before the checkouts); the
        # second dump joins each probe seat to its own service's attempt.
        # Attempts ride each service's daemon port; the dump rows arrive on
        # the mgr connection, and feature names are unique per service here.
        def both_services_recorded() -> bool:
            with sqlite3.connect(db_path) as conn:
                for feature, daemon_port in (
                        ("alpha", daemon_a), ("beta", daemon_b)):
                    seat = conn.execute("""SELECT COUNT(*) FROM license_events
                        WHERE status='FLEXLM_IN_USE' AND feature=?
                        AND correlation='MATCHED_CHECKOUT_TS'""",
                        (feature,)).fetchone()[0]
                    attempt = conn.execute("""SELECT COUNT(*) FROM license_events
                        WHERE status='FLEXLM_CHECKOUT_ATTEMPT' AND server_port=?
                        AND client_pid IS NOT NULL""",
                        (daemon_port,)).fetchone()[0]
                    summary = conn.execute("""SELECT COUNT(*) FROM poller_summaries
                        WHERE feature=?""", (feature,)).fetchone()[0]
                    detail = conn.execute("""SELECT COUNT(*) FROM poller_details
                        WHERE feature=?""", (feature,)).fetchone()[0]
                    if not (seat and attempt and summary and detail):
                        return False
                return True

        _wait(both_services_recorded, timeout=45)
        with sqlite3.connect(db_path) as conn:
            # manager_pid stamping follows each listener's own tree
            ports = dict(conn.execute(
                "SELECT port, manager_pid FROM listeners").fetchall())
            assert ports[port_a] == proc_a.pid and ports[port_b] == proc_b.pid
            assert ports[daemon_a] == proc_a.pid and ports[daemon_b] == proc_b.pid
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
        for proc in (proc_a, proc_b):
            proc.send_signal(signal.SIGTERM)
            try:
                proc.wait(timeout=5)
            except subprocess.TimeoutExpired:
                proc.kill()
                proc.wait(timeout=5)


def test_discovery_auto_adopts_and_survives_tree_churn(tmp_path):
    """--discovery auto: a tree started AFTER the monitor (argv0 renamed to
    lmgrd, holding a listening socket) is adopted without a manual --pid,
    and killing it must NOT stop the monitor. (Traffic capture for adopted
    trees rides the regular discover/attribute/BPF machinery exercised by
    the manual-mode tests above.)"""
    subprocess.run(["sudo", "-n", "true"], check=True, capture_output=True)
    port = _port()
    db_path = tmp_path / "audit.sqlite"
    ready = tmp_path / "monitor.ready"
    monitor = subprocess.Popen([
        "sudo", "-n", "env", f"PYTHONPATH={ROOT / 'simulators/src'}", sys.executable,
        "-m", "license_manager_simulators.monitor.cli",
        "--discovery", "auto", "--db", str(db_path), "--ready-file", str(ready),
    ])

    def monitor_ready() -> bool:
        if monitor.poll() is not None:
            raise AssertionError("monitor exited before any tree existed")
        return ready.exists()

    _wait(monitor_ready)
    tree = None
    try:
        # argv0 renamed to lmgrd; binds a listening port like a fresh lmgrd
        tree = subprocess.Popen(
            ["/bin/bash", "-c",
             f"exec -a lmgrd \"{sys.executable}\" -c \"import socket, time; "
             f"s = socket.socket(); s.bind(('127.0.0.1', {port})); "
             f"s.listen(5); time.sleep(300)\""],
        )

        def adopted() -> bool:
            if tree.poll() is not None:
                raise AssertionError("tree exited before being adopted")
            with sqlite3.connect(db_path) as conn:
                return conn.execute(
                    "SELECT count(*) FROM listeners WHERE manager_pid = ?",
                    (tree.pid,)).fetchone()[0] >= 1

        _wait(adopted, timeout=15)
        tree.terminate()
        tree.wait(timeout=5)
        tree = None
        time.sleep(2.5)  # several refresh ticks
        assert monitor.poll() is None, "monitor must survive a monitored tree dying"
    finally:
        if tree is not None:
            tree.kill()
            try:
                tree.wait(timeout=5)
            except subprocess.TimeoutExpired:
                pass
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
