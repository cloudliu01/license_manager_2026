# lmstat FlexNet Format Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Change simulator `lmstat` output to FlexNet-style text matching `tests/sample.decrypted.txt` patterns, while preserving raw snapshots in `samples.sqlite`.

**Architecture:** Update only the lmstat rendering and workload parser/storage boundary. `lmstat.output` emits real-looking FlexNet sections, `workload.sampler` parses those sections back into structured sample tables, and `SQLiteSink.samples.raw_output` remains the original full stdout snapshot.

**Tech Stack:** Python 3.11+, stdlib regex/datetime/subprocess/sqlite3, pytest.

---

### Task 1: FlexNet lmstat Renderer

**Files:**
- Modify: `simulators/src/license_manager_simulators/lmstat/output.py`
- Modify: `simulators/tests/unit/test_lmstat_output.py`

- [ ] Write failing tests asserting output starts with `lmstat - Copyright`, includes `Flexible License Manager status`, `License server status`, `Vendor daemon status`, `Feature usage info`, and `Users of alpha:` lines.
- [ ] Run `pytest simulators/tests/unit/test_lmstat_output.py -q`; expect failure because current output is custom machine format.
- [ ] Implement FlexNet-style output for generated feature names.
- [ ] Re-run the test and expect pass.

### Task 2: FlexNet Sampler Parser and Raw Snapshot Storage

**Files:**
- Modify: `simulators/src/license_manager_simulators/workload/sampler.py`
- Modify: `simulators/tests/unit/test_workload_sampler.py`
- Modify: `simulators/tests/unit/test_workload_sqlite_sink.py`

- [ ] Write failing parser tests for `Users of alpha: (Total...)`, granted detail rows, and queued rows.
- [ ] Write a SQLite test that asserts `samples.raw_output` stores the original FlexNet text unchanged.
- [ ] Run targeted tests and expect parser failures.
- [ ] Implement regex-based parsing for FlexNet-style feature/detail/queued lines.
- [ ] Re-run targeted tests and expect pass.

### Task 3: Integration Updates

**Files:**
- Modify: `simulators/tests/integration/test_lmstat_realtime.py`
- Modify: `simulators/tests/integration/test_workload_runner.py`

- [ ] Update integration assertions from custom `feature: alpha ...` output to FlexNet `Users of alpha:` output.
- [ ] Add integration assertion that workload SQLite `samples.raw_output` contains `lmstat - Copyright` and `Users of`.
- [ ] Run affected integration tests and expect pass.

### Task 4: Full Verification and Commit

**Files:**
- Existing simulator files and tests.

- [ ] Run `pytest -q`; expect all tests pass.
- [ ] Run `ruff check .`; if unavailable, record `command not found`.
- [ ] Commit feature branch with message `Update lmstat output to FlexNet format`.
