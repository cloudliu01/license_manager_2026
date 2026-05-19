from datetime import UTC, date, datetime

from license_manager_simulators.core.log_writer import MemoryLogWriter
from license_manager_simulators.core.models import FeatureDef, LicenseConfig
from license_manager_simulators.core.service import SimulatorService
from license_manager_simulators.core.store import SimulatorStore


def _service(features: dict[str, FeatureDef]) -> SimulatorService:
    config = LicenseConfig(port=27000, server_name="test-host", daemons=[], features=features)
    store = SimulatorStore.from_license(config)
    return SimulatorService(
        store=store,
        log_writer=MemoryLogWriter(),
        server_name="test-host",
        port=27000,
        config_hash="hash",
        started_at=datetime(2026, 5, 7, tzinfo=UTC),
    )


def test_checkout_return_and_status_snapshot_update_in_realtime():
    service = _service({"alpha": FeatureDef("alpha", 1, "default", date(2026, 11, 1))})

    checkout = service.checkout("alpha", "user1", "host1", 101, request_id="r1")
    assert checkout.status == "GRANTED"
    assert service.status()["features"][0]["in_use"] == 1
    assert service.status()["features"][0]["expires_at"] == "2026-11-01"

    returned = service.return_checkout(checkout.checkout_id, request_id="r2")
    assert returned.status == "RETURNED"
    assert service.status()["features"][0]["in_use"] == 0


def test_queue_counts_are_per_feature_and_dequeue_same_feature_only():
    service = _service(
        {
            "alpha": FeatureDef("alpha", 1, "default", None),
            "beta": FeatureDef("beta", 1, "default", None),
        }
    )

    first = service.checkout("alpha", "user1", "host1", 101, request_id="r1")
    queued = service.checkout("alpha", "user2", "host2", 102, request_id="r2")
    service.checkout("beta", "user3", "host3", 103, request_id="r3")

    features = {item["feature"]: item for item in service.status()["features"]}
    assert features["alpha"]["queued"] == 1
    assert features["beta"]["queued"] == 0

    service.return_checkout(first.checkout_id, request_id="r4")
    checkouts = {item["checkout_id"]: item for item in service.debug_checkouts()}
    assert checkouts[queued.checkout_id]["status"] == "GRANTED"


def test_returning_queued_checkout_does_not_release_granted_license():
    service = _service({"alpha": FeatureDef("alpha", 1, "default", None)})

    granted = service.checkout("alpha", "user1", "host1", 101, request_id="r1")
    queued = service.checkout("alpha", "user2", "host2", 102, request_id="r2")

    returned = service.return_checkout(queued.checkout_id, request_id="r3")

    assert granted.status == "GRANTED"
    assert queued.status == "QUEUED"
    assert returned.status == "RETURNED"
    feature = service.status()["features"][0]
    assert feature["in_use"] == 1
    assert feature["queued"] == 0


def test_repeated_request_id_returns_same_checkout_response():
    service = _service({"alpha": FeatureDef("alpha", 2, "default", None)})

    first = service.checkout("alpha", "user1", "host1", 101, request_id="same")
    second = service.checkout("alpha", "user1", "host1", 101, request_id="same")

    assert second.checkout_id == first.checkout_id
    assert service.status()["features"][0]["in_use"] == 1


def test_unknown_and_expired_features_are_rejected_and_logged():
    service = _service({"alpha": FeatureDef("alpha", 1, "default", date(2020, 1, 1))})

    unknown = service.checkout("missing", "user1", "host1", 101, request_id="r1")
    expired = service.checkout("alpha", "user1", "host1", 101, request_id="r2")

    assert unknown.status == "REJECTED"
    assert unknown.reason == "UNKNOWN_FEATURE"
    assert expired.status == "REJECTED"
    assert expired.reason == "FEATURE_EXPIRED"
    assert service.status()["counters"]["rejected"] == 2
