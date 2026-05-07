from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from pathlib import Path
from threading import RLock


@dataclass(frozen=True)
class WorkloadEvent:
    event_time: str
    user: str
    action: str
    feature: str | None
    status: str | None
    reason: str | None
    checkout_id: str | None


class SQLiteSink:
    def __init__(self, path: Path | str) -> None:
        self.path = Path(path)
        self.conn: sqlite3.Connection | None = None
        self._lock = RLock()

    def initialize(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.conn = sqlite3.connect(self.path, check_same_thread=False)
        self.conn.execute(
            "create table if not exists samples (sample_id integer primary key autoincrement, sampled_at text not null, raw_output text not null)"
        )
        self.conn.execute(
            "create table if not exists feature_samples (sample_id integer not null, feature text not null, total integer not null, in_use integer not null, queued integer not null, expired integer not null)"
        )
        self.conn.execute(
            "create table if not exists checkout_samples (sample_id integer not null, feature text not null, user text, host text, pid integer, checkout_id text, status text, granted_at text)"
        )
        self.conn.execute(
            "create table if not exists workload_events (event_id integer primary key autoincrement, event_time text not null, user text not null, action text not null, feature text, status text, reason text, checkout_id text)"
        )
        self.conn.commit()

    def insert_sample(self, sampled_at: str, raw_output: str, features: list[dict], checkouts: list[dict]) -> int:
        with self._lock:
            conn = self._conn()
            cursor = conn.execute("insert into samples (sampled_at, raw_output) values (?, ?)", (sampled_at, raw_output))
            sample_id = int(cursor.lastrowid)
            for feature in features:
                conn.execute(
                    "insert into feature_samples values (?, ?, ?, ?, ?, ?)",
                    (
                        sample_id,
                        feature["feature"],
                        int(feature["total"]),
                        int(feature["in_use"]),
                        int(feature["queued"]),
                        1 if feature["expired"] else 0,
                    ),
                )
            for checkout in checkouts:
                conn.execute(
                    "insert into checkout_samples values (?, ?, ?, ?, ?, ?, ?, ?)",
                    (
                        sample_id,
                        checkout.get("feature"),
                        checkout.get("user"),
                        checkout.get("host"),
                        checkout.get("pid"),
                        checkout.get("checkout_id"),
                        checkout.get("status"),
                        checkout.get("granted_at"),
                    ),
                )
            conn.commit()
            return sample_id

    def insert_event(self, event: WorkloadEvent) -> None:
        with self._lock:
            self._conn().execute(
                "insert into workload_events (event_time, user, action, feature, status, reason, checkout_id) values (?, ?, ?, ?, ?, ?, ?)",
                (event.event_time, event.user, event.action, event.feature, event.status, event.reason, event.checkout_id),
            )
            self._conn().commit()

    def close(self) -> None:
        if self.conn is not None:
            self.conn.close()
            self.conn = None

    def _conn(self) -> sqlite3.Connection:
        if self.conn is None:
            raise RuntimeError("SQLiteSink is not initialized")
        return self.conn
