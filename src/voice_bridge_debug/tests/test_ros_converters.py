from builtin_interfaces.msg import Duration, Time

from g1_agent_msgs.msg import (
    LocoIntent,
    RobotStateSummary,
    SafetyDecision,
    SafetyStatus,
    ValidatedLocoCommand,
    VoiceEvent,
)
from voice_bridge_debug.ros_converters import (
    safety_status_to_dict,
    validated_loco_to_dict,
    voice_event_to_dict,
)


def test_safety_status_to_dict_preserves_nested_decision():
    msg = SafetyStatus(
        node_name="safety_control",
        enabled=True,
        strict_mode=True,
    )
    msg.robot_state.mode = RobotStateSummary.MODE_SPORT_API_LOCO
    msg.has_last_decision = True
    msg.last_decision.command_id = "c1"

    data = safety_status_to_dict(msg)

    assert data["enabled"] is True
    assert data["robot_state"]["mode"] == "sport_api_loco"
    assert data["last_decision"]["command_id"] == "c1"


def test_validated_loco_to_dict_is_json_safe():
    intent = LocoIntent(
        created_at=Time(sec=9),
        command_id="c1",
        vx=0.2,
        duration=Duration(sec=1),
    )
    decision = SafetyDecision(
        stamp=Time(sec=10),
        command_id="c1",
        command_kind=SafetyDecision.KIND_LOCO,
        decision=SafetyDecision.DECISION_ALLOW,
    )
    msg = ValidatedLocoCommand(
        intent=intent,
        validated_at=Time(sec=10),
        validation=decision,
    )

    data = validated_loco_to_dict(msg)

    assert data["intent"]["duration_sec"] == 1.0
    assert data["validation"]["decision"] == "allow"


def test_voice_event_to_dict_preserves_optional_fields():
    msg = VoiceEvent(
        stamp=Time(sec=10),
        source="debug",
        event_type=VoiceEvent.EVENT_ASR,
        text="停止",
        has_confidence=True,
        confidence=0.9,
        is_final=True,
    )

    data = voice_event_to_dict(msg)

    assert data["text"] == "停止"
    assert data["confidence"] == msg.confidence
    assert data["playback_state"] is None
