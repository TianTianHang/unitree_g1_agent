from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml


DEFAULT_CONFIG: dict[str, Any] = {
    "safety": {
        "enabled": True,
        "strict_mode": True,
        "default_mode": "sport_api_loco",
        "require_command_timestamp": True,
        "command_timeout_ms": 100,
        "state_timeout_ms": 300,
        "rate_limits": {
            "loco": {"max_per_second": 5, "burst": 3},
            "stop": {"max_per_second": 10, "burst": 10},
            "action": {"max_per_second": 3, "burst": 2},
        },
        "motion_limits": {
            "vx": {"min": -0.5, "max": 0.5, "rate_limit": 0.3},
            "vy": {"min": -0.3, "max": 0.3, "rate_limit": 0.2},
            "vyaw": {"min": -0.8, "max": 0.8, "rate_limit": 0.4},
            "duration_sec": {"min": 0.01, "max": 2.0},
        },
        "velocity_continuity": {
            "enabled": True,
            "max_acceleration": 2.0,
            "max_jerk": 5.0,
        },
        "mode_restrictions": {
            "sport_api_loco": {
                "allow_loco": True,
                "allow_action_stop": True,
                "allow_action_cancel": True,
            },
            "user_ctrl": {
                "allow_loco": False,
                "allow_action_stop": True,
                "allow_action_cancel": True,
            },
            "armed_mode": {
                "allow_loco": False,
                "allow_action_stop": True,
                "allow_action_cancel": True,
            },
        },
        "health_thresholds": {
            "max_lowstate_age_ms": 300,
            "max_motor_temperature": 60.0,
            "require_motor_temperature": False,
            "min_battery_voltage": 42.0,
            "require_battery_voltage": False,
        },
        "audit": {
            "log_all_decisions": True,
            "log_rejected_only": False,
            "retain_days": 30,
        },
    },
    "topics": {
        "input": {
            "loco_intent": "/voice/cmd/loco",
            "action_intent": "/voice/cmd/action",
            "robot_mode": "/g1/state/mode",
            "health": "/g1/state/health",
            "lowstate": "/g1/state/low",
        },
        "output": {
            "safe_loco": "/g1/safe_cmd/loco",
            "safe_stop": "/g1/safe_cmd/stop",
            "decisions": "/g1/safety/decisions",
            "safety_state": "/g1/state/safety",
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


def _require_bool(mapping: dict[str, Any], key: str) -> None:
    if not isinstance(mapping.get(key), bool):
        raise ValueError(f"{key} must be boolean")


def _require_number(mapping: dict[str, Any], key: str, *, positive: bool = False) -> None:
    value = mapping.get(key)
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError(f"{key} must be numeric")
    if positive and value <= 0:
        raise ValueError(f"{key} must be positive")


def _require_string(mapping: dict[str, Any], key: str) -> None:
    value = mapping.get(key)
    if not isinstance(value, str) or not value:
        raise ValueError(f"{key} must be a non-empty string")


def _require_topic_group(topics: dict[str, Any], group: str, required: list[str]) -> None:
    value = topics.get(group)
    if not isinstance(value, dict):
        raise ValueError(f"topics.{group} must be a mapping")
    missing = [key for key in required if not isinstance(value.get(key), str) or not value[key]]
    if missing:
        raise ValueError(f"missing topic config: {', '.join(missing)}")


@dataclass(frozen=True)
class SafetyControlConfig:
    safety: dict[str, Any]
    topics: dict[str, dict[str, str]]

    @classmethod
    def default(cls) -> "SafetyControlConfig":
        return cls._from_dict(deepcopy(DEFAULT_CONFIG))

    @classmethod
    def from_yaml(cls, path: str | Path) -> "SafetyControlConfig":
        with Path(path).open("r", encoding="utf-8") as handle:
            loaded = yaml.safe_load(handle) or {}
        if not isinstance(loaded, dict):
            raise ValueError("config root must be a mapping")
        return cls._from_dict(_deep_merge(DEFAULT_CONFIG, loaded))

    @classmethod
    def _from_dict(cls, raw: dict[str, Any]) -> "SafetyControlConfig":
        config = cls(
            safety=dict(raw["safety"]),
            topics={
                "input": dict(raw["topics"]["input"]),
                "output": dict(raw["topics"]["output"]),
            },
        )
        config.validate()
        return config

    @property
    def rate_limits(self) -> dict[str, dict[str, Any]]:
        return self.safety["rate_limits"]

    @property
    def motion_limits(self) -> dict[str, dict[str, Any]]:
        return self.safety["motion_limits"]

    @property
    def velocity_continuity(self) -> dict[str, Any]:
        return self.safety["velocity_continuity"]

    @property
    def mode_restrictions(self) -> dict[str, dict[str, bool]]:
        return self.safety["mode_restrictions"]

    @property
    def health_thresholds(self) -> dict[str, Any]:
        return self.safety["health_thresholds"]

    @property
    def audit(self) -> dict[str, Any]:
        return self.safety["audit"]

    def validate(self) -> None:
        _require_bool(self.safety, "enabled")
        _require_bool(self.safety, "strict_mode")
        _require_bool(self.safety, "require_command_timestamp")
        _require_string(self.safety, "default_mode")
        _require_number(self.safety, "command_timeout_ms", positive=True)
        _require_number(self.safety, "state_timeout_ms", positive=True)

        self._validate_rate_limits()
        self._validate_motion_limits()
        self._validate_velocity_continuity()
        self._validate_mode_restrictions()
        self._validate_health_thresholds()
        self._validate_audit()

        _require_topic_group(
            self.topics,
            "input",
            ["loco_intent", "action_intent", "robot_mode", "health", "lowstate"],
        )
        _require_topic_group(
            self.topics,
            "output",
            ["safe_loco", "safe_stop", "decisions", "safety_state"],
        )

    def _validate_rate_limits(self) -> None:
        rate_limits = self.safety.get("rate_limits")
        if not isinstance(rate_limits, dict):
            raise ValueError("rate_limits must be a mapping")
        for kind in ["loco", "stop", "action"]:
            limits = rate_limits.get(kind)
            if not isinstance(limits, dict):
                raise ValueError(f"missing rate limit config: {kind}")
            _require_number(limits, "max_per_second", positive=True)
            _require_number(limits, "burst", positive=True)

    def _validate_motion_limits(self) -> None:
        motion_limits = self.safety.get("motion_limits")
        if not isinstance(motion_limits, dict):
            raise ValueError("motion_limits must be a mapping")
        for field in ["vx", "vy", "vyaw", "duration_sec"]:
            limits = motion_limits.get(field)
            if not isinstance(limits, dict):
                raise ValueError(f"missing motion limit config: {field}")
            _require_number(limits, "min")
            _require_number(limits, "max")
            if limits["min"] >= limits["max"]:
                raise ValueError(f"{field} min must be less than max")
            if field != "duration_sec":
                _require_number(limits, "rate_limit", positive=True)

    def _validate_velocity_continuity(self) -> None:
        continuity = self.safety.get("velocity_continuity")
        if not isinstance(continuity, dict):
            raise ValueError("velocity_continuity must be a mapping")
        _require_bool(continuity, "enabled")
        _require_number(continuity, "max_acceleration", positive=True)
        _require_number(continuity, "max_jerk", positive=True)

    def _validate_mode_restrictions(self) -> None:
        restrictions = self.safety.get("mode_restrictions")
        if not isinstance(restrictions, dict):
            raise ValueError("mode_restrictions must be a mapping")
        for mode, rules in restrictions.items():
            if not isinstance(mode, str) or not mode:
                raise ValueError("mode restriction keys must be non-empty strings")
            if not isinstance(rules, dict):
                raise ValueError(f"mode restriction must be a mapping: {mode}")
            for key in ["allow_loco", "allow_action_stop", "allow_action_cancel"]:
                _require_bool(rules, key)

    def _validate_health_thresholds(self) -> None:
        thresholds = self.safety.get("health_thresholds")
        if not isinstance(thresholds, dict):
            raise ValueError("health_thresholds must be a mapping")
        _require_number(thresholds, "max_lowstate_age_ms", positive=True)
        _require_number(thresholds, "max_motor_temperature", positive=True)
        _require_bool(thresholds, "require_motor_temperature")
        _require_number(thresholds, "min_battery_voltage", positive=True)
        _require_bool(thresholds, "require_battery_voltage")

    def _validate_audit(self) -> None:
        audit = self.safety.get("audit")
        if not isinstance(audit, dict):
            raise ValueError("audit must be a mapping")
        _require_bool(audit, "log_all_decisions")
        _require_bool(audit, "log_rejected_only")
        _require_number(audit, "retain_days", positive=True)
