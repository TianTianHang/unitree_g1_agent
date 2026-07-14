"""Tests for asr_node.config."""
import os
import tempfile

import pytest

from asr_node.config import DEFAULT_CONFIG, AsrNodeConfig


def test_default_config_has_required_sections():
    config = AsrNodeConfig.default()
    assert "size" in config.model
    assert "device" in config.model
    assert "language" in config.model
    assert "threshold" in config.vad
    assert "multicast_group" in config.capture
    assert "asr_output" in config.topics
    assert "source" in config.output


def test_default_model_values():
    config = AsrNodeConfig.default()
    assert config.model["size"] == "medium"
    assert config.model["device"] == "cuda"
    assert config.model["compute_type"] == "float16"
    assert config.model["language"] == "zh"


def test_default_capture_values():
    config = AsrNodeConfig.default()
    assert config.capture["multicast_group"] == "239.168.123.161"
    assert config.capture["multicast_port"] == 5555
    assert config.capture["sample_rate"] == 16000
    assert config.capture["network_prefix"] == "192.168.123."


def test_default_vad_values():
    config = AsrNodeConfig.default()
    assert config.vad["threshold"] == 0.5
    assert config.vad["max_silence_duration_ms"] == 800
    assert config.vad["min_speech_duration_ms"] == 300
    assert config.vad["max_speech_duration_ms"] == 15000


def test_default_topics():
    config = AsrNodeConfig.default()
    assert config.topics["asr_output"] == "/g1/audio/asr"
    assert config.output["source"] == "custom_asr"


def test_yaml_override():
    yaml_content = """
model:
  size: "small"
  device: "cpu"
vad:
  threshold: 0.7
capture:
  multicast_port: 6666
topics:
  asr_output: "/custom/asr"
"""
    with tempfile.NamedTemporaryFile(mode="w", suffix=".yaml", delete=False) as f:
        f.write(yaml_content)
        f.flush()
        config = AsrNodeConfig.from_yaml(f.name)
        os.unlink(f.name)

    assert config.model["size"] == "small"
    assert config.model["device"] == "cpu"
    assert config.vad["threshold"] == 0.7
    assert config.capture["multicast_port"] == 6666
    assert config.topics["asr_output"] == "/custom/asr"
    assert config.model["language"] == "zh"
    assert config.output["source"] == "custom_asr"


def test_yaml_partial_override_preserves_defaults():
    yaml_content = 'model:\n  size: "tiny"\n'
    with tempfile.NamedTemporaryFile(mode="w", suffix=".yaml", delete=False) as f:
        f.write(yaml_content)
        f.flush()
        config = AsrNodeConfig.from_yaml(f.name)
        os.unlink(f.name)

    assert config.model["size"] == "tiny"
    assert config.model["device"] == "cuda"
    assert config.vad["threshold"] == 0.5


def test_validate_invalid_device():
    config = AsrNodeConfig.default()
    raw = {
        "model": {**config.model, "device": "tpu"},
        "vad": dict(config.vad),
        "capture": dict(config.capture),
        "topics": dict(config.topics),
        "output": dict(config.output),
    }
    with pytest.raises(ValueError, match="unsupported device"):
        AsrNodeConfig._from_dict(raw)


def test_validate_invalid_model_size():
    config = AsrNodeConfig.default()
    raw = {
        "model": {**config.model, "size": "huge"},
        "vad": dict(config.vad),
        "capture": dict(config.capture),
        "topics": dict(config.topics),
        "output": dict(config.output),
    }
    with pytest.raises(ValueError, match="unsupported model size"):
        AsrNodeConfig._from_dict(raw)


def test_validate_vad_threshold_out_of_range():
    config = AsrNodeConfig.default()
    raw = {
        "model": dict(config.model),
        "vad": {**config.vad, "threshold": 1.5},
        "capture": dict(config.capture),
        "topics": dict(config.topics),
        "output": dict(config.output),
    }
    with pytest.raises(ValueError, match="vad threshold"):
        AsrNodeConfig._from_dict(raw)


def test_validate_missing_topic():
    raw = {
        "model": dict(DEFAULT_CONFIG["model"]),
        "vad": dict(DEFAULT_CONFIG["vad"]),
        "capture": dict(DEFAULT_CONFIG["capture"]),
        "topics": {},
        "output": dict(DEFAULT_CONFIG["output"]),
    }
    with pytest.raises(ValueError, match="missing topic"):
        AsrNodeConfig._from_dict(raw)


def test_frozen_dataclass():
    config = AsrNodeConfig.default()
    with pytest.raises(AttributeError):
        config.model = {"size": "tiny"}


def test_yaml_file_not_found():
    with pytest.raises(FileNotFoundError):
        AsrNodeConfig.from_yaml("/nonexistent/path.yaml")
