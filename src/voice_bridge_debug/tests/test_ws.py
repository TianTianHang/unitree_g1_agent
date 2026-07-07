import asyncio

from voice_bridge_debug.ws import WebSocketManager


class FakeWebSocket:
    def __init__(self, fail=False):
        self.accepted = False
        self.messages = []
        self.fail = fail

    async def accept(self):
        self.accepted = True

    async def send_json(self, message):
        if self.fail:
            raise RuntimeError("closed")
        self.messages.append(message)


def test_websocket_manager_connects_and_broadcasts():
    manager = WebSocketManager()
    ws = FakeWebSocket()

    async def run():
        await manager.connect(ws)
        await manager.broadcast({"type": "connection_status", "data": {"websocket": "connected"}})

    asyncio.run(run())

    assert ws.accepted is True
    assert ws.messages == [{"type": "connection_status", "data": {"websocket": "connected"}}]


def test_websocket_manager_removes_failed_connections():
    manager = WebSocketManager()
    ws = FakeWebSocket(fail=True)

    async def run():
        await manager.connect(ws)
        await manager.broadcast({"type": "timeline_event", "data": {}})

    asyncio.run(run())

    assert ws not in manager.connections
