import pytest

from voice_bridge_debug.config import DebugPanelConfig


def test_default_config_values():
    config = DebugPanelConfig.default()

    assert config.server["host"] == "127.0.0.1"
    assert config.server["port"] == 8765
    assert config.server["allow_remote"] is False
    assert config.topics["voice_debug_events"] == "/voice/debug/events"
    assert config.topics["safe_cmd_stop"] == "/g1/safe_cmd/stop"
    assert config.defaults["asr_confidence"] == 0.9
    assert config.timeline["max_events"] == 200


def test_remote_host_requires_allow_remote():
    raw = DebugPanelConfig.default().to_dict()
    raw["server"]["host"] = "0.0.0.0"
    raw["server"]["allow_remote"] = False

    with pytest.raises(ValueError, match="allow_remote"):
        DebugPanelConfig.from_dict(raw)


def test_remote_host_allowed_when_explicit():
    raw = DebugPanelConfig.default().to_dict()
    raw["server"]["host"] = "0.0.0.0"
    raw["server"]["allow_remote"] = True

    config = DebugPanelConfig.from_dict(raw)

    assert config.server["host"] == "0.0.0.0"
