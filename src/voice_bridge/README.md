# voice_bridge

ROS2 Python node that bridges ASR text and Pi Agent decisions into project-internal voice command topics.

P0 safety boundary: this node publishes motion intent only to `/voice/cmd/*`. It does not publish `/api/*`, `/lowcmd`, `/arm_sdk`, `/dex3/*/cmd`, or `/g1/safe_cmd/*`.

## Pi RPC Agent Backend

Set `agent.backend: pi_rpc` to run Pi Agent as a JSONL RPC subprocess. The default workspace is `.agent-runtime/.unitree_agent`; `.agent-runtime` is runtime/cache space only. The project-owned robot tools extension lives at `src/voice_bridge/pi_extensions/robot-tools.ts` and is loaded through `agent.pi.extensions`.

Pi is not sandboxed by `voice_bridge`. It may use Pi built-in tools such as bash/read/write under the current user. The ROS motion safety boundary remains in Python: only confirmed `robot_*` tool calls are mapped to `AgentCommand`s, and `voice_bridge` validates/clamps motion, action, LED, and TTS payloads before publishing.

Use the workspace-level Python 3.10 uv environment and test entry points:

```bash
make bootstrap
make build
make test
make test-integration
```

Real Pi RPC smoke tests are opt-in and are not run by normal CI because they
execute the locally installed Pi process.

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

ros2 topic pub --once /g1/audio/asr g1_agent_msgs/msg/VoiceEvent \
  "{source: debug_cli, event_type: asr, text: '宇树，向前走一秒', has_confidence: true, confidence: 0.9, is_final: true, language: zh}"

ros2 topic pub --once /g1/audio/asr g1_agent_msgs/msg/VoiceEvent \
  "{source: debug_cli, event_type: asr, text: '停止', is_final: true, language: zh}"
```
