# Docker Prometheus Grafana FlexLM Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a Docker-based local observability stack that can show `flexlm_exporter` simulator metrics in Prometheus and Grafana.

**Architecture:** Add a self-contained `docker/` folder with a full compose stack and a Prometheus/Grafana-only compose stack. The full stack runs the Python simulator, a locally built `flexlm_exporter`, Prometheus, and Grafana with provisioned datasource/dashboard files. The no-simulator compose stack reuses Prometheus/Grafana provisioning and scrapes a host-managed exporter at `host.docker.internal:9319`.

**Tech Stack:** Docker Compose, Prometheus, Grafana provisioning, Python simulator package, Go-built `flexlm_exporter`, pytest for static config tests.

---

## File Structure

- Create: `docker/docker-compose.yml` - full local demo stack.
- Create: `docker/docker-compose.no_sim_no_exporter.yml` - Prometheus and Grafana only.
- Create: `docker/simulator/Dockerfile` - Python simulator container image.
- Create: `docker/simulator/license.dat` - sample simulator license with usage, reservations, and expirations.
- Create: `docker/flexlm-exporter/Dockerfile` - exporter image built from local submodule with a container-local shim.
- Create: `docker/flexlm-exporter/licenses.yml` - exporter config targeting `27000@simulator`.
- Create: `docker/flexlm-exporter/lmutil` - container-local `lmutil` shim.
- Create: `docker/prometheus/prometheus.yml` - full stack scrape config.
- Create: `docker/prometheus/prometheus.no_sim_no_exporter.yml` - host exporter scrape config.
- Create: `docker/grafana/provisioning/datasources/prometheus.yml` - Grafana datasource provisioning.
- Create: `docker/grafana/provisioning/dashboards/dashboards.yml` - Grafana dashboard provider.
- Create: `docker/grafana/dashboards/flexlm-simulator.json` - basic dashboard panels.
- Create: `docker/README.md` - run/view/stop instructions.
- Create: `tests/tools/test_docker_observability_config.py` - static tests for compose/provisioning files.
- Modify: `README.md` - link to Docker observability docs.

Do not commit unless explicitly asked.

---

### Task 1: Add Static Docker Config Tests

**Files:**
- Create: `tests/tools/test_docker_observability_config.py`

- [ ] **Step 1: Write failing tests**

Create `tests/tools/test_docker_observability_config.py`:

```python
from __future__ import annotations

from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]


def test_full_compose_declares_expected_services_and_ports():
    compose = (ROOT / "docker" / "docker-compose.yml").read_text(encoding="utf-8")

    for service in ["simulator:", "flexlm-exporter:", "prometheus:", "grafana:"]:
        assert service in compose
    for port in ['"27000:27000"', '"9319:9319"', '"9090:9090"', '"3000:3000"']:
        assert port in compose


def test_no_sim_compose_only_declares_prometheus_and_grafana_services():
    compose = (ROOT / "docker" / "docker-compose.no_sim_no_exporter.yml").read_text(encoding="utf-8")

    assert "prometheus:" in compose
    assert "grafana:" in compose
    assert "simulator:" not in compose
    assert "flexlm-exporter:" not in compose


def test_prometheus_configs_target_expected_exporters():
    full = (ROOT / "docker" / "prometheus" / "prometheus.yml").read_text(encoding="utf-8")
    no_sim = (ROOT / "docker" / "prometheus" / "prometheus.no_sim_no_exporter.yml").read_text(encoding="utf-8")

    assert "flexlm-exporter:9319" in full
    assert "host.docker.internal:9319" in no_sim


def test_grafana_dashboard_contains_core_flexlm_metrics():
    dashboard = (ROOT / "docker" / "grafana" / "dashboards" / "flexlm-simulator.json").read_text(
        encoding="utf-8"
    )

    for metric in [
        "flexlm_server_status",
        "flexlm_feature_issued",
        "flexlm_feature_used",
        "flexlm_feature_reserved_groups",
        "flexlm_feature_reserved_host",
        "flexlm_feature_used_users",
        "flexlm_feature_expiration_seconds",
    ]:
        assert metric in dashboard
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m pytest tests/tools/test_docker_observability_config.py -q`

Expected: FAIL because the `docker/` files do not exist.

---

### Task 2: Add Docker Images And Compose Files

**Files:**
- Create: `docker/docker-compose.yml`
- Create: `docker/docker-compose.no_sim_no_exporter.yml`
- Create: `docker/simulator/Dockerfile`
- Create: `docker/simulator/license.dat`
- Create: `docker/flexlm-exporter/Dockerfile`
- Create: `docker/flexlm-exporter/licenses.yml`
- Create: `docker/flexlm-exporter/lmutil`

- [ ] **Step 1: Create simulator Dockerfile**

Create `docker/simulator/Dockerfile`:

```dockerfile
FROM python:3.11-slim

WORKDIR /app

COPY simulators/pyproject.toml /app/simulators/pyproject.toml
COPY simulators/src /app/simulators/src
COPY simulators/wrappers /app/simulators/wrappers
COPY docker/simulator/license.dat /demo/license.dat

RUN pip install --no-cache-dir -e /app/simulators

EXPOSE 27000

CMD ["/app/simulators/wrappers/lmgrd", "-c", "/demo/license.dat", "-l", "/demo/lmgrd.log"]
```

- [ ] **Step 2: Create simulator license file**

Create `docker/simulator/license.dat`:

```text
PORT 27000
DAEMON vendorA
FEATURE alpha 2 DAEMON vendorA EXP 2026-11-01 RESERVE 2 GROUP engineering RESERVE 1 HOST buildhost1
FEATURE beta 5 DAEMON vendorA EXP 2027-01-15
```

- [ ] **Step 3: Create exporter Dockerfile**

Create `docker/flexlm-exporter/Dockerfile`:

```dockerfile
FROM golang:1.26 AS builder

WORKDIR /src
COPY third_party/flexlm_exporter/ ./
RUN go build -o /out/flexlm_exporter .

FROM python:3.11-slim

WORKDIR /app

COPY --from=builder /out/flexlm_exporter /usr/local/bin/flexlm_exporter
COPY simulators/pyproject.toml /app/simulators/pyproject.toml
COPY simulators/src /app/simulators/src
COPY simulators/wrappers /app/simulators/wrappers
COPY docker/flexlm-exporter/lmutil /usr/local/bin/lmutil
COPY docker/flexlm-exporter/licenses.yml /etc/flexlm-exporter/licenses.yml

RUN pip install --no-cache-dir -e /app/simulators && chmod +x /usr/local/bin/lmutil

EXPOSE 9319

CMD ["flexlm_exporter", "--web.listen-address=0.0.0.0:9319", "--path.lmutil=/usr/local/bin/lmutil", "--path.config=/etc/flexlm-exporter/licenses.yml"]
```

- [ ] **Step 4: Create container-local lmutil shim**

Create `docker/flexlm-exporter/lmutil`:

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

if [[ ${has_a} -eq 1 && ${has_i} -eq 0 ]]; then
  args+=("-i")
elif [[ ${has_a} -eq 0 && ${has_i} -eq 1 ]]; then
  args+=("-a")
fi

exec /app/simulators/wrappers/lmstat "${args[@]}"
```

- [ ] **Step 5: Create exporter license config**

Create `docker/flexlm-exporter/licenses.yml`:

```yaml
licenses:
  - name: simulator
    license_server: 27000@simulator
    monitor_users: true
    monitor_reservations: true
    monitor_versions: true
```

- [ ] **Step 6: Create full compose stack**

Create `docker/docker-compose.yml`:

```yaml
services:
  simulator:
    build:
      context: ..
      dockerfile: docker/simulator/Dockerfile
    ports:
      - "27000:27000"

  flexlm-exporter:
    build:
      context: ..
      dockerfile: docker/flexlm-exporter/Dockerfile
    depends_on:
      - simulator
    ports:
      - "9319:9319"

  prometheus:
    image: prom/prometheus:v3.7.3
    depends_on:
      - flexlm-exporter
    command:
      - "--config.file=/etc/prometheus/prometheus.yml"
    volumes:
      - ./prometheus/prometheus.yml:/etc/prometheus/prometheus.yml:ro
    ports:
      - "9090:9090"

  grafana:
    image: grafana/grafana:12.3.0
    depends_on:
      - prometheus
    environment:
      GF_SECURITY_ADMIN_USER: admin
      GF_SECURITY_ADMIN_PASSWORD: admin
      GF_USERS_ALLOW_SIGN_UP: "false"
    volumes:
      - ./grafana/provisioning:/etc/grafana/provisioning:ro
      - ./grafana/dashboards:/var/lib/grafana/dashboards:ro
    ports:
      - "3000:3000"
```

- [ ] **Step 7: Create Prometheus/Grafana-only compose stack**

Create `docker/docker-compose.no_sim_no_exporter.yml`:

```yaml
services:
  prometheus:
    image: prom/prometheus:v3.7.3
    command:
      - "--config.file=/etc/prometheus/prometheus.yml"
    volumes:
      - ./prometheus/prometheus.no_sim_no_exporter.yml:/etc/prometheus/prometheus.yml:ro
    ports:
      - "9090:9090"
    extra_hosts:
      - "host.docker.internal:host-gateway"

  grafana:
    image: grafana/grafana:12.3.0
    depends_on:
      - prometheus
    environment:
      GF_SECURITY_ADMIN_USER: admin
      GF_SECURITY_ADMIN_PASSWORD: admin
      GF_USERS_ALLOW_SIGN_UP: "false"
    volumes:
      - ./grafana/provisioning:/etc/grafana/provisioning:ro
      - ./grafana/dashboards:/var/lib/grafana/dashboards:ro
    ports:
      - "3000:3000"
```

- [ ] **Step 8: Make container shim executable**

Run: `chmod +x docker/flexlm-exporter/lmutil`

Expected: command exits with status `0`.

- [ ] **Step 9: Run static tests again**

Run: `python -m pytest tests/tools/test_docker_observability_config.py -q`

Expected: all tests pass.

---

### Task 3: Add Prometheus And Grafana Provisioning

**Files:**
- Create: `docker/prometheus/prometheus.yml`
- Create: `docker/prometheus/prometheus.no_sim_no_exporter.yml`
- Create: `docker/grafana/provisioning/datasources/prometheus.yml`
- Create: `docker/grafana/provisioning/dashboards/dashboards.yml`
- Create: `docker/grafana/dashboards/flexlm-simulator.json`

- [ ] **Step 1: Create full-stack Prometheus config**

Create `docker/prometheus/prometheus.yml`:

```yaml
global:
  scrape_interval: 5s

scrape_configs:
  - job_name: flexlm-exporter
    static_configs:
      - targets:
          - flexlm-exporter:9319
```

- [ ] **Step 2: Create no-simulator Prometheus config**

Create `docker/prometheus/prometheus.no_sim_no_exporter.yml`:

```yaml
global:
  scrape_interval: 5s

scrape_configs:
  - job_name: flexlm-exporter-host
    static_configs:
      - targets:
          - host.docker.internal:9319
```

- [ ] **Step 3: Create Grafana datasource provisioning**

Create `docker/grafana/provisioning/datasources/prometheus.yml`:

```yaml
apiVersion: 1

datasources:
  - name: Prometheus
    uid: Prometheus
    type: prometheus
    access: proxy
    url: http://prometheus:9090
    isDefault: true
```

- [ ] **Step 4: Create Grafana dashboard provider**

Create `docker/grafana/provisioning/dashboards/dashboards.yml`:

```yaml
apiVersion: 1

providers:
  - name: FlexLM
    orgId: 1
    folder: License Manager
    type: file
    disableDeletion: false
    editable: true
    options:
      path: /var/lib/grafana/dashboards
```

- [ ] **Step 5: Create dashboard JSON**

Create `docker/grafana/dashboards/flexlm-simulator.json` with panels for these PromQL expressions:

```json
{
  "annotations": {"list": []},
  "editable": true,
  "fiscalYearStartMonth": 0,
  "graphTooltip": 0,
  "links": [],
  "panels": [
    {
      "datasource": {"type": "prometheus", "uid": "Prometheus"},
      "fieldConfig": {"defaults": {}, "overrides": []},
      "gridPos": {"h": 4, "w": 6, "x": 0, "y": 0},
      "id": 1,
      "options": {"reduceOptions": {"calcs": ["lastNotNull"], "fields": "", "values": false}},
      "targets": [{"expr": "flexlm_server_status", "legendFormat": "{{app}} {{fqdn}}:{{port}}"}],
      "title": "Server Status",
      "type": "stat"
    },
    {
      "datasource": {"type": "prometheus", "uid": "Prometheus"},
      "fieldConfig": {"defaults": {}, "overrides": []},
      "gridPos": {"h": 8, "w": 12, "x": 6, "y": 0},
      "id": 2,
      "targets": [
        {"expr": "flexlm_feature_issued", "legendFormat": "issued {{name}}"},
        {"expr": "flexlm_feature_used", "legendFormat": "used {{name}}"}
      ],
      "title": "Feature Issued vs Used",
      "type": "timeseries"
    },
    {
      "datasource": {"type": "prometheus", "uid": "Prometheus"},
      "fieldConfig": {"defaults": {}, "overrides": []},
      "gridPos": {"h": 8, "w": 12, "x": 0, "y": 8},
      "id": 3,
      "targets": [
        {"expr": "flexlm_feature_reserved_groups", "legendFormat": "group {{group}} {{name}}"},
        {"expr": "flexlm_feature_reserved_host", "legendFormat": "host {{host}} {{name}}"}
      ],
      "title": "Reservations",
      "type": "timeseries"
    },
    {
      "datasource": {"type": "prometheus", "uid": "Prometheus"},
      "fieldConfig": {"defaults": {}, "overrides": []},
      "gridPos": {"h": 8, "w": 12, "x": 12, "y": 8},
      "id": 4,
      "targets": [{"expr": "flexlm_feature_used_users", "legendFormat": "{{name}} {{user}} {{version}}"}],
      "title": "User Usage By Version",
      "type": "timeseries"
    },
    {
      "datasource": {"type": "prometheus", "uid": "Prometheus"},
      "fieldConfig": {"defaults": {}, "overrides": []},
      "gridPos": {"h": 8, "w": 12, "x": 0, "y": 16},
      "id": 5,
      "targets": [{"expr": "flexlm_feature_expiration_seconds", "legendFormat": "{{name}} {{version}}"}],
      "title": "Feature Expiration Seconds",
      "type": "timeseries"
    }
  ],
  "refresh": "5s",
  "schemaVersion": 41,
  "tags": ["flexlm", "simulator"],
  "templating": {"list": []},
  "time": {"from": "now-15m", "to": "now"},
  "timepicker": {},
  "timezone": "browser",
  "title": "FlexLM Simulator",
  "uid": "flexlm-simulator",
  "version": 1
}
```

- [ ] **Step 6: Run static tests**

Run: `python -m pytest tests/tools/test_docker_observability_config.py -q`

Expected: all tests pass.

---

### Task 4: Add Documentation

**Files:**
- Create: `docker/README.md`
- Modify: `README.md`

- [ ] **Step 1: Create Docker README**

Create `docker/README.md`:

```markdown
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
```

- [ ] **Step 2: Link Docker docs from root README**

Add this bullet under root `README.md` `## Documentation`:

```markdown
- [Docker observability stack](docker/README.md): run simulator, `flexlm_exporter`, Prometheus, and Grafana locally.
```

- [ ] **Step 3: Verify docs paths exist**

Run:

```bash
python - <<'PY'
from pathlib import Path
for path in [Path('docker/README.md'), Path('docker/docker-compose.yml'), Path('docker/docker-compose.no_sim_no_exporter.yml')]:
    assert path.exists(), path
print('docker docs paths ok')
PY
```

Expected: `docker docs paths ok`.

---

### Task 5: Verify Docker Configuration And Stack

**Files:**
- No new files.

- [ ] **Step 1: Run static tests**

Run: `python -m pytest tests/tools/test_docker_observability_config.py -q`

Expected: all tests pass.

- [ ] **Step 2: Validate compose files**

Run: `docker compose -f docker/docker-compose.yml config`

Expected: exits `0` and prints normalized compose config.

Run: `docker compose -f docker/docker-compose.no_sim_no_exporter.yml config`

Expected: exits `0` and prints normalized compose config.

If Docker is unavailable, stop and report the missing prerequisite.

- [ ] **Step 3: Start full stack**

Run: `docker compose -f docker/docker-compose.yml up --build -d`

Expected: all four services start.

- [ ] **Step 4: Verify metrics and UIs**

Run:

```bash
python - <<'PY'
import time
from urllib.request import urlopen

checks = {
    'exporter metrics': 'http://127.0.0.1:9319/metrics',
    'prometheus': 'http://127.0.0.1:9090/-/ready',
    'grafana': 'http://127.0.0.1:3000/api/health',
}
for name, url in checks.items():
    last = None
    for _ in range(60):
        try:
            with urlopen(url, timeout=1) as response:
                body = response.read().decode('utf-8', errors='replace')
                print(f'{name}: ok')
                if name == 'exporter metrics':
                    for needle in ['flexlm_feature_used', 'flexlm_feature_reserved_groups', 'flexlm_feature_used_users']:
                        assert needle in body, needle
                break
        except Exception as exc:
            last = exc
            time.sleep(1)
    else:
        raise SystemExit(f'{name} failed: {last}')
PY
```

Expected: prints `exporter metrics: ok`, `prometheus: ok`, and `grafana: ok`.

- [ ] **Step 5: Stop full stack**

Run: `docker compose -f docker/docker-compose.yml down`

Expected: containers stop and are removed.

- [ ] **Step 6: Run repository checks**

Run: `ruff check .`

Expected: `All checks passed!`

Run: `git status --short`

Expected: only intended Docker docs/config/test files and prior spec/plan docs are changed.
