# Docker Prometheus Grafana FlexLM Design

## Context

The project now has a FlexNet-style simulator, a local `lmutil` shim, and a `flexlm_exporter` submodule. Manual verification can expose exporter metrics at `/metrics`, but viewing trends and panels still requires a Prometheus and Grafana setup.

## Goals

- Add a `docker/` folder for local observability demos.
- Provide one compose stack that runs simulator, `flexlm_exporter`, Prometheus, and Grafana.
- Provide a second compose stack that runs only Prometheus and Grafana for connecting to an externally managed exporter.
- Auto-provision Grafana with a Prometheus datasource and a basic FlexLM dashboard.
- Keep the setup local and reproducible without changing the project core architecture.

## Non-Goals

- Do not replace the existing Python simulator workflows.
- Do not add production Kubernetes, alertmanager, authentication, or persistent production storage.
- Do not fork or modify upstream `flexlm_exporter` source.
- Do not add TimescaleDB or the future License Manager server/agent stack.

## Architecture

The full local demo stack lives under `docker/` and is started with `docker compose -f docker/docker-compose.yml up --build`. It contains four services:

- `simulator`: builds from project source and runs `simulators/wrappers/lmgrd` with a sample license file.
- `flexlm-exporter`: builds the upstream exporter submodule, copies in the project `lmutil` shim, and scrapes `27000@simulator`.
- `prometheus`: scrapes `flexlm-exporter:9319`.
- `grafana`: exposes `http://localhost:3000` and auto-loads a Prometheus datasource plus a FlexLM dashboard.

The lightweight stack lives in `docker/docker-compose.no_sim_no_exporter.yml` and contains only:

- `prometheus`
- `grafana`

That stack is for users who already run a simulator/exporter elsewhere. Its Prometheus config should default to a host-reachable exporter target such as `host.docker.internal:9319`.

## Files

Create these files:

- `docker/docker-compose.yml`: full demo stack.
- `docker/docker-compose.no_sim_no_exporter.yml`: Prometheus and Grafana only.
- `docker/simulator/Dockerfile`: Python simulator image.
- `docker/simulator/license.dat`: sample features, reservations, and expirations.
- `docker/flexlm-exporter/Dockerfile`: local exporter image using the submodule and shim.
- `docker/flexlm-exporter/licenses.yml`: exporter config targeting `27000@simulator`.
- `docker/flexlm-exporter/lmutil`: container-local shim compatible with the exporter image.
- `docker/prometheus/prometheus.yml`: full-stack scrape config.
- `docker/prometheus/prometheus.no_sim_no_exporter.yml`: host-exporter scrape config.
- `docker/grafana/provisioning/datasources/prometheus.yml`: datasource provisioning.
- `docker/grafana/provisioning/dashboards/dashboards.yml`: dashboard provisioning.
- `docker/grafana/dashboards/flexlm-simulator.json`: basic dashboard.
- `docker/README.md`: run, view, and stop instructions.

Update:

- `README.md`: link to `docker/README.md`.

## Data Flow

Full stack:

1. `simulator` exposes FlexNet-style status on port `27000` inside the Docker network.
2. `flexlm-exporter` runs `lmutil lmstat` through the container-local shim.
3. The shim calls simulator-compatible logic and returns FlexNet-style output.
4. `flexlm_exporter` exposes metrics on `:9319`.
5. `prometheus` scrapes `http://flexlm-exporter:9319/metrics`.
6. `grafana` queries Prometheus and displays the preloaded dashboard.

Prometheus/Grafana-only stack:

1. User runs exporter outside this compose stack.
2. Prometheus scrapes `host.docker.internal:9319` by default.
3. Grafana shows the same dashboard using the same datasource.

## Dashboard Panels

The initial dashboard should include these simple panels:

- Server status: `flexlm_server_status`.
- Feature issued vs used: `flexlm_feature_issued` and `flexlm_feature_used`.
- Reservations: `flexlm_feature_reserved_groups` and `flexlm_feature_reserved_host`.
- User usage by version: `flexlm_feature_used_users` grouped by feature, user, and version.
- Expiration: `flexlm_feature_expiration_seconds` rendered as feature expiration values.

The dashboard should prioritize showing that data flows through the stack. It does not need polished production visualization.

## Ports

- Simulator: `27000`.
- flexlm_exporter: `9319`.
- Prometheus: `9090`.
- Grafana: `3000`.

If these ports are busy, users can override them by editing the compose file.

## Verification

The implementation should verify:

- `docker compose -f docker/docker-compose.yml config` succeeds.
- `docker compose -f docker/docker-compose.no_sim_no_exporter.yml config` succeeds.
- The full stack can start with `docker compose -f docker/docker-compose.yml up --build -d`.
- Prometheus target for `flexlm-exporter` is reachable.
- `curl http://127.0.0.1:9319/metrics` includes `flexlm_feature_used`, `flexlm_feature_reserved_groups`, and `flexlm_feature_used_users`.
- Grafana is reachable at `http://127.0.0.1:3000`.

If Docker is unavailable, verification should stop with a clear prerequisite note rather than claiming the stack works.

## Risks

- Docker networking differs by platform; `host.docker.internal` is reliable on Docker Desktop, but Linux users may need a different host-gateway configuration.
- The dashboard JSON can become stale if metric names change upstream.
- The full demo stack is for local observability only and should not be treated as production monitoring infrastructure.

## Approved Scope

Build the recommended full Docker demo stack plus a Prometheus/Grafana-only compose file. Keep the changes confined to `docker/` and README documentation unless a small supporting test or script is required.
