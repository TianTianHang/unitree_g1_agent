from pathlib import Path

import pytest

from g1_interface.config import G1InterfaceConfig


def test_default_config_uses_unitree_ros2_topic_names():
    config = G1InterfaceConfig.default()

    assert config.native_topics["low_state"] == "lowstate"
    assert config.native_topics["sport_request"] == "/api/sport/request"
    assert config.native_topics["sport_response"] == "/api/sport/response"
    assert config.control["allow_low_level"] is False
    assert config.control["default_mode"] == "sport_api_loco"


def test_yaml_overrides_defaults(tmp_path: Path):
    config_path = tmp_path / "g1_interface.yaml"
    config_path.write_text(
        """
robot:
  model: g1
  dof_profile: 29dof
native_topics:
  low_state: /robot/lowstate
control:
  allow_dex3: true
timeouts:
  state_timeout_ms: 250
""",
        encoding="utf-8",
    )

    config = G1InterfaceConfig.from_yaml(config_path)

    assert config.robot["dof_profile"] == "29dof"
    assert config.native_topics["low_state"] == "/robot/lowstate"
    assert config.native_topics["sport_request"] == "/api/sport/request"
    assert config.control["allow_dex3"] is True
    assert config.timeouts["state_timeout_ms"] == 250


def test_invalid_low_level_enabled_without_manual_confirm_is_rejected(tmp_path: Path):
    config_path = tmp_path / "g1_interface.yaml"
    config_path.write_text(
        """
control:
  allow_low_level: true
  require_manual_confirm_for_mode_switch: false
""",
        encoding="utf-8",
    )

    with pytest.raises(ValueError, match="low level control requires manual confirmation"):
        G1InterfaceConfig.from_yaml(config_path)
