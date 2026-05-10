# License Manager Simulator

This repository includes a local FlexNet-style simulator for exercising license usage workflows without running a real FlexNet server.

It provides:

- `lmgrd` wrapper: starts a simulated license daemon with checkout, return, status, and debug HTTP endpoints.
- `lmstat` wrapper: prints FlexNet-style license usage output from the simulated daemon.
- Workload runner: generates synthetic user activity, samples `lmstat`, and stores raw snapshots plus parsed rows in SQLite.

The simulator is CLI-compatible for the workflows below, but it does not implement the real FlexNet wire protocol.

## Documentation

- [Manual simulator usage](docs/manual-simulator.md): start `lmgrd`, check out and return licenses from the command line, and print usage with `lmstat`.
- [Workload simulator usage](docs/workload-simulator.md): generate synthetic activity, validate runs, inspect `samples.sqlite`, and query raw `lmstat` snapshots.

## Requirements

- Python 3.11+
- Project dependencies available on `PYTHONPATH=simulators/src`
- `curl` for manual checkout/checkin examples
- `sqlite3` CLI for inspecting workload databases

## Quick Start

Run a short workload and inspect the first raw `lmstat` snapshot:

```bash
PYTHONPATH=simulators/src python -m license_manager_simulators.workload.cli run \
  --duration-seconds 6 \
  --users 6 \
  --sample-interval-seconds 2 \
  --seed 11 \
  --out runs/raw-output-check

sqlite3 runs/raw-output-check/samples.sqlite \
  "select raw_output from samples order by sample_id limit 1;"
```

## Test Commands

Run the simulator test suite and lint checks:

```bash
pytest -q
ruff check .
```
