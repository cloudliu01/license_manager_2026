"""Native-style FlexLM wire, transcribed from annotated node0 captures.

The captured server exchanges three frame families (see monitor/flexlm.py):
- EDA greeting: fixed 147 bytes, head ``68 ?? "13"``, NUL-separated fields
  user, host, daemon, tty, pid, platform; the server answers with a broker
  HELLO (0x0e) echoing the client host and daemon name.
- lmgrd ping/keepalive: fixed 147 bytes, head ``3c ?? 30 00`` (client) and
  ``3e ?? 30 00`` (server), ASCII "0" at offset 12.
- Broker frames: ``2f`` + 3 session bytes, u16be declared total length
  (12-byte header included), version byte (0 for SEATS, 1 otherwise),
  type byte, u32be Unix timestamp, then the payload: 8 zero bytes, a short
  binary prologue (0104 on requests, 0b0d0104 00 on responses) and
  NUL-terminated strings. Client strings start at offset 22, server strings
  at offset 20-25; the trailing region is what the monitor decodes.

Message types used by the status surface (readable strings on the wire):
    0x08 REQUEST  client -> server [user, host, daemon, tty, command]
    0x0e HELLO    server -> client [client_host, daemon]
    0x46 LISTING  server -> client [multi-line text or path]
    0x4e SEATS    server -> client [str(total), str(unix_ts)]
    0x14 USER     server -> client [user, host, tty, version, status]
    0x13 END      server -> client terminator

This is a capture-derived status-surface simulation, not a claim of general
FlexNet wire compatibility. The session-crypto handshake is reproduced in
SHAPE only (observed frame sizes, random bodies): real key material is not,
and none of the monitor's decode logic depends on it.
"""

from __future__ import annotations

import os
import re
import socket
import struct
import time
import uuid
import zlib
from collections.abc import Callable
from datetime import date, datetime

GREETING_SIZE = 147
PING_SIZE = 147
BROKER_HEADER = 12
REQUEST_TYPE = 0x08
QUERY_TYPE = 0x3C
HELLO_TYPE = 0x0E
LISTING_TYPE = 0x46
SEATS_TYPE = 0x4E
USER_TYPE = 0x14
END_TYPE = 0x13
# Encrypted-session checkout exchange (shape-only; verified sizes from
# qa-ls captures). 0x47 S->C is the crypto response, 0x55 C->S the daemon
# handshake ("vendmock"), 0x56 S->C the grant, 0x3d C->S the checkout
# request (client epoch as 8 hex chars), 0x61 S->C the checkout return.
# 0x49 C->S is the checkin (observed opcode in qa-ls daemon captures).
PARAMS_TYPE = 0x41
CRYPTO_RESPONSE_TYPE = 0x47
DAEMON_HANDSHAKE_TYPE = 0x55
GRANT_TYPE = 0x56
CHECKOUT_REQ_TYPE = 0x3D
CHECKOUT_RETURN_TYPE = 0x61
CHECKIN_TYPE = 0x49
DAEMON_NAME = "vendmock"
CRYPTO_FRAME_SIZE = 168
GRANT_FRAME_SIZE = 25
CHECKOUT_REQ_FRAME_SIZE = 66
REQUEST_PROLOGUE = b"\x01\x04"
RESPONSE_PROLOGUE = b"\x0b\x0d\x01\x04\x00"
MAX_FRAME = 0xFFFF
_EPOCH_MIN = 1_500_000_000
_CHECKOUT_TS_RE = re.compile(r"[0-9a-f]{8}")

# Transaction result trailer: real 0x61 bodies are encrypted payloads the
# monitor cannot read; the simulator keeps that property by carrying the
# machine-readable outcome in a mask-XORed trailer behind the random body.
# Layout: 1B mask + XOR(mask, "!BBIHHH" struct + uuid36 + feature utf-8),
# where the struct is (status, reason, checkout_num, total, in_use, queued),
# followed by a plain !H suffix holding the trailer length (mask + body) so
# variable-length feature names stay locatable from the frame end.
RESULT_STRUCT = "!BBIHHH"
_RESULT_BODY_SIZE = 12
UUID_LEN = 36
_RESULT_FIXED_SIZE = 1 + _RESULT_BODY_SIZE + UUID_LEN
RESULT_SUFFIX_SIZE = 2
RESULT_STATUSES = {"GRANTED": 0, "QUEUED": 1, "REJECTED": 2, "DENIED": 3, "RETURNED": 4}
RESULT_STATUS_NAMES = {code: name for name, code in RESULT_STATUSES.items()}
RESULT_REASONS = {
    "UNKNOWN_FEATURE": 1,
    "FEATURE_EXPIRED": 2,
    "QUEUE_FULL": 3,
    "UNKNOWN_CHECKOUT": 4,
    "LICENSE_LIMIT_REACHED": 5,
    "ALREADY_RETURNED": 6,
}
RESULT_REASON_NAMES = {code: name for name, code in RESULT_REASONS.items()}
_FEATURE_SLOT_RE = re.compile(r"[A-Za-z][A-Za-z0-9_.\-]*")
_UUID_LEN = 36


class ProtocolError(ValueError):
    """Malformed capture-derived native-style frame."""


def _random_fill(frame: bytearray, start: int, size: int) -> None:
    frame[start : start + size] = os.urandom(size)


def encode_greeting(user: str, host: str, daemon: str, tty: str, pid: int, platform: str) -> bytes:
    """147B greeting at the real fixed-slot layout (user@4, host@25,
    daemon@58, tty@69, pid@115, platform@126 – verified against qa-ls
    captures and the monitor's GREETING_FIELDS)."""
    frame = bytearray(GREETING_SIZE)
    frame[0] = 0x68
    _random_fill(frame, 1, 1)
    frame[2:4] = b"13"
    for offset, value in (
        (4, user), (25, host), (58, daemon), (69, tty),
        (115, str(pid)), (126, platform),
    ):
        encoded = value.encode("utf-8")
        if offset + len(encoded) > GREETING_SIZE:
            raise ProtocolError("GREETING_TOO_LONG")
        frame[offset:offset + len(encoded)] = encoded
    return bytes(frame)


def decode_greeting(data: bytes) -> dict[str, str | int] | None:
    if len(data) < 100 or data[0] != 0x68 or data[2:4] != b"13":
        return None
    fields = [part.decode("utf-8", "replace") for part in data[4:].split(b"\x00") if part]
    return {
        "user": fields[0] if fields else "",
        "host": fields[1] if len(fields) > 1 else "",
        "daemon": fields[2] if len(fields) > 2 else "",
        "tty": fields[3] if len(fields) > 3 else "",
        "pid": int(fields[4]) if len(fields) > 4 and fields[4].isdigit() else 0,
        "platform": fields[5] if len(fields) > 5 else "",
    }


def encode_ping(client: bool) -> bytes:
    frame = bytearray(PING_SIZE)
    frame[0] = 0x3C if client else 0x3E
    _random_fill(frame, 1, 1)
    frame[2] = 0x30
    frame[12:14] = b"0\x00"
    return bytes(frame)


def looks_like_ping(data: bytes) -> bool:
    return len(data) >= 14 and data[0] in (0x3C, 0x3E) and data[2] == 0x30 and data[3] == 0x00


def native_expires(value: str | date | None) -> str:
    """Format the status-surface expiry as ``01-nov-2026`` or ``permanent``."""
    if value is None:
        return "permanent"
    if isinstance(value, date):
        return f"{value.day:02d}-{value:%b-%Y}".lower()
    try:
        return native_expires(date.fromisoformat(str(value)))
    except ValueError:
        return str(value)


def encode_frame(
    message_type: int,
    strings: list[str],
    *,
    client: bool,
    ts: int | None = None,
    tail: bytes = b"",
) -> bytes:
    if ts is None:
        ts = 0 if message_type == HELLO_TYPE else int(time.time())
    prologue = REQUEST_PROLOGUE if client else RESPONSE_PROLOGUE
    body = b"\x00" * 8 + prologue + b"".join(
        b"%s\x00" % value.encode("utf-8") for value in strings
    ) + tail
    declared = BROKER_HEADER + len(body)
    if declared > MAX_FRAME:
        raise ProtocolError("FRAME_TOO_LARGE")
    version = 0 if message_type == SEATS_TYPE else 1
    return (
        struct.pack("!B", 0x2F)
        + os.urandom(3)
        + struct.pack("!HBBI", declared, version, message_type, ts)
        + body
    )


def seat_tail(start_epoch: int, checkout_num: int) -> bytes:
    """Verified 0x14 row tail (qa-ls, cross-checked against `lmstat -f`):
    4B pad, 4B flag, 4B start epoch (BE), 4B zero pad, 4B checkout id (BE).
    The monitor promotes both numbers from exactly this pattern."""
    return (
        b"\x00\x00\x00\x00" + b"\x01\x00\x00\x00"
        + struct.pack("!I", start_epoch & 0xFFFFFFFF)
        + b"\x00\x00\x00\x00"
        + struct.pack("!I", checkout_num & 0xFFFFFFFF)
    )


def checkout_num(checkout_id: str) -> int:
    """Stable u32 for the 0x14 tail: real servers run a u32 counter while
    simulator checkout ids are uuid4 strings."""
    try:
        return uuid.UUID(checkout_id).int & 0xFFFFFFFF
    except ValueError:
        return zlib.crc32(checkout_id.encode()) & 0xFFFFFFFF


def iso_epoch(value: str | None) -> int | None:
    """Epoch seconds of an ISO timestamp, None when absent/malformed."""
    if not value:
        return None
    try:
        return int(datetime.fromisoformat(value).timestamp())
    except ValueError:
        return None


def encode_crypto(frame_type: int) -> bytes:
    """Shape-only server crypto frame (0x47/0x56/0x61): observed total size,
    random body. The monitor reads these as structural markers only."""
    size = GRANT_FRAME_SIZE if frame_type == GRANT_TYPE else CRYPTO_FRAME_SIZE
    frame = bytearray(encode_frame(frame_type, [], client=False))
    frame.extend(os.urandom(size - len(frame)))
    struct.pack_into("!H", frame, 4, size)
    return bytes(frame)


def _crypto_strings(count: int = 3) -> list[str]:
    """Short random string codes like the real 0x61's ["DC", "OQ", "MU"]."""
    alphabet = "ABCDEFGHIJKLMNOPQRSTUVWXYZ"
    return ["".join(alphabet[byte % 26] for byte in os.urandom(2))
            for _ in range(count)]


def encode_checkout_request(ts: int) -> bytes:
    """C->S 0x3d checkout request shape: the client epoch as 8 hex chars in
    the first string slot (the monitor promotes it as checkout_ts), random
    bytes behind it, observed total size 66B."""
    frame = bytearray(encode_frame(CHECKOUT_REQ_TYPE, [f"{ts:08x}"], client=True))
    frame.extend(os.urandom(CHECKOUT_REQ_FRAME_SIZE - len(frame)))
    struct.pack_into("!H", frame, 4, CHECKOUT_REQ_FRAME_SIZE)
    return bytes(frame)


def checkout_ts_from(strings: list[str]) -> int | None:
    """Client epoch from a 0x3d request's first string slot, range-guarded."""
    if not strings or not _CHECKOUT_TS_RE.fullmatch(strings[0]):
        return None
    ts = int(strings[0], 16)
    return ts if _EPOCH_MIN <= ts <= time.time() + 86400 else None


def xor_hex(value: str, mask: int = 0x5A) -> str:
    """Printable-hex one-byte XOR obfuscation for wire slots that real
    traffic keeps inside its encrypted payload (e.g. the 0x41 feature)."""
    return bytes(byte ^ mask for byte in value.encode("utf-8")).hex()


def feature_from_slot(value: str) -> str:
    """Invert :func:`xor_hex`; plaintext falls through for legacy peers."""
    try:
        decoded = bytes(
            byte ^ 0x5A for byte in bytes.fromhex(value)
        ).decode("utf-8")
    except ValueError:
        return value
    if _FEATURE_SLOT_RE.fullmatch(decoded):
        return decoded
    return value


def encode_result(
    status: str,
    reason: str | None = None,
    checkout_id: str | None = None,
    feature: str | None = None,
    total: int = 0,
    in_use: int = 0,
    queued: int = 0,
) -> bytes:
    """Mask-XORed transaction outcome trailer with a plain !H length suffix
    (see the module comment on the trailer layout)."""
    status_code = RESULT_STATUSES.get(status, RESULT_STATUSES["REJECTED"])
    reason_code = RESULT_REASONS.get(reason or "", 0)
    if checkout_id:
        uuid_field = checkout_id.encode("ascii").ljust(UUID_LEN, b"\x00")
    else:
        uuid_field = b"\x00" * UUID_LEN
    feature_field = (feature or "").encode("utf-8")
    body = struct.pack(
        RESULT_STRUCT, status_code, reason_code,
        checkout_num(checkout_id) if checkout_id else 0,
        max(total, 0), max(in_use, 0), max(queued, 0),
    ) + uuid_field + feature_field
    assert len(body) == _RESULT_BODY_SIZE + UUID_LEN + len(feature_field)
    mask = os.urandom(1)[0] or 0x5A
    payload = bytes([mask]) + bytes(byte ^ mask for byte in body)
    return payload + struct.pack("!H", len(payload))


def decode_result(raw: bytes) -> dict | None:
    """Parse an :func:`encode_result` trailer from the frame tail; None when
    the suffix does not locate a structurally valid trailer."""
    if len(raw) < RESULT_SUFFIX_SIZE + _RESULT_FIXED_SIZE:
        return None
    n = int.from_bytes(raw[-RESULT_SUFFIX_SIZE:], "big")
    if not _RESULT_FIXED_SIZE <= n <= _RESULT_FIXED_SIZE + 255:
        return None
    if len(raw) < n + RESULT_SUFFIX_SIZE:
        return None
    trailer = raw[-(n + RESULT_SUFFIX_SIZE):-RESULT_SUFFIX_SIZE]
    mask = trailer[0]
    body = bytes(byte ^ mask for byte in trailer[1:])
    status_code, reason_code, checkout_num_v, total, in_use, queued = struct.unpack_from(
        RESULT_STRUCT, body)
    uuid_field = body[_RESULT_BODY_SIZE:_RESULT_BODY_SIZE + UUID_LEN]
    checkout_id = (
        uuid_field.decode("ascii").rstrip("\x00") if uuid_field.strip(b"\x00") else None
    )
    feature = body[_RESULT_BODY_SIZE + UUID_LEN:].decode("utf-8", "replace") or None
    return {
        "status": RESULT_STATUS_NAMES.get(status_code, "REJECTED"),
        "reason": RESULT_REASON_NAMES.get(reason_code),
        "checkout_num": checkout_num_v,
        "checkout_id": checkout_id,
        "feature": feature,
        "total": total,
        "in_use": in_use,
        "queued": queued,
    }


def encode_crypto_result(
    frame_type: int, strings: list[str], result: bytes,
) -> bytes:
    """Crypto-shaped reply (0x61) carrying a transaction result trailer:
    observed 168B total, random body, trailer in the final bytes."""
    frame = bytearray(encode_frame(frame_type, strings, client=False))
    pad = CRYPTO_FRAME_SIZE - len(frame) - len(result)
    if pad < 0:
        raise ProtocolError("RESULT_TOO_LARGE")
    frame.extend(os.urandom(pad))
    frame.extend(result)
    struct.pack_into("!H", frame, 4, CRYPTO_FRAME_SIZE)
    return bytes(frame)


def encode_end_result(error: str | None, result: bytes) -> bytes:
    """END-type (0x13) reply carrying a transaction result trailer."""
    return encode_frame(END_TYPE, [error] if error else [], client=False, tail=result)


def _text_byte(byte: int) -> bool:
    # Printable ASCII plus newlines: listing payloads are multi-line text.
    return byte == 0x0A or 0x20 <= byte < 0x7F


def decode_frame(data: bytes) -> tuple[int, list[str], int]:
    if len(data) < BROKER_HEADER or data[0] != 0x2F:
        raise ProtocolError("INVALID_HEADER")
    declared, _version, message_type, ts = struct.unpack_from("!HBBI", data, 4)
    if declared < BROKER_HEADER or declared > len(data):
        raise ProtocolError("INVALID_LENGTH")
    strings: list[str] = []
    for part in data[BROKER_HEADER:declared].split(b"\x00"):
        # The binary prologue sticks to the first NUL-separated field; observed
        # captures show the same, so strip any leading non-text bytes.
        while part and not _text_byte(part[0]):
            part = part[1:]
        if part and all(_text_byte(byte) for byte in part):
            strings.append(part.decode("ascii"))
    return message_type, strings, ts


def _read_exact(sock: socket.socket, size: int) -> bytes | None:
    chunks = bytearray()
    stalls = 0
    while len(chunks) < size:
        try:
            chunk = sock.recv(size - len(chunks))
        except TimeoutError:
            stalls += 1
            if stalls > 30:  # ~30 socket timeouts with a silent peer: dead
                raise ProtocolError("READ_STALLED")
            continue
        stalls = 0
        if not chunk:
            return None
        chunks.extend(chunk)
    return bytes(chunks)


def recv_broker_frame(sock: socket.socket) -> tuple[int, list[str], int] | None:
    frame = _recv_broker(sock)
    return None if frame is None else frame[:3]


def recv_broker_frame_full(sock: socket.socket) -> tuple[int, list[str], int, bytes] | None:
    """Like :func:`recv_broker_frame` but also returns the raw frame bytes
    (clients slice fixed-width trailers off the frame tail)."""
    return _recv_broker(sock)


def _recv_broker(sock: socket.socket) -> tuple[int, list[str], int, bytes] | None:
    header = _read_exact(sock, BROKER_HEADER)
    if header is None:
        return None
    if header[0] != 0x2F:
        raise ProtocolError("INVALID_HEADER")
    declared = struct.unpack_from("!H", header, 4)[0]
    if declared < BROKER_HEADER or declared > MAX_FRAME:
        raise ProtocolError("INVALID_LENGTH")
    rest = _read_exact(sock, declared - BROKER_HEADER)
    if rest is None:
        raise ProtocolError("TRUNCATED_FRAME")
    message_type, strings, ts = decode_frame(header + rest)
    return message_type, strings, ts, header + rest


def send_frame(sock: socket.socket, frame: bytes) -> None:
    sock.sendall(frame)


def peek_protocol(sock: socket.socket) -> int | None:
    """Peek at the first stream byte: 0x53 for SIM1, capture signatures otherwise."""
    try:
        first = sock.recv(1, socket.MSG_PEEK)
    except TimeoutError:
        return None
    return first[0] if first else None


ResponderFrame = tuple[int, list[str]] | tuple[int, list[str], bytes]
Responder = Callable[[str, str], tuple[list[ResponderFrame], str]]
CheckoutHandler = Callable[[str, dict[str, str | int], int], dict | None]
CheckinHandler = Callable[[str], dict | None]


def serve_native(
    connection: socket.socket,
    daemon: str,
    responder: Responder,
    greeting: dict[str, str | int] | None = None,
    checkout_handler: CheckoutHandler | None = None,
    checkin_handler: CheckinHandler | None = None,
) -> None:
    """Greeting/ping/command loop for one native-style connection.

    ``responder(command, argument)`` returns ``(frames, error)``; ``frames``
    is a list of ``(message_type, strings)`` pairs, optionally with a third
    raw ``tail`` element appended to the frame body (0x14 seat rows carry
    the verified binary tail; the manager's 0x13 route reply carries the
    vendor port). An END frame always terminates each command response: its
    string is empty on success or contains the error.

    Per-type request shapes (verified against qa-ls captures): ``0x08`` carries
    ``[user, host, daemon, tty, command, argument?]``; ``0x3c`` is a feature
    query ``[feature]`` dispatched as the ``usage`` command. Seat summaries
    follow the calibrated ``[in_use, issued, epoch]`` layout.

    With ``checkout_handler`` the connection also speaks the encrypted-session
    checkout exchange: ``0x41`` params (the feature rides xor-obfuscated in
    the first string slot; real traffic keeps it inside the encrypted
    payload) -> ``0x47`` crypto response, ``0x55`` daemon handshake -> ``0x56``
    grant, ``0x3d`` checkout request -> ``0x61`` checkout return. The handler
    records the checkout and returns the outcome dict, which rides the
    mask-XORed result trailer real traffic keeps encrypted (the monitor reads
    only the random-looking body). ``checkin_handler`` mirrors this for
    ``0x49`` checkin requests (checkout id in the first string slot); its
    0x13 reply deliberately avoids a second 0x61, which the monitor counts
    as one checkout attempt per session.
    ``checkout_handler(feature, greeting, client_ts)`` records the checkout;
    the handler-supplied timestamp becomes the seat start epoch (verified
    real-server behavior), which is what ties the monitor's checkout-timestamp
    join together.
    """
    with connection:
        connection.settimeout(10)
        try:
            try:
                peer = connection.getpeername()[0]
            except (OSError, IndexError, TypeError):
                peer = ""
            peer_host = socket.getfqdn(peer) if peer else socket.gethostname()
            first = _read_exact(connection, GREETING_SIZE)
            if first is None:
                return
            if looks_like_ping(first):
                send_frame(connection, encode_ping(client=False))
                return

            identity = greeting
            hello_daemon = daemon
            if greeting is None:
                fields = decode_greeting(first)
                if fields is None:
                    return
                identity = fields
                hello_daemon = str(fields.get("daemon") or daemon)
            send_frame(
                connection,
                encode_frame(HELLO_TYPE, [peer_host, hello_daemon], client=False),
            )
            params_feature: str | None = None
            while True:
                frame = recv_broker_frame(connection)
                if frame is None:
                    return
                message_type, strings, _timestamp = frame
                if os.environ.get("LM_WIRE_DEBUG"):
                    print(f"[srv] {daemon}: type=0x{message_type:02x} strings={strings}",
                          flush=True)
                if message_type == QUERY_TYPE and strings:
                    command, argument = "usage", strings[0]
                elif message_type == REQUEST_TYPE and strings:
                    command = strings[4] if len(strings) > 4 else ""
                    argument = strings[5] if len(strings) > 5 else ""
                elif message_type == PARAMS_TYPE and checkout_handler is not None:
                    params_feature = feature_from_slot(strings[0]) if strings else None
                    send_frame(connection, encode_crypto(CRYPTO_RESPONSE_TYPE))
                    continue
                elif message_type == DAEMON_HANDSHAKE_TYPE and checkout_handler is not None:
                    send_frame(connection, encode_crypto(GRANT_TYPE))
                    continue
                elif (
                    message_type == CHECKOUT_REQ_TYPE
                    and checkout_handler is not None
                ):
                    ts = checkout_ts_from(strings)
                    result = None
                    if params_feature and ts is not None and identity is not None:
                        result = checkout_handler(params_feature, identity, ts)
                    if result is None:
                        send_frame(connection, encode_crypto(CHECKOUT_RETURN_TYPE))
                    else:
                        send_frame(connection, encode_crypto_result(
                            CHECKOUT_RETURN_TYPE, _crypto_strings(), encode_result(**result)))
                    params_feature = None
                    continue
                elif message_type == CHECKIN_TYPE and checkin_handler is not None:
                    result = checkin_handler(strings[0]) if strings else None
                    trailer = encode_result(**result) if result else encode_result(
                        "REJECTED", "UNKNOWN_CHECKOUT", None)
                    send_frame(connection, encode_end_result(None, trailer))
                    continue
                else:
                    return
                frames, error = responder(command, argument)
                for reply in frames:
                    tail = reply[2] if len(reply) > 2 else b""
                    out = encode_frame(reply[0], reply[1], client=False, tail=tail)
                    if os.environ.get("LM_WIRE_DEBUG"):
                        print(f"[srv-out] {daemon}: type=0x{reply[0]:02x} len={len(out)}",
                              flush=True)
                    send_frame(connection, out)
                end_frame = encode_frame(END_TYPE, [error] if error else [], client=False)
                if os.environ.get("LM_WIRE_DEBUG"):
                    print(f"[srv-out] {daemon}: END len={len(end_frame)} error={error!r}",
                          flush=True)
                send_frame(connection, end_frame)
        except (OSError, TimeoutError, ProtocolError):
            return
