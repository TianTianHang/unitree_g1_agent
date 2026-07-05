import pytest

from safety_control.config import SafetyControlConfig
from safety_control.internal_types import RobotStateSnapshot
from safety_control.validator import RateLimiter, SafetyValidator, parse_action_intent, parse_loco_intent


def healthy_state(**overrides):
    values = {
        "timestamp": 10.0,
        "mode": "sport_api_loco",
        "health_state": "ok",
        "lowstate_age_ms": 20,
        "current_velocity": {"vx": 0.0, "vy": 0.0, "vyaw": 0.0},
        "motor_count": 35,
        "max_temperature": 40.0,
        "battery_voltage": 48.0,
    }
    values.update(overrides)
    return RobotStateSnapshot(**values)


def loco_payload(**overrides):
    values = {
        "source": "voice_bridge",
        "session_id": "s1",
        "command_id": "c1",
        "text": "forward",
        "vx": 0.2,
        "vy": 0.0,
        "vyaw": 0.0,
        "duration_sec": 1.0,
        "created_at": 9.95,
    }
    values.update(overrides)
    return values


def test_parse_loco_intent_requires_numeric_fields():
    intent = parse_loco_intent(
        '{"command_id": "c1", "vx": 0.2, "vy": 0.0, "vyaw": 0.1, "duration_sec": 1.0}',
        now_sec=10.0,
    )

    assert intent.command_id == "c1"
    assert intent.vx == 0.2
    assert intent.created_at_sec is None

    with pytest.raises(ValueError, match="missing field: vyaw"):
        parse_loco_intent('{"vx": 0.2, "vy": 0.0, "duration_sec": 1.0}', now_sec=10.0)


def test_parse_action_intent_normalizes_action():
    intent = parse_action_intent('{"command_id": "c2", "action": "STOP", "priority": "emergency"}', 10.0)

    assert intent.action == "stop"
    assert intent.priority == "emergency"


def test_validator_allows_fresh_loco_in_sport_mode():
    config = SafetyControlConfig.default()
    validator = SafetyValidator(config)
    intent = parse_loco_intent_json(loco_payload())

    decision = validator.validate_loco(intent, healthy_state(), now_sec=10.0)

    assert decision.allowed is True
    assert decision.check_details["health_ok"] is True
    assert decision.check_details["mode_allowed"] is True


def test_validator_allows_missing_battery_by_default():
    config = SafetyControlConfig.default()
    validator = SafetyValidator(config)
    intent = parse_loco_intent_json(loco_payload())

    decision = validator.validate_loco(intent, healthy_state(battery_voltage=None), now_sec=10.0)

    assert decision.allowed is True
    assert decision.check_details["battery_ok"] is True


def test_validator_allows_missing_temperature_by_default():
    config = SafetyControlConfig.default()
    validator = SafetyValidator(config)
    intent = parse_loco_intent_json(loco_payload())

    decision = validator.validate_loco(intent, healthy_state(max_temperature=None), now_sec=10.0)

    assert decision.allowed is True
    assert decision.check_details["temperature_ok"] is True


def test_validator_rejects_missing_battery_when_required():
    config = SafetyControlConfig._from_dict(
        {
            **SafetyControlConfig.default().__dict__,
            "safety": {
                **SafetyControlConfig.default().safety,
                "health_thresholds": {
                    **SafetyControlConfig.default().health_thresholds,
                    "require_battery_voltage": True,
                },
            },
        }
    )
    validator = SafetyValidator(config)
    intent = parse_loco_intent_json(loco_payload())

    decision = validator.validate_loco(intent, healthy_state(battery_voltage=None), now_sec=10.0)

    assert decision.allowed is False
    assert decision.reason == "battery voltage unavailable"


def test_strict_validator_rejects_missing_timestamp():
    config = SafetyControlConfig.default()
    validator = SafetyValidator(config)
    intent = parse_loco_intent_json(loco_payload(created_at=None))

    decision = validator.validate_loco(intent, healthy_state(), now_sec=10.0)

    assert decision.allowed is False
    assert decision.reason == "command timestamp missing"


def test_strict_validator_rejects_missing_mode():
    config = SafetyControlConfig.default()
    validator = SafetyValidator(config)
    intent = parse_loco_intent_json(loco_payload())

    decision = validator.validate_loco(intent, healthy_state(mode=None), now_sec=10.0)

    assert decision.allowed is False
    assert decision.reason == "robot mode unavailable"


def test_validator_rejects_stale_lowstate():
    decision = SafetyValidator(SafetyControlConfig.default()).validate_loco(
        parse_loco_intent_json(loco_payload()),
        healthy_state(lowstate_age_ms=500),
        now_sec=10.0,
    )

    assert decision.allowed is False
    assert decision.reason == "lowstate stale: age_ms=500"


def test_validator_rejects_user_control_mode_for_loco():
    decision = SafetyValidator(SafetyControlConfig.default()).validate_loco(
        parse_loco_intent_json(loco_payload()),
        healthy_state(mode="user_ctrl"),
        now_sec=10.0,
    )

    assert decision.allowed is False
    assert decision.reason == "loco not allowed in mode: user_ctrl"


def test_validator_rejects_expired_command():
    decision = SafetyValidator(SafetyControlConfig.default()).validate_loco(
        parse_loco_intent_json(loco_payload(created_at=9.0)),
        healthy_state(),
        now_sec=10.0,
    )

    assert decision.allowed is False
    assert "command expired" in decision.reason


def test_validator_rejects_motion_limit_and_continuity_violations():
    validator = SafetyValidator(SafetyControlConfig.default())

    range_decision = validator.validate_loco(
        parse_loco_intent_json(loco_payload(vx=0.6)),
        healthy_state(),
        now_sec=10.0,
    )
    assert range_decision.allowed is False
    assert range_decision.reason == "vx out of range: 0.6"

    continuity_decision = validator.validate_loco(
        parse_loco_intent_json(loco_payload(vx=0.5)),
        healthy_state(current_velocity={"vx": -0.1, "vy": 0.0, "vyaw": 0.0}),
        now_sec=10.0,
    )
    assert continuity_decision.allowed is False
    assert "vx velocity step too large" in continuity_decision.reason


def test_stop_and_cancel_are_allowed_even_without_state():
    validator = SafetyValidator(SafetyControlConfig.default())
    stop = parse_action_intent('{"command_id": "stop1", "action": "stop"}', 10.0)
    cancel = parse_action_intent('{"command_id": "cancel1", "action": "cancel"}', 10.0)
    unhealthy = RobotStateSnapshot.unhealthy(timestamp=10.0)

    assert validator.validate_action(stop, unhealthy, now_sec=10.0).allowed is True
    assert validator.validate_action(cancel, unhealthy, now_sec=10.0).allowed is True


def test_non_stop_action_is_rejected():
    validator = SafetyValidator(SafetyControlConfig.default())
    action = parse_action_intent('{"command_id": "a1", "action": "dance"}', 10.0)

    decision = validator.validate_action(action, healthy_state(), now_sec=10.0)

    assert decision.allowed is False
    assert decision.reason == "unsupported action: dance"


def test_rate_limiter_allows_burst_then_refill():
    limiter = RateLimiter(max_per_second=2, burst=2)

    assert limiter.allow(10.0) is True
    assert limiter.allow(10.0) is True
    assert limiter.allow(10.0) is False
    assert limiter.allow(10.5) is True


def parse_loco_intent_json(payload):
    import json

    return parse_loco_intent(json.dumps(payload), now_sec=10.0)
