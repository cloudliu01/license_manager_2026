# Feature Specification: License Manager Core

**Feature Branch**: `003-license-manager-core`  
**Created**: 2026-01-27  
**Status**: Draft  
**Input**: User description: "Implement the License Manager Core control plane as described in spec.md"

## Clarifications

### Session 2026-01-27

- Q: How should the server reconcile offline events during sync? → A: Automatic Chronological Merge
- Q: What is the default retention period for the structured audit log? → A: 1 Year
- Q: How to handle Control Requests for Stale agents? → A: Timed Wait (30s) before failure
- Q: Behavior on Edit Lease expiration? → A: Revoke & Prevent (Submission fails)
- Q: How is the Heartbeat Threshold configured? → A: Global Default (e.g., 3x interval)

## User Scenarios & Testing *(mandatory)*

### User Story 1 - Fleet Monitoring & Observability (Priority: P1)

As a license administrator, I want a centralized dashboard that shows the health, connection status, and license usage of all agents across the organization so I can proactively identify issues.

**Why this priority**: Essential for the core mission of "control + observability". Without monitoring, administration is reactive and blind.

**Independent Test**: Can be tested by connecting a simulator-backed agent to the server and verifying that the dashboard correctly displays the agent's status, features, and current usage seats without any manual intervention.

**Acceptance Scenarios**:

1. **Given** a running License Manager Server and one connected Agent, **When** the Agent reports its state, **Then** the Server GUI shows the Agent as "Online" with accurate feature counts.
2. **Given** an Agent that has lost connectivity, **When** the Global Default heartbeat threshold (e.g., 3 missed heartbeats) is exceeded, **Then** the Server GUI marks the Agent as "Stale".

---

### User Story 2 - Remote Service Control (Priority: P2)

As a license administrator, I want to perform lifecycle operations (start, stop, restart) on license services via the Server GUI so I can manage the fleet without direct SSH access to client machines.

**Why this priority**: High operational value; reduces the need for manual login and specialized knowledge for each client host.

**Independent Test**: Can be tested by triggering a "Restart" action from the Server GUI and verifying (via simulator logs) that the `lmgrd-sim` process was terminated and restarted with the correct parameters.

**Acceptance Scenarios**:

1. **Given** a running license service on an Agent, **When** the Admin clicks "Restart" in the GUI, **Then** the Agent executes the restart and reports the new process ID and status.
2. **Given** a failed restart operation, **When** the Agent encounters an error, **Then** the Server GUI displays the specific error message and diagnostic context.

---

### User Story 3 - Auditable Config Management (Priority: P3)

As a license administrator, I want to update license configurations (port settings, asset paths) with an audit trail and guaranteed idempotency so I can safely evolve the system state.

**Why this priority**: Crucial for "Deterministic + auditable operations" and "Idempotency" invariants.

**Independent Test**: Can be tested by submitting the same configuration update twice and verifying that the Agent revision only increments once and the audit log shows both the attempt and the redundant status.

**Acceptance Scenarios**:

1. **Given** a target Agent, **When** an Admin acquires an edit lease and submits a new configuration, **Then** the Agent applies the change and increments its configuration revision.
2. **Given** a submitted change with an outdated base revision, **When** the Agent receives the request, **Then** it rejects the change to prevent "split-brain" or lost updates.

---

### Edge Cases

- **Offline Sync Reconcile**: Server MUST perform an automatic chronological merge of the Agent's offline event journal into the global audit log upon reconnection, interleaving events based on their original local timestamp.
- **Network Partition during Control**: If a control request is issued to a Stale or disconnected Agent, the Server MUST wait for 30 seconds for the Agent to reconnect before failing the request with a timeout error. Commands issued just as an agent goes offline will remain in a "Pending" state during this window.

### Assumptions & Dependencies

- **Assumption**: User authentication for the Server GUI will follow standard enterprise patterns (e.g., OIDC/LDAP) and is considered a prerequisite for administrative actions.
- **Assumption**: The target infrastructure allows outgoing connections from Agents to the Server API (default port 443/8080).
- **Dependency**: Requires a functional TimescaleDB instance for telemetry and audit storage.
- **Dependency**: Relies on the availability of the `agentd` binary on client hosts for local orchestration.

## Requirements *(mandatory)*

### Functional Requirements

- **FR-001**: System MUST maintain a registry of Agents with their unique `server_id` and binding.
- **FR-002**: System MUST display real-time (or near real-time) status of license features including `total` and `in_use` counts.
- **FR-003**: System MUST support idempotent lifecycle commands: START, STOP, RESTART, REREAD.
- **FR-004**: System MUST implement a "Lease" mechanism for configuration edits to prevent concurrent conflicting changes. If a lease expires before submission, the Server MUST reject the change request, requiring the administrator to acquire a new lease.
- **FR-005**: System MUST store a full audit trail of all administrative actions, including the initiator, action, timestamp, and result.
- **FR-007**: System MUST retain structured audit logs for a default period of 1 year.
- **FR-006**: System MUST support "Client-authoritative" configuration where the agent's reported state is the source of truth.

### Key Entities *(include if feature involves data)*

- **Agent**: Represents a client host; attributes include `id`, `hostname`, `status`, `config_rev`.
- **Config Snapshot**: A record of the configuration state at a point in time; attributes include `rev`, `hash`, `payload`.
- **Control Request**: A command sent to an agent; attributes include `type`, `status`, `initiator_id`.
- **Audit Log Entry**: A record of a state change or administrative action.

## Success Criteria *(mandatory)*

### Measurable Outcomes

- **SC-001**: Admins can view the status of 100+ agents in a single dashboard with under 2 seconds of latency.
- **SC-002**: 100% of state-changing operations are recorded in the audit log with valid user attribution.
- **SC-003**: 0% of configuration updates result in an inconsistent state due to concurrent edits (guaranteed by lease mechanism).
- **SC-004**: Users can successfully reconcile offline journals within 60 seconds of reconnection for up to 1000 logged events.