---

description: "Task list template for feature implementation"
---

# Tasks: License Manager Technical Specification

**Input**: Design documents from `/specs/002-license-tech-spec/`
**Prerequisites**: plan.md (required), spec.md (required for user stories), research.md, data-model.md, contracts/

**Tests**: No explicit test tasks requested in the feature specification.

**Organization**: Tasks are grouped by user story to enable independent implementation and testing of each story.

## Format: `[ID] [P?] [Story] Description`

- **[P]**: Can run in parallel (different files, no dependencies)
- **[Story]**: Which user story this task belongs to (e.g., US1, US2, US3)
- Include exact file paths in descriptions

## Path Conventions

- **Multi-service**: `server/src/`, `agent/src/`, `shared/src/`

## Phase 1: Setup (Shared Infrastructure)

**Purpose**: Project initialization and basic structure

- [ ] T001 Create server configuration module in server/src/config.py
- [ ] T002 Create agent configuration module in agent/src/config.py
- [ ] T003 Create shared protocol module in shared/src/protocol.py
- [ ] T004 Create server entrypoint in server/src/main.py
- [ ] T005 Create agent entrypoint in agent/src/main.py
- [ ] T006 [P] Create server dependency manifest in server/pyproject.toml
- [ ] T007 [P] Create agent dependency manifest in agent/pyproject.toml
- [ ] T008 [P] Create shared dependency manifest in shared/pyproject.toml

---

## Phase 2: Foundational (Blocking Prerequisites)

**Purpose**: Core infrastructure that MUST be complete before ANY user story can be implemented

**⚠️ CRITICAL**: No user story work can begin until this phase is complete

- [ ] T009 Initialize Alembic config in server/alembic.ini
- [ ] T010 Configure Alembic env in server/src/db/migrations/env.py
- [ ] T011 Define SQLAlchemy base and session in server/src/db/session.py
- [ ] T012 [P] Define shared enums in shared/src/models/enums.py
- [ ] T013 [P] Create Agent model in shared/src/models/agent.py
- [ ] T014 [P] Create ConfigSnapshot model in shared/src/models/config_snapshot.py
- [ ] T015 [P] Create ControlRequest model in shared/src/models/control_request.py
- [ ] T016 [P] Create ControlResult model in shared/src/models/control_result.py
- [ ] T017 [P] Create JournalEvent model in shared/src/models/journal_event.py
- [ ] T018 [P] Create EditLease model in shared/src/models/edit_lease.py
- [ ] T019 Implement protocol versioning helpers in shared/src/protocol/versioning.py
- [ ] T020 Implement auth identity contracts in shared/src/auth/identity.py
- [ ] T021 Implement server auth middleware in server/src/api/middleware/auth.py
- [ ] T022 Implement agent auth validator in agent/src/services/auth_service.py
- [ ] T023 Implement audit logging service in server/src/services/audit_service.py
- [ ] T024 Implement server idempotency registry in server/src/services/idempotency_service.py
- [ ] T025 Implement agent idempotency cache in agent/src/services/idempotency_cache.py
- [ ] T026 Implement agent journal store in agent/src/services/journal_store.py
- [ ] T027 Implement server sync ingestion service in server/src/services/sync_ingest.py
- [ ] T028 Implement server error middleware in server/src/api/middleware/errors.py
- [ ] T029 Implement agent error middleware in agent/src/api/middleware/errors.py
- [ ] T030 Implement lmgrd simulator core in tests/simulators/lmgrd_simulator.py
- [ ] T031 Implement lmstat simulator generator in tests/simulators/lmstat_simulator.py
- [ ] T032 Add simulator fixtures in tests/fixtures/simulator/
- [ ] T033 Document rollback/escape hatches in specs/002-license-tech-spec/rollback.md

**Checkpoint**: Foundation ready - user story implementation can now begin in parallel

---

## Phase 3: User Story 1 - Admin Controls Fleet (Priority: P1) 🎯 MVP

**Goal**: Provide fleet visibility and safe control actions with auditability in the Server GUI

**Independent Test**: Connect one client, issue a control action, and verify status and audit entries in the Server GUI

### Implementation for User Story 1

- [ ] T034 [US1] Implement agent status service in server/src/services/agent_status_service.py
- [ ] T035 [US1] Implement control request service in server/src/services/control_request_service.py
- [ ] T036 [US1] Implement command dispatch queue in server/src/services/command_dispatch.py
- [ ] T037 [US1] Add agent status and control routes in server/src/api/routes/agents.py
- [ ] T038 [US1] Add control request routes in server/src/api/routes/control_requests.py
- [ ] T039 [US1] Add command pull route in server/src/api/routes/commands.py
- [ ] T040 [US1] Implement control executor in agent/src/services/control_executor.py
- [ ] T041 [US1] Add agent command handling route in agent/src/api/routes/commands.py
- [ ] T042 [US1] Build Server GUI main window in server/src/gui/main_window.py
- [ ] T043 [US1] Wire control actions panel in server/src/gui/control_panel.py

**Checkpoint**: User Story 1 is fully functional and testable independently

---

## Phase 4: User Story 2 - Local Operator Works Offline (Priority: P2)

**Goal**: Enable offline local operations with durable journaling and reconnect sync

**Independent Test**: Perform a local operation offline, reconnect, and verify server history reflects the change

### Implementation for User Story 2

- [ ] T044 [US2] Implement local config service with revisioning in agent/src/services/config_service.py
- [ ] T045 [US2] Implement config snapshot reporter in agent/src/services/config_snapshot.py
- [ ] T046 [US2] Implement sync client in agent/src/services/sync_client.py
- [ ] T047 [US2] Add server sync route in server/src/api/routes/sync.py
- [ ] T048 [US2] Add local agent API routes in agent/src/api/routes/local.py
- [ ] T049 [US2] Implement rebind workflow in agent/src/services/rebind_service.py
- [ ] T050 [US2] Build Client GUI main window in agent/src/gui/main_window.py
- [ ] T051 [US2] Add offline status view in agent/src/gui/offline_status.py

**Checkpoint**: User Story 2 is independently functional with offline sync

---

## Phase 5: User Story 3 - Auditor Reviews History (Priority: P3)

**Goal**: Provide audit views that trace intent, outcomes, and rejection reasons

**Independent Test**: Execute a control and config change, then verify audit filters and detail view show outcomes

### Implementation for User Story 3

- [ ] T052 [US3] Implement audit query service in server/src/services/audit_query.py
- [ ] T053 [US3] Add audit query route in server/src/api/routes/audit.py
- [ ] T054 [US3] Build Server GUI audit view in server/src/gui/audit_view.py
- [ ] T055 [US3] Add audit detail dialog in server/src/gui/audit_detail.py

**Checkpoint**: All user stories are independently functional

---

## Phase N: Polish & Cross-Cutting Concerns

**Purpose**: Improvements that affect multiple user stories

- [ ] T056 [P] Update quickstart for final behavior in specs/002-license-tech-spec/quickstart.md
- [ ] T057 [P] Record quickstart validation notes in specs/002-license-tech-spec/quickstart-validation.md
- [ ] T058 [P] Add security hardening notes in specs/002-license-tech-spec/security-notes.md
- [ ] T059 [P] Add performance notes in specs/002-license-tech-spec/performance-notes.md

---

## Dependencies & Execution Order

### Phase Dependencies

- **Setup (Phase 1)**: No dependencies - can start immediately
- **Foundational (Phase 2)**: Depends on Setup completion - BLOCKS all user stories
- **User Stories (Phase 3+)**: All depend on Foundational phase completion
  - User stories can then proceed in parallel (if staffed)
  - Or sequentially in priority order (P1 → P2 → P3)
- **Polish (Final Phase)**: Depends on all desired user stories being complete

### User Story Dependencies

- **User Story 1 (P1)**: Can start after Foundational (Phase 2) - No dependencies on other stories
- **User Story 2 (P2)**: Can start after Foundational (Phase 2) - Independent but uses shared services
- **User Story 3 (P3)**: Can start after Foundational (Phase 2) - Depends on audit data produced by US1/US2

### Within Each User Story

- Models before services
- Services before endpoints
- Core implementation before GUI wiring
- Story complete before moving to next priority

### Parallel Opportunities

- All Setup tasks marked [P] can run in parallel
- Shared model tasks in Foundational phase can run in parallel
- Server and agent tasks in different modules can run in parallel

---

## Parallel Example: User Story 1

```bash
Task: "Implement agent status service in server/src/services/agent_status_service.py"
Task: "Implement control request service in server/src/services/control_request_service.py"
Task: "Build Server GUI main window in server/src/gui/main_window.py"
```

---

## Parallel Example: User Story 2

```bash
Task: "Implement local config service with revisioning in agent/src/services/config_service.py"
Task: "Add local agent API routes in agent/src/api/routes/local.py"
Task: "Build Client GUI main window in agent/src/gui/main_window.py"
```

---

## Parallel Example: User Story 3

```bash
Task: "Implement audit query service in server/src/services/audit_query.py"
Task: "Build Server GUI audit view in server/src/gui/audit_view.py"
```

---

## Implementation Strategy

### MVP First (User Story 1 Only)

1. Complete Phase 1: Setup
2. Complete Phase 2: Foundational (CRITICAL - blocks all stories)
3. Complete Phase 3: User Story 1
4. **STOP and VALIDATE**: Test User Story 1 independently
5. Deploy/demo if ready

### Incremental Delivery

1. Complete Setup + Foundational → Foundation ready
2. Add User Story 1 → Test independently → Deploy/Demo (MVP!)
3. Add User Story 2 → Test independently → Deploy/Demo
4. Add User Story 3 → Test independently → Deploy/Demo
5. Each story adds value without breaking previous stories

### Parallel Team Strategy

With multiple developers:

1. Team completes Setup + Foundational together
2. Once Foundational is done:
   - Developer A: User Story 1
   - Developer B: User Story 2
   - Developer C: User Story 3
3. Stories complete and integrate independently

---

## Notes

- [P] tasks = different files, no dependencies
- [Story] label maps task to specific user story for traceability
- Each user story should be independently completable and testable
- Avoid: vague tasks, same file conflicts, cross-story dependencies that break independence
