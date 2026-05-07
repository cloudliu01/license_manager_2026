# Simulator CLI Fidelity Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Rebuild the simulator suite as normal Python packages whose `lmgrd` and `lmstat` wrappers provide real-time state snapshots and FlexLM-like runtime logging.

**Architecture:** Move simulator code into `simulators/src/license_manager_simulators`, use a SQLite-backed store as runtime authority, and route FastAPI mutations through a locking service layer that also appends log events. Keep wrappers as the public interface and HTTP as the deterministic internal simulator protocol.

**Tech Stack:** Python 3.11+, FastAPI, Pydantic, SQLite, pytest, urllib stdlib client, bash wrappers.

---

### Task 1: Package Layout and CLI Entrypoints

**Files:**
- Modify: `simulators/pyproject.toml`
- Create: `simulators/src/license_manager_simulators/__init__.py`
- Create: `simulators/src/license_manager_simulators/core/__init__.py`
- Create: `simulators/src/license_manager_simulators/lmgrd/__init__.py`
- Create: `simulators/src/license_manager_simulators/lmstat/__init__.py`
- Modify: `simulators/wrappers/lmgrd`
- Modify: `simulators/wrappers/lmstat`
- Test: `simulators/tests/unit/test_license_parser.py`

- [ ] Add `simulators/src` package discovery and console scripts `lmgrd-sim` and `lmstat-sim`.
- [ ] Create package directories and marker files.
- [ ] Update wrappers to run `python -m license_manager_simulators.lmgrd.cli` and `python -m license_manager_simulators.lmstat.cli` with `PYTHONPATH` pointed at `simulators/src`.
- [ ] Move parser behavior into package and verify imports use normal Python imports.
- [ ] Run `pytest simulators/tests/unit/test_license_parser.py -q` and expect parser tests to pass.

### Task 2: SQLite Store and Service Behavior

**Files:**
- Create: `simulators/src/license_manager_simulators/core/models.py`
- Create: `simulators/src/license_manager_simulators/core/store.py`
- Create: `simulators/src/license_manager_simulators/core/service.py`
- Test: `simulators/tests/unit/test_store_service.py`

- [ ] Write failing tests for grant, queue, return, per-feature queue counts, idempotency, and unknown/expired feature rejection.
- [ ] Implement dataclasses for feature definitions, checkout records, and result objects.
- [ ] Implement SQLite schema and mutation methods.
- [ ] Implement service methods with one `threading.RLock` around all state mutations.
- [ ] Run `pytest simulators/tests/unit/test_store_service.py -q` and expect all service tests to pass.

### Task 3: Runtime Log Writer

**Files:**
- Create: `simulators/src/license_manager_simulators/core/log_writer.py`
- Test: `simulators/tests/unit/test_log_writer.py`

- [ ] Write failing tests for startup banner, `OUT`, `IN`, `DENIED`, `QUEUED`, queue grant, and shutdown lines.
- [ ] Implement reusable FlexLM-like line rendering with immediate file flush.
- [ ] Integrate log writer with the service callback interface.
- [ ] Run `pytest simulators/tests/unit/test_log_writer.py -q` and expect log writer tests to pass.

### Task 4: FastAPI App and lmgrd CLI

**Files:**
- Create: `simulators/src/license_manager_simulators/lmgrd/app.py`
- Create: `simulators/src/license_manager_simulators/lmgrd/cli.py`
- Test: `simulators/tests/integration/test_lmgrd_api.py`

- [ ] Write failing integration tests for `/v1/health`, `/v1/status`, checkout, return, debug checkouts, and debug queue.
- [ ] Implement FastAPI routes using Pydantic request models and the service layer.
- [ ] Implement `lmgrd` CLI startup that initializes store, log writer, service, and Uvicorn.
- [ ] Add FastAPI shutdown hook to append the shutdown log line.
- [ ] Run `pytest simulators/tests/integration/test_lmgrd_api.py -q` and expect API tests to pass.

### Task 5: lmstat CLI and Output Fidelity

**Files:**
- Create: `simulators/src/license_manager_simulators/lmstat/client.py`
- Create: `simulators/src/license_manager_simulators/lmstat/output.py`
- Create: `simulators/src/license_manager_simulators/lmstat/cli.py`
- Test: `simulators/tests/unit/test_lmstat_output.py`
- Test: `simulators/tests/integration/test_lmstat_realtime.py`

- [ ] Write failing tests for `-a`, `-f`, `-i`, service-unreachable stderr, and detail fields including `checkout_id`, `status`, and `granted_at`.
- [ ] Implement lmstat client and output rendering.
- [ ] Implement CLI argument validation and non-zero failure behavior.
- [ ] Run `pytest simulators/tests/unit/test_lmstat_output.py simulators/tests/integration/test_lmstat_realtime.py -q` and expect tests to pass.

### Task 6: Remove Old Hyphenated Modules and Stabilize Test Layout

**Files:**
- Delete: `simulators/lmgrd-sim/*`
- Delete: `simulators/lmstat-sim/*`
- Modify: `simulators/tests/*`
- Modify: `.gitignore`

- [ ] Delete old hyphenated module directories after package tests cover replacement behavior.
- [ ] Replace dynamic `spec_from_file_location` test imports with normal package imports.
- [ ] Move tests into `simulators/tests/unit` and `simulators/tests/integration`.
- [ ] Use dynamic free ports in subprocess integration tests.
- [ ] Add `.hypothesis/` and `.ruff_cache/` to `.gitignore`.
- [ ] Run `pytest -q` from repository root and expect all tests to pass.
- [ ] Run `ruff check .` if ruff is available; if unavailable, record that verification could not run.
