"""Silero VAD wrapper - voice activity detection on PCM audio chunks."""
from __future__ import annotations

from typing import Any

_model: Any | None = None
_utils = None


def _ensure_model() -> None:
    """Lazily load the Silero VAD model."""
    global _model, _utils
    if _model is not None:
        return
    import torch

    _model, _utils = torch.hub.load(
        repo_or_dir="snakers4/silero-vad",
        model="silero_vad",
        trust_repo=True,
    )


class SileroVAD:
    """Voice activity detector based on Silero VAD."""

    def __init__(
        self,
        threshold: float = 0.5,
        sample_rate: int = 16000,
        min_speech_duration_ms: int = 300,
        max_silence_duration_ms: int = 800,
        min_audio_after_silence_ms: int = 200,
        max_speech_duration_ms: int = 15000,
    ) -> None:
        self.threshold = threshold
        self.sample_rate = sample_rate
        self.min_speech_duration_ms = min_speech_duration_ms
        self.max_silence_duration_ms = max_silence_duration_ms
        self.min_audio_after_silence_ms = min_audio_after_silence_ms
        self.max_speech_duration_ms = max_speech_duration_ms

        _ensure_model()

    def _window_size_samples(self) -> int:
        if self.sample_rate == 16000:
            return 512
        if self.sample_rate == 8000:
            return 256
        raise ValueError(f"unsupported VAD sample_rate: {self.sample_rate}")

    def detect(self, pcm_bytes: bytes) -> bool:
        """Detect whether a 16-bit LE PCM chunk contains speech."""
        import numpy as np
        import torch

        audio = np.frombuffer(pcm_bytes, dtype=np.int16).astype(np.float32) / 32768.0
        model = _model
        if model is None:
            raise RuntimeError("Silero VAD model is not loaded")
        window = self._window_size_samples()
        if audio.size == 0:
            return False

        probabilities = []
        for start in range(0, audio.size, window):
            chunk = audio[start : start + window]
            if chunk.size < window:
                chunk = np.pad(chunk, (0, window - chunk.size))
            tensor = torch.from_numpy(chunk)
            probabilities.append(float(model(tensor, self.sample_rate).item()))

        return max(probabilities, default=0.0) > self.threshold
