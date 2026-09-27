"""Synthetic SIM1 workload client; performs discovery before daemon transactions."""

from __future__ import annotations

import time
from dataclasses import dataclass

from license_manager_simulators.lmgrd.wire import (
    CHECKIN,
    CHECKOUT,
    ENQUIRE,
    STATUS,
    ProtocolError,
    request,
)


@dataclass(frozen=True)
class LmgrdClient:
    port: int
    host: str = "127.0.0.1"

    def post_json(self, path: str, payload: dict) -> dict:
        """Compatibility name for runner; transport is binary TCP, NOT HTTP/JSON."""
        if path == "/v1/checkout":
            feature = payload["feature"]
            try:
                endpoint = request(self.host, self.port, ENQUIRE, {"feature": feature})
            except ProtocolError as exc:
                if str(exc) == "UNKNOWN_FEATURE":
                    return {"status": "REJECTED", "reason": "UNKNOWN_FEATURE", "feature": feature,
                            "checkout_id": None}
                raise
            daemon = next(iter(endpoint["daemons"].values()))
            return request(self.host, daemon["port"], CHECKOUT, payload)
        if path in ("/v1/return", "/v1/checkin"):
            endpoint = request(self.host, self.port, ENQUIRE, {"checkout_id": payload["checkout_id"]})
            daemon = next(iter(endpoint["daemons"].values()))
            return request(self.host, daemon["port"], CHECKIN, payload)
        raise ValueError("UNSUPPORTED_OPERATION")

    def wait_for_health(self, timeout: float = 5.0) -> None:
        end = time.monotonic() + timeout
        while time.monotonic() < end:
            try:
                request(self.host, self.port, STATUS, {})
                return
            except (OSError, ValueError):
                time.sleep(0.1)
        raise RuntimeError("lmgrd TCP status not ready")
