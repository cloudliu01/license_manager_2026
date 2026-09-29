# Manual simulator (SIM1 TCP + native-style status-surface notes)

> License transactions use **SIM1, a synthetic test protocol**, NOT the FlexNet wire format; no real FlexNet vendor binary/client can use SIM1. The manager listens on `PORT`, and each dummy vendor daemon has its own **child PID and TCP port**. The annotated-capture notes below describe a separate native-style status surface, not general FlexNet client compatibility.

## Start

```bash
cat >/tmp/license.dat <<'EOF'
SERVER_NAME lic_server
PORT 27000
DAEMON vendorA PORT 42000
FEATURE alpha 2 DAEMON vendorA EXP 2099-11-01
EOF
conda run -n venv312 simulators/wrappers/lmgrd -c /tmp/license.dat -l /tmp/lmgrd.log
```

In another terminal use the SIM1 client. Without a `DAEMON` port, a child binds a random port in **40000–50000** inclusive. Publish fixed vendor ports through Docker/firewalls. `FEATURE` may appear before its `DAEMON` declaration. Undeclared `default` is added when a feature uses it. `PORT 0`, duplicate daemon/port and unknown feature ownership are rejected.

```bash
PYTHONPATH=simulators/src conda run -n venv312 python - <<'PY'
from license_manager_simulators.lmgrd.wire import (
    ENQUIRE, CHECKOUT, CHECKIN, HEARTBEAT, STATUS, request,
)
manager = ('127.0.0.1', 27000)
endpoint = request(*manager, ENQUIRE, {'feature': 'alpha'})
port = endpoint['daemons']['vendorA']['port']
print('daemon PID and port:', endpoint)
print('before:', request(*manager, STATUS, {})['features'])
checkout = request('127.0.0.1', port, CHECKOUT, {
    'feature': 'alpha', 'user': 'user1', 'host': 'host1', 'pid': 101,
    'request_id': 'demo-1', 'quantity': 1, 'allow_queue': False,
})
print('checkout:', checkout)
print('heartbeat:', request('127.0.0.1', port, HEARTBEAT, {}))
print('checkin:', request('127.0.0.1', port, CHECKIN, {
    'checkout_id': checkout['checkout_id'], 'request_id': 'demo-2',
}))
PY
```

`request` opens one connection per call; applications may also send multiple `encode_frame(...)` requests on the same socket. HEARTBEAT does not change seat counts. TCP FIN without CHECKIN does **not** return seats. To observe a live checkout, omit the final checkin. The daemon writes OUT/IN/DENIED to the manager's single debug log writer. On daemon failure the manager reports unavailable, never zero usage.

```bash
conda run -n venv312 simulators/wrappers/lmstat -c 27000@127.0.0.1 -a -i
```

The synthetic format is specified in `simulators/src/license_manager_simulators/lmgrd/wire.py`: `SIM1` + opcode + u32be length + typed binary payload. Example **generated, not captured** enquiry hex for `{'feature':'alpha'}`:

```text
53494d31010000001564000173000766656174757265730005616c706861
```

It deliberately does not claim the screenshot's A/B/C payload bytes. The screenshot's six-byte server-name slot cannot hold the redacted ten-byte `lic_server` value without moving offsets. Public FlexNet administration guides describe daemon/manager roles, not enough wire fields to establish real-client compatibility. See `openspec/changes/simulate-vendor-daemon-ports/evidence.md`.

## Annotated-capture native-style status surface (experimental notes)

The supplied editor diff describes a **second, separate status-query surface** transcribed from annotated captures. It is distinct from SIM1 transactions above and must not be mistaken for the standard or universally compatible FlexNet protocol. The screenshot indicates that `lmstat`-style status queries use these command names:

| Command | Purpose indicated by the capture notes | Request/response type noted |
|---|---|---|
| `getpaths` | Request server/daemon path information (lmgrd greeting/enquiry path) | `0x08` request; `0x0e` hello response |
| `dlist` | List vendor daemons | `0x46` listing response |
| `inventory` | List licensed features/inventory | `0x46` listing response (plus `0x4e` seats on the daemon-scoped surface) |
| `usage <feature>` / `0x3c` feature query | Query users/checkouts for one feature | `0x4e` seats `[in_use, issued, epoch]`; `0x14` user rows `[user, host, tty, version]`; `0x13` end marker (simulator extension) |
| `ping` | Status-surface liveness probe | Fixed 147-byte messages: request starts `0x3c`, response starts `0x3e` |

The `0x3c` broker-frame feature query (not to be confused with the 147-byte `0x3c` ping) carries the feature name (and an opaque key handle on real servers) and is answered by `0x4e` followed by one `0x14` row per in-use seat; es-fs captures calibrate the `0x4e` numbers as `[in_use, issued, epoch]`.

The capture notes further describe a fixed 147-byte EDA greeting beginning `0x68`, with subsequent bytes only partially identified (`??`, `"13"`); and `0x2f` broker frames containing a declared big-endian u16 length, version, type, Unix timestamp and NUL-terminated strings at capture-observed offsets. These are **capture-specific observations**, not a complete grammar. String offsets and lengths can change when values are redacted (for example, the server display name is shown here as `lic_server`).

A session-crypto handshake was observed with leading bytes `0x41/0x47/0x55/0x56/0x3d/0x61`; the screenshot explicitly says this handshake is omitted and the simulator grants without issuing a challenge. Consequently this surface does **not** implement or validate FlexNet session encryption/authentication. Do not send real license-server traffic or treat these message IDs as a stable public API.

**Implementation status:** this surface is implemented in `simulators/src/license_manager_simulators/lmgrd/native.py` (served by the manager/worker alongside SIM1, consumed by the simulator's `lmstat` client in `simulators/src/license_manager_simulators/lmstat/client.py`) and covered by `simulators/tests/unit/test_native_wire.py` plus the opt-in live monitor test. The passive monitor decodes these frames as `FLEXLM_DECODED`, but derives `license_events` only from correlated SIM1 checkout/checkin responses, **not** from native-style status frames. The session-crypto handshake remains omitted, the `0x14` status column is a simulator extension, and END-terminated responses differ from the real count-driven flow.

## Passive PID/port monitor and SQLite

On Linux, start `lmgrd` in the background (or use its actual Python PID shown in the debug log), then start a **separate** monitor *before* generating traffic:

```bash
PYTHON="$(command -v python)" simulators/wrappers/lmgrd -c /tmp/license.dat -l /tmp/lmgrd.log &
LMGRD_PID=$!
mkdir -p /tmp/sim1-audit
sudo env PYTHONPATH="$PWD/simulators/src" "$(command -v python)" \
  -m license_manager_simulators.monitor.cli \
  --pid "$LMGRD_PID" --iface lo --db /tmp/sim1-audit/capture.sqlite \
  --ready-file /tmp/sim1-audit/ready
```

`sim-monitor` discovers child PIDs and their actual TCP listening ports from `/proc`; it uses Linux AF_PACKET to observe loopback **IPv4** TCP without a proxy. It needs root/`CAP_NET_RAW`. Run the checkout/heartbeat/checkin snippet above in another terminal **after** the ready file appears. The demo report and a live capture database are in [`artifacts/sim1-monitor-demo/`](../artifacts/sim1-monitor-demo/report.md).

```bash
sqlite3 /tmp/sim1-audit/capture.sqlite \
  "SELECT daemon,direction,opcode,json_extract(decoded_json,'$.status'),length(raw_bytes),raw_hex FROM frames ORDER BY id;"
sqlite3 /tmp/sim1-audit/capture.sqlite \
  "SELECT pid,daemon,port FROM listeners ORDER BY port;"
```

`frames.decoded_json` is **SIM1-only**; `raw_bytes` is the complete original binary frame BLOB, `raw_hex` is its lowercase hex, and `tcp_segments` preserves the actual captured TCP payload chunks even if a frame could not be decoded. `license_events` records observed GRANTED/DENIED/RETURNED responses linked to captured request/response frame IDs; unknown user identities stay NULL rather than guessed. For an end-to-end demo that launches both processes, executes transactions, verifies SQLite, and leaves them running, use `python tools/sim1_monitor_demo.py` (stop with `python tools/sim1_monitor_demo.py --stop`). The monitor does **not** recover traffic that occurred before attach. Packet loss, IPv6/IP fragmentation, encrypted vendor payloads, or insufficient privileges prevent reliable decoding; don't infer zero usage from missing frames. This is not a real FlexNet sniffer. Stop monitor/lmgrd with Ctrl-C or SIGTERM. HTTP `curl /v1/...` requests to the manager no longer work.
