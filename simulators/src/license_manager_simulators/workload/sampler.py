from __future__ import annotations

import subprocess
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

from .sqlite_sink import SQLiteSink


@dataclass(frozen=True)
class LmstatSnapshot:
    features: list[dict]
    checkouts: list[dict]
    raw_output: str


def parse_lmstat_output(output: str) -> LmstatSnapshot:
    features: list[dict] = []
    checkouts: list[dict] = []
    for raw_line in output.splitlines():
        line = raw_line.strip()
        if line.startswith("feature: "):
            parts = line.split()
            values = _key_values(parts[2:])
            features.append(
                {
                    "feature": parts[1],
                    "total": int(values["total"]),
                    "in_use": int(values["in_use"]),
                    "queued": int(values["queued"]),
                    "expired": values["expired"].lower() == "true",
                }
            )
        elif line.startswith("detail: "):
            parts = line.split()
            values = _key_values(parts[2:])
            checkouts.append(
                {
                    "feature": parts[1],
                    "user": values.get("user"),
                    "host": values.get("host"),
                    "pid": int(values["pid"]) if values.get("pid") not in (None, "None") else None,
                    "checkout_id": values.get("checkout_id"),
                    "status": values.get("status"),
                    "granted_at": values.get("granted_at"),
                }
            )
    return LmstatSnapshot(features=features, checkouts=checkouts, raw_output=output)


def sample_once(lmstat_path: Path, port: int, sink: SQLiteSink) -> int:
    result = subprocess.run(
        [str(lmstat_path), "-c", f"{port}@127.0.0.1", "-a", "-i"],
        check=True,
        capture_output=True,
        text=True,
    )
    snapshot = parse_lmstat_output(result.stdout)
    return sink.insert_sample(
        sampled_at=datetime.now(UTC).isoformat(),
        raw_output=snapshot.raw_output,
        features=snapshot.features,
        checkouts=snapshot.checkouts,
    )


def _key_values(parts: list[str]) -> dict[str, str]:
    values: dict[str, str] = {}
    for part in parts:
        if "=" in part:
            key, value = part.split("=", 1)
            values[key] = value
    return values
