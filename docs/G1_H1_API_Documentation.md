# Unitree G1 & H1 High-Level API Documentation

## Overview

This document provides a comprehensive overview of the high-level API IDs and interfaces for Unitree G1 and H1 humanoid robots. The APIs are organized by robot model and service category.

---

## G1 Robot APIs

### Service Architecture

G1 robot uses the following services:
- **Sport Service** (`"sport"`) - Locomotion control
- **Arm Service** (`"arm"`) - Arm manipulation
- **Voice Service** (`"voice"`) - Audio and voice control
- **AGV Service** (`"agv"`) - Mobile base control

### API Version Information

| Service | Version |
|---------|---------|
| Locomotion (Sport) | 1.0.0.0 |
| Arm Action | 1.0.0.14 |
| Audio/Voice | 1.0.0.0 |
| AGV | 1.0.0.1 |

---

### G1 Locomotion API (Service: `"sport"`)

**Base API ID Range: 7000-7199**

#### Get Operations (7001-7006)

| API ID | Constant Name | Description | Status |
|--------|---------------|-------------|--------|
| 7001 | `ROBOT_API_ID_LOCO_GET_FSM_ID` | Get current FSM state ID | Active |
| 7002 | `ROBOT_API_ID_LOCO_GET_FSM_MODE` | Get FSM mode | Active |
| 7003 | `ROBOT_API_ID_LOCO_GET_BALANCE_MODE` | Get balance mode | Active |
| 7004 | `ROBOT_API_ID_LOCO_GET_SWING_HEIGHT` | Get swing height | Active |
| 7005 | `ROBOT_API_ID_LOCO_GET_STAND_HEIGHT` | Get standing height | Active |
| 7006 | `ROBOT_API_ID_LOCO_GET_PHASE` | Get phase | **Deprecated** |

#### Set Operations (7101-7111)

| API ID | Constant Name | Description | Status |
|--------|---------------|-------------|--------|
| 7101 | `ROBOT_API_ID_LOCO_SET_FSM_ID` | Set FSM state ID | Active |
| 7102 | `ROBOT_API_ID_LOCO_SET_BALANCE_MODE` | Set balance mode | Active |
| 7103 | `ROBOT_API_ID_LOCO_SET_SWING_HEIGHT` | Set swing height | Active |
| 7104 | `ROBOT_API_ID_LOCO_SET_STAND_HEIGHT` | Set standing height | Active |
| 7105 | `ROBOT_API_ID_LOCO_SET_VELOCITY` | Set velocity command | Active |
| 7106 | `ROBOT_API_ID_LOCO_SET_ARM_TASK` | Set arm task | Active |
| 7107 | `ROBOT_API_ID_LOCO_SET_SPEED_MODE` | Set speed mode | Active |
| 7110 | `ROBOT_API_ID_LOCO_SWITCH_TO_USER_CTRL` | Switch to user control | Active |
| 7111 | `ROBOT_API_ID_LOCO_SWITCH_TO_INTERNAL_CTRL` | Switch to internal control | Active |

#### FSM Modes

```cpp
enum class InternalFsmMode {
    LAST,      // Last/Previous mode
    PASSIVE,   // Passive mode
    WALKRUN    // Walk/Run mode
};
```

#### Data Structures

**Velocity Command:**
```cpp
class JsonizeVelocityCommand {
    std::vector<float> velocity;  // [vx, vy, vyaw]
    float duration;               // Duration in seconds
};
```

---

### G1 Arm Action API (Service: `"arm"`)

**Base API ID Range: 7100-7199**

| API ID | Constant Name | Description |
|--------|---------------|-------------|
| 7106 | `ROBOT_API_ID_ARM_ACTION_EXECUTE_ACTION` | Execute predefined action |
| 7107 | `ROBOT_API_ID_ARM_ACTION_GET_ACTION_LIST` | Get available action list |
| 7108 | `ROBOT_API_ID_ARM_ACTION_EXECUTE_CUSTOM_ACTION` | Execute custom action |
| 7113 | `ROBOT_API_ID_ARM_ACTION_STOP_CUSTOM_ACTION` | Stop custom action |

---

### G1 Audio/Voice API (Service: `"voice"`)

**Base API ID Range: 1000-1099**

| API ID | Constant Name | Description |
|--------|---------------|-------------|
| 1001 | `ROBOT_API_ID_AUDIO_TTS` | Text-to-Speech |
| 1002 | `ROBOT_API_ID_AUDIO_ASR` | Automatic Speech Recognition |
| 1003 | `ROBOT_API_ID_AUDIO_START_PLAY` | Start audio playback |
| 1004 | `ROBOT_API_ID_AUDIO_STOP_PLAY` | Stop audio playback |
| 1005 | `ROBOT_API_ID_AUDIO_GET_VOLUME` | Get volume level |
| 1006 | `ROBOT_API_ID_AUDIO_SET_VOLUME` | Set volume level |
| 1010 | `ROBOT_API_ID_AUDIO_SET_RGB_LED` | Set RGB LED indicator |

#### Audio Data Structures

**TTS Parameter:**
```cpp
class TtsMakerParameter {
    int32_t index;          // TTS index
    uint16_t speaker_id;    // Speaker ID
    std::string text;       // Text to synthesize
};
```

**Play Stream Parameter:**
```cpp
class PlayStreamParameter {
    std::string app_name;    // Application name
    std::string stream_id;   // Stream ID
};
```

**LED Control:**
```cpp
class LedControlParameter {
    uint8_t R, G, B;  // RGB values (0-255)
};
```

---

### G1 AGV API (Service: `"agv"`)

**Base API ID Range: 1000-1099**

| API ID | Constant Name | Description |
|--------|---------------|-------------|
| 1001 | `ROBOT_API_ID_AGV_MOVE` | Move AGV base |
| 1002 | `ROBOT_API_ID_AGV_HEIGHT_ADJUST` | Adjust AGV height |

#### AGV Data Structures

**Move Parameter:**
```cpp
class MoveParameter {
    float vx;    // X velocity (m/s)
    float vy;    // Y velocity (m/s)
    float vyaw;  // Yaw velocity (rad/s)
};
```

---

### G1 Joint Index Definitions

```cpp
enum JointIndex {
    // Left Leg (0-5)
    LeftHipPitch = 0,
    LeftHipRoll = 1,
    LeftHipYaw = 2,
    LeftKnee = 3,
    LeftAnklePitch = 4,
    LeftAnkleRoll = 5,

    // Right Leg (6-11)
    RightHipPitch = 6,
    RightHipRoll = 7,
    RightHipYaw = 8,
    RightKnee = 9,
    RightAnklePitch = 10,
    RightAnkleRoll = 11,

    // Waist (12-14)
    WaistYaw = 12,
    WaistRoll = 13,
    WaistPitch = 14,

    // Left Arm (15-21)
    LeftShoulderPitch = 15,
    LeftShoulderRoll = 16,
    LeftShoulderYaw = 17,
    LeftElbow = 18,
    LeftWristRoll = 19,
    LeftWristPitch = 20,
    LeftWristYaw = 21,

    // Right Arm (22-28)
    RightShoulderPitch = 22,
    RightShoulderRoll = 23,
    RightShoulderYaw = 24,
    RightElbow = 25,
    RightWristRoll = 26,
    RightWristPitch = 27,
    RightWristYaw = 28
};
```

**Arm Joints Array (17 joints total):**
- Left arm: 7 joints (ShoulderPitch, ShoulderRoll, ShoulderYaw, Elbow, WristRoll, WristPitch, WristYaw)
- Right arm: 7 joints (ShoulderPitch, ShoulderRoll, ShoulderYaw, Elbow, WristRoll, WristPitch, WristYaw)
- Waist: 3 joints (Yaw, Roll, Pitch)

---

## H1 Robot APIs

### Service Architecture

H1 robot uses the following services:
- **Loco Service** (`"loco"`) - Locomotion control

### API Version Information

| Service | Version |
|---------|---------|
| Locomotion | 2.0.0.0 |

---

### H1 Locomotion API (Service: `"loco"`)

**Base API ID Range: 8000-8299**

#### Get Operations (8001-8006)

| API ID | Constant Name | Description | Status |
|--------|---------------|-------------|--------|
| 8001 | `ROBOT_API_ID_LOCO_GET_FSM_ID` | Get current FSM state ID | Active |
| 8002 | `ROBOT_API_ID_LOCO_GET_FSM_MODE` | Get FSM mode | Active |
| 8003 | `ROBOT_API_ID_LOCO_GET_BALANCE_MODE` | Get balance mode | Active |
| 8004 | `ROBOT_API_ID_LOCO_GET_SWING_HEIGHT` | Get swing height | Active |
| 8005 | `ROBOT_API_ID_LOCO_GET_STAND_HEIGHT` | Get standing height | Active |
| 8006 | `ROBOT_API_ID_LOCO_GET_PHASE` | Get phase | **Deprecated** |

#### Set Operations (8101-8107)

| API ID | Constant Name | Description |
|--------|---------------|-------------|
| 8101 | `ROBOT_API_ID_LOCO_SET_FSM_ID` | Set FSM state ID |
| 8102 | `ROBOT_API_ID_LOCO_SET_BALANCE_MODE` | Set balance mode |
| 8103 | `ROBOT_API_ID_LOCO_SET_SWING_HEIGHT` | Set swing height |
| 8104 | `ROBOT_API_ID_LOCO_SET_STAND_HEIGHT` | Set standing height |
| 8105 | `ROBOT_API_ID_LOCO_SET_VELOCITY` | Set velocity command |
| 8106 | `ROBOT_API_ID_LOCO_SET_PHASE` | Set phase |
| 8107 | `ROBOT_API_ID_LOCO_SET_ARM_TASK` | Set arm task |

#### Odometry Operations (8201-8204)

| API ID | Constant Name | Description |
|--------|---------------|-------------|
| 8201 | `ROBOT_API_ID_LOCO_ENABLE_ODOM` | Enable odometry |
| 8202 | `ROBOT_API_ID_LOCO_DISABLE_ODOM` | Disable odometry |
| 8203 | `ROBOT_API_ID_LOCO_GET_ODOM` | Get odometry data |
| 8204 | `ROBOT_API_ID_LOCO_SET_TARGET_POSITION` | Set target position |

#### Data Structures

**Velocity Command:**
```cpp
class JsonizeVelocityCommand {
    std::vector<float> velocity;  // [vx, vy, vyaw]
    float duration;               // Duration in seconds
};
```

**Target Position:**
```cpp
class JsonizeTargetPos {
    float x, y, yaw;   // Target position and orientation
    bool relative;     // true for relative, false for absolute
};
```

**Data Vector (for generic data):**
```cpp
class JsonizeDataVecFloat {
    std::vector<float> data;
};
```

---

## API ID Summary by Robot

### G1 API ID Allocation

| Range | Service | Count |
|-------|---------|-------|
| 1000-1099 | Voice/Audio | 7 IDs |
| 1000-1099 | AGV | 2 IDs |
| 7000-7099 | Locomotion (Get) | 6 IDs |
| 7100-7199 | Locomotion (Set) | 8 IDs |
| 7100-7199 | Arm Action | 4 IDs |

**Total G1 APIs: 27 API IDs**

### H1 API ID Allocation

| Range | Service | Count |
|-------|---------|-------|
| 8000-8099 | Locomotion (Get) | 6 IDs |
| 8100-8199 | Locomotion (Set) | 7 IDs |
| 8200-8299 | Odometry | 4 IDs |

**Total H1 APIs: 17 API IDs**

---

## Key Differences Between G1 and H1

### API ID Ranges
- **G1** uses 7000-7199 for locomotion
- **H1** uses 8000-8299 for locomotion

### Service Names
- **G1**: `"sport"` for locomotion
- **H1**: `"loco"` for locomotion

### Additional Services
- **G1** includes: Arm, Voice/Audio, AGV services
- **H1** focuses on: Locomotion with odometry support

### API Versions
- **G1 Locomotion**: 1.0.0.0
- **H1 Locomotion**: 2.0.0.0 (newer version)

### Unique Features
- **G1**: User/Internal control switching (7110, 7111)
- **H1**: Odometry operations (8201-8204)

---

## Usage Notes

### Client Registration
All API clients use the `UT_ROBOT_CLIENT_REG_API_NO_PROI` macro to register APIs.

### API Call Pattern
```cpp
int32_t ret = Call(API_ID, parameter, data);
```

### Deprecated APIs
- `ROBOT_API_ID_LOCO_GET_PHASE` (both G1 and H1)

### Version Compatibility
Ensure your client version matches the API version declared in the respective `_API_VERSION` constant.

---

## File References

### G1 API Headers
- `third/unitree_sdk2/include/unitree/robot/g1/loco/g1_loco_api.hpp`
- `third/unitree_sdk2/include/unitree/robot/g1/arm/g1_arm_action_api.hpp`
- `third/unitree_sdk2/include/unitree/robot/g1/audio/g1_audio_api.hpp`
- `third/unitree_sdk2/include/unitree/robot/g1/agv/g1_agv_api.hpp`
- `third/unitree_sdk2/include/unitree/dds_wrapper/robots/g1/defines.h`

### H1 API Headers
- `third/unitree_sdk2/include/unitree/robot/h1/loco/h1_loco_api.hpp`

### Example Code
- `third/unitree_sdk2/example/g1/high_level/`
- `third/unitree_sdk2/example/h1/high_level/`

---

## Appendix: Complete API ID Listing

### G1 Complete API IDs
```
Locomotion (Sport Service):
- 7001: ROBOT_API_ID_LOCO_GET_FSM_ID
- 7002: ROBOT_API_ID_LOCO_GET_FSM_MODE
- 7003: ROBOT_API_ID_LOCO_GET_BALANCE_MODE
- 7004: ROBOT_API_ID_LOCO_GET_SWING_HEIGHT
- 7005: ROBOT_API_ID_LOCO_GET_STAND_HEIGHT
- 7006: ROBOT_API_ID_LOCO_GET_PHASE (deprecated)
- 7101: ROBOT_API_ID_LOCO_SET_FSM_ID
- 7102: ROBOT_API_ID_LOCO_SET_BALANCE_MODE
- 7103: ROBOT_API_ID_LOCO_SET_SWING_HEIGHT
- 7104: ROBOT_API_ID_LOCO_SET_STAND_HEIGHT
- 7105: ROBOT_API_ID_LOCO_SET_VELOCITY
- 7106: ROBOT_API_ID_LOCO_SET_ARM_TASK
- 7107: ROBOT_API_ID_LOCO_SET_SPEED_MODE
- 7110: ROBOT_API_ID_LOCO_SWITCH_TO_USER_CTRL
- 7111: ROBOT_API_ID_LOCO_SWITCH_TO_INTERNAL_CTRL

Arm Action (Arm Service):
- 7106: ROBOT_API_ID_ARM_ACTION_EXECUTE_ACTION
- 7107: ROBOT_API_ID_ARM_ACTION_GET_ACTION_LIST
- 7108: ROBOT_API_ID_ARM_ACTION_EXECUTE_CUSTOM_ACTION
- 7113: ROBOT_API_ID_ARM_ACTION_STOP_CUSTOM_ACTION

Audio/Voice (Voice Service):
- 1001: ROBOT_API_ID_AUDIO_TTS
- 1002: ROBOT_API_ID_AUDIO_ASR
- 1003: ROBOT_API_ID_AUDIO_START_PLAY
- 1004: ROBOT_API_ID_AUDIO_STOP_PLAY
- 1005: ROBOT_API_ID_AUDIO_GET_VOLUME
- 1006: ROBOT_API_ID_AUDIO_SET_VOLUME
- 1010: ROBOT_API_ID_AUDIO_SET_RGB_LED

AGV (AGV Service):
- 1001: ROBOT_API_ID_AGV_MOVE
- 1002: ROBOT_API_ID_AGV_HEIGHT_ADJUST
```

### H1 Complete API IDs
```
Locomotion (Loco Service):
- 8001: ROBOT_API_ID_LOCO_GET_FSM_ID
- 8002: ROBOT_API_ID_LOCO_GET_FSM_MODE
- 8003: ROBOT_API_ID_LOCO_GET_BALANCE_MODE
- 8004: ROBOT_API_ID_LOCO_GET_SWING_HEIGHT
- 8005: ROBOT_API_ID_LOCO_GET_STAND_HEIGHT
- 8006: ROBOT_API_ID_LOCO_GET_PHASE (deprecated)
- 8101: ROBOT_API_ID_LOCO_SET_FSM_ID
- 8102: ROBOT_API_ID_LOCO_SET_BALANCE_MODE
- 8103: ROBOT_API_ID_LOCO_SET_SWING_HEIGHT
- 8104: ROBOT_API_ID_LOCO_SET_STAND_HEIGHT
- 8105: ROBOT_API_ID_LOCO_SET_VELOCITY
- 8106: ROBOT_API_ID_LOCO_SET_PHASE
- 8107: ROBOT_API_ID_LOCO_SET_ARM_TASK
- 8201: ROBOT_API_ID_LOCO_ENABLE_ODOM
- 8202: ROBOT_API_ID_LOCO_DISABLE_ODOM
- 8203: ROBOT_API_ID_LOCO_GET_ODOM
- 8204: ROBOT_API_ID_LOCO_SET_TARGET_POSITION
```

---

*Document Version: 1.0*
*Last Updated: 2025-07-04*
*SDK Version: Based on unitree_sdk2*
