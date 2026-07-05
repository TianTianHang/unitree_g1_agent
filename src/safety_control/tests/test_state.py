from types import SimpleNamespace

from safety_control.state import RobotStateTracker, extract_mode, extract_velocity, normalize_mode


def test_normalize_mode_aliases():
    assert normalize_mode("sport") == "sport_api_loco"
    assert normalize_mode("internal_ctrl") == "sport_api_loco"
    assert normalize_mode("user") == "user_ctrl"


def test_extract_mode_from_json_payload():
    assert extract_mode('{"control_owner": "user"}') == "user_ctrl"
    assert extract_mode('{"mode": "sport_api_loco"}') == "sport_api_loco"
    assert extract_mode('{"rpy": [0, 0, 0]}') is None


def test_extract_velocity_from_common_shapes():
    assert extract_velocity({"velocity": [0.1, 0.0, 0.2]}) == {"vx": 0.1, "vy": 0.0, "vyaw": 0.2}
    assert extract_velocity({"current_velocity": {"x": 0.1, "y": 0.2, "z": 0.3}}) == {
        "vx": 0.1,
        "vy": 0.2,
        "vyaw": 0.3,
    }


def test_state_tracker_builds_snapshot_from_lowstate_and_health():
    tracker = RobotStateTracker(state_timeout_ms=300)
    tracker.update_from_lowstate_text(
        '{"stamp_sec": 10.0, "motor_count": 35, "max_temperature_c": 42.5, "velocity": [0.1, 0.0, 0.2]}',
        now_sec=10.0,
    )

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
    assert snapshot.motor_count == 35
    assert snapshot.max_temperature == 42.5
    assert snapshot.current_velocity == {"vx": 0.1, "vy": 0.0, "vyaw": 0.2}


def test_state_tracker_uses_lowstate_producer_timestamp_for_age():
    tracker = RobotStateTracker(state_timeout_ms=300)
    tracker.update_from_lowstate_text(
        '{"stamp_sec": 9.5, "motor_count": 35, "max_temperature_c": 42.5}',
        now_sec=10.0,
    )

    snapshot = tracker.get_snapshot(10.1)

    assert snapshot.lowstate_age_ms == 600
