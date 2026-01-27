# Research: License Manager Technical Specification

## Decision: Python 3.11 for server and agent runtime

**Rationale**: Python is a boring, well-supported choice and aligns with the
portable miniforge runtime in the packaging guidance. It is widely deployed on
RHEL systems and lowers operator friction.

**Alternatives considered**: Go (static binaries, low ops overhead), Java/Kotlin
(stable ecosystem but heavier runtime).

## Decision: FastAPI + Pydantic for API layer

**Rationale**: Provides a stable, explicit schema model and structured input
validation while keeping dependencies modest.

**Alternatives considered**: Flask (less structured), Django (heavier stack).

## Decision: TimescaleDB for server storage, SQLite for agent journal

**Rationale**: TimescaleDB satisfies time-series and audit requirements; SQLite
provides a durable local journal for offline operations with minimal complexity.

**Alternatives considered**: Plain PostgreSQL (no time-series optimizations),
append-only flat files (harder to query and compact).

## Decision: Local journaling uses append-only entries with idempotency keys

**Rationale**: Append-only journaling preserves auditability and enables replay.
Idempotency keys allow safe retries during reconnect and flaky networks.

**Alternatives considered**: In-memory queues only (lose data on crash), full
state-only sync (loses intent and history).

## Decision: Reconnect sync uses at-least-once delivery with server de-dup

**Rationale**: At-least-once guarantees delivery without silent loss; server
de-dup by request/change ID ensures idempotent outcomes.

**Alternatives considered**: Exactly-once semantics (complex), last-write-wins
without event history (hides conflicts).

## Decision: Edit leases use TTL and single active lease per client

**Rationale**: Lease TTL reduces stale-lock risk; single lease prevents
concurrent edits. Rejections are explicit and audit logged.

**Alternatives considered**: Optimistic concurrency without leases (higher
conflict rate), manual operator coordination (error-prone).

## Decision: GUIs are PyQt6 desktop applications

**Rationale**: Desktop GUIs provide a consistent local operator experience on
RHEL environments and avoid browser dependencies.

**Alternatives considered**: Web UIs (lighter deployment), Electron (heavier
footprint).

## Decision: Deterministic lmgrd and lmstat simulators are required

**Rationale**: Simulators provide replayable fixtures for parser, control, and
offline workflows while keeping tests deterministic and auditable.

**Alternatives considered**: Manual log capture only (non-deterministic), live
vendor tools in tests (fragile and environment-dependent).
