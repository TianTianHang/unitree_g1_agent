from __future__ import annotations

import math
from dataclasses import dataclass


@dataclass(frozen=True)
class OdometryValidation:
    stamp_sec: float
    age_sec: float


def _stamp_seconds(stamp) -> float:
    return float(stamp.sec) + float(stamp.nanosec) * 1e-9


def _values(message) -> tuple[float, ...]:
    pose = message.pose.pose
    twist = message.twist.twist
    return (
        float(pose.position.x),
        float(pose.position.y),
        float(pose.position.z),
        float(pose.orientation.x),
        float(pose.orientation.y),
        float(pose.orientation.z),
        float(pose.orientation.w),
        float(twist.linear.x),
        float(twist.linear.y),
        float(twist.linear.z),
        float(twist.angular.x),
        float(twist.angular.y),
        float(twist.angular.z),
    )


def validate_odometry(
    message,
    *,
    now_sec: float,
    timeout: float,
    expected_frame: str,
    expected_child_frame: str,
    future_tolerance: float = 0.02,
) -> OdometryValidation:
    if timeout <= 0.0:
        raise ValueError("odometry timeout must be positive")
    if message.header.frame_id != expected_frame:
        raise ValueError(
            f"odometry frame_id mismatch: expected={expected_frame} actual={message.header.frame_id}"
        )
    if message.child_frame_id != expected_child_frame:
        raise ValueError(
            "odometry child_frame_id mismatch: "
            f"expected={expected_child_frame} actual={message.child_frame_id}"
        )
    values = _values(message)
    if not all(math.isfinite(value) for value in values):
        raise ValueError("odometry pose and twist must contain finite values")
    quaternion = values[3:7]
    norm = math.sqrt(sum(value * value for value in quaternion))
    if not math.isclose(norm, 1.0, abs_tol=1e-3):
        raise ValueError(f"odometry quaternion must be normalized: norm={norm}")
    stamp_sec = _stamp_seconds(message.header.stamp)
    if not math.isfinite(stamp_sec) or stamp_sec <= 0.0:
        raise ValueError("odometry timestamp must be positive and finite")
    age_sec = now_sec - stamp_sec
    if age_sec < -future_tolerance:
        raise ValueError(f"odometry timestamp is in the future: age_sec={age_sec}")
    if age_sec > timeout:
        raise ValueError(f"odometry is stale: age_sec={age_sec}")
    return OdometryValidation(stamp_sec=stamp_sec, age_sec=max(0.0, age_sec))


class ReadinessGate:
    def __init__(self) -> None:
        self._ready = False
        self._reason = "tracker readiness unavailable"
        self._updated_at: float | None = None

    def update(self, *, ready: bool, reason: str, at_sec: float) -> None:
        self._ready = bool(ready)
        self._reason = reason if reason else ("" if ready else "tracker not ready")
        self._updated_at = float(at_sec)

    def can_accept(self, *, now_sec: float, timeout: float) -> tuple[bool, str | None]:
        if self._updated_at is None:
            return False, "tracker readiness unavailable"
        if now_sec - self._updated_at > timeout:
            return False, "tracker readiness stale"
        if not self._ready:
            return False, self._reason
        return True, None
