# voice_bridge

ROS2 Python node that bridges ASR text and Pi Agent decisions into project-internal voice command topics.

P0 safety boundary: this node publishes motion intent only to `/voice/cmd/*`. It does not publish `/api/*`, `/lowcmd`, `/arm_sdk`, `/dex3/*/cmd`, or `/g1/safe_cmd/*`.

## Unit Tests

```bash
PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 PYTHONPATH=src/voice_bridge .venv/bin/python -m pytest src/voice_bridge/tests -q
```

## Build

```bash
source /opt/ros/humble/setup.bash
colcon build --symlink-install --packages-select voice_bridge
source install/setup.bash
```

## Launch

```bash
ros2 launch voice_bridge voice_bridge.launch.py \
  config_path:=src/voice_bridge/config/voice_bridge.yaml
```

## Loopback Check

```bash
ros2 topic echo /voice/cmd/loco
ros2 topic echo /voice/cmd/action
ros2 topic echo /g1/cmd/audio/tts

ros2 topic pub /g1/audio/asr std_msgs/msg/String \
  '{data: "{\"text\":\"宇树，向前走一秒\",\"confidence\":0.9,\"is_final\":true}"}' --once

ros2 topic pub /g1/audio/asr std_msgs/msg/String \
  '{data: "停止"}' --once
```
