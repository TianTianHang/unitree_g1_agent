from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Protocol

import numpy as np
from numpy.typing import NDArray

from .generator import GenerationToken, GeneratorStateMachine
from .reference import MotionReferenceSegment


FloatArray = NDArray[np.float32]
MUJOCO_TO_ISAACLAB = np.asarray(
    [0, 6, 12, 1, 7, 13, 2, 8, 14, 3, 9, 15, 22, 4, 10, 16, 23, 5, 11, 17, 24, 18, 25, 19, 26, 20, 27, 21, 28],
    dtype=np.int64,
)


@dataclass(frozen=True)
class PrimitiveResult:
    future_motion: Any
    absolute_pose: Any
    dof_position: FloatArray
    dof_velocity: FloatArray
    anchor_position: FloatArray
    anchor_orientation_xyzw: FloatArray


class PrimitiveRuntime(Protocol):
    history_len: int
    future_len: int
    dt: float

    def initial_state(self) -> tuple[Any, Any]: ...
    def encode_text(self, prompt: str) -> Any: ...
    def generate(self, embedding: Any, history: Any, absolute_pose: Any) -> PrimitiveResult: ...


def _expand_23_to_29(value: FloatArray) -> FloatArray:
    if value.ndim != 2 or value.shape[1] != 23:
        raise ValueError("RobotMDAR joint data must have shape [T,23]")
    expanded = np.zeros((value.shape[0], 29), dtype=np.float32)
    expanded[:, :19] = value[:, :19]
    expanded[:, 22:26] = value[:, 19:23]
    return expanded[:, MUJOCO_TO_ISAACLAB]


class GeneratorEngine:
    def __init__(self, runtime: PrimitiveRuntime) -> None:
        if runtime.history_len != 2 or runtime.future_len != 8 or runtime.dt != 0.02:
            raise ValueError("TextOp v1 runtime must use history=2, future=8 and dt=0.02")
        self.runtime = runtime
        self.machine = GeneratorStateMachine()
        self.machine.loaded()

    def begin(self, request_id: str, prompt: str) -> GenerationToken:
        token = self.machine.begin(request_id, prompt)
        self.history, self.absolute_pose = self.runtime.initial_state()
        self.embedding = self.runtime.encode_text(prompt)
        self.segment_index = 0
        self.start_frame = 0
        return token

    def cancel(self, request_id: str) -> None:
        self.machine.cancel(request_id)

    def generate_next(self, token: GenerationToken, *, end_of_motion: bool = False) -> MotionReferenceSegment:
        self.machine.ensure_active(token)
        result = self.runtime.generate(self.embedding, self.history, self.absolute_pose)
        self.machine.ensure_active(token)
        self.history = result.future_motion
        self.absolute_pose = result.absolute_pose
        tail = slice(-self.runtime.future_len, None)
        orientation = np.asarray(result.anchor_orientation_xyzw[tail], dtype=np.float32)[:, [3, 0, 1, 2]]
        segment = MotionReferenceSegment(
            request_id=token.request_id,
            segment_index=self.segment_index,
            start_frame=self.start_frame,
            dt=self.runtime.dt,
            reset=self.segment_index == 0,
            end_of_motion=end_of_motion,
            joint_position=_expand_23_to_29(np.asarray(result.dof_position[tail], dtype=np.float32)),
            joint_velocity=_expand_23_to_29(np.asarray(result.dof_velocity[tail], dtype=np.float32)),
            anchor_position=np.asarray(result.anchor_position[tail], dtype=np.float32),
            anchor_orientation_wxyz=orientation,
        )
        self.segment_index += 1
        self.start_frame += self.runtime.future_len
        if end_of_motion:
            self.machine.accept(token)
        return segment
