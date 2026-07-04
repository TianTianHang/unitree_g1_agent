import pytest

from g1_interface.node import (
    build_health_status,
    check_sport_command_allowed,
    parse_safe_loco_command,
    parse_stop_command,
)


def test_parse_safe_loco_command_clamps_to_required_fields():
    command = parse_safe_loco_command('{"vx": 0.2, "vy": -0.1, "vyaw": 0.3, "duration_sec": 1.5}')

    assert command.action == "set_velocity"
    assert command.params == {"velocity": [0.2, -0.1, 0.3], "duration": 1.5}


def test_parse_safe_loco_command_rejects_missing_velocity():
    with pytest.raises(ValueError, match="missing required loco field"):
        parse_safe_loco_command('{"vx": 0.2, "vy": 0.0}')


def test_parse_safe_loco_command_rejects_unsafe_values():
    with pytest.raises(ValueError, match="vx out of range"):
        parse_safe_loco_command('{"vx": 2.0, "vy": 0.0, "vyaw": 0.0, "duration_sec": 1.0}')

    with pytest.raises(ValueError, match="duration_sec out of range"):
        parse_safe_loco_command('{"vx": 0.1, "vy": 0.0, "vyaw": 0.0, "duration_sec": -1.0}')

    with pytest.raises(ValueError, match="non-finite"):
        parse_safe_loco_command('{"vx": "nan", "vy": 0.0, "vyaw": 0.0, "duration_sec": 1.0}')


def test_parse_stop_command_always_builds_zero_velocity():
    command = parse_stop_command("{}")

    assert command.action == "set_velocity"
    assert command.params == {"velocity": [0.0, 0.0, 0.0], "duration": 0.1}


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
