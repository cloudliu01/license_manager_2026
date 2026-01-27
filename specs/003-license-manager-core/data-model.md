# Data Model: License Manager Core

## Entities

### 1. Agent
Represents a client machine running the `agentd` daemon.

| Field | Type | Description |
|-------|------|-------------|
| id | UUID | Primary Key |
| hostname | String | Hostname of the client machine |
| server_id | String | The ID of the server this agent is bound to |
| public_key | String | Ed25519 Public Key for message verification |
| status | Enum | ONLINE, STALE, OFFLINE |
| config_rev | Integer | Current configuration revision number |
| config_hash | String | SHA256 of the active configuration |
| last_seen_at | DateTime | Last successful heartbeat or communication |

### 2. ConfigSnapshot
Historical snapshots of agent configurations.

| Field | Type | Description |
|-------|------|-------------|
| id | UUID | Primary Key |
| agent_id | UUID | Foreign Key -> Agent.id |
| rev | Integer | Revision number |
| payload | JSON | The full configuration payload (license paths, ports, etc.) |
| hash | String | SHA256 of the payload |
| created_at | DateTime | When the snapshot was recorded by the server |

### 3. ControlRequest
Commands issued to agents (Restart, Reread, Apply).

| Field | Type | Description |
|-------|------|-------------|
| id | UUID | Primary Key |
| agent_id | UUID | Foreign Key -> Agent.id |
| type | Enum | START, STOP, RESTART, REREAD, APPLY_CONFIG |
| status | Enum | PENDING, SENT, SUCCESS, FAILED, TIMEOUT |
| initiator_id | String | User ID who initiated the action |
| payload | JSON | Parameters for the command (e.g., config changeset) |
| result | JSON | Response from the agent |
| expires_at | DateTime | Time after which the request is considered TIMEOUT |
| created_at | DateTime | |

### 4. AuditLog
Authoritative record of all administrative actions.

| Field | Type | Description |
|-------|------|-------------|
| id | BigInt | Primary Key |
| timestamp | DateTime | |
| initiator_id | String | User ID |
| agent_id | UUID | (Optional) Target agent |
| action | String | Action name (e.g., "RESTART_LMGRD", "EDIT_CONFIG") |
| details | JSON | Contextual details (diffs, command IDs) |
| result | Enum | SUCCESS, FAILURE |

### 5. EditLease
Concurrency control for configuration editing.

| Field | Type | Description |
|-------|------|-------------|
| id | UUID | Primary Key |
| agent_id | UUID | Foreign Key -> Agent.id |
| user_id | String | User who holds the lease |
| expires_at | DateTime | Lease TTL |

## Relationships

- **Agent (1) <-> (N) ConfigSnapshot**: History of all reported configurations.
- **Agent (1) <-> (N) ControlRequest**: Log of all commands sent to the agent.
- **Agent (1) <-> (1) EditLease**: Only one active lease per agent.
