import pytest

from g1_interface.node import (
    build_low_state_payload,
    build_mode_payload,
    build_health_status,
    check_sport_command_allowed,
    parse_safe_loco_command,
    parse_stop_command,
)
from g1_interface.internal_types import LowStateSummary


def test_parse_safe_loco_command_clamps_to_required_fields():
    command = parse_safe_loco_command(
        '{"validation_result": {"allowed": true}, "vx": 0.2, "vy": -0.1, "vyaw": 0.3, "duration_sec": 1.5}'
    )

    assert command.action == "set_velocity"
    assert command.params == {"velocity": [0.2, -0.1, 0.3], "duration": 1.5}


def test_parse_safe_loco_command_rejects_missing_velocity():
    with pytest.raises(ValueError, match="missing required loco field"):
        parse_safe_loco_command('{"validation_result": {"allowed": true}, "vx": 0.2, "vy": 0.0}')


def test_parse_safe_loco_command_requires_safety_validation():
    with pytest.raises(ValueError, match="missing validation_result"):
        parse_safe_loco_command('{"vx": 0.2, "vy": 0.0, "vyaw": 0.0, "duration_sec": 1.0}')

    with pytest.raises(ValueError, match="not allowed by safety validation"):
        parse_safe_loco_command(
            '{"validation_result": {"allowed": false}, "vx": 0.2, "vy": 0.0, "vyaw": 0.0, "duration_sec": 1.0}'
        )


def test_parse_safe_loco_command_rejects_unsafe_values():
    with pytest.raises(ValueError, match="vx out of range"):
        parse_safe_loco_command(
            '{"validation_result": {"allowed": true}, "vx": 2.0, "vy": 0.0, "vyaw": 0.0, "duration_sec": 1.0}'
        )

    with pytest.raises(ValueError, match="duration_sec out of range"):
        parse_safe_loco_command(
            '{"validation_result": {"allowed": true}, "vx": 0.1, "vy": 0.0, "vyaw": 0.0, "duration_sec": -1.0}'
        )

    with pytest.raises(ValueError, match="non-finite"):
        parse_safe_loco_command(
            '{"validation_result": {"allowed": true}, "vx": "nan", "vy": 0.0, "vyaw": 0.0, "duration_sec": 1.0}'
        )


def test_parse_stop_command_always_builds_zero_velocity():
    command = parse_stop_command('{"validation_result": {"allowed": true}, "action": "stop"}')

    assert command.action == "set_velocity"
    assert command.params == {"velocity": [0.0, 0.0, 0.0], "duration": 0.1}


def test_parse_stop_command_requires_safety_validation():
    with pytest.raises(ValueError, match="missing validation_result"):
        parse_stop_command('{"action": "stop"}')

    with pytest.raises(ValueError, match="safe_stop action must be stop or cancel"):
        parse_stop_command('{"validation_result": {"allowed": true}, "action": "dance"}')


def test_health_status_reports_stale_state_and_pending_api():
    status = build_health_status(
        now_sec=12.0,
        last_lowstate_sec=11.6,
        state_timeout_sec=0.3,
        pending_api_count=2,
        last_api_result={"code": 0, "action": "move"},
    )

    assert status["state"] == "degraded"
    assert status["lowstate_age_ms"] == 400
    assert status["pending_api_count"] == 2
    assert status["last_api_result"] == {"code": 0, "action": "move"}


def test_sport_command_allowed_requires_fresh_lowstate():
    allowed, reason = check_sport_command_allowed(
        now_sec=10.0,
        last_lowstate_sec=None,
        state_timeout_sec=0.3,
    )
    assert allowed is False
    assert reason == "lowstate unavailable"

    allowed, reason = check_sport_command_allowed(
        now_sec=10.5,
        last_lowstate_sec=10.0,
        state_timeout_sec=0.3,
    )
    assert allowed is False
    assert reason == "lowstate stale: age_ms=500"

    allowed, reason = check_sport_command_allowed(
        now_sec=10.2,
        last_lowstate_sec=10.0,
        state_timeout_sec=0.3,
    )
    assert allowed is True
    assert reason is None


def test_build_low_state_payload_has_fixed_contract():
    summary = LowStateSummary(
        source="lowstate",
        rpy=[0.0, 0.0, 0.0],
        quaternion=[1.0, 0.0, 0.0, 0.0],
        gyroscope=[0.0, 0.0, 0.0],
        accelerometer=[0.0, 0.0, 9.8],
        motor_count=35,
        max_temperature_c=42.0,
        motors=[],
    )

    payload = build_low_state_payload(
        stamp_sec=10.0,
        source="lowstate",
        mode="sport_api_loco",
        control_owner="internal",
        mode_source="sport_api.get_fsm_mode",
        summary=summary,
        velocity={"vx": 0.1, "vy": 0.0, "vyaw": 0.2},
        sport_fsm_mode=2,
        sport_fsm_id=0,
    )

    assert payload["schema_version"] == "g1_state.v1"
    assert payload["stamp_sec"] == 10.0
    assert payload["mode"] == "sport_api_loco"
    assert payload["control_owner"] == "internal"
    assert payload["mode_source"] == "sport_api.get_fsm_mode"
    assert payload["sport_fsm_mode"] == 2
    assert payload["sport_fsm_id"] == 0
    assert payload["velocity"] == {"vx": 0.1, "vy": 0.0, "vyaw": 0.2}
    assert payload["motor_count"] == 35
    assert payload["max_temperature_c"] == 42.0


def test_build_mode_payload_has_fixed_contract():
    payload = build_mode_payload(
        stamp_sec=10.0,
        source="lf/lowstate",
        mode="sport_api_loco",
        control_owner="internal",
        mode_source="sport_api.get_fsm_mode",
        motor_count=35,
        sport_fsm_mode=2,
        sport_fsm_id=0,
    )

    assert payload == {
        "schema_version": "g1_state.v1",
        "source": "lf/lowstate",
        "stamp_sec": 10.0,
        "mode": "sport_api_loco",
        "control_owner": "internal",
        "mode_source": "sport_api.get_fsm_mode",
        "sport_fsm_mode": 2,
        "sport_fsm_id": 0,
        "motor_count": 35,
    }
