import pytest
from builtin_interfaces.msg import Duration, Time

from g1_agent_msgs.msg import (
    ActionIntent,
    LocoIntent,
    RobotStateSummary,
    SafetyDecision,
    ValidatedActionCommand,
    ValidatedLocoCommand,
    VoiceEvent,
)
from g1_interface.internal_types import LowStateSummary
from g1_interface.ros_converters import (
    native_audio_event,
    robot_state_summary,
    sport_command_from_action,
    sport_command_from_loco,
)


def _validated_loco():
    intent = LocoIntent(
        command_id="c1",
        vx=0.2,
        vy=0.0,
        vyaw=0.1,
        duration=Duration(sec=1),
    )
    decision = SafetyDecision(
        command_id="c1",
        command_kind=SafetyDecision.KIND_LOCO,
        decision=SafetyDecision.DECISION_ALLOW,
    )
    return ValidatedLocoCommand(
        intent=intent,
        validated_at=Time(sec=10),
        validation=decision,
    )


def _validated_stop():
    intent = ActionIntent(
        command_id="stop1",
        action=ActionIntent.ACTION_STOP,
        priority=ActionIntent.PRIORITY_EMERGENCY,
    )
    decision = SafetyDecision(
        command_id="stop1",
        command_kind=SafetyDecision.KIND_ACTION,
        decision=SafetyDecision.DECISION_ALLOW,
    )
    return ValidatedActionCommand(
        intent=intent,
        validated_at=Time(sec=10),
        validation=decision,
    )


def test_validated_loco_becomes_sport_command():
    command = sport_command_from_loco(_validated_loco())

    assert command.action == "set_velocity"
    assert command.params == {"velocity": [0.2, 0.0, 0.1], "duration": 1.0}


def test_mismatched_or_rejected_validation_is_refused():
    validated_loco = _validated_loco()
    validated_loco.validation.command_id = "different"
    with pytest.raises(ValueError, match="command_id mismatch"):
        sport_command_from_loco(validated_loco)

    validated_loco.validation.command_id = validated_loco.intent.command_id
    validated_loco.validation.decision = validated_loco.validation.DECISION_REJECT
    with pytest.raises(ValueError, match="not allowed"):
        sport_command_from_loco(validated_loco)


def test_validated_loco_rejects_unsafe_values():
    validated_loco = _validated_loco()
    validated_loco.intent.vx = 2.0
    with pytest.raises(ValueError, match="vx out of range"):
        sport_command_from_loco(validated_loco)

    validated_loco.intent.vx = 0.2
    validated_loco.intent.duration = Duration(sec=-1)
    with pytest.raises(ValueError, match="duration out of range"):
        sport_command_from_loco(validated_loco)


def test_validated_stop_always_builds_zero_velocity():
    command = sport_command_from_action(_validated_stop())

    assert command.action == "set_velocity"
    assert command.params == {"velocity": [0.0, 0.0, 0.0], "duration": 0.1}


def test_validated_stop_rejects_non_stop_action():
    validated_stop = _validated_stop()
    validated_stop.intent.action = "dance"

    with pytest.raises(ValueError, match="safe_stop action must be stop or cancel"):
        sport_command_from_action(validated_stop)


def test_native_asr_json_becomes_voice_event():
    msg = native_audio_event(
        '{"index": 7, "text": "停止", "confidence": 0.8, "is_final": true}',
        10.0,
    )

    assert isinstance(msg, VoiceEvent)
    assert msg.event_type == VoiceEvent.EVENT_ASR
    assert msg.sequence_id == 7
    assert msg.text == "停止"


def test_native_play_state_becomes_playback_event():
    msg = native_audio_event('{"play_state": 1}', 10.0)

    assert msg.event_type == VoiceEvent.EVENT_PLAYBACK
    assert msg.playback_state == VoiceEvent.PLAYBACK_PLAYING


def test_summary_preserves_official_lowstate_fields():
    lowstate_summary = LowStateSummary(
        source="lowstate",
        rpy=[0.0, 0.0, 0.0],
        quaternion=[1.0, 0.0, 0.0, 0.0],
        gyroscope=[0.0, 0.0, 0.1],
        accelerometer=[0.0, 0.0, 9.8],
        motor_count=35,
        max_temperature_c=42.0,
        motors=[],
    )

    msg = robot_state_summary(
        lowstate_summary,
        10.0,
        "lowstate",
        "sport_api_loco",
        "internal",
        "sport_api.get_fsm_mode",
        {"vx": 0.1, "vy": 0.0, "vyaw": 0.2},
        2,
        0,
    )

    assert isinstance(msg, RobotStateSummary)
    assert msg.motor_count == 35
    assert msg.orientation.w == 1.0
    assert msg.velocity.linear.x == 0.1
