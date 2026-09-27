"""Generated SIM1 vectors are synthetic and NEVER captured FlexNet packets."""

import socket
import struct

import pytest
from license_manager_simulators.lmgrd.wire import (
    ENQUIRE,
    MAX_FRAME,
    ProtocolError,
    decode_frame,
    encode_frame,
    recv_frame,
)


def test_synthetic_enquiry_hex_golden():
    frame = encode_frame(ENQUIRE, {"feature": "alpha"})
    assert frame.hex() == "53494d31010000001564000173000766656174757265730005616c706861"
    assert decode_frame(bytes.fromhex(frame.hex())) == (ENQUIRE, {"feature": "alpha"})
    # Distinctive SIM1 magic explicitly differs from screenshot's claimed A/B/C headers.
    assert frame[:4] != b"\x2f\x00\x00\x00"


def test_stream_split_and_multiple_frames_on_one_socket():
    left, right = socket.socketpair()
    with left, right:
        first = encode_frame(ENQUIRE, {"feature": "alpha"})
        second = encode_frame(ENQUIRE, {"feature": "beta"})
        left.sendall(first[:5])
        left.sendall(first[5:] + second)
        assert recv_frame(right) == (ENQUIRE, {"feature": "alpha"})
        assert recv_frame(right) == (ENQUIRE, {"feature": "beta"})


@pytest.mark.parametrize("frame", [
    b"BAD!" + encode_frame(ENQUIRE, {})[4:],
    b"SIM1\x01" + struct.pack("!I", MAX_FRAME + 1),
    encode_frame(ENQUIRE, {})[:-1],
    encode_frame(ENQUIRE, {"x": "ok"}) + b"trailing",
])
def test_invalid_wire_rejected(frame):
    with pytest.raises(ProtocolError):
        decode_frame(frame)


def test_non_utf8_string_rejected():
    frame = b"SIM1\x01" + struct.pack("!I", 7) + b"d\x00\x01s\x00\x01\xff"
    with pytest.raises(ProtocolError, match="INVALID_UTF8"):
        decode_frame(frame)
