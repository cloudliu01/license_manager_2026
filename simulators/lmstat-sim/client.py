from __future__ import annotations

import json
from urllib.error import URLError
from urllib.request import urlopen


def _get_json(url: str) -> dict:
    try:
        with urlopen(url, timeout=2) as response:
            return json.loads(response.read().decode("utf-8"))
    except URLError as exc:
        raise RuntimeError("SERVICE_UNREACHABLE") from exc


def fetch_status(host: str, port: int) -> dict:
    return _get_json(f"http://{host}:{port}/v1/status")


def fetch_checkouts(host: str, port: int) -> dict:
    return _get_json(f"http://{host}:{port}/v1/debug/checkouts")
