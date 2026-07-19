import numpy as np
import pytest

from textop_backend.generator import StaleGeneration
from textop_backend.generator_engine import GeneratorEngine, PrimitiveResult


class FakeRuntime:
    history_len = 2
    future_len = 8
    dt = 0.02

    def __init__(self):
        self.calls = []

    def initial_state(self):
        return "history-0", "pose-0"

    def encode_text(self, prompt):
        return f"embedding:{prompt}"

    def generate(self, embedding, history, absolute_pose):
        self.calls.append((embedding, history, absolute_pose))
        base = len(self.calls) * 100
        frames = 10
        dof = np.arange(frames * 23, dtype=np.float32).reshape(frames, 23) + base
        return PrimitiveResult(
            future_motion=f"history-{len(self.calls)}",
            absolute_pose=f"pose-{len(self.calls)}",
            dof_position=dof,
            dof_velocity=dof + 1000,
            anchor_position=np.zeros((frames, 3), np.float32),
            anchor_orientation_xyzw=np.tile([0, 0, 0, 1], (frames, 1)).astype(np.float32),
        )


def test_generator_publishes_only_eight_future_frames_and_carries_state():
    runtime = FakeRuntime()
    engine = GeneratorEngine(runtime)
    token = engine.begin("r1", "wave")

    first = engine.generate_next(token)
    second = engine.generate_next(token, end_of_motion=True)

    assert first.joint_position.shape == (8, 29)
    assert first.segment_index == 0 and first.start_frame == 0 and first.reset
    assert second.segment_index == 1 and second.start_frame == 8 and second.end_of_motion
    assert runtime.calls[0] == ("embedding:wave", "history-0", "pose-0")
    assert runtime.calls[1] == ("embedding:wave", "history-1", "pose-1")
    np.testing.assert_array_equal(first.anchor_orientation_wxyz[0], [1, 0, 0, 0])
    # Wrist pitch/yaw slots are absent in the 23-DoF generator and remain zero.
    np.testing.assert_array_equal(first.joint_position[:, 23:29], 0)


def test_cancel_rejects_late_primitive_result():
    engine = GeneratorEngine(FakeRuntime())
    token = engine.begin("r1", "wave")
    engine.cancel("r1")
    with pytest.raises(StaleGeneration):
        engine.generate_next(token)


def test_replace_changes_text_but_preserves_history_and_pose():
    runtime = FakeRuntime()
    engine = GeneratorEngine(runtime)
    old = engine.begin("r1", "wave")
    engine.generate_next(old)

    new = engine.replace("r2", "turn left")
    segment = engine.generate_next(new)

    assert runtime.calls[1] == ("embedding:turn left", "history-1", "pose-1")
    assert segment.request_id == "r2"
    assert segment.segment_index == 0
    assert segment.start_frame == 0
    assert segment.reset
    with pytest.raises(StaleGeneration):
        engine.generate_next(old)
