# Pi Agent Integration Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a `pi_rpc` agent backend to `src/voice_bridge` that runs Pi Agent as a JSONL RPC subprocess, maps only confirmed `robot_*` tool calls into validated `AgentResult` output, and lets stop/cancel interrupt an active Pi turn without changing the ROS motion safety boundary.

**Architecture:** Keep `AgentClient.decide()` as the stable contract and add an optional `abort()`/`close()` capability detected by `hasattr` in `node.py`. Put Pi subprocess configuration in `pi_config.py`, JSONL lifecycle and event routing in `PiRpcTransport`, result mapping and safety validation in `PiRpcAgentClient`, and robot tool registration in `.agent-runtime/.unitree_agent/.pi/extensions/robot-tools.ts`.

**Tech Stack:** Python 3.10+, ROS2/rclpy node code, stdlib `subprocess`/`threading`/`queue`, pytest, TypeScript Pi extension API (`@earendil-works/pi-ai`, `@earendil-works/pi-coding-agent`).

## Global Constraints

- Do not route Pi built-in tools directly to ROS topics; only Python-confirmed `robot_*` custom tool events may become `AgentCommand`s.
- Pi is not an OS sandbox. It keeps current-user file and command capability except for scrubbed environment variables.
- Stop/cancel detection stays inside `voice_bridge`, publishes emergency action first, then calls non-blocking `abort()`.
- Pi crash, timeout, invalid JSON, invalid result, or missing `agent_end` must produce no motion commands.
- P0 supports one ASR final text to one Pi turn; a normal turn may return multiple motion commands in tool start order.
- `robot_led` maps only to `AgentResult.led`, never to `AgentResult.commands`.
- Use `--no-session`; session reuse is only in-process and is reset via `new_session` followed by `get_state`.
- Do not compute repository paths from `__file__`; resolve from an explicit `repo_root` argument or by searching upward from `Path.cwd()`.
- Run unit tests with `PYTHONPATH=src/voice_bridge pytest ...`. Integration tests requiring real Pi use `PI_AGENT_INTEGRATION=1`.

---

## File Structure

- Create `src/voice_bridge/voice_bridge/pi_types.py`: optional closeable protocol, custom tool constants, timeout defaults, blocked environment prefixes, and lightweight type aliases.
- Create `src/voice_bridge/voice_bridge/pi_config.py`: workspace resolution, repo-root discovery, command building, environment scrubbing, and Pi config validation helper.
- Create `src/voice_bridge/voice_bridge/pi_agent.py`: `PiTransportError`, `PiRpcTransport`, `PiRpcAgentClient`, tool event accumulation, reply extraction, result finalization, and validation helpers.
- Modify `src/voice_bridge/voice_bridge/config.py`: add `pi_rpc` backend validation and default `agent.pi` config.
- Modify `src/voice_bridge/voice_bridge/agent.py`: add `pi_rpc` branch in `build_agent_client`.
- Modify `src/voice_bridge/voice_bridge/node.py`: detect optional `abort`/`close`, abort on stop/cancel after publishing emergency action, close on shutdown.
- Modify `src/voice_bridge/config/voice_bridge.yaml`: add the `agent.pi` configuration block while keeping default backend as `rule_based`.
- Create `.agent-runtime/.unitree_agent/.pi/extensions/robot-tools.ts`: Pi extension registering `robot_walk`, `robot_stop`, `robot_say`, and `robot_led`.
- Create `src/voice_bridge/tests/test_pi_config.py`: config, command, workspace, and environment tests.
- Create `src/voice_bridge/tests/test_pi_transport.py`: JSONL framing, response correlation, event queue, wakeup, close, and generation tests.
- Create `src/voice_bridge/tests/test_pi_agent.py`: mocked transport tests for prompt/session flow, tool mapping, validation, safety filtering, abort, timeout, and close.
- Create `src/voice_bridge/tests/test_pi_integration.py`: skipped-by-default real Pi smoke tests.
- Modify `src/voice_bridge/tests/test_config.py`: default and validation coverage for `pi_rpc`.
- Modify `src/voice_bridge/tests/test_node_helpers.py`: optional closeable detection and stop/shutdown behavior tests.
- Modify `src/voice_bridge/README.md`: document `pi_rpc` setup, environment variables, safety boundary, and integration test command.

---

### Task 1: Pi Config, Types, and Backend Factory

**Files:**
- Create: `src/voice_bridge/voice_bridge/pi_types.py`
- Create: `src/voice_bridge/voice_bridge/pi_config.py`
- Create: `src/voice_bridge/tests/test_pi_config.py`
- Modify: `src/voice_bridge/voice_bridge/config.py`
- Modify: `src/voice_bridge/voice_bridge/agent.py`
- Modify: `src/voice_bridge/config/voice_bridge.yaml`
- Modify: `src/voice_bridge/tests/test_config.py`

**Interfaces:**
- Produces: `OptionalCloseableAgent.abort() -> None`, `OptionalCloseableAgent.close() -> None`
- Produces: `resolve_repo_root(start: Path | None = None) -> Path`
- Produces: `resolve_workspace(pi_config: dict[str, Any], repo_root: Path) -> Path`
- Produces: `build_pi_command(pi_config: dict[str, Any], workspace: Path) -> list[str]`
- Produces: `scrubbed_env(pi_config: dict[str, Any], base_env: Mapping[str, str] | None = None) -> dict[str, str]`
- Produces: `validate_pi_config(pi_config: object) -> None`
- Produces: `DEFAULT_PI_CONFIG: dict[str, Any]`
- Consumes: existing `VoiceBridgeConfig`, `AgentClient`, `build_agent_client(config)`

- [ ] **Step 1: Write failing config and factory tests**

Add `src/voice_bridge/tests/test_pi_config.py`:

```python
from pathlib import Path

import pytest

from voice_bridge.pi_config import (
    DEFAULT_PI_CONFIG,
    build_pi_command,
    resolve_repo_root,
    resolve_workspace,
    scrubbed_env,
    validate_pi_config,
)


def test_resolve_workspace_defaults_under_repo_root(tmp_path: Path):
    workspace = resolve_workspace({}, tmp_path)

    assert workspace == tmp_path / ".agent-runtime" / ".unitree_agent"


def test_resolve_workspace_accepts_absolute_path(tmp_path: Path):
    absolute = tmp_path / "pi-workspace"

    assert resolve_workspace({"workspace": str(absolute)}, tmp_path) == absolute


def test_resolve_repo_root_searches_for_git_marker(tmp_path: Path):
    root = tmp_path / "repo"
    child = root / "src" / "voice_bridge"
    child.mkdir(parents=True)
    (root / ".git").mkdir()

    assert resolve_repo_root(child) == root


def test_build_pi_command_loads_robot_tools_when_present(tmp_path: Path):
    workspace = tmp_path / ".agent-runtime" / ".unitree_agent"
    tools = workspace / ".pi" / "extensions" / "robot-tools.ts"
    tools.parent.mkdir(parents=True)
    tools.write_text("export default function() {}", encoding="utf-8")

    command = build_pi_command(
        {
            "command": "pi",
            "args": ["--mode", "rpc", "--no-session"],
            "model": "gpt-5-mini",
            "provider": "openai",
            "extensions": ["extra.ts"],
        },
        workspace,
    )

    assert command == [
        "pi",
        "--mode",
        "rpc",
        "--no-session",
        "--model",
        "gpt-5-mini",
        "--provider",
        "openai",
        "-e",
        str(tools),
        "-e",
        "extra.ts",
        "--append-system-prompt",
        DEFAULT_PI_CONFIG["append_system_prompt"],
    ]


def test_scrubbed_env_removes_ros_dds_and_ssh_values():
    env = scrubbed_env(
        {
            "env_keep": ["HOME", "PATH", "ROS_DOMAIN_ID", "OPENAI_API_KEY"],
            "env_extra": {"SAFE_VALUE": "1", "ROS_LOCALHOST_ONLY": "1"},
        },
        base_env={
            "HOME": "/home/test",
            "PATH": "/usr/bin",
            "ROS_DOMAIN_ID": "7",
            "RMW_IMPLEMENTATION": "rmw",
            "CYCLONEDDS_URI": "file.xml",
            "SSH_AUTH_SOCK": "sock",
            "OPENAI_API_KEY": "sk-test",
        },
    )

    assert env == {
        "HOME": "/home/test",
        "PATH": "/usr/bin",
        "OPENAI_API_KEY": "sk-test",
        "SAFE_VALUE": "1",
    }


@pytest.mark.parametrize(
    ("pi_config", "message"),
    [
        ([], "agent.pi must be a mapping"),
        ({"enabled": False}, "agent.backend=pi_rpc requires agent.pi.enabled=true"),
        ({"command": ""}, "agent.pi.command must be non-empty string"),
        ({"args": "--mode rpc"}, "agent.pi.args must be list\\[str\\]"),
        ({"extensions": [1]}, "agent.pi.extensions must be list\\[str\\]"),
        ({"env_keep": ["ROS_DOMAIN_ID"]}, "agent.pi.env_keep key 'ROS_DOMAIN_ID' is not allowed"),
        ({"env_extra": {"SSH_AUTH_SOCK": "sock"}}, "agent.pi.env_extra key 'SSH_AUTH_SOCK' is not allowed"),
        ({"timeouts": {"restart_max_attempts": 0}}, "restart_max_attempts must be positive integer"),
    ],
)
def test_validate_pi_config_rejects_invalid_values(pi_config, message):
    with pytest.raises(ValueError, match=message):
        validate_pi_config(pi_config)
```

Extend `src/voice_bridge/tests/test_config.py`:

```python
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
```

- [ ] **Step 2: Run tests to verify failure**

Run:

```bash
PYTHONPATH=src/voice_bridge pytest src/voice_bridge/tests/test_pi_config.py src/voice_bridge/tests/test_config.py -q
```

Expected: failures for missing `voice_bridge.pi_config`, missing `agent.pi`, and unsupported `pi_rpc` backend.

- [ ] **Step 3: Add `pi_types.py`**

Create `src/voice_bridge/voice_bridge/pi_types.py`:

```python
from __future__ import annotations

from typing import Any, Protocol


class OptionalCloseableAgent(Protocol):
    def abort(self) -> None:
        ...

    def close(self) -> None:
        ...


CUSTOM_TOOLS: dict[str, str] = {
    "robot_walk": "loco",
    "robot_stop": "action",
    "robot_say": "say",
    "robot_led": "led",
}

BLOCKED_ENV_PREFIXES = ("ROS_", "RMW_", "CYCLONEDDS_", "SSH_", "GIT_SSH_")

DEFAULT_PI_TIMEOUTS: dict[str, float | int] = {
    "startup_health_sec": 20.0,
    "command_response_sec": 5.0,
    "first_event_sec": 15.0,
    "motion_turn_hard_sec": 25.0,
    "conversational_turn_sec": 60.0,
    "idle_health_check_sec": 30.0,
    "stall_detection_sec": 60.0,
    "restart_backoff_max_sec": 30.0,
    "restart_max_attempts": 5,
}

PiEvent = dict[str, Any]
```

- [ ] **Step 4: Add `pi_config.py`**

Create `src/voice_bridge/voice_bridge/pi_config.py`:

```python
from __future__ import annotations

import os
from copy import deepcopy
from pathlib import Path
from typing import Any, Mapping

from voice_bridge.pi_types import BLOCKED_ENV_PREFIXES, DEFAULT_PI_TIMEOUTS

DEFAULT_PI_WORKSPACE = Path(".agent-runtime") / ".unitree_agent"

ROBOT_APPEND_SYSTEM_PROMPT = (
    "You control a Unitree G1 robot only by calling robot_* tools. "
    "Use robot_walk for movement, robot_stop for immediate stop, robot_say for speech, "
    "and robot_led for LED color. Motion safety limits are enforced outside Pi by voice_bridge."
)

DEFAULT_PI_CONFIG: dict[str, Any] = {
    "enabled": True,
    "command": "pi",
    "args": ["--mode", "rpc", "--no-session"],
    "workspace": str(DEFAULT_PI_WORKSPACE),
    "model": "",
    "provider": "",
    "extensions": [],
    "env_keep": ["HOME", "PATH", "NODE_PATH", "ANTHROPIC_API_KEY", "OPENAI_API_KEY", "GEMINI_API_KEY"],
    "env_extra": {},
    "timeouts": deepcopy(DEFAULT_PI_TIMEOUTS),
    "append_system_prompt": ROBOT_APPEND_SYSTEM_PROMPT,
}


def _blocked(key: str) -> bool:
    return key.startswith(BLOCKED_ENV_PREFIXES)


def resolve_repo_root(start: Path | None = None) -> Path:
    current = (start or Path.cwd()).resolve()
    if current.is_file():
        current = current.parent
    for candidate in [current, *current.parents]:
        if (candidate / ".git").exists():
            return candidate
    return current


def resolve_workspace(pi_config: dict[str, Any], repo_root: Path) -> Path:
    raw = pi_config.get("workspace") or str(DEFAULT_PI_WORKSPACE)
    path = Path(str(raw))
    if not path.is_absolute():
        path = repo_root / path
    return path


def build_pi_command(pi_config: dict[str, Any], workspace: Path) -> list[str]:
    command = str(pi_config.get("command") or "pi")
    args = pi_config.get("args", ["--mode", "rpc", "--no-session"])
    cmd = [command, *list(args)]
    model = str(pi_config.get("model") or "")
    provider = str(pi_config.get("provider") or "")
    if model:
        cmd.extend(["--model", model])
    if provider:
        cmd.extend(["--provider", provider])
    robot_tools = workspace / ".pi" / "extensions" / "robot-tools.ts"
    if robot_tools.exists():
        cmd.extend(["-e", str(robot_tools)])
    for extension in pi_config.get("extensions", []):
        cmd.extend(["-e", str(extension)])
    append_prompt = str(pi_config.get("append_system_prompt") or "")
    if append_prompt:
        cmd.extend(["--append-system-prompt", append_prompt])
    return cmd


def scrubbed_env(pi_config: dict[str, Any], base_env: Mapping[str, str] | None = None) -> dict[str, str]:
    source = dict(os.environ if base_env is None else base_env)
    keep = set(pi_config.get("env_keep", DEFAULT_PI_CONFIG["env_keep"]))
    keep = {key for key in keep if not _blocked(str(key))}
    env = {key: value for key, value in source.items() if key in keep and not _blocked(key)}
    for key, value in pi_config.get("env_extra", {}).items():
        if not _blocked(str(key)):
            env[str(key)] = str(value)
    return env


def validate_pi_config(pi_config: object) -> None:
    if not isinstance(pi_config, dict):
        raise ValueError("agent.pi must be a mapping")
    enabled = pi_config.get("enabled", True)
    if not isinstance(enabled, bool):
        raise ValueError("agent.pi.enabled must be boolean")
    if not enabled:
        raise ValueError("agent.backend=pi_rpc requires agent.pi.enabled=true")
    command = pi_config.get("command", "pi")
    if not isinstance(command, str) or not command:
        raise ValueError("agent.pi.command must be non-empty string")
    workspace = pi_config.get("workspace", str(DEFAULT_PI_WORKSPACE))
    if not isinstance(workspace, str):
        raise ValueError("agent.pi.workspace must be string")
    args = pi_config.get("args", ["--mode", "rpc", "--no-session"])
    if not isinstance(args, list) or any(not isinstance(item, str) for item in args):
        raise ValueError("agent.pi.args must be list[str]")
    extensions = pi_config.get("extensions", [])
    if not isinstance(extensions, list) or any(not isinstance(item, str) for item in extensions):
        raise ValueError("agent.pi.extensions must be list[str]")
    for key in ("model", "provider", "append_system_prompt"):
        if key in pi_config and pi_config[key] is not None and not isinstance(pi_config[key], str):
            raise ValueError(f"agent.pi.{key} must be string")
    env_keep = pi_config.get("env_keep", DEFAULT_PI_CONFIG["env_keep"])
    if not isinstance(env_keep, list) or any(not isinstance(item, str) or not item for item in env_keep):
        raise ValueError("agent.pi.env_keep must be a non-empty string list")
    for key in env_keep:
        if _blocked(key):
            raise ValueError(f"agent.pi.env_keep key '{key}' is not allowed")
    env_extra = pi_config.get("env_extra", {})
    if not isinstance(env_extra, dict):
        raise ValueError("agent.pi.env_extra must be mapping")
    for key in env_extra:
        if not isinstance(key, str):
            raise ValueError("agent.pi.env_extra keys must be strings")
        if _blocked(key):
            raise ValueError(f"agent.pi.env_extra key '{key}' is not allowed")
    timeouts = pi_config.get("timeouts", {})
    if not isinstance(timeouts, dict):
        raise ValueError("agent.pi.timeouts must be mapping")
    for key, value in timeouts.items():
        if key == "restart_max_attempts":
            if not isinstance(value, int) or value <= 0:
                raise ValueError("agent.pi.timeouts.restart_max_attempts must be positive integer")
        elif isinstance(value, bool) or not isinstance(value, (int, float)) or value <= 0:
            raise ValueError(f"agent.pi.timeouts.{key} must be positive")
```

- [ ] **Step 5: Extend default config and validation**

In `src/voice_bridge/voice_bridge/config.py`, import `DEFAULT_PI_CONFIG` and `validate_pi_config`, add `pi` under `DEFAULT_CONFIG["agent"]`, and accept `pi_rpc`:

```python
from voice_bridge.pi_config import DEFAULT_PI_CONFIG, validate_pi_config
```

```python
"agent": {
    "backend": "rule_based",
    "http_endpoint": "",
    "timeout_sec": 2.0,
    "pi": deepcopy(DEFAULT_PI_CONFIG),
},
```

Replace backend validation block with:

```python
backend = self.agent.get("backend")
if backend not in {"rule_based", "http_json", "pi_rpc", "disabled"}:
    raise ValueError(f"unsupported agent backend: {backend}")
_require_number(self.agent, "timeout_sec", positive=True)
if backend == "http_json" and not self.agent.get("http_endpoint"):
    raise ValueError("http_json backend requires http_endpoint")
if backend == "pi_rpc":
    validate_pi_config(self.agent.get("pi", {}))
```

- [ ] **Step 6: Extend backend factory**

In `src/voice_bridge/voice_bridge/agent.py`, update `build_agent_client`:

```python
def build_agent_client(config: VoiceBridgeConfig) -> AgentClient:
    backend = config.agent["backend"]
    if backend == "rule_based":
        return RuleBasedAgentClient(config)
    if backend == "http_json":
        return HttpJsonAgentClient(config)
    if backend == "pi_rpc":
        from voice_bridge.pi_agent import PiRpcAgentClient

        return PiRpcAgentClient(config)
    return DisabledAgentClient()
```

- [ ] **Step 7: Extend YAML config**

In `src/voice_bridge/config/voice_bridge.yaml`, keep `backend: rule_based` and add:

```yaml
  pi:
    enabled: true
    command: "pi"
    args: ["--mode", "rpc", "--no-session"]
    workspace: ".agent-runtime/.unitree_agent"
    model: ""
    provider: ""
    extensions: []
    env_keep:
      - HOME
      - PATH
      - NODE_PATH
      - ANTHROPIC_API_KEY
      - OPENAI_API_KEY
      - GEMINI_API_KEY
    env_extra: {}
    timeouts:
      startup_health_sec: 20.0
      command_response_sec: 5.0
      first_event_sec: 15.0
      motion_turn_hard_sec: 25.0
      conversational_turn_sec: 60.0
      idle_health_check_sec: 30.0
      stall_detection_sec: 60.0
      restart_backoff_max_sec: 30.0
      restart_max_attempts: 5
```

- [ ] **Step 8: Run tests and commit**

Run:

```bash
PYTHONPATH=src/voice_bridge pytest src/voice_bridge/tests/test_pi_config.py src/voice_bridge/tests/test_config.py -q
```

Expected: all selected tests pass.

Commit:

```bash
git add src/voice_bridge/voice_bridge/pi_types.py src/voice_bridge/voice_bridge/pi_config.py src/voice_bridge/voice_bridge/config.py src/voice_bridge/voice_bridge/agent.py src/voice_bridge/config/voice_bridge.yaml src/voice_bridge/tests/test_pi_config.py src/voice_bridge/tests/test_config.py
git commit -m "feat: add pi rpc configuration"
```

---

### Task 2: PiRpcTransport JSONL Lifecycle

**Files:**
- Create: `src/voice_bridge/tests/test_pi_transport.py`
- Create/Modify: `src/voice_bridge/voice_bridge/pi_agent.py`

**Interfaces:**
- Consumes: `PiEvent` from `pi_types.py`
- Produces: `class PiTransportError(RuntimeError)`
- Produces: `class PiRpcTransport`
- Produces: `PiRpcTransport.start(command: list[str], cwd: Path, env: dict[str, str]) -> None`
- Produces: `PiRpcTransport.send(command: dict[str, Any], timeout: float = 5.0) -> dict[str, Any]`
- Produces: `PiRpcTransport.get_event(expected_generation: int, timeout: float = 5.0) -> tuple[int, dict[str, Any]] | None`
- Produces: `PiRpcTransport.wake_events(reason: str) -> None`
- Produces: `PiRpcTransport.current_generation() -> int`
- Produces: `PiRpcTransport.close() -> None`

- [ ] **Step 1: Write failing transport tests**

Add `src/voice_bridge/tests/test_pi_transport.py`:

```python
import io
import json
import queue
import threading
import time
from pathlib import Path

import pytest

from voice_bridge.pi_agent import PiRpcTransport, PiTransportError


class FakeStdin(io.StringIO):
    def __init__(self):
        super().__init__()
        self.lines: list[dict] = []

    def write(self, value: str) -> int:
        self.lines.append(json.loads(value))
        return len(value)

    def flush(self) -> None:
        return None


class FakeProc:
    def __init__(self, stdout_lines: list[bytes]):
        self.stdin = FakeStdin()
        self.stdout = iter(stdout_lines)
        self.stderr = iter([])
        self.pid = 4242
        self.returncode = None
        self.wait_called = False

    def wait(self, timeout=None):
        self.wait_called = True
        self.returncode = 0
        return 0


def make_transport(proc: FakeProc) -> PiRpcTransport:
    transport = PiRpcTransport(popen_factory=lambda *args, **kwargs: proc)
    transport.start(["pi", "--mode", "rpc"], Path("."), {})
    return transport


def test_send_correlates_response_by_id(monkeypatch):
    proc = FakeProc([])
    transport = make_transport(proc)

    def responder():
        deadline = time.monotonic() + 1
        while not proc.stdin.lines and time.monotonic() < deadline:
            time.sleep(0.01)
        request_id = proc.stdin.lines[0]["id"]
        transport._route_message({"type": "response", "id": request_id, "success": True, "data": {"ok": True}})

    thread = threading.Thread(target=responder)
    thread.start()
    response = transport.send({"type": "get_state"}, timeout=1.0)
    thread.join(timeout=1)

    assert response["data"] == {"ok": True}
    assert proc.stdin.lines[0]["type"] == "get_state"


def test_route_message_puts_events_in_generation_queue():
    transport = PiRpcTransport()
    generation = transport.current_generation()

    transport._route_message({"type": "tool_execution_start", "toolCallId": "t1"})

    assert transport.get_event(generation, timeout=0.1) == (
        generation,
        {"type": "tool_execution_start", "toolCallId": "t1"},
    )


def test_get_event_discards_old_generation_events():
    transport = PiRpcTransport()
    old_generation = transport.current_generation()
    transport._route_message({"type": "agent_end"})
    new_generation = transport._bump_generation()
    transport.wake_events("restart")

    assert transport.get_event(new_generation, timeout=0.1) == (
        new_generation,
        {"type": "_transport_wakeup", "reason": "restart"},
    )
    assert transport.get_event(old_generation, timeout=0.01) is None


def test_reader_finally_wakes_pending_and_event_waiters():
    proc = FakeProc([])
    transport = make_transport(proc)
    generation = transport.current_generation()

    response_q: queue.Queue = queue.Queue(maxsize=1)
    with transport._pending_lock:
        transport._pending["abc"] = response_q
    transport._reader()

    assert response_q.get(timeout=0.1)["success"] is False
    event = transport.get_event(generation + 1, timeout=0.1)
    assert event == (generation + 1, {"type": "_transport_wakeup", "reason": "closed"})


def test_send_rejects_closed_transport():
    transport = PiRpcTransport()

    with pytest.raises(PiTransportError, match="transport not running"):
        transport.send({"type": "get_state"}, timeout=0.01)
```

- [ ] **Step 2: Run tests to verify failure**

Run:

```bash
PYTHONPATH=src/voice_bridge pytest src/voice_bridge/tests/test_pi_transport.py -q
```

Expected: import failure or missing `PiRpcTransport`.

- [ ] **Step 3: Implement transport in `pi_agent.py`**

Create `src/voice_bridge/voice_bridge/pi_agent.py` with the transport foundation:

```python
from __future__ import annotations

import json
import os
import queue
import signal
import subprocess
import threading
import time
import uuid
from enum import Enum
from pathlib import Path
from typing import Any, Callable


class PiTransportError(RuntimeError):
    pass


class PiRpcTransport:
    class _State(Enum):
        IDLE = "idle"
        RUNNING = "running"
        CLOSING = "closing"
        CLOSED = "closed"

    def __init__(self, popen_factory: Callable[..., subprocess.Popen] | None = None):
        self._popen_factory = popen_factory or subprocess.Popen
        self._state = self._State.IDLE
        self._state_lock = threading.Lock()
        self._proc: subprocess.Popen | None = None
        self._write_lock = threading.Lock()
        self._pending_lock = threading.Lock()
        self._pending: dict[str, queue.Queue] = {}
        self._events: queue.Queue[tuple[int, dict[str, Any]]] = queue.Queue()
        self._reader_thread: threading.Thread | None = None
        self._stderr_thread: threading.Thread | None = None
        self._generation = 0

    def _get_generation(self) -> int:
        with self._state_lock:
            return self._generation

    def current_generation(self) -> int:
        return self._get_generation()

    def _bump_generation(self) -> int:
        with self._state_lock:
            self._generation += 1
            return self._generation

    def start(self, command: list[str], cwd: Path, env: dict[str, str]) -> None:
        with self._state_lock:
            if self._state != self._State.IDLE:
                raise PiTransportError(f"cannot start from state {self._state.name}")
        proc = self._popen_factory(
            command,
            cwd=str(cwd),
            env=env,
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            bufsize=1,
            start_new_session=True,
        )
        self._proc = proc
        self._reader_thread = threading.Thread(target=self._reader, daemon=True)
        self._stderr_thread = threading.Thread(target=self._stderr_reader, daemon=True)
        self._reader_thread.start()
        self._stderr_thread.start()
        with self._state_lock:
            self._state = self._State.RUNNING

    def wake_events(self, reason: str) -> None:
        self._events.put((self._get_generation(), {"type": "_transport_wakeup", "reason": reason}))

    def _route_message(self, msg: dict[str, Any]) -> None:
        msg_id = msg.get("id")
        if msg.get("type") == "response" and msg_id:
            with self._pending_lock:
                response_q = self._pending.pop(str(msg_id), None)
            if response_q is not None:
                response_q.put(msg)
                return
        self._events.put((self._get_generation(), msg))

    def _reader(self) -> None:
        try:
            proc = self._proc
            stdout = getattr(proc, "stdout", None)
            if stdout is None:
                return
            for raw_line in stdout:
                line = raw_line.rstrip("\n")
                if line.endswith("\r"):
                    line = line[:-1]
                try:
                    msg = json.loads(line)
                except json.JSONDecodeError:
                    continue
                if isinstance(msg, dict):
                    self._route_message(msg)
        finally:
            self._mark_closed("closed")

    def _stderr_reader(self) -> None:
        proc = self._proc
        stderr = getattr(proc, "stderr", None)
        if stderr is None:
            return
        for _line in stderr:
            pass

    def _mark_closed(self, reason: str) -> None:
        with self._state_lock:
            if self._state == self._State.RUNNING:
                self._state = self._State.CLOSED
                self._generation += 1
            generation = self._generation
        with self._pending_lock:
            queues = list(self._pending.values())
            self._pending.clear()
        for response_q in queues:
            try:
                response_q.put({"type": "response", "success": False, "error": "transport closed"})
            except queue.Full:
                pass
        self._events.put((generation, {"type": "_transport_wakeup", "reason": reason}))

    def send(self, command: dict[str, Any], timeout: float = 5.0) -> dict[str, Any]:
        with self._state_lock:
            if self._state != self._State.RUNNING:
                raise PiTransportError(f"transport not running (state={self._state.name})")
        request_id = uuid.uuid4().hex[:8]
        payload = {**command, "id": request_id}
        response_q: queue.Queue = queue.Queue(maxsize=1)
        with self._pending_lock:
            self._pending[request_id] = response_q
        try:
            with self._write_lock:
                proc = self._proc
                if proc is None or proc.stdin is None:
                    raise PiTransportError("transport process not available")
                proc.stdin.write(json.dumps(payload, ensure_ascii=False) + "\n")
                proc.stdin.flush()
            result = response_q.get(timeout=timeout)
            if result.get("success") is False:
                raise PiTransportError(str(result.get("error", "rpc command failed")))
            return result
        except BrokenPipeError as exc:
            raise PiTransportError("broken pipe") from exc
        except queue.Empty as exc:
            raise PiTransportError("command timeout") from exc
        finally:
            with self._pending_lock:
                self._pending.pop(request_id, None)

    def get_event(self, expected_generation: int, timeout: float = 5.0) -> tuple[int, dict[str, Any]] | None:
        deadline = time.monotonic() + timeout
        while True:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                return None
            try:
                generation, event = self._events.get(timeout=remaining)
            except queue.Empty:
                return None
            if generation == expected_generation:
                return generation, event

    def close(self) -> None:
        with self._state_lock:
            if self._state not in {self._State.RUNNING, self._State.IDLE}:
                return
            self._state = self._State.CLOSING
            proc = self._proc
            self._proc = None
        with self._pending_lock:
            queues = list(self._pending.values())
            self._pending.clear()
        for response_q in queues:
            try:
                response_q.put({"type": "response", "success": False, "error": "transport closing"})
            except queue.Full:
                pass
        self.wake_events("closing")
        if proc is not None:
            try:
                os.killpg(proc.pid, signal.SIGTERM)
                proc.wait(timeout=2)
            except (ProcessLookupError, subprocess.TimeoutExpired):
                try:
                    os.killpg(proc.pid, signal.SIGKILL)
                except ProcessLookupError:
                    pass
        if self._reader_thread and self._reader_thread is not threading.current_thread():
            self._reader_thread.join(timeout=2)
        if self._stderr_thread and self._stderr_thread is not threading.current_thread():
            self._stderr_thread.join(timeout=2)
        with self._state_lock:
            self._state = self._State.CLOSED
```

- [ ] **Step 4: Run tests and commit**

Run:

```bash
PYTHONPATH=src/voice_bridge pytest src/voice_bridge/tests/test_pi_transport.py -q
```

Expected: all selected tests pass. If `FakeProc` exposes iterator-only `stdout`, keep `_reader()` tolerant of that shape as shown.

Commit:

```bash
git add src/voice_bridge/voice_bridge/pi_agent.py src/voice_bridge/tests/test_pi_transport.py
git commit -m "feat: add pi rpc transport"
```

---

### Task 3: Tool Event Mapping and Result Finalization

**Files:**
- Modify: `src/voice_bridge/voice_bridge/pi_agent.py`
- Create/Modify: `src/voice_bridge/tests/test_pi_agent.py`

**Interfaces:**
- Consumes: `AgentCommand`, `AgentRequest`, `AgentResult`, `VoiceBridgeConfig`
- Produces: `_build_prompt_text(request: AgentRequest) -> str`
- Produces: `_extract_reply_text(events: list[dict[str, Any]]) -> str | None`
- Produces: `_build_agent_result(pending_tools: dict[str, dict[str, Any]], reply_text: str | None) -> AgentResult`
- Produces: `_finalize_agent_result(result: AgentResult, request: AgentRequest, config: VoiceBridgeConfig) -> AgentResult`

- [ ] **Step 1: Write failing result-mapping tests**

Add the first half of `src/voice_bridge/tests/test_pi_agent.py`:

```python
import math

from voice_bridge.config import VoiceBridgeConfig
from voice_bridge.internal_types import AgentCommand, AgentRequest, AgentResult
from voice_bridge.pi_agent import (
    _build_agent_result,
    _build_prompt_text,
    _extract_reply_text,
    _finalize_agent_result,
)


def make_request(safety_state: str | None = None) -> AgentRequest:
    return AgentRequest(
        session_id="s1",
        text="向前走然后停下",
        asr_confidence=0.9,
        robot_mode="normal",
        safety_state=safety_state,
        health_state="ok",
    )


def test_build_prompt_text_includes_robot_context():
    prompt = _build_prompt_text(make_request())

    assert "session_id: s1" in prompt
    assert "robot_mode: normal" in prompt
    assert "health_state: ok" in prompt
    assert "User said: 向前走然后停下" in prompt


def test_build_agent_result_keeps_confirmed_motion_order_and_led_separate():
    result = _build_agent_result(
        {
            "b": {"order": 1, "tool_name": "robot_stop", "kind": "action", "params": {"action": "stand"}, "confirmed": True},
            "a": {"order": 0, "tool_name": "robot_walk", "kind": "loco", "params": {"vx": 0.2, "vy": 0, "vyaw": 0, "duration_sec": 1}, "confirmed": True},
            "c": {"order": 2, "tool_name": "robot_led", "kind": "led", "params": {"r": 1, "g": 2, "b": 3, "ttl_sec": 1}, "confirmed": True},
            "d": {"order": 3, "tool_name": "robot_walk", "kind": "loco", "params": {"vx": 9}, "confirmed": False},
        },
        reply_text="收到",
    )

    assert result.commands == [
        AgentCommand(kind="loco", params={"vx": 0.2, "vy": 0, "vyaw": 0, "duration_sec": 1}),
        AgentCommand(kind="action", params={"action": "stop"}),
    ]
    assert result.led == {"r": 1, "g": 2, "b": 3, "ttl_sec": 1}
    assert result.reply_text == "收到"


def test_finalize_clamps_loco_rejects_nan_and_preserves_other_commands():
    config = VoiceBridgeConfig.default()
    result = AgentResult(
        commands=[
            AgentCommand(kind="loco", params={"vx": 9, "vy": -9, "vyaw": 9, "duration_sec": 99}),
            AgentCommand(kind="loco", params={"vx": math.nan, "vy": 0, "vyaw": 0, "duration_sec": 1}),
            AgentCommand(kind="action", params={"action": "resume"}),
            AgentCommand(kind="say", params={"text": "  " + "好" * 300}),
        ],
        led={"r": 300, "g": -1, "b": 10.7, "ttl_sec": 100},
    )

    finalized = _finalize_agent_result(result, make_request(), config)

    assert finalized.commands == [
        AgentCommand(kind="loco", params={"vx": 0.25, "vy": -0.15, "vyaw": 0.5, "duration_sec": 2.0}),
        AgentCommand(kind="action", params={"action": "resume"}),
        AgentCommand(kind="say", params={"text": "好" * 200}),
    ]
    assert finalized.led == {"r": 255, "g": 0, "b": 10, "ttl_sec": 30.0}


def test_finalize_drops_motion_when_safety_state_is_unsafe_but_keeps_tts_and_led():
    result = AgentResult(
        commands=[
            AgentCommand(kind="loco", params={"vx": 0.1, "vy": 0, "vyaw": 0, "duration_sec": 1}),
            AgentCommand(kind="action", params={"action": "stop"}),
            AgentCommand(kind="say", params={"text": "收到"}),
        ],
        reply_text="我会等待",
        led={"r": 1, "g": 2, "b": 3, "ttl_sec": 1},
    )

    finalized = _finalize_agent_result(result, make_request("estop"), VoiceBridgeConfig.default())

    assert finalized.commands == [AgentCommand(kind="say", params={"text": "收到"})]
    assert finalized.reply_text == "我会等待"
    assert finalized.led == {"r": 1, "g": 2, "b": 3, "ttl_sec": 1.0}


def test_extract_reply_text_from_agent_end_messages():
    text = _extract_reply_text(
        [
            {
                "type": "agent_end",
                "messages": [
                    {"role": "user", "content": [{"type": "text", "text": "hi"}]},
                    {"role": "assistant", "content": [{"type": "text", "text": "收到"}, {"type": "tool_use"}]},
                ],
            }
        ]
    )

    assert text == "收到"
```

- [ ] **Step 2: Run tests to verify failure**

Run:

```bash
PYTHONPATH=src/voice_bridge pytest src/voice_bridge/tests/test_pi_agent.py -q
```

Expected: failures for missing mapping/finalization functions.

- [ ] **Step 3: Implement mapping and validation helpers**

Append to `src/voice_bridge/voice_bridge/pi_agent.py`:

```python
import math

from voice_bridge.config import VoiceBridgeConfig
from voice_bridge.internal_types import AgentCommand, AgentRequest, AgentResult
from voice_bridge.pi_types import CUSTOM_TOOLS

VALID_ACTIONS = {"stop", "cancel", "stand", "resume"}


def _build_prompt_text(request: AgentRequest) -> str:
    context_parts = [f"session_id: {request.session_id}"]
    if request.robot_mode:
        context_parts.append(f"robot_mode: {request.robot_mode}")
    if request.safety_state:
        context_parts.append(f"safety_state: {request.safety_state}")
    if request.health_state:
        context_parts.append(f"health_state: {request.health_state}")
    return f"Robot context:\n{chr(10).join(context_parts)}\n\nUser said: {request.text}"


def _extract_reply_text(events: list[dict[str, Any]]) -> str | None:
    for event in reversed(events):
        if event.get("type") != "agent_end":
            continue
        for msg in reversed(event.get("messages", [])):
            if msg.get("role") == "assistant":
                parts = [
                    block.get("text", "")
                    for block in msg.get("content", [])
                    if isinstance(block, dict) and block.get("type") == "text"
                ]
                text = " ".join(part for part in parts if part).strip()
                return text or None
    return None


def _build_agent_result(pending_tools: dict[str, dict[str, Any]], reply_text: str | None) -> AgentResult:
    commands: list[AgentCommand] = []
    led_params: dict[str, Any] | None = None
    for item in sorted(pending_tools.values(), key=lambda value: int(value["order"])):
        if not item.get("confirmed"):
            continue
        tool_name = item["tool_name"]
        kind = item["kind"]
        if tool_name == "robot_stop":
            commands.append(AgentCommand(kind="action", params={"action": "stop"}))
        elif kind == "led":
            led_params = dict(item.get("params", {}))
        else:
            commands.append(AgentCommand(kind=kind, params=dict(item.get("params", {}))))
    return AgentResult(commands=commands, reply_text=reply_text, led=led_params)


def _finite_float(value: object) -> float | None:
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        return None
    if math.isnan(parsed) or math.isinf(parsed):
        return None
    return parsed


def _validate_and_clamp_loco(params: dict[str, Any], config: VoiceBridgeConfig) -> dict[str, float] | None:
    vx = _finite_float(params.get("vx", 0))
    vy = _finite_float(params.get("vy", 0))
    vyaw = _finite_float(params.get("vyaw", 0))
    duration_sec = _finite_float(params.get("duration_sec", 0))
    if None in {vx, vy, vyaw, duration_sec}:
        return None
    defaults = config.motion_defaults
    return {
        "vx": max(-float(defaults["default_vx"]), min(float(defaults["default_vx"]), float(vx))),
        "vy": max(-float(defaults["default_vy"]), min(float(defaults["default_vy"]), float(vy))),
        "vyaw": max(-float(defaults["default_vyaw"]), min(float(defaults["default_vyaw"]), float(vyaw))),
        "duration_sec": max(0.1, min(float(defaults["max_motion_duration_sec"]), float(duration_sec))),
    }


def _validate_action(params: dict[str, Any]) -> dict[str, str]:
    action = str(params.get("action", "stop"))
    return {"action": action if action in VALID_ACTIONS else "stop"}


def _validate_led(params: dict[str, Any]) -> dict[str, Any] | None:
    r = _finite_float(params.get("r", 0))
    g = _finite_float(params.get("g", 0))
    b = _finite_float(params.get("b", 0))
    ttl_sec = _finite_float(params.get("ttl_sec", 1.0))
    if None in {r, g, b, ttl_sec}:
        return None
    return {
        "r": max(0, min(255, int(float(r)))),
        "g": max(0, min(255, int(float(g)))),
        "b": max(0, min(255, int(float(b)))),
        "ttl_sec": max(0.1, min(30.0, float(ttl_sec))),
    }


def _sanitize_tts(text: object) -> str | None:
    if not isinstance(text, str):
        return None
    stripped = text.strip()
    return stripped[:200] if stripped else None


def _safety_allows_motion(safety_state: str | None) -> bool:
    return (safety_state or "").lower() not in {"emergency", "estop", "fault", "unsafe"}


def _finalize_agent_result(result: AgentResult, request: AgentRequest, config: VoiceBridgeConfig) -> AgentResult:
    motion_candidates: list[AgentCommand] = []
    non_motion: list[AgentCommand] = []
    for command in result.commands:
        if command.kind == "loco":
            params = _validate_and_clamp_loco(command.params, config)
            if params is not None:
                motion_candidates.append(AgentCommand(kind="loco", params=params))
        elif command.kind == "action":
            motion_candidates.append(AgentCommand(kind="action", params=_validate_action(command.params)))
        elif command.kind == "say":
            text = _sanitize_tts(command.params.get("text"))
            if text is not None:
                non_motion.append(AgentCommand(kind="say", params={"text": text}))
    commands = (motion_candidates if _safety_allows_motion(request.safety_state) else []) + non_motion
    led = _validate_led(result.led) if result.led else None
    reply_text = _sanitize_tts(result.reply_text) if result.reply_text else None
    return AgentResult(commands=commands, reply_text=reply_text, led=led)
```

- [ ] **Step 4: Run tests and commit**

Run:

```bash
PYTHONPATH=src/voice_bridge pytest src/voice_bridge/tests/test_pi_agent.py -q
```

Expected: all selected mapping tests pass.

Commit:

```bash
git add src/voice_bridge/voice_bridge/pi_agent.py src/voice_bridge/tests/test_pi_agent.py
git commit -m "feat: map pi robot tools to agent results"
```

---

### Task 4: PiRpcAgentClient Lifecycle, Sessions, Abort, and Timeouts

**Files:**
- Modify: `src/voice_bridge/voice_bridge/pi_agent.py`
- Modify: `src/voice_bridge/tests/test_pi_agent.py`

**Interfaces:**
- Consumes: `PiRpcTransport`, `PiTransportError`, `build_pi_command`, `resolve_repo_root`, `resolve_workspace`, `scrubbed_env`
- Produces: `class PiRpcAgentClient`
- Produces: `PiRpcAgentClient.decide(request: AgentRequest) -> AgentResult`
- Produces: `PiRpcAgentClient.abort() -> None`
- Produces: `PiRpcAgentClient.close() -> None`

- [ ] **Step 1: Add mocked transport tests**

Append to `src/voice_bridge/tests/test_pi_agent.py`:

```python
import queue
import threading
import time
from pathlib import Path

from voice_bridge.pi_agent import PiRpcAgentClient, PiTransportError


class FakeTransport:
    def __init__(self, events=None):
        self.events = queue.Queue()
        for event in events or []:
            self.events.put(event)
        self.sent: list[dict] = []
        self.started = False
        self.closed = False
        self.wake_reasons: list[str] = []
        self.generation = 3

    def start(self, command, cwd, env):
        self.started = True

    def current_generation(self):
        return self.generation

    def send(self, command, timeout=5.0):
        self.sent.append(command)
        if command["type"] == "get_state":
            return {"type": "response", "success": True, "data": {"sessionId": "pi-s1", "isStreaming": False}}
        if command["type"] == "new_session":
            return {"type": "response", "success": True, "data": {"cancelled": False}}
        if command["type"] == "prompt":
            return {"type": "response", "success": True}
        if command["type"] == "abort":
            return {"type": "response", "success": True}
        raise AssertionError(command)

    def get_event(self, expected_generation, timeout=5.0):
        try:
            return expected_generation, self.events.get(timeout=timeout)
        except queue.Empty:
            return None

    def wake_events(self, reason):
        self.wake_reasons.append(reason)
        self.events.put({"type": "_transport_wakeup", "reason": reason})

    def close(self):
        self.closed = True


def make_client(fake: FakeTransport, config: VoiceBridgeConfig | None = None) -> PiRpcAgentClient:
    return PiRpcAgentClient(
        config or VoiceBridgeConfig.default(),
        repo_root=Path.cwd(),
        transport_factory=lambda: fake,
    )


def test_decide_sends_prompt_and_returns_confirmed_tools():
    fake = FakeTransport(
        [
            {"type": "tool_execution_start", "toolCallId": "w1", "toolName": "robot_walk", "args": {"vx": 0.1, "vy": 0, "vyaw": 0, "duration_sec": 1}},
            {"type": "tool_execution_end", "toolCallId": "w1", "toolName": "robot_walk", "result": {}, "isError": False},
            {"type": "agent_end", "messages": [{"role": "assistant", "content": [{"type": "text", "text": "收到"}]}]},
        ]
    )
    client = make_client(fake)

    result = client.decide(make_request())

    assert fake.started is True
    assert fake.sent[0]["type"] == "get_state"
    assert fake.sent[-1]["type"] == "prompt"
    assert "User said: 向前走然后停下" in fake.sent[-1]["text"]
    assert result.commands == [AgentCommand(kind="loco", params={"vx": 0.1, "vy": 0.0, "vyaw": 0.0, "duration_sec": 1.0})]
    assert result.reply_text == "收到"


def test_decide_returns_no_motion_when_agent_end_missing():
    fake = FakeTransport(
        [
            {"type": "tool_execution_start", "toolCallId": "w1", "toolName": "robot_walk", "args": {"vx": 0.1, "vy": 0, "vyaw": 0, "duration_sec": 1}},
            {"type": "tool_execution_end", "toolCallId": "w1", "toolName": "robot_walk", "result": {}, "isError": False},
        ]
    )
    client = make_client(fake)

    assert client.decide(make_request()).commands == []


def test_abort_wakes_decide_and_returns_no_motion():
    fake = FakeTransport(
        [
            {"type": "tool_execution_start", "toolCallId": "w1", "toolName": "robot_walk", "args": {"vx": 0.1, "vy": 0, "vyaw": 0, "duration_sec": 1}},
            {"type": "tool_execution_end", "toolCallId": "w1", "toolName": "robot_walk", "result": {}, "isError": False},
        ]
    )
    client = make_client(fake)
    result_box = {}

    thread = threading.Thread(target=lambda: result_box.setdefault("result", client.decide(make_request())))
    thread.start()
    time.sleep(0.05)
    client.abort()
    thread.join(timeout=2)

    assert result_box["result"].commands == []
    assert "aborted" in fake.wake_reasons
    assert any(command["type"] == "abort" for command in fake.sent)


def test_close_delegates_to_transport():
    fake = FakeTransport()
    client = make_client(fake)
    client.decide(make_request())

    client.close()

    assert fake.closed is True


def test_startup_failure_returns_empty_result():
    class BrokenTransport(FakeTransport):
        def start(self, command, cwd, env):
            raise PiTransportError("boom")

    client = make_client(BrokenTransport())

    assert client.decide(make_request()) == AgentResult()
```

- [ ] **Step 2: Run tests to verify failure**

Run:

```bash
PYTHONPATH=src/voice_bridge pytest src/voice_bridge/tests/test_pi_agent.py -q
```

Expected: failures for missing `PiRpcAgentClient`.

- [ ] **Step 3: Implement `PiRpcAgentClient`**

Append to `src/voice_bridge/voice_bridge/pi_agent.py`:

```python
from copy import deepcopy

from voice_bridge.pi_config import (
    DEFAULT_PI_CONFIG,
    build_pi_command,
    resolve_repo_root,
    resolve_workspace,
    scrubbed_env,
)
from voice_bridge.pi_types import DEFAULT_PI_TIMEOUTS


class PiRpcAgentClient:
    def __init__(
        self,
        config: VoiceBridgeConfig,
        repo_root: Path | None = None,
        transport_factory: Callable[[], PiRpcTransport] = PiRpcTransport,
    ):
        self._config = config
        self._pi_config = deepcopy(DEFAULT_PI_CONFIG)
        self._pi_config.update(config.agent.get("pi", {}))
        self._timeouts = dict(DEFAULT_PI_TIMEOUTS)
        self._timeouts.update(self._pi_config.get("timeouts", {}))
        self._repo_root = repo_root or resolve_repo_root()
        self._workspace = resolve_workspace(self._pi_config, self._repo_root)
        self._transport_factory = transport_factory
        self._transport: PiRpcTransport | None = None
        self._startup_lock = threading.Lock()
        self._shutdown_lock = threading.Lock()
        self._aborted = threading.Event()
        self._pi_session_id: str | None = None
        self._last_activity = 0.0

    def _ensure_transport(self) -> PiRpcTransport:
        with self._startup_lock:
            if self._transport is not None:
                return self._transport
            transport = self._transport_factory()
            command = build_pi_command(self._pi_config, self._workspace)
            self._workspace.mkdir(parents=True, exist_ok=True)
            transport.start(command, self._workspace, scrubbed_env(self._pi_config))
            transport.send({"type": "get_state"}, timeout=float(self._timeouts["startup_health_sec"]))
            self._transport = transport
            return transport

    def _ensure_session(self, transport: PiRpcTransport) -> None:
        idle_timeout = float(self._config.voice["idle_timeout_sec"])
        now = time.monotonic()
        if self._pi_session_id is not None and now - self._last_activity <= idle_timeout:
            return
        if self._pi_session_id is not None:
            response = transport.send({"type": "new_session"}, timeout=float(self._timeouts["command_response_sec"]))
            if response.get("data", {}).get("cancelled"):
                self._pi_session_id = None
                return
        state = transport.send({"type": "get_state"}, timeout=float(self._timeouts["command_response_sec"]))
        self._pi_session_id = state.get("data", {}).get("sessionId")

    def abort(self) -> None:
        self._aborted.set()
        transport = self._transport
        if transport is None:
            return
        transport.wake_events("aborted")

        def _send_abort() -> None:
            try:
                transport.send({"type": "abort"}, timeout=1.0)
            except PiTransportError:
                pass

        threading.Thread(target=_send_abort, daemon=True).start()

    def close(self) -> None:
        with self._shutdown_lock:
            transport = self._transport
            self._transport = None
        if transport is not None:
            transport.close()

    def decide(self, request: AgentRequest) -> AgentResult:
        self._aborted.clear()
        pending_tools: dict[str, dict[str, Any]] = {}
        events: list[dict[str, Any]] = []
        normal_completion = False
        try:
            transport = self._ensure_transport()
            self._ensure_session(transport)
            generation = transport.current_generation()
            transport.send(
                {"type": "prompt", "text": _build_prompt_text(request)},
                timeout=float(self._timeouts["command_response_sec"]),
            )
            hard_deadline = time.monotonic() + float(self._timeouts["motion_turn_hard_sec"])
            while not self._aborted.is_set():
                remaining = hard_deadline - time.monotonic()
                if remaining <= 0:
                    self.abort()
                    break
                event_item = transport.get_event(generation, timeout=min(1.0, remaining))
                if event_item is None:
                    continue
                _generation, event = event_item
                if event.get("type") == "_transport_wakeup":
                    break
                events.append(event)
                event_type = event.get("type")
                if event_type == "tool_execution_start":
                    tool_name = str(event.get("toolName", ""))
                    if tool_name in CUSTOM_TOOLS and isinstance(event.get("toolCallId"), str):
                        pending_tools[str(event["toolCallId"])] = {
                            "order": len(pending_tools),
                            "tool_name": tool_name,
                            "kind": CUSTOM_TOOLS[tool_name],
                            "params": event.get("args", {}) if isinstance(event.get("args"), dict) else {},
                            "confirmed": False,
                        }
                elif event_type == "tool_execution_end":
                    if event.get("isError", False):
                        continue
                    tool_call_id = str(event.get("toolCallId", ""))
                    if tool_call_id in pending_tools:
                        pending_tools[tool_call_id]["confirmed"] = True
                elif event_type == "agent_end":
                    normal_completion = True
                    break
        except PiTransportError:
            self.close()
            return AgentResult()
        finally:
            self._aborted.clear()
        if not normal_completion:
            return AgentResult(reply_text=_sanitize_tts(_extract_reply_text(events)))
        result = _build_agent_result(pending_tools, _extract_reply_text(events))
        finalized = _finalize_agent_result(result, request, self._config)
        self._last_activity = time.monotonic()
        return finalized
```

- [ ] **Step 4: Run tests and commit**

Run:

```bash
PYTHONPATH=src/voice_bridge pytest src/voice_bridge/tests/test_pi_agent.py -q
```

Expected: all `test_pi_agent.py` tests pass. If `test_abort_wakes_decide_and_returns_no_motion` flakes, shorten the fake transport wait or add one `threading.Event` in the fake to signal prompt was sent before calling `abort()`.

Commit:

```bash
git add src/voice_bridge/voice_bridge/pi_agent.py src/voice_bridge/tests/test_pi_agent.py
git commit -m "feat: add pi rpc agent client"
```

---

### Task 5: Node Stop/Shutdown Integration

**Files:**
- Modify: `src/voice_bridge/voice_bridge/node.py`
- Modify: `src/voice_bridge/tests/test_node_helpers.py`

**Interfaces:**
- Consumes: optional `abort()` and `close()` methods from active agent
- Produces: `_supports_closeable(agent: object) -> bool`
- Produces: `VoiceBridgeNode._closeable_agent`

- [ ] **Step 1: Write failing node helper tests**

Append to `src/voice_bridge/tests/test_node_helpers.py`:

```python
from voice_bridge.node import _supports_closeable


class CloseableAgent:
    def decide(self, request):
        raise AssertionError("not used")

    def abort(self):
        return None

    def close(self):
        return None


class NonCloseableAgent:
    def decide(self, request):
        raise AssertionError("not used")


def test_supports_closeable_uses_hasattr():
    assert _supports_closeable(CloseableAgent()) is True
    assert _supports_closeable(NonCloseableAgent()) is False
```

Add a minimal fake node test near the bottom:

```python
class FakePublisher:
    def __init__(self):
        self.payloads = []

    def publish(self, msg):
        self.payloads.append(msg.data)


class FakeClockNow:
    nanoseconds = 1_000_000_000


class FakeClock:
    def now(self):
        return FakeClockNow()


class FakeLogger:
    def warning(self, message):
        self.message = message


class FakeNode:
    def __init__(self):
        self.publishers = []

    def create_publisher(self, msg_type, topic, depth):
        pub = FakePublisher()
        self.publishers.append(pub)
        return pub

    def create_subscription(self, *args, **kwargs):
        return None

    def create_timer(self, *args, **kwargs):
        return None

    def get_clock(self):
        return FakeClock()

    def get_logger(self):
        return FakeLogger()


def test_stop_action_aborts_closeable_agent_after_publish():
    from voice_bridge.config import VoiceBridgeConfig
    from voice_bridge.internal_types import SessionDecision
    from voice_bridge.node import VoiceBridgeNode

    class Agent(CloseableAgent):
        def __init__(self):
            self.aborted = False

        def abort(self):
            self.aborted = True

    agent = Agent()
    node = VoiceBridgeNode(FakeNode(), VoiceBridgeConfig.default(), agent=agent)

    node._publish_action_decision(SessionDecision(kind="action", session_id="s1", text="停止", action="stop"), 1.0)

    assert agent.aborted is True
    assert len(node.action_pub.payloads) == 1


def test_shutdown_closes_closeable_agent():
    from voice_bridge.config import VoiceBridgeConfig
    from voice_bridge.node import VoiceBridgeNode

    class Agent(CloseableAgent):
        def __init__(self):
            self.closed = False

        def close(self):
            self.closed = True

    agent = Agent()
    node = VoiceBridgeNode(FakeNode(), VoiceBridgeConfig.default(), agent=agent)

    node.shutdown()

    assert agent.closed is True
```

- [ ] **Step 2: Run tests to verify failure**

Run:

```bash
PYTHONPATH=src/voice_bridge pytest src/voice_bridge/tests/test_node_helpers.py -q
```

Expected: missing `_supports_closeable`, no abort call, no close call.

- [ ] **Step 3: Modify `node.py`**

Add helper near top of `src/voice_bridge/voice_bridge/node.py`:

```python
def _supports_closeable(agent: object) -> bool:
    return hasattr(agent, "abort") and hasattr(agent, "close")
```

In `VoiceBridgeNode.__init__`, after `self.agent = ...`:

```python
self._closeable_agent = self.agent if _supports_closeable(self.agent) else None
```

In `_publish_action_decision`, change the stop/cancel branch:

```python
if action in {"stop", "cancel"}:
    self._agent_requests.invalidate()
payload = build_action_payload(
    action=action,
    session_id=session_id,
    command_id=self._new_command_id(now_sec, action),
    text=decision.text or "",
    created_at=now_sec,
    priority="emergency" if action == "stop" else "normal",
)
self._publish_string(self.action_pub, payload)
if action in {"stop", "cancel"} and self._closeable_agent is not None:
    self._closeable_agent.abort()
```

In `shutdown`, close before executor shutdown:

```python
def shutdown(self) -> None:
    self._agent_requests.invalidate()
    if self._closeable_agent is not None:
        self._closeable_agent.close()
    self._agent_executor.shutdown(wait=False, cancel_futures=True)
```

- [ ] **Step 4: Run tests and commit**

Run:

```bash
PYTHONPATH=src/voice_bridge pytest src/voice_bridge/tests/test_node_helpers.py -q
```

Expected: all selected tests pass.

Commit:

```bash
git add src/voice_bridge/voice_bridge/node.py src/voice_bridge/tests/test_node_helpers.py
git commit -m "feat: abort pi agent on stop"
```

---

### Task 6: Robot Tools Extension, Integration Tests, and Docs

**Files:**
- Create: `.agent-runtime/.unitree_agent/.pi/extensions/robot-tools.ts`
- Create: `src/voice_bridge/tests/test_pi_integration.py`
- Modify: `src/voice_bridge/README.md`

**Interfaces:**
- Produces Pi tools: `robot_walk`, `robot_stop`, `robot_say`, `robot_led`
- Consumes Pi CLI command built by `build_pi_command()`

- [ ] **Step 1: Create `robot-tools.ts`**

Create `.agent-runtime/.unitree_agent/.pi/extensions/robot-tools.ts`:

```typescript
import { Type } from "@earendil-works/pi-ai";
import { defineTool, type ExtensionAPI } from "@earendil-works/pi-coding-agent";

const robotWalk = defineTool({
	name: "robot_walk",
	label: "Robot Walk",
	description: "控制机器人移动方向和持续时间。vx 前后速度，vy 左右速度，vyaw 转向速度，duration_sec 持续时间。",
	promptSnippet: "robot_walk(vx, vy, vyaw, duration_sec): request robot locomotion through voice_bridge.",
	promptGuidelines: ["Use robot_walk only for explicit movement requests."],
	executionMode: "sequential",
	parameters: Type.Object({
		vx: Type.Number({ minimum: -1, maximum: 1, description: "Forward velocity. Positive moves forward." }),
		vy: Type.Number({ minimum: -1, maximum: 1, description: "Lateral velocity. Positive moves left." }),
		vyaw: Type.Number({ minimum: -1, maximum: 1, description: "Yaw velocity. Positive turns left." }),
		duration_sec: Type.Number({ minimum: 0.1, maximum: 10, description: "Movement duration in seconds." }),
	}),
	async execute(_toolCallId, params) {
		return {
			content: [{ type: "text", text: `robot_walk accepted ${JSON.stringify(params)}` }],
			details: params,
		};
	},
});

const robotStop = defineTool({
	name: "robot_stop",
	label: "Robot Stop",
	description: "立即停止机器人运动。",
	promptSnippet: "robot_stop(): request an immediate stop through voice_bridge.",
	promptGuidelines: ["Use robot_stop for stop, cancel, freeze, or unsafe movement requests."],
	executionMode: "sequential",
	parameters: Type.Object({}),
	async execute() {
		return {
			content: [{ type: "text", text: "robot_stop accepted" }],
			details: {},
		};
	},
});

const robotSay = defineTool({
	name: "robot_say",
	label: "Robot Say",
	description: "通过 TTS 输出语音。",
	promptSnippet: "robot_say(text): request text-to-speech through voice_bridge.",
	parameters: Type.Object({
		text: Type.String({ minLength: 1, description: "Text to speak." }),
	}),
	async execute(_toolCallId, params) {
		return {
			content: [{ type: "text", text: `robot_say accepted ${params.text}` }],
			details: params,
		};
	},
});

const robotLed = defineTool({
	name: "robot_led",
	label: "Robot LED",
	description: "控制 LED 颜色和持续时间。",
	promptSnippet: "robot_led(r, g, b, ttl_sec): request LED color through voice_bridge.",
	parameters: Type.Object({
		r: Type.Number({ minimum: 0, maximum: 255, description: "Red channel." }),
		g: Type.Number({ minimum: 0, maximum: 255, description: "Green channel." }),
		b: Type.Number({ minimum: 0, maximum: 255, description: "Blue channel." }),
		ttl_sec: Type.Number({ minimum: 0.1, maximum: 30, description: "LED duration in seconds." }),
	}),
	async execute(_toolCallId, params) {
		return {
			content: [{ type: "text", text: `robot_led accepted ${JSON.stringify(params)}` }],
			details: params,
		};
	},
});

export default function (pi: ExtensionAPI) {
	pi.registerTool(robotWalk);
	pi.registerTool(robotStop);
	pi.registerTool(robotSay);
	pi.registerTool(robotLed);
}
```

- [ ] **Step 2: Add real Pi integration tests**

Create `src/voice_bridge/tests/test_pi_integration.py`:

```python
import os
from pathlib import Path

import pytest

from voice_bridge.config import VoiceBridgeConfig
from voice_bridge.pi_agent import PiRpcTransport
from voice_bridge.pi_config import build_pi_command, resolve_workspace, scrubbed_env

PI_AGENT_INTEGRATION = os.environ.get("PI_AGENT_INTEGRATION", "")


@pytest.mark.skipif(not PI_AGENT_INTEGRATION, reason="Pi not available")
def test_pi_rpc_get_state_smoke():
    repo_root = Path.cwd()
    config = VoiceBridgeConfig.default()
    pi_config = dict(config.agent["pi"])
    workspace = resolve_workspace(pi_config, repo_root)
    transport = PiRpcTransport()
    try:
        transport.start(build_pi_command(pi_config, workspace), workspace, scrubbed_env(pi_config))
        response = transport.send({"type": "get_state"}, timeout=20.0)
        assert response["type"] == "response"
        assert response["success"] is True
        assert "sessionId" in response.get("data", {})
    finally:
        transport.close()
```

- [ ] **Step 3: Document setup and safety boundary**

In `src/voice_bridge/README.md`, add a section:

```markdown
## Pi RPC Agent Backend

Set `agent.backend: pi_rpc` to run Pi Agent as a JSONL RPC subprocess. The default workspace is `.agent-runtime/.unitree_agent`, and `voice_bridge` loads `.pi/extensions/robot-tools.ts` with `-e` when the file exists.

Pi is not sandboxed by `voice_bridge`. It may use Pi built-in tools such as bash/read/write under the current user. The ROS motion safety boundary remains in Python: only confirmed `robot_*` tool calls are mapped to `AgentCommand`s, and `voice_bridge` validates/clamps motion, action, LED, and TTS payloads before publishing.

Run unit tests:

```bash
PYTHONPATH=src/voice_bridge pytest src/voice_bridge/tests -q
```

Run real Pi smoke tests:

```bash
PI_AGENT_INTEGRATION=1 PYTHONPATH=src/voice_bridge pytest src/voice_bridge/tests/test_pi_integration.py -q
```
```

- [ ] **Step 4: Run full unit tests**

Run:

```bash
PYTHONPATH=src/voice_bridge pytest src/voice_bridge/tests -q
```

Expected: all unit tests pass, with `test_pi_integration.py` skipped unless `PI_AGENT_INTEGRATION=1`.

- [ ] **Step 5: Run integration smoke test when Pi is configured**

Run only when `pi` is on `PATH` and provider credentials are configured:

```bash
PI_AGENT_INTEGRATION=1 PYTHONPATH=src/voice_bridge pytest src/voice_bridge/tests/test_pi_integration.py -q
```

Expected: `test_pi_rpc_get_state_smoke` passes with a `response.success == True` result.

- [ ] **Step 6: Commit**

Commit:

```bash
git add .agent-runtime/.unitree_agent/.pi/extensions/robot-tools.ts src/voice_bridge/tests/test_pi_integration.py src/voice_bridge/README.md
git commit -m "feat: add pi robot tools extension"
```

---

## Final Verification

- [ ] Run all unit tests:

```bash
PYTHONPATH=src/voice_bridge pytest src/voice_bridge/tests -q
```

Expected: all non-integration tests pass; Pi integration test is skipped when `PI_AGENT_INTEGRATION` is unset.

- [ ] Run focused Pi test suite:

```bash
PYTHONPATH=src/voice_bridge pytest src/voice_bridge/tests/test_pi_config.py src/voice_bridge/tests/test_pi_transport.py src/voice_bridge/tests/test_pi_agent.py -q
```

Expected: all selected tests pass.

- [ ] Run real Pi smoke test when credentials and `pi` executable are available:

```bash
PI_AGENT_INTEGRATION=1 PYTHONPATH=src/voice_bridge pytest src/voice_bridge/tests/test_pi_integration.py -q
```

Expected: `get_state` smoke test passes.

- [ ] Check backend selection manually:

```bash
PYTHONPATH=src/voice_bridge python - <<'PY'
from voice_bridge.config import VoiceBridgeConfig
from voice_bridge.agent import build_agent_client

raw = VoiceBridgeConfig.default()
config = VoiceBridgeConfig(raw.voice, raw.motion_defaults, {**raw.agent, "backend": "pi_rpc"}, raw.topics)
print(type(build_agent_client(config)).__name__)
PY
```

Expected output:

```text
PiRpcAgentClient
```

---

## Self-Review

- Spec coverage: protocol extension, node abort/close, workspace resolution, env scrubbing, command construction, transport generation, pending wakeup, session renewal, tool mapping, validation, safety filtering, robot extension, unit tests, integration tests, and docs are covered by Tasks 1-6.
- Placeholder scan: this plan contains no deferred implementation markers; each task names concrete files, interfaces, commands, and expected results.
- Type consistency: all later tasks consume interfaces produced by earlier tasks: `pi_types.py` and `pi_config.py` in Task 1, `PiRpcTransport` in Task 2, mapping helpers in Task 3, `PiRpcAgentClient` in Task 4, node optional closeable behavior in Task 5, and extension/integration docs in Task 6.
