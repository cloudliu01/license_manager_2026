import json
import socket
import struct

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
