from __future__ import annotations

from datetime import UTC, date, datetime
from threading import RLock
from uuid import uuid4

from .log_writer import MemoryLogWriter
from .models import CheckoutResult
from .store import SimulatorStore


class SimulatorService:
    def __init__(
        self,
        store: SimulatorStore,
        log_writer: MemoryLogWriter,
        server_name: str,
        port: int,
        config_hash: str,
        started_at: datetime | None = None,
    ) -> None:
        self.store = store
        self.log_writer = log_writer
        self.server_name = server_name
        self.port = port
        self.config_hash = config_hash
        self.started_at = started_at or datetime.now(UTC)
        self._lock = RLock()

    def health(self) -> dict:
        features = self.store.status_rows()
        return {
            "protocol_version": 1,
            "server_time": _server_time(),
            "request_id": str(uuid4()),
            "server_name": self.server_name,
            "port": self.port,
            "feature_count": len(features),
            "daemons": sorted({item["daemon"] for item in features}),
        }

    def status(self) -> dict:
        return {
            "protocol_version": 1,
            "server_time": _server_time(),
            "request_id": str(uuid4()),
            "server_name": self.server_name,
            "port": self.port,
            "features": self.store.status_rows(),
            "uptime_seconds": int((datetime.now(UTC) - self.started_at).total_seconds()),
            "config_hash": self.config_hash,
            "counters": self.store.counters(),
        }

    def checkout(self, feature_name: str, user: str, host: str, pid: int, request_id: str | None = None) -> CheckoutResult:
        with self._lock:
            now = datetime.now(UTC)
            if request_id:
                cached = self.store.cache_get(request_id, "checkout")
                if cached:
                    return CheckoutResult(**cached)
            feature = self.store.get_feature(feature_name)
            if feature is None:
                result = CheckoutResult("REJECTED", "UNKNOWN_FEATURE", None, feature_name, "default", 0, 0, 0)
                self.store.event("REJECTED_CHECKOUT", result.__dict__, now)
                self.store.cache_set(request_id, "checkout", result.__dict__, now)
                self.log_writer.denied("default", feature_name, user, host, "UNKNOWN_FEATURE")
                return result

            expires_at = date.fromisoformat(feature["expires_at"]) if feature["expires_at"] else None
            if expires_at and expires_at < date.today():
                result = CheckoutResult(
                    "REJECTED",
                    "FEATURE_EXPIRED",
                    None,
                    feature_name,
                    feature["daemon"],
                    feature["total"],
                    feature["in_use"],
                    self.store.queue_count(feature_name, feature["daemon"]),
                )
                self.store.event("REJECTED_CHECKOUT", result.__dict__, now)
                self.store.cache_set(request_id, "checkout", result.__dict__, now)
                self.log_writer.denied(feature["daemon"], feature_name, user, host, "FEATURE_EXPIRED")
                return result

            if feature["in_use"] < feature["total"]:
                checkout_id = str(uuid4())
                self.store.add_checkout(checkout_id, feature_name, feature["daemon"], user, host, pid, "GRANTED", now, now)
                current = self.store.get_feature(feature_name)
                result = CheckoutResult(
                    "GRANTED",
                    None,
                    checkout_id,
                    feature_name,
                    feature["daemon"],
                    feature["total"],
                    current["in_use"],
                    self.store.queue_count(feature_name, feature["daemon"]),
                )
                self.store.event("GRANTED_CHECKOUT", result.__dict__, now)
                self.store.cache_set(request_id, "checkout", result.__dict__, now)
                self.log_writer.checkout_granted(feature["daemon"], feature_name, user, host, pid, checkout_id)
                return result

            queued_count = self.store.queue_count(feature_name, feature["daemon"])
            if queued_count >= 100:
                result = CheckoutResult(
                    "REJECTED", "QUEUE_FULL", None, feature_name, feature["daemon"], feature["total"], feature["in_use"], queued_count
                )
                self.store.event("REJECTED_CHECKOUT", result.__dict__, now)
                self.store.cache_set(request_id, "checkout", result.__dict__, now)
                self.log_writer.denied(feature["daemon"], feature_name, user, host, "QUEUE_FULL")
                return result

            checkout_id = str(uuid4())
            position = self.store.next_queue_position(feature_name, feature["daemon"])
            self.store.add_checkout(checkout_id, feature_name, feature["daemon"], user, host, pid, "QUEUED", now, None)
            self.store.add_queue(checkout_id, feature_name, feature["daemon"], user, host, pid, now, position)
            result = CheckoutResult(
                "QUEUED", None, checkout_id, feature_name, feature["daemon"], feature["total"], feature["in_use"], queued_count + 1
            )
            self.store.event("QUEUED_CHECKOUT", result.__dict__, now)
            self.store.cache_set(request_id, "checkout", result.__dict__, now)
            self.log_writer.queued(feature["daemon"], feature_name, user, host, checkout_id, position)
            return result

    def return_checkout(self, checkout_id: str, request_id: str | None = None) -> CheckoutResult:
        with self._lock:
            now = datetime.now(UTC)
            if request_id:
                cached = self.store.cache_get(request_id, "return")
                if cached:
                    return CheckoutResult(**cached)
            record = self.store.get_checkout(checkout_id)
            if record is None:
                result = CheckoutResult("REJECTED", "UNKNOWN_CHECKOUT", None, None, None, 0, 0, 0)
                self.store.event("REJECTED_RETURN", result.__dict__, now)
                self.store.cache_set(request_id, "return", result.__dict__, now)
                return result
            if record.returned_at is not None or record.status == "RETURNED":
                feature = self.store.get_feature(record.feature)
                result = CheckoutResult(
                    "REJECTED",
                    "ALREADY_RETURNED",
                    record.checkout_id,
                    record.feature,
                    record.daemon,
                    feature["total"] if feature else 0,
                    feature["in_use"] if feature else 0,
                    self.store.queue_count(record.feature, record.daemon),
                )
                self.store.event("REJECTED_RETURN", result.__dict__, now)
                self.store.cache_set(request_id, "return", result.__dict__, now)
                return result

            self.store.mark_returned(record, now)
            self.log_writer.returned(record.daemon, record.feature, record.user, record.host, record.pid, record.checkout_id)
            feature = self.store.get_feature(record.feature)
            granted = self.store.grant_next_queued(record.feature, record.daemon, now)
            if granted:
                self.log_writer.checkout_granted(
                    granted.daemon, granted.feature, granted.user, granted.host, granted.pid, granted.checkout_id
                )
                feature = self.store.get_feature(record.feature)
            result = CheckoutResult(
                "RETURNED",
                None,
                record.checkout_id,
                record.feature,
                record.daemon,
                feature["total"] if feature else 0,
                feature["in_use"] if feature else 0,
                self.store.queue_count(record.feature, record.daemon),
            )
            self.store.event("RETURNED_CHECKOUT", result.__dict__, now)
            self.store.cache_set(request_id, "return", result.__dict__, now)
            return result

    def debug_checkouts(self, limit: int = 100, feature: str | None = None, daemon: str | None = None, status: str | None = None) -> list[dict]:
        return self.store.debug_checkouts(limit, feature, daemon, status)

    def debug_queue(self, limit: int = 100, feature: str | None = None, daemon: str | None = None) -> list[dict]:
        return self.store.debug_queue(limit, feature, daemon)


def _server_time() -> str:
    return datetime.now(UTC).isoformat()
