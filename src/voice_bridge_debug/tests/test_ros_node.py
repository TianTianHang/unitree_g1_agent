import json
import queue

from voice_bridge_debug.config import DebugPanelConfig
from voice_bridge_debug.ros_node import DebugBridgeNode
from voice_bridge_debug.state import PanelState


class FakeString:
    def __init__(self):
        self.data = ""


class FakePublisher:
    def __init__(self):
        self.messages = []

    def publish(self, msg):
        self.messages.append(msg.data)


class FakeClockNow:
    nanoseconds = 1_000_000_000


class FakeClock:
    def now(self):
        return FakeClockNow()


class FakeNode:
    def __init__(self):
        self.publishers = {}
        self.subscriptions = []
        self.timers = []

    def create_publisher(self, msg_type, topic, depth):
        pub = FakePublisher()
        self.publishers[topic] = pub
        return pub

    def create_subscription(self, msg_type, topic, callback, depth):
        self.subscriptions.append((topic, callback))
        return callback

    def create_timer(self, period, callback):
        self.timers.append((period, callback))
        return callback

    def get_clock(self):
        return FakeClock()


def test_drain_asr_queue_publishes_json(monkeypatch):
    from voice_bridge_debug import ros_node as ros_node_module

    monkeypatch.setattr(ros_node_module, "_load_ros_messages", lambda: {"String": FakeString, "DiagnosticArray": object})
    config = DebugPanelConfig.default()
    q = queue.Queue()
    q.put({"text": "小宇向前", "confidence": 0.9, "is_final": True, "source": "debug"})
    node = DebugBridgeNode(FakeNode(), config, PanelState(), q, lambda message: None)

    node.drain_asr_queue()

    payload = json.loads(node.asr_pub.messages[-1])
    assert payload["text"] == "小宇向前"
    assert payload["confidence"] == 0.9
    assert payload["is_final"] is True
    assert payload["source"] == "debug"
    assert "stamp" in payload


def test_voice_debug_agent_result_updates_agent_result(monkeypatch):
    from voice_bridge_debug import ros_node as ros_node_module

    monkeypatch.setattr(ros_node_module, "_load_ros_messages", lambda: {"String": FakeString, "DiagnosticArray": object})
    messages = []
    state = PanelState(notify_web=messages.append)
    node = DebugBridgeNode(FakeNode(), DebugPanelConfig.default(), state, queue.Queue(), messages.append)
    msg = FakeString()
    msg.data = json.dumps(
        {
            "schema_version": "voice_debug_event.v1",
            "timestamp": 1.0,
            "session_id": "s1",
            "event": "agent_result",
            "data": {"commands": [], "reply_text": "收到", "led": None, "requires_confirmation": False},
        },
        ensure_ascii=False,
    )

    node.on_voice_debug_event(msg)

    assert state.agent_result["reply_text"] == "收到"
    assert messages[-1]["type"] == "agent_result"
