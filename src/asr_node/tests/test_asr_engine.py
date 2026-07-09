"""Tests for asr_node.asr_engine - faster-whisper wrapper."""
import pytest

GPU_AND_WHISPER = pytest.mark.skipif(
    True,
    reason="Requires faster-whisper + CUDA GPU",
)


@GPU_AND_WHISPER
def test_transcribe_returns_string():
    from asr_node.asr_engine import AsrEngine

    engine = AsrEngine(
        model_size="tiny",
        device="cuda",
        compute_type="float16",
        language="zh",
        initial_prompt="",
    )
    silence = b"\x00\x00" * 16000
    text = engine.transcribe(silence, sample_rate=16000)
    assert isinstance(text, str)
    assert text.strip() == "" or len(text) < 50


@GPU_AND_WHISPER
def test_transcribe_with_hotwords():
    from asr_node.asr_engine import AsrEngine

    engine = AsrEngine(
        model_size="tiny",
        device="cuda",
        compute_type="float16",
        language="zh",
        initial_prompt="停止,向前",
    )
    assert engine.language == "zh"
    assert engine.initial_prompt == "停止,向前"


def test_import_without_gpu():
    """Module can be imported even without faster-whisper installed."""
    import asr_node.asr_engine

    assert hasattr(asr_node.asr_engine, "AsrEngine")
