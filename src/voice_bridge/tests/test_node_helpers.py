import pytest

from g1_agent_msgs.msg import (
    ActionIntent,
    LocoIntent,
    RobotStateSummary,
    SafetyStatus,
    VoiceEvent,
)
from voice_bridge.internal_types import AgentCommand
from voice_bridge.node import (
    AgentRequestState,
    _supports_closeable,
    build_action_payload,
    build_led_payload,
    build_loco_payload,
    build_tts_payload,
    diagnostic_summary,
)


def test_build_loco_payload():
    payload = build_loco_payload(
        AgentCommand(kind="loco", params={"vx": 0.1, "vy": 0.0, "vyaw": 0.2, "duration_sec": 1.0}),
        session_id="s1",
        command_id="c1",
        text="向前",
        created_at=10.0,
    )

    assert payload["schema_version"] == "voice_command.v1"
    assert payload["source"] == "voice_bridge"
    assert payload["session_id"] == "s1"
    assert payload["created_at"] == 10.0
    assert payload["vx"] == 0.1
    assert payload["duration_sec"] == 1.0


def test_build_loco_payload_rejects_missing_fields():
    with pytest.raises(ValueError, match="missing loco field"):
        build_loco_payload(AgentCommand(kind="loco", params={"vx": 0.1}), "s1", "c1", "向前", created_at=10.0)


def test_build_action_payload():
    payload = build_action_payload("stop", "s1", "c1", "停止", created_at=10.0, priority="emergency")

    assert payload["schema_version"] == "voice_command.v1"
    assert payload["action"] == "stop"
    assert payload["created_at"] == 10.0
    assert payload["priority"] == "emergency"


def test_build_tts_payload():
    payload = build_tts_payload("收到", "s1")

    assert payload["text"] == "收到"
    assert payload["speaker_id"] == 0
    assert payload["interrupt"] is True


def test_build_led_payload():
    payload = build_led_payload({"r": 1, "g": 2, "b": 3, "ttl_sec": 0.5})

    assert payload == {"source": "voice_bridge", "r": 1, "g": 2, "b": 3, "ttl_sec": 0.5}


def test_diagnostic_summary_serializes_ros_byte_level():
    import json

    from diagnostic_msgs.msg import DiagnosticArray, DiagnosticStatus

    status = DiagnosticStatus()
    status.name = "g1_interface"
    status.level = b"\x01"
    status.message = "degraded"

    msg = DiagnosticArray()
    msg.status.append(status)

    payload = json.loads(diagnostic_summary(msg))

    assert payload["status"] == [{"level": 1, "message": "degraded", "name": "g1_interface"}]


def test_agent_request_state_invalidates_old_requests():
    state = AgentRequestState()

    first = state.start("s1")
    assert state.is_current(first, "s1") is True

    state.invalidate()

    assert state.is_current(first, "s1") is False


def test_agent_request_state_only_accepts_latest_session():
    state = AgentRequestState()

    first = state.start("s1")
    second = state.start("s2")

    assert state.is_current(first, "s1") is False
    assert state.is_current(second, "s2") is True


class CloseableAgent:
    def decide(self, request):
        raise AssertionError("not used")

    def abort(self):
        return None

    def close(self):
        return None


class NonCloseableAgent:
    def decide(self, request):
        raise AssertionError("not used")


def test_supports_closeable_uses_hasattr():
    assert _supports_closeable(CloseableAgent()) is True
    assert _supports_closeable(NonCloseableAgent()) is False


class FakePublisher:
    def __init__(self):
        self.payloads = []

    def publish(self, msg):
        self.payloads.append(msg)


class FakeClockNow:
    nanoseconds = 1_000_000_000


class FakeClock:
    def now(self):
        return FakeClockNow()


class FakeLogger:
    def warning(self, message):
        self.message = message


class FakeString:
    def __init__(self):
        self.data = ""


def fake_ros_messages():
    return {
        "ActionIntent": ActionIntent,
        "DiagnosticArray": object,
        "LocoIntent": LocoIntent,
        "RobotStateSummary": RobotStateSummary,
        "SafetyStatus": SafetyStatus,
        "String": FakeString,
        "VoiceEvent": VoiceEvent,
    }


class FakeNode:
    def __init__(self):
        self.publishers = []

    def create_publisher(self, msg_type, topic, depth):
        pub = FakePublisher()
        self.publishers.append(pub)
        return pub

    def create_subscription(self, *args, **kwargs):
        return None

    def create_timer(self, *args, **kwargs):
        return None

    def get_clock(self):
        return FakeClock()

    def get_logger(self):
        return FakeLogger()


def test_stop_action_aborts_closeable_agent_after_publish(monkeypatch):
    from voice_bridge import node as node_module
    from voice_bridge.config import VoiceBridgeConfig
    from voice_bridge.internal_types import SessionDecision
    from voice_bridge.node import VoiceBridgeNode

    monkeypatch.setattr(node_module, "_load_ros_messages", fake_ros_messages)

    class Agent(CloseableAgent):
        def __init__(self):
            self.aborted = False

        def abort(self):
            self.aborted = True

    agent = Agent()
    node = VoiceBridgeNode(FakeNode(), VoiceBridgeConfig.default(), agent=agent)

    node._publish_action_decision(SessionDecision(kind="action", session_id="s1", text="停止", action="stop"), 1.0)

    assert agent.aborted is True
    assert len(node.action_pub.payloads) == 1
    assert node.action_pub.payloads[0].action == "stop"


def test_shutdown_closes_closeable_agent(monkeypatch):
    from voice_bridge import node as node_module
    from voice_bridge.config import VoiceBridgeConfig
    from voice_bridge.node import VoiceBridgeNode

    monkeypatch.setattr(node_module, "_load_ros_messages", fake_ros_messages)

    class Agent(CloseableAgent):
        def __init__(self):
            self.closed = False

        def close(self):
            self.closed = True

    agent = Agent()
    node = VoiceBridgeNode(FakeNode(), VoiceBridgeConfig.default(), agent=agent)

    node.shutdown()

    assert agent.closed is True


def test_build_debug_event_payload():
    from voice_bridge.node import DEBUG_EVENT_SCHEMA_VERSION, build_debug_event

    payload = build_debug_event(
        "agent_result",
        "s1",
        {"reply_text": "收到"},
        timestamp=10.5,
    )

    assert payload == {
        "schema_version": DEBUG_EVENT_SCHEMA_VERSION,
        "timestamp": 10.5,
        "session_id": "s1",
        "event": "agent_result",
        "data": {"reply_text": "收到"},
    }


def test_debug_event_publish_is_best_effort(monkeypatch):
    import json

    from voice_bridge import node as node_module
    from voice_bridge.config import VoiceBridgeConfig
    from voice_bridge.node import VoiceBridgeNode

    monkeypatch.setattr(node_module, "_load_ros_messages", fake_ros_messages)

    node = VoiceBridgeNode(FakeNode(), VoiceBridgeConfig.default(), agent=NonCloseableAgent())
    node._publish_debug_event("agent_started", "s1", {"text": "向前"}, 1.0)

    payload = json.loads(node.debug_pub.payloads[-1].data)
    assert payload["schema_version"] == "voice_debug_event.v1"
    assert payload["event"] == "agent_started"
    assert payload["session_id"] == "s1"
    assert payload["data"] == {"text": "向前"}


def test_agent_result_debug_event_publishes_before_commands(monkeypatch):
    import json

    from voice_bridge import node as node_module
    from voice_bridge.config import VoiceBridgeConfig
    from voice_bridge.internal_types import AgentCommand, AgentRequest, AgentResult
    from voice_bridge.node import VoiceBridgeNode

    monkeypatch.setattr(node_module, "_load_ros_messages", fake_ros_messages)

    node = VoiceBridgeNode(FakeNode(), VoiceBridgeConfig.default(), agent=NonCloseableAgent())
    request = AgentRequest(session_id="s1", text="向前", asr_confidence=0.9)
    result = AgentResult(
        commands=[AgentCommand(kind="loco", params={"vx": 0.25, "vy": 0.0, "vyaw": 0.0, "duration_sec": 1.0})],
        reply_text="收到",
        led={"r": 0, "g": 1, "b": 0},
    )

    node._publish_agent_result(result, request, 1.0)

    debug_payload = json.loads(node.debug_pub.payloads[0].data)
    assert debug_payload["event"] == "agent_result"
    assert debug_payload["data"]["reply_text"] == "收到"
    assert debug_payload["data"]["commands"][0]["kind"] == "loco"
    assert len(node.loco_pub.payloads) == 1
    assert node.loco_pub.payloads[0].vx == 0.25
