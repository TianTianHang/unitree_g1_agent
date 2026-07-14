"""Tests for asr_node.node - AsrNode pipeline wiring."""
import queue
import threading
from unittest.mock import MagicMock

from builtin_interfaces.msg import Time
from g1_agent_msgs.msg import VoiceEvent

from asr_node.config import AsrNodeConfig

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
    node.node.get_clock.return_value.now.return_value.to_msg.return_value = Time(sec=1)
    node.config = config
    node.msg = {"VoiceEvent": VoiceEvent}
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


def test_transcribe_and_publish_builds_voice_event():
    """Successful transcription publishes a typed voice event."""
    mock_pub = MagicMock()
    node = _make_uninitialized_node(_make_config(), mock_pub)
    node._engine = MagicMock()
    node._engine.transcribe.return_value = "向前走"

    from asr_node.buffer import SpeechSegment

    seg = SpeechSegment(pcm_int16=b"\x00" * 3200, sample_rate=16000, duration_ms=100)

    node._transcribe_and_publish(seg)

    msg = mock_pub.publish.call_args.args[0]
    assert msg.event_type == msg.EVENT_ASR
    assert msg.text == "向前走"
    assert msg.source == "custom_asr"
    assert msg.language == "zh"
    assert msg.is_final is True
    assert msg.has_sequence_id is True
    assert msg.sequence_id == 1
    assert msg.has_confidence is False
    assert msg.stamp.sec == 1


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

    messages = [mock_pub.publish.call_args_list[i].args[0] for i in range(3)]
    assert messages[0].sequence_id == 1
    assert messages[1].sequence_id == 2
    assert messages[2].sequence_id == 3


def test_transcribe_and_publish_marks_confidence_absent():
    """Published event marks confidence absent when the engine has none."""
    mock_pub = MagicMock()
    node = _make_uninitialized_node(_make_config(), mock_pub)
    node._engine = MagicMock()
    node._engine.transcribe.return_value = "你好"

    from asr_node.buffer import SpeechSegment

    seg = SpeechSegment(pcm_int16=b"\x00" * 3200, sample_rate=16000, duration_ms=100)

    node._transcribe_and_publish(seg)
    msg = mock_pub.publish.call_args.args[0]
    assert msg.has_confidence is False
    assert msg.confidence == 0.0


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
