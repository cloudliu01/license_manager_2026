# lmstat Full Real Format Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Tighten simulated `lmstat` full real-output formatting and prove workload SQLite snapshots store that raw stdout unchanged.

**Architecture:** Keep formatting in `license_manager_simulators.lmstat.output.generate_output`, parsing in `license_manager_simulators.workload.sampler.parse_lmstat_output`, and storage in `SQLiteSink`. Make minimal test-first edits without changing simulator protocols or workload feature names.

**Tech Stack:** Python 3.11, pytest, Ruff, SQLite.

---

## File Structure

- Modify `simulators/tests/unit/test_lmstat_output.py`: renderer expectations for full real-output layout and indented detail rows.
- Modify `simulators/src/license_manager_simulators/lmstat/output.py`: minimal formatting fixes.
- Modify `simulators/tests/unit/test_workload_sampler.py`: parser fixture that reflects the generated full format.
- Modify `simulators/tests/integration/test_workload_runner.py`: assert `samples.raw_output` contains full real-output structure.
- Run `pytest -q` and `ruff check .` from repository root.

### Task 1: Renderer Format

**Files:**
- Modify: `simulators/tests/unit/test_lmstat_output.py`
- Modify: `simulators/src/license_manager_simulators/lmstat/output.py`

- [ ] **Step 1: Write failing renderer expectations**

Update `test_generate_output_includes_details_for_verbose_mode` to assert the full real-output layout and indented checkout row:

```python
    assert "License server status: 27000@127.0.0.1" in content
    assert "    License file(s) on 127.0.0.1: /path/to/license.dat:" in content
    assert "127.0.0.1: license server UP (MASTER) v11.19.5" in content
    assert "Vendor daemon status (on 127.0.0.1):" in content
    assert "    default: UP v11.19.5" in content
    assert "Feature usage info:" in content
    assert '  "alpha" v1.0, vendor: default, expiry: permanent' in content
    assert "  floating license" in content
    assert '    "user1" host1 /dev/pts/101 (v1.0) (127.0.0.1/27000 101), start ' in content
```

Update queued row expectation:

```python
    assert '    "user2" host2 /dev/pts/102 (v1.0) (127.0.0.1/27000 102) queued for 1 license' in content
```

- [ ] **Step 2: Run renderer tests to verify failure**

Run: `pytest simulators/tests/unit/test_lmstat_output.py -q`

Expected: FAIL because `_detail_line` currently emits unindented checkout rows.

- [ ] **Step 3: Implement minimal renderer formatting fix**

Change `_detail_line` in `simulators/src/license_manager_simulators/lmstat/output.py`:

```python
def _detail_line(server: str, port: int, detail: dict) -> str:
    user = detail.get("user")
    host = detail.get("host")
    pid = detail.get("pid")
    status = detail.get("status")
    prefix = f'    "{user}" {host} /dev/pts/{pid} (v1.0) ({server}/{port} {pid})'
    if status == "QUEUED":
        return f"{prefix} queued for 1 license"
    return f"{prefix}, start {_format_start(detail.get('granted_at'))}"
```

- [ ] **Step 4: Run renderer tests to verify pass**

Run: `pytest simulators/tests/unit/test_lmstat_output.py -q`

Expected: PASS.

### Task 2: Parser Fixture Coverage

**Files:**
- Modify: `simulators/tests/unit/test_workload_sampler.py`

- [ ] **Step 1: Update parser fixture to generated full format**

Use indented checkout rows in the test fixture:

```python
    "user01" host01 /dev/pts/101 (v1.0) (127.0.0.1/27000 101), start Thu 5/7 00:00
    "user02" host02 /dev/pts/102 (v1.0) (127.0.0.1/27000 102) queued for 1 license
```

- [ ] **Step 2: Run parser test**

Run: `pytest simulators/tests/unit/test_workload_sampler.py -q`

Expected: PASS because `parse_lmstat_output` strips leading whitespace before regex matching.

### Task 3: Workload Raw Output Assertion

**Files:**
- Modify: `simulators/tests/integration/test_workload_runner.py`

- [ ] **Step 1: Tighten SQLite raw-output assertions**

Add assertions after reading `raw_output`:

```python
    assert "License server status:" in raw_output
    assert "    License file(s) on 127.0.0.1: /path/to/license.dat:" in raw_output
    assert "Vendor daemon status (on 127.0.0.1):" in raw_output
    assert "Feature usage info:" in raw_output
    assert "  floating license" in raw_output
```

- [ ] **Step 2: Run workload integration test**

Run: `pytest simulators/tests/integration/test_workload_runner.py -q`

Expected: PASS and at least two samples in `samples.sqlite`.

### Task 4: Full Verification

**Files:**
- No additional file edits.

- [ ] **Step 1: Run full pytest suite**

Run: `pytest -q`

Expected: `19 passed` with existing warnings acceptable.

- [ ] **Step 2: Run Ruff**

Run: `ruff check .`

Expected: `All checks passed!`

- [ ] **Step 3: Inspect git status**

Run: `git status --short --branch`

Expected: modified simulator files, new spec/plan docs, untracked existing `.opencode/package-lock.json` and `runs/`; do not commit unless explicitly requested.
