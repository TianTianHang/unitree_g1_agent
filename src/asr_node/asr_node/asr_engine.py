"""ASR engine - faster-whisper speech recognition wrapper."""
from __future__ import annotations


class AsrEngine:
    """faster-whisper ASR engine for speech-to-text transcription."""

    def __init__(
        self,
        model_size: str = "medium",
        device: str = "cuda",
        compute_type: str = "float16",
        language: str = "zh",
        initial_prompt: str = "",
    ) -> None:
        from faster_whisper import WhisperModel

        self.language = language
        self.initial_prompt = initial_prompt
        self.model = WhisperModel(
            model_size,
            device=device,
            compute_type=compute_type,
        )

    def transcribe(self, pcm_int16: bytes, sample_rate: int = 16000) -> str:
        """Transcribe 16-bit LE PCM audio to text."""
        import numpy as np

        audio = np.frombuffer(pcm_int16, dtype=np.int16).astype(np.float32) / 32768.0

        segments, _info = self.model.transcribe(
            audio,
            language=self.language,
            initial_prompt=self.initial_prompt if self.initial_prompt else None,
            beam_size=5,
            vad_filter=False,
        )

        return " ".join(seg.text.strip() for seg in segments if seg.text.strip())
