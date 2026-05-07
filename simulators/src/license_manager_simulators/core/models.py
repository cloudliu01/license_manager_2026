from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime


@dataclass(frozen=True)
class FeatureDef:
    name: str
    total: int
    daemon: str
    expires_at: date | None


@dataclass(frozen=True)
class LicenseConfig:
    port: int
    server_name: str | None
    daemons: list[str]
    features: dict[str, FeatureDef]


@dataclass(frozen=True)
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


@dataclass(frozen=True)
class CheckoutResult:
    status: str
    reason: str | None
    checkout_id: str | None
    feature: str | None
    daemon: str | None
    total: int
    in_use: int
    queued: int
