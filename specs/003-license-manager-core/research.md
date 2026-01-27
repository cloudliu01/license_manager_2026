# Research: License Manager Core

## Decision Log

### 1. Authentication & Authorization (Server GUI)
- **Decision**: Use `authlib` for OIDC/LDAP integration.
- **Rationale**: `authlib` provides a flexible, standard-compliant way to integrate with enterprise providers like Okta, AD, or generic OIDC servers. It integrates well with FastAPI via Starlette-based middleware.
- **Alternatives considered**: `fastapi-users` (too opinionated on the user model), `python-jose` (manual implementation, higher maintenance).

### 2. Server-Agent Communication Protocol
- **Decision**: Hybrid approach: HTTP for Agent Registration/Snapshots; WebSockets for real-time Heartbeats and Control Commands.
- **Rationale**: WebSockets allow the server to push control commands (Restart, Reread) to the agent with low latency, fulfilling the observability and responsiveness goals. Heartbeats via WS also provide instant "Stale" detection.
- **Alternatives considered**: HTTP Polling (too much overhead/latency), gRPC (excellent but adds complexity to relocatable packaging).

### 3. Message Signing & Identity
- **Decision**: Ed25519 (using the `nacl` or `cryptography` library) for signing JSON payloads.
- **Rationale**: Ed25519 signatures are very small (64 bytes) and public keys are short (32 bytes), making them ideal for embedding in telemetry headers or payloads. High performance and security.
- **Registration**: Agents will be bootstrapped with a `SERVER_PUBLIC_KEY` and an `AGENT_SECRET_TOKEN` during installation.

### 4. Database Schema Management
- **Decision**: Alembic with SQLAlchemy.
- **Rationale**: Industry standard for Python. Supports TimescaleDB specific SQL (like `create_hypertable`) via raw SQL migrations or extensions.

### 5. Packaging (Relocatable)
- **Decision**: Use `conda-pack` or `shiv` to create self-contained Python environments.
- **Rationale**: Ensures "Unpack-and-run" portability. `conda-pack` is particularly good for C-extensions like `psycopg2` and `cryptography`.

## Technology Choices Summary

| Category | Technology |
|----------|------------|
| API Framework | FastAPI |
| ORM | SQLAlchemy |
| Migrations | Alembic |
| Security | Ed25519 + authlib |
| Real-time | WebSockets |
| Packaging | Conda-pack / Miniforge |
