# Workload Simulator Usage

Use the workload simulator to generate synthetic license activity, sample `lmstat` periodically, and store raw and parsed results in SQLite.

## Run A Workload

Generate a short workload run:

```bash
conda run -n venv312_license_manager python -m license_manager_simulators.workload.cli run \
  --duration-seconds 6 \
  --users 6 \
  --sample-interval-seconds 2 \
  --seed 11 \
  --out runs/raw-output-check
```

Common options:

- `--duration-seconds`: how long synthetic users run.
- `--users`: number of synthetic users.
- `--sample-interval-seconds`: interval between `lmstat -a -i` snapshots.
- `--seed`: deterministic workload seed.
- `--out`: output run directory.

The runner starts a simulated `lmgrd`, creates user threads, samples `lmstat`, writes SQLite rows, validates the run, and stops the daemon.

## Run Directory Contents

Each run directory contains:

- `metadata.json`: run settings, paths, timing, port, and process status.
- `license.dat`: generated simulator license file.
- `lmgrd.log`: simulated daemon activity log with `OUT`, `IN`, `DENIED`, and `QUEUED` records.
- `samples.sqlite`: raw `lmstat` snapshots, parsed feature rows, parsed checkout rows, and workload events.
- `validation.json`: validation report for the generated run.

## Validate A Run

Validate a generated run directory:

```bash
conda run -n venv312_license_manager python -m license_manager_simulators.workload.cli validate \
  --run-dir runs/raw-output-check \
  --min-samples 2
```

## Inspect Raw lmstat Output

Show the first raw `lmstat` snapshot captured in SQLite:

```bash
sqlite3 runs/raw-output-check/samples.sqlite \
  "select raw_output from samples order by sample_id limit 1;"
```

List sample timestamps and raw output sizes:

```bash
sqlite3 runs/raw-output-check/samples.sqlite \
  "select sample_id, sampled_at, length(raw_output) from samples order by sample_id;"
```

Show raw output for a specific sample timestamp:

```bash
sqlite3 runs/raw-output-check/samples.sqlite \
  "select raw_output from samples where sampled_at = '2026-05-10T08:40:04.116013+00:00';"
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

## Query Examples

Feature usage over time:

```bash
sqlite3 runs/raw-output-check/samples.sqlite \
  "select sampled_at, feature, total, in_use, queued from feature_samples order by sampled_at, feature;"
```

Checkout detail rows over time:

```bash
sqlite3 runs/raw-output-check/samples.sqlite \
  "select sampled_at, feature, user, host, pid, status from checkout_samples order by sampled_at, feature, user;"
```

Compare feature summary counts against parsed detail rows:

```bash
sqlite3 runs/raw-output-check/samples.sqlite \
  "select fs.sampled_at, fs.feature, fs.in_use, coalesce(sum(cs.status='GRANTED'),0) as granted_rows, fs.queued, coalesce(sum(cs.status='QUEUED'),0) as queued_rows
   from feature_samples fs
   left join checkout_samples cs on cs.sample_id = fs.sample_id and cs.feature = fs.feature
   group by fs.sample_id, fs.sampled_at, fs.feature, fs.in_use, fs.queued
   order by fs.sampled_at, fs.feature;"
```

Workload events:

```bash
sqlite3 runs/raw-output-check/samples.sqlite \
  "select event_time, user, action, feature, status, reason from workload_events order by event_id limit 20;"
```

## Notes

- Feature names in generated workloads are synthetic, for example `alpha`, `beta`, and `gamma`.
- `samples.raw_output` stores the original stdout captured from `lmstat` for that sample.
- `feature_samples` and `checkout_samples` are parsed from `samples.raw_output` and include `sampled_at` for direct time-based analysis.
