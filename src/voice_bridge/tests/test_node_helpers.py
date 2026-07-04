import pytest

from voice_bridge.internal_types import AgentCommand
from voice_bridge.node import (
    AgentRequestState,
    build_action_payload,
    build_led_payload,
    build_loco_payload,
    build_tts_payload,
)


def test_build_loco_payload():
    payload = build_loco_payload(
        AgentCommand(kind="loco", params={"vx": 0.1, "vy": 0.0, "vyaw": 0.2, "duration_sec": 1.0}),
        session_id="s1",
        command_id="c1",
        text="向前",
    )

    assert payload["source"] == "voice_bridge"
    assert payload["session_id"] == "s1"
    assert payload["vx"] == 0.1
    assert payload["duration_sec"] == 1.0


def test_build_loco_payload_rejects_missing_fields():
    with pytest.raises(ValueError, match="missing loco field"):
        build_loco_payload(AgentCommand(kind="loco", params={"vx": 0.1}), "s1", "c1", "向前")


def test_build_action_payload():
    payload = build_action_payload("stop", "s1", "c1", "停止", priority="emergency")

    assert payload["action"] == "stop"
    assert payload["priority"] == "emergency"


def test_build_tts_payload():
    payload = build_tts_payload("收到", "s1")

    assert payload["text"] == "收到"
    assert payload["speaker_id"] == 0
    assert payload["interrupt"] is True


def test_build_led_payload():
    payload = build_led_payload({"r": 1, "g": 2, "b": 3, "ttl_sec": 0.5})

    assert payload == {"source": "voice_bridge", "r": 1, "g": 2, "b": 3, "ttl_sec": 0.5}


def test_agent_request_state_invalidates_old_requests():
    state = AgentRequestState()

    first = state.start("s1")
    assert state.is_current(first, "s1") is True

    state.invalidate()

    assert state.is_current(first, "s1") is False


def test_agent_request_state_only_accepts_latest_session():
    state = AgentRequestState()

    first = state.start("s1")
    second = state.start("s2")

    assert state.is_current(first, "s1") is False
    assert state.is_current(second, "s2") is True
