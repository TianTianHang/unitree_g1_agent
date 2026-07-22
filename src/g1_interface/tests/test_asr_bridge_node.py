from __future__ import annotations

import json

import pytest
from builtin_interfaces.msg import Duration, Time

import g1_interface.node as node_module
from g1_agent_msgs.msg import (
    ActionIntent,
    LocoIntent,
    RobotStateSummary,
    SafetyDecision,
    SafetyStatus,
    ValidatedActionCommand,
    ValidatedLocoCommand,
    VoiceEvent,
)
from g1_interface.config import G1InterfaceConfig
from g1_interface.node import G1InterfaceNode


class FakePublisher:
    def __init__(self):
        self.messages = []

    def publish(self, msg):
        self.messages.append(msg)


class FakeClockTime:
    nanoseconds = 1_000_000_000


class FakeClock:
    def now(self):
        return FakeClockTime()


class FakeLogger:
    def __init__(self):
        self.warnings = []

    def warning(self, message):
        self.warnings.append(message)


class FakeNode:
    def __init__(self):
        self.publishers = {}
        self.publisher_types = {}
        self.subscription_types = {}
        self.subscriptions = []
        self.timers = []
        self.logger = FakeLogger()

    def create_publisher(self, msg_type, topic, qos):
        publisher = FakePublisher()
        self.publishers[topic] = publisher
        self.publisher_types[topic] = msg_type
        return publisher

    def create_subscription(self, msg_type, topic, callback, qos):
        self.subscription_types[topic] = msg_type
        self.subscriptions.append((topic, callback))
        return callback

    def create_timer(self, period, callback, callback_group=None, clock=None):
        self.timers.append((period, callback, clock))
        return callback

    def get_clock(self):
        return FakeClock()

    def get_logger(self):
        return self.logger


def _string_msg(data: str):
    from std_msgs.msg import String

    msg = String()
    msg.data = data
    return msg


def test_g1_interface_wires_audio_msg_to_project_asr_and_event_topics():
    node = FakeNode()
    bridge = G1InterfaceNode(node=node, config=G1InterfaceConfig.default())

    audio_subscriptions = [topic for topic, callback in node.subscriptions if callback == bridge.on_audio_msg]

    assert audio_subscriptions == ["/audio_msg"]
    assert "/g1/audio/asr" in node.publishers
    assert "/g1/audio/event" in node.publishers
    assert node.publisher_types["/g1/audio/asr"] is VoiceEvent
    assert node.publisher_types["/g1/audio/event"] is VoiceEvent
    assert node.publisher_types["/g1/state/low"] is RobotStateSummary
    assert node.publisher_types["/g1/state/mode"] is RobotStateSummary


def test_audio_msg_callback_forwards_asr_as_typed_event():
    node = FakeNode()
    bridge = G1InterfaceNode(node=node, config=G1InterfaceConfig.default())
    raw = '{"text":"宇树，向前走一秒","confidence":0.95,"is_final":true,"index":1}'

    bridge.on_audio_msg(_string_msg(raw))

    published = node.publishers["/g1/audio/asr"].messages
    assert len(published) == 1
    assert published[0].event_type == VoiceEvent.EVENT_ASR
    assert published[0].text == "宇树，向前走一秒"
    assert published[0].has_confidence is True
    assert published[0].confidence == pytest.approx(0.95)
    assert published[0].has_sequence_id is True
    assert published[0].sequence_id == 1
    assert node.publishers["/g1/audio/event"].messages == []


def test_audio_msg_callback_bridges_play_state_to_audio_event():
    node = FakeNode()
    bridge = G1InterfaceNode(node=node, config=G1InterfaceConfig.default())

    bridge.on_audio_msg(_string_msg('{"play_state":1}'))

    assert node.publishers["/g1/audio/asr"].messages == []
    published = node.publishers["/g1/audio/event"].messages
    assert len(published) == 1
    assert published[0].event_type == VoiceEvent.EVENT_PLAYBACK
    assert published[0].playback_state == VoiceEvent.PLAYBACK_PLAYING


def test_audio_msg_callback_drops_unsupported_json_and_counts_it():
    node = FakeNode()
    bridge = G1InterfaceNode(node=node, config=G1InterfaceConfig.default())

    bridge.on_audio_msg(_string_msg("[1, 2, 3]"))

    assert node.publishers["/g1/audio/asr"].messages == []
    assert node.publishers["/g1/audio/event"].messages == []
    assert bridge.invalid_audio_event_count == 1


def test_audio_msg_callback_drops_builtin_asr_when_source_mode_custom():
    node = FakeNode()
    config = G1InterfaceConfig.default().with_asr_source_mode("custom")
    bridge = G1InterfaceNode(node=node, config=config)
    raw = '{"text":"宇树，向前走一秒","confidence":0.95,"is_final":true,"index":1}'

    bridge.on_audio_msg(_string_msg(raw))

    assert node.publishers["/g1/audio/asr"].messages == []
    assert node.publishers["/g1/audio/event"].messages == []


def test_audio_msg_callback_keeps_audio_events_when_source_mode_custom():
    node = FakeNode()
    config = G1InterfaceConfig.default().with_asr_source_mode("custom")
    bridge = G1InterfaceNode(node=node, config=config)

    bridge.on_audio_msg(_string_msg('{"play_state":1}'))

    assert node.publishers["/g1/audio/asr"].messages == []
    published = node.publishers["/g1/audio/event"].messages
    assert len(published) == 1
    assert published[0].event_type == VoiceEvent.EVENT_PLAYBACK


def test_audio_msg_callback_forwards_builtin_asr_when_source_mode_both():
    node = FakeNode()
    config = G1InterfaceConfig.default().with_asr_source_mode("both")
    bridge = G1InterfaceNode(node=node, config=config)
    raw = '{"text":"宇树，向前走一秒","confidence":0.95,"is_final":true,"index":1}'

    bridge.on_audio_msg(_string_msg(raw))

    published = node.publishers["/g1/audio/asr"].messages
    assert [msg.text for msg in published] == ["宇树，向前走一秒"]


class ManualMonotonicClock:
    def __init__(self, value=10.0):
        self.value = value

    def __call__(self):
        return self.value


def _sport_response(request, *, code=0, payload=None):
    from unitree_api.msg import Response

    response = Response()
    response.header.identity.id = request.header.identity.id
    response.header.identity.api_id = request.header.identity.api_id
    response.header.status = type("Status", (), {"code": code})()
    response.data = json.dumps(payload or {})
    return response


def _valid_loco(*, duration_sec=1.0, vx=0.2):
    sec = int(duration_sec)
    intent = LocoIntent(
        command_id="c1",
        vx=vx,
        vy=0.0,
        vyaw=0.0,
        duration=Duration(
            sec=sec,
            nanosec=int(round((duration_sec - sec) * 1_000_000_000)),
        ),
    )
    decision = SafetyDecision(
        command_id=intent.command_id,
        command_kind=SafetyDecision.KIND_LOCO,
        decision=SafetyDecision.DECISION_ALLOW,
    )
    return ValidatedLocoCommand(
        intent=intent,
        validated_at=Time(sec=10),
        validation=decision,
    )


def _valid_stop():
    intent = ActionIntent(
        command_id="stop1",
        action=ActionIntent.ACTION_STOP,
        priority=ActionIntent.PRIORITY_EMERGENCY,
    )
    decision = SafetyDecision(
        command_id=intent.command_id,
        command_kind=SafetyDecision.KIND_ACTION,
        decision=SafetyDecision.DECISION_ALLOW,
    )
    return ValidatedActionCommand(
        intent=intent,
        validated_at=Time(sec=10),
        validation=decision,
    )


def _ready_bridge():
    clock = ManualMonotonicClock(10.0)
    node = FakeNode()
    bridge = G1InterfaceNode(node=node, config=G1InterfaceConfig.default(), monotonic_clock=clock)
    bridge.last_lowstate_monotonic_sec = clock.value
    bridge.last_safety_heartbeat_monotonic_sec = clock.value
    bridge.last_successful_mode_query_monotonic_sec = clock.value
    bridge.mode = "sport_api_loco"
    bridge.control_owner = "internal"
    bridge.mode_source = "sport_api.get_fsm_mode"
    return clock, node, bridge


def test_textop_backend_does_not_construct_sport_command_bridge():
    node = FakeNode()
    bridge = G1InterfaceNode(
        node=node,
        config=G1InterfaceConfig.default().with_motion_backend("textop"),
        monotonic_clock=ManualMonotonicClock(),
    )

    assert bridge.motion_backend == "textop"
    assert "/api/sport/request" not in node.publishers
    assert "/g1/safe_cmd/loco" not in node.subscription_types
    assert "/g1/safe_cmd/stop" not in node.subscription_types
    assert all(callback != bridge.query_sport_mode for _, callback, _ in node.timers)
    assert all(callback != bridge.watchdog_tick for _, callback, _ in node.timers)


def test_textop_backend_shutdown_never_publishes_sport_stop():
    node = FakeNode()
    bridge = G1InterfaceNode(
        node=node,
        config=G1InterfaceConfig.default().with_motion_backend("textop"),
        monotonic_clock=ManualMonotonicClock(),
    )

    bridge.shutdown()

    assert "/api/sport/request" not in node.publishers


def test_textop_backend_health_timer_does_not_access_sport_client():
    node = FakeNode()
    bridge = G1InterfaceNode(
        node=node,
        config=G1InterfaceConfig.default().with_motion_backend("textop"),
        monotonic_clock=ManualMonotonicClock(),
    )

    bridge.publish_health()

    assert len(node.publishers["/g1/state/health"].messages) == 1


def _velocity_requests(node):
    return [json.loads(request.parameter)["velocity"] for request in node.publishers["/api/sport/request"].messages]


def test_g1_interface_subscribes_to_safety_heartbeat_and_creates_watchdog_timer():
    node = FakeNode()
    bridge = G1InterfaceNode(
        node=node,
        config=G1InterfaceConfig.default(),
        monotonic_clock=ManualMonotonicClock(),
    )

    safety_subscriptions = [topic for topic, callback in node.subscriptions if callback == bridge.on_safety_state]
    watchdog_timers = [(period, clock) for period, callback, clock in node.timers if callback == bridge.watchdog_tick]

    assert safety_subscriptions == ["/g1/state/safety"]
    assert node.subscription_types["/g1/state/safety"] is SafetyStatus
    assert node.subscription_types["/g1/safe_cmd/loco"] is ValidatedLocoCommand
    assert node.subscription_types["/g1/safe_cmd/stop"] is ValidatedActionCommand
    assert len(watchdog_timers) == 1
    assert watchdog_timers[0][0] == pytest.approx(0.05)
    assert watchdog_timers[0][1].clock_type == "steady_time"


def test_safety_heartbeat_accepts_only_safety_control_state():
    clock = ManualMonotonicClock(10.0)
    node = FakeNode()
    bridge = G1InterfaceNode(node=node, config=G1InterfaceConfig.default(), monotonic_clock=clock)

    bridge.on_safety_state(SafetyStatus(node_name="other"))
    assert bridge.last_safety_heartbeat_monotonic_sec is None

    clock.value = 10.2
    bridge.on_safety_state(SafetyStatus(node_name="safety_control", enabled=True))
    assert bridge.last_safety_heartbeat_monotonic_sec == 10.2


def test_successful_mode_response_updates_monotonic_freshness():
    clock = ManualMonotonicClock(10.0)
    node = FakeNode()
    bridge = G1InterfaceNode(node=node, config=G1InterfaceConfig.default(), monotonic_clock=clock)
    bridge.consecutive_api_timeouts = 2

    bridge.query_sport_mode()
    request = next(
        item for item in node.publishers["/api/sport/request"].messages if item.header.identity.api_id == 7002
    )
    clock.value = 10.1
    bridge.on_sport_response(_sport_response(request, payload={"data": 2}))

    assert bridge.last_sport_response_monotonic_sec == 10.1
    assert bridge.last_successful_mode_query_monotonic_sec == 10.1
    assert bridge.consecutive_api_timeouts == 0
    assert bridge.last_api_result["latency_ms"] == 100
    assert bridge.mode == "sport_api_loco"


def test_mode_staleness_rejects_new_loco_command():
    clock, node, bridge = _ready_bridge()
    bridge.last_successful_mode_query_monotonic_sec = 8.0

    bridge.on_safe_loco(_valid_loco())

    assert node.publishers["/api/sport/request"].messages == []
    assert node.logger.warnings[-1] == "rejecting safe_loco: sport mode stale: age_ms=2000"


def test_motion_deadline_publishes_zero_velocity_once():
    clock, node, bridge = _ready_bridge()
    bridge.on_safe_loco(_valid_loco(duration_sec=1.0))
    motion_request = node.publishers["/api/sport/request"].messages[-1]
    clock.value = 10.1
    bridge.on_sport_response(_sport_response(motion_request))

    clock.value = 11.01
    bridge.last_lowstate_monotonic_sec = clock.value
    bridge.last_safety_heartbeat_monotonic_sec = clock.value
    bridge.watchdog_tick()
    bridge.watchdog_tick()

    assert _velocity_requests(node) == [[0.2, 0.0, 0.0], [0.0, 0.0, 0.0]]
    assert bridge.last_command_ack["stop_reason"] == "command_deadline"
    assert bridge.commanded_velocity == {"vx": 0.0, "vy": 0.0, "vyaw": 0.0}


def test_safety_heartbeat_loss_stops_active_motion():
    clock, node, bridge = _ready_bridge()
    bridge.on_safe_loco(_valid_loco(duration_sec=2.0))
    motion_request = node.publishers["/api/sport/request"].messages[-1]
    clock.value = 10.1
    bridge.on_sport_response(_sport_response(motion_request))

    clock.value = 11.21
    bridge.last_lowstate_monotonic_sec = clock.value
    bridge.watchdog_tick()

    assert _velocity_requests(node)[-1] == [0.0, 0.0, 0.0]
    assert bridge.last_command_ack["stop_reason"] == "safety_heartbeat_lost"


def test_lowstate_loss_stops_active_motion():
    clock, node, bridge = _ready_bridge()
    bridge.on_safe_loco(_valid_loco(duration_sec=2.0))
    motion_request = node.publishers["/api/sport/request"].messages[-1]
    clock.value = 10.1
    bridge.on_sport_response(_sport_response(motion_request))

    clock.value = 10.31
    bridge.last_safety_heartbeat_monotonic_sec = clock.value
    bridge.watchdog_tick()

    assert _velocity_requests(node)[-1] == [0.0, 0.0, 0.0]
    assert bridge.last_command_ack["stop_reason"] == "lowstate_lost"


def test_unacknowledged_motion_timeout_triggers_stop():
    clock, node, bridge = _ready_bridge()
    bridge.on_safe_loco(_valid_loco(duration_sec=2.0))

    clock.value = 10.51
    bridge.last_lowstate_monotonic_sec = clock.value
    bridge.last_safety_heartbeat_monotonic_sec = clock.value
    bridge.watchdog_tick()

    assert _velocity_requests(node) == [[0.2, 0.0, 0.0], [0.0, 0.0, 0.0]]
    assert bridge.consecutive_api_timeouts == 1
    assert bridge.last_command_ack["command_kind"] == "stop"
    assert bridge.last_command_ack["stop_reason"] == "command_unacknowledged"


def test_rejected_motion_command_triggers_stop():
    clock, node, bridge = _ready_bridge()
    bridge.on_safe_loco(_valid_loco(duration_sec=2.0))
    motion_request = node.publishers["/api/sport/request"].messages[-1]

    clock.value = 10.1
    bridge.on_sport_response(_sport_response(motion_request, code=5))

    assert _velocity_requests(node) == [[0.2, 0.0, 0.0], [0.0, 0.0, 0.0]]
    assert bridge.last_command_ack["stop_reason"] == "command_rejected"


def test_safe_stop_bypasses_stale_state_gates():
    clock = ManualMonotonicClock(10.0)
    node = FakeNode()
    bridge = G1InterfaceNode(node=node, config=G1InterfaceConfig.default(), monotonic_clock=clock)

    bridge.on_safe_stop(_valid_stop())

    assert _velocity_requests(node) == [[0.0, 0.0, 0.0]]
    assert bridge.last_command_ack["command_kind"] == "stop"


def test_timed_out_stop_blocks_new_loco_until_stop_is_acknowledged():
    clock = ManualMonotonicClock(10.0)
    node = FakeNode()
    bridge = G1InterfaceNode(node=node, config=G1InterfaceConfig.default(), monotonic_clock=clock)
    bridge.on_safe_stop(_valid_stop())

    clock.value = 10.51
    bridge.watchdog_tick()
    bridge.last_lowstate_monotonic_sec = clock.value
    bridge.last_safety_heartbeat_monotonic_sec = clock.value
    bridge.last_successful_mode_query_monotonic_sec = clock.value
    bridge.mode = "sport_api_loco"
    bridge.control_owner = "internal"
    bridge.on_safe_loco(_valid_loco())

    assert _velocity_requests(node) == [[0.0, 0.0, 0.0]]
    assert node.logger.warnings[-1] == (
        "rejecting safe_loco: sport command acknowledgement unresolved: state=timed_out"
    )


def test_shutdown_publishes_stop_once():
    clock = ManualMonotonicClock(10.0)
    node = FakeNode()
    bridge = G1InterfaceNode(node=node, config=G1InterfaceConfig.default(), monotonic_clock=clock)

    bridge.shutdown()
    bridge.shutdown()

    assert _velocity_requests(node) == [[0.0, 0.0, 0.0]]
    assert bridge.last_command_ack["stop_reason"] == "shutdown"


def test_publish_health_exposes_watchdog_and_sport_fields():
    clock, node, bridge = _ready_bridge()

    bridge.publish_health()

    diagnostic = node.publishers["/g1/state/health"].messages[-1].status[0]
    values = {item.key: json.loads(item.value) for item in diagnostic.values}
    assert {
        "last_sport_response_age_ms",
        "last_successful_mode_query_age_ms",
        "consecutive_api_timeouts",
        "last_command_ack",
        "mode_fresh",
        "safety_control_age_ms",
        "safety_control_fresh",
        "dds_connection_state",
        "invalid_audio_event_count",
    }.issubset(values)


def test_main_shuts_down_bridge_before_destroying_node(monkeypatch):
    import rclpy

    events = []

    class RuntimeNode:
        def declare_parameter(self, name, default):
            return None

        def get_parameter(self, name):
            value = type("ParameterValue", (), {"string_value": ""})()
            return type("Parameter", (), {"get_parameter_value": lambda self: value})()

        def destroy_node(self):
            events.append("destroy_node")

    runtime_node = RuntimeNode()
    class Bridge:
        def __init__(self, node, config):
            assert node is runtime_node

        def shutdown(self):
            events.append("bridge_shutdown")

    monkeypatch.setattr(node_module, "G1InterfaceNode", Bridge)
    monkeypatch.setattr(
        rclpy,
        "init",
        lambda args=None: events.append(("rclpy_init", args)),
        raising=False,
    )
    monkeypatch.setattr(rclpy, "create_node", lambda name: runtime_node, raising=False)
    monkeypatch.setattr(rclpy, "spin", lambda node: (_ for _ in ()).throw(KeyboardInterrupt()), raising=False)
    monkeypatch.setattr(rclpy, "ok", lambda: True, raising=False)
    monkeypatch.setattr(rclpy, "shutdown", lambda: events.append("rclpy_shutdown"), raising=False)

    node_module.main()

    assert events == [
        ("rclpy_init", None),
        "bridge_shutdown",
        "destroy_node",
        "rclpy_shutdown",
    ]
