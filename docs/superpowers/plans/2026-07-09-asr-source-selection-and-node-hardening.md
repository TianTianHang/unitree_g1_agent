# ASR Source Selection And Node Hardening Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make ASR source selection explicit, prevent built-in/custom ASR duplicate command triggers, and harden the custom ASR node runtime path.

**Architecture:** `g1_interface` owns native `/audio_msg` bridging and should decide whether built-in ASR text is forwarded to the canonical `/g1/audio/asr` topic. `asr_node` remains an optional custom ASR publisher to `/g1/audio/asr`, but its VAD/buffer/shutdown paths should tolerate runtime errors and preserve configured audio padding. Tests must run through `nix develop` so ROS message packages are loaded when available, while unit tests still provide stubs for non-ROS local runs.

**Tech Stack:** ROS 2 Humble, `rclpy`, `std_msgs/msg/String`, Unitree ROS messages, Python 3.10, pytest, Nix dev shell, faster-whisper, torch/Silero VAD.

## Global Constraints

- Keep `/g1/audio/asr` as the canonical topic consumed by `voice_bridge`.
- Preserve built-in ASR default behavior unless explicitly configured otherwise.
- Do not add source filtering in `voice_bridge`; keep source selection in bridge/config layer.
- Use `nix develop --command bash -lc '...'` for ROS-aware verification.
- Keep custom ASR output JSON compatible with current `voice_bridge.parse_asr_event()`: `text`, `is_final`, `source`, `language`, `index`; no required `confidence`.

---

## File Structure

- `src/g1_interface/g1_interface/config.py`: add `asr.source_mode` config with validation and override helper.
- `src/g1_interface/g1_interface/node.py`: gate native `/audio_msg` ASR forwarding based on `asr.source_mode`; add ROS parameter override in `main()`.
- `src/g1_interface/config/g1_interface.yaml`: document default `asr.source_mode: builtin`.
- `src/g1_interface/launch/g1_interface.launch.py`: expose `asr_source_mode` launch argument.
- `src/g1_interface/tests/conftest.py`: provide complete ROS message stubs for unit tests without native ROS Python packages.
- `src/g1_interface/tests/test_config.py`: cover default, override, and invalid source modes.
- `src/g1_interface/tests/test_asr_bridge_node.py`: cover `builtin`, `custom`, and `both` forwarding behavior.
- `src/asr_node/asr_node/buffer.py`: use accumulated silence buffer for configured trailing padding.
- `src/asr_node/asr_node/vad.py`: evaluate Silero VAD using fixed windows and aggregate probabilities.
- `src/asr_node/asr_node/node.py`: prevent process-thread death from VAD exceptions and avoid indefinite shutdown blocking.
- `src/asr_node/tests/test_buffer.py`: add regression for multi-chunk trailing padding.
- `src/asr_node/tests/test_vad.py`: add unit test using fake model to prove chunk windowing.
- `src/asr_node/tests/test_node.py`: add process-loop and shutdown hardening tests.
- `src/asr_node/setup.py`: declare Python runtime dependencies used by `asr_engine.py` and `vad.py`.
- `src/asr_node/package.xml`: document runtime dependency expectation.
- `docs/data_contracts.md`: document ASR source mode and duplicate-source behavior.

---

### Task 1: Stabilize ROS Message Test Environment

**Files:**
- Create: `src/g1_interface/tests/conftest.py`
- Modify: `src/g1_interface/tests/test_asr_bridge_node.py`
- Test: `src/g1_interface/tests/test_asr_bridge_node.py`

**Interfaces:**
- Consumes: imports performed by `g1_interface.node._load_ros_messages()`
- Produces: pytest stubs for `diagnostic_msgs.msg`, `sensor_msgs.msg`, `std_msgs.msg`, `unitree_api.msg`, and `unitree_hg.msg`

- [ ] **Step 1: Add failing reproduction command**

Run:

```bash
nix develop --command bash -lc 'source /opt/ros/humble/setup.bash 2>/dev/null || true; source install/setup.bash 2>/dev/null || true; PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 PYTHONPATH=src/g1_interface python3 -m pytest src/g1_interface/tests/test_asr_bridge_node.py -q'
```

Expected before fix in non-ROS Python environments: FAIL with `ModuleNotFoundError: No module named 'diagnostic_msgs'` or equivalent missing message module.

- [ ] **Step 2: Create test stubs**

Create `src/g1_interface/tests/conftest.py`:

```python
from __future__ import annotations

import sys
import types


class String:
    def __init__(self):
        self.data = ""


class DiagnosticArray:
    def __init__(self):
        self.status = []


class DiagnosticStatus:
    def __init__(self):
        self.name = ""
        self.level = b"\x00"
        self.message = ""
        self.values = []


class KeyValue:
    def __init__(self):
        self.key = ""
        self.value = ""


class Imu:
    def __init__(self):
        self.header = types.SimpleNamespace(frame_id="")
        self.orientation = types.SimpleNamespace(x=0.0, y=0.0, z=0.0, w=1.0)
        self.angular_velocity = types.SimpleNamespace(x=0.0, y=0.0, z=0.0)
        self.linear_acceleration = types.SimpleNamespace(x=0.0, y=0.0, z=0.0)


class Request:
    def __init__(self):
        self.header = types.SimpleNamespace(identity=types.SimpleNamespace(id=0, api_id=0))
        self.parameter = ""


class Response:
    def __init__(self):
        self.header = types.SimpleNamespace(identity=types.SimpleNamespace(id=0, api_id=0))
        self.status = types.SimpleNamespace(code=0)
        self.data = ""


class IMUState:
    pass


class LowState:
    pass


def _install_module(name: str, attributes: dict[str, object]) -> None:
    package_name, _, child_name = name.partition(".")
    package = sys.modules.get(package_name)
    if package is None:
        package = types.ModuleType(package_name)
        sys.modules[package_name] = package
    module = types.ModuleType(name)
    for key, value in attributes.items():
        setattr(module, key, value)
    setattr(package, child_name, module)
    sys.modules[name] = module


def pytest_configure():
    _install_module(
        "diagnostic_msgs.msg",
        {
            "DiagnosticArray": DiagnosticArray,
            "DiagnosticStatus": DiagnosticStatus,
            "KeyValue": KeyValue,
        },
    )
    _install_module("sensor_msgs.msg", {"Imu": Imu})
    _install_module("std_msgs.msg", {"String": String})
    _install_module("unitree_api.msg", {"Request": Request, "Response": Response})
    _install_module("unitree_hg.msg", {"IMUState": IMUState, "LowState": LowState})
```

- [ ] **Step 3: Remove local String helper if redundant**

In `src/g1_interface/tests/test_asr_bridge_node.py`, keep `_string_msg()` as-is if it imports `std_msgs.msg.String`; it will now use the stub from `conftest.py`.

- [ ] **Step 4: Verify g1_interface ASR bridge tests pass**

Run:

```bash
nix develop --command bash -lc 'source /opt/ros/humble/setup.bash 2>/dev/null || true; source install/setup.bash 2>/dev/null || true; PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 PYTHONPATH=src/g1_interface python3 -m pytest src/g1_interface/tests/test_asr_bridge_node.py -q'
```

Expected: `4 passed`.

- [ ] **Step 5: Commit**

```bash
git add src/g1_interface/tests/conftest.py src/g1_interface/tests/test_asr_bridge_node.py
git commit -m "test: stabilize g1 interface ros message stubs"
```

---

### Task 2: Add Explicit ASR Source Mode In g1_interface

**Files:**
- Modify: `src/g1_interface/g1_interface/config.py`
- Modify: `src/g1_interface/g1_interface/node.py`
- Modify: `src/g1_interface/config/g1_interface.yaml`
- Modify: `src/g1_interface/launch/g1_interface.launch.py`
- Test: `src/g1_interface/tests/test_config.py`
- Test: `src/g1_interface/tests/test_asr_bridge_node.py`

**Interfaces:**
- Consumes: `G1InterfaceConfig.default()`, `G1InterfaceConfig.from_yaml(path)`, `G1InterfaceNode.on_audio_msg(msg)`
- Produces: `G1InterfaceConfig.asr: dict[str, Any]`, `G1InterfaceConfig.with_asr_source_mode(source_mode: str) -> G1InterfaceConfig`, source modes `"builtin" | "custom" | "both"`

- [ ] **Step 1: Write config tests first**

Append to `src/g1_interface/tests/test_config.py`:

```python
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
```

If `pytest` is not imported in this file, add:

```python
import pytest
```

- [ ] **Step 2: Run config tests and verify they fail**

Run:

```bash
nix develop --command bash -lc 'source /opt/ros/humble/setup.bash 2>/dev/null || true; source install/setup.bash 2>/dev/null || true; PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 PYTHONPATH=src/g1_interface python3 -m pytest src/g1_interface/tests/test_config.py -q'
```

Expected before implementation: FAIL because `G1InterfaceConfig` has no `asr` field.

- [ ] **Step 3: Implement config field and validation**

In `src/g1_interface/g1_interface/config.py`, add this default section to `DEFAULT_CONFIG`:

```python
    "asr": {
        "source_mode": "builtin",
    },
```

Update the dataclass:

```python
@dataclass(frozen=True)
class G1InterfaceConfig:
    robot: dict[str, Any]
    native_topics: dict[str, str]
    project_topics: dict[str, str]
    control: dict[str, Any]
    timeouts: dict[str, int]
    sport_api: dict[str, Any]
    asr: dict[str, Any]
```

Update `_from_dict()`:

```python
        config = cls(
            robot=dict(raw["robot"]),
            native_topics=dict(raw["native_topics"]),
            project_topics=dict(raw["project_topics"]),
            control=dict(raw["control"]),
            timeouts=dict(raw["timeouts"]),
            sport_api=dict(raw["sport_api"]),
            asr=dict(raw["asr"]),
        )
```

Add this method to `G1InterfaceConfig`:

```python
    def with_asr_source_mode(self, source_mode: str) -> "G1InterfaceConfig":
        raw = {
            "robot": self.robot,
            "native_topics": self.native_topics,
            "project_topics": self.project_topics,
            "control": self.control,
            "timeouts": self.timeouts,
            "sport_api": self.sport_api,
            "asr": {**self.asr, "source_mode": source_mode},
        }
        return self._from_dict(raw)
```

Add this validation block in `validate()`:

```python
        source_mode = self.asr.get("source_mode")
        if source_mode not in {"builtin", "custom", "both"}:
            raise ValueError(f"unsupported asr source_mode: {source_mode}")
```

- [ ] **Step 4: Verify config tests pass**

Run:

```bash
nix develop --command bash -lc 'source /opt/ros/humble/setup.bash 2>/dev/null || true; source install/setup.bash 2>/dev/null || true; PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 PYTHONPATH=src/g1_interface python3 -m pytest src/g1_interface/tests/test_config.py -q'
```

Expected: PASS.

- [ ] **Step 5: Write ASR forwarding tests**

Append to `src/g1_interface/tests/test_asr_bridge_node.py`:

```python
def test_audio_msg_callback_drops_builtin_asr_when_source_mode_custom():
    node = FakeNode()
    config = G1InterfaceConfig.default().with_asr_source_mode("custom")
    bridge = G1InterfaceNode(node=node, config=config)
    raw = '{"text":"宇树，向前走一秒","confidence":0.95,"is_final":true,"index":1}'

    bridge.on_audio_msg(_string_msg(raw))

    assert node.publishers["/g1/audio/asr"].messages == []
    assert node.publishers["/g1/audio/event"].messages == []


def test_audio_msg_callback_keeps_audio_events_when_source_mode_custom():
    node = FakeNode()
    config = G1InterfaceConfig.default().with_asr_source_mode("custom")
    bridge = G1InterfaceNode(node=node, config=config)

    bridge.on_audio_msg(_string_msg('{"play_state":1}'))

    assert node.publishers["/g1/audio/asr"].messages == []
    published = node.publishers["/g1/audio/event"].messages
    assert [msg.data for msg in published] == ['{"play_state":1}']


def test_audio_msg_callback_forwards_builtin_asr_when_source_mode_both():
    node = FakeNode()
    config = G1InterfaceConfig.default().with_asr_source_mode("both")
    bridge = G1InterfaceNode(node=node, config=config)
    raw = '{"text":"宇树，向前走一秒","confidence":0.95,"is_final":true,"index":1}'

    bridge.on_audio_msg(_string_msg(raw))

    published = node.publishers["/g1/audio/asr"].messages
    assert [msg.data for msg in published] == [raw]
```

- [ ] **Step 6: Run ASR forwarding tests and verify new test fails**

Run:

```bash
nix develop --command bash -lc 'source /opt/ros/humble/setup.bash 2>/dev/null || true; source install/setup.bash 2>/dev/null || true; PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 PYTHONPATH=src/g1_interface python3 -m pytest src/g1_interface/tests/test_asr_bridge_node.py -q'
```

Expected before node implementation: custom mode test FAILS because built-in ASR is still forwarded.

- [ ] **Step 7: Implement source-mode gate**

In `src/g1_interface/g1_interface/node.py`, add this helper near `normalize_audio_asr_message()`:

```python
def should_forward_native_asr(source_mode: str) -> bool:
    return source_mode in {"builtin", "both"}
```

Update `on_audio_msg()`:

```python
    def on_audio_msg(self, msg) -> None:
        raw = getattr(msg, "data", "").strip()
        if not raw:
            return

        normalized = normalize_audio_asr_message(raw)
        if normalized is not None:
            if should_forward_native_asr(str(self.config.asr["source_mode"])):
                text = self.msg["String"]()
                text.data = normalized
                self.asr_pub.publish(text)
            return

        text = self.msg["String"]()
        text.data = raw
        self.audio_event_pub.publish(text)
```

- [ ] **Step 8: Add ROS parameter override in main**

In `src/g1_interface/g1_interface/node.py`, update `main()` after `config_path` handling:

```python
    node.declare_parameter("asr_source_mode", "")
    asr_source_mode = node.get_parameter("asr_source_mode").get_parameter_value().string_value
    config = G1InterfaceConfig.from_yaml(config_path) if config_path else G1InterfaceConfig.default()
    if asr_source_mode:
        config = config.with_asr_source_mode(asr_source_mode)
```

This replaces the existing single-line `config = ...` assignment.

- [ ] **Step 9: Add launch argument**

In `src/g1_interface/launch/g1_interface.launch.py`, add:

```python
    asr_source_mode = LaunchConfiguration("asr_source_mode")
```

Add a launch argument:

```python
            DeclareLaunchArgument("asr_source_mode", default_value=""),
```

Update node parameters:

```python
                parameters=[{"config_path": config_path, "asr_source_mode": asr_source_mode}],
```

- [ ] **Step 10: Update default YAML**

In `src/g1_interface/config/g1_interface.yaml`, add:

```yaml
asr:
  source_mode: builtin
```

- [ ] **Step 11: Verify g1_interface tests pass**

Run:

```bash
nix develop --command bash -lc 'source /opt/ros/humble/setup.bash 2>/dev/null || true; source install/setup.bash 2>/dev/null || true; PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 PYTHONPATH=src/g1_interface python3 -m pytest src/g1_interface/tests/test_config.py src/g1_interface/tests/test_asr_bridge_node.py -q'
```

Expected: all selected g1_interface tests PASS.

- [ ] **Step 12: Commit**

```bash
git add src/g1_interface/g1_interface/config.py src/g1_interface/g1_interface/node.py src/g1_interface/config/g1_interface.yaml src/g1_interface/launch/g1_interface.launch.py src/g1_interface/tests/test_config.py src/g1_interface/tests/test_asr_bridge_node.py
git commit -m "feat: add asr source selection"
```

---

### Task 3: Fix Speech Buffer Padding

**Files:**
- Modify: `src/asr_node/asr_node/buffer.py`
- Test: `src/asr_node/tests/test_buffer.py`

**Interfaces:**
- Consumes: `SpeechBuffer.add_silence(pcm_bytes: bytes) -> SpeechSegment | None`
- Produces: completed segment whose trailing silence padding uses accumulated `_silence_buffer[-padding_bytes:]`

- [ ] **Step 1: Add failing padding test**

Append to `src/asr_node/tests/test_buffer.py`:

```python
def test_segment_padding_uses_accumulated_silence_buffer():
    buf = SpeechBuffer(
        sample_rate=16000,
        min_speech_duration_ms=100,
        max_silence_duration_ms=300,
        max_speech_duration_ms=15000,
        padding_ms=200,
    )
    speech = b"\x01\x00" * (16000 * 200 // 1000)
    silence_a = b"\x02\x00" * (16000 * 160 // 1000)
    silence_b = b"\x03\x00" * (16000 * 160 // 1000)

    buf.add_speech(speech)
    assert buf.add_silence(silence_a) is None
    result = buf.add_silence(silence_b)

    assert result is not None
    expected_padding_bytes = 200 * 32
    assert result.pcm_int16.endswith((silence_a + silence_b)[-expected_padding_bytes:])
```

- [ ] **Step 2: Run test and verify it fails**

Run:

```bash
nix develop --command bash -lc 'source /opt/ros/humble/setup.bash 2>/dev/null || true; source install/setup.bash 2>/dev/null || true; PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 PYTHONPATH=src/asr_node python3 -m pytest src/asr_node/tests/test_buffer.py::test_segment_padding_uses_accumulated_silence_buffer -q'
```

Expected before implementation: FAIL because only the current silence chunk is used for padding.

- [ ] **Step 3: Implement accumulated padding**

In `src/asr_node/asr_node/buffer.py`, replace:

```python
            keep = min(self.padding_bytes, len(pcm_bytes))
            self._buffer.extend(pcm_bytes[-keep:])
```

with:

```python
            keep = min(self.padding_bytes, len(self._silence_buffer))
            if keep > 0:
                self._buffer.extend(self._silence_buffer[-keep:])
```

- [ ] **Step 4: Verify buffer tests pass**

Run:

```bash
nix develop --command bash -lc 'source /opt/ros/humble/setup.bash 2>/dev/null || true; source install/setup.bash 2>/dev/null || true; PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 PYTHONPATH=src/asr_node python3 -m pytest src/asr_node/tests/test_buffer.py -q'
```

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add src/asr_node/asr_node/buffer.py src/asr_node/tests/test_buffer.py
git commit -m "fix: preserve configured asr trailing padding"
```

---

### Task 4: Harden VAD Windowing And Process Loop Errors

**Files:**
- Modify: `src/asr_node/asr_node/vad.py`
- Modify: `src/asr_node/asr_node/node.py`
- Test: `src/asr_node/tests/test_vad.py`
- Test: `src/asr_node/tests/test_node.py`

**Interfaces:**
- Consumes: `SileroVAD.detect(pcm_bytes: bytes) -> bool`, `AsrNode._process_loop() -> None`
- Produces: VAD detection that chunks long PCM buffers into model windows; process loop that logs VAD errors and continues without killing the thread

- [ ] **Step 1: Add VAD windowing test**

Append to `src/asr_node/tests/test_vad.py`:

```python
def test_detect_splits_160ms_chunk_into_512_sample_windows(monkeypatch):
    import asr_node.vad as vad_module

    calls = []

    class FakeTensor:
        def __init__(self, value):
            self._value = value

        def item(self):
            return self._value

    class FakeModel:
        def __call__(self, tensor, sample_rate):
            calls.append((len(tensor), sample_rate))
            return FakeTensor(0.6 if len(calls) == 2 else 0.1)

    monkeypatch.setattr(vad_module, "_model", FakeModel())
    monkeypatch.setattr(vad_module, "_ensure_model", lambda: None)

    detector = SileroVAD(threshold=0.5, sample_rate=16000)
    pcm = b"\x00\x00" * 2560

    assert detector.detect(pcm) is True
    assert calls == [(512, 16000), (512, 16000), (512, 16000), (512, 16000), (512, 16000)]
```

- [ ] **Step 2: Run VAD test and verify it fails**

Run:

```bash
nix develop --command bash -lc 'source /opt/ros/humble/setup.bash 2>/dev/null || true; source install/setup.bash 2>/dev/null || true; PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 PYTHONPATH=src/asr_node python3 -m pytest src/asr_node/tests/test_vad.py::test_detect_splits_160ms_chunk_into_512_sample_windows -q'
```

Expected before implementation: FAIL because the whole 2560-sample chunk is passed once.

- [ ] **Step 3: Implement VAD windowing**

In `src/asr_node/asr_node/vad.py`, add this method to `SileroVAD`:

```python
    def _window_size_samples(self) -> int:
        if self.sample_rate == 16000:
            return 512
        if self.sample_rate == 8000:
            return 256
        raise ValueError(f"unsupported VAD sample_rate: {self.sample_rate}")
```

Replace `detect()` with:

```python
    def detect(self, pcm_bytes: bytes) -> bool:
        """Detect whether a 16-bit LE PCM chunk contains speech."""
        import numpy as np
        import torch

        audio = np.frombuffer(pcm_bytes, dtype=np.int16).astype(np.float32) / 32768.0
        window = self._window_size_samples()
        if audio.size == 0:
            return False

        probabilities = []
        for start in range(0, audio.size, window):
            chunk = audio[start : start + window]
            if chunk.size < window:
                chunk = np.pad(chunk, (0, window - chunk.size))
            tensor = torch.from_numpy(chunk)
            probabilities.append(float(_model(tensor, self.sample_rate).item()))

        return max(probabilities, default=0.0) > self.threshold
```

- [ ] **Step 4: Add process-loop VAD error test**

Append to `src/asr_node/tests/test_node.py`:

```python
def test_process_loop_logs_vad_error_and_continues():
    mock_pub = MagicMock()
    node = _make_uninitialized_node(_make_config(), mock_pub)
    node._pcm_queue = queue.Queue()
    node._segment_queue = queue.Queue()
    node._vad = MagicMock()
    node._vad.detect.side_effect = [RuntimeError("bad vad input"), False]
    node._buffer = MagicMock()
    node._buffer.add_silence.return_value = None
    node._buffer.force_complete.return_value = None

    node._pcm_queue.put(b"\x00\x00" * 2560)
    node._pcm_queue.put(b"\x00\x00" * 2560)
    node._pcm_queue.put(_STOP_SENTINEL)
    node._process_loop()

    warnings = [call.args[0] for call in node.node.get_logger.return_value.warning.call_args_list]
    assert any("VAD detection failed" in warning for warning in warnings)
    assert node._segment_queue.get_nowait() is _STOP_SENTINEL
```

- [ ] **Step 5: Run process-loop test and verify it fails**

Run:

```bash
nix develop --command bash -lc 'source /opt/ros/humble/setup.bash 2>/dev/null || true; source install/setup.bash 2>/dev/null || true; PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 PYTHONPATH=src/asr_node python3 -m pytest src/asr_node/tests/test_node.py::test_process_loop_logs_vad_error_and_continues -q'
```

Expected before implementation: FAIL because VAD exception exits `_process_loop()`.

- [ ] **Step 6: Catch VAD exceptions**

In `src/asr_node/asr_node/node.py`, replace:

```python
            is_speech = self._vad.detect(pcm_bytes)
```

with:

```python
            try:
                is_speech = self._vad.detect(pcm_bytes)
            except Exception as exc:
                self.node.get_logger().warning(f"VAD detection failed: {exc}")
                is_speech = False
```

- [ ] **Step 7: Verify VAD and node tests pass**

Run:

```bash
nix develop --command bash -lc 'source /opt/ros/humble/setup.bash 2>/dev/null || true; source install/setup.bash 2>/dev/null || true; PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 PYTHONPATH=src/asr_node python3 -m pytest src/asr_node/tests/test_vad.py src/asr_node/tests/test_node.py -q'
```

Expected: PASS with existing skipped GPU tests unchanged.

- [ ] **Step 8: Commit**

```bash
git add src/asr_node/asr_node/vad.py src/asr_node/asr_node/node.py src/asr_node/tests/test_vad.py src/asr_node/tests/test_node.py
git commit -m "fix: harden asr vad processing"
```

---

### Task 5: Prevent Shutdown Blocking And Declare Runtime Dependencies

**Files:**
- Modify: `src/asr_node/asr_node/node.py`
- Modify: `src/asr_node/setup.py`
- Modify: `src/asr_node/package.xml`
- Test: `src/asr_node/tests/test_node.py`

**Interfaces:**
- Consumes: `AsrNode.stop() -> None`
- Produces: shutdown path that uses bounded queue operations and logs failure instead of blocking forever

- [ ] **Step 1: Add shutdown sentinel tests**

Append to `src/asr_node/tests/test_node.py`:

```python
def test_stop_logs_warning_when_pcm_queue_full():
    mock_pub = MagicMock()
    node = _make_uninitialized_node(_make_config(), mock_pub)
    node._capture = MagicMock()
    node._pcm_queue = queue.Queue(maxsize=1)
    node._pcm_queue.put(b"full")

    node.stop()

    warnings = [call.args[0] for call in node.node.get_logger.return_value.warning.call_args_list]
    assert any("pcm queue full during shutdown" in warning for warning in warnings)
```

- [ ] **Step 2: Run shutdown test and verify it fails or hangs without timeout**

Run:

```bash
nix develop --command bash -lc 'source /opt/ros/humble/setup.bash 2>/dev/null || true; source install/setup.bash 2>/dev/null || true; PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 PYTHONPATH=src/asr_node timeout 10 python3 -m pytest src/asr_node/tests/test_node.py::test_stop_logs_warning_when_pcm_queue_full -q'
```

Expected before implementation: command times out or fails because `stop()` blocks on `_pcm_queue.put()`.

- [ ] **Step 3: Implement bounded stop**

In `src/asr_node/asr_node/node.py`, replace:

```python
        self._pcm_queue.put(_STOP_SENTINEL)
```

with:

```python
        try:
            self._pcm_queue.put(_STOP_SENTINEL, timeout=1.0)
        except queue.Full:
            self.node.get_logger().warning("pcm queue full during shutdown, process thread may not stop cleanly")
```

In `_process_loop()`, replace:

```python
                self._segment_queue.put(_STOP_SENTINEL)
```

with:

```python
                try:
                    self._segment_queue.put(_STOP_SENTINEL, timeout=2.0)
                except queue.Full:
                    self.node.get_logger().warning("segment queue full during shutdown, worker may not stop cleanly")
```

- [ ] **Step 4: Declare Python dependencies**

In `src/asr_node/setup.py`, replace:

```python
    install_requires=["setuptools", "PyYAML", "numpy"],
```

with:

```python
    install_requires=["setuptools", "PyYAML", "numpy", "faster-whisper", "torch"],
```

In `src/asr_node/package.xml`, after `std_msgs`, add:

```xml
  <!-- faster-whisper and torch are Python runtime dependencies declared in setup.py. -->
```

- [ ] **Step 5: Verify ASR node tests pass**

Run:

```bash
nix develop --command bash -lc 'source /opt/ros/humble/setup.bash 2>/dev/null || true; source install/setup.bash 2>/dev/null || true; PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 PYTHONPATH=src/asr_node python3 -m pytest src/asr_node/tests -q'
```

Expected: `34+ passed` with GPU-dependent VAD tests still skipped unless explicitly enabled.

- [ ] **Step 6: Commit**

```bash
git add src/asr_node/asr_node/node.py src/asr_node/setup.py src/asr_node/package.xml src/asr_node/tests/test_node.py
git commit -m "fix: bound asr shutdown and declare runtime deps"
```

---

### Task 6: Document ASR Source Modes And Run Full Verification

**Files:**
- Modify: `docs/data_contracts.md`
- Optional Modify: `docs/superpowers/specs/2026-07-08-custom-asr-node-design.md`

**Interfaces:**
- Consumes: implemented `asr.source_mode`
- Produces: documented operator behavior for `builtin`, `custom`, and `both`

- [ ] **Step 1: Update data contract**

In `docs/data_contracts.md`, in the `/g1/audio/asr` section, add:

```markdown
ASR source selection is controlled by `g1_interface` config `asr.source_mode`:

- `builtin`: forward ASR-shaped native `/audio_msg` messages to `/g1/audio/asr`; do not start `asr_node`.
- `custom`: drop ASR-shaped native `/audio_msg` messages; start `asr_node`, which publishes `/g1/audio/asr` directly.
- `both`: forward native ASR and allow custom ASR concurrently; downstream consumers may receive duplicate semantic commands and this mode is for diagnostics only.

Recommended runtime commands:

```bash
ros2 launch g1_interface g1_interface.launch.py asr_source_mode:=builtin
ros2 launch g1_interface g1_interface.launch.py asr_source_mode:=custom
ros2 launch asr_node asr_node.launch.py
```
```

- [ ] **Step 2: Run full focused verification with nix shell**

Run:

```bash
nix develop --command bash -lc 'source /opt/ros/humble/setup.bash 2>/dev/null || true; source install/setup.bash 2>/dev/null || true; PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 PYTHONPATH=src/asr_node:src/g1_interface:src/voice_bridge python3 -m pytest src/asr_node/tests src/g1_interface/tests/test_config.py src/g1_interface/tests/test_asr_bridge_node.py src/voice_bridge/tests/test_intent.py -q'
```

Expected: selected tests PASS; GPU-dependent tests remain skipped unless the environment explicitly enables them.

- [ ] **Step 3: Run package import smoke check through nix shell**

Run:

```bash
nix develop --command bash -lc 'source /opt/ros/humble/setup.bash 2>/dev/null || true; source install/setup.bash 2>/dev/null || true; PYTHONPATH=src/asr_node:src/g1_interface:src/voice_bridge python3 - <<'"'"'PY'"'"'
from asr_node.config import AsrNodeConfig
from g1_interface.config import G1InterfaceConfig
from voice_bridge.intent import parse_asr_event

assert AsrNodeConfig.default().topics["asr_output"] == "/g1/audio/asr"
assert G1InterfaceConfig.default().asr["source_mode"] == "builtin"
assert G1InterfaceConfig.default().with_asr_source_mode("custom").asr["source_mode"] == "custom"
assert parse_asr_event('{"text":"宇树向前","source":"custom_asr"}').source == "custom_asr"
print("smoke ok")
PY'
```

Expected: `smoke ok`.

- [ ] **Step 4: Commit**

```bash
git add docs/data_contracts.md docs/superpowers/specs/2026-07-08-custom-asr-node-design.md
git commit -m "docs: describe asr source modes"
```

---

## Self-Review

**Spec coverage:** The plan implements explicit built-in/custom/both ASR source selection, fixes duplicate forwarding risk, hardens custom ASR VAD/buffer/shutdown paths, and uses `nix develop` for ROS-aware verification.

**Placeholder scan:** No task uses TBD/TODO-style placeholders. Every code-changing step includes concrete snippets and exact verification commands.

**Type consistency:** `G1InterfaceConfig.asr["source_mode"]`, `with_asr_source_mode(source_mode: str)`, and `should_forward_native_asr(source_mode: str) -> bool` are consistently named across config, node, launch, and tests.

