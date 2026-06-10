# Docker Observability Stack

This folder provides local Docker Compose stacks for viewing `flexlm_exporter` simulator metrics in Prometheus and Grafana.

## Full Demo Stack

Starts the simulator, `flexlm_exporter`, Prometheus, and Grafana:

```bash
docker compose -f docker/docker-compose.yml up --build
```

Open:

- Grafana: <http://127.0.0.1:3000> (`admin` / `admin`)
- Prometheus: <http://127.0.0.1:9090>
- flexlm_exporter metrics: <http://127.0.0.1:9319/metrics>
- Simulator health: <http://127.0.0.1:27000/v1/health>

The Grafana dashboard is provisioned under `License Manager / FlexLM Simulator`.

## Prometheus And Grafana Only

Use this when `flexlm_exporter` is already running outside Docker on port `9319`:

```bash
docker compose -f docker/docker-compose.no_sim_no_exporter.yml up
```

Prometheus scrapes `host.docker.internal:9319` by default.

## Stop

```bash
docker compose -f docker/docker-compose.yml down
docker compose -f docker/docker-compose.no_sim_no_exporter.yml down
```

## Notes

- This stack is for local demos, not production monitoring.
- Prometheus uses its native local time-series database.
- TimescaleDB is not required for this stack. Grafana can add TimescaleDB/PostgreSQL later as a separate datasource for future server/client telemetry.
