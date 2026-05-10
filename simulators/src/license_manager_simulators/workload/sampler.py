from __future__ import annotations

import subprocess
import re
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
    current_feature: str | None = None
    queued_by_feature: dict[str, int] = {}
    for raw_line in output.splitlines():
        line = raw_line.strip()
        users_match = re.match(
            r"Users of (?P<feature>[^:]+):\s+\(Total of (?P<total>\d+) licenses issued;\s+Total of (?P<in_use>\d+) licenses? in use\)",
            line,
        )
        if users_match:
            current_feature = users_match.group("feature")
            features.append(
                {
                    "feature": current_feature,
                    "total": int(users_match.group("total")),
                    "in_use": int(users_match.group("in_use")),
                    "queued": 0,
                    "expired": False,
                }
            )
            continue

        detail_match = re.match(
            r'"(?P<user>[^"]+)"\s+(?P<host>\S+)\s+/dev/pts/(?P<pid>\d+)\s+\(v[^)]*\)\s+\((?P<server>[^)]+)\s+(?P<server_pid>\d+)\)(?P<tail>.*)',
            line,
        )
        if detail_match and current_feature:
            is_queued = "queued for" in detail_match.group("tail")
            if is_queued:
                queued_by_feature[current_feature] = queued_by_feature.get(current_feature, 0) + 1
            granted_at = None
            start_match = re.search(r", start (?P<start>.+)$", detail_match.group("tail"))
            if start_match:
                granted_at = start_match.group("start")
            checkouts.append(
                {
                    "feature": current_feature,
                    "user": detail_match.group("user"),
                    "host": detail_match.group("host"),
                    "pid": int(detail_match.group("pid")),
                    "checkout_id": f"{detail_match.group('server')}:{detail_match.group('server_pid')}",
                    "status": "QUEUED" if is_queued else "GRANTED",
                    "granted_at": granted_at,
                }
            )
    for feature in features:
        feature["queued"] = queued_by_feature.get(feature["feature"], 0)
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
