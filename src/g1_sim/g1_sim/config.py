from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml

DDS_TOPIC_PREFIXES = ("rt/", "/rt/")


DEFAULT_CONFIG: dict[str, dict[str, Any]] = {
    "topics": {
        "low_state": "lowstate",
        "low_state_low_freq": "lf/lowstate",
        "secondary_imu": "secondary_imu",
        "odometry": "/odom",
        "low_cmd_root": "/lowcmd",
        "low_cmd_relative": "lowcmd",
        "arm_sdk": "/arm_sdk",
        "user_lowcmd": "/user_lowcmd",
        "dex3_left_cmd": "/dex3/left/cmd",
        "dex3_right_cmd": "/dex3/right/cmd",
        "dex3_left_state": "/lf/dex3/left/state",
        "dex3_right_state": "/lf/dex3/right/state",
        "dex3_left_state_legacy": "/dex3/left/state",
        "dex3_right_state_legacy": "/dex3/right/state",
        "audio_msg": "/audio_msg",
        "asr_input": "~/asr_input",
        "sport_request": "/api/sport/request",
        "sport_response": "/api/sport/response",
        "arm_request": "/api/arm/request",
        "arm_response": "/api/arm/response",
        "voice_request": "/api/voice/request",
        "voice_response": "/api/voice/response",
        "agv_request": "/api/agv/request",
        "agv_response": "/api/agv/response",
        "motion_switcher_request": "/api/motion_switcher/request",
        "motion_switcher_response": "/api/motion_switcher/response",
    },
    "sim": {
        "motor_count": 35,
        "hand_motor_count": 7,
        "low_state_hz": 50.0,
        "low_state_low_freq_hz": 5.0,
        "imu_hz": 50.0,
        "odometry_hz": 50.0,
        "hand_state_hz": 20.0,
        "pelvis_height": 0.77,
        "sport_api_ids": {
            "get_fsm_id": 7001,
            "get_fsm_mode": 7002,
            "get_balance_mode": 7003,
            "get_swing_height": 7004,
            "get_stand_height": 7005,
            "get_phase": 7006,
            "set_fsm_id": 7101,
            "set_balance_mode": 7102,
            "set_swing_height": 7103,
            "set_stand_height": 7104,
            "set_velocity": 7105,
            "set_arm_task": 7106,
            "set_speed_mode": 7107,
            "switch_to_user_ctrl": 7110,
            "switch_to_internal_ctrl": 7111,
        },
        "arm_api_ids": {
            "execute_action": 7106,
            "get_action_list": 7107,
            "execute_custom_action": 7108,
            "stop_custom_action": 7113,
        },
        "voice_api_ids": {
            "tts": 1001,
            "asr": 1002,
            "start_play": 1003,
            "stop_play": 1004,
            "get_volume": 1005,
            "set_volume": 1006,
            "set_rgb_led": 1010,
        },
        "agv_api_ids": {
            "move": 1001,
            "height_adjust": 1002,
        },
        "motion_switcher_api_ids": {
            "check_mode": 1001,
            "select_mode": 1002,
            "release_mode": 1003,
            "set_silent": 1004,
            "get_silent": 1005,
        },
        "default_asr_text": "模拟 ASR 文本",
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


def _require_positive_number(mapping: dict[str, Any], key: str) -> None:
    value = mapping.get(key)
    if isinstance(value, bool) or not isinstance(value, (int, float)) or value <= 0:
        raise ValueError(f"{key} must be a positive number")


def _looks_like_dds_topic(topic: str) -> bool:
    return topic.startswith(DDS_TOPIC_PREFIXES)


@dataclass(frozen=True)
class G1SimConfig:
    topics: dict[str, str]
    sim: dict[str, Any]

    @classmethod
    def default(cls) -> G1SimConfig:
        return cls._from_dict(deepcopy(DEFAULT_CONFIG))

    @classmethod
    def from_yaml(cls, path: str | Path) -> G1SimConfig:
        with Path(path).open("r", encoding="utf-8") as handle:
            loaded = yaml.safe_load(handle) or {}
        if not isinstance(loaded, dict):
            raise ValueError("config root must be a mapping")
        return cls._from_dict(_deep_merge(DEFAULT_CONFIG, loaded))

    @classmethod
    def _from_dict(cls, raw: dict[str, Any]) -> G1SimConfig:
        config = cls(topics=dict(raw["topics"]), sim=dict(raw["sim"]))
        config.validate()
        return config

    def validate(self) -> None:
        required_topics = [
            "low_state",
            "low_state_low_freq",
            "secondary_imu",
            "odometry",
            "low_cmd_root",
            "low_cmd_relative",
            "arm_sdk",
            "user_lowcmd",
            "dex3_left_cmd",
            "dex3_right_cmd",
            "dex3_left_state",
            "dex3_right_state",
            "dex3_left_state_legacy",
            "dex3_right_state_legacy",
            "audio_msg",
            "asr_input",
            "sport_request",
            "sport_response",
            "arm_request",
            "arm_response",
            "voice_request",
            "voice_response",
            "agv_request",
            "agv_response",
            "motion_switcher_request",
            "motion_switcher_response",
        ]
        missing_topics = [
            key for key in required_topics if not isinstance(self.topics.get(key), str) or not self.topics[key]
        ]
        if missing_topics:
            raise ValueError(f"missing topic config: {', '.join(missing_topics)}")

        dds_topics = [
            f"{key}={self.topics[key]}"
            for key in required_topics
            if _looks_like_dds_topic(self.topics[key])
        ]
        if dds_topics:
            raise ValueError(
                "g1_sim ROS2 topics must not include the DDS rt/ prefix: "
                + ", ".join(dds_topics)
            )

        for key in [
            "low_state_hz",
            "low_state_low_freq_hz",
            "imu_hz",
            "odometry_hz",
            "hand_state_hz",
            "pelvis_height",
        ]:
            _require_positive_number(self.sim, key)

        motor_count = self.sim.get("motor_count")
        if isinstance(motor_count, bool) or not isinstance(motor_count, int) or motor_count <= 0:
            raise ValueError("motor_count must be a positive integer")

        hand_motor_count = self.sim.get("hand_motor_count")
        if isinstance(hand_motor_count, bool) or not isinstance(hand_motor_count, int) or hand_motor_count <= 0:
            raise ValueError("hand_motor_count must be a positive integer")

        for group, required_keys in {
            "sport_api_ids": [
                "get_fsm_id",
                "get_fsm_mode",
                "get_balance_mode",
                "get_swing_height",
                "get_stand_height",
                "get_phase",
                "set_fsm_id",
                "set_balance_mode",
                "set_swing_height",
                "set_stand_height",
                "set_velocity",
                "set_arm_task",
                "set_speed_mode",
                "switch_to_user_ctrl",
                "switch_to_internal_ctrl",
            ],
            "arm_api_ids": [
                "execute_action",
                "get_action_list",
                "execute_custom_action",
                "stop_custom_action",
            ],
            "voice_api_ids": [
                "tts",
                "asr",
                "start_play",
                "stop_play",
                "get_volume",
                "set_volume",
                "set_rgb_led",
            ],
            "agv_api_ids": [
                "move",
                "height_adjust",
            ],
            "motion_switcher_api_ids": [
                "check_mode",
                "select_mode",
                "release_mode",
                "set_silent",
                "get_silent",
            ],
        }.items():
            values = self.sim.get(group)
            if not isinstance(values, dict):
                raise ValueError(f"{group} must be a mapping")
            missing = [
                key
                for key in required_keys
                if isinstance(values.get(key), bool) or not isinstance(values.get(key), int)
            ]
            if missing:
                raise ValueError(f"missing API id config in {group}: {', '.join(missing)}")

        if not isinstance(self.sim.get("default_asr_text"), str):
            raise ValueError("default_asr_text must be a string")
