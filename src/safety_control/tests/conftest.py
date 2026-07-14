from types import SimpleNamespace

import pytest
from builtin_interfaces.msg import Duration, Time
from diagnostic_msgs.msg import DiagnosticArray, DiagnosticStatus

from g1_agent_msgs.msg import ActionIntent, LocoIntent, RobotStateSummary
from safety_control.config import SafetyControlConfig
from safety_control.node import SafetyControlNode


class FakePublisher:
    def __init__(self):
        self.messages = []

    def publish(self, msg):
        self.messages.append(msg)


class FakeNow:
    nanoseconds = 10_000_000_000

    def to_msg(self):
        return Time(sec=10)


class FakeClock:
    def now(self):
        return FakeNow()


class FakeLogger:
    def warning(self, message):
        self.last_warning = message


class FakeNode:
    def __init__(self):
        self.publishers = {}
        self.subscriptions = []

    def create_publisher(self, msg_type, topic, depth):
        del msg_type, depth
        self.publishers[topic] = FakePublisher()
        return self.publishers[topic]

    def create_subscription(self, msg_type, topic, callback, depth):
        del depth
        self.subscriptions.append((msg_type, topic, callback))

    def create_timer(self, period, callback):
        return (period, callback)

    def get_clock(self):
        return FakeClock()

    def get_logger(self):
        return FakeLogger()


@pytest.fixture
def bridge_node():
    node = FakeNode()
    return SimpleNamespace(
        node=node,
        bridge=SafetyControlNode(node, SafetyControlConfig.default()),
        publishers=node.publishers,
    )


@pytest.fixture
def ready_node(bridge_node):
    summary = RobotStateSummary(
        stamp=Time(sec=10),
        mode=RobotStateSummary.MODE_SPORT_API_LOCO,
        motor_count=35,
        has_max_temperature=True,
        max_temperature_c=40.0,
    )
    bridge_node.bridge.on_lowstate(summary)
    bridge_node.bridge.on_robot_mode(summary)
    health = DiagnosticArray()
    status = DiagnosticStatus()
    status.level = DiagnosticStatus.OK
    status.message = "ok"
    health.status.append(status)
    bridge_node.bridge.on_health(health)
    return bridge_node


@pytest.fixture
def loco_msg():
    return LocoIntent(
        created_at=Time(sec=9, nanosec=950_000_000),
        source="voice_bridge",
        session_id="s1",
        command_id="c1",
        text="向前",
        vx=0.2,
        vy=0.0,
        vyaw=0.0,
        duration=Duration(sec=1),
    )


@pytest.fixture
def stop_msg():
    return ActionIntent(
        created_at=Time(sec=10),
        source="voice_bridge",
        session_id="s1",
        command_id="stop1",
        text="停止",
        action=ActionIntent.ACTION_STOP,
        priority=ActionIntent.PRIORITY_EMERGENCY,
    )
