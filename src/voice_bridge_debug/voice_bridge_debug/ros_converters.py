from __future__ import annotations

from typing import Any

from g1_agent_msgs.msg import (
    ActionIntent,
    LocoIntent,
    RobotStateSummary,
    SafetyDecision,
    SafetyStatus,
    ValidatedActionCommand,
    ValidatedLocoCommand,
    VoiceEvent,
)


def _time(msg) -> float:
    return float(msg.sec) + float(msg.nanosec) / 1_000_000_000.0


def _duration(msg) -> float:
    return float(msg.sec) + float(msg.nanosec) / 1_000_000_000.0


def voice_event_to_dict(msg: VoiceEvent) -> dict[str, Any]:
    return {
        "stamp": _time(msg.stamp),
        "source": msg.source,
        "event_type": msg.event_type,
        "sequence_id": msg.sequence_id if msg.has_sequence_id else None,
        "text": msg.text,
        "confidence": msg.confidence if msg.has_confidence else None,
        "is_final": msg.is_final,
        "language": msg.language,
        "playback_state": msg.playback_state if msg.has_playback_state else None,
    }


def loco_intent_to_dict(msg: LocoIntent) -> dict[str, Any]:
    return {
        "created_at": _time(msg.created_at),
        "source": msg.source,
        "session_id": msg.session_id,
        "command_id": msg.command_id,
        "text": msg.text,
        "vx": msg.vx,
        "vy": msg.vy,
        "vyaw": msg.vyaw,
        "duration_sec": _duration(msg.duration),
    }


def action_intent_to_dict(msg: ActionIntent) -> dict[str, Any]:
    return {
        "created_at": _time(msg.created_at),
        "source": msg.source,
        "session_id": msg.session_id,
        "command_id": msg.command_id,
        "text": msg.text,
        "action": msg.action,
        "priority": msg.priority,
    }


def robot_state_to_dict(msg: RobotStateSummary) -> dict[str, Any]:
    return {
        "stamp": _time(msg.stamp),
        "source": msg.source,
        "mode": msg.mode,
        "control_owner": msg.control_owner,
        "mode_source": msg.mode_source,
        "sport_fsm_mode": msg.sport_fsm_mode if msg.has_sport_fsm_mode else None,
        "sport_fsm_id": msg.sport_fsm_id if msg.has_sport_fsm_id else None,
        "rpy": [msg.rpy.x, msg.rpy.y, msg.rpy.z],
        "quaternion": [
            msg.orientation.w,
            msg.orientation.x,
            msg.orientation.y,
            msg.orientation.z,
        ],
        "motor_count": msg.motor_count,
        "max_temperature_c": (msg.max_temperature_c if msg.has_max_temperature else None),
        "battery_voltage": msg.battery_voltage if msg.has_battery_voltage else None,
        "velocity": {
            "vx": msg.velocity.linear.x,
            "vy": msg.velocity.linear.y,
            "vyaw": msg.velocity.angular.z,
        },
        "velocity_source": msg.velocity_source,
        "health_state": msg.health_state,
        "lowstate_age_sec": (_duration(msg.lowstate_age) if msg.has_lowstate_age else None),
    }


def safety_decision_to_dict(msg: SafetyDecision) -> dict[str, Any]:
    return {
        "timestamp": _time(msg.stamp),
        "command_id": msg.command_id,
        "command_kind": msg.command_kind,
        "decision": msg.decision,
        "reason": msg.reason or None,
        "validation_time_sec": _duration(msg.validation_latency),
        "robot_state": robot_state_to_dict(msg.robot_state),
    }


def validated_loco_to_dict(msg: ValidatedLocoCommand) -> dict[str, Any]:
    return {
        "intent": loco_intent_to_dict(msg.intent),
        "validated_at": _time(msg.validated_at),
        "validation": safety_decision_to_dict(msg.validation),
    }


def validated_action_to_dict(msg: ValidatedActionCommand) -> dict[str, Any]:
    return {
        "intent": action_intent_to_dict(msg.intent),
        "validated_at": _time(msg.validated_at),
        "validation": safety_decision_to_dict(msg.validation),
    }


def safety_status_to_dict(msg: SafetyStatus) -> dict[str, Any]:
    return {
        "timestamp": _time(msg.stamp),
        "node": msg.node_name,
        "enabled": msg.enabled,
        "strict_mode": msg.strict_mode,
        "robot_state": robot_state_to_dict(msg.robot_state),
        "allow_count": msg.allow_count,
        "reject_count": msg.reject_count,
        "rejection_rate": msg.rejection_rate,
        "last_rejection_reason": msg.last_rejection_reason or None,
        "last_decision": (safety_decision_to_dict(msg.last_decision) if msg.has_last_decision else None),
    }
