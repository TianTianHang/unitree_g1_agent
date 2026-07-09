from __future__ import annotations

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
        self.subscriptions = []
        self.timers = []
        self.logger = FakeLogger()

    def create_publisher(self, msg_type, topic, qos):
        publisher = FakePublisher()
        self.publishers[topic] = publisher
        return publisher

    def create_subscription(self, msg_type, topic, callback, qos):
        self.subscriptions.append((topic, callback))
        return callback

    def create_timer(self, period, callback):
        self.timers.append((period, callback))
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


def test_audio_msg_callback_forwards_asr_json_unchanged():
    node = FakeNode()
    bridge = G1InterfaceNode(node=node, config=G1InterfaceConfig.default())
    raw = '{"text":"宇树，向前走一秒","confidence":0.95,"is_final":true,"index":1}'

    bridge.on_audio_msg(_string_msg(raw))

    published = node.publishers["/g1/audio/asr"].messages
    assert [msg.data for msg in published] == [raw]
    assert node.publishers["/g1/audio/event"].messages == []


def test_audio_msg_callback_bridges_play_state_to_audio_event():
    node = FakeNode()
    bridge = G1InterfaceNode(node=node, config=G1InterfaceConfig.default())

    bridge.on_audio_msg(_string_msg('{"play_state":1}'))

    assert node.publishers["/g1/audio/asr"].messages == []
    published = node.publishers["/g1/audio/event"].messages
    assert [msg.data for msg in published] == ['{"play_state":1}']


def test_audio_msg_callback_bridges_empty_json_to_audio_event():
    node = FakeNode()
    bridge = G1InterfaceNode(node=node, config=G1InterfaceConfig.default())

    bridge.on_audio_msg(_string_msg("[1, 2, 3]"))

    assert node.publishers["/g1/audio/asr"].messages == []
    published = node.publishers["/g1/audio/event"].messages
    assert [msg.data for msg in published] == ["[1, 2, 3]"]


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
    assert [msg.data for msg in published] == ['{"play_state":1}']


def test_audio_msg_callback_forwards_builtin_asr_when_source_mode_both():
    node = FakeNode()
    config = G1InterfaceConfig.default().with_asr_source_mode("both")
    bridge = G1InterfaceNode(node=node, config=config)
    raw = '{"text":"宇树，向前走一秒","confidence":0.95,"is_final":true,"index":1}'

    bridge.on_audio_msg(_string_msg(raw))

    published = node.publishers["/g1/audio/asr"].messages
    assert [msg.data for msg in published] == [raw]
