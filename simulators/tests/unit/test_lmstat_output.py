from license_manager_simulators.lmstat.output import generate_output


def test_generate_output_includes_details_for_verbose_mode():
    content = generate_output(
        server="127.0.0.1",
        port=27000,
        features=[
            {
                "name": "alpha",
                "total": 2,
                "in_use": 1,
                "queued": 0,
                "expired": False,
                "details": [
                    {
                        "checkout_id": "co-1",
                        "user": "user1",
                        "host": "host1",
                        "pid": 101,
                        "status": "GRANTED",
                        "granted_at": "2026-05-07T00:00:00+00:00",
                    }
                ],
            }
        ],
        include_details=True,
    )

    assert "LMSTAT_SIM_FORMAT_VERSION=1" in content
    assert "feature: alpha total=2 in_use=1 queued=0 expired=false" in content
    assert "checkout_id=co-1" in content
    assert "status=GRANTED" in content
    assert "granted_at=2026-05-07T00:00:00+00:00" in content
