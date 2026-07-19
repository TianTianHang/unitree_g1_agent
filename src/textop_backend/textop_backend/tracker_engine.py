from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol

import numpy as np
from numpy.typing import NDArray

from .manifest import ModelManifest
from .reference import MotionReferenceSegment, ReferenceBuffer
from .tracker import MotorCommand, RobotState, build_observation, decode_action

FloatArray = NDArray[np.float32]


class ReferencePending(RuntimeError):
    """The tracker consumed all generated frames but the motion is not final."""


class Policy(Protocol):
    def predict(self, observation: FloatArray) -> FloatArray: ...


@dataclass(frozen=True)
class TrackerStep:
    frame: int
    command: MotorCommand
    motion_complete: bool


class TrackerEngine:
    def __init__(self, manifest: ModelManifest, policy: Policy) -> None:
        self.manifest = manifest
        self.policy = policy
        self.references = ReferenceBuffer(manifest.future_steps, expected_dt=manifest.control_period)
        self.reset()

    def reset(self) -> None:
        self.references.clear()
        self.frame = 0
        self.last_action = np.zeros(29, dtype=np.float32)

    def append_reference(self, segment: MotionReferenceSegment) -> None:
        if segment.reset:
            replacing = self.references.request_id is not None
            self.frame = 0
            if not replacing:
                self.last_action.fill(0.0)
        self.references.append(segment)

    def step(self, request_id: str, state: RobotState) -> TrackerStep:
        if self.frame >= self.references.frame_count and not self.references.end_of_motion:
            raise ReferencePending("waiting for the next reference segment")
        window = self.references.window(request_id, self.frame)
        observation = build_observation(
            window.joint_position,
            window.joint_velocity,
            window.anchor_position,
            window.anchor_orientation_wxyz,
            state,
            self.last_action,
            default_q_unitree=np.asarray(self.manifest.default_q, dtype=np.float32),
            unitree_to_isaaclab=self.manifest.unitree_to_isaaclab,
        )
        action = np.asarray(self.policy.predict(observation), dtype=np.float32).reshape(-1)
        command = decode_action(
            action,
            isaaclab_to_unitree=self.manifest.isaaclab_to_unitree,
            default_q_unitree=np.asarray(self.manifest.default_q, dtype=np.float32),
            action_scale_unitree=np.asarray(self.manifest.action_scale, dtype=np.float32),
            kp_unitree=np.asarray(self.manifest.kp, dtype=np.float32),
            kd_unitree=np.asarray(self.manifest.kd, dtype=np.float32),
        )
        completed = self.references.end_of_motion and self.frame >= self.references.frame_count - 1
        result = TrackerStep(frame=self.frame, command=command, motion_complete=completed)
        self.last_action = action.copy()
        if not completed:
            self.frame += 1
        return result
