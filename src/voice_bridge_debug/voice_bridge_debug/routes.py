from __future__ import annotations

from typing import Any

from fastapi import FastAPI, HTTPException, WebSocket, WebSocketDisconnect
from pydantic import BaseModel, Field


class AsrPublishRequest(BaseModel):
    text: str = Field(min_length=1)
    confidence: float | None = Field(default=None, ge=0.0, le=1.0)
    is_final: bool | None = None
    source: str | None = None


class QuickAsrRequest(BaseModel):
    text: str = Field(min_length=1)


def _asr_payload(server: Any, request: AsrPublishRequest) -> dict[str, Any]:
    return {
        "text": request.text.strip(),
        "confidence": float(
            request.confidence
            if request.confidence is not None
            else server.config.defaults["asr_confidence"]
        ),
        "is_final": bool(request.is_final if request.is_final is not None else server.config.defaults["asr_is_final"]),
        "source": str(request.source or server.config.defaults["asr_source"]),
    }


def create_app(server: Any) -> FastAPI:
    app = FastAPI(title="G1 Voice Bridge Debug Panel")

    @app.on_event("startup")
    async def startup() -> None:
        startup_fn = getattr(server, "startup", None)
        if startup_fn is not None:
            await startup_fn()

    @app.on_event("shutdown")
    async def shutdown() -> None:
        shutdown_fn = getattr(server, "shutdown", None)
        if shutdown_fn is not None:
            await shutdown_fn()

    @app.post("/api/asr/publish")
    async def publish_asr(request: AsrPublishRequest) -> dict[str, bool]:
        server.asr_publish_queue.put(_asr_payload(server, request))
        return {"ok": True}

    @app.post("/api/asr/quick")
    async def quick_asr(request: QuickAsrRequest) -> dict[str, bool]:
        server.asr_publish_queue.put(
            {
                "text": request.text.strip(),
                "confidence": float(server.config.defaults["asr_confidence"]),
                "is_final": bool(server.config.defaults["asr_is_final"]),
                "source": str(server.config.defaults["asr_source"]),
            }
        )
        return {"ok": True}

    @app.get("/api/history")
    async def history(limit: int = 50, offset: int = 0) -> dict[str, Any]:
        if limit <= 0 or offset < 0:
            raise HTTPException(status_code=400, detail="invalid pagination")
        events = server.state.snapshot()["timeline"]
        return {"events": events[offset : offset + limit], "total": len(events)}

    @app.get("/api/config")
    async def config() -> dict[str, Any]:
        return server.config.to_dict()

    @app.get("/api/state")
    async def state() -> dict[str, Any]:
        return server.state.snapshot()

    @app.websocket("/ws")
    async def websocket(ws: WebSocket) -> None:
        await server.ws_manager.connect(ws)
        try:
            await ws.send_json({"type": "connection_status", "data": {"websocket": "connected"}})
            while True:
                await ws.receive_text()
        except WebSocketDisconnect:
            await server.ws_manager.disconnect(ws)

    return app
