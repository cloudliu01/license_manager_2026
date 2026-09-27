"""Native-style FlexLM status client: greeting, then broker-frame commands.

Speaks the wire defined in ``lmgrd/native.py`` so the simulator's ``lmstat``
behaves like a status client against the simulator manager (and can be decoded
by the monitor as FLEXLM traffic). The public ``fetch_status``/``fetch_checkouts``
API and rendered output are unchanged.
"""

from __future__ import annotations

import getpass
import os
import socket

from license_manager_simulators.lmgrd import native
from license_manager_simulators.lmgrd.native import (
    END_TYPE,
    HELLO_TYPE,
    LISTING_TYPE,
    SEATS_TYPE,
    ProtocolError,
    USER_TYPE,
)

_PLATFORM = "x64_lsb"


class NativeSession:
    def __init__(self, host: str, port: int, timeout: float = 5.0) -> None:
        self.sock = socket.create_connection((host, port), timeout=timeout)
        self.sock.settimeout(timeout)
        self.sock.sendall(
            native.encode_greeting(
                getpass.getuser(),
                socket.getfqdn(),
                "lmgrd",
                "/dev/tty",
                os.getpid(),
                _PLATFORM,
            )
        )
        hello = native.recv_broker_frame(self.sock)
        if hello is None or hello[0] != HELLO_TYPE:
            self.sock.close()
            raise ProtocolError("NO_HELLO")

    def __enter__(self) -> NativeSession:
        return self

    def __exit__(self, *_: object) -> None:
        self.sock.close()

    def command(
        self, command: str, argument: str = ""
    ) -> tuple[list[tuple[int, list[str]]], str]:
        self.sock.sendall(
            native.encode_frame(
                native.REQUEST_TYPE,
                [getpass.getuser(), socket.getfqdn(), "lmgrd", "/dev/tty", command, argument],
                client=True,
            )
        )
        frames: list[tuple[int, list[str]]] = []
        while True:
            frame = native.recv_broker_frame(self.sock)
            if frame is None:
                raise ProtocolError("TRUNCATED_RESPONSE")
            if frame[0] == END_TYPE:
                return frames, frame[1][0] if frame[1] else ""
            frames.append((frame[0], frame[1]))


def _parse_inventory(text: str) -> list[dict]:
    features: list[dict] = []
    for line in text.splitlines():
        fields = line.split()
        if len(fields) < 5 or fields[0] != "FEATURE":
            continue
        try:
            name, total, expires_at, vendor = (
                fields[1],
                int(fields[2]),
                fields[3],
                fields[4],
            )
        except (IndexError, ValueError):
            continue
        reservations = []
        rest = fields[5:]
        for index in range(0, len(rest) - 3, 4):
            if rest[index] == "RESERVE":
                try:
                    reservations.append(
                        {
                            "count": int(rest[index + 1]),
                            "kind": rest[index + 2],
                            "name": rest[index + 3],
                        }
                    )
                except ValueError:
                    continue
        features.append(
            {
                "feature": name,
                "daemon": vendor,
                "total": total,
                "in_use": 0,
                "queued": 0,
                "expired": False,
                "expires_at": expires_at,
                "reservations": reservations,
            }
        )
    return features


def _pid_from_tty(tty: str) -> int:
    tail = tty.rsplit("/", 1)[-1]
    return int(tail) if tail.isdigit() else 0


def _collect_usage(session: NativeSession, feature: dict) -> list[dict]:
    rows: list[dict] = []
    frames, error = session.command("usage", feature["feature"])
    if error:
        return rows
    for frame_type, strings in frames:
        if frame_type == SEATS_TYPE and strings:
            try:
                feature["total"] = int(strings[0])
            except ValueError:
                continue
        elif frame_type == USER_TYPE and len(strings) >= 5:
            user, host, tty, _version, status = strings[:5]
            rows.append(
                {
                    "feature": feature["feature"],
                    "user": user,
                    "host": host,
                    "pid": _pid_from_tty(tty),
                    "status": status,
                }
            )
            if status == "GRANTED":
                feature["in_use"] += 1
            elif status == "QUEUED":
                feature["queued"] += 1
    return rows


def fetch_status(host: str, port: int) -> dict:
    try:
        with NativeSession(host, port) as session:
            features: list[dict] = []
            frames, error = session.command("inventory")
            if error:
                raise ProtocolError(error)
            for frame_type, strings in frames:
                if frame_type == LISTING_TYPE and strings:
                    features.extend(_parse_inventory(strings[0]))
            for feature in features:
                _collect_usage(session, feature)
            return {"features": sorted(features, key=lambda item: item["feature"])}
    except (OSError, ProtocolError) as exc:
        raise RuntimeError("SERVICE_UNREACHABLE") from exc


def fetch_checkouts(
    host: str,
    port: int,
    feature: str | None = None,
    daemon: str | None = None,
    status: str | None = None,
) -> dict:
    rows: list[dict] = []
    try:
        with NativeSession(host, port) as session:
            inventory: list[dict] = []
            frames, error = session.command("inventory")
            if error:
                raise ProtocolError(error)
            for frame_type, strings in frames:
                if frame_type == LISTING_TYPE and strings:
                    inventory.extend(_parse_inventory(strings[0]))

            targets = (
                [
                    {
                        "feature": feature,
                        "total": 0,
                        "in_use": 0,
                        "queued": 0,
                    }
                ]
                if feature
                else inventory
            )
            feature_daemons = {item["feature"]: item["daemon"] for item in inventory}
            for target in targets:
                if daemon and feature_daemons.get(target["feature"]) != daemon:
                    continue
                rows.extend(_collect_usage(session, target))
    except (OSError, ProtocolError) as exc:
        raise RuntimeError("SERVICE_UNREACHABLE") from exc

    if status:
        rows = [row for row in rows if row["status"] == status]
    return {"checkouts": rows}
