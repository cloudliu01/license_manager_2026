from __future__ import annotations

from contextlib import asynccontextmanager
from datetime import UTC, datetime
from uuid import uuid4

from fastapi import FastAPI, HTTPException

from license_manager_simulators.core.service import SimulatorService

from .schemas import CheckoutRequest, OperationResponse, ReturnRequest


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
    def checkout(payload: CheckoutRequest) -> dict:
        request_id = payload.request_id or str(uuid4())
        try:
            result = service.checkout(
                payload.feature,
                payload.user,
                payload.host,
                payload.pid,
                request_id=request_id,
                quantity=payload.quantity,
                info=payload.info,
            )
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        return _result_response(result, request_id)

    @app.post("/v1/return")
    def return_checkout(payload: ReturnRequest) -> dict:
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
    return OperationResponse.from_result(result, request_id, service_time()).model_dump()


def service_time() -> str:
    return datetime.now(UTC).isoformat()
