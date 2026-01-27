# Implementation Plan: License Manager Core

**Branch**: `003-license-manager-core` | **Date**: 2026-01-27 | **Spec**: [/specs/003-license-manager-core/spec.md](spec.md)
**Input**: Feature specification from `/specs/003-license-manager-core/spec.md`

## Summary

Implement the core control plane for the License Manager system, enabling centralized observability and management of distributed license agents. The technical approach involves a FastAPI-based Server Core, a TimescaleDB backend for telemetry and audit logs, and a secure communication protocol with client agents using signed JSON payloads.

## Technical Context

**Language/Version**: Python 3.11 (via relocatable Miniforge)
**Primary Dependencies**: FastAPI, SQLAlchemy/Alembic, Pydantic, `cryptography` (for signing), `psycopg2-binary`
**Storage**: TimescaleDB (PostgreSQL-compatible)
**Testing**: pytest, simulator-backed integration tests
**Target Platform**: Linux (RHEL 7/8)
**Project Type**: Single project (Monorepo-style structure)
**Performance Goals**: 100+ concurrent agents; < 2s dashboard latency; reconciliation of 1000 events < 60s
**Constraints**: Offline-capable agent journaling; relocatable installation (no `/opt/` or `/usr/local/` requirements)
**Scale/Scope**: ~100 agents per server; 1 year audit retention

## Constitution Check

*GATE: Must pass before Phase 0 research. Re-check after Phase 1 design.*

- [x] **Client-authoritative config**: Agent is the source of truth; Server stores snapshots and manages revisions.
- [x] **One active server per client**: Agent strictly bound to a single `server_id`.
- [x] **Explicit authority boundaries**: GUI proposes via Server; Server arbitrates via leases; Agent executes.
- [x] **Deterministic + auditable operations**: Every administrative action is logged with user attribution and 1-year retention.
- [x] **Offline capability without deception**: Agent journals local actions; Server performs automatic chronological merge upon reconnection.
- [x] **Idempotency and safety over speed**: All control actions and config updates use revision checks and are idempotent.
- [x] **Observability before automation**: Dashboard provides fleet health and license usage before any automated control.
- [x] **Failure is first-class**: Timed wait (30s) for stale agents and explicit failure reporting in GUI.
- [x] **Portable without fragility**: Unpack-and-run relocatable layout specified.
- [x] **Evolve without erasing history**: 1-year retention for structured audit logs.

## Project Structure

### Documentation (this feature)

```text
specs/003-license-manager-core/
├── plan.md              # This file
├── research.md          # Phase 0 output
├── data-model.md        # Phase 1 output
├── quickstart.md        # Phase 1 output
├── contracts/           # Phase 1 output
└── tasks.md             # Phase 2 output
```

### Source Code (repository root)

```text
src/
├── server/
│   ├── api/             # FastAPI routes
│   ├── core/            # Business logic (leases, audits)
│   ├── models/          # SQLAlchemy entities
│   └── database/        # DB migrations and session management
├── agent/
│   ├── daemon/          # agentd core logic
│   ├── journaling/      # SQLite journal management
│   └── protocol/        # Signed JSON communication
└── common/
    ├── protocol/        # Shared schemas and crypto
    └── logging/         # Structured logging config

tests/
├── integration/         # Simulator-backed tests
├── unit/
└── contract/            # API schema validation
```

**Structure Decision**: Single repository containing both Server and Agent code to ensure protocol and model synchronization during the core implementation phase.

## Complexity Tracking

| Violation | Why Needed | Simpler Alternative Rejected Because |
|-----------|------------|-------------------------------------|
| None | N/A | N/A |