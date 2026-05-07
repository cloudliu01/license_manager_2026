from __future__ import annotations

from datetime import UTC, datetime


def generate_output(
    server: str, port: int, features: list[dict], include_details: bool
) -> str:
    lines = [
        "LMSTAT_SIM_FORMAT_VERSION=1",
        f"server: {server} port: {port}",
        f"timestamp: {datetime.now(UTC).isoformat()}",
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
                    "detail: "
                    f"{name} "
                    f"user={detail.get('user')} "
                    f"host={detail.get('host')} "
                    f"pid={detail.get('pid')} "
                    f"checkout_id={detail.get('checkout_id')} "
                    f"status={detail.get('status')} "
                    f"granted_at={detail.get('granted_at')}"
                )

    return "\n".join(lines)
