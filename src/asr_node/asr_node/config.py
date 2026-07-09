"""ASR node configuration."""
from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml


DEFAULT_CONFIG: dict[str, dict[str, Any]] = {
    "model": {
        "size": "medium",
        "device": "cuda",
        "compute_type": "float16",
        "language": "zh",
        "initial_prompt": (
            "以下是机器人常用指令词汇: "
            "宇树, 向前, 后退, 左转, 右转, 停止, 停下, "
            "蹲下, 站起来, 挥手, 鞠躬, 走一圈, 加速, 减速, 别动, 取消"
        ),
    },
    "vad": {
        "threshold": 0.5,
        "min_speech_duration_ms": 300,
        "max_silence_duration_ms": 800,
        "min_audio_after_silence_ms": 200,
        "max_speech_duration_ms": 15000,
    },
    "capture": {
        "multicast_group": "239.168.123.161",
        "multicast_port": 5555,
        "sample_rate": 16000,
        "recv_buffer_size": 8192,
        "network_prefix": "192.168.123.",
    },
    "topics": {
        "asr_output": "/g1/audio/asr",
    },
    "output": {
        "source": "custom_asr",
    },
}


def _deep_merge(base: dict[str, Any], override: dict[str, Any]) -> dict[str, Any]:
    merged = deepcopy(base)
    for key, value in override.items():
        if isinstance(value, dict) and isinstance(merged.get(key), dict):
            merged[key] = _deep_merge(merged[key], value)
        else:
            merged[key] = value
    return merged


@dataclass(frozen=True)
class AsrNodeConfig:
    model: dict[str, Any]
    vad: dict[str, Any]
    capture: dict[str, Any]
    topics: dict[str, str]
    output: dict[str, str]

    @classmethod
    def default(cls) -> AsrNodeConfig:
        return cls._from_dict(deepcopy(DEFAULT_CONFIG))

    @classmethod
    def from_yaml(cls, path: str | Path) -> AsrNodeConfig:
        p = Path(path)
        if not p.exists():
            raise FileNotFoundError(f"config file not found: {path}")
        with p.open("r", encoding="utf-8") as f:
            loaded = yaml.safe_load(f) or {}
        if not isinstance(loaded, dict):
            raise ValueError("config root must be a mapping")
        merged = _deep_merge(DEFAULT_CONFIG, loaded)
        return cls._from_dict(merged)

    @classmethod
    def _from_dict(cls, raw: dict[str, Any]) -> AsrNodeConfig:
        config = cls(
            model=dict(raw["model"]),
            vad=dict(raw["vad"]),
            capture=dict(raw["capture"]),
            topics=dict(raw["topics"]),
            output=dict(raw["output"]),
        )
        config.validate()
        return config

    def validate(self) -> None:
        if self.model["device"] not in ("cuda", "cpu"):
            raise ValueError(f"unsupported device: {self.model['device']}")
        if self.model["size"] not in ("tiny", "base", "small", "medium", "large-v3"):
            raise ValueError(f"unsupported model size: {self.model['size']}")
        if not self.topics.get("asr_output"):
            raise ValueError("missing topic config: asr_output")
        threshold = self.vad.get("threshold")
        if threshold is not None and not (0.0 < threshold < 1.0):
            raise ValueError(f"vad threshold must be in (0, 1): {threshold}")
