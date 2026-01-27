# Quickstart: License Manager Core

## Prerequisites
- Python 3.11+
- TimescaleDB (PostgreSQL 14+)
- `agentd` binary (built or installed)

## 1. Server Setup

1. **Initialize Database**:
   ```bash
   export DATABASE_URL="postgresql://user:pass@localhost:5432/license_manager"
   alembic upgrade head
   ```

2. **Start Server API**:
   ```bash
   cd src/server
   uvicorn api.main:app --host 0.0.0.0 --port 8080
   ```

## 2. Agent Bootstrap

1. **Register Agent**:
   ```bash
   agentd register --server http://server-host:8080 --token <bootstrap-token>
   ```

2. **Start Agent Daemon**:
   ```bash
   agentd run
   ```

## 3. Verify Connectivity

1. **Check Server Dashboard**:
   Navigate to `http://server-host:8080/docs` (Swagger UI) and call `GET /agents`.
   Your agent should appear with status `ONLINE`.

2. **Trigger a Restart**:
   ```bash
   curl -X POST http://server-host:8080/agents/<agent-id>/control \
        -H "Content-Type: application/json" \
        -d '{"type": "RESTART"}'
   ```
   Check `agentd` logs to verify the restart was received and executed.
