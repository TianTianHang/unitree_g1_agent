"""Speech buffer - VAD-driven state machine for segmenting PCM audio."""
from __future__ import annotations

from dataclasses import dataclass


@dataclass
class SpeechSegment:
    """A completed speech recording."""

    pcm_int16: bytes
    sample_rate: int = 16000
    duration_ms: int = 0


class SpeechBuffer:
    """VAD-driven state machine that accumulates PCM audio into speech segments."""

    def __init__(
        self,
        sample_rate: int = 16000,
        min_speech_duration_ms: int = 300,
        max_silence_duration_ms: int = 800,
        max_speech_duration_ms: int = 15000,
        padding_ms: int = 200,
    ) -> None:
        self.sample_rate = sample_rate
        self.bytes_per_second = sample_rate * 2
        self.bytes_per_ms = self.bytes_per_second // 1000
        self.max_silence_bytes = max_silence_duration_ms * self.bytes_per_ms
        self.max_speech_bytes = max_speech_duration_ms * self.bytes_per_ms
        self.padding_bytes = padding_ms * self.bytes_per_ms
        self.min_speech_bytes = min_speech_duration_ms * self.bytes_per_ms

        self._buffer: bytearray = bytearray()
        self._silence_buffer: bytearray = bytearray()
        self._recording = False

    def add_speech(self, pcm_bytes: bytes) -> SpeechSegment | None:
        """Add a PCM chunk that contains speech."""
        self._recording = True
        self._silence_buffer.clear()
        self._buffer.extend(pcm_bytes)

        if len(self._buffer) >= self.max_speech_bytes:
            return self._flush()

        return None

    def add_silence(self, pcm_bytes: bytes) -> SpeechSegment | None:
        """Add a PCM chunk that contains silence."""
        if not self._recording:
            return None

        self._silence_buffer.extend(pcm_bytes)

        if len(self._silence_buffer) >= self.max_silence_bytes:
            if len(self._buffer) < self.min_speech_bytes:
                self._discard()
                return None
            keep = min(self.padding_bytes, len(self._silence_buffer))
            if keep > 0:
                self._buffer.extend(self._silence_buffer[-keep:])
            return self._flush()

        return None

    def force_complete(self) -> SpeechSegment | None:
        """Force-flush the current recording, ignoring minimum duration."""
        if self._recording and self._buffer:
            return self._flush()
        return None

    def _discard(self) -> None:
        self._buffer.clear()
        self._silence_buffer.clear()
        self._recording = False

    def _flush(self) -> SpeechSegment:
        segment = SpeechSegment(
            pcm_int16=bytes(self._buffer),
            sample_rate=self.sample_rate,
            duration_ms=len(self._buffer) // self.bytes_per_ms,
        )
        self._buffer.clear()
        self._silence_buffer.clear()
        self._recording = False
        return segment
