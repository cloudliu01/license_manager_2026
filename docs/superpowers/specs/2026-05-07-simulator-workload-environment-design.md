# Simulator Workload Environment Design

## Context

The simulator suite now provides a package-based `lmgrd` service, an `lmstat` CLI, real-time checkout/return state, and FlexLM-like activity logging. The next requirement is a repeatable simulation environment that creates license files, runs `lmgrd`, drives multiple synthetic users through checkout/checkin/denial scenarios, samples `lmstat` periodically into SQLite, and validates the final result.

## Goals

- Provide one command that creates a complete run directory with generated license files, `lmgrd` logs, SQLite sampling data, and a validation report.
- Simulate 10-20 users repeatedly checking out and checking in licenses for five minutes by default.
- Generate realistic mixed outcomes: granted checkouts, checkins, queued or denied capacity pressure, and requests for non-existent features.
- Keep `lmgrd` as the long-running server under test and run `lmstat` periodically to retrieve snapshots.
- Store periodic `lmstat` snapshots in SQLite as queryable tables.
- Validate the completed run using a separate verifier command.

## Non-Goals

- No real FlexLM protocol implementation.
- No GUI or dashboard.
- No distributed multi-machine load generation.
- No long-term persistence beyond the run output directory.

## User-Facing Commands

Add a workload CLI module with two subcommands:

```bash
python -m license_manager_simulators.workload.cli run \
  --duration-seconds 300 \
  --users 20 \
  --sample-interval-seconds 60 \
  --out runs/demo

python -m license_manager_simulators.workload.cli validate --run-dir runs/demo
```

Default values:

- `duration-seconds`: `300`.
- `users`: `20`.
- `sample-interval-seconds`: `60`.
- `out`: `runs/<timestamp>` if omitted.
- `seed`: optional integer; if omitted, generate and record one in `metadata.json`.

Tests should use shorter durations, but not race-prone zero-length runs. Integration tests should use approximately 6-10 seconds with a 2-second sampling interval so the runner produces multiple samples while keeping the test suite practical.

## Output Directory

Each run creates:

```text
<run-dir>/
  metadata.json
  license.dat
  lmgrd.log
  samples.sqlite
  validation.json
```

`metadata.json` records duration, users, sample interval, seed, selected free port, start time, end time, command paths, and process exit status.

## Generated License Scenario

The default generated license file should include multiple features with small capacities to force contention:

```text
PORT <free_port>
SERVER_NAME 127.0.0.1
DAEMON vendorA
FEATURE alpha 5 DAEMON vendorA
FEATURE beta 3 DAEMON vendorA
FEATURE gamma 2
```

The workload also includes one intentionally missing feature name, `missing_feature`, which is never written to the license file and is used to trigger `UNKNOWN_FEATURE` denials.

## Runtime Architecture

Add package modules:

```text
simulators/src/license_manager_simulators/workload/
  __init__.py
  cli.py
  scenario.py
  runner.py
  sampler.py
  sqlite_sink.py
  validator.py
```

Responsibilities:

- `scenario.py`: create license text, choose actions, model synthetic users, and hold deterministic random seed logic.
- `runner.py`: create output directory, choose a free port, write `license.dat`, start/stop `lmgrd`, drive user workers, invoke sampler, and write `metadata.json`.
- `sampler.py`: run `lmstat -a -i`, parse its stable text output, and pass structured snapshots to SQLite.
- `sqlite_sink.py`: own the `samples.sqlite` schema and inserts.
- `validator.py`: inspect `metadata.json`, `samples.sqlite`, and `lmgrd.log`, then write `validation.json`.
- `cli.py`: expose `run` and `validate` subcommands.

## Synthetic User Behavior

The runner should create `N` user loops, where each loop represents one user and host pair:

- User IDs: `user01` through `userNN`.
- Hosts: `host01` through `hostNN`.
- PIDs: deterministic per user plus action counter.

Each user maintains a local list of currently held checkout IDs. On each iteration, choose one action using weighted probabilities:

- 55% checkout an existing feature.
- 25% return one of the user's held checkouts, if any.
- 10% checkout an existing feature already likely to be saturated, creating queue pressure.
- 10% checkout `missing_feature`, creating `UNKNOWN_FEATURE`.

When a checkout returns `GRANTED`, the user records the checkout ID. When it returns `QUEUED`, the user does not treat it as held until it appears as granted in later snapshots; for this first workload version, queued items may remain queued until capacity frees. Before shutdown, the runner should attempt to return all locally held granted checkouts.

The iteration sleep should be small and randomized, for example 0.2-1.0 seconds, so a five-minute run produces meaningful activity without overloading the local process.

## Sampling SQLite Schema

`samples.sqlite` should contain:

```sql
create table samples (
  sample_id integer primary key autoincrement,
  sampled_at text not null,
  raw_output text not null
);

create table feature_samples (
  sample_id integer not null,
  feature text not null,
  total integer not null,
  in_use integer not null,
  queued integer not null,
  expired integer not null
);

create table checkout_samples (
  sample_id integer not null,
  feature text not null,
  user text,
  host text,
  pid integer,
  checkout_id text,
  status text,
  granted_at text
);

create table workload_events (
  event_id integer primary key autoincrement,
  event_time text not null,
  user text not null,
  action text not null,
  feature text,
  status text,
  reason text,
  checkout_id text
);
```

The sampler writes `samples`, `feature_samples`, and `checkout_samples`. The user action workers write `workload_events` for attempted checkout/return calls and responses.

## Validation Rules

The verifier reads the run directory and produces `validation.json` with `passed`, `checks`, and summary counts.

Required checks:

- `metadata.json`, `license.dat`, `lmgrd.log`, and `samples.sqlite` exist.
- SQLite has at least two samples for short test runs and at least five samples for the default five-minute run.
- Every `feature_samples` row satisfies `0 <= in_use <= total` and `queued >= 0`.
- `workload_events` includes at least one `GRANTED` checkout.
- `workload_events` includes at least one return attempt with `RETURNED`.
- `workload_events` includes at least one rejected checkout with `UNKNOWN_FEATURE`.
- The log file contains at least one `OUT:` and one `IN:` line.
- If the run generated queued responses, the log file contains `QUEUED:`.
- The `lmgrd` subprocess exited or was terminated cleanly by the runner.

The validator should not require exact equality between every workload event and every log line. The simulator is concurrent, so the validation should focus on invariants and required evidence rather than exact ordering.

## Error Handling

- If `lmgrd` fails to become healthy within a bounded timeout, stop the run and write metadata with failure details.
- If an individual checkout/return request fails due to transient HTTP errors, record a failed workload event and continue unless the run is shutting down.
- If `lmstat` sampling fails once, record a failed sample event and continue; repeated failures should make validation fail.
- The runner must always attempt to terminate `lmgrd` in `finally` cleanup.

## Testing Strategy

Unit tests:

- License scenario generation includes the expected features and excludes `missing_feature`.
- `lmstat` parser converts feature and detail lines into structured rows.
- SQLite sink inserts samples and workload events correctly.
- Validator fails missing files and passes a minimal valid run directory.

Integration tests:

- Run workload for 6-10 seconds with 6-8 users and a 2-second sample interval.
- Verify the command creates all output files.
- Run the validator command against that output directory.
- Assert validation passes and SQLite contains at least two samples.

This slightly longer integration runtime is intentional to reduce timing flakiness and allow user actions plus multiple `lmstat` samples to occur naturally.
