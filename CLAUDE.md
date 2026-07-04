# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

This is a **Unitree G1 Agent** project - a ROS2-based control system for the Unitree G1 humanoid robot. The project is currently in early development stage (design phase) with source directories yet to be populated.

**Key Goal**: Transform a Rust CLI-based G1 control system into a maintainable ROS2 architecture while preserving Pi Agent voice interaction capabilities.

**Robot Model**: Unitree G1 humanoid robot (23/29/35 DoF versions)

## Architecture Philosophy

### Layered Safety-First Architecture

```
Application Layer (Voice/Vision Nodes)
    ↓
Safety Control Layer (Safety limits, mode gating, timeout protection)
    ↓  
G1 Interface Layer (ROS2/DDS bridge to robot hardware)
    ↓
Unitree G1 Robot Hardware
```

**Critical Safety Principle**: All motion commands MUST pass through the safety control node. Application nodes never directly publish to Unitree native topics like `/lowcmd`, `/arm_sdk`, or `/api/*`.

### Interface Boundaries

- **Unitree Native Layer**: `lowstate`, `/lowcmd`, `/api/*`, `/dex3/*` (hardware-specific)
- **G1 Interface Node Output**: `/g1/state/*`, `/g1/audio/*` (project-internal stable interface)
- **Safety Node Output**: `/g1/safe_cmd/*`, `/g1/state/safety` (safety-validated commands)
- **Application Layer**: `/voice/cmd/*`, `/g1/cmd/audio/*` (intent from voice/vision)

## Development Environment

### Nix Flake Development Shell

This project uses Nix for reproducible development environments.

```bash
# Enter development environment
nix develop

# Or if using older Nix version
nix-shell

# Build packages
nix build .#unitree-sdk2    # Build SDK2
nix build .#unitree-ros2     # Build ROS2 packages
nix build .#default          # Build default (unitree-sdk2)
```

### Environment Prerequisites

**IMPORTANT**: The Nix environment depends on system-level ROS2 Humble installation:

- ROS2 Humble must be installed at `/opt/ros/humble`
- The development shell automatically sources ROS2 environment
- CycloneDDS configuration (`CYCLONEDDS_URI`) must be set for robot communication

### Network Configuration

**CycloneDDS Network Setup**:
- Real robot: Set `CYCLONEDDS_URI` to point to robot network interface (e.g., `enp3s0`)
- Local testing: Use `lo` (loopback) interface
- Typical robot network: `192.168.123.0/24`

## Project Structure

```
├── flake.nix                  # Nix flake configuration
├── nix/
│   └── pkgs/
│       ├── unitree-sdk2.nix   # SDK2 package definition
│       └── unitree-ros2.nix   # ROS2 packages definition
├── third/
│   └── unitree_sdk2/          # Unitree SDK2 source (vendored)
├── docs/
│   ├── 设计文档.md            # Architecture design doc (Chinese)
│   ├── unitree_ros2_topics.md # Complete ROS2 topics reference
│   ├── G1_H1_API_Documentation.md # API IDs and interfaces
│   └── unitree_sdk2.md        # SDK2 documentation
└── src/                       # Source code (to be implemented)
    ├── g1_interface/          # G1 interface ROS2 node
    ├── safety_controller/     # Safety control node
    ├── voice_bridge/          # Voice/Pi Agent bridge node
    └── vision/                # RealSense vision node (future)
```

## Build and Test Commands

### Building Project Packages

```bash
# Using Nix (recommended)
nix build .#unitree-sdk2
nix build .#unitree-ros2

# Manual build of SDK2 (if needed)
cd third/unitree_sdk2
mkdir build && cd build
cmake .. -G Ninja -DCMAKE_BUILD_TYPE=Release
ninja
```

### ROS2 Environment Setup

```bash
# After entering nix develop, ROS2 is already sourced
# Verify ROS2 installation
ros2 --version

# Check available topics (if robot connected)
ros2 topic list

# Verify unitree packages
ros2 pkg list | grep unitree
```

### Testing Communication with Robot

```bash
# Test low-level state (500Hz)
ros2 topic echo /lowstate

# Test low-frequency state (~50Hz)  
ros2 topic echo /lf/lowstate

# Test IMU data
ros2 topic echo /secondary_imu

# Test high-level API response
ros2 topic echo /api/sport/response
```

## ROS2 Topics Reference

### Unitree Native Topics (Input to Interface Node)

**State Topics**:
- `lowstate` - High-frequency (500Hz) robot state
- `lf/lowstate` - Low-frequency (~50Hz) robot state  
- `secondary_imu` - Torso IMU data (500Hz)

**Control Topics** (must go through safety layer):
- `/lowcmd` - Low-level motor commands (500Hz) - **SAFETY CRITICAL**
- `/arm_sdk` - Arm SDK control (50Hz) - **SAFETY CRITICAL**
- `/dex3/left/cmd`, `/dex3/right/cmd` - Hand control - **SAFETY CRITICAL**

**API Request/Response**:
- `/api/sport/request` - Locomotion API requests
- `/api/sport/response` - Locomotion API responses
- `/api/arm/request` - Arm action API requests
- `/api/voice/request` - Audio/voice API requests
- `/api/motion_switcher/request` - Mode switching requests

### Project-Internal Topics (Output from Interface Node)

**State Topics**:
- `/g1/state/health` - Node health, DDS connectivity
- `/g1/state/low` - Standardized low-level state summary
- `/g1/state/imu` - IMU orientation, angular velocity
- `/g1/state/motors` - Motor positions, velocities, torques, temperatures
- `/g1/state/bms` - Battery voltage, current, capacity
- `/g1/state/mode` - FSM state, motion mode, control ownership

**Command Topics** (input to safety layer):
- `/g1/safe_cmd/loco` - Safety-validated locomotion commands
- `/g1/safe_cmd/arm` - Safety-validated arm commands
- `/g1/safe_cmd/hand` - Safety-validated hand commands

**Audio Topics**:
- `/g1/audio/asr` - ASR text events
- `/g1/audio/status` - Audio service status

## Safety-Critical Development Rules

### ⚠️ CRITICAL SAFETY RULES

1. **NEVER** directly publish to `/lowcmd`, `/arm_sdk`, or `/dex3/*/cmd` from application nodes
2. **ALWAYS** route motion commands through safety control node
3. **ALWAYS** implement velocity limits, duration limits, and mode gating in safety node
4. **ALWAYS** require manual confirmation for mode switches that affect safety
5. **NEVER** allow high-level locomotion (`/api/sport`) and low-level control (`/lowcmd`) simultaneously

### Default Safety Limits

```yaml
safety:
  max_vx: 0.5        # Max forward velocity (m/s)
  max_vy: 0.3        # Max lateral velocity (m/s) 
  max_vyaw: 0.8      # Max yaw rate (rad/s)
  max_duration_sec: 5.0  # Max single command duration
  command_timeout_ms: 500  # Command timeout
  state_timeout_ms: 300   # State timeout
```

## Common Development Patterns

### ROS2 Node Creation

```bash
# Create new ROS2 package
ros2 pkg create --build-type ament_python <package_name>
ros2 pkg create --build-type ament_cmake <package_name>

# Build ROS2 workspace
cd <workspace>
colcon build --symlink-install
source install/setup.bash
```

### Running and Debugging

```bash
# Run a node
ros2 run <package_name> <node_name>

# Launch file
ros2 launch <package_name> <launch_file>

# Monitor topics
ros2 topic list
ros2 topic echo <topic_name>
ros2 topic hz <topic_name>

# Debug DDS issues
RMW_IMPLEMENTATION=rmw_cyclonedds_cpp ros2 topic list
```

## Common Issues and Solutions

### CycloneDDS Connection Issues

**Problem**: Cannot see topics from robot

**Solutions**:
1. Check `CYCLONEDDS_URI` points to correct network interface
2. Verify network connectivity: `ping <robot_ip>`
3. Check firewall rules
4. Verify `RMW_IMPLEMENTATION=rmw_cyclonedds_cpp`

### ROS2 Environment Issues

**Problem**: Cannot find unitree packages

**Solutions**:
1. Ensure `/opt/ros/humble/setup.bash` is sourced
2. Ensure unitree_ros2 install directory is in `AMENT_PREFIX_PATH`
3. Verify build completed successfully: `colcon build`

### Build Issues

**Problem**: Nix build fails

**Solutions**:
1. Update flake.lock: `nix flake update`
2. Check system dependencies (ROS2 must be pre-installed)
3. Verify network connectivity for GitHub dependencies

## Phase 0: Interface Inventory

Before development, perform robot interface inventory:

```bash
# 1. Check network interface
ip addr show

# 2. Set up environment
source /opt/ros/humble/setup.bash
export RMW_IMPLEMENTATION=rmw_cyclonedds_cpp
export CYCLONEDDS_URI=<path_to_cyclonedds_config>

# 3. List all topics
ros2 topic list > docs/g1_topics_list.txt

# 4. Verify low-level state
ros2 topic echo /lowstate --once

# 5. Verify high-level API
ros2 topic echo /api/sport/response --once
```

## Key API IDs for G1

### Locomotion API (Service: "sport")

- `7001` - Get FSM ID
- `7002` - Get FSM mode  
- `7105` - Set velocity `[vx, vy, vyaw, duration]`
- `7110` - Switch to user control
- `7111` - Switch to internal control

### Voice/Audio API (Service: "voice")

- `1001` - Text-to-speech (TTS)
- `1002` - Automatic speech recognition (ASR)
- `1005` - Get volume
- `1006` - Set volume
- `1010` - Set RGB LED

## Important File Locations

- **Design Doc**: [docs/设计文档.md](docs/设计文档.md) - Comprehensive architecture (Chinese)
- **Topics Reference**: [docs/unitree_ros2_topics.md](docs/unitree_ros2_topics.md) - Complete topics list
- **API Documentation**: [docs/G1_H1_API_Documentation.md](docs/G1_H1_API_Documentation.md) - API IDs
- **SDK2 Reference**: [docs/unitree_sdk2.md](docs/unitree_sdk2.md) - SDK2 interfaces
- **Nix Packages**: [nix/pkgs/](nix/pkgs/) - Package definitions
- **Unitree SDK2**: [third/unitree_sdk2/](third/unitree_sdk2/) - Official SDK

## Development Priorities

1. **P0 - Basic Interface**: Read-only state bridge + high-level locomotion
2. **P0 - Safety Layer**: Velocity limits, timeout protection, mode gating
3. **P0 - Voice Bridge**: Restore voice control via safety layer
4. **P1 - Vision/Arms**: RealSense integration + arm control (post-P0 verification)

## External References

- Unitree Developer Support: https://support.unitree.com/home/zh/developer
- unitree_sdk2 GitHub: https://github.com/unitreerobotics/unitree_sdk2
- unitree_ros2 GitHub: https://github.com/unitreerobotics/unitree_ros2
- ROS2 Documentation: https://docs.ros.org/en/humble/
- CycloneDDS Documentation: https://docs.cyclonedds.io/en/latest/