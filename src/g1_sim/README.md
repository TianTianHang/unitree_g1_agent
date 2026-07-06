# g1_sim

ROS2 simulator for Unitree G1 native hardware topics.

The node stays at the Unitree-native boundary. It does not publish project-internal topics such as `/voice/*`, `/g1/safe_cmd/*`, or `/g1/audio/*`.

## Simulated Native Topics

Published by the simulator:

- `lowstate`
- `lf/lowstate`
- `secondary_imu`
- `/lf/dex3/left/state`
- `/lf/dex3/right/state`
- `/dex3/left/state`
- `/dex3/right/state`
- `/audio_msg`
- `/api/sport/response`
- `/api/arm/response`
- `/api/voice/response`
- `/api/agv/response`
- `/api/motion_switcher/response`

Subscribed by the simulator:

- `/lowcmd`
- `lowcmd`
- `/arm_sdk`
- `/user_lowcmd`
- `/dex3/left/cmd`
- `/dex3/right/cmd`
- `~/asr_input`
- `/api/sport/request`
- `/api/arm/request`
- `/api/voice/request`
- `/api/agv/request`
- `/api/motion_switcher/request`


## ROS2 And SDK2 Topic Names

SDK2 examples show DDS channel names such as `rt/lowstate`. In ROS2, `rt/` is the RMW DDS prefix for normal ROS topics. A ROS2 publisher/subscriber should use `lowstate`, not `rt/lowstate`; on the DDS wire that becomes `rt/lowstate` and can interoperate with SDK2 when the message type matches.

The same rule applies to request/response APIs. SDK2 builds API channels under `rt/api/`, while ROS2 code uses `/api/...`.

Examples:

- SDK2 `rt/lowstate` <-> ROS2 `lowstate`
- SDK2 `rt/lowcmd` <-> ROS2 `/lowcmd` or `lowcmd`
- SDK2 `rt/arm_sdk` <-> ROS2 `/arm_sdk`
- SDK2 `rt/user_lowcmd` <-> ROS2 `/user_lowcmd`
- SDK2 `rt/dex3/left/cmd` <-> ROS2 `/dex3/left/cmd`
- SDK2 `rt/lf/dex3/left/state` <-> ROS2 `/lf/dex3/left/state`
- SDK2 `rt/dex3/left/state` <-> ROS2 `/dex3/left/state` compatibility alias
- SDK2 `rt/audio_msg` <-> ROS2 `/audio_msg`
- SDK2 `rt/api/sport/request` <-> ROS2 `/api/sport/request`
- SDK2 `rt/api/voice/response` <-> ROS2 `/api/voice/response`

## API Coverage

- Sport: all G1 loco IDs in `g1_loco_api.hpp`, including `get_*`, `set_*`, `set_velocity`, `switch_to_user_ctrl`, and `switch_to_internal_ctrl`.
- Arm: action execution and action-list responses.
- Voice: TTS, ASR response payload, `/audio_msg` ASR JSON, play_state JSON, play/stop, volume, RGB LED.
- AGV: move and height-adjust responses from the G1 high-level API documentation.
- Motion switcher: mode check/select/release and silent flag.

## Evidence

- ROS2 G1 low-level examples use `lowstate`, `lf/lowstate`, `secondary_imu`, `lowcmd`, and `/lowcmd`.
- ROS2 G1 Dex3 example uses `/dex3/*/cmd` and `/lf/dex3/*/state`.
- ROS2 G1 clients use `/api/sport/*`, `/api/arm/*`, `/api/voice/*`, and `/api/motion_switcher/*`.
- SDK2 client channels are built with prefix `rt/api/`, service names such as `sport`, `voice`, `arm`, and suffixes `/request` and `/response`.
- SDK2 G1 DDS wrappers and examples use DDS wire names like `rt/lowstate`, `rt/lowcmd`, `rt/arm_sdk`, `rt/user_lowcmd`, `rt/dex3/*`, and `rt/audio_msg`; ROS2 uses the corresponding topic names without the `rt/` DDS prefix.
- Official `unitree_hg/msg/LowState.msg` puts IMU data under `imu_state`; official `MotorState.msg` defines `temperature` as `int16[2]`.

## Unit Tests

```bash
PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 PYTHONPATH=src/g1_sim .venv/bin/python -m pytest src/g1_sim/tests -q
```

## Build

```bash
source /opt/ros/humble/setup.bash
source <unitree_ros2_install>/setup.bash
colcon build --symlink-install --packages-select g1_sim
source install/setup.bash
```

## Launch

```bash
ros2 launch g1_sim g1_sim.launch.py \
  config_path:=src/g1_sim/config/g1_sim.yaml
```

## Smoke Checks

```bash
ros2 topic echo /lowstate
ros2 topic echo /secondary_imu
ros2 topic echo /api/sport/response
ros2 topic echo /audio_msg
```

Example sport request:

```bash
ros2 topic pub /api/sport/request unitree_api/msg/Request '{...}' --once
```

Example ASR input:

```bash
ros2 topic pub /g1_sim_node/asr_input std_msgs/msg/String "data: '你好世界'" --once
```

The simulator publishes ASR messages on `/audio_msg` as JSON:

```json
{
  "index": 1,
  "timestamp": 12345678900000000,
  "text": "你好世界",
  "angle": 90,
  "speaker_id": 0,
  "sense": "unknown",
  "confidence": 0.95,
  "language": "zh-CN",
  "is_final": true
}
```

Successful voice `start_play` and `stop_play` API calls also publish playback state on `/audio_msg`:

```json
{"play_state": 1}
```

`{"play_state": 0}` is published only when a stop request actually stops an active stream.
