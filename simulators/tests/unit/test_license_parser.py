import pytest

from license_manager_simulators.core.license_parser import parse_license_text


def test_parse_license_text_groups_features_by_daemon():
    config = parse_license_text(
        """
        PORT 27000
        SERVER_NAME test-host
        DAEMON vendorA
        FEATURE alpha 10 DAEMON vendorA EXP 2026-12-31
        FEATURE beta 5
        """
    )

    assert config.port == 27000
    assert config.server_name == "test-host"
    assert config.daemons == ["vendorA"]
    assert config.features["alpha"].daemon == "vendorA"
    assert config.features["alpha"].expires_at.isoformat() == "2026-12-31"
    assert config.features["beta"].daemon == "default"


def test_parse_license_text_supports_feature_reservations():
    config = parse_license_text(
        """
        PORT 27000
        DAEMON vendorA
        FEATURE alpha 10 DAEMON vendorA EXP 2026-12-31 RESERVE 2 GROUP engineering RESERVE 1 HOST buildhost1
        """
    )

    reservations = config.features["alpha"].reservations
    assert [(item.kind, item.name, item.count) for item in reservations] == [
        ("GROUP", "engineering", 2),
        ("HOST", "buildhost1", 1),
    ]


def test_parse_license_text_supports_host_group_reservation():
    config = parse_license_text(
        """
        PORT 27000
        FEATURE alpha 10 RESERVE 3 HOST_GROUP buildfarm
        """
    )

    reservations = config.features["alpha"].reservations
    assert [(item.kind, item.name, item.count) for item in reservations] == [
        ("HOST_GROUP", "buildfarm", 3),
    ]


def test_parse_license_text_rejects_incomplete_reservation():
    with pytest.raises(ValueError, match="RESERVE requires count, kind, and name"):
        parse_license_text("PORT 27000\nFEATURE alpha 10 RESERVE 1 GROUP\n")


def test_parse_license_text_rejects_invalid_reservation_count():
    with pytest.raises(ValueError, match="RESERVE count must be >= 1"):
        parse_license_text("PORT 27000\nFEATURE alpha 10 RESERVE 0 GROUP engineering\n")


def test_parse_license_text_rejects_invalid_reservation_kind():
    with pytest.raises(ValueError, match="RESERVE kind must be GROUP, HOST_GROUP, or HOST"):
        parse_license_text("PORT 27000\nFEATURE alpha 10 RESERVE 1 USER user1\n")


def test_parse_license_text_rejects_exporter_incompatible_reservation_name():
    with pytest.raises(ValueError, match="RESERVE name must contain only letters, numbers, and underscores"):
        parse_license_text("PORT 27000\nFEATURE alpha 10 RESERVE 1 HOST build-host1\n")
