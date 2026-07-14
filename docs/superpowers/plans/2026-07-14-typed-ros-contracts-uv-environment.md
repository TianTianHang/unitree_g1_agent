# Typed ROS Contracts and uv Environment Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 建立 `g1_agent_msgs`，把语音运动核心链路原地迁移到强类型 ROS 2 消息，并以 uv 管理唯一受支持的 ROS Humble/Python 3.10 开发与 CI 环境。

**Architecture:** `g1_agent_msgs` 只定义项目上层的语音事件、运动意图、安全决策和状态摘要；Unitree 官方 `unitree_hg` 与 `unitree_api` 消息继续作为底层硬件接口。各节点在 ROS 边界构造或消费生成消息，JSON 仅保留在 Unitree API、Pi/HTTP、WebSocket 和调试日志边界。

**Tech Stack:** Ubuntu 22.04、ROS 2 Humble、Python 3.10、uv 0.11.26、ament_cmake、rosidl、rclpy、launch_testing、pytest、ruff、pyright、FastAPI、React/Vite。

## Global Constraints

- 唯一支持的 Python 是 `/usr/bin/python3` 3.10；现有 Python 3.11 `.venv` 不用于 ROS 构建或测试。
- uv 固定为 `0.11.26`，项目环境固定为 `.venv-ros`，并以 `--system-site-packages` 访问 ROS Humble apt 包。
- 所有 Python 命令设置 `PYTHONNOUSERSITE=1`；所有 pytest 命令设置 `PYTEST_DISABLE_PLUGIN_AUTOLOAD=1`。
- 核心 topic 原地切换，不新增 `/typed` topic，不提供 JSON 双发布或兼容开关。
- Unitree 官方 `.unitree/unitree_ros2/cyclonedds_ws/src/unitree/unitree_hg/msg/LowState.msg`、`.unitree/unitree_ros2/cyclonedds_ws/src/unitree/unitree_api/msg/Request.msg` 和 `Response.msg` 是底层字段证据；不得在 `g1_agent_msgs` 重复定义 LowState、MotorState、Request 或 Response。
- Unitree Sport API 官方 `parameter`/`data` 字段本身是 string，因此该外部边界继续使用 JSON。
- `/g1/state/motors` 是本阶段之外的非核心监控 topic，继续使用现有格式；本阶段不得顺带设计电机数组消息。
- stop、cancel、watchdog stop 和 shutdown stop 不得被 stale lowstate、mode 或 safety heartbeat 阻止。
- 所有安全 deadline 和 freshness 继续使用单调时钟；ROS time 只用于对外消息时间戳。
- 不在核心消息中加入 raw JSON、通用 key/value 或 `schema_version` 字段。

---

### Task 1: 建立 uv Python 3.10 环境和统一 Makefile

**Files:**
- Create: `pyproject.toml`
- Create: `uv.lock`
- Create: `Makefile`
- Create: `tests/tooling/test_tooling_contract.sh`
- Modify: `.gitignore`
- Modify: `flake.nix`

**Interfaces:**
- Consumes: `/usr/bin/python3`、uv 0.11.26、`/opt/ros/humble/setup.bash`、可选 `result/setup.bash`。
- Produces: `.venv-ros`、`make bootstrap`、`make bootstrap-asr`、`make build`、`make test`、`make test-integration`、`make lint`、`make frontend`。

- [ ] **Step 1: 写工具链契约失败测试**

```bash
#!/usr/bin/env bash
set -euo pipefail

test -f pyproject.toml
test -f uv.lock
test -f Makefile
grep -Fq 'requires-python = "==3.10.*"' pyproject.toml
grep -Fq 'package = false' pyproject.toml
grep -Fq '.venv-ros/' .gitignore

for target in bootstrap bootstrap-asr build test test-integration lint frontend; do
  make -pn | grep -Eq "^${target}:"
done

test "$(uv --version)" = "uv 0.11.26"
```

- [ ] **Step 2: 运行契约测试并确认失败**

Run: `bash tests/tooling/test_tooling_contract.sh`

Expected: FAIL at `test -f pyproject.toml`。

- [ ] **Step 3: 添加 pyproject 和 uv 锁定依赖**

Create `pyproject.toml`:

```toml
[project]
name = "unitree-g1-agent-workspace"
version = "0.1.0"
requires-python = "==3.10.*"
dependencies = [
  "PyYAML==6.0.3",
]

[dependency-groups]
test = [
  "numpy==2.2.6",
  "pytest==8.3.5",
  "pytest-timeout==2.4.0",
]
debug = [
  "fastapi==0.115.12",
  "httpx==0.28.1",
  "starlette==0.46.2",
  "uvicorn[standard]==0.34.3",
]
lint = [
  "pyright==1.1.401",
  "ruff==0.11.13",
]
asr = [
  "faster-whisper==1.2.1",
  "torch==2.7.1",
]

[tool.uv]
package = false
default-groups = ["test", "debug", "lint"]

[tool.pytest.ini_options]
testpaths = ["src"]
addopts = "-ra --import-mode=importlib"

[tool.ruff]
target-version = "py310"
line-length = 120
src = ["src"]

[tool.ruff.lint]
select = ["E", "F", "I", "UP"]

[tool.pyright]
pythonVersion = "3.10"
typeCheckingMode = "basic"
include = [
  "src/asr_node/asr_node",
  "src/g1_interface/g1_interface",
  "src/safety_control/safety_control",
  "src/voice_bridge/voice_bridge",
  "src/voice_bridge_debug/voice_bridge_debug",
]
exclude = ["build", "install", "log", ".unitree"]
reportMissingImports = false
```

Generate the lock file:

Run: `uv lock --python /usr/bin/python3`

Expected: creates `uv.lock` with Python 3.10-compatible locked transitive dependencies.

- [ ] **Step 4: 添加 Makefile 和环境隔离**

Create `Makefile`:

```make
SHELL := /bin/bash
UV_ENV := .venv-ros
UV_RUN := UV_PROJECT_ENVIRONMENT=$(UV_ENV) uv run --frozen
ROS_SETUP := source /opt/ros/humble/setup.bash; if [[ -f result/setup.bash ]]; then source result/setup.bash; fi

export PYTHONNOUSERSITE := 1
export PYTEST_DISABLE_PLUGIN_AUTOLOAD := 1
export UV_PROJECT_ENVIRONMENT := $(UV_ENV)

.PHONY: bootstrap bootstrap-asr build test test-integration lint frontend

bootstrap:
	@test "$$($(abspath /usr/bin/python3) -c 'import sys; print(str(sys.version_info.major) + "." + str(sys.version_info.minor))')" = "3.10"
	@test "$$(uv --version)" = "uv 0.11.26"
	@if [[ ! -d $(UV_ENV) ]]; then uv venv --python /usr/bin/python3 --system-site-packages $(UV_ENV); fi
	@test "$$($(UV_ENV)/bin/python -c 'import sys; print(str(sys.version_info.major) + "." + str(sys.version_info.minor))')" = "3.10"
	@grep -Fq 'include-system-site-packages = true' $(UV_ENV)/pyvenv.cfg
	@uv sync --frozen

bootstrap-asr: bootstrap
	@uv sync --frozen --group asr

build: bootstrap
	@$(ROS_SETUP); colcon build --symlink-install --event-handlers console_direct+

test: build
	@$(ROS_SETUP); source install/setup.bash; $(UV_RUN) python -m pytest -q \
		src/g1_agent_msgs/test src/asr_node/tests src/g1_interface/tests src/g1_sim/tests \
		src/safety_control/tests src/voice_bridge/tests src/voice_bridge_debug/tests

test-integration: build
	@$(ROS_SETUP); source install/setup.bash; colcon test --packages-select g1_system_tests --event-handlers console_direct+
	@$(ROS_SETUP); source install/setup.bash; colcon test-result --verbose

lint: bootstrap
	@$(UV_RUN) ruff check src
	@$(UV_RUN) pyright

frontend:
	@npm --prefix src/voice_bridge_debug/frontend ci
	@npm --prefix src/voice_bridge_debug/frontend run build
	@git diff --exit-code -- src/voice_bridge_debug/voice_bridge_debug/frontend_dist
```

Append to `.gitignore`:

```gitignore
.venv-ros/
```

In `flake.nix`, delete `systemPytest` and remove it from `buildInputs`; keep `cmake`, `gcc`, `ninja`, `git`, SDK2 and Unitree ROS inputs. Change the shell help to print `make bootstrap`, `make build`, and `make test`.

- [ ] **Step 5: 验证工具链契约和 frozen sync**

Run: `bash tests/tooling/test_tooling_contract.sh`

Expected: PASS.

Run: `make bootstrap`

Expected: `.venv-ros/bin/python` reports Python 3.10 and `uv sync --frozen` exits 0.

- [ ] **Step 6: Commit**

```bash
git add pyproject.toml uv.lock Makefile tests/tooling/test_tooling_contract.sh .gitignore flake.nix
git commit -m "build: standardize ROS Python environment with uv"
```

---

### Task 2: 创建 g1_agent_msgs 接口包

**Files:**
- Create: `src/g1_agent_msgs/CMakeLists.txt`
- Create: `src/g1_agent_msgs/package.xml`
- Create: `src/g1_agent_msgs/msg/VoiceEvent.msg`
- Create: `src/g1_agent_msgs/msg/LocoIntent.msg`
- Create: `src/g1_agent_msgs/msg/ActionIntent.msg`
- Create: `src/g1_agent_msgs/msg/RobotStateSummary.msg`
- Create: `src/g1_agent_msgs/msg/SafetyDecision.msg`
- Create: `src/g1_agent_msgs/msg/ValidatedLocoCommand.msg`
- Create: `src/g1_agent_msgs/msg/ValidatedActionCommand.msg`
- Create: `src/g1_agent_msgs/msg/SafetyStatus.msg`
- Create: `src/g1_agent_msgs/test/test_interfaces.py`

**Interfaces:**
- Consumes: `builtin_interfaces`, `geometry_msgs`, standard ROS Humble rosidl generators.
- Produces: the eight generated Python message classes used by Tasks 3-9.

- [ ] **Step 1: 写消息导入与常量失败测试**

```python
from builtin_interfaces.msg import Duration, Time
from g1_agent_msgs.msg import (
    ActionIntent,
    LocoIntent,
    RobotStateSummary,
    SafetyDecision,
    SafetyStatus,
    ValidatedActionCommand,
    ValidatedLocoCommand,
    VoiceEvent,
)


def test_all_interfaces_construct_and_nest():
    voice = VoiceEvent(stamp=Time(sec=1), event_type=VoiceEvent.EVENT_ASR, text="向前")
    loco = LocoIntent(created_at=Time(sec=1), command_id="c1", duration=Duration(sec=1))
    action = ActionIntent(action=ActionIntent.ACTION_STOP, priority=ActionIntent.PRIORITY_EMERGENCY)
    state = RobotStateSummary(mode=RobotStateSummary.MODE_SPORT_API_LOCO)
    decision = SafetyDecision(
        command_id="c1",
        command_kind=SafetyDecision.KIND_LOCO,
        decision=SafetyDecision.DECISION_ALLOW,
        robot_state=state,
    )

    assert voice.text == "向前"
    assert ValidatedLocoCommand(intent=loco, validation=decision).intent.command_id == "c1"
    assert ValidatedActionCommand(intent=action, validation=decision).intent.action == "stop"
    assert SafetyStatus(last_decision=decision).last_decision.command_id == "c1"


def test_optional_numeric_fields_use_presence_flags():
    voice = VoiceEvent(has_confidence=False, confidence=0.0)
    state = RobotStateSummary(has_battery_voltage=False, battery_voltage=0.0)
    assert voice.has_confidence is False
    assert state.has_battery_voltage is False
```

- [ ] **Step 2: 运行接口测试并确认失败**

Run: `source /opt/ros/humble/setup.bash && PYTHONNOUSERSITE=1 .venv-ros/bin/python -m pytest -q src/g1_agent_msgs/test/test_interfaces.py`

Expected: FAIL with `ModuleNotFoundError: g1_agent_msgs`.

- [ ] **Step 3: 写 8 个消息定义**

Create `VoiceEvent.msg`:

```text
string EVENT_ASR="asr"
string EVENT_PLAYBACK="playback"
int8 PLAYBACK_STOPPED=0
int8 PLAYBACK_PLAYING=1

builtin_interfaces/Time stamp
string source
string event_type
bool has_sequence_id
uint64 sequence_id
string text
bool has_confidence
float32 confidence
bool is_final
string language
bool has_playback_state
int8 playback_state
```

Create `LocoIntent.msg`:

```text
builtin_interfaces/Time created_at
string source
string session_id
string command_id
string text
float64 vx
float64 vy
float64 vyaw
builtin_interfaces/Duration duration
```

Create `ActionIntent.msg`:

```text
string ACTION_STOP="stop"
string ACTION_CANCEL="cancel"
string PRIORITY_NORMAL="normal"
string PRIORITY_EMERGENCY="emergency"

builtin_interfaces/Time created_at
string source
string session_id
string command_id
string text
string action
string priority
```

Create `RobotStateSummary.msg`:

```text
string MODE_UNKNOWN="unknown"
string MODE_SPORT_API_LOCO="sport_api_loco"
string MODE_USER_CTRL="user_ctrl"
string MODE_ARMED="armed_mode"
string OWNER_UNKNOWN="unknown"
string OWNER_INTERNAL="internal"
string OWNER_USER="user"
string HEALTH_UNKNOWN="unknown"
string HEALTH_OK="ok"
string HEALTH_DEGRADED="degraded"
string HEALTH_UNHEALTHY="unhealthy"

builtin_interfaces/Time stamp
string source
string mode
string control_owner
string mode_source
bool has_sport_fsm_mode
int32 sport_fsm_mode
bool has_sport_fsm_id
int32 sport_fsm_id
geometry_msgs/Vector3 rpy
geometry_msgs/Quaternion orientation
geometry_msgs/Vector3 angular_velocity
geometry_msgs/Vector3 linear_acceleration
uint32 motor_count
bool has_max_temperature
float32 max_temperature_c
bool has_battery_voltage
float32 battery_voltage
geometry_msgs/Twist velocity
string velocity_source
string health_state
bool has_lowstate_age
builtin_interfaces/Duration lowstate_age
```

Create `SafetyDecision.msg`:

```text
string KIND_LOCO="loco"
string KIND_ACTION="action"
string DECISION_ALLOW="allow"
string DECISION_REJECT="reject"

builtin_interfaces/Time stamp
string command_id
string command_kind
string decision
string reason
builtin_interfaces/Duration validation_latency
g1_agent_msgs/RobotStateSummary robot_state
```

Create `ValidatedLocoCommand.msg`:

```text
g1_agent_msgs/LocoIntent intent
builtin_interfaces/Time validated_at
g1_agent_msgs/SafetyDecision validation
```

Create `ValidatedActionCommand.msg`:

```text
g1_agent_msgs/ActionIntent intent
builtin_interfaces/Time validated_at
g1_agent_msgs/SafetyDecision validation
```

Create `SafetyStatus.msg`:

```text
builtin_interfaces/Time stamp
string node_name
bool enabled
bool strict_mode
g1_agent_msgs/RobotStateSummary robot_state
uint64 allow_count
uint64 reject_count
float64 rejection_rate
string last_rejection_reason
bool has_last_decision
g1_agent_msgs/SafetyDecision last_decision
```

- [ ] **Step 4: 添加官方风格的接口包构建文件**

Create `CMakeLists.txt`:

```cmake
cmake_minimum_required(VERSION 3.8)
project(g1_agent_msgs)

find_package(ament_cmake REQUIRED)
find_package(builtin_interfaces REQUIRED)
find_package(geometry_msgs REQUIRED)
find_package(rosidl_default_generators REQUIRED)

rosidl_generate_interfaces(${PROJECT_NAME}
  "msg/VoiceEvent.msg"
  "msg/LocoIntent.msg"
  "msg/ActionIntent.msg"
  "msg/RobotStateSummary.msg"
  "msg/SafetyDecision.msg"
  "msg/ValidatedLocoCommand.msg"
  "msg/ValidatedActionCommand.msg"
  "msg/SafetyStatus.msg"
  DEPENDENCIES builtin_interfaces geometry_msgs
)

if(BUILD_TESTING)
  find_package(ament_cmake_pytest REQUIRED)
  ament_add_pytest_test(test_interfaces test/test_interfaces.py)
endif()

ament_export_dependencies(rosidl_default_runtime)
ament_package()
```

Create `package.xml`:

```xml
<?xml version="1.0"?>
<package format="3">
  <name>g1_agent_msgs</name>
  <version>0.1.0</version>
  <description>Typed ROS 2 contracts for the Unitree G1 agent control stack.</description>
  <maintainer email="2450804878@qq.com">unitree_g1_agent</maintainer>
  <license>Apache-2.0</license>
  <buildtool_depend>ament_cmake</buildtool_depend>
  <build_depend>rosidl_default_generators</build_depend>
  <depend>builtin_interfaces</depend>
  <depend>geometry_msgs</depend>
  <exec_depend>rosidl_default_runtime</exec_depend>
  <test_depend>ament_cmake_pytest</test_depend>
  <member_of_group>rosidl_interface_packages</member_of_group>
  <export><build_type>ament_cmake</build_type></export>
</package>
```

- [ ] **Step 5: 构建并运行接口测试**

Run: `source /opt/ros/humble/setup.bash && colcon build --symlink-install --packages-select g1_agent_msgs`

Expected: build succeeds.

Run: `source install/setup.bash && PYTHONNOUSERSITE=1 .venv-ros/bin/python -m pytest -q src/g1_agent_msgs/test/test_interfaces.py`

Expected: `2 passed`.

- [ ] **Step 6: Commit**

```bash
git add src/g1_agent_msgs
git commit -m "feat: add typed G1 agent ROS messages"
```

---

### Task 3: 将 asr_node 输出迁移为 VoiceEvent

**Files:**
- Modify: `src/asr_node/package.xml`
- Modify: `src/asr_node/asr_node/node.py`
- Modify: `src/asr_node/tests/test_node.py`

**Interfaces:**
- Consumes: `g1_agent_msgs.msg.VoiceEvent` from Task 2.
- Produces: typed `/g1/audio/asr` events with source, language, sequence and ROS timestamp.

- [ ] **Step 1: 将 JSON 断言改为强类型失败测试**

Replace the successful publish assertions with:

```python
def test_transcribe_and_publish_builds_voice_event():
    mock_pub = MagicMock()
    node = _make_uninitialized_node(_make_config(), mock_pub)
    node._engine = MagicMock()
    node._engine.transcribe.return_value = "向前走"

    seg = SpeechSegment(pcm_int16=b"\x00" * 3200, sample_rate=16000, duration_ms=100)
    node._transcribe_and_publish(seg)

    msg = mock_pub.publish.call_args.args[0]
    assert msg.event_type == msg.EVENT_ASR
    assert msg.text == "向前走"
    assert msg.source == "custom_asr"
    assert msg.language == "zh"
    assert msg.is_final is True
    assert msg.has_sequence_id is True
    assert msg.sequence_id == 1
    assert msg.has_confidence is False
    assert msg.stamp.sec == 1
```

Import `builtin_interfaces.msg.Time`; update `_make_uninitialized_node` to use `VoiceEvent` in `node.msg` and configure the existing `MagicMock` clock:

```python
node.msg = {"VoiceEvent": VoiceEvent}
node.node.get_clock.return_value.now.return_value.to_msg.return_value = Time(sec=1)
```

- [ ] **Step 2: 运行 ASR node 测试并确认失败**

Run: `source install/setup.bash && PYTHONNOUSERSITE=1 PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 .venv-ros/bin/python -m pytest -q src/asr_node/tests/test_node.py`

Expected: FAIL because the node still publishes `String.data` JSON.

- [ ] **Step 3: 发布 VoiceEvent**

Change `_load_ros_messages()` and `_transcribe_and_publish()` to:

```python
def _load_ros_messages():
    from g1_agent_msgs.msg import VoiceEvent

    return {"VoiceEvent": VoiceEvent}


def _build_voice_event(self, text: str, sequence_id: int):
    msg = self.msg["VoiceEvent"]()
    msg.stamp = self.node.get_clock().now().to_msg()
    msg.source = str(self.config.output["source"])
    msg.event_type = msg.EVENT_ASR
    msg.has_sequence_id = True
    msg.sequence_id = sequence_id
    msg.text = text
    msg.has_confidence = False
    msg.confidence = 0.0
    msg.is_final = True
    msg.language = str(self.config.model["language"])
    msg.has_playback_state = False
    return msg
```

Create the publisher with `self.msg["VoiceEvent"]`, publish `_build_voice_event(text, index)`, and remove the `json` import.

Add `<exec_depend>g1_agent_msgs</exec_depend>` and remove `<exec_depend>std_msgs</exec_depend>` from `package.xml`.

- [ ] **Step 4: 运行 ASR tests**

Run: `source install/setup.bash && PYTHONNOUSERSITE=1 PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 .venv-ros/bin/python -m pytest -q src/asr_node/tests`

Expected: all ASR unit tests pass; GPU/model tests remain skipped when optional runtime models are unavailable.

- [ ] **Step 5: Commit**

```bash
git add src/asr_node/package.xml src/asr_node/asr_node/node.py src/asr_node/tests/test_node.py
git commit -m "feat: publish typed ASR voice events"
```

---

### Task 4: 将 voice_bridge 输入和运动意图迁移为强类型消息

**Files:**
- Create: `src/voice_bridge/voice_bridge/ros_converters.py`
- Create: `src/voice_bridge/tests/test_ros_converters.py`
- Modify: `src/voice_bridge/package.xml`
- Modify: `src/voice_bridge/voice_bridge/intent.py`
- Modify: `src/voice_bridge/voice_bridge/node.py`
- Modify: `src/voice_bridge/tests/test_intent.py`
- Modify: `src/voice_bridge/tests/test_node_helpers.py`

**Interfaces:**
- Consumes: `VoiceEvent`, `RobotStateSummary`, `SafetyStatus`.
- Produces: `LocoIntent`, `ActionIntent`; debug/TTS/LED/state topics remain JSON `String` boundaries.

- [ ] **Step 1: 写 converter 和节点失败测试**

```python
import pytest
from builtin_interfaces.msg import Time
from g1_agent_msgs.msg import ActionIntent, LocoIntent, VoiceEvent
from voice_bridge.ros_converters import action_intent, asr_event, loco_intent


def test_voice_event_to_internal_asr_event():
    msg = VoiceEvent(
        stamp=Time(sec=10), source="custom_asr", event_type=VoiceEvent.EVENT_ASR,
        text="小宇向前", has_confidence=True, confidence=0.9, is_final=True,
    )
    event = asr_event(msg)
    assert event.text == "小宇向前"
    assert event.confidence == pytest.approx(0.9)
    assert event.source == "custom_asr"


def test_build_typed_intents():
    loco = loco_intent("s1", "c1", "向前", 10.0, 0.2, 0.0, 0.0, 1.0)
    stop = action_intent("s1", "c2", "停止", 10.0, "stop", "emergency")
    assert isinstance(loco, LocoIntent)
    assert loco.duration.sec == 1
    assert isinstance(stop, ActionIntent)
    assert stop.action == ActionIntent.ACTION_STOP
```

Update node tests so `FakePublisher.payloads` stores message objects and asserts `node.action_pub.payloads[0].action == "stop"` and `node.loco_pub.payloads[0].vx == 0.25`.

- [ ] **Step 2: 运行 voice_bridge tests 并确认失败**

Run: `source install/setup.bash && PYTHONNOUSERSITE=1 PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 .venv-ros/bin/python -m pytest -q src/voice_bridge/tests/test_ros_converters.py src/voice_bridge/tests/test_intent.py src/voice_bridge/tests/test_node_helpers.py`

Expected: FAIL because `ros_converters` does not exist and node publishers are still `String`.

- [ ] **Step 3: 实现强类型 converter**

Create `ros_converters.py` with normalized time conversion and builders:

```python
from __future__ import annotations

import math

from builtin_interfaces.msg import Duration, Time
from g1_agent_msgs.msg import ActionIntent, LocoIntent, VoiceEvent
from voice_bridge.internal_types import AsrEvent


def _time_from_sec(value: float) -> Time:
    sec = math.floor(value)
    return Time(sec=sec, nanosec=int((value - sec) * 1_000_000_000))


def _duration_from_sec(value: float) -> Duration:
    sec = math.floor(value)
    return Duration(sec=sec, nanosec=int((value - sec) * 1_000_000_000))


def asr_event(msg: VoiceEvent) -> AsrEvent:
    if msg.event_type != VoiceEvent.EVENT_ASR:
        raise ValueError(f"unsupported voice event: {msg.event_type}")
    return AsrEvent(
        text=msg.text.strip(),
        confidence=float(msg.confidence) if msg.has_confidence else None,
        is_final=bool(msg.is_final),
        source=msg.source,
        stamp=f"{msg.stamp.sec}.{msg.stamp.nanosec:09d}",
    )


def loco_intent(session_id, command_id, text, created_at, vx, vy, vyaw, duration_sec):
    return LocoIntent(
        created_at=_time_from_sec(created_at), source="voice_bridge", session_id=session_id,
        command_id=command_id, text=text, vx=float(vx), vy=float(vy), vyaw=float(vyaw),
        duration=_duration_from_sec(duration_sec),
    )


def action_intent(session_id, command_id, text, created_at, action, priority):
    return ActionIntent(
        created_at=_time_from_sec(created_at), source="voice_bridge", session_id=session_id,
        command_id=command_id, text=text, action=action.lower(), priority=priority.lower(),
    )
```

Delete JSON parsing from `parse_asr_event`; replace it with a direct `AsrEvent` acceptance path or remove the function and call `ros_converters.asr_event` from the node.

- [ ] **Step 4: 迁移 node wiring**

Load and wire generated messages:

```python
from g1_agent_msgs.msg import ActionIntent, LocoIntent, RobotStateSummary, SafetyStatus, VoiceEvent
from std_msgs.msg import String

return {
    "ActionIntent": ActionIntent,
    "DiagnosticArray": DiagnosticArray,
    "LocoIntent": LocoIntent,
    "RobotStateSummary": RobotStateSummary,
    "SafetyStatus": SafetyStatus,
    "String": String,
    "VoiceEvent": VoiceEvent,
}
```

Use `VoiceEvent` for ASR subscription, `RobotStateSummary` for mode, `SafetyStatus` for safety, and typed intent publishers. `on_robot_mode` stores `msg.mode`; `on_safety_state` stores `msg.robot_state.health_state`. Keep `_publish_string` only for debug/TTS/LED/state.

In `_publish_action_decision` and `_publish_agent_result`, publish converter results directly. Build debug payloads explicitly from the typed message fields so debug telemetry remains JSON but motion authorization does not.

Add `<exec_depend>builtin_interfaces</exec_depend>` and `<exec_depend>g1_agent_msgs</exec_depend>` to `package.xml`; retain `std_msgs` for debug/TTS/LED/state.

- [ ] **Step 5: 运行 voice_bridge 全量 tests**

Run: `source install/setup.bash && PYTHONNOUSERSITE=1 PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 .venv-ros/bin/python -m pytest -q src/voice_bridge/tests`

Expected: all non-Pi-integration tests pass; the opt-in Pi integration test remains skipped unless enabled.

- [ ] **Step 6: Commit**

```bash
git add src/voice_bridge
git commit -m "feat: publish typed voice motion intents"
```

---

### Task 5: 将 g1_interface 的 ASR 和机器人摘要发布迁移为强类型消息

**Files:**
- Create: `src/g1_interface/g1_interface/ros_converters.py`
- Create: `src/g1_interface/tests/test_ros_converters.py`
- Modify: `src/g1_interface/package.xml`
- Modify: `src/g1_interface/g1_interface/node.py`
- Modify: `src/g1_interface/tests/test_node_helpers.py`
- Modify: `src/g1_interface/tests/test_asr_bridge_node.py`

**Interfaces:**
- Consumes: Unitree `LowState` and native `/audio_msg` `String`.
- Produces: `RobotStateSummary` on low/mode and `VoiceEvent` on asr/audio event.

- [ ] **Step 1: 写 native audio 和 state converter 失败测试**

```python
from g1_agent_msgs.msg import RobotStateSummary, VoiceEvent
from g1_interface.internal_types import LowStateSummary
from g1_interface.ros_converters import native_audio_event, robot_state_summary


def test_native_asr_json_becomes_voice_event():
    msg = native_audio_event('{"index": 7, "text": "停止", "confidence": 0.8, "is_final": true}', 10.0)
    assert isinstance(msg, VoiceEvent)
    assert msg.event_type == VoiceEvent.EVENT_ASR
    assert msg.sequence_id == 7
    assert msg.text == "停止"


def test_native_play_state_becomes_playback_event():
    msg = native_audio_event('{"play_state": 1}', 10.0)
    assert msg.event_type == VoiceEvent.EVENT_PLAYBACK
    assert msg.playback_state == VoiceEvent.PLAYBACK_PLAYING


def test_summary_preserves_official_lowstate_fields():
    lowstate_summary = LowStateSummary(
        source="lowstate", rpy=[0.0, 0.0, 0.0], quaternion=[1.0, 0.0, 0.0, 0.0],
        gyroscope=[0.0, 0.0, 0.1], accelerometer=[0.0, 0.0, 9.8],
        motor_count=35, max_temperature_c=42.0, motors=[],
    )
    msg = robot_state_summary(
        lowstate_summary, 10.0, "lowstate", "sport_api_loco", "internal",
        "sport_api.get_fsm_mode", {"vx": 0.1, "vy": 0.0, "vyaw": 0.2}, 2, 0,
    )
    assert isinstance(msg, RobotStateSummary)
    assert msg.motor_count == 35
    assert msg.orientation.w == 1.0
    assert msg.velocity.linear.x == 0.1
```

- [ ] **Step 2: 运行 converter tests 并确认失败**

Run: `source install/setup.bash && PYTHONNOUSERSITE=1 PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 .venv-ros/bin/python -m pytest -q src/g1_interface/tests/test_ros_converters.py`

Expected: FAIL because `g1_interface.ros_converters` does not exist.

- [ ] **Step 3: 实现官方底层消息到项目摘要的转换**

Create `ros_converters.py`:

```python
from __future__ import annotations

import json
import math

from builtin_interfaces.msg import Time
from g1_agent_msgs.msg import RobotStateSummary, VoiceEvent
from g1_interface.internal_types import LowStateSummary


def _time_from_sec(value: float) -> Time:
    sec = math.floor(value)
    return Time(sec=sec, nanosec=int((value - sec) * 1_000_000_000))


def native_audio_event(raw_text: str, stamp_sec: float) -> VoiceEvent | None:
    text = raw_text.strip()
    if not text:
        return None
    try:
        payload = json.loads(text)
    except json.JSONDecodeError:
        if text.startswith(("{", "[")):
            return None
        payload = {"text": text}
    if not isinstance(payload, dict):
        return None

    event_text = payload.get("text")
    if isinstance(event_text, str) and event_text.strip():
        msg = VoiceEvent(
            stamp=_time_from_sec(stamp_sec), source=str(payload.get("source", "builtin_asr")),
            event_type=VoiceEvent.EVENT_ASR, text=event_text.strip(),
            is_final=bool(payload.get("is_final", True)), language=str(payload.get("language", "")),
        )
        index = payload.get("index")
        if isinstance(index, int) and index >= 0:
            msg.has_sequence_id = True
            msg.sequence_id = index
        confidence = payload.get("confidence")
        if not isinstance(confidence, bool) and isinstance(confidence, (int, float)) and math.isfinite(float(confidence)) and 0.0 <= confidence <= 1.0:
            msg.has_confidence = True
            msg.confidence = float(confidence)
        return msg

    play_state = payload.get("play_state")
    if not isinstance(play_state, bool) and play_state in {0, 1}:
        return VoiceEvent(
            stamp=_time_from_sec(stamp_sec), source="builtin_audio",
            event_type=VoiceEvent.EVENT_PLAYBACK, has_playback_state=True,
            playback_state=VoiceEvent.PLAYBACK_PLAYING if play_state == 1 else VoiceEvent.PLAYBACK_STOPPED,
        )
    return None


def robot_state_summary(summary: LowStateSummary, stamp_sec: float, source: str,
                        mode: str | None, control_owner: str, mode_source: str,
                        velocity: dict[str, float], sport_fsm_mode: int | None,
                        sport_fsm_id: int | None) -> RobotStateSummary:
    msg = RobotStateSummary(
        stamp=_time_from_sec(stamp_sec), source=source,
        mode=mode or RobotStateSummary.MODE_UNKNOWN,
        control_owner=control_owner or RobotStateSummary.OWNER_UNKNOWN,
        mode_source=mode_source, motor_count=summary.motor_count,
        velocity_source="last_sport_command", health_state=RobotStateSummary.HEALTH_UNKNOWN,
    )
    msg.has_sport_fsm_mode = sport_fsm_mode is not None
    msg.sport_fsm_mode = int(sport_fsm_mode or 0)
    msg.has_sport_fsm_id = sport_fsm_id is not None
    msg.sport_fsm_id = int(sport_fsm_id or 0)
    msg.rpy.x, msg.rpy.y, msg.rpy.z = map(float, summary.rpy)
    msg.orientation.w, msg.orientation.x, msg.orientation.y, msg.orientation.z = map(float, summary.quaternion)
    msg.angular_velocity.x, msg.angular_velocity.y, msg.angular_velocity.z = map(float, summary.gyroscope)
    msg.linear_acceleration.x, msg.linear_acceleration.y, msg.linear_acceleration.z = map(float, summary.accelerometer)
    msg.has_max_temperature = summary.max_temperature_c is not None
    msg.max_temperature_c = float(summary.max_temperature_c or 0.0)
    msg.has_battery_voltage = False
    msg.velocity.linear.x = float(velocity.get("vx", 0.0))
    msg.velocity.linear.y = float(velocity.get("vy", 0.0))
    msg.velocity.angular.z = float(velocity.get("vyaw", 0.0))
    return msg
```

`native_audio_event` accepts plain text as built-in ASR, maps valid ASR JSON and `play_state`, and returns `None` for empty, malformed, non-object, or unsupported events. `robot_state_summary` maps official `unitree_hg/IMUState` arrays through the existing `LowStateSummary`, uses `has_*` flags for optional FSM/temperature/battery values, and writes velocity to `Twist.linear.x/y` and `Twist.angular.z`.

- [ ] **Step 4: 迁移 publishers 和 diagnostics**

Load `RobotStateSummary` and `VoiceEvent`; create low/mode/audio publishers with those types. Replace `build_low_state_payload`, `build_mode_payload`, and `normalize_audio_asr_message` with converter calls. Keep `/g1/state/motors` as `String` and keep native `/audio_msg` subscription as `String`.

Preserve ASR source selection exactly:

```python
event = native_audio_event(msg.data, self._now_sec())
if event is None:
    self.invalid_audio_event_count += 1
    return
if event.event_type == VoiceEvent.EVENT_ASR:
    if should_forward_native_asr(self.config.asr["source_mode"]):
        self.asr_pub.publish(event)
    return
self.audio_event_pub.publish(event)
```

Add `self.invalid_audio_event_count = 0`; increment it when `native_audio_event` returns `None`, and publish `invalid_audio_event_count` in health diagnostics.

Add `<exec_depend>builtin_interfaces</exec_depend>` and `<exec_depend>g1_agent_msgs</exec_depend>`; retain `std_msgs` because native audio and motor monitoring remain strings.

- [ ] **Step 5: 运行 g1_interface state/audio tests**

Run: `source install/setup.bash && PYTHONNOUSERSITE=1 PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 .venv-ros/bin/python -m pytest -q src/g1_interface/tests/test_converters.py src/g1_interface/tests/test_ros_converters.py src/g1_interface/tests/test_node_helpers.py src/g1_interface/tests/test_asr_bridge_node.py`

Expected: tests pass with typed low/mode/asr/audio publishers and unchanged watchdog assertions.

- [ ] **Step 6: Commit**

```bash
git add src/g1_interface
git commit -m "feat: publish typed robot and audio summaries"
```

---

### Task 6: 将 safety_control 的状态追踪和验证器改为强类型输入

**Files:**
- Modify: `src/safety_control/safety_control/internal_types.py`
- Modify: `src/safety_control/safety_control/state.py`
- Modify: `src/safety_control/safety_control/validator.py`
- Modify: `src/safety_control/package.xml`
- Modify: `src/safety_control/tests/test_state.py`
- Modify: `src/safety_control/tests/test_validator.py`

**Interfaces:**
- Consumes: `LocoIntent`, `ActionIntent`, `RobotStateSummary`, `DiagnosticArray`.
- Produces: internal `ValidationResult` and `RobotStateSnapshot`; no JSON parsing APIs remain.

- [ ] **Step 1: 将 validator tests 改为构造生成消息**

Use helpers:

```python
from builtin_interfaces.msg import Duration, Time
from g1_agent_msgs.msg import ActionIntent, LocoIntent, RobotStateSummary


def loco_intent(**overrides):
    values = dict(
        created_at=Time(sec=9, nanosec=950_000_000), source="voice_bridge",
        session_id="s1", command_id="c1", text="forward", vx=0.2, vy=0.0,
        vyaw=0.0, duration=Duration(sec=1),
    )
    values.update(overrides)
    return LocoIntent(**values)


def stop_intent(action="stop"):
    return ActionIntent(
        created_at=Time(sec=10), command_id="stop1", action=action,
        priority=ActionIntent.PRIORITY_EMERGENCY,
    )
```

Change state tests to construct a concrete summary:

```python
summary = RobotStateSummary(
    stamp=Time(sec=10), mode=RobotStateSummary.MODE_SPORT_API_LOCO,
    motor_count=35, has_max_temperature=True, max_temperature_c=42.5,
)
summary.velocity.linear.x = 0.1
summary.velocity.angular.z = 0.2
tracker.update_from_summary(summary, now_sec=10.0)
snapshot = tracker.get_snapshot(10.05)
assert snapshot.motor_count == 35
assert snapshot.max_temperature == 42.5
assert snapshot.current_velocity == {"vx": 0.1, "vy": 0.0, "vyaw": 0.2}
```

- [ ] **Step 2: 运行 state/validator tests 并确认失败**

Run: `source install/setup.bash && PYTHONNOUSERSITE=1 PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 .venv-ros/bin/python -m pytest -q src/safety_control/tests/test_state.py src/safety_control/tests/test_validator.py`

Expected: FAIL because production functions still expect JSON strings.

- [ ] **Step 3: 精简内部类型并直接验证 ROS 消息**

Rename the internal `SafetyDecision` dataclass to `ValidationResult`; retain `RobotStateSnapshot`. Remove internal `LocoIntent`, `ActionIntent`, and `ValidatedCommand` dataclasses.

Replace JSON parsers with:

```python
def time_to_sec(value) -> float | None:
    if value.sec == 0 and value.nanosec == 0:
        return None
    return float(value.sec) + float(value.nanosec) / 1_000_000_000.0


def duration_to_sec(value) -> float:
    return float(value.sec) + float(value.nanosec) / 1_000_000_000.0


def validate_intent_shape(intent: LocoIntent) -> None:
    if not intent.command_id.strip():
        raise ValueError("command_id must be non-empty")
    for name in ("vx", "vy", "vyaw"):
        if not math.isfinite(float(getattr(intent, name))):
            raise ValueError(f"{name} must be finite")
    if not math.isfinite(duration_to_sec(intent.duration)):
        raise ValueError("duration must be finite")


def validate_action_shape(intent: ActionIntent) -> None:
    if not intent.command_id.strip():
        raise ValueError("command_id must be non-empty")
    if not intent.action.strip():
        raise ValueError("action must be non-empty")
```

`SafetyValidator.validate_loco` calls `validate_intent_shape` and accepts `LocoIntent`; `validate_action` calls `validate_action_shape` and accepts `ActionIntent`. Use `duration_to_sec(intent.duration)` for limits and `time_to_sec(intent.created_at)` for freshness. Empty IDs are rejected instead of synthesized.

`RobotStateTracker.update_from_summary` reads `msg.stamp`, `msg.mode`, `msg.velocity`, `motor_count`, and optional fields. Mode aliases remain normalized for inputs from hardware-derived summaries.

Add `<exec_depend>builtin_interfaces</exec_depend>` and `<exec_depend>g1_agent_msgs</exec_depend>` to `package.xml` so colcon orders the generated interfaces before safety Python modules.

- [ ] **Step 4: 运行 pure safety tests**

Run: `source install/setup.bash && PYTHONNOUSERSITE=1 PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 .venv-ros/bin/python -m pytest -q src/safety_control/tests/test_state.py src/safety_control/tests/test_validator.py`

Expected: all state and validator tests pass, including unconditional stop/cancel.

- [ ] **Step 5: Commit**

```bash
git add src/safety_control/package.xml src/safety_control/safety_control/internal_types.py src/safety_control/safety_control/state.py src/safety_control/safety_control/validator.py src/safety_control/tests/test_state.py src/safety_control/tests/test_validator.py
git commit -m "refactor: validate typed safety inputs"
```

---

### Task 7: 将 SafetyControlNode 输出迁移为强类型命令和状态

**Files:**
- Create: `src/safety_control/safety_control/ros_converters.py`
- Create: `src/safety_control/tests/test_node.py`
- Create: `src/safety_control/tests/conftest.py`
- Modify: `src/safety_control/package.xml`
- Modify: `src/safety_control/safety_control/node.py`

**Interfaces:**
- Consumes: typed intents and robot summaries plus health diagnostics.
- Produces: `ValidatedLocoCommand`, `ValidatedActionCommand`, `SafetyDecision`, `SafetyStatus`.

- [ ] **Step 1: 写节点 wiring 和发布失败测试**

Create `tests/conftest.py` with real generated messages and only fake rclpy node mechanics:

```python
from types import SimpleNamespace

import pytest
from builtin_interfaces.msg import Duration, Time
from diagnostic_msgs.msg import DiagnosticArray, DiagnosticStatus
from g1_agent_msgs.msg import ActionIntent, LocoIntent, RobotStateSummary

from safety_control.config import SafetyControlConfig
from safety_control.node import SafetyControlNode


class FakePublisher:
    def __init__(self):
        self.messages = []
    def publish(self, msg):
        self.messages.append(msg)


class FakeNow:
    nanoseconds = 10_000_000_000
    def to_msg(self):
        return Time(sec=10)


class FakeClock:
    def now(self):
        return FakeNow()


class FakeLogger:
    def warning(self, message):
        self.last_warning = message


class FakeNode:
    def __init__(self):
        self.publishers = {}
        self.subscriptions = []
    def create_publisher(self, msg_type, topic, depth):
        self.publishers[topic] = FakePublisher()
        return self.publishers[topic]
    def create_subscription(self, msg_type, topic, callback, depth):
        self.subscriptions.append((msg_type, topic, callback))
    def create_timer(self, period, callback):
        return (period, callback)
    def get_clock(self):
        return FakeClock()
    def get_logger(self):
        return FakeLogger()


@pytest.fixture
def bridge_node():
    node = FakeNode()
    return SimpleNamespace(node=node, bridge=SafetyControlNode(node, SafetyControlConfig.default()),
                           publishers=node.publishers)


@pytest.fixture
def ready_node(bridge_node):
    summary = RobotStateSummary(
        stamp=Time(sec=10), mode=RobotStateSummary.MODE_SPORT_API_LOCO,
        motor_count=35, has_max_temperature=True, max_temperature_c=40.0,
    )
    bridge_node.bridge.on_lowstate(summary)
    bridge_node.bridge.on_robot_mode(summary)
    health = DiagnosticArray()
    status = DiagnosticStatus()
    status.level = DiagnosticStatus.OK
    status.message = "ok"
    health.status.append(status)
    bridge_node.bridge.on_health(health)
    return bridge_node


@pytest.fixture
def loco_msg():
    return LocoIntent(
        created_at=Time(sec=9, nanosec=950_000_000), source="voice_bridge",
        session_id="s1", command_id="c1", text="向前", vx=0.2, vy=0.0,
        vyaw=0.0, duration=Duration(sec=1),
    )


@pytest.fixture
def stop_msg():
    return ActionIntent(
        created_at=Time(sec=10), source="voice_bridge", session_id="s1",
        command_id="stop1", text="停止", action=ActionIntent.ACTION_STOP,
        priority=ActionIntent.PRIORITY_EMERGENCY,
    )
```

Create `tests/test_node.py`:

```python
def test_allowed_loco_publishes_validated_command_and_decision(ready_node, loco_msg):
    ready_node.bridge.on_loco_intent(loco_msg)
    safe = ready_node.publishers["/g1/safe_cmd/loco"].messages[-1]
    audit = ready_node.publishers["/g1/safety/decisions"].messages[-1]
    assert safe.intent.command_id == loco_msg.command_id
    assert safe.validation.decision == safe.validation.DECISION_ALLOW
    assert audit.command_kind == audit.KIND_LOCO


def test_stop_publishes_validated_action_without_robot_state(bridge_node, stop_msg):
    bridge_node.bridge.on_action_intent(stop_msg)
    safe = bridge_node.publishers["/g1/safe_cmd/stop"].messages[-1]
    assert safe.intent.action == "stop"
    assert safe.validation.decision == safe.validation.DECISION_ALLOW


def test_safety_status_is_typed_heartbeat(ready_node):
    ready_node.bridge.publish_safety_state()
    status = ready_node.publishers["/g1/state/safety"].messages[-1]
    assert status.node_name == "safety_control"
    assert status.enabled is True
```

- [ ] **Step 2: 运行 node tests 并确认失败**

Run: `source install/setup.bash && PYTHONNOUSERSITE=1 PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 .venv-ros/bin/python -m pytest -q src/safety_control/tests/test_node.py`

Expected: FAIL because the node still wires and publishes `String`.

- [ ] **Step 3: 实现 safety ROS converters**

Create `ros_converters.py`:

```python
from __future__ import annotations

import math

from builtin_interfaces.msg import Duration, Time
from g1_agent_msgs.msg import (
    ActionIntent, LocoIntent, RobotStateSummary, SafetyDecision, SafetyStatus,
    ValidatedActionCommand, ValidatedLocoCommand,
)
from safety_control.internal_types import RobotStateSnapshot, ValidationResult


def _time(value: float) -> Time:
    sec = math.floor(value)
    return Time(sec=sec, nanosec=int((value - sec) * 1_000_000_000))


def _duration(value: float) -> Duration:
    sec = math.floor(max(0.0, value))
    return Duration(sec=sec, nanosec=int((max(0.0, value) - sec) * 1_000_000_000))


def snapshot_msg(snapshot: RobotStateSnapshot) -> RobotStateSummary:
    msg = RobotStateSummary(
        stamp=_time(snapshot.timestamp), source="safety_control",
        mode=snapshot.mode or RobotStateSummary.MODE_UNKNOWN,
        control_owner=RobotStateSummary.OWNER_UNKNOWN,
        health_state=snapshot.health_state, motor_count=snapshot.motor_count,
    )
    msg.velocity.linear.x = float(snapshot.current_velocity["vx"])
    msg.velocity.linear.y = float(snapshot.current_velocity["vy"])
    msg.velocity.angular.z = float(snapshot.current_velocity["vyaw"])
    msg.has_max_temperature = snapshot.max_temperature is not None
    msg.max_temperature_c = float(snapshot.max_temperature or 0.0)
    msg.has_battery_voltage = snapshot.battery_voltage is not None
    msg.battery_voltage = float(snapshot.battery_voltage or 0.0)
    msg.has_lowstate_age = snapshot.lowstate_age_ms is not None
    msg.lowstate_age = _duration(float(snapshot.lowstate_age_ms or 0) / 1000.0)
    return msg


def decision_msg(command_id: str, command_kind: str, result: ValidationResult,
                 snapshot: RobotStateSnapshot, stamp_sec: float,
                 latency_sec: float) -> SafetyDecision:
    return SafetyDecision(
        stamp=_time(stamp_sec), command_id=command_id, command_kind=command_kind,
        decision=SafetyDecision.DECISION_ALLOW if result.allowed else SafetyDecision.DECISION_REJECT,
        reason=result.reason or "", validation_latency=_duration(latency_sec),
        robot_state=snapshot_msg(snapshot),
    )


def validated_loco_msg(intent: LocoIntent, decision: SafetyDecision) -> ValidatedLocoCommand:
    return ValidatedLocoCommand(intent=intent, validated_at=decision.stamp, validation=decision)


def validated_action_msg(intent: ActionIntent, decision: SafetyDecision) -> ValidatedActionCommand:
    return ValidatedActionCommand(intent=intent, validated_at=decision.stamp, validation=decision)


def safety_status_msg(enabled: bool, strict_mode: bool, snapshot: RobotStateSnapshot,
                      allow_count: int, reject_count: int,
                      last_rejection_reason: str | None,
                      last_decision: SafetyDecision | None,
                      stamp_sec: float) -> SafetyStatus:
    total = allow_count + reject_count
    msg = SafetyStatus(
        stamp=_time(stamp_sec), node_name="safety_control", enabled=enabled,
        strict_mode=strict_mode, robot_state=snapshot_msg(snapshot),
        allow_count=allow_count, reject_count=reject_count,
        rejection_rate=(reject_count / total) if total else 0.0,
        last_rejection_reason=last_rejection_reason or "",
        has_last_decision=last_decision is not None,
    )
    if last_decision is not None:
        msg.last_decision = last_decision
    return msg
```

The validated message uses the same decision instance and copies its stamp into `validated_at`. `SafetyStatus.has_last_decision` is false until the first decision.

- [ ] **Step 4: Rewire SafetyControlNode**

Load all generated classes and `DiagnosticArray`; remove `std_msgs`, `_json`, `_publish_string`, and JSON exception handling. Subscribe to typed inputs, call Task 6 validators, publish Task 7 converter outputs, and retain `check_details` only in diagnostics/debug logging.

Change `self.last_decision` from a dictionary to `SafetyDecision | None`; `_record_and_publish_decision` builds one message, stores it, and publishes that same message when audit policy allows. Log `ValidationResult.check_details` with the rejection warning, but do not add it to a core ROS message.

Add `<exec_depend>g1_agent_msgs</exec_depend>` and remove `<exec_depend>std_msgs</exec_depend>` from `package.xml`.

- [ ] **Step 5: 运行 safety_control 全量 tests**

Run: `source install/setup.bash && PYTHONNOUSERSITE=1 PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 .venv-ros/bin/python -m pytest -q src/safety_control/tests`

Expected: all tests pass.

- [ ] **Step 6: Commit**

```bash
git add src/safety_control
git commit -m "feat: publish typed safety decisions and commands"
```

---

### Task 8: 将 g1_interface 安全心跳和执行命令订阅迁移为强类型消息

**Files:**
- Modify: `src/g1_interface/g1_interface/ros_converters.py`
- Modify: `src/g1_interface/g1_interface/node.py`
- Modify: `src/g1_interface/tests/test_ros_converters.py`
- Modify: `src/g1_interface/tests/test_node_helpers.py`
- Modify: `src/g1_interface/tests/test_asr_bridge_node.py`

**Interfaces:**
- Consumes: `SafetyStatus`, `ValidatedLocoCommand`, `ValidatedActionCommand`.
- Produces: unchanged official `unitree_api/Request` Sport commands.

- [ ] **Step 1: 写 validated command 失败测试**

```python
from builtin_interfaces.msg import Duration, Time
from g1_agent_msgs.msg import (
    ActionIntent, LocoIntent, SafetyDecision, ValidatedActionCommand, ValidatedLocoCommand,
)


def _validated_loco():
    intent = LocoIntent(command_id="c1", vx=0.2, vy=0.0, vyaw=0.1, duration=Duration(sec=1))
    decision = SafetyDecision(command_id="c1", command_kind=SafetyDecision.KIND_LOCO,
                              decision=SafetyDecision.DECISION_ALLOW)
    return ValidatedLocoCommand(intent=intent, validated_at=Time(sec=10), validation=decision)


def _validated_stop():
    intent = ActionIntent(command_id="stop1", action=ActionIntent.ACTION_STOP,
                          priority=ActionIntent.PRIORITY_EMERGENCY)
    decision = SafetyDecision(command_id="stop1", command_kind=SafetyDecision.KIND_ACTION,
                              decision=SafetyDecision.DECISION_ALLOW)
    return ValidatedActionCommand(intent=intent, validated_at=Time(sec=10), validation=decision)


def test_validated_loco_becomes_sport_command():
    validated_loco = _validated_loco()
    command = sport_command_from_loco(validated_loco)
    assert command.action == "set_velocity"
    assert command.params == {"velocity": [0.2, 0.0, 0.1], "duration": 1.0}


def test_mismatched_or_rejected_validation_is_refused():
    validated_loco = _validated_loco()
    validated_loco.validation.command_id = "different"
    with pytest.raises(ValueError, match="command_id mismatch"):
        sport_command_from_loco(validated_loco)

    validated_loco.validation.command_id = validated_loco.intent.command_id
    validated_loco.validation.decision = validated_loco.validation.DECISION_REJECT
    with pytest.raises(ValueError, match="not allowed"):
        sport_command_from_loco(validated_loco)


def test_validated_stop_always_builds_zero_velocity():
    validated_stop = _validated_stop()
    assert sport_command_from_action(validated_stop).params["velocity"] == [0.0, 0.0, 0.0]
```

Update node tests to pass generated `SafetyStatus` and validated command objects instead of `_string_msg(JSON)`.

- [ ] **Step 2: 运行 command tests 并确认失败**

Run: `source install/setup.bash && PYTHONNOUSERSITE=1 PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 .venv-ros/bin/python -m pytest -q src/g1_interface/tests/test_ros_converters.py src/g1_interface/tests/test_node_helpers.py src/g1_interface/tests/test_asr_bridge_node.py`

Expected: FAIL because callbacks still parse `msg.data`.

- [ ] **Step 3: 实现 typed command conversion**

Add:

```python
def _require_allow(command_id: str, command_kind: str, validation) -> None:
    if validation.command_id != command_id:
        raise ValueError("validation command_id mismatch")
    if validation.command_kind != command_kind:
        raise ValueError("validation command_kind mismatch")
    if validation.decision != validation.DECISION_ALLOW:
        raise ValueError("command not allowed by safety validation")


def sport_command_from_loco(msg: ValidatedLocoCommand) -> SportCommand:
    _require_allow(msg.intent.command_id, msg.validation.KIND_LOCO, msg.validation)
    duration = duration_to_sec(msg.intent.duration)
    values = [
        _bounded(float(msg.intent.vx), "vx", -0.5, 0.5),
        _bounded(float(msg.intent.vy), "vy", -0.3, 0.3),
        _bounded(float(msg.intent.vyaw), "vyaw", -0.8, 0.8),
    ]
    duration = _bounded(duration, "duration", 0.01, 2.0)
    return SportCommand(action="set_velocity", params={"velocity": values, "duration": duration})


def sport_command_from_action(msg: ValidatedActionCommand) -> SportCommand:
    _require_allow(msg.intent.command_id, msg.validation.KIND_ACTION, msg.validation)
    if msg.intent.action not in {msg.intent.ACTION_STOP, msg.intent.ACTION_CANCEL}:
        raise ValueError(f"safe_stop action must be stop or cancel: {msg.intent.action}")
    return SportCommand(action="set_velocity", params={"velocity": [0.0, 0.0, 0.0], "duration": 0.1})
```

Add the bounded helper:

```python
def _bounded(value: float, field: str, low: float, high: float) -> float:
    if not math.isfinite(value):
        raise ValueError(f"{field} non-finite")
    if value < low or value > high:
        raise ValueError(f"{field} out of range")
    return value
```

- [ ] **Step 4: Rewire callbacks without changing watchdog semantics**

Create subscriptions with generated types. `on_safety_state` accepts a heartbeat only when `msg.node_name == "safety_control"` and updates `last_safety_heartbeat_monotonic_sec`. `on_safe_loco` uses `sport_command_from_loco` and still applies `check_sport_command_allowed`; `on_safe_stop` uses `sport_command_from_action` and bypasses those gates.

Do not change `_publish_velocity_command`, `_publish_stop_request`, acknowledgement tracking, deadline handling, or shutdown order.

- [ ] **Step 5: 运行 g1_interface 全量 tests**

Run: `source install/setup.bash && PYTHONNOUSERSITE=1 PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 .venv-ros/bin/python -m pytest -q src/g1_interface/tests`

Expected: all tests pass, including stale-state stop, heartbeat loss, API timeout, deadline and shutdown cases.

- [ ] **Step 6: Commit**

```bash
git add src/g1_interface
git commit -m "feat: execute typed validated commands"
```

---

### Task 9: 将 voice_bridge_debug ROS adapter 迁移为强类型消息

**Files:**
- Create: `src/voice_bridge_debug/voice_bridge_debug/ros_converters.py`
- Create: `src/voice_bridge_debug/tests/test_ros_converters.py`
- Modify: `src/voice_bridge_debug/package.xml`
- Modify: `src/voice_bridge_debug/setup.py`
- Modify: `src/voice_bridge_debug/voice_bridge_debug/ros_node.py`
- Modify: `src/voice_bridge_debug/tests/test_ros_node.py`
- Modify: `src/voice_bridge_debug/frontend/src/types/index.ts`
- Modify: `src/voice_bridge_debug/frontend/vite.config.ts`

**Interfaces:**
- Consumes: all typed core messages.
- Produces: plain dictionaries for `PanelState` and JSON WebSocket messages; publishes typed debug `VoiceEvent`.

- [ ] **Step 1: 写 ROS-to-web converter 失败测试**

```python
def test_safety_status_to_dict_preserves_nested_decision():
    msg = SafetyStatus(node_name="safety_control", enabled=True, strict_mode=True)
    msg.robot_state.mode = "sport_api_loco"
    msg.has_last_decision = True
    msg.last_decision.command_id = "c1"
    data = safety_status_to_dict(msg)
    assert data["enabled"] is True
    assert data["robot_state"]["mode"] == "sport_api_loco"
    assert data["last_decision"]["command_id"] == "c1"


def test_debug_asr_queue_publishes_voice_event(monkeypatch):
    messages = []
    q = queue.Queue()
    q.put({"text": "小宇向前", "confidence": 0.9, "is_final": True, "source": "debug"})
    node = FakeNode()
    bridge = DebugBridgeNode(node, DebugPanelConfig.default(), PanelState(), q, messages.append)
    bridge.drain_asr_queue()
    msg = node.publishers["/g1/audio/asr"].messages[-1]
    assert msg.event_type == msg.EVENT_ASR
    assert msg.text == "小宇向前"
```

This test lives in the existing `test_ros_node.py` and reuses its `FakeNode`; update `FakePublisher.publish` to store the message object instead of `msg.data`, and add `FakeClockNow.to_msg()`.

- [ ] **Step 2: 运行 debug adapter tests 并确认失败**

Run: `source install/setup.bash && PYTHONNOUSERSITE=1 PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 .venv-ros/bin/python -m pytest -q src/voice_bridge_debug/tests/test_ros_converters.py src/voice_bridge_debug/tests/test_ros_node.py`

Expected: FAIL because all callbacks still assume `.data` JSON.

- [ ] **Step 3: 实现显式 web dictionary converters**

Create explicit JSON-safe converters:

```python
from __future__ import annotations

from typing import Any

from g1_agent_msgs.msg import (
    ActionIntent, LocoIntent, RobotStateSummary, SafetyDecision, SafetyStatus,
    ValidatedActionCommand, ValidatedLocoCommand, VoiceEvent,
)


def _time(msg) -> float:
    return float(msg.sec) + float(msg.nanosec) / 1_000_000_000.0


def _duration(msg) -> float:
    return float(msg.sec) + float(msg.nanosec) / 1_000_000_000.0


def voice_event_to_dict(msg: VoiceEvent) -> dict[str, Any]:
    return {
        "stamp": _time(msg.stamp), "source": msg.source, "event_type": msg.event_type,
        "sequence_id": msg.sequence_id if msg.has_sequence_id else None,
        "text": msg.text, "confidence": msg.confidence if msg.has_confidence else None,
        "is_final": msg.is_final, "language": msg.language,
        "playback_state": msg.playback_state if msg.has_playback_state else None,
    }


def loco_intent_to_dict(msg: LocoIntent) -> dict[str, Any]:
    return {
        "created_at": _time(msg.created_at), "source": msg.source,
        "session_id": msg.session_id, "command_id": msg.command_id, "text": msg.text,
        "vx": msg.vx, "vy": msg.vy, "vyaw": msg.vyaw,
        "duration_sec": _duration(msg.duration),
    }


def action_intent_to_dict(msg: ActionIntent) -> dict[str, Any]:
    return {
        "created_at": _time(msg.created_at), "source": msg.source,
        "session_id": msg.session_id, "command_id": msg.command_id, "text": msg.text,
        "action": msg.action, "priority": msg.priority,
    }


def robot_state_to_dict(msg: RobotStateSummary) -> dict[str, Any]:
    return {
        "stamp": _time(msg.stamp), "source": msg.source, "mode": msg.mode,
        "control_owner": msg.control_owner, "mode_source": msg.mode_source,
        "sport_fsm_mode": msg.sport_fsm_mode if msg.has_sport_fsm_mode else None,
        "sport_fsm_id": msg.sport_fsm_id if msg.has_sport_fsm_id else None,
        "rpy": [msg.rpy.x, msg.rpy.y, msg.rpy.z],
        "quaternion": [msg.orientation.w, msg.orientation.x, msg.orientation.y, msg.orientation.z],
        "motor_count": msg.motor_count,
        "max_temperature_c": msg.max_temperature_c if msg.has_max_temperature else None,
        "battery_voltage": msg.battery_voltage if msg.has_battery_voltage else None,
        "velocity": {"vx": msg.velocity.linear.x, "vy": msg.velocity.linear.y, "vyaw": msg.velocity.angular.z},
        "velocity_source": msg.velocity_source, "health_state": msg.health_state,
        "lowstate_age_sec": _duration(msg.lowstate_age) if msg.has_lowstate_age else None,
    }


def safety_decision_to_dict(msg: SafetyDecision) -> dict[str, Any]:
    return {
        "timestamp": _time(msg.stamp), "command_id": msg.command_id,
        "command_kind": msg.command_kind, "decision": msg.decision,
        "reason": msg.reason or None, "validation_time_sec": _duration(msg.validation_latency),
        "robot_state": robot_state_to_dict(msg.robot_state),
    }


def validated_loco_to_dict(msg: ValidatedLocoCommand) -> dict[str, Any]:
    return {"intent": loco_intent_to_dict(msg.intent), "validated_at": _time(msg.validated_at),
            "validation": safety_decision_to_dict(msg.validation)}


def validated_action_to_dict(msg: ValidatedActionCommand) -> dict[str, Any]:
    return {"intent": action_intent_to_dict(msg.intent), "validated_at": _time(msg.validated_at),
            "validation": safety_decision_to_dict(msg.validation)}


def safety_status_to_dict(msg: SafetyStatus) -> dict[str, Any]:
    return {
        "timestamp": _time(msg.stamp), "node": msg.node_name, "enabled": msg.enabled,
        "strict_mode": msg.strict_mode, "robot_state": robot_state_to_dict(msg.robot_state),
        "allow_count": msg.allow_count, "reject_count": msg.reject_count,
        "rejection_rate": msg.rejection_rate,
        "last_rejection_reason": msg.last_rejection_reason or None,
        "last_decision": safety_decision_to_dict(msg.last_decision) if msg.has_last_decision else None,
    }
```

- [ ] **Step 4: Rewire debug ROS subscriptions and frontend types**

Subscribe with typed classes for migrated topics; keep `String` only for `/voice/state`, `/voice/debug/events`, TTS and LED. Replace `on_string_event` calls on typed topics with converter-specific callbacks. `drain_asr_queue` creates `VoiceEvent` and stamps it with `node.get_clock().now().to_msg()`.

Change frontend types so `RobotModeState = RobotModeFields` and `SafetyState = SafetyFields`; remove the `ParsedTopicState` wrapper for typed mode and safety state. Existing JSON debug views remain valid.

Set Vite output:

```ts
build: {
  outDir: "../voice_bridge_debug/frontend_dist",
  emptyOutDir: true,
},
```

Add `<exec_depend>g1_agent_msgs</exec_depend>`; retain `std_msgs` for remaining debug topics.

Make the debug panel runtime and test extra explicit in `setup.py`:

```python
install_requires=[
    "setuptools", "PyYAML==6.0.3", "fastapi==0.115.12",
    "starlette==0.46.2", "uvicorn[standard]==0.34.3",
],
extras_require={
    "test": ["pytest==8.3.5", "httpx==0.28.1"],
},
```

- [ ] **Step 5: 运行 debug backend 和 frontend tests**

Run: `source install/setup.bash && PYTHONNOUSERSITE=1 PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 .venv-ros/bin/python -m pytest -q src/voice_bridge_debug/tests`

Expected: all backend tests pass, including FastAPI TestClient routes.

Run: `npm --prefix src/voice_bridge_debug/frontend ci && npm --prefix src/voice_bridge_debug/frontend run build`

Expected: TypeScript and Vite build succeed and write `frontend_dist`.

- [ ] **Step 6: Commit**

```bash
git add src/voice_bridge_debug
git commit -m "feat: adapt typed ROS messages for debug panel"
```

---

### Task 10: 添加强类型核心链路 launch_testing smoke test

**Files:**
- Create: `src/g1_system_tests/CMakeLists.txt`
- Create: `src/g1_system_tests/package.xml`
- Create: `src/g1_system_tests/config/voice_bridge_test.yaml`
- Create: `src/g1_system_tests/test/test_typed_control_chain.py`

**Interfaces:**
- Consumes: installed `g1_sim`, `g1_interface`, `safety_control`, `voice_bridge`, `g1_agent_msgs`.
- Produces: an end-to-end proof that typed ASR yields nonzero Sport velocity and typed stop yields zero velocity.

- [ ] **Step 1: 写 launch test 并确认包不存在**

Create `test/test_typed_control_chain.py`:

```python
import json
import time
import unittest

import launch
import launch_ros.actions
import launch_testing.actions
import rclpy
from ament_index_python.packages import get_package_share_directory
from diagnostic_msgs.msg import DiagnosticArray
from g1_agent_msgs.msg import (
    LocoIntent, SafetyStatus, ValidatedActionCommand, ValidatedLocoCommand, VoiceEvent,
)
from unitree_api.msg import Request


def generate_test_description():
    config = get_package_share_directory("g1_system_tests") + "/config/voice_bridge_test.yaml"
    nodes = [
        launch_ros.actions.Node(package="g1_sim", executable="g1_sim_node", output="screen"),
        launch_ros.actions.Node(package="g1_interface", executable="g1_interface_node", output="screen"),
        launch_ros.actions.Node(package="safety_control", executable="safety_control_node", output="screen"),
        launch_ros.actions.Node(
            package="voice_bridge", executable="voice_bridge_node", output="screen",
            parameters=[{"config_path": config}],
        ),
    ]
    return launch.LaunchDescription(nodes + [launch_testing.actions.ReadyToTest()])


def _velocity(request):
    if request.header.identity.api_id != 7105:
        return None
    payload = json.loads(request.parameter)
    value = payload.get("velocity")
    return value if isinstance(value, list) and len(value) == 3 else None


class TestTypedControlChain(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        rclpy.init()
        cls.node = rclpy.create_node("typed_control_chain_test")
        cls.asr_pub = cls.node.create_publisher(VoiceEvent, "/g1/audio/asr", 10)
        cls.loco = []
        cls.safe_loco = []
        cls.safe_stop = []
        cls.sport = []
        cls.health = []
        cls.safety = []
        cls.node.create_subscription(LocoIntent, "/voice/cmd/loco", cls.loco.append, 10)
        cls.node.create_subscription(ValidatedLocoCommand, "/g1/safe_cmd/loco", cls.safe_loco.append, 10)
        cls.node.create_subscription(ValidatedActionCommand, "/g1/safe_cmd/stop", cls.safe_stop.append, 10)
        cls.node.create_subscription(Request, "/api/sport/request", cls.sport.append, 10)
        cls.node.create_subscription(DiagnosticArray, "/g1/state/health", cls.health.append, 10)
        cls.node.create_subscription(SafetyStatus, "/g1/state/safety", cls.safety.append, 10)

    @classmethod
    def tearDownClass(cls):
        cls.node.destroy_node()
        rclpy.shutdown()

    def wait_for(self, predicate, timeout=10.0):
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            rclpy.spin_once(self.node, timeout_sec=0.1)
            if predicate():
                return
        self.fail("timed out waiting for typed control-chain condition")

    def test_loco_then_stop(self):
        self.wait_for(lambda: self.safety and any(
            status.message == "ok" for msg in self.health for status in msg.status
        ), timeout=20.0)
        loco_event = VoiceEvent(
            stamp=self.node.get_clock().now().to_msg(), source="test",
            event_type=VoiceEvent.EVENT_ASR, text="小宇向前一秒", is_final=True,
        )
        self.asr_pub.publish(loco_event)
        self.wait_for(lambda: self.loco and self.safe_loco)
        self.wait_for(lambda: any(
            velocity is not None and velocity[0] > 0.0
            for velocity in (_velocity(req) for req in self.sport)
        ))

        stop_event = VoiceEvent(
            stamp=self.node.get_clock().now().to_msg(), source="test",
            event_type=VoiceEvent.EVENT_ASR, text="停止", is_final=True,
        )
        self.asr_pub.publish(stop_event)
        self.wait_for(lambda: self.safe_stop)
        self.wait_for(lambda: any(
            velocity == [0.0, 0.0, 0.0]
            for velocity in (_velocity(req) for req in self.sport)
        ))
```

- [ ] **Step 2: 运行 package-select build 并确认失败**

Run: `source /opt/ros/humble/setup.bash && colcon build --packages-select g1_system_tests`

Expected: FAIL because package files do not exist yet.

- [ ] **Step 3: 添加 ament_cmake launch test package**

Create `CMakeLists.txt`:

```cmake
cmake_minimum_required(VERSION 3.8)
project(g1_system_tests)
find_package(ament_cmake REQUIRED)
install(DIRECTORY config DESTINATION share/${PROJECT_NAME})
if(BUILD_TESTING)
  find_package(launch_testing_ament_cmake REQUIRED)
  add_launch_test(test/test_typed_control_chain.py TIMEOUT 60)
endif()
ament_package()
```

Create `package.xml`:

```xml
<?xml version="1.0"?>
<package format="3">
  <name>g1_system_tests</name>
  <version>0.1.0</version>
  <description>Launch tests for the typed G1 agent control chain.</description>
  <maintainer email="2450804878@qq.com">unitree_g1_agent</maintainer>
  <license>Apache-2.0</license>
  <buildtool_depend>ament_cmake</buildtool_depend>
  <test_depend>diagnostic_msgs</test_depend>
  <test_depend>ament_index_python</test_depend>
  <test_depend>g1_agent_msgs</test_depend>
  <test_depend>g1_interface</test_depend>
  <test_depend>g1_sim</test_depend>
  <test_depend>launch</test_depend>
  <test_depend>launch_ros</test_depend>
  <test_depend>launch_testing</test_depend>
  <test_depend>launch_testing_ament_cmake</test_depend>
  <test_depend>launch_testing_ros</test_depend>
  <test_depend>rclpy</test_depend>
  <test_depend>safety_control</test_depend>
  <test_depend>unitree_api</test_depend>
  <test_depend>voice_bridge</test_depend>
  <export><build_type>ament_cmake</build_type></export>
</package>
```

Test config:

```yaml
agent:
  backend: rule_based
```

The launch description passes this config only to `voice_bridge_node`; other nodes use their installed defaults.

- [ ] **Step 4: 运行 typed chain integration test**

Run: `make test-integration`

Expected: `g1_system_tests` passes and `colcon test-result --verbose` reports zero failures.

- [ ] **Step 5: Commit**

```bash
git add src/g1_system_tests
git commit -m "test: add typed control chain launch smoke test"
```

---

### Task 11: 添加 CI、更新契约文档并执行总验证

**Files:**
- Create: `.github/workflows/ci.yml`
- Modify: `docs/data_contracts.md`
- Create: `README.md`
- Modify: `src/asr_node/README.md`
- Modify: `src/g1_interface/README.md`
- Modify: `src/g1_sim/README.md`
- Modify: `src/voice_bridge/README.md`
- Modify: `docs/voice_bridge_debug_panel.md`

**Interfaces:**
- Consumes: all Makefile targets from Task 1 and all packages from Tasks 2-10.
- Produces: one CI workflow and current strong-type contract documentation.

- [ ] **Step 1: 写静态契约检查并确认旧文档失败**

Run:

```bash
rg -n 'std_msgs/msg/String.*JSON' docs/data_contracts.md
rg -n 'exec /usr/bin/python3 -m pytest' flake.nix
rg -n 'create_(publisher|subscription)\(self\.msg\["String"\].*(voice_loco|voice_action|safe_loco|safe_stop|decisions|safety_state)' src
```

Expected: the first command finds the old core contracts before documentation migration; after implementation all three commands return no matches.

- [ ] **Step 2: 添加 CI workflow**

Create `.github/workflows/ci.yml`:

```yaml
name: ci

on:
  push:
  pull_request:

jobs:
  test:
    runs-on: ubuntu-22.04
    steps:
      - uses: actions/checkout@v4
      - uses: ros-tooling/setup-ros@v0.7
        with:
          required-ros-distributions: humble
      - uses: cachix/install-nix-action@v31
      - uses: astral-sh/setup-uv@v6
        with:
          version: "0.11.26"
      - run: nix build .#unitree-ros2
      - run: make bootstrap
      - run: make build
      - run: make test
      - run: make test-integration
      - run: make frontend
      - run: make lint
```

Do not duplicate Python paths, pytest file lists, or environment flags in the workflow.

- [ ] **Step 3: 重写数据契约和开发命令**

Update `docs/data_contracts.md` to use the exact eight `.msg` types, fields, constants, units, `has_*` semantics, and topic table from the approved design. Explicitly document that `/audio_msg` and Sport API string payloads remain official external JSON boundaries and that `/g1/state/motors` is outside this phase.

Replace package-specific Python 3.11 or direct pytest instructions with `make bootstrap`, `make build`, `make test`, and `make test-integration`. Document `make frontend` for the debug panel.

Create the root `README.md` with this development entry point:

````markdown
# Unitree G1 Agent

ROS 2 Humble control stack for the Unitree G1. Motion intents pass through
`safety_control` before `g1_interface` emits Unitree Sport API requests.

## Development

Requirements: Ubuntu 22.04, ROS 2 Humble, `/usr/bin/python3` 3.10,
uv 0.11.26, Nix, and Node.js/npm.

```bash
nix build .#unitree-ros2
make bootstrap
make build
make test
make test-integration
make frontend
make lint
```

The project environment is `.venv-ros`. Do not run ROS nodes or tests from
the legacy Python 3.11 `.venv`.

Install the optional local ASR runtime with `make bootstrap-asr`; normal CI
does not download ASR models or initialize CUDA.
````

- [ ] **Step 4: 执行完整验证**

Run: `make bootstrap`

Expected: frozen uv sync succeeds with Python 3.10.

Run: `make build`

Expected: every ROS package builds.

Run: `make test`

Expected: all Python unit tests pass with zero failures.

Run: `make test-integration`

Expected: typed control-chain launch test passes with zero failures.

Run: `make frontend`

Expected: frontend builds and `frontend_dist` has no uncommitted drift after generated assets are staged.

Run: `make lint`

Expected: ruff and pyright exit 0.

Run:

```bash
source /opt/ros/humble/setup.bash
source result/setup.bash
source install/setup.bash
ros2 interface show g1_agent_msgs/msg/LocoIntent
ros2 interface show g1_agent_msgs/msg/SafetyStatus
```

Expected: both interfaces display the committed fields and constants.

- [ ] **Step 5: 检查只在允许边界保留 JSON String**

Run:

```bash
rg -n 'std_msgs\.msg import String|self\.msg\["String"\]' \
  src/asr_node src/g1_interface src/safety_control src/voice_bridge src/voice_bridge_debug
```

Expected matches only for native Unitree audio, motor monitoring, voice debug/state, TTS, LED, and Web/debug boundaries. No match may wire any topic listed in the strong-type topic table as `String`.

- [ ] **Step 6: Commit**

```bash
git add .github/workflows/ci.yml docs README.md src/*/README.md src/voice_bridge_debug/voice_bridge_debug/frontend_dist
git commit -m "docs: document typed ROS workflow and CI"
```

---

## Final Review Checklist

- [ ] `g1_agent_msgs` follows the official Unitree interface-package build pattern without copying official low-level messages.
- [ ] All eight message definitions match the approved design and use no JSON escape hatch.
- [ ] Every producer and consumer on the typed topic table uses the same generated class.
- [ ] stop/cancel bypass behavior and watchdog monotonic timing are unchanged.
- [ ] `uv.lock` is frozen and Python 3.11 is absent from build/test commands.
- [ ] FastAPI, Starlette and HTTPX tests run from the uv environment.
- [ ] Unit tests, launch test, frontend build, ruff and pyright all pass freshly.
- [ ] Documentation matches the generated interfaces and current Makefile commands.
