from __future__ import annotations

import json
import threading
from typing import Any

from g1_agent_msgs.msg import LocoIntent, RobotStateSummary
from safety_control.internal_types import RobotStateSnapshot
from safety_control.validator import duration_to_sec, time_to_sec


def _as_float(value: Any) -> float | None:
    if value is None:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _as_int(value: Any) -> int | None:
    result = _as_float(value)
    if result is None:
        return None
    return int(round(result))


def _decode_value(value: str) -> Any:
    try:
        return json.loads(value)
    except (TypeError, json.JSONDecodeError):
        return value


def _diagnostic_level_to_int(value: Any) -> int:
    if isinstance(value, int):
        return value
    if isinstance(value, bytes | bytearray):
        if len(value) == 1:
            return value[0]
        return int(value)
    return int(value)


def normalize_mode(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    if not text:
        return None
    key = text.lower().replace("-", "_").replace(" ", "_")
    aliases = {
        "sport": "sport_api_loco",
        "sport_api": "sport_api_loco",
        "sport_api_loco": "sport_api_loco",
        "internal": "sport_api_loco",
        "internal_ctrl": "sport_api_loco",
        "user": "user_ctrl",
        "user_ctrl": "user_ctrl",
        "user_control": "user_ctrl",
        "armed": "armed_mode",
        "armed_mode": "armed_mode",
    }
    return aliases.get(key, key)


class RobotStateTracker:
    def __init__(self, state_timeout_ms: int):
        self.state_timeout_ms = int(state_timeout_ms)
        self._lock = threading.RLock()
        self._mode: str | None = None
        self._health_state = "unhealthy"
        self._last_health_sec: float | None = None
        self._diagnostic_lowstate_age_ms: int | None = None
        self._last_lowstate_sec: float | None = None
        self._current_velocity = {"vx": 0.0, "vy": 0.0, "vyaw": 0.0}
        self._command_until_sec = 0.0
        self._motor_count = 0
        self._max_temperature: float | None = None
        self._battery_voltage: float | None = None

    def update_from_summary(self, msg: RobotStateSummary, now_sec: float) -> None:
        stamp_sec = time_to_sec(msg.stamp)
        mode = normalize_mode(msg.mode)
        with self._lock:
            self._last_lowstate_sec = stamp_sec if stamp_sec is not None else now_sec
            if mode is not None:
                self._mode = mode
            self._current_velocity = {
                "vx": float(msg.velocity.linear.x),
                "vy": float(msg.velocity.linear.y),
                "vyaw": float(msg.velocity.angular.z),
            }
            self._command_until_sec = 0.0
            self._motor_count = int(msg.motor_count)
            self._max_temperature = (
                float(msg.max_temperature_c) if msg.has_max_temperature else None
            )
            self._battery_voltage = float(msg.battery_voltage) if msg.has_battery_voltage else None

    def update_from_health(self, msg: object, now_sec: float) -> None:
        statuses = list(getattr(msg, "status", []))
        worst_level = 2 if not statuses else 0
        explicit_state: str | None = None
        lowstate_age_ms: int | None = None

        for status in statuses:
            try:
                worst_level = max(worst_level, _diagnostic_level_to_int(getattr(status, "level", 0)))
            except (TypeError, ValueError):
                worst_level = max(worst_level, 2)
            message = str(getattr(status, "message", "")).strip().lower()
            if message in {"ok", "degraded", "unhealthy"}:
                explicit_state = message

            for pair in list(getattr(status, "values", [])):
                key = str(getattr(pair, "key", ""))
                value = _decode_value(str(getattr(pair, "value", "")))
                if key == "state" and str(value).lower() in {"ok", "degraded", "unhealthy"}:
                    explicit_state = str(value).lower()
                elif key == "lowstate_age_ms":
                    lowstate_age_ms = _as_int(value)

        state_from_level = "unhealthy" if worst_level >= 2 else "degraded" if worst_level == 1 else "ok"
        order = {"ok": 0, "degraded": 1, "unhealthy": 2}
        if explicit_state is not None and order[explicit_state] > order[state_from_level]:
            health_state = explicit_state
        else:
            health_state = state_from_level

        with self._lock:
            self._health_state = health_state
            self._last_health_sec = now_sec
            self._diagnostic_lowstate_age_ms = lowstate_age_ms

    def record_loco_command(self, intent: LocoIntent, now_sec: float) -> None:
        with self._lock:
            self._current_velocity = {"vx": intent.vx, "vy": intent.vy, "vyaw": intent.vyaw}
            self._command_until_sec = now_sec + max(0.0, duration_to_sec(intent.duration))

    def record_stop(self, now_sec: float) -> None:
        with self._lock:
            self._current_velocity = {"vx": 0.0, "vy": 0.0, "vyaw": 0.0}
            self._command_until_sec = now_sec

    def get_snapshot(self, now_sec: float) -> RobotStateSnapshot:
        with self._lock:
            lowstate_age_ms = self._lowstate_age_ms(now_sec)
            current_velocity = dict(self._current_velocity)
            if now_sec >= self._command_until_sec and self._command_until_sec > 0.0:
                current_velocity = {"vx": 0.0, "vy": 0.0, "vyaw": 0.0}

            return RobotStateSnapshot(
                timestamp=now_sec,
                mode=self._mode,
                health_state=self._health_state,
                lowstate_age_ms=lowstate_age_ms,
                current_velocity=current_velocity,
                motor_count=self._motor_count,
                max_temperature=self._max_temperature,
                battery_voltage=self._battery_voltage,
            )

    def _lowstate_age_ms(self, now_sec: float) -> int | None:
        if self._last_lowstate_sec is not None:
            return int(round((now_sec - self._last_lowstate_sec) * 1000.0))
        if self._diagnostic_lowstate_age_ms is not None and self._last_health_sec is not None:
            elapsed_ms = int(round((now_sec - self._last_health_sec) * 1000.0))
            return self._diagnostic_lowstate_age_ms + max(0, elapsed_ms)
        return None
