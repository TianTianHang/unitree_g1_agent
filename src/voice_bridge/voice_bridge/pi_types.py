from __future__ import annotations

from typing import Any, Protocol


class OptionalCloseableAgent(Protocol):
    def abort(self) -> None:
        ...

    def close(self) -> None:
        ...


CUSTOM_TOOLS: dict[str, str] = {
    "robot_walk": "loco",
    "robot_stop": "action",
    "robot_say": "say",
    "robot_led": "led",
}

BLOCKED_ENV_PREFIXES = ("ROS_", "RMW_", "CYCLONEDDS_", "SSH_", "GIT_SSH_")

DEFAULT_PI_TIMEOUTS: dict[str, float | int] = {
    "startup_health_sec": 20.0,
    "command_response_sec": 5.0,
    "conversational_turn_sec": 120.0,
    "idle_health_check_sec": 30.0,
    "restart_backoff_max_sec": 30.0,
    "restart_max_attempts": 5,
}

PiEvent = dict[str, Any]
