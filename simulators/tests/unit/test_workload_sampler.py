from license_manager_simulators.workload.sampler import parse_lmstat_output


def test_parse_lmstat_output_extracts_feature_and_checkout_rows():
    output = """
lmstat - Copyright (c) 1989-2015 Flexera Software LLC. All Rights Reserved.
Flexible License Manager status on Thu 5/7/2026 00:00

License server status: 27000@127.0.0.1
    License file(s) on 127.0.0.1: /path/to/license.dat:

127.0.0.1: license server UP (MASTER) v11.19.5

Vendor daemon status (on 127.0.0.1):
    default: UP v11.19.5
Feature usage info:
Users of alpha:               (Total of 5 licenses issued;  Total of 2 licenses in use)

  "alpha" v1.0, vendor: default, expiry: permanent
  floating license

    "user01" host01 /dev/pts/101 (v1.0) (127.0.0.1/27000 101), start Thu 5/7 00:00
    "user02" host02 /dev/pts/102 (v1.0) (127.0.0.1/27000 102) queued for 1 license
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
            "checkout_id": "127.0.0.1/27000:101",
            "status": "GRANTED",
            "granted_at": "Thu 5/7 00:00",
        },
        {
            "feature": "alpha",
            "user": "user02",
            "host": "host02",
            "pid": 102,
            "checkout_id": "127.0.0.1/27000:102",
            "status": "QUEUED",
            "granted_at": None,
        },
    ]
