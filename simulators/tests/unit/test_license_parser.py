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
