# Simulator CLI Fidelity Design

## Context

The simulator suite should behave like the tools an agent will supervise: `lmgrd` is a long-running license server process that accepts requests, writes a FlexLM-like debug log, and exposes current license usage; `lmstat` is a separate CLI that can be invoked at any time to retrieve the current state.

The current implementation partially supports this through HTTP endpoints and wrappers, but it does not yet meet the desired behavior:

- `lmgrd` writes only startup logs, not live checkout/return activity.
- Runtime state is kept in dataclasses, while the spec says SQLite should be authoritative.
- The queue is global instead of per `(feature, daemon)`.
- State mutations are not serialized.
- `lmstat -i` omits fields required by the spec.
- The Python layout uses hyphenated directories and dynamic imports instead of normal packages.

## Goals

- Make `simulators/wrappers/lmgrd` and `simulators/wrappers/lmstat` the stable public interface for tests and future agent integration.
- Keep the simulator deterministic and easy to test; do not implement the real FlexLM network protocol.
- Preserve HTTP as the internal control surface for simulated checkout/return and for `lmstat` retrieval.
- Make every processed checkout/return update or read authoritative state and append a matching log event when it changes or rejects simulator state.
- Allow `lmstat` to retrieve an accurate snapshot at any point while `lmgrd` is running.

## Non-Goals

- Real FlexLM protocol compatibility.
- Crash recovery or persistent state after `lmgrd` exits.
- Multi-process Uvicorn workers.
- Security hardening beyond local deterministic simulator needs.

## Package Layout

Use a normal Python package under `simulators/src`:

```text
simulators/
  pyproject.toml
  src/license_manager_simulators/
    core/
      license_parser.py
      models.py
      store.py
      log_writer.py
      service.py
    lmgrd/
      app.py
      cli.py
    lmstat/
      client.py
      cli.py
      output.py
  wrappers/
    lmgrd
    lmstat
  tests/
    unit/
    integration/
```

The old `lmgrd-sim` and `lmstat-sim` modules should be replaced rather than kept as compatibility shims, because they are not external APIs and keeping both layouts would increase maintenance cost.

## Runtime Architecture

`lmgrd` startup flow:

1. Parse CLI arguments: `lmgrd -c <license.dat> -l <log_path>`.
2. Parse `license.dat` into feature and daemon definitions.
3. Initialize an in-memory SQLite store from the parsed license config.
4. Create a log writer for the `-l` path and write the startup/vendor daemon banner.
5. Start a single-process FastAPI app on the license file `PORT`.

Request flow:

1. HTTP endpoint validates request payload.
2. Endpoint calls a service method, not the store directly.
3. Service acquires one process-local lock for all state mutations.
4. Service updates SQLite tables and records an event.
5. Service appends a FlexLM-like log line for the resulting action.
6. Endpoint returns the response model.

`lmstat` flow:

1. Parse CLI arguments: `lmstat -c <port@server> -a`, `-f <feature>`, optional `-i`.
2. Call `GET /v1/status` for the summary snapshot.
3. If `-i` is present, call `GET /v1/debug/checkouts` with filters matching the CLI arguments.
4. Render stable, versioned text output beginning with `LMSTAT_SIM_FORMAT_VERSION=1`.

## State Model

SQLite `:memory:` is authoritative while `lmgrd` is running. Minimum tables:

- `features(name, daemon, total, in_use, expires_at)`.
- `checkouts(checkout_id, feature, daemon, user, host, pid, status, requested_at, granted_at, returned_at)`.
- `queue(queue_id, checkout_id, feature, daemon, user, host, pid, requested_at, position, status)`.
- `req_dedupe(request_id, operation, response_json, first_seen_at)`.
- `events(event_id, event_time, type, payload_json)`.

Queue semantics are per `(feature, daemon)`, not global. Returning a granted checkout frees one seat for the same `(feature, daemon)` and grants the oldest queued item for that same pair.

## API Contract

Stable endpoints remain under `/v1`:

- `GET /v1/health` returns server identity, daemon list, feature count, and current server time.
- `GET /v1/status` returns one feature row per `(feature, daemon)` with `total`, `in_use`, `queued`, and `expired`, plus `uptime_seconds`, `config_hash`, and aggregate counters.
- `POST /v1/checkout` accepts `request_id`, `feature`, `user`, `host`, and `pid`.
- `POST /v1/return` accepts `request_id` and `checkout_id`.
- `GET /v1/debug/checkouts` supports bounded `limit` plus optional `feature`, `daemon`, and `status` filters.
- `GET /v1/debug/queue` supports bounded `limit` plus optional `feature` and `daemon` filters.

`request_id` idempotency applies per operation. Reusing the same `request_id` for the same operation returns the original response. Reusing it for a different operation is rejected as `INVALID_REQUEST_ID`.

## Logging Behavior

The simulator log is append-only after startup.

Required runtime log events:

- Granted checkout: `OUT: "<FEATURE>" <user>@<host> [pid=<pid> checkout_id=<id>]`.
- Return: `IN: "<FEATURE>" <user>@<host> [pid=<pid> checkout_id=<id>]`.
- Rejected checkout: `DENIED: "<FEATURE>" <user>@<host> [reason=<reason>]`.
- Queued checkout: `QUEUED: "<FEATURE>" <user>@<host> [checkout_id=<id> position=<n>]`.
- Queue grant transition: an `OUT` line for the queued checkout when it becomes granted.
- Clean shutdown: append a short `lmgrd` shutdown line when the app receives shutdown.

All log writes should be flushed immediately so tests and supervising agents can tail the file reliably.

## Error Handling

- Invalid request payloads return HTTP 400 with `INVALID_REQUEST`.
- Unknown features produce a structured rejected checkout result with `UNKNOWN_FEATURE` and a `DENIED` log line.
- Expired features produce `FEATURE_EXPIRED`.
- Queue overflow produces `QUEUE_FULL`.
- Unknown checkout returns produce `UNKNOWN_CHECKOUT`.
- Already returned checkouts produce `ALREADY_RETURNED`.
- `lmstat` exits non-zero and writes one concise stderr line if the service is unreachable or returns invalid data.

## Testing Strategy

Unit tests:

- License parsing and validation.
- SQLite store checkout, return, queue, idempotency, and invariants.
- Log line rendering.
- `lmstat` output rendering.

Integration tests:

- Start `wrappers/lmgrd` with a temporary license file and free port.
- Poll `/v1/health` until ready.
- Issue HTTP checkout and return requests.
- Invoke `wrappers/lmstat` after each mutation and assert the snapshot reflects current usage.
- Assert the log file contains startup, `OUT`, `IN`, `DENIED`, `QUEUED`, and queue transition lines as appropriate.
- Always terminate the subprocess and verify it exits.

Tooling tests:

- `pytest -q` from repository root.
- `ruff check .` once ruff is added to development dependencies.

## Migration Plan

1. Add package layout and move simulator modules into `simulators/src/license_manager_simulators`.
2. Update `simulators/pyproject.toml` with package discovery and console scripts.
3. Update wrappers to call the package CLIs.
4. Replace dataclass-only state with SQLite-backed store and service layer.
5. Wire FastAPI endpoints through the service layer.
6. Add append-only runtime logging.
7. Update tests to import package modules normally and cover live `lmstat` snapshots.
8. Remove old hyphenated simulator module directories.

## Open Decisions

- HTTP remains the internal simulator protocol. It is not intended to mimic the real FlexLM wire protocol.
- The public compatibility surface is the two wrappers and the `/v1` simulator API, not the old Python module paths.
- Runtime persistence ends when `lmgrd` exits.
