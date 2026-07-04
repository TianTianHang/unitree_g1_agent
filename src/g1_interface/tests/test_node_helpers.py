import pytest

from g1_interface.node import build_health_status, parse_safe_loco_command, parse_stop_command


def test_parse_safe_loco_command_clamps_to_required_fields():
    command = parse_safe_loco_command('{"vx": 0.2, "vy": -0.1, "vyaw": 0.3, "duration_sec": 1.5}')

    assert command.action == "set_velocity"
    assert command.params == {"velocity": [0.2, -0.1, 0.3], "duration": 1.5}


def test_parse_safe_loco_command_rejects_missing_velocity():
    with pytest.raises(ValueError, match="missing required loco field"):
        parse_safe_loco_command('{"vx": 0.2, "vy": 0.0}')


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
