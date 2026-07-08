# G1 Native Topic Simulator Design

## Goal

`g1_sim` simulates the Unitree G1 hardware/firmware ROS2 surface documented in this repository and confirmed against `.unitree/unitree_ros2` plus `.unitree/unitree_sdk2`. It is meant to stand in for the robot side while developing interface nodes.

This package does not implement an application closed loop. Project-internal topics such as `/voice/*`, `/g1/safe_cmd/*`, and `/g1/audio/*` remain outside `g1_sim`.


## ROS2 Versus SDK2 Names

The SDK2 examples use DDS channel names with an `rt/` prefix. ROS2 normal topics are mapped by the RMW layer to DDS names with the same `rt/` prefix. Therefore a ROS2 node should not create a topic named `rt/lowstate`; it should create `lowstate`, which maps onto the DDS topic `rt/lowstate`.

This is why `g1_sim` config keeps ROS2 names such as `lowstate`, `/lowcmd`, `/arm_sdk`, `/user_lowcmd`, `/lf/dex3/left/state`, and `/audio_msg`.

Request/response APIs follow the same mapping. SDK2 constructs API DDS channels with `rt/api/` plus the service name and `/request` or `/response`; ROS2 uses the corresponding `/api/<service>/request` and `/api/<service>/response` topics.

## Native Topic Surface

| Capability | Topic | Simulator Role |
| --- | --- | --- |
| High-rate low state | `lowstate` | publish `unitree_hg/msg/LowState` |
| Low-rate low state | `lf/lowstate` | publish `unitree_hg/msg/LowState` |
| Torso IMU | `secondary_imu` | publish `unitree_hg/msg/IMUState` |
| Low-level command | `/lowcmd`, `lowcmd` | subscribe `unitree_hg/msg/LowCmd` |
| Arm SDK command | `/arm_sdk` | subscribe `unitree_hg/msg/LowCmd` |
| Dex3 command | `/dex3/left/cmd`, `/dex3/right/cmd` | subscribe `unitree_hg/msg/HandCmd` |
| Dex3 state | `/lf/dex3/left/state`, `/lf/dex3/right/state` | publish `unitree_hg/msg/HandState` |
| SDK2 user low command | `/user_lowcmd` | subscribe `unitree_hg/msg/LowCmd`; maps to DDS `rt/user_lowcmd` |
| Legacy Dex3 state alias | `/dex3/left/state`, `/dex3/right/state` | publish `unitree_hg/msg/HandState`; maps to DDS `rt/dex3/*/state` |
| SDK2 ASR text | `/audio_msg` | publish `std_msgs/msg/String`; maps to DDS `rt/audio_msg` |
| Sport API | `/api/sport/request`, `/api/sport/response` | subscribe request, publish response; maps to DDS `rt/api/sport/*` |
| Arm API | `/api/arm/request`, `/api/arm/response` | subscribe request, publish response; maps to DDS `rt/api/arm/*` |
| Voice API | `/api/voice/request`, `/api/voice/response` | subscribe request, publish response; maps to DDS `rt/api/voice/*` |
| AGV API | `/api/agv/request`, `/api/agv/response` | subscribe request, publish response; maps to DDS `rt/api/agv/*` |
| Motion switcher API | `/api/motion_switcher/request`, `/api/motion_switcher/response` | subscribe request, publish response; maps to DDS `rt/api/motion_switcher/*` |

## Simulated API Behavior

- Sport API ID `7105` updates an internal velocity command and pose estimate.
- Sport get APIs return official `{"data": ...}` response payloads, matching the G1 ROS2/SDK2 clients.
- Voice TTS accepts text and echoes a response payload.
- Voice ASR returns a configurable text payload through `/api/voice/response` and publishes the same text on ROS2 `/audio_msg`, which maps to SDK2 DDS `rt/audio_msg`. `g1_interface` bridges ASR-shaped `/audio_msg` events into the project-internal `/g1/audio/asr` topic consumed by `voice_bridge`; non-ASR audio events such as play-state JSON are bridged to `/g1/audio/event` for downstream consumers.
- Voice volume and RGB LED APIs update mock state.
- AGV move and height-adjust APIs are modeled from `docs/G1_H1_API_Documentation.md`; confirm whether `/api/agv/*` is exposed on the target firmware.
- Arm and motion-switcher APIs return accepted mock responses.

## Official Documentation To Confirm

- Whether the deployed firmware's non-ROS SDK2 DDS endpoints appear in the ROS graph; even when they do not show in `ros2 topic list`, matching ROS2 subscriptions should interoperate at the DDS topic/type level.
- Exact `/api/voice` ASR runtime behavior: SDK2 confirms DDS `rt/audio_msg` (ROS2 `/audio_msg`); ROS2 source confirms `/api/voice/*`, but does not include a ROS2 ASR event example.
- G1 DoF profile and Dex3 availability for the actual hardware.

## Source Evidence

- `.unitree/unitree_ros2/cyclonedds_ws/src/unitree/unitree_api/msg/Request.msg`: `header`, `parameter`, `binary`.
- `.unitree/unitree_ros2/cyclonedds_ws/src/unitree/unitree_api/msg/Response.msg`: `header`, `data`, `binary`.
- `.unitree/unitree_ros2/cyclonedds_ws/src/unitree/unitree_hg/msg/LowState.msg`: `imu_state`, `motor_state[35]`, `mode_machine`, `crc`.
- `.unitree/unitree_ros2/cyclonedds_ws/src/unitree/unitree_hg/msg/MotorState.msg`: `temperature` is `int16[2]`.
- `.unitree/unitree_ros2/example/src/src/g1/lowlevel/g1_low_level_example.cpp`: ROS2 `lowstate`/`lf/lowstate` and `/lowcmd`.
- `.unitree/unitree_ros2/example/src/src/g1/lowlevel/g1_ankle_swing_example.cpp`: ROS2 `lowcmd`, `lowstate`, `secondary_imu`.
- `.unitree/unitree_ros2/example/src/src/g1/dex3/g1_dex3_example.cpp`: ROS2 `/dex3/*/cmd` and `/lf/dex3/*/state`.
- `.unitree/unitree_ros2/example/src/include/g1/g1_loco_client.hpp`: `/api/sport/*` and G1 loco API IDs.
- `.unitree/unitree_ros2/example/src/include/g1/g1_audio_client.hpp`: `/api/voice/*` and audio API IDs.
- `.unitree/unitree_ros2/example/src/include/g1/g1_arm_action_client.hpp`: `/api/arm/*` and arm action IDs.
- `.unitree/unitree_ros2/example/src/include/g1/g1_motion_switch_client.hpp`: `/api/motion_switcher/*`.
- `.unitree/unitree_sdk2/include/unitree/robot/channel/channel_namer.hpp`: SDK2 API channel prefix `rt/api/` plus `/request` and `/response` suffixes.
- `.unitree/unitree_sdk2/include/unitree/dds_wrapper/robots/g1/g1_pub.h`: SDK2 defaults `rt/lowstate`, `rt/lowcmd`, `rt/arm_sdk`.
- `.unitree/unitree_sdk2/include/unitree/dds_wrapper/robots/g1/g1_sub.h`: SDK2 defaults `rt/lowcmd`, `rt/arm_sdk`, `rt/lowstate`, `rt/dex3/*/state`.
- `.unitree/unitree_sdk2/example/g1/audio/g1_audio_client_example.cpp`: SDK2 ASR text topic `rt/audio_msg`.
