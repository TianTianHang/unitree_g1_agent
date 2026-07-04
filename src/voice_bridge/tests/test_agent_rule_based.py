from voice_bridge.agent import RuleBasedAgentClient, agent_result_from_payload
from voice_bridge.config import VoiceBridgeConfig
from voice_bridge.internal_types import AgentRequest


def _request(text: str) -> AgentRequest:
    return AgentRequest(session_id="s1", text=text, asr_confidence=0.9)


def test_rule_based_forward_command():
    config = VoiceBridgeConfig.default()
    agent = RuleBasedAgentClient(config)

    result = agent.decide(_request("向前走一秒"))

    assert result.reply_text == "收到"
    assert result.commands[0].kind == "loco"
    assert result.commands[0].params["vx"] == config.motion_defaults["default_vx"]
    assert result.commands[0].params["duration_sec"] == 1.0


def test_rule_based_stop_command():
    agent = RuleBasedAgentClient(VoiceBridgeConfig.default())

    result = agent.decide(_request("停止"))

    assert result.commands[0].kind == "action"
    assert result.commands[0].params["action"] == "stop"


def test_rule_based_unknown_text_only_replies():
    agent = RuleBasedAgentClient(VoiceBridgeConfig.default())

    result = agent.decide(_request("今天天气怎么样"))

    assert result.commands == []
    assert result.reply_text


def test_rule_based_duration_is_capped():
    config = VoiceBridgeConfig.default()
    agent = RuleBasedAgentClient(config)

    result = agent.decide(_request("向前走10秒"))

    assert result.commands[0].params["duration_sec"] == config.motion_defaults["max_motion_duration_sec"]


def test_agent_result_from_payload():
    result = agent_result_from_payload(
        {
            "commands": [{"kind": "loco", "params": {"vx": 0.1}}],
            "reply_text": "ok",
            "led": {"r": 1, "g": 2, "b": 3},
        }
    )

    assert result.commands[0].kind == "loco"
    assert result.reply_text == "ok"
    assert result.led == {"r": 1, "g": 2, "b": 3}
