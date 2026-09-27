"""SIM1 topology/seat flow; never a real FlexNet compatibility test."""

from __future__ import annotations

import socket
import threading
import time

import pytest
from license_manager_simulators.core.license_parser import parse_license_file
from license_manager_simulators.lmgrd.manager import serve
from license_manager_simulators.lmgrd.processes import start_process_group
from license_manager_simulators.lmgrd.wire import (
    CHECKIN,
    CHECKOUT,
    ENQUIRE,
    HEARTBEAT,
    STATUS,
    ProtocolError,
    encode_frame,
    recv_frame,
    request,
)


def _free_port() -> int:
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]


def test_discovery_direct_checkout_heartbeat_fin_and_reconciliation(tmp_path):
    manager_port, a_port, b_port = (_free_port() for _ in range(3))
    while len({manager_port, a_port, b_port}) < 3:
        b_port = _free_port()
    license_path = tmp_path / "license.txt"
    log_path = tmp_path / "debug.log"
    license_path.write_text(
        f"SERVER_NAME lic_server\nPORT {manager_port}\n"
        f"DAEMON vend_a PORT {a_port}\nDAEMON vend_b PORT {b_port}\n"
        "FEATURE alpha 1 DAEMON vend_a\nFEATURE beta 2 DAEMON vend_b\n"
    )
    config = parse_license_file(str(license_path))
    stop = threading.Event()
    with start_process_group(config, str(license_path), log_path=str(log_path)) as group:
        server = threading.Thread(target=serve, args=(config, group, stop), daemon=True)
        server.start()
        try:
            route_a = request("127.0.0.1", manager_port, ENQUIRE, {"feature": "alpha"})["daemons"]["vend_a"]
            route_b = request("127.0.0.1", manager_port, ENQUIRE, {"feature": "beta"})["daemons"]["vend_b"]
            assert route_a == {"port": a_port, "pid": group.workers["vend_a"].pid}
            assert route_b == {"port": b_port, "pid": group.workers["vend_b"].pid}
            assert route_a["pid"] != route_b["pid"]
            with socket.create_connection(("127.0.0.1", manager_port)) as old_http:
                old_http.settimeout(2)
                old_http.sendall(b"GET /v1/health HTTP/1.1\r\nHost: localhost\r\n\r\n")
                assert not old_http.recv(128).startswith(b"HTTP/")
            with socket.create_connection(("127.0.0.1", a_port)) as malformed:
                malformed.sendall(b"SIM1\x03\xff\xff\xff\xff")
                malformed.shutdown(socket.SHUT_WR)
            assert request("127.0.0.1", manager_port, STATUS, {})["features"][0]["in_use"] == 0
            # Multiple messages on one socket; packet splitting is not a frame boundary.
            with socket.create_connection(("127.0.0.1", a_port)) as client:
                checkout = encode_frame(CHECKOUT, {
                    "feature": "alpha", "user": "u", "host": "h", "pid": 7,
                    "allow_queue": False,
                })
                client.sendall(checkout[:3])
                client.sendall(checkout[3:] + encode_frame(HEARTBEAT, {}))
                op, granted = recv_frame(client)
                assert op == CHECKOUT | 0x80
                assert granted["status"] == "GRANTED"
                assert recv_frame(client) == (HEARTBEAT | 0x80, {"alive": True})
                client.sendall(encode_frame(CHECKOUT, {
                    "feature": "alpha", "user": "u2", "host": "h", "pid": 8,
                    "allow_queue": False,
                }))
                assert recv_frame(client)[1]["status"] == "DENIED"
            assert request("127.0.0.1", manager_port, STATUS, {})["features"][0]["in_use"] == 1
            queued = request("127.0.0.1", a_port, CHECKOUT, {
                "feature": "alpha", "user": "u3", "host": "h", "pid": 9,
            })
            assert queued["status"] == "QUEUED"
            assert request("127.0.0.1", manager_port, STATUS, {})["features"][0]["queued"] == 1
            with pytest.raises(ProtocolError, match="WRONG_ENDPOINT"):
                request("127.0.0.1", manager_port, CHECKOUT, {"feature": "alpha"})
            with pytest.raises(ProtocolError, match="UNKNOWN_FEATURE"):
                request("127.0.0.1", b_port, CHECKOUT, {
                    "feature": "alpha", "user": "u", "host": "h", "pid": 7,
                })
            returned = request("127.0.0.1", a_port, CHECKIN, {"checkout_id": granted["checkout_id"]})
            assert returned["status"] == "RETURNED"
            assert request("127.0.0.1", manager_port, STATUS, {})["features"][0]["in_use"] == 1
            assert request("127.0.0.1", a_port, CHECKIN, {"checkout_id": queued["checkout_id"]})["status"] == "RETURNED"
            assert request("127.0.0.1", manager_port, STATUS, {})["features"][0]["in_use"] == 0
            for _ in range(20):
                lines = log_path.read_text()
                if lines.count('IN:\t"alpha"') == 2:
                    break
                time.sleep(0.05)
            assert lines.count('OUT:\t"alpha"') == 2
            assert lines.count('DENIED:\t"alpha"') == 1
            assert lines.count('IN:\t"alpha"') == 2
        finally:
            stop.set()
            server.join(timeout=2)
