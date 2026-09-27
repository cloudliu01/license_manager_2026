"""SIM1 manager TCP endpoint: discovery and read-only snapshots only."""

from __future__ import annotations

import socket
from datetime import UTC, datetime
from threading import Event, Thread
from uuid import uuid4

from license_manager_simulators.core.models import LicenseConfig
from license_manager_simulators.lmgrd.processes import ProcessGroup, WorkerUnavailable
from license_manager_simulators.lmgrd.wire import (
    CHECKOUTS,
    ENQUIRE,
    ERROR,
    QUEUE,
    STATUS,
    ProtocolError,
    encode_frame,
    recv_frame,
)


def _route(config: LicenseConfig, group: ProcessGroup, payload: dict) -> dict:
    for key in ("daemon", "feature", "checkout_id"):
        if key in payload and not isinstance(payload[key], str):
            raise ProtocolError("INVALID_ENQUIRY")
    name = payload.get("daemon")
    if name is None and "feature" in payload:
        feature = config.features.get(payload["feature"])
        if feature is None:
            raise ProtocolError("UNKNOWN_FEATURE")
        name = feature.daemon
    if name is None and "checkout_id" in payload:
        found = [vendor for vendor, worker in group.workers.items()
                 if worker.request("find", checkout_id=payload["checkout_id"]).get("found")]
        if len(found) != 1:
            raise ProtocolError("UNKNOWN_CHECKOUT")
        name = found[0]
    if name is None:
        return {vendor: _worker_endpoint(worker) for vendor, worker in group.workers.items()}
    if name not in group.workers:
        raise ProtocolError("UNKNOWN_DAEMON")
    return {name: _worker_endpoint(group.workers[name])}


def _worker_endpoint(worker) -> dict:
    if worker.process.poll() is not None:
        raise WorkerUnavailable(f"{worker.name} unavailable")
    return {"port": worker.port, "pid": worker.pid}


def _aggregate(config: LicenseConfig, group: ProcessGroup) -> dict:
    snapshots = group.snapshot()
    first = next(iter(snapshots.values()), {})
    counters: dict[str, int] = {}
    for snapshot in snapshots.values():
        for key, value in snapshot["counters"].items():
            counters[key] = counters.get(key, 0) + value
    return {
        "protocol_version": 1,
        "server_time": datetime.now(UTC).isoformat(),
        "request_id": str(uuid4()),
        "server_name": config.server_name or "127.0.0.1",
        "port": config.port,
        "features": sorted((row for snapshot in snapshots.values() for row in snapshot["features"]),
                           key=lambda row: row["feature"]),
        "uptime_seconds": min((s["uptime_seconds"] for s in snapshots.values()), default=0),
        "config_hash": first.get("config_hash", "internal"),
        "counters": counters,
    }


def _details(group: ProcessGroup, operation: str, payload: dict) -> dict:
    limit = payload.get("limit", 100)
    if type(limit) is not int or not 1 <= limit <= 500:
        raise ProtocolError("INVALID_LIMIT")
    for field in ("feature", "daemon", "status"):
        if field in payload and not isinstance(payload[field], str):
            raise ProtocolError("INVALID_FILTER")
    key = "checkouts" if operation == "checkouts" else "queue"
    rows = []
    for worker in group.workers.values():
        if payload.get("daemon") and payload["daemon"] != worker.name:
            continue
        rows.extend(worker.request(operation, **payload)[key])
    return {key: rows[:limit], "protocol_version": 1}


def _handle(connection: socket.socket, config: LicenseConfig, group: ProcessGroup) -> None:
    with connection:
        connection.settimeout(10)
        while True:
            try:
                frame = recv_frame(connection)
                if frame is None:
                    return
                op, payload = frame
                if op == ENQUIRE:
                    response = {"daemons": _route(config, group, payload)}
                elif op == STATUS:
                    response = _aggregate(config, group)
                elif op == CHECKOUTS:
                    response = _details(group, "checkouts", payload)
                elif op == QUEUE:
                    response = _details(group, "queue", payload)
                else:
                    raise ProtocolError("WRONG_ENDPOINT")
                connection.sendall(encode_frame(op | 0x80, response))
            except (WorkerUnavailable, ProtocolError, KeyError, TypeError, ValueError) as exc:
                try:
                    connection.sendall(encode_frame(ERROR, {"error": str(exc) or "INVALID_REQUEST"}))
                except OSError:
                    pass
                return
            except (OSError, TimeoutError):
                return


def serve(config: LicenseConfig, group: ProcessGroup, stop: Event) -> None:
    listener = group.reservation.manager
    listener.settimeout(0.5)
    while not stop.is_set():
        try:
            connection, _ = listener.accept()
        except TimeoutError:
            continue
        except OSError:
            if stop.is_set():
                break
            raise
        Thread(target=_handle, args=(connection, config, group), daemon=True).start()
