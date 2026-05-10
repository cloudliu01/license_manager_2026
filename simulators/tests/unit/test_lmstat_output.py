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

    assert content.startswith("lmstat - Copyright")
    assert "Flexible License Manager status on" in content
    assert "License server status: 27000@127.0.0.1" in content
    assert "Vendor daemon status (on 127.0.0.1):" in content
    assert "Feature usage info:" in content
    assert "Users of alpha:  (Total of 2 licenses issued;  Total of 1 license in use)" in content
    assert '  "alpha" v1.0, vendor: default, expiry: permanent' in content
    assert '"user1" host1 /dev/pts/101 (v1.0) (127.0.0.1/27000 101), start ' in content


def test_generate_output_includes_queued_detail_rows():
    content = generate_output(
        server="127.0.0.1",
        port=27000,
        features=[
            {
                "name": "alpha",
                "total": 1,
                "in_use": 1,
                "queued": 1,
                "expired": False,
                "details": [
                    {
                        "checkout_id": "co-2",
                        "user": "user2",
                        "host": "host2",
                        "pid": 102,
                        "status": "QUEUED",
                        "granted_at": None,
                    }
                ],
            }
        ],
        include_details=True,
    )

    assert '"user2" host2 /dev/pts/102 (v1.0) (127.0.0.1/27000 102) queued for 1 license' in content
