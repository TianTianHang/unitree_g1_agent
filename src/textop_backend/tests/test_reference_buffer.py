import numpy as np
import pytest

from textop_backend.reference import MotionReferenceSegment, ReferenceBuffer, ReferenceError


def _segment(*, request_id="r1", index=0, start=0, frames=3, reset=False, end=False):
    return MotionReferenceSegment(
        request_id=request_id,
        segment_index=index,
        start_frame=start,
        dt=0.02,
        reset=reset,
        end_of_motion=end,
        joint_position=np.zeros((frames, 29), dtype=np.float32),
        joint_velocity=np.ones((frames, 29), dtype=np.float32),
        anchor_position=np.zeros((frames, 3), dtype=np.float32),
        anchor_orientation_wxyz=np.tile([1.0, 0.0, 0.0, 0.0], (frames, 1)).astype(np.float32),
    )


def test_reset_replaces_old_request_and_future_clamps_to_last_frame():
    buffer = ReferenceBuffer(future_steps=5)
    buffer.append(_segment(reset=True))
    buffer.append(_segment(index=1, start=3, frames=2, end=True))

    window = buffer.window("r1", frame=3)
    assert window.joint_position.shape == (5, 29)
    np.testing.assert_array_equal(window.joint_velocity, np.ones((5, 29), dtype=np.float32))
    assert buffer.end_of_motion is True

    buffer.append(_segment(request_id="r2", reset=True, frames=1))
    assert buffer.request_id == "r2"
    assert buffer.frame_count == 1


def test_rejects_non_contiguous_segment():
    buffer = ReferenceBuffer(future_steps=5)
    buffer.append(_segment(reset=True))
    with pytest.raises(ReferenceError, match="start_frame"):
        buffer.append(_segment(index=1, start=4))


def test_rejects_non_finite_values():
    segment = _segment(reset=True)
    segment.joint_position[0, 0] = np.nan
    with pytest.raises(ReferenceError, match="finite"):
        ReferenceBuffer(future_steps=5).append(segment)
