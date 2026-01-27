from __future__ import annotations

import sqlite3


def init_db() -> sqlite3.Connection:
    conn = sqlite3.connect(":memory:")
    cursor = conn.cursor()
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
            first_seen_at text not null,
            response_json text not null
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
    conn.commit()
    return conn
