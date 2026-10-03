"""Passive IPv4/TCP SIM1 sniffer: raw segments plus reassembled decoded frames.

Linux AF_PACKET requires CAP_NET_RAW. No simulator instrumentation or proxy is used.
The program attaches to *OS* PID/socket ownership and reads loopback packets.
"""

from __future__ import annotations

import ctypes
import json
import os
import select
import socket
import sqlite3
import struct
import subprocess
import time
from collections.abc import Iterable
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from pathlib import Path

from license_manager_simulators.lmgrd.wire import (
    MAGIC,
    MAX_FRAME,
    ProtocolError,
    decode_frame,
)
from license_manager_simulators.monitor.flexlm import (
    FLEXLM_CHECKOUT_REQ,
    FLEXLM_CRYPTO_READY,
    FLEXLM_DAEMON_HELLO,
    FLEXLM_LICENSE_LINE,
    FLEXLM_LICENSE_LOOKUP,
    FLEXLM_QUERY,
    FLEXLM_SEATS,
    FLEXLM_USER_ROW,
    decode_flexlm_frame,
    greeting_boundary,
    lsf_declared,
)
from license_manager_simulators.monitor.topology import (
    Listener,
    discover,
    discover_managers,
)

PACKET_HOST = 0
PACKET_OUTGOING = 4
# Linux socket option Python's socket module does not export
SO_ATTACH_FILTER = 26
# Data retention: cap frames/tcp_segments/license_events at RETENTION_ROWS
# rows each and collapse repeated client_sessions identity tuple to their
# newest rows, pruned every PRUNE_INTERVAL_S while running.
RETENTION_ROWS = 9999
DEDUP_KEEP = 10
PRUNE_INTERVAL_S = 300.0
# Poller tables roll: keep only the newest observations per feature.
POLLER_OBSERVATIONS = 120
# Self-query channel: the monitor spawns its own lmstat poller on a fixed
# cadence and captures its loopback traffic, so detail/summary data no longer
# depends on external pollers' schedules.
SELF_QUERY_INTERVAL_S = 30.0
# A self-query dump that takes longer is killed and its partial rows rolled
# back (all-or-nothing dumps); the failure is logged in self_query_errors.
LMSTAT_TIMEOUT_S = 5.0
LMUTIL_PATH = os.environ.get("LM_MONITOR_LMUTIL", "/usr/local/bin/lmutil")
# Buffered out-of-order segments before a stream is re-synced: on a tap-side
# loss the real TCP receiver has already ACKed the data, so no retransmit
# will ever fill our gap and the reassembly would stall forever.
PENDING_STALL_LIMIT = 8


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
            elif len(self.data) >= 12 and self._resync() > 0:
                # mid-stream capture: re-sync to the next LSF frame boundary
                del self.data[:self._resync()]
                self.mode = "lsf"
            elif len(self.data) >= 512:
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
            CREATE TABLE IF NOT EXISTS poller_summaries (
                id INTEGER PRIMARY KEY, observed_at TEXT NOT NULL,
                server_pid INTEGER NOT NULL, server_port INTEGER NOT NULL, daemon TEXT,
                feature TEXT, in_use INTEGER, issued INTEGER, report_ts INTEGER,
                request_frame_id INTEGER, response_frame_id INTEGER NOT NULL,
                correlation TEXT NOT NULL, poller_user TEXT, poller_pid TEXT,
                FOREIGN KEY(request_frame_id) REFERENCES frames(id),
                FOREIGN KEY(response_frame_id) REFERENCES frames(id)
            );
            CREATE TABLE IF NOT EXISTS poller_details (
                id INTEGER PRIMARY KEY, observation TEXT NOT NULL,
                server_pid INTEGER NOT NULL, server_port INTEGER NOT NULL, daemon TEXT,
                feature TEXT NOT NULL, client_user TEXT, client_host TEXT,
                client_tty TEXT, client_version TEXT,
                checkout_id INTEGER, checkout_ts INTEGER,
                client_pid TEXT, correlation TEXT,
                poller_user TEXT, poller_pid TEXT
            );
            CREATE TABLE IF NOT EXISTS capture_stats (
                id INTEGER PRIMARY KEY, observed_at TEXT NOT NULL,
                packets INTEGER NOT NULL, drops INTEGER NOT NULL
            );
            CREATE TABLE IF NOT EXISTS client_sessions (
                id INTEGER PRIMARY KEY, observed_at TEXT NOT NULL,
                server_pid INTEGER NOT NULL, server_port INTEGER NOT NULL, daemon TEXT,
                client_ip TEXT NOT NULL, client_port INTEGER NOT NULL,
                client_user TEXT, client_host TEXT, client_pid TEXT,
                client_tty TEXT, client_platform TEXT, greeting_daemon TEXT,
                feature TEXT, greeting_frame_id INTEGER,
                FOREIGN KEY(greeting_frame_id) REFERENCES frames(id)
            );
            CREATE INDEX IF NOT EXISTS idx_frames_observed ON frames(observed_at);
            CREATE INDEX IF NOT EXISTS idx_segments_observed ON tcp_segments(observed_at);
            CREATE INDEX IF NOT EXISTS idx_events_observed ON license_events(observed_at);
            CREATE INDEX IF NOT EXISTS idx_summaries_observed ON poller_summaries(observed_at);
            CREATE INDEX IF NOT EXISTS idx_details_feature ON poller_details(feature, observation);
            CREATE INDEX IF NOT EXISTS idx_sessions_observed ON client_sessions(observed_at);
            CREATE INDEX IF NOT EXISTS idx_sessions_user_host
                ON client_sessions(client_user, client_host);
            CREATE VIEW IF NOT EXISTS v_client_events AS
            SELECT e.*,
                   s.client_pid AS holder_pid,
                   s.client_tty AS holder_tty,
                   s.client_platform AS holder_platform,
                   s.client_port AS holder_client_port,
                   s.observed_at AS holder_greeting_at
            FROM license_events e
            LEFT JOIN client_sessions s ON s.id = (
                SELECT s2.id FROM client_sessions s2
                WHERE s2.client_user = e.client_user
                  AND s2.client_host = e.client_host
                ORDER BY s2.id DESC LIMIT 1
            );
            CREATE TABLE IF NOT EXISTS heartbeats (
                id INTEGER PRIMARY KEY,
                session_key TEXT NOT NULL UNIQUE,
                server_pid INTEGER NOT NULL, server_port INTEGER NOT NULL, daemon TEXT,
                client_user TEXT, client_host TEXT, client_pid TEXT,
                feature TEXT,
                first_seen TEXT NOT NULL, last_seen TEXT NOT NULL,
                beats INTEGER NOT NULL, bytes INTEGER NOT NULL, last_len INTEGER
            );
            CREATE TABLE IF NOT EXISTS license_definitions (
                id INTEGER PRIMARY KEY, observed_at TEXT NOT NULL,
                server_pid INTEGER NOT NULL, server_port INTEGER NOT NULL, daemon TEXT,
                keyword TEXT NOT NULL, feature TEXT NOT NULL, vendor TEXT,
                version TEXT, expiry TEXT, seats INTEGER,
                line TEXT NOT NULL
            );
            CREATE INDEX IF NOT EXISTS idx_licdef_feature
                ON license_definitions(feature, id);
            CREATE TABLE IF NOT EXISTS self_query_errors (
                id INTEGER PRIMARY KEY, observed_at TEXT NOT NULL,
                manager_pid INTEGER NOT NULL, mgr_port INTEGER,
                elapsed_s REAL, reason TEXT NOT NULL
            );
        """)
        # Migrations for DBs created before these columns existed (the live
        # capture DB is appended to across monitor restarts).
        columns = {row[1] for row in self.conn.execute("PRAGMA table_info(license_events)")}
        for name in ("client_pid", "client_tty", "client_platform",
                     "poller_user", "poller_pid"):
            if name not in columns:
                self.conn.execute(f"ALTER TABLE license_events ADD COLUMN {name} TEXT")
        if "checkout_ts" not in columns:
            # Client checkout epoch (0x3d request) / seat start epoch (0x14
            # row): the wire-native key that ties an encrypted checkout
            # exchange to its seat row.
            self.conn.execute("ALTER TABLE license_events ADD COLUMN checkout_ts INTEGER")
        self.conn.execute("""CREATE INDEX IF NOT EXISTS idx_events_seat_join
            ON license_events(client_user, client_host, checkout_ts)""")
        # Poller seat summaries moved out of license_events into their own
        # table; migrate rows recorded before the split (legacy rows keep
        # NULL issued/report_ts, which the 0x4e payload only later supplies).
        legacy = self.conn.execute(
            "SELECT COUNT(*) FROM license_events WHERE status = 'FLEXLM_FEATURE_SUMMARY'"
        ).fetchone()[0]
        if legacy:
            self.conn.execute("""INSERT INTO poller_summaries
                (observed_at,server_pid,server_port,daemon,feature,in_use,
                 request_frame_id,response_frame_id,correlation,poller_user,poller_pid)
                SELECT observed_at,server_pid,server_port,daemon,feature,quantity,
                       request_frame_id,response_frame_id,correlation,poller_user,poller_pid
                FROM license_events WHERE status = 'FLEXLM_FEATURE_SUMMARY'""")
            self.conn.execute(
                "DELETE FROM license_events WHERE status = 'FLEXLM_FEATURE_SUMMARY'")
            self.conn.commit()
        # Rolling per-feature retention: poller tables keep only the 3 newest
        # observations per feature (a one-time trim here; each write trims
        # its own feature afterwards).
        legacy_details = {row[1] for row in self.conn.execute(
            "PRAGMA table_info(poller_details)")}
        if "count" in legacy_details:
            # holder-grouped rollup schema from before the per-seat rows:
            # a rolling 3-observation cache, safe to rebuild from traffic
            self.conn.execute("DROP TABLE poller_details")
            self.conn.execute("""CREATE TABLE IF NOT EXISTS poller_details (
                id INTEGER PRIMARY KEY, observation TEXT NOT NULL,
                server_pid INTEGER NOT NULL, server_port INTEGER NOT NULL, daemon TEXT,
                feature TEXT NOT NULL, client_user TEXT, client_host TEXT,
                client_tty TEXT, client_version TEXT,
                checkout_id INTEGER, checkout_ts INTEGER,
                client_pid TEXT, correlation TEXT,
                poller_user TEXT, poller_pid TEXT
            )""")
            self.conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_details_feature "
                "ON poller_details(feature, observation)")
            self.conn.commit()
        self.conn.execute("""DELETE FROM poller_summaries WHERE id IN (
            SELECT id FROM (
                SELECT id, ROW_NUMBER() OVER (
                    PARTITION BY feature ORDER BY id DESC) AS rn
                FROM poller_summaries) WHERE rn > ?)""", (POLLER_OBSERVATIONS,))
        self.conn.execute("""DELETE FROM license_definitions WHERE id IN (
            SELECT id FROM (
                SELECT id, ROW_NUMBER() OVER (
                    PARTITION BY feature ORDER BY id DESC) AS rn
                FROM license_definitions) WHERE rn > ?)""", (POLLER_OBSERVATIONS,))
        self.conn.execute("""DELETE FROM poller_details WHERE id IN (
            SELECT id FROM (
                SELECT id, DENSE_RANK() OVER (
                    PARTITION BY feature ORDER BY observation DESC) AS rn
                FROM poller_details) WHERE rn > ?)""", (POLLER_OBSERVATIONS,))
        self.conn.commit()
        self.manager_pid = manager_pid

    def listeners(self, listeners: dict[int, Listener]) -> None:
        for item in listeners.values():
            self.conn.execute("INSERT OR IGNORE INTO listeners VALUES (?, ?, ?, ?, ?, ?)",
                              (_now(), item.manager_pid or self.manager_pid,
                               item.pid, item.daemon, item.port, item.inode))
        self.conn.commit()

    def flush(self) -> None:
        """Commit queued writes. Batch commits (#6): one commit per captured
        packet instead of per row, because every commit on an NFS-backed DB
        is a network round trip that throttles the capture loop."""
        if self.conn.in_transaction:
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
                _now(), listener.manager_pid or self.manager_pid,
                listener.pid, listener.port, listener.daemon,
                segment.src_ip, segment.src_port, segment.dst_ip, segment.dst_port,
                direction, opcode, decoded, state, raw.hex(), raw,
            ))
        frame_id = self.conn.execute("SELECT last_insert_rowid()").fetchone()[0]
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

    def flexlm_event(
        self, frame_id: int, listener: Listener, *, feature: str | None,
        client_user: str | None, client_host: str | None, quantity: int | None,
        status: str, reason: str | None, request_frame_id: int | None,
        correlation: str, client_pid: str | None = None, client_tty: str | None = None,
        client_platform: str | None = None, poller_user: str | None = None,
        poller_pid: str | None = None, checkout_id: int | None = None,
        checkout_ts: int | None = None,
    ) -> int:
        """Record a license observation decoded from real FlexLM traffic."""
        cursor = self.conn.execute("""INSERT INTO license_events
            (observed_at,server_pid,server_port,daemon,feature,client_user,client_host,
             checkout_id,quantity,status,reason,request_frame_id,response_frame_id,correlation,
             client_pid,client_tty,client_platform,poller_user,poller_pid,checkout_ts)
            VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""", (
                _now(), listener.pid, listener.port, listener.daemon,
                feature, client_user, client_host, checkout_id, quantity,
                status, reason, request_frame_id, frame_id, correlation,
                client_pid, client_tty, client_platform, poller_user, poller_pid,
                checkout_ts,
            ))
        return cursor.lastrowid

    def poller_summary(
        self, frame_id: int, listener: Listener, *, feature: str | None,
        in_use: int | None, issued: int | None, report_ts: int | None,
        request_frame_id: int | None, correlation: str,
        poller_user: str | None = None, poller_pid: str | None = None,
    ) -> int:
        """Record a 0x4e poller seat summary. These are poller-scoped totals
        (feature, seat counts, reporting poller), not per-client events, so
        they live in their own table instead of license_events."""
        cursor = self.conn.execute("""INSERT INTO poller_summaries
            (observed_at,server_pid,server_port,daemon,feature,in_use,issued,
             report_ts,request_frame_id,response_frame_id,correlation,
             poller_user,poller_pid)
            VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)""", (
                _now(), listener.pid, listener.port, listener.daemon,
                feature, in_use, issued, report_ts, request_frame_id, frame_id,
                correlation, poller_user, poller_pid,
            ))
        # keep only the newest observations of this feature
        self.conn.execute("""DELETE FROM poller_summaries WHERE feature IS ?
            AND id NOT IN (SELECT id FROM poller_summaries WHERE feature IS ?
            ORDER BY id DESC LIMIT ?)""",
            (feature, feature, POLLER_OBSERVATIONS))
        return cursor.lastrowid

    def poller_detail(
        self, observation: str, listener: Listener, *, feature: str,
        user: str | None, host: str | None, tty: str | None,
        version: str | None, checkout_id: int, checkout_ts: int | None,
        client_pid: str | None, correlation: str,
        poller_user: str | None = None, poller_pid: str | None = None,
    ) -> int:
        """Record one poller-reported seat (one lmstat user line): feature,
        holder identity, checkout handle, seat start epoch and the ts-join
        pid attribution. Only features with real checkouts reach this (a
        feature with no held seats has no 0x14 rows)."""
        cursor = self.conn.execute("""INSERT INTO poller_details
            (observation,server_pid,server_port,daemon,feature,client_user,
             client_host,client_tty,client_version,checkout_id,checkout_ts,
             client_pid,correlation,poller_user,poller_pid)
            VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""", (
                observation, listener.pid, listener.port, listener.daemon,
                feature, user, host, tty, version, checkout_id, checkout_ts,
                client_pid, correlation, poller_user, poller_pid,
            ))
        # keep only the newest observations of this feature
        self.conn.execute("""DELETE FROM poller_details WHERE feature IS ?
            AND observation NOT IN (SELECT DISTINCT observation FROM poller_details
            WHERE feature IS ? ORDER BY observation DESC LIMIT ?)""",
            (feature, feature, POLLER_OBSERVATIONS))
        return cursor.lastrowid

    def license_definition(
        self, listener: Listener, *, keyword: str, feature: str, vendor: str | None,
        version: str | None, expiry: str | None, seats: int | None, line: str,
    ) -> int:
        """Record one license-file definition line (INCREMENT/FEATURE) parsed
        from the lmstat -i dump text on the wire: feature, vendor daemon,
        version, expiry and seat count. Like poller_summaries, each feature
        keeps only the newest POLLER_OBSERVATIONS rows."""
        cursor = self.conn.execute("""INSERT INTO license_definitions
            (observed_at,server_pid,server_port,daemon,keyword,feature,vendor,
             version,expiry,seats,line)
            VALUES (?,?,?,?,?,?,?,?,?,?,?)""", (
                _now(), listener.pid, listener.port, listener.daemon,
                keyword, feature, vendor, version, expiry, seats, line))
        self.conn.execute("""DELETE FROM license_definitions WHERE feature IS ?
            AND id NOT IN (SELECT id FROM license_definitions WHERE feature IS ?
            ORDER BY id DESC LIMIT ?)""", (feature, feature, POLLER_OBSERVATIONS))
        return cursor.lastrowid

    def self_query_error(
        self, manager_pid: int, mgr_port: int | None, elapsed_s: float, reason: str,
    ) -> int:
        """Log a failed self-query dump (timeout, spawn failure) so capture
        gaps are explainable instead of silent."""
        cursor = self.conn.execute("""INSERT INTO self_query_errors
            (observed_at, manager_pid, mgr_port, elapsed_s, reason)
            VALUES (?,?,?,?,?)""",
            (_now(), manager_pid, mgr_port, elapsed_s, reason))
        return cursor.lastrowid

    def rollback_partial_dump(
        self, manager_pid: int, ports: list[int], since_iso: str,
    ) -> int:
        """Delete the partial rows a timed-out lmstat dump already wrote for
        this service (all-or-nothing dumps). Only query-channel tables are
        touched, scoped to the service's ports and the dump window; checkout
        attempts live on the --iface socket and are never touched."""
        if not ports:
            return 0
        placeholders = ",".join("?" * len(ports))
        total = 0
        for table, ts_col in (("poller_summaries", "observed_at"),
                              ("poller_details", "observation"),
                              ("license_definitions", "observed_at")):
            cur = self.conn.execute(
                f"DELETE FROM {table} WHERE {ts_col} >= ? AND server_port IN "
                f"({placeholders})", (since_iso, *ports))
            total += cur.rowcount
        cur = self.conn.execute(
            f"""DELETE FROM license_events WHERE status = 'FLEXLM_IN_USE'
                AND observed_at >= ? AND server_port IN ({placeholders})""",
            (since_iso, *ports))
        total += cur.rowcount
        return total

    def seat_seen(self, feature: str | None, client_user: str | None,
                  client_host: str | None, checkout_id: int | None,
                  max_age_s: float = 21600.0) -> bool:
        """True when this exact seat (feature, user, host, checkout id) was
        already reported within the window; the pollers re-report every seat
        each cycle, so only the first sighting is stored."""
        if checkout_id is None:
            return False
        cutoff = (datetime.now(UTC) - timedelta(seconds=max_age_s)).isoformat()
        row = self.conn.execute("""SELECT 1 FROM license_events
            WHERE status = 'FLEXLM_IN_USE' AND feature IS ?
              AND client_user IS ? AND client_host IS ? AND checkout_id IS ?
              AND observed_at >= ? LIMIT 1""", (
                feature, client_user, client_host, checkout_id, cutoff,
            )).fetchone()
        return row is not None

    def match_checkout_attempts(
        self, client_user: str | None, client_host: str | None, checkout_ts: int,
    ) -> tuple[str | None, str | None, str | None, str | None, str]:
        """Pids and features of the checkout attempts at (user, host, ts).

        The checkout exchange itself is encrypted, but each attempt carries
        its same-session greeting identity plus the client epoch from the
        0x3d request, and each 0x14 seat row carries its start epoch: equal
        timestamps tie a seat to the process that checked it out. Several
        processes of one user may check out within the same second – that
        yields a comma-joined pid set (and, when those attempts were named
        for different features, a comma-joined feature set) instead of a
        guess.

        The two epochs are read from different clocks, so hosts with
        drifting clocks miss the exact-second join; a bounded +-3s window on
        the SAME (user, host) recovers those as *_SKEW matches. A checkout
        and its seat always share the host, so attempts from other hosts are
        never joined."""
        rows = self.conn.execute("""SELECT client_pid, client_tty, client_platform, feature
            FROM license_events
            WHERE status = 'FLEXLM_CHECKOUT_ATTEMPT' AND client_user IS ?
              AND client_host IS ? AND checkout_ts IS ? AND client_pid IS NOT NULL""",
            (client_user, client_host, checkout_ts)).fetchall()
        skew = False
        pids = sorted({row[0] for row in rows})
        if not pids:
            rows = self.conn.execute("""SELECT client_pid, client_tty, client_platform, feature
                FROM license_events
                WHERE status = 'FLEXLM_CHECKOUT_ATTEMPT' AND client_user IS ?
                  AND client_host IS ? AND checkout_ts BETWEEN ? - 3 AND ? + 3
                  AND client_pid IS NOT NULL""",
                (client_user, client_host, checkout_ts, checkout_ts)).fetchall()
            pids = sorted({row[0] for row in rows})
            skew = bool(pids)
        features = sorted({row[3] for row in rows if row[3]})
        feature_set = ",".join(features) if features else None
        if not pids:
            return None, None, None, None, "NO_CHECKOUT_MATCH"
        suffix = "_SKEW" if skew else ""
        if len(pids) == 1:
            return (pids[0], rows[0][1], rows[0][2], feature_set,
                    f"MATCHED_CHECKOUT_TS{suffix}")
        return (",".join(pids), None, None, feature_set,
                f"AMBIGUOUS_CHECKOUT_TS{suffix}")

    def backfill_attempt_features(
        self, client_user: str | None, client_host: str | None, checkout_ts: int,
    ) -> bool:
        """Name the feature on checkout attempts and feature-less seats at
        (user, host, ts) from each other, when the counts line up 1:1.

        Two equally guarded directions, both requiring a single distinct
        feature and an exact attempt:seat count match, so nothing is
        fabricated: (a) N unnamed attempts + N same-named seats -> each
        attempt ran that seat's feature; (b) N unnamed seats + N
        same-named attempts (e.g. named by their own 0x47 lookups) -> those
        seats belong to those attempts. Ambiguous cases (count mismatch,
        mixed features) stay unnamed."""
        seats = self.conn.execute("""SELECT COUNT(*), COUNT(feature),
                COUNT(DISTINCT feature) FROM license_events
            WHERE status = 'FLEXLM_IN_USE' AND client_user IS ?
              AND client_host IS ? AND checkout_ts IS ?""",
            (client_user, client_host, checkout_ts)).fetchone()
        attempts = self.conn.execute("""SELECT COUNT(*), COUNT(feature),
                COUNT(DISTINCT feature) FROM license_events
            WHERE status = 'FLEXLM_CHECKOUT_ATTEMPT' AND client_user IS ?
              AND client_host IS ? AND checkout_ts IS ?""",
            (client_user, client_host, checkout_ts)).fetchone()
        total_seats, named_seats, seat_features_n = seats
        total_attempts, named_attempts, attempt_features_n = attempts
        # (a) name attempts from seats
        if (
            total_seats and named_seats == total_seats and seat_features_n == 1
            and total_attempts - named_attempts == total_seats
        ):
            feature = self.conn.execute("""SELECT feature FROM license_events
                WHERE status = 'FLEXLM_IN_USE' AND client_user IS ?
                  AND client_host IS ? AND checkout_ts IS ? LIMIT 1""",
                (client_user, client_host, checkout_ts)).fetchone()[0]
            self.conn.execute("""UPDATE license_events
                SET feature = ?, correlation = 'FEATURE_FROM_SEAT_TS'
                WHERE status = 'FLEXLM_CHECKOUT_ATTEMPT' AND client_user IS ?
                  AND client_host IS ? AND checkout_ts IS ? AND feature IS NULL""",
                (feature, client_user, client_host, checkout_ts))
            return True
        # (b) name seats from attempts
        if (
            total_seats and named_seats == 0
            and named_attempts == total_attempts and attempt_features_n == 1
            and total_attempts == total_seats
        ):
            feature = self.conn.execute("""SELECT feature FROM license_events
                WHERE status = 'FLEXLM_CHECKOUT_ATTEMPT' AND client_user IS ?
                  AND client_host IS ? AND checkout_ts IS ? LIMIT 1""",
                (client_user, client_host, checkout_ts)).fetchone()[0]
            self.conn.execute("""UPDATE license_events
                SET feature = ?
                WHERE status = 'FLEXLM_IN_USE' AND client_user IS ?
                  AND client_host IS ? AND checkout_ts IS ? AND feature IS NULL""",
                (feature, client_user, client_host, checkout_ts))
            return True
        return False

    def client_session(self, greeting_frame_id: int, listener: Listener,
                       session: tuple, payload: dict) -> int:
        """Record the client tool identity decoded from its greeting (user,
        host, pid, tty, platform, requested daemon). One row per greeting."""
        cursor = self.conn.execute("""INSERT INTO client_sessions
            (observed_at,server_pid,server_port,daemon,client_ip,client_port,
             client_user,client_host,client_pid,client_tty,client_platform,
             greeting_daemon,greeting_frame_id)
            VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)""", (
                _now(), listener.pid, listener.port, listener.daemon,
                session[0], session[1], payload.get("user"), payload.get("host"),
                payload.get("pid"), payload.get("tty"), payload.get("platform"),
                payload.get("daemon"), greeting_frame_id,
            ))
        return cursor.lastrowid

    def session_feature(self, session_id: int, feature: str) -> None:
        """Attach a decoded feature (0x3c query / 0x47 lookup) to the client
        session row created from its greeting."""
        self.conn.execute("UPDATE client_sessions SET feature = ? WHERE id = ?",
                          (feature, session_id))

    def heartbeat(self, session: tuple, listener: Listener, identity: tuple | None,
                  feature: str | None, segment: Segment) -> None:
        """Aggregate encrypted-session keepalive traffic (client heartbeats)
        per connection: beat count, byte totals, first/last seen."""
        key = f"{session[0]}:{session[1]}->{session[2]}:{session[3]}"
        now = _now()
        self.conn.execute("""
            INSERT INTO heartbeats
            (session_key,server_pid,server_port,daemon,client_user,client_host,
             client_pid,feature,first_seen,last_seen,beats,bytes,last_len)
            VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)
            ON CONFLICT(session_key) DO UPDATE SET
                last_seen=excluded.last_seen, beats=beats+1,
                bytes=bytes+excluded.bytes, last_len=excluded.last_len,
                feature=COALESCE(heartbeats.feature, excluded.feature),
                client_user=COALESCE(heartbeats.client_user, excluded.client_user),
                client_pid=COALESCE(heartbeats.client_pid, excluded.client_pid)
        """, (
            key, listener.pid, listener.port, listener.daemon,
            identity[0] if identity else None, identity[1] if identity else None,
            identity[2] if identity else None, feature,
            now, now, 1, len(segment.payload), len(segment.payload),
        ))

    def capture_stats(self, packets: int, drops: int) -> None:
        """Sample the AF_PACKET socket counters. Reading PACKET_STATISTICS
        resets the kernel counters, so each row holds the packets/drops
        since the previous sample; SUM(drops) is the total since start."""
        self.conn.execute(
            "INSERT INTO capture_stats (observed_at, packets, drops) VALUES (?,?,?)",
            (_now(), packets, drops))

    def prune(self) -> None:
        """Enforce the retention caps: keep only the RETENTION_ROWS newest
        rows in frames/tcp_segments/license_events (row id is insertion
        order) and collapse repeated client_sessions identity tuples (all
        columns except id/observed_at) to their DEDUP_KEEP newest rows.
        Frames and events are pruned independently, so a retained event may
        reference pruned frames."""
        for table in ("tcp_segments", "frames", "license_events", "heartbeats",
                      "poller_summaries", "poller_details", "capture_stats",
                      "license_definitions", "self_query_errors"):
            self.conn.execute(f"""
                DELETE FROM {table} WHERE id NOT IN (
                    SELECT id FROM {table} ORDER BY id DESC LIMIT ?
                )""", (RETENTION_ROWS,))
        self.conn.execute("""
            DELETE FROM client_sessions WHERE id IN (
                SELECT id FROM (
                    SELECT id, ROW_NUMBER() OVER (
                        PARTITION BY server_pid, server_port, daemon, client_ip,
                        client_port, client_pid, client_user, client_host,
                        client_tty, client_platform, greeting_daemon, feature
                        ORDER BY id DESC
                    ) AS rn
                    FROM client_sessions
                ) WHERE rn > ?
            )""", (DEDUP_KEEP,))

    def attach_feature(
        self, feature: str, client_user: str | None, client_host: str | None,
        client_pid: str | None, request_frame_id: int, max_age_s: float = 60.0,
    ) -> bool:
        """Attach a decoded license-lookup feature to the most recent
        FLEXLM_CHECKOUT_ATTEMPT of the same client PROCESS (identity plus the
        greeting pid; the encrypted checkout request itself is unreadable, the
        0x47 lookup that follows names the feature)."""
        cutoff = (datetime.now(UTC) - timedelta(seconds=max_age_s)).isoformat()
        row = self.conn.execute("""SELECT id FROM license_events
            WHERE status = 'FLEXLM_CHECKOUT_ATTEMPT' AND feature IS NULL
              AND client_user IS ? AND client_host IS ? AND client_pid IS ?
              AND observed_at >= ?
            ORDER BY id ASC LIMIT 1""", (
                client_user, client_host, client_pid, cutoff,
            )).fetchone()
        if row is None:
            return False
        self.conn.execute("""UPDATE license_events
            SET feature = ?, request_frame_id = ?,
                correlation = 'FEATURE_FROM_LICENSE_LOOKUP'
            WHERE id = ?""", (feature, request_frame_id, row[0]))
        return True

    def close(self) -> None:
        self.conn.close()


def _accumulate_poller_detail(
    state: dict, session: tuple, feature: str, user: str | None, host: str | None,
    tty: str | None, version: str | None, checkout_id: int,
    start_ts: int | None, pid: str | None, match: str,
) -> None:
    """Buffer one 0x14 seat row (one lmstat user line) for the poller_details
    roll-up, grouped per (session, feature) until the observation completes
    (the next 0x3c feature switch or the connection closing)."""
    state.setdefault("poller_details", {}).setdefault(session, {}).setdefault(
        feature, []).append(
        (user, host, tty, version, checkout_id, start_ts, pid, match))


def _flush_poller_details(
    db: AuditDatabase, state: dict, session: tuple, listener: Listener,
) -> None:
    """Write one observation's buffered seat rows to poller_details, one row
    per lmstat user line. All rows of one observation share the observation
    timestamp, which the per-feature 3-observation retention keys on."""
    groups = state.get("poller_details", {}).pop(session, None)
    if not groups:
        return
    observation = _now()
    poller = state.get("recent_identity", {}).get(session[0])
    poller_user = poller[0] if poller else None
    poller_pid = poller[2] if poller else None
    for feature, seats in groups.items():
        for user, host, tty, version, checkout_id, start_ts, pid, match in seats:
            db.poller_detail(
                observation, listener, feature=feature, user=user, host=host,
                tty=tty, version=version, checkout_id=checkout_id,
                checkout_ts=start_ts, client_pid=pid, correlation=match,
                poller_user=poller_user, poller_pid=poller_pid,
            )


def _identity_for(state: dict, session: tuple) -> tuple[tuple | None, str]:
    """Client identity for encrypted-session frames: prefer this session's
    own greeting, else the latest greeting seen from the same client IP
    (FlexLM opens sibling connections per request phase). Identity tuples are
    (user, host, pid, tty, platform) from the greeting."""
    identity = state["identities"].get(session)
    if identity:
        return identity, "IDENTITY_FROM_GREETING"
    recent = state["recent_identity"].get(session[0])
    if recent:
        return recent, "IDENTITY_FROM_RECENT_GREETING"
    return None, "NO_GREETING_IDENTITY"


def _identity_fields(identity: tuple | None) -> dict:
    if not identity:
        return {"client_user": None, "client_host": None, "client_pid": None,
                "client_tty": None, "client_platform": None}
    user, host, pid, tty, platform = identity
    return {"client_user": user, "client_host": host, "client_pid": pid,
            "client_tty": tty, "client_platform": platform}


def _seat_pid(
    state: dict, db: AuditDatabase, user: str | None, host: str | None,
    start_ts: int | None,
) -> tuple[str | None, str | None, str | None, str | None, str]:
    """Pid and feature attribution for a 0x14 seat row.

    Wire-native first: the seat's start epoch equals the checkout session's
    0x3d client timestamp, whose own greeting named the pid; the backfilled
    attempt features name what those pids checked out (comma-joined when
    several processes of one user checked out different features in the same
    second – mirroring the pid set). The latest-greeting holder is only a
    fallback when NO checkout attempt exists at that (user, host, ts) – it
    must never override a real match, since several processes of one user
    share the holder key (verified: sample.user@qa-gui32, five concurrent
    pids)."""
    if start_ts is not None:
        pid, tty, platform, features, match = db.match_checkout_attempts(user, host, start_ts)
        if match != "NO_CHECKOUT_MATCH":
            return pid, tty, platform, features, match
    holder = state["holders"].get((user, host))
    if holder is None:
        return None, None, None, None, (
            "NO_CHECKOUT_MATCH" if start_ts is not None else "MATCHED_FLEXLM_QUERY"
        )
    return holder[2], holder[3], holder[4], None, (
        "HOLDER_NO_TS_MATCH" if start_ts is not None else "MATCHED_FLEXLM_QUERY"
    )


def _observe_flexlm(
    db: AuditDatabase, listener: Listener, session: tuple, direction: str,
    frame_id: int, payload: dict, state: dict,
) -> None:
    """Extract license observations from decoded FlexLM frames.

    State holds per-session correlation: the last 0x3c feature query
    (feature, frame_id), the 0x47 license lookup, the greeting identity, the
    client_sessions row id, seat-holder identities keyed by (user, host) for
    matching IN_USE rows, and crypto sessions already recorded. Poller
    attribution matches the poller's IP to its latest greeting (ambiguous on
    shared hosts). Missing identity/feature is never fabricated.
    """
    proto = payload.get("proto")
    ftype = payload.get("type")
    if proto == "lsf-broker" and direction == "server_to_client" and ftype == FLEXLM_DAEMON_HELLO:
        _record_daemon_name(state, listener.port, payload)
    listener = _wire_listener(state, listener)
    if proto == "lsf-broker" and direction == "client_to_server" and ftype == FLEXLM_QUERY:
        # the new 0x3c ends the previous feature's block: its seat rows
        # form a complete observation now
        _flush_poller_details(db, state, session, listener)
        state["features"][session] = (payload.get("feature"), frame_id)
        session_id = state["session_ids"].get(session)
        if session_id and payload.get("feature"):
            db.session_feature(session_id, payload["feature"])
    elif (
        proto == "lsf-broker" and direction == "client_to_server"
        and ftype == FLEXLM_LICENSE_LOOKUP
    ):
        # 0x47: the client asks for a feature's license terms; the 0x46 reply
        # carries the INCREMENT line. Both are recorded as observations. The
        # lookup also teaches the monitor which feature this client PROCESS
        # (ip, pid from its own greeting) is about to use.
        feature = payload.get("feature")
        state["lookups"][session] = (feature, frame_id)
        identity, correlation = _identity_for(state, session)
        db.flexlm_event(
            frame_id, listener, feature=feature, quantity=None,
            status="FLEXLM_LICENSE_LOOKUP", reason=payload.get("param"),
            request_frame_id=None, correlation=correlation,
            **_identity_fields(identity),
        )
        session_id = state["session_ids"].get(session)
        if session_id and feature:
            db.session_feature(session_id, feature)
        if feature and identity and identity[2]:
            # Remember what feature this client PROCESS (ip, pid from its own
            # greeting) checked out: its heartbeat rows on sibling connections
            # carry the same pid via their own greetings.
            state["pid_feature"][(session[0], identity[2])] = feature
            db.attach_feature(feature, identity[0], identity[1], identity[2], frame_id)
    elif (
        proto == "lsf-broker" and direction == "server_to_client"
        and ftype == FLEXLM_LICENSE_LINE and payload.get("feature")
    ):
        feature, lookup_id = state["lookups"].get(session, (None, None))
        identity, correlation = _identity_for(state, session)
        db.flexlm_event(
            frame_id, listener, feature=payload.get("feature"),
            # the INCREMENT seat count is the license pool size, NOT a
            # checkout quantity: quantity stays NULL, the raw line (with
            # seats) is preserved in reason/decoded_json/license_definitions
            quantity=None, status="FLEXLM_LICENSE_LINE",
            reason=payload.get("license_line"),
            request_frame_id=lookup_id if feature else None,
            correlation="MATCHED_FLEXLM_LOOKUP" if feature else correlation,
            **_identity_fields(identity),
        )
    elif proto == "lsf-broker" and direction == "server_to_client" and ftype == FLEXLM_SEATS:
        feature, query_id = state["features"].get(session, (None, None))
        poller = state["recent_identity"].get(session[0])
        db.poller_summary(
            frame_id, listener, feature=feature, in_use=payload.get("in_use"),
            issued=payload.get("issued"), report_ts=payload.get("report_ts"),
            request_frame_id=query_id if feature else None,
            correlation="MATCHED_FLEXLM_QUERY" if feature else "NO_FLEXLM_QUERY",
            poller_user=poller[0] if poller else None,
            poller_pid=poller[2] if poller else None,
        )
    elif proto == "lsf-broker" and direction == "server_to_client" and ftype == FLEXLM_USER_ROW:
        feature, query_id = state["features"].get(session, (None, None))
        user, host = payload.get("user"), payload.get("host")
        poller = state["recent_identity"].get(session[0])
        start_ts = payload.get("start_ts")
        if start_ts is not None:
            # Name the attempts (and NULL-feature seats) for this second
            # before matching, so the feature set below sees fresh names.
            db.backfill_attempt_features(user, host, start_ts)
        pid, tty, platform, seat_features, match = _seat_pid(state, db, user, host, start_ts)
        if feature and payload.get("checkout_id") is not None:
            _accumulate_poller_detail(
                state, session, feature, user, host, payload.get("tty"),
                payload.get("version"), payload["checkout_id"], start_ts, pid, match,
            )
        db.flexlm_event(
            frame_id, listener, feature=seat_features or feature, client_user=user,
            client_host=host, quantity=1, status="FLEXLM_IN_USE",
            reason=None, request_frame_id=query_id if feature else None,
            correlation=match if (feature or seat_features) else "NO_FLEXLM_QUERY",
            client_pid=pid, client_tty=tty, client_platform=platform,
            poller_user=poller[0] if poller else None,
            poller_pid=poller[2] if poller else None,
            checkout_id=payload.get("checkout_id"), checkout_ts=start_ts,
        )
    elif proto == "eda-greeting" and direction == "client_to_server" and payload.get("user"):
        identity = (
            payload["user"], payload.get("host"), payload.get("pid"),
            payload.get("tty"), payload.get("platform"),
        )
        state["identities"][session] = identity
        state["recent_identity"][session[0]] = identity
        state["holders"][(payload["user"], payload.get("host"))] = identity
        state["session_ids"][session] = db.client_session(frame_id, listener, session, payload)
    elif (
        proto == "lsf-broker" and direction == "client_to_server"
        and ftype == FLEXLM_CHECKOUT_REQ and payload.get("checkout_ts") is not None
    ):
        # Encrypted checkout request: its 0x61 response fires the attempt
        # event, so remember the client timestamp (equal to the eventual
        # seat row's start epoch) for the seat join.
        state["checkout_requests"][session] = (frame_id, payload["checkout_ts"])
    elif (
        proto == "lsf-broker" and direction == "server_to_client"
        and ftype == FLEXLM_CRYPTO_READY and session not in state["crypto_seen"]
    ):
        identity, correlation = _identity_for(state, session)
        if identity:
            state["crypto_seen"].add(session)
            request = state["checkout_requests"].pop(session, None)
            db.flexlm_event(
                frame_id, listener, feature=None, quantity=None,
                status="FLEXLM_CHECKOUT_ATTEMPT",
                reason="encrypted session payload; identity from greeting",
                request_frame_id=request[0] if request else None,
                correlation=correlation,
                checkout_ts=request[1] if request else None,
                **_identity_fields(identity),
            )


# lmstat-style seat-query traffic: 0x3c feature query and its 0x4e/0x14 seat
# responses. Dropped entirely (both stream directions) when the monitor runs
# with filter_queries.
QUERY_FRAME_TYPES = (FLEXLM_QUERY, FLEXLM_SEATS, FLEXLM_USER_ROW)


def _is_query_frame(frame: bytes) -> bool:
    """True for LSF broker frames whose type byte marks seat-query traffic."""
    return frame[:1] == b"\x2f" and len(frame) >= 8 and frame[7] in QUERY_FRAME_TYPES


def _record_daemon_name(state: dict, port: int, payload: dict) -> None:
    """Remember the vendor daemon name from its own 0x0e hello ([client host,
    daemon name]) on its connection. Vendor/daemon naming can differ from the
    port owner's process name found via /proc, so rows are attributed from
    the wire when the daemon has announced itself, falling back to the
    process name. (lmgrd's 0x13 redirect was checked and rejected: its last
    string is a constant code, not a daemon name.)"""
    strings = payload.get("strings") or []
    if len(strings) >= 2 and strings[1]:
        state.setdefault("daemon_by_port", {})[port] = strings[1]


def _wire_listener(state: dict, listener: Listener) -> Listener:
    """Override the port owner's process-name daemon with the name the
    protocol announced for that port (0x13), when known."""
    name = state.get("daemon_by_port", {}).get(listener.port)
    if name and name != listener.daemon:
        return Listener(listener.pid, listener.port, name, listener.inode)
    return listener


def _parse_license_lines(
    db: AuditDatabase, state: dict, session: tuple, listener: Listener,
    payload: bytes,
) -> None:
    """Parse INCREMENT/FEATURE lines from the lmstat -i dump (the license
    file text rides the wire as raw payload, NOT as LSF frames) into
    license_definitions. Lines can span TCP segments: the trailing partial
    line is buffered per session until its remainder arrives."""
    if not payload:
        return
    buffers = state.setdefault("lic_buffers", {})
    text = buffers.get(session, "") + payload.decode("latin-1")
    lines = text.split("\n")
    buffers[session] = lines.pop()  # trailing partial line (or "")
    for line in lines:
        word = line.strip().split()
        if (
            len(word) >= 6 and word[0] in ("INCREMENT", "FEATURE")
            and word[5].isdigit()
        ):
            db.license_definition(
                listener, keyword=word[0], feature=word[1], vendor=word[2],
                version=word[3], expiry=word[4], seats=int(word[5]),
                line=line.rstrip("\r"))


def _observe_query_stream(
    db: AuditDatabase, listener: Listener, session: tuple, direction: str,
    segment: Segment, frames: list[bytes], state: dict,
) -> None:
    """Decode lmstat-style query traffic in memory WITHOUT storing it: note
    the queried feature (0x3c) and record only FIRST sightings of seat rows
    (0x14 carrying a checkout_id) as FLEXLM_IN_USE events, so the pollers'
    repeated re-reports stay out of the database while new/changed seats
    (with their checkout ids) are still captured.

    Seat pid attribution uses the wire-native start-epoch join (the seat's
    start_ts equals the checkout session's 0x3d client timestamp, whose own
    greeting named the pid); the latest-greeting holder is only a fallback
    when no attempt exists at that (user, host, ts). After each batch,
    checkout attempts get their feature backfilled when the seat count lines
    up 1:1."""
    debug = os.environ.get("LM_MONITOR_DEBUG")
    listener = _wire_listener(state, listener)
    if direction == "server_to_client":
        _parse_license_lines(db, state, session, listener, segment.payload)
    seat_ts_groups: set[tuple[str | None, str | None, int]] = set()
    for frame in frames:
        if not (frame[:1] == b"\x2f" and len(frame) >= 8):
            continue
        decoded = decode_flexlm_frame(frame, direction)
        if decoded is None:
            continue
        ftype, payload = decoded
        if payload is None or "proto" not in payload:
            continue
        if debug:
            print(f"[dbg] qstream t={ftype} dir={direction} "
                  f"feature={payload.get('feature')} cid={payload.get('checkout_id')} "
                  f"qfeat={state['features'].get(session)}", flush=True)
        if ftype == FLEXLM_DAEMON_HELLO and direction == "server_to_client":
            _record_daemon_name(state, listener.port, payload)
            listener = _wire_listener(state, listener)
        if ftype == FLEXLM_QUERY and direction == "client_to_server" and payload.get("feature"):
            # the new 0x3c ends the previous feature's block: its seat rows
            # form a complete observation now
            _flush_poller_details(db, state, session, listener)
            state["features"][session] = (payload["feature"], None)
        elif ftype == FLEXLM_SEATS and direction == "server_to_client":
            feature, _ = state["features"].get(session, (None, None))
            frame_id, _, _ = db.frame(
                frame, segment, listener, direction,
                {"feature": feature} if feature else None,
            )
            poller = state["recent_identity"].get(session[0])
            db.poller_summary(
                frame_id, listener, feature=feature, in_use=payload.get("in_use"),
                issued=payload.get("issued"), report_ts=payload.get("report_ts"),
                request_frame_id=None,
                correlation="MATCHED_FLEXLM_QUERY" if feature else "NO_FLEXLM_QUERY",
                poller_user=poller[0] if poller else None,
                poller_pid=poller[2] if poller else None,
            )
        elif (
            ftype == FLEXLM_USER_ROW and direction == "server_to_client"
            and payload.get("checkout_id") is not None
        ):
            feature = state["features"].get(session, (None, None))[0]
            user, host = payload.get("user"), payload.get("host")
            checkout_id = payload["checkout_id"]
            poller = state["recent_identity"].get(session[0])
            start_ts = payload.get("start_ts")
            if start_ts is not None:
                # Name the attempts (and NULL-feature seats) for this second
                # before matching, so the feature set below sees fresh names.
                db.backfill_attempt_features(user, host, start_ts)
            pid, tty, platform, seat_features, match = _seat_pid(state, db, user, host, start_ts)
            if start_ts is not None:
                seat_ts_groups.add((user, host, start_ts))
            if feature:
                # every observation feeds poller_details, seat_seen dedup
                # only governs the license_events write below
                _accumulate_poller_detail(
                    state, session, feature, user, host, payload.get("tty"),
                    payload.get("version"), checkout_id, start_ts, pid, match,
                )
            if feature is None or db.seat_seen(feature, user, host, checkout_id):
                continue
            frame_id, _, _ = db.frame(frame, segment, listener, direction, {"feature": feature})
            db.flexlm_event(
                frame_id, listener, feature=seat_features or feature, client_user=user,
                client_host=host, quantity=1, status="FLEXLM_IN_USE",
                reason=None, request_frame_id=None,
                correlation=match,
                client_pid=pid, client_tty=tty, client_platform=platform,
                poller_user=poller[0] if poller else None,
                poller_pid=poller[2] if poller else None,
                checkout_id=checkout_id, checkout_ts=start_ts,
            )
    for user, host, ts in seat_ts_groups:
        db.backfill_attempt_features(user, host, ts)


class _SockFilter(ctypes.Structure):
    _fields_ = [
        ("code", ctypes.c_uint16), ("jt", ctypes.c_uint8),
        ("jf", ctypes.c_uint8), ("k", ctypes.c_uint32),
    ]


class _SockFprog(ctypes.Structure):
    _fields_ = [("len", ctypes.c_uint16), ("filter", ctypes.POINTER(_SockFilter))]


def _bpf_instructions(ports: Iterable[int]) -> list[tuple[int, int, int, int]]:
    """Classic BPF program admitting only IPv4 TCP segments to/from ports.

    Without it the socket sees every packet on the interface (htons(0x0003));
    on ens1f0 that is mostly unrelated traffic Python cannot drain fast
    enough, so the kernel drops ~58% of packets. With the filter those
    packets are discarded before they even reach the socket queue.

    Layout (n ports): a 3-instruction prologue (ethertype -> IHL into X),
    a 4-instruction src/dst block per port, then reject(0) and accept(64 KiB)
    returns. With no ports the program rejects everything.
    """
    ordered = sorted({int(port) for port in ports})
    n = len(ordered)
    reject_idx = 3 + 4 * n
    accept_idx = reject_idx + 1
    insns: list[tuple[int, int, int, int]] = [
        (0x28, 0, 0, 12),                    # ldh [12]: ethertype
        (0x15, 0, reject_idx - 2, 0x0800),  # jeq ipv4, else reject
        (0xB1, 0, 0, 14),                    # ldx 4*([14]&0xf): IHL bytes in X
    ]
    for i, port in enumerate(ordered):
        base = 3 + 4 * i
        insns += [
            (0x48, 0, 0, 14),               # ldh [X+14]: TCP src port
            (0x15, accept_idx - (base + 2), 0, port),
            (0x48, 0, 0, 16),               # ldh [X+16]: TCP dst port
            (0x15, accept_idx - (base + 4), 0, port),
        ]
    insns += [
        (0x06, 0, 0, 0),                    # reject: drop packet
        (0x06, 0, 0, 0x40000),             # accept: keep whole packet
    ]
    return insns


def attach_bpf(sock: socket.socket, ports: Iterable[int]) -> None:
    """Attach (or atomically replace) the kernel-side capture filter."""
    insns = _bpf_instructions(ports)
    array = (_SockFilter * len(insns))(
        *(_SockFilter(code, jt, jf, k) for code, jt, jf, k in insns))
    prog = _SockFprog(len(insns), array)
    sock.setsockopt(socket.SOL_SOCKET, SO_ATTACH_FILTER, prog)


def _handle_packet(
    db: AuditDatabase, raw: bytes, address: tuple, channel: dict,
    listeners: dict[int, Listener], state: dict,
) -> None:
    """Decode one captured packet for its channel.

    Channel modes: "full" decodes and stores everything; "legacy-filter"
    marks lmstat-style query streams and records only their poller
    summaries/details plus first-sighting seat events; "drop" fully excludes
    query streams (external pollers leave no trace); "observe-all" treats
    every stream as the self-query channel (dedicated loopback socket).
    """
    iface = channel["iface"]
    mode = channel["mode"]
    streams = channel["streams"]
    requests = channel["requests"]
    query_streams = channel["query_streams"]
    if address[2] not in (PACKET_HOST, PACKET_OUTGOING):
        return
    if iface == "lo" and address[2] != PACKET_OUTGOING:
        return  # loopback duplicates outgoing/incoming copies
    segment = parse_ipv4_tcp(raw)
    if segment is None:
        return
    listener = listeners.get(segment.dst_port)
    direction = "client_to_server"
    if listener is None:
        listener = listeners.get(segment.src_port)
        direction = "server_to_client"
    if listener is None:
        return
    key = (segment.src_ip, segment.src_port, segment.dst_ip, segment.dst_port)
    rkey = (segment.dst_ip, segment.dst_port, segment.src_ip, segment.src_port)
    if mode == "observe-all":
        stream = streams.setdefault(key, Stream())
        session = key if direction == "client_to_server" else rkey
        frames = stream.feed(segment)
        if len(stream.pending) >= PENDING_STALL_LIMIT:
            stream = streams[key] = Stream()  # resync after tap loss
        _observe_query_stream(
            db, listener, session, direction, segment, frames, state,
        )
        if segment.fin or segment.rst:
            _flush_poller_details(db, state, session, listener)
            streams.pop(key, None)
            state["features"].pop(session, None)
            state.get("lic_buffers", {}).pop(session, None)
        db.flush()
        return
    if segment.syn:
        streams[key] = Stream()
        query_streams.discard(key)
        query_streams.discard(rkey)
    stream = streams.setdefault(key, Stream())
    session = key if direction == "client_to_server" else rkey
    if mode == "drop" and key in query_streams:
        streams.pop(key, None)  # external poller: not even buffered
        return
    if mode == "legacy-filter" and key in query_streams:
        frames = stream.feed(segment)
        if len(stream.pending) >= PENDING_STALL_LIMIT:
            stream = streams[key] = Stream()  # resync after tap loss
        _observe_query_stream(
            db, listener, session, direction, segment, frames, state,
        )
        if segment.fin or segment.rst:
            _flush_poller_details(db, state, session, listener)
            streams.pop(key, None)
            state["features"].pop(session, None)
            state.get("lic_buffers", {}).pop(session, None)
        db.flush()
        return
    if segment.syn and direction == "client_to_server":
        requests.pop(session, None)
    frames = stream.feed(segment)
    if len(stream.pending) >= PENDING_STALL_LIMIT:
        stream = streams[key] = Stream()  # resync after tap loss
    if mode in ("legacy-filter", "drop") and any(_is_query_frame(frame) for frame in frames):
        # Mark the stream (both directions) as lmstat-style query traffic –
        # short-lived query connections send exactly one 0x3c, first.
        query_streams.add(key)
        query_streams.add(rkey)
        streams.pop(key, None)
        if mode == "drop":
            return  # fully exclude external pollers
        _observe_query_stream(
            db, listener, session, direction, segment, frames, state,
        )
        if segment.fin or segment.rst:
            _flush_poller_details(db, state, session, listener)
            state["features"].pop(session, None)
        db.flush()
        return
    if segment.payload:
        db.segment(segment, listener, direction)
        if not frames and (
            session in state["crypto_seen"]
            or stream.mode in (None, "sim1")
        ):
            # Encrypted payload that never decodes into frames:
            # session keepalive/heartbeat traffic on an
            # established crypto session (or a stream captured
            # mid-session). Aggregated per connection.
            identity, _ = _identity_for(state, session)
            beat_feature = state["lookups"].get(session, (None, None))[0]
            if beat_feature is None:
                own = state["identities"].get(session)
                if own and own[2]:
                    # pid-accurate: this stream's own greeting pid
                    beat_feature = state["pid_feature"].get(
                        (session[0], own[2])
                    )
            db.heartbeat(session, listener, identity, beat_feature, segment)
    for frame in frames:
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
        _flush_poller_details(db, state, session, listener)
        state["features"].pop(session, None)
        state["identities"].pop(session, None)
        state["lookups"].pop(session, None)
        state["session_ids"].pop(session, None)
        state["checkout_requests"].pop(session, None)
        state["crypto_seen"].discard(session)
    db.flush()


def run(
    manager_pids: list[int], db_path: str, interface: str = "lo",
    ready_file: str | None = None,
    filter_queries: bool = False, self_query: bool = False,
    lmstat_timeout: float = LMSTAT_TIMEOUT_S,
    discovery: bool = False,
) -> None:
    """Attach without modifying lmgrd. Require root or CAP_NET_RAW for AF_PACKET.

    Multiple lmgrd trees on one host are supported: every --pid gets
    discovered separately and the port -> listener maps are merged (a TCP
    port has exactly one owning tree, so per-service attribution rides the
    port). A kernel BPF filter admits only IPv4/TCP segments to or from the
    discovered license ports, so interface noise never reaches userspace.

    With discovery (monitor CLI --discovery auto) the tree set is dynamic:
    the host is re-scanned for lmgrd processes on every refresh tick, new
    trees are adopted once they hold a listening socket, vanished trees are
    dropped (rolling back any in-flight self-query dump) instead of exiting,
    and the monitor only stops on signal. --pid trees are pinned in addition
    to the scan. Without it the tree set is exactly the --pid list and any
    tree vanishing still stops the monitor (fail closed).

    With self_query, the loop spawns `lmutil lmstat -c PORT@127.0.0.1 -a -i`
    for EVERY service (its own lmgrd port) every SELF_QUERY_INTERVAL_S and
    captures their loopback traffic on a dedicated socket ("observe-all");
    poller_summaries/poller_details then come from our own deterministic
    cadence, while the --iface socket drops external pollers' query streams
    entirely ("drop"). A dump that exceeds lmstat_timeout is killed and its
    partial rows rolled back (all-or-nothing dumps); the failure lands in
    self_query_errors. Without self_query the --iface socket behaves as
    before: filter_queries marks query streams and records their
    summaries/details, otherwise everything is decoded.
    """
    seeds = list(manager_pids)
    trees: set[int] = set(seeds)
    if discovery:
        trees |= set(discover_managers())

    def merged_listeners() -> dict[int, Listener]:
        """Re-discover every tree and merge (a TCP port has one owner, so
        first-wins on the impossible collision)."""
        merged: dict[int, Listener] = {}
        for pid in sorted(trees):
            for port, listener in discover(pid).items():
                merged.setdefault(port, listener)
        return merged

    if discovery and not trees:
        print("[monitor] no lmgrd trees found yet; waiting for one to appear",
              flush=True)
    query_windows: dict = {}  # manager_pid -> in-flight lmutil dump window

    def drop_tree(pid: int, reason: str) -> None:
        """Retire a tree: stop monitoring it and roll back its in-flight
        self-query dump via the regular reap path."""
        trees.discard(pid)
        print(f"[monitor] tree {pid} dropped ({reason})", flush=True)
        window = query_windows.get(pid)
        if window is not None and window["kill_at"] is None:
            window["elapsed"] = time.monotonic() - window["spawn"]
            window["kill_at"] = True
            window["reason"] = reason

    def current_listeners() -> dict[int, Listener]:
        """Listener map for the live tree set; in discovery mode a tree that
        dies between scans is dropped here instead of stopping the monitor."""
        if not discovery:
            return merged_listeners()
        while True:
            try:
                return merged_listeners()
            except ProcessLookupError as exc:
                drop_tree(exc.args[0], "lmgrd process vanished")

    def refresh_trees() -> None:
        """Discovery mode only: adopt new lmgrd trees (deferred until they
        hold a listening socket) and drop vanished ones."""
        found = set(discover_managers())
        found |= {pid for pid in seeds if Path(f"/proc/{pid}").exists()}
        for pid in sorted(found - trees):
            try:
                tree = discover(pid)
            except ProcessLookupError:
                continue  # died between scan and admission; retry next tick
            if pid not in {listener.pid for listener in tree.values()}:
                continue  # not listening yet (lmgrd still starting up)
            trees.add(pid)
            print(f"[monitor] adopted lmgrd tree pid={pid}", flush=True)
        for pid in sorted(trees - found):
            drop_tree(pid, "lmgrd process vanished")

    if discovery:
        refresh_trees()
    listeners = current_listeners()
    if not discovery:
        for manager_pid in manager_pids:
            tree = discover(manager_pid)
            if manager_pid not in {listener.pid for listener in tree.values()}:
                raise RuntimeError(f"manager PID {manager_pid} has no listening TCP socket")

    def open_channel(iface: str, mode: str) -> dict:
        sock = socket.socket(socket.AF_PACKET, socket.SOCK_RAW, socket.htons(0x0003))
        sock.bind((iface, 0))
        try:
            sock.setsockopt(socket.SOL_SOCKET, socket.SO_RCVBUF, 8 << 20)
        except OSError:
            pass  # best effort on busy interfaces; see lic_capture_server.py
        sock.settimeout(0.25)
        return {"sock": sock, "iface": iface, "mode": mode,
                "streams": {}, "requests": {}, "query_streams": set()}

    if self_query and interface != "lo":
        ext_mode = "drop"
    elif self_query or filter_queries:
        # single-socket loopback mode: our own self-query traffic must be
        # observed, so query streams are marked and recorded, not dropped
        ext_mode = "legacy-filter"
    else:
        ext_mode = "full"
    channels = [open_channel(interface, ext_mode)]
    if self_query and interface != "lo":
        # our own lmstat talks to a local IP, which Linux always routes via
        # loopback – a dedicated socket keeps the self-query channel separate
        channels.append(open_channel("lo", "observe-all"))
    try:
        attached_ports: frozenset[int] | None = None
        try:
            for channel in channels:
                attach_bpf(channel["sock"], listeners)
            attached_ports = frozenset(listeners)
        except OSError:
            pass  # best effort: unfiltered capture is noisier but works
        db = AuditDatabase(db_path, manager_pids[0] if manager_pids
                           else (min(trees) if trees else 0))
    except Exception:
        for channel in channels:
            channel["sock"].close()
        raise
    state = {
        "features": {}, "identities": {}, "recent_identity": {},
        "lookups": {}, "session_ids": {}, "holders": {}, "pid_feature": {},
        "crypto_seen": set(), "checkout_requests": {}, "poller_details": {},
        "daemon_by_port": {}, "lic_buffers": {},
    }
    last_refresh = 0.0
    last_prune = 0.0
    last_stats = 0.0
    last_self_query = 0.0
    # Linux constants Python's socket module does not export
    # (PACKET_STATISTICS = 6, and reading it resets the kernel counters)
    packet_stats_opt = 6
    sol_packet = getattr(socket, "SOL_PACKET", 263)
    try:
        db.listeners(listeners)
        if ready_file:
            Path(ready_file).write_text(
                ",".join(str(p) for p in manager_pids) or "auto",
                encoding="utf-8")
        while True:
            if time.monotonic() - last_refresh >= 0.5:
                if discovery:
                    refresh_trees()
                listeners = current_listeners()
                db.listeners(listeners)
                if frozenset(listeners) != attached_ports:
                    try:
                        for channel in channels:
                            attach_bpf(channel["sock"], listeners)
                        attached_ports = frozenset(listeners)
                    except OSError:
                        pass
                last_refresh = time.monotonic()
            if time.monotonic() - last_prune >= PRUNE_INTERVAL_S:
                db.prune()
                last_prune = time.monotonic()
            if time.monotonic() - last_stats >= 5.0:
                # kernel resets the counters on read: each sample holds
                # the packets/drops since the previous one, so capture
                # loss is measurable, not just suspected
                try:
                    packets, drops = struct.unpack(
                        "II", channels[0]["sock"].getsockopt(
                            sol_packet, packet_stats_opt, 8))
                    db.capture_stats(packets, drops)
                except OSError:
                    pass
                last_stats = time.monotonic()
            if self_query:
                # per-service dump lifecycle, checked every tick: reap
                # finished pollers, kill + roll back dumps that exceed the
                # timeout (all-or-nothing: a failed dump leaves no rows),
                # and log the failure to self_query_errors
                for manager_pid in list(query_windows):
                    window = query_windows[manager_pid]
                    if window["kill_at"] is not None:
                        rolled = db.rollback_partial_dump(
                            manager_pid, window["ports"], window["spawn_wall"])
                        window["reason"] += f"; rolled back {rolled} partial rows"
                        db.self_query_error(
                            manager_pid, window["mgr_port"],
                            window["elapsed"], window["reason"])
                        del query_windows[manager_pid]
                    elif window["proc"].poll() is not None:
                        del query_windows[manager_pid]  # finished in time
                    elif time.monotonic() - window["spawn"] >= lmstat_timeout:
                        window["elapsed"] = time.monotonic() - window["spawn"]
                        try:
                            window["proc"].kill()
                        except OSError:
                            pass
                        window["kill_at"] = True
                        window["reason"] = (
                            f"timeout: lmstat exceeded {lmstat_timeout:g}s")
                if time.monotonic() - last_self_query >= SELF_QUERY_INTERVAL_S:
                    for manager_pid in sorted(trees):
                        if manager_pid in query_windows:
                            continue  # previous dump still in flight
                        mgr_port = next(
                            (port for port, listener in listeners.items()
                             if listener.pid == manager_pid), None)
                        if mgr_port is None:
                            continue
                        ports = [port for port, listener in listeners.items()
                                 if listener.manager_pid == manager_pid]
                        try:
                            proc = subprocess.Popen(
                                [LMUTIL_PATH, "lmstat", "-c", f"{mgr_port}@127.0.0.1",
                                 "-a", "-i"],
                                stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                                stderr=subprocess.DEVNULL,
                            )
                            query_windows[manager_pid] = {
                                "proc": proc, "spawn": time.monotonic(),
                                "spawn_wall": _now(), "mgr_port": mgr_port,
                                "ports": ports, "kill_at": None,
                                "elapsed": 0.0, "reason": "",
                            }
                            if os.environ.get("LM_MONITOR_DEBUG"):
                                print(f"[dbg] self-query spawn mgr_port={mgr_port} "
                                      f"pid={proc.pid}", flush=True)
                        except OSError as exc:
                            db.self_query_error(
                                manager_pid, mgr_port, 0.0, f"spawn failed: {exc}")
                    last_self_query = time.monotonic()
            ready, _, _ = select.select(
                [channel["sock"] for channel in channels], [], [], 0.25)
            for channel in channels:
                if channel["sock"] not in ready:
                    continue
                try:
                    raw, address = channel["sock"].recvfrom(65535)
                except TimeoutError:
                    continue
                _handle_packet(db, raw, address, channel, listeners, state)
    finally:
        for channel in channels:
            channel["sock"].close()
        db.flush()
        db.close()
