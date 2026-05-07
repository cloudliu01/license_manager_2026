import json

from license_manager_simulators.workload.sqlite_sink import SQLiteSink, WorkloadEvent
from license_manager_simulators.workload.validator import validate_run, write_validation_report


def test_validator_fails_when_required_files_are_missing(tmp_path):
    result = validate_run(tmp_path, min_samples=1)

    assert result.passed is False
    assert any(check["name"] == "required_files" for check in result.checks)


def test_validator_passes_minimal_valid_run_directory(tmp_path):
    (tmp_path / "metadata.json").write_text(json.dumps({"lmgrd_exit_status": 0}), encoding="utf-8")
    (tmp_path / "license.dat").write_text("PORT 27000\nFEATURE alpha 1\n", encoding="utf-8")
    (tmp_path / "lmgrd.log").write_text(
        '00:00:00 (default) OUT: "alpha" user01@host01 [pid=1 checkout_id=co-1]\n'
        '00:00:01 (default) IN: "alpha" user01@host01 [pid=1 checkout_id=co-1]\n'
        '00:00:02 (default) DENIED: "missing_feature" user02@host02 [reason=UNKNOWN_FEATURE]\n',
        encoding="utf-8",
    )
    sink = SQLiteSink(tmp_path / "samples.sqlite")
    sink.initialize()
    sink.insert_sample(
        sampled_at="2026-05-07T00:00:00+00:00",
        raw_output="raw",
        features=[{"feature": "alpha", "total": 1, "in_use": 0, "queued": 0, "expired": False}],
        checkouts=[],
    )
    sink.insert_event(WorkloadEvent("2026-05-07T00:00:00+00:00", "user01", "checkout", "alpha", "GRANTED", None, "co-1"))
    sink.insert_event(WorkloadEvent("2026-05-07T00:00:01+00:00", "user01", "return", "alpha", "RETURNED", None, "co-1"))
    sink.insert_event(
        WorkloadEvent(
            "2026-05-07T00:00:02+00:00",
            "user02",
            "checkout",
            "missing_feature",
            "REJECTED",
            "UNKNOWN_FEATURE",
            None,
        )
    )
    sink.close()

    result = validate_run(tmp_path, min_samples=1)
    write_validation_report(tmp_path, result)

    assert result.passed is True
    assert json.loads((tmp_path / "validation.json").read_text(encoding="utf-8"))["passed"] is True
