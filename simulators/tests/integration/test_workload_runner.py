import json
import sqlite3

from license_manager_simulators.workload.runner import run_workload
from license_manager_simulators.workload.validator import validate_run


def test_workload_runner_creates_valid_run_directory(tmp_path):
    run_dir = tmp_path / "run"

    result = run_workload(
        out_dir=run_dir,
        duration_seconds=6,
        users=6,
        sample_interval_seconds=2,
        seed=7,
    )

    assert result.run_dir == run_dir
    assert (run_dir / "metadata.json").exists()
    assert (run_dir / "license.dat").exists()
    assert (run_dir / "lmgrd.log").exists()
    assert (run_dir / "samples.sqlite").exists()

    validation = validate_run(run_dir, min_samples=2)
    assert validation.passed is True

    metadata = json.loads((run_dir / "metadata.json").read_text(encoding="utf-8"))
    assert metadata["users"] == 6
    conn = sqlite3.connect(run_dir / "samples.sqlite")
    assert conn.execute("select count(*) from samples").fetchone()[0] >= 2
    raw_output = conn.execute("select raw_output from samples order by sample_id limit 1").fetchone()[0]
    assert "lmstat - Copyright" in raw_output
    assert "Users of" in raw_output
    assert "License server status:" in raw_output
    assert "    License file(s) on 127.0.0.1: /path/to/license.dat:" in raw_output
    assert "Vendor daemon status (on 127.0.0.1):" in raw_output
    assert "Feature usage info:" in raw_output
    raw_output_with_checkout = conn.execute(
        "select raw_output from samples where raw_output like '%  floating license%' limit 1"
    ).fetchone()
    assert raw_output_with_checkout is not None
