# FlexLM Simulator Suite Specification (v0.3)

**Scope:** `lmgrd-sim` service + `lmstat-sim` CLI, sharing one backend state model and log templating.

## 0. Purpose & Intention

Provide deterministic substitutes for vendor tools to support:

* Agent supervision flows (`lmgrd` long-running, `lmstat` periodic CLI)
* Integration tests and development without vendor binaries
* Stable parsing inputs (lmstat text output + FlexLM-like logs)
* Multi-daemon and per-feature license accounting

Non-goals:

* Implement real FlexLM network protocol.
* Provide persistence/crash recovery.
* Provide security hardening (simulator only).

---

## 1. Implementation Constraints

1. Language: **Python** (3.11 recommended).
2. Two wrappers:

   * `lmgrd` (bash wrapper) launches **lmgrd-sim** service
   * `lmstat` (bash wrapper) launches **lmstat-sim** CLI
3. Shared Python package (recommended layout):

```
sim/
  core/                 # parser, models, sqlite schema, log templating
  lmgrd_sim/            # FastAPI app + service runner
  lmstat_sim/           # CLI + output formatter
  wrappers/
    lmgrd               # bash
    lmstat              # bash
```

---

## 2. CLI Interfaces (No optional flags)

### 2.1 `lmgrd` wrapper (lmgrd-sim)

`lmgrd -c <path_to_license.dat> -l <path_to_out_log.log>`

* `-c` required
* `-l` required

Exit codes:

* `0` clean exit
* `>0` startup failure (parse errors, bind errors)

### 2.2 `lmstat` wrapper (lmstat-sim)

Must accept a minimal subset similar to real usage:

* `lmstat -c <port@server> -a`
* `lmstat -c <port@server> -f <feature>`
* `lmstat -c <port@server> -a -i` *(verbose checkout detail)*
* `lmstat -c <port@server> -f <feature> -i`

Notes:

* `<port@server>` parsing: extract `port` and optional host

  * if host missing, default to `127.0.0.1`
* lmstat-sim does **HTTP** to lmgrd-sim at that host:port.

Exit codes:

* `0` on successful output generation
* `>0` if service unreachable / bad args / invalid response

---

## 3. `license.dat` Grammar (Spec-defined)

### 3.1 Supported Syntax

Example:

```
PORT 27000
SERVER_NAME myhost

DAEMON vendorA
DAEMON vendorB

FEATURE alpha 10 DAEMON vendorA EXP 2026-12-31
FEATURE beta  3  DAEMON vendorB
FEATURE gamma 25
```

### 3.2 Rules

* `PORT <int>` required, 1–65535
* `SERVER_NAME <string>` optional
* `DAEMON <name>` optional, repeatable
* `FEATURE <name> <total> [DAEMON <daemon_name>] [EXP <YYYY-MM-DD>]`

  * `total` integer ≥ 0
  * default daemon: `"default"` if omitted
  * expired features are non-grantable

Parse failures:

* unknown keyword → startup fail
* feature references unknown daemon → startup fail
* duplicate feature name → startup fail

---

## 4. Service Interface (lmgrd-sim FastAPI)

### 4.1 Port Binding Rule (Important)

`PORT` in `license.dat` defines the **HTTP API port** for the simulator service.

This is a simulator-only convention.

### 4.2 API Versioning

* All stable endpoints under `/v1/...`
* Responses include:

  * `protocol_version: 1`
  * `server_time`
  * `request_id`

### 4.3 Stable vs Non-stable Endpoints

* `/v1/*` endpoints are the **stable contract**
* `/v1/debug/*` endpoints are **also stable** in this spec (since lmstat-sim will use them for `-i`), but their fields must still be explicitly defined and versioned.

---

## 5. State and Storage (In-memory SQLite)

### 5.1 Storage

* Use SQLite in-memory (`:memory:`) as the authoritative runtime state store.
* Single-process service. Do not run multiple Uvicorn workers.

### 5.2 Minimum Logical Tables

* `features(name, daemon, total, in_use, expires_at)`
* `checkouts(checkout_id, feature, daemon, user, host, pid, status, requested_at, granted_at, returned_at)`
* `queue(queue_id, feature, daemon, user, host, pid, requested_at, position, status)`
* `req_dedupe(request_id, first_seen_at, response_json)` *(for idempotency)*
* `events(event_id, event_time, type, payload_json)` *(for monitoring / debugging)*

---

## 6. License Semantics

### 6.1 Checkout statuses

* `GRANTED`
* `QUEUED`
* `REJECTED`

### 6.2 Return statuses

* `RETURNED`
* `REJECTED`

### 6.3 Queue semantics

* FIFO per `(feature, daemon)`
* When a seat is freed, earliest queued request is auto-granted
* `QUEUE_MAX` constant = 100 (v0.3)

  * beyond → REJECTED (`QUEUE_FULL`)

### 6.4 Standard rejection reasons

* `UNKNOWN_FEATURE`
* `FEATURE_EXPIRED`
* `INVALID_REQUEST`
* `QUEUE_FULL`
* `UNKNOWN_CHECKOUT`
* `ALREADY_RETURNED`

---

## 7. API Endpoints (lmgrd-sim)

All endpoints respond with JSON and include `protocol_version`, `server_time`, `request_id`.

### 7.1 Health

`GET /v1/health`

Returns: running status, server_name, port, daemon list, feature count.

### 7.2 Status (Stable snapshot used by lmstat-sim)

`GET /v1/status`

Returns:

* `server_name`, `port`
* `features`: list of `{feature, daemon, total, in_use, queued, expired}`
* counters: granted/queued/rejected/returned
* `config_hash` (hash of parsed license.dat)
* `uptime_seconds`

### 7.3 Checkout

`POST /v1/checkout`
Request:

```json
{"request_id":"optional-uuid","feature":"alpha","user":"u1","host":"h1","pid":1234}
```

Response:

```json
{
  "protocol_version":1,
  "request_id":"uuid",
  "checkout_id":"uuid-or-null",
  "feature":"alpha",
  "daemon":"vendorA",
  "status":"GRANTED|QUEUED|REJECTED",
  "reason":"string-or-null",
  "total":10,"in_use":3,"queued":1
}
```

Idempotency:

* If request_id repeats, return identical response.

### 7.4 Return

`POST /v1/return`
Request:

```json
{"request_id":"optional-uuid","checkout_id":"uuid"}
```

Response:

```json
{
  "protocol_version":1,
  "request_id":"uuid",
  "checkout_id":"uuid",
  "feature":"alpha",
  "daemon":"vendorA",
  "status":"RETURNED|REJECTED",
  "reason":"string-or-null",
  "total":10,"in_use":2,"queued":0
}
```

Return idempotency:

* Returning an already returned checkout_id → REJECTED (`ALREADY_RETURNED`)

### 7.5 Debug endpoints (needed for `lmstat -i`)

`GET /v1/debug/checkouts?feature=...&daemon=...&status=...&limit=...`

* returns active and/or recent checkouts.

`GET /v1/debug/queue?feature=...&daemon=...&limit=...`

* returns queue entries in FIFO order.

These endpoints are read-only and must be bounded (limit with server-side caps).

> No reset/shutdown/load admin endpoints are provided.

---

## 8. Logging (FlexLM-like, template-driven)

### 8.1 Template Input

A template file is provided: `@samples/logs/license_log_template.txt`.

* lmgrd-sim must produce output log at the `-l` path.
* Log lines MUST follow the template semantics and line prefixes.

### 8.2 Line Format Requirements

* Each line begins with `HH:MM:SS (TAG)`.
* `TAG` values must include at least: `lmgrd`, `lmgd`, and vendor daemon names (e.g., `daemon_v`, `daemon_c`).
* Blank lines and separator lines (`------------------------------`) are part of the startup banner and must be preserved.

### 8.3 Startup and Service Banner Content

The startup section must include, in order, the major blocks present in the template:

* A "Please Note" informational block describing debug log intent.
* "Server's System Date and Time" line with a human-readable timestamp.
* Security level change and SLOG enablement lines.
* License server manager startup lines including:

  * version/build
  * server host identity
  * license file path
  * lmd_tcp-port value
* An `(@lmgrd-SLOG@)` block with:

  * Start-Date
  * PID
  * LMGRD Version
  * Listening port
  * Command-line options used at LS startup
  * License file(s) used

### 8.4 Redundant Server Quorum Messages

If redundancy is enabled, log the connection attempts and quorum establishment lines using the template phrasing:

* Attempting connection to secondary/tertiary redundant server
* Failed to connect... and connection attempt failed lines
* Quorum established and master selection line

### 8.5 Vendor Daemon Startup Blocks

Vendor daemon startup must include:

* "Starting vendor daemons ..." line
* "Started <daemon> (internet tcp port <port> pid <pid>)" lines
* Version/kit lines for each daemon
* TCP override detection lines
* SLOG and internal checkpoint lines
* "Server started on <host> for: <feature list>" lines
* "All FEATURE lines ... behave like INCREMENT lines" lines
* Per-daemon `(@daemon-SLOG@)` blocks covering startup, network, and host info

### 8.6 Checkout/Return Activity Lines

* OUT lines: `OUT: "<FEATURE>" <user>@<host> [<detail>] (N licenses)`
* IN lines: `IN: "<FEATURE>" <user>@<host> [<detail>]`
* These lines must be emitted for simulated checkouts/returns and be compatible with downstream parsing.

### 8.7 Token Substitution

At minimum, support these tokens:
`{TIMESTAMP}`, `{SERVER_NAME}`, `{PORT}`, `{DAEMON}`, `{FEATURE}`, `{USER}`, `{HOST}`, `{PID}`,
`{CHECKOUT_ID}`, `{ACTION}`, `{RESULT}`, `{REASON}`, `{IN_USE}`, `{TOTAL}`, `{QUEUED}`,
`{LICENSE_PATH}`, `{VERSION}`, `{BUILD}`, `{OPTIONS_PATH}`

### 8.8 Events to Log

* startup banner and loaded inventory summary
* redundant server connection attempts (if enabled)
* vendor daemon startup summaries
* each checkout result
* each return result
* queue insertion
* queue grant transition
* shutdown banner (if cleanly terminated)

---

## 9. Concurrency & Server Runtime Rules

* Service must serialize all state mutations (async lock).
* Uvicorn single-process; no multi-worker mode.

---

## 10. `lmstat-sim` Behavior (part of suite)

### 10.1 Inputs

lmstat-sim reads `-c port@server` and calls:

* `GET /v1/status` for normal output
* `GET /v1/debug/checkouts` when `-i` is requested

### 10.2 Output Format

lmstat-sim must output stable text intended for parsing in later stages.

Minimum content:

* server line: host, port
* timestamp line
* per feature summary:

  * name, total, in_use, queued, expired
* if `-i`: include per-checkout details:

  * feature, user, host, pid, checkout_id, granted_at/status

The exact text layout should be fixed and versioned as:

* `LMSTAT_SIM_FORMAT_VERSION=1` printed in header line

### 10.3 Failure behavior

If service is unreachable:

* print a one-line error to stderr
* exit with non-zero

---

## 11. Testing Specification

You require async-managed subprocess lifecycle.

### 11.1 Test Types

* Unit tests for:

  * license.dat parsing
  * queue semantics
  * idempotency behavior
  * log templating substitution
* Integration tests (mandatory):

  * spawn lmgrd wrapper as async subprocess
  * poll `/v1/health` until ready
  * run HTTP checkout/return flows
  * call `lmstat` wrapper as subprocess and assert text output contains expected lines
  * verify log file contains template-compliant events
* Functional behavior tests (mandatory):

  * checkout grants when capacity available
  * checkout denies for unknown feature
  * checkout denies when feature expired
  * queue when capacity exhausted
  * dequeue grant when a seat is returned
  * return (checkin) updates usage counters
  * denied return for unknown checkout
  * idempotent responses for repeated request_id
  * bookkeeping invariants: `in_use` never exceeds `total`, queued count matches queue size

### 11.2 Subprocess Management Requirements

* Use async subprocess APIs.
* Tests must always teardown:

  * terminate the process
  * kill process group if needed
  * wait for exit within bounded timeout

When tests exit (pass or fail), `lmgrd` subprocess must not remain running.

### 11.3 Port management

Tests must generate a `license.dat` with a free port per test run to avoid collisions.

---

## 12. Multi-daemon Support (Required)

* Multiple `DAEMON` entries supported.
* Features grouped by daemon.
* All APIs and logs must include daemon field.

Daemon remains logical (no separate daemon processes required).

---

## 13. Deferred / Non-required

* Real FlexLM protocol: not required
* Persistence/crash recovery: not required
* Security: not required

---

## Summary of Key Decisions (as implemented)

* lmstat-sim is part of the same suite and reads **lmgrd-sim API** (good for determinism)
* lmstat remains a separate CLI executable to match agent behavior
* In-memory SQLite is the runtime source of truth; monitored via API
* FlexLM-like log output is generated using your template
* Tests manage subprocesses asynchronously without special admin endpoints

---
