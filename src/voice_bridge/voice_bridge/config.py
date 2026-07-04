from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml


DEFAULT_CONFIG: dict[str, dict[str, Any]] = {
    "voice": {
        "wake_words": ["宇树", "小宇"],
        "stop_words": ["停止", "停下", "别动", "取消", "stop"],
        "idle_timeout_sec": 20.0,
        "max_session_sec": 300.0,
        "min_confidence": 0.5,
        "process_partial": False,
    },
    "motion_defaults": {
        "default_vx": 0.25,
        "default_vy": 0.15,
        "default_vyaw": 0.5,
        "default_motion_duration_sec": 1.0,
        "max_motion_duration_sec": 2.0,
    },
    "agent": {
        "backend": "rule_based",
        "http_endpoint": "",
        "timeout_sec": 2.0,
    },
    "topics": {
        "asr": "/g1/audio/asr",
        "voice_loco": "/voice/cmd/loco",
        "voice_action": "/voice/cmd/action",
        "tts": "/g1/cmd/audio/tts",
        "led": "/g1/cmd/audio/led",
        "voice_state": "/voice/state",
        "robot_mode": "/g1/state/mode",
        "safety_state": "/g1/state/safety",
        "health": "/g1/state/health",
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


def _require_number(mapping: dict[str, Any], key: str, *, positive: bool = False) -> None:
    value = mapping.get(key)
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError(f"{key} must be numeric")
    if positive and value <= 0:
        raise ValueError(f"{key} must be positive")


def _require_string_list(mapping: dict[str, Any], key: str) -> None:
    value = mapping.get(key)
    if not isinstance(value, list) or not value or any(not isinstance(item, str) or not item for item in value):
        raise ValueError(f"{key} must be a non-empty string list")


@dataclass(frozen=True)
class VoiceBridgeConfig:
    voice: dict[str, Any]
    motion_defaults: dict[str, Any]
    agent: dict[str, Any]
    topics: dict[str, str]

    @classmethod
    def default(cls) -> "VoiceBridgeConfig":
        return cls._from_dict(deepcopy(DEFAULT_CONFIG))

    @classmethod
    def from_yaml(cls, path: str | Path) -> "VoiceBridgeConfig":
        with Path(path).open("r", encoding="utf-8") as handle:
            loaded = yaml.safe_load(handle) or {}
        if not isinstance(loaded, dict):
            raise ValueError("config root must be a mapping")
        return cls._from_dict(_deep_merge(DEFAULT_CONFIG, loaded))

    @classmethod
    def _from_dict(cls, raw: dict[str, Any]) -> "VoiceBridgeConfig":
        config = cls(
            voice=dict(raw["voice"]),
            motion_defaults=dict(raw["motion_defaults"]),
            agent=dict(raw["agent"]),
            topics=dict(raw["topics"]),
        )
        config.validate()
        return config

    def validate(self) -> None:
        _require_string_list(self.voice, "wake_words")
        _require_string_list(self.voice, "stop_words")
        _require_number(self.voice, "idle_timeout_sec", positive=True)
        _require_number(self.voice, "max_session_sec", positive=True)
        _require_number(self.voice, "min_confidence")
        if not 0.0 <= float(self.voice["min_confidence"]) <= 1.0:
            raise ValueError("min_confidence must be between 0 and 1")
        if not isinstance(self.voice.get("process_partial"), bool):
            raise ValueError("process_partial must be boolean")

        for key in [
            "default_vx",
            "default_vy",
            "default_vyaw",
            "default_motion_duration_sec",
            "max_motion_duration_sec",
        ]:
            _require_number(self.motion_defaults, key, positive=True)
        if self.motion_defaults["default_motion_duration_sec"] > self.motion_defaults["max_motion_duration_sec"]:
            raise ValueError("default_motion_duration_sec must not exceed max_motion_duration_sec")

        backend = self.agent.get("backend")
        if backend not in {"rule_based", "http_json", "disabled"}:
            raise ValueError(f"unsupported agent backend: {backend}")
        _require_number(self.agent, "timeout_sec", positive=True)
        if backend == "http_json" and not self.agent.get("http_endpoint"):
            raise ValueError("http_json backend requires http_endpoint")

        required_topics = [
            "asr",
            "voice_loco",
            "voice_action",
            "tts",
            "led",
            "voice_state",
            "robot_mode",
            "safety_state",
            "health",
        ]
        missing = [key for key in required_topics if not isinstance(self.topics.get(key), str) or not self.topics[key]]
        if missing:
            raise ValueError(f"missing topic config: {', '.join(missing)}")
