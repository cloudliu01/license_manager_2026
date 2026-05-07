from license_manager_simulators.workload.scenario import DEFAULT_MISSING_FEATURE, Scenario


def test_default_scenario_license_text_contains_small_capacity_features():
    scenario = Scenario.default(port=27654, users=12, seed=123)

    text = scenario.license_text()

    assert "PORT 27654" in text
    assert "FEATURE alpha 5 DAEMON vendorA" in text
    assert "FEATURE beta 3 DAEMON vendorA" in text
    assert "FEATURE gamma 2" in text
    assert DEFAULT_MISSING_FEATURE not in text
    assert len(scenario.users) == 12


def test_scenario_choose_action_can_emit_missing_feature():
    scenario = Scenario.default(port=27654, users=1, seed=1)

    actions = [scenario.choose_action([]) for _ in range(100)]

    features = {action.feature for action in actions if action.feature}

    assert DEFAULT_MISSING_FEATURE in features
