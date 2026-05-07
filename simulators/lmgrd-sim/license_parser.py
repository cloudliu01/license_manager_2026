from __future__ import annotations

from dataclasses import dataclass
from datetime import date


@dataclass(frozen=True)
class FeatureDef:
    name: str
    total: int
    daemon: str
    expires_at: date | None


@dataclass(frozen=True)
class LicenseConfig:
    port: int
    server_name: str | None
    daemons: list[str]
    features: dict[str, FeatureDef]


def parse_license_text(text: str) -> LicenseConfig:
    port: int | None = None
    server_name: str | None = None
    daemons: list[str] = []
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
            port = int(parts[1])
            if port < 1 or port > 65535:
                raise ValueError("PORT out of range")
            continue

        if keyword == "SERVER_NAME":
            if len(parts) < 2:
                raise ValueError("SERVER_NAME requires a value")
            server_name = " ".join(parts[1:])
            continue

        if keyword == "DAEMON":
            if len(parts) != 2:
                raise ValueError("DAEMON requires one name")
            daemon_name = parts[1]
            if daemon_name not in daemons:
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
                raise ValueError(f"Unknown FEATURE token: {parts[idx]}")

            if daemon_name != "default" and daemon_name not in daemons:
                raise ValueError("FEATURE references unknown daemon")
            features[name] = FeatureDef(
                name=name,
                total=total,
                daemon=daemon_name,
                expires_at=expires_at,
            )
            continue

        raise ValueError(f"Unknown keyword: {parts[0]}")

    if port is None:
        raise ValueError("PORT is required")

    return LicenseConfig(
        port=port,
        server_name=server_name,
        daemons=daemons,
        features=features,
    )


def parse_license_file(path: str) -> LicenseConfig:
    with open(path, "r", encoding="utf-8") as handle:
        return parse_license_text(handle.read())
