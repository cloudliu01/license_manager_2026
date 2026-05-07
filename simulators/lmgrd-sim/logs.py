from __future__ import annotations

from datetime import datetime
from typing import Iterable


def _time_prefix(ts: datetime, tag: str, message: str) -> str:
    return f"{ts:%H:%M:%S} ({tag}) {message}"


def startup_banner(
    ts: datetime,
    server_name: str,
    license_path: str,
    port: int,
    pid: int,
    version: str,
    build: str,
    options_path: str,
) -> list[str]:
    lines = [
        _time_prefix(ts, "lmgrd", "------------------------------"),
        _time_prefix(ts, "lmgrd", ""),
        _time_prefix(ts, "lmgrd", "Please Note:"),
        _time_prefix(ts, "lmgrd", "This log is intended for debug purposes only."),
        _time_prefix(ts, "lmgrd", "In order to capture accurate license"),
        _time_prefix(ts, "lmgrd", "usage data into an organized repository,"),
        _time_prefix(ts, "lmgrd", "please enable report logging. Use Flexera's"),
        _time_prefix(ts, "lmgrd", "software license administration solution,"),
        _time_prefix(ts, "lmgrd", "FlexNet Manager, to readily gain visibility"),
        _time_prefix(ts, "lmgrd", "into license usage data and to create"),
        _time_prefix(ts, "lmgrd", "insightful reports on critical information like"),
        _time_prefix(ts, "lmgrd", "license availability and usage. FlexNet Manager"),
        _time_prefix(ts, "lmgrd", "can be fully automated to run these reports on"),
        _time_prefix(ts, "lmgrd", "schedule and can be used to track license"),
        _time_prefix(ts, "lmgrd", "servers and usage across a heterogeneous"),
        _time_prefix(ts, "lmgrd", "network of servers including Windows NT, Linux"),
        _time_prefix(ts, "lmgrd", "and UNIX."),
        _time_prefix(ts, "lmgrd", ""),
        _time_prefix(ts, "lmgrd", "------------------------------"),
        _time_prefix(ts, "lmgrd", ""),
        _time_prefix(ts, "lmgrd", ""),
        _time_prefix(
            ts, "lmgrd", f"Server's System Date and Time: {ts:%a %b %d %Y %H:%M:%S %Z}"
        ),
        _time_prefix(ts, "lmgrd", "Changing message security level from -1 to 8"),
        _time_prefix(ts, "lmgrd", "SLOG: Summary LOG statistics is enabled."),
        _time_prefix(
            ts, "lmgrd", "The license server manager (lmgrd) running as root:"
        ),
        _time_prefix(ts, "lmgrd", "and this is a potential security problem"),
        _time_prefix(ts, "lmgrd", "and is not recommended."),
        _time_prefix(
            ts,
            "lmgrd",
            f"FlexNet Licensing ({version} build {build}) started on {server_name} (linux) ({ts.month}/{ts.day}/{ts.year})",
        ),
        _time_prefix(
            ts, "lmgrd", "Copyright (c) 1988-2023 Flexera. All Rights Reserved."
        ),
        _time_prefix(ts, "lmgrd", "World Wide Web: http://www.flexerasoftware.com"),
        _time_prefix(ts, "lmgrd", f"License file(s): {license_path}"),
        _time_prefix(ts, "lmgrd", f"lmd_tcp-port {port}"),
        _time_prefix(
            ts,
            "lmgrd",
            "(@lmgrd-SLOG@) ================================================",
        ),
        _time_prefix(ts, "lmgrd", "(@lmgrd-SLOG@) == LMGRD ==="),
        _time_prefix(
            ts, "lmgrd", f"(@lmgrd-SLOG@) Start-Date: {ts:%a %b %d %Y %H:%M:%S %Z}"
        ),
        _time_prefix(ts, "lmgrd", f"(@lmgrd-SLOG@) PID: {pid}"),
        _time_prefix(
            ts, "lmgrd", f"(@lmgrd-SLOG@) LMGRD Version: {version} build {build}"
        ),
        _time_prefix(ts, "lmgrd", "(@lmgrd-SLOG@)"),
        _time_prefix(ts, "lmgrd", "(@lmgrd-SLOG@) == Network Info ==="),
        _time_prefix(ts, "lmgrd", f"(@lmgrd-SLOG@) Listening port {port}"),
        _time_prefix(ts, "lmgrd", "(@lmgrd-SLOG@)"),
        _time_prefix(ts, "lmgrd", "(@lmgrd-SLOG@) == Startup Info ==="),
        _time_prefix(
            ts, "lmgrd", "(@lmgrd-SLOG@) Server Configuration: 3-Server Certificate"
        ),
        _time_prefix(
            ts,
            "lmgrd",
            f"(@lmgrd-SLOG@) Command-line options used at LS startup: -c {license_path} -l {options_path}",
        ),
        _time_prefix(
            ts, "lmgrd", f"(@lmgrd-SLOG@) License file(s) used: {license_path}"
        ),
        _time_prefix(
            ts,
            "lmgrd",
            "(@lmgrd-SLOG@) ================================================",
        ),
    ]
    return lines


def redundancy_attempt(ts: datetime, host: str, role: str, success: bool) -> list[str]:
    lines = [
        _time_prefix(
            ts, "lmgrd", f"Attempting connection to {role} redundant server {host}"
        ),
    ]
    if not success:
        lines.append(
            _time_prefix(
                ts, "lmgrd", f"Failed to connect to {role} redundant server {host}"
            )
        )
        lines.append(
            _time_prefix(
                ts,
                "lmgrd",
                f"Connection attempt to {role} redundant server {host} failed",
            )
        )
    return lines


def quorum_established(ts: datetime, master: str) -> list[str]:
    return [
        _time_prefix(ts, "lmgrd", "Redundant server quorum established."),
        _time_prefix(
            ts, "lmgrd", f"Redundant server quorum established. Master is {master}"
        ),
    ]


def vendor_daemon_startup(
    ts: datetime,
    daemon: str,
    port: int,
    pid: int,
    version: str,
    kit_version: str,
    host: str,
    features: Iterable[str],
) -> list[str]:
    feature_list = "  ".join(features) if features else ""
    return [
        _time_prefix(ts, "lmgd", "Starting vendor daemons ..."),
        _time_prefix(
            ts, "lmgd", f"Started {daemon} (internet tcp port {port} pid {pid})"
        ),
        _time_prefix(
            ts, daemon, f"FlexNet Licensing version {version} build {kit_version}"
        ),
        _time_prefix(ts, daemon, f"{daemon} kit version: {kit_version}"),
        _time_prefix(ts, daemon, "executing tcp override dynamic setting"),
        _time_prefix(ts, daemon, "No TCP override detected"),
        _time_prefix(ts, daemon, "SLOG: Summary LOG statistics is enabled."),
        _time_prefix(ts, daemon, "SLOG: FNPLS-INTERNAL-CKPT1"),
        _time_prefix(ts, daemon, "SLOG: VM Status: 4"),
        _time_prefix(ts, daemon, "SLOG: FNPLS-INTERNAL-CKPT5"),
        _time_prefix(ts, daemon, "SLOG: TPM Status: 0"),
        _time_prefix(ts, daemon, "SLOG: FNPLS-INTERNAL-CKPT6"),
        _time_prefix(ts, daemon, f"Server started on {host} for: {feature_list}"),
        _time_prefix(
            ts,
            daemon,
            "All FEATURE lines for " + daemon + " behave like INCREMENT lines",
        ),
        _time_prefix(
            ts,
            daemon,
            f"(@{daemon}-SLOG@) ================================================================",
        ),
        _time_prefix(ts, daemon, f"(@{daemon}-SLOG@) === Vendor Daemon ==="),
        _time_prefix(ts, daemon, f"(@{daemon}-SLOG@) Vendor daemon: {daemon}"),
        _time_prefix(
            ts, daemon, f"(@{daemon}-SLOG@) Start-Date: {ts:%a %b %d %Y %H:%M:%S %Z}"
        ),
        _time_prefix(ts, daemon, f"(@{daemon}-SLOG@) PID: {pid}"),
        _time_prefix(
            ts, daemon, f"(@{daemon}-SLOG@) VD Version: {version} build {kit_version}"
        ),
        _time_prefix(ts, daemon, f"(@{daemon}-SLOG@)"),
        _time_prefix(ts, daemon, f"(@{daemon}-SLOG@) == Startup/Restart Info =="),
        _time_prefix(ts, daemon, f"(@{daemon}-SLOG@) Options file used: None"),
        _time_prefix(ts, daemon, f"(@{daemon}-SLOG@) Is vendor daemon a CVD: No"),
        _time_prefix(
            ts,
            daemon,
            f"(@{daemon}-SLOG@) Is FlexNet Licensing Service installed and compatible: No",
        ),
        _time_prefix(
            ts, daemon, f"(@{daemon}-SLOG@) FlexNet Licensing Service Version: -NA-"
        ),
        _time_prefix(ts, daemon, f"(@{daemon}-SLOG@) Is TS accessed: No"),
        _time_prefix(ts, daemon, f"(@{daemon}-SLOG@) TS access time: -NA-"),
        _time_prefix(
            ts, daemon, f"(@{daemon}-SLOG@) Number of VD restarts since LS startup: 0"
        ),
        _time_prefix(ts, daemon, f"(@{daemon}-SLOG@)"),
        _time_prefix(ts, daemon, f"(@{daemon}-SLOG@) == Network Info =="),
        _time_prefix(ts, daemon, f"(@{daemon}-SLOG@) Listening port: {port}"),
        _time_prefix(
            ts, daemon, f"(@{daemon}-SLOG@) Daemon select timeout (in seconds): 1"
        ),
        _time_prefix(ts, daemon, f"(@{daemon}-SLOG@)"),
        _time_prefix(ts, daemon, f"(@{daemon}-SLOG@) == Host Info =="),
        _time_prefix(
            ts, daemon, f"(@{daemon}-SLOG@) Host used in license file: {host}"
        ),
        _time_prefix(
            ts, daemon, f"(@{daemon}-SLOG@) HostID of the License Server: 352"
        ),
        _time_prefix(
            ts, daemon, f"(@{daemon}-SLOG@) Running on Hypervisor: Unknown Hypervisor"
        ),
        _time_prefix(
            ts,
            daemon,
            f"(@{daemon}-SLOG@) ================================================================",
        ),
    ]


def checkout_line(
    ts: datetime,
    daemon: str,
    feature: str,
    user: str,
    host: str,
    detail: str,
    count: int,
) -> str:
    suffix = f" ({count} licenses)" if count > 1 else ""
    return _time_prefix(
        ts, daemon, f'OUT: "{feature}" {user}@{host} [{detail}]{suffix}'
    )


def return_line(
    ts: datetime, daemon: str, feature: str, user: str, host: str, detail: str
) -> str:
    return _time_prefix(ts, daemon, f'IN: "{feature}" {user}@{host} [{detail}]')
