from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class ValidationResult:
    allowed: bool
    reason: str | None = None
    modified_params: dict[str, Any] | None = None
    check_details: dict[str, bool] | None = None

    @classmethod
    def allow(cls, check_details: dict[str, bool] | None = None) -> ValidationResult:
        return cls(allowed=True, reason=None, check_details=check_details)

    @classmethod
    def reject(cls, reason: str, check_details: dict[str, bool] | None = None) -> ValidationResult:
        return cls(allowed=False, reason=reason, check_details=check_details)


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
    def unhealthy(cls, timestamp: float) -> RobotStateSnapshot:
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
