from __future__ import annotations

from datetime import datetime
from pathlib import Path
from typing import TextIO


def _time_prefix(ts: datetime, tag: str, message: str) -> str:
    return f"{ts.hour}:{ts:%M:%S}\t({tag})\t{message}"


def _client_info(info: str | None) -> str:
    return f"\t[{info}]" if info else ""


def _license_count(quantity: int) -> str:
    if quantity <= 1:
        return ""
    return f"\t({quantity}\tlicenses)"


class MemoryLogWriter:
    def __init__(self) -> None:
        self.lines: list[str] = []

    def write_line(self, tag: str, message: str, ts: datetime | None = None) -> None:
        self.lines.append(_time_prefix(ts or datetime.now(), tag, message))

    def checkout_granted(
        self,
        daemon: str,
        feature: str,
        user: str,
        host: str,
        pid: int,
        checkout_id: str,
        quantity: int = 1,
        info: str | None = None,
    ) -> None:
        self.write_line(
            daemon,
            f'OUT:\t"{feature}"\t{user}@{host}{_client_info(info)}{_license_count(quantity)}',
        )

    def returned(
        self,
        daemon: str,
        feature: str,
        user: str,
        host: str,
        pid: int,
        checkout_id: str,
        quantity: int = 1,
        info: str | None = None,
    ) -> None:
        self.write_line(
            daemon,
            f'IN:\t"{feature}"\t{user}@{host}{_client_info(info)}{_license_count(quantity)}',
        )

    def unsupported(
        self, daemon: str, feature: str, user: str, host: str, info: str | None = None
    ) -> None:
        self.write_line(
            daemon,
            f'UNSUPPORTED:\t"{feature}"\t{user}@{host}{_client_info(info)}\t'
            '(No such feature exists. (-5,346:104 "Connection reset by peer"))',
        )

    def denied(
        self, daemon: str, feature: str, user: str, host: str, reason: str, info: str | None = None
    ) -> None:
        message = _denied_message(reason)
        self.write_line(daemon, f'DENIED:\t"{feature}"\t{user}@{host}{_client_info(info)}\t{message}')

    def queued(
        self,
        daemon: str,
        feature: str,
        user: str,
        host: str,
        checkout_id: str,
        position: int,
    ) -> None:
        self.write_line(
            daemon,
            f'QUEUED: "{feature}" {user}@{host} [checkout_id={checkout_id} position={position}]',
        )

    def shutdown(self) -> None:
        self.write_line("lmgrd", "License server manager shutdown complete")


class FileLogWriter(MemoryLogWriter):
    def __init__(self, path: str) -> None:
        super().__init__()
        Path(path).parent.mkdir(parents=True, exist_ok=True)
        self._handle: TextIO = open(path, "w", encoding="utf-8")

    def write_line(self, tag: str, message: str, ts: datetime | None = None) -> None:
        line = _time_prefix(ts or datetime.now(), tag, message)
        self.lines.append(line)
        self._handle.write(line + "\n")
        self._handle.flush()

    def write_raw_lines(self, lines: list[str]) -> None:
        for line in lines:
            self.lines.append(line)
            self._handle.write(line + "\n")
        self._handle.flush()

    def close(self) -> None:
        self._handle.close()


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
    return [
        _time_prefix(ts, "lmgrd", "------------------------------"),
        _time_prefix(ts, "lmgrd", ""),
        _time_prefix(ts, "lmgrd", "Please Note:"),
        _time_prefix(ts, "lmgrd", "This log is intended for debug purposes only."),
        _time_prefix(
            ts, "lmgrd", f"Server's System Date and Time: {ts:%a %b %d %Y %H:%M:%S %Z}"
        ),
        _time_prefix(ts, "lmgrd", "SLOG: Summary LOG statistics is enabled."),
        _time_prefix(
            ts,
            "lmgrd",
            f"FlexNet Licensing ({version} build {build}) started on {server_name} (linux) ({ts.month}/{ts.day}/{ts.year})",
        ),
        _time_prefix(ts, "lmgrd", f"License file(s): {license_path}"),
        _time_prefix(ts, "lmgrd", f"lmd_tcp-port {port}"),
        _time_prefix(ts, "lmgrd", f"(@lmgrd-SLOG@) PID: {pid}"),
        _time_prefix(ts, "lmgrd", f"(@lmgrd-SLOG@) LMGRD Version: {version} build {build}"),
        _time_prefix(
            ts,
            "lmgrd",
            f"(@lmgrd-SLOG@) Command-line options used at LS startup: -c {license_path} -l {options_path}",
        ),
    ]


def vendor_daemon_startup(
    ts: datetime,
    daemon: str,
    port: int,
    pid: int,
    version: str,
    build: str,
    host: str,
    features: list[str],
) -> list[str]:
    return [
        _time_prefix(ts, "lmgd", "Starting vendor daemons ..."),
        _time_prefix(ts, "lmgd", f"Started {daemon} (internet tcp port {port} pid {pid})"),
        _time_prefix(ts, daemon, f"FlexNet Licensing version {version} build {build}"),
        _time_prefix(ts, daemon, f"Server started on {host} for: {'  '.join(features)}"),
        _time_prefix(ts, daemon, f"All FEATURE lines for {daemon} behave like INCREMENT lines"),
    ]


def _denied_message(reason: str) -> str:
    if reason in {"LICENSE_LIMIT_REACHED", "QUEUE_FULL"}:
        return '(Licensed number of users already reached. (-4,342:104 "Connection reset by peer"))'
    if reason == "FEATURE_EXPIRED":
        return '(Feature has expired. (-10,346:104 "Connection reset by peer"))'
    return f'({reason}. (-4,342:104 "Connection reset by peer"))'
