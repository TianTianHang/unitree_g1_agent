from __future__ import annotations

import math

from builtin_interfaces.msg import Duration, Time

from g1_agent_msgs.msg import (
    ActionIntent,
    LocoIntent,
    RobotStateSummary,
    SafetyDecision,
    SafetyStatus,
    ValidatedActionCommand,
    ValidatedLocoCommand,
)
from safety_control.internal_types import RobotStateSnapshot, ValidationResult


def _time(value: float) -> Time:
    sec = math.floor(value)
    return Time(sec=sec, nanosec=int((value - sec) * 1_000_000_000))


def _duration(value: float) -> Duration:
    value = max(0.0, value)
    sec = math.floor(value)
    return Duration(sec=sec, nanosec=int((value - sec) * 1_000_000_000))


def snapshot_msg(snapshot: RobotStateSnapshot) -> RobotStateSummary:
    msg = RobotStateSummary(
        stamp=_time(snapshot.timestamp),
        source="safety_control",
        mode=snapshot.mode or RobotStateSummary.MODE_UNKNOWN,
        control_owner=RobotStateSummary.OWNER_UNKNOWN,
        health_state=snapshot.health_state,
        motor_count=snapshot.motor_count,
    )
    msg.velocity.linear.x = float(snapshot.current_velocity["vx"])
    msg.velocity.linear.y = float(snapshot.current_velocity["vy"])
    msg.velocity.angular.z = float(snapshot.current_velocity["vyaw"])
    msg.has_max_temperature = snapshot.max_temperature is not None
    msg.max_temperature_c = float(snapshot.max_temperature or 0.0)
    msg.has_battery_voltage = snapshot.battery_voltage is not None
    msg.battery_voltage = float(snapshot.battery_voltage or 0.0)
    msg.has_lowstate_age = snapshot.lowstate_age_ms is not None
    msg.lowstate_age = _duration(float(snapshot.lowstate_age_ms or 0) / 1000.0)
    return msg


def decision_msg(
    command_id: str,
    command_kind: str,
    result: ValidationResult,
    snapshot: RobotStateSnapshot,
    stamp_sec: float,
    latency_sec: float,
) -> SafetyDecision:
    return SafetyDecision(
        stamp=_time(stamp_sec),
        command_id=command_id,
        command_kind=command_kind,
        decision=(SafetyDecision.DECISION_ALLOW if result.allowed else SafetyDecision.DECISION_REJECT),
        reason=result.reason or "",
        validation_latency=_duration(latency_sec),
        robot_state=snapshot_msg(snapshot),
    )


def validated_loco_msg(
    intent: LocoIntent,
    decision: SafetyDecision,
) -> ValidatedLocoCommand:
    return ValidatedLocoCommand(
        intent=intent,
        validated_at=decision.stamp,
        validation=decision,
    )


def validated_action_msg(
    intent: ActionIntent,
    decision: SafetyDecision,
) -> ValidatedActionCommand:
    return ValidatedActionCommand(
        intent=intent,
        validated_at=decision.stamp,
        validation=decision,
    )


def safety_status_msg(
    enabled: bool,
    strict_mode: bool,
    snapshot: RobotStateSnapshot,
    allow_count: int,
    reject_count: int,
    last_rejection_reason: str | None,
    last_decision: SafetyDecision | None,
    stamp_sec: float,
) -> SafetyStatus:
    total = allow_count + reject_count
    msg = SafetyStatus(
        stamp=_time(stamp_sec),
        node_name="safety_control",
        enabled=enabled,
        strict_mode=strict_mode,
        robot_state=snapshot_msg(snapshot),
        allow_count=allow_count,
        reject_count=reject_count,
        rejection_rate=(reject_count / total) if total else 0.0,
        last_rejection_reason=last_rejection_reason or "",
        has_last_decision=last_decision is not None,
    )
    if last_decision is not None:
        msg.last_decision = last_decision
    return msg
