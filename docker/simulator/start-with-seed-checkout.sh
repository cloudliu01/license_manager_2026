#!/usr/bin/env sh
set -eu

/app/simulators/wrappers/lmgrd -c /demo/license.dat -l /demo/lmgrd.log &
lmgrd_pid=$!

cleanup() {
  kill "${lmgrd_pid}" 2>/dev/null || true
  wait "${lmgrd_pid}" 2>/dev/null || true
}
trap cleanup EXIT INT TERM

python - <<'PY'
import json
import time
from urllib.request import Request, urlopen

deadline = time.time() + 10
last_error = None
while time.time() < deadline:
    try:
        with urlopen("http://127.0.0.1:27000/v1/health", timeout=1):
            break
    except Exception as exc:
        last_error = exc
        time.sleep(0.2)
else:
    raise SystemExit(f"lmgrd health endpoint not ready: {last_error}")

payload = {
    "request_id": "seed-observability-checkout",
    "feature": "alpha",
    "user": "demo_user",
    "host": "demo_host",
    "pid": 1001,
}
request = Request(
    "http://127.0.0.1:27000/v1/checkout",
    data=json.dumps(payload).encode("utf-8"),
    headers={"Content-Type": "application/json"},
    method="POST",
)
with urlopen(request, timeout=2) as response:
    body = json.loads(response.read().decode("utf-8"))
if body.get("status") != "GRANTED":
    raise SystemExit(f"seed checkout failed: {body}")
PY

wait "${lmgrd_pid}"
