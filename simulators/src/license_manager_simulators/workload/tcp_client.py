"""FlexLM-shaped workload client: the checkout/checkin wire is the native
broker surface from ``lmgrd.native`` (0x2f magic, real opcodes, encrypted-
looking payloads), so the traffic decodes as FLEXLM like real clients. The
public API (``wait_for_health``/``post_json`` response dicts) is unchanged.
"""

from __future__ import annotations

import getpass
import os
import socket
import time

from license_manager_simulators.lmgrd import native
from license_manager_simulators.lmgrd.native import (
    CHECKOUT_RETURN_TYPE,
    CHECKIN_TYPE,
    CRYPTO_RESPONSE_TYPE,
    DAEMON_HANDSHAKE_TYPE,
    END_TYPE,
    GRANT_TYPE,
    HELLO_TYPE,
    REQUEST_TYPE,
    ProtocolError,
)

_PLATFORM = "x64_lsb"


def _debug(frame: tuple, tag: str) -> None:
    if os.environ.get("LM_WIRE_DEBUG"):
        print(f"[wire] {tag}: type={frame[0]} strings={frame[1]} raw={frame[3].hex()}",
              flush=True)


class LmgrdClient:
    def __init__(self, port: int, host: str = "127.0.0.1", timeout: float = 5.0) -> None:
        self.port = port
        self.host = host
        self.timeout = timeout

    def wait_for_health(self, timeout: float = 5.0) -> None:
        """Ping/pong (0x3c/0x3e keepalive shape) instead of a status call."""
        end = time.monotonic() + timeout
        while time.monotonic() < end:
            try:
                with socket.create_connection((self.host, self.port), timeout=3) as sock:
                    sock.settimeout(3)
                    sock.sendall(native.encode_ping(client=True))
                    reply = native._read_exact(sock, native.PING_SIZE)
                if reply is not None and reply[0] == 0x3E:
                    return
            except (OSError, ValueError):
                pass
            time.sleep(0.1)
        raise RuntimeError("lmgrd TCP status not ready")

    def post_json(self, path: str, payload: dict) -> dict:
        """Compatibility name for runner; transport is the native broker wire."""
        if path == "/v1/checkout":
            return self._checkout(payload)
        if path in ("/v1/return", "/v1/checkin"):
            return self._return(payload)
        raise ValueError("UNSUPPORTED_OPERATION")

    def _route(self, command: str, argument: str, payload: dict) -> int:
        """0x08 route/find to the manager; returns the vendor daemon port."""
        user = str(payload.get("user") or getpass.getuser())
        host = str(payload.get("host") or socket.gethostname())
        pid = int(payload.get("pid", 0) or 0)
        with socket.create_connection((self.host, self.port), timeout=self.timeout) as sock:
            sock.settimeout(self.timeout)
            sock.sendall(native.encode_greeting(
                user or "unknown", host or "unknown", "lmgrd",
                f"pts/{pid}" if pid else "/dev/tty", pid, _PLATFORM,
            ))
            _expect_hello(sock)
            sock.sendall(native.encode_frame(
                REQUEST_TYPE,
                [user, host, "lmgrd", f"pts/{pid}" if pid else "/dev/tty",
                 command, argument],
                client=True,
            ))
            first = native.recv_broker_frame_full(sock)
            if first is None:
                raise ProtocolError("NO_ROUTE_REPLY")
            _debug(first, "route-reply")
            frame_type, strings, _ts, raw = first
            # Success replies carry the "PORT" marker string plus a 2-byte
            # port tail; error replies carry the error text instead. String
            # slots alone are unreliable (tail bytes can phantom-decode), so
            # match on the marker.
            if not strings:
                raise ProtocolError("NO_ROUTE_PORT")
            if strings[0] != "PORT":
                raise ProtocolError(strings[0])
            port = int.from_bytes(raw[-2:], "big")
            if not 1024 <= port <= 65535:
                raise ProtocolError("BAD_ROUTE_PORT")
            native.recv_broker_frame(sock)  # trailing END (best effort)
            return port

    def _checkout(self, payload: dict) -> dict:
        feature = payload["feature"]
        user = str(payload.get("user", ""))
        host = str(payload.get("host", ""))
        pid = int(payload.get("pid", 0) or 0)
        try:
            daemon_port = self._route("route", feature, payload)
        except ProtocolError as exc:
            reason = str(exc)
            if reason in ("UNKNOWN_FEATURE", "UNKNOWN_DAEMON"):
                return {"status": "REJECTED", "reason": reason, "feature": feature,
                        "checkout_id": None}
            raise
        ts = int(time.time())
        with socket.create_connection((self.host, daemon_port), timeout=self.timeout) as sock:
            sock.settimeout(self.timeout)
            sock.sendall(native.encode_greeting(
                user or "unknown", host or "unknown", "lmgrd",
                f"pts/{pid}" if pid else "/dev/tty", pid, _PLATFORM,
            ))
            _expect_hello(sock)
            sock.sendall(native.encode_frame(
                native.PARAMS_TYPE, [native.xor_hex(feature)], client=True))
            _expect_type(sock, CRYPTO_RESPONSE_TYPE)
            sock.sendall(native.encode_frame(
                DAEMON_HANDSHAKE_TYPE, [native.DAEMON_NAME], client=True))
            _expect_type(sock, GRANT_TYPE)
            sock.sendall(native.encode_checkout_request(ts))
            frame = native.recv_broker_frame_full(sock)
            if frame is not None:
                _debug(frame, "checkout-return")
            if frame is None or frame[0] != CHECKOUT_RETURN_TYPE:
                raise ProtocolError("NO_CHECKOUT_RETURN")
            result = native.decode_result(frame[3])
            if result is None:
                raise ProtocolError("NO_RESULT_TRAILER")
            return {
                "status": result["status"],
                "reason": result["reason"],
                "checkout_id": result["checkout_id"],
                "feature": result["feature"] or feature,
                "checkout_ts": ts,
            }

    def _return(self, payload: dict) -> dict:
        checkout_id = payload["checkout_id"]
        user = str(payload.get("user") or getpass.getuser())
        host = str(payload.get("host") or socket.gethostname())
        try:
            daemon_port = self._route("find", str(checkout_id), payload)
        except ProtocolError as exc:
            reason = str(exc)
            if reason == "UNKNOWN_CHECKOUT":
                return {"status": "REJECTED", "reason": reason,
                        "checkout_id": checkout_id}
            raise
        with socket.create_connection((self.host, daemon_port), timeout=self.timeout) as sock:
            sock.settimeout(self.timeout)
            sock.sendall(native.encode_greeting(
                user, host, "lmgrd", "/dev/tty", os.getpid(), _PLATFORM,
            ))
            _expect_hello(sock)
            sock.sendall(native.encode_frame(
                CHECKIN_TYPE, [str(checkout_id)], client=True))
            frame = native.recv_broker_frame_full(sock)
            if frame is None or frame[0] != END_TYPE:
                raise ProtocolError("NO_CHECKIN_REPLY")
            result = native.decode_result(frame[3])
            if result is None:
                raise ProtocolError("NO_RESULT_TRAILER")
            return {
                "status": result["status"],
                "reason": result["reason"],
                "checkout_id": result["checkout_id"],
                "feature": result["feature"],
            }


def _expect_hello(sock: socket.socket) -> None:
    hello = native.recv_broker_frame(sock)
    if hello is None or hello[0] != HELLO_TYPE:
        raise ProtocolError("NO_HELLO")


def _expect_type(sock: socket.socket, expected: int) -> None:
    frame = native.recv_broker_frame(sock)
    if frame is None or frame[0] != expected:
        raise ProtocolError(f"EXPECTED_0X{expected:02X}")
