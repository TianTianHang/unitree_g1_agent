"""Tests for asr_node.buffer - SpeechBuffer state machine."""
from asr_node.buffer import SpeechBuffer, SpeechSegment


def _make_chunk(sample_rate: int = 16000, duration_ms: int = 160) -> bytes:
    """Generate a silent PCM chunk of given duration."""
    num_samples = sample_rate * duration_ms // 1000
    return b"\x00\x00" * num_samples


def test_bytes_per_ms_calculation():
    """16kHz 16-bit mono = 32 bytes/ms."""
    buf = SpeechBuffer(
        sample_rate=16000,
        max_silence_duration_ms=800,
        max_speech_duration_ms=15000,
        padding_ms=200,
    )
    assert buf.bytes_per_second == 32000
    assert buf.bytes_per_ms == 32
    assert buf.max_silence_bytes == 800 * 32
    assert buf.max_speech_bytes == 15000 * 32
    assert buf.padding_bytes == 200 * 32


def test_idle_state_no_segment_on_silence():
    buf = SpeechBuffer(
        sample_rate=16000,
        max_silence_duration_ms=800,
        max_speech_duration_ms=15000,
        padding_ms=200,
    )
    chunk = _make_chunk()
    result = buf.add_silence(chunk)
    assert result is None


def test_speech_transitions_to_recording():
    buf = SpeechBuffer(
        sample_rate=16000,
        max_silence_duration_ms=800,
        max_speech_duration_ms=15000,
        padding_ms=200,
    )
    chunk = _make_chunk()
    result = buf.add_speech(chunk)
    assert result is None
    assert buf._recording is True


def test_short_speech_discarded_on_silence_timeout():
    """Speech segment below min_speech_duration_ms should be discarded."""
    buf = SpeechBuffer(
        sample_rate=16000,
        min_speech_duration_ms=300,
        max_silence_duration_ms=200,
        max_speech_duration_ms=15000,
        padding_ms=0,
    )
    short_chunk = _make_chunk(duration_ms=160)
    buf.add_speech(short_chunk)
    silence = _make_chunk(duration_ms=200)
    result = buf.add_silence(silence)
    assert result is None
    assert buf._recording is False


def test_normal_speech_returns_segment():
    """500ms speech + 800ms silence returns a segment."""
    buf = SpeechBuffer(
        sample_rate=16000,
        min_speech_duration_ms=300,
        max_silence_duration_ms=800,
        max_speech_duration_ms=15000,
        padding_ms=200,
    )
    speech = _make_chunk(duration_ms=500)
    buf.add_speech(speech)
    silence = _make_chunk(duration_ms=800)
    result = buf.add_silence(silence)
    assert result is not None
    assert isinstance(result, SpeechSegment)
    assert result.sample_rate == 16000
    assert 600 <= result.duration_ms <= 800
    assert buf._recording is False


def test_long_speech_triggers_flush():
    """add_speech returns a segment when max_speech_duration_ms is exceeded."""
    buf = SpeechBuffer(
        sample_rate=16000,
        min_speech_duration_ms=100,
        max_silence_duration_ms=800,
        max_speech_duration_ms=500,
        padding_ms=0,
    )
    for _ in range(3):
        buf.add_speech(_make_chunk(duration_ms=160))
    result = buf.add_speech(_make_chunk(duration_ms=160))
    assert result is not None
    assert isinstance(result, SpeechSegment)
    assert result.duration_ms >= 500


def test_segment_includes_padding():
    """Completed segment includes trailing padding silence."""
    buf = SpeechBuffer(
        sample_rate=16000,
        min_speech_duration_ms=100,
        max_silence_duration_ms=100,
        max_speech_duration_ms=15000,
        padding_ms=160,
    )
    buf.add_speech(_make_chunk(duration_ms=160))
    result = buf.add_silence(_make_chunk(duration_ms=160))
    assert result is not None
    assert result.duration_ms >= 160


def test_force_complete_ignores_min_duration():
    """force_complete does not check min_speech_duration_ms."""
    buf = SpeechBuffer(
        sample_rate=16000,
        min_speech_duration_ms=1000,
        max_silence_duration_ms=800,
        max_speech_duration_ms=15000,
        padding_ms=0,
    )
    buf.add_speech(_make_chunk(duration_ms=160))
    result = buf.force_complete()
    assert result is not None
    assert isinstance(result, SpeechSegment)
    assert result.duration_ms == 160


def test_force_complete_no_recording_returns_none():
    buf = SpeechBuffer(
        sample_rate=16000,
        max_silence_duration_ms=800,
        max_speech_duration_ms=15000,
        padding_ms=0,
    )
    result = buf.force_complete()
    assert result is None


def test_multiple_segments_sequentially():
    """Multiple speech segments can be produced sequentially."""
    buf = SpeechBuffer(
        sample_rate=16000,
        min_speech_duration_ms=100,
        max_silence_duration_ms=100,
        max_speech_duration_ms=15000,
        padding_ms=0,
    )
    buf.add_speech(_make_chunk(duration_ms=160))
    seg1 = buf.add_silence(_make_chunk(duration_ms=100))
    assert seg1 is not None

    buf.add_speech(_make_chunk(duration_ms=160))
    seg2 = buf.add_silence(_make_chunk(duration_ms=100))
    assert seg2 is not None

    assert seg1 is not seg2


def test_segment_padding_uses_accumulated_silence_buffer():
    buf = SpeechBuffer(
        sample_rate=16000,
        min_speech_duration_ms=100,
        max_silence_duration_ms=300,
        max_speech_duration_ms=15000,
        padding_ms=200,
    )
    speech = b"\x01\x00" * (16000 * 200 // 1000)
    silence_a = b"\x02\x00" * (16000 * 160 // 1000)
    silence_b = b"\x03\x00" * (16000 * 160 // 1000)

    buf.add_speech(speech)
    assert buf.add_silence(silence_a) is None
    result = buf.add_silence(silence_b)

    assert result is not None
    expected_padding_bytes = 200 * 32
    assert result.pcm_int16.endswith((silence_a + silence_b)[-expected_padding_bytes:])
