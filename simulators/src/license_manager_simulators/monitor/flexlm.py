"""Best-effort decoders for real FlexLM/EDA license traffic.

Ported from the port-1702 analysis sniffer (lic_capture_server.py): the
LSF-style broker framing used by lmgrd/vendor daemons (0x2f magic, 12-byte
header, big-endian declared total length), the Cadence-style 147-byte greeting
(head 0x68 followed by ``13``) and the lmgrd ping/keepalive (head 0x3c/0x3e).
Decoding is heuristic: raw bytes stay authoritative in tcp_segments/frames.
"""

from __future__ import annotations

import struct
import time

DIRECTION_LABEL = {"client_to_server": "C->S", "server_to_client": "S->C"}
LSF_MAGIC = 0x2F
LSF_HEADER = 12
TYPE_NAMES = {0x02: "REQ", 0x13: "RSP"}


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


def strings_in(data: bytes) -> list[tuple[int, str]]:
    out = []
    i = 0
    while i < len(data):
        j = i
        while j < len(data) and 0x20 <= data[j] < 0x7F:
            j += 1
        if j - i >= 2 and (j == len(data) or data[j] == 0):
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


def decode_message(data: bytes, direction: str) -> dict:
    header = _header(data)
    decoded = {
        "proto": "lsf-broker",
        "dir": direction,
        "magic": header["magic"],
        "len": header["declared"],
        "ver": header["ver"],
        "type": header["type"],
        "type_name": TYPE_NAMES.get(header["type"], f"0x{header['type']:02x}"),
        "msg_ts": None
        if header["ts"] == 0
        else time.strftime("%Y-%m-%d %H:%M:%S", time.gmtime(header["ts"])),
    }
    if header["ts"] == 0:
        decoded["msg_ts_note"] = "timestamp is 0 (request format carried no timestamp to echo)"
    if direction == "C->S":
        # Request frames carry the string region from offset 22 (verified
        # against captures); earlier offsets are the binary prologue.
        names = ["user", "host", "tty", "name", "arch"]
        runs = strings_in(data[22:])
        decoded["strings"] = [value for _, value in runs]
        for index, (_, value) in enumerate(runs):
            decoded[names[index] if index < len(names) else f"string_{index}"] = value
    else:
        tail = data[20:]
        runs = strings_in(tail)
        values = []
        ip = None
        for _, value in runs:
            values.append(value)
            if ip is None and looks_ipv4(value):
                ip = value
        decoded["strings"] = values
        if ip:
            decoded["server_ip"] = ip
        candidates = []
        for zone in zones_between(tail, runs):
            candidates.extend(scan_ports(zone))
        if candidates:
            decoded["port_candidates"] = candidates
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
        "strings": harvest(data, 2),
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
