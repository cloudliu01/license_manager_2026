from datetime import UTC, datetime

from fastapi.testclient import TestClient

from license_manager_simulators.core.log_writer import MemoryLogWriter
from license_manager_simulators.core.models import FeatureDef, LicenseConfig
from license_manager_simulators.core.service import SimulatorService
from license_manager_simulators.core.store import SimulatorStore
from license_manager_simulators.lmgrd.app import create_app


def _client(total: int = 4) -> TestClient:
    config = LicenseConfig(
        port=27000,
        server_name="test-host",
        daemons=[],
        features={"alpha": FeatureDef("alpha", total, "default", None)},
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
        json={
            "request_id": "r1",
            "feature": "alpha",
            "user": "user1",
            "host": "host1",
            "pid": 101,
            "quantity": 3,
            "info": "info_APS_26",
        },
    ).json()
    assert checkout["status"] == "GRANTED"
    assert checkout["quantity"] == 3

    status = client.get("/v1/status").json()
    assert status["features"][0]["in_use"] == 3

    debug = client.get("/v1/debug/checkouts", params={"status": "GRANTED"}).json()
    assert debug["checkouts"][0]["checkout_id"] == checkout["checkout_id"]
    assert debug["checkouts"][0]["quantity"] == 3
    assert debug["checkouts"][0]["info"] == "info_APS_26"

    returned = client.post("/v1/return", json={"request_id": "r2", "checkout_id": checkout["checkout_id"]}).json()
    assert returned["status"] == "RETURNED"
    assert client.get("/v1/status").json()["features"][0]["in_use"] == 0


def test_debug_queue_filters_by_feature():
    client = _client(total=1)
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


def test_checkout_denied_when_no_queue_and_quota_reached():
    writer = MemoryLogWriter()
    config = LicenseConfig(
        port=27000,
        server_name="test-host",
        daemons=["dummy_daemon"],
        features={"dummy_feat": FeatureDef("dummy_feat", 1, "dummy_daemon", None)},
    )
    service = SimulatorService(
        store=SimulatorStore.from_license(config),
        log_writer=writer,
        server_name="test-host",
        port=27000,
        config_hash="hash",
        started_at=datetime(2026, 5, 7, tzinfo=UTC),
    )
    client = TestClient(create_app(service))

    # 1. 成功借出唯一 1 个席位
    first = client.post(
        "/v1/checkout",
        json={"feature": "dummy_feat", "user": "alice", "host": "host_a", "pid": 1001},
    ).json()
    assert first["status"] == "GRANTED"

    # 检查状态：total=1, in_use=1, available=0, denied=0
    status = client.get("/v1/status").json()
    feat_stat = status["features"][0]
    assert feat_stat["total"] == 1
    assert feat_stat["in_use"] == 1
    assert feat_stat["available"] == 0
    assert feat_stat["denied"] == 0

    # 2. 第二个请求 checkout，指定 allow_queue=False -> 预期 DENIED
    second = client.post(
        "/v1/checkout",
        json={"feature": "dummy_feat", "user": "bob", "host": "host_b", "pid": 1002, "allow_queue": False},
    ).json()
    assert second["status"] == "DENIED"
    assert second["reason"] == "LICENSE_LIMIT_REACHED"

    # 检查状态：denied 统计自增为 1
    status_after_deny = client.get("/v1/status").json()
    assert status_after_deny["features"][0]["denied"] == 1

    # 验证 log writer 写入了标准 DENIED 行
    denied_logs = [line for line in writer.lines if "DENIED:" in line]
    assert len(denied_logs) == 1
    assert 'DENIED:\t"dummy_feat"\tbob@host_b' in denied_logs[0]
    assert "Licensed number of users already reached." in denied_logs[0]

    # 3. alice 归还（测试 /v1/checkin 别名）
    checkin_res = client.post(
        "/v1/checkin",
        json={"checkout_id": first["checkout_id"]},
    ).json()
    assert checkin_res["status"] == "RETURNED"

    # 状态恢复：in_use=0, available=1
    status_after_in = client.get("/v1/status").json()
    assert status_after_in["features"][0]["in_use"] == 0
    assert status_after_in["features"][0]["available"] == 1

