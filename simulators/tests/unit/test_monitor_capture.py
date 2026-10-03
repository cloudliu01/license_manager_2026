import json
import socket
import struct

import license_manager_simulators.monitor.capture as cap
from license_manager_simulators.lmgrd.wire import CHECKOUT, encode_frame
from license_manager_simulators.monitor.capture import (
    AuditDatabase,
    Segment,
    Stream,
    parse_ipv4_tcp,
)
from license_manager_simulators.monitor.topology import Listener


def _segment(seq: int, data: bytes, syn: bool = False) -> Segment:
    return Segment("127.0.0.1", 50001, "127.0.0.1", 42000, seq, syn, False, False, data)


def test_reassembles_split_coalesced_out_of_order_and_retransmission():
    first = encode_frame(CHECKOUT, {"feature": "alpha"})
    second = encode_frame(CHECKOUT, {"feature": "beta"})
    stream = Stream()
    assert stream.feed(_segment(99, b"", syn=True)) == []
    assert stream.feed(_segment(110, first[10:])) == []  # later segment first
    assert stream.feed(_segment(100, first[:10])) == [first]
    assert stream.feed(_segment(100, first[:10])) == []  # retransmit
    assert stream.feed(_segment(100 + len(first), second)) == [second]


def test_parse_loopback_ethernet_ipv4_tcp_payload():
    payload = encode_frame(CHECKOUT, {"feature": "alpha"})
    eth = bytes(12) + b"\x08\x00"
    ip = bytearray(20)
    ip[0] = 0x45
    ip[9] = 6
    ip[12:16] = socket.inet_aton("127.0.0.1")
    ip[16:20] = socket.inet_aton("127.0.0.1")
    struct.pack_into("!H", ip, 2, 40 + len(payload))
    tcp = bytearray(20)
    struct.pack_into("!HHI", tcp, 0, 50123, 42000, 123)
    tcp[12] = 0x50
    parsed = parse_ipv4_tcp(eth + ip + tcp + payload)
    assert parsed is not None
    assert (parsed.src_port, parsed.dst_port, parsed.seq, parsed.payload) == (50123, 42000, 123, payload)


def test_sqlite_keeps_decoded_json_exact_frame_hex_and_binary(tmp_path):
    raw = encode_frame(CHECKOUT, {"feature": "alpha", "user": "user1"})
    db = AuditDatabase(str(tmp_path / "capture.sqlite"), 123)
    segment = _segment(1, raw)
    listener = Listener(456, 42000, "vendorA", 123456)
    db.listeners({42000: listener})
    db.segment(segment, listener, "client_to_server")
    request_id, opcode, payload = db.frame(raw, segment, listener, "client_to_server")
    assert (opcode, payload) == (CHECKOUT, {"feature": "alpha", "user": "user1"})
    response = encode_frame(CHECKOUT | 0x80, {
        "status": "GRANTED", "feature": "alpha", "checkout_id": "id-1", "quantity": 1,
    })
    response_id, _, decoded = db.frame(response, segment, listener, "server_to_client")
    db.license_event(response_id, decoded, (request_id, payload), listener)
    row = db.conn.execute("SELECT server_pid,daemon,raw_hex,raw_bytes,decoded_json FROM frames LIMIT 1").fetchone()
    assert row[:4] == (456, "vendorA", raw.hex(), raw)
    assert json.loads(row[4]) == {"feature": "alpha", "user": "user1"}
    assert db.conn.execute("SELECT payload_hex,payload_bytes FROM tcp_segments").fetchone() == (raw.hex(), raw)
    assert db.conn.execute("""SELECT feature,client_user,client_host,status,correlation
        FROM license_events""").fetchone() == ("alpha", "user1", None, "GRANTED", "MATCHED_SIM1_REQUEST")
    db.close()


def test_attach_feature_pairs_attempts_fifo(tmp_path):
    db = AuditDatabase(str(tmp_path / "capture.sqlite"), 123)
    listener = Listener(456, 42000, "vendorA", 123456)
    segment = _segment(1, b"x")
    for _ in range(2):
        db.flexlm_event(
            1, listener, feature=None, client_user="userx",
            client_host="qa-srv47", quantity=None, status="FLEXLM_CHECKOUT_ATTEMPT",
            reason=None, request_frame_id=None, correlation="IDENTITY_FROM_GREETING",
            client_pid="23578",
        )
    assert db.attach_feature("QZ", "userx", "qa-srv47", "23578", 163)
    assert db.attach_feature("QZ", "userx", "qa-srv47", "23578", 165)
    rows = db.conn.execute("""SELECT request_frame_id, feature, correlation
        FROM license_events ORDER BY id""").fetchall()
    assert rows == [
        (163, "QZ", "FEATURE_FROM_LICENSE_LOOKUP"),
        (165, "QZ", "FEATURE_FROM_LICENSE_LOOKUP"),
    ]
    # a different process of the same user must NOT receive the feature
    assert not db.attach_feature("QZ", "userx", "qa-srv47", "99999", 166)
    assert not db.attach_feature("QZ", "other", "qa-srv47", "23578", 167)  # identity mismatch
    db.close()


def test_client_session_records_pid_and_feature(tmp_path):
    from license_manager_simulators.monitor.capture import _observe_flexlm

    db = AuditDatabase(str(tmp_path / "capture.sqlite"), 123)
    listener = Listener(456, 43095, "vendmock", 123456)
    state = {
        "features": {}, "identities": {}, "recent_identity": {},
        "lookups": {}, "session_ids": {}, "holders": {}, "pid_feature": {},
        "crypto_seen": set(), "checkout_requests": {},
    }
    session = ("10.20.64.75", 36067, "10.20.86.79", 43095)
    greeting = {
        "proto": "eda-greeting", "user": "userx", "host": "qa-srv47",
        "pid": "23578", "tty": "/dev/tty", "platform": "x64_lsb",
        "daemon": "vendmock",
    }
    _observe_flexlm(db, listener, session, "client_to_server", 160, greeting, state)
    lookup = {"proto": "lsf-broker", "type": 0x47, "feature": "QZ", "param": "P=25b4760"}
    _observe_flexlm(db, listener, session, "client_to_server", 163, lookup, state)
    assert db.conn.execute("""SELECT client_user,client_host,client_pid,client_tty,
        client_platform,greeting_daemon,feature,greeting_frame_id
        FROM client_sessions""").fetchone() == (
        "userx", "qa-srv47", "23578", "/dev/tty", "x64_lsb", "vendmock", "QZ", 160,
    )
    assert db.conn.execute("""SELECT client_user,client_pid,client_platform,status,feature,reason
        FROM license_events""").fetchone() == (
        "userx", "23578", "x64_lsb", "FLEXLM_LICENSE_LOOKUP", "QZ", "P=25b4760",
    )
    # the lookup teaches the monitor what feature this client PROCESS runs
    assert state["pid_feature"] == {("10.20.64.75", "23578"): "QZ"}

    # the 0x46 reply carries the INCREMENT line: recorded, but its seat count
    # is the pool size, so quantity stays NULL (raw line kept in reason)
    line = {
        "proto": "lsf-broker", "type": 0x46, "feature": "QZ",
        "license_line": "INCREMENT QZ vendorA 2030.1231 15-apr-2027 100 SIGN=x",
        "seats": 100,
    }
    _observe_flexlm(db, listener, session, "server_to_client", 164, line, state)
    assert db.conn.execute("""SELECT quantity, request_frame_id, correlation, reason
        FROM license_events WHERE status='FLEXLM_LICENSE_LINE'""").fetchone() == (
        None, 163, "MATCHED_FLEXLM_LOOKUP",
        "INCREMENT QZ vendorA 2030.1231 15-apr-2027 100 SIGN=x",
    )

    # a 0x14 user row on a queried stream: one seat, linked to its 0x3c request;
    # holder pid matched from the greeting, poller matched from the client IP
    state["features"][session] = ("QZ", 200)
    user_row = {"proto": "lsf-broker", "type": 0x14, "user": "userx", "host": "qa-srv47"}
    _observe_flexlm(db, listener, session, "server_to_client", 201, user_row, state)
    assert db.conn.execute("""SELECT quantity, request_frame_id, correlation,
        client_pid, client_tty, client_platform, poller_user, poller_pid
        FROM license_events WHERE status='FLEXLM_IN_USE'""").fetchone() == (
        1, 200, "MATCHED_FLEXLM_QUERY", "23578", "/dev/tty", "x64_lsb", "userx", "23578",
    )
    assert db.conn.execute("""SELECT holder_pid, holder_platform FROM v_client_events
        WHERE status='FLEXLM_IN_USE'""").fetchone() == ("23578", "x64_lsb")
    db.close()


def test_poller_summaries_table_and_migration(tmp_path):
    import struct

    from license_manager_simulators.monitor.capture import (
        AuditDatabase,
        _observe_flexlm,
        _observe_query_stream,
    )
    from license_manager_simulators.monitor.flexlm import decode_flexlm_frame

    def lsf(frame_type: int, body: bytes) -> bytes:
        return struct.pack("!4sHBBI", b"\x2f\x01\x02\x03", 12 + len(body), 1, frame_type, 0) + body

    path = str(tmp_path / "capture.sqlite")
    db = AuditDatabase(path, 123)
    listener = Listener(456, 43095, "vendmock", 123456)
    # a summary row recorded before the table split
    db.flexlm_event(
        1, listener, feature="DEMO_AX", client_user=None, client_host=None,
        quantity=7, status="FLEXLM_FEATURE_SUMMARY", reason=None,
        request_frame_id=None, correlation="MATCHED_FLEXLM_QUERY",
        poller_user="jobadmin", poller_pid="777",
    )
    db.flush()
    db.close()

    # reopening migrates it: summary rows live in poller_summaries only
    db = AuditDatabase(path, 123)
    assert db.conn.execute(
        "SELECT COUNT(*) FROM license_events WHERE status='FLEXLM_FEATURE_SUMMARY'"
    ).fetchone()[0] == 0
    assert db.conn.execute(
        """SELECT feature, in_use, issued, report_ts, correlation,
        poller_user, poller_pid FROM poller_summaries""").fetchone() == (
        "DEMO_AX", 7, None, None, "MATCHED_FLEXLM_QUERY", "jobadmin", "777",
    )

    # a live 0x4e via the full-frame path: in_use/issued/report_ts preserved
    epoch = 1790870940
    _, payload = decode_flexlm_frame(
        lsf(0x4E, b"\x00" * 8 + b"5\x0010\x00" + str(epoch).encode() + b"\x00"), "server_to_client",
    )
    assert (payload["in_use"], payload["issued"], payload["report_ts"]) == (5, 10, epoch)
    session = ("10.20.64.212", 5000, "10.20.86.79", 43095)
    state = {
        "features": {session: ("DEMO_AX", None)}, "identities": {},
        "recent_identity": {session[0]: ("jobadmin", "qa-jobmaster", "910", "/dev/tty", "x64_lsb")},
        "lookups": {}, "session_ids": {}, "holders": {}, "pid_feature": {},
        "crypto_seen": set(), "checkout_requests": {},
    }
    _observe_flexlm(db, listener, session, "server_to_client", 401, payload, state)
    assert db.conn.execute(
        "SELECT in_use, issued, report_ts, poller_user, correlation FROM poller_summaries "
        "WHERE response_frame_id = 401").fetchone() == (5, 10, epoch, "jobadmin", "MATCHED_FLEXLM_QUERY")

    # filtered query-stream path records summaries too (they used to be dropped)
    stream_state = {
        "features": {session: ("DEMO_SIM", None)},
        "holders": {},
        "recent_identity": {session[0]: ("jobadmin", "qa-jobmaster", "910", "/dev/tty", "x64_lsb")},
    }
    segment = Segment("10.20.64.212", 5000, "10.20.86.79", 43095, 1, False, False, False, b"")
    _observe_query_stream(db, listener, session, "server_to_client", segment,
                          [lsf(0x4E, b"\x00" * 8 + b"3\x008\x00" + str(epoch).encode() + b"\x00")], stream_state)
    assert db.conn.execute(
        "SELECT feature, in_use, issued, report_ts, correlation FROM poller_summaries "
        "ORDER BY id DESC LIMIT 1").fetchone() == ("DEMO_SIM", 3, 8, epoch, "MATCHED_FLEXLM_QUERY")
    # no summary rows leak into license_events
    assert db.conn.execute(
        "SELECT COUNT(*) FROM license_events WHERE status='FLEXLM_FEATURE_SUMMARY'"
    ).fetchone()[0] == 0
    db.close()


def test_seat_feature_set_mirrors_pid_set(tmp_path):
    import struct

    from license_manager_simulators.monitor.capture import _observe_query_stream

    def lsf(frame_type: int, body: bytes) -> bytes:
        return struct.pack("!4sHBBI", b"\x2f\x01\x02\x03", 12 + len(body), 1, frame_type, 0) + body

    db = AuditDatabase(str(tmp_path / "capture.sqlite"), 123)
    listener = Listener(456, 59001, "lmgrd", 123456)
    session = ("10.20.64.212", 5000, "10.20.86.79", 59001)
    state = {
        "features": {session: ("DEMO_AX", None)}, "holders": {}, "recent_identity": {},
    }

    def seat(user: str, host: str, ts: int, cid: int) -> bytes:
        return lsf(0x14, (
            b"\x00" * 8 + user.encode() + b"\x00" + host.encode() + b"\x00"
            + b"/dev/tty\x001.0\x00" + b"\x00" * 4 + b"\x01\x00\x00\x00"
            + struct.pack("!I", ts) + b"\x00" * 4 + struct.pack("!I", cid)
        ))

    segment = Segment("10.20.64.212", 5000, "10.20.86.79", 59001, 1, False, False, False, b"")
    for pid, feature in (("31158", "DEMO_AX"), ("31184", "DEMO_SIM")):
        db.flexlm_event(
            1, listener, feature=feature, client_user="sample.user", client_host="qa-gui32",
            quantity=None, status="FLEXLM_CHECKOUT_ATTEMPT", reason=None,
            request_frame_id=None, correlation="IDENTITY_FROM_GREETING",
            client_pid=pid, checkout_ts=1790866419,
        )
    _observe_query_stream(db, listener, session, "server_to_client", segment,
                          [seat("sample.user", "qa-gui32", 1790866419, 35684)], state)
    assert db.conn.execute("""SELECT client_pid, feature, correlation FROM license_events
        WHERE status='FLEXLM_IN_USE'""").fetchone() == (
        "31158,31184", "DEMO_AX,DEMO_SIM", "AMBIGUOUS_CHECKOUT_TS",
    )
    db.close()


def test_backfill_names_featureless_seats_from_named_attempts(tmp_path):
    db = AuditDatabase(str(tmp_path / "capture.sqlite"), 123)
    listener = Listener(456, 43095, "vendmock", 123456)
    # one named attempt (its own 0x47 lookup) + one feature-less seat
    # (session without a 0x3c query), same (user, host, ts), 1:1
    db.flexlm_event(
        1, listener, feature="QZ", client_user="userx", client_host="qa-srv47",
        quantity=None, status="FLEXLM_CHECKOUT_ATTEMPT", reason=None,
        request_frame_id=None, correlation="IDENTITY_FROM_GREETING",
        client_pid="23578", checkout_ts=1790861015,
    )
    db.flexlm_event(
        2, listener, feature=None, client_user="userx", client_host="qa-srv47",
        quantity=1, status="FLEXLM_IN_USE", reason=None, request_frame_id=None,
        correlation="NO_FLEXLM_QUERY", checkout_id=49202, checkout_ts=1790861015,
    )
    assert db.backfill_attempt_features("userx", "qa-srv47", 1790861015)
    assert db.conn.execute("""SELECT feature FROM license_events
        WHERE status='FLEXLM_IN_USE'""").fetchone()[0] == "QZ"
    # idempotent: nothing feature-less remains
    assert not db.backfill_attempt_features("userx", "qa-srv47", 1790861015)
    db.close()


def test_poller_details_rollup_and_retention(tmp_path):
    import struct

    from license_manager_simulators.monitor.capture import _observe_query_stream

    def lsf(frame_type: int, body: bytes) -> bytes:
        return struct.pack("!4sHBBI", b"\x2f\x01\x02\x03", 12 + len(body), 1, frame_type, 0) + body

    def seat(user: str, host: str, ts: int, cid: int) -> bytes:
        return lsf(0x14, (
            b"\x00" * 8 + user.encode() + b"\x00" + host.encode() + b"\x00"
            + b"/dev/tty\x001.0\x00" + b"\x00" * 4 + b"\x01\x00\x00\x00"
            + struct.pack("!I", ts) + b"\x00" * 4 + struct.pack("!I", cid)
        ))

    db = AuditDatabase(str(tmp_path / "capture.sqlite"), 123)
    listener = Listener(456, 59001, "lmgrd", 123456)
    session = ("10.20.64.212", 5000, "10.20.86.79", 59001)
    state = {
        "features": {}, "holders": {}, "recent_identity": {}, "poller_details": {},
    }
    segment = Segment("10.20.64.212", 5000, "10.20.86.79", 59001, 1, False, False, False, b"")
    pid = "31266"
    state["holders"][("sample.user", "qa-gui32")] = (
        "sample.user", "qa-gui32", pid, "/dev/tty", "x64_lsb",
    )

    def observe(frames: list[bytes], direction: str = "server_to_client") -> None:
        _observe_query_stream(db, listener, session, direction, segment, frames, state)

    def query(feature: str) -> bytes:
        return lsf(0x3C, b"\x00" * 8 + feature.encode() + b"\x00")

    # dump 1: three seats (one holder checked out twice, another holder
    # once) -> one poller_details row PER SEAT; a feature switch (0x3c)
    # completes the observation; an empty feature (no 0x14 rows) must not
    # appear at all
    state["features"][session] = ("DEMO_AX", None)
    observe([seat("sample.user", "qa-gui32", 1790866419, 35684),
             seat("sample.user", "qa-gui32", 1790866421, 39200),
             seat("userx", "qa-srv63", 1790866425, 11111)])
    observe([query("EMPTY_FEAT")], direction="client_to_server")
    observe([query("DEMO_AX")], direction="client_to_server")
    rows = db.conn.execute("""SELECT feature, client_user, client_host, client_tty,
        client_version, checkout_id, checkout_ts, client_pid, correlation
        FROM poller_details ORDER BY id""").fetchall()
    assert rows == [
        ("DEMO_AX", "sample.user", "qa-gui32", "/dev/tty", "1.0", 35684,
         1790866419, "31266", "HOLDER_NO_TS_MATCH"),
        ("DEMO_AX", "sample.user", "qa-gui32", "/dev/tty", "1.0", 39200,
         1790866421, "31266", "HOLDER_NO_TS_MATCH"),
        ("DEMO_AX", "userx", "qa-srv63", "/dev/tty", "1.0", 11111,
         1790866425, None, "NO_CHECKOUT_MATCH"),
    ]
    assert db.conn.execute(
        "SELECT COUNT(*) FROM poller_details WHERE feature='EMPTY_FEAT'").fetchone()[0] == 0
    # the seat license_events rows were still written once each (first sighting)
    assert db.conn.execute(
        "SELECT COUNT(*) FROM license_events WHERE status='FLEXLM_IN_USE'").fetchone()[0] == 3

    # retention: a small history all fits under POLLER_OBSERVATIONS (120);
    # each cycle forms one complete observation of the feature
    for cycle in range(4):
        observe([query("DEMO_AX")], direction="client_to_server")
        observe([seat("sample.user", "qa-gui32", 1790866419, 35684 + cycle)])
        observe([query("NEXT")], direction="client_to_server")  # completes the observation
    rows = db.conn.execute("""SELECT checkout_id FROM poller_details
        WHERE feature='DEMO_AX' ORDER BY observation DESC, id LIMIT 4""").fetchall()
    assert [r[0] for r in rows] == [35687, 35686, 35685, 35684]
    assert db.conn.execute(
        "SELECT COUNT(*) FROM poller_details WHERE feature='DEMO_AX'").fetchone()[0] == 7
    db.close()


def test_poller_summaries_keep_observation_window(tmp_path):
    db = AuditDatabase(str(tmp_path / "capture.sqlite"), 123)
    listener = Listener(456, 43095, "vendmock", 123456)
    total = cap.POLLER_OBSERVATIONS + 2
    for cycle in range(total):
        db.poller_summary(
            cycle + 1, listener, feature="DEMO_AX", in_use=cycle, issued=10,
            report_ts=1790870000 + cycle, request_frame_id=None,
            correlation="MATCHED_FLEXLM_QUERY",
        )
    # an unrelated feature keeps its own observation window
    db.poller_summary(
        99, listener, feature="QY", in_use=1, issued=4, report_ts=1790870000,
        request_frame_id=None, correlation="MATCHED_FLEXLM_QUERY",
    )
    rows = db.conn.execute("""SELECT in_use FROM poller_summaries
        WHERE feature='DEMO_AX' ORDER BY id""").fetchall()
    assert [r[0] for r in rows] == list(range(2, total))
    assert db.conn.execute(
        "SELECT COUNT(*) FROM poller_summaries WHERE feature='QY'").fetchone()[0] == 1
    db.close()


def test_capture_stats_samples_are_increments(tmp_path):
    db = AuditDatabase(str(tmp_path / "capture.sqlite"), 123)
    db.capture_stats(1200, 0)
    db.capture_stats(980, 3)
    assert db.conn.execute("""SELECT packets, drops FROM capture_stats
        ORDER BY id""").fetchall() == [(1200, 0), (980, 3)]
    assert db.conn.execute("SELECT SUM(drops) FROM capture_stats").fetchone()[0] == 3
    db.close()


def test_is_query_frame_type_bytes():
    import struct

    from license_manager_simulators.monitor.capture import _is_query_frame

    def lsf(frame_type: int) -> bytes:
        return struct.pack("!4sHBBI", b"\x2f\x01\x02\x03", 12, 1, frame_type, 0)

    for frame_type in (0x3C, 0x4E, 0x14):  # query / seat summary / user row
        assert _is_query_frame(lsf(frame_type)), hex(frame_type)
    for frame_type in (0x0E, 0x41, 0x46, 0x47, 0x61):  # non-query frame types
        assert not _is_query_frame(lsf(frame_type)), hex(frame_type)
    assert not _is_query_frame(b"\x68\xc6" + b"13")  # greeting, not an LSF frame
    assert not _is_query_frame(b"\x2f\x01\x02\x03")  # too short for a type byte


def test_heartbeat_upsert_aggregates_per_session(tmp_path):
    db = AuditDatabase(str(tmp_path / "capture.sqlite"), 123)
    listener = Listener(456, 43095, "vendmock", 123456)
    session = ("10.20.64.75", 36067, "10.20.86.79", 43095)
    identity = ("userx", "qa-srv47", "23578", "/dev/tty", "x64_lsb")
    segment = Segment("10.20.64.75", 36067, "10.20.86.79", 43095, 1, False, False, False, b"x" * 36)
    db.heartbeat(session, listener, identity, "QZ", segment)
    db.heartbeat(session, listener, None, None, segment)  # later beat without identity
    assert db.conn.execute("""SELECT client_user, client_pid, feature, beats, bytes, last_len
        FROM heartbeats""").fetchone() == ("userx", "23578", "QZ", 2, 72, 36)
    db.close()


def test_query_stream_records_only_new_seats(tmp_path):
    import struct

    from license_manager_simulators.monitor.capture import _observe_query_stream

    db = AuditDatabase(str(tmp_path / "capture.sqlite"), 123)
    listener = Listener(456, 59001, "lmgrd", 123456)
    state = {"features": {}, "holders": {}, "recent_identity": {}}
    # a stale holder guess must NOT win over the checkout-timestamp join
    state["holders"][("userx", "qa-srv47")] = (
        "userx", "qa-srv47", "99999", "/dev/tty", "x64_lsb",
    )
    session = ("10.20.64.212", 5000, "10.20.86.79", 59001)

    def lsf(frame_type: int, body: bytes) -> bytes:
        return struct.pack("!4sHBBI", b"\x2f\x01\x02\x03", 12 + len(body), 1, frame_type, 0) + body

    # the checkout attempt whose encrypted 0x3d carried this seat's start epoch
    db.flexlm_event(
        1, listener, feature=None, client_user="userx", client_host="qa-srv47",
        quantity=None, status="FLEXLM_CHECKOUT_ATTEMPT", reason=None,
        request_frame_id=None, correlation="IDENTITY_FROM_GREETING",
        client_pid="23578", client_tty="/dev/pts/42", client_platform="x64_lsb",
        checkout_ts=1790861015,
    )
    query = lsf(0x3C, b"\x00" * 8 + b"QZ\x00")
    seat = lsf(0x14, (
        b"\x00" * 8 + b"userx\x00qa-srv47\x00/dev/pts/42\x001.0\x00"
        + b"\x00" * 4 + b"\x01\x00\x00\x00" + struct.pack("!I", 1790861015)
        + b"\x00" * 4 + struct.pack("!I", 49202)
    ))
    segment = Segment("10.20.64.212", 5000, "10.20.86.79", 59001, 1, False, False, False, query)
    state["recent_identity"][session[0]] = ("userx", "qa-srv47", "23578", "/dev/pts/42", "x64_lsb")

    _observe_query_stream(db, listener, session, "client_to_server", segment, [query], state)
    _observe_query_stream(db, listener, session, "server_to_client", segment, [seat], state)
    assert db.conn.execute("""SELECT feature, client_user, client_host, checkout_id,
        client_pid, client_tty, client_platform, checkout_ts, status FROM license_events
        WHERE status='FLEXLM_IN_USE'""").fetchone() == (
        "QZ", "userx", "qa-srv47", "49202", "23578", "/dev/pts/42", "x64_lsb",
        1790861015, "FLEXLM_IN_USE",
    )
    assert db.conn.execute("""SELECT correlation FROM license_events
        WHERE status='FLEXLM_IN_USE'""").fetchone()[0] == "MATCHED_CHECKOUT_TS"
    # the seat row frame is stored with its checkout_id in decoded_json
    assert db.conn.execute(
        "SELECT COUNT(*) FROM frames WHERE decoded_json LIKE '%49202%'"
    ).fetchone()[0] == 1
    # the same seat re-reported by the poller must not duplicate
    _observe_query_stream(db, listener, session, "server_to_client", segment, [seat], state)
    assert db.conn.execute(
        "SELECT COUNT(*) FROM license_events WHERE status='FLEXLM_IN_USE'"
    ).fetchone()[0] == 1
    db.close()


def test_seat_pid_join_ambiguous_single_and_missing(tmp_path):
    import struct

    from license_manager_simulators.monitor.capture import _observe_query_stream

    db = AuditDatabase(str(tmp_path / "capture.sqlite"), 123)
    listener = Listener(456, 59001, "lmgrd", 123456)
    state = {"features": {}, "holders": {}, "recent_identity": {}}
    state["features"][("10.20.64.212", 5000, "10.20.86.79", 59001)] = ("DEMO_SIM", None)
    session = ("10.20.64.212", 5000, "10.20.86.79", 59001)

    def lsf(frame_type: int, body: bytes) -> bytes:
        return struct.pack("!4sHBBI", b"\x2f\x01\x02\x03", 12 + len(body), 1, frame_type, 0) + body

    def seat(user: str, host: str, ts: int, cid: int) -> bytes:
        return lsf(0x14, (
            b"\x00" * 8 + user.encode() + b"\x00" + host.encode() + b"\x00"
            + b"/dev/tty\x001.0\x00" + b"\x00" * 4 + b"\x01\x00\x00\x00"
            + struct.pack("!I", ts) + b"\x00" * 4 + struct.pack("!I", cid)
        ))

    segment = Segment("10.20.64.212", 5000, "10.20.86.79", 59001, 1, False, False, False, b"")

    def observe(raw: bytes) -> None:
        _observe_query_stream(db, listener, session, "server_to_client", segment, [raw], state)

    # two processes of one user checked out within the same second:
    # the seat must carry the pid SET, never one guessed pid
    for pid in ("31158", "31184"):
        db.flexlm_event(
            1, listener, feature=None, client_user="sample.user", client_host="qa-gui32",
            quantity=None, status="FLEXLM_CHECKOUT_ATTEMPT", reason=None,
            request_frame_id=None, correlation="IDENTITY_FROM_GREETING",
            client_pid=pid, checkout_ts=1790866419,
        )
    observe(seat("sample.user", "qa-gui32", 1790866419, 35684))
    assert db.conn.execute("""SELECT client_pid, correlation FROM license_events
        WHERE status='FLEXLM_IN_USE'""").fetchone() == (
        "31158,31184", "AMBIGUOUS_CHECKOUT_TS",
    )

    # unique attempt at its own second: full attempt identity wins
    db.flexlm_event(
        1, listener, feature=None, client_user="sample.user", client_host="qa-gui32",
        quantity=None, status="FLEXLM_CHECKOUT_ATTEMPT", reason=None,
        request_frame_id=None, correlation="IDENTITY_FROM_GREETING",
        client_pid="31266", client_tty="/dev/tty", client_platform="x64_lsb",
        checkout_ts=1790866421,
    )
    observe(seat("sample.user", "qa-gui32", 1790866421, 45630))
    assert db.conn.execute("""SELECT client_pid, client_tty, client_platform, correlation
        FROM license_events WHERE status='FLEXLM_IN_USE' AND checkout_id=45630
    """).fetchone() == ("31266", "/dev/tty", "x64_lsb", "MATCHED_CHECKOUT_TS")

    # clock skew: no attempt at the seat's exact second, but the same
    # (user, host) checked out 3s earlier -> bounded skew join, clearly marked
    observe(seat("sample.user", "qa-gui32", 1790866424, 53564))
    assert db.conn.execute("""SELECT client_pid, correlation FROM license_events
        WHERE status='FLEXLM_IN_USE' AND checkout_id=53564""").fetchone() == (
        "31266", "MATCHED_CHECKOUT_TS_SKEW",
    )
    # skew window spanning both seconds: pid set, never one guessed pid
    observe(seat("sample.user", "qa-gui32", 1790866422, 53565))
    assert db.conn.execute("""SELECT client_pid, correlation FROM license_events
        WHERE status='FLEXLM_IN_USE' AND checkout_id=53565""").fetchone() == (
        "31158,31184,31266", "AMBIGUOUS_CHECKOUT_TS_SKEW",
    )

    # no attempt within +-3s: NULL pid, no fabricated guess
    observe(seat("sample.user", "qa-gui32", 1790866429, 53566))
    assert db.conn.execute("""SELECT client_pid, correlation FROM license_events
        WHERE status='FLEXLM_IN_USE' AND checkout_id=53566""").fetchone() == (
        None, "NO_CHECKOUT_MATCH",
    )

    # no attempt but a greeting holder exists: holder fallback, clearly marked
    state["holders"][("sample.user", "qa-gui32")] = (
        "sample.user", "qa-gui32", "31266", "/dev/tty", "x64_lsb",
    )
    observe(seat("sample.user", "qa-gui32", 1790866430, 47411))
    assert db.conn.execute("""SELECT client_pid, client_tty, correlation FROM license_events
        WHERE status='FLEXLM_IN_USE' AND checkout_id=47411""").fetchone() == (
        "31266", "/dev/tty", "HOLDER_NO_TS_MATCH",
    )
    # an attempt on ANOTHER host is never joined, even at the same second
    db.flexlm_event(
        1, listener, feature=None, client_user="sample.user", client_host="qa-gui31",
        quantity=None, status="FLEXLM_CHECKOUT_ATTEMPT", reason=None,
        request_frame_id=None, correlation="IDENTITY_FROM_GREETING",
        client_pid="777", checkout_ts=1790866431,
    )
    observe(seat("sample.user", "qa-gui32", 1790866431, 47412))
    assert db.conn.execute("""SELECT client_pid, correlation FROM license_events
        WHERE status='FLEXLM_IN_USE' AND checkout_id=47412""").fetchone() == (
        "31266", "HOLDER_NO_TS_MATCH",
    )
    db.close()


def test_backfill_names_attempts_when_seats_line_up(tmp_path):
    db = AuditDatabase(str(tmp_path / "capture.sqlite"), 123)
    listener = Listener(456, 43095, "vendmock", 123456)

    def attempt(pid: str, ts: int) -> None:
        db.flexlm_event(
            1, listener, feature=None, client_user="sample.user", client_host="qa-gui32",
            quantity=None, status="FLEXLM_CHECKOUT_ATTEMPT", reason=None,
            request_frame_id=None, correlation="IDENTITY_FROM_GREETING",
            client_pid=pid, checkout_ts=ts,
        )

    def seat(cid: int, ts: int, feature: str = "DEMO_AX") -> None:
        db.flexlm_event(
            1, listener, feature=feature, client_user="sample.user", client_host="qa-gui32",
            quantity=1, status="FLEXLM_IN_USE", reason=None, request_frame_id=None,
            correlation="MATCHED_CHECKOUT_TS", checkout_id=cid, checkout_ts=ts,
        )

    # 2 attempts + 2 same-feature seats at the same second: 1:1 lineup
    attempt("31158", 1790866419)
    attempt("31184", 1790866419)
    seat(35684, 1790866419)
    seat(39200, 1790866419)
    assert db.backfill_attempt_features("sample.user", "qa-gui32", 1790866419)
    assert db.conn.execute("""SELECT feature, correlation FROM license_events
        WHERE status='FLEXLM_CHECKOUT_ATTEMPT' ORDER BY client_pid""").fetchall() == [
        ("DEMO_AX", "FEATURE_FROM_SEAT_TS"), ("DEMO_AX", "FEATURE_FROM_SEAT_TS"),
    ]
    # idempotent: no feature-less attempts left
    assert not db.backfill_attempt_features("sample.user", "qa-gui32", 1790866419)

    # count mismatch (1 attempt, 2 seats): stays unnamed
    attempt("31214", 1790866422)
    seat(50600, 1790866422, "DEMO_SIM")
    seat(10286, 1790866422, "DEMO_SIM")
    assert not db.backfill_attempt_features("sample.user", "qa-gui32", 1790866422)
    assert db.conn.execute("""SELECT feature FROM license_events
        WHERE status='FLEXLM_CHECKOUT_ATTEMPT' AND checkout_ts=1790866422
    """).fetchone()[0] is None

    # mixed features at one second: stays unnamed
    attempt("31241", 1790866423)
    seat(39200, 1790866423, "DEMO_AX")
    seat(46039, 1790866423, "DEMO_SIM")
    assert not db.backfill_attempt_features("sample.user", "qa-gui32", 1790866423)
    db.close()


def test_checkout_request_links_timestamp_to_attempt(tmp_path):
    import time

    from license_manager_simulators.monitor.capture import _observe_flexlm
    from license_manager_simulators.monitor.flexlm import decode_flexlm_frame

    def lsf(frame_type: int, body: bytes) -> bytes:
        return struct.pack("!4sHBBI", b"\x2f\x01\x02\x03", 12 + len(body), 1, frame_type, 0) + body

    db = AuditDatabase(str(tmp_path / "capture.sqlite"), 123)
    listener = Listener(456, 43095, "vendmock", 123456)
    state = {
        "features": {}, "identities": {}, "recent_identity": {},
        "lookups": {}, "session_ids": {}, "holders": {}, "pid_feature": {},
        "crypto_seen": set(), "checkout_requests": {},
    }
    session = ("10.32.9.217", 58464, "10.20.86.79", 43095)
    greeting = {
        "proto": "eda-greeting", "user": "sample.user", "host": "qa-gui32",
        "pid": "31158", "tty": "/dev/tty", "platform": "x64_lsb",
        "daemon": "vendmock",
    }
    _observe_flexlm(db, listener, session, "client_to_server", 300, greeting, state)

    # the 0x3d checkout request promotes its 8-hex epoch string
    ts = int(time.time())
    ftype, payload = decode_flexlm_frame(
        lsf(0x3D, b"\x00" * 10 + f"{ts:08x}".encode() + b"\x00" + b"\x11" * 13),
        "client_to_server",
    )
    assert (ftype, payload["checkout_ts"]) == (0x3D, ts)
    _observe_flexlm(db, listener, session, "client_to_server", 303, payload, state)

    # its 0x61 response fires the attempt, carrying ts and request frame
    _, rsp = decode_flexlm_frame(lsf(0x61, b"\x00" * 24), "server_to_client")
    _observe_flexlm(db, listener, session, "server_to_client", 305, rsp, state)
    assert db.conn.execute("""SELECT request_frame_id, checkout_ts, client_pid,
        client_user, client_host, feature, status FROM license_events""").fetchone() == (
        303, ts, "31158", "sample.user", "qa-gui32", None, "FLEXLM_CHECKOUT_ATTEMPT",
    )
    db.close()


def test_prune_caps_tables_and_dedups_client_sessions(tmp_path, monkeypatch):
    import license_manager_simulators.monitor.capture as cap
    from datetime import UTC, datetime, timedelta

    monkeypatch.setattr(cap, "RETENTION_ROWS", 50)
    db = AuditDatabase(str(tmp_path / "capture.sqlite"), 123)
    now = datetime.now(UTC)
    old = (now - timedelta(hours=2)).isoformat()
    fresh = now.isoformat()

    for _ in range(55):
        db.conn.execute(
            "INSERT INTO frames (observed_at,manager_pid,server_pid,server_port,src_ip,"
            "src_port,dst_ip,dst_port,direction,decode_status,raw_hex,raw_bytes) "
            "VALUES (?,123,30907,43095,'10.0.0.1',40000,'10.0.0.2',43095,"
            "'client_to_server','FLEXLM_DECODED',x'00',x'00')", (fresh,),
        )
        db.conn.execute(
            "INSERT INTO tcp_segments (observed_at,server_pid,server_port,src_ip,"
            "src_port,dst_ip,dst_port,seq,direction,payload_hex,payload_bytes) "
            "VALUES (?,30907,43095,'10.0.0.1',40000,'10.0.0.2',43095,1,"
            "'client_to_server',x'00',x'00')", (fresh,),
        )
        db.conn.execute(
            "INSERT INTO license_events (observed_at,server_pid,server_port,status,"
            "response_frame_id,correlation) VALUES (?,30907,43095,'FLEXLM_IN_USE',1,'X')",
            (fresh,),
        )

    def session_row(observed_at: str) -> None:
        db.conn.execute(
            "INSERT INTO client_sessions (observed_at,server_pid,server_port,daemon,"
            "client_ip,client_port,client_user,client_host,client_pid,client_tty,"
            "client_platform,greeting_daemon,feature,greeting_frame_id) "
            "VALUES (?,30907,43095,'vendmock','10.0.0.1',40000,'userx','qa-srv47',"
            "'2670','/dev/tty','x64_lsb','vendmock','QZ',NULL)", (observed_at,),
        )

    session_row(old)
    for _ in range(cap.DEDUP_KEEP + 3):
        session_row(fresh)
    db.conn.commit()

    db.prune()

    for table in ("frames", "tcp_segments", "license_events"):
        count = db.conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
        assert count == 50, table
    # identical tuples collapse to the newest DEDUP_KEEP; the old row is gone
    assert db.conn.execute("SELECT COUNT(*) FROM client_sessions").fetchone()[0] == cap.DEDUP_KEEP
    assert db.conn.execute(
        "SELECT COUNT(*) FROM client_sessions WHERE observed_at = ?", (old,)
    ).fetchone()[0] == 0
    db.close()


def _run_bpf(insns, data):
    """Minimal classic-BPF interpreter covering the opcodes attach_bpf emits."""
    pc, acc, x = 0, 0, 0
    while True:
        code, jt, jf, k = insns[pc]
        if code == 0x28:    # ldh [k]
            acc = int.from_bytes(data[k:k + 2], "big")
        elif code == 0x48:  # ldh [x + k]
            acc = int.from_bytes(data[x + k:x + k + 2], "big")
        elif code == 0xB1:  # ldx 4*([k]&0xf)
            x = 4 * (data[k] & 0xF)
        elif code == 0x15:  # jeq k
            pc = pc + 1 + (jt if acc == k else jf)
            continue
        elif code == 0x06:  # ret k
            return k
        else:
            raise AssertionError(f"unsupported opcode {code:#x}")
        pc += 1


def _eth_ip_tcp(src_port, dst_port, ihl=5, ethertype=0x0800):
    options = b"\x01\x01\x01\x01" if ihl == 6 else b""
    tcp = struct.pack(">HHIIBBHHH", src_port, dst_port, 0, 0, 5 << 4, 0x18, 8192, 0, 0)
    ip = struct.pack(
        ">BBHHHBBH4s4s", (4 << 4) | ihl, 0, ihl * 4 + len(tcp), 0, 0, 64, 6, 0,
        b"\x0a\x00\x00\x01", b"\x0a\x00\x00\x02") + options + tcp
    return struct.pack(">12sH", b"\x00" * 12, ethertype) + ip


def test_bpf_instructions_layout_and_empty_rejects_all():
    insns = cap._bpf_instructions({43095, 1234})
    assert len(insns) == 3 + 4 * 2 + 2
    assert insns[-2] == (0x06, 0, 0, 0)
    assert insns[-1] == (0x06, 0, 0, 0x40000)
    empty = cap._bpf_instructions([])
    assert len(empty) == 5
    frame = _eth_ip_tcp(1234, 43095)
    assert _run_bpf(empty, frame) == 0


def test_bpf_filter_accepts_only_license_ports():
    insns = cap._bpf_instructions({43095})
    assert _run_bpf(insns, _eth_ip_tcp(50000, 43095)) == 0x40000  # to license port
    assert _run_bpf(insns, _eth_ip_tcp(43095, 50000)) == 0x40000  # from license port
    assert _run_bpf(insns, _eth_ip_tcp(50001, 2049)) == 0         # unrelated ports
    assert _run_bpf(insns, _eth_ip_tcp(50000, 43095, ihl=6)) == 0x40000  # IP options
    arp = struct.pack(">12sH", b"\xff" * 6, 0x0806) + b"\x00" * 28
    assert _run_bpf(insns, arp) == 0                            # non-IPv4
    assert _run_bpf(insns, _eth_ip_tcp(50000, 43095, ethertype=0x86DD)) == 0  # ipv6


def test_bpf_filter_multiple_ports_match_each():
    insns = cap._bpf_instructions({111, 222, 333})
    for port in (111, 222, 333):
        assert _run_bpf(insns, _eth_ip_tcp(40000, port)) == 0x40000
        assert _run_bpf(insns, _eth_ip_tcp(port, 40000)) == 0x40000
    assert _run_bpf(insns, _eth_ip_tcp(40000, 444)) == 0


def test_handle_packet_drop_mode_excludes_query_streams(tmp_path):
    """--self-query: external pollers' query streams leave no trace at all."""
    def lsf(frame_type: int, body: bytes) -> bytes:
        return struct.pack("!4sHBBI", b"\x2f\x01\x02\x03", 12 + len(body), 1, frame_type, 0) + body

    def raw_packet(payload: bytes, src_port: int = 5000, dst_port: int = 59001) -> bytes:
        tcp = struct.pack(">HHIIBBHHH", src_port, dst_port, 0, 0, 5 << 4, 0x18, 8192, 0, 0) + payload
        ip = struct.pack(">BBHHHBBH4s4s", 0x45, 0, 20 + len(tcp), 0, 0, 64, 6, 0,
                         b"\x0a\x00\x00\x01", b"\x0a\x00\x00\x02") + tcp
        return b"\x00" * 12 + struct.pack(">H", 0x0800) + ip

    def channel(mode: str) -> dict:
        return {"iface": "ens1f0", "mode": mode, "streams": {}, "requests": {},
                "query_streams": set()}

    db = AuditDatabase(str(tmp_path / "capture.sqlite"), 123)
    listener = Listener(456, 59001, "lmgrd", 123456)
    listeners = {59001: listener}
    state = {
        "features": {}, "identities": {}, "recent_identity": {},
        "lookups": {}, "session_ids": {}, "holders": {}, "pid_feature": {},
        "crypto_seen": set(), "checkout_requests": {}, "poller_details": {},
    }
    address = ("ens1f0", 0, cap.PACKET_OUTGOING, 1, b"")
    query_frame = lsf(0x3C, b"\x00" * 8 + b"DEMO_AX\x00")

    # full mode stores the query frame
    full = channel("full")
    cap._handle_packet(db, raw_packet(query_frame), address, full, listeners, state)
    assert db.conn.execute("SELECT COUNT(*) FROM frames").fetchone()[0] == 1

    # drop mode marks the stream, discards it, and records nothing
    drop = channel("drop")
    cap._handle_packet(db, raw_packet(query_frame), address, drop, listeners, state)
    assert drop["query_streams"]
    assert not drop["streams"]
    assert db.conn.execute("SELECT COUNT(*) FROM frames").fetchone()[0] == 1  # unchanged
    cap._handle_packet(db, raw_packet(lsf(0x4E, b"\x00" * 24)), address, drop, listeners, state)
    cap._handle_packet(db, raw_packet(lsf(0x14, b"\x00" * 48)), address, drop, listeners, state)
    assert db.conn.execute("SELECT COUNT(*) FROM frames").fetchone()[0] == 1
    assert db.conn.execute("SELECT COUNT(*) FROM poller_summaries").fetchone()[0] == 0
    assert db.conn.execute("SELECT COUNT(*) FROM license_events").fetchone()[0] == 0

    # a fresh client stream (no query frame types) is not marked in drop mode
    drop2 = channel("drop")
    cap._handle_packet(
        db, raw_packet(lsf(0x3D, b"\x00" * 32), dst_port=59002), address, drop2,
        {59002: Listener(457, 59002, "lmgrd", 123457)}, state)
    assert not drop2["query_streams"]
    db.close()


def test_wire_daemon_overrides_process_name(tmp_path):
    """poller_details.daemon comes from the daemon's own 0x0e hello on its
    connection (strings[1]), falling back to the /proc process name."""
    db = AuditDatabase(str(tmp_path / "capture.sqlite"), 123)
    listener = Listener(456, 43095, "vendmock_renamed", 123456)
    state = {
        "features": {}, "holders": {}, "recent_identity": {},
        "poller_details": {}, "daemon_by_port": {},
    }
    # gate: the hello needs a daemon name as its second string
    cap._record_daemon_name(state, 43095, {"strings": ["qa-srv85"]})
    assert state["daemon_by_port"] == {}
    cap._record_daemon_name(state, 43095, {"strings": ["qa-srv85", "vendmock"]})
    assert state["daemon_by_port"] == {43095: "vendmock"}
    # ports the daemon never said hello on keep the process-name attribution
    assert cap._wire_listener(state, Listener(456, 59001, None, 1)).daemon is None
    wired = cap._wire_listener(state, listener)
    assert wired.daemon == "vendmock"
    assert (wired.pid, wired.port, wired.inode) == (456, 43095, 123456)

    # a flushed seat observation is attributed to the wire daemon
    session = ("10.20.64.212", 5000, "10.20.86.79", 43095)
    cap._accumulate_poller_detail(
        state, session, "SYN_READER", "userx", "qa-srv63", "/dev/tty", "1.0",
        35684, 1790866419, None, "NO_CHECKOUT_MATCH")
    cap._flush_poller_details(db, state, session, wired)
    rows = db.conn.execute(
        "SELECT daemon, feature FROM poller_details").fetchall()
    assert rows == [("vendmock", "SYN_READER")]
    db.close()


def test_license_definitions_parsed_from_i_dump_text(tmp_path):
    """The lmstat -i dump carries the license file as raw wire text; lines
    may span TCP segments. license_definitions keeps the newest
    POLLER_OBSERVATIONS rows per feature."""
    db = AuditDatabase(str(tmp_path / "capture.sqlite"), 123)
    listener = Listener(456, 59001, None, 123456)
    state = {"lic_buffers": {}}
    session = ("127.0.0.1", 40000, "127.0.0.1", 59001)

    dump1 = (
        'INCREMENT DEMO_AX vendmock 1.0 29-nov-2027 45 SIGN="077A E9DD"\\\r\n'
        '\tVENDOR_STRING=UHD vendor_info=x\r\n'
        'INCREMENT SYN_STAMP vendmock 1.0 31-dec-2026 500 SIGN="0340"\\\r\n'
        '# comment lines are skipped\r\n'
        'FEATURE 222 vendyy 25.1 04-jan-2027 1 9FADE185479208D4A940 \\\r\n'
        'INCREMENT DEMO_AX vendmock 1.0 29-nov-2027 45 SIGN="077A"\\'
    )
    # split mid-line to exercise the partial-line buffer
    cut = dump1.index("29-nov-2027 45")
    cap._parse_license_lines(db, state, session, listener, dump1[:cut].encode())
    assert db.conn.execute("SELECT COUNT(*) FROM license_definitions").fetchone()[0] == 0
    cap._parse_license_lines(db, state, session, listener, dump1[cut:].encode())
    rows = db.conn.execute("""SELECT keyword, feature, vendor, version, expiry, seats
        FROM license_definitions ORDER BY id""").fetchall()
    assert rows == [
        ("INCREMENT", "DEMO_AX", "vendmock", "1.0", "29-nov-2027", 45),
        ("INCREMENT", "SYN_STAMP", "vendmock", "1.0", "31-dec-2026", 500),
        ("FEATURE", "222", "vendyy", "25.1", "04-jan-2027", 1),
    ]
    # the trailing partial line ('...SIGN="077A"\\') stays buffered, not a row
    assert state["lic_buffers"][session].endswith('SIGN="077A"\\')

    # per-feature rolling window: POLLER_OBSERVATIONS rows for DEMO_AX
    for cycle in range(cap.POLLER_OBSERVATIONS + 1):
        cap._parse_license_lines(
            db, state, session, listener,
            b'INCREMENT DEMO_AX vendmock 1.0 29-nov-2027 45 SIGN="x"\r\n')
    kept = db.conn.execute(
        "SELECT COUNT(*) FROM license_definitions WHERE feature='DEMO_AX'"
    ).fetchone()[0]
    assert kept == cap.POLLER_OBSERVATIONS
    db.close()


def test_self_query_timeout_rolls_back_partial_dump(tmp_path):
    """A dump exceeding --lmstat-timeout is all-or-nothing: its partial rows
    are deleted for the service's ports only, and the failure is logged in
    self_query_errors."""
    db = AuditDatabase(str(tmp_path / "capture.sqlite"), 123)
    bad = Listener(456, 5280, "lmgrd", 1)      # timed-out service's mgr port
    good = Listener(789, 59001, "lmgrd", 2)   # unrelated service keeps rows
    since = cap._now()

    db.poller_summary(1, bad, feature="222", in_use=2, issued=31,
                      report_ts=1790880000, request_frame_id=None,
                      correlation="MATCHED_FLEXLM_QUERY")
    db.license_definition(bad, keyword="INCREMENT", feature="222",
                          vendor="vendyy", version="25.1",
                          expiry="04-jan-2027", seats=31, line="INCREMENT 222 ...")
    db.flexlm_event(2, bad, feature="222", client_user="guest.accountx",
                    client_host="qa-srv52", quantity=1, status="FLEXLM_IN_USE",
                    reason=None, request_frame_id=None, correlation="MATCHED_FLEXLM_QUERY",
                    checkout_id=123, checkout_ts=1790880000)
    db.flexlm_event(3, bad, feature=None, client_user="guest.accountx",
                    client_host="qa-srv52", quantity=None,
                    status="FLEXLM_CHECKOUT_ATTEMPT", reason="greeting",
                    request_frame_id=None, correlation="IDENTITY_FROM_GREETING")
    # an unrelated service's rows survive the rollback
    db.poller_summary(4, good, feature="SYN_READER", in_use=1, issued=500,
                      report_ts=1790880000, request_frame_id=None,
                      correlation="MATCHED_FLEXLM_QUERY")

    rolled = db.rollback_partial_dump(2072243, [5280], since)
    assert rolled == 3  # summary + definition + IN_USE seat
    assert db.conn.execute("SELECT COUNT(*) FROM poller_summaries").fetchone()[0] == 1
    assert db.conn.execute("SELECT COUNT(*) FROM license_definitions").fetchone()[0] == 0
    # checkout attempts are never touched (they come from the --iface socket)
    assert db.conn.execute("""SELECT COUNT(*) FROM license_events
        WHERE status='FLEXLM_CHECKOUT_ATTEMPT'""").fetchone()[0] == 1
    assert db.conn.execute("""SELECT COUNT(*) FROM license_events
        WHERE status='FLEXLM_IN_USE'""").fetchone()[0] == 0

    db.self_query_error(2072243, 5280, 5.3,
                        "timeout: lmstat exceeded 5s; rolled back 3 partial rows")
    err = db.conn.execute("""SELECT manager_pid, mgr_port, elapsed_s, reason
        FROM self_query_errors ORDER BY id DESC LIMIT 1""").fetchone()
    assert err == (2072243, 5280, 5.3,
                   "timeout: lmstat exceeded 5s; rolled back 3 partial rows")
    # empty port list is a no-op
    assert db.rollback_partial_dump(1, [], since) == 0
    db.close()
