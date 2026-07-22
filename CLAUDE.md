# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working in this repository.

## Project Overview

This is a ROS2-based control stack for the Unitree G1 humanoid robot. The project is moving from direct CLI/SDK-style control toward a maintainable ROS2 architecture that preserves Pi Agent voice interaction while enforcing a safety boundary around all motion.

Current packages:

- `src/g1_interface`: bridge from Unitree native ROS2 topics/APIs to project-internal state topics.
- `src/voice_bridge`: voice/Pi Agent bridge package.
- `src/g1_sim`: simulator for the official Unitree G1 native topic surface.
- `safety_controller`: planned safety layer; design work lives under `docs/`.

Official Unitree SDK/ROS2 source snapshots may be present under `.unitree/` for local evidence gathering. That directory is ignored and should not be committed.

## Architecture

All motion commands must pass through the safety layer before reaching robot-native command topics.

```text
Application Layer (voice, vision, tools)
  -> Safety Control Layer (limits, mode gating, timeouts)
  -> G1 Interface Layer (ROS2/DDS bridge)
  -> Unitree G1 Hardware or g1_sim
```

Interface boundaries:

- Unitree native topics: `lowstate`, `lf/lowstate`, `secondary_imu`, `/lowcmd`, `/arm_sdk`, `/dex3/*`, `/api/*`.
- Project state topics: `/g1/state/*`, `/g1/audio/*`.
- Safety command topics: `/g1/safe_cmd/*`, `/g1/state/safety`.
- Application intent topics: `/voice/cmd/*`, `/g1/cmd/audio/*`.

## Safety Rules

1. Application nodes must not publish directly to `/lowcmd`, `/arm_sdk`, or `/dex3/*/cmd`.
2. Motion commands must be routed through the safety layer.
3. Safety code must enforce velocity limits, command duration limits, state freshness checks, and mode gating.
4. Mode switches that affect safety must require explicit handling and should not be hidden inside application logic.
5. Avoid mixing high-level locomotion (`/api/sport`) and low-level control (`/lowcmd`) without an explicit ownership switch.

Default safety limits used in design docs:

```yaml
safety:
  max_vx: 0.5
  max_vy: 0.3
  max_vyaw: 0.8
  max_duration_sec: 5.0
  command_timeout_ms: 500
  state_timeout_ms: 300
```

## ROS2 And Unitree Naming

Use ROS2 topic names in ROS2 nodes. Do not create ROS2 topics named `rt/...`.

SDK2 examples use DDS channel names such as `rt/lowstate` and `rt/api/sport/request`. ROS2 normal topics are mapped by the RMW layer to DDS names with the `rt/` prefix:

- SDK2 `rt/lowstate` maps to ROS2 `lowstate`.
- SDK2 `rt/lowcmd` maps to ROS2 `/lowcmd` or `lowcmd`.
- SDK2 `rt/arm_sdk` maps to ROS2 `/arm_sdk`.
- SDK2 `rt/audio_msg` maps to ROS2 `/audio_msg`.
- SDK2 `rt/api/sport/request` maps to ROS2 `/api/sport/request`.

`g1_sim` should simulate the ROS2-visible official hardware surface, not project-internal topics or application closed loops.

## Native Topic Reference

State topics:

- `lowstate`: high-rate `unitree_hg/msg/LowState`.
- `lf/lowstate`: low-rate `unitree_hg/msg/LowState`.
- `secondary_imu`: torso `unitree_hg/msg/IMUState`.
- `/lf/dex3/left/state`, `/lf/dex3/right/state`: Dex3 hand state.

Control topics:

- `/lowcmd`, `lowcmd`: low-level `unitree_hg/msg/LowCmd`.
- `/arm_sdk`: arm SDK `unitree_hg/msg/LowCmd`.
- `/user_lowcmd`: SDK2 user low command alias.
- `/dex3/left/cmd`, `/dex3/right/cmd`: `unitree_hg/msg/HandCmd`.

Request/response APIs:

- `/api/sport/request`, `/api/sport/response`.
- `/api/arm/request`, `/api/arm/response`.
- `/api/voice/request`, `/api/voice/response`.
- `/api/motion_switcher/request`, `/api/motion_switcher/response`.
- `/api/agv/request`, `/api/agv/response` where supported by target firmware.

Key G1 API IDs:

- Sport: `7001` get FSM ID, `7002` get FSM mode, `7105` set velocity, `7110` switch to user control, `7111` switch to internal control.
- Voice: `1001` TTS, `1002` ASR, `1005` get volume, `1006` set volume, `1010` set RGB LED.

## Development Environment

ROS 2 Foxy is the current real-robot baseline. Unitree SDK2 and ROS2 message packages are
downloaded and built from pinned source revisions by the Makefile.

```bash
make unitree-source
make unitree-build
make foxy-build
```

ROS2/CycloneDDS prerequisites:

- Source `/opt/ros/foxy/setup.bash` before using the built Unitree overlay.
- Use `RMW_IMPLEMENTATION=rmw_cyclonedds_cpp`.
- Set `CYCLONEDDS_URI` to the robot network interface for hardware, or `lo` for local simulation.
- Typical Unitree robot network: `192.168.123.0/24`.

Useful checks:

```bash
ros2 pkg list | grep unitree
ros2 topic echo /lowstate --once
ros2 topic echo /lf/lowstate --once
ros2 topic echo /secondary_imu --once
ros2 topic echo /api/sport/response --once
```

## Test Commands

Run focused Python tests from the repository root:

```bash
PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 PYTHONPATH=src/g1_interface .venv/bin/python -m pytest src/g1_interface/tests -q
PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 PYTHONPATH=src/voice_bridge .venv/bin/python -m pytest src/voice_bridge/tests -q
PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 PYTHONPATH=src/g1_sim .venv/bin/python -m pytest src/g1_sim/tests -q
```

Build ROS2 packages when a ROS2 environment is available:

```bash
source /opt/ros/foxy/setup.bash
make foxy-build
source install-foxy/setup.bash
```

## Important Files

- `docs/设计文档.md`: overall architecture.
- `docs/unitree_ros2_topics.md`: ROS2 topic reference.
- `docs/G1_H1_API_Documentation.md`: API IDs and interfaces.
- `docs/unitree_sdk2.md`: SDK2 reference.
- `docs/g1_native_topic_sim.md`: evidence and design notes for `g1_sim`.
- `src/g1_interface/README.md`: G1 interface package usage.
- `src/g1_sim/README.md`: simulator package usage.

## Development Priorities

1. P0: read-only state bridge plus high-level locomotion request path.
2. P0: safety layer with limits, timeout protection, state freshness checks, and mode ownership.
3. P0: voice bridge routed through safety-controlled commands.
4. P1: vision and arm workflows after P0 verification on simulator and hardware.

## External References

- Unitree Developer Support: https://support.unitree.com/home/zh/developer
- unitree_sdk2 GitHub: https://github.com/unitreerobotics/unitree_sdk2
- unitree_ros2 GitHub: https://github.com/unitreerobotics/unitree_ros2
- ROS2 Documentation: https://docs.ros.org/en/foxy/
- CycloneDDS Documentation: https://docs.cyclonedds.io/en/latest/
