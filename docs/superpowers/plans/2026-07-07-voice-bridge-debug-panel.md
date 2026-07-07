# Voice Bridge Debug Panel Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a local Web debug panel for `voice_bridge` that can publish simulated ASR events, observe voice/safety/robot ROS topics in real time, and display agent output, decision timeline, and robot status.

**Architecture:** Add best-effort debug telemetry to `voice_bridge`, then add a new `voice_bridge_debug` ROS Python package. The debug package hosts a FastAPI server, a ROS node running in a background thread, an in-memory state buffer, WebSocket broadcasting through an asyncio queue, and a React/Vite frontend served by FastAPI in production.

**Tech Stack:** Python, ROS2 Humble `rclpy`, `std_msgs/msg/String`, `diagnostic_msgs/msg/DiagnosticArray`, FastAPI >= 0.100, uvicorn[standard] >= 0.20, PyYAML, React 18, Vite 5, TypeScript 5, TailwindCSS 3.

## Global Constraints

- Default debug panel host is `127.0.0.1`; non-loopback host requires `allow_remote: true` and must log a safety warning.
- REST routes must not call ROS publishers directly; they enqueue ASR publish requests for a ROS timer to drain.
- ROS callbacks must not await WebSocket operations; they update thread-safe state and notify the FastAPI event loop through `loop.call_soon_threadsafe()`.
- `voice_bridge` publishes exactly one debug event topic: `/voice/debug/events`.
- `voice_bridge` debug events are best-effort and must never affect `/voice/cmd/*`, `/g1/cmd/audio/*`, or `/voice/state` behavior.
- Debug panel sends ASR only to `/g1/audio/asr`; it does not directly publish motion commands.
- Timeline history is in memory only and defaults to the latest 200 events.
- Development frontend uses Vite proxy for `/api` and `/ws`; production frontend is served by FastAPI.
- `voice_bridge` config key is `topics.debug_events`; `voice_bridge_debug` config key is `topics.voice_debug_events`; both default to `/voice/debug/events`.

---

## File Structure

### Existing Files To Modify

- `src/voice_bridge/voice_bridge/config.py`: add `debug_events` topic default and validation.
- `src/voice_bridge/config/voice_bridge.yaml`: add `debug_events: /voice/debug/events`.
- `src/voice_bridge/voice_bridge/node.py`: add debug event schema helpers, debug publisher, and event emission points.
- `src/voice_bridge/tests/test_config.py`: verify default and YAML debug topic config.
- `src/voice_bridge/tests/test_node_helpers.py`: verify debug event helper and publisher behavior.

### New Backend Package Files

- `src/voice_bridge_debug/setup.py`: package metadata, package data, dependencies, console script.
- `src/voice_bridge_debug/setup.cfg`: pytest and style config matching existing packages.
- `src/voice_bridge_debug/package.xml`: ROS package metadata and runtime dependencies.
- `src/voice_bridge_debug/resource/voice_bridge_debug`: ament resource marker.
- `src/voice_bridge_debug/config/debug_panel.yaml`: default server, topic, timeline, and ASR defaults.
- `src/voice_bridge_debug/launch/debug_panel.launch.py`: ROS launch entry.
- `src/voice_bridge_debug/voice_bridge_debug/__init__.py`: package marker.
- `src/voice_bridge_debug/voice_bridge_debug/config.py`: load and validate debug panel config.
- `src/voice_bridge_debug/voice_bridge_debug/state.py`: dataclasses, JSON parsing, health normalization, ring buffer.
- `src/voice_bridge_debug/voice_bridge_debug/ws.py`: WebSocket connection manager.
- `src/voice_bridge_debug/voice_bridge_debug/ros_node.py`: ROS publishers/subscribers and ASR queue drain.
- `src/voice_bridge_debug/voice_bridge_debug/routes.py`: FastAPI REST and WebSocket route registration.
- `src/voice_bridge_debug/voice_bridge_debug/server.py`: lifecycle, asyncio broadcast queue, static file hosting, CLI entry.

### New Backend Test Files

- `src/voice_bridge_debug/tests/conftest.py`: ROS message stubs for non-ROS unit test runs.
- `src/voice_bridge_debug/tests/test_config.py`: config defaults, validation, remote host guard.
- `src/voice_bridge_debug/tests/test_state.py`: parsing, health normalization, ring buffer, event conversion.
- `src/voice_bridge_debug/tests/test_ros_node.py`: ASR queue drain and topic callback behavior with fake ROS node.
- `src/voice_bridge_debug/tests/test_routes.py`: REST validation and response shapes.
- `src/voice_bridge_debug/tests/test_ws.py`: WebSocket manager broadcast/disconnect behavior.

### New Frontend Files

- `src/voice_bridge_debug/frontend/package.json`: scripts and dependencies.
- `src/voice_bridge_debug/frontend/vite.config.ts`: React plugin and `/api` `/ws` proxy.
- `src/voice_bridge_debug/frontend/tailwind.config.js`: Tailwind content paths.
- `src/voice_bridge_debug/frontend/postcss.config.js`: Tailwind/PostCSS config.
- `src/voice_bridge_debug/frontend/tsconfig.json`: TypeScript compiler config.
- `src/voice_bridge_debug/frontend/index.html`: app mount point.
- `src/voice_bridge_debug/frontend/src/main.tsx`: React bootstrap.
- `src/voice_bridge_debug/frontend/src/App.tsx`: layout composition.
- `src/voice_bridge_debug/frontend/src/types/index.ts`: shared message and state types.
- `src/voice_bridge_debug/frontend/src/state/appState.tsx`: reducer/context.
- `src/voice_bridge_debug/frontend/src/api/http.ts`: REST client helpers.
- `src/voice_bridge_debug/frontend/src/api/ws.ts`: reconnecting WebSocket client.
- `src/voice_bridge_debug/frontend/src/components/AsrInput.tsx`: ASR publish form.
- `src/voice_bridge_debug/frontend/src/components/AgentOutput.tsx`: latest agent result panel.
- `src/voice_bridge_debug/frontend/src/components/DecisionTimeline.tsx`: event list and expandable JSON.
- `src/voice_bridge_debug/frontend/src/components/RobotStatus.tsx`: robot/session/connection status.
- `src/voice_bridge_debug/frontend/src/components/layout/Header.tsx`: title and connection indicators.
- `src/voice_bridge_debug/frontend/src/components/layout/Panel.tsx`: shared panel shell.

---

### Task 1: Add `voice_bridge` Debug Telemetry

**Files:**
- Modify: `src/voice_bridge/voice_bridge/config.py`
- Modify: `src/voice_bridge/config/voice_bridge.yaml`
- Modify: `src/voice_bridge/voice_bridge/node.py`
- Test: `src/voice_bridge/tests/test_config.py`
- Test: `src/voice_bridge/tests/test_node_helpers.py`

**Interfaces:**
- Produces: `DEBUG_EVENT_SCHEMA_VERSION = "voice_debug_event.v1"`
- Produces: `build_debug_event(event: str, session_id: str | None, data: dict[str, Any], *, timestamp: float) -> dict[str, Any]`
- Produces: `VoiceBridgeNode._publish_debug_event(event: str, session_id: str | None, data: dict[str, Any], now_sec: float) -> None`
- Produces ROS topic: `/voice/debug/events` with `std_msgs/msg/String` JSON payload.

- [ ] **Step 1: Add failing config tests**

Append these tests to `src/voice_bridge/tests/test_config.py`:

```python
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
```

- [ ] **Step 2: Run config tests and verify failure**

Run:

```bash
pytest src/voice_bridge/tests/test_config.py -q
```

Expected: failure mentioning missing `debug_events` default or validation.

- [ ] **Step 3: Add debug topic config**

In `src/voice_bridge/voice_bridge/config.py`, add the topic default:

```python
"debug_events": "/voice/debug/events",
```

inside `DEFAULT_CONFIG["topics"]`, and add `"debug_events"` to `required_topics`.

In `src/voice_bridge/config/voice_bridge.yaml`, add:

```yaml
topics:
  debug_events: /voice/debug/events
```

under the existing topic mappings, preserving existing keys.

- [ ] **Step 4: Run config tests and verify pass**

Run:

```bash
pytest src/voice_bridge/tests/test_config.py -q
```

Expected: all tests in that file pass.

- [ ] **Step 5: Add failing debug event helper test**

Append to `src/voice_bridge/tests/test_node_helpers.py`:

```python
def test_build_debug_event_payload():
    from voice_bridge.node import DEBUG_EVENT_SCHEMA_VERSION, build_debug_event

    payload = build_debug_event(
        "agent_result",
        "s1",
        {"reply_text": "收到"},
        timestamp=10.5,
    )

    assert payload == {
        "schema_version": DEBUG_EVENT_SCHEMA_VERSION,
        "timestamp": 10.5,
        "session_id": "s1",
        "event": "agent_result",
        "data": {"reply_text": "收到"},
    }
```

- [ ] **Step 6: Run helper test and verify failure**

Run:

```bash
pytest src/voice_bridge/tests/test_node_helpers.py::test_build_debug_event_payload -q
```

Expected: import failure for `build_debug_event` or `DEBUG_EVENT_SCHEMA_VERSION`.

- [ ] **Step 7: Add debug event helper**

In `src/voice_bridge/voice_bridge/node.py`, near `COMMAND_SCHEMA_VERSION`, add:

```python
DEBUG_EVENT_SCHEMA_VERSION = "voice_debug_event.v1"


def build_debug_event(
    event: str,
    session_id: str | None,
    data: dict[str, Any],
    *,
    timestamp: float,
) -> dict[str, Any]:
    return {
        "schema_version": DEBUG_EVENT_SCHEMA_VERSION,
        "timestamp": float(timestamp),
        "session_id": session_id,
        "event": event,
        "data": data,
    }
```

- [ ] **Step 8: Run helper test and verify pass**

Run:

```bash
pytest src/voice_bridge/tests/test_node_helpers.py::test_build_debug_event_payload -q
```

Expected: pass.

- [ ] **Step 9: Add failing debug publisher behavior tests**

Append to `src/voice_bridge/tests/test_node_helpers.py`:

```python
def test_debug_event_publish_is_best_effort(monkeypatch):
    import json

    from voice_bridge import node as node_module
    from voice_bridge.config import VoiceBridgeConfig
    from voice_bridge.node import VoiceBridgeNode

    monkeypatch.setattr(node_module, "_load_ros_messages", fake_ros_messages)

    node = VoiceBridgeNode(FakeNode(), VoiceBridgeConfig.default(), agent=NonCloseableAgent())
    node._publish_debug_event("agent_started", "s1", {"text": "向前"}, 1.0)

    payload = json.loads(node.debug_pub.payloads[-1])
    assert payload["schema_version"] == "voice_debug_event.v1"
    assert payload["event"] == "agent_started"
    assert payload["session_id"] == "s1"
    assert payload["data"] == {"text": "向前"}


def test_agent_result_debug_event_publishes_before_commands(monkeypatch):
    import json

    from voice_bridge import node as node_module
    from voice_bridge.config import VoiceBridgeConfig
    from voice_bridge.internal_types import AgentCommand, AgentRequest, AgentResult
    from voice_bridge.node import VoiceBridgeNode

    monkeypatch.setattr(node_module, "_load_ros_messages", fake_ros_messages)

    node = VoiceBridgeNode(FakeNode(), VoiceBridgeConfig.default(), agent=NonCloseableAgent())
    request = AgentRequest(session_id="s1", text="向前", asr_confidence=0.9)
    result = AgentResult(
        commands=[AgentCommand(kind="loco", params={"vx": 0.25, "vy": 0.0, "vyaw": 0.0, "duration_sec": 1.0})],
        reply_text="收到",
        led={"r": 0, "g": 1, "b": 0},
    )

    node._publish_agent_result(result, request, 1.0)

    debug_payload = json.loads(node.debug_pub.payloads[0])
    assert debug_payload["event"] == "agent_result"
    assert debug_payload["data"]["reply_text"] == "收到"
    assert debug_payload["data"]["commands"][0]["kind"] == "loco"
    assert len(node.loco_pub.payloads) == 1
```

- [ ] **Step 10: Run new debug publisher tests and verify failure**

Run:

```bash
pytest \
  src/voice_bridge/tests/test_node_helpers.py::test_debug_event_publish_is_best_effort \
  src/voice_bridge/tests/test_node_helpers.py::test_agent_result_debug_event_publishes_before_commands \
  -q
```

Expected: fail because `debug_pub` and `_publish_debug_event` do not exist.

- [ ] **Step 11: Add debug publisher and event emissions**

In `VoiceBridgeNode.__init__`, after `self.state_pub`:

```python
self.debug_pub = node.create_publisher(self.msg["String"], topics["debug_events"], 10)
```

Add methods to `VoiceBridgeNode`:

```python
def _publish_debug_event(self, event: str, session_id: str | None, data: dict[str, Any], now_sec: float) -> None:
    try:
        self._publish_string(self.debug_pub, build_debug_event(event, session_id, data, timestamp=now_sec))
    except Exception as exc:  # Debug telemetry must never affect command behavior.
        self.node.get_logger().warning(f"failed to publish voice debug event: {exc}")


def _agent_result_to_debug_data(self, result: AgentResult) -> dict[str, Any]:
    return {
        "commands": [{"kind": command.kind, "params": dict(command.params)} for command in result.commands],
        "reply_text": result.reply_text,
        "led": result.led,
        "requires_confirmation": result.requires_confirmation,
    }
```

In `on_asr`, after `event = parse_asr_event(msg.data)`:

```python
self._publish_debug_event(
    "asr_received",
    None,
    {
        "text": event.text,
        "confidence": event.confidence,
        "is_final": event.is_final,
        "source": event.source,
        "stamp": event.stamp,
    },
    now_sec,
)
```

After `self.last_decision = decision.to_dict()`:

```python
self._publish_debug_event("session_decision", decision.session_id, decision.to_dict(), now_sec)
```

In `_call_agent`, before `self._agent_requests.start(session_id)`:

```python
self._publish_debug_event(
    "agent_started",
    session_id,
    {
        "text": request.text,
        "backend": self.config.agent["backend"],
        "robot_mode": self.robot_mode,
        "safety_state": self.safety_state,
    },
    now_sec,
)
```

At the start of `_publish_agent_result`, before the command loop:

```python
self._publish_debug_event("agent_result", request.session_id, self._agent_result_to_debug_data(result), now_sec)
```

After each successful `_publish_string(...)` command publish, add a matching `command_published` event using the same payload and topic string.

In `_run_agent_request` exception branch, before publishing fallback TTS:

```python
self._publish_debug_event(
    "agent_error",
    request.session_id,
    {"error": str(exc), "fallback_reply_text": "语音服务暂时不可用"},
    request_sec,
)
```

- [ ] **Step 12: Run voice_bridge tests**

Run:

```bash
pytest src/voice_bridge/tests -q
```

Expected: all voice_bridge tests pass.

- [ ] **Step 13: Commit voice_bridge debug telemetry**

Run:

```bash
git add \
  src/voice_bridge/voice_bridge/config.py \
  src/voice_bridge/config/voice_bridge.yaml \
  src/voice_bridge/voice_bridge/node.py \
  src/voice_bridge/tests/test_config.py \
  src/voice_bridge/tests/test_node_helpers.py
git commit -m "feat: add voice bridge debug events"
```

Expected: commit succeeds.

---

### Task 2: Create Debug Panel Backend Core

**Files:**
- Create: `src/voice_bridge_debug/setup.py`
- Create: `src/voice_bridge_debug/setup.cfg`
- Create: `src/voice_bridge_debug/package.xml`
- Create: `src/voice_bridge_debug/resource/voice_bridge_debug`
- Create: `src/voice_bridge_debug/config/debug_panel.yaml`
- Create: `src/voice_bridge_debug/voice_bridge_debug/__init__.py`
- Create: `src/voice_bridge_debug/voice_bridge_debug/config.py`
- Create: `src/voice_bridge_debug/voice_bridge_debug/state.py`
- Test: `src/voice_bridge_debug/tests/conftest.py`
- Test: `src/voice_bridge_debug/tests/test_config.py`
- Test: `src/voice_bridge_debug/tests/test_state.py`

**Interfaces:**
- Produces: `DebugPanelConfig.from_yaml(path: str | Path) -> DebugPanelConfig`
- Produces: `DebugPanelConfig.default() -> DebugPanelConfig`
- Produces: `TimelineEvent.to_dict() -> dict[str, Any]`
- Produces: `PanelState.snapshot() -> dict[str, Any]`
- Produces: `PanelState.push_event(source: str, kind: str, data: dict[str, Any], session_id: str | None = None, timestamp: float | None = None) -> dict[str, Any]`
- Produces: `parse_json_topic(raw: str) -> dict[str, Any]`
- Produces: `normalize_health(msg: Any, now_sec: float, stale_after_sec: float, last: HealthState | None = None) -> HealthState`

- [ ] **Step 1: Add package skeleton**

Create package files with these contents.

`src/voice_bridge_debug/resource/voice_bridge_debug`:

```text
voice_bridge_debug
```

`src/voice_bridge_debug/voice_bridge_debug/__init__.py`:

```python
"""Web debug panel for the G1 voice bridge."""
```

`src/voice_bridge_debug/setup.cfg`:

```ini
[develop]
script_dir=$base/lib/voice_bridge_debug
[install]
install_scripts=$base/lib/voice_bridge_debug
```

`src/voice_bridge_debug/package.xml`:

```xml
<?xml version="1.0"?>
<package format="3">
  <name>voice_bridge_debug</name>
  <version>0.1.0</version>
  <description>Web debug panel for Unitree G1 voice bridge</description>
  <maintainer email="dev@example.local">unitree_g1_agent</maintainer>
  <license>Apache-2.0</license>

  <exec_depend>diagnostic_msgs</exec_depend>
  <exec_depend>rclpy</exec_depend>
  <exec_depend>std_msgs</exec_depend>

  <test_depend>pytest</test_depend>

  <export>
    <build_type>ament_python</build_type>
  </export>
</package>
```

`src/voice_bridge_debug/setup.py`:

```python
from glob import glob

from setuptools import find_packages, setup

package_name = "voice_bridge_debug"

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
    install_requires=["setuptools", "PyYAML", "fastapi>=0.100", "uvicorn[standard]>=0.20"],
    zip_safe=True,
    maintainer="unitree_g1_agent",
    maintainer_email="dev@example.local",
    description="Web debug panel for Unitree G1 voice bridge",
    license="Apache-2.0",
    tests_require=["pytest"],
    entry_points={
        "console_scripts": [
            "debug_panel_server = voice_bridge_debug.server:main",
        ],
    },
)
```

`src/voice_bridge_debug/config/debug_panel.yaml`:

```yaml
server:
  host: "127.0.0.1"
  port: 8765
  allow_remote: false

topics:
  asr: /g1/audio/asr
  voice_state: /voice/state
  voice_debug_events: /voice/debug/events
  robot_mode: /g1/state/mode
  safety_state: /g1/state/safety
  health: /g1/state/health
  voice_cmd_loco: /voice/cmd/loco
  voice_cmd_action: /voice/cmd/action
  tts: /g1/cmd/audio/tts
  led: /g1/cmd/audio/led
  safe_cmd_loco: /g1/safe_cmd/loco
  safe_cmd_stop: /g1/safe_cmd/stop
  safety_decisions: /g1/safety/decisions

defaults:
  asr_confidence: 0.9
  asr_is_final: true
  asr_source: "debug"

timeline:
  max_events: 200
  state_timeout_ms: 2000

asr_default_text: "小宇"
```

- [ ] **Step 2: Add config tests**

Create `src/voice_bridge_debug/tests/test_config.py`:

```python
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
```

- [ ] **Step 3: Run config tests and verify failure**

Run:

```bash
pytest src/voice_bridge_debug/tests/test_config.py -q
```

Expected: failure because `voice_bridge_debug.config` does not exist.

- [ ] **Step 4: Implement config module**

Create `src/voice_bridge_debug/voice_bridge_debug/config.py`:

```python
from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml


DEFAULT_CONFIG: dict[str, Any] = {
    "server": {"host": "127.0.0.1", "port": 8765, "allow_remote": False},
    "topics": {
        "asr": "/g1/audio/asr",
        "voice_state": "/voice/state",
        "voice_debug_events": "/voice/debug/events",
        "robot_mode": "/g1/state/mode",
        "safety_state": "/g1/state/safety",
        "health": "/g1/state/health",
        "voice_cmd_loco": "/voice/cmd/loco",
        "voice_cmd_action": "/voice/cmd/action",
        "tts": "/g1/cmd/audio/tts",
        "led": "/g1/cmd/audio/led",
        "safe_cmd_loco": "/g1/safe_cmd/loco",
        "safe_cmd_stop": "/g1/safe_cmd/stop",
        "safety_decisions": "/g1/safety/decisions",
    },
    "defaults": {"asr_confidence": 0.9, "asr_is_final": True, "asr_source": "debug"},
    "timeline": {"max_events": 200, "state_timeout_ms": 2000},
    "asr_default_text": "小宇",
}


def _deep_merge(base: dict[str, Any], override: dict[str, Any]) -> dict[str, Any]:
    merged = deepcopy(base)
    for key, value in override.items():
        if isinstance(value, dict) and isinstance(merged.get(key), dict):
            merged[key] = _deep_merge(merged[key], value)
        else:
            merged[key] = value
    return merged


def _is_loopback(host: str) -> bool:
    return host in {"127.0.0.1", "localhost", "::1"}


@dataclass(frozen=True)
class DebugPanelConfig:
    server: dict[str, Any]
    topics: dict[str, str]
    defaults: dict[str, Any]
    timeline: dict[str, Any]
    asr_default_text: str

    @classmethod
    def default(cls) -> "DebugPanelConfig":
        return cls.from_dict(deepcopy(DEFAULT_CONFIG))

    @classmethod
    def from_yaml(cls, path: str | Path) -> "DebugPanelConfig":
        with Path(path).open("r", encoding="utf-8") as handle:
            loaded = yaml.safe_load(handle) or {}
        if not isinstance(loaded, dict):
            raise ValueError("config root must be a mapping")
        return cls.from_dict(_deep_merge(DEFAULT_CONFIG, loaded))

    @classmethod
    def from_dict(cls, raw: dict[str, Any]) -> "DebugPanelConfig":
        config = cls(
            server=dict(raw["server"]),
            topics=dict(raw["topics"]),
            defaults=dict(raw["defaults"]),
            timeline=dict(raw["timeline"]),
            asr_default_text=str(raw.get("asr_default_text", "")),
        )
        config.validate()
        return config

    def to_dict(self) -> dict[str, Any]:
        return {
            "server": dict(self.server),
            "topics": dict(self.topics),
            "defaults": dict(self.defaults),
            "timeline": dict(self.timeline),
            "asr_default_text": self.asr_default_text,
        }

    def validate(self) -> None:
        host = self.server.get("host")
        if not isinstance(host, str) or not host:
            raise ValueError("server.host must be a non-empty string")
        port = self.server.get("port")
        if isinstance(port, bool) or not isinstance(port, int) or not 1 <= port <= 65535:
            raise ValueError("server.port must be an integer between 1 and 65535")
        allow_remote = self.server.get("allow_remote")
        if not isinstance(allow_remote, bool):
            raise ValueError("server.allow_remote must be boolean")
        if not _is_loopback(host) and not allow_remote:
            raise ValueError("non-loopback host requires allow_remote: true")

        required_topics = [
            "asr",
            "voice_state",
            "voice_debug_events",
            "robot_mode",
            "safety_state",
            "health",
            "voice_cmd_loco",
            "voice_cmd_action",
            "tts",
            "led",
            "safe_cmd_loco",
            "safe_cmd_stop",
            "safety_decisions",
        ]
        missing = [key for key in required_topics if not isinstance(self.topics.get(key), str) or not self.topics[key]]
        if missing:
            raise ValueError(f"missing topic config: {', '.join(missing)}")

        confidence = self.defaults.get("asr_confidence")
        if isinstance(confidence, bool) or not isinstance(confidence, (int, float)) or not 0.0 <= float(confidence) <= 1.0:
            raise ValueError("defaults.asr_confidence must be between 0 and 1")
        if not isinstance(self.defaults.get("asr_is_final"), bool):
            raise ValueError("defaults.asr_is_final must be boolean")
        if not isinstance(self.defaults.get("asr_source"), str) or not self.defaults["asr_source"]:
            raise ValueError("defaults.asr_source must be a non-empty string")
        if not isinstance(self.timeline.get("max_events"), int) or self.timeline["max_events"] <= 0:
            raise ValueError("timeline.max_events must be positive integer")
        if not isinstance(self.timeline.get("state_timeout_ms"), int) or self.timeline["state_timeout_ms"] <= 0:
            raise ValueError("timeline.state_timeout_ms must be positive integer")
```

- [ ] **Step 5: Run config tests and verify pass**

Run:

```bash
pytest src/voice_bridge_debug/tests/test_config.py -q
```

Expected: all tests pass.

- [ ] **Step 6: Add ROS test stubs**

Create `src/voice_bridge_debug/tests/conftest.py`:

```python
import sys
import types


def _install_diagnostic_msgs_stub() -> None:
    try:
        import diagnostic_msgs.msg  # noqa: F401
    except ModuleNotFoundError:
        diagnostic_msgs = types.ModuleType("diagnostic_msgs")
        msg = types.ModuleType("diagnostic_msgs.msg")

        class KeyValue:
            def __init__(self):
                self.key = ""
                self.value = ""

        class DiagnosticStatus:
            def __init__(self):
                self.name = ""
                self.level = 0
                self.message = ""
                self.values = []

        class DiagnosticArray:
            def __init__(self):
                self.status = []

        msg.KeyValue = KeyValue
        msg.DiagnosticArray = DiagnosticArray
        msg.DiagnosticStatus = DiagnosticStatus
        diagnostic_msgs.msg = msg
        sys.modules["diagnostic_msgs"] = diagnostic_msgs
        sys.modules["diagnostic_msgs.msg"] = msg


_install_diagnostic_msgs_stub()
```

- [ ] **Step 7: Add state tests**

Create `src/voice_bridge_debug/tests/test_state.py`:

```python
import json

from diagnostic_msgs.msg import DiagnosticArray, DiagnosticStatus, KeyValue

from voice_bridge_debug.state import PanelState, parse_json_topic, normalize_health


def test_parse_json_topic_success():
    assert parse_json_topic('{"mode":"sport_api_loco"}') == {"data": {"mode": "sport_api_loco"}}


def test_parse_json_topic_error_keeps_raw():
    parsed = parse_json_topic("not json")

    assert parsed["raw"] == "not json"
    assert "parse_error" in parsed


def test_panel_state_ring_buffer_keeps_latest_events():
    state = PanelState(max_events=2, notify_web=None)

    state.push_event("test", "first", {"index": 1}, timestamp=1.0)
    state.push_event("test", "second", {"index": 2}, timestamp=2.0)
    state.push_event("test", "third", {"index": 3}, timestamp=3.0)

    assert [event.kind for event in state.timeline] == ["second", "third"]


def test_push_event_notifies_web_with_timeline_event():
    messages = []
    state = PanelState(max_events=10, notify_web=messages.append)

    state.push_event("asr", "asr_received", {"text": "小宇"}, session_id="s1", timestamp=1.0)

    assert messages == [
        {
            "type": "timeline_event",
            "data": {
                "timestamp": 1.0,
                "source": "asr",
                "kind": "asr_received",
                "data": {"text": "小宇"},
                "session_id": "s1",
            },
        }
    ]


def test_normalize_health_maps_status_levels():
    key_value = KeyValue()
    key_value.key = "dds"
    key_value.value = "ok"
    status = DiagnosticStatus()
    status.name = "g1_interface"
    status.level = 1
    status.message = "degraded"
    status.values.append(key_value)
    msg = DiagnosticArray()
    msg.status.append(status)

    health = normalize_health(msg, now_sec=10.0, stale_after_sec=2.0)

    assert health.summary == "warn"
    assert health.max_level == 1
    assert health.status_count == 1
    assert health.raw["statuses"][0]["values"] == {"dds": "ok"}


def test_snapshot_is_json_serializable():
    state = PanelState(max_events=10, notify_web=None)
    state.robot_mode = {"data": {"mode": "sport_api_loco"}}
    state.push_event("asr", "asr_received", {"text": "小宇"}, timestamp=1.0)

    json.dumps(state.snapshot(), ensure_ascii=False)
```

- [ ] **Step 8: Run state tests and verify failure**

Run:

```bash
pytest src/voice_bridge_debug/tests/test_state.py -q
```

Expected: failure because `voice_bridge_debug.state` does not exist.

- [ ] **Step 9: Implement state module**

Create `src/voice_bridge_debug/voice_bridge_debug/state.py` with:

```python
from __future__ import annotations

import json
import threading
import time
from dataclasses import asdict, dataclass, field
from typing import Any, Callable


@dataclass
class TimelineEvent:
    timestamp: float
    source: str
    kind: str
    data: dict[str, Any]
    session_id: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class HealthState:
    summary: str
    max_level: int | None
    status_count: int
    raw: dict[str, Any] | None
    updated_at: float | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "summary": self.summary,
            "max_level": self.max_level,
            "status_count": self.status_count,
            "raw": self.raw,
        }


def parse_json_topic(raw: str) -> dict[str, Any]:
    try:
        data = json.loads(raw)
    except (TypeError, json.JSONDecodeError) as exc:
        return {"raw": raw, "parse_error": str(exc)}
    if not isinstance(data, dict):
        return {"raw": raw, "parse_error": "JSON payload must be an object"}
    return {"data": data}


def _diagnostic_level_to_int(level: Any) -> int | None:
    if level is None:
        return None
    if isinstance(level, (bytes, bytearray, memoryview)):
        raw = bytes(level)
        return raw[0] if raw else None
    return int(level)


def _summary_from_level(level: int | None) -> str:
    if level is None:
        return "unknown"
    if level <= 0:
        return "ok"
    if level == 1:
        return "warn"
    return "error"


def normalize_health(
    msg: Any,
    now_sec: float,
    stale_after_sec: float,
    last: HealthState | None = None,
) -> HealthState:
    statuses = []
    levels: list[int] = []
    for status in getattr(msg, "status", []):
        level = _diagnostic_level_to_int(getattr(status, "level", None))
        if level is not None:
            levels.append(level)
        values = {
            str(getattr(item, "key", "")): str(getattr(item, "value", ""))
            for item in getattr(status, "values", [])
            if getattr(item, "key", "")
        }
        statuses.append(
            {
                "name": getattr(status, "name", ""),
                "level": level,
                "message": getattr(status, "message", ""),
                "values": values,
            }
        )
    max_level = max(levels) if levels else None
    summary = _summary_from_level(max_level)
    if last is not None and last.updated_at is not None and now_sec - last.updated_at > stale_after_sec:
        return HealthState(summary="stale", max_level=last.max_level, status_count=last.status_count, raw=last.raw, updated_at=last.updated_at)
    return HealthState(summary=summary, max_level=max_level, status_count=len(statuses), raw={"statuses": statuses}, updated_at=now_sec)


@dataclass
class PanelState:
    max_events: int = 200
    notify_web: Callable[[dict[str, Any]], None] | None = None
    robot_mode: dict[str, Any] | None = None
    safety_state: dict[str, Any] | None = None
    health: HealthState | None = None
    voice_session: dict[str, Any] | None = None
    last_asr_text: str | None = None
    last_decision: dict[str, Any] | None = None
    last_error: str | None = None
    agent_backend: str | None = None
    agent_result: dict[str, Any] | None = None
    timeline: list[TimelineEvent] = field(default_factory=list)
    _lock: threading.RLock = field(default_factory=threading.RLock)

    def push_event(
        self,
        source: str,
        kind: str,
        data: dict[str, Any],
        session_id: str | None = None,
        timestamp: float | None = None,
    ) -> dict[str, Any]:
        event = TimelineEvent(
            timestamp=float(timestamp if timestamp is not None else time.time()),
            source=source,
            kind=kind,
            data=data,
            session_id=session_id,
        )
        with self._lock:
            self.timeline.append(event)
            self.timeline = self.timeline[-self.max_events :]
        message = {"type": "timeline_event", "data": event.to_dict()}
        if self.notify_web is not None:
            self.notify_web(message)
        return message

    def set_robot_state(self, **updates: Any) -> dict[str, Any]:
        with self._lock:
            for key, value in updates.items():
                setattr(self, key, value)
            snapshot = self.robot_state_snapshot()
        message = {"type": "robot_state", "data": snapshot}
        if self.notify_web is not None:
            self.notify_web(message)
        return message

    def set_agent_result(self, result: dict[str, Any]) -> dict[str, Any]:
        with self._lock:
            self.agent_result = result
        message = {"type": "agent_result", "data": result}
        if self.notify_web is not None:
            self.notify_web(message)
        return message

    def robot_state_snapshot(self) -> dict[str, Any]:
        health = self.health.to_dict() if self.health is not None else None
        return {
            "robot_mode": self.robot_mode,
            "safety_state": self.safety_state,
            "health": health,
            "voice_session": self.voice_session,
            "last_asr_text": self.last_asr_text,
            "last_decision": self.last_decision,
            "last_error": self.last_error,
            "agent_backend": self.agent_backend,
        }

    def snapshot(self) -> dict[str, Any]:
        with self._lock:
            return {
                "robot_state": self.robot_state_snapshot(),
                "agent_result": self.agent_result,
                "timeline": [event.to_dict() for event in self.timeline],
            }
```

- [ ] **Step 10: Run backend core tests**

Run:

```bash
pytest src/voice_bridge_debug/tests/test_config.py src/voice_bridge_debug/tests/test_state.py -q
```

Expected: all tests pass.

- [ ] **Step 11: Commit backend core**

Run:

```bash
git add src/voice_bridge_debug
git commit -m "feat: add voice bridge debug backend core"
```

Expected: commit succeeds.

---

### Task 3: Implement Debug Panel FastAPI and ROS Bridge

**Files:**
- Create: `src/voice_bridge_debug/voice_bridge_debug/ws.py`
- Create: `src/voice_bridge_debug/voice_bridge_debug/ros_node.py`
- Create: `src/voice_bridge_debug/voice_bridge_debug/routes.py`
- Create: `src/voice_bridge_debug/voice_bridge_debug/server.py`
- Create: `src/voice_bridge_debug/launch/debug_panel.launch.py`
- Test: `src/voice_bridge_debug/tests/test_ws.py`
- Test: `src/voice_bridge_debug/tests/test_ros_node.py`
- Test: `src/voice_bridge_debug/tests/test_routes.py`

**Interfaces:**
- Consumes: `DebugPanelConfig`, `PanelState`, `parse_json_topic`, `normalize_health`.
- Produces: `WebSocketManager.connect(ws)`, `disconnect(ws)`, `broadcast(message)`.
- Produces: `DebugBridgeNode.drain_asr_queue() -> None`.
- Produces: `create_app(server: DebugBridgeServer) -> FastAPI`.
- Produces: `DebugBridgeServer.startup()`, `shutdown()`, `notify_web_from_ros_thread(message)`, `main(argv=None)`.

- [ ] **Step 1: Add WebSocket manager tests**

Create `src/voice_bridge_debug/tests/test_ws.py`:

```python
import asyncio

from voice_bridge_debug.ws import WebSocketManager


class FakeWebSocket:
    def __init__(self, fail=False):
        self.accepted = False
        self.messages = []
        self.fail = fail

    async def accept(self):
        self.accepted = True

    async def send_json(self, message):
        if self.fail:
            raise RuntimeError("closed")
        self.messages.append(message)


def test_websocket_manager_connects_and_broadcasts():
    manager = WebSocketManager()
    ws = FakeWebSocket()

    async def run():
        await manager.connect(ws)
        await manager.broadcast({"type": "connection_status", "data": {"websocket": "connected"}})

    asyncio.run(run())

    assert ws.accepted is True
    assert ws.messages == [{"type": "connection_status", "data": {"websocket": "connected"}}]


def test_websocket_manager_removes_failed_connections():
    manager = WebSocketManager()
    ws = FakeWebSocket(fail=True)

    async def run():
        await manager.connect(ws)
        await manager.broadcast({"type": "timeline_event", "data": {}})

    asyncio.run(run())

    assert ws not in manager.connections
```

- [ ] **Step 2: Implement WebSocket manager**

Create `src/voice_bridge_debug/voice_bridge_debug/ws.py`:

```python
from __future__ import annotations

import asyncio
from typing import Any

from fastapi import WebSocket


class WebSocketManager:
    def __init__(self):
        self.connections: set[WebSocket] = set()
        self._lock = asyncio.Lock()

    async def connect(self, ws: WebSocket) -> None:
        await ws.accept()
        async with self._lock:
            self.connections.add(ws)

    async def disconnect(self, ws: WebSocket) -> None:
        async with self._lock:
            self.connections.discard(ws)

    async def broadcast(self, message: dict[str, Any]) -> None:
        async with self._lock:
            connections = list(self.connections)
        failed = []
        for ws in connections:
            try:
                await ws.send_json(message)
            except Exception:
                failed.append(ws)
        if failed:
            async with self._lock:
                for ws in failed:
                    self.connections.discard(ws)
```

- [ ] **Step 3: Run WebSocket tests**

Run:

```bash
pytest src/voice_bridge_debug/tests/test_ws.py -q
```

Expected: pass.

- [ ] **Step 4: Add ROS node tests**

Create `src/voice_bridge_debug/tests/test_ros_node.py`:

```python
import json
import queue

from voice_bridge_debug.config import DebugPanelConfig
from voice_bridge_debug.ros_node import DebugBridgeNode
from voice_bridge_debug.state import PanelState


class FakeString:
    def __init__(self):
        self.data = ""


class FakePublisher:
    def __init__(self):
        self.messages = []

    def publish(self, msg):
        self.messages.append(msg.data)


class FakeClockNow:
    nanoseconds = 1_000_000_000


class FakeClock:
    def now(self):
        return FakeClockNow()


class FakeNode:
    def __init__(self):
        self.publishers = {}
        self.subscriptions = []
        self.timers = []

    def create_publisher(self, msg_type, topic, depth):
        pub = FakePublisher()
        self.publishers[topic] = pub
        return pub

    def create_subscription(self, msg_type, topic, callback, depth):
        self.subscriptions.append((topic, callback))
        return callback

    def create_timer(self, period, callback):
        self.timers.append((period, callback))
        return callback

    def get_clock(self):
        return FakeClock()


def test_drain_asr_queue_publishes_json(monkeypatch):
    from voice_bridge_debug import ros_node as ros_node_module

    monkeypatch.setattr(ros_node_module, "_load_ros_messages", lambda: {"String": FakeString, "DiagnosticArray": object})
    config = DebugPanelConfig.default()
    q = queue.Queue()
    q.put({"text": "小宇向前", "confidence": 0.9, "is_final": True, "source": "debug"})
    node = DebugBridgeNode(FakeNode(), config, PanelState(), q, lambda message: None)

    node.drain_asr_queue()

    payload = json.loads(node.asr_pub.messages[-1])
    assert payload["text"] == "小宇向前"
    assert payload["confidence"] == 0.9
    assert payload["is_final"] is True
    assert payload["source"] == "debug"
    assert "stamp" in payload


def test_voice_debug_agent_result_updates_agent_result(monkeypatch):
    from voice_bridge_debug import ros_node as ros_node_module

    monkeypatch.setattr(ros_node_module, "_load_ros_messages", lambda: {"String": FakeString, "DiagnosticArray": object})
    messages = []
    state = PanelState(notify_web=messages.append)
    node = DebugBridgeNode(FakeNode(), DebugPanelConfig.default(), state, queue.Queue(), messages.append)
    msg = FakeString()
    msg.data = json.dumps(
        {
            "schema_version": "voice_debug_event.v1",
            "timestamp": 1.0,
            "session_id": "s1",
            "event": "agent_result",
            "data": {"commands": [], "reply_text": "收到", "led": None, "requires_confirmation": False},
        },
        ensure_ascii=False,
    )

    node.on_voice_debug_event(msg)

    assert state.agent_result["reply_text"] == "收到"
    assert messages[-1]["type"] == "agent_result"
```

- [ ] **Step 5: Implement ROS node**

Create `src/voice_bridge_debug/voice_bridge_debug/ros_node.py` with imports and:

```python
from __future__ import annotations

import json
import queue
from datetime import datetime, timezone
from typing import Any, Callable

from voice_bridge_debug.config import DebugPanelConfig
from voice_bridge_debug.state import PanelState, parse_json_topic, normalize_health


def _load_ros_messages():
    from diagnostic_msgs.msg import DiagnosticArray
    from std_msgs.msg import String

    return {"DiagnosticArray": DiagnosticArray, "String": String}


class DebugBridgeNode:
    def __init__(
        self,
        node,
        config: DebugPanelConfig,
        state: PanelState,
        asr_publish_queue: queue.Queue,
        notify_web: Callable[[dict[str, Any]], None],
    ):
        self.node = node
        self.config = config
        self.state = state
        self.asr_publish_queue = asr_publish_queue
        self.notify_web = notify_web
        self.msg = _load_ros_messages()
        topics = config.topics
        self.asr_pub = node.create_publisher(self.msg["String"], topics["asr"], 10)
        node.create_subscription(self.msg["String"], topics["voice_state"], self.on_voice_state, 10)
        node.create_subscription(self.msg["String"], topics["voice_debug_events"], self.on_voice_debug_event, 10)
        node.create_subscription(self.msg["String"], topics["robot_mode"], self.on_robot_mode, 10)
        node.create_subscription(self.msg["String"], topics["safety_state"], self.on_safety_state, 10)
        node.create_subscription(self.msg["DiagnosticArray"], topics["health"], self.on_health, 10)
        node.create_subscription(self.msg["String"], topics["voice_cmd_loco"], lambda msg: self.on_string_event("cmd_loco", "command_published", msg), 10)
        node.create_subscription(self.msg["String"], topics["voice_cmd_action"], lambda msg: self.on_string_event("cmd_action", "command_published", msg), 10)
        node.create_subscription(self.msg["String"], topics["tts"], lambda msg: self.on_string_event("tts", "tts_published", msg), 10)
        node.create_subscription(self.msg["String"], topics["led"], lambda msg: self.on_string_event("led", "led_published", msg), 10)
        node.create_subscription(self.msg["String"], topics["safe_cmd_loco"], lambda msg: self.on_string_event("safe_cmd_loco", "safe_command_published", msg), 10)
        node.create_subscription(self.msg["String"], topics["safe_cmd_stop"], lambda msg: self.on_string_event("safe_cmd_stop", "safe_stop_published", msg), 10)
        node.create_subscription(self.msg["String"], topics["safety_decisions"], lambda msg: self.on_string_event("safety_decision", "safety_decision", msg), 10)
        node.create_timer(0.05, self.drain_asr_queue)

    def _now_sec(self) -> float:
        return self.node.get_clock().now().nanoseconds / 1_000_000_000.0

    def drain_asr_queue(self) -> None:
        while True:
            try:
                request = self.asr_publish_queue.get_nowait()
            except queue.Empty:
                return
            payload = dict(request)
            payload["stamp"] = datetime.now(timezone.utc).isoformat()
            msg = self.msg["String"]()
            msg.data = json.dumps(payload, ensure_ascii=False, sort_keys=True)
            self.asr_pub.publish(msg)

    def on_voice_state(self, msg) -> None:
        parsed = parse_json_topic(msg.data)
        data = parsed.get("data")
        if isinstance(data, dict):
            session = data.get("session")
            self.state.set_robot_state(
                voice_session=session if isinstance(session, dict) else None,
                last_asr_text=data.get("last_asr_text"),
                last_decision=data.get("last_decision"),
                last_error=data.get("last_error"),
                agent_backend=data.get("agent_backend"),
            )
        else:
            self.state.push_event("voice_state", "parse_error", parsed, timestamp=self._now_sec())

    def on_voice_debug_event(self, msg) -> None:
        parsed = parse_json_topic(msg.data)
        data = parsed.get("data")
        if not isinstance(data, dict):
            self.state.push_event("voice_debug", "parse_error", parsed, timestamp=self._now_sec())
            return
        event = str(data.get("event", "unknown"))
        session_id = data.get("session_id") if isinstance(data.get("session_id"), str) else None
        event_data = data.get("data") if isinstance(data.get("data"), dict) else {}
        timestamp = float(data.get("timestamp", self._now_sec()))
        if event == "agent_result":
            result = dict(event_data)
            result["session_id"] = session_id
            self.state.set_agent_result(result)
        self.state.push_event("voice_debug", event, event_data, session_id=session_id, timestamp=timestamp)

    def on_robot_mode(self, msg) -> None:
        self.state.set_robot_state(robot_mode=parse_json_topic(msg.data))

    def on_safety_state(self, msg) -> None:
        self.state.set_robot_state(safety_state=parse_json_topic(msg.data))

    def on_health(self, msg) -> None:
        stale_after = self.config.timeline["state_timeout_ms"] / 1000.0
        self.state.set_robot_state(health=normalize_health(msg, self._now_sec(), stale_after, self.state.health))

    def on_string_event(self, source: str, kind: str, msg) -> None:
        self.state.push_event(source, kind, parse_json_topic(msg.data), timestamp=self._now_sec())
```

- [ ] **Step 6: Run ROS node tests**

Run:

```bash
pytest src/voice_bridge_debug/tests/test_ros_node.py -q
```

Expected: pass.

- [ ] **Step 7: Add route tests**

Create `src/voice_bridge_debug/tests/test_routes.py`:

```python
import queue

from fastapi.testclient import TestClient

from voice_bridge_debug.config import DebugPanelConfig
from voice_bridge_debug.routes import create_app
from voice_bridge_debug.state import PanelState
from voice_bridge_debug.ws import WebSocketManager


class FakeServer:
    def __init__(self):
        self.config = DebugPanelConfig.default()
        self.state = PanelState()
        self.asr_publish_queue = queue.Queue()
        self.ws_manager = WebSocketManager()


def test_publish_asr_enqueues_request():
    server = FakeServer()
    client = TestClient(create_app(server))

    response = client.post("/api/asr/publish", json={"text": "小宇向前", "confidence": 0.9, "is_final": True})

    assert response.status_code == 200
    assert response.json() == {"ok": True}
    assert server.asr_publish_queue.get_nowait()["text"] == "小宇向前"


def test_publish_asr_rejects_invalid_confidence():
    client = TestClient(create_app(FakeServer()))

    response = client.post("/api/asr/publish", json={"text": "小宇", "confidence": 2})

    assert response.status_code == 422


def test_state_and_history_routes_return_snapshot():
    server = FakeServer()
    server.state.push_event("asr", "asr_received", {"text": "小宇"}, timestamp=1.0)
    client = TestClient(create_app(server))

    assert client.get("/api/state").status_code == 200
    history = client.get("/api/history?limit=1").json()
    assert history["events"][0]["kind"] == "asr_received"
```

- [ ] **Step 8: Implement routes**

Create `src/voice_bridge_debug/voice_bridge_debug/routes.py`:

```python
from __future__ import annotations

from typing import Any

from fastapi import FastAPI, HTTPException, WebSocket, WebSocketDisconnect
from pydantic import BaseModel, Field


class AsrPublishRequest(BaseModel):
    text: str = Field(min_length=1)
    confidence: float | None = Field(default=None, ge=0.0, le=1.0)
    is_final: bool | None = None
    source: str | None = None


class QuickAsrRequest(BaseModel):
    text: str = Field(min_length=1)


def _asr_payload(server: Any, request: AsrPublishRequest) -> dict[str, Any]:
    return {
        "text": request.text.strip(),
        "confidence": float(request.confidence if request.confidence is not None else server.config.defaults["asr_confidence"]),
        "is_final": bool(request.is_final if request.is_final is not None else server.config.defaults["asr_is_final"]),
        "source": str(request.source or server.config.defaults["asr_source"]),
    }


def create_app(server: Any) -> FastAPI:
    app = FastAPI(title="G1 Voice Bridge Debug Panel")

    @app.on_event("startup")
    async def startup() -> None:
        startup_fn = getattr(server, "startup", None)
        if startup_fn is not None:
            await startup_fn()

    @app.on_event("shutdown")
    async def shutdown() -> None:
        shutdown_fn = getattr(server, "shutdown", None)
        if shutdown_fn is not None:
            await shutdown_fn()

    @app.post("/api/asr/publish")
    async def publish_asr(request: AsrPublishRequest) -> dict[str, bool]:
        server.asr_publish_queue.put(_asr_payload(server, request))
        return {"ok": True}

    @app.post("/api/asr/quick")
    async def quick_asr(request: QuickAsrRequest) -> dict[str, bool]:
        server.asr_publish_queue.put(
            {
                "text": request.text.strip(),
                "confidence": float(server.config.defaults["asr_confidence"]),
                "is_final": bool(server.config.defaults["asr_is_final"]),
                "source": str(server.config.defaults["asr_source"]),
            }
        )
        return {"ok": True}

    @app.get("/api/history")
    async def history(limit: int = 50, offset: int = 0) -> dict[str, Any]:
        if limit <= 0 or offset < 0:
            raise HTTPException(status_code=400, detail="invalid pagination")
        events = server.state.snapshot()["timeline"]
        return {"events": events[offset : offset + limit], "total": len(events)}

    @app.get("/api/config")
    async def config() -> dict[str, Any]:
        return server.config.to_dict()

    @app.get("/api/state")
    async def state() -> dict[str, Any]:
        return server.state.snapshot()

    @app.websocket("/ws")
    async def websocket(ws: WebSocket) -> None:
        await server.ws_manager.connect(ws)
        try:
            await ws.send_json({"type": "connection_status", "data": {"websocket": "connected"}})
            while True:
                await ws.receive_text()
        except WebSocketDisconnect:
            await server.ws_manager.disconnect(ws)

    return app
```

- [ ] **Step 9: Run route tests**

Run:

```bash
pytest src/voice_bridge_debug/tests/test_routes.py -q
```

Expected: pass.

- [ ] **Step 10: Implement server and launch**

Create `src/voice_bridge_debug/voice_bridge_debug/server.py`:

```python
from __future__ import annotations

import argparse
import asyncio
import queue
import threading
from pathlib import Path
from typing import Any

import uvicorn
from fastapi.staticfiles import StaticFiles

from voice_bridge_debug.config import DebugPanelConfig
from voice_bridge_debug.ros_node import DebugBridgeNode
from voice_bridge_debug.routes import create_app
from voice_bridge_debug.state import PanelState
from voice_bridge_debug.ws import WebSocketManager


class DebugBridgeServer:
    def __init__(self, config: DebugPanelConfig, *, prod: bool = False):
        static_dir = Path(__file__).with_name("frontend_dist")
        if prod and not static_dir.exists():
            raise FileNotFoundError(f"frontend static directory not found: {static_dir}")

        import rclpy

        self.rclpy = rclpy
        if not rclpy.ok():
            rclpy.init()
        self.config = config
        self.prod = prod
        self.loop: asyncio.AbstractEventLoop | None = None
        self.web_broadcast_queue: asyncio.Queue | None = None
        self.asr_publish_queue: queue.Queue = queue.Queue()
        self.ws_manager = WebSocketManager()
        self.state = PanelState(max_events=int(config.timeline["max_events"]), notify_web=self.notify_web_from_ros_thread)
        self.node = rclpy.create_node("voice_bridge_debug_node")
        self.ros_node = DebugBridgeNode(self.node, config, self.state, self.asr_publish_queue, self.notify_web_from_ros_thread)
        self._spin_thread: threading.Thread | None = None
        self._broadcast_task: asyncio.Task | None = None
        self.app = create_app(self)
        if prod:
            self.app.mount("/", StaticFiles(directory=static_dir, html=True), name="static")

    async def startup(self) -> None:
        self.loop = asyncio.get_running_loop()
        self.web_broadcast_queue = asyncio.Queue()
        self._broadcast_task = asyncio.create_task(self.broadcast_worker())
        self._spin_thread = threading.Thread(target=self.rclpy.spin, args=(self.node,), daemon=True)
        self._spin_thread.start()

    def notify_web_from_ros_thread(self, message: dict[str, Any]) -> None:
        if self.loop is None or self.web_broadcast_queue is None:
            return
        self.loop.call_soon_threadsafe(self.web_broadcast_queue.put_nowait, message)

    async def broadcast_worker(self) -> None:
        assert self.web_broadcast_queue is not None
        while True:
            message = await self.web_broadcast_queue.get()
            await self.ws_manager.broadcast(message)

    async def shutdown(self) -> None:
        if self._broadcast_task is not None:
            self._broadcast_task.cancel()
        self.node.destroy_node()
        if self.rclpy.ok():
            self.rclpy.shutdown()

    def run(self) -> None:
        if self.config.server["allow_remote"]:
            print("WARNING: debug panel remote access enabled; ASR publishing may trigger robot command chains.")
        uvicorn.run(self.app, host=self.config.server["host"], port=int(self.config.server["port"]))


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--config", default="")
    parser.add_argument("--prod", action="store_true")
    args = parser.parse_args(argv)
    config = DebugPanelConfig.from_yaml(args.config) if args.config else DebugPanelConfig.default()
    DebugBridgeServer(config, prod=args.prod).run()
```

Create `src/voice_bridge_debug/launch/debug_panel.launch.py`:

```python
from launch import LaunchDescription
from launch_ros.actions import Node


def generate_launch_description():
    return LaunchDescription(
        [
            Node(
                package="voice_bridge_debug",
                executable="debug_panel_server",
                name="voice_bridge_debug_node",
                output="screen",
                arguments=[],
            )
        ]
    )
```

- [ ] **Step 11: Run debug backend tests**

Run:

```bash
pytest src/voice_bridge_debug/tests -q
```

Expected: all debug backend tests pass.

- [ ] **Step 12: Build package**

Run:

```bash
source /opt/ros/humble/setup.bash
colcon build --packages-select voice_bridge_debug
```

Expected: build completes with return code 0.

- [ ] **Step 13: Commit backend ROS/FastAPI bridge**

Run:

```bash
git add src/voice_bridge_debug
git commit -m "feat: add voice bridge debug server"
```

Expected: commit succeeds.

---

### Task 4: Build React Debug Panel Frontend

**Files:**
- Create all files under `src/voice_bridge_debug/frontend/`
- Modify only frontend files in this task.

**Interfaces:**
- Consumes REST: `POST /api/asr/publish`, `POST /api/asr/quick`, `GET /api/state`, `GET /api/history`, `GET /api/config`.
- Consumes WebSocket: `/ws` with `robot_state`, `timeline_event`, `agent_result`, `connection_status`.
- Produces build output: `src/voice_bridge_debug/frontend/dist`.

- [ ] **Step 1: Create frontend package files**

Create `src/voice_bridge_debug/frontend/package.json`:

```json
{
  "scripts": {
    "dev": "vite",
    "build": "tsc && vite build",
    "preview": "vite preview"
  },
  "dependencies": {
    "@vitejs/plugin-react": "^4.0.0",
    "vite": "^5.0.0",
    "typescript": "^5.0.0",
    "react": "^18.2.0",
    "react-dom": "^18.2.0",
    "tailwindcss": "^3.4.0",
    "postcss": "^8.4.0",
    "autoprefixer": "^10.4.0",
    "@types/react": "^18.2.0",
    "@types/react-dom": "^18.2.0"
  },
  "devDependencies": {}
}
```

Create `src/voice_bridge_debug/frontend/vite.config.ts`:

```typescript
import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

export default defineConfig({
  plugins: [react()],
  server: {
    proxy: {
      "/api": "http://127.0.0.1:8765",
      "/ws": {
        target: "ws://127.0.0.1:8765",
        ws: true,
      },
    },
  },
});
```

Create `src/voice_bridge_debug/frontend/tailwind.config.js`:

```javascript
module.exports = {
  content: ["./index.html", "./src/**/*.{ts,tsx}"],
  theme: {
    extend: {},
  },
  plugins: [],
};
```

Create `src/voice_bridge_debug/frontend/postcss.config.js`:

```javascript
module.exports = {
  plugins: {
    tailwindcss: {},
    autoprefixer: {},
  },
};
```

Create `src/voice_bridge_debug/frontend/tsconfig.json`:

```json
{
  "compilerOptions": {
    "target": "ES2020",
    "useDefineForClassFields": true,
    "lib": ["DOM", "DOM.Iterable", "ES2020"],
    "allowJs": false,
    "skipLibCheck": true,
    "esModuleInterop": true,
    "allowSyntheticDefaultImports": true,
    "strict": true,
    "forceConsistentCasingInFileNames": true,
    "module": "ESNext",
    "moduleResolution": "Node",
    "resolveJsonModule": true,
    "isolatedModules": true,
    "noEmit": true,
    "jsx": "react-jsx"
  },
  "include": ["src"],
  "references": []
}
```

Create `src/voice_bridge_debug/frontend/index.html`:

```html
<html>
  <head>
    <title>G1 Voice Bridge Debug Panel</title>
  </head>
  <body>
    <div id="root"></div>
    <script type="module" src="/src/main.tsx"></script>
  </body>
</html>
```

- [ ] **Step 2: Create frontend types**

Create `src/voice_bridge_debug/frontend/src/types/index.ts`:

```typescript
export interface ParsedTopicState<T extends Record<string, unknown>> {
  raw?: string;
  parse_error?: string;
  data?: T;
}

export interface RobotModeFields {
  mode?: string | null;
  control_owner?: string | null;
  mode_source?: string | null;
  sport_fsm_mode?: number | null;
  sport_fsm_id?: number | null;
  source?: string | null;
}

export type RobotModeState = ParsedTopicState<RobotModeFields>;

export interface SafetyFields {
  enabled?: boolean;
  strict_mode?: boolean;
  robot_state?: Record<string, unknown>;
  last_decision?: Record<string, unknown> | null;
  last_rejection_reason?: string | null;
  allow_count?: number;
  reject_count?: number;
}

export type SafetyState = ParsedTopicState<SafetyFields>;

export interface HealthState {
  summary: "ok" | "warn" | "error" | "stale" | "unknown";
  max_level: number | null;
  status_count: number;
  raw: Record<string, unknown> | null;
}

export interface VoiceSession {
  state: "IDLE" | "ACTIVE" | "AGENT_PENDING";
  session_id: string | null;
  started_sec: number | null;
  last_activity_sec: number | null;
}

export interface RobotState {
  robot_mode: RobotModeState | null;
  safety_state: SafetyState | null;
  health: HealthState | null;
  voice_session: VoiceSession | null;
  last_asr_text: string | null;
  last_decision: Record<string, unknown> | null;
  last_error: string | null;
  agent_backend: string | null;
}

export interface TimelineEvent {
  timestamp: number;
  source: string;
  kind: string;
  data: Record<string, unknown>;
  session_id: string | null;
}

export interface AgentCommand {
  kind: string;
  params: Record<string, unknown>;
}

export interface AgentResult {
  commands: AgentCommand[];
  reply_text: string | null;
  led: Record<string, unknown> | null;
  requires_confirmation: boolean;
  session_id: string | null;
}

export interface ConnectionStatus {
  websocket: "connecting" | "connected" | "reconnecting" | "disconnected";
  ros_node: "unknown" | "ready" | "stale" | "error";
  last_message_at: number | null;
  reconnect_attempt: number;
  error: string | null;
}

export type WsMessage =
  | { type: "robot_state"; data: RobotState }
  | { type: "timeline_event"; data: TimelineEvent }
  | { type: "agent_result"; data: AgentResult }
  | { type: "connection_status"; data: Partial<ConnectionStatus> };
```

- [ ] **Step 3: Create state reducer**

Create `src/voice_bridge_debug/frontend/src/state/appState.tsx`:

```typescript
import React, { createContext, useContext, useReducer } from "react";
import type { AgentResult, ConnectionStatus, RobotState, TimelineEvent, WsMessage } from "../types";

interface AppState {
  robotState: RobotState | null;
  timeline: TimelineEvent[];
  agentResult: AgentResult | null;
  connectionStatus: ConnectionStatus;
}

const initialState: AppState = {
  robotState: null,
  timeline: [],
  agentResult: null,
  connectionStatus: {
    websocket: "disconnected",
    ros_node: "unknown",
    last_message_at: null,
    reconnect_attempt: 0,
    error: null,
  },
};

type Action =
  | { type: "ws_message"; message: WsMessage }
  | { type: "history"; events: TimelineEvent[] }
  | { type: "state_snapshot"; robotState: RobotState | null; agentResult: AgentResult | null; timeline: TimelineEvent[] }
  | { type: "connection"; status: Partial<ConnectionStatus> };

function reducer(state: AppState, action: Action): AppState {
  if (action.type === "history") {
    return { ...state, timeline: action.events.slice(-200) };
  }
  if (action.type === "state_snapshot") {
    return {
      ...state,
      robotState: action.robotState,
      agentResult: action.agentResult,
      timeline: action.timeline.slice(-200),
    };
  }
  if (action.type === "connection") {
    return { ...state, connectionStatus: { ...state.connectionStatus, ...action.status } };
  }
  const message = action.message;
  if (message.type === "robot_state") {
    return {
      ...state,
      robotState: message.data,
      connectionStatus: { ...state.connectionStatus, last_message_at: Date.now(), ros_node: "ready" },
    };
  }
  if (message.type === "timeline_event") {
    return {
      ...state,
      timeline: [...state.timeline, message.data].slice(-200),
      connectionStatus: { ...state.connectionStatus, last_message_at: Date.now(), ros_node: "ready" },
    };
  }
  if (message.type === "agent_result") {
    return {
      ...state,
      agentResult: message.data,
      connectionStatus: { ...state.connectionStatus, last_message_at: Date.now(), ros_node: "ready" },
    };
  }
  return { ...state, connectionStatus: { ...state.connectionStatus, ...message.data } };
}

const AppStateContext = createContext<{ state: AppState; dispatch: React.Dispatch<Action> } | null>(null);

export function AppStateProvider({ children }: { children: React.ReactNode }) {
  const [state, dispatch] = useReducer(reducer, initialState);
  return <AppStateContext.Provider value={{ state, dispatch }}>{children}</AppStateContext.Provider>;
}

export function useAppState() {
  const context = useContext(AppStateContext);
  if (context === null) {
    throw new Error("useAppState must be used inside AppStateProvider");
  }
  return context;
}
```

- [ ] **Step 4: Create API clients**

Create `src/voice_bridge_debug/frontend/src/api/http.ts`:

```typescript
export async function postJson<T>(url: string, body: unknown): Promise<T> {
  const response = await fetch(url, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
  if (!response.ok) {
    throw new Error(await response.text());
  }
  return response.json() as Promise<T>;
}

export async function getJson<T>(url: string): Promise<T> {
  const response = await fetch(url);
  if (!response.ok) {
    throw new Error(await response.text());
  }
  return response.json() as Promise<T>;
}
```

Create `src/voice_bridge_debug/frontend/src/api/ws.ts`:

```typescript
import type { WsMessage } from "../types";

export function connectWebSocket(
  onMessage: (message: WsMessage) => void,
  onStatus: (status: { websocket: "connecting" | "connected" | "reconnecting" | "disconnected"; reconnect_attempt?: number; error?: string | null }) => void,
): () => void {
  let closed = false;
  let attempt = 0;
  let ws: WebSocket | null = null;

  const open = () => {
    if (closed) return;
    onStatus({ websocket: attempt === 0 ? "connecting" : "reconnecting", reconnect_attempt: attempt });
    const protocol = window.location.protocol === "https:" ? "wss" : "ws";
    ws = new WebSocket(`${protocol}://${window.location.host}/ws`);
    ws.onopen = () => {
      attempt = 0;
      onStatus({ websocket: "connected", reconnect_attempt: 0, error: null });
    };
    ws.onmessage = (event) => onMessage(JSON.parse(event.data) as WsMessage);
    ws.onerror = () => onStatus({ websocket: "reconnecting", error: "WebSocket error" });
    ws.onclose = () => {
      if (closed) return;
      attempt += 1;
      const delay = Math.min(30000, 1000 * 2 ** Math.min(attempt - 1, 5));
      onStatus({ websocket: "reconnecting", reconnect_attempt: attempt });
      window.setTimeout(open, delay);
    };
  };

  open();
  return () => {
    closed = true;
    ws?.close();
    onStatus({ websocket: "disconnected" });
  };
}
```

- [ ] **Step 5: Create components and app**

Create `src/voice_bridge_debug/frontend/src/components/layout/Panel.tsx`:

```tsx
export function Panel({ title, children }: { title: string; children: React.ReactNode }) {
  return (
    <section className="min-h-0 border border-slate-200 bg-white p-4">
      <h2 className="mb-3 text-sm font-semibold uppercase tracking-wide text-slate-600">{title}</h2>
      {children}
    </section>
  );
}
```

Create `src/voice_bridge_debug/frontend/src/components/layout/Header.tsx`:

```tsx
import type { ConnectionStatus } from "../../types";

export function Header({ status }: { status: ConnectionStatus }) {
  const connected = status.websocket === "connected";
  return (
    <header className="flex items-center justify-between border-b border-slate-200 bg-slate-50 px-5 py-3">
      <h1 className="text-base font-semibold text-slate-900">G1 Voice Bridge Debug Panel</h1>
      <div className="flex items-center gap-3 text-sm text-slate-600">
        <span className={connected ? "text-emerald-700" : "text-red-700"}>{status.websocket}</span>
        <span>ROS2: {status.ros_node}</span>
      </div>
    </header>
  );
}
```

Create `src/voice_bridge_debug/frontend/src/components/AsrInput.tsx`:

```tsx
import { useState } from "react";
import { postJson } from "../api/http";

export function AsrInput() {
  const [text, setText] = useState("小宇");
  const [confidence, setConfidence] = useState(0.9);
  const [isFinal, setIsFinal] = useState(true);
  const [source, setSource] = useState("debug");
  const [error, setError] = useState<string | null>(null);

  const send = async () => {
    setError(null);
    try {
      await postJson<{ ok: boolean }>("/api/asr/publish", { text, confidence, is_final: isFinal, source });
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    }
  };

  return (
    <div className="space-y-3">
      <textarea className="h-28 w-full border border-slate-300 p-2 text-sm" value={text} onChange={(event) => setText(event.target.value)} />
      <label className="block text-sm">
        confidence
        <input className="ml-2 w-24 border border-slate-300 px-2 py-1" type="number" min={0} max={1} step={0.01} value={confidence} onChange={(event) => setConfidence(Number(event.target.value))} />
      </label>
      <label className="flex items-center gap-2 text-sm">
        <input type="checkbox" checked={isFinal} onChange={(event) => setIsFinal(event.target.checked)} />
        is_final
      </label>
      <input className="w-full border border-slate-300 px-2 py-1 text-sm" value={source} onChange={(event) => setSource(event.target.value)} />
      <button className="w-full bg-slate-900 px-3 py-2 text-sm font-medium text-white" onClick={send}>发送 ASR</button>
      {error ? <p className="text-sm text-red-700">{error}</p> : null}
    </div>
  );
}
```

Create `src/voice_bridge_debug/frontend/src/components/AgentOutput.tsx`, `DecisionTimeline.tsx`, and `RobotStatus.tsx` with simple JSON-safe rendering:

```tsx
// AgentOutput.tsx
import type { AgentResult } from "../types";

export function AgentOutput({ result }: { result: AgentResult | null }) {
  if (!result) return <p className="text-sm text-slate-500">No agent result yet.</p>;
  return (
    <div className="space-y-3 text-sm">
      <div>reply: {result.reply_text ?? "null"}</div>
      <div>requires_confirmation: {String(result.requires_confirmation)}</div>
      <pre className="max-h-64 overflow-auto bg-slate-50 p-2">{JSON.stringify(result.commands, null, 2)}</pre>
    </div>
  );
}
```

```tsx
// DecisionTimeline.tsx
import type { TimelineEvent } from "../types";

export function DecisionTimeline({ events }: { events: TimelineEvent[] }) {
  return (
    <div className="h-full space-y-2 overflow-auto text-sm">
      {events.length === 0 ? <p className="text-slate-500">No events yet.</p> : null}
      {events.map((event, index) => (
        <details key={`${event.timestamp}-${index}`} className="border-l-2 border-slate-300 pl-3">
          <summary>{new Date(event.timestamp * 1000).toLocaleTimeString()} {event.source}: {event.kind}</summary>
          {event.source === "voice_debug" && event.kind === "agent_result" && !events.some((item) => item.kind === "agent_tool_event") ? (
            <p className="my-2 text-slate-500">未提供工具事件</p>
          ) : null}
          <pre className="mt-2 overflow-auto bg-slate-50 p-2">{JSON.stringify(event.data, null, 2)}</pre>
        </details>
      ))}
    </div>
  );
}
```

```tsx
// RobotStatus.tsx
import type { ConnectionStatus, RobotState } from "../types";

export function RobotStatus({ state, connection }: { state: RobotState | null; connection: ConnectionStatus }) {
  return (
    <div className="space-y-3 text-sm">
      <div>WebSocket: {connection.websocket}</div>
      <div>ROS2: {connection.ros_node}</div>
      <div>Health: {state?.health?.summary ?? "unknown"}</div>
      <div>Session: {state?.voice_session?.state ?? "unknown"}</div>
      <div>Agent Backend: {state?.agent_backend ?? "unknown"}</div>
      <pre className="max-h-64 overflow-auto bg-slate-50 p-2">{JSON.stringify({ mode: state?.robot_mode, safety: state?.safety_state, last_error: state?.last_error }, null, 2)}</pre>
    </div>
  );
}
```

Create `src/voice_bridge_debug/frontend/src/App.tsx`:

```tsx
import { useEffect } from "react";
import { connectWebSocket } from "./api/ws";
import { getJson } from "./api/http";
import { AgentOutput } from "./components/AgentOutput";
import { AsrInput } from "./components/AsrInput";
import { DecisionTimeline } from "./components/DecisionTimeline";
import { RobotStatus } from "./components/RobotStatus";
import { Header } from "./components/layout/Header";
import { Panel } from "./components/layout/Panel";
import { AppStateProvider, useAppState } from "./state/appState";
import type { AgentResult, RobotState, TimelineEvent } from "./types";
import "./style.css";

interface Snapshot {
  robot_state: RobotState | null;
  agent_result: AgentResult | null;
  timeline: TimelineEvent[];
}

function AppBody() {
  const { state, dispatch } = useAppState();
  useEffect(() => {
    const stop = connectWebSocket(
      (message) => dispatch({ type: "ws_message", message }),
      (status) => dispatch({ type: "connection", status }),
    );
    Promise.all([getJson<Snapshot>("/api/state"), getJson<{ events: TimelineEvent[] }>("/api/history?limit=200")]).then(([snapshot, history]) => {
      dispatch({ type: "state_snapshot", robotState: snapshot.robot_state, agentResult: snapshot.agent_result, timeline: history.events });
    });
    return stop;
  }, [dispatch]);

  return (
    <div className="flex h-screen flex-col bg-slate-100 text-slate-900">
      <Header status={state.connectionStatus} />
      <main className="grid min-h-0 flex-1 grid-cols-1 gap-3 p-3 lg:grid-cols-[360px_1fr] lg:grid-rows-2">
        <Panel title="ASR 输入"><AsrInput /></Panel>
        <Panel title="决策时间线"><DecisionTimeline events={state.timeline} /></Panel>
        <Panel title="Agent 输出"><AgentOutput result={state.agentResult} /></Panel>
        <Panel title="机器人状态"><RobotStatus state={state.robotState} connection={state.connectionStatus} /></Panel>
      </main>
    </div>
  );
}

export default function App() {
  return (
    <AppStateProvider>
      <AppBody />
    </AppStateProvider>
  );
}
```

Create `src/voice_bridge_debug/frontend/src/main.tsx`:

```tsx
import React from "react";
import ReactDOM from "react-dom/client";
import App from "./App";

ReactDOM.createRoot(document.getElementById("root")!).render(
  <React.StrictMode>
    <App />
  </React.StrictMode>,
);
```

Create `src/voice_bridge_debug/frontend/src/style.css`:

```css
@tailwind base;
@tailwind components;
@tailwind utilities;

body {
  margin: 0;
}
```

- [ ] **Step 6: Build frontend**

Run:

```bash
cd src/voice_bridge_debug/frontend
npm install
npm run build
```

Expected: TypeScript and Vite build pass and `dist/` is created.

- [ ] **Step 7: Commit frontend**

Run:

```bash
git add src/voice_bridge_debug/frontend
git commit -m "feat: add voice bridge debug frontend"
```

Expected: commit succeeds.

---

### Task 5: Production Static Packaging and End-to-End Verification

**Files:**
- Modify: `src/voice_bridge_debug/setup.py`
- Modify: `src/voice_bridge_debug/voice_bridge_debug/server.py`
- Test: `src/voice_bridge_debug/tests/test_routes.py`
- Documentation: no new docs unless commands or paths differ from the approved spec.

**Interfaces:**
- Consumes frontend build output: `src/voice_bridge_debug/frontend/dist`.
- Produces package data directory: `voice_bridge_debug/frontend_dist`.
- Produces production mode: `ros2 run voice_bridge_debug debug_panel_server -- --prod`.

- [ ] **Step 1: Add static-dir regression test**

Append to `src/voice_bridge_debug/tests/test_routes.py`:

```python
def test_prod_mode_requires_static_directory(tmp_path, monkeypatch):
    import pytest

    from voice_bridge_debug.config import DebugPanelConfig
    from voice_bridge_debug.server import DebugBridgeServer

    monkeypatch.setattr("voice_bridge_debug.server.Path.with_name", lambda self, name: tmp_path / "missing")

    with pytest.raises(FileNotFoundError, match="frontend static directory"):
        DebugBridgeServer(DebugPanelConfig.default(), prod=True)
```

- [ ] **Step 2: Run static-dir test**

Run:

```bash
pytest src/voice_bridge_debug/tests/test_routes.py::test_prod_mode_requires_static_directory -q
```

Expected: pass because Task 3 checks the production static directory before initializing ROS.

- [ ] **Step 3: Copy frontend build into package data directory**

Run:

```bash
rm -rf src/voice_bridge_debug/voice_bridge_debug/frontend_dist
mkdir -p src/voice_bridge_debug/voice_bridge_debug/frontend_dist
cp -R src/voice_bridge_debug/frontend/dist/. src/voice_bridge_debug/voice_bridge_debug/frontend_dist/
```

Expected: `src/voice_bridge_debug/voice_bridge_debug/frontend_dist/index.html` exists.

- [ ] **Step 4: Include static files in setup.py**

Modify `src/voice_bridge_debug/setup.py` to import `os` and collect static files:

```python
import os
from glob import glob


def package_files(directory):
    paths = []
    for path, _, filenames in os.walk(directory):
        for filename in filenames:
            full_path = os.path.join(path, filename)
            paths.append(os.path.relpath(full_path, package_name))
    return paths
```

Then add:

```python
package_data={package_name: package_files(f"{package_name}/frontend_dist")},
include_package_data=True,
```

to `setup(...)`.

- [ ] **Step 5: Run full Python tests**

Run:

```bash
pytest src/voice_bridge/tests src/voice_bridge_debug/tests -q
```

Expected: all tests pass.

- [ ] **Step 6: Build frontend and ROS package**

Run:

```bash
cd src/voice_bridge_debug/frontend
npm run build
cd /home/ubuntu/Desktop/unitree_g1_agent
rm -rf src/voice_bridge_debug/voice_bridge_debug/frontend_dist
mkdir -p src/voice_bridge_debug/voice_bridge_debug/frontend_dist
cp -R src/voice_bridge_debug/frontend/dist/. src/voice_bridge_debug/voice_bridge_debug/frontend_dist/
source /opt/ros/humble/setup.bash
colcon build --packages-select voice_bridge voice_bridge_debug
```

Expected: frontend build and colcon build both pass.

- [ ] **Step 7: Run smoke server**

Run:

```bash
source /opt/ros/humble/setup.bash
source install/setup.bash
python -m voice_bridge_debug.server --prod
```

Expected: server starts on `127.0.0.1:8765`. Stop it with Ctrl-C after confirming startup. If `python -m` does not work after install, use:

```bash
ros2 run voice_bridge_debug debug_panel_server -- --prod
```

- [ ] **Step 8: Verify default remote guard manually**

Run:

```bash
python - <<'PY'
from voice_bridge_debug.config import DebugPanelConfig
raw = DebugPanelConfig.default().to_dict()
raw["server"]["host"] = "0.0.0.0"
raw["server"]["allow_remote"] = False
try:
    DebugPanelConfig.from_dict(raw)
except ValueError as exc:
    print(str(exc))
PY
```

Expected output contains:

```text
allow_remote
```

- [ ] **Step 9: Commit packaging and verification updates**

Run:

```bash
git add src/voice_bridge_debug
git commit -m "feat: package voice bridge debug panel"
```

Expected: commit succeeds.

---

## Final Verification Checklist

- [ ] `pytest src/voice_bridge/tests src/voice_bridge_debug/tests -q` passes.
- [ ] `cd src/voice_bridge_debug/frontend && npm run build` passes.
- [ ] `source /opt/ros/humble/setup.bash && colcon build --packages-select voice_bridge voice_bridge_debug` passes.
- [ ] `ros2 topic echo /voice/debug/events` shows `voice_debug_event.v1` when ASR is processed.
- [ ] Stop/cancel flow appears as `/voice/cmd/action` → `/g1/safety/decisions` → `/g1/safe_cmd/stop`.
- [ ] Default server binds `127.0.0.1:8765`.
- [ ] Non-loopback host without `allow_remote: true` fails config validation.
- [ ] Frontend shows four panels and reconnects WebSocket after server restart.
