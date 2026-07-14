from g1_interface.node import (
    build_health_status,
    check_sport_command_allowed,
    diagnostic_level_for_state,
)


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
