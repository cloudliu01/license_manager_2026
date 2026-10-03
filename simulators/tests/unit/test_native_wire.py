import socket
import struct

from license_manager_simulators.lmgrd import native
from license_manager_simulators.monitor.capture import Segment, Stream
from license_manager_simulators.monitor.flexlm import decode_flexlm_frame


def test_greeting_round_trip_and_monitor_compat():
    raw = native.encode_greeting("alice", "client.example.com", "vend", "/dev/tty", 4242, "x64_lsb")
    assert len(raw) == native.GREETING_SIZE
    assert raw[0] == 0x68 and raw[2:4] == b"13"
    fields = native.decode_greeting(raw)
    assert fields == {"user": "alice", "host": "client.example.com", "daemon": "vend",
                      "tty": "/dev/tty", "pid": 4242, "platform": "x64_lsb"}
    _, decoded = decode_flexlm_frame(raw, "client_to_server")
    assert decoded["proto"] == "eda-greeting"
    # The passive decoder identifies greeting fields from offset 4.
    assert [field["value"] for field in decoded["fields"][:2]] == ["alice", "client.example.com"]
    # Fixed real-layout slots: the monitor must recover every identity field.
    assert (decoded["user"], decoded["host"], decoded["daemon"]) == (
        "alice", "client.example.com", "vend")
    assert (decoded["tty"], decoded["pid"], decoded["platform"]) == (
        "/dev/tty", "4242", "x64_lsb")


def test_ping_layout_matches_capture():
    request = native.encode_ping(client=True)
    reply = native.encode_ping(client=False)
    assert len(request) == len(reply) == native.PING_SIZE
    assert request[0] == 0x3C and request[2] == 0x30 and request[12:14] == b"0\x00"
    assert reply[0] == 0x3E
    assert native.looks_like_ping(request) and native.looks_like_ping(reply)


def test_broker_frame_layout_and_round_trip():
    request = native.encode_frame(native.REQUEST_TYPE, ["u1", "h1", "vend", "/dev/tty", "usage", "alpha"], client=True)
    assert struct.unpack_from("!H", request, 4)[0] == len(request)
    assert request[6] == 1 and request[7] == native.REQUEST_TYPE
    assert request[20:22] == native.REQUEST_PROLOGUE
    assert request[22:27] == b"u1\x00h1"
    message_type, strings, ts = native.decode_frame(request)
    assert (message_type, strings) == (native.REQUEST_TYPE, ["u1", "h1", "vend", "/dev/tty", "usage", "alpha"])
    assert ts > 0

    seats = native.encode_frame(native.SEATS_TYPE, ["500", "1790533012"], client=False)
    assert struct.unpack_from("!H", seats, 4)[0] == len(seats)
    assert seats[6] == 0 and seats[7] == native.SEATS_TYPE
    assert seats[20:25] == native.RESPONSE_PROLOGUE
    message_type, strings, _ = native.decode_frame(seats)
    assert message_type == native.SEATS_TYPE
    assert strings == ["500", "1790533012"]


def test_monitor_stream_decodes_simulator_native_traffic():
    request = native.encode_frame(native.REQUEST_TYPE, ["u1", "h1", "vend", "/dev/tty", "usage", "alpha"], client=True)
    query = native.encode_frame(native.QUERY_TYPE, ["alpha"], client=True)
    seats = native.encode_frame(native.SEATS_TYPE, ["3", "500", "1790533012"], client=False)
    listing = native.encode_frame(native.LISTING_TYPE, ["FEATURE alpha 5 01-nov-2026 vend"], client=False)
    greeting = native.encode_greeting("u1", "client.example.com", "lmgrd", "/dev/tty", 7, "x64_lsb")
    ping = native.encode_ping(client=True)

    client_stream, server_stream, ping_stream = Stream(), Stream(), Stream()

    def feed(stream, seq, payload):
        return stream.feed(Segment("1.1.1.1", 5000, "2.2.2.2", 59001, seq, False, False, False, payload))

    frames = []
    offset = 1000
    for payload in (greeting, request, query):
        frames += feed(client_stream, offset, payload)
        offset += len(payload)
    for payload in (seats, listing):
        frames += feed(server_stream, offset, payload)
        offset += len(payload)
    assert client_stream.finish() == []
    frames += feed(ping_stream, 5000, ping)
    frames += ping_stream.finish()

    assert frames == [greeting, request, query, seats, listing, ping]
    decoded = [decode_flexlm_frame(frame, "client_to_server") for frame in frames[:3]]
    decoded += [decode_flexlm_frame(frame, "server_to_client") for frame in frames[3:5]]
    decoded += [decode_flexlm_frame(frames[5], "client_to_server")]
    assert all(item is not None for item in decoded)
    assert [(item[0], item[1]["proto"]) for item in decoded] == [
        (None, "eda-greeting"),
        (native.REQUEST_TYPE, "lsf-broker"),
        (native.QUERY_TYPE, "lsf-broker"),
        (native.SEATS_TYPE, "lsf-broker"),
        (native.LISTING_TYPE, "lsf-broker"),
        (None, "lmgrd-ping"),
    ]
    assert [field["value"] for field in decoded[0][1]["fields"][:2]] == ["u1", "client.example.com"]
    assert decoded[1][1]["strings"] == ["u1", "h1", "vend", "/dev/tty", "usage", "alpha"]
    assert decoded[1][1]["user"] == "u1"
    # The passive decoder attributes the calibrated 0x4e layout.
    assert decoded[2][1]["feature"] == "alpha"
    assert decoded[3][1]["in_use"] == 3
    assert decoded[3][1]["issued"] == 500
    assert decoded[4][1]["strings"] == ["FEATURE alpha 5 01-nov-2026 vend"]


def test_frame_rejects_bad_declared_length():
    frame = bytearray(native.encode_frame(native.LISTING_TYPE, ["x"], client=False))
    frame[4:6] = b"\xff\xff"
    try:
        native.decode_frame(bytes(frame))
    except native.ProtocolError as exc:
        assert "INVALID_LENGTH" in str(exc)
    else:
        raise AssertionError("expected ProtocolError")


def test_seat_tail_roundtrip_through_monitor_decoder():
    tail = native.seat_tail(1790866419, 0x814E)
    row = native.encode_frame(
        native.USER_TYPE, ["bob", "hostB", "/dev/pts/9", "1.0", "GRANTED"],
        client=False, tail=tail,
    )
    assert len(row[-8:-4]) == 4 and row[-8:-4] == b"\x00\x00\x00\x00"
    # monitor promotion: start epoch + checkout id from the verified tail
    ftype, decoded = decode_flexlm_frame(row, "server_to_client")
    assert (ftype, decoded["start_ts"], decoded["checkout_id"]) == (0x14, 1790866419, 0x814E)
    assert decoded["user"] == "bob" and decoded["tty"] == "/dev/pts/9"
    # lmstat client parsing: the named fields survive the trailing binary
    message_type, strings, _ = native.decode_frame(row)
    assert message_type == native.USER_TYPE
    assert strings[:5] == ["bob", "hostB", "/dev/pts/9", "1.0", "GRANTED"]


def test_checkout_num_stable():
    first = native.checkout_num("6f1a2b3c-0000-4000-8000-000000000001")
    assert first == native.checkout_num("6f1a2b3c-0000-4000-8000-000000000001")
    assert 0 <= first <= 0xFFFFFFFF
    assert native.checkout_num("not-a-uuid") == native.checkout_num("not-a-uuid")


def test_checkout_request_promotes_client_epoch():
    import time

    ts = int(time.time())
    raw = native.encode_checkout_request(ts)
    assert len(raw) == native.CHECKOUT_REQ_FRAME_SIZE
    ftype, decoded = decode_flexlm_frame(raw, "client_to_server")
    assert ftype == native.CHECKOUT_REQ_TYPE
    assert decoded["checkout_ts"] == ts


def test_serve_native_checkout_exchange():
    import threading

    recorded = []

    def handler(feature, greeting, ts):
        recorded.append((feature, dict(greeting), ts))

    def responder(command, argument):
        return [
            (native.SEATS_TYPE, ["1", "5", "1790533012"]),
            (native.USER_TYPE, ["bob", "hostB", "/dev/pts/9", "1.0", "GRANTED"],
             native.seat_tail(1790866419, 77)),
        ], ""

    server, client = socket.socketpair()
    thread = threading.Thread(
        target=native.serve_native,
        args=(server, "vend", responder),
        kwargs={"checkout_handler": handler},
        daemon=True,
    )
    thread.start()
    try:
        client.settimeout(2)
        client.sendall(native.encode_greeting("alice", "hA", "vend", "/dev/tty", 42, "x64_lsb"))
        hello = native.recv_broker_frame(client)
        assert hello is not None and hello[0] == native.HELLO_TYPE

        ts = 1790866419
        client.sendall(native.encode_frame(native.PARAMS_TYPE, ["alpha"], client=True))
        reply = native.recv_broker_frame(client)
        assert reply is not None and reply[0] == native.CRYPTO_RESPONSE_TYPE
        client.sendall(native.encode_frame(
            native.DAEMON_HANDSHAKE_TYPE, [native.DAEMON_NAME], client=True))
        reply = native.recv_broker_frame(client)
        assert reply is not None and reply[0] == native.GRANT_TYPE
        client.sendall(native.encode_checkout_request(ts))
        reply = native.recv_broker_frame(client)
        assert reply is not None and reply[0] == native.CHECKOUT_RETURN_TYPE
        assert recorded == [("alpha", {"user": "alice", "host": "hA", "daemon": "vend",
                                      "tty": "/dev/tty", "pid": 42, "platform": "x64_lsb"}, ts)]

        # the usage responder's 0x14 row carries the verified binary tail:
        # raw-read it and confirm via the monitor decoder
        client.sendall(native.encode_frame(native.QUERY_TYPE, ["alpha"], client=True))
        seats = native.recv_broker_frame(client)
        assert seats is not None and seats[0] == native.SEATS_TYPE
        header = b""
        while len(header) < 12:
            header += client.recv(12 - len(header))
        declared = struct.unpack_from("!H", header, 4)[0]
        rest = b""
        while len(rest) < declared - 12:
            rest += client.recv(declared - 12 - len(rest))
        ftype, decoded = decode_flexlm_frame(header + rest, "server_to_client")
        assert ftype == native.USER_TYPE
        assert decoded["start_ts"] == ts and decoded["checkout_id"] == 77
        end = native.recv_broker_frame(client)
        assert end is not None and end[0] == native.END_TYPE
    finally:
        client.close()
        server.close()
        thread.join(timeout=2)


def test_serve_native_greeting_ping_and_usage(tmp_path):
    import threading

    def responder(command, argument):
        if command == "usage":
            return [
                (native.SEATS_TYPE, ["1", "5", "1790533012"]),
                (native.USER_TYPE, ["bob", "hostB", "/dev/pts/9", "1.0", "GRANTED"]),
            ], ""
        return [], "UNKNOWN_COMMAND"

    server, client = socket.socketpair()
    thread = threading.Thread(
        target=native.serve_native, args=(server, "vend", responder), daemon=True)
    thread.start()
    try:
        client.settimeout(2)
        client.sendall(native.encode_greeting("alice", "h", "vend", "/dev/tty", 1, "x64_lsb"))
        hello = native.recv_broker_frame(client)
        assert hello is not None and hello[0] == native.HELLO_TYPE and hello[1][1] == "vend"

        # 0x3c feature query dispatches as the usage command.
        client.sendall(native.encode_frame(native.QUERY_TYPE, ["alpha"], client=True))
        replies = []
        while True:
            frame = native.recv_broker_frame(client)
            assert frame is not None
            replies.append(frame)
            if frame[0] == native.END_TYPE:
                break
        assert [frame[0] for frame in replies] == [
            native.SEATS_TYPE, native.USER_TYPE, native.END_TYPE]
        assert replies[0][1] == ["1", "5", "1790533012"]
        assert replies[1][1] == ["bob", "hostB", "/dev/pts/9", "1.0", "GRANTED"]
        assert replies[2][1] == []
    finally:
        client.close()
        server.close()
        thread.join(timeout=2)

    ping_server, ping_client = socket.socketpair()
    ping_thread = threading.Thread(
        target=native.serve_native, args=(ping_server, "vend", responder), daemon=True)
    ping_thread.start()
    try:
        ping_client.settimeout(2)
        ping_client.sendall(native.encode_ping(client=True))
        reply = ping_client.recv(native.PING_SIZE)
        assert native.looks_like_ping(reply) and reply[0] == 0x3E
    finally:
        ping_client.close()
        ping_server.close()
        ping_thread.join(timeout=2)
