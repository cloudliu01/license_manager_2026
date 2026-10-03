"""Named-field extraction from real FlexLM frame layouts.

Frames follow the node0 capture layout: 12-byte broker
header, fixed prologue zones, NUL-terminated strings.
"""
import struct

from license_manager_simulators.monitor.flexlm import decode_flexlm_frame


def broker(frame_type: int, strings: list[bytes], direction: str, ver: int = 1) -> bytes:
    """C->S frames: 0x3c/0x47 carry name+param after an 8-byte prologue
    (string region at 20); other requests use a 10-byte prologue (region at
    22). S->C frames: 8-byte prologue then strings (region at 20)."""
    if direction == "client_to_server":
        prologue = b"\x00" * (8 if frame_type in (0x3C, 0x47) else 10)
    else:
        prologue = b"\x00" * 8
    body = prologue + b"\x00".join(strings) + (b"\x00" if strings else b"")
    total = 12 + len(body)
    head = struct.pack("!4sHBBI", b"\x2f\x01\x02\x03", total, ver, frame_type, 0)
    return head + body


def test_feature_query_carries_name_and_handle():
    raw = broker(0x3C, [b"DEMO_FEATUREX", b"1111 2222 3333 4444"], "client_to_server")
    _, decoded = decode_flexlm_frame(raw, "client_to_server")
    assert decoded["feature"] == "DEMO_FEATUREX"
    assert decoded["feature_handle"] == "1111 2222 3333 4444"

    short = broker(0x3C, [b"FX", b"AAAA BBBB CCCC DDDD"], "client_to_server")
    _, decoded = decode_flexlm_frame(short, "client_to_server")
    assert decoded["feature"] == "FX"
    assert decoded["feature_handle"] == "AAAA BBBB CCCC DDDD"


def test_seat_summary_calibrated_triplet():
    raw = broker(0x4E, [b"Nz100", b"500", b"1790605334"], "server_to_client", ver=0)
    _, decoded = decode_flexlm_frame(raw, "server_to_client")
    assert decoded["in_use"] == 100
    assert decoded["issued"] == 500
    assert decoded["report_ts"] == 1790605334
    assert "port_candidates" not in decoded


def test_seat_summary_single_digit_in_use():
    # minlen=1 harvesting splits the "N\x19 0" field into junk "N" plus "0";
    # digit-less tokens must be dropped before positional attribution.
    raw = broker(0x4E, [b"N", b"0", b"500", b"1790605334"], "server_to_client", ver=0)
    _, decoded = decode_flexlm_frame(raw, "server_to_client")
    assert decoded["in_use"] == 0
    assert decoded["issued"] == 500
    assert decoded["report_ts"] == 1790605334


def test_seat_summary_degenerate_variant_stays_unattributed():
    raw = broker(0x4E, [b"500", b"1790605349"], "server_to_client", ver=0)
    _, decoded = decode_flexlm_frame(raw, "server_to_client")
    assert decoded["counts"] == [500]
    assert decoded["report_ts"] == 1790605349
    assert "in_use" not in decoded and "issued" not in decoded


def test_user_row_promotion():
    raw = broker(
        0x14, [b"sample.account", b"node0001", b"/dev/pts/10", b"1.0"],
        "server_to_client",
    )
    _, decoded = decode_flexlm_frame(raw, "server_to_client")
    assert decoded["user"] == "sample.account"
    assert decoded["host"] == "node0001"
    assert decoded["tty"] == "/dev/pts/10"
    assert decoded["version"] == "1.0"
    assert "port_candidates" not in decoded


def test_user_row_checkout_id_and_start_ts():
    # verified qa-ls tail: pad, flag, start epoch (BE), pad, checkout id (BE);
    # lmstat prints the id as "(qa-ls/59001 49202)"
    raw = bytearray(broker(
        0x14, [b"userx", b"qa-srv47.placeholder.invalid", b"/dev/pts/42", b"1.0"],
        "server_to_client",
    ))
    tail = (
        b"\x00\x00\x00\x00" + b"\x01\x00\x00\x00"
        + struct.pack("!I", 1790861015) + b"\x00\x00\x00\x00"
        + struct.pack("!I", 49202)
    )
    raw[4:6] = struct.pack("!H", len(raw) + len(tail))  # declared covers the tail
    raw += tail
    _, decoded = decode_flexlm_frame(bytes(raw), "server_to_client")
    assert decoded["checkout_id"] == 49202
    assert decoded["start_ts"] == 1790861015


def test_user_row_unknown_tail_variant_stays_unattributed():
    raw = broker(0x14, [b"a", b"b", b"c", b"1.0"], "server_to_client")
    raw += b"\xff" * 12  # verified padding pattern absent
    _, decoded = decode_flexlm_frame(raw, "server_to_client")
    assert "checkout_id" not in decoded
    assert "start_ts" not in decoded


def test_request_and_login_layouts():
    request = broker(
        0x08, [b"demo1", b"node0002", b"lmgrd", b"/dev/tty", b"getpaths"],
        "client_to_server",
    )
    _, decoded = decode_flexlm_frame(request, "client_to_server")
    assert decoded["user"] == "demo1"
    assert decoded["host"] == "node0002"
    assert decoded["daemon"] == "lmgrd"
    assert decoded["tty"] == "/dev/tty"
    assert decoded["command"] == "getpaths"

    login = broker(0x02, [b"demo1", b"node0002", b"/dev/tty", b"x64_linux"], "client_to_server")
    _, decoded = decode_flexlm_frame(login, "client_to_server")
    assert decoded["user"] == "demo1"
    assert decoded["tty"] == "/dev/tty"
    assert decoded["arch"] == "x64_linux"
    assert "name" not in decoded


def test_unnamed_request_types_keep_strings_only():
    raw = broker(0x3D, [b"abcdef01"], "client_to_server")
    _, decoded = decode_flexlm_frame(raw, "client_to_server")
    assert decoded["strings"] == ["abcdef01"]
    assert "user" not in decoded


def test_rsp_single_port_promotes_vendor_port():
    port = struct.pack("!H", 45031)
    raw = broker(0x13, [b"node0", b"ZZ"], "server_to_client")
    frame = bytearray(raw)
    frame[20:22] = port  # zone before the first string
    _, decoded = decode_flexlm_frame(bytes(frame), "server_to_client")
    assert decoded["vendor_port"] == 45031
    assert "port_candidates" not in decoded


def test_other_response_types_do_not_scan_ports():
    raw = broker(0x14, [b"a" * 40, b"b" * 40], "server_to_client")
    frame = bytearray(raw)
    frame[20:22] = b"\xff\xff"  # would look like port 65535
    _, decoded = decode_flexlm_frame(bytes(frame), "server_to_client")
    assert "port_candidates" not in decoded
    assert "vendor_port" not in decoded


def test_license_lookup_carries_feature_and_param():
    raw = broker(0x47, [b"QZ", b"P=25b4760"], "client_to_server")
    _, decoded = decode_flexlm_frame(raw, "client_to_server")
    assert decoded["feature"] == "QZ"
    assert decoded["param"] == "P=25b4760"


def test_license_lookup_without_param():
    raw = broker(0x47, [b"QZ", b"P="], "client_to_server")
    _, decoded = decode_flexlm_frame(raw, "client_to_server")
    assert decoded["feature"] == "QZ"
    assert decoded["param"] == "P="


def test_license_lookup_binary_noise_keeps_strings_only():
    # 0x47 rides crypto sessions; a binary frame misread as a lookup must not
    # promote garbage as a feature name.
    raw = broker(0x47, [b"6ABE18B0", b"\x01\x02jT"], "client_to_server")
    _, decoded = decode_flexlm_frame(raw, "client_to_server")
    assert "feature" not in decoded
    assert "param" not in decoded


def test_license_line_increment_fields():
    line = (
        b'25b4760 200 500 INCREMENT QZ vendmock 1.0 31-dec-2026 500 '
        b'SIGN="0267 03FB E0BE 692D"'
    )
    raw = broker(0x46, [line], "server_to_client")
    _, decoded = decode_flexlm_frame(raw, "server_to_client")
    assert decoded["feature"] == "QZ"
    assert decoded["vendor"] == "vendmock"
    assert decoded["version"] == "1.0"
    assert decoded["expiry"] == "31-dec-2026"
    assert decoded["seats"] == 500
    assert decoded["sign"] == "0267 03FB E0BE 692D"
    assert decoded["license_line"].startswith("25b4760")


def test_license_line_nomore_terminator():
    raw = broker(0x46, [b"NOMORE"], "server_to_client")
    _, decoded = decode_flexlm_frame(raw, "server_to_client")
    assert decoded["nomore"] is True
    assert "feature" not in decoded


def test_greeting_named_fields_and_no_version_glue():
    buf = bytearray(147)
    buf[0] = 0x68
    buf[1] = 0xC6
    buf[2:4] = b"13"

    def put(off: int, value: bytes) -> None:
        buf[off:off + len(value)] = value

    put(4, b"demo1.guest")
    put(25, b"node0003")
    put(58, b"vendor00")
    put(69, b"/dev/tty")
    put(102, b"T")
    put(115, b"1234")
    put(126, b"x64_lsb")
    _, decoded = decode_flexlm_frame(bytes(buf), "client_to_server")
    assert decoded["proto"] == "eda-greeting"
    assert decoded["user"] == "demo1.guest"
    assert decoded["host"] == "node0003"
    assert decoded["daemon"] == "vendor00"
    assert decoded["tty"] == "/dev/tty"
    assert decoded["pid"] == "1234"
    assert decoded["platform"] == "x64_lsb"
    assert not decoded["strings"][0].startswith("13")
