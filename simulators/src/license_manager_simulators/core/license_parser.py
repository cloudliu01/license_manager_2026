from __future__ import annotations

import re
from datetime import date

from .models import FeatureDef, LicenseConfig, ReservationDef


def parse_license_text(text: str) -> LicenseConfig:
    port: int | None = None
    server_name: str | None = None
    daemons: list[str] = []
    daemon_ports: dict[str, int | None] = {}
    features: dict[str, FeatureDef] = {}

    for raw_line in text.splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        parts = line.split()
        keyword = parts[0].upper()

        if keyword == "PORT":
            if len(parts) != 2:
                raise ValueError("PORT requires one value")
            if port is not None:
                raise ValueError("Duplicate PORT")
            port = _parse_port(parts[1])
            continue

        if keyword == "SERVER_NAME":
            if len(parts) < 2:
                raise ValueError("SERVER_NAME requires a value")
            server_name = " ".join(parts[1:])
            continue

        if keyword == "DAEMON":
            if len(parts) not in (2, 4) or (len(parts) == 4 and parts[2].upper() != "PORT"):
                raise ValueError("DAEMON requires name [PORT number]")
            daemon_name = parts[1]
            if not re.fullmatch(r"[A-Za-z0-9_]+", daemon_name):
                raise ValueError("Invalid DAEMON name")
            if daemon_name in daemon_ports:
                raise ValueError("Duplicate DAEMON")
            daemon_ports[daemon_name] = _parse_port(parts[3]) if len(parts) == 4 else None
            daemons.append(daemon_name)
            continue

        if keyword == "FEATURE":
            if len(parts) < 3:
                raise ValueError("FEATURE requires name and total")
            name = parts[1]
            if name in features:
                raise ValueError("Duplicate feature name")
            total = int(parts[2])
            if total < 0:
                raise ValueError("FEATURE total must be >= 0")
            daemon_name = "default"
            expires_at: date | None = None
            reservations: list[ReservationDef] = []
            idx = 3
            while idx < len(parts):
                token = parts[idx].upper()
                if token == "DAEMON":
                    if idx + 1 >= len(parts):
                        raise ValueError("DAEMON requires a value")
                    daemon_name = parts[idx + 1]
                    idx += 2
                    continue
                if token == "EXP":
                    if idx + 1 >= len(parts):
                        raise ValueError("EXP requires a date")
                    year, month, day = parts[idx + 1].split("-")
                    expires_at = date(int(year), int(month), int(day))
                    idx += 2
                    continue
                if token == "RESERVE":
                    if idx + 3 >= len(parts):
                        raise ValueError("RESERVE requires count, kind, and name")
                    count = int(parts[idx + 1])
                    if count < 1:
                        raise ValueError("RESERVE count must be >= 1")
                    kind = parts[idx + 2].upper()
                    if kind not in {"GROUP", "HOST_GROUP", "HOST"}:
                        raise ValueError("RESERVE kind must be GROUP, HOST_GROUP, or HOST")
                    reservation_name = parts[idx + 3]
                    if not re.fullmatch(r"[A-Za-z0-9_]+", reservation_name):
                        raise ValueError("RESERVE name must contain only letters, numbers, and underscores")
                    reservations.append(ReservationDef(kind, reservation_name, count))
                    idx += 4
                    continue
                raise ValueError(f"Unknown FEATURE token: {parts[idx]}")

            features[name] = FeatureDef(name, total, daemon_name, expires_at, tuple(reservations))
            continue

        raise ValueError(f"Unknown keyword: {parts[0]}")

    if port is None:
        raise ValueError("PORT is required")
    for feature in features.values():
        if feature.daemon != "default" and feature.daemon not in daemon_ports:
            raise ValueError(f"FEATURE references unknown daemon: {feature.daemon}")
    if any(feature.daemon == "default" for feature in features.values()):
        daemon_ports.setdefault("default", None)
    fixed_ports = [value for value in daemon_ports.values() if value is not None]
    if port in fixed_ports or len(fixed_ports) != len(set(fixed_ports)):
        raise ValueError("Conflicting daemon port")

    return LicenseConfig(port, server_name, daemons, features, daemon_ports)


def _parse_port(value: str) -> int:
    try:
        port = int(value)
    except ValueError as exc:
        raise ValueError("PORT must be an integer") from exc
    if not 1 <= port <= 65535:
        raise ValueError("PORT out of range")
    return port


def parse_license_file(path: str) -> LicenseConfig:
    with open(path, "r", encoding="utf-8") as handle:
        return parse_license_text(handle.read())
