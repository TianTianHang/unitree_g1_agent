from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from typing import Any


@dataclass(frozen=True)
class SafetyDecision:
    allowed: bool
    reason: str | None = None
    modified_params: dict[str, Any] | None = None
    check_details: dict[str, bool] | None = None

    @classmethod
    def allow(cls, check_details: dict[str, bool] | None = None) -> "SafetyDecision":
        return cls(allowed=True, reason=None, check_details=check_details)

    @classmethod
    def reject(cls, reason: str, check_details: dict[str, bool] | None = None) -> "SafetyDecision":
        return cls(allowed=False, reason=reason, check_details=check_details)


@dataclass(frozen=True)
class LocoIntent:
    raw_command: dict[str, Any]
    command_id: str
    session_id: str | None
    source: str | None
    text: str
    vx: float
    vy: float
    vyaw: float
    duration_sec: float
    created_at_sec: float | None
    received_at_sec: float

    @property
    def kind(self) -> str:
        return "loco"


@dataclass(frozen=True)
class ActionIntent:
    raw_command: dict[str, Any]
    command_id: str
    session_id: str | None
    source: str | None
    text: str
    action: str
    priority: str
    created_at_sec: float | None
    received_at_sec: float

    @property
    def kind(self) -> str:
        return "action"


@dataclass(frozen=True)
class RobotStateSnapshot:
    timestamp: float
    mode: str | None
    health_state: str
    lowstate_age_ms: int | None
    current_velocity: dict[str, float]
    motor_count: int
    max_temperature: float | None
    battery_voltage: float | None = None

    @classmethod
    def unhealthy(cls, timestamp: float) -> "RobotStateSnapshot":
        return cls(
            timestamp=timestamp,
            mode=None,
            health_state="unhealthy",
            lowstate_age_ms=None,
            current_velocity={"vx": 0.0, "vy": 0.0, "vyaw": 0.0},
            motor_count=0,
            max_temperature=None,
            battery_voltage=None,
        )

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class ValidatedCommand:
    original_command: dict[str, Any]
    validation_timestamp: float
    safety_decision: SafetyDecision
    robot_state_snapshot: RobotStateSnapshot

    def to_safe_payload(self) -> dict[str, Any]:
        payload = dict(self.original_command)
        payload["validated_at"] = self.validation_timestamp
        payload["validation_result"] = {
            "allowed": self.safety_decision.allowed,
            "reason": self.safety_decision.reason,
            "check_details": self.safety_decision.check_details or {},
        }
        payload["robot_state_snapshot"] = self.robot_state_snapshot.to_dict()
        return payload

    def to_json(self) -> str:
        return json.dumps(self.to_safe_payload(), ensure_ascii=False, sort_keys=True)
