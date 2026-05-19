from license_manager_simulators.lmstat.output import generate_output


def test_generate_output_includes_details_for_verbose_mode():
    content = generate_output(
        server="127.0.0.1",
        port=27000,
        features=[
            {
                "name": "alpha",
                "daemon": "vendorA",
                "total": 2,
                "in_use": 1,
                "queued": 0,
                "expired": False,
                "expires_at": "2026-11-01",
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
            },
            {
                "name": "beta",
                "daemon": "vendorB",
                "total": 4,
                "in_use": 0,
                "queued": 0,
                "expired": False,
                "details": [],
            },
        ],
        include_details=True,
    )

    assert content.startswith("lmstat - Copyright")
    assert "Flexible License Manager status on" in content
    assert "[Detecting lmgrd processes...]" not in content
    assert "License server status: 27000@127.0.0.1" in content
    assert "    License file(s) on 127.0.0.1: /path/to/license.dat:" in content
    assert "127.0.0.1: license server UP (MASTER) v11.19.5" in content
    assert "Vendor daemon status (on 127.0.0.1):" in content
    assert "    vendorA: UP v11.19.5" in content
    assert "    vendorB: UP v11.19.5" in content
    assert "Feature usage info:" in content
    assert "Users of alpha:               (Total of 2 licenses issued;  Total of 1 license in use)" in content
    assert "Users of beta:                (Total of 4 licenses issued;  Total of 0 licenses in use)" in content
    assert "NOTE: lmstat -i does not give information from the server," in content
    assert "      but only reads the license file.  For this reason," in content
    assert "      lmstat -a is recommended instead." in content
    assert "Feature                         Version     #licenses    Expires      Vendor" in content
    assert "alpha                           1.0         2           01-Nov-2026  vendorA" in content
    assert "beta                            1.0         4           permanent    vendorB" in content
    assert '  "alpha" v1.0, vendor: vendorA, expiry: 01-Nov-2026' in content
    assert "  floating license" in content
    assert '    "user1" host1 /dev/pts/101 (v1.0) (127.0.0.1/27000 101), start ' in content
    assert content.index('  "alpha" v1.0, vendor: vendorA') < content.index("NOTE: lmstat -i")
    assert content.index("NOTE: lmstat -i") < content.index("Feature                         Version")


def test_generate_output_includes_queued_detail_rows():
    content = generate_output(
        server="127.0.0.1",
        port=27000,
        features=[
            {
                "name": "alpha",
                "daemon": "vendorA",
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

    assert '    "user2" host2 /dev/pts/102 (v1.0) (127.0.0.1/27000 102) queued for 1 license' in content


def test_generate_output_omits_i_note_without_inventory_flag():
    content = generate_output(
        server="127.0.0.1",
        port=27000,
        features=[
            {
                "name": "alpha",
                "daemon": "vendorA",
                "total": 1,
                "in_use": 0,
                "queued": 0,
                "expired": False,
                "details": [],
            }
        ],
        include_details=False,
    )

    assert "Users of alpha:               (Total of 1 license issued;  Total of 0 licenses in use)" in content
    assert "NOTE: lmstat -i" not in content
    assert "Feature                         Version" not in content


def test_generate_output_without_feature_usage_only_shows_header_and_daemons():
    content = generate_output(
        server="127.0.0.1",
        port=27000,
        features=[
            {
                "name": "alpha",
                "daemon": "vendorA",
                "total": 1,
                "in_use": 0,
                "queued": 0,
                "expired": False,
                "details": [],
            },
            {
                "name": "beta",
                "daemon": "vendorB",
                "total": 1,
                "in_use": 0,
                "queued": 0,
                "expired": False,
                "details": [],
            },
        ],
        include_details=False,
        include_feature_usage=False,
    )

    assert "License server status: 27000@127.0.0.1" in content
    assert "Vendor daemon status (on 127.0.0.1):" in content
    assert "    vendorA: UP v11.19.5" in content
    assert "    vendorB: UP v11.19.5" in content
    assert "Feature usage info:" not in content
    assert "Users of alpha:" not in content
    assert "NOTE: lmstat -i" not in content
