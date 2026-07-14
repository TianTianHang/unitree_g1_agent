from __future__ import annotations

import json
import math

from builtin_interfaces.msg import Time

from g1_agent_msgs.msg import (
    ActionIntent,
    RobotStateSummary,
    SafetyDecision,
    ValidatedActionCommand,
    ValidatedLocoCommand,
    VoiceEvent,
)
from g1_interface.internal_types import LowStateSummary, SportCommand

KIND_LOCO = str(getattr(SafetyDecision, "KIND_LOCO"))
KIND_ACTION = str(getattr(SafetyDecision, "KIND_ACTION"))
ACTION_STOP = str(getattr(ActionIntent, "ACTION_STOP"))
ACTION_CANCEL = str(getattr(ActionIntent, "ACTION_CANCEL"))


def _time_from_sec(value: float) -> Time:
    sec = math.floor(value)
    return Time(sec=sec, nanosec=int((value - sec) * 1_000_000_000))


def _duration_to_sec(value) -> float:
    return float(value.sec) + float(value.nanosec) / 1_000_000_000.0


def _bounded(value: float, field: str, low: float, high: float) -> float:
    if not math.isfinite(value):
        raise ValueError(f"{field} non-finite")
    if value < low or value > high:
        raise ValueError(f"{field} out of range")
    return value


def _require_allow(command_id: str, command_kind: str, validation) -> None:
    if validation.command_id != command_id:
        raise ValueError("validation command_id mismatch")
    if validation.command_kind != command_kind:
        raise ValueError("validation command_kind mismatch")
    if validation.decision != validation.DECISION_ALLOW:
        raise ValueError("command not allowed by safety validation")


def sport_command_from_loco(msg: ValidatedLocoCommand) -> SportCommand:
    _require_allow(
        msg.intent.command_id,
        KIND_LOCO,
        msg.validation,
    )
    values = [
        _bounded(float(msg.intent.vx), "vx", -0.5, 0.5),
        _bounded(float(msg.intent.vy), "vy", -0.3, 0.3),
        _bounded(float(msg.intent.vyaw), "vyaw", -0.8, 0.8),
    ]
    duration = _bounded(
        _duration_to_sec(msg.intent.duration),
        "duration",
        0.01,
        2.0,
    )
    return SportCommand(
        action="set_velocity",
        params={"velocity": values, "duration": duration},
    )


def sport_command_from_action(msg: ValidatedActionCommand) -> SportCommand:
    _require_allow(
        msg.intent.command_id,
        KIND_ACTION,
        msg.validation,
    )
    if msg.intent.action not in {
        ACTION_STOP,
        ACTION_CANCEL,
    }:
        raise ValueError(f"safe_stop action must be stop or cancel: {msg.intent.action}")
    return SportCommand(
        action="set_velocity",
        params={"velocity": [0.0, 0.0, 0.0], "duration": 0.1},
    )


def native_audio_event(raw_text: str, stamp_sec: float) -> VoiceEvent | None:
    text = raw_text.strip()
    if not text:
        return None
    try:
        payload = json.loads(text)
    except json.JSONDecodeError:
        if text.startswith(("{", "[")):
            return None
        payload = {"text": text}
    if not isinstance(payload, dict):
        return None

    event_text = payload.get("text")
    if isinstance(event_text, str) and event_text.strip():
        msg = VoiceEvent(
            stamp=_time_from_sec(stamp_sec),
            source=str(payload.get("source", "builtin_asr")),
            event_type=VoiceEvent.EVENT_ASR,
            text=event_text.strip(),
            is_final=bool(payload.get("is_final", True)),
            language=str(payload.get("language", "")),
        )
        index = payload.get("index")
        if isinstance(index, int) and not isinstance(index, bool) and index >= 0:
            msg.has_sequence_id = True
            msg.sequence_id = index
        confidence = payload.get("confidence")
        if (
            not isinstance(confidence, bool)
            and isinstance(confidence, int | float)
            and math.isfinite(float(confidence))
            and 0.0 <= confidence <= 1.0
        ):
            msg.has_confidence = True
            msg.confidence = float(confidence)
        return msg

    play_state = payload.get("play_state")
    if isinstance(play_state, int) and not isinstance(play_state, bool) and play_state in {0, 1}:
        return VoiceEvent(
            stamp=_time_from_sec(stamp_sec),
            source="builtin_audio",
            event_type=VoiceEvent.EVENT_PLAYBACK,
            has_playback_state=True,
            playback_state=(VoiceEvent.PLAYBACK_PLAYING if play_state == 1 else VoiceEvent.PLAYBACK_STOPPED),
        )
    return None


def robot_state_summary(
    summary: LowStateSummary,
    stamp_sec: float,
    source: str,
    mode: str | None,
    control_owner: str,
    mode_source: str,
    velocity: dict[str, float],
    sport_fsm_mode: int | None,
    sport_fsm_id: int | None,
) -> RobotStateSummary:
    msg = RobotStateSummary(
        stamp=_time_from_sec(stamp_sec),
        source=source,
        mode=mode or RobotStateSummary.MODE_UNKNOWN,
        control_owner=control_owner or RobotStateSummary.OWNER_UNKNOWN,
        mode_source=mode_source,
        motor_count=summary.motor_count,
        velocity_source="last_sport_command",
        health_state=RobotStateSummary.HEALTH_UNKNOWN,
    )
    msg.has_sport_fsm_mode = sport_fsm_mode is not None
    msg.sport_fsm_mode = int(sport_fsm_mode or 0)
    msg.has_sport_fsm_id = sport_fsm_id is not None
    msg.sport_fsm_id = int(sport_fsm_id or 0)
    msg.rpy.x, msg.rpy.y, msg.rpy.z = map(float, summary.rpy)
    (
        msg.orientation.w,
        msg.orientation.x,
        msg.orientation.y,
        msg.orientation.z,
    ) = map(float, summary.quaternion)
    (
        msg.angular_velocity.x,
        msg.angular_velocity.y,
        msg.angular_velocity.z,
    ) = map(float, summary.gyroscope)
    (
        msg.linear_acceleration.x,
        msg.linear_acceleration.y,
        msg.linear_acceleration.z,
    ) = map(float, summary.accelerometer)
    msg.has_max_temperature = summary.max_temperature_c is not None
    msg.max_temperature_c = float(summary.max_temperature_c or 0.0)
    msg.has_battery_voltage = False
    msg.velocity.linear.x = float(velocity.get("vx", 0.0))
    msg.velocity.linear.y = float(velocity.get("vy", 0.0))
    msg.velocity.angular.z = float(velocity.get("vyaw", 0.0))
    return msg
