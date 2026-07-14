import pytest
from builtin_interfaces.msg import Time

from g1_agent_msgs.msg import ActionIntent, LocoIntent, VoiceEvent
from voice_bridge.ros_converters import action_intent, asr_event, loco_intent


def test_voice_event_to_internal_asr_event():
    msg = VoiceEvent(
        stamp=Time(sec=10),
        source="custom_asr",
        event_type=VoiceEvent.EVENT_ASR,
        text="小宇向前",
        has_confidence=True,
        confidence=0.9,
        is_final=True,
    )

    event = asr_event(msg)

    assert event.text == "小宇向前"
    assert event.confidence == pytest.approx(0.9)
    assert event.source == "custom_asr"


def test_build_typed_intents():
    loco = loco_intent("s1", "c1", "向前", 10.0, 0.2, 0.0, 0.0, 1.0)
    stop = action_intent("s1", "c2", "停止", 10.0, "stop", "emergency")

    assert isinstance(loco, LocoIntent)
    assert loco.duration.sec == 1
    assert isinstance(stop, ActionIntent)
    assert stop.action == ActionIntent.ACTION_STOP
