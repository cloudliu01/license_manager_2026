from __future__ import annotations
from __future__ import annotations

from datetime import datetime, timezone
from typing import TYPE_CHECKING
from uuid import uuid4

from fastapi import FastAPI, HTTPException

if TYPE_CHECKING:
    from .state import SimulatorState


def _server_time() -> str:
    return datetime.now(timezone.utc).isoformat()


def create_app(state: "SimulatorState", server_name: str, port: int) -> FastAPI:
    app = FastAPI()

    @app.get("/v1/health")
    def health():
        return {
            "protocol_version": 1,
            "server_time": _server_time(),
            "request_id": str(uuid4()),
            "server_name": server_name,
            "port": port,
            "feature_count": len(state.features),
            "daemons": sorted({f.daemon for f in state.features.values()}),
        }

    @app.get("/v1/status")
    def status():
        features = []
        for feature in state.features.values():
            features.append(
                {
                    "feature": feature.name,
                    "daemon": feature.daemon,
                    "total": feature.total,
                    "in_use": feature.in_use,
                    "queued": len(state.queue),
                    "expired": feature.expired,
                }
            )
        return {
            "protocol_version": 1,
            "server_time": _server_time(),
            "request_id": str(uuid4()),
            "server_name": server_name,
            "port": port,
            "features": features,
            "uptime_seconds": 0,
            "config_hash": "",
            "counters": {
                "granted": len(
                    [c for c in state.checkouts.values() if c.status == "GRANTED"]
                ),
                "queued": len(state.queue),
                "rejected": 0,
                "returned": len(
                    [c for c in state.checkouts.values() if c.status == "RETURNED"]
                ),
            },
        }

    @app.post("/v1/checkout")
    def checkout(payload: dict):
        request_id = payload.get("request_id")
        feature = payload.get("feature")
        user = payload.get("user")
        host = payload.get("host")
        pid = payload.get("pid")
        if not feature or not user or not host or pid is None:
            raise HTTPException(status_code=400, detail="INVALID_REQUEST")
        result = state.checkout(feature, user, host, int(pid), request_id=request_id)
        feature_state = state.features.get(feature)
        return {
            "protocol_version": 1,
            "server_time": _server_time(),
            "request_id": request_id or str(uuid4()),
            "checkout_id": result.checkout_id,
            "feature": feature,
            "daemon": feature_state.daemon if feature_state else "default",
            "status": result.status,
            "reason": result.reason,
            "total": result.total,
            "in_use": result.in_use,
            "queued": result.queued,
        }

    @app.post("/v1/return")
    def return_checkout(payload: dict):
        request_id = payload.get("request_id")
        checkout_id = payload.get("checkout_id")
        if not checkout_id:
            raise HTTPException(status_code=400, detail="INVALID_REQUEST")
        result = state.return_checkout(checkout_id, request_id=request_id)
        checkout = state.checkouts.get(checkout_id)
        return {
            "protocol_version": 1,
            "server_time": _server_time(),
            "request_id": request_id or str(uuid4()),
            "checkout_id": result.checkout_id,
            "feature": checkout.feature if checkout else None,
            "daemon": checkout.daemon if checkout else None,
            "status": result.status,
            "reason": result.reason,
            "total": result.total,
            "in_use": result.in_use,
            "queued": result.queued,
        }

    @app.get("/v1/debug/checkouts")
    def debug_checkouts(limit: int = 100):
        items = list(state.checkouts.values())[:limit]
        return {
            "protocol_version": 1,
            "server_time": _server_time(),
            "request_id": str(uuid4()),
            "checkouts": [
                {
                    "checkout_id": c.checkout_id,
                    "feature": c.feature,
                    "daemon": c.daemon,
                    "user": c.user,
                    "host": c.host,
                    "pid": c.pid,
                    "status": c.status,
                    "requested_at": c.requested_at.isoformat(),
                    "granted_at": c.granted_at.isoformat() if c.granted_at else None,
                    "returned_at": c.returned_at.isoformat() if c.returned_at else None,
                }
                for c in items
            ],
        }

    @app.get("/v1/debug/queue")
    def debug_queue(limit: int = 100):
        items = state.queue[:limit]
        return {
            "protocol_version": 1,
            "server_time": _server_time(),
            "request_id": str(uuid4()),
            "queue": [
                {
                    "checkout_id": c.checkout_id,
                    "feature": c.feature,
                    "daemon": c.daemon,
                    "user": c.user,
                    "host": c.host,
                    "pid": c.pid,
                    "status": c.status,
                    "requested_at": c.requested_at.isoformat(),
                }
                for c in items
            ],
        }

    return app
