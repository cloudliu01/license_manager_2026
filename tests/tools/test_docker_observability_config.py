from __future__ import annotations

from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]


def _has_service_key(compose: str, service: str) -> bool:
    return f"{service}:" in {line.strip() for line in compose.splitlines()}


def _has_port_mapping(compose: str, mapping: str) -> bool:
    for line in compose.splitlines():
        port = line.strip().removeprefix("-").strip().strip("\"'")
        if port == mapping:
            return True
    return False


def test_full_compose_declares_expected_services_and_ports():
    compose = (ROOT / "docker" / "docker-compose.yml").read_text(encoding="utf-8")

    for service in ["simulator", "flexlm-exporter", "prometheus", "grafana"]:
        assert _has_service_key(compose, service)
    for port in ["27000:27000", "9319:9319", "9090:9090", "3000:3000"]:
        assert _has_port_mapping(compose, port)


def test_no_sim_compose_only_declares_prometheus_and_grafana_services():
    compose = (ROOT / "docker" / "docker-compose.no_sim_no_exporter.yml").read_text(encoding="utf-8")

    assert _has_service_key(compose, "prometheus")
    assert _has_service_key(compose, "grafana")
    assert not _has_service_key(compose, "simulator")
    assert not _has_service_key(compose, "flexlm-exporter")


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


def test_simulator_image_seeds_observability_checkout():
    dockerfile = (ROOT / "docker" / "simulator" / "Dockerfile").read_text(encoding="utf-8")
    startup_script = ROOT / "docker" / "simulator" / "start-with-seed-checkout.sh"

    assert "start-with-seed-checkout.sh" in dockerfile
    assert startup_script.exists()
    script = startup_script.read_text(encoding="utf-8")
    assert "/v1/checkout" in script
    assert "seed-observability-checkout" in script
