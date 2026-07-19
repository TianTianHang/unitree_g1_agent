import math
import queue
import threading
import time
from copy import deepcopy
from pathlib import Path

from voice_bridge.config import VoiceBridgeConfig
from voice_bridge.internal_types import AgentCommand, AgentRequest, AgentResult
from voice_bridge.pi_agent import (
    PiRpcAgentClient,
    PiTransportError,
    _build_agent_result,
    _build_prompt_text,
    _extract_reply_text,
    _finalize_agent_result,
)


def make_request(safety_state: str | None = None, motion_backend: str = "official_loco") -> AgentRequest:
    return AgentRequest(
        session_id="s1",
        text="向前走然后停下",
        asr_confidence=0.9,
        robot_mode="normal",
        safety_state=safety_state,
        health_state="ok",
        motion_backend=motion_backend,
    )


def test_build_prompt_text_includes_robot_context():
    prompt = _build_prompt_text(make_request())

    assert "session_id: s1" in prompt
    assert "robot_mode: normal" in prompt
    assert "health_state: ok" in prompt
    assert "motion_backend: official_loco" in prompt
    assert "User said: 向前走然后停下" in prompt


def test_build_agent_result_keeps_confirmed_motion_order_and_led_separate():
    result = _build_agent_result(
        {
            "b": {
                "order": 1,
                "tool_name": "robot_stop",
                "kind": "action",
                "params": {"action": "stand"},
                "confirmed": True,
            },
            "a": {
                "order": 0,
                "tool_name": "robot_walk",
                "kind": "loco",
                "params": {"vx": 0.2, "vy": 0, "vyaw": 0, "duration_sec": 1},
                "confirmed": True,
            },
            "c": {
                "order": 2,
                "tool_name": "robot_led",
                "kind": "led",
                "params": {"r": 1, "g": 2, "b": 3, "ttl_sec": 1},
                "confirmed": True,
            },
            "d": {"order": 3, "tool_name": "robot_walk", "kind": "loco", "params": {"vx": 9}, "confirmed": False},
        },
        reply_text="收到",
    )

    assert result.commands == [
        AgentCommand(kind="loco", params={"vx": 0.2, "vy": 0, "vyaw": 0, "duration_sec": 1}),
        AgentCommand(kind="action", params={"action": "stop"}),
    ]
    assert result.led == {"r": 1, "g": 2, "b": 3, "ttl_sec": 1}
    assert result.reply_text == "收到"


def test_finalize_clamps_loco_rejects_nan_and_preserves_other_commands():
    config = VoiceBridgeConfig.default()
    result = AgentResult(
        commands=[
            AgentCommand(kind="loco", params={"vx": 9, "vy": -9, "vyaw": 9, "duration_sec": 99}),
            AgentCommand(kind="loco", params={"vx": math.nan, "vy": 0, "vyaw": 0, "duration_sec": 1}),
            AgentCommand(kind="action", params={"action": "resume"}),
            AgentCommand(kind="say", params={"text": "  " + "好" * 300}),
        ],
        led={"r": 300, "g": -1, "b": 10.7, "ttl_sec": 100},
    )

    finalized = _finalize_agent_result(result, make_request(), config)

    assert finalized.commands == [
        AgentCommand(kind="loco", params={"vx": 0.25, "vy": -0.15, "vyaw": 0.5, "duration_sec": 2.0}),
        AgentCommand(kind="action", params={"action": "resume"}),
        AgentCommand(kind="say", params={"text": "好" * 200}),
    ]
    assert finalized.led == {"r": 255, "g": 0, "b": 10, "ttl_sec": 30.0}


def test_finalize_drops_motion_when_safety_state_is_unsafe_but_keeps_tts_and_led():
    result = AgentResult(
        commands=[
            AgentCommand(kind="loco", params={"vx": 0.1, "vy": 0, "vyaw": 0, "duration_sec": 1}),
            AgentCommand(kind="action", params={"action": "stop"}),
            AgentCommand(kind="say", params={"text": "收到"}),
        ],
        reply_text="我会等待",
        led={"r": 1, "g": 2, "b": 3, "ttl_sec": 1},
    )

    finalized = _finalize_agent_result(result, make_request("estop"), VoiceBridgeConfig.default())

    assert finalized.commands == [
        AgentCommand(kind="action", params={"action": "stop"}),
        AgentCommand(kind="say", params={"text": "收到"}),
    ]
    assert finalized.reply_text == "我会等待"
    assert finalized.led == {"r": 1, "g": 2, "b": 3, "ttl_sec": 1.0}


def test_finalize_textop_accepts_simple_english_and_rejects_non_english_prompt():
    result = AgentResult(
        commands=[
            AgentCommand(kind="textop", params={"prompt": " turn   right ", "duration_sec": 2}),
            AgentCommand(kind="textop", params={"prompt": "向右转", "duration_sec": 2}),
        ]
    )

    finalized = _finalize_agent_result(result, make_request(motion_backend="textop"), VoiceBridgeConfig.default())

    assert finalized.commands == [
        AgentCommand(kind="textop", params={"prompt": "turn right", "duration_sec": 2.0})
    ]


def test_extract_reply_text_from_agent_end_messages():
    text = _extract_reply_text(
        [
            {
                "type": "agent_end",
                "messages": [
                    {"role": "user", "content": [{"type": "text", "text": "hi"}]},
                    {"role": "assistant", "content": [{"type": "text", "text": "收到"}, {"type": "tool_use"}]},
                ],
            }
        ]
    )

    assert text == "收到"


class FakeTransport:
    def __init__(self, events=None):
        self.events = queue.Queue()
        for event in events or []:
            self.events.put(event)
        self.sent: list[dict] = []
        self.started = False
        self.closed = False
        self.wake_reasons: list[str] = []
        self.generation = 3

    def start(self, command, cwd, env):
        self.started = True

    def current_generation(self):
        return self.generation

    def send(self, command, timeout=5.0):
        self.sent.append(command)
        if command["type"] == "get_state":
            return {"type": "response", "success": True, "data": {"sessionId": "pi-s1", "isStreaming": False}}
        if command["type"] == "new_session":
            return {"type": "response", "success": True, "data": {"cancelled": False}}
        if command["type"] == "prompt":
            return {"type": "response", "success": True}
        if command["type"] == "abort":
            return {"type": "response", "success": True}
        raise AssertionError(command)

    def get_event(self, expected_generation, timeout=5.0):
        try:
            return expected_generation, self.events.get(timeout=timeout)
        except queue.Empty:
            return None

    def wake_events(self, reason):
        self.wake_reasons.append(reason)
        self.events.put({"type": "_transport_wakeup", "reason": reason})

    def close(self):
        self.closed = True


def make_client(fake: FakeTransport, config: VoiceBridgeConfig | None = None) -> PiRpcAgentClient:
    return PiRpcAgentClient(
        config or VoiceBridgeConfig.default(),
        repo_root=Path.cwd(),
        transport_factory=lambda: fake,
    )


def config_with_pi_timeouts(**timeouts) -> VoiceBridgeConfig:
    base = VoiceBridgeConfig.default()
    agent = deepcopy(base.agent)
    pi_config = deepcopy(agent.get("pi", {}))
    pi_timeouts = deepcopy(pi_config.get("timeouts", {}))
    pi_timeouts.update(timeouts)
    pi_config["timeouts"] = pi_timeouts
    agent["pi"] = pi_config
    return VoiceBridgeConfig(
        motion=deepcopy(base.motion),
        voice=deepcopy(base.voice),
        motion_defaults=deepcopy(base.motion_defaults),
        agent=agent,
        topics=deepcopy(base.topics),
    )


def test_decide_sends_prompt_and_returns_confirmed_tools():
    fake = FakeTransport(
        [
            {
                "type": "tool_execution_start",
                "toolCallId": "w1",
                "toolName": "robot_walk",
                "args": {"vx": 0.1, "vy": 0, "vyaw": 0, "duration_sec": 1},
            },
            {
                "type": "tool_execution_end",
                "toolCallId": "w1",
                "toolName": "robot_walk",
                "result": {},
                "isError": False,
            },
            {"type": "agent_end", "messages": [{"role": "assistant", "content": [{"type": "text", "text": "收到"}]}]},
        ]
    )
    client = make_client(fake)

    result = client.decide(make_request())

    assert fake.started is True
    assert fake.sent[0]["type"] == "get_state"
    assert fake.sent[-1]["type"] == "prompt"
    assert "text" not in fake.sent[-1]
    assert "User said: 向前走然后停下" in fake.sent[-1]["message"]
    assert result.commands == [
        AgentCommand(
            kind="loco",
            params={"vx": 0.1, "vy": 0.0, "vyaw": 0.0, "duration_sec": 1.0},
        )
    ]
    assert result.reply_text == "收到"


def test_decide_returns_no_motion_when_agent_end_missing():
    fake = FakeTransport(
        [
            {
                "type": "tool_execution_start",
                "toolCallId": "w1",
                "toolName": "robot_walk",
                "args": {"vx": 0.1, "vy": 0, "vyaw": 0, "duration_sec": 1},
            },
            {
                "type": "tool_execution_end",
                "toolCallId": "w1",
                "toolName": "robot_walk",
                "result": {},
                "isError": False,
            },
        ]
    )
    client = make_client(
        fake,
        config_with_pi_timeouts(
            conversational_turn_sec=0.05,
        ),
    )

    assert client.decide(make_request()).commands == []


def test_decide_returns_empty_after_conversational_turn_timeout():
    fake = FakeTransport()
    client = make_client(
        fake,
        config_with_pi_timeouts(
            conversational_turn_sec=0.05,
        ),
    )

    started = time.monotonic()
    result = client.decide(make_request())
    elapsed = time.monotonic() - started

    assert result == AgentResult()
    assert elapsed < 0.25


def test_decide_waits_for_final_agent_end_after_auto_retry():
    fake = FakeTransport(
        [
            {
                "type": "agent_end",
                "messages": [
                    {"role": "assistant", "content": [], "stopReason": "error"}
                ],
                "willRetry": True,
            },
            {
                "type": "tool_execution_start",
                "toolCallId": "say1",
                "toolName": "robot_say",
                "args": {"text": "第二轮收到"},
            },
            {
                "type": "tool_execution_end",
                "toolCallId": "say1",
                "toolName": "robot_say",
                "result": {},
                "isError": False,
            },
            {
                "type": "agent_end",
                "messages": [
                    {
                        "role": "assistant",
                        "content": [{"type": "text", "text": "好的"}],
                    }
                ],
                "willRetry": False,
            },
        ]
    )
    client = make_client(fake)

    result = client.decide(make_request())

    assert result.commands == [AgentCommand(kind="say", params={"text": "第二轮收到"})]
    assert result.reply_text == "好的"


def test_decide_wakes_when_transport_closes_in_next_generation():
    class ClosingTransport(FakeTransport):
        def __init__(self):
            super().__init__()
            self.generation = 10
            self.events: queue.Queue[tuple[int, dict]] = queue.Queue()
            self.prompt_sent = False

        def send(self, command, timeout=5.0):
            response = super().send(command, timeout)
            if command["type"] == "prompt":
                self.prompt_sent = True
                self.events.put((self.generation + 1, {"type": "_transport_wakeup", "reason": "closed"}))
            return response

        def current_generation(self):
            if self.prompt_sent:
                return self.generation
            return super().current_generation()

        def get_event(self, expected_generation, timeout=5.0):
            deadline = time.monotonic() + timeout
            while True:
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    return None
                try:
                    generation, event = self.events.get(timeout=remaining)
                except queue.Empty:
                    return None
                if generation == expected_generation or event.get("reason") in {"closed", "closing"}:
                    return generation, event

    fake = ClosingTransport()
    client = make_client(
        fake,
        config_with_pi_timeouts(
            conversational_turn_sec=0.8,
        ),
    )

    started = time.monotonic()
    result = client.decide(make_request())
    elapsed = time.monotonic() - started

    assert result == AgentResult()
    assert elapsed < 0.2
    assert not any(command["type"] == "abort" for command in fake.sent)


def test_abort_wakes_decide_and_returns_no_motion():
    fake = FakeTransport(
        [
            {
                "type": "tool_execution_start",
                "toolCallId": "w1",
                "toolName": "robot_walk",
                "args": {"vx": 0.1, "vy": 0, "vyaw": 0, "duration_sec": 1},
            },
            {
                "type": "tool_execution_end",
                "toolCallId": "w1",
                "toolName": "robot_walk",
                "result": {},
                "isError": False,
            },
        ]
    )
    client = make_client(
        fake,
        config_with_pi_timeouts(
            conversational_turn_sec=0.5,
        ),
    )
    result_box = {}

    thread = threading.Thread(target=lambda: result_box.setdefault("result", client.decide(make_request())))
    thread.start()
    time.sleep(0.05)
    client.abort()
    thread.join(timeout=2)

    assert result_box["result"].commands == []
    assert "aborted" in fake.wake_reasons
    assert any(command["type"] == "abort" for command in fake.sent)


def test_close_delegates_to_transport():
    fake = FakeTransport([{"type": "agent_end", "messages": []}])
    client = make_client(fake)
    client.decide(make_request())

    client.close()

    assert fake.closed is True


def test_startup_failure_returns_empty_result():
    class BrokenTransport(FakeTransport):
        def start(self, command, cwd, env):
            raise PiTransportError("boom")

    client = make_client(BrokenTransport())

    assert client.decide(make_request()) == AgentResult()
