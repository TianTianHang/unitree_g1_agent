from __future__ import annotations

from dataclasses import dataclass

import numpy as np
from numpy.typing import NDArray


class ReferenceError(ValueError):
    pass


FloatArray = NDArray[np.float32]


@dataclass
class MotionReferenceSegment:
    request_id: str
    segment_index: int
    start_frame: int
    dt: float
    reset: bool
    end_of_motion: bool
    joint_position: FloatArray
    joint_velocity: FloatArray
    anchor_position: FloatArray
    anchor_orientation_wxyz: FloatArray


@dataclass(frozen=True)
class ReferenceWindow:
    joint_position: FloatArray
    joint_velocity: FloatArray
    anchor_position: FloatArray
    anchor_orientation_wxyz: FloatArray


class ReferenceBuffer:
    def __init__(self, future_steps: int, *, expected_dt: float = 0.02) -> None:
        self.future_steps = future_steps
        self.expected_dt = expected_dt
        self.clear()

    def clear(self) -> None:
        self.request_id: str | None = None
        self.frame_count = 0
        self.next_segment_index = 0
        self.end_of_motion = False
        self._joint_position = np.empty((0, 29), dtype=np.float32)
        self._joint_velocity = np.empty((0, 29), dtype=np.float32)
        self._anchor_position = np.empty((0, 3), dtype=np.float32)
        self._anchor_orientation = np.empty((0, 4), dtype=np.float32)

    def append(self, segment: MotionReferenceSegment) -> None:
        self._validate(segment)
        if segment.reset:
            self.clear()
            self.request_id = segment.request_id
        elif self.request_id != segment.request_id:
            raise ReferenceError("request_id does not match active request")
        if segment.segment_index != self.next_segment_index:
            raise ReferenceError("segment_index is not contiguous")
        if segment.start_frame != self.frame_count:
            raise ReferenceError("start_frame is not contiguous")
        self._joint_position = np.concatenate((self._joint_position, segment.joint_position), axis=0)
        self._joint_velocity = np.concatenate((self._joint_velocity, segment.joint_velocity), axis=0)
        self._anchor_position = np.concatenate((self._anchor_position, segment.anchor_position), axis=0)
        self._anchor_orientation = np.concatenate((self._anchor_orientation, segment.anchor_orientation_wxyz), axis=0)
        self.frame_count += segment.joint_position.shape[0]
        self.next_segment_index += 1
        self.end_of_motion = segment.end_of_motion

    def window(self, request_id: str, frame: int) -> ReferenceWindow:
        if request_id != self.request_id or self.frame_count == 0:
            raise ReferenceError("reference request is not available")
        indices = np.clip(np.arange(frame, frame + self.future_steps), 0, self.frame_count - 1)
        return ReferenceWindow(
            joint_position=self._joint_position[indices],
            joint_velocity=self._joint_velocity[indices],
            anchor_position=self._anchor_position[indices],
            anchor_orientation_wxyz=self._anchor_orientation[indices],
        )

    def _validate(self, segment: MotionReferenceSegment) -> None:
        if not segment.request_id:
            raise ReferenceError("request_id must not be empty")
        if segment.dt != self.expected_dt:
            raise ReferenceError("dt does not match TextOp control period")
        arrays = (
            (segment.joint_position, 29, "joint_position"),
            (segment.joint_velocity, 29, "joint_velocity"),
            (segment.anchor_position, 3, "anchor_position"),
            (segment.anchor_orientation_wxyz, 4, "anchor_orientation_wxyz"),
        )
        frame_count = segment.joint_position.shape[0] if segment.joint_position.ndim == 2 else -1
        for value, width, name in arrays:
            if value.ndim != 2 or value.shape != (frame_count, width) or frame_count <= 0:
                raise ReferenceError(f"{name} has an invalid shape")
            if not np.isfinite(value).all():
                raise ReferenceError(f"{name} must contain finite values")
        norms = np.linalg.norm(segment.anchor_orientation_wxyz, axis=1)
        if not np.allclose(norms, 1.0, atol=1e-3):
            raise ReferenceError("anchor quaternions must be normalized")
        if segment.reset and (segment.segment_index != 0 or segment.start_frame != 0):
            raise ReferenceError("reset segment must start at segment and frame zero")
