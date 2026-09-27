"""SIM1: synthetic, test-only binary framing. NOT the FlexNet wire protocol.

Frame: 'SIM1' | opcode:u8 | payload_length:u32be | typed binary payload.
Payload tags: n=null, t/f=bool, i=signed i64, s=utf8 (u16be length),
l=list (u16be items), d=dict (u16be pairs of string keys + values).
This deliberately has a distinctive magic to prevent mistaking generated hex for
captured A/B/C messages. MAX_FRAME also limits allocations on untrusted sockets.
"""

from __future__ import annotations

import socket
import struct
from typing import Any

MAGIC = b"SIM1"
MAX_FRAME = 1 << 20
MAX_STRING = 4096
MAX_ITEMS = 4096
MAX_DEPTH = 12
ENQUIRE, STATUS, CHECKOUT, CHECKIN, HEARTBEAT, CHECKOUTS, QUEUE = range(1, 8)
ERROR = 255


class ProtocolError(ValueError):
    pass


def _encode(value: Any, depth: int = 0) -> bytes:
    if depth > MAX_DEPTH:
        raise ProtocolError("NESTING_LIMIT")
    if value is None:
        return b"n"
    if isinstance(value, bool):
        return b"t" if value else b"f"
    if isinstance(value, int):
        try:
            return b"i" + struct.pack("!q", value)
        except struct.error as exc:
            raise ProtocolError("INTEGER_RANGE") from exc
    if isinstance(value, str):
        encoded = value.encode("utf-8")
        if len(encoded) > MAX_STRING:
            raise ProtocolError("STRING_TOO_LONG")
        return b"s" + struct.pack("!H", len(encoded)) + encoded
    if isinstance(value, (list, tuple)):
        if len(value) > MAX_ITEMS:
            raise ProtocolError("ITEM_LIMIT")
        return b"l" + struct.pack("!H", len(value)) + b"".join(_encode(x, depth + 1) for x in value)
    if isinstance(value, dict):
        if len(value) > MAX_ITEMS or not all(isinstance(key, str) for key in value):
            raise ProtocolError("INVALID_DICTIONARY")
        return b"d" + struct.pack("!H", len(value)) + b"".join(
            _encode(key, depth + 1) + _encode(item, depth + 1) for key, item in value.items()
        )
    raise ProtocolError("UNSUPPORTED_VALUE")


def encode_frame(opcode: int, payload: dict[str, Any]) -> bytes:
    if not 0 <= opcode <= 255:
        raise ProtocolError("INVALID_OPCODE")
    body = _encode(payload)
    if len(body) > MAX_FRAME:
        raise ProtocolError("FRAME_TOO_LARGE")
    return MAGIC + bytes([opcode]) + struct.pack("!I", len(body)) + body


class _Reader:
    def __init__(self, data: bytes) -> None:
        self.data = data
        self.pos = 0

    def take(self, size: int) -> bytes:
        if size > len(self.data) - self.pos:
            raise ProtocolError("TRUNCATED_VALUE")
        result = self.data[self.pos:self.pos + size]
        self.pos += size
        return result

    def value(self, depth: int = 0) -> Any:
        if depth > MAX_DEPTH:
            raise ProtocolError("NESTING_LIMIT")
        tag = self.take(1)
        if tag == b"n":
            return None
        if tag == b"t":
            return True
        if tag == b"f":
            return False
        if tag == b"i":
            return struct.unpack("!q", self.take(8))[0]
        if tag == b"s":
            size = struct.unpack("!H", self.take(2))[0]
            if size > MAX_STRING:
                raise ProtocolError("STRING_TOO_LONG")
            try:
                return self.take(size).decode("utf-8")
            except UnicodeDecodeError as exc:
                raise ProtocolError("INVALID_UTF8") from exc
        if tag in (b"l", b"d"):
            count = struct.unpack("!H", self.take(2))[0]
            if count > MAX_ITEMS:
                raise ProtocolError("ITEM_LIMIT")
            if tag == b"l":
                return [self.value(depth + 1) for _ in range(count)]
            result = {}
            for _ in range(count):
                key = self.value(depth + 1)
                if not isinstance(key, str) or key in result:
                    raise ProtocolError("INVALID_DICTIONARY")
                result[key] = self.value(depth + 1)
            return result
        raise ProtocolError("INVALID_TAG")


def decode_frame(frame: bytes) -> tuple[int, dict[str, Any]]:
    if len(frame) < 9 or frame[:4] != MAGIC:
        raise ProtocolError("INVALID_HEADER")
    length = struct.unpack("!I", frame[5:9])[0]
    if length > MAX_FRAME or length != len(frame) - 9:
        raise ProtocolError("INVALID_LENGTH")
    reader = _Reader(frame[9:])
    payload = reader.value()
    if not isinstance(payload, dict) or reader.pos != length:
        raise ProtocolError("INVALID_PAYLOAD")
    return frame[4], payload


def _read_exact(sock: socket.socket, size: int) -> bytes | None:
    chunks = bytearray()
    while len(chunks) < size:
        chunk = sock.recv(size - len(chunks))
        if not chunk:
            if not chunks:
                return None
            raise ProtocolError("TRUNCATED_FRAME")
        chunks.extend(chunk)
    return bytes(chunks)


def recv_frame(sock: socket.socket) -> tuple[int, dict[str, Any]] | None:
    header = _read_exact(sock, 9)
    if header is None:
        return None
    if header[:4] != MAGIC:
        raise ProtocolError("INVALID_HEADER")
    size = struct.unpack("!I", header[5:9])[0]
    if size > MAX_FRAME:
        raise ProtocolError("FRAME_TOO_LARGE")
    body = _read_exact(sock, size)
    if body is None:
        raise ProtocolError("TRUNCATED_FRAME")
    return decode_frame(header + body)


def request(host: str, port: int, opcode: int, payload: dict[str, Any]) -> dict[str, Any]:
    with socket.create_connection((host, port), timeout=3) as sock:
        sock.settimeout(3)
        sock.sendall(encode_frame(opcode, payload))
        result = recv_frame(sock)
    if result is None:
        raise ProtocolError("NO_RESPONSE")
    op, data = result
    if op == ERROR:
        raise ProtocolError(str(data.get("error", "UNKNOWN_ERROR")))
    if op != (opcode | 0x80):
        raise ProtocolError("WRONG_RESPONSE")
    return data
