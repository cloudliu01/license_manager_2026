from __future__ import annotations

from contextlib import asynccontextmanager
from uuid import uuid4

from fastapi import FastAPI, HTTPException
from pydantic import BaseModel

from license_manager_simulators.core.service import SimulatorService


class CheckoutRequest(BaseModel):
    request_id: str | None = None
    feature: str
    user: str
    host: str
    pid: int


class ReturnRequest(BaseModel):
    request_id: str | None = None
    checkout_id: str


def create_app(service: SimulatorService) -> FastAPI:
    @asynccontextmanager
    async def lifespan(_app: FastAPI):
        yield
        service.log_writer.shutdown()

    app = FastAPI(lifespan=lifespan)

    @app.get("/v1/health")
    def health():
        return service.health()

    @app.get("/v1/status")
    def status():
        return service.status()

    @app.post("/v1/checkout")
    def checkout(payload: CheckoutRequest):
        request_id = payload.request_id or str(uuid4())
        try:
            result = service.checkout(
                payload.feature, payload.user, payload.host, payload.pid, request_id=request_id
            )
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        return _result_response(result, request_id)

    @app.post("/v1/return")
    def return_checkout(payload: ReturnRequest):
        request_id = payload.request_id or str(uuid4())
        try:
            result = service.return_checkout(payload.checkout_id, request_id=request_id)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        return _result_response(result, request_id)

    @app.get("/v1/debug/checkouts")
    def debug_checkouts(
        limit: int = 100,
        feature: str | None = None,
        daemon: str | None = None,
        status: str | None = None,
    ):
        return {
            "protocol_version": 1,
            "server_time": service.status()["server_time"],
            "request_id": str(uuid4()),
            "checkouts": service.debug_checkouts(limit, feature, daemon, status),
        }

    @app.get("/v1/debug/queue")
    def debug_queue(limit: int = 100, feature: str | None = None, daemon: str | None = None):
        return {
            "protocol_version": 1,
            "server_time": service.status()["server_time"],
            "request_id": str(uuid4()),
            "queue": service.debug_queue(limit, feature, daemon),
        }

    return app


def _result_response(result, request_id: str) -> dict:
    return {
        "protocol_version": 1,
        "server_time": service_time(),
        "request_id": request_id,
        "checkout_id": result.checkout_id,
        "feature": result.feature,
        "daemon": result.daemon,
        "status": result.status,
        "reason": result.reason,
        "total": result.total,
        "in_use": result.in_use,
        "queued": result.queued,
    }


def service_time() -> str:
    from datetime import UTC, datetime

    return datetime.now(UTC).isoformat()
