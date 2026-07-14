from __future__ import annotations

import math

from g1_agent_msgs.msg import ActionIntent, LocoIntent
from safety_control.config import SafetyControlConfig
from safety_control.internal_types import RobotStateSnapshot, ValidationResult


def time_to_sec(value) -> float | None:
    if value.sec == 0 and value.nanosec == 0:
        return None
    return float(value.sec) + float(value.nanosec) / 1_000_000_000.0


def duration_to_sec(value) -> float:
    return float(value.sec) + float(value.nanosec) / 1_000_000_000.0


def validate_intent_shape(intent: LocoIntent) -> None:
    if not intent.command_id.strip():
        raise ValueError("command_id must be non-empty")
    for name in ("vx", "vy", "vyaw"):
        if not math.isfinite(float(getattr(intent, name))):
            raise ValueError(f"{name} must be finite")
    if not math.isfinite(duration_to_sec(intent.duration)):
        raise ValueError("duration must be finite")


def validate_action_shape(intent: ActionIntent) -> None:
    if not intent.command_id.strip():
        raise ValueError("command_id must be non-empty")
    if not intent.action.strip():
        raise ValueError("action must be non-empty")


class RateLimiter:
    def __init__(self, max_per_second: float, burst: float):
        if max_per_second <= 0:
            raise ValueError("max_per_second must be positive")
        if burst <= 0:
            raise ValueError("burst must be positive")
        self.max_per_second = float(max_per_second)
        self.burst = float(burst)
        self._tokens = float(burst)
        self._updated_sec: float | None = None

    def allow(self, now_sec: float) -> bool:
        if self._updated_sec is None:
            self._updated_sec = now_sec
        else:
            elapsed = max(0.0, now_sec - self._updated_sec)
            self._tokens = min(self.burst, self._tokens + elapsed * self.max_per_second)
            self._updated_sec = now_sec

        if self._tokens >= 1.0:
            self._tokens -= 1.0
            return True
        return False

    def reset(self) -> None:
        self._tokens = self.burst
        self._updated_sec = None


class SafetyValidator:
    def __init__(self, config: SafetyControlConfig):
        self.config = config

    def validate_loco(
        self,
        intent: LocoIntent,
        robot_state: RobotStateSnapshot,
        now_sec: float,
    ) -> ValidationResult:
        validate_intent_shape(intent)
        details: dict[str, bool] = {}
        if not self.config.safety["enabled"]:
            details["safety_enabled"] = False
            return ValidationResult.allow(details)

        for check in [
            self._check_robot_state(robot_state),
            self._check_mode("loco", robot_state),
            self._check_command_freshness(time_to_sec(intent.created_at), now_sec),
            self._check_motion_limits(intent),
            self._check_velocity_continuity(intent, robot_state),
        ]:
            details.update(check.check_details or {})
            if not check.allowed:
                return ValidationResult.reject(check.reason or "safety check failed", details)

        return ValidationResult.allow(details)

    def validate_action(
        self,
        intent: ActionIntent,
        robot_state: RobotStateSnapshot,
        now_sec: float,
    ) -> ValidationResult:
        validate_action_shape(intent)
        del now_sec
        details: dict[str, bool] = {}
        if intent.action in {"stop", "cancel"}:
            details["emergency_action"] = True
            return ValidationResult.allow(details)

        del robot_state
        return ValidationResult.reject(f"unsupported action: {intent.action}", details)

    def _check_robot_state(self, robot_state: RobotStateSnapshot) -> ValidationResult:
        details: dict[str, bool] = {}
        thresholds = self.config.health_thresholds
        max_age_ms = float(thresholds["max_lowstate_age_ms"])
        max_temperature = float(thresholds["max_motor_temperature"])
        require_motor_temperature = bool(thresholds["require_motor_temperature"])
        min_battery_voltage = float(thresholds["min_battery_voltage"])
        require_battery_voltage = bool(thresholds["require_battery_voltage"])

        if robot_state.lowstate_age_ms is None:
            details["lowstate_fresh"] = False
            return ValidationResult.reject("lowstate unavailable", details)
        details["lowstate_fresh"] = robot_state.lowstate_age_ms <= max_age_ms
        if not details["lowstate_fresh"]:
            return ValidationResult.reject(f"lowstate stale: age_ms={robot_state.lowstate_age_ms}", details)

        details["health_ok"] = robot_state.health_state == "ok"
        if not details["health_ok"]:
            return ValidationResult.reject(f"robot health not ok: {robot_state.health_state}", details)

        if robot_state.max_temperature is None:
            details["temperature_ok"] = not require_motor_temperature
        else:
            details["temperature_ok"] = robot_state.max_temperature < max_temperature
        if not details["temperature_ok"]:
            if robot_state.max_temperature is None:
                return ValidationResult.reject("motor temperature unavailable", details)
            return ValidationResult.reject(f"motor temperature too high: {robot_state.max_temperature}", details)

        if robot_state.battery_voltage is None:
            details["battery_ok"] = not require_battery_voltage
        else:
            details["battery_ok"] = robot_state.battery_voltage >= min_battery_voltage
        if not details["battery_ok"]:
            if robot_state.battery_voltage is None:
                return ValidationResult.reject("battery voltage unavailable", details)
            return ValidationResult.reject(f"battery voltage too low: {robot_state.battery_voltage}", details)

        return ValidationResult.allow(details)

    def _policy_mode(self, robot_state: RobotStateSnapshot) -> str | None:
        if robot_state.mode:
            return robot_state.mode
        if self.config.safety["strict_mode"]:
            return None
        return str(self.config.safety["default_mode"])

    def _check_mode(self, command_kind: str, robot_state: RobotStateSnapshot) -> ValidationResult:
        mode = self._policy_mode(robot_state)
        details: dict[str, bool] = {}
        if mode is None:
            details["mode_available"] = False
            return ValidationResult.reject("robot mode unavailable", details)
        details["mode_available"] = True

        restrictions = self.config.mode_restrictions.get(mode)
        if restrictions is None:
            details["mode_allowed"] = False
            return ValidationResult.reject(f"unsupported robot mode: {mode}", details)

        if command_kind == "loco":
            key = "allow_loco"
        elif command_kind == "action_stop":
            key = "allow_action_stop"
        elif command_kind == "action_cancel":
            key = "allow_action_cancel"
        else:
            key = ""

        allowed = bool(restrictions.get(key, False))
        details["mode_allowed"] = allowed
        if not allowed:
            return ValidationResult.reject(f"{command_kind} not allowed in mode: {mode}", details)
        return ValidationResult.allow(details)

    def _check_command_freshness(self, created_at_sec: float | None, now_sec: float) -> ValidationResult:
        details: dict[str, bool] = {}
        if created_at_sec is None:
            if self.config.safety["strict_mode"] or self.config.safety["require_command_timestamp"]:
                details["command_fresh"] = False
                return ValidationResult.reject("command timestamp missing", details)
            details["command_fresh"] = True
            return ValidationResult.allow(details)

        age_ms = (now_sec - created_at_sec) * 1000.0
        if age_ms < -50.0:
            details["command_fresh"] = False
            return ValidationResult.reject(f"command timestamp is in the future: age_ms={age_ms:.1f}", details)

        timeout_ms = float(self.config.safety["command_timeout_ms"])
        details["command_fresh"] = age_ms <= timeout_ms
        if not details["command_fresh"]:
            return ValidationResult.reject(f"command expired: age_ms={age_ms:.1f}", details)
        return ValidationResult.allow(details)

    def _check_motion_limits(self, intent: LocoIntent) -> ValidationResult:
        details: dict[str, bool] = {}
        values = {
            "vx": float(intent.vx),
            "vy": float(intent.vy),
            "vyaw": float(intent.vyaw),
            "duration_sec": duration_to_sec(intent.duration),
        }
        for field, value in values.items():
            limits = self.config.motion_limits[field]
            allowed = float(limits["min"]) <= value <= float(limits["max"])
            details[f"{field}_range"] = allowed
            if not allowed:
                return ValidationResult.reject(f"{field} out of range: {value}", details)
        return ValidationResult.allow(details)

    def _check_velocity_continuity(
        self,
        intent: LocoIntent,
        robot_state: RobotStateSnapshot,
    ) -> ValidationResult:
        details: dict[str, bool] = {}
        if not self.config.velocity_continuity["enabled"]:
            details["velocity_continuity"] = True
            return ValidationResult.allow(details)

        for axis in ["vx", "vy", "vyaw"]:
            current = float(robot_state.current_velocity.get(axis, 0.0))
            target = float(getattr(intent, axis))
            limit = float(self.config.motion_limits[axis]["rate_limit"])
            allowed = abs(target - current) <= limit
            details[f"{axis}_continuity"] = allowed
            if not allowed:
                return ValidationResult.reject(
                    f"{axis} velocity step too large: current={current}, target={target}",
                    details,
                )
        return ValidationResult.allow(details)
