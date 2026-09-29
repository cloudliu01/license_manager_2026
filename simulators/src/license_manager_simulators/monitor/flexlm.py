"""Best-effort decoders for real FlexLM/EDA license traffic.

Ported from the port-1702 analysis sniffer (lic_capture_server.py): the
LSF-style broker framing used by lmgrd/vendor daemons (0x2f magic, 12-byte
header, big-endian declared total length), the Cadence-style 147-byte greeting
(head 0x68 followed by ``13``) and the lmgrd ping/keepalive (head 0x3c/0x3e).
Decoding is heuristic: raw bytes stay authoritative in tcp_segments/frames.
"""

from __future__ import annotations

import re
import struct
import time

DIRECTION_LABEL = {"client_to_server": "C->S", "server_to_client": "S->C"}
LSF_MAGIC = 0x2F
LSF_HEADER = 12
TYPE_NAMES = {0x02: "REQ", 0x13: "RSP"}

# Frame types with verified semantics (node0 captures, calibrated against
# `lmstat -a` output): feature query, seat summary, per-user seat row, and
# the final crypto-session handshake before encrypted payloads.
FLEXLM_QUERY = 0x3C
FLEXLM_SEATS = 0x4E
FLEXLM_USER_ROW = 0x14
FLEXLM_CRYPTO_READY = 0x61

# Named string slots per C->S request type; types without an entry keep
# their strings unnamed (their slots hold handles/binary, not identity).
C_TO_S_NAMES = {
    0x02: ["user", "host", "tty", "arch"],
    0x08: ["user", "host", "daemon", "tty", "command"],
}
# Response types whose binary zones hold a meaningful port value; scanning
# other types only yields false positives from binary noise.
PORT_TYPES = {0x13}
# Fixed-width greeting slots, stable across 134 captured node0 greetings.
GREETING_FIELDS = {
    4: "user", 25: "host", 58: "daemon", 69: "tty", 115: "pid", 126: "platform",
}
_HANDLE_RE = re.compile(r"[0-9A-F]{4}(?: [0-9A-F]{4}){3}")
_TRAILING_NUMBER_RE = re.compile(r"(\d+)\s*$")
_EPOCH_MIN = 1_500_000_000


def lsf_declared(data: bytes) -> int:
    """Total declared length (header included) of a broker frame at pos 0."""
    if len(data) < LSF_HEADER or data[0] != LSF_MAGIC:
        return 0
    declared = struct.unpack_from("!H", data, 4)[0]
    return declared if declared >= LSF_HEADER else 0


def greeting_boundary(data: bytes) -> int | None:
    """Find a structurally valid broker header after an unframed greeting/ping.

    Requires the observed protocol-version byte 0x01 to reject 0x2f bytes
    inside strings.
    """
    for offset in range(LSF_HEADER, max(len(data) - LSF_HEADER, LSF_HEADER)):
        if (
            data[offset] == LSF_MAGIC
            and data[offset + 6] == 0x01
            and struct.unpack_from("!H", data, offset + 4)[0] >= LSF_HEADER
        ):
            return offset
    return None


def _header(raw: bytes) -> dict:
    return {
        "magic": raw[0:4].hex(),
        "declared": struct.unpack(">H", raw[4:6])[0],
        "ver": raw[6],
        "type": raw[7],
        "ts": struct.unpack(">I", raw[8:12])[0],
    }


def strings_in(data: bytes, minlen: int = 2) -> list[tuple[int, str]]:
    out = []
    i = 0
    while i < len(data):
        j = i
        while j < len(data) and 0x20 <= data[j] < 0x7F:
            j += 1
        if j - i >= minlen and (j == len(data) or data[j] == 0):
            out.append((i, data[i:j].decode("ascii", "replace")))
        i = j + 1 if j > i else i + 1
    return out


def harvest(data: bytes, minlen: int = 3) -> list[str]:
    out = []
    i = 0
    while i < len(data):
        if 0x20 <= data[i] < 0x7F:
            j = i
            while j < len(data) and 0x20 <= data[j] < 0x7F:
                j += 1
            if j - i >= minlen:
                out.append(data[i:j].decode("ascii", "replace"))
            i = j
        else:
            i += 1
    return out


def looks_ipv4(value: str) -> bool:
    parts = value.split(".")
    return len(parts) == 4 and all(
        part.isdigit() and 0 <= int(part) <= 255 for part in parts
    )


def zones_between(data: bytes, runs: list[tuple[int, str]]) -> list[bytes]:
    zones = []
    pos = 0
    for offset, value in runs:
        if offset > pos:
            zones.append(data[pos:offset])
        pos = offset + len(value) + 1
    if pos < len(data):
        zones.append(data[pos:])
    return zones


def scan_ports(zone: bytes) -> list[int]:
    candidates = []
    i = 0
    while i + 1 < len(zone):
        value = struct.unpack(">H", zone[i : i + 2])[0]
        if 1024 <= value <= 65535:
            candidates.append(value)
            i += 2
        else:
            i += 1
    return candidates


def _seat_fields(values: list[str]) -> dict:
    """0x4e seat summary, calibrated 3-number layout [in_use, issued, epoch]
    (node0, cross-checked against `lmstat -a`). Each number may carry binary
    noise inside its token (e.g. "Nz100"); tokens without digits are dropped
    before positional attribution. Degenerate variants keep their numbers
    unattributed (no fabrication)."""
    numbers = []
    for value in values:
        match = _TRAILING_NUMBER_RE.search(value)
        if match:
            numbers.append(int(match.group(1)))
    out: dict = {}
    if len(numbers) >= 3 and numbers[-1] >= _EPOCH_MIN:
        out["in_use"] = numbers[0]
        out["issued"] = numbers[1]
        out["report_ts"] = numbers[-1]
    else:
        counts = [n for n in numbers if n < _EPOCH_MIN]
        if counts:
            out["counts"] = counts
        epochs = [n for n in numbers if n >= _EPOCH_MIN]
        if epochs:
            out["report_ts"] = epochs[-1]
    return out


def decode_message(data: bytes, direction: str) -> dict:
    header = _header(data)
    frame_type = header["type"]
    decoded = {
        "proto": "lsf-broker",
        "dir": direction,
        "magic": header["magic"],
        "len": header["declared"],
        "ver": header["ver"],
        "type": frame_type,
        "type_name": TYPE_NAMES.get(frame_type, f"0x{frame_type:02x}"),
        "msg_ts": None
        if header["ts"] == 0
        else time.strftime("%Y-%m-%d %H:%M:%S", time.gmtime(header["ts"])),
    }
    if header["ts"] == 0:
        decoded["msg_ts_note"] = "timestamp is 0 (request format carried no timestamp to echo)"
    if direction == "C->S":
        # Request frames carry NUL-terminated strings after a fixed prologue.
        # 0x3c feature queries start at offset 20 (name + optional key
        # handle); other request types start at 22 (verified against captures).
        start = 20 if frame_type == FLEXLM_QUERY else 22
        runs = strings_in(data[start:])
        decoded["strings"] = [value for _, value in runs]
        if frame_type == FLEXLM_QUERY:
            if decoded["strings"]:
                decoded["feature"] = decoded["strings"][0]
            if len(decoded["strings"]) > 1:
                candidate = decoded["strings"][1].strip()
                if _HANDLE_RE.fullmatch(candidate):
                    decoded["feature_handle"] = candidate
        else:
            names = C_TO_S_NAMES.get(frame_type, [])
            for index, (_, value) in enumerate(runs):
                if index < len(names):
                    decoded[names[index]] = value
    else:
        tail = data[20:]
        # Seat summaries and user rows carry single-character fields (e.g.
        # in_use 0..9); harvest them with minlen=1.
        minlen = 1 if frame_type in (FLEXLM_USER_ROW, FLEXLM_SEATS) else 2
        runs = strings_in(tail, minlen)
        values = [value for _, value in runs]
        decoded["strings"] = values
        ip = next((value for value in values if looks_ipv4(value)), None)
        if ip:
            decoded["server_ip"] = ip
        if frame_type == FLEXLM_USER_ROW:
            for name, value in zip(("user", "host", "tty", "version"), values):
                decoded[name] = value
        elif frame_type == FLEXLM_SEATS:
            decoded.update(_seat_fields(values))
        if frame_type in PORT_TYPES:
            candidates = []
            for zone in zones_between(tail, runs):
                candidates.extend(scan_ports(zone))
            if len(candidates) == 1:
                decoded["vendor_port"] = candidates[0]
            elif candidates:
                decoded["port_candidates"] = candidates[:8]
    return decoded


def decode_greeting(data: bytes, direction: str) -> dict:
    decoded = {
        "proto": "eda-greeting" if data[0] == 0x68 else "lmgrd-ping",
        "dir": direction,
        "len": len(data),
        "head_hex": data[:4].hex(),
        "note": (
            "no length field in this format; fields identified by content "
            "heuristics, strings harvested from the fixed-size message"
        ),
        "strings": harvest(data[4:], 2),
    }
    if decoded["proto"] == "eda-greeting":
        fields = []
        pos = 4
        while pos < len(data):
            if data[pos] == 0:
                pos += 1
                continue
            end = pos
            while end < len(data) and 0x20 <= data[end] < 0x7F:
                end += 1
            if end > pos:
                fields.append({"off": pos, "value": data[pos:end].decode("ascii", "replace")})
                pos = end
            else:
                pos += 1
        decoded["fields"] = fields
        for field in fields:
            name = GREETING_FIELDS.get(field["off"])
            if name:
                decoded[name] = field["value"]
    return decoded


def decode_flexlm_frame(raw: bytes, direction: str) -> tuple[int | None, dict] | None:
    """Decode one reassembled application frame; None when unrecognized."""
    label = DIRECTION_LABEL.get(direction, direction)
    declared = lsf_declared(raw)
    if declared and len(raw) >= declared:
        message = decode_message(raw[:declared], label)
        return message["type"], message
    if raw[:1] == b"\x68" and len(raw) >= 4 and raw[2:4] == b"13":
        return None, decode_greeting(raw, label)
    if raw[:1] in (b"\x3c", b"\x3e") and len(raw) >= 4:
        return None, decode_greeting(raw, label)
    return None
