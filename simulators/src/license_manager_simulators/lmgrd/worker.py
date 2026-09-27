"""Dummy daemon child: SIM1 is synthetic and cannot serve real FlexNet clients."""

from __future__ import annotations

import os
import socket
import sys
from dataclasses import asdict
from datetime import datetime
from threading import Lock, Thread

from license_manager_simulators.core.license_parser import parse_license_file
from license_manager_simulators.core.log_writer import MemoryLogWriter
from license_manager_simulators.core.models import LicenseConfig
from license_manager_simulators.core.service import SimulatorService
from license_manager_simulators.core.store import SimulatorStore
from license_manager_simulators.lmgrd.processes import (
    WorkerUnavailable,
    _receive,
    _send,
)
from license_manager_simulators.lmgrd.wire import (
    CHECKIN,
    CHECKOUT,
    ERROR,
    HEARTBEAT,
    ProtocolError,
    encode_frame,
    recv_frame,
)


class IpcLogWriter(MemoryLogWriter):
    def __init__(self, channel: socket.socket) -> None:
        super().__init__()
        self.channel = channel
        self.lock = Lock()

    def write_line(self, tag: str, message: str, ts: datetime | None = None) -> None:
        with self.lock:
            super().write_line(tag, message, ts)
            self.channel.sendall((self.lines[-1] + "\n").encode("utf-8"))


def _handle_client(connection: socket.socket, service: SimulatorService) -> None:
    with connection:
        connection.settimeout(10)
        while True:
            try:
                frame = recv_frame(connection)
                if frame is None:
                    return
                op, data = frame
                if op == HEARTBEAT:
                    reply = {"alive": True}
                elif op == CHECKOUT:
                    feature = data["feature"]
                    if not isinstance(feature, str) or service.store.get_feature(feature) is None:
                        raise ProtocolError("UNKNOWN_FEATURE")
                    if not isinstance(data["user"], str) or not isinstance(data["host"], str):
                        raise ProtocolError("INVALID_CLIENT")
                    if type(data["pid"]) is not int or type(data.get("quantity", 1)) is not int:
                        raise ProtocolError("INVALID_QUANTITY")
                    if data.get("request_id") is not None and not isinstance(data["request_id"], str):
                        raise ProtocolError("INVALID_REQUEST_ID")
                    if data.get("info") is not None and not isinstance(data["info"], str):
                        raise ProtocolError("INVALID_INFO")
                    if type(data.get("allow_queue", True)) is not bool:
                        raise ProtocolError("INVALID_QUEUE_FLAG")
                    reply = asdict(service.checkout(
                        feature, data["user"], data["host"], data["pid"],
                        request_id=data.get("request_id"), quantity=data.get("quantity", 1),
                        info=data.get("info"), allow_queue=data.get("allow_queue", True),
                    ))
                elif op == CHECKIN:
                    checkout_id = data["checkout_id"]
                    if data.get("request_id") is not None and not isinstance(data["request_id"], str):
                        raise ProtocolError("INVALID_REQUEST_ID")
                    if not isinstance(checkout_id, str) or not service.has_checkout(checkout_id):
                        raise ProtocolError("UNKNOWN_CHECKOUT")
                    reply = asdict(service.return_checkout(checkout_id, request_id=data.get("request_id")))
                else:
                    raise ProtocolError("WRONG_ENDPOINT")
                connection.sendall(encode_frame(op | 0x80, reply))
            except (KeyError, ValueError, TypeError) as exc:
                try:
                    connection.sendall(encode_frame(ERROR, {"error": str(exc) or "INVALID_REQUEST"}))
                except OSError:
                    pass
                return
            except (OSError, TimeoutError):
                return


def _serve(listener: socket.socket, service: SimulatorService) -> None:
    listener.settimeout(0.5)
    while listener.fileno() != -1:
        try:
            connection, _ = listener.accept()
        except TimeoutError:
            continue
        except OSError:
            return
        Thread(target=_handle_client, args=(connection, service), daemon=True).start()


def main() -> int:
    license_path, daemon, listener_fd, channel_fd, log_fd = sys.argv[1:]
    listener = socket.socket(fileno=int(listener_fd))
    channel = socket.socket(fileno=int(channel_fd))
    log_channel = socket.socket(fileno=int(log_fd))
    try:
        config = parse_license_file(license_path)
        if daemon not in config.daemon_ports:
            raise ValueError("Unknown daemon")
        scoped = LicenseConfig(
            port=config.port,
            server_name=config.server_name,
            daemons=[daemon],
            features={name: feature for name, feature in config.features.items() if feature.daemon == daemon},
            daemon_ports={daemon: config.daemon_ports[daemon]},
        )
        service = SimulatorService(
            SimulatorStore.from_license(scoped), IpcLogWriter(log_channel),
            config.server_name or "127.0.0.1", config.port, "internal",
        )
        # Only the manager may publish readiness after every child acknowledges.
        Thread(target=_serve, args=(listener, service), daemon=True).start()
        while True:
            try:
                request = _receive(channel)
            except WorkerUnavailable:  # parent control channel closed
                break
            operation = request.get("op")
            if operation == "ready":
                reply = {"pid": os.getpid(), "port": listener.getsockname()[1]}
            elif operation == "status":
                reply = {"status": service.status()}
            elif operation == "checkouts":
                reply = {"checkouts": service.debug_checkouts(
                    request.get("limit", 100), request.get("feature"),
                    request.get("daemon"), request.get("status"),
                )}
            elif operation == "queue":
                reply = {"queue": service.debug_queue(
                    request.get("limit", 100), request.get("feature"), request.get("daemon"),
                )}
            elif operation == "find":
                checkout_id = request.get("checkout_id")
                reply = {"found": isinstance(checkout_id, str) and service.has_checkout(checkout_id)}
            elif operation == "stop":
                _send(channel, {"stopped": True})
                break
            else:
                reply = {"error": "UNKNOWN_OPERATION"}
            _send(channel, reply)
        return 0
    finally:
        listener.close()
        channel.close()
        log_channel.close()


if __name__ == "__main__":
    raise SystemExit(main())
