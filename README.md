# License Manager Simulator

This repository includes a local FlexNet-style simulator for exercising license usage workflows without running a real FlexNet server. It provides:

- `lmgrd` wrapper: starts a simulated license daemon with checkout, return, status, and debug HTTP endpoints.
- `lmstat` wrapper: prints FlexNet-style license usage output from the simulated daemon.
- workload runner: generates synthetic user activity, samples `lmstat`, and stores raw snapshots plus parsed rows in SQLite.

The simulator is CLI-compatible for the workflows below, but it does not implement the real FlexNet wire protocol.

## Requirements

- Python 3.11+
- Project dependencies available on `PYTHONPATH=simulators/src`
- `sqlite3` CLI if you want to inspect generated databases from the shell

## Run A Workload

Generate a short synthetic workload run:

```bash
PYTHONPATH=simulators/src python -m license_manager_simulators.workload.cli run \
  --duration-seconds 6 \
  --users 6 \
  --sample-interval-seconds 2 \
  --seed 11 \
  --out runs/raw-output-check
```

The run directory contains:

- `metadata.json`: run settings, paths, timing, and process status.
- `license.dat`: generated simulator license file.
- `lmgrd.log`: simulated daemon activity log with `OUT`, `IN`, `DENIED`, and `QUEUED` records.
- `samples.sqlite`: raw `lmstat` snapshots, parsed feature usage rows, parsed checkout rows, and workload events.
- `validation.json`: validation report for the generated run.

## Validate A Run

```bash
PYTHONPATH=simulators/src python -m license_manager_simulators.workload.cli validate \
  --run-dir runs/raw-output-check \
  --min-samples 2
```

## Inspect Raw lmstat Output

Show the first raw snapshot captured in SQLite:

```bash
sqlite3 runs/raw-output-check/samples.sqlite \
  "select raw_output from samples order by sample_id limit 1;"
```

List sample timestamps and raw output sizes:

```bash
sqlite3 runs/raw-output-check/samples.sqlite \
  "select sample_id, sampled_at, length(raw_output) from samples order by sample_id;"
```

## SQLite Tables

`samples` stores one row per `lmstat` sample:

```text
sample_id, sampled_at, raw_output
```

`feature_samples` stores parsed feature summary rows. `sampled_at` duplicates `samples.sampled_at` so feature rows can be queried directly by time:

```text
sample_id, sampled_at, feature, total, in_use, queued, expired
```

`checkout_samples` stores parsed checkout detail rows. `sampled_at` duplicates `samples.sampled_at` so checkout rows can be queried directly by time:

```text
sample_id, sampled_at, feature, user, host, pid, checkout_id, status, granted_at
```

`workload_events` stores synthetic user actions and simulator responses:

```text
event_id, event_time, user, action, feature, status, reason, checkout_id
```

Example summary query:

```bash
sqlite3 runs/raw-output-check/samples.sqlite \
  "select sampled_at, feature, total, in_use, queued from feature_samples order by sampled_at, feature;"
```

Example checkout query:

```bash
sqlite3 runs/raw-output-check/samples.sqlite \
  "select sampled_at, feature, user, host, pid, status from checkout_samples order by sampled_at, feature, user;"
```

## Run lmgrd And lmstat Manually

Create a minimal license file:

```bash
cat > /tmp/license.dat <<'EOF'
PORT 27000
FEATURE alpha 2
FEATURE beta 1
EOF
```

Start the simulated daemon:

```bash
simulators/wrappers/lmgrd -c /tmp/license.dat -l /tmp/lmgrd.log
```

In another shell, query status with details:

```bash
simulators/wrappers/lmstat -c 27000@127.0.0.1 -a -i
```

## Test Commands

Run the simulator test suite and lint checks:

```bash
pytest -q
ruff check .
```
