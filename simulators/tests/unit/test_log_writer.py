from license_manager_simulators.core.log_writer import FileLogWriter


def test_file_log_writer_appends_runtime_events_and_flushes(tmp_path):
    log_path = tmp_path / "license.log"
    writer = FileLogWriter(str(log_path))

    writer.checkout_granted("default", "alpha", "user1", "host1", 101, "co-1", 4, "info_APS_26")
    writer.returned("default", "alpha", "user1", "host1", 101, "co-1", 4, "info_APS_26")
    writer.unsupported("default", "missing", "user1", "host1", "info_X_1")
    writer.denied("default", "alpha", "user1", "host1", "LICENSE_LIMIT_REACHED")
    writer.queued("default", "alpha", "user2", "host2", "co-2", 1)
    writer.shutdown()

    content = log_path.read_text(encoding="utf-8")
    assert 'OUT:\t"alpha"\tuser1@host1\t[info_APS_26]\t(4\tlicenses)' in content
    assert 'IN:\t"alpha"\tuser1@host1\t[info_APS_26]\t(4\tlicenses)' in content
    assert 'UNSUPPORTED:\t"missing"\tuser1@host1\t[info_X_1]' in content
    assert 'No such feature exists. (-5,346:104 "Connection reset by peer")' in content
    assert 'DENIED:\t"alpha"\tuser1@host1' in content
    assert 'Licensed number of users already reached. (-4,342:104 "Connection reset by peer")' in content
    assert 'QUEUED: "alpha" user2@host2 [checkout_id=co-2 position=1]' in content
    assert "License server manager shutdown complete" in content
