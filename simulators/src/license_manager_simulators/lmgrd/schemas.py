from __future__ import annotations

from pydantic import BaseModel

from license_manager_simulators.core.models import CheckoutResult


class CheckoutRequest(BaseModel):
    request_id: str | None = None
    feature: str
    user: str
    host: str
    pid: int


class ReturnRequest(BaseModel):
    request_id: str | None = None
    checkout_id: str


class OperationResponse(BaseModel):
    protocol_version: int = 1
    server_time: str
    request_id: str
    checkout_id: str | None
    feature: str | None
    daemon: str | None
    status: str
    reason: str | None
    total: int
    in_use: int
    queued: int

    @classmethod
    def from_result(
        cls, result: CheckoutResult, request_id: str, server_time: str
    ) -> "OperationResponse":
        return cls(
            server_time=server_time,
            request_id=request_id,
            checkout_id=result.checkout_id,
            feature=result.feature,
            daemon=result.daemon,
            status=result.status,
            reason=result.reason,
            total=result.total,
            in_use=result.in_use,
            queued=result.queued,
        )
