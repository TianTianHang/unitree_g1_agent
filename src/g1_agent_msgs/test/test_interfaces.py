from builtin_interfaces.msg import Duration, Time
from g1_agent_msgs.msg import (
    ActionIntent,
    LocoIntent,
    RobotStateSummary,
    SafetyDecision,
    SafetyStatus,
    ValidatedActionCommand,
    ValidatedLocoCommand,
    VoiceEvent,
)


def test_all_interfaces_construct_and_nest():
    voice = VoiceEvent(stamp=Time(sec=1), event_type=VoiceEvent.EVENT_ASR, text="向前")
    loco = LocoIntent(created_at=Time(sec=1), command_id="c1", duration=Duration(sec=1))
    action = ActionIntent(action=ActionIntent.ACTION_STOP, priority=ActionIntent.PRIORITY_EMERGENCY)
    state = RobotStateSummary(mode=RobotStateSummary.MODE_SPORT_API_LOCO)
    decision = SafetyDecision(
        command_id="c1",
        command_kind=SafetyDecision.KIND_LOCO,
        decision=SafetyDecision.DECISION_ALLOW,
        robot_state=state,
    )

    assert voice.text == "向前"
    assert ValidatedLocoCommand(intent=loco, validation=decision).intent.command_id == "c1"
    assert ValidatedActionCommand(intent=action, validation=decision).intent.action == "stop"
    assert SafetyStatus(last_decision=decision).last_decision.command_id == "c1"


def test_optional_numeric_fields_use_presence_flags():
    voice = VoiceEvent(has_confidence=False, confidence=0.0)
    state = RobotStateSummary(has_battery_voltage=False, battery_voltage=0.0)
    assert voice.has_confidence is False
    assert state.has_battery_voltage is False
