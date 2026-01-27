# Tasks: License Manager Core

**Input**: Design documents from `/specs/003-license-manager-core/`
**Prerequisites**: plan.md (required), spec.md (required for user stories), research.md, data-model.md, contracts/

**Tests**: Included as mandatory per "Testing Requirements" in the project spec (simulator-backed integration tests, etc.).

## Phase 1: Setup (Shared Infrastructure)

**Purpose**: Project initialization and basic structure for both Server and Agent.

- [ ] T001 Create project structure per implementation plan (src/server, src/agent, src/common, tests)
- [ ] T002 [P] Initialize Python project with Miniforge/Conda environment and dependencies (FastAPI, SQLAlchemy, Pydantic, etc.)
- [ ] T003 [P] Configure linting (ruff/flake8) and formatting (black) tools
- [ ] T004 [P] Initialize Alembic for database migrations in src/server/database/

---

## Phase 2: Foundational (Blocking Prerequisites)

**Purpose**: Core infrastructure that MUST be complete before ANY user story can be implemented.

**⚠️ CRITICAL**: No user story work can begin until this phase is complete.

- [ ] T005 Implement common protocol schemas and Ed25519 signing in src/common/protocol/
- [ ] T006 Implement Agent and ConfigSnapshot models in src/server/models/
- [ ] T007 Implement basic Agent registration logic in src/server/core/
- [ ] T008 [P] Setup FastAPI routing and WebSocket endpoint structure in src/server/api/
- [ ] T009 [P] Implement agentd daemon loop and heartbeat logic in src/agent/daemon/
- [ ] T010 [P] Configure structured logging for both Server and Agent in src/common/logging/
- [ ] T011 Create integration test harness with simulators in tests/integration/conftest.py

**Checkpoint**: Foundation ready - Agent can register and maintain a heartbeat with the Server.

---

## Phase 3: User Story 1 - Fleet Monitoring & Observability (Priority: P1) 🎯 MVP

**Goal**: Centralized dashboard showing health, connection status, and license usage.

**Independent Test**: Verify that a simulator-backed agent reports status/usage and the server correctly identifies it as "ONLINE" or "STALE".

### Tests for User Story 1

- [ ] T012 [P] [US1] Integration test for agent status reporting (Online/Stale) in tests/integration/test_fleet_status.py
- [ ] T013 [P] [US1] Integration test for license usage reporting (total/in_use) in tests/integration/test_license_usage.py

### Implementation for User Story 1

- [ ] T014 [US1] Implement license feature parsing logic in src/server/core/parsers.py
- [ ] T015 [US1] Implement Fleet View API endpoint (`GET /agents`) in src/server/api/agents.py
- [ ] T016 [US1] Implement Agent usage shipping logic (lmstat-sim integration) in src/agent/daemon/shipping.py
- [ ] T017 [US1] Implement Server heartbeat monitor (Global Default threshold) in src/server/core/monitor.py

**Checkpoint**: User Story 1 functional - Fleet status and license usage visible in API/GUI.

---

## Phase 4: User Story 2 - Remote Service Control (Priority: P2)

**Goal**: Lifecycle operations (start, stop, restart) via Server GUI.

**Independent Test**: Trigger "Restart" from Server and verify simulator process restart via logs.

### Tests for User Story 2

- [ ] T018 [P] [US2] Integration test for START/STOP/RESTART commands in tests/integration/test_control_actions.py
- [ ] T019 [P] [US2] Test for command timeout (30s wait for stale agents) in tests/integration/test_control_timeouts.py

### Implementation for User Story 2

- [ ] T020 [US2] Implement ControlRequest model and repository in src/server/models/control.py
- [ ] T021 [US2] Implement Control API endpoint (`POST /agents/{id}/control`) in src/server/api/control.py
- [ ] T022 [US2] Implement Agent command execution handler (lmgrd-sim control) in src/agent/daemon/commands.py
- [ ] T023 [US2] Implement Server-side command dispatching and result tracking (WebSockets) in src/server/core/dispatcher.py

**Checkpoint**: User Story 2 functional - Remote control of simulator processes successful.

---

## Phase 5: User Story 3 - Auditable Config Management (Priority: P3)

**Goal**: Idempotent config updates with audit trail and edit leases.

**Independent Test**: Verify that config updates require a lease and increment the revision correctly.

### Tests for User Story 3

- [ ] T024 [P] [US3] Integration test for Edit Lease acquisition and expiration in tests/integration/test_leases.py
- [ ] T025 [P] [US3] Integration test for idempotent config updates and audit log creation in tests/integration/test_config_audit.py

### Implementation for User Story 3

- [ ] T026 [US3] Implement EditLease and AuditLog models in src/server/models/governance.py
- [ ] T027 [US3] Implement Lease API (`POST /agents/{id}/lease`) and Config API (`POST /agents/{id}/config`) in src/server/api/governance.py
- [ ] T028 [US3] Implement Agent local journaling (SQLite) and reconciliation in src/agent/journaling/
- [ ] T029 [US3] Implement Server-side config validation and revision management in src/server/core/config_manager.py
- [ ] T030 [US3] Implement Automatic Chronological Merge for offline events in src/server/core/sync.py

**Checkpoint**: User Story 3 functional - Config edits are safe, auditable, and support offline sync.

---

## Phase N: Polish & Cross-Cutting Concerns

- [ ] T031 [P] Implement 1-year audit log retention cleanup task in src/server/core/retention.py
- [ ] T032 [P] Finalize relocatable packaging scripts (conda-pack) in scripts/package.sh
- [ ] T033 Run and validate all steps in quickstart.md
- [ ] T034 Code cleanup, refactoring, and final documentation update

---

## Dependencies & Execution Order

1. **Setup (Phase 1)** -> **Foundational (Phase 2)** (Linear)
2. **Foundational (Phase 2)** BLOCKS all User Stories.
3. **User Story 1 (P1)** is the MVP and should be prioritized.
4. **User Stories 2 & 3** can run in parallel with each other after US1, but US3 depends on US2's command infrastructure.

## Parallel Execution Examples

### Foundational Phase
- T008 (API structure), T009 (Agent daemon), and T010 (Logging) can run in parallel.

### User Story 1
- T012 (Tests) and T013 (Tests) can run in parallel.
- T014 (Parsers) and T015 (API) can run in parallel.

## Implementation Strategy

### MVP First
- Complete Phase 1 & 2.
- Complete Phase 3 (User Story 1).
- **Result**: A system that can monitor a fleet of agents and their license usage.

### Incremental Delivery
- Add Phase 4 for remote control capability.
- Add Phase 5 for secure, auditable configuration management and offline support.
