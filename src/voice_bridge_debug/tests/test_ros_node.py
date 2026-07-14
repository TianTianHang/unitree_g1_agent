import json
import queue

from builtin_interfaces.msg import Time

from g1_agent_msgs.msg import RobotStateSummary, SafetyStatus, VoiceEvent
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
        self.messages.append(msg)


class FakeClockNow:
    nanoseconds = 1_000_000_000

    def to_msg(self):
        return Time(sec=1)


class FakeClock:
    def now(self):
        return FakeClockNow()


class FakeNode:
    def __init__(self):
        self.publishers = {}
        self.publisher_types = {}
        self.subscription_types = {}
        self.subscriptions = []
        self.timers = []

    def create_publisher(self, msg_type, topic, depth):
        pub = FakePublisher()
        self.publishers[topic] = pub
        self.publisher_types[topic] = msg_type
        return pub

    def create_subscription(self, msg_type, topic, callback, depth):
        self.subscription_types[topic] = msg_type
        self.subscriptions.append((topic, callback))
        return callback

    def create_timer(self, period, callback):
        self.timers.append((period, callback))
        return callback

    def get_clock(self):
        return FakeClock()


def test_debug_asr_queue_publishes_voice_event():
    config = DebugPanelConfig.default()
    q = queue.Queue()
    q.put({"text": "小宇向前", "confidence": 0.9, "is_final": True, "source": "debug"})
    fake_node = FakeNode()
    bridge = DebugBridgeNode(fake_node, config, PanelState(), q, lambda message: None)

    bridge.drain_asr_queue()

    msg = fake_node.publishers["/g1/audio/asr"].messages[-1]
    assert fake_node.publisher_types["/g1/audio/asr"] is VoiceEvent
    assert msg.event_type == msg.EVENT_ASR
    assert msg.text == "小宇向前"
    assert msg.has_confidence is True
    assert msg.confidence == 0.9
    assert msg.stamp == Time(sec=1)


def test_typed_robot_and_safety_state_are_stored_without_json_wrapper():
    fake_node = FakeNode()
    state = PanelState()
    bridge = DebugBridgeNode(
        fake_node,
        DebugPanelConfig.default(),
        state,
        queue.Queue(),
        lambda message: None,
    )

    bridge.on_robot_mode(
        RobotStateSummary(
            stamp=Time(sec=1),
            mode=RobotStateSummary.MODE_SPORT_API_LOCO,
            control_owner=RobotStateSummary.OWNER_INTERNAL,
        )
    )
    bridge.on_safety_state(SafetyStatus(node_name="safety_control", enabled=True))

    assert state.robot_mode["mode"] == "sport_api_loco"
    assert state.safety_state["enabled"] is True
    assert fake_node.subscription_types["/g1/state/mode"] is RobotStateSummary
    assert fake_node.subscription_types["/g1/state/safety"] is SafetyStatus


def test_voice_debug_agent_result_updates_agent_result():
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


def test_voice_debug_agent_started_marks_current_result_pending():
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
