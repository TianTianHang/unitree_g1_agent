from __future__ import annotations

import asyncio
from typing import Any

from fastapi import WebSocket


class WebSocketManager:
    def __init__(self):
        self.connections: set[WebSocket] = set()
        self._lock = asyncio.Lock()

    async def connect(self, ws: WebSocket) -> None:
        await ws.accept()
        async with self._lock:
            self.connections.add(ws)

    async def disconnect(self, ws: WebSocket) -> None:
        async with self._lock:
            self.connections.discard(ws)

    async def broadcast(self, message: dict[str, Any]) -> None:
        async with self._lock:
            connections = list(self.connections)
        failed = []
        for ws in connections:
            try:
                await ws.send_json(message)
            except Exception:
                failed.append(ws)
        if failed:
            async with self._lock:
                for ws in failed:
                    self.connections.discard(ws)
