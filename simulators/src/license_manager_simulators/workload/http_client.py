from __future__ import annotations

import json
import time
from dataclasses import dataclass
from urllib.request import Request, urlopen


@dataclass(frozen=True)
class LmgrdClient:
    port: int
    host: str = "127.0.0.1"

    def post_json(self, path: str, payload: dict) -> dict:
        request = Request(
            f"http://{self.host}:{self.port}{path}",
            data=json.dumps(payload).encode("utf-8"),
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        with urlopen(request, timeout=2) as response:
            return json.loads(response.read().decode("utf-8"))

    def wait_for_health(self, timeout: float = 5.0) -> None:
        end = time.time() + timeout
        while time.time() < end:
            try:
                with urlopen(f"http://{self.host}:{self.port}/v1/health", timeout=0.5):
                    return
            except Exception:
                time.sleep(0.1)
        raise RuntimeError("lmgrd health endpoint not ready")
