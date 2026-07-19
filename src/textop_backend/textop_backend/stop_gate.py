from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class StopToken:
    request_id: str
    generation: int


def validated_stop_action(message) -> str:
    try:
        command_id = str(message.intent.command_id)
        action = str(message.intent.action)
        validation = message.validation
    except AttributeError as exc:
        raise ValueError("invalid safe stop message") from exc
    if not command_id or validation.command_id != command_id:
        raise ValueError("validation command_id mismatch")
    if validation.command_kind != "action":
        raise ValueError("validation command_kind must be action")
    if validation.decision != "allow":
        raise ValueError("safe stop was not allowed")
    if action not in {"stop", "cancel"}:
        raise ValueError(f"safe stop action must be stop or cancel: {action}")
    return action


class StopGate:
    """Request-scoped stop generation, protected by the caller's lock."""

    def __init__(self) -> None:
        self._generation = 0
        self._active_request_id: str | None = None
        self._stopped_generation: int | None = None
        self._reason: str | None = None

    @property
    def active_request_id(self) -> str | None:
        return self._active_request_id

    def begin(self, request_id: str) -> StopToken:
        if not request_id:
            raise ValueError("request_id must not be empty")
        self._generation += 1
        self._active_request_id = request_id
        self._stopped_generation = None
        self._reason = None
        return StopToken(request_id=request_id, generation=self._generation)

    def request_active_stop(self, *, reason: str) -> str | None:
        request_id = self._active_request_id
        if request_id is None:
            return None
        self.request_stop(request_id, reason=reason)
        return request_id

    def request_stop(self, request_id: str, *, reason: str) -> bool:
        if request_id != self._active_request_id:
            return False
        if self._stopped_generation == self._generation:
            return False
        self._stopped_generation = self._generation
        self._reason = reason
        return True

    def is_stopped(self, token: StopToken) -> bool:
        if token.request_id != self._active_request_id or token.generation != self._generation:
            return True
        return self._stopped_generation == token.generation

    def stop_reason(self, token: StopToken) -> str | None:
        return self._reason if self.is_stopped(token) else None

    def finish(self, token: StopToken) -> None:
        if token.request_id == self._active_request_id and token.generation == self._generation:
            self._active_request_id = None
