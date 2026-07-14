import json
import sys
import types
from unittest.mock import MagicMock

from g1_sim.config import G1SimConfig


class String:
    def __init__(self):
        self.data = ""


class _Identity:
    def __init__(self):
        self.id = 0
        self.api_id = 0


class _Status:
    def __init__(self):
        self.code = 0


class _Header:
    def __init__(self):
        self.identity = _Identity()
        self.status = _Status()


class Request:
    def __init__(self):
        self.header = _Header()
        self.parameter = ""


class Response:
    def __init__(self):
        self.header = _Header()
        self.parameter = ""
        self.data = ""


class _EmptyMessage:
    pass


def _install_fake_ros_modules():
    std_msgs = types.ModuleType("std_msgs")
    std_msgs_msg = types.ModuleType("std_msgs.msg")
    std_msgs_msg.String = String
    unitree_api = types.ModuleType("unitree_api")
    unitree_api_msg = types.ModuleType("unitree_api.msg")
    unitree_api_msg.Request = Request
    unitree_api_msg.Response = Response
    unitree_hg = types.ModuleType("unitree_hg")
    unitree_hg_msg = types.ModuleType("unitree_hg.msg")
    for name in ["HandCmd", "HandState", "IMUState", "LowCmd", "LowState"]:
        setattr(unitree_hg_msg, name, type(name, (_EmptyMessage,), {}))

    sys.modules.setdefault("std_msgs", std_msgs)
    sys.modules.setdefault("std_msgs.msg", std_msgs_msg)
    sys.modules.setdefault("unitree_api", unitree_api)
    sys.modules.setdefault("unitree_api.msg", unitree_api_msg)
    sys.modules.setdefault("unitree_hg", unitree_hg)
    sys.modules.setdefault("unitree_hg.msg", unitree_hg_msg)


_install_fake_ros_modules()

from g1_sim.node import G1SimNode  # noqa: E402


def _make_node():
    mock_node = MagicMock()
    mock_node.create_publisher.return_value = MagicMock()
    mock_node.create_subscription = MagicMock()
    mock_node.create_timer = MagicMock()
    return mock_node, G1SimNode(mock_node, G1SimConfig.default())


def test_publish_asr_message_json_format():
    mock_node, node = _make_node()
    mock_clock = MagicMock()
    mock_clock.now.return_value.nanoseconds = 12345678900000000
    mock_node.get_clock.return_value = mock_clock

    published_messages = []
    node.audio_msg_pub.publish = lambda msg: published_messages.append(msg.data)

    node.publish_asr_message("测试文本")

    assert len(published_messages) == 1
    msg_data = json.loads(published_messages[0])
    assert msg_data["index"] == 1
    assert msg_data["timestamp"] == 12345678900000000
    assert msg_data["text"] == "测试文本"
    assert msg_data["angle"] == 90
    assert msg_data["speaker_id"] == 0
    assert msg_data["sense"] == "unknown"
    assert msg_data["confidence"] == 0.95
    assert msg_data["language"] == "zh-CN"
    assert msg_data["is_final"] is True
    assert node.state.asr_index == 1

    node.publish_asr_message("第二文本")
    assert json.loads(published_messages[1])["index"] == 2


def test_publish_asr_message_timestamp_is_int():
    mock_node, node = _make_node()
    mock_clock = MagicMock()
    mock_clock.now.return_value.nanoseconds = 12345678900000000
    mock_node.get_clock.return_value = mock_clock

    published_messages = []
    node.audio_msg_pub.publish = lambda msg: published_messages.append(msg.data)

    node.publish_asr_message("测试")

    msg_data = json.loads(published_messages[0])
    assert isinstance(msg_data["timestamp"], int)
    assert not isinstance(msg_data["timestamp"], float)


def test_publish_play_state_format():
    _, node = _make_node()
    published_messages = []
    node.audio_msg_pub.publish = lambda msg: published_messages.append(msg.data)

    node.publish_play_state(True)
    assert json.loads(published_messages[0]) == {"play_state": 1}

    node.publish_play_state(False)
    assert json.loads(published_messages[1]) == {"play_state": 0}


def test_on_asr_input_callback_non_empty_text():
    _, node = _make_node()
    asr_texts = []
    node.publish_asr_message = lambda text: asr_texts.append(text)

    msg = String()
    msg.data = "测试语音"
    node._on_asr_input_callback(msg)

    assert asr_texts == ["测试语音"]


def test_on_asr_input_callback_empty_text_ignored():
    _, node = _make_node()
    asr_texts = []
    node.publish_asr_message = lambda text: asr_texts.append(text)

    msg = String()
    msg.data = ""
    node._on_asr_input_callback(msg)
    msg.data = "   "
    node._on_asr_input_callback(msg)

    assert asr_texts == []


def test_init_creates_asr_input_subscription():
    mock_node = MagicMock()
    mock_node.create_publisher.return_value = MagicMock()
    mock_node.create_subscription = MagicMock()
    mock_node.create_timer = MagicMock()

    config = G1SimConfig.default()
    G1SimNode(mock_node, config)

    subscription_calls = [
        call
        for call in mock_node.create_subscription.call_args_list
        if len(call[0]) > 1 and call[0][1] == config.topics["asr_input"]
    ]
    assert len(subscription_calls) == 1
    assert subscription_calls[0][0][2].__name__ == "_on_asr_input_callback"


def test_on_voice_request_publishes_asr_on_success():
    _, node = _make_node()
    published_responses = []
    node.voice_response_pub.publish = lambda msg: published_responses.append(msg)
    published_asr = []
    node.publish_asr_message = lambda text: published_asr.append(text)

    req = Request()
    req.header.identity.id = 1
    req.header.identity.api_id = node.config.sim["voice_api_ids"]["asr"]
    req.parameter = json.dumps({"text": "API测试文本"})

    node.on_voice_request(req)

    assert published_asr == ["API测试文本"]
    assert len(published_responses) == 1


def test_on_voice_request_publishes_play_state_on_start_play():
    _, node = _make_node()
    published_play_states = []
    node.publish_play_state = lambda is_playing: published_play_states.append(is_playing)

    req = Request()
    req.header.identity.id = 1
    req.header.identity.api_id = node.config.sim["voice_api_ids"]["start_play"]
    req.parameter = json.dumps({"app_name": "test_app", "stream_id": "stream123"})

    node.on_voice_request(req)

    assert published_play_states == [True]


def test_on_voice_request_no_play_state_on_failed_stop():
    _, node = _make_node()
    published_play_states = []
    node.publish_play_state = lambda is_playing: published_play_states.append(is_playing)

    req = Request()
    req.header.identity.id = 1
    req.header.identity.api_id = node.config.sim["voice_api_ids"]["stop_play"]
    req.parameter = json.dumps({"app_name": "non_existent_app"})

    node.on_voice_request(req)

    assert published_play_states == []
