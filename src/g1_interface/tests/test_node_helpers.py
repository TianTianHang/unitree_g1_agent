import pytest

from g1_interface.node import (
    build_low_state_payload,
    build_mode_payload,
    build_health_status,
    check_sport_command_allowed,
    diagnostic_level_for_state,
    normalize_audio_asr_message,
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


def test_normalize_audio_asr_message_forwards_plain_text():
    assert normalize_audio_asr_message("停止") == "停止"


def test_normalize_audio_asr_message_forwards_asr_json_unchanged():
    raw = '{"text":"宇树，向前走一秒","confidence":0.95,"is_final":true,"index":1}'

    assert normalize_audio_asr_message(raw) == raw


def test_normalize_audio_asr_message_filters_non_asr_audio_events():
    assert normalize_audio_asr_message("") is None
    assert normalize_audio_asr_message("   ") is None
    assert normalize_audio_asr_message('{"play_state":1}') is None
    assert normalize_audio_asr_message('{"text":null,"confidence":0.95}') is None
    assert normalize_audio_asr_message('{"text":"   ","confidence":0.95}') is None
    assert normalize_audio_asr_message("[1, 2, 3]") is None


def _healthy_status_inputs():
    return {
        "now_sec": 12.0,
        "last_lowstate_sec": 11.9,
        "state_timeout_sec": 0.3,
        "pending_api_count": 0,
        "last_api_result": {"matched": True, "code": 0},
        "last_sport_response_sec": 11.8,
        "last_successful_mode_query_sec": 11.7,
        "mode_freshness_timeout_sec": 1.5,
        "consecutive_api_timeouts": 0,
        "api_unhealthy_timeout_count": 3,
        "last_command_ack": {"sequence_id": 8, "state": "acknowledged", "updated_monotonic_sec": 11.95},
        "last_safety_heartbeat_sec": 11.6,
        "safety_heartbeat_timeout_sec": 1.2,
    }


def test_health_status_reports_sport_mode_safety_and_dds_state():
    inputs = _healthy_status_inputs()
    inputs["pending_api_count"] = 1
    inputs["consecutive_api_timeouts"] = 1
    inputs["last_command_ack"] = {
        "sequence_id": 8,
        "state": "pending",
        "code": None,
        "updated_monotonic_sec": 11.95,
    }

    status = build_health_status(**inputs)

    assert status["state"] == "degraded"
    assert status["lowstate_age_ms"] == 100
    assert status["last_sport_response_age_ms"] == 200
    assert status["last_successful_mode_query_age_ms"] == 300
    assert status["consecutive_api_timeouts"] == 1
    assert status["mode_fresh"] is True
    assert status["safety_control_age_ms"] == 400
    assert status["safety_control_fresh"] is True
    assert status["dds_connection_state"] == "degraded"
    assert status["last_command_ack"]["age_ms"] == 50
    assert "updated_monotonic_sec" not in status["last_command_ack"]


def test_health_status_marks_stale_lowstate_unhealthy_and_disconnected():
    inputs = _healthy_status_inputs()
    inputs["last_lowstate_sec"] = 11.0

    status = build_health_status(**inputs)

    assert status["state"] == "unhealthy"
    assert status["lowstate_age_ms"] == 1000
    assert status["dds_connection_state"] == "disconnected"


def test_health_status_marks_repeated_api_timeouts_unhealthy():
    inputs = _healthy_status_inputs()
    inputs["consecutive_api_timeouts"] = 3

    status = build_health_status(**inputs)

    assert status["state"] == "unhealthy"
    assert status["dds_connection_state"] == "degraded"


def test_health_status_marks_stale_mode_or_safety_heartbeat_degraded():
    mode_inputs = _healthy_status_inputs()
    mode_inputs["last_successful_mode_query_sec"] = 10.0
    safety_inputs = _healthy_status_inputs()
    safety_inputs["last_safety_heartbeat_sec"] = None

    mode_status = build_health_status(**mode_inputs)
    safety_status = build_health_status(**safety_inputs)

    assert mode_status["state"] == "degraded"
    assert mode_status["mode_fresh"] is False
    assert safety_status["state"] == "degraded"
    assert safety_status["safety_control_fresh"] is False


def test_diagnostic_level_for_state_matches_ros_message_field_type():
    from diagnostic_msgs.msg import DiagnosticStatus

    ok_status = DiagnosticStatus()
    ok_status.level = diagnostic_level_for_state("ok")

    degraded_status = DiagnosticStatus()
    degraded_status.level = diagnostic_level_for_state("degraded")

    unhealthy_status = DiagnosticStatus()
    unhealthy_status.level = diagnostic_level_for_state("unhealthy")

    assert ok_status.level == b"\x00"
    assert degraded_status.level == b"\x01"
    assert unhealthy_status.level == b"\x02"


def _command_gate_inputs():
    return {
        "now_sec": 10.2,
        "last_lowstate_sec": 10.0,
        "state_timeout_sec": 0.3,
        "last_safety_heartbeat_sec": 10.0,
        "safety_heartbeat_timeout_sec": 1.2,
        "last_successful_mode_query_sec": 10.0,
        "mode_freshness_timeout_sec": 1.5,
        "command_ack_state": "acknowledged",
        "mode": "sport_api_loco",
        "control_owner": "internal",
    }


def test_sport_command_allowed_requires_fresh_lowstate():
    inputs = _command_gate_inputs()
    inputs["last_lowstate_sec"] = None
    assert check_sport_command_allowed(**inputs) == (False, "lowstate unavailable")

    inputs = _command_gate_inputs()
    inputs["now_sec"] = 10.5
    assert check_sport_command_allowed(**inputs) == (False, "lowstate stale: age_ms=500")


def test_sport_command_allowed_requires_safety_mode_and_no_pending_command():
    inputs = _command_gate_inputs()
    inputs["last_safety_heartbeat_sec"] = None
    assert check_sport_command_allowed(**inputs) == (False, "safety_control heartbeat unavailable")

    inputs = _command_gate_inputs()
    inputs["last_successful_mode_query_sec"] = 8.0
    assert check_sport_command_allowed(**inputs) == (False, "sport mode stale: age_ms=2200")

    inputs = _command_gate_inputs()
    inputs["command_ack_state"] = "pending"
    assert check_sport_command_allowed(**inputs) == (
        False,
        "sport command acknowledgement unresolved: state=pending",
    )

    inputs = _command_gate_inputs()
    inputs["command_ack_state"] = "timed_out"
    assert check_sport_command_allowed(**inputs) == (
        False,
        "sport command acknowledgement unresolved: state=timed_out",
    )

    inputs = _command_gate_inputs()
    inputs["mode"] = "user_ctrl"
    inputs["control_owner"] = "user"
    assert check_sport_command_allowed(**inputs) == (False, "sport mode does not allow loco: mode=user_ctrl owner=user")

    assert check_sport_command_allowed(**_command_gate_inputs()) == (True, None)


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
