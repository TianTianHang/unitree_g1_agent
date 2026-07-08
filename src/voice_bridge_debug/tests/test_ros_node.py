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


def test_voice_debug_agent_started_marks_current_result_pending(monkeypatch):
    from voice_bridge_debug import ros_node as ros_node_module

    monkeypatch.setattr(ros_node_module, "_load_ros_messages", lambda: {"String": FakeString, "DiagnosticArray": object})
    messages = []
    state = PanelState(notify_web=messages.append)
    state.set_agent_result(
        {
            "status": "complete",
            "session_id": "s1",
            "commands": [],
            "reply_text": "上一轮",
            "led": None,
            "requires_confirmation": False,
        }
    )
    node = DebugBridgeNode(FakeNode(), DebugPanelConfig.default(), state, queue.Queue(), messages.append)
    msg = FakeString()
    msg.data = json.dumps(
        {
            "schema_version": "voice_debug_event.v1",
            "timestamp": 2.0,
            "session_id": "s2",
            "event": "agent_started",
            "data": {"text": "向前", "backend": "pi"},
        },
        ensure_ascii=False,
    )

    node.on_voice_debug_event(msg)

    assert state.agent_result == {
        "status": "pending",
        "session_id": "s2",
        "request_text": "向前",
        "backend": "pi",
        "started_at": 2.0,
        "commands": [],
        "reply_text": None,
        "led": None,
        "requires_confirmation": False,
    }
    assert messages[-1]["type"] == "agent_result"
    assert messages[-1]["data"]["status"] == "pending"
