---

description: "Task list for License Manager Specification"
---

# Tasks: License Manager Specification

**Input**: Design documents from `/specs/001-license-manager-spec/`
**Prerequisites**: plan.md (required), spec.md (required), research.md, data-model.md, contracts/, quickstart.md

**Tests**: Included to satisfy the phase-gated test requirement in the spec.

**Organization**: Tasks are grouped by user story to enable independent implementation and testing of each story.

## Phase 1: Setup (Shared Infrastructure)

**Purpose**: Project initialization and basic structure

- [ ] T001 Create top-level directories `server/`, `client/`, `simulators/`, `tests/`
- [ ] T002 Initialize server dependencies in `server/pyproject.toml`
- [ ] T003 [P] Initialize client dependencies in `client/pyproject.toml`
- [ ] T004 [P] Initialize simulators dependencies in `simulators/pyproject.toml`
- [ ] T005 [P] Add test configuration in `tests/pytest.ini`

---

## Phase 2: Foundational (Blocking Prerequisites)

**Purpose**: Core simulator infrastructure and deterministic data sources

**⚠️ CRITICAL**: No user story work can begin until this phase is complete

- [ ] T006 Implement license grammar parser in `simulators/lmgrd-sim/license_parser.py`
- [ ] T007 Implement simulator state store in `simulators/lmgrd-sim/state.py`
- [ ] T008 Implement log templating and startup banner blocks in `simulators/lmgrd-sim/logs.py`
- [ ] T009 Implement redundancy/quorum log messages in `simulators/lmgrd-sim/logs.py`
- [ ] T010 Implement vendor daemon startup log blocks in `simulators/lmgrd-sim/logs.py`
- [ ] T011 Implement checkout/return OUT/IN log lines in `simulators/lmgrd-sim/logs.py`
- [ ] T012 Implement lmgrd-sim CLI in `simulators/lmgrd-sim/main.py`
- [ ] T013 Implement lmstat-sim output generator in `simulators/lmstat-sim/output.py`
- [ ] T014 Implement lmstat-sim CLI in `simulators/lmstat-sim/main.py`
- [ ] T015 [P] Add lmgrd-sim tests in `simulators/tests/test_lmgrd_sim.py`
- [ ] T016 [P] Add lmstat-sim tests in `simulators/tests/test_lmstat_sim.py`

**Checkpoint**: Simulator test suite passes before any client or server work begins

---

## Phase 3: User Story 1 - Fleet Visibility (Priority: P1) 🎯 MVP

**Goal**: Provide a consolidated fleet view of endpoint health, availability, usage, and expiry risk

**Independent Test**: Admin can view fleet status and per-endpoint details from API and server GUI using simulator data

### Tests for User Story 1

- [ ] T017 [P] [US1] Contract test for endpoints list in `tests/contract/test_endpoints_api.py`
- [ ] T018 [P] [US1] Integration test for fleet visibility in `tests/integration/test_fleet_visibility.py`

### Implementation for User Story 1

- [ ] T019 [P] [US1] Create endpoint model in `server/src/core/models/endpoint.py`
- [ ] T020 [P] [US1] Create license feature model in `server/src/core/models/license_feature.py`
- [ ] T021 [P] [US1] Create usage sample model in `server/src/core/models/usage_sample.py`
- [ ] T022 [US1] Implement fleet service in `server/src/core/services/fleet_service.py`
- [ ] T023 [US1] Implement endpoints API routes in `server/src/api/routes/endpoints.py`
- [ ] T024 [US1] Implement fleet GUI view in `server/src/gui/pages/fleet.py`
- [ ] T025 [US1] Add fleet GUI template in `server/src/gui/templates/fleet.html`

**Checkpoint**: User Story 1 is fully functional and independently testable

---

## Phase 4: User Story 2 - Consistent Operations with Audit (Priority: P2)

**Goal**: Provide standardized operational actions with auditable outcomes

**Independent Test**: Admin can request an action and see a recorded audit entry with outcome

### Tests for User Story 2

- [ ] T026 [P] [US2] Contract test for action requests in `tests/contract/test_actions_api.py`
- [ ] T027 [P] [US2] Integration test for audit trail in `tests/integration/test_audit_trail.py`

### Implementation for User Story 2

- [ ] T028 [P] [US2] Create operation request model in `server/src/core/models/operation_request.py`
- [ ] T029 [P] [US2] Create audit event model in `server/src/core/models/audit_event.py`
- [ ] T030 [US2] Implement operations service in `server/src/core/services/operations_service.py`
- [ ] T031 [US2] Implement audit service in `server/src/core/services/audit_service.py`
- [ ] T032 [US2] Implement actions API routes in `server/src/api/routes/actions.py`
- [ ] T033 [US2] Implement audits API routes in `server/src/api/routes/audits.py`
- [ ] T034 [US2] Implement agent action executor in `client/src/agent/actions.py`

**Checkpoint**: User Story 2 is fully functional and independently testable

---

## Phase 5: User Story 3 - Offline Local Operation (Priority: P3)

**Goal**: Enable local operations while offline with reliable synchronization

**Independent Test**: Client performs offline actions, then syncs successfully after reconnect

### Tests for User Story 3

- [ ] T035 [P] [US3] Unit test for local journal in `client/tests/test_offline_journal.py`
- [ ] T036 [P] [US3] Integration test for offline sync in `tests/integration/test_offline_sync.py`

### Implementation for User Story 3

- [ ] T037 [US3] Implement local journal store in `client/src/agent/journal.py`
- [ ] T038 [US3] Implement sync handler in `client/src/agent/sync.py`
- [ ] T039 [US3] Implement offline status UI in `client/src/gui/offline_status.py`
- [ ] T040 [US3] Implement server sync API route in `server/src/api/routes/sync.py`

**Checkpoint**: User Story 3 is fully functional and independently testable

---

## Phase 6: User Story 4 - Phased Delivery with Test Gates (Priority: P4)

**Goal**: Document and enforce phase gates before proceeding to the next component

**Independent Test**: Phase gate criteria are documented and mapped to existing test suites

### Implementation for User Story 4

- [ ] T041 [US4] Define phase gate criteria in `specs/001-license-manager-spec/phase-gates.md`
- [ ] T042 [US4] Add gate verification checklist in `tests/phase_gates/README.md`

**Checkpoint**: Phase gate documentation is complete

---

## Phase 7: Polish & Cross-Cutting Concerns

**Purpose**: Improvements that affect multiple user stories

- [ ] T043 [P] Implement usage export service in `server/src/core/services/export_service.py`
- [ ] T044 [P] Implement export API routes in `server/src/api/routes/exports.py`
- [ ] T045 [P] Contract test for export endpoints in `tests/contract/test_exports_api.py`
- [ ] T046 Implement server data persistence in `server/src/core/services/storage_service.py`
- [ ] T047 Implement database migrations in `server/src/migrations/versions/0001_init.py`
- [ ] T048 [P] Add retention policy task notes in `server/src/core/services/retention_policy.py`
- [ ] T049 Run quickstart validation checklist in `specs/001-license-manager-spec/quickstart.md`

---

## Dependencies & Execution Order

### Phase Dependencies

- **Setup (Phase 1)**: No dependencies - can start immediately
- **Foundational (Phase 2)**: Depends on Setup completion - BLOCKS all user stories
- **User Stories (Phase 3+)**: All depend on Foundational phase completion
- **Polish (Phase 7)**: Depends on all desired user stories being complete

### User Story Dependencies

- **User Story 1 (P1)**: Can start after Foundational (Phase 2)
- **User Story 2 (P2)**: Can start after Foundational (Phase 2)
- **User Story 3 (P3)**: Can start after Foundational (Phase 2)
- **User Story 4 (P4)**: Can start after User Stories 1-3 complete

### Within Each User Story

- Tests must be written and fail before implementation
- Models before services
- Services before endpoints
- Core implementation before integration

### Parallel Opportunities

- All Setup tasks marked [P] can run in parallel
- Simulator tests in Phase 2 can run in parallel
- Model tasks marked [P] can run in parallel within each story
- Contract and integration tests marked [P] can run in parallel per story

---

## Parallel Example: User Story 1

```bash
# Launch contract + integration tests together:
Task: "Contract test for endpoints list in tests/contract/test_endpoints_api.py"
Task: "Integration test for fleet visibility in tests/integration/test_fleet_visibility.py"

# Launch models together:
Task: "Create endpoint model in server/src/core/models/endpoint.py"
Task: "Create license feature model in server/src/core/models/license_feature.py"
Task: "Create usage sample model in server/src/core/models/usage_sample.py"
```

---

## Implementation Strategy

### MVP First (User Story 1 Only)

1. Complete Phase 1: Setup
2. Complete Phase 2: Foundational (simulators)
3. Complete Phase 3: User Story 1
4. **STOP and VALIDATE**: Test User Story 1 independently

### Incremental Delivery

1. Complete Setup + Foundational → Foundation ready
2. Add User Story 1 → Test independently → Demo
3. Add User Story 2 → Test independently → Demo
4. Add User Story 3 → Test independently → Demo
5. Add User Story 4 → Document phase gates → Demo
6. Complete Polish tasks

---

## Notes

- [P] tasks = different files, no dependencies
- [Story] label maps task to specific user story for traceability
- Each user story should be independently completable and testable
- Verify tests fail before implementing
- Stop at any checkpoint to validate story independently
