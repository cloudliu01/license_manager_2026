# Simulator Workload Environment Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a repeatable workload environment that generates a license file, runs `lmgrd`, simulates users, samples `lmstat` into SQLite, and validates the run.

**Architecture:** Keep `lmgrd` and `lmstat` as the public simulator tools, and add a separate `license_manager_simulators.workload` package for orchestration. The runner owns process lifecycle and synthetic user actions, the sampler parses `lmstat`, SQLite stores samples/events, and the validator checks invariants after the run.

**Tech Stack:** Python 3.11+, stdlib subprocess/threading/sqlite3/urllib, existing simulator wrappers, pytest.

---

### Task 1: Scenario and SQLite Sink

**Files:**
- Create: `simulators/src/license_manager_simulators/workload/__init__.py`
- Create: `simulators/src/license_manager_simulators/workload/scenario.py`
- Create: `simulators/src/license_manager_simulators/workload/sqlite_sink.py`
- Test: `simulators/tests/unit/test_workload_scenario.py`
- Test: `simulators/tests/unit/test_workload_sqlite_sink.py`

- [ ] Write tests that assert generated license text includes `alpha`, `beta`, `gamma`, excludes `missing_feature`, and SQLite inserts samples/events.
- [ ] Run `pytest simulators/tests/unit/test_workload_scenario.py simulators/tests/unit/test_workload_sqlite_sink.py -q`; expect import failures.
- [ ] Implement `Scenario`, `FeatureSpec`, `WorkloadEvent`, and `SQLiteSink` with the schema from the design doc.
- [ ] Re-run the same tests and expect pass.

### Task 2: lmstat Sampler Parser

**Files:**
- Create: `simulators/src/license_manager_simulators/workload/sampler.py`
- Test: `simulators/tests/unit/test_workload_sampler.py`

- [ ] Write parser tests for feature lines and verbose detail lines from current `lmstat` output.
- [ ] Run `pytest simulators/tests/unit/test_workload_sampler.py -q`; expect import failure.
- [ ] Implement `parse_lmstat_output` and `sample_once`.
- [ ] Re-run parser tests and expect pass.

### Task 3: Validator

**Files:**
- Create: `simulators/src/license_manager_simulators/workload/validator.py`
- Test: `simulators/tests/unit/test_workload_validator.py`

- [ ] Write tests for a minimal valid run directory and an invalid missing-file run directory.
- [ ] Run `pytest simulators/tests/unit/test_workload_validator.py -q`; expect import failure.
- [ ] Implement `validate_run` and `write_validation_report`.
- [ ] Re-run validator tests and expect pass.

### Task 4: Runner and CLI

**Files:**
- Create: `simulators/src/license_manager_simulators/workload/runner.py`
- Create: `simulators/src/license_manager_simulators/workload/cli.py`
- Modify: `simulators/pyproject.toml`
- Test: `simulators/tests/integration/test_workload_runner.py`

- [ ] Write an integration test that runs the workload for 6 seconds with 6 users and 2-second sampling, then validates the run.
- [ ] Run `pytest simulators/tests/integration/test_workload_runner.py -q`; expect import failure.
- [ ] Implement `run_workload`, user worker loops, process lifecycle cleanup, CLI `run` and `validate`, and console script `sim-workload`.
- [ ] Re-run the integration test and expect pass.

### Task 5: Full Verification

**Files:**
- Existing tests and package files.

- [ ] Run `pytest -q`; expect all tests pass.
- [ ] Run `ruff check .`; if `ruff` is unavailable, record `command not found`.
- [ ] Commit the workload implementation on the feature branch.
