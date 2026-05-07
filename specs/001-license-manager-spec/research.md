# Research

## Decision: Core stack and runtime

**Rationale**: The project guidelines already define Python 3.11 with FastAPI, Pydantic, SQLAlchemy, psycopg, Alembic, PyQt6, Jinja2, and HTMX, which align with the system’s API, data parsing, and GUI needs.
**Alternatives considered**: None (preset by project constraints).

## Decision: Storage split by role

**Rationale**: TimescaleDB is best for time-series usage samples at the server, while SQLite supports durable, offline local journals on clients.
**Alternatives considered**: Single shared storage for all components (rejected due to offline requirements).

## Decision: API style for contracts

**Rationale**: A REST-style contract maps cleanly to the operational actions and reporting needs described in the spec and is easy to validate with JSON export requirements.
**Alternatives considered**: GraphQL (rejected for higher complexity and lower alignment with simple operational flows).
