# Data Model

## Entities

### Managed Endpoint

- **Represents**: A license server instance tracked by host and port.
- **Key fields**: id, host, port, display_name, status, last_reported_at, server_binding_id.
- **Relationships**: Has many Usage Samples, Operation Requests, Audit Events.
- **Validation rules**: `host + port` must be unique; status must be one of `healthy`, `degraded`, `stale`, `unknown`.

### License Feature

- **Represents**: A licensable capability exposed by a managed endpoint.
- **Key fields**: id, endpoint_id, name, total_count, in_use_count, expiry_date, vendor_tag.
- **Relationships**: Belongs to Managed Endpoint; appears in Usage Samples.
- **Validation rules**: `name` required; counts are non-negative integers.

### Usage Sample

- **Represents**: A time-stamped snapshot of usage for a managed endpoint.
- **Key fields**: id, endpoint_id, captured_at, raw_payload_ref, parsed_summary.
- **Relationships**: Belongs to Managed Endpoint; contains multiple License Feature records for the snapshot.
- **Validation rules**: `captured_at` required; `endpoint_id` required.

### Configuration Snapshot

- **Represents**: Effective client configuration recorded at a point in time.
- **Key fields**: id, client_id, config_rev, config_hash, captured_at, payload_ref.
- **Relationships**: Belongs to a Client/Endpoint; referenced by Audit Events.
- **Validation rules**: `config_rev` monotonic per client.

### Operation Request

- **Represents**: A requested operational action and its outcome.
- **Key fields**: id, endpoint_id, action_type, requested_by, requested_at, status, result_summary.
- **Relationships**: Belongs to Managed Endpoint; links to Audit Events.
- **Validation rules**: `action_type` in allowed set; `status` in `requested`, `in_progress`, `succeeded`, `failed`.

### Audit Event

- **Represents**: An immutable record of who initiated a change, when, and the resulting state.
- **Key fields**: id, actor_id, actor_type, action, occurred_at, endpoint_id, outcome, config_snapshot_id.
- **Relationships**: Belongs to Managed Endpoint; references Configuration Snapshot when applicable.
- **Validation rules**: `occurred_at` required; `actor_id` required.

### Local Journal Entry

- **Represents**: A local offline action queued for synchronization.
- **Key fields**: id, endpoint_id, action_type, created_at, status, sync_attempts.
- **Relationships**: Belongs to Managed Endpoint; may map to Operation Request after sync.
- **Validation rules**: `status` in `pending`, `synced`, `failed`.

## State Transitions

- **Managed Endpoint status**: `unknown` → `healthy` or `degraded`; `healthy` → `stale` on missed reports; `stale` → `healthy` on new report.
- **Operation Request**: `requested` → `in_progress` → `succeeded` | `failed`.
- **Local Journal Entry**: `pending` → `synced` | `failed`; `failed` may retry back to `pending` after operator action.

## Data Retention

- Usage Samples and Audit Events retained for 24 months.
