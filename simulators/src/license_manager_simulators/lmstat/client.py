from __future__ import annotations

from license_manager_simulators.lmgrd.wire import CHECKOUTS, STATUS, request


def fetch_status(host: str, port: int) -> dict:
    try:
        return request(host, port, STATUS, {})
    except (OSError, ValueError) as exc:
        raise RuntimeError("SERVICE_UNREACHABLE") from exc


def fetch_checkouts(
    host: str,
    port: int,
    feature: str | None = None,
    daemon: str | None = None,
    status: str | None = None,
) -> dict:
    params = {key: value for key, value in
              (("feature", feature), ("daemon", daemon), ("status", status)) if value}
    try:
        return request(host, port, CHECKOUTS, params)
    except (OSError, ValueError) as exc:
        raise RuntimeError("SERVICE_UNREACHABLE") from exc
