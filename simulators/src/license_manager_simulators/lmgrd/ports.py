"""Atomic socket reservation for the manager and dummy daemon processes.

The sockets remain open until the caller either hands them to workers or closes
this reservation. This is deliberately not a network protocol implementation.
"""

from __future__ import annotations

import errno
import random
import socket
from collections.abc import Iterable
from dataclasses import dataclass
from typing import Self

from license_manager_simulators.core.models import LicenseConfig

DYNAMIC_PORTS = range(40000, 50001)


@dataclass
class PortReservation:
    manager: socket.socket
    daemons: dict[str, socket.socket]

    def close(self) -> None:
        for sock in (self.manager, *self.daemons.values()):
            sock.close()

    def __enter__(self) -> Self:
        return self

    def __exit__(self, *_: object) -> None:
        self.close()


def _bind(host: str, port: int) -> socket.socket:
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    # TIME_WAIT remnants from closed connections must not block a re-bind
    # (SO_REUSEADDR does not permit stealing an ACTIVE listener).
    sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    try:
        sock.bind((host, port))
        sock.listen(socket.SOMAXCONN)
    except BaseException:
        sock.close()
        raise
    return sock


def reserve_ports(
    config: LicenseConfig,
    host: str = "0.0.0.0",
    *,
    candidates: Iterable[int] | None = None,
) -> PortReservation:
    """Bind and hold all ports, or close every socket on any failure.

    candidates is injectable for deterministic tests; production uses a random
    permutation of the inclusive range. No probe-and-release TOCTOU window.
    """
    manager = _bind(host, config.port)
    reservation = PortReservation(manager, {})
    try:
        dynamic = list(candidates) if candidates is not None else list(DYNAMIC_PORTS)
        if candidates is None:
            random.SystemRandom().shuffle(dynamic)
        for name, fixed in config.daemon_ports.items():
            if fixed is not None:
                if fixed == config.port or any(
                    sock.getsockname()[1] == fixed for sock in reservation.daemons.values()
                ):
                    raise ValueError("Conflicting daemon port")
                reservation.daemons[name] = _bind(host, fixed)
                continue
            for port in dynamic:
                # Even injected test candidates must be in the specified range.
                if port not in DYNAMIC_PORTS:
                    raise ValueError("Dynamic port outside 40000..50000")
                try:
                    reservation.daemons[name] = _bind(host, port)
                    break
                except OSError as exc:
                    if exc.errno != errno.EADDRINUSE:
                        raise
            else:
                raise OSError("No free daemon port in 40000..50000")
        return reservation
    except BaseException:
        reservation.close()
        raise
