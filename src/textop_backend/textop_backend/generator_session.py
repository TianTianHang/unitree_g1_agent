from __future__ import annotations

import math


class GeneratorSession:
    """ROS-independent accounting for one TextOp action execution."""

    def __init__(self, *, future_len: int, dt: float) -> None:
        self.future_len = future_len
        self.dt = dt
        self.active_request_id: str | None = None
        self.required_primitives = 0
        self.generated_frames = 0
        self.executed_frames = 0

    def primitive_count(self, duration_seconds: float) -> int:
        if not math.isfinite(duration_seconds) or duration_seconds <= 0.0:
            raise ValueError("duration must be finite and positive")
        return math.ceil(duration_seconds / (self.future_len * self.dt))

    def begin(self, request_id: str, *, duration_seconds: float) -> None:
        if self.active_request_id is not None:
            raise RuntimeError("a session is already active")
        if not request_id:
            raise ValueError("request_id must not be empty")
        self.required_primitives = self.primitive_count(duration_seconds)
        self.active_request_id = request_id
        self.generated_frames = 0
        self.executed_frames = 0

    def replace(self, request_id: str, *, duration_seconds: float) -> None:
        if self.active_request_id is None:
            raise RuntimeError("session is not active")
        if not request_id:
            raise ValueError("request_id must not be empty")
        self.required_primitives = self.primitive_count(duration_seconds)
        self.active_request_id = request_id
        self.generated_frames = 0
        self.executed_frames = 0

    def mark_generated(self, request_id: str) -> bool:
        self._ensure_active(request_id)
        self.generated_frames += self.future_len
        if self.generated_frames > self.total_frames:
            raise RuntimeError("too many primitives generated")
        return self.generated_frames == self.total_frames

    def update_executed(self, request_id: str, executed_frames: int) -> None:
        if request_id != self.active_request_id:
            return
        if executed_frames < self.executed_frames:
            return
        self.executed_frames = min(int(executed_frames), self.total_frames)

    @property
    def total_frames(self) -> int:
        return self.required_primitives * self.future_len

    @property
    def execution_complete(self) -> bool:
        return self.active_request_id is not None and self.executed_frames >= self.total_frames

    def cancel(self, request_id: str) -> None:
        if request_id == self.active_request_id:
            self.active_request_id = None

    def finish(self, request_id: str) -> None:
        self._ensure_active(request_id)
        self.active_request_id = None

    def _ensure_active(self, request_id: str) -> None:
        if self.active_request_id is None:
            raise RuntimeError("session is not active")
        if request_id != self.active_request_id:
            raise RuntimeError("request does not own the active session")
