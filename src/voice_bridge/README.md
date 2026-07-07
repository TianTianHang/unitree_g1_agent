# voice_bridge

ROS2 Python node that bridges ASR text and Pi Agent decisions into project-internal voice command topics.

P0 safety boundary: this node publishes motion intent only to `/voice/cmd/*`. It does not publish `/api/*`, `/lowcmd`, `/arm_sdk`, `/dex3/*/cmd`, or `/g1/safe_cmd/*`.

## Unit Tests

```bash
PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 PYTHONPATH=src/voice_bridge .venv/bin/python -m pytest src/voice_bridge/tests -q
```

## Pi RPC Agent Backend

Set `agent.backend: pi_rpc` to run Pi Agent as a JSONL RPC subprocess. The default workspace is `.agent-runtime/.unitree_agent`; `.agent-runtime` is runtime/cache space only. The project-owned robot tools extension lives at `src/voice_bridge/pi_extensions/robot-tools.ts` and is loaded through `agent.pi.extensions`.

Pi is not sandboxed by `voice_bridge`. It may use Pi built-in tools such as bash/read/write under the current user. The ROS motion safety boundary remains in Python: only confirmed `robot_*` tool calls are mapped to `AgentCommand`s, and `voice_bridge` validates/clamps motion, action, LED, and TTS payloads before publishing.

Run unit tests:

```bash
PYTHONPATH=src/voice_bridge pytest src/voice_bridge/tests -q
```

Run real Pi smoke tests:

```bash
PI_AGENT_INTEGRATION=1 PYTHONPATH=src/voice_bridge pytest src/voice_bridge/tests/test_pi_integration.py -q
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
