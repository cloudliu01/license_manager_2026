# Implementation Plan: License Manager Specification

**Branch**: `001-license-manager-spec` | **Date**: 2026-01-27 | **Spec**: specs/001-license-manager-spec/spec.md
**Input**: Feature specification from `/specs/001-license-manager-spec/spec.md`

**Note**: This template is filled in by the `/speckit.plan` command. See `.specify/templates/commands/plan.md` for the execution workflow.

## Summary

Deliver a phased, test-gated license management system starting with deterministic simulators, then client, server, database, and GUIs, ensuring fleet visibility, auditable operations, offline capability, and JSON export with support for up to 100 managed endpoints.

## Technical Context

<!--
  ACTION REQUIRED: Replace the content in this section with the technical details
  for the project. The structure here is presented in advisory capacity to guide
  the iteration process.
-->

**Language/Version**: Python 3.11  
**Primary Dependencies**: FastAPI, Pydantic, SQLAlchemy, psycopg, Alembic, PyQt6, Jinja2, HTMX  
**Storage**: TimescaleDB (PostgreSQL) for server data; SQLite for client journal  
**Testing**: pytest  
**Target Platform**: Linux server (RHEL7 target) with desktop client GUI  
**Project Type**: Web application (backend + frontend) with desktop client  
**Performance Goals**: Fleet view available within 30 seconds for 95% of attempts; operational actions return outcome within 2 minutes  
**Constraints**: Offline-capable clients; best-effort availability (no SLA); 24-month retention for usage and audit records  
**Scale/Scope**: Up to 100 managed endpoints

## Constitution Check

*GATE: Must pass before Phase 0 research. Re-check after Phase 1 design.*

- Client-authoritative config respected in requirements. Initial: Pass. Post-design: Pass.
- One active server per client enforced in requirements. Initial: Pass. Post-design: Pass.
- Explicit authority boundaries maintained (GUIs propose, agent executes). Initial: Pass. Post-design: Pass.
- Deterministic + auditable operations required by spec. Initial: Pass. Post-design: Pass.
- Offline capability with clear reconciliation required. Initial: Pass. Post-design: Pass.
- Idempotency and safety prioritized. Initial: Pass. Post-design: Pass.
- Observability and failure states required. Initial: Pass. Post-design: Pass.
- Portable, unpack-and-run delivery preserved. Initial: Pass. Post-design: Pass.
- History preserved via audit records and retention. Initial: Pass. Post-design: Pass.

## Project Structure

### Documentation (this feature)

```text
specs/001-license-manager-spec/
├── plan.md              # This file (/speckit.plan command output)
├── research.md          # Phase 0 output (/speckit.plan command)
├── data-model.md        # Phase 1 output (/speckit.plan command)
├── quickstart.md        # Phase 1 output (/speckit.plan command)
├── contracts/           # Phase 1 output (/speckit.plan command)
└── tasks.md             # Phase 2 output (/speckit.tasks command - NOT created by /speckit.plan)
```

### Source Code (repository root)
<!--
  ACTION REQUIRED: Replace the placeholder tree below with the concrete layout
  for this feature. Delete unused options and expand the chosen structure with
  real paths (e.g., apps/admin, packages/something). The delivered plan must
  not include Option labels.
-->

```text
server/
├── src/
│   ├── core/
│   ├── api/
│   ├── gui/
│   └── migrations/
└── tests/

client/
├── src/
│   ├── agent/
│   └── gui/
└── tests/

simulators/
├── lmgrd-sim/
├── lmstat-sim/
└── tests/

tests/
```

**Structure Decision**: Plan for separate server, client, and simulators directories with shared top-level tests for cross-component validation.

## Complexity Tracking

No constitution violations requiring justification.
