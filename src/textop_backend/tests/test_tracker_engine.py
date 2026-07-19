from pathlib import Path

import numpy as np
import pytest
import yaml

from textop_backend.manifest import load_manifest
from textop_backend.reference import MotionReferenceSegment
from textop_backend.tracker import RobotState
from textop_backend.tracker_engine import ReferencePending, TrackerEngine


class FakePolicy:
    def __init__(self):
        self.observations = []

    def predict(self, observation):
        self.observations.append(observation.copy())
        return np.arange(29, dtype=np.float32)


def _manifest(tmp_path: Path):
    joints = [f"j{i}" for i in range(29)]
    data = {
        "schema_version": 1,
        "model_id": "test",
        "robot_profile": "g1_29dof_unitree_v1",
        "control_profile": "textop_tracker_v1",
        "control_frequency": 50,
        "policy": {
            "path": "p.onnx",
            "sha256": "a" * 64,
            "input_name": "obs",
            "output_name": "actions",
            "input_shape": [1, 431],
            "output_shape": [1, 29],
        },
        "generator": {
            "checkpoint": {"path": "ckpt.pth", "sha256": "b" * 64},
            "vae": {"path": "vae.pth", "sha256": "c" * 64},
            "normalization": {"path": "meanstd.pkl", "sha256": "e" * 64},
            "clip": {"path": "ViT-B-32.pt", "sha256": "f" * 64},
        },
        "joint_names": {"isaaclab": joints, "unitree": joints},
        "default_q": [1.0] * 29,
        "action_scale": [0.5] * 29,
        "kp": [40.0] * 29,
        "kd": [1.0] * 29,
        "reference": {"future_steps": 5, "anchor_body": "torso_link", "quaternion_order": "wxyz"},
    }
    path = tmp_path / "m.yaml"
    path.write_text(yaml.safe_dump(data), encoding="utf-8")
    return load_manifest(path, verify_assets=False)


def _segment():
    return MotionReferenceSegment(
        request_id="r1", segment_index=0, start_frame=0, dt=0.02, reset=True, end_of_motion=True,
        joint_position=np.zeros((2, 29), np.float32), joint_velocity=np.zeros((2, 29), np.float32),
        anchor_position=np.zeros((2, 3), np.float32),
        anchor_orientation_wxyz=np.tile([1, 0, 0, 0], (2, 1)).astype(np.float32),
    )


def test_engine_runs_policy_tracks_last_action_and_advances_frame(tmp_path):
    policy = FakePolicy()
    engine = TrackerEngine(_manifest(tmp_path), policy)
    engine.append_reference(_segment())
    state = RobotState(
        anchor_position_w=np.zeros(3, np.float32), anchor_orientation_wxyz=np.array([1, 0, 0, 0], np.float32),
        linear_velocity_w=np.zeros(3, np.float32), angular_velocity_b=np.zeros(3, np.float32),
        joint_position_unitree=np.ones(29, np.float32), joint_velocity_unitree=np.zeros(29, np.float32),
    )

    first = engine.step("r1", state)
    second = engine.step("r1", state)

    assert first.frame == 0 and second.frame == 1
    np.testing.assert_array_equal(first.command.q, 1 + np.arange(29) * 0.5)
    np.testing.assert_array_equal(policy.observations[0][402:431], np.zeros(29))
    np.testing.assert_array_equal(policy.observations[1][402:431], np.arange(29))
    assert second.motion_complete is True


def test_reset_clears_frame_and_last_action(tmp_path):
    policy = FakePolicy()
    engine = TrackerEngine(_manifest(tmp_path), policy)
    engine.append_reference(_segment())
    engine.reset()

    assert engine.frame == 0
    np.testing.assert_array_equal(engine.last_action, np.zeros(29))


def test_engine_does_not_advance_beyond_generated_reference(tmp_path):
    policy = FakePolicy()
    engine = TrackerEngine(_manifest(tmp_path), policy)
    segment = _segment()
    segment.end_of_motion = False
    engine.append_reference(segment)
    state = RobotState(
        anchor_position_w=np.zeros(3, np.float32), anchor_orientation_wxyz=np.array([1, 0, 0, 0], np.float32),
        linear_velocity_w=np.zeros(3, np.float32), angular_velocity_b=np.zeros(3, np.float32),
        joint_position_unitree=np.ones(29, np.float32), joint_velocity_unitree=np.zeros(29, np.float32),
    )

    engine.step("r1", state)
    engine.step("r1", state)
    with pytest.raises(ReferencePending):
        engine.step("r1", state)

    assert engine.frame == 2
    assert len(policy.observations) == 2
