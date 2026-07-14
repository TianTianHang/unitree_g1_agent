from __future__ import annotations

import math

from builtin_interfaces.msg import Duration, Time

from g1_agent_msgs.msg import ActionIntent, LocoIntent, VoiceEvent
from voice_bridge.internal_types import AsrEvent


def _time_from_sec(value: float) -> Time:
    sec = math.floor(value)
    return Time(sec=sec, nanosec=int((value - sec) * 1_000_000_000))


def _duration_from_sec(value: float) -> Duration:
    sec = math.floor(value)
    return Duration(sec=sec, nanosec=int((value - sec) * 1_000_000_000))


def asr_event(msg: VoiceEvent) -> AsrEvent:
    if msg.event_type != VoiceEvent.EVENT_ASR:
        raise ValueError(f"unsupported voice event: {msg.event_type}")
    return AsrEvent(
        text=msg.text.strip(),
        confidence=float(msg.confidence) if msg.has_confidence else None,
        is_final=bool(msg.is_final),
        source=msg.source,
        stamp=f"{msg.stamp.sec}.{msg.stamp.nanosec:09d}",
    )


def loco_intent(
    session_id: str,
    command_id: str,
    text: str,
    created_at: float,
    vx: float,
    vy: float,
    vyaw: float,
    duration_sec: float,
) -> LocoIntent:
    return LocoIntent(
        created_at=_time_from_sec(created_at),
        source="voice_bridge",
        session_id=session_id,
        command_id=command_id,
        text=text,
        vx=float(vx),
        vy=float(vy),
        vyaw=float(vyaw),
        duration=_duration_from_sec(duration_sec),
    )


def action_intent(
    session_id: str,
    command_id: str,
    text: str,
    created_at: float,
    action: str,
    priority: str,
) -> ActionIntent:
    return ActionIntent(
        created_at=_time_from_sec(created_at),
        source="voice_bridge",
        session_id=session_id,
        command_id=command_id,
        text=text,
        action=action.lower(),
        priority=priority.lower(),
    )
