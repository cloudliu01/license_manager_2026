from __future__ import annotations

import json
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import urlopen


def fetch_status(host: str, port: int) -> dict:
    return _get_json(f"http://{host}:{port}/v1/status")


def fetch_checkouts(
    host: str,
    port: int,
    feature: str | None = None,
    daemon: str | None = None,
    status: str | None = None,
) -> dict:
    params = {"feature": feature, "daemon": daemon, "status": status}
    query = urlencode({key: value for key, value in params.items() if value})
    suffix = f"?{query}" if query else ""
    return _get_json(f"http://{host}:{port}/v1/debug/checkouts{suffix}")


def _get_json(url: str) -> dict:
    try:
        with urlopen(url, timeout=2) as response:
            return json.loads(response.read().decode("utf-8"))
    except (HTTPError, URLError, TimeoutError, OSError) as exc:
        raise RuntimeError("SERVICE_UNREACHABLE") from exc
