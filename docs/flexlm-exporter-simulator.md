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
flexlm_exporter simulator verification passed
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
