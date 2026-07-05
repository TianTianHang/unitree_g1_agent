from pathlib import Path

import pytest

from safety_control.config import SafetyControlConfig


def test_default_config_uses_expected_topics_and_limits():
    config = SafetyControlConfig.default()

    assert config.topics["input"]["loco_intent"] == "/voice/cmd/loco"
    assert config.topics["output"]["safe_loco"] == "/g1/safe_cmd/loco"
    assert config.topics["output"]["safety_state"] == "/g1/state/safety"
    assert config.safety["strict_mode"] is True
    assert config.safety["require_command_timestamp"] is True
    assert config.health_thresholds["require_battery_voltage"] is False
    assert config.health_thresholds["require_motor_temperature"] is False
    assert config.motion_limits["vx"]["max"] == 0.5
    assert config.rate_limits["loco"]["burst"] == 3


def test_yaml_overrides_defaults(tmp_path: Path):
    config_path = tmp_path / "safety_control.yaml"
    config_path.write_text(
        """
safety:
  strict_mode: true
  motion_limits:
    vx:
      max: 0.25
topics:
  output:
    decisions: /debug/safety_decisions
""",
        encoding="utf-8",
    )

    config = SafetyControlConfig.from_yaml(config_path)

    assert config.safety["strict_mode"] is True
    assert config.motion_limits["vx"]["max"] == 0.25
    assert config.motion_limits["vx"]["min"] == -0.5
    assert config.topics["output"]["decisions"] == "/debug/safety_decisions"


def test_invalid_motion_limit_is_rejected(tmp_path: Path):
    config_path = tmp_path / "safety_control.yaml"
    config_path.write_text(
        """
safety:
  motion_limits:
    vx:
      min: 1.0
      max: 0.5
""",
        encoding="utf-8",
    )

    with pytest.raises(ValueError, match="vx min must be less than max"):
        SafetyControlConfig.from_yaml(config_path)


def test_missing_topic_is_rejected(tmp_path: Path):
    config_path = tmp_path / "safety_control.yaml"
    config_path.write_text(
        """
topics:
  input:
    lowstate: ""
""",
        encoding="utf-8",
    )

    with pytest.raises(ValueError, match="missing topic config: lowstate"):
        SafetyControlConfig.from_yaml(config_path)
