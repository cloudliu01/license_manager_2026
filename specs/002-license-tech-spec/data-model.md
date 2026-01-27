# Data Model: License Manager Technical Specification

## Entities

### Agent

- **Fields**: agent_id, hostname, server_id, server_addr, protocol_version,
  software_version, last_seen_at, sync_state
- **Validation**: agent_id and server_id are UUIDs; server_id is immutable
  without explicit rebind; sync_state is one of UNKNOWN/IN_SYNC/CLIENT_AHEAD/
  SERVER_STALE.

### ConfigSnapshot

- **Fields**: snapshot_id, agent_id, config_rev, config_hash, payload,
  reported_at, source (client)
- **Validation**: config_rev is monotonic per agent; config_hash is derived from
  normalized config; payload stored as raw + structured forms.

### ControlRequest

- **Fields**: request_id, agent_id, action_type, initiated_by, created_at,
  idempotency_key, status
- **Validation**: request_id is UUID; idempotency_key must be unique per agent
  within retention window; status is PENDING/SENT/ACKED/FAILED.

### ControlResult

- **Fields**: result_id, request_id, agent_id, status, details, recorded_at
- **Validation**: request_id must exist; status is SUCCESS/REJECTED/FAILED.

### EditLease

- **Fields**: lease_id, agent_id, issued_at, expires_at, issued_to_user
- **Validation**: only one active lease per agent; expires_at > issued_at.

### ConfigChangeRequest

- **Fields**: change_id, lease_id, agent_id, base_config_rev, change_set,
  requested_by, requested_at, status
- **Validation**: base_config_rev must match agent current config_rev at apply
  time; change_id is idempotent.

### JournalEvent

- **Fields**: event_id, agent_id, event_time, action_type, change_id,
  config_rev_before, config_rev_after, payload, upload_status
- **Validation**: event_id is UUID; upload_status is PENDING/SENT/ACKED.

### AuditRecord

- **Fields**: audit_id, actor_id, actor_type, action_type, target_id,
  correlation_id, outcome, recorded_at
- **Validation**: correlation_id links to request/change; outcome is explicit.

### RawRecord

- **Fields**: record_id, agent_id, record_type, payload, recorded_at
- **Validation**: record_type is LMSTAT/LMGRD_LOG/DIAGNOSTIC.

### LmstatSample

- **Fields**: sample_id, agent_id, collected_at, license_usage, server_status
- **Validation**: collected_at is time-series key; values derive from raw record.

## Relationships

- Agent 1..N ConfigSnapshot
- Agent 1..N JournalEvent
- Agent 1..N ControlRequest; ControlRequest 1..1 ControlResult
- Agent 1..N EditLease; EditLease 1..N ConfigChangeRequest
- ConfigChangeRequest 0..1 ControlResult (apply result)
- AuditRecord links to ControlRequest or ConfigChangeRequest via correlation_id
- RawRecord feeds LmstatSample and AuditRecord

## State Transitions

- **Sync State**: UNKNOWN → IN_SYNC/CLIENT_AHEAD/SERVER_STALE; reconciles on
  connect and snapshot upload.
- **ControlRequest**: PENDING → SENT → ACKED/FAILED.
- **ConfigChangeRequest**: PROPOSED → APPLIED/REJECTED/FAILED.
- **JournalEvent**: PENDING → SENT → ACKED.
