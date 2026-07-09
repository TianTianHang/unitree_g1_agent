"""Tests for asr_node.vad - Silero VAD wrapper."""
import pytest

from asr_node.vad import SileroVAD


def _make_silence_pcm(num_samples: int = 2560) -> bytes:
    """Generate pure-silence PCM, 16-bit LE."""
    return b"\x00\x00" * num_samples


def _make_noise_pcm(num_samples: int = 2560, amplitude: int = 16000) -> bytes:
    """Generate loud noise PCM, 16-bit LE."""
    import struct

    samples = []
    for i in range(num_samples):
        val = amplitude if i % 2 == 0 else -amplitude
        samples.append(val)
    return b"".join(struct.pack("<h", s) for s in samples)


@pytest.mark.skipif(
    True,
    reason="Silero VAD requires torch - enable in GPU test environment",
)
def test_silence_detected_as_not_speech():
    vad = SileroVAD(threshold=0.5, sample_rate=16000)
    silence = _make_silence_pcm(2560)
    assert vad.detect(silence) is False


@pytest.mark.skipif(
    True,
    reason="Silero VAD requires torch - enable in GPU test environment",
)
def test_loud_noise_detected_as_speech():
    vad = SileroVAD(threshold=0.3, sample_rate=16000)
    noise = _make_noise_pcm(2560, amplitude=30000)
    assert vad.detect(noise) is True


@pytest.mark.skipif(
    True,
    reason="Silero VAD requires torch - enable in GPU test environment",
)
def test_detect_returns_bool():
    vad = SileroVAD(threshold=0.5, sample_rate=16000)
    silence = _make_silence_pcm(2560)
    result = vad.detect(silence)
    assert isinstance(result, bool)


def test_detect_splits_160ms_chunk_into_512_sample_windows(monkeypatch):
    import sys

    import asr_node.vad as vad_module

    calls = []

    class FakeTensor:
        def __init__(self, value):
            self._value = value

        def item(self):
            return self._value

    class FakeModel:
        def __call__(self, tensor, sample_rate):
            calls.append((len(tensor), sample_rate))
            return FakeTensor(0.6 if len(calls) == 2 else 0.1)

    class FakeTorch:
        @staticmethod
        def from_numpy(array):
            return array

    monkeypatch.setitem(sys.modules, "torch", FakeTorch)
    monkeypatch.setattr(vad_module, "_model", FakeModel())
    monkeypatch.setattr(vad_module, "_ensure_model", lambda: None)

    detector = SileroVAD(threshold=0.5, sample_rate=16000)
    pcm = b"\x00\x00" * 2560

    assert detector.detect(pcm) is True
    assert calls == [(512, 16000), (512, 16000), (512, 16000), (512, 16000), (512, 16000)]
