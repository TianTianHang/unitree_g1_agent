from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any


@dataclass(frozen=True)
class AsrEvent:
    text: str
    confidence: float | None = None
    is_final: bool = True
    source: str = "unknown"
    stamp: str | None = None


@dataclass(frozen=True)
class AgentRequest:
    session_id: str
    text: str
    asr_confidence: float | None
    robot_mode: str | None = None
    safety_state: str | None = None
    health_state: str | None = None
    image_ref: str | None = None


@dataclass(frozen=True)
class AgentCommand:
    kind: str
    params: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class AgentResult:
    commands: list[AgentCommand] = field(default_factory=list)
    reply_text: str | None = None
    led: dict[str, Any] | None = None
    requires_confirmation: bool = False


@dataclass(frozen=True)
class SessionDecision:
    kind: str
    session_id: str | None = None
    text: str | None = None
    reason: str | None = None
    action: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)
