from __future__ import annotations

from datetime import datetime


def generate_output(
    server: str, port: int, features: list[dict], include_details: bool
) -> str:
    lines = [
        "LMSTAT_SIM_FORMAT_VERSION=1",
        f"server: {server} port: {port}",
        f"timestamp: {datetime.utcnow().isoformat()}Z",
    ]

    for feature in features:
        name = feature.get("name")
        total = feature.get("total", 0)
        in_use = feature.get("in_use", 0)
        queued = feature.get("queued", 0)
        expired = feature.get("expired", False)
        lines.append(
            f"feature: {name} total={total} in_use={in_use} queued={queued} expired={str(expired).lower()}"
        )

        if include_details:
            for detail in feature.get("details", []):
                lines.append(
                    f"detail: {name} user={detail.get('user')} host={detail.get('host')} pid={detail.get('pid')}"
                )

    return "\n".join(lines)
