# Feature Specification: License Manager Technical Specification

**Feature Branch**: `001-license-tech-spec`  
**Created**: 2026-01-27  
**Status**: Draft  
**Input**: User description: "License Manager Technical Specification (v1.6)"

## User Scenarios & Testing *(mandatory)*

### User Story 1 - Admin Controls Fleet (Priority: P1)

An admin uses the Server GUI to observe fleet status and issue control actions
with clear, auditable outcomes.

**Why this priority**: Safe operational control and visibility are the primary
value of the system.

**Independent Test**: Connect one client to the server, issue a control action,
and verify the action result and audit trail are visible from the Server GUI.

**Acceptance Scenarios**:

1. **Given** a connected client with a running license service, **When** the admin
   requests a restart, **Then** the system records the request, reports the
   result, and shows an audit record tied to the admin identity.
2. **Given** a client bound to a different server identity, **When** an admin
   issues a control request, **Then** the system rejects the request and reports
   the reason without performing the action.

---

### User Story 2 - Local Operator Works Offline (Priority: P2)

A local operator uses the Client GUI to perform operations and configuration
changes while offline, and those changes sync later.

**Why this priority**: Offline capability is required for reliability in
imperfect networks and remote environments.

**Independent Test**: Disconnect a client from the server, perform a local
operation and configuration change, then reconnect and verify the changes
appear in server history.

**Acceptance Scenarios**:

1. **Given** the server is unreachable, **When** the operator updates local
   configuration and restarts the service, **Then** the system records the
   actions in a durable journal for later sync.
2. **Given** the client reconnects, **When** the journal sync completes, **Then**
   the server view reflects the updated configuration and the full action history.

---

### User Story 3 - Auditor Reviews History (Priority: P3)

An auditor reviews operational history to understand what happened, who did it,
and why decisions were made.

**Why this priority**: Auditability and explainability are required by the
system constitution.

**Independent Test**: Perform a control action and a configuration edit, then
verify the audit trail shows an end-to-end trace from intent to outcome.

**Acceptance Scenarios**:

1. **Given** a control action was executed, **When** the auditor reviews the
   history, **Then** the system shows who initiated the action, the target
   client, and the outcome.
2. **Given** a configuration change was proposed and rejected, **When** the
   auditor reviews the history, **Then** the system shows the rejection reason
   and the client’s current configuration state.

---

### Edge Cases

- What happens when a client’s journal cannot sync due to authentication errors?
- How does the system handle duplicate or replayed control requests?
- What happens when an edit lease expires mid-change submission?
- How does the system represent partial failures during multi-step operations?
- What happens when client and server clocks differ significantly?

## Requirements *(mandatory)*

### Functional Requirements

- **FR-001**: The system MUST provide a server-side view of fleet status, client
  health, and license service state.
- **FR-002**: The system MUST support control actions (start, stop, restart,
  reread, diagnostics) with clear success/failure outcomes.
- **FR-003**: The client agent MUST be the authoritative source of effective
  configuration on its host.
- **FR-004**: The server MUST store configuration snapshots reported by clients
  for visibility and history.
- **FR-005**: Each client MUST accept commands only from its bound server
  identity and reject others.
- **FR-006**: The system MUST support offline client operations with a durable
  local journal that syncs on reconnect.
- **FR-007**: Control requests MUST be idempotent and return consistent results
  for duplicate requests.
- **FR-008**: Server-initiated configuration changes MUST require a refresh,
  edit lease, and base revision match.
- **FR-009**: The server core MUST be headless, with all capabilities available
  through programmatic interfaces.
- **FR-010**: The system MUST maintain a complete audit trail for control
  actions and configuration changes.
- **FR-011**: The system MUST enforce protocol compatibility windows during
  client-server interactions.
- **FR-012**: The system MUST use the designated time-series datastore with
  configurable retention for raw records and audit history.
- **FR-013**: The release MUST support unpack-and-run deployment on RHEL7 with
  forward compatibility for RHEL8.

### Constitutional Constraints *(mandatory if applicable)*

- **CC-001**: The design MUST preserve a single source of truth for license
  state, control intent, and operational history.
- **CC-002**: The system MUST make actions traceable and derived state
  explainable before automation is allowed.
- **CC-003**: Control behavior MUST be deterministic and replayable.
- **CC-004**: Authority grants and exercises MUST be explicit and recorded.
- **CC-005**: Operator intent, ambiguity handling, and override paths MUST be
  documented and supported.
- **CC-006**: Historical records MUST remain queryable across schema evolution.
- **CC-007**: Partial failure, uncertainty, and absence of data MUST be
  representable.
- **CC-008**: The design MUST account for heterogeneous hosts, imperfect
  networks, clock skew, and legacy software.
- **CC-009**: Any irreversible decision MUST include a documented rollback or
  escape hatch.

### Key Entities *(include if feature involves data)*

- **Agent**: A client-side operator component bound to a single server identity.
- **Server Core**: The control plane responsible for orchestration and audit.
- **Config Snapshot**: The last known client configuration state with revision
  and timestamp.
- **Control Request**: A uniquely identified request with intent and outcome.
- **Journal Event**: A durable record of a local action or change while offline.
- **Edit Lease**: A time-bound concurrency token for server-initiated edits.
- **Audit Record**: The authoritative history entry linking actor, action, and
  result.

## Assumptions

- The project will maintain two GUIs: a Server GUI for fleet control and a
  Client GUI for local operations.
- Configuration changes are applied only after client confirmation.
- Data retention windows are configurable by operators and documented in policy.

## Success Criteria *(mandatory)*

### Measurable Outcomes

- **SC-001**: 95% of control actions show a definitive outcome to the initiating
  operator within 2 minutes when connectivity is available.
- **SC-002**: 100% of control actions and configuration changes appear in the
  audit trail with actor, target, and result recorded.
- **SC-003**: 90% of offline changes synchronize and appear in the server view
  within 5 minutes of reconnect.
- **SC-004**: At least 90% of operators can complete a local offline action
  without server connectivity on their first attempt.
