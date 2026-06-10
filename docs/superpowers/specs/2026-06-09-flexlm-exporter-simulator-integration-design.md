# Flexlm Exporter Simulator Integration Design

## Context

The repository already contains a FlexNet-style simulator under `simulators/` with `lmgrd` and `lmstat` wrappers, workload generation, and tests for FlexNet-format output. The core project specs describe simulator-backed integration tests for future server and agent observability work.

`mjtrangoni/flexlm_exporter` is a Prometheus exporter that shells out to `lmutil lmstat` and parses FlexNet-style `lmstat` output. It supports `--path.lmutil`, so this project can verify compatibility without changing the exporter source.

## Goals

- Add `flexlm_exporter` as an external Git submodule.
- Prove whether the existing simulator can be scraped through `flexlm_exporter`.
- Verify exporter collection with user, reservation, and version monitoring enabled.
- Keep changes small and avoid broad repository restructuring.
- Document a repeatable local verification workflow.

## Non-Goals

- Do not fork or edit `flexlm_exporter` source.
- Do not reorganize `server/`, `client/`, or `simulators/` into the future `src/` layout yet.
- Do not add Prometheus, Grafana, or TimescaleDB runtime infrastructure as part of this step.
- Do not implement the final License Manager server or agent control plane.

## Architecture

External code will live under `third_party/flexlm_exporter` as a Git submodule. Project-owned integration assets will live outside the submodule, under a small tools/docs area such as `tools/flexlm_exporter/` and `docs/`.

The verification path is:

1. Start the existing simulator with `simulators/wrappers/lmgrd` and a local license file.
2. Generate at least one checkout through the simulator HTTP API.
3. Start `flexlm_exporter` from the submodule.
4. Point exporter `--path.lmutil` to a project-owned shim.
5. Configure exporter with `license_server: <port>@127.0.0.1`.
6. Scrape exporter `/metrics` and assert expected FlexLM metrics are present.

## Components

### Submodule

`third_party/flexlm_exporter` tracks `https://github.com/mjtrangoni/flexlm_exporter.git`. The parent repository owns only the submodule pointer and integration files.

### lmutil Shim

The shim accepts the command shape used by the exporter:

```text
lmutil lmstat -v
lmutil lmstat -c <port@host> -a
lmutil lmstat -c <port@host> -i
```

For `lmstat`, it forwards arguments to `simulators/wrappers/lmstat`. For `lmstat -v`, it returns a FlexNet-like version line matching the exporter parser. Because `flexlm_exporter` calls `lmstat -a` for usage and `lmstat -i` for inventory, while the simulator exposes detailed user, reservation, and inventory output when both flags are present, the shim normalizes either single flag to `-a -i`. Unsupported subcommands fail with a clear non-zero exit.

### Exporter Config

A sample YAML config defines one simulator license target:

```yaml
licenses:
  - name: simulator
    license_server: 27000@127.0.0.1
    monitor_users: true
    monitor_reservations: true
    monitor_versions: true
```

The verification workflow may generate the port dynamically to avoid conflicts.

### Verification Workflow

A small script or documented command sequence starts `lmgrd`, waits for health, creates checkout activity, starts the exporter, scrapes metrics, and stops all child processes. Success means the scrape includes at least:

- `flexlm_server_status` for the simulator target.
- `flexlm_feature_issued` for a known feature.
- `flexlm_feature_used` reflecting the checkout.
- `flexlm_feature_used_users` with a `version` label for an active checkout.
- `flexlm_feature_reserved_groups` or `flexlm_feature_reserved_host` when the simulator scenario includes reservations.
- `flexlm_lmstat_info` with parsed `lmstat -v` metadata.

## Compatibility Notes

The simulator already emits output that appears aligned with the exporter's core regex expectations: license server status, server status, vendor daemon status, feature usage summaries, detail rows with versions, and expiration rows. The most important compatibility gap is executable shape: the exporter runs `lmutil lmstat`, while this project currently exposes `lmstat` directly.

Reservation monitoring requires simulator output that includes FlexNet-style reservation lines, such as `1 license for GROUP engineering` or `1 license for HOST buildhost1`, under the relevant feature section. The current simulator does not appear to emit reservation lines, so implementation must either add a minimal reservation scenario to the simulator output or document reservation verification as blocked until option-file reservation support exists.

If the exporter fails to parse a metric, the fix should prefer improving simulator output fidelity or the shim behavior in this repository. The submodule source should remain unmodified unless a deliberate upstream patch is planned separately.

## Repository Organization

This step intentionally avoids the larger `src/server`, `src/agent`, `src/common` refactor described in `specs/003-license-manager-core/plan.md`. The current simulator remains in `simulators/` because it is already coherent and tested. The exporter is external tooling and should not be mixed into application package code.

A future reorganization can move application code toward the spec layout while preserving:

- `simulators/` for local FlexNet-compatible simulation.
- `third_party/` for external source dependencies.
- `tools/` for local integration scripts and shims.
- `docs/` for user-facing workflows.

## Testing

Verification should include a local end-to-end check that builds or runs `flexlm_exporter`, starts the simulator, scrapes `/metrics`, and checks metric names and values with `monitor_users`, `monitor_reservations`, and `monitor_versions` enabled. If Go tooling is unavailable, the workflow should fail with a clear prerequisite message rather than silently skipping compatibility verification.

Existing simulator tests should continue to pass after adding the shim and documentation.

## Risks

- `flexlm_exporter` parser behavior may change as the submodule pointer advances.
- The simulator is FlexNet-style, not a real FlexNet wire-protocol implementation; this integration verifies exporter parsing, not real FlexNet protocol behavior.
- Dynamic timestamps in user metrics can make exact metric text brittle, so checks should focus on stable metric names, labels, and feature counts.
- Reservation metrics will not be emitted unless the simulator produces reservation lines that match `flexlm_exporter` parser expectations.

## Implementation Approval

The approved implementation scope is the small integration path: submodule, shim, sample config/docs, and repeatable verification. Broad repository refactoring is deferred.
