from __future__ import annotations

from datetime import UTC, date, datetime


def generate_output(
    server: str,
    port: int,
    features: list[dict],
    include_details: bool,
    include_feature_usage: bool = True,
) -> str:
    now = datetime.now(UTC)
    feature_groups = _feature_groups(features)
    lines = [
        "lmstat - Copyright (c) 1989-2015 Flexera Software LLC. All Rights Reserved.",
        f"Flexible License Manager status on {_status_time(now)}",
        "",
        f"License server status: {port}@{server}",
        f"    License file(s) on {server}: /path/to/license.dat:",
        "",
        f"{server}: license server UP (MASTER) v11.19.5",
        "",
        f"Vendor daemon status (on {server}):",
    ]

    if not include_feature_usage:
        lines.extend(f"    {vendor}: UP v11.19.5" for vendor, _ in feature_groups)
        return "\n".join(lines)

    for group_index, (vendor, group_features) in enumerate(feature_groups):
        if group_index:
            lines.append("")
        lines.append(f"    {vendor}: UP v11.19.5")
        lines.append("Feature usage info:")

        for feature in group_features:
            lines.append(_usage_line(feature))
            if include_details:
                detail_lines = _feature_detail_lines(server, port, feature)
                if detail_lines:
                    lines.extend(detail_lines)

    if include_details:
        lines.extend(["", *_note_lines(), "", *_inventory_lines(features)])

    return "\n".join(lines)


def _users_prefix(name: str) -> str:
    return f"Users of {name}:".ljust(30)


def _usage_line(feature: dict) -> str:
    name = feature.get("name")
    total = feature.get("total", 0)
    in_use = feature.get("in_use", 0)
    issued_word = "license" if total == 1 else "licenses"
    license_word = "license" if in_use == 1 else "licenses"
    return (
        f"{_users_prefix(name)}"
        f"(Total of {total} {issued_word} issued;  Total of {in_use} {license_word} in use)"
    )


def _feature_detail_lines(server: str, port: int, feature: dict) -> list[str]:
    name = feature.get("name")
    vendor = _vendor(feature)
    expires_at = _expires_at(feature)
    details = feature.get("details", [])
    if not details:
        return []
    lines = [
        "",
        f'  "{name}" v1.0, vendor: {vendor}, expiry: {expires_at}',
        "  floating license",
        "",
    ]
    lines.extend(_detail_line(server, port, detail) for detail in details)
    return lines


def _status_time(value: datetime) -> str:
    return f"{value:%a} {value.month}/{value.day}/{value.year} {value:%H:%M}"


def _vendor(feature: dict) -> str:
    return feature.get("daemon") or feature.get("vendor") or "default"


def _feature_groups(features: list[dict]) -> list[tuple[str, list[dict]]]:
    groups: list[tuple[str, list[dict]]] = []
    by_vendor: dict[str, list[dict]] = {}
    for feature in features:
        vendor = _vendor(feature)
        if vendor not in by_vendor:
            by_vendor[vendor] = []
            groups.append((vendor, by_vendor[vendor]))
        by_vendor[vendor].append(feature)
    return groups or [("default", [])]


def _note_lines() -> list[str]:
    return [
        "NOTE: lmstat -i does not give information from the server,",
        "      but only reads the license file.  For this reason,",
        "      lmstat -a is recommended instead.",
    ]


def _inventory_lines(features: list[dict]) -> list[str]:
    lines = [
        "Feature                         Version     #licenses    Expires      Vendor",
        "_______                         _________   _________    __________   ______",
    ]
    for feature in features:
        name = str(feature.get("name") or "")
        total = int(feature.get("total", 0))
        vendor = _vendor(feature)
        expires_at = _expires_at(feature)
        lines.append(f"{name:<31} 1.0         {total:<11} {expires_at:<12} {vendor}")
    return lines


def _expires_at(feature: dict) -> str:
    value = feature.get("expires_at")
    if not value:
        return "permanent"
    if isinstance(value, date):
        expires = value
    else:
        try:
            expires = date.fromisoformat(str(value))
        except ValueError:
            return str(value)
    return f"{expires.day:02d}-{expires:%b-%Y}"


def _detail_line(server: str, port: int, detail: dict) -> str:
    user = detail.get("user")
    host = detail.get("host")
    pid = detail.get("pid")
    status = detail.get("status")
    prefix = f'    "{user}" {host} /dev/pts/{pid} (v1.0) ({server}/{port} {pid})'
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
