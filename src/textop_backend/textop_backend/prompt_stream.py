from __future__ import annotations

import math
from dataclasses import dataclass
from enum import Enum


class CommandState(str, Enum):
    PENDING = "pending"
    ACTIVE = "active"
    SUPERSEDED = "superseded"
    COMPLETED = "completed"
    CANCELED = "canceled"
    FAILED = "failed"


@dataclass(frozen=True)
class PromptCommand:
    request_id: str
    prompt: str
    duration_sec: float

    def validate(self) -> None:
        if not self.request_id:
            raise ValueError("request_id must not be empty")
        if not self.prompt.strip():
            raise ValueError("prompt must not be empty")
        if not math.isfinite(self.duration_sec) or self.duration_sec <= 0.0:
            raise ValueError("duration must be finite and positive")


@dataclass(frozen=True)
class CommandOutcome:
    state: CommandState
    reason: str = ""


@dataclass(frozen=True)
class PromptTransition:
    previous: PromptCommand | None
    current: PromptCommand


class PromptStreamCoordinator:
    """Own the latest-wins command stream independently of ROS and GPU code."""

    def __init__(self) -> None:
        self.active: PromptCommand | None = None
        self.pending: PromptCommand | None = None
        self._outcomes: dict[str, CommandOutcome] = {}

    def submit(self, command: PromptCommand) -> None:
        command.validate()
        if command.request_id in self._outcomes or (
            self.active is not None and command.request_id == self.active.request_id
        ):
            raise ValueError("request_id must be unique")
        if self.pending is not None:
            self._outcomes[self.pending.request_id] = CommandOutcome(
                CommandState.SUPERSEDED,
                f"superseded_by:{command.request_id}",
            )
        self.pending = command
        self._outcomes[command.request_id] = CommandOutcome(CommandState.PENDING)

    def activate_pending(self) -> PromptTransition | None:
        if self.pending is None:
            return None
        previous = self.active
        current = self.pending
        self.pending = None
        if previous is not None:
            self._outcomes[previous.request_id] = CommandOutcome(
                CommandState.SUPERSEDED,
                f"superseded_by:{current.request_id}",
            )
        self.active = current
        self._outcomes[current.request_id] = CommandOutcome(CommandState.ACTIVE)
        return PromptTransition(previous=previous, current=current)

    def complete_active(self) -> PromptCommand:
        if self.active is None:
            raise RuntimeError("no active prompt command")
        command = self.active
        self.active = None
        self._outcomes[command.request_id] = CommandOutcome(CommandState.COMPLETED, "motion completed")
        return command

    def cancel_all(self, reason: str) -> tuple[PromptCommand, ...]:
        canceled = tuple(command for command in (self.active, self.pending) if command is not None)
        for command in canceled:
            self._outcomes[command.request_id] = CommandOutcome(CommandState.CANCELED, reason)
        self.active = None
        self.pending = None
        return canceled

    def fail_active(self, reason: str) -> PromptCommand:
        if self.active is None:
            raise RuntimeError("no active prompt command")
        command = self.active
        self.active = None
        self._outcomes[command.request_id] = CommandOutcome(CommandState.FAILED, reason)
        return command

    def outcome(self, request_id: str) -> CommandOutcome | None:
        return self._outcomes.get(request_id)

    def forget(self, request_id: str) -> None:
        if self.active is not None and self.active.request_id == request_id:
            raise RuntimeError("cannot forget active command")
        if self.pending is not None and self.pending.request_id == request_id:
            raise RuntimeError("cannot forget pending command")
        self._outcomes.pop(request_id, None)
