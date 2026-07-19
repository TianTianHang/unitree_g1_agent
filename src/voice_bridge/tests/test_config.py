from pathlib import Path

import pytest

from voice_bridge.config import VoiceBridgeConfig


def test_default_config_uses_internal_topics():
    config = VoiceBridgeConfig.default()

    assert config.topics["asr"] == "/g1/audio/asr"
    assert config.topics["voice_loco"] == "/voice/cmd/loco"
    assert config.topics["voice_action"] == "/voice/cmd/action"
    assert config.agent["backend"] == "rule_based"
    assert config.motion["backend"] == "official_loco"
    assert "宇树" in config.voice["wake_words"]


def test_motion_backend_can_be_selected_statically():
    config = VoiceBridgeConfig.default().with_motion_backend("textop")

    assert config.motion["backend"] == "textop"


def test_invalid_motion_backend_is_rejected():
    with pytest.raises(ValueError, match="unsupported motion backend"):
        VoiceBridgeConfig.default().with_motion_backend("automatic")


def test_yaml_overrides_defaults(tmp_path: Path):
    config_path = tmp_path / "voice_bridge.yaml"
    config_path.write_text(
        """
voice:
  wake_words: ["小一"]
motion_defaults:
  default_vx: 0.2
agent:
  backend: disabled
topics:
  voice_state: /debug/voice_state
""",
        encoding="utf-8",
    )

    config = VoiceBridgeConfig.from_yaml(config_path)

    assert config.voice["wake_words"] == ["小一"]
    assert config.voice["stop_words"]
    assert config.motion_defaults["default_vx"] == 0.2
    assert config.agent["backend"] == "disabled"
    assert config.topics["voice_state"] == "/debug/voice_state"


def test_invalid_backend_is_rejected(tmp_path: Path):
    config_path = tmp_path / "voice_bridge.yaml"
    config_path.write_text(
        """
agent:
  backend: shell
""",
        encoding="utf-8",
    )

    with pytest.raises(ValueError, match="unsupported agent backend"):
        VoiceBridgeConfig.from_yaml(config_path)


def test_http_backend_requires_endpoint(tmp_path: Path):
    config_path = tmp_path / "voice_bridge.yaml"
    config_path.write_text(
        """
agent:
  backend: http_json
  http_endpoint: ""
""",
        encoding="utf-8",
    )

    with pytest.raises(ValueError, match="requires http_endpoint"):
        VoiceBridgeConfig.from_yaml(config_path)


def test_pi_rpc_backend_is_accepted_with_defaults(tmp_path: Path):
    config_path = tmp_path / "voice_bridge.yaml"
    config_path.write_text(
        """
agent:
  backend: pi_rpc
""",
        encoding="utf-8",
    )

    config = VoiceBridgeConfig.from_yaml(config_path)

    assert config.agent["backend"] == "pi_rpc"
    assert config.agent["pi"]["enabled"] is True
    assert config.agent["pi"]["workspace"] == ".agent-runtime/.unitree_agent"


def test_pi_rpc_rejects_blocked_env_keep(tmp_path: Path):
    config_path = tmp_path / "voice_bridge.yaml"
    config_path.write_text(
        """
agent:
  backend: pi_rpc
  pi:
    env_keep: ["HOME", "ROS_DOMAIN_ID"]
""",
        encoding="utf-8",
    )

    with pytest.raises(ValueError, match="ROS_DOMAIN_ID"):
        VoiceBridgeConfig.from_yaml(config_path)


def test_empty_topic_is_rejected(tmp_path: Path):
    config_path = tmp_path / "voice_bridge.yaml"
    config_path.write_text(
        """
topics:
  asr: ""
""",
        encoding="utf-8",
    )

    with pytest.raises(ValueError, match="missing topic config: asr"):
        VoiceBridgeConfig.from_yaml(config_path)


def test_default_config_includes_debug_events_topic():
    from voice_bridge.config import VoiceBridgeConfig

    config = VoiceBridgeConfig.default()

    assert config.topics["debug_events"] == "/voice/debug/events"


def test_config_requires_debug_events_topic():
    import pytest

    from voice_bridge.config import DEFAULT_CONFIG, VoiceBridgeConfig

    raw = {key: dict(value) for key, value in DEFAULT_CONFIG.items()}
    raw["topics"].pop("debug_events", None)

    with pytest.raises(ValueError, match="debug_events"):
        VoiceBridgeConfig._from_dict(raw)
