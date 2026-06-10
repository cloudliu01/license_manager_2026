# Flexlm Exporter Simulator Integration Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add `flexlm_exporter` as a submodule and provide a repeatable local proof that it can scrape the existing simulator, including user, version, and reservation metrics.

**Architecture:** Keep third-party source in `third_party/flexlm_exporter` and project-owned integration code in `tools/flexlm_exporter/`. Add a small `lmutil` shim because the exporter invokes `lmutil lmstat`, while the simulator currently exposes `lmstat` directly. Extend simulator output just enough to emit FlexNet-style reservation lines so exporter reservation metrics can be verified without broad refactoring.

**Tech Stack:** Python 3.11, pytest, FastAPI simulator, Bash wrapper scripts, Go toolchain for building `flexlm_exporter`, Git submodules.

---

## File Structure

- Create: `.gitmodules` through `git submodule add`; owned by Git.
- Create: `third_party/flexlm_exporter`; Git submodule for upstream exporter source.
- Create: `tools/flexlm_exporter/lmutil`; executable shim that translates `lmutil lmstat` calls to simulator `lmstat` calls.
- Create: `tools/flexlm_exporter/licenses.yml`; sample exporter config with users, reservations, and versions enabled.
- Create: `tools/flexlm_exporter/verify_exporter.py`; end-to-end local verifier that starts simulator and exporter, scrapes metrics, and checks expected output.
- Create: `tests/tools/test_lmutil_shim.py`; unit tests for the shim's command behavior.
- Create: `tests/tools/test_verify_exporter.py`; unit tests for the verifier's metric checks.
- Modify: `simulators/src/license_manager_simulators/core/models.py`; add reservation model and attach reservations to features.
- Modify: `simulators/src/license_manager_simulators/core/license_parser.py`; parse simple reservation metadata on `FEATURE` lines.
- Modify: `simulators/src/license_manager_simulators/core/store.py`; persist reservations and expose them in status rows.
- Modify: `simulators/src/license_manager_simulators/lmstat/output.py`; emit reservation lines in FlexNet-style output.
- Modify: `simulators/tests/unit/test_license_parser.py`; cover reservation parsing.
- Modify: `simulators/tests/unit/test_lmstat_output.py`; cover reservation output and version-compatible detail rows.
- Modify: `docs/manual-simulator.md`; document the reservation syntax.
- Create: `docs/flexlm-exporter-simulator.md`; user-facing verification workflow.
- Modify: `README.md`; link to the exporter verification doc.

Do not commit during execution unless the user explicitly asks for commits. Use diff checkpoints instead.

---

### Task 1: Add `flexlm_exporter` Submodule

**Files:**
- Create: `.gitmodules`
- Create: `third_party/flexlm_exporter`

- [ ] **Step 1: Verify there is no existing submodule**

Run: `git submodule status`

Expected: either no output, or output that does not mention `third_party/flexlm_exporter`.

- [ ] **Step 2: Add the upstream exporter as a submodule**

Run: `git submodule add https://github.com/mjtrangoni/flexlm_exporter.git third_party/flexlm_exporter`

Expected: command exits with status `0` and creates `.gitmodules` plus `third_party/flexlm_exporter`.

- [ ] **Step 3: Verify submodule pointer**

Run: `git submodule status third_party/flexlm_exporter`

Expected: output contains one commit SHA followed by `third_party/flexlm_exporter`.

- [ ] **Step 4: Check exporter supports `--path.lmutil`**

Run: `grep -R "path.lmutil" third_party/flexlm_exporter/collector third_party/flexlm_exporter/*.go`

Expected: output includes `collector/paths.go` with `path.lmutil`.

- [ ] **Step 5: Diff checkpoint**

Run: `git status --short`

Expected: `.gitmodules` and `third_party/flexlm_exporter` are listed as new changes.

---

### Task 2: Add `lmutil` Shim

**Files:**
- Create: `tools/flexlm_exporter/lmutil`
- Create: `tests/tools/test_lmutil_shim.py`

- [ ] **Step 1: Write failing shim tests**

Create `tests/tools/test_lmutil_shim.py`:

```python
from __future__ import annotations

import subprocess
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
SHIM = ROOT / "tools" / "flexlm_exporter" / "lmutil"


def test_lmutil_shim_reports_lmstat_version():
    result = subprocess.run(
        [str(SHIM), "lmstat", "-v"],
        check=True,
        capture_output=True,
        text=True,
    )

    assert result.stdout.strip() == "lmstat v11.19.5 build 300000 x64_lsb"


def test_lmutil_shim_rejects_unsupported_subcommand():
    result = subprocess.run(
        [str(SHIM), "lmdiag"],
        capture_output=True,
        text=True,
    )

    assert result.returncode == 2
    assert "unsupported lmutil subcommand: lmdiag" in result.stderr
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m pytest tests/tools/test_lmutil_shim.py -q`

Expected: FAIL because `tools/flexlm_exporter/lmutil` does not exist.

- [ ] **Step 3: Create the shim**

Create `tools/flexlm_exporter/lmutil`:

```bash
#!/usr/bin/env bash
set -euo pipefail

if [[ $# -lt 1 ]]; then
  printf 'usage: lmutil lmstat [args]\n' >&2
  exit 2
fi

subcommand="$1"
shift

if [[ "${subcommand}" != "lmstat" ]]; then
  printf 'unsupported lmutil subcommand: %s\n' "${subcommand}" >&2
  exit 2
fi

if [[ "${1:-}" == "-v" ]]; then
  printf 'lmstat v11.19.5 build 300000 x64_lsb\n'
  exit 0
fi

args=("$@")
has_a=0
has_i=0
for arg in "${args[@]}"; do
  [[ "${arg}" == "-a" ]] && has_a=1
  [[ "${arg}" == "-i" ]] && has_i=1
done

# flexlm_exporter calls `lmstat -a` for user metrics and `lmstat -i` for
# expiration metrics. The simulator exposes detailed user, reservation, and
# inventory output when both flags are present, so normalize exporter calls.
if [[ ${has_a} -eq 1 && ${has_i} -eq 0 ]]; then
  args+=("-i")
elif [[ ${has_a} -eq 0 && ${has_i} -eq 1 ]]; then
  args+=("-a")
fi

SCRIPT_DIR=$(cd "$(dirname "$0")" && pwd)
REPO_ROOT=$(cd "${SCRIPT_DIR}/../.." && pwd)

exec "${REPO_ROOT}/simulators/wrappers/lmstat" "${args[@]}"
```

- [ ] **Step 4: Make the shim executable**

Run: `chmod +x tools/flexlm_exporter/lmutil`

Expected: command exits with status `0`.

- [ ] **Step 5: Run shim tests to verify they pass**

Run: `python -m pytest tests/tools/test_lmutil_shim.py -q`

Expected: `2 passed`.

- [ ] **Step 6: Diff checkpoint**

Run: `git diff -- tools/flexlm_exporter/lmutil tests/tools/test_lmutil_shim.py`

Expected: diff shows only the shim and tests above.

---

### Task 3: Add Minimal Reservation Support To Simulator Output

**Files:**
- Modify: `simulators/src/license_manager_simulators/core/models.py`
- Modify: `simulators/src/license_manager_simulators/core/license_parser.py`
- Modify: `simulators/src/license_manager_simulators/core/store.py`
- Modify: `simulators/src/license_manager_simulators/lmstat/output.py`
- Modify: `simulators/tests/unit/test_license_parser.py`
- Modify: `simulators/tests/unit/test_lmstat_output.py`
- Modify: `docs/manual-simulator.md`

- [ ] **Step 1: Write failing parser test for reservations**

Append this test to `simulators/tests/unit/test_license_parser.py`:

```python
def test_parse_license_text_supports_feature_reservations():
    config = parse_license_text(
        """
        PORT 27000
        DAEMON vendorA
        FEATURE alpha 10 DAEMON vendorA EXP 2026-12-31 RESERVE 2 GROUP engineering RESERVE 1 HOST buildhost1
        """
    )

    reservations = config.features["alpha"].reservations
    assert [(item.kind, item.name, item.count) for item in reservations] == [
        ("GROUP", "engineering", 2),
        ("HOST", "buildhost1", 1),
    ]
```

- [ ] **Step 2: Write failing output test for reservation lines**

Append this test to `simulators/tests/unit/test_lmstat_output.py`:

```python
def test_generate_output_includes_reservation_lines_for_exporter():
    content = generate_output(
        server="127.0.0.1",
        port=27000,
        features=[
            {
                "name": "alpha",
                "daemon": "vendorA",
                "total": 4,
                "in_use": 1,
                "queued": 0,
                "expired": False,
                "expires_at": "2026-11-01",
                "reservations": [
                    {"kind": "GROUP", "name": "engineering", "count": 2},
                    {"kind": "HOST", "name": "buildhost1", "count": 1},
                ],
                "details": [
                    {
                        "checkout_id": "co-1",
                        "user": "user1",
                        "host": "host1",
                        "pid": 101,
                        "status": "GRANTED",
                        "granted_at": "2026-05-07T00:00:00+00:00",
                    }
                ],
            }
        ],
        include_details=True,
    )

    assert "2 licenses for GROUP engineering" in content
    assert "1 license for HOST buildhost1" in content
    assert content.index("Users of alpha:") < content.index("2 licenses for GROUP engineering")
```

- [ ] **Step 3: Run tests to verify they fail**

Run: `python -m pytest simulators/tests/unit/test_license_parser.py simulators/tests/unit/test_lmstat_output.py -q`

Expected: FAIL with missing `reservations` attribute or missing reservation output.

- [ ] **Step 4: Add reservation data model**

Modify `simulators/src/license_manager_simulators/core/models.py` so the feature models are:

```python
@dataclass(frozen=True)
class ReservationDef:
    kind: str
    name: str
    count: int


@dataclass(frozen=True)
class FeatureDef:
    name: str
    total: int
    daemon: str
    expires_at: date | None
    reservations: tuple[ReservationDef, ...] = ()
```

Keep the remaining dataclasses unchanged.

- [ ] **Step 5: Parse reservation tokens**

Modify `simulators/src/license_manager_simulators/core/license_parser.py`:

```python
from .models import FeatureDef, LicenseConfig, ReservationDef
```

Inside the `FEATURE` branch, add this before `idx = 3`:

```python
            reservations: list[ReservationDef] = []
```

Inside the `while idx < len(parts):` loop, after the `EXP` handling block and before the final `raise ValueError`, add:

```python
                if token == "RESERVE":
                    if idx + 3 >= len(parts):
                        raise ValueError("RESERVE requires count, kind, and name")
                    count = int(parts[idx + 1])
                    kind = parts[idx + 2].upper()
                    name = parts[idx + 3]
                    if count < 1:
                        raise ValueError("RESERVE count must be >= 1")
                    if kind not in {"GROUP", "HOST", "HOST_GROUP"}:
                        raise ValueError("RESERVE kind must be GROUP, HOST_GROUP, or HOST")
                    reservations.append(ReservationDef(kind, name, count))
                    idx += 4
                    continue
```

Replace the feature assignment with:

```python
            features[name] = FeatureDef(name, total, daemon_name, expires_at, tuple(reservations))
```

- [ ] **Step 6: Persist reservations in store status**

Modify `simulators/src/license_manager_simulators/core/store.py`.

Add a `reservations` table in `init_schema` after the `features` table:

```python
        cursor.execute(
            """
            create table reservations (
                feature text not null,
                kind text not null,
                name text not null,
                count integer not null
            )
            """
        )
```

In `insert_feature`, after the `insert into features` call and before `self.conn.commit()`, add:

```python
        for reservation in feature.reservations:
            self.conn.execute(
                "insert into reservations values (?, ?, ?, ?)",
                (feature.name, reservation.kind, reservation.name, reservation.count),
            )
```

Add this method to `SimulatorStore` before `status_rows`:

```python
    def reservation_rows(self, feature: str) -> list[dict]:
        rows = self.conn.execute(
            "select kind, name, count from reservations where feature = ? order by kind, name",
            (feature,),
        ).fetchall()
        return [_row_to_dict(row) for row in rows]
```

In `status_rows`, add the reservation field to each item:

```python
                    "reservations": self.reservation_rows(row["name"]),
```

- [ ] **Step 7: Emit reservation lines in lmstat output**

Modify `simulators/src/license_manager_simulators/lmstat/output.py`.

In `_feature_detail_lines`, after the `lines.extend(_detail_line(server, port, detail) for detail in details)` line, add:

```python
    lines.extend(_reservation_lines(feature))
```

Add this helper before `_detail_line`:

```python
def _reservation_lines(feature: dict) -> list[str]:
    lines = []
    for reservation in feature.get("reservations", []):
        count = int(reservation.get("count", 0))
        if count < 1:
            continue
        kind = str(reservation.get("kind", "")).upper()
        name = reservation.get("name")
        license_word = "license" if count == 1 else "licenses"
        lines.append(f"    {count} {license_word} for {kind} {name}")
    return lines
```

This line shape matches the exporter's reservation regexes for `GROUP`, `HOST_GROUP`, and `HOST`.

- [ ] **Step 8: Run simulator unit tests**

Run: `python -m pytest simulators/tests/unit/test_license_parser.py simulators/tests/unit/test_lmstat_output.py simulators/tests/unit/test_store_service.py -q`

Expected: all selected tests pass.

- [ ] **Step 9: Document reservation syntax**

Modify `docs/manual-simulator.md` under supported license-file lines by adding:

```markdown
- `FEATURE <name> <total> RESERVE <count> GROUP <group>`: optional reservation metadata emitted in `lmstat -a -i` output for exporter compatibility.
- `FEATURE <name> <total> RESERVE <count> HOST <host>`: optional host reservation metadata emitted in `lmstat -a -i` output for exporter compatibility.
```

- [ ] **Step 10: Diff checkpoint**

Run: `git diff -- simulators/src/license_manager_simulators/core/models.py simulators/src/license_manager_simulators/core/license_parser.py simulators/src/license_manager_simulators/core/store.py simulators/src/license_manager_simulators/lmstat/output.py simulators/tests/unit/test_license_parser.py simulators/tests/unit/test_lmstat_output.py docs/manual-simulator.md`

Expected: diff shows only reservation model, parser, status, output, tests, and docs changes.

---

### Task 4: Add Exporter Verification Script And Tests

**Files:**
- Create: `tools/flexlm_exporter/verify_exporter.py`
- Create: `tools/flexlm_exporter/licenses.yml`
- Create: `tests/tools/test_verify_exporter.py`

- [ ] **Step 1: Write failing verifier unit tests**

Create `tests/tools/test_verify_exporter.py`:

```python
from __future__ import annotations

import importlib.util
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
VERIFY_PATH = ROOT / "tools" / "flexlm_exporter" / "verify_exporter.py"


def _load_verify_module():
    spec = importlib.util.spec_from_file_location("verify_exporter", VERIFY_PATH)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


def test_missing_required_metrics_accepts_expected_exporter_output():
    verify = _load_verify_module()
    metrics = """
flexlm_lmstat_info{arch="x64_lsb",build="300000",version="v11.19.5"} 1
flexlm_server_status{app="simulator",fqdn="127.0.0.1",master="true",port="27000",version="v11.19.5"} 1
flexlm_feature_issued{app="simulator",name="alpha"} 2
flexlm_feature_used{app="simulator",name="alpha"} 1
flexlm_feature_used_users{app="simulator",name="alpha",since="1778112000",user="user1",version="(v1.0)"} 1
flexlm_feature_reserved_groups{app="simulator",group="engineering",name="alpha"} 2
flexlm_feature_reserved_host{app="simulator",host="buildhost1",name="alpha"} 1
"""

    assert verify.missing_required_metrics(metrics) == []


def test_missing_required_metrics_reports_absent_reservations():
    verify = _load_verify_module()
    metrics = """
flexlm_lmstat_info{arch="x64_lsb",build="300000",version="v11.19.5"} 1
flexlm_server_status{app="simulator",fqdn="127.0.0.1",master="true",port="27000",version="v11.19.5"} 1
flexlm_feature_issued{app="simulator",name="alpha"} 2
flexlm_feature_used{app="simulator",name="alpha"} 1
flexlm_feature_used_users{app="simulator",name="alpha",since="1778112000",user="user1",version="(v1.0)"} 1
"""

    missing = verify.missing_required_metrics(metrics)

    assert "group reservation metric" in missing
    assert "host reservation metric" in missing
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m pytest tests/tools/test_verify_exporter.py -q`

Expected: FAIL because `tools/flexlm_exporter/verify_exporter.py` does not exist.

- [ ] **Step 3: Create sample exporter config**

Create `tools/flexlm_exporter/licenses.yml`:

```yaml
licenses:
  - name: simulator
    license_server: 27000@127.0.0.1
    monitor_users: true
    monitor_reservations: true
    monitor_versions: true
```

- [ ] **Step 4: Create verifier script**

Create `tools/flexlm_exporter/verify_exporter.py`:

```python
from __future__ import annotations

import argparse
import json
import socket
import subprocess
import tempfile
import time
from pathlib import Path
from urllib.error import URLError
from urllib.request import Request, urlopen


ROOT = Path(__file__).resolve().parents[2]
EXPORTER_DIR = ROOT / "third_party" / "flexlm_exporter"
LMGRD = ROOT / "simulators" / "wrappers" / "lmgrd"
LMUTIL = ROOT / "tools" / "flexlm_exporter" / "lmutil"

REQUIRED_METRICS = [
    ("lmstat info", "flexlm_lmstat_info"),
    ("server status", "flexlm_server_status"),
    ("feature issued", 'flexlm_feature_issued{app="simulator",name="alpha"} 2'),
    ("feature used", 'flexlm_feature_used{app="simulator",name="alpha"} 1'),
    ("versioned user metric", "flexlm_feature_used_users{"),
    ("version label", 'version="(v1.0)"'),
    ("group reservation metric", "flexlm_feature_reserved_groups"),
    ("host reservation metric", "flexlm_feature_reserved_host"),
]


def main() -> int:
    parser = argparse.ArgumentParser(description="Verify flexlm_exporter against the local simulator")
    parser.add_argument("--sim-port", type=int, default=0, help="Simulator port, or 0 for a free port")
    parser.add_argument("--exporter-port", type=int, default=0, help="Exporter port, or 0 for a free port")
    args = parser.parse_args()

    if not EXPORTER_DIR.exists():
        raise SystemExit("third_party/flexlm_exporter is missing; run git submodule update --init --recursive")
    if not (EXPORTER_DIR / "go.mod").exists():
        raise SystemExit("third_party/flexlm_exporter does not look like the exporter source tree")

    sim_port = args.sim_port or free_port()
    exporter_port = args.exporter_port or free_port()

    with tempfile.TemporaryDirectory(prefix="flexlm-exporter-verify-") as tmp:
        tmp_path = Path(tmp)
        exporter_bin = tmp_path / "flexlm_exporter"
        license_path = tmp_path / "license.dat"
        log_path = tmp_path / "lmgrd.log"
        config_path = tmp_path / "licenses.yml"

        build_exporter(exporter_bin)
        write_license_file(license_path, sim_port)
        write_exporter_config(config_path, sim_port)

        lmgrd_proc = subprocess.Popen([str(LMGRD), "-c", str(license_path), "-l", str(log_path)])
        exporter_proc: subprocess.Popen[str] | None = None
        try:
            wait_for_url(f"http://127.0.0.1:{sim_port}/v1/health")
            post_json(
                sim_port,
                "/v1/checkout",
                {"request_id": "verify-1", "feature": "alpha", "user": "user1", "host": "host1", "pid": 101},
            )
            exporter_proc = subprocess.Popen(
                [
                    str(exporter_bin),
                    f"--web.listen-address=127.0.0.1:{exporter_port}",
                    f"--path.lmutil={LMUTIL}",
                    f"--path.config={config_path}",
                ],
                text=True,
            )
            metrics = wait_for_metrics(exporter_port)
            missing = missing_required_metrics(metrics)
            if missing:
                raise SystemExit("missing expected metrics: " + ", ".join(missing))
            print(f"flexlm_exporter simulator verification passed on :{exporter_port}")
            return 0
        finally:
            stop_process(exporter_proc)
            stop_process(lmgrd_proc)


def build_exporter(output_path: Path) -> None:
    subprocess.run(["go", "build", "-o", str(output_path), "."], cwd=EXPORTER_DIR, check=True)


def write_license_file(path: Path, port: int) -> None:
    path.write_text(
        f"""PORT {port}
DAEMON vendorA
FEATURE alpha 2 DAEMON vendorA EXP 2026-11-01 RESERVE 2 GROUP engineering RESERVE 1 HOST buildhost1
""",
        encoding="utf-8",
    )


def write_exporter_config(path: Path, port: int) -> None:
    path.write_text(
        f"""licenses:
  - name: simulator
    license_server: {port}@127.0.0.1
    monitor_users: true
    monitor_reservations: true
    monitor_versions: true
""",
        encoding="utf-8",
    )


def missing_required_metrics(metrics: str) -> list[str]:
    return [name for name, needle in REQUIRED_METRICS if needle not in metrics]


def free_port() -> int:
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


def wait_for_url(url: str, timeout: float = 10.0) -> str:
    deadline = time.time() + timeout
    last_error: Exception | None = None
    while time.time() < deadline:
        try:
            with urlopen(url, timeout=1.0) as response:
                return response.read().decode("utf-8")
        except Exception as exc:
            last_error = exc
            time.sleep(0.2)
    raise RuntimeError(f"timed out waiting for {url}: {last_error}")


def wait_for_metrics(port: int) -> str:
    return wait_for_url(f"http://127.0.0.1:{port}/metrics", timeout=15.0)


def post_json(port: int, path: str, payload: dict) -> dict:
    request = Request(
        f"http://127.0.0.1:{port}{path}",
        data=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    with urlopen(request, timeout=2.0) as response:
        return json.loads(response.read().decode("utf-8"))


def stop_process(proc: subprocess.Popen | None) -> None:
    if proc is None or proc.poll() is not None:
        return
    proc.terminate()
    try:
        proc.wait(timeout=3)
    except subprocess.TimeoutExpired:
        proc.kill()
        proc.wait(timeout=3)


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except FileNotFoundError as exc:
        if exc.filename == "go":
            raise SystemExit("Go toolchain is required to build flexlm_exporter") from exc
        raise
    except URLError as exc:
        raise SystemExit(f"HTTP verification failed: {exc}") from exc
```

- [ ] **Step 5: Run verifier unit tests**

Run: `python -m pytest tests/tools/test_verify_exporter.py -q`

Expected: `2 passed`.

- [ ] **Step 6: Diff checkpoint**

Run: `git diff -- tools/flexlm_exporter tests/tools/test_verify_exporter.py`

Expected: diff shows sample config, verifier, and verifier tests.

---

### Task 5: Add User-Facing Exporter Verification Docs

**Files:**
- Create: `docs/flexlm-exporter-simulator.md`
- Modify: `README.md`

- [ ] **Step 1: Create exporter verification doc**

Create `docs/flexlm-exporter-simulator.md`:

```markdown
# Flexlm Exporter Simulator Verification

Use this workflow to verify that `mjtrangoni/flexlm_exporter` can scrape the local FlexNet-style simulator through the project-owned `lmutil` shim.

## Prerequisites

- Python 3.11+
- Go toolchain available as `go`
- Git submodules initialized with `git submodule update --init --recursive`

## What Is Verified

The verifier starts the simulator, checks out one `alpha` license, starts `flexlm_exporter`, scrapes `/metrics`, and checks for:

- `flexlm_server_status`
- `flexlm_feature_issued`
- `flexlm_feature_used`
- `flexlm_feature_used_users` with `version="(v1.0)"`
- `flexlm_feature_reserved_groups`
- `flexlm_feature_reserved_host`
- `flexlm_lmstat_info`

## Run

```bash
python tools/flexlm_exporter/verify_exporter.py
```

Expected output:

```text
flexlm_exporter simulator verification passed on :<port>
```

## Manual Exporter Config

The sample config at `tools/flexlm_exporter/licenses.yml` enables user, reservation, and version monitoring:

```yaml
licenses:
  - name: simulator
    license_server: 27000@127.0.0.1
    monitor_users: true
    monitor_reservations: true
    monitor_versions: true
```

## Notes

The exporter invokes `lmutil lmstat`, while this repository exposes `simulators/wrappers/lmstat`. The shim at `tools/flexlm_exporter/lmutil` bridges that command shape and returns a parser-compatible `lmstat -v` line.
```

- [ ] **Step 2: Link the doc from README**

Modify `README.md` under `## Documentation` by adding:

```markdown
- [Flexlm exporter verification](docs/flexlm-exporter-simulator.md): build `flexlm_exporter`, run it through the local `lmutil` shim, and verify simulator metrics.
```

- [ ] **Step 3: Verify docs paths exist**

Run: `python - <<'PY'
from pathlib import Path
for path in [Path('docs/flexlm-exporter-simulator.md'), Path('tools/flexlm_exporter/licenses.yml')]:
    assert path.exists(), path
print('docs paths ok')
PY`

Expected: `docs paths ok`.

- [ ] **Step 4: Diff checkpoint**

Run: `git diff -- README.md docs/manual-simulator.md docs/flexlm-exporter-simulator.md`

Expected: diff shows documentation updates only.

---

### Task 6: End-To-End Verification

**Files:**
- No new files.

- [ ] **Step 1: Run focused unit tests**

Run: `python -m pytest tests/tools simulators/tests/unit/test_license_parser.py simulators/tests/unit/test_lmstat_output.py simulators/tests/unit/test_store_service.py -q`

Expected: all selected tests pass.

- [ ] **Step 2: Run simulator integration tests affected by lmstat output**

Run: `python -m pytest simulators/tests/integration/test_lmstat_realtime.py -q`

Expected: all tests pass.

- [ ] **Step 3: Run exporter compatibility verification**

Run: `python tools/flexlm_exporter/verify_exporter.py`

Expected: prints `flexlm_exporter simulator verification passed on :<port>`.

If this fails with `Go toolchain is required to build flexlm_exporter`, install or activate Go and rerun. If it fails with missing metrics, inspect the printed missing metric names and compare the simulator `lmstat -a -i` output to `third_party/flexlm_exporter/collector/regexp.go`.

- [ ] **Step 4: Run lint if available in the environment**

Run: `python -m ruff check .`

Expected: command exits with status `0`. If `ruff` is not installed, record the missing tool and do not claim lint passed.

- [ ] **Step 5: Inspect final diff**

Run: `git status --short`

Expected: changes are limited to `.gitmodules`, `third_party/flexlm_exporter`, `tools/flexlm_exporter/`, `tests/tools/`, simulator reservation support files, and docs.

Run: `git diff --stat`

Expected: diff size is consistent with the planned small integration and minimal simulator reservation support.
