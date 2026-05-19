from __future__ import annotations

import json
import sqlite3
from datetime import date, datetime
from uuid import uuid4

from .models import CheckoutRecord, FeatureDef, LicenseConfig


class SimulatorStore:
    def __init__(self, conn: sqlite3.Connection) -> None:
        self.conn = conn
        self.conn.row_factory = sqlite3.Row

    @classmethod
    def from_license(cls, config: LicenseConfig) -> "SimulatorStore":
        conn = sqlite3.connect(":memory:", check_same_thread=False)
        store = cls(conn)
        store.init_schema()
        for feature in config.features.values():
            store.insert_feature(feature)
        return store

    def init_schema(self) -> None:
        cursor = self.conn.cursor()
        cursor.execute(
            """
            create table features (
                name text primary key,
                daemon text not null,
                total integer not null,
                in_use integer not null,
                expires_at text
            )
            """
        )
        cursor.execute(
            """
            create table checkouts (
                checkout_id text primary key,
                feature text not null,
                daemon text not null,
                user text not null,
                host text not null,
                pid integer not null,
                status text not null,
                requested_at text not null,
                granted_at text,
                returned_at text
            )
            """
        )
        cursor.execute(
            """
            create table queue (
                queue_id text primary key,
                checkout_id text not null,
                feature text not null,
                daemon text not null,
                user text not null,
                host text not null,
                pid integer not null,
                requested_at text not null,
                position integer not null,
                status text not null
            )
            """
        )
        cursor.execute(
            """
            create table req_dedupe (
                request_id text primary key,
                operation text not null,
                response_json text not null,
                first_seen_at text not null
            )
            """
        )
        cursor.execute(
            """
            create table events (
                event_id text primary key,
                event_time text not null,
                type text not null,
                payload_json text not null
            )
            """
        )
        self.conn.commit()

    def insert_feature(self, feature: FeatureDef) -> None:
        self.conn.execute(
            "insert into features values (?, ?, ?, 0, ?)",
            (
                feature.name,
                feature.daemon,
                feature.total,
                feature.expires_at.isoformat() if feature.expires_at else None,
            ),
        )
        self.conn.commit()

    def get_feature(self, feature: str) -> sqlite3.Row | None:
        return self.conn.execute("select * from features where name = ?", (feature,)).fetchone()

    def get_checkout(self, checkout_id: str) -> CheckoutRecord | None:
        row = self.conn.execute(
            "select * from checkouts where checkout_id = ?", (checkout_id,)
        ).fetchone()
        if row is None:
            return None
        return _record_from_row(row)

    def queue_count(self, feature: str, daemon: str) -> int:
        row = self.conn.execute(
            "select count(*) as count from queue where feature = ? and daemon = ? and status = 'QUEUED'",
            (feature, daemon),
        ).fetchone()
        return int(row["count"])

    def next_queue_position(self, feature: str, daemon: str) -> int:
        row = self.conn.execute(
            "select coalesce(max(position), 0) + 1 as position from queue where feature = ? and daemon = ?",
            (feature, daemon),
        ).fetchone()
        return int(row["position"])

    def add_checkout(
        self,
        checkout_id: str,
        feature: str,
        daemon: str,
        user: str,
        host: str,
        pid: int,
        status: str,
        requested_at: datetime,
        granted_at: datetime | None,
    ) -> None:
        self.conn.execute(
            "insert into checkouts values (?, ?, ?, ?, ?, ?, ?, ?, ?, null)",
            (
                checkout_id,
                feature,
                daemon,
                user,
                host,
                pid,
                status,
                requested_at.isoformat(),
                granted_at.isoformat() if granted_at else None,
            ),
        )
        if status == "GRANTED":
            self.conn.execute("update features set in_use = in_use + 1 where name = ?", (feature,))
        self.conn.commit()

    def add_queued_checkout(
        self,
        checkout_id: str,
        feature: str,
        daemon: str,
        user: str,
        host: str,
        pid: int,
        requested_at: datetime,
        position: int,
    ) -> None:
        with self.conn:
            self.conn.execute(
                "insert into checkouts values (?, ?, ?, ?, ?, ?, 'QUEUED', ?, null, null)",
                (
                    checkout_id,
                    feature,
                    daemon,
                    user,
                    host,
                    pid,
                    requested_at.isoformat(),
                ),
            )
            self.conn.execute(
                "insert into queue values (?, ?, ?, ?, ?, ?, ?, ?, ?, 'QUEUED')",
                (
                    str(uuid4()),
                    checkout_id,
                    feature,
                    daemon,
                    user,
                    host,
                    pid,
                    requested_at.isoformat(),
                    position,
                ),
            )

    def add_queue(self, checkout_id: str, feature: str, daemon: str, user: str, host: str, pid: int, requested_at: datetime, position: int) -> None:
        self.conn.execute(
            "insert into queue values (?, ?, ?, ?, ?, ?, ?, ?, ?, 'QUEUED')",
            (str(uuid4()), checkout_id, feature, daemon, user, host, pid, requested_at.isoformat(), position),
        )
        self.conn.commit()

    def mark_returned(self, record: CheckoutRecord, returned_at: datetime) -> None:
        self.conn.execute(
            "update checkouts set status = 'RETURNED', returned_at = ? where checkout_id = ?",
            (returned_at.isoformat(), record.checkout_id),
        )
        self.conn.execute(
            "update features set in_use = max(in_use - 1, 0) where name = ?", (record.feature,)
        )
        self.conn.commit()

    def return_queued(self, record: CheckoutRecord, returned_at: datetime) -> None:
        with self.conn:
            self.conn.execute(
                "update checkouts set status = 'RETURNED', returned_at = ? where checkout_id = ?",
                (returned_at.isoformat(), record.checkout_id),
            )
            self.conn.execute("delete from queue where checkout_id = ?", (record.checkout_id,))

    def return_granted_and_promote_next(
        self, record: CheckoutRecord, returned_at: datetime
    ) -> CheckoutRecord | None:
        with self.conn:
            self.conn.execute(
                "update checkouts set status = 'RETURNED', returned_at = ? where checkout_id = ?",
                (returned_at.isoformat(), record.checkout_id),
            )
            self.conn.execute(
                "update features set in_use = max(in_use - 1, 0) where name = ?",
                (record.feature,),
            )
            row = self.conn.execute(
                "select * from queue where feature = ? and daemon = ? and status = 'QUEUED' order by position limit 1",
                (record.feature, record.daemon),
            ).fetchone()
            if row is None:
                return None
            self.conn.execute("delete from queue where queue_id = ?", (row["queue_id"],))
            self.conn.execute(
                "update checkouts set status = 'GRANTED', granted_at = ? where checkout_id = ?",
                (returned_at.isoformat(), row["checkout_id"]),
            )
            self.conn.execute(
                "update features set in_use = in_use + 1 where name = ?", (record.feature,)
            )
        checkout = self.get_checkout(row["checkout_id"])
        if checkout is None:
            raise RuntimeError("Queued checkout missing")
        return checkout

    def grant_next_queued(self, feature: str, daemon: str, granted_at: datetime) -> CheckoutRecord | None:
        row = self.conn.execute(
            "select * from queue where feature = ? and daemon = ? and status = 'QUEUED' order by position limit 1",
            (feature, daemon),
        ).fetchone()
        if row is None:
            return None
        self.conn.execute("delete from queue where queue_id = ?", (row["queue_id"],))
        self.conn.execute(
            "update checkouts set status = 'GRANTED', granted_at = ? where checkout_id = ?",
            (granted_at.isoformat(), row["checkout_id"]),
        )
        self.conn.execute("update features set in_use = in_use + 1 where name = ?", (feature,))
        self.conn.commit()
        checkout = self.get_checkout(row["checkout_id"])
        if checkout is None:
            raise RuntimeError("Queued checkout missing")
        return checkout

    def status_rows(self) -> list[dict]:
        rows = self.conn.execute("select * from features order by name").fetchall()
        items = []
        today = date.today()
        for row in rows:
            expires_at = date.fromisoformat(row["expires_at"]) if row["expires_at"] else None
            items.append(
                {
                    "feature": row["name"],
                    "daemon": row["daemon"],
                    "total": row["total"],
                    "in_use": row["in_use"],
                    "queued": self.queue_count(row["name"], row["daemon"]),
                    "expired": bool(expires_at and expires_at < today),
                    "expires_at": expires_at.isoformat() if expires_at else None,
                }
            )
        return items

    def debug_checkouts(self, limit: int = 100, feature: str | None = None, daemon: str | None = None, status: str | None = None) -> list[dict]:
        query = "select * from checkouts where 1 = 1"
        params: list[object] = []
        if feature:
            query += " and feature = ?"
            params.append(feature)
        if daemon:
            query += " and daemon = ?"
            params.append(daemon)
        if status:
            query += " and status = ?"
            params.append(status)
        query += " order by requested_at limit ?"
        params.append(min(limit, 500))
        return [_row_to_dict(row) for row in self.conn.execute(query, params).fetchall()]

    def debug_queue(self, limit: int = 100, feature: str | None = None, daemon: str | None = None) -> list[dict]:
        query = "select * from queue where status = 'QUEUED'"
        params: list[object] = []
        if feature:
            query += " and feature = ?"
            params.append(feature)
        if daemon:
            query += " and daemon = ?"
            params.append(daemon)
        query += " order by feature, daemon, position limit ?"
        params.append(min(limit, 500))
        return [_row_to_dict(row) for row in self.conn.execute(query, params).fetchall()]

    def counters(self) -> dict[str, int]:
        granted = self.conn.execute("select count(*) as count from checkouts where status = 'GRANTED'").fetchone()["count"]
        returned = self.conn.execute("select count(*) as count from checkouts where status = 'RETURNED'").fetchone()["count"]
        queued = self.conn.execute("select count(*) as count from queue where status = 'QUEUED'").fetchone()["count"]
        rejected = self.conn.execute("select count(*) as count from events where type like 'REJECTED%'").fetchone()["count"]
        return {"granted": granted, "queued": queued, "rejected": rejected, "returned": returned}

    def cache_get(self, request_id: str, operation: str) -> dict | None:
        row = self.conn.execute(
            "select operation, response_json from req_dedupe where request_id = ?", (request_id,)
        ).fetchone()
        if row is None:
            return None
        if row["operation"] != operation:
            raise ValueError("INVALID_REQUEST_ID")
        return json.loads(row["response_json"])

    def cache_set(self, request_id: str | None, operation: str, response: dict, now: datetime) -> None:
        if not request_id:
            return
        self.conn.execute(
            "insert into req_dedupe values (?, ?, ?, ?)",
            (request_id, operation, json.dumps(response), now.isoformat()),
        )
        self.conn.commit()

    def event(self, event_type: str, payload: dict, now: datetime) -> None:
        self.conn.execute(
            "insert into events values (?, ?, ?, ?)",
            (str(uuid4()), now.isoformat(), event_type, json.dumps(payload)),
        )
        self.conn.commit()


def _record_from_row(row: sqlite3.Row) -> CheckoutRecord:
    return CheckoutRecord(
        checkout_id=row["checkout_id"],
        feature=row["feature"],
        daemon=row["daemon"],
        user=row["user"],
        host=row["host"],
        pid=row["pid"],
        status=row["status"],
        requested_at=datetime.fromisoformat(row["requested_at"]),
        granted_at=datetime.fromisoformat(row["granted_at"]) if row["granted_at"] else None,
        returned_at=datetime.fromisoformat(row["returned_at"]) if row["returned_at"] else None,
    )


def _row_to_dict(row: sqlite3.Row) -> dict:
    return {key: row[key] for key in row.keys()}
