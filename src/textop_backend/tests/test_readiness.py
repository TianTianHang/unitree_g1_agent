from types import SimpleNamespace

import pytest

from textop_backend.readiness import ReadinessGate, validate_odometry


def _odometry(*, stamp=10.0, frame="odom", child="pelvis", q=(0.0, 0.0, 0.0, 1.0)):
    sec = int(stamp)
    nanosec = int((stamp - sec) * 1e9)
    def vector(xyz):
        return SimpleNamespace(x=xyz[0], y=xyz[1], z=xyz[2])

    return SimpleNamespace(
        header=SimpleNamespace(stamp=SimpleNamespace(sec=sec, nanosec=nanosec), frame_id=frame),
        child_frame_id=child,
        pose=SimpleNamespace(
            pose=SimpleNamespace(
                position=vector((1.0, 2.0, 0.8)),
                orientation=SimpleNamespace(x=q[0], y=q[1], z=q[2], w=q[3]),
            )
        ),
        twist=SimpleNamespace(
            twist=SimpleNamespace(
                linear=vector((0.1, 0.0, 0.0)),
                angular=vector((0.0, 0.0, 0.1)),
            )
        ),
    )


def test_odometry_contract_accepts_fresh_pelvis_sample():
    sample = validate_odometry(
        _odometry(), now_sec=10.05, timeout=0.1, expected_frame="odom", expected_child_frame="pelvis"
    )

    assert sample.stamp_sec == pytest.approx(10.0)
    assert sample.age_sec == pytest.approx(0.05)


@pytest.mark.parametrize(
    ("message", "now", "reason"),
    [
        (_odometry(stamp=9.0), 10.0, "stale"),
        (_odometry(stamp=10.1), 10.0, "future"),
        (_odometry(frame="map"), 10.0, "frame_id"),
        (_odometry(child="torso"), 10.0, "child_frame_id"),
        (_odometry(q=(0.0, 0.0, 0.0, 0.0)), 10.0, "quaternion"),
        (_odometry(q=(float("nan"), 0.0, 0.0, 1.0)), 10.0, "finite"),
    ],
)
def test_odometry_contract_rejects_invalid_sample(message, now, reason):
    with pytest.raises(ValueError, match=reason):
        validate_odometry(
            message, now_sec=now, timeout=0.1, expected_frame="odom", expected_child_frame="pelvis"
        )


def test_readiness_gate_requires_fresh_ready_status():
    gate = ReadinessGate()

    assert gate.can_accept(now_sec=10.0, timeout=0.2) == (False, "tracker readiness unavailable")
    gate.update(ready=False, reason="odometry unavailable", at_sec=10.0)
    assert gate.can_accept(now_sec=10.1, timeout=0.2) == (False, "odometry unavailable")
    gate.update(ready=True, reason="", at_sec=10.1)
    assert gate.can_accept(now_sec=10.2, timeout=0.2) == (True, None)
    assert gate.can_accept(now_sec=10.31, timeout=0.2) == (False, "tracker readiness stale")
