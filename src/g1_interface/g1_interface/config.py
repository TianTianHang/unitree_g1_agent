from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml

DEFAULT_CONFIG: dict[str, dict[str, Any]] = {
    "robot": {
        "model": "g1",
        "dof_profile": "auto",
        "network_interface": "auto",
        "domain_id": 0,
        "rmw_implementation": "rmw_cyclonedds_cpp",
    },
    "native_topics": {
        "low_state": "lowstate",
        "low_state_low_freq": "lf/lowstate",
        "secondary_imu": "secondary_imu",
        "low_cmd": "/lowcmd",
        "arm_sdk": "/arm_sdk",
        "sport_request": "/api/sport/request",
        "sport_response": "/api/sport/response",
        "audio_msg": "/audio_msg",
        "voice_request": "/api/voice/request",
        "voice_response": "/api/voice/response",
        "motion_switcher_request": "/api/motion_switcher/request",
        "motion_switcher_response": "/api/motion_switcher/response",
        "dex3_left_cmd": "/dex3/left/cmd",
        "dex3_right_cmd": "/dex3/right/cmd",
        "dex3_left_state": "/lf/dex3/left/state",
        "dex3_right_state": "/lf/dex3/right/state",
    },
    "project_topics": {
        "asr": "/g1/audio/asr",
        "audio_event": "/g1/audio/event",
        "safety_state": "/g1/state/safety",
    },
    "control": {
        "default_mode": "sport_api_loco",
        "allow_low_level": False,
        "allow_arm_sdk": False,
        "allow_dex3": False,
        "allow_arm_while_loco": False,
        "require_manual_confirm_for_mode_switch": True,
    },
    "timeouts": {
        "state_timeout_ms": 300,
        "api_response_timeout_ms": 500,
        "health_publish_period_ms": 200,
        "mode_query_period_ms": 500,
        "motion_watchdog_period_ms": 50,
        "safety_heartbeat_timeout_ms": 1200,
        "mode_freshness_timeout_ms": 1500,
        "api_unhealthy_timeout_count": 3,
    },
    "sport_api": {
        "parameter_encoding": "json",
        "api_ids": {
            "get_fsm_id": 7001,
            "get_fsm_mode": 7002,
            "set_velocity": 7105,
            "switch_to_user_ctrl": 7110,
            "switch_to_internal_ctrl": 7111,
        },
    },
    "asr": {
        "source_mode": "builtin",
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
class G1InterfaceConfig:
    robot: dict[str, Any]
    native_topics: dict[str, str]
    project_topics: dict[str, str]
    control: dict[str, Any]
    timeouts: dict[str, int]
    sport_api: dict[str, Any]
    asr: dict[str, Any]

    @classmethod
    def default(cls) -> G1InterfaceConfig:
        return cls._from_dict(deepcopy(DEFAULT_CONFIG))

    @classmethod
    def from_yaml(cls, path: str | Path) -> G1InterfaceConfig:
        with Path(path).open("r", encoding="utf-8") as handle:
            loaded = yaml.safe_load(handle) or {}
        if not isinstance(loaded, dict):
            raise ValueError("config root must be a mapping")
        return cls._from_dict(_deep_merge(DEFAULT_CONFIG, loaded))

    @classmethod
    def _from_dict(cls, raw: dict[str, Any]) -> G1InterfaceConfig:
        config = cls(
            robot=dict(raw["robot"]),
            native_topics=dict(raw["native_topics"]),
            project_topics=dict(raw["project_topics"]),
            control=dict(raw["control"]),
            timeouts=dict(raw["timeouts"]),
            sport_api=dict(raw["sport_api"]),
            asr=dict(raw["asr"]),
        )
        config.validate()
        return config

    def with_asr_source_mode(self, source_mode: str) -> G1InterfaceConfig:
        raw = {
            "robot": self.robot,
            "native_topics": self.native_topics,
            "project_topics": self.project_topics,
            "control": self.control,
            "timeouts": self.timeouts,
            "sport_api": self.sport_api,
            "asr": {**self.asr, "source_mode": source_mode},
        }
        return self._from_dict(raw)

    def validate(self) -> None:
        required_topics = [
            ("native_topics", "low_state"),
            ("native_topics", "low_state_low_freq"),
            ("native_topics", "secondary_imu"),
            ("native_topics", "sport_request"),
            ("native_topics", "sport_response"),
            ("native_topics", "audio_msg"),
            ("project_topics", "asr"),
            ("project_topics", "audio_event"),
            ("project_topics", "safety_state"),
        ]
        missing_topics = []
        for section, key in required_topics:
            mapping = getattr(self, section)
            if not mapping.get(key):
                missing_topics.append(f"{section}.{key}")
        if missing_topics:
            raise ValueError(f"missing topic config: {', '.join(missing_topics)}")

        required_timeouts = [
            "state_timeout_ms",
            "api_response_timeout_ms",
            "health_publish_period_ms",
            "mode_query_period_ms",
            "motion_watchdog_period_ms",
            "safety_heartbeat_timeout_ms",
            "mode_freshness_timeout_ms",
            "api_unhealthy_timeout_count",
        ]
        missing_timeouts = []
        for key in required_timeouts:
            value = self.timeouts.get(key)
            if isinstance(value, bool) or not isinstance(value, int | float):
                missing_timeouts.append(key)
        if missing_timeouts:
            raise ValueError(f"missing timeout config: {', '.join(missing_timeouts)}")

        for key in required_timeouts:
            if self.timeouts[key] <= 0:
                raise ValueError(f"{key} must be positive")
        api_unhealthy_timeout_count = self.timeouts["api_unhealthy_timeout_count"]
        if not isinstance(api_unhealthy_timeout_count, int):
            raise ValueError("api_unhealthy_timeout_count must be a positive integer")

        if self.control["allow_low_level"] and not self.control["require_manual_confirm_for_mode_switch"]:
            raise ValueError("low level control requires manual confirmation")

        encoding = self.sport_api.get("parameter_encoding")
        if encoding != "json":
            raise ValueError(f"unsupported sport API parameter encoding: {encoding}")

        source_mode = self.asr.get("source_mode")
        if source_mode not in {"builtin", "custom", "both"}:
            raise ValueError(f"unsupported asr source_mode: {source_mode}")

        api_ids = self.sport_api.get("api_ids")
        required_api_ids = ["set_velocity", "get_fsm_mode"]
        missing_api_ids = []
        if not isinstance(api_ids, dict):
            missing_api_ids = required_api_ids
        else:
            for key in required_api_ids:
                value = api_ids.get(key)
                if isinstance(value, bool) or not isinstance(value, int):
                    missing_api_ids.append(key)
        if missing_api_ids:
            raise ValueError(f"missing sport API id config: {', '.join(missing_api_ids)}")
