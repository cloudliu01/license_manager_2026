"""Native-style FlexLM wire, transcribed from annotated captures.

This is a capture-derived status-surface simulation, not a claim of general
FlexNet wire compatibility. The session-crypto handshake is intentionally
omitted; encrypted key payloads are not reproduced.
"""

from __future__ import annotations

import os
import socket
import struct
import time
from collections.abc import Callable
from datetime import date

GREETING_SIZE = 147
PING_SIZE = 147
BROKER_HEADER = 12
REQUEST_TYPE = 0x08
HELLO_TYPE = 0x0E
LISTING_TYPE = 0x46
SEATS_TYPE = 0x4E
USER_TYPE = 0x14
END_TYPE = 0x13
REQUEST_PROLOGUE = b"\x01\x04"
RESPONSE_PROLOGUE = b"\x0b\x0d\x01\x04\x00"
MAX_FRAME = 0xFFFF


class ProtocolError(ValueError):
    """Malformed capture-derived native-style frame."""


def _random_fill(frame: bytearray, start: int, size: int) -> None:
    frame[start : start + size] = os.urandom(size)


def encode_greeting(user: str, host: str, daemon: str, tty: str, pid: int, platform: str) -> bytes:
    frame = bytearray(GREETING_SIZE)
    frame[0] = 0x68
    _random_fill(frame, 1, 1)
    frame[2:4] = b"13"
    payload = b"".join(
        b"%s\x00" % value.encode("utf-8")
        for value in (user, host, daemon, tty, str(pid), platform)
    )
    if 4 + len(payload) > GREETING_SIZE:
        raise ProtocolError("GREETING_TOO_LONG")
    frame[4 : 4 + len(payload)] = payload
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
) -> bytes:
    if ts is None:
        ts = 0 if message_type == HELLO_TYPE else int(time.time())
    prologue = REQUEST_PROLOGUE if client else RESPONSE_PROLOGUE
    body = b"\x00" * 8 + prologue + b"".join(
        b"%s\x00" % value.encode("utf-8") for value in strings
    )
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
    while len(chunks) < size:
        try:
            chunk = sock.recv(size - len(chunks))
        except TimeoutError:
            continue
        if not chunk:
            return None
        chunks.extend(chunk)
    return bytes(chunks)


def recv_broker_frame(sock: socket.socket) -> tuple[int, list[str], int] | None:
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
    return decode_frame(header + rest)


def send_frame(sock: socket.socket, frame: bytes) -> None:
    sock.sendall(frame)


def peek_protocol(sock: socket.socket) -> int | None:
    """Peek at the first stream byte: 0x53 for SIM1, capture signatures otherwise."""
    try:
        first = sock.recv(1, socket.MSG_PEEK)
    except TimeoutError:
        return None
    return first[0] if first else None


Responder = Callable[[str, str], tuple[list[tuple[int, list[str]]], str]]


def serve_native(
    connection: socket.socket,
    daemon: str,
    responder: Responder,
    greeting: dict[str, str | int] | None = None,
) -> None:
    """Greeting/ping/command loop for one native-style connection.

    ``responder(command, argument)`` returns ``(frames, error)``; ``frames`` is
    a list of ``(message_type, strings)`` pairs. An END frame always terminates
    each command response; its string is empty on success or contains the error.
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

            hello_daemon = daemon
            if greeting is None:
                fields = decode_greeting(first)
                if fields is None:
                    return
                hello_daemon = str(fields.get("daemon") or daemon)
            send_frame(
                connection,
                encode_frame(HELLO_TYPE, [peer_host, hello_daemon], client=False),
            )
            while True:
                frame = recv_broker_frame(connection)
                if frame is None:
                    return
                message_type, strings, _timestamp = frame
                if message_type != REQUEST_TYPE or not strings:
                    return
                command = strings[4] if len(strings) > 4 else ""
                argument = strings[5] if len(strings) > 5 else ""
                frames, error = responder(command, argument)
                for reply_type, reply_strings in frames:
                    send_frame(
                        connection,
                        encode_frame(reply_type, reply_strings, client=False),
                    )
                send_frame(
                    connection,
                    encode_frame(END_TYPE, [error] if error else [], client=False),
                )
        except (OSError, TimeoutError, ProtocolError):
            return
