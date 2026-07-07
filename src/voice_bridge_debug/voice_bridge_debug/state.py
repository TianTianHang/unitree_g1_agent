from __future__ import annotations

import json
import threading
import time
from dataclasses import asdict, dataclass, field
from typing import Any, Callable


@dataclass
class TimelineEvent:
    timestamp: float
    source: str
    kind: str
    data: dict[str, Any]
    session_id: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class HealthState:
    summary: str
    max_level: int | None
    status_count: int
    raw: dict[str, Any] | None
    updated_at: float | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "summary": self.summary,
            "max_level": self.max_level,
            "status_count": self.status_count,
            "raw": self.raw,
        }


def parse_json_topic(raw: str) -> dict[str, Any]:
    try:
        data = json.loads(raw)
    except (TypeError, json.JSONDecodeError) as exc:
        return {"raw": raw, "parse_error": str(exc)}
    if not isinstance(data, dict):
        return {"raw": raw, "parse_error": "JSON payload must be an object"}
    return {"data": data}


def _diagnostic_level_to_int(level: Any) -> int | None:
    if level is None:
        return None
    if isinstance(level, (bytes, bytearray, memoryview)):
        raw = bytes(level)
        return raw[0] if raw else None
    return int(level)


def _summary_from_level(level: int | None) -> str:
    if level is None:
        return "unknown"
    if level <= 0:
        return "ok"
    if level == 1:
        return "warn"
    return "error"


def normalize_health(
    msg: Any,
    now_sec: float,
    stale_after_sec: float,
    last: HealthState | None = None,
) -> HealthState:
    statuses = []
    levels: list[int] = []
    for status in getattr(msg, "status", []):
        level = _diagnostic_level_to_int(getattr(status, "level", None))
        if level is not None:
            levels.append(level)
        values = {
            str(getattr(item, "key", "")): str(getattr(item, "value", ""))
            for item in getattr(status, "values", [])
            if getattr(item, "key", "")
        }
        statuses.append(
            {
                "name": getattr(status, "name", ""),
                "level": level,
                "message": getattr(status, "message", ""),
                "values": values,
            }
        )
    max_level = max(levels) if levels else None
    summary = _summary_from_level(max_level)
    if last is not None and last.updated_at is not None and now_sec - last.updated_at > stale_after_sec:
        return HealthState(
            summary="stale",
            max_level=last.max_level,
            status_count=last.status_count,
            raw=last.raw,
            updated_at=last.updated_at,
        )
    return HealthState(summary=summary, max_level=max_level, status_count=len(statuses), raw={"statuses": statuses}, updated_at=now_sec)


@dataclass
class PanelState:
    max_events: int = 200
    notify_web: Callable[[dict[str, Any]], None] | None = None
    robot_mode: dict[str, Any] | None = None
    safety_state: dict[str, Any] | None = None
    health: HealthState | None = None
    voice_session: dict[str, Any] | None = None
    last_asr_text: str | None = None
    last_decision: dict[str, Any] | None = None
    last_error: str | None = None
    agent_backend: str | None = None
    agent_result: dict[str, Any] | None = None
    timeline: list[TimelineEvent] = field(default_factory=list)
    _lock: threading.RLock = field(default_factory=threading.RLock)

    def push_event(
        self,
        source: str,
        kind: str,
        data: dict[str, Any],
        session_id: str | None = None,
        timestamp: float | None = None,
    ) -> dict[str, Any]:
        event = TimelineEvent(
            timestamp=float(timestamp if timestamp is not None else time.time()),
            source=source,
            kind=kind,
            data=data,
            session_id=session_id,
        )
        with self._lock:
            self.timeline.append(event)
            self.timeline = self.timeline[-self.max_events :]
        message = {"type": "timeline_event", "data": event.to_dict()}
        if self.notify_web is not None:
            self.notify_web(message)
        return message

    def set_robot_state(self, **updates: Any) -> dict[str, Any]:
        with self._lock:
            for key, value in updates.items():
                setattr(self, key, value)
            snapshot = self.robot_state_snapshot()
        message = {"type": "robot_state", "data": snapshot}
        if self.notify_web is not None:
            self.notify_web(message)
        return message

    def set_agent_result(self, result: dict[str, Any]) -> dict[str, Any]:
        with self._lock:
            self.agent_result = result
        message = {"type": "agent_result", "data": result}
        if self.notify_web is not None:
            self.notify_web(message)
        return message

    def robot_state_snapshot(self) -> dict[str, Any]:
        health = self.health.to_dict() if self.health is not None else None
        return {
            "robot_mode": self.robot_mode,
            "safety_state": self.safety_state,
            "health": health,
            "voice_session": self.voice_session,
            "last_asr_text": self.last_asr_text,
            "last_decision": self.last_decision,
            "last_error": self.last_error,
            "agent_backend": self.agent_backend,
        }

    def snapshot(self) -> dict[str, Any]:
        with self._lock:
            return {
                "robot_state": self.robot_state_snapshot(),
                "agent_result": self.agent_result,
                "timeline": [event.to_dict() for event in self.timeline],
            }
