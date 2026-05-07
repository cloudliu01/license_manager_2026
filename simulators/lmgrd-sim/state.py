from __future__ import annotations
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime
from uuid import uuid4
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from .license_parser import LicenseConfig


def _load_license_parser():
    try:
        from . import license_parser

        return license_parser
    except Exception:
        import importlib.util
        import sys
        from pathlib import Path

        base_dir = Path(__file__).resolve().parent
        spec = importlib.util.spec_from_file_location(
            "license_parser", base_dir / "license_parser.py"
        )
        if spec is None or spec.loader is None:
            raise
        module = importlib.util.module_from_spec(spec)
        sys.modules["license_parser"] = module
        spec.loader.exec_module(module)
        return module


@dataclass
class FeatureState:
    name: str
    daemon: str
    total: int
    in_use: int = 0
    expires_at: date | None = None

    @property
    def expired(self) -> bool:
        if self.expires_at is None:
            return False
        return self.expires_at < date.today()


@dataclass
class CheckoutRecord:
    checkout_id: str
    feature: str
    daemon: str
    user: str
    host: str
    pid: int
    status: str
    requested_at: datetime
    granted_at: datetime | None = None
    returned_at: datetime | None = None


@dataclass
class CheckoutResult:
    status: str
    reason: str | None
    checkout_id: str | None
    total: int
    in_use: int
    queued: int


@dataclass
class SimulatorState:
    features: dict[str, FeatureState] = field(default_factory=dict)
    checkouts: dict[str, CheckoutRecord] = field(default_factory=dict)
    queue: list[CheckoutRecord] = field(default_factory=list)
    request_cache: dict[str, CheckoutResult] = field(default_factory=dict)

    @classmethod
    def from_license(cls, config: "LicenseConfig") -> "SimulatorState":
        features = {
            name: FeatureState(
                name=feature.name,
                daemon=feature.daemon,
                total=feature.total,
                expires_at=feature.expires_at,
            )
            for name, feature in config.features.items()
        }
        return cls(features=features)

    def checkout(
        self,
        feature_name: str,
        user: str,
        host: str,
        pid: int,
        request_id: str | None = None,
    ) -> CheckoutResult:
        now = datetime.utcnow()
        if request_id and request_id in self.request_cache:
            return self.request_cache[request_id]
        feature = self.features.get(feature_name)
        if feature is None:
            result = CheckoutResult(
                "REJECTED", "UNKNOWN_FEATURE", None, 0, 0, len(self.queue)
            )
            if request_id:
                self.request_cache[request_id] = result
            return result
        if feature.expired:
            result = CheckoutResult(
                "REJECTED",
                "FEATURE_EXPIRED",
                None,
                feature.total,
                feature.in_use,
                len(self.queue),
            )
            if request_id:
                self.request_cache[request_id] = result
            return result

        if feature.in_use < feature.total:
            checkout_id = str(uuid4())
            feature.in_use += 1
            record = CheckoutRecord(
                checkout_id=checkout_id,
                feature=feature.name,
                daemon=feature.daemon,
                user=user,
                host=host,
                pid=pid,
                status="GRANTED",
                requested_at=now,
                granted_at=now,
            )
            self.checkouts[checkout_id] = record
            result = CheckoutResult(
                "GRANTED",
                None,
                checkout_id,
                feature.total,
                feature.in_use,
                len(self.queue),
            )
            if request_id:
                self.request_cache[request_id] = result
            return result

        if len(self.queue) >= 100:
            result = CheckoutResult(
                "REJECTED",
                "QUEUE_FULL",
                None,
                feature.total,
                feature.in_use,
                len(self.queue),
            )
            if request_id:
                self.request_cache[request_id] = result
            return result

        checkout_id = str(uuid4())
        record = CheckoutRecord(
            checkout_id=checkout_id,
            feature=feature.name,
            daemon=feature.daemon,
            user=user,
            host=host,
            pid=pid,
            status="QUEUED",
            requested_at=now,
        )
        self.queue.append(record)
        result = CheckoutResult(
            "QUEUED", None, checkout_id, feature.total, feature.in_use, len(self.queue)
        )
        if request_id:
            self.request_cache[request_id] = result
        return result

    def return_checkout(
        self, checkout_id: str, request_id: str | None = None
    ) -> CheckoutResult:
        now = datetime.utcnow()
        if request_id and request_id in self.request_cache:
            return self.request_cache[request_id]
        record = self.checkouts.get(checkout_id)
        if record is None:
            result = CheckoutResult(
                "REJECTED", "UNKNOWN_CHECKOUT", None, 0, 0, len(self.queue)
            )
            if request_id:
                self.request_cache[request_id] = result
            return result
        if record.returned_at is not None:
            result = CheckoutResult(
                "REJECTED",
                "ALREADY_RETURNED",
                record.checkout_id,
                0,
                0,
                len(self.queue),
            )
            if request_id:
                self.request_cache[request_id] = result
            return result

        feature = self.features.get(record.feature)
        if feature:
            feature.in_use = max(0, feature.in_use - 1)
        record.status = "RETURNED"
        record.returned_at = now

        if self.queue and feature and feature.in_use < feature.total:
            queued = self.queue.pop(0)
            queued.status = "GRANTED"
            queued.granted_at = now
            feature.in_use += 1
            self.checkouts[queued.checkout_id] = queued

        result = CheckoutResult(
            "RETURNED",
            None,
            record.checkout_id,
            feature.total if feature else 0,
            feature.in_use if feature else 0,
            len(self.queue),
        )
        if request_id:
            self.request_cache[request_id] = result
        return result
