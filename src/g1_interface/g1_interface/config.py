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
        "voice_request": "/api/voice/request",
        "voice_response": "/api/voice/response",
        "motion_switcher_request": "/api/motion_switcher/request",
        "motion_switcher_response": "/api/motion_switcher/response",
        "dex3_left_cmd": "/dex3/left/cmd",
        "dex3_right_cmd": "/dex3/right/cmd",
        "dex3_left_state": "/lf/dex3/left/state",
        "dex3_right_state": "/lf/dex3/right/state",
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
    control: dict[str, Any]
    timeouts: dict[str, int]
    sport_api: dict[str, Any]

    @classmethod
    def default(cls) -> "G1InterfaceConfig":
        return cls._from_dict(deepcopy(DEFAULT_CONFIG))

    @classmethod
    def from_yaml(cls, path: str | Path) -> "G1InterfaceConfig":
        with Path(path).open("r", encoding="utf-8") as handle:
            loaded = yaml.safe_load(handle) or {}
        if not isinstance(loaded, dict):
            raise ValueError("config root must be a mapping")
        return cls._from_dict(_deep_merge(DEFAULT_CONFIG, loaded))

    @classmethod
    def _from_dict(cls, raw: dict[str, Any]) -> "G1InterfaceConfig":
        config = cls(
            robot=dict(raw["robot"]),
            native_topics=dict(raw["native_topics"]),
            control=dict(raw["control"]),
            timeouts=dict(raw["timeouts"]),
            sport_api=dict(raw["sport_api"]),
        )
        config.validate()
        return config

    def validate(self) -> None:
        required_topics = [
            "low_state",
            "low_state_low_freq",
            "secondary_imu",
            "sport_request",
            "sport_response",
        ]
        missing_topics = [key for key in required_topics if not self.native_topics.get(key)]
        if missing_topics:
            raise ValueError(f"missing native topic config: {', '.join(missing_topics)}")

        required_timeouts = [
            "state_timeout_ms",
            "api_response_timeout_ms",
            "health_publish_period_ms",
            "mode_query_period_ms",
        ]
        missing_timeouts = []
        for key in required_timeouts:
            value = self.timeouts.get(key)
            if isinstance(value, bool) or not isinstance(value, (int, float)):
                missing_timeouts.append(key)
        if missing_timeouts:
            raise ValueError(f"missing timeout config: {', '.join(missing_timeouts)}")

        if self.control["allow_low_level"] and not self.control["require_manual_confirm_for_mode_switch"]:
            raise ValueError("low level control requires manual confirmation")

        encoding = self.sport_api.get("parameter_encoding")
        if encoding != "json":
            raise ValueError(f"unsupported sport API parameter encoding: {encoding}")

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
