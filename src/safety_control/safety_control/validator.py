from __future__ import annotations

import json
import math
from datetime import datetime
from typing import Any

from safety_control.config import SafetyControlConfig
from safety_control.internal_types import ActionIntent, LocoIntent, RobotStateSnapshot, SafetyDecision


def _parse_json_object(raw_json: str) -> dict[str, Any]:
    payload = json.loads(raw_json)
    if not isinstance(payload, dict):
        raise ValueError("payload must be a JSON object")
    return payload


def _finite_float(payload: dict[str, Any], field: str) -> float:
    if field not in payload:
        raise ValueError(f"missing field: {field}")
    try:
        value = float(payload[field])
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{field} must be numeric") from exc
    if not math.isfinite(value):
        raise ValueError(f"{field} must be finite")
    return value


def _optional_str(payload: dict[str, Any], field: str) -> str | None:
    value = payload.get(field)
    if value is None:
        return None
    return str(value)


def _command_id(payload: dict[str, Any], kind: str, now_sec: float) -> str:
    value = str(payload.get("command_id") or "").strip()
    if value:
        return value
    return f"{kind}-{now_sec:.6f}"


def _timestamp_sec(payload: dict[str, Any]) -> float | None:
    for field in ["created_at", "created_at_sec", "timestamp", "stamp_sec", "issued_at"]:
        if field not in payload:
            continue
        value = payload[field]
        if value is None or value == "":
            return None
        if isinstance(value, dict):
            sec = value.get("sec", value.get("secs", 0))
            nanosec = value.get("nanosec", value.get("nsec", 0))
            return float(sec) + float(nanosec) / 1_000_000_000.0
        try:
            return float(value)
        except (TypeError, ValueError):
            if isinstance(value, str):
                try:
                    return datetime.fromisoformat(value.replace("Z", "+00:00")).timestamp()
                except ValueError as exc:
                    raise ValueError(f"{field} must be numeric or ISO-8601") from exc
            raise ValueError(f"{field} must be numeric") from None
    return None


def parse_loco_intent(raw_json: str, now_sec: float) -> LocoIntent:
    payload = _parse_json_object(raw_json)
    return LocoIntent(
        raw_command=dict(payload),
        command_id=_command_id(payload, "loco", now_sec),
        session_id=_optional_str(payload, "session_id"),
        source=_optional_str(payload, "source"),
        text=str(payload.get("text", "")),
        vx=_finite_float(payload, "vx"),
        vy=_finite_float(payload, "vy"),
        vyaw=_finite_float(payload, "vyaw"),
        duration_sec=_finite_float(payload, "duration_sec"),
        created_at_sec=_timestamp_sec(payload),
        received_at_sec=now_sec,
    )


def parse_action_intent(raw_json: str, now_sec: float) -> ActionIntent:
    payload = _parse_json_object(raw_json)
    action = str(payload.get("action", "")).strip().lower()
    if not action:
        raise ValueError("missing field: action")
    return ActionIntent(
        raw_command=dict(payload),
        command_id=_command_id(payload, "action", now_sec),
        session_id=_optional_str(payload, "session_id"),
        source=_optional_str(payload, "source"),
        text=str(payload.get("text", "")),
        action=action,
        priority=str(payload.get("priority", "normal")),
        created_at_sec=_timestamp_sec(payload),
        received_at_sec=now_sec,
    )


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
    ) -> SafetyDecision:
        details: dict[str, bool] = {}
        if not self.config.safety["enabled"]:
            details["safety_enabled"] = False
            return SafetyDecision.allow(details)

        for check in [
            self._check_robot_state(robot_state),
            self._check_mode("loco", robot_state),
            self._check_command_freshness(intent.created_at_sec, now_sec),
            self._check_motion_limits(intent),
            self._check_velocity_continuity(intent, robot_state),
        ]:
            details.update(check.check_details or {})
            if not check.allowed:
                return SafetyDecision.reject(check.reason or "safety check failed", details)

        return SafetyDecision.allow(details)

    def validate_action(
        self,
        intent: ActionIntent,
        robot_state: RobotStateSnapshot,
        now_sec: float,
    ) -> SafetyDecision:
        del now_sec
        details: dict[str, bool] = {}
        if intent.action in {"stop", "cancel"}:
            details["emergency_action"] = True
            return SafetyDecision.allow(details)

        del robot_state
        return SafetyDecision.reject(f"unsupported action: {intent.action}", details)

    def _check_robot_state(self, robot_state: RobotStateSnapshot) -> SafetyDecision:
        details: dict[str, bool] = {}
        thresholds = self.config.health_thresholds
        max_age_ms = float(thresholds["max_lowstate_age_ms"])
        max_temperature = float(thresholds["max_motor_temperature"])
        require_motor_temperature = bool(thresholds["require_motor_temperature"])
        min_battery_voltage = float(thresholds["min_battery_voltage"])
        require_battery_voltage = bool(thresholds["require_battery_voltage"])

        if robot_state.lowstate_age_ms is None:
            details["lowstate_fresh"] = False
            return SafetyDecision.reject("lowstate unavailable", details)
        details["lowstate_fresh"] = robot_state.lowstate_age_ms <= max_age_ms
        if not details["lowstate_fresh"]:
            return SafetyDecision.reject(f"lowstate stale: age_ms={robot_state.lowstate_age_ms}", details)

        details["health_ok"] = robot_state.health_state == "ok"
        if not details["health_ok"]:
            return SafetyDecision.reject(f"robot health not ok: {robot_state.health_state}", details)

        if robot_state.max_temperature is None:
            details["temperature_ok"] = not require_motor_temperature
        else:
            details["temperature_ok"] = robot_state.max_temperature < max_temperature
        if not details["temperature_ok"]:
            if robot_state.max_temperature is None:
                return SafetyDecision.reject("motor temperature unavailable", details)
            return SafetyDecision.reject(f"motor temperature too high: {robot_state.max_temperature}", details)

        if robot_state.battery_voltage is None:
            details["battery_ok"] = not require_battery_voltage
        else:
            details["battery_ok"] = robot_state.battery_voltage >= min_battery_voltage
        if not details["battery_ok"]:
            if robot_state.battery_voltage is None:
                return SafetyDecision.reject("battery voltage unavailable", details)
            return SafetyDecision.reject(f"battery voltage too low: {robot_state.battery_voltage}", details)

        return SafetyDecision.allow(details)

    def _policy_mode(self, robot_state: RobotStateSnapshot) -> str | None:
        if robot_state.mode:
            return robot_state.mode
        if self.config.safety["strict_mode"]:
            return None
        return str(self.config.safety["default_mode"])

    def _check_mode(self, command_kind: str, robot_state: RobotStateSnapshot) -> SafetyDecision:
        mode = self._policy_mode(robot_state)
        details: dict[str, bool] = {}
        if mode is None:
            details["mode_available"] = False
            return SafetyDecision.reject("robot mode unavailable", details)
        details["mode_available"] = True

        restrictions = self.config.mode_restrictions.get(mode)
        if restrictions is None:
            details["mode_allowed"] = False
            return SafetyDecision.reject(f"unsupported robot mode: {mode}", details)

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
            return SafetyDecision.reject(f"{command_kind} not allowed in mode: {mode}", details)
        return SafetyDecision.allow(details)

    def _check_command_freshness(self, created_at_sec: float | None, now_sec: float) -> SafetyDecision:
        details: dict[str, bool] = {}
        if created_at_sec is None:
            if self.config.safety["strict_mode"] or self.config.safety["require_command_timestamp"]:
                details["command_fresh"] = False
                return SafetyDecision.reject("command timestamp missing", details)
            details["command_fresh"] = True
            return SafetyDecision.allow(details)

        age_ms = (now_sec - created_at_sec) * 1000.0
        if age_ms < -50.0:
            details["command_fresh"] = False
            return SafetyDecision.reject(f"command timestamp is in the future: age_ms={age_ms:.1f}", details)

        timeout_ms = float(self.config.safety["command_timeout_ms"])
        details["command_fresh"] = age_ms <= timeout_ms
        if not details["command_fresh"]:
            return SafetyDecision.reject(f"command expired: age_ms={age_ms:.1f}", details)
        return SafetyDecision.allow(details)

    def _check_motion_limits(self, intent: LocoIntent) -> SafetyDecision:
        details: dict[str, bool] = {}
        for field in ["vx", "vy", "vyaw", "duration_sec"]:
            limits = self.config.motion_limits[field]
            value = float(getattr(intent, field))
            allowed = float(limits["min"]) <= value <= float(limits["max"])
            details[f"{field}_range"] = allowed
            if not allowed:
                return SafetyDecision.reject(f"{field} out of range: {value}", details)
        return SafetyDecision.allow(details)

    def _check_velocity_continuity(
        self,
        intent: LocoIntent,
        robot_state: RobotStateSnapshot,
    ) -> SafetyDecision:
        details: dict[str, bool] = {}
        if not self.config.velocity_continuity["enabled"]:
            details["velocity_continuity"] = True
            return SafetyDecision.allow(details)

        for axis in ["vx", "vy", "vyaw"]:
            current = float(robot_state.current_velocity.get(axis, 0.0))
            target = float(getattr(intent, axis))
            limit = float(self.config.motion_limits[axis]["rate_limit"])
            allowed = abs(target - current) <= limit
            details[f"{axis}_continuity"] = allowed
            if not allowed:
                return SafetyDecision.reject(
                    f"{axis} velocity step too large: current={current}, target={target}",
                    details,
                )
        return SafetyDecision.allow(details)
