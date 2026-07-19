from __future__ import annotations

from dataclasses import dataclass
from enum import Enum, auto


class GeneratorState(Enum):
    UNLOADED = auto()
    READY = auto()
    GENERATING = auto()
    DRAINING = auto()
    FAULT = auto()


class StaleGeneration(RuntimeError):
    pass


@dataclass(frozen=True)
class GenerationToken:
    request_id: str
    generation: int


class GeneratorStateMachine:
    def __init__(self) -> None:
        self.state = GeneratorState.UNLOADED
        self.request_id: str | None = None
        self.prompt: str | None = None
        self._generation = 0

    def loaded(self) -> None:
        if self.state is not GeneratorState.UNLOADED:
            raise RuntimeError(f"cannot load from {self.state.name}")
        self.state = GeneratorState.READY

    def begin(self, request_id: str, prompt: str) -> GenerationToken:
        if self.state is not GeneratorState.READY:
            raise RuntimeError(f"cannot begin from {self.state.name}")
        if not request_id or not prompt.strip():
            raise ValueError("request_id and prompt must not be empty")
        self._generation += 1
        self.request_id = request_id
        self.prompt = prompt
        self.state = GeneratorState.GENERATING
        return GenerationToken(request_id, self._generation)

    def replace(self, request_id: str, prompt: str) -> GenerationToken:
        if self.state not in {GeneratorState.GENERATING, GeneratorState.DRAINING}:
            raise RuntimeError(f"cannot replace from {self.state.name}")
        if not request_id or not prompt.strip():
            raise ValueError("request_id and prompt must not be empty")
        self._generation += 1
        self.request_id = request_id
        self.prompt = prompt
        self.state = GeneratorState.GENERATING
        return GenerationToken(request_id, self._generation)

    def accept(self, token: GenerationToken) -> None:
        self.ensure_active(token)
        if self.state is not GeneratorState.GENERATING:
            raise StaleGeneration("generation is no longer active")
        self.state = GeneratorState.DRAINING

    def drained(self, token: GenerationToken) -> None:
        self._check(token)
        if self.state is not GeneratorState.DRAINING:
            raise StaleGeneration("generation is not draining")
        self.request_id = None
        self.prompt = None
        self.state = GeneratorState.READY

    def cancel(self, request_id: str) -> None:
        if self.request_id != request_id:
            return
        self._generation += 1
        self.request_id = None
        self.prompt = None
        self.state = GeneratorState.READY

    def fault(self) -> None:
        self._generation += 1
        self.request_id = None
        self.prompt = None
        self.state = GeneratorState.FAULT

    def _check(self, token: GenerationToken) -> None:
        if token.generation != self._generation or token.request_id != self.request_id:
            raise StaleGeneration("stale generation result")

    def ensure_active(self, token: GenerationToken) -> None:
        self._check(token)
        if self.state is not GeneratorState.GENERATING:
            raise StaleGeneration("generation is no longer active")
