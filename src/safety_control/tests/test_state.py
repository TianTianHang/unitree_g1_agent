from types import SimpleNamespace

from builtin_interfaces.msg import Time

from g1_agent_msgs.msg import RobotStateSummary
from safety_control.state import RobotStateTracker, normalize_mode


def test_normalize_mode_aliases():
    assert normalize_mode("sport") == "sport_api_loco"
    assert normalize_mode("internal_ctrl") == "sport_api_loco"
    assert normalize_mode("user") == "user_ctrl"


def test_state_tracker_builds_snapshot_from_lowstate_and_health():
    tracker = RobotStateTracker(state_timeout_ms=300)
    summary = RobotStateSummary(
        stamp=Time(sec=10),
        mode=RobotStateSummary.MODE_SPORT_API_LOCO,
        motor_count=35,
        has_max_temperature=True,
        max_temperature_c=42.5,
    )
    summary.velocity.linear.x = 0.1
    summary.velocity.angular.z = 0.2
    tracker.update_from_summary(summary, now_sec=10.0)

    status = SimpleNamespace(
        level=0,
        message="ok",
        values=[
            SimpleNamespace(key="state", value='"ok"'),
            SimpleNamespace(key="lowstate_age_ms", value="10"),
        ],
    )
    tracker.update_from_health(SimpleNamespace(status=[status]), now_sec=10.01)

    snapshot = tracker.get_snapshot(10.05)

    assert snapshot.health_state == "ok"
    assert snapshot.lowstate_age_ms == 50
    assert snapshot.mode == "sport_api_loco"
    assert snapshot.motor_count == 35
    assert snapshot.max_temperature == 42.5
    assert snapshot.current_velocity == {"vx": 0.1, "vy": 0.0, "vyaw": 0.2}


def test_state_tracker_accepts_ros_byte_diagnostic_level():
    tracker = RobotStateTracker(state_timeout_ms=300)
    tracker.update_from_summary(RobotStateSummary(stamp=Time(sec=10)), now_sec=10.0)

    tracker.update_from_health(
        SimpleNamespace(status=[SimpleNamespace(level=b"\x00", message="ok", values=[])]),
        now_sec=10.01,
    )
    assert tracker.get_snapshot(10.02).health_state == "ok"

    tracker.update_from_health(
        SimpleNamespace(status=[SimpleNamespace(level=b"\x01", message="degraded", values=[])]),
        now_sec=10.03,
    )
    assert tracker.get_snapshot(10.04).health_state == "degraded"


def test_state_tracker_uses_lowstate_producer_timestamp_for_age():
    tracker = RobotStateTracker(state_timeout_ms=300)
    tracker.update_from_summary(
        RobotStateSummary(
            stamp=Time(sec=9, nanosec=500_000_000),
            motor_count=35,
            has_max_temperature=True,
            max_temperature_c=42.5,
        ),
        now_sec=10.0,
    )

    snapshot = tracker.get_snapshot(10.1)

    assert snapshot.lowstate_age_ms == 600
