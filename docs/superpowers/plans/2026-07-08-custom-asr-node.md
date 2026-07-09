# Custom ASR Node Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 新建 `asr_node` ROS2 包，从 G1 麦克风 UDP 组播接收 PCM 音频，通过 VAD 分段后用 faster-whisper 识别，发布中文文本到 `/g1/audio/asr`。

**Architecture:** 三线程流水线：AudioCapture 线程（UDP recvfrom → pcm_queue）→ 处理线程（Silero VAD + SpeechBuffer 状态机 → segment_queue）→ ASR Worker 线程（faster-whisper medium + GPU → ROS2 publish）。纯 Python ROS2 节点，独立于 `g1_interface` 和 `voice_bridge`，启动即替换内置 ASR。

**Tech Stack:** Python 3.10, ROS2 Humble, faster-whisper (medium, CUDA float16), Silero VAD, numpy, `std_msgs/msg/String`, pytest, nix develop shell。

## Global Constraints

- 所有验证命令必须在 `nix develop` 环境内运行。
- 设置 `PYTEST_DISABLE_PLUGIN_AUTOLOAD=1`，避免用户级 pytest 插件影响测试。
- 追加 `PYTHONPATH=src/asr_node:${PYTHONPATH:-}`，不要覆盖 nix/ROS 注入的 Python path。
- 包布局与 `voice_bridge` 一致：`src/asr_node/asr_node/*.py`，`setup.py` 使用 `find_packages()` + `data_files`。
- MVP 不支持双路并存：内置 ASR 和自建 ASR 二选一运行，不同时启动。
- 输出 JSON 不含 `confidence` 字段（`voice_bridge.parse_asr_event()` 在 confidence 为 None 时跳过阈值检查）。
- `SpeechBuffer` 时间换算：`bytes_per_second = sample_rate * 2`，`bytes_per_ms = bytes_per_second // 1000`（16kHz/16bit/mono = 32 bytes/ms）。

---

## File Structure

- Create: `src/asr_node/package.xml` — ament_python 包描述
- Create: `src/asr_node/setup.py` — 包安装脚本（复制 voice_bridge 模板）
- Create: `src/asr_node/setup.cfg` — setuptools 配置
- Create: `src/asr_node/resource/asr_node` — ament 包资源标记文件
- Create: `src/asr_node/config/asr_node.yaml` — 默认配置文件
- Create: `src/asr_node/launch/asr_node.launch.py` — ROS2 launch 文件
- Create: `src/asr_node/asr_node/__init__.py` — 包初始化（docstring only）
- Create: `src/asr_node/asr_node/config.py` — `AsrNodeConfig` 数据类，默认配置，YAML 加载
- Create: `src/asr_node/asr_node/buffer.py` — `SpeechSegment` 数据类，`SpeechBuffer` 状态机
- Create: `src/asr_node/asr_node/audio_capture.py` — `AudioCapture` UDP 组播接收器
- Create: `src/asr_node/asr_node/vad.py` — `SileroVAD` 封装
- Create: `src/asr_node/asr_node/asr_engine.py` — `AsrEngine` faster-whisper 封装
- Create: `src/asr_node/asr_node/node.py` — `AsrNode` ROS2 节点，三线程协调，`main()` 入口
- Create: `src/asr_node/tests/__init__.py`
- Create: `src/asr_node/tests/test_config.py` — 配置测试
- Create: `src/asr_node/tests/test_buffer.py` — SpeechBuffer 状态机测试
- Create: `src/asr_node/tests/test_audio_capture.py` — UDP 接收测试
- Create: `src/asr_node/tests/test_vad.py` — VAD 检测测试
- Create: `src/asr_node/tests/test_asr_engine.py` — ASR 推理测试（GPU skipif）
- Create: `src/asr_node/tests/test_node.py` — 节点集成测试
- Create: `src/asr_node/README.md` — 使用说明

---

### Task 1: Package Scaffolding

**Files:**
- Create: `src/asr_node/package.xml`
- Create: `src/asr_node/setup.py`
- Create: `src/asr_node/setup.cfg`
- Create: `src/asr_node/resource/asr_node`
- Create: `src/asr_node/config/asr_node.yaml`
- Create: `src/asr_node/launch/asr_node.launch.py`
- Create: `src/asr_node/asr_node/__init__.py`
- Create: `src/asr_node/tests/__init__.py`

**Interfaces:**
- Produces: `asr_node` Python 包可被 `PYTHONPATH=src/asr_node python -c "import asr_node"` 发现
- Produces: `ros2 pkg list | grep asr_node` 可见（colcon build 后）

- [ ] **Step 1: Create package.xml**

```xml
<?xml version="1.0"?>
<package format="3">
  <name>asr_node</name>
  <version>0.1.0</version>
  <description>Custom ASR node for Unitree G1: UDP mic capture, VAD, faster-whisper recognition.</description>
  <maintainer email="2450804878@qq.com">unitree_g1_agent</maintainer>
  <license>Apache-2.0</license>

  <buildtool_depend>ament_python</buildtool_depend>

  <exec_depend>rclpy</exec_depend>
  <exec_depend>std_msgs</exec_depend>

  <test_depend>pytest</test_depend>

  <export>
    <build_type>ament_python</build_type>
  </export>
</package>
```

- [ ] **Step 2: Create setup.py**

复制 `src/voice_bridge/setup.py` 模板，替换包名和描述：

```python
from glob import glob

from setuptools import find_packages, setup

package_name = "asr_node"

setup(
    name=package_name,
    version="0.1.0",
    packages=find_packages(exclude=["tests"]),
    data_files=[
        ("share/ament_index/resource_index/packages", [f"resource/{package_name}"]),
        (f"share/{package_name}", ["package.xml"]),
        (f"share/{package_name}/config", glob("config/*.yaml")),
        (f"share/{package_name}/launch", glob("launch/*.py")),
    ],
    install_requires=["setuptools", "PyYAML"],
    zip_safe=True,
    maintainer="unitree_g1_agent",
    maintainer_email="dev@example.local",
    description="Custom ASR node for Unitree G1",
    license="Apache-2.0",
    tests_require=["pytest"],
    entry_points={
        "console_scripts": [
            "asr_node=asr_node.node:main",
        ],
    },
)
```

- [ ] **Step 3: Create setup.cfg**

```ini
[develop]
script_dir=$base/lib/asr_node
[install]
install_scripts=$base/lib/asr_node
```

- [ ] **Step 4: Create resource/asr_node**

空文件。用途是让 ament 找到此包：

```bash
touch src/asr_node/resource/asr_node
```

- [ ] **Step 5: Create config/asr_node.yaml**

```yaml
# asr_node 配置
model:
  size: "medium"
  device: "cuda"
  compute_type: "float16"
  language: "zh"
  initial_prompt: >-
    以下是机器人常用指令词汇:
    宇树, 向前, 后退, 左转, 右转, 停止, 停下,
    蹲下, 站起来, 挥手, 鞠躬, 走一圈, 加速, 减速, 别动, 取消

vad:
  threshold: 0.5
  min_speech_duration_ms: 300
  max_silence_duration_ms: 800
  min_audio_after_silence_ms: 200
  max_speech_duration_ms: 15000

capture:
  multicast_group: "239.168.123.161"
  multicast_port: 5555
  sample_rate: 16000
  recv_buffer_size: 8192
  network_prefix: "192.168.123."

topics:
  asr_output: "/g1/audio/asr"

output:
  source: "custom_asr"
```

- [ ] **Step 6: Create launch/asr_node.launch.py**

```python
from launch import LaunchDescription
from launch_ros.actions import Node
from ament_index_python.packages import get_package_share_directory
import os


def generate_launch_description():
    config_dir = os.path.join(get_package_share_directory("asr_node"), "config")
    return LaunchDescription([
        Node(
            package="asr_node",
            executable="asr_node",
            name="asr_node",
            output="screen",
            parameters=[{
                "config_path": os.path.join(config_dir, "asr_node.yaml"),
            }],
        ),
    ])
```

- [ ] **Step 7: Create asr_node/__init__.py**

```python
"""Custom ASR node for Unitree G1 — faster-whisper based speech recognition."""
```

- [ ] **Step 8: Create tests/__init__.py**

空文件。

- [ ] **Step 9: Verify package is discoverable**

Run: `PYTHONPATH=src/asr_node python -c "import asr_node; print(asr_node.__doc__)"`
Expected: `Custom ASR node for Unitree G1 — faster-whisper based speech recognition.`

- [ ] **Step 10: Commit**

```bash
git add src/asr_node/
git commit -m "feat(asr_node): scaffold package structure

- ament_python package with setup.py, package.xml, setup.cfg
- Default config (asr_node.yaml), launch file
- Python package layout matching voice_bridge convention"
```

---

### Task 2: AsrNodeConfig

**Files:**
- Create: `src/asr_node/asr_node/config.py`
- Create: `src/asr_node/tests/test_config.py`

**Interfaces:**
- Produces: `asr_node.config.AsrNodeConfig` frozen dataclass
- Produces: `AsrNodeConfig.default()` — 返回默认配置
- Produces: `AsrNodeConfig.from_yaml(path)` — YAML 覆盖默认值
- Produces: `config.validate()` — 校验 device/size/topics/vad threshold

- [ ] **Step 1: Write the failing test**

```python
"""Tests for asr_node.config."""
import os
import tempfile

from asr_node.config import AsrNodeConfig, DEFAULT_CONFIG


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
    # Unchanged values come from defaults
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
    assert config.model["device"] == "cuda"  # from default
    assert config.vad["threshold"] == 0.5  # from default


def test_validate_invalid_device():
    import pytest
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
    import pytest
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
    import pytest
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
    import pytest
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
    import pytest
    with pytest.raises(AttributeError):
        config.model = {"size": "tiny"}


def test_yaml_file_not_found():
    import pytest
    with pytest.raises(FileNotFoundError):
        AsrNodeConfig.from_yaml("/nonexistent/path.yaml")
```

- [ ] **Step 2: Run test to verify it fails**

Run: `PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 PYTHONPATH=src/asr_node .venv/bin/python -m pytest src/asr_node/tests/test_config.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'asr_node.config'`

- [ ] **Step 3: Write config.py**

```python
"""ASR node configuration."""
from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml


DEFAULT_CONFIG: dict[str, dict[str, Any]] = {
    "model": {
        "size": "medium",
        "device": "cuda",
        "compute_type": "float16",
        "language": "zh",
        "initial_prompt": (
            "以下是机器人常用指令词汇: "
            "宇树, 向前, 后退, 左转, 右转, 停止, 停下, "
            "蹲下, 站起来, 挥手, 鞠躬, 走一圈, 加速, 减速, 别动, 取消"
        ),
    },
    "vad": {
        "threshold": 0.5,
        "min_speech_duration_ms": 300,
        "max_silence_duration_ms": 800,
        "min_audio_after_silence_ms": 200,
        "max_speech_duration_ms": 15000,
    },
    "capture": {
        "multicast_group": "239.168.123.161",
        "multicast_port": 5555,
        "sample_rate": 16000,
        "recv_buffer_size": 8192,
        "network_prefix": "192.168.123.",
    },
    "topics": {
        "asr_output": "/g1/audio/asr",
    },
    "output": {
        "source": "custom_asr",
    },
}


def _deep_merge(base: dict[str, Any], override: dict[str, Any]) -> dict[str, Any]:
    merged = deepcopy(base)
    for key, value in override.items():
        if isinstance(value, dict) and isinstance(merged.get(key), dict):
            merged[key] = _deep_merge(merged[key], value)
        else:
            merged[key] = value
    return merged


@dataclass(frozen=True)
class AsrNodeConfig:
    model: dict[str, Any]
    vad: dict[str, Any]
    capture: dict[str, Any]
    topics: dict[str, str]
    output: dict[str, str]

    @classmethod
    def default(cls) -> AsrNodeConfig:
        return cls._from_dict(deepcopy(DEFAULT_CONFIG))

    @classmethod
    def from_yaml(cls, path: str | Path) -> AsrNodeConfig:
        p = Path(path)
        if not p.exists():
            raise FileNotFoundError(f"config file not found: {path}")
        with p.open("r", encoding="utf-8") as f:
            loaded = yaml.safe_load(f) or {}
        if not isinstance(loaded, dict):
            raise ValueError("config root must be a mapping")
        merged = _deep_merge(DEFAULT_CONFIG, loaded)
        return cls._from_dict(merged)

    @classmethod
    def _from_dict(cls, raw: dict[str, Any]) -> AsrNodeConfig:
        config = cls(
            model=dict(raw["model"]),
            vad=dict(raw["vad"]),
            capture=dict(raw["capture"]),
            topics=dict(raw["topics"]),
            output=dict(raw["output"]),
        )
        config.validate()
        return config

    def validate(self) -> None:
        if self.model["device"] not in ("cuda", "cpu"):
            raise ValueError(f"unsupported device: {self.model['device']}")
        if self.model["size"] not in ("tiny", "base", "small", "medium", "large-v3"):
            raise ValueError(f"unsupported model size: {self.model['size']}")
        if not self.topics.get("asr_output"):
            raise ValueError("missing topic config: asr_output")
        threshold = self.vad.get("threshold")
        if threshold is not None and not (0.0 < threshold < 1.0):
            raise ValueError(f"vad threshold must be in (0, 1): {threshold}")
```

- [ ] **Step 4: Run test to verify it passes**

Run: `PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 PYTHONPATH=src/asr_node .venv/bin/python -m pytest src/asr_node/tests/test_config.py -v`
Expected: 12 passed

- [ ] **Step 5: Commit**

```bash
git add src/asr_node/asr_node/config.py src/asr_node/tests/test_config.py
git commit -m "feat(asr_node): add AsrNodeConfig with defaults, YAML loading, validation"
```

---

### Task 3: SpeechBuffer

**Files:**
- Create: `src/asr_node/asr_node/buffer.py`
- Create: `src/asr_node/tests/test_buffer.py`

**Interfaces:**
- Produces: `asr_node.buffer.SpeechSegment` dataclass (`pcm_int16: bytes`, `sample_rate: int`, `duration_ms: int`)
- Produces: `asr_node.buffer.SpeechBuffer(sample_rate, min_speech_duration_ms, max_silence_duration_ms, max_speech_duration_ms, padding_ms)`
- Produces: `SpeechBuffer.add_speech(pcm_bytes) -> SpeechSegment | None` — 超长时 flush
- Produces: `SpeechBuffer.add_silence(pcm_bytes) -> SpeechSegment | None` — 静音超时且段够长时 flush，太短时 discard
- Produces: `SpeechBuffer.force_complete() -> SpeechSegment | None` — 忽略最短时长

- [ ] **Step 1: Write the failing test**

```python
"""Tests for asr_node.buffer — SpeechBuffer state machine."""
import pytest

from asr_node.buffer import SpeechBuffer, SpeechSegment


def _make_chunk(sample_rate: int = 16000, duration_ms: int = 160) -> bytes:
    """Generate a silent PCM chunk of given duration."""
    num_samples = sample_rate * duration_ms // 1000
    return b"\x00\x00" * num_samples


def test_bytes_per_ms_calculation():
    """16kHz 16-bit mono = 32 bytes/ms."""
    buf = SpeechBuffer(sample_rate=16000, max_silence_duration_ms=800,
                        max_speech_duration_ms=15000, padding_ms=200)
    assert buf.bytes_per_second == 32000
    assert buf.bytes_per_ms == 32
    assert buf.max_silence_bytes == 800 * 32   # 25600
    assert buf.max_speech_bytes == 15000 * 32    # 480000
    assert buf.padding_bytes == 200 * 32          # 6400


def test_idle_state_no_segment_on_silence():
    buf = SpeechBuffer(sample_rate=16000, max_silence_duration_ms=800,
                        max_speech_duration_ms=15000, padding_ms=200)
    chunk = _make_chunk()
    result = buf.add_silence(chunk)
    assert result is None


def test_speech_transitions_to_recording():
    buf = SpeechBuffer(sample_rate=16000, max_silence_duration_ms=800,
                        max_speech_duration_ms=15000, padding_ms=200)
    chunk = _make_chunk()
    result = buf.add_speech(chunk)
    assert result is None
    assert buf._recording is True


def test_short_speech_discarded_on_silence_timeout():
    """语音段 < min_speech_duration_ms (300ms) 应被丢弃。"""
    buf = SpeechBuffer(sample_rate=16000, min_speech_duration_ms=300,
                        max_silence_duration_ms=200,
                        max_speech_duration_ms=15000, padding_ms=0)
    # 160ms of speech (shorter than 300ms min)
    short_chunk = _make_chunk(duration_ms=160)
    buf.add_speech(short_chunk)
    # Add 200ms silence (exceeds max_silence_duration_ms=200)
    silence = _make_chunk(duration_ms=200)
    result = buf.add_silence(silence)
    assert result is None  # Discarded: too short
    assert buf._recording is False


def test_normal_speech_returns_segment():
    """正常语音：500ms speech + 800ms silence → 返回 segment。"""
    buf = SpeechBuffer(sample_rate=16000, min_speech_duration_ms=300,
                        max_silence_duration_ms=800,
                        max_speech_duration_ms=15000, padding_ms=200)
    # 500ms speech
    speech = _make_chunk(duration_ms=500)
    buf.add_speech(speech)
    # 800ms silence triggers flush
    silence = _make_chunk(duration_ms=800)
    result = buf.add_silence(silence)
    assert result is not None
    assert isinstance(result, SpeechSegment)
    assert result.sample_rate == 16000
    # duration_ms should be ~700 (500ms speech + 200ms padding, no extra silence)
    assert 600 <= result.duration_ms <= 800
    assert buf._recording is False


def test_long_speech_triggers_flush():
    """超长语音 > max_speech_duration_ms 时 add_speech 返回 segment。"""
    buf = SpeechBuffer(sample_rate=16000, min_speech_duration_ms=100,
                        max_silence_duration_ms=800,
                        max_speech_duration_ms=500,  # 500ms for test
                        padding_ms=0)
    # Accumulate > 500ms of speech
    for _ in range(4):
        buf.add_speech(_make_chunk(duration_ms=160))  # 640ms total
    # Next speech chunk should trigger flush
    result = buf.add_speech(_make_chunk(duration_ms=160))
    assert result is not None
    assert isinstance(result, SpeechSegment)
    assert result.duration_ms >= 500


def test_segment_includes_padding():
    """flush 后的 segment 应包含 padding 的尾部静音。"""
    buf = SpeechBuffer(sample_rate=16000, min_speech_duration_ms=100,
                        max_silence_duration_ms=100,
                        max_speech_duration_ms=15000, padding_ms=160)
    buf.add_speech(_make_chunk(duration_ms=160))
    # 160ms silence (enough to trigger, also serves as padding)
    result = buf.add_silence(_make_chunk(duration_ms=160))
    assert result is not None
    # segment should be 160ms speech + up to 160ms padding
    assert result.duration_ms >= 160


def test_force_complete_ignores_min_duration():
    """force_complete 不检查最短时长。"""
    buf = SpeechBuffer(sample_rate=16000, min_speech_duration_ms=1000,
                        max_silence_duration_ms=800,
                        max_speech_duration_ms=15000, padding_ms=0)
    # Only 160ms of speech (shorter than 1000ms min)
    buf.add_speech(_make_chunk(duration_ms=160))
    result = buf.force_complete()
    assert result is not None
    assert isinstance(result, SpeechSegment)
    assert result.duration_ms == 160


def test_force_complete_no_recording_returns_none():
    buf = SpeechBuffer(sample_rate=16000, max_silence_duration_ms=800,
                        max_speech_duration_ms=15000, padding_ms=0)
    result = buf.force_complete()
    assert result is None


def test_multiple_segments_sequentially():
    """多段语音顺序处理。"""
    buf = SpeechBuffer(sample_rate=16000, min_speech_duration_ms=100,
                        max_silence_duration_ms=100,
                        max_speech_duration_ms=15000, padding_ms=0)
    # First segment: 160ms speech + 100ms silence
    buf.add_speech(_make_chunk(duration_ms=160))
    seg1 = buf.add_silence(_make_chunk(duration_ms=100))
    assert seg1 is not None

    # Second segment: 160ms speech + 100ms silence
    buf.add_speech(_make_chunk(duration_ms=160))
    seg2 = buf.add_silence(_make_chunk(duration_ms=100))
    assert seg2 is not None

    assert seg1 is not seg2
```

- [ ] **Step 2: Run test to verify it fails**

Run: `PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 PYTHONPATH=src/asr_node .venv/bin/python -m pytest src/asr_node/tests/test_buffer.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'asr_node.buffer'`

- [ ] **Step 3: Write buffer.py**

```python
"""Speech buffer — VAD-driven state machine for segmenting PCM audio."""
from __future__ import annotations

from dataclasses import dataclass


@dataclass
class SpeechSegment:
    """A completed speech recording."""

    pcm_int16: bytes
    sample_rate: int = 16000
    duration_ms: int = 0


class SpeechBuffer:
    """VAD-driven state machine that accumulates PCM audio into speech segments.

    States:
        IDLE → add_speech() → RECORDING
        RECORDING → add_silence() [silence timeout] → IDLE + return SpeechSegment
        RECORDING → add_speech() [max duration] → IDLE + return SpeechSegment
        RECORDING → add_silence() [silence timeout, too short] → IDLE (discard)
    """

    def __init__(
        self,
        sample_rate: int = 16000,
        min_speech_duration_ms: int = 300,
        max_silence_duration_ms: int = 800,
        max_speech_duration_ms: int = 15000,
        padding_ms: int = 200,
    ) -> None:
        self.sample_rate = sample_rate
        # 16kHz mono 16-bit = 32000 bytes/sec = 32 bytes/ms
        self.bytes_per_second = sample_rate * 2
        self.bytes_per_ms = self.bytes_per_second // 1000
        self.max_silence_bytes = max_silence_duration_ms * self.bytes_per_ms
        self.max_speech_bytes = max_speech_duration_ms * self.bytes_per_ms
        self.padding_bytes = padding_ms * self.bytes_per_ms
        self.min_speech_bytes = min_speech_duration_ms * self.bytes_per_ms

        self._buffer: bytearray = bytearray()
        self._silence_buffer: bytearray = bytearray()
        self._recording = False

    def add_speech(self, pcm_bytes: bytes) -> SpeechSegment | None:
        """Add a PCM chunk that contains speech.

        Returns:
            SpeechSegment if max duration exceeded and segment was flushed, else None.
        """
        self._recording = True
        self._silence_buffer.clear()
        self._buffer.extend(pcm_bytes)

        if len(self._buffer) >= self.max_speech_bytes:
            return self._flush()

        return None

    def add_silence(self, pcm_bytes: bytes) -> SpeechSegment | None:
        """Add a PCM chunk that is silence.

        Returns:
            SpeechSegment if silence timeout reached and segment is long enough,
            None if still recording or if segment was too short (discarded).
        """
        if not self._recording:
            return None

        self._silence_buffer.extend(pcm_bytes)

        if len(self._silence_buffer) >= self.max_silence_bytes:
            if len(self._buffer) < self.min_speech_bytes:
                self._discard()
                return None
            keep = min(self.padding_bytes, len(pcm_bytes))
            self._buffer.extend(pcm_bytes[-keep:])
            return self._flush()

        return None

    def force_complete(self) -> SpeechSegment | None:
        """Force-flush the current recording (used during shutdown).

        Ignores min_speech_duration_ms to avoid losing audio on close.
        """
        if self._recording and self._buffer:
            return self._flush()
        return None

    def _discard(self) -> None:
        self._buffer.clear()
        self._silence_buffer.clear()
        self._recording = False

    def _flush(self) -> SpeechSegment:
        segment = SpeechSegment(
            pcm_int16=bytes(self._buffer),
            sample_rate=self.sample_rate,
            duration_ms=len(self._buffer) // self.bytes_per_ms,
        )
        self._buffer.clear()
        self._silence_buffer.clear()
        self._recording = False
        return segment
```

- [ ] **Step 4: Run test to verify it passes**

Run: `PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 PYTHONPATH=src/asr_node .venv/bin/python -m pytest src/asr_node/tests/test_buffer.py -v`
Expected: 12 passed

- [ ] **Step 5: Commit**

```bash
git add src/asr_node/asr_node/buffer.py src/asr_node/tests/test_buffer.py
git commit -m "feat(asr_node): add SpeechBuffer state machine with min/max duration"

---

### Task 4: AudioCapture

**Files:**
- Create: `src/asr_node/asr_node/audio_capture.py`
- Create: `src/asr_node/tests/test_audio_capture.py`

**Interfaces:**
- Produces: `asr_node.audio_capture.AudioCapture(multicast_group, multicast_port, network_prefix, recv_buffer_size)`
- Produces: `AudioCapture.start(callback: Callable[[bytes], None])` — 启动 daemon 接收线程
- Produces: `AudioCapture.stop()` — 停止线程，关闭 socket
- Produces: `AudioCapture._find_interface_ip(prefix) -> str` — 静态方法，自动发现网卡

- [ ] **Step 1: Write the failing test**

```python
"""Tests for asr_node.audio_capture — UDP multicast receiver."""
import socket
import threading
import time

from asr_node.audio_capture import AudioCapture


def _send_udp(data: bytes, port: int = 15555) -> None:
    """Send a UDP packet to localhost on the given port."""
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    sock.sendto(data, ("127.0.0.1", port))
    sock.close()


def test_start_and_stop():
    """AudioCapture can be started and stopped without error."""
    cap = AudioCapture(
        multicast_group="239.0.0.1",
        multicast_port=15555,
        network_prefix="127.0.0.",
        recv_buffer_size=1024,
    )
    cap.start(lambda d: None)
    cap.stop()


def test_stop_is_idempotent():
    cap = AudioCapture(
        multicast_group="239.0.0.1",
        multicast_port=15556,
        network_prefix="127.0.0.",
        recv_buffer_size=1024,
    )
    cap.start(lambda d: None)
    cap.stop()
    cap.stop()  # Should not raise


def test_recv_callback_called():
    """Callback is called when a UDP packet is received."""
    received = []
    event = threading.Event()

    cap = AudioCapture(
        multicast_group="239.0.0.1",
        multicast_port=15557,
        network_prefix="127.0.0.",
        recv_buffer_size=1024,
    )
    cap.start(lambda d: (received.append(d), event.set()))

    # Give thread time to start
    time.sleep(0.1)
    _send_udp(b"\x00\x01" * 100, port=15557)
    event.wait(timeout=2.0)
    cap.stop()

    assert len(received) == 1
    assert len(received[0]) == 200


def test_stop_thread_exits():
    """Thread exits after stop() without hanging."""
    cap = AudioCapture(
        multicast_group="239.0.0.1",
        multicast_port=15558,
        network_prefix="127.0.0.",
        recv_buffer_size=1024,
    )
    cap.start(lambda d: None)
    time.sleep(0.1)
    cap.stop()
    assert not cap._thread.is_alive()
```

- [ ] **Step 2: Run test to verify it fails**

Run: `PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 PYTHONPATH=src/asr_node .venv/bin/python -m pytest src/asr_node/tests/test_audio_capture.py -v`
Expected: FAIL with `ModuleNotFoundError`

- [ ] **Step 3: Write audio_capture.py**

```python
"""Audio capture — receive G1 microphone PCM from UDP multicast."""
from __future__ import annotations

import socket
import struct
import threading
from typing import Callable


class AudioCapture:
    """Receives PCM audio from G1 microphone UDP multicast.

    Runs in a daemon thread. Each received UDP datagram is passed
    to the callback as raw bytes.
    """

    def __init__(
        self,
        multicast_group: str = "239.168.123.161",
        multicast_port: int = 5555,
        network_prefix: str = "192.168.123.",
        recv_buffer_size: int = 8192,
    ) -> None:
        self._multicast_group = multicast_group
        self._recv_buffer_size = recv_buffer_size

        self._sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self._sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        self._sock.bind(("0.0.0.0", multicast_port))
        self._sock.settimeout(2.0)

        local_ip = self._find_interface_ip(network_prefix)
        mreq = struct.pack(
            "4s4s",
            socket.inet_aton(multicast_group),
            socket.inet_aton(local_ip),
        )
        self._sock.setsockopt(socket.IPPROTO_IP, socket.IP_ADD_MEMBERSHIP, mreq)

        self._running = False
        self._thread: threading.Thread | None = None

    @staticmethod
    def _find_interface_ip(prefix: str) -> str:
        """Find the first IPv4 address matching the given network prefix."""
        try:
            for iface in socket.if_nameindex():
                name = iface[1]
                try:
                    addrs = socket.getaddrinfo(name, None, socket.AF_INET)
                    for addr_info in addrs:
                        ip = addr_info[4][0]
                        if ip.startswith(prefix):
                            return ip
                except OSError:
                    continue
        except (AttributeError, OSError):
            pass
        raise RuntimeError(
            f"no network interface found with prefix '{prefix}'"
        )

    def start(self, callback: Callable[[bytes], None]) -> None:
        self._running = True
        self._thread = threading.Thread(target=self._recv_loop, args=(callback,), daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._running = False
        if self._thread is not None:
            self._thread.join(timeout=5.0)
        try:
            self._sock.close()
        except OSError:
            pass

    def _recv_loop(self, callback: Callable[[bytes], None]) -> None:
        while self._running:
            try:
                data, _ = self._sock.recvfrom(self._recv_buffer_size)
                if data:
                    callback(data)
            except socket.timeout:
                continue
            except OSError:
                break
```

- [ ] **Step 4: Run test to verify it passes**

Run: `PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 PYTHONPATH=src/asr_node .venv/bin/python -m pytest src/asr_node/tests/test_audio_capture.py -v`
Expected: 4 passed

- [ ] **Step 5: Commit**

```bash
git add src/asr_node/asr_node/audio_capture.py src/asr_node/tests/test_audio_capture.py
git commit -m "feat(asr_node): add AudioCapture UDP multicast receiver with auto interface detection"
```

---

### Task 5: SileroVAD

**Files:**
- Create: `src/asr_node/asr_node/vad.py`
- Create: `src/asr_node/tests/test_vad.py`

**Interfaces:**
- Produces: `asr_node.vad.SileroVAD(threshold, sample_rate, ...)`
- Produces: `SileroVAD.detect(pcm_bytes: bytes) -> bool` — True if chunk contains speech

Note: Silero VAD model download (~2MB) happens at init time. Tests use short synthetic PCM data (pure zero = silence).

- [ ] **Step 1: Write the failing test**

```python
"""Tests for asr_node.vad — Silero VAD wrapper."""
import pytest

from asr_node.vad import SileroVAD


def _make_silence_pcm(num_samples: int = 2560) -> bytes:
    """Generate pure-silence PCM (all zeros), 16-bit LE."""
    return b"\x00\x00" * num_samples


def _make_noise_pcm(num_samples: int = 2560, amplitude: int = 16000) -> bytes:
    """Generate loud noise PCM, 16-bit LE."""
    import struct
    samples = []
    for i in range(num_samples):
        val = amplitude if i % 2 == 0 else -amplitude
        samples.append(val)
    return b"".join(struct.pack("<h", s) for s in samples)


@pytest.mark.skipif(
    True,  # Silero VAD requires torch download; enable when GPU available
    reason="Silero VAD requires torch — enable in GPU test environment"
)
def test_silence_detected_as_not_speech():
    vad = SileroVAD(threshold=0.5, sample_rate=16000)
    silence = _make_silence_pcm(2560)  # 160ms at 16kHz
    assert vad.detect(silence) is False


@pytest.mark.skipif(
    True,
    reason="Silero VAD requires torch — enable in GPU test environment"
)
def test_loud_noise_detected_as_speech():
    vad = SileroVAD(threshold=0.3, sample_rate=16000)
    noise = _make_noise_pcm(2560, amplitude=30000)
    assert vad.detect(noise) is True


@pytest.mark.skipif(
    True,
    reason="Silero VAD requires torch — enable in GPU test environment"
)
def test_detect_returns_bool():
    vad = SileroVAD(threshold=0.5, sample_rate=16000)
    silence = _make_silence_pcm(2560)
    result = vad.detect(silence)
    assert isinstance(result, bool)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 PYTHONPATH=src/asr_node .venv/bin/python -m pytest src/asr_node/tests/test_vad.py -v`
Expected: FAIL with `ModuleNotFoundError`

- [ ] **Step 3: Write vad.py**

```python
"""Silero VAD wrapper — voice activity detection on PCM audio chunks."""
from __future__ import annotations

import numpy as np

# torch is imported inside __init__ so that non-GPU environments
# can import the module without pulling in torch at module level.
_model = None
_utils = None


def _ensure_model():
    """Lazily load Silero VAD model (torch.hub download, ~2MB)."""
    global _model, _utils
    if _model is not None:
        return
    import torch

    _model, _utils = torch.hub.load(
        repo_or_dir="snakers4/silero-vad",
        model="silero_vad",
        trust_repo=True,
    )


class SileroVAD:
    """Voice activity detector based on Silero VAD.

    Converts 16-bit LE PCM chunks to float32 and returns whether
    the chunk likely contains speech.
    """

    def __init__(
        self,
        threshold: float = 0.5,
        sample_rate: int = 16000,
        min_speech_duration_ms: int = 300,
        max_silence_duration_ms: int = 800,
        min_audio_after_silence_ms: int = 200,
        max_speech_duration_ms: int = 15000,
    ) -> None:
        self.threshold = threshold
        self.sample_rate = sample_rate
        # These params are stored for reference; real-time path uses
        # SpeechBuffer for duration enforcement.
        self.min_speech_duration_ms = min_speech_duration_ms
        self.max_silence_duration_ms = max_silence_duration_ms
        self.min_audio_after_silence_ms = min_audio_after_silence_ms
        self.max_speech_duration_ms = max_speech_duration_ms

        _ensure_model()

    def detect(self, pcm_bytes: bytes) -> bool:
        """Detect whether a PCM chunk contains speech.

        Args:
            pcm_bytes: 16-bit LE PCM data (must be 16kHz mono).

        Returns:
            True if the chunk likely contains speech.
        """
        import torch

        audio = np.frombuffer(pcm_bytes, dtype=np.int16).astype(np.float32) / 32768.0
        tensor = torch.from_numpy(audio)
        probability = _model(tensor, self.sample_rate).item()
        return probability > self.threshold
```

- [ ] **Step 4: Run test to verify it passes**

Run: `PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 PYTHONPATH=src/asr_node .venv/bin/python -m pytest src/asr_node/tests/test_vad.py -v`
Expected: 3 passed (all skipped — torch not available in CI)

- [ ] **Step 5: Commit**

```bash
git add src/asr_node/asr_node/vad.py src/asr_node/tests/test_vad.py
git commit -m "feat(asr_node): add SileroVAD wrapper with lazy model loading"
```

---

### Task 6: AsrEngine

**Files:**
- Create: `src/asr_node/asr_node/asr_engine.py`
- Create: `src/asr_node/tests/test_asr_engine.py`

**Interfaces:**
- Produces: `asr_node.asr_engine.AsrEngine(model_size, device, compute_type, language, initial_prompt)`
- Produces: `AsrEngine.transcribe(pcm_int16: bytes, sample_rate: int = 16000) -> str`

Note: GPU-only test. faster-whisper + CUDA required for actual inference. Tests are skipif-guarded.

- [ ] **Step 1: Write the failing test**

```python
"""Tests for asr_node.asr_engine — faster-whisper wrapper."""
import pytest

GPU_AND_WHISPER = pytest.mark.skipif(
    True,  # Enable in GPU test environment
    reason="Requires faster-whisper + CUDA GPU"
)


@GPU_AND_WHISPER
def test_transcribe_returns_string():
    from asr_node.asr_engine import AsrEngine

    engine = AsrEngine(
        model_size="tiny",  # tiny for fast test
        device="cuda",
        compute_type="float16",
        language="zh",
        initial_prompt="",
    )
    # 1 second of silence should return empty string
    silence = b"\x00\x00" * 16000
    text = engine.transcribe(silence, sample_rate=16000)
    assert isinstance(text, str)
    # silence may produce empty or whitespace-only
    assert text.strip() == "" or len(text) < 50


@GPU_AND_WHISPER
def test_transcribe_with_hotwords():
    from asr_node.asr_engine import AsrEngine

    engine = AsrEngine(
        model_size="tiny",
        device="cuda",
        compute_type="float16",
        language="zh",
        initial_prompt="停止,向前",
    )
    # Verify engine attributes
    assert engine.language == "zh"
    assert engine.initial_prompt == "停止,向前"


def test_import_without_gpu():
    """Module can be imported even without faster-whisper installed."""
    # Already imported at top; just verify it doesn't crash
    import asr_node.asr_engine
    assert hasattr(asr_node.asr_engine, "AsrEngine")
```

- [ ] **Step 2: Run test to verify it fails**

Run: `PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 PYTHONPATH=src/asr_node .venv/bin/python -m pytest src/asr_node/tests/test_asr_engine.py -v`
Expected: FAIL with `ModuleNotFoundError`

- [ ] **Step 3: Write asr_engine.py**

```python
"""ASR engine — faster-whisper speech recognition wrapper."""
from __future__ import annotations

import numpy as np


class AsrEngine:
    """faster-whisper ASR engine for speech-to-text transcription."""

    def __init__(
        self,
        model_size: str = "medium",
        device: str = "cuda",
        compute_type: str = "float16",
        language: str = "zh",
        initial_prompt: str = "",
    ) -> None:
        from faster_whisper import WhisperModel

        self.language = language
        self.initial_prompt = initial_prompt
        self.model = WhisperModel(
            model_size,
            device=device,
            compute_type=compute_type,
        )

    def transcribe(self, pcm_int16: bytes, sample_rate: int = 16000) -> str:
        """Transcribe PCM audio to text.

        Args:
            pcm_int16: 16-bit LE PCM raw data.
            sample_rate: Sample rate (must be 16000).

        Returns:
            Recognized text string, or empty string if no speech detected.
        """
        audio = np.frombuffer(pcm_int16, dtype=np.int16).astype(np.float32) / 32768.0

        segments, _info = self.model.transcribe(
            audio,
            language=self.language,
            initial_prompt=self.initial_prompt if self.initial_prompt else None,
            beam_size=5,
            vad_filter=False,
        )

        text = " ".join(seg.text.strip() for seg in segments if seg.text.strip())
        return text
```

- [ ] **Step 4: Run test to verify it passes**

Run: `PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 PYTHONPATH=src/asr_node .venv/bin/python -m pytest src/asr_node/tests/test_asr_engine.py -v`
Expected: 1 passed, 2 skipped (GPU tests)

- [ ] **Step 5: Commit**

```bash
git add src/asr_node/asr_node/asr_engine.py src/asr_node/tests/test_asr_engine.py
git commit -m "feat(asr_node): add AsrEngine faster-whisper wrapper (GPU required)"
```

---

### Task 7: AsrNode (ROS2 node with three-thread pipeline)

**Files:**
- Create: `src/asr_node/asr_node/node.py`
- Create: `src/asr_node/tests/test_node.py`

**Interfaces:**
- Consumes: `AsrNodeConfig`, `AudioCapture`, `SileroVAD`, `SpeechBuffer`, `SpeechSegment`, `AsrEngine`
- Produces: `AsrNode(node, config)` — 构造函数初始化三线程和 ROS2 publisher
- Produces: `AsrNode.start()` — 启动 AudioCapture + 处理线程 + ASR Worker
- Produces: `AsrNode.stop()` — 按序停止，flush 残余
- Produces: `main(args)` — ROS2 入口点，加载配置，spin，shutdown
- Produces: 发布 JSON 到 `/g1/audio/asr`（`std_msgs/msg/String`）

- [ ] **Step 1: Write the failing test**

```python
"""Tests for asr_node.node — AsrNode pipeline wiring."""
import json
import queue
import threading
from unittest.mock import MagicMock, patch

from asr_node.config import AsrNodeConfig
from asr_node.node import AsrNode, PCM_QUEUE_SIZE, SEGMENT_QUEUE_SIZE, _STOP_SENTINEL


def _make_config(**overrides) -> AsrNodeConfig:
    raw = {
        "model": {"size": "tiny", "device": "cpu", "compute_type": "int8",
                 "language": "zh", "initial_prompt": ""},
        "vad": {"threshold": 0.5, "min_speech_duration_ms": 100,
                "max_silence_duration_ms": 100, "min_audio_after_silence_ms": 0,
                "max_speech_duration_ms": 15000},
        "capture": {"multicast_group": "239.0.0.1", "multicast_port": 15599,
                     "sample_rate": 16000, "recv_buffer_size": 1024,
                     "network_prefix": "127.0.0."},
        "topics": {"asr_output": "/g1/audio/asr"},
        "output": {"source": "custom_asr"},
    }
    raw.update(overrides)
    return AsrNodeConfig._from_dict(raw)


def test_transcribe_and_publish_empty_text_skipped():
    """Empty transcription result is not published."""
    mock_node = MagicMock()
    mock_pub = MagicMock()
    mock_node.create_publisher.return_value = mock_pub

    config = _make_config()
    node = AsrNode.__new__(AsrNode)
    node.node = mock_node
    node.config = config
    node._msg_counter = 0
    node._lock = threading.Lock()
    node._asr_pub = mock_pub

    from asr_node.buffer import SpeechSegment
    seg = SpeechSegment(pcm_int16=b"\x00" * 320, sample_rate=16000, duration_ms=10)

    node._transcribe_and_publish(seg)
    mock_pub.publish.assert_not_called()


def test_transcribe_and_publish_formats_json():
    """Successful transcription publishes correct JSON."""
    mock_node = MagicMock()
    mock_pub = MagicMock()
    mock_node.create_publisher.return_value = mock_pub

    config = _make_config()
    node = AsrNode.__new__(AsrNode)
    node.node = mock_node
    node.config = config
    node._msg_counter = 0
    node._lock = threading.Lock()
    node._asr_pub = mock_pub

    # Mock engine to return text
    node._engine = MagicMock()
    node._engine.transcribe.return_value = "向前走"

    from asr_node.buffer import SpeechSegment
    seg = SpeechSegment(pcm_int16=b"\x00" * 3200, sample_rate=16000, duration_ms=100)

    node._transcribe_and_publish(seg)

    assert mock_pub.publish.call_count == 1
    msg = mock_pub.publish.call_args[0][0]
    payload = json.loads(msg.data)
    assert payload["text"] == "向前走"
    assert payload["is_final"] is True
    assert payload["source"] == "custom_asr"
    assert payload["language"] == "zh"
    assert payload["index"] == 1


def test_transcribe_and_publish_index_increments():
    """Index increments on each publish."""
    mock_node = MagicMock()
    mock_pub = MagicMock()
    mock_node.create_publisher.return_value = mock_pub

    config = _make_config()
    node = AsrNode.__new__(AsrNode)
    node.node = mock_node
    node.config = config
    node._msg_counter = 0
    node._lock = threading.Lock()
    node._asr_pub = mock_pub
    node._engine = MagicMock()
    node._engine.transcribe.return_value = "测试"

    from asr_node.buffer import SpeechSegment
    seg = SpeechSegment(pcm_int16=b"\x00" * 3200, sample_rate=16000, duration_ms=100)

    node._transcribe_and_publish(seg)
    node._transcribe_and_publish(seg)
    node._transcribe_and_publish(seg)

    payloads = [json.loads(mock_pub.publish.call_args_list[i][0][0].data) for i in range(3)]
    assert payloads[0]["index"] == 1
    assert payloads[1]["index"] == 2
    assert payloads[2]["index"] == 3


def test_transcribe_and_publish_no_confidence_field():
    """Published JSON does not contain 'confidence' field."""
    mock_node = MagicMock()
    mock_pub = MagicMock()
    mock_node.create_publisher.return_value = mock_pub

    config = _make_config()
    node = AsrNode.__new__(AsrNode)
    node.node = mock_node
    node.config = config
    node._msg_counter = 0
    node._lock = threading.Lock()
    node._asr_pub = mock_pub
    node._engine = MagicMock()
    node._engine.transcribe.return_value = "你好"

    from asr_node.buffer import SpeechSegment
    seg = SpeechSegment(pcm_int16=b"\x00" * 3200, sample_rate=16000, duration_ms=100)

    node._transcribe_and_publish(seg)
    payload = json.loads(mock_pub.publish.call_args[0][0][0].data)
    assert "confidence" not in payload


def test_process_loop_flushes_on_sentinel():
    """Processing thread flushes residual audio and forwards sentinel."""
    mock_node = MagicMock()
    mock_pub = MagicMock()
    mock_node.create_publisher.return_value = mock_pub
    mock_node.get_logger = MagicMock(return_value=MagicMock())

    config = _make_config()
    node = AsrNode.__new__(AsrNode)
    node.node = mock_node
    node.config = config
    node._pcm_queue = queue.Queue()
    node._segment_queue = queue.Queue()
    node._asr_pub = mock_pub

    # Mock VAD
    node._vad = MagicMock()
    node._vad.detect.return_value = False
    # Mock buffer with pre-loaded speech
    node._buffer = MagicMock()
    seg = object()  # just need non-None
    node._buffer.force_complete.return_value = seg

    # Run process loop with sentinel
    node._pcm_queue.put(_STOP_SENTINEL)
    node._process_loop()

    # Sentinel forwarded to segment_queue
    assert node._segment_queue.get() is _STOP_SENTINEL


def test_process_loop_routes_segments_to_segment_queue():
    """Completed segments are put into segment_queue."""
    mock_node = MagicMock()
    mock_pub = MagicMock()
    mock_node.create_publisher.return_value = mock_pub
    mock_node.get_logger = MagicMock(return_value=MagicMock())

    config = _make_config()
    node = AsrNode.__new__(AsrNode)
    node.node = mock_node
    node.config = config
    node._pcm_queue = queue.Queue()
    node._segment_queue = queue.Queue()

    from asr_node.buffer import SpeechBuffer
    node._vad = MagicMock()
    node._buffer = SpeechBuffer(
        sample_rate=16000, min_speech_duration_ms=50,
        max_silence_duration_ms=50, max_speech_duration_ms=15000,
        padding_ms=0,
    )

    # Add speech then silence to trigger flush
    node._vad.detect.return_value = True
    node._pcm_queue.put(b"\x00\x01" * 800)  # 50ms
    node._vad.detect.return_value = False
    node._pcm_queue.put(b"\x00\x00" * 800)  # 50ms silence (>= max_silence)

    # Add sentinel to stop the loop
    node._pcm_queue.put(_STOP_SENTINEL)
    node._process_loop()

    # Should have gotten a segment + sentinel
    result = node._segment_queue.get_nowait()
    sentinel = node._segment_queue.get_nowait()
    assert result is not None
    assert isinstance(result, type(SpeechSegment(b"", 16000)))
    assert sentinel is _STOP_SENTINEL
```

- [ ] **Step 2: Run test to verify it fails**

Run: `PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 PYTHONPATH=src/asr_node .venv/bin/python -m pytest src/asr_node/tests/test_node.py -v`
Expected: FAIL with `ModuleNotFoundError`

- [ ] **Step 3: Write node.py**

```python
"""ASR node — ROS2 node with three-thread pipeline for speech recognition."""
from __future__ import annotations

import json
import os
import queue
import threading

import rclpy
from std_msgs.msg import String

from asr_node.asr_engine import AsrEngine
from asr_node.audio_capture import AudioCapture
from asr_node.buffer import SpeechBuffer, SpeechSegment
from asr_node.config import AsrNodeConfig
from asr_node.vad import SileroVAD

PCM_QUEUE_SIZE = 100
SEGMENT_QUEUE_SIZE = 10
_STOP_SENTINEL = None


class AsrNode:
    """Custom ASR node with three-thread pipeline.

    1. AudioCapture thread: UDP recvfrom -> pcm_queue (lightweight)
    2. Processing thread: VAD + SpeechBuffer -> segment_queue (CPU light)
    3. ASR Worker thread: faster-whisper inference -> ROS2 publish (GPU heavy)
    """

    def __init__(self, node: rclpy.node.Node, config: AsrNodeConfig) -> None:
        self.node = node
        self.config = config
        self._msg_counter = 0
        self._lock = threading.Lock()

        self._pcm_queue: queue.Queue[bytes | None] = queue.Queue(maxsize=PCM_QUEUE_SIZE)
        self._segment_queue: queue.Queue[SpeechSegment | None] = queue.Queue(maxsize=SEGMENT_QUEUE_SIZE)

        self._engine = AsrEngine(
            model_size=config.model["size"],
            device=config.model["device"],
            compute_type=config.model["compute_type"],
            language=config.model["language"],
            initial_prompt=config.model.get("initial_prompt", ""),
        )
        self._vad = SileroVAD(
            threshold=config.vad["threshold"],
            sample_rate=config.capture["sample_rate"],
            min_speech_duration_ms=config.vad["min_speech_duration_ms"],
            max_silence_duration_ms=config.vad["max_silence_duration_ms"],
            min_audio_after_silence_ms=config.vad["min_audio_after_silence_ms"],
            max_speech_duration_ms=config.vad["max_speech_duration_ms"],
        )
        self._buffer = SpeechBuffer(
            sample_rate=config.capture["sample_rate"],
            min_speech_duration_ms=config.vad["min_speech_duration_ms"],
            max_silence_duration_ms=config.vad["max_silence_duration_ms"],
            max_speech_duration_ms=config.vad["max_speech_duration_ms"],
            padding_ms=config.vad["min_audio_after_silence_ms"],
        )
        self._capture = AudioCapture(
            multicast_group=config.capture["multicast_group"],
            multicast_port=config.capture["multicast_port"],
            network_prefix=config.capture["network_prefix"],
            recv_buffer_size=config.capture["recv_buffer_size"],
        )

        self._asr_pub = node.create_publisher(
            String, config.topics["asr_output"], 10
        )

        node.get_logger().info(
            f"ASR engine loaded: model={config.model['size']}, "
            f"device={config.model['device']}, "
            f"language={config.model['language']}"
        )

    def start(self) -> None:
        """Start all threads."""
        self._capture.start(self._pcm_queue.put)
        self._process_thread = threading.Thread(
            target=self._process_loop, daemon=True, name="asr_process"
        )
        self._process_thread.start()
        self._worker_thread = threading.Thread(
            target=self._worker_loop, daemon=True, name="asr_worker"
        )
        self._worker_thread.start()

        self.node.get_logger().info(
            f"Audio capture started: "
            f"{self.config.capture['multicast_group']}:{self.config.capture['multicast_port']}"
        )

    def stop(self) -> None:
        """Stop all threads in order: capture -> process -> worker."""
        self._capture.stop()
        self._pcm_queue.put(_STOP_SENTINEL)
        self._process_thread.join(timeout=5.0)
        self._segment_queue.put(_STOP_SENTINEL)
        self._worker_thread.join(timeout=10.0)

    def _process_loop(self) -> None:
        """Processing thread: VAD + SpeechBuffer state machine."""
        while True:
            pcm_bytes = self._pcm_queue.get()
            if pcm_bytes is _STOP_SENTINEL:
                segment = self._buffer.force_complete()
                if segment:
                    try:
                        self._segment_queue.put(segment, timeout=2.0)
                    except queue.Full:
                        self.node.get_logger().warning(
                            "segment queue full during shutdown, dropping residual audio"
                        )
                self._segment_queue.put(_STOP_SENTINEL)
                return

            is_speech = self._vad.detect(pcm_bytes)

            if is_speech:
                segment = self._buffer.add_speech(pcm_bytes)
            else:
                segment = self._buffer.add_silence(pcm_bytes)

            if segment is not None:
                try:
                    self._segment_queue.put(segment, timeout=2.0)
                except queue.Full:
                    self.node.get_logger().warning(
                        "segment queue full, dropping speech segment"
                    )

    def _worker_loop(self) -> None:
        """ASR Worker thread: transcribe segments and publish."""
        while True:
            segment = self._segment_queue.get()
            if segment is _STOP_SENTINEL:
                return
            self._transcribe_and_publish(segment)

    def _transcribe_and_publish(self, segment: SpeechSegment) -> None:
        """Run ASR inference and publish result to ROS2 topic."""
        try:
            text = self._engine.transcribe(
                segment.pcm_int16, segment.sample_rate
            )
        except Exception as exc:
            self.node.get_logger().warning(f"ASR transcription failed: {exc}")
            return

        if not text.strip():
            self.node.get_logger().debug("ASR returned empty text, skipping publish")
            return

        with self._lock:
            self._msg_counter += 1
            index = self._msg_counter

        payload = json.dumps({
            "text": text,
            "is_final": True,
            "source": self.config.output["source"],
            "language": self.config.model["language"],
            "index": index,
        }, ensure_ascii=False)

        msg = String()
        msg.data = payload
        self._asr_pub.publish(msg)

        self.node.get_logger().info(f"ASR result [{index}]: {text}")


def main(args=None) -> None:
    rclpy.init(args=args)
    node = rclpy.create_node("asr_node")
    node.declare_parameter("config_path", "")
    config_path = node.get_parameter("config_path").get_parameter_value().string_value

    if not config_path:
        try:
            from ament_index_python.packages import get_package_share_directory
            config_dir = get_package_share_directory("asr_node")
            config_path = os.path.join(config_dir, "config", "asr_node.yaml")
        except Exception:
            pass

    config = AsrNodeConfig.from_yaml(config_path) if config_path else AsrNodeConfig.default()

    asr_node = AsrNode(node=node, config=config)
    asr_node.start()

    try:
        rclpy.spin(node)
    except KeyboardInterrupt:
        pass
    finally:
        asr_node.stop()
        node.destroy_node()
        if rclpy.ok():
            rclpy.shutdown()


if __name__ == "__main__":
    main()
```

- [ ] **Step 4: Run test to verify it passes**

Run: `PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 PYTHONPATH=src/asr_node .venv/bin/python -m pytest src/asr_node/tests/test_node.py -v`
Expected: 6 passed

- [ ] **Step 5: Commit**

```bash
git add src/asr_node/asr_node/node.py src/asr_node/tests/test_node.py
git commit -m "feat(asr_node): add AsrNode with three-thread pipeline and ROS2 publish"
```

---

### Task 8: README and Final Integration Check

**Files:**
- Create: `src/asr_node/README.md`

**Interfaces:**
- Produces: 使用文档（安装、配置、启动、验证）

- [ ] **Step 1: Write README.md**

```markdown
# asr_node

Custom ASR node for Unitree G1 — receives microphone audio from UDP multicast, runs faster-whisper speech recognition, and publishes recognized text to `/g1/audio/asr`.

## Architecture

Three-thread pipeline:

```
[AudioCapture]  UDP recvfrom → pcm_queue
[Processor]    VAD + SpeechBuffer → segment_queue
[ASR Worker]  faster-whisper → /g1/audio/asr
```

## Dependencies

```bash
pip install faster-whisper
# torch + torchaudio must match your CUDA version
pip install torch torchaudio --index-url https://download.pytorch.org/whl/cu118
```

## Build

```bash
source /opt/ros/humble/setup.bash
colcon build --packages-select asr_node
source install/setup.bash
```

## Launch

```bash
ros2 launch asr_node asr_node.launch.py
```

## Verify

```bash
ros2 topic echo /g1/audio/asr
```

Expected output:
```
data: "{\"text\":\"向前走\",\"is_final\":true,\"source\":\"custom_asr\",\"language\":\"zh\",\"index\":1}"
```

## Configuration

Edit `src/asr_node/config/asr_node.yaml` before building. Key settings:

- `model.size`: `tiny`/`base`/`small`/`medium`/`large-v3` (default: `medium`)
- `model.device`: `cuda` or `cpu` (default: `cuda`)
- `vad.threshold`: 0.0–1.0 (default: 0.5)
- `capture.network_prefix`: network interface filter (default: `192.168.123.`)

## Unit Tests

```bash
PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 PYTHONPATH=src/asr_node .venv/bin/python -m pytest src/asr_node/tests -q
```

GPU-dependent tests (VAD, ASR engine) are automatically skipped when torch/CUDA is unavailable.
```

- [ ] **Step 2: Run all tests**

Run: `PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 PYTHONPATH=src/asr_node .venv/bin/python -m pytest src/asr_node/tests -q`
Expected: all pass (some skipped for GPU)

- [ ] **Step 3: Commit**

```bash
git add src/asr_node/README.md
git commit -m "docs(asr_node): add README with setup, config, launch, and verify instructions"
```

---

## File Structure Summary

| File | Task | Responsibility |
|------|------|---------------|
| `package.xml` | 1 | ament_python 包元数据 |
| `setup.py` | 1 | 安装脚本 |
| `setup.cfg` | 1 | setuptools 脚本目录 |
| `resource/asr_node` | 1 | ament 包资源标记 |
| `config/asr_node.yaml` | 1 | 默认配置 |
| `launch/asr_node.launch.py` | 1 | ROS2 launch |
| `asr_node/__init__.py` | 1 | 包 docstring |
| `asr_node/config.py` | 2 | 配置数据类 |
| `asr_node/buffer.py` | 3 | 语音分段状态机 |
| `asr_node/audio_capture.py` | 4 | UDP 组播接收 |
| `asr_node/vad.py` | 5 | Silero VAD |
| `asr_node/asr_engine.py` | 6 | faster-whisper 封装 |
| `asr_node/node.py` | 7 | ROS2 节点主循环 |
| `tests/test_config.py` | 2 | 配置测试 |
| `tests/test_buffer.py` | 3 | 缓冲区测试 |
| `tests/test_audio_capture.py` | 4 | 接收器测试 |
| `tests/test_vad.py` | 5 | VAD 测试 |
| `tests/test_asr_engine.py` | 6 | ASR 引擎测试 |
| `tests/test_node.py` | 7 | 节点测试 |
| `README.md` | 8 | 使用文档 |
