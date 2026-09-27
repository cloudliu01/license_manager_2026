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
from license_manager_simulators.workload.tcp_client import LmgrdClient

client = LmgrdClient(27000)
client.wait_for_health(timeout=10)
body = client.post_json("/v1/checkout", {
    "request_id": "seed-observability-checkout",
    "feature": "alpha",
    "user": "demo_user",
    "host": "demo_host",
    "pid": 1001,
})
if body.get("status") != "GRANTED":
    raise SystemExit(f"seed checkout failed: {body}")
PY

wait "${lmgrd_pid}"
