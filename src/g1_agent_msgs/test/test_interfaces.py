from builtin_interfaces.msg import Duration, Time

from g1_agent_msgs.action import ExecuteMotion
from g1_agent_msgs.msg import (
    ActionIntent,
    JointMotorCommand,
    LocoIntent,
    LowLevelCommandCandidate,
    LowLevelControlLease,
    MotionReferenceSegment,
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

    motors = [JointMotorCommand(q=float(index)) for index in range(29)]
    candidate = LowLevelCommandCandidate(
        backend_id="textop",
        model_id="policy.onnx",
        request_id="m1",
        lease_id="lease-1",
        sequence_id=1,
        valid_for=Duration(nanosec=60_000_000),
        robot_profile="g1_29dof_unitree_v1",
        control_profile="textop_tracker_v1",
        motors=motors,
    )
    lease = LowLevelControlLease(
        lease_id="lease-1",
        request_id="m1",
        owner="motion_manager",
        robot_profile="g1_29dof_unitree_v1",
        control_profile="textop_tracker_v1",
        ttl=Duration(sec=1),
        active=True,
    )
    assert len(candidate.motors) == 29
    assert candidate.motors[28].q == 28.0
    assert lease.active is True

    segment = MotionReferenceSegment(request_id="m1", frame_count=1, joint_position=[0.0] * 29)
    goal = ExecuteMotion.Goal(request_id="m1", backend_id="textop", prompt="wave")
    assert segment.frame_count == 1
    assert goal.prompt == "wave"


def test_optional_numeric_fields_use_presence_flags():
    voice = VoiceEvent(has_confidence=False, confidence=0.0)
    state = RobotStateSummary(has_battery_voltage=False, battery_voltage=0.0)
    assert voice.has_confidence is False
    assert state.has_battery_voltage is False
