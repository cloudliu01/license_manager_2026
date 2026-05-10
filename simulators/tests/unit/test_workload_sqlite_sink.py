import sqlite3

from license_manager_simulators.workload.sqlite_sink import SQLiteSink, WorkloadEvent


def test_sqlite_sink_records_samples_feature_rows_details_and_events(tmp_path):
    db_path = tmp_path / "samples.sqlite"
    sink = SQLiteSink(db_path)
    sink.initialize()

    sample_id = sink.insert_sample(
        sampled_at="2026-05-07T00:00:00+00:00",
        raw_output="raw lmstat output",
        features=[{"feature": "alpha", "total": 5, "in_use": 2, "queued": 1, "expired": False}],
        checkouts=[
            {
                "feature": "alpha",
                "user": "user01",
                "host": "host01",
                "pid": 101,
                "checkout_id": "co-1",
                "status": "GRANTED",
                "granted_at": "2026-05-07T00:00:00+00:00",
            }
        ],
    )
    sink.insert_event(
        WorkloadEvent(
            event_time="2026-05-07T00:00:01+00:00",
            user="user01",
            action="checkout",
            feature="alpha",
            status="GRANTED",
            reason=None,
            checkout_id="co-1",
        )
    )
    sink.close()

    conn = sqlite3.connect(db_path)
    assert conn.execute("select count(*) from samples").fetchone()[0] == 1
    assert conn.execute("select raw_output from samples").fetchone()[0] == "raw lmstat output"
    assert conn.execute("select sampled_at, feature, in_use from feature_samples").fetchone() == (
        "2026-05-07T00:00:00+00:00",
        "alpha",
        2,
    )
    assert conn.execute("select sampled_at, checkout_id from checkout_samples").fetchone() == (
        "2026-05-07T00:00:00+00:00",
        "co-1",
    )
    assert conn.execute("select status from workload_events").fetchone()[0] == "GRANTED"
    assert sample_id == 1
