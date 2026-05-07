from datetime import UTC, datetime

from fastapi.testclient import TestClient

from license_manager_simulators.core.log_writer import MemoryLogWriter
from license_manager_simulators.core.models import FeatureDef, LicenseConfig
from license_manager_simulators.core.service import SimulatorService
from license_manager_simulators.core.store import SimulatorStore
from license_manager_simulators.lmgrd.app import create_app


def _client() -> TestClient:
    config = LicenseConfig(
        port=27000,
        server_name="test-host",
        daemons=[],
        features={"alpha": FeatureDef("alpha", 1, "default", None)},
    )
    service = SimulatorService(
        store=SimulatorStore.from_license(config),
        log_writer=MemoryLogWriter(),
        server_name="test-host",
        port=27000,
        config_hash="hash",
        started_at=datetime(2026, 5, 7, tzinfo=UTC),
    )
    return TestClient(create_app(service))


def test_checkout_return_and_debug_endpoints_expose_realtime_state():
    client = _client()

    assert client.get("/v1/health").json()["feature_count"] == 1

    checkout = client.post(
        "/v1/checkout",
        json={"request_id": "r1", "feature": "alpha", "user": "user1", "host": "host1", "pid": 101},
    ).json()
    assert checkout["status"] == "GRANTED"

    status = client.get("/v1/status").json()
    assert status["features"][0]["in_use"] == 1

    debug = client.get("/v1/debug/checkouts", params={"status": "GRANTED"}).json()
    assert debug["checkouts"][0]["checkout_id"] == checkout["checkout_id"]

    returned = client.post("/v1/return", json={"request_id": "r2", "checkout_id": checkout["checkout_id"]}).json()
    assert returned["status"] == "RETURNED"
    assert client.get("/v1/status").json()["features"][0]["in_use"] == 0


def test_debug_queue_filters_by_feature():
    client = _client()
    client.post(
        "/v1/checkout",
        json={"request_id": "r1", "feature": "alpha", "user": "user1", "host": "host1", "pid": 101},
    )
    queued = client.post(
        "/v1/checkout",
        json={"request_id": "r2", "feature": "alpha", "user": "user2", "host": "host2", "pid": 102},
    ).json()

    queue = client.get("/v1/debug/queue", params={"feature": "alpha"}).json()
    assert queue["queue"][0]["checkout_id"] == queued["checkout_id"]
