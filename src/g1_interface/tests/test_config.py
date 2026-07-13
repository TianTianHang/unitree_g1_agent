from pathlib import Path

import pytest

from g1_interface.config import G1InterfaceConfig


def test_default_config_uses_unitree_ros2_topic_names():
    config = G1InterfaceConfig.default()

    assert config.native_topics["low_state"] == "lowstate"
    assert config.native_topics["sport_request"] == "/api/sport/request"
    assert config.native_topics["sport_response"] == "/api/sport/response"
    assert config.native_topics["audio_msg"] == "/audio_msg"
    assert config.project_topics["asr"] == "/g1/audio/asr"
    assert config.project_topics["audio_event"] == "/g1/audio/event"
    assert config.control["allow_low_level"] is False
    assert config.control["default_mode"] == "sport_api_loco"
    assert config.timeouts["mode_query_period_ms"] == 500


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
    assert config.project_topics["asr"] == "/g1/audio/asr"
    assert config.project_topics["audio_event"] == "/g1/audio/event"
    assert config.control["allow_dex3"] is True
    assert config.timeouts["state_timeout_ms"] == 250


def test_project_asr_topic_can_be_overridden(tmp_path: Path):
    config_path = tmp_path / "g1_interface.yaml"
    config_path.write_text(
        """
native_topics:
  audio_msg: /robot/audio_msg
project_topics:
  asr: /robot/g1/audio/asr
  audio_event: /robot/g1/audio/event
""",
        encoding="utf-8",
    )

    config = G1InterfaceConfig.from_yaml(config_path)

    assert config.native_topics["audio_msg"] == "/robot/audio_msg"
    assert config.project_topics["asr"] == "/robot/g1/audio/asr"
    assert config.project_topics["audio_event"] == "/robot/g1/audio/event"


def test_audio_bridge_topics_are_required(tmp_path: Path):
    config_path = tmp_path / "g1_interface.yaml"
    config_path.write_text(
        """
native_topics:
  audio_msg: ""
project_topics:
  asr: ""
  audio_event: ""
""",
        encoding="utf-8",
    )

    with pytest.raises(
        ValueError,
        match="missing topic config: native_topics.audio_msg, project_topics.asr, project_topics.audio_event",
    ):
        G1InterfaceConfig.from_yaml(config_path)


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


def test_runtime_required_topics_are_rejected_when_empty(tmp_path: Path):
    config_path = tmp_path / "g1_interface.yaml"
    config_path.write_text(
        """
native_topics:
  low_state_low_freq: ""
  secondary_imu: ""
""",
        encoding="utf-8",
    )

    with pytest.raises(
        ValueError,
        match="missing topic config: native_topics.low_state_low_freq, native_topics.secondary_imu",
    ):
        G1InterfaceConfig.from_yaml(config_path)


def test_set_velocity_api_id_is_required(tmp_path: Path):
    config_path = tmp_path / "g1_interface.yaml"
    config_path.write_text(
        """
sport_api:
  api_ids:
    set_velocity:
""",
        encoding="utf-8",
    )

    with pytest.raises(ValueError, match="missing sport API id config: set_velocity"):
        G1InterfaceConfig.from_yaml(config_path)


def test_get_fsm_mode_api_id_is_required(tmp_path: Path):
    config_path = tmp_path / "g1_interface.yaml"
    config_path.write_text(
        """
sport_api:
  api_ids:
    get_fsm_mode:
""",
        encoding="utf-8",
    )

    with pytest.raises(ValueError, match="missing sport API id config: get_fsm_mode"):
        G1InterfaceConfig.from_yaml(config_path)


def test_runtime_timeouts_are_required(tmp_path: Path):
    config_path = tmp_path / "g1_interface.yaml"
    config_path.write_text(
        """
timeouts:
  state_timeout_ms:
  api_response_timeout_ms:
""",
        encoding="utf-8",
    )

    with pytest.raises(ValueError, match="missing timeout config: state_timeout_ms, api_response_timeout_ms"):
        G1InterfaceConfig.from_yaml(config_path)


def test_default_asr_source_mode_is_builtin():
    config = G1InterfaceConfig.default()

    assert config.asr["source_mode"] == "builtin"


def test_asr_source_mode_loaded_from_yaml(tmp_path):
    path = tmp_path / "g1_interface.yaml"
    path.write_text(
        """
asr:
  source_mode: custom
""",
        encoding="utf-8",
    )

    config = G1InterfaceConfig.from_yaml(path)

    assert config.asr["source_mode"] == "custom"


def test_invalid_asr_source_mode_rejected(tmp_path):
    path = tmp_path / "g1_interface.yaml"
    path.write_text(
        """
asr:
  source_mode: invalid
""",
        encoding="utf-8",
    )

    with pytest.raises(ValueError, match="unsupported asr source_mode"):
        G1InterfaceConfig.from_yaml(path)


def test_with_asr_source_mode_returns_overridden_config():
    config = G1InterfaceConfig.default().with_asr_source_mode("custom")

    assert config.asr["source_mode"] == "custom"


def test_default_watchdog_and_health_config():
    config = G1InterfaceConfig.default()

    assert config.project_topics["safety_state"] == "/g1/state/safety"
    assert config.timeouts["motion_watchdog_period_ms"] == 50
    assert config.timeouts["safety_heartbeat_timeout_ms"] == 1200
    assert config.timeouts["mode_freshness_timeout_ms"] == 1500
    assert config.timeouts["api_unhealthy_timeout_count"] == 3


def test_watchdog_timeouts_must_be_positive(tmp_path: Path):
    config_path = tmp_path / "g1_interface.yaml"
    config_path.write_text(
        """
timeouts:
  motion_watchdog_period_ms: 0
""",
        encoding="utf-8",
    )

    with pytest.raises(ValueError, match="motion_watchdog_period_ms must be positive"):
        G1InterfaceConfig.from_yaml(config_path)


def test_api_unhealthy_timeout_count_must_be_integer(tmp_path: Path):
    config_path = tmp_path / "g1_interface.yaml"
    config_path.write_text(
        """
timeouts:
  api_unhealthy_timeout_count: 2.5
""",
        encoding="utf-8",
    )

    with pytest.raises(ValueError, match="api_unhealthy_timeout_count must be a positive integer"):
        G1InterfaceConfig.from_yaml(config_path)
