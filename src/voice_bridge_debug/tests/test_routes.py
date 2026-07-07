import queue

from fastapi.testclient import TestClient

from voice_bridge_debug.config import DebugPanelConfig
from voice_bridge_debug.routes import create_app
from voice_bridge_debug.state import PanelState
from voice_bridge_debug.ws import WebSocketManager


class FakeServer:
    def __init__(self):
        self.config = DebugPanelConfig.default()
        self.state = PanelState()
        self.asr_publish_queue = queue.Queue()
        self.ws_manager = WebSocketManager()


def test_publish_asr_enqueues_request():
    server = FakeServer()
    client = TestClient(create_app(server))

    response = client.post("/api/asr/publish", json={"text": "小宇向前", "confidence": 0.9, "is_final": True})

    assert response.status_code == 200
    assert response.json() == {"ok": True}
    assert server.asr_publish_queue.get_nowait()["text"] == "小宇向前"


def test_publish_asr_rejects_invalid_confidence():
    client = TestClient(create_app(FakeServer()))

    response = client.post("/api/asr/publish", json={"text": "小宇", "confidence": 2})

    assert response.status_code == 422


def test_state_and_history_routes_return_snapshot():
    server = FakeServer()
    server.state.push_event("asr", "asr_received", {"text": "小宇"}, timestamp=1.0)
    client = TestClient(create_app(server))

    assert client.get("/api/state").status_code == 200
    history = client.get("/api/history?limit=1").json()
    assert history["events"][0]["kind"] == "asr_received"


def test_prod_mode_requires_static_directory(tmp_path, monkeypatch):
    import pytest

    from voice_bridge_debug.config import DebugPanelConfig
    from voice_bridge_debug.server import DebugBridgeServer

    monkeypatch.setattr("voice_bridge_debug.server.Path.with_name", lambda self, name: tmp_path / "missing")

    with pytest.raises(FileNotFoundError, match="frontend static directory"):
        DebugBridgeServer(DebugPanelConfig.default(), prod=True)
