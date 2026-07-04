# G1 Interface Node Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build the P0 `g1_interface` ROS2 Python node that bridges Unitree G1 native ROS2/DDS topics and `/api/sport/*` into stable internal `/g1/*` topics and safe command inputs.

**Architecture:** Create one focused `ament_python` package under `src/g1_interface`. Keep Unitree message imports at the ROS boundary, keep conversion and API request building pure-Python for unit testing, and expose runtime behavior through a single `g1_interface_node` executable plus a launch file and YAML config.

**Tech Stack:** ROS2 Humble, `rclpy`, `std_msgs`, `sensor_msgs`, `diagnostic_msgs`, `unitree_hg`, `unitree_api`, Python 3.10+, `pytest`, `colcon`.

## Global Constraints

- Use `rmw_cyclonedds_cpp`.
- Default deployment target is the G1 onboard computer; external PC is for debugging and visualization.
- P0 must use `/api/sport/request` and `/api/sport/response` for high-level locomotion.
- P0 must not publish `/lowcmd`.
- Unitree native topic and `/api/*` access must stay inside the G1 interface node.
- Application nodes must only consume internal `/g1/*` topics or publish `/g1/safe_cmd/*`.
- Default native topics: `lowstate`, `lf/lowstate`, `secondary_imu`, `/api/sport/request`, `/api/sport/response`, `/api/voice/request`, `/api/voice/response`.
- G1 sport API IDs come from `docs/G1_H1_API_Documentation.md`: `7001` get FSM ID, `7002` get FSM mode, `7105` set velocity, `7110` switch to user control, `7111` switch to internal control.
- G1 velocity command payload uses `JsonizeVelocityCommand`: `velocity: [vx, vy, vyaw]` and `duration`.
- ASR source is configurable: external ASR or a confirmed robot ASR topic can publish into `/g1/audio/asr`.
- G1 model and DoF differences must be configured, not hard-coded into control logic.
- The first real movement test must happen after read-only state and stop behavior are verified.

---

## File Structure

- Create `src/g1_interface/package.xml`: ROS package metadata and runtime dependencies.
- Create `src/g1_interface/setup.py`: Python package entry points.
- Create `src/g1_interface/setup.cfg`: install layout for scripts.
- Create `src/g1_interface/resource/g1_interface`: ament resource marker.
- Create `src/g1_interface/g1_interface/__init__.py`: package marker.
- Create `src/g1_interface/g1_interface/config.py`: load and validate config.
- Create `src/g1_interface/g1_interface/internal_types.py`: dataclasses shared by converters and API client.
- Create `src/g1_interface/g1_interface/converters.py`: convert Unitree-like messages into JSON-serializable internal payloads.
- Create `src/g1_interface/g1_interface/sport_api.py`: build `/api/sport/request` messages and track responses.
- Create `src/g1_interface/g1_interface/node.py`: `rclpy` node wiring publishers, subscriptions, timers, and diagnostics.
- Create `src/g1_interface/config/g1_interface.yaml`: default runtime configuration.
- Create `src/g1_interface/launch/g1_interface.launch.py`: launch file with config parameter.
- Create `src/g1_interface/tests/test_config.py`: config unit tests.
- Create `src/g1_interface/tests/test_converters.py`: conversion unit tests using fake message objects.
- Create `src/g1_interface/tests/test_sport_api.py`: sport API request and response tracking tests.
- Create `src/g1_interface/tests/test_node_helpers.py`: tests for safe command parsing and health payload formatting.
- Modify `flake.nix`: add Python test tooling and colcon packages to the dev shell if missing.
- Modify `docs/设计文档.md`: add a short implementation status note after the plan is executed.

---

### Task 1: Package Scaffold And Config Loader

**Files:**
- Create: `src/g1_interface/package.xml`
- Create: `src/g1_interface/setup.py`
- Create: `src/g1_interface/setup.cfg`
- Create: `src/g1_interface/resource/g1_interface`
- Create: `src/g1_interface/g1_interface/__init__.py`
- Create: `src/g1_interface/g1_interface/config.py`
- Create: `src/g1_interface/config/g1_interface.yaml`
- Create: `src/g1_interface/tests/test_config.py`
- Modify: `flake.nix`

**Interfaces:**
- Produces: `G1InterfaceConfig.from_yaml(path: str | Path) -> G1InterfaceConfig`
- Produces: `G1InterfaceConfig.default() -> G1InterfaceConfig`
- Produces: config fields used by later tasks: `native_topics`, `control`, `timeouts`, `robot`

- [ ] **Step 1: Write the failing config tests**

Create `src/g1_interface/tests/test_config.py`:

```python
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
```

- [ ] **Step 2: Run the config tests to verify they fail**

Run:

```bash
cd /home/ubuntu/Desktop/unitree_g1_agent
pytest src/g1_interface/tests/test_config.py -q
```

Expected: FAIL with `ModuleNotFoundError: No module named 'g1_interface'`.

- [ ] **Step 3: Create the ROS2 Python package scaffold**

Create `src/g1_interface/package.xml`:

```xml
<?xml version="1.0"?>
<package format="3">
  <name>g1_interface</name>
  <version>0.1.0</version>
  <description>Unitree G1 ROS2 interface node for native state and sport API bridging.</description>
  <maintainer email="dev@example.local">unitree_g1_agent</maintainer>
  <license>Apache-2.0</license>

  <buildtool_depend>ament_python</buildtool_depend>

  <exec_depend>rclpy</exec_depend>
  <exec_depend>std_msgs</exec_depend>
  <exec_depend>sensor_msgs</exec_depend>
  <exec_depend>diagnostic_msgs</exec_depend>
  <exec_depend>unitree_hg</exec_depend>
  <exec_depend>unitree_api</exec_depend>

  <test_depend>pytest</test_depend>

  <export>
    <build_type>ament_python</build_type>
  </export>
</package>
```

Create `src/g1_interface/setup.py`:

```python
from glob import glob

from setuptools import find_packages, setup

package_name = "g1_interface"

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
    description="Unitree G1 ROS2 interface node",
    license="Apache-2.0",
    tests_require=["pytest"],
    entry_points={
        "console_scripts": [
            "g1_interface_node = g1_interface.node:main",
        ],
    },
)
```

Create `src/g1_interface/setup.cfg`:

```ini
[develop]
script_dir=$base/lib/g1_interface
[install]
install_scripts=$base/lib/g1_interface
```

Create `src/g1_interface/resource/g1_interface` as an empty file.

Create `src/g1_interface/g1_interface/__init__.py`:

```python
"""Unitree G1 interface node package."""
```

- [ ] **Step 4: Implement config loading and validation**

Create `src/g1_interface/g1_interface/config.py`:

```python
from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml


DEFAULT_CONFIG: dict[str, dict[str, Any]] = {
    "robot": {
        "model": "g1",
        "dof_profile": "auto",
        "network_interface": "auto",
        "domain_id": 0,
        "rmw_implementation": "rmw_cyclonedds_cpp",
    },
    "native_topics": {
        "low_state": "lowstate",
        "low_state_low_freq": "lf/lowstate",
        "secondary_imu": "secondary_imu",
        "low_cmd": "/lowcmd",
        "arm_sdk": "/arm_sdk",
        "sport_request": "/api/sport/request",
        "sport_response": "/api/sport/response",
        "voice_request": "/api/voice/request",
        "voice_response": "/api/voice/response",
        "motion_switcher_request": "/api/motion_switcher/request",
        "motion_switcher_response": "/api/motion_switcher/response",
        "dex3_left_cmd": "/dex3/left/cmd",
        "dex3_right_cmd": "/dex3/right/cmd",
        "dex3_left_state": "/lf/dex3/left/state",
        "dex3_right_state": "/lf/dex3/right/state",
    },
    "control": {
        "default_mode": "sport_api_loco",
        "allow_low_level": False,
        "allow_arm_sdk": False,
        "allow_dex3": False,
        "allow_arm_while_loco": False,
        "require_manual_confirm_for_mode_switch": True,
    },
    "timeouts": {
        "state_timeout_ms": 300,
        "api_response_timeout_ms": 500,
        "health_publish_period_ms": 200,
    },
    "sport_api": {
        "parameter_encoding": "json",
        "api_ids": {
            "get_fsm_id": 7001,
            "get_fsm_mode": 7002,
            "set_velocity": 7105,
            "switch_to_user_ctrl": 7110,
            "switch_to_internal_ctrl": 7111,
        },
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
class G1InterfaceConfig:
    robot: dict[str, Any]
    native_topics: dict[str, str]
    control: dict[str, Any]
    timeouts: dict[str, int]
    sport_api: dict[str, Any]

    @classmethod
    def default(cls) -> "G1InterfaceConfig":
        return cls._from_dict(deepcopy(DEFAULT_CONFIG))

    @classmethod
    def from_yaml(cls, path: str | Path) -> "G1InterfaceConfig":
        with Path(path).open("r", encoding="utf-8") as handle:
            loaded = yaml.safe_load(handle) or {}
        if not isinstance(loaded, dict):
            raise ValueError("config root must be a mapping")
        return cls._from_dict(_deep_merge(DEFAULT_CONFIG, loaded))

    @classmethod
    def _from_dict(cls, raw: dict[str, Any]) -> "G1InterfaceConfig":
        config = cls(
            robot=dict(raw["robot"]),
            native_topics=dict(raw["native_topics"]),
            control=dict(raw["control"]),
            timeouts=dict(raw["timeouts"]),
            sport_api=dict(raw["sport_api"]),
        )
        config.validate()
        return config

    def validate(self) -> None:
        required_topics = ["low_state", "sport_request", "sport_response"]
        missing_topics = [key for key in required_topics if not self.native_topics.get(key)]
        if missing_topics:
            raise ValueError(f"missing native topic config: {', '.join(missing_topics)}")

        if self.control["allow_low_level"] and not self.control["require_manual_confirm_for_mode_switch"]:
            raise ValueError("low level control requires manual confirmation")

        encoding = self.sport_api.get("parameter_encoding")
        if encoding != "json":
            raise ValueError(f"unsupported sport API parameter encoding: {encoding}")
```

Create `src/g1_interface/config/g1_interface.yaml`:

```yaml
robot:
  model: g1
  dof_profile: auto
  network_interface: auto
  domain_id: 0
  rmw_implementation: rmw_cyclonedds_cpp

native_topics:
  low_state: lowstate
  low_state_low_freq: lf/lowstate
  secondary_imu: secondary_imu
  low_cmd: /lowcmd
  arm_sdk: /arm_sdk
  sport_request: /api/sport/request
  sport_response: /api/sport/response
  voice_request: /api/voice/request
  voice_response: /api/voice/response
  motion_switcher_request: /api/motion_switcher/request
  motion_switcher_response: /api/motion_switcher/response
  dex3_left_cmd: /dex3/left/cmd
  dex3_right_cmd: /dex3/right/cmd
  dex3_left_state: /lf/dex3/left/state
  dex3_right_state: /lf/dex3/right/state

control:
  default_mode: sport_api_loco
  allow_low_level: false
  allow_arm_sdk: false
  allow_dex3: false
  allow_arm_while_loco: false
  require_manual_confirm_for_mode_switch: true

timeouts:
  state_timeout_ms: 300
  api_response_timeout_ms: 500
  health_publish_period_ms: 200

sport_api:
  parameter_encoding: json
  api_ids:
    get_fsm_id: 7001
    get_fsm_mode: 7002
    set_velocity: 7105
    switch_to_user_ctrl: 7110
    switch_to_internal_ctrl: 7111
```

Modify `flake.nix` dev shell `buildInputs` to include:

```nix
python3
python3Packages.pytest
python3Packages.pyyaml
colcon
```

- [ ] **Step 5: Run the config tests to verify they pass**

Run:

```bash
cd /home/ubuntu/Desktop/unitree_g1_agent
PYTHONPATH=src/g1_interface pytest src/g1_interface/tests/test_config.py -q
```

Expected: `3 passed`.

- [ ] **Step 6: Commit**

Run:

```bash
git add flake.nix src/g1_interface
git commit -m "feat: scaffold g1 interface package"
```

Expected: commit succeeds when executed inside a git checkout.

---

### Task 2: Internal Types And State Converters

**Files:**
- Create: `src/g1_interface/g1_interface/internal_types.py`
- Create: `src/g1_interface/g1_interface/converters.py`
- Create: `src/g1_interface/tests/test_converters.py`

**Interfaces:**
- Consumes: `G1InterfaceConfig.robot["dof_profile"]`
- Produces: `lowstate_to_summary(msg: object, source: str, max_motors: int = 35) -> LowStateSummary`
- Produces: `imu_to_payload(msg: object, frame_id: str) -> ImuPayload`
- Produces: `LowStateSummary.to_json() -> str`

- [ ] **Step 1: Write the failing converter tests**

Create `src/g1_interface/tests/test_converters.py`:

```python
from types import SimpleNamespace

from g1_interface.converters import imu_to_payload, lowstate_to_summary


def _motor(q, dq, tau, temperature):
    return SimpleNamespace(q=q, dq=dq, tau_est=tau, temperature=temperature)


def test_lowstate_summary_extracts_imu_and_motor_ranges():
    msg = SimpleNamespace(
        rpy=[0.1, -0.2, 0.3],
        quaternion=[1.0, 0.0, 0.0, 0.0],
        gyroscope=[0.01, 0.02, 0.03],
        accelerometer=[0.0, 0.0, 9.81],
        motor_state=[
            _motor(0.1, 0.2, 0.3, 40),
            _motor(-0.1, -0.2, -0.3, 42),
        ],
    )

    summary = lowstate_to_summary(msg, source="lowstate", max_motors=35)

    assert summary.source == "lowstate"
    assert summary.motor_count == 2
    assert summary.max_temperature_c == 42
    assert summary.rpy == [0.1, -0.2, 0.3]
    assert summary.motors[0]["q"] == 0.1
    assert '"source": "lowstate"' in summary.to_json()


def test_lowstate_summary_handles_missing_optional_arrays():
    msg = SimpleNamespace(motor_state=[])

    summary = lowstate_to_summary(msg, source="lf/lowstate")

    assert summary.source == "lf/lowstate"
    assert summary.motor_count == 0
    assert summary.rpy == [0.0, 0.0, 0.0]
    assert summary.quaternion == [1.0, 0.0, 0.0, 0.0]


def test_imu_payload_uses_ros_quaternion_order():
    msg = SimpleNamespace(
        quaternion=[1.0, 0.1, 0.2, 0.3],
        gyroscope=[0.4, 0.5, 0.6],
        accelerometer=[0.7, 0.8, 0.9],
    )

    payload = imu_to_payload(msg, frame_id="g1_torso")

    assert payload.frame_id == "g1_torso"
    assert payload.orientation_xyzw == [0.1, 0.2, 0.3, 1.0]
    assert payload.angular_velocity == [0.4, 0.5, 0.6]
    assert payload.linear_acceleration == [0.7, 0.8, 0.9]
```

- [ ] **Step 2: Run the converter tests to verify they fail**

Run:

```bash
cd /home/ubuntu/Desktop/unitree_g1_agent
PYTHONPATH=src/g1_interface pytest src/g1_interface/tests/test_converters.py -q
```

Expected: FAIL with `ModuleNotFoundError` or `ImportError` for `g1_interface.converters`.

- [ ] **Step 3: Implement internal dataclasses**

Create `src/g1_interface/g1_interface/internal_types.py`:

```python
from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from typing import Any


@dataclass(frozen=True)
class LowStateSummary:
    source: str
    rpy: list[float]
    quaternion: list[float]
    gyroscope: list[float]
    accelerometer: list[float]
    motor_count: int
    max_temperature_c: float | None
    motors: list[dict[str, float]]

    def to_json(self) -> str:
        return json.dumps(asdict(self), ensure_ascii=False, sort_keys=True)


@dataclass(frozen=True)
class ImuPayload:
    frame_id: str
    orientation_xyzw: list[float]
    angular_velocity: list[float]
    linear_acceleration: list[float]


@dataclass(frozen=True)
class SportCommand:
    action: str
    params: dict[str, Any]


@dataclass(frozen=True)
class PendingApiRequest:
    sequence_id: int
    api_id: int
    action: str
    created_monotonic_sec: float
```

- [ ] **Step 4: Implement pure-Python converters**

Create `src/g1_interface/g1_interface/converters.py`:

```python
from __future__ import annotations

from typing import Iterable

from g1_interface.internal_types import ImuPayload, LowStateSummary


def _float_list(value: object, length: int, default: list[float]) -> list[float]:
    if value is None:
        return list(default)
    if not isinstance(value, Iterable):
        return list(default)
    result = [float(item) for item in list(value)[:length]]
    while len(result) < length:
        result.append(default[len(result)])
    return result


def lowstate_to_summary(msg: object, source: str, max_motors: int = 35) -> LowStateSummary:
    motors = []
    for motor in list(getattr(msg, "motor_state", []))[:max_motors]:
        motors.append(
            {
                "q": float(getattr(motor, "q", 0.0)),
                "dq": float(getattr(motor, "dq", 0.0)),
                "tau_est": float(getattr(motor, "tau_est", 0.0)),
                "temperature": float(getattr(motor, "temperature", 0.0)),
            }
        )

    temperatures = [motor["temperature"] for motor in motors]
    max_temperature = max(temperatures) if temperatures else None

    return LowStateSummary(
        source=source,
        rpy=_float_list(getattr(msg, "rpy", None), 3, [0.0, 0.0, 0.0]),
        quaternion=_float_list(getattr(msg, "quaternion", None), 4, [1.0, 0.0, 0.0, 0.0]),
        gyroscope=_float_list(getattr(msg, "gyroscope", None), 3, [0.0, 0.0, 0.0]),
        accelerometer=_float_list(getattr(msg, "accelerometer", None), 3, [0.0, 0.0, 0.0]),
        motor_count=len(motors),
        max_temperature_c=max_temperature,
        motors=motors,
    )


def imu_to_payload(msg: object, frame_id: str) -> ImuPayload:
    quaternion_wxyz = _float_list(getattr(msg, "quaternion", None), 4, [1.0, 0.0, 0.0, 0.0])
    return ImuPayload(
        frame_id=frame_id,
        orientation_xyzw=[
            quaternion_wxyz[1],
            quaternion_wxyz[2],
            quaternion_wxyz[3],
            quaternion_wxyz[0],
        ],
        angular_velocity=_float_list(getattr(msg, "gyroscope", None), 3, [0.0, 0.0, 0.0]),
        linear_acceleration=_float_list(getattr(msg, "accelerometer", None), 3, [0.0, 0.0, 0.0]),
    )
```

- [ ] **Step 5: Run the converter tests to verify they pass**

Run:

```bash
cd /home/ubuntu/Desktop/unitree_g1_agent
PYTHONPATH=src/g1_interface pytest src/g1_interface/tests/test_converters.py -q
```

Expected: `3 passed`.

- [ ] **Step 6: Commit**

Run:

```bash
git add src/g1_interface/g1_interface/internal_types.py src/g1_interface/g1_interface/converters.py src/g1_interface/tests/test_converters.py
git commit -m "feat: add g1 state converters"
```

Expected: commit succeeds when executed inside a git checkout.

---

### Task 3: Sport API Request Builder And Response Tracker

**Files:**
- Create: `src/g1_interface/g1_interface/sport_api.py`
- Create: `src/g1_interface/tests/test_sport_api.py`

**Interfaces:**
- Consumes: `SportCommand(action: str, params: dict[str, Any])`
- Produces: `SportApiClient.build_request(command: SportCommand, now_sec: float) -> object`
- Produces: `SportApiClient.record_response(msg: object, now_sec: float) -> dict[str, object]`
- Produces: `SportApiClient.expired_requests(now_sec: float) -> list[PendingApiRequest]`

- [ ] **Step 1: Write the failing sport API tests**

Create `src/g1_interface/tests/test_sport_api.py`:

```python
import json

import pytest

from g1_interface.internal_types import SportCommand
from g1_interface.sport_api import SportApiClient


class FakeRequest:
    def __init__(self):
        self.sequence_id = 0
        self.api_id = 0
        self.parameter = b""


def test_build_velocity_request_sets_sequence_api_id_and_json_payload():
    client = SportApiClient(
        request_cls=FakeRequest,
        api_ids={"set_velocity": 7105},
        response_timeout_sec=0.5,
    )

    request = client.build_request(
        SportCommand(action="set_velocity", params={"velocity": [0.2, 0.0, 0.1], "duration": 1.5}),
        now_sec=10.0,
    )

    assert request.sequence_id == 1
    assert request.api_id == 7105
    assert json.loads(request.parameter.decode("utf-8")) == {"duration": 1.5, "velocity": [0.2, 0.0, 0.1]}
    assert client.pending_count == 1


def test_build_request_rejects_unknown_action():
    client = SportApiClient(request_cls=FakeRequest, api_ids={"set_velocity": 7105}, response_timeout_sec=0.5)

    with pytest.raises(ValueError, match="unsupported sport action"):
        client.build_request(SportCommand(action="dance", params={}), now_sec=10.0)


def test_record_response_clears_pending_request():
    client = SportApiClient(request_cls=FakeRequest, api_ids={"set_velocity": 7105}, response_timeout_sec=0.5)
    request = client.build_request(
        SportCommand(action="set_velocity", params={"velocity": [0.0, 0.0, 0.0], "duration": 0.1}),
        now_sec=10.0,
    )
    response = type("Response", (), {"sequence_id": request.sequence_id, "api_id": request.api_id, "code": 0})()

    result = client.record_response(response, now_sec=10.1)

    assert result == {
        "matched": True,
        "sequence_id": 1,
        "api_id": 7105,
        "action": "set_velocity",
        "code": 0,
        "latency_ms": 100,
    }
    assert client.pending_count == 0


def test_expired_requests_are_returned_and_removed():
    client = SportApiClient(request_cls=FakeRequest, api_ids={"set_velocity": 7105}, response_timeout_sec=0.5)
    client.build_request(
        SportCommand(action="set_velocity", params={"velocity": [0.1, 0.0, 0.0], "duration": 1.0}),
        now_sec=10.0,
    )

    expired = client.expired_requests(now_sec=10.6)

    assert len(expired) == 1
    assert expired[0].action == "set_velocity"
    assert client.pending_count == 0
```

- [ ] **Step 2: Run the sport API tests to verify they fail**

Run:

```bash
cd /home/ubuntu/Desktop/unitree_g1_agent
PYTHONPATH=src/g1_interface pytest src/g1_interface/tests/test_sport_api.py -q
```

Expected: FAIL with `ModuleNotFoundError` or `ImportError` for `g1_interface.sport_api`.

- [ ] **Step 3: Implement the sport API client**

Create `src/g1_interface/g1_interface/sport_api.py`:

```python
from __future__ import annotations

import json
from typing import Callable

from g1_interface.internal_types import PendingApiRequest, SportCommand


class SportApiClient:
    def __init__(
        self,
        request_cls: Callable[[], object],
        api_ids: dict[str, int],
        response_timeout_sec: float,
    ) -> None:
        self._request_cls = request_cls
        self._api_ids = dict(api_ids)
        self._response_timeout_sec = response_timeout_sec
        self._next_sequence_id = 1
        self._pending: dict[int, PendingApiRequest] = {}

    @property
    def pending_count(self) -> int:
        return len(self._pending)

    def build_request(self, command: SportCommand, now_sec: float) -> object:
        api_id = self._api_ids.get(command.action)
        if api_id is None:
            raise ValueError(f"unsupported sport action: {command.action}")

        request = self._request_cls()
        request.sequence_id = self._next_sequence_id
        request.api_id = int(api_id)
        request.parameter = json.dumps(command.params, sort_keys=True).encode("utf-8")

        self._pending[self._next_sequence_id] = PendingApiRequest(
            sequence_id=self._next_sequence_id,
            api_id=int(api_id),
            action=command.action,
            created_monotonic_sec=now_sec,
        )
        self._next_sequence_id += 1
        return request

    def record_response(self, msg: object, now_sec: float) -> dict[str, object]:
        sequence_id = int(getattr(msg, "sequence_id", 0))
        pending = self._pending.pop(sequence_id, None)
        if pending is None:
            return {
                "matched": False,
                "sequence_id": sequence_id,
                "api_id": int(getattr(msg, "api_id", 0)),
                "code": int(getattr(msg, "code", -1)),
            }

        latency_ms = int(round((now_sec - pending.created_monotonic_sec) * 1000))
        return {
            "matched": True,
            "sequence_id": pending.sequence_id,
            "api_id": pending.api_id,
            "action": pending.action,
            "code": int(getattr(msg, "code", -1)),
            "latency_ms": latency_ms,
        }

    def expired_requests(self, now_sec: float) -> list[PendingApiRequest]:
        expired = [
            pending
            for pending in self._pending.values()
            if now_sec - pending.created_monotonic_sec > self._response_timeout_sec
        ]
        for pending in expired:
            self._pending.pop(pending.sequence_id, None)
        return expired
```

- [ ] **Step 4: Run the sport API tests to verify they pass**

Run:

```bash
cd /home/ubuntu/Desktop/unitree_g1_agent
PYTHONPATH=src/g1_interface pytest src/g1_interface/tests/test_sport_api.py -q
```

Expected: `4 passed`.

- [ ] **Step 5: Commit**

Run:

```bash
git add src/g1_interface/g1_interface/sport_api.py src/g1_interface/tests/test_sport_api.py
git commit -m "feat: add sport api request tracking"
```

Expected: commit succeeds when executed inside a git checkout.

---

### Task 4: ROS Node Helper Functions

**Files:**
- Create: `src/g1_interface/tests/test_node_helpers.py`
- Modify: `src/g1_interface/g1_interface/node.py`

**Interfaces:**
- Consumes: `SportCommand`
- Produces: `parse_safe_loco_command(raw_json: str) -> SportCommand`
- Produces: `parse_stop_command(raw_json: str) -> SportCommand`
- Produces: `build_health_status(...) -> dict[str, object]`

- [ ] **Step 1: Write the failing helper tests**

Create `src/g1_interface/tests/test_node_helpers.py`:

```python
import pytest

from g1_interface.node import build_health_status, parse_safe_loco_command, parse_stop_command


def test_parse_safe_loco_command_clamps_to_required_fields():
    command = parse_safe_loco_command('{"vx": 0.2, "vy": -0.1, "vyaw": 0.3, "duration_sec": 1.5}')

    assert command.action == "set_velocity"
    assert command.params == {"velocity": [0.2, -0.1, 0.3], "duration": 1.5}


def test_parse_safe_loco_command_rejects_missing_velocity():
    with pytest.raises(ValueError, match="missing required loco field"):
        parse_safe_loco_command('{"vx": 0.2, "vy": 0.0}')


def test_parse_stop_command_always_builds_zero_velocity():
    command = parse_stop_command("{}")

    assert command.action == "set_velocity"
    assert command.params == {"velocity": [0.0, 0.0, 0.0], "duration": 0.1}


def test_health_status_reports_stale_state_and_pending_api():
    status = build_health_status(
        now_sec=12.0,
        last_lowstate_sec=11.6,
        state_timeout_sec=0.3,
        pending_api_count=2,
        last_api_result={"code": 0, "action": "move"},
    )

    assert status["state"] == "degraded"
    assert status["lowstate_age_ms"] == 400
    assert status["pending_api_count"] == 2
    assert status["last_api_result"] == {"code": 0, "action": "move"}
```

- [ ] **Step 2: Run the helper tests to verify they fail**

Run:

```bash
cd /home/ubuntu/Desktop/unitree_g1_agent
PYTHONPATH=src/g1_interface pytest src/g1_interface/tests/test_node_helpers.py -q
```

Expected: FAIL with `ModuleNotFoundError` or missing helper functions.

- [ ] **Step 3: Implement node helper functions**

Create `src/g1_interface/g1_interface/node.py` with these helper functions at the top:

```python
from __future__ import annotations

import json
from typing import Any

from g1_interface.internal_types import SportCommand


def parse_safe_loco_command(raw_json: str) -> SportCommand:
    payload = json.loads(raw_json)
    required = ["vx", "vy", "vyaw", "duration_sec"]
    missing = [field for field in required if field not in payload]
    if missing:
        raise ValueError(f"missing required loco field: {', '.join(missing)}")
    return SportCommand(
        action="set_velocity",
        params={
            "velocity": [float(payload["vx"]), float(payload["vy"]), float(payload["vyaw"])],
            "duration": float(payload["duration_sec"]),
        },
    )


def parse_stop_command(raw_json: str) -> SportCommand:
    if raw_json.strip():
        json.loads(raw_json)
    return SportCommand(action="set_velocity", params={"velocity": [0.0, 0.0, 0.0], "duration": 0.1})


def build_health_status(
    now_sec: float,
    last_lowstate_sec: float | None,
    state_timeout_sec: float,
    pending_api_count: int,
    last_api_result: dict[str, Any] | None,
) -> dict[str, Any]:
    if last_lowstate_sec is None:
        lowstate_age_ms = None
        state = "unhealthy"
    else:
        lowstate_age_ms = int(round((now_sec - last_lowstate_sec) * 1000))
        state = "ok" if now_sec - last_lowstate_sec <= state_timeout_sec else "degraded"

    return {
        "state": state,
        "lowstate_age_ms": lowstate_age_ms,
        "pending_api_count": pending_api_count,
        "last_api_result": last_api_result,
    }
```

- [ ] **Step 4: Run helper tests to verify they pass**

Run:

```bash
cd /home/ubuntu/Desktop/unitree_g1_agent
PYTHONPATH=src/g1_interface pytest src/g1_interface/tests/test_node_helpers.py -q
```

Expected: `4 passed`.

- [ ] **Step 5: Commit**

Run:

```bash
git add src/g1_interface/g1_interface/node.py src/g1_interface/tests/test_node_helpers.py
git commit -m "feat: add g1 node helper logic"
```

Expected: commit succeeds when executed inside a git checkout.

---

### Task 5: Runtime ROS2 Node Wiring

**Files:**
- Modify: `src/g1_interface/g1_interface/node.py`
- Create: `src/g1_interface/launch/g1_interface.launch.py`

**Interfaces:**
- Consumes native Unitree topics: `lowstate`, `lf/lowstate`, `secondary_imu`, `/api/sport/response`
- Produces internal topics: `/g1/state/health`, `/g1/state/low`, `/g1/state/imu`, `/g1/state/motors`, `/g1/state/mode`
- Consumes safe command topics: `/g1/safe_cmd/loco`, `/g1/safe_cmd/stop`
- Publishes native command topic: `/api/sport/request`

- [ ] **Step 1: Run all existing unit tests before wiring ROS imports**

Run:

```bash
cd /home/ubuntu/Desktop/unitree_g1_agent
PYTHONPATH=src/g1_interface pytest src/g1_interface/tests -q
```

Expected: `10 passed`.

- [ ] **Step 2: Implement lazy ROS imports and the node class**

Append this code to `src/g1_interface/g1_interface/node.py` below the helper functions:

```python
def _load_ros_messages():
    from diagnostic_msgs.msg import DiagnosticArray, DiagnosticStatus, KeyValue
    from sensor_msgs.msg import Imu
    from std_msgs.msg import String
    from unitree_api.msg import Request, Response
    from unitree_hg.msg import IMUState, LowState

    return {
        "DiagnosticArray": DiagnosticArray,
        "DiagnosticStatus": DiagnosticStatus,
        "KeyValue": KeyValue,
        "Imu": Imu,
        "String": String,
        "Request": Request,
        "Response": Response,
        "IMUState": IMUState,
        "LowState": LowState,
    }
```

Then append:

```python
class G1InterfaceNode:
    def __init__(self, node, config):
        self.node = node
        self.config = config
        self.msg = _load_ros_messages()
        self.last_lowstate_sec = None
        self.last_api_result = None
        self.state_timeout_sec = config.timeouts["state_timeout_ms"] / 1000.0

        from g1_interface.converters import imu_to_payload, lowstate_to_summary
        from g1_interface.sport_api import SportApiClient

        self._imu_to_payload = imu_to_payload
        self._lowstate_to_summary = lowstate_to_summary
        self._sport_api = SportApiClient(
            request_cls=self.msg["Request"],
            api_ids=config.sport_api["api_ids"],
            response_timeout_sec=config.timeouts["api_response_timeout_ms"] / 1000.0,
        )

        self.low_pub = node.create_publisher(self.msg["String"], "/g1/state/low", 10)
        self.motor_pub = node.create_publisher(self.msg["String"], "/g1/state/motors", 10)
        self.mode_pub = node.create_publisher(self.msg["String"], "/g1/state/mode", 10)
        self.health_pub = node.create_publisher(self.msg["DiagnosticArray"], "/g1/state/health", 10)
        self.imu_pub = node.create_publisher(self.msg["Imu"], "/g1/state/imu", 10)
        self.sport_request_pub = node.create_publisher(
            self.msg["Request"],
            config.native_topics["sport_request"],
            10,
        )

        node.create_subscription(
            self.msg["LowState"],
            config.native_topics["low_state"],
            self.on_lowstate,
            10,
        )
        node.create_subscription(
            self.msg["LowState"],
            config.native_topics["low_state_low_freq"],
            self.on_lowstate_low_freq,
            10,
        )
        node.create_subscription(
            self.msg["IMUState"],
            config.native_topics["secondary_imu"],
            self.on_secondary_imu,
            10,
        )
        node.create_subscription(
            self.msg["Response"],
            config.native_topics["sport_response"],
            self.on_sport_response,
            10,
        )
        node.create_subscription(self.msg["String"], "/g1/safe_cmd/loco", self.on_safe_loco, 10)
        node.create_subscription(self.msg["String"], "/g1/safe_cmd/stop", self.on_safe_stop, 10)

        period = config.timeouts["health_publish_period_ms"] / 1000.0
        node.create_timer(period, self.publish_health)

    def _now_sec(self):
        return self.node.get_clock().now().nanoseconds / 1_000_000_000.0

    def on_lowstate(self, msg):
        self.last_lowstate_sec = self._now_sec()
        summary = self._lowstate_to_summary(msg, source=self.config.native_topics["low_state"])
        text = self.msg["String"]()
        text.data = summary.to_json()
        self.low_pub.publish(text)

        motor_text = self.msg["String"]()
        motor_text.data = json.dumps(
            {"motor_count": summary.motor_count, "motors": summary.motors},
            ensure_ascii=False,
            sort_keys=True,
        )
        self.motor_pub.publish(motor_text)

    def on_lowstate_low_freq(self, msg):
        summary = self._lowstate_to_summary(msg, source=self.config.native_topics["low_state_low_freq"])
        mode_text = self.msg["String"]()
        mode_text.data = json.dumps(
            {"source": summary.source, "rpy": summary.rpy, "motor_count": summary.motor_count},
            ensure_ascii=False,
            sort_keys=True,
        )
        self.mode_pub.publish(mode_text)

    def on_secondary_imu(self, msg):
        payload = self._imu_to_payload(msg, frame_id="g1_torso")
        imu = self.msg["Imu"]()
        imu.header.frame_id = payload.frame_id
        imu.orientation.x = payload.orientation_xyzw[0]
        imu.orientation.y = payload.orientation_xyzw[1]
        imu.orientation.z = payload.orientation_xyzw[2]
        imu.orientation.w = payload.orientation_xyzw[3]
        imu.angular_velocity.x = payload.angular_velocity[0]
        imu.angular_velocity.y = payload.angular_velocity[1]
        imu.angular_velocity.z = payload.angular_velocity[2]
        imu.linear_acceleration.x = payload.linear_acceleration[0]
        imu.linear_acceleration.y = payload.linear_acceleration[1]
        imu.linear_acceleration.z = payload.linear_acceleration[2]
        self.imu_pub.publish(imu)

    def on_sport_response(self, msg):
        self.last_api_result = self._sport_api.record_response(msg, now_sec=self._now_sec())

    def on_safe_loco(self, msg):
        command = parse_safe_loco_command(msg.data)
        request = self._sport_api.build_request(command, now_sec=self._now_sec())
        self.sport_request_pub.publish(request)

    def on_safe_stop(self, msg):
        command = parse_stop_command(msg.data)
        request = self._sport_api.build_request(command, now_sec=self._now_sec())
        self.sport_request_pub.publish(request)

    def publish_health(self):
        now_sec = self._now_sec()
        for expired in self._sport_api.expired_requests(now_sec):
            self.node.get_logger().warning(
                f"sport API request timed out: sequence_id={expired.sequence_id} action={expired.action}"
            )

        status_payload = build_health_status(
            now_sec=now_sec,
            last_lowstate_sec=self.last_lowstate_sec,
            state_timeout_sec=self.state_timeout_sec,
            pending_api_count=self._sport_api.pending_count,
            last_api_result=self.last_api_result,
        )

        status = self.msg["DiagnosticStatus"]()
        status.name = "g1_interface"
        status.level = 0 if status_payload["state"] == "ok" else 1
        status.message = status_payload["state"]
        for key, value in status_payload.items():
            pair = self.msg["KeyValue"]()
            pair.key = str(key)
            pair.value = json.dumps(value, ensure_ascii=False, sort_keys=True)
            status.values.append(pair)

        array = self.msg["DiagnosticArray"]()
        array.status.append(status)
        self.health_pub.publish(array)
```

Then append the executable entry point:

```python
def main(args=None):
    import rclpy

    from g1_interface.config import G1InterfaceConfig

    rclpy.init(args=args)
    node = rclpy.create_node("g1_interface_node")
    node.declare_parameter("config_path", "")
    config_path = node.get_parameter("config_path").get_parameter_value().string_value
    config = G1InterfaceConfig.from_yaml(config_path) if config_path else G1InterfaceConfig.default()
    G1InterfaceNode(node=node, config=config)
    try:
        rclpy.spin(node)
    finally:
        node.destroy_node()
        rclpy.shutdown()


if __name__ == "__main__":
    main()
```

- [ ] **Step 3: Add the launch file**

Create `src/g1_interface/launch/g1_interface.launch.py`:

```python
from launch import LaunchDescription
from launch.actions import DeclareLaunchArgument
from launch.substitutions import LaunchConfiguration
from launch_ros.actions import Node


def generate_launch_description():
    config_path = LaunchConfiguration("config_path")
    return LaunchDescription(
        [
            DeclareLaunchArgument("config_path", default_value=""),
            Node(
                package="g1_interface",
                executable="g1_interface_node",
                name="g1_interface_node",
                output="screen",
                parameters=[{"config_path": config_path}],
            ),
        ]
    )
```

- [ ] **Step 4: Run unit tests after ROS wiring**

Run:

```bash
cd /home/ubuntu/Desktop/unitree_g1_agent
PYTHONPATH=src/g1_interface pytest src/g1_interface/tests -q
```

Expected: `10 passed`.

- [ ] **Step 5: Build the ROS package**

Run in a shell where `/opt/ros/humble/setup.bash` and Unitree ROS2 packages are sourced:

```bash
cd /home/ubuntu/Desktop/unitree_g1_agent
colcon build --symlink-install --packages-select g1_interface
```

Expected: build exits with code 0 and installs `g1_interface_node`.

- [ ] **Step 6: Commit**

Run:

```bash
git add src/g1_interface/g1_interface/node.py src/g1_interface/launch/g1_interface.launch.py
git commit -m "feat: wire g1 interface ros node"
```

Expected: commit succeeds when executed inside a git checkout.

---

### Task 6: Local Verification Commands And Documentation

**Files:**
- Create: `src/g1_interface/README.md`
- Modify: `docs/设计文档.md`

**Interfaces:**
- Produces documented commands for unit tests, colcon build, launch, topic echo, and safe command smoke test.

- [ ] **Step 1: Create package README**

Create `src/g1_interface/README.md`:

````markdown
# g1_interface

ROS2 Python interface node for Unitree G1 P0 state bridging and high-level sport API commands.

## Unit Tests

```bash
PYTHONPATH=src/g1_interface pytest src/g1_interface/tests -q
```

## Build

```bash
source /opt/ros/humble/setup.bash
source <unitree_ros2_install>/setup.bash
colcon build --symlink-install --packages-select g1_interface
source install/setup.bash
```

## Launch

```bash
ros2 launch g1_interface g1_interface.launch.py \
  config_path:=src/g1_interface/config/g1_interface.yaml
```

## Read-Only Verification

```bash
ros2 topic echo /g1/state/health
ros2 topic echo /g1/state/low
ros2 topic echo /g1/state/imu
```

## Safe Command Smoke Test

Run this only after `/g1/state/health` reports fresh lowstate data and the robot is in a safe test posture.

```bash
ros2 topic pub /g1/safe_cmd/stop std_msgs/msg/String '{data: "{}"}' --once
ros2 topic echo /api/sport/request
```
````

- [ ] **Step 2: Add an implementation note to the design document**

Add this paragraph after `### 8.2 阶段 1：G1 接口节点 P0` in `docs/设计文档.md`:

```markdown
实现计划见 `docs/superpowers/plans/2026-07-04-g1-interface-node.md`。P0 实现优先交付 Python `ament_python` 包 `src/g1_interface`，用纯 Python 单元测试覆盖配置、状态转换、`/api/sport` 请求构造和健康状态逻辑，再用 ROS2/Unitree 真机环境验证 topic wiring。
```

- [ ] **Step 3: Run documentation and unit verification**

Run:

```bash
cd /home/ubuntu/Desktop/unitree_g1_agent
PYTHONPATH=src/g1_interface pytest src/g1_interface/tests -q
rg -n "g1_interface|/api/sport|lowstate" src/g1_interface/README.md docs/设计文档.md
```

Expected: pytest reports `10 passed`; `rg` prints matches from both files.

- [ ] **Step 4: Commit**

Run:

```bash
git add src/g1_interface/README.md docs/设计文档.md
git commit -m "docs: add g1 interface verification guide"
```

Expected: commit succeeds when executed inside a git checkout.

---

## Self-Review

**Spec coverage:**
- Unitree native state topics are covered by Task 2 and Task 5.
- `/api/sport/request` and `/api/sport/response` are covered by Task 3 and Task 5.
- The P0 ban on `/lowcmd` is enforced by package scope: no publisher is created for `/lowcmd`.
- Internal `/g1/state/*` and `/g1/safe_cmd/*` boundaries are covered by Task 5.
- Configurable topic names and G1 profile data are covered by Task 1.
- Read-only verification and smoke commands are covered by Task 6.

**Known execution constraints:**
- `colcon build` requires ROS2 Humble and Unitree message packages sourced in the shell.
- This repository directory is not currently a git repository; commit steps are valid for execution inside a git checkout.
- Sport API parameter encoding is implemented as deterministic JSON bytes matching `docs/G1_H1_API_Documentation.md` `JsonizeVelocityCommand` shape: `velocity: [vx, vy, vyaw]` and `duration`. Before real movement, verify on the robot that `/api/sport/request` accepts this JSON payload for API ID `7105`.
