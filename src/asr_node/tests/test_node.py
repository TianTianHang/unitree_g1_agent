"""Tests for asr_node.node - AsrNode pipeline wiring."""
import json
import queue
import sys
import threading
import types
from unittest.mock import MagicMock

from asr_node.config import AsrNodeConfig


class String:
    def __init__(self):
        self.data = ""


def _install_fake_ros_modules():
    std_msgs = types.ModuleType("std_msgs")
    std_msgs_msg = types.ModuleType("std_msgs.msg")
    std_msgs_msg.String = String
    sys.modules.setdefault("std_msgs", std_msgs)
    sys.modules.setdefault("std_msgs.msg", std_msgs_msg)


_install_fake_ros_modules()

from asr_node.node import AsrNode, _STOP_SENTINEL


def _make_config(**overrides) -> AsrNodeConfig:
    raw = {
        "model": {
            "size": "tiny",
            "device": "cpu",
            "compute_type": "int8",
            "language": "zh",
            "initial_prompt": "",
        },
        "vad": {
            "threshold": 0.5,
            "min_speech_duration_ms": 100,
            "max_silence_duration_ms": 100,
            "min_audio_after_silence_ms": 0,
            "max_speech_duration_ms": 15000,
        },
        "capture": {
            "multicast_group": "239.0.0.1",
            "multicast_port": 15599,
            "sample_rate": 16000,
            "recv_buffer_size": 1024,
            "network_prefix": "127.0.0.",
        },
        "topics": {"asr_output": "/g1/audio/asr"},
        "output": {"source": "custom_asr"},
    }
    raw.update(overrides)
    return AsrNodeConfig._from_dict(raw)


def _make_uninitialized_node(config: AsrNodeConfig, mock_pub: MagicMock) -> AsrNode:
    node = AsrNode.__new__(AsrNode)
    node.node = MagicMock()
    node.node.get_logger.return_value = MagicMock()
    node.config = config
    node.msg = {"String": String}
    node._msg_counter = 0
    node._lock = threading.Lock()
    node._asr_pub = mock_pub
    return node


def test_transcribe_and_publish_empty_text_skipped():
    """Empty transcription result is not published."""
    mock_pub = MagicMock()
    node = _make_uninitialized_node(_make_config(), mock_pub)
    node._engine = MagicMock()
    node._engine.transcribe.return_value = ""

    from asr_node.buffer import SpeechSegment

    seg = SpeechSegment(pcm_int16=b"\x00" * 320, sample_rate=16000, duration_ms=10)

    node._transcribe_and_publish(seg)
    mock_pub.publish.assert_not_called()


def test_transcribe_and_publish_formats_json():
    """Successful transcription publishes correct JSON."""
    mock_pub = MagicMock()
    node = _make_uninitialized_node(_make_config(), mock_pub)
    node._engine = MagicMock()
    node._engine.transcribe.return_value = "向前走"

    from asr_node.buffer import SpeechSegment

    seg = SpeechSegment(pcm_int16=b"\x00" * 3200, sample_rate=16000, duration_ms=100)

    node._transcribe_and_publish(seg)

    assert mock_pub.publish.call_count == 1
    msg = mock_pub.publish.call_args[0][0]
    payload = json.loads(msg.data)
    assert payload["text"] == "向前走"
    assert payload["is_final"] is True
    assert payload["source"] == "custom_asr"
    assert payload["language"] == "zh"
    assert payload["index"] == 1


def test_transcribe_and_publish_index_increments():
    """Index increments on each publish."""
    mock_pub = MagicMock()
    node = _make_uninitialized_node(_make_config(), mock_pub)
    node._engine = MagicMock()
    node._engine.transcribe.return_value = "测试"

    from asr_node.buffer import SpeechSegment

    seg = SpeechSegment(pcm_int16=b"\x00" * 3200, sample_rate=16000, duration_ms=100)

    node._transcribe_and_publish(seg)
    node._transcribe_and_publish(seg)
    node._transcribe_and_publish(seg)

    payloads = [
        json.loads(mock_pub.publish.call_args_list[i][0][0].data)
        for i in range(3)
    ]
    assert payloads[0]["index"] == 1
    assert payloads[1]["index"] == 2
    assert payloads[2]["index"] == 3


def test_transcribe_and_publish_no_confidence_field():
    """Published JSON does not contain a confidence field."""
    mock_pub = MagicMock()
    node = _make_uninitialized_node(_make_config(), mock_pub)
    node._engine = MagicMock()
    node._engine.transcribe.return_value = "你好"

    from asr_node.buffer import SpeechSegment

    seg = SpeechSegment(pcm_int16=b"\x00" * 3200, sample_rate=16000, duration_ms=100)

    node._transcribe_and_publish(seg)
    payload = json.loads(mock_pub.publish.call_args[0][0].data)
    assert "confidence" not in payload


def test_process_loop_flushes_on_sentinel():
    """Processing thread flushes residual audio and forwards sentinel."""
    mock_pub = MagicMock()
    node = _make_uninitialized_node(_make_config(), mock_pub)
    node._pcm_queue = queue.Queue()
    node._segment_queue = queue.Queue()
    node._vad = MagicMock()
    node._vad.detect.return_value = False
    node._buffer = MagicMock()
    seg = object()
    node._buffer.force_complete.return_value = seg

    node._pcm_queue.put(_STOP_SENTINEL)
    node._process_loop()

    assert node._segment_queue.get() is seg
    assert node._segment_queue.get() is _STOP_SENTINEL


def test_process_loop_routes_segments_to_segment_queue():
    """Completed segments are put into segment_queue."""
    mock_pub = MagicMock()
    node = _make_uninitialized_node(_make_config(), mock_pub)
    node._pcm_queue = queue.Queue()
    node._segment_queue = queue.Queue()

    from asr_node.buffer import SpeechBuffer, SpeechSegment

    node._vad = MagicMock()
    node._buffer = SpeechBuffer(
        sample_rate=16000,
        min_speech_duration_ms=50,
        max_silence_duration_ms=50,
        max_speech_duration_ms=15000,
        padding_ms=0,
    )

    node._vad.detect.side_effect = [True, False]
    node._pcm_queue.put(b"\x00\x01" * 800)
    node._pcm_queue.put(b"\x00\x00" * 800)
    node._pcm_queue.put(_STOP_SENTINEL)
    node._process_loop()

    result = node._segment_queue.get_nowait()
    sentinel = node._segment_queue.get_nowait()
    assert isinstance(result, SpeechSegment)
    assert sentinel is _STOP_SENTINEL


def test_process_loop_logs_vad_error_and_continues():
    mock_pub = MagicMock()
    node = _make_uninitialized_node(_make_config(), mock_pub)
    node._pcm_queue = queue.Queue()
    node._segment_queue = queue.Queue()
    node._vad = MagicMock()
    node._vad.detect.side_effect = [RuntimeError("bad vad input"), False]
    node._buffer = MagicMock()
    node._buffer.add_silence.return_value = None
    node._buffer.force_complete.return_value = None

    node._pcm_queue.put(b"\x00\x00" * 2560)
    node._pcm_queue.put(b"\x00\x00" * 2560)
    node._pcm_queue.put(_STOP_SENTINEL)
    node._process_loop()

    warnings = [call.args[0] for call in node.node.get_logger.return_value.warning.call_args_list]
    assert any("VAD detection failed" in warning for warning in warnings)
    assert node._segment_queue.get_nowait() is _STOP_SENTINEL


def test_stop_logs_warning_when_pcm_queue_full():
    mock_pub = MagicMock()
    node = _make_uninitialized_node(_make_config(), mock_pub)
    node._capture = MagicMock()
    node._pcm_queue = queue.Queue(maxsize=1)
    node._pcm_queue.put(b"full")

    node.stop()

    warnings = [call.args[0] for call in node.node.get_logger.return_value.warning.call_args_list]
    assert any("pcm queue full during shutdown" in warning for warning in warnings)
