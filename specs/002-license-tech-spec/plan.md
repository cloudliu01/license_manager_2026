# Implementation Plan: License Manager Technical Specification

**Branch**: `002-license-tech-spec` | **Date**: 2026-01-27 | **Spec**: /Users/liulizhuang/GitHubProjects/license_manager_2026/specs/002-license-tech-spec/spec.md
**Input**: Feature specification from `/specs/002-license-tech-spec/spec.md`

**Note**: This template is filled in by the `/speckit.plan` command. See `.specify/templates/commands/plan.md` for the execution workflow.

## Summary

Deliver a control-plane system with a headless server core, a client agent, and
two GUIs (server + local) that support offline-capable operations, idempotent
control requests, edit leases, and TimescaleDB-backed observability with
portable RHEL7-compatible packaging.

## Technical Context

**Language/Version**: Python 3.11 (miniforge runtime for portable packaging)  
**Primary Dependencies**: FastAPI, Pydantic, SQLAlchemy, psycopg, Alembic, PyQt6  
**Storage**: TimescaleDB (PostgreSQL) for server data; SQLite for agent journal  
**Testing**: pytest  
**Target Platform**: Linux servers and clients (RHEL7 baseline, RHEL8 compatible)  
**Project Type**: Multi-service (server core + agent) with two desktop GUIs  
**Performance Goals**: Support 1,000 agents; 1-minute sampling; 100 control requests/min  
**Constraints**: Offline-capable client operations, idempotent requests, headless server core, auditable history, unpack-and-run deployment  
**Constraints**: GUI is a replaceable client; future Java GUI must work via the same APIs without server/agent changes  
**Constraints**: Deterministic lmgrd and lmstat simulators required for replayable fixtures and parser coverage  
**Scale/Scope**: Two GUIs, one server core, one agent, single control-plane instance per fleet

## Constitution Check

*GATE: Must pass before Phase 0 research. Re-check after Phase 1 design.*

- [x] Control plane focus: global correctness over local convenience; system-level view.
- [x] Single source of truth defined for license state, control intent, history.
- [x] Observability before automation: actions traceable; derived state explainable.
- [x] Determinism over cleverness: behavior replayable and auditable.
- [x] Authority boundaries explicit: no inferred intent or implicit escalation.
- [x] Humans are part of the system: operator intent/arbitration/override supported.
- [x] History preserved: schema evolution keeps meaning; records remain queryable.
- [x] Failure is first-class: partial failure, uncertainty, and absence represented.
- [x] Infrastructure reality accounted for: heterogeneity, networks, clock skew, legacy.
- [x] Boring tech preferred; novelty justified by reduced operational risk.
- [x] Portability without fragility: errors surfaced; guarantees not weakened.
- [x] Irreversible decisions have rollback or escape hatches.
- [x] Constitution above spec: exceptions documented with explicit waivers.

Post-design re-check: PASS (no waivers required).

## Project Structure

### Documentation (this feature)

```text
specs/002-license-tech-spec/
├── plan.md              # This file (/speckit.plan command output)
├── research.md          # Phase 0 output (/speckit.plan command)
├── data-model.md        # Phase 1 output (/speckit.plan command)
├── quickstart.md        # Phase 1 output (/speckit.plan command)
├── contracts/           # Phase 1 output (/speckit.plan command)
└── tasks.md             # Phase 2 output (/speckit.tasks command - NOT created by /speckit.plan)
```

### Source Code (repository root)

```text
server/
├── src/
│   ├── api/
│   ├── models/
│   ├── services/
│   └── gui/
└── tests/

agent/
├── src/
│   ├── api/
│   ├── models/
│   ├── services/
│   └── gui/
└── tests/

shared/
└── src/

tests/
├── contract/
├── integration/
└── unit/
```

**Structure Decision**: Multi-service layout for server core and agent, each
with its own API, services, and desktop GUI modules. Shared libraries live under
`shared/` for protocol and domain types.

## Complexity Tracking

> **Fill ONLY if Constitution Check has violations that must be justified**
