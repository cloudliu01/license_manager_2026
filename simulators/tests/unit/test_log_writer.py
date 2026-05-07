from license_manager_simulators.core.log_writer import FileLogWriter


def test_file_log_writer_appends_runtime_events_and_flushes(tmp_path):
    log_path = tmp_path / "license.log"
    writer = FileLogWriter(str(log_path))

    writer.checkout_granted("default", "alpha", "user1", "host1", 101, "co-1")
    writer.returned("default", "alpha", "user1", "host1", 101, "co-1")
    writer.denied("default", "missing", "user1", "host1", "UNKNOWN_FEATURE")
    writer.queued("default", "alpha", "user2", "host2", "co-2", 1)
    writer.shutdown()

    content = log_path.read_text(encoding="utf-8")
    assert 'OUT: "alpha" user1@host1 [pid=101 checkout_id=co-1]' in content
    assert 'IN: "alpha" user1@host1 [pid=101 checkout_id=co-1]' in content
    assert 'DENIED: "missing" user1@host1 [reason=UNKNOWN_FEATURE]' in content
    assert 'QUEUED: "alpha" user2@host2 [checkout_id=co-2 position=1]' in content
    assert "License server manager shutdown complete" in content
