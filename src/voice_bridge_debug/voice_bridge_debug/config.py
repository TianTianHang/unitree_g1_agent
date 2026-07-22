from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml

DEFAULT_CONFIG: dict[str, Any] = {
    "server": {"host": "127.0.0.1", "port": 8765, "allow_remote": False},
    "topics": {
        "asr": "/g1/audio/asr",
        "voice_state": "/voice/state",
        "voice_debug_events": "/voice/debug/events",
        "robot_mode": "/g1/state/mode",
        "safety_state": "/g1/state/safety",
        "health": "/g1/state/health",
        "voice_cmd_loco": "/voice/cmd/loco",
        "voice_cmd_action": "/voice/cmd/action",
        "tts": "/g1/cmd/audio/tts",
        "led": "/g1/cmd/audio/led",
        "safe_cmd_loco": "/g1/safe_cmd/loco",
        "safe_cmd_stop": "/g1/safe_cmd/stop",
        "safety_decisions": "/g1/safety/decisions",
    },
    "defaults": {"asr_confidence": 0.9, "asr_is_final": True, "asr_source": "debug"},
    "timeline": {"max_events": 200, "state_timeout_ms": 2000},
    "asr_default_text": "小宇",
}


def _deep_merge(base: dict[str, Any], override: dict[str, Any]) -> dict[str, Any]:
    merged = deepcopy(base)
    for key, value in override.items():
        if isinstance(value, dict) and isinstance(merged.get(key), dict):
            merged[key] = _deep_merge(merged[key], value)
        else:
            merged[key] = value
    return merged


def _is_loopback(host: str) -> bool:
    return host in {"127.0.0.1", "localhost", "::1"}


@dataclass(frozen=True)
class DebugPanelConfig:
    server: dict[str, Any]
    topics: dict[str, str]
    defaults: dict[str, Any]
    timeline: dict[str, Any]
    asr_default_text: str

    @classmethod
    def default(cls) -> DebugPanelConfig:
        return cls.from_dict(deepcopy(DEFAULT_CONFIG))

    @classmethod
    def from_yaml(cls, path: str | Path) -> DebugPanelConfig:
        with Path(path).open("r", encoding="utf-8") as handle:
            loaded = yaml.safe_load(handle) or {}
        if not isinstance(loaded, dict):
            raise ValueError("config root must be a mapping")
        return cls.from_dict(_deep_merge(DEFAULT_CONFIG, loaded))

    @classmethod
    def from_dict(cls, raw: dict[str, Any]) -> DebugPanelConfig:
        config = cls(
            server=dict(raw["server"]),
            topics=dict(raw["topics"]),
            defaults=dict(raw["defaults"]),
            timeline=dict(raw["timeline"]),
            asr_default_text=str(raw.get("asr_default_text", "")),
        )
        config.validate()
        return config

    def to_dict(self) -> dict[str, Any]:
        return {
            "server": dict(self.server),
            "topics": dict(self.topics),
            "defaults": dict(self.defaults),
            "timeline": dict(self.timeline),
            "asr_default_text": self.asr_default_text,
        }

    def validate(self) -> None:
        host = self.server.get("host")
        if not isinstance(host, str) or not host:
            raise ValueError("server.host must be a non-empty string")
        port = self.server.get("port")
        if isinstance(port, bool) or not isinstance(port, int) or not 1 <= port <= 65535:
            raise ValueError("server.port must be an integer between 1 and 65535")
        allow_remote = self.server.get("allow_remote")
        if not isinstance(allow_remote, bool):
            raise ValueError("server.allow_remote must be boolean")
        if not _is_loopback(host) and not allow_remote:
            raise ValueError("non-loopback host requires allow_remote: true")

        required_topics = [
            "asr",
            "voice_state",
            "voice_debug_events",
            "robot_mode",
            "safety_state",
            "health",
            "voice_cmd_loco",
            "voice_cmd_action",
            "tts",
            "led",
            "safe_cmd_loco",
            "safe_cmd_stop",
            "safety_decisions",
        ]
        missing = [key for key in required_topics if not isinstance(self.topics.get(key), str) or not self.topics[key]]
        if missing:
            raise ValueError(f"missing topic config: {', '.join(missing)}")

        confidence = self.defaults.get("asr_confidence")
        if (
            isinstance(confidence, bool)
            or not isinstance(confidence, (int, float))
            or not 0.0 <= float(confidence) <= 1.0
        ):
            raise ValueError("defaults.asr_confidence must be between 0 and 1")
        if not isinstance(self.defaults.get("asr_is_final"), bool):
            raise ValueError("defaults.asr_is_final must be boolean")
        if not isinstance(self.defaults.get("asr_source"), str) or not self.defaults["asr_source"]:
            raise ValueError("defaults.asr_source must be a non-empty string")
        if not isinstance(self.timeline.get("max_events"), int) or self.timeline["max_events"] <= 0:
            raise ValueError("timeline.max_events must be positive integer")
        if not isinstance(self.timeline.get("state_timeout_ms"), int) or self.timeline["state_timeout_ms"] <= 0:
            raise ValueError("timeline.state_timeout_ms must be positive integer")
