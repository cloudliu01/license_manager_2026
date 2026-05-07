from license_manager_simulators.workload.sampler import parse_lmstat_output


def test_parse_lmstat_output_extracts_feature_and_checkout_rows():
    output = """
LMSTAT_SIM_FORMAT_VERSION=1
server: 127.0.0.1 port: 27000
timestamp: 2026-05-07T00:00:00+00:00
feature: alpha total=5 in_use=2 queued=1 expired=false
detail: alpha user=user01 host=host01 pid=101 checkout_id=co-1 status=GRANTED granted_at=2026-05-07T00:00:00+00:00
""".strip()

    parsed = parse_lmstat_output(output)

    assert parsed.features == [
        {"feature": "alpha", "total": 5, "in_use": 2, "queued": 1, "expired": False}
    ]
    assert parsed.checkouts == [
        {
            "feature": "alpha",
            "user": "user01",
            "host": "host01",
            "pid": 101,
            "checkout_id": "co-1",
            "status": "GRANTED",
            "granted_at": "2026-05-07T00:00:00+00:00",
        }
    ]
