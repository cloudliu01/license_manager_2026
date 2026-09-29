"""Passive IPv4/TCP SIM1 sniffer: raw segments plus reassembled decoded frames.

Linux AF_PACKET requires CAP_NET_RAW. No simulator instrumentation or proxy is used.
The program attaches to *OS* PID/socket ownership and reads loopback packets.
"""

from __future__ import annotations

import json
import socket
import sqlite3
import struct
import time
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path

from license_manager_simulators.lmgrd.wire import (
    MAGIC,
    MAX_FRAME,
    ProtocolError,
    decode_frame,
)
from license_manager_simulators.monitor.flexlm import (
    FLEXLM_CRYPTO_READY,
    FLEXLM_QUERY,
    FLEXLM_SEATS,
    FLEXLM_USER_ROW,
    decode_flexlm_frame,
    greeting_boundary,
    lsf_declared,
)
from license_manager_simulators.monitor.topology import Listener, discover

PACKET_HOST = 0
PACKET_OUTGOING = 4


def _now() -> str:
    return datetime.now(UTC).isoformat()


@dataclass(frozen=True)
class Segment:
    src_ip: str
    src_port: int
    dst_ip: str
    dst_port: int
    seq: int
    syn: bool
    fin: bool
    rst: bool
    payload: bytes


def parse_ipv4_tcp(packet: bytes) -> Segment | None:
    """Parse Ethernet/loopback Ethernet header + IPv4 TCP. Skip fragments."""
    if len(packet) < 54 or struct.unpack_from("!H", packet, 12)[0] != 0x0800:
        return None
    offset = 14
    ihl = (packet[offset] & 15) * 4
    if packet[offset] >> 4 != 4 or ihl < 20 or len(packet) < offset + ihl + 20:
        return None
    total = struct.unpack_from("!H", packet, offset + 2)[0]
    if total < ihl + 20 or packet[offset + 9] != 6:
        return None
    # Fragments require IP defragmentation; do not silently parse partial data.
    if struct.unpack_from("!H", packet, offset + 6)[0] & 0x3FFF:
        return None
    tcp = offset + ihl
    header = (packet[tcp + 12] >> 4) * 4
    if header < 20 or len(packet) < tcp + header or len(packet) < offset + total:
        return None
    src, dst, seq = struct.unpack_from("!HHI", packet, tcp)
    flags = packet[tcp + 13]
    return Segment(
        socket.inet_ntoa(packet[offset + 12:offset + 16]), src,
        socket.inet_ntoa(packet[offset + 16:offset + 20]), dst, seq,
        bool(flags & 2), bool(flags & 1), bool(flags & 4),
        packet[tcp + header:offset + total],
    )


@dataclass
class Stream:
    next_seq: int | None = None
    data: bytearray = field(default_factory=bytearray)
    pending: dict[int, bytes] = field(default_factory=dict)
    mode: str | None = None  # sim1 | lsf | greeting; None until enough bytes

    def feed(self, segment: Segment) -> list[bytes]:
        if segment.syn:
            self.next_seq = (segment.seq + 1) & 0xFFFFFFFF
            self.data.clear()
            self.pending.clear()
            self.mode = None
        if not segment.payload:
            return []
        seq = segment.seq
        if self.next_seq is None:
            self.next_seq = seq  # best effort if capture began mid-session
        if seq < self.next_seq:
            offset = self.next_seq - seq
            if offset >= len(segment.payload):
                return []  # TCP retransmit
            payload = segment.payload[offset:]
        elif seq > self.next_seq:
            if len(self.pending) < 128:
                self.pending[seq] = segment.payload
            return []
        else:
            payload = segment.payload
        self._append(payload)
        while self.next_seq in self.pending:
            self._append(self.pending.pop(self.next_seq))
        return self._extract()

    def _extract(self) -> list[bytes]:
        if self.mode is None:
            if self.data[:4] == MAGIC:
                self.mode = "sim1"
            elif self.data[:1] == b"\x2f":
                self.mode = "lsf"
            elif (
                len(self.data) >= 4
                and (
                    (self.data[:1] == b"\x68" and self.data[2:4] == b"13")
                    or self.data[:1] in (b"\x3c", b"\x3e")
                )
            ):
                self.mode = "greeting"
            elif len(self.data) >= 4:
                self.mode = "sim1"  # legacy resync-until-magic behavior
        if self.mode == "sim1":
            return self._extract_sim1()
        if self.mode == "lsf":
            return self._extract_lsf()
        if self.mode == "greeting":
            return self._extract_greeting()
        return []

    def _extract_sim1(self) -> list[bytes]:
        frames: list[bytes] = []
        while len(self.data) >= 9:
            if self.data[:4] != MAGIC:
                pos = self.data.find(MAGIC, 1)
                if pos < 0:
                    del self.data[:-3]
                    break
                del self.data[:pos]
                continue
            size = struct.unpack_from("!I", self.data, 5)[0]
            if size > MAX_FRAME:
                del self.data[:4]
                continue  # raw bytes are still retained in tcp_segments
            if len(self.data) < size + 9:
                break
            frames.append(bytes(self.data[:size + 9]))
            del self.data[:size + 9]
        return frames

    def _extract_lsf(self) -> list[bytes]:
        frames: list[bytes] = []
        while len(self.data) >= 12:
            if self.data[:1] != b"\x2f":
                pos = self._resync()
                if pos < 0:
                    del self.data[:-11]
                    break
                del self.data[:pos]
                continue
            declared = lsf_declared(self.data)
            if not declared:
                del self.data[:1]
                continue
            if len(self.data) < declared:
                break
            frames.append(bytes(self.data[:declared]))
            del self.data[:declared]
        return frames

    def _extract_greeting(self) -> list[bytes]:
        end = greeting_boundary(self.data)
        if end is None:
            return []
        frames = [bytes(self.data[:end])]
        del self.data[:end]
        self.mode = "lsf"
        frames.extend(self._extract_lsf())
        return frames

    def _resync(self) -> int:
        for pos in range(1, max(len(self.data) - 11, 1)):
            if lsf_declared(self.data[pos:]) and self.data[pos + 6] == 0x01:
                return pos
        return -1

    def finish(self) -> list[bytes]:
        """Return trailing unframed greeting/ping bytes when a stream closes."""
        if self.mode == "greeting" and self.data:
            out = bytes(self.data)
            self.data.clear()
            return [out]
        return []

    def _append(self, payload: bytes) -> None:
        self.data.extend(payload)
        assert self.next_seq is not None
        self.next_seq = (self.next_seq + len(payload)) & 0xFFFFFFFF
        if len(self.data) > MAX_FRAME + 9:
            self.data.clear()


class AuditDatabase:
    def __init__(self, path: str, manager_pid: int) -> None:
        Path(path).parent.mkdir(parents=True, exist_ok=True)
        self.conn = sqlite3.connect(path)
        self.conn.executescript("""
            PRAGMA journal_mode=WAL;
            PRAGMA synchronous=OFF;
            CREATE TABLE IF NOT EXISTS listeners (
                observed_at TEXT NOT NULL, manager_pid INTEGER NOT NULL,
                pid INTEGER NOT NULL, daemon TEXT, port INTEGER NOT NULL, socket_inode INTEGER NOT NULL,
                UNIQUE(pid, port, socket_inode)
            );
            CREATE TABLE IF NOT EXISTS tcp_segments (
                id INTEGER PRIMARY KEY, observed_at TEXT NOT NULL,
                server_pid INTEGER NOT NULL, server_port INTEGER NOT NULL, daemon TEXT,
                src_ip TEXT NOT NULL, src_port INTEGER NOT NULL,
                dst_ip TEXT NOT NULL, dst_port INTEGER NOT NULL,
                seq INTEGER NOT NULL, direction TEXT NOT NULL,
                payload_hex TEXT NOT NULL, payload_bytes BLOB NOT NULL
            );
            CREATE TABLE IF NOT EXISTS frames (
                id INTEGER PRIMARY KEY, observed_at TEXT NOT NULL,
                manager_pid INTEGER NOT NULL, server_pid INTEGER NOT NULL,
                server_port INTEGER NOT NULL, daemon TEXT,
                src_ip TEXT NOT NULL, src_port INTEGER NOT NULL,
                dst_ip TEXT NOT NULL, dst_port INTEGER NOT NULL,
                direction TEXT NOT NULL, opcode INTEGER,
                decoded_json TEXT, decode_status TEXT NOT NULL,
                raw_hex TEXT NOT NULL, raw_bytes BLOB NOT NULL
            );
            CREATE TABLE IF NOT EXISTS license_events (
                id INTEGER PRIMARY KEY, observed_at TEXT NOT NULL,
                server_pid INTEGER NOT NULL, server_port INTEGER NOT NULL, daemon TEXT,
                feature TEXT, client_user TEXT, client_host TEXT, checkout_id TEXT,
                quantity INTEGER, status TEXT NOT NULL, reason TEXT,
                request_frame_id INTEGER, response_frame_id INTEGER NOT NULL,
                correlation TEXT NOT NULL,
                FOREIGN KEY(request_frame_id) REFERENCES frames(id),
                FOREIGN KEY(response_frame_id) REFERENCES frames(id)
            );
        """)
        self.manager_pid = manager_pid

    def listeners(self, listeners: dict[int, Listener]) -> None:
        for item in listeners.values():
            self.conn.execute("INSERT OR IGNORE INTO listeners VALUES (?, ?, ?, ?, ?, ?)",
                              (_now(), self.manager_pid, item.pid, item.daemon, item.port, item.inode))
        self.conn.commit()

    def segment(self, segment: Segment, listener: Listener, direction: str) -> None:
        self.conn.execute("""INSERT INTO tcp_segments
            (observed_at,server_pid,server_port,daemon,src_ip,src_port,dst_ip,dst_port,
             seq,direction,payload_hex,payload_bytes)
            VALUES (?,?,?,?,?,?,?,?,?,?,?,?)""", (
                _now(), listener.pid, listener.port, listener.daemon,
                segment.src_ip, segment.src_port, segment.dst_ip, segment.dst_port,
                segment.seq, direction, segment.payload.hex(), segment.payload,
            ))
        self.conn.commit()

    def frame(
        self, raw: bytes, segment: Segment, listener: Listener, direction: str,
        enrich: dict | None = None,
    ) -> tuple[int, int | None, dict | None]:
        try:
            opcode, payload = decode_frame(raw)
            decoded = json.dumps(payload, ensure_ascii=False, sort_keys=True)
            state = "SIM1_DECODED"
        except ProtocolError as exc:
            flex = decode_flexlm_frame(raw, direction)
            if flex is None:
                opcode, payload, decoded, state = None, None, None, f"DECODE_ERROR:{exc}"
            else:
                opcode, payload = flex
                decoded = json.dumps(payload, ensure_ascii=False, sort_keys=True)
                state = "FLEXLM_DECODED"
        if enrich and payload is not None:
            payload.update(enrich)
            decoded = json.dumps(payload, ensure_ascii=False, sort_keys=True)
        self.conn.execute("""INSERT INTO frames
            (observed_at,manager_pid,server_pid,server_port,daemon,src_ip,src_port,
             dst_ip,dst_port,direction,opcode,decoded_json,decode_status,raw_hex,raw_bytes)
            VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""", (
                _now(), self.manager_pid, listener.pid, listener.port, listener.daemon,
                segment.src_ip, segment.src_port, segment.dst_ip, segment.dst_port,
                direction, opcode, decoded, state, raw.hex(), raw,
            ))
        frame_id = self.conn.execute("SELECT last_insert_rowid()").fetchone()[0]
        self.conn.commit()
        return frame_id, opcode, payload

    def license_event(
        self, response_id: int, response: dict, request: tuple[int, dict] | None,
        listener: Listener,
    ) -> None:
        request_id, sent = request if request is not None else (None, {})
        self.conn.execute("""INSERT INTO license_events
            (observed_at,server_pid,server_port,daemon,feature,client_user,client_host,
             checkout_id,quantity,status,reason,request_frame_id,response_frame_id,correlation)
            VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)""", (
                _now(), listener.pid, listener.port, listener.daemon,
                response.get("feature"), sent.get("user"), sent.get("host"),
                response.get("checkout_id"), response.get("quantity"),
                response.get("status", "UNKNOWN"), response.get("reason"),
                request_id, response_id, "MATCHED_SIM1_REQUEST" if request else "MISSING_REQUEST",
            ))
        self.conn.commit()

    def flexlm_event(
        self, frame_id: int, listener: Listener, *, feature: str | None,
        client_user: str | None, client_host: str | None, quantity: int | None,
        status: str, reason: str | None, request_frame_id: int | None,
        correlation: str,
    ) -> None:
        """Record a license observation decoded from real FlexLM traffic."""
        self.conn.execute("""INSERT INTO license_events
            (observed_at,server_pid,server_port,daemon,feature,client_user,client_host,
             checkout_id,quantity,status,reason,request_frame_id,response_frame_id,correlation)
            VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)""", (
                _now(), listener.pid, listener.port, listener.daemon,
                feature, client_user, client_host, None, quantity,
                status, reason, request_frame_id, frame_id, correlation,
            ))
        self.conn.commit()

    def close(self) -> None:
        self.conn.close()


def _observe_flexlm(
    db: AuditDatabase, listener: Listener, session: tuple, direction: str,
    frame_id: int, payload: dict, state: dict,
) -> None:
    """Extract license observations from decoded FlexLM frames.

    State holds per-session correlation: the last 0x3c feature query
    (feature, frame_id), the greeting identity, and crypto sessions already
    recorded. Missing identity/feature is never fabricated.
    """
    proto = payload.get("proto")
    ftype = payload.get("type")
    if proto == "lsf-broker" and direction == "client_to_server" and ftype == FLEXLM_QUERY:
        state["features"][session] = (payload.get("feature"), frame_id)
    elif proto == "lsf-broker" and direction == "server_to_client" and ftype == FLEXLM_SEATS:
        feature, query_id = state["features"].get(session, (None, None))
        db.flexlm_event(
            frame_id, listener, feature=feature, client_user=None, client_host=None,
            quantity=payload.get("in_use"), status="FLEXLM_FEATURE_SUMMARY", reason=None,
            request_frame_id=query_id if feature else None,
            correlation="MATCHED_FLEXLM_QUERY" if feature else "NO_FLEXLM_QUERY",
        )
    elif proto == "lsf-broker" and direction == "server_to_client" and ftype == FLEXLM_USER_ROW:
        feature, _ = state["features"].get(session, (None, None))
        db.flexlm_event(
            frame_id, listener, feature=feature, client_user=payload.get("user"),
            client_host=payload.get("host"), quantity=None, status="FLEXLM_IN_USE",
            reason=None, request_frame_id=None,
            correlation="MATCHED_FLEXLM_QUERY" if feature else "NO_FLEXLM_QUERY",
        )
    elif proto == "eda-greeting" and direction == "client_to_server" and payload.get("user"):
        state["identities"][session] = (payload["user"], payload.get("host"))
    elif (
        proto == "lsf-broker" and direction == "server_to_client"
        and ftype == FLEXLM_CRYPTO_READY and session not in state["crypto_seen"]
    ):
        identity = state["identities"].get(session)
        if identity:
            state["crypto_seen"].add(session)
            db.flexlm_event(
                frame_id, listener, feature=None, client_user=identity[0],
                client_host=identity[1], quantity=None, status="FLEXLM_CHECKOUT_ATTEMPT",
                reason="encrypted session payload; identity from greeting",
                request_frame_id=None, correlation="IDENTITY_FROM_GREETING",
            )


def run(manager_pid: int, db_path: str, interface: str = "lo", ready_file: str | None = None) -> None:
    """Attach without modifying lmgrd. Require root or CAP_NET_RAW for AF_PACKET."""
    listeners = discover(manager_pid)
    if manager_pid not in {listener.pid for listener in listeners.values()}:
        raise RuntimeError("manager PID has no listening TCP socket")
    with socket.socket(socket.AF_PACKET, socket.SOCK_RAW, socket.htons(0x0003)) as capture:
        capture.bind((interface, 0))
        try:
            capture.setsockopt(socket.SOL_SOCKET, socket.SO_RCVBUF, 8 << 20)
        except OSError:
            pass  # best effort on busy interfaces; see lic_capture_server.py
        capture.settimeout(0.25)
        db = AuditDatabase(db_path, manager_pid)
        streams: dict[tuple[str, int, str, int], Stream] = {}
        requests: dict[tuple[str, int, str, int], list[tuple[int, int, dict]]] = {}
        state = {"features": {}, "identities": {}, "crypto_seen": set()}
        last_refresh = 0.0
        try:
            db.listeners(listeners)
            if ready_file:
                Path(ready_file).write_text(str(manager_pid), encoding="utf-8")
            while True:
                if time.monotonic() - last_refresh >= 0.5:
                    listeners = discover(manager_pid)
                    db.listeners(listeners)
                    last_refresh = time.monotonic()
                try:
                    raw, address = capture.recvfrom(65535)
                except TimeoutError:
                    continue
                if address[2] not in (PACKET_HOST, PACKET_OUTGOING):
                    continue
                if interface == "lo" and address[2] != PACKET_OUTGOING:
                    continue  # loopback duplicates outgoing/incoming copies
                segment = parse_ipv4_tcp(raw)
                if segment is None:
                    continue
                listener = listeners.get(segment.dst_port)
                direction = "client_to_server"
                if listener is None:
                    listener = listeners.get(segment.src_port)
                    direction = "server_to_client"
                if listener is None:
                    continue
                if segment.payload:
                    db.segment(segment, listener, direction)
                key = (segment.src_ip, segment.src_port, segment.dst_ip, segment.dst_port)
                if segment.syn:
                    streams[key] = Stream()
                stream = streams.setdefault(key, Stream())
                session = (segment.src_ip, segment.src_port, segment.dst_ip, segment.dst_port)
                if direction == "server_to_client":
                    session = (segment.dst_ip, segment.dst_port, segment.src_ip, segment.src_port)
                if segment.syn and direction == "client_to_server":
                    requests.pop(session, None)
                for frame in stream.feed(segment):
                    enrich = None
                    if (
                        direction == "server_to_client"
                        and frame[:1] == b"\x2f"
                        and len(frame) >= 8
                        and frame[7] in (FLEXLM_USER_ROW, FLEXLM_SEATS)
                    ):
                        feature = state["features"].get(session, (None, None))[0]
                        if feature:
                            enrich = {"feature": feature}
                    frame_id, opcode, payload = db.frame(frame, segment, listener, direction, enrich)
                    if payload is None:
                        continue
                    if "proto" not in payload:
                        # SIM1 request/response correlation
                        if direction == "client_to_server" and opcode in (3, 4):
                            pending = requests.setdefault(session, [])
                            if len(pending) < 128:
                                pending.append((opcode, frame_id, payload))
                        elif direction == "server_to_client" and opcode in (131, 132):
                            pending = requests.get(session, [])
                            expected = opcode & 0x7F
                            index = next((i for i, item in enumerate(pending) if item[0] == expected), None)
                            sent = pending.pop(index) if index is not None else None
                            db.license_event(frame_id, payload, (sent[1], sent[2]) if sent else None, listener)
                        continue
                    _observe_flexlm(db, listener, session, direction, frame_id, payload, state)
                if segment.fin or segment.rst:
                    for tail in stream.finish():
                        db.frame(tail, segment, listener, direction)
                    streams.pop(key, None)
                    if direction == "client_to_server":
                        requests.pop(session, None)
                    state["features"].pop(session, None)
                    state["identities"].pop(session, None)
                    state["crypto_seen"].discard(session)
        finally:
            db.close()
