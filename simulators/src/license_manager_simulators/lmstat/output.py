from __future__ import annotations

from datetime import UTC, datetime


def generate_output(
    server: str, port: int, features: list[dict], include_details: bool
) -> str:
    now = datetime.now(UTC)
    lines = [
        "lmstat - Copyright (c) 1994-2024 Flexera. All rights reserved.",
        f"Flexible License Manager status on {now:%a %b %d %H:%M:%S %Y}",
        "",
        f"License server status: {port}@{server}",
        f"    License file(s) on {server}: /path/to/license.dat:",
        "",
        f"{server}: license server UP (MASTER) v11.19.5",
        "",
        f"Vendor daemon status (on {server}):",
        "",
        "    default: UP v11.19.5",
        "Feature usage info:",
    ]

    for feature in features:
        name = feature.get("name")
        total = feature.get("total", 0)
        in_use = feature.get("in_use", 0)
        license_word = "license" if in_use == 1 else "licenses"
        lines.extend(
            [
                "",
                f"Users of {name}:  (Total of {total} licenses issued;  Total of {in_use} {license_word} in use)",
            ]
        )

        if include_details:
            details = feature.get("details", [])
            if details:
                lines.extend(
                    [
                        "",
                        f'  "{name}" v1.0, vendor: default, expiry: permanent',
                        "  floating license",
                        "",
                    ]
                )
                for detail in details:
                    lines.append(_detail_line(server, port, detail))

    return "\n".join(lines)


def _detail_line(server: str, port: int, detail: dict) -> str:
    user = detail.get("user")
    host = detail.get("host")
    pid = detail.get("pid")
    status = detail.get("status")
    prefix = f'"{user}" {host} /dev/pts/{pid} (v1.0) ({server}/{port} {pid})'
    if status == "QUEUED":
        return f"{prefix} queued for 1 license"
    return f"{prefix}, start {_format_start(detail.get('granted_at'))}"


def _format_start(value: str | None) -> str:
    if not value:
        return datetime.now(UTC).strftime("%a %-m/%-d %H:%M")
    try:
        return datetime.fromisoformat(value).strftime("%a %-m/%-d %H:%M")
    except ValueError:
        return datetime.now(UTC).strftime("%a %-m/%-d %H:%M")
